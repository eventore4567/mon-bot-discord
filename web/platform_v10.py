"""Intégration dashboard Bot V10 au-dessus de Platform V4."""
from __future__ import annotations

import logging
from aiohttp import web

logger = logging.getLogger("bot.web-v10")
_INSTALLED = False


async def _ctx(dashboard, request: web.Request, *, write: bool = False):
    from . import platform_v4
    session, guild, _platform, error = await platform_v4._admin_ctx(dashboard, request, write=write)
    if error:
        return None, None, None, error
    service = dashboard.BOT.get_cog("BotV10")
    if service is None:
        return session, guild, None, dashboard._json_error("Bot V10 se charge encore. Réessayez dans quelques secondes.", 503)
    return session, guild, service, None


async def api_summary(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request)
    if error:
        return error
    return web.json_response({
        "ok": True,
        "health": await service.health_data(guild),
        "audit": await service.server_audit_data(guild, persist=False),
        "economy": await service.economy_insights(guild.id),
        "privacy": await service.get_privacy_policy(guild.id),
        "signals": await service.recent_signals(guild.id, 8),
    })


async def api_privacy_policy_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "policy": await service.get_privacy_policy(guild.id)})


async def api_privacy_policy_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await request.json()
        days = int(data.get("retention_days"))
        policy = await service.set_privacy_policy(guild.id, int(session["user"]["id"]), days)
    except (TypeError, ValueError):
        return dashboard._json_error("Durée invalide. Choisissez entre 7 et 365 jours.", 400)
    return web.json_response({"ok": True, "policy": policy})


_V10_CSS = r'''
<style id="sentrix-platform-v10-style">
.v10-status{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;border:1px solid #30405f;background:linear-gradient(135deg,#10182a,#11141d);border-radius:14px;padding:13px 15px;margin-bottom:13px}
.v10-status strong{font-size:13px}.v10-status span{color:var(--muted);font-size:11px}.v10-score{font-size:22px;font-weight:900;white-space:nowrap}.v10-retention{margin-top:15px;padding-top:14px;border-top:1px solid var(--line)}
@media(max-width:650px){.v10-status{grid-template-columns:1fr}.v10-score{font-size:19px}.btn,.back,button,input,select,textarea{min-height:44px}input,select,textarea{font-size:16px}.side{scroll-snap-type:x proximity}.nav{scroll-snap-align:start}.scroll{overscroll-behavior-x:contain}.card,.item,.metric{overflow-wrap:anywhere}}
</style>
'''

_V10_BANNER = '''<div id="v10Status" class="v10-status"><div><strong>Bot V10 — diagnostic en cours</strong><br><span id="v10Detail">Chargement de la santé, de l’audit et de l’économie…</span></div><div id="v10Score" class="v10-score">—/100</div></div>'''

_V10_RETENTION = '''<div class="v10-retention"><h3>Conservation automatique V10</h3><p>Durée appliquée aux conversations IA et à la télémétrie non sensible. Les sanctions, avertissements, journaux d’audit et transactions économiques ne sont pas purgés automatiquement.</p><div class="row"><div class="field"><label>Conservation (7 à 365 jours)</label><input id="v10RetentionDays" type="number" min="7" max="365" value="90"></div><div style="display:flex;align-items:end"><button class="btn" id="v10SaveRetention">Enregistrer la durée</button></div></div></div>'''

_V10_JS = r'''
<script id="sentrix-platform-v10-js">
(()=>{"use strict";if(window.__sentrixPlatformV10)return;window.__sentrixPlatformV10=true;
async function v10Load(){if(!guildId)return;try{const d=await api(`/api/guilds/${guildId}/v10/summary`);const score=d.audit?.total_score??0;const status=d.health?.status||"inconnu";const signals=(d.signals||[]).filter(x=>x.severity==="high"||x.severity==="critical").length;const blocked=d.economy?.blocked_accounts??0;const missing=d.health?.missing_permissions?.length??0;const scoreEl=document.getElementById("v10Score");const detailEl=document.getElementById("v10Detail");const statusEl=document.getElementById("v10Status");if(scoreEl)scoreEl.textContent=`${score}/100`;if(detailEl)detailEl.textContent=`Santé: ${status} · ${signals} signal(s) prioritaire(s) · ${blocked} limitation(s) économie · ${missing} permission(s) manquante(s)`;if(statusEl)statusEl.style.borderColor=status==="healthy"?"#2d7457":"#725b30";const retention=document.getElementById("v10RetentionDays");if(retention&&document.activeElement!==retention)retention.value=d.privacy?.retention_days??90}catch(err){const detail=document.getElementById("v10Detail");if(detail)detail.textContent=`V10 indisponible: ${err.message}`}}
const save=document.getElementById("v10SaveRetention");if(save)save.addEventListener("click",async()=>{try{if(!guildId)throw new Error("Choisissez d’abord un serveur.");const value=Number(document.getElementById("v10RetentionDays").value);await api(`/api/guilds/${guildId}/v10/privacy-policy`,{method:"PUT",body:JSON.stringify({retention_days:value})});notice("Durée de conservation V10 enregistrée.");await v10Load()}catch(err){notice(err.message,false)}});document.getElementById("guild")?.addEventListener("change",()=>setTimeout(v10Load,250));setTimeout(v10Load,600);setInterval(v10Load,15000)})();
</script>
'''


def _inject_ui(platform_v4) -> None:
    html = platform_v4.PLATFORM_HTML
    if 'id="sentrix-platform-v10-style"' not in html:
        html = html.replace("</head>", _V10_CSS + "\n</head>", 1)
    if 'id="v10Status"' not in html:
        marker = '<div id="notice" class="notice">Chargement...</div>'
        html = html.replace(marker, marker + _V10_BANNER, 1)
    if 'id="v10RetentionDays"' not in html:
        marker = '<button class="btn danger" id="privacyDelete">Supprimer mes données personnelles</button></section>'
        html = html.replace(marker, '<button class="btn danger" id="privacyDelete">Supprimer mes données personnelles</button>' + _V10_RETENTION + '</section>', 1)
    if 'id="sentrix-platform-v10-js"' not in html:
        html = html.replace("</body>", _V10_JS + "\n</body>", 1)
    platform_v4.PLATFORM_HTML = html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import platform_v4
    _inject_ui(platform_v4)
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_routes([
            web.get("/api/guilds/{guild_id}/v10/summary", lambda r: api_summary(dashboard, r)),
            web.get("/api/guilds/{guild_id}/v10/privacy-policy", lambda r: api_privacy_policy_get(dashboard, r)),
            web.put("/api/guilds/{guild_id}/v10/privacy-policy", lambda r: api_privacy_policy_put(dashboard, r)),
        ])
        return app

    dashboard.build_app = build_app
    logger.info("Bot V10: dashboard live/mobile et rétention installés.")
