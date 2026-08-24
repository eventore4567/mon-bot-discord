from __future__ import annotations

import html
from aiohttp import web

_INSTALLED = False


def _clean(value, fallback="") -> str:
    text = str(value or fallback).strip()
    return " ".join(text.split())


def _prefix_commands(bot) -> list[dict]:
    rows = []
    seen = set()
    for command in list(getattr(bot, "commands", []) or []):
        if getattr(command, "hidden", False) or not getattr(command, "enabled", True):
            continue
        name = _clean(getattr(command, "qualified_name", None) or getattr(command, "name", "")).lower()
        if not name or name in seen:
            continue
        seen.add(name)
        description = _clean(
            getattr(command, "help", None)
            or getattr(command, "brief", None)
            or getattr(command, "description", None),
            "Commande SentriX.",
        )
        signature = _clean(getattr(command, "signature", ""))
        usage = f"+{name}" + (f" {signature}" if signature else "")
        cog = _clean(getattr(command, "cog_name", None), "Autres")
        rows.append({"kind": "prefix", "name": name, "usage": usage, "description": description, "category": cog})
    return sorted(rows, key=lambda item: item["name"])


def _slash_commands(bot) -> list[dict]:
    tree = getattr(bot, "tree", None)
    if tree is None:
        return []
    rows = []
    seen = set()
    try:
        commands = list(tree.get_commands())
    except Exception:
        commands = []
    for command in commands:
        name = _clean(getattr(command, "qualified_name", None) or getattr(command, "name", "")).lower()
        if not name or name in seen:
            continue
        seen.add(name)
        description = _clean(getattr(command, "description", None), "Commande SentriX.")
        rows.append({"kind": "slash", "name": name, "usage": f"/{name}", "description": description, "category": "Slash"})
    return sorted(rows, key=lambda item: item["name"])


def _command_card(item: dict) -> str:
    usage = html.escape(item["usage"])
    description = html.escape(item["description"])
    category = html.escape(item["category"])
    kind = html.escape(item["kind"])
    searchable = html.escape(f"{item['name']} {item['description']} {item['category']} {item['usage']}".lower(), quote=True)
    badge = "/ Slash" if item["kind"] == "slash" else "+ Préfixe"
    return (
        f'<article class="command" data-kind="{kind}" data-search="{searchable}">'
        f'<div class="command-top"><code>{usage}</code><span>{html.escape(badge)}</span></div>'
        f'<p>{description}</p><small>{category}</small></article>'
    )


def _page(bot, dashboard, request: web.Request) -> str:
    slash = _slash_commands(bot)
    prefix = _prefix_commands(bot)
    all_commands = slash + prefix
    cards = "".join(_command_card(item) for item in all_commands)
    base = str(dashboard._public_url(request)).rstrip("/")
    canonical = html.escape(base + "/commands", quote=True)
    return f'''<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Commandes SentriX — Slash / et préfixe +</title>
<meta name="description" content="Liste officielle des commandes SentriX : commandes slash / et commandes avec le préfixe +, avec recherche rapide.">
<meta name="robots" content="index,follow,max-snippet:-1"><link rel="canonical" href="{canonical}">
<meta property="og:type" content="website"><meta property="og:title" content="Commandes SentriX"><meta property="og:description" content="Toutes les commandes / et + de SentriX au même endroit."><meta property="og:url" content="{canonical}">
<meta name="twitter:card" content="summary">
<style>
:root{{--bg:#080a11;--panel:#111522;--panel2:#151a29;--line:#283047;--text:#f4f6ff;--muted:#a8b0c3;--brand:#7566ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:inherit;text-decoration:none}}header{{position:sticky;top:0;z-index:5;background:#080a11e8;backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}}.bar{{max-width:1120px;margin:auto;padding:15px 20px;display:flex;justify-content:space-between;align-items:center;gap:16px}}.brand{{display:flex;align-items:center;gap:10px;font-weight:900;font-size:20px}}.brand img{{width:36px;height:36px;border-radius:10px}}.back{{color:var(--muted)}}main{{max-width:1120px;margin:auto;padding:54px 20px 80px}}.eyebrow{{font-size:12px;font-weight:900;color:#aaa1ff;letter-spacing:.1em;text-transform:uppercase}}h1{{font-size:clamp(38px,6vw,64px);letter-spacing:-.045em;margin:8px 0 12px}}.lead{{max-width:760px;color:var(--muted);font-size:17px;line-height:1.6}}.stats{{display:flex;gap:10px;flex-wrap:wrap;margin:25px 0}}.stat{{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:10px 14px}}.toolbar{{display:grid;grid-template-columns:1fr auto;gap:12px;margin:28px 0 18px}}input{{width:100%;background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:12px;padding:13px 15px;font:inherit;outline:none}}input:focus{{border-color:#6f64c9}}.filters{{display:flex;gap:7px;flex-wrap:wrap}}button{{border:1px solid var(--line);background:var(--panel);color:var(--text);padding:11px 13px;border-radius:10px;font-weight:800;cursor:pointer}}button.active{{background:#2a235e;border-color:#5e54bd}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}}.command{{border:1px solid var(--line);background:linear-gradient(180deg,var(--panel2),#10131f);border-radius:14px;padding:16px;min-width:0}}.command-top{{display:flex;justify-content:space-between;gap:12px;align-items:center}}code{{font:700 15px ui-monospace,SFMono-Regular,Menlo,monospace;color:#e9e6ff;overflow-wrap:anywhere}}.command-top span{{font-size:11px;color:#bbb4ff;border:1px solid #403873;border-radius:999px;padding:4px 7px;white-space:nowrap}}.command p{{color:var(--muted);line-height:1.5;margin:11px 0}}.command small{{color:#777f93}}.empty{{display:none;text-align:center;border:1px dashed var(--line);border-radius:14px;padding:28px;color:var(--muted)}}@media(max-width:720px){{.toolbar{{grid-template-columns:1fr}}.grid{{grid-template-columns:1fr}}.command-top{{align-items:flex-start}}}}
</style></head><body>
<header><div class="bar"><a class="brand" href="/"><img src="/sentrix-avatar.png" alt="SentriX"><span>SentriX</span></a><a class="back" href="/">Retour au hub</a></div></header>
<main><div class="eyebrow">Documentation officielle</div><h1>Commandes SentriX</h1><p class="lead">Retrouvez les commandes slash <strong>/</strong> et les commandes classiques avec le préfixe <strong>+</strong>. Utilisez la recherche pour trouver une commande instantanément.</p>
<div class="stats"><div class="stat"><strong>{len(all_commands)}</strong> commandes affichées</div><div class="stat"><strong>{len(slash)}</strong> slash /</div><div class="stat"><strong>{len(prefix)}</strong> préfixe +</div></div>
<div class="toolbar"><input id="search" type="search" placeholder="Rechercher ban, ticket, niveau, IA..." autocomplete="off"><div class="filters"><button class="active" data-filter="all">Toutes</button><button data-filter="slash">Slash /</button><button data-filter="prefix">Préfixe +</button></div></div>
<section class="grid" id="grid">{cards}</section><div class="empty" id="empty">Aucune commande trouvée.</div></main>
<script>
(() => {{
 const search=document.getElementById('search'), cards=[...document.querySelectorAll('.command')], empty=document.getElementById('empty'); let filter='all';
 const render=()=>{{const q=search.value.trim().toLowerCase();let shown=0;cards.forEach(card=>{{const okKind=filter==='all'||card.dataset.kind===filter;const okSearch=!q||card.dataset.search.includes(q);const show=okKind&&okSearch;card.style.display=show?'':'none';if(show)shown++;}});empty.style.display=shown?'none':'block';}};
 search.addEventListener('input',render); document.querySelectorAll('[data-filter]').forEach(btn=>btn.addEventListener('click',()=>{{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('active'));btn.classList.add('active');filter=btn.dataset.filter;render();}}));
}})();
</script></body></html>'''


async def commands_page(request: web.Request) -> web.Response:
    dashboard = request.app.get("dashboard_module")
    bot = request.app.get("bot")
    if dashboard is None or bot is None:
        raise web.HTTPServiceUnavailable(text="SentriX démarre")
    return web.Response(
        text=_page(bot, dashboard, request),
        content_type="text/html",
        headers={"Cache-Control": "public, max-age=60", "X-Robots-Tag": "index, follow"},
    )


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get("/commands", commands_page)
        return app

    dashboard.build_app = build_app
