"""Centre Database propriétaire du dashboard SentriX.

Cette page expose uniquement de la télémétrie sûre sur le backend réellement utilisé par
SentriX. Elle ne renvoie jamais d'URI, de mot de passe, de variable d'environnement ni de
ligne de données. Les actions sont non destructives et réservées au propriétaire du bot.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from aiohttp import web

from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.dashboard.database")
_INSTALLED = False
MONGODB_CLOUD_URL = "https://cloud.mongodb.com/"


def _owner_session(dashboard, request: web.Request) -> dict | None:
    session = dashboard._session(request)
    if not session:
        return None
    return session if is_bot_owner_id(session.get("user", {}).get("id")) else None


def _human_bytes(value: int | None) -> str | None:
    if value is None:
        return None
    size = float(max(0, value))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return None


def _safe_file_stats(db) -> dict:
    path_value = getattr(db, "path", None)
    if not path_value:
        return {"file_size_bytes": None, "storage_size_bytes": None, "modified_at": None}
    try:
        path = Path(str(path_value))
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.is_file():
                total += candidate.stat().st_size
        stat = path.stat() if path.is_file() else None
        return {
            "file_size_bytes": stat.st_size if stat else None,
            "storage_size_bytes": total or None,
            "modified_at": int(stat.st_mtime) if stat else None,
        }
    except (OSError, ValueError):
        return {"file_size_bytes": None, "storage_size_bytes": None, "modified_at": None}


async def _sqlite_snapshot(db) -> dict:
    started = time.perf_counter()
    row = await db.fetchone("SELECT 1 AS ok")
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    connected = bool(row and int(row["ok"]) == 1)

    tables = []
    journal_mode = None
    page_count = None
    page_size = None
    free_pages = None
    try:
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [str(item["name"]) for item in rows]
    except Exception:
        logger.exception("Impossible de lire l'inventaire SQLite du dashboard Database.")

    try:
        pragma = await db.fetchone("PRAGMA journal_mode")
        if pragma:
            journal_mode = str(pragma[0]).upper()
    except Exception:
        pass
    try:
        pragma = await db.fetchone("PRAGMA page_count")
        page_count = int(pragma[0]) if pragma else None
        pragma = await db.fetchone("PRAGMA page_size")
        page_size = int(pragma[0]) if pragma else None
        pragma = await db.fetchone("PRAGMA freelist_count")
        free_pages = int(pragma[0]) if pragma else None
    except Exception:
        pass

    logical_size = page_count * page_size if page_count is not None and page_size is not None else None
    free_bytes = free_pages * page_size if free_pages is not None and page_size is not None else None
    file_stats = _safe_file_stats(db)
    return {
        "backend": "SQLite",
        "connected": connected,
        "latency_ms": latency_ms,
        "journal_mode": journal_mode,
        "table_count": len(tables),
        "tables": tables,
        "logical_size_bytes": logical_size,
        "free_bytes": free_bytes,
        **file_stats,
    }


async def _database_snapshot(request: web.Request) -> dict:
    db = request.app["bot"].db
    connected = getattr(db, "_conn", None) is not None
    module_name = db.__class__.__module__.casefold()
    class_name = db.__class__.__name__.casefold()

    if "mongo" in module_name or "mongo" in class_name:
        # Filet futur : ne jamais lire l'URI. On indique seulement le type de backend.
        started = time.perf_counter()
        try:
            await db.fetchone("SELECT 1 AS ok")
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
        except Exception:
            latency_ms = None
        return {
            "backend": "MongoDB",
            "connected": connected,
            "latency_ms": latency_ms,
            "journal_mode": None,
            "table_count": None,
            "tables": [],
            "logical_size_bytes": None,
            "free_bytes": None,
            "file_size_bytes": None,
            "storage_size_bytes": None,
            "modified_at": None,
        }

    if hasattr(db, "path"):
        return await _sqlite_snapshot(db)

    return {
        "backend": db.__class__.__name__,
        "connected": connected,
        "latency_ms": None,
        "journal_mode": None,
        "table_count": None,
        "tables": [],
        "logical_size_bytes": None,
        "free_bytes": None,
        "file_size_bytes": None,
        "storage_size_bytes": None,
        "modified_at": None,
    }


def _public_snapshot(snapshot: dict) -> dict:
    return {
        "backend": snapshot.get("backend"),
        "connected": bool(snapshot.get("connected")),
        "latency_ms": snapshot.get("latency_ms"),
        "journal_mode": snapshot.get("journal_mode"),
        "table_count": snapshot.get("table_count"),
        "logical_size_bytes": snapshot.get("logical_size_bytes"),
        "logical_size": _human_bytes(snapshot.get("logical_size_bytes")),
        "storage_size_bytes": snapshot.get("storage_size_bytes"),
        "storage_size": _human_bytes(snapshot.get("storage_size_bytes")),
        "free_bytes": snapshot.get("free_bytes"),
        "free_space": _human_bytes(snapshot.get("free_bytes")),
        "modified_at": snapshot.get("modified_at"),
        "mongodb": {
            "active": snapshot.get("backend") == "MongoDB",
            "cloud_url": MONGODB_CLOUD_URL,
        },
    }


async def handle_database_page(request: web.Request) -> web.Response:
    dashboard = request.app["dashboard_module"]
    session = dashboard._session(request)
    if session is None:
        raise web.HTTPFound("/login")
    if not is_bot_owner_id(session.get("user", {}).get("id")):
        raise web.HTTPNotFound()
    return web.Response(
        text=DATABASE_HTML,
        content_type="text/html",
        headers={
            "Cache-Control": "private, no-store, no-cache, must-revalidate, max-age=0",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


async def api_database_status(dashboard, request: web.Request) -> web.Response:
    if _owner_session(dashboard, request) is None:
        raise web.HTTPNotFound()
    try:
        snapshot = await _database_snapshot(request)
    except Exception:
        logger.exception("Lecture du statut Database impossible.")
        return dashboard._json_error("La base ne répond pas pour le moment.", 503)
    return web.json_response({"ok": True, "database": _public_snapshot(snapshot)})


async def api_database_verify(dashboard, request: web.Request) -> web.Response:
    session = _owner_session(dashboard, request)
    if session is None:
        raise web.HTTPNotFound()
    csrf_error = dashboard._require_csrf(request, session)
    if csrf_error:
        return csrf_error
    try:
        started = time.perf_counter()
        row = await request.app["bot"].db.fetchone("SELECT 1 AS ok")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if not row or int(row["ok"]) != 1:
            raise RuntimeError("Réponse de vérification invalide")
    except Exception:
        logger.exception("Vérification manuelle Database échouée.")
        return dashboard._json_error("La vérification de connexion a échoué.", 503)
    return web.json_response({"ok": True, "connected": True, "latency_ms": latency_ms})


async def api_database_export(dashboard, request: web.Request) -> web.Response:
    if _owner_session(dashboard, request) is None:
        raise web.HTTPNotFound()
    try:
        snapshot = await _database_snapshot(request)
    except Exception:
        logger.exception("Export diagnostic Database impossible.")
        return dashboard._json_error("Impossible de générer le diagnostic.", 503)

    # Export volontairement DIAGNOSTIQUE : aucune ligne métier, aucun chemin local, aucune
    # URI et aucun secret. L'inventaire des tables aide au support sans exporter les données.
    payload = {
        "product": "SentriX",
        "kind": "database-diagnostic",
        "generated_at": int(time.time()),
        "database": _public_snapshot(snapshot),
        "schema": {"tables": snapshot.get("tables", [])},
        "security": {
            "contains_rows": False,
            "contains_credentials": False,
            "contains_connection_uri": False,
        },
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return web.Response(
        text=body,
        content_type="application/json",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="sentrix-database-diagnostic-{stamp}.json"',
            "X-Content-Type-Options": "nosniff",
        },
    )


DATABASE_LINK_JS = r"""
<script id="sentrix-database-link">
(() => {
  "use strict";
  if (window.__sentrixDatabaseLink) return;
  window.__sentrixDatabaseLink = true;
  async function install(){
    try {
      const probe = await fetch("/api/owner/database/status", {credentials:"same-origin", cache:"no-store"});
      if (!probe.ok) return;
      const host = document.querySelector(".side-bottom") || document.querySelector(".nav");
      if (!host || document.getElementById("sentrixDatabaseLink")) return;
      const link = document.createElement("a");
      link.id = "sentrixDatabaseLink";
      link.className = "btn ghost";
      link.href = "/database";
      link.textContent = "Database";
      host.appendChild(link);
    } catch (_) {}
  }
  setTimeout(install, 250);
})();
</script>
"""


def _inject_main(html: str) -> str:
    if 'id="sentrix-database-link"' in html:
        return html
    return html.replace("</body>", DATABASE_LINK_JS + "\n</body>", 1)


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    try:
        from . import admin_only_dashboard
        admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/database")
    except Exception:
        logger.exception("Impossible d'enregistrer /database comme page privée.")

    original_build_app = dashboard.build_app

    def bind(fn):
        async def handler(request: web.Request):
            return await fn(dashboard, request)
        return handler

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/database", handle_database_page)
        app.router.add_get("/api/owner/database/status", bind(api_database_status))
        app.router.add_post("/api/owner/database/verify", bind(api_database_verify))
        app.router.add_get("/api/owner/database/export", bind(api_database_export))
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject_main(dashboard.INDEX_HTML)
    logger.info("Database Center propriétaire ajouté au dashboard stable.")


DATABASE_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090b12"><meta name="robots" content="noindex,nofollow">
<title>SentriX — Database</title>
<style>
:root{color-scheme:dark;--bg:#080a11;--panel:#101522;--panel2:#151b2b;--line:#293149;--text:#f4f6ff;--muted:#98a2ba;--brand:#7467ff;--ok:#49d59c;--bad:#ff687f;--warn:#f1bc58}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 18% -8%,#372c7155,transparent 35%),var(--bg);color:var(--text);font:14px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}a{color:inherit;text-decoration:none}button{font:inherit}.top{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 4vw;border-bottom:1px solid var(--line);background:#080a11e8;backdrop-filter:blur(14px)}.brand{font-weight:900;font-size:18px}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:11px;padding:10px 14px;background:var(--panel2);color:var(--text);font-weight:800;cursor:pointer}.btn:hover{border-color:#596580}.btn.primary{background:linear-gradient(135deg,var(--brand),#5848dd);border-color:transparent}.btn:disabled{opacity:.5;cursor:not-allowed}main{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:34px 0 70px}.hero{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;margin-bottom:22px}.hero h1{font-size:34px;line-height:1.05;margin:0 0 10px}.hero p{margin:0;color:var(--muted);max-width:720px;line-height:1.65}.status{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:var(--panel)}.dot{width:9px;height:9px;border-radius:50%;background:var(--warn)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.metric,.card{border:1px solid var(--line);background:linear-gradient(180deg,#121827,#0e1320);border-radius:16px}.metric{padding:17px}.metric span{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;font-size:23px;margin-top:8px;word-break:break-word}.cards{display:grid;grid-template-columns:1.35fr .65fr;gap:14px}.card{padding:20px}.card h2{margin:0 0 7px;font-size:17px}.card p{margin:0;color:var(--muted);line-height:1.6}.rows{margin-top:17px;border-top:1px solid var(--line)}.row{display:flex;justify-content:space-between;gap:16px;padding:13px 0;border-bottom:1px solid var(--line)}.row span{color:var(--muted)}.row b{text-align:right}.safe{margin-top:16px;padding:14px;border:1px solid #2e5d50;background:#10251f;border-radius:12px;color:#baf3dd;line-height:1.55}.warn{margin-top:16px;padding:14px;border:1px solid #5b4b29;background:#241d0f;border-radius:12px;color:#f5d996;line-height:1.55}.toolbar{display:flex;gap:9px;flex-wrap:wrap;margin-top:17px}.message{min-height:21px;margin-top:12px;color:var(--muted)}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}@media(max-width:850px){.grid{grid-template-columns:repeat(2,1fr)}.cards{grid-template-columns:1fr}.hero{display:block}.hero .status{margin-top:14px}}@media(max-width:520px){.grid{grid-template-columns:1fr}.top{align-items:flex-start}.actions{justify-content:flex-end}.hero h1{font-size:29px}}
</style>
</head>
<body>
<header class="top"><div class="brand">SentriX Database</div><div class="actions"><a class="btn" href="/app">Dashboard</a><a class="btn" href="https://cloud.mongodb.com/" target="_blank" rel="noopener noreferrer">MongoDB Cloud</a></div></header>
<main>
<section class="hero"><div><h1>Centre Database</h1><p>État réel du stockage SentriX, latence, taille et vérification de connexion. Les identifiants, URI et secrets restent strictement côté serveur.</p></div><div class="status"><span class="dot" id="dot"></span><b id="statusText">Chargement</b></div></section>
<section class="grid"><div class="metric"><span>Backend actif</span><strong id="backend">—</strong></div><div class="metric"><span>Latence DB</span><strong id="latency">—</strong></div><div class="metric"><span>Stockage</span><strong id="storage">—</strong></div><div class="metric"><span>Tables</span><strong id="tables">—</strong></div></section>
<section class="cards"><article class="card"><h2>État du backend</h2><p>Lecture directe de la connexion utilisée par le bot en production.</p><div class="rows"><div class="row"><span>Connexion</span><b id="connected">—</b></div><div class="row"><span>Mode journal</span><b id="journal">—</b></div><div class="row"><span>Taille logique</span><b id="logical">—</b></div><div class="row"><span>Espace libre interne</span><b id="free">—</b></div><div class="row"><span>Dernière écriture fichier</span><b id="modified">—</b></div></div><div class="toolbar"><button class="btn primary" id="verify">Vérifier la connexion</button><a class="btn" href="/api/owner/database/export">Exporter le diagnostic JSON</a><button class="btn" id="refresh">Actualiser</button></div><div class="message" id="message"></div></article><aside class="card"><h2>MongoDB</h2><p id="mongoText">Vérification du backend actif.</p><div class="warn" id="mongoNote">Le dashboard n'active jamais un changement de backend automatiquement. Une migration de stockage doit être développée et testée séparément.</div><div class="safe">Aucune URI de connexion, aucun mot de passe, aucun token et aucune ligne de données ne sont envoyés au navigateur. L'export JSON contient uniquement un diagnostic et l'inventaire du schéma.</div></aside></section>
</main>
<script>
(() => {"use strict";let csrf="";const $=id=>document.getElementById(id);const fmtDate=v=>v?new Date(v*1000).toLocaleString("fr-FR"):"—";function render(d){$("backend").textContent=d.backend||"—";$("latency").textContent=d.latency_ms==null?"—":`${d.latency_ms} ms`;$("storage").textContent=d.storage_size||d.logical_size||"—";$("tables").textContent=d.table_count==null?"—":String(d.table_count);$("connected").textContent=d.connected?"Connectée":"Indisponible";$("journal").textContent=d.journal_mode||"—";$("logical").textContent=d.logical_size||"—";$("free").textContent=d.free_space||"—";$("modified").textContent=fmtDate(d.modified_at);$("dot").style.background=d.connected?"var(--ok)":"var(--bad)";$("statusText").textContent=d.connected?"Opérationnelle":"Indisponible";$("mongoText").textContent=d.mongodb&&d.mongodb.active?"MongoDB est le backend actif de cette instance.":`${d.backend||"Le backend actuel"} est le backend actif. MongoDB Cloud n'est pas utilisé par cette version.`;}async function load(){try{const r=await fetch("/api/owner/database/status",{credentials:"same-origin",cache:"no-store"});if(!r.ok)throw new Error("Statut indisponible");const p=await r.json();render(p.database);}catch(e){$("dot").style.background="var(--bad)";$("statusText").textContent="Erreur";$("message").textContent=e.message;}}async function init(){try{const r=await fetch("/api/me",{credentials:"same-origin",cache:"no-store"});if(r.ok){const me=await r.json();csrf=me.csrf||"";}}catch(_){}await load();}$("refresh").addEventListener("click",load);$("verify").addEventListener("click",async()=>{const b=$("verify");b.disabled=true;$("message").textContent="Vérification en cours…";try{const r=await fetch("/api/owner/database/verify",{method:"POST",credentials:"same-origin",headers:{"X-CSRF-Token":csrf}});const p=await r.json();if(!r.ok)throw new Error(p.error||"Vérification impossible");$("message").textContent=`Connexion validée en ${p.latency_ms} ms.`;await load();}catch(e){$("message").textContent=e.message;}finally{b.disabled=false;}});init();})();
</script>
</body></html>"""
