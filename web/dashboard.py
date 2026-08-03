"""
Dashboard web de SentriX — tableau de bord en temps réel (serveurs, membres, latence,
commandes...), inspiré des pages "Observe" de Railway. Tourne dans le même processus que
le bot via aiohttp (déjà une dépendance du projet), donc pas de service séparé à héberger :
sur Railway, il suffit de générer un domaine public (Paramètres → Networking → Generate
Domain) pointant sur le port du bot pour y accéder.

Protection : si DASHBOARD_TOKEN est défini dans .env, la page et l'API exigent
`?token=...` (ou l'en-tête X-Dashboard-Token). Sans jeton défini, l'accès est libre —
recommandé uniquement si le domaine Railway n'est pas généré / reste privé.
"""

import time
import logging

from aiohttp import web

import config
from database.db import now

logger = logging.getLogger("bot")

START_TIME = time.time()


def _check_token(request: web.Request) -> bool:
    if not config.DASHBOARD_TOKEN:
        return True
    provided = request.query.get("token") or request.headers.get("X-Dashboard-Token")
    return provided == config.DASHBOARD_TOKEN


async def handle_index(request: web.Request):
    if not _check_token(request):
        return web.Response(text=LOCKED_HTML, content_type="text/html", status=401)
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def handle_stats(request: web.Request):
    if not _check_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    bot = request.app["bot"]
    db = bot.db

    guilds = bot.guilds
    guild_count = len(guilds)
    member_total = sum(g.member_count or 0 for g in guilds)
    latency_ms = round(bot.latency * 1000) if bot.latency == bot.latency else 0  # NaN-safe
    uptime_seconds = int(time.time() - START_TIME)

    since_24h = now() - 86400
    commands_24h = await db.commands_count_since(since_24h)
    commands_total = await db.commands_count_total()
    top_rows = await db.top_commands_since(since_24h, limit=5)
    top_commands = [{"name": r["command_name"], "count": r["c"]} for r in top_rows]

    hourly_rows = await db.commands_hourly_since(since_24h)
    hourly_map = {r["bucket"]: r["c"] for r in hourly_rows}
    current_hour_bucket = (int(time.time()) // 3600) * 3600
    hourly = []
    for i in range(23, -1, -1):
        bucket = current_hour_bucket - i * 3600
        hourly.append(hourly_map.get(bucket, 0))

    top_guilds = sorted(guilds, key=lambda g: g.member_count or 0, reverse=True)[:5]

    return web.json_response({
        "bot_name": bot.user.name if bot.user else "SentriX",
        "avatar_url": str(bot.user.display_avatar.url) if bot.user else None,
        "guilds": guild_count,
        "members": member_total,
        "latency_ms": latency_ms,
        "uptime_seconds": uptime_seconds,
        "commands_24h": commands_24h,
        "commands_total": commands_total,
        "top_commands": top_commands,
        "hourly": hourly,
        "top_guilds": [{"name": g.name, "members": g.member_count or 0} for g in top_guilds],
        "generated_at": now(),
    })


def build_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_stats)
    return app


async def start_dashboard(bot):
    """À appeler une fois depuis setup_hook (main.py). Démarre le serveur web en tâche de
    fond, sans jamais bloquer ni faire planter le bot si le port est indisponible."""
    try:
        app = build_app(bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", config.DASHBOARD_PORT)
        await site.start()
        logger.info(f"Dashboard web démarré sur le port {config.DASHBOARD_PORT}.")
        if not config.DASHBOARD_TOKEN:
            logger.warning(
                "DASHBOARD_TOKEN n'est pas défini : le dashboard web est accessible sans "
                "protection à quiconque connaît l'URL. Définissez DASHBOARD_TOKEN dans .env "
                "si le domaine Railway est public."
            )
    except Exception:
        logger.error("Échec du démarrage du dashboard web (le bot continue de fonctionner normalement).")


LOCKED_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>SentriX — Accès refusé</title>
<style>
body{background:#100e18;color:#e6e2f2;font-family:-apple-system,Segoe UI,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
.card{border:1px solid #2a2540;border-radius:14px;padding:40px 50px;background:#15121f}
h1{margin:0 0 10px;font-size:22px} p{color:#8b86a3;margin:0}
code{background:#211d33;padding:2px 8px;border-radius:6px;color:#b794f6}
</style></head><body>
<div class="card"><h1>🔒 Accès protégé</h1><p>Ajoutez <code>?token=...</code> à l'URL avec le bon jeton (DASHBOARD_TOKEN).</p></div>
</body></html>"""


INDEX_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SentriX — Tableau de bord</title>
<style>
  :root{
    --bg:#0d0b14; --panel:#15121f; --border:#241f36; --border-soft:#1d1930;
    --text:#eae7f5; --muted:#8b86a3; --accent:#8b5cf6; --accent2:#a855f7;
    --green:#34d399; --red:#f87171; --yellow:#fbbf24;
  }
  *{box-sizing:border-box}
  body{
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    min-height:100vh;
  }
  header{
    display:flex; align-items:center; justify-content:space-between;
    padding:18px 28px; border-bottom:1px solid var(--border-soft);
  }
  .brand{display:flex; align-items:center; gap:12px}
  .brand img{width:34px; height:34px; border-radius:9px; background:var(--panel)}
  .brand .fallback{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--accent2));
    display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px}
  .brand h1{font-size:16px; margin:0; font-weight:600}
  .brand span{font-size:12px; color:var(--muted)}
  .pill{
    display:flex; align-items:center; gap:8px; border:1px solid var(--border);
    border-radius:9px; padding:8px 14px; font-size:13px; color:var(--muted);
    background:var(--panel);
  }
  .dot{width:7px; height:7px; border-radius:50%; background:var(--green); box-shadow:0 0 8px var(--green)}
  main{max-width:1180px; margin:0 auto; padding:32px 24px 60px}
  .grid{display:grid; grid-template-columns:repeat(4, 1fr); gap:16px; margin-bottom:16px}
  @media (max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}}
  .card{
    border:1px solid var(--border); border-radius:14px; background:var(--panel);
    padding:18px 20px; min-height:118px; display:flex; flex-direction:column;
  }
  .card .label{font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:8px}
  .card .value{font-size:28px; font-weight:700; line-height:1.1}
  .card .sub{font-size:12.5px; color:var(--muted); margin-top:4px}
  .wide{grid-column: span 2}
  @media (max-width:900px){.wide{grid-column: span 2}}
  .panel-title{font-size:14px; font-weight:600; margin-bottom:14px; display:flex; align-items:center; gap:8px}
  .bars{display:flex; align-items:flex-end; gap:3px; height:70px; margin-top:8px}
  .bars .bar{flex:1; background:linear-gradient(180deg,var(--accent2),var(--accent)); border-radius:3px 3px 0 0; min-height:2px; opacity:.9}
  .list{display:flex; flex-direction:column; gap:10px; margin-top:4px}
  .row{display:flex; align-items:center; justify-content:space-between; font-size:13.5px}
  .row .rank{color:var(--muted); width:20px; display:inline-block}
  .row .count{color:var(--accent2); font-weight:600}
  .bottom-grid{display:grid; grid-template-columns:1fr 1fr; gap:16px}
  @media (max-width:900px){.bottom-grid{grid-template-columns:1fr}}
  .panel{border:1px solid var(--border); border-radius:14px; background:var(--panel); padding:20px}
  footer{text-align:center; color:var(--muted); font-size:12px; padding:20px}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div id="avatarWrap"><div class="fallback">S</div></div>
    <div>
      <h1 id="botName">SentriX</h1>
      <span>Tableau de bord en direct</span>
    </div>
  </div>
  <div class="pill"><span class="dot"></span><span id="refreshLabel">Actualisation toutes les 15s</span></div>
</header>

<main>
  <div class="grid">
    <div class="card">
      <div class="label">🌐 Serveurs</div>
      <div class="value" id="guildCount">—</div>
      <div class="sub" id="memberSub">— membres au total</div>
    </div>
    <div class="card">
      <div class="label">📡 Latence</div>
      <div class="value" id="latency">—</div>
      <div class="sub" id="uptime">Uptime —</div>
    </div>
    <div class="card">
      <div class="label">⚡ Commandes (24h)</div>
      <div class="value" id="cmd24h">—</div>
      <div class="sub" id="cmdTotal">— au total</div>
    </div>
    <div class="card">
      <div class="label">🏆 Commande la + utilisée</div>
      <div class="value" id="topCmdName" style="font-size:20px">—</div>
      <div class="sub" id="topCmdCount">—</div>
    </div>
  </div>

  <div class="bottom-grid">
    <div class="panel">
      <div class="panel-title">📈 Commandes exécutées — dernières 24h</div>
      <div class="bars" id="hourlyBars"></div>
    </div>
    <div class="panel">
      <div class="panel-title">🥇 Top commandes (24h)</div>
      <div class="list" id="topCommandsList"><div class="row"><span class="rank">—</span></div></div>
    </div>
  </div>

  <div class="bottom-grid" style="margin-top:16px">
    <div class="panel" style="grid-column: 1 / -1">
      <div class="panel-title">🌍 Plus gros serveurs</div>
      <div class="list" id="topGuildsList"></div>
    </div>
  </div>
</main>

<footer>SentriX — dashboard généré côté bot • données rafraîchies automatiquement</footer>

<script>
const params = new URLSearchParams(window.location.search);
const token = params.get("token");

function fmtDuration(sec){
  const d = Math.floor(sec/86400), h = Math.floor((sec%86400)/3600), m = Math.floor((sec%3600)/60);
  if(d > 0) return `${d}j ${h}h`;
  if(h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

async function refresh(){
  try{
    const url = token ? `/api/stats?token=${encodeURIComponent(token)}` : "/api/stats";
    const res = await fetch(url);
    if(!res.ok){ document.getElementById("refreshLabel").textContent = "Accès refusé"; return; }
    const data = await res.json();

    document.getElementById("botName").textContent = data.bot_name || "SentriX";
    if(data.avatar_url){
      document.getElementById("avatarWrap").innerHTML = `<img src="${data.avatar_url}">`;
    }
    document.getElementById("guildCount").textContent = data.guilds.toLocaleString("fr-FR");
    document.getElementById("memberSub").textContent = `${data.members.toLocaleString("fr-FR")} membres au total`;
    document.getElementById("latency").textContent = `${data.latency_ms} ms`;
    document.getElementById("uptime").textContent = `Uptime ${fmtDuration(data.uptime_seconds)}`;
    document.getElementById("cmd24h").textContent = data.commands_24h.toLocaleString("fr-FR");
    document.getElementById("cmdTotal").textContent = `${data.commands_total.toLocaleString("fr-FR")} au total`;

    if(data.top_commands.length){
      document.getElementById("topCmdName").textContent = data.top_commands[0].name;
      document.getElementById("topCmdCount").textContent = `${data.top_commands[0].count} utilisations`;
    } else {
      document.getElementById("topCmdName").textContent = "Aucune";
      document.getElementById("topCmdCount").textContent = "—";
    }

    const max = Math.max(1, ...data.hourly);
    document.getElementById("hourlyBars").innerHTML = data.hourly.map(v =>
      `<div class="bar" style="height:${Math.max(2, Math.round((v/max)*100))}%" title="${v}"></div>`
    ).join("");

    const list = data.top_commands.length ? data.top_commands.map((c,i) =>
      `<div class="row"><span><span class="rank">${i+1}.</span>${c.name}</span><span class="count">${c.count}</span></div>`
    ).join("") : `<div class="row"><span class="rank">—</span><span style="color:var(--muted)">Aucune commande enregistrée sur 24h</span></div>`;
    document.getElementById("topCommandsList").innerHTML = list;

    const guildList = data.top_guilds.length ? data.top_guilds.map((g,i) =>
      `<div class="row"><span><span class="rank">${i+1}.</span>${g.name}</span><span class="count">${g.members.toLocaleString("fr-FR")}</span></div>`
    ).join("") : `<div class="row"><span style="color:var(--muted)">Aucun serveur</span></div>`;
    document.getElementById("topGuildsList").innerHTML = guildList;

    document.getElementById("refreshLabel").textContent = "Actualisation toutes les 15s";
  } catch(e){
    document.getElementById("refreshLabel").textContent = "Connexion perdue, nouvelle tentative...";
  }
}

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>"""
