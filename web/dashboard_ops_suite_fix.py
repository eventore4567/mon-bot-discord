"""Compatibility hardening for the SentriX dashboard operations suite.

Kept separate so the operational layer can stay additive and low-risk while older dashboard
schemas continue to expose internal columns such as guild_id/updated_at.
"""
from __future__ import annotations

import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.ops-suite-fix")
_INSTALLED = False

PATCH_JS = r'''
<script id="sentrix-ops-suite-fix-js">
(() => {
  "use strict";
  if (window.__sentrixOpsSuiteFix) return;
  window.__sentrixOpsSuiteFix = true;
  const byId = id => document.getElementById(id);
  const csrf = () => { try { return String(state?.csrf || ""); } catch (_) { return ""; } };
  async function safeClone(source, target){
    const response = await fetch(`/api/guilds/${encodeURIComponent(source)}/ops/clone-safe/${encodeURIComponent(target)}`, {
      method:"POST", credentials:"same-origin", cache:"no-store",
      headers:{"X-CSRF-Token":csrf(),"Content-Type":"application/json"}, body:"{}"
    });
    let data={}; try{data=await response.json()}catch(_){}
    if(!response.ok) throw new Error(data.error || `Erreur HTTP ${response.status}`);
    return data;
  }
  document.addEventListener("click", async event => {
    const button = event.target?.closest?.("#sxCloneConfig");
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    let source=""; try{source=String(state?.guildId||"")}catch(_){}
    const target=String(byId("sxCloneTarget")?.value||"");
    if(!source||!target){ window.toast?.("Choisis un serveur cible.",true); return; }
    button.disabled=true;
    try{ await safeClone(source,target); window.toast?.("Configuration copiée vers le serveur cible."); }
    catch(error){ window.toast?.(error.message||"Duplication impossible.",true); }
    finally{ button.disabled=false; }
  }, true);
})();
</script>
'''


def install(dashboard, ops) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    async def clean_snapshot(_dashboard, db, guild_id: int) -> dict:
        conf = await db.get_guild_config(guild_id)
        automod = await db.get_automod(guild_id)
        ai = await db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
        conf_dict = dict(conf) if conf else {}
        automod_dict = dict(automod) if automod else {}
        ai_dict = dict(ai) if ai else {}
        allowed_settings = (
            set(getattr(dashboard, "TEXT_FIELDS", {}))
            | set(getattr(dashboard, "URL_FIELDS", set()))
            | set(getattr(dashboard, "ROLE_FIELDS", set()))
            | set(getattr(dashboard, "CHANNEL_FIELDS", set()))
            | set(getattr(dashboard, "BOOL_FIELDS", set()))
            | set(getattr(dashboard, "INT_FIELDS", {}))
            | {"security_level", "xp_multiplier", "ticket_category"}
        )
        allowed_ai = (
            set(getattr(dashboard, "AI_BOOL_FIELDS", set()))
            | set(getattr(dashboard, "AI_INT_FIELDS", {}))
            | set(getattr(dashboard, "AI_CHOICE_FIELDS", {}))
        )
        return {
            "settings": {key: conf_dict.get(key) for key in allowed_settings if key in conf_dict},
            "automod": {key: automod_dict.get(key) for key in getattr(dashboard, "AUTOMOD_FIELDS", set()) if key in automod_dict},
            "ai": {key: ai_dict.get(key) for key in allowed_ai if key in ai_dict},
        }

    ops._snapshot = clean_snapshot

    # Make runtime policy installation fail-open if a discord.py build prevents replacing
    # CommandTree.interaction_check on the instance. Prefix guards still remain active.
    original_policy_installer = ops._install_runtime_policy
    def safe_policy_installer(bot):
        try:
            return original_policy_installer(bot)
        except Exception:
            logger.exception("Slash policy guard could not be installed; dashboard remains available.")
            return None
    ops._install_runtime_policy = safe_policy_installer

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-ops-suite-fix-js"' not in html:
        dashboard.INDEX_HTML = html.replace("</body>", PATCH_JS + "\n</body>", 1)

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_ops_fix_routes", False):
        def build_app_with_safe_clone(bot):
            app = original_build(bot)

            async def clone_safe(request: web.Request):
                try:
                    source_id = int(request.match_info["guild_id"])
                    target_id = int(request.match_info["target_id"])
                except (TypeError, ValueError):
                    return dashboard._json_error("Serveur invalide.", 400)
                session, source, error = await dashboard._manageable_guild(request, source_id)
                if error:
                    return error
                csrf_error = dashboard._require_csrf(request, session)
                if csrf_error:
                    return csrf_error
                target = bot.get_guild(target_id)
                if target is None:
                    return dashboard._json_error("Serveur cible introuvable.", 404)
                user_id = int(session["user"]["id"])
                if await dashboard._administrator_member(target, user_id) is None:
                    return dashboard._json_error("Tu dois aussi être administrateur du serveur cible.", 403)

                source_snapshot = await clean_snapshot(dashboard, bot.db, source_id)
                target_before = await clean_snapshot(dashboard, bot.db, target_id)
                source_settings = source_snapshot.get("settings") or {}

                # IDs Discord are guild-specific. Copy scalar settings directly but keep only
                # role/channel references that also exist in the target guild.
                portable = {}
                role_fields = set(getattr(dashboard, "ROLE_FIELDS", set()))
                channel_fields = set(getattr(dashboard, "CHANNEL_FIELDS", set())) | {"ticket_category"}
                for key, value in source_settings.items():
                    if key in role_fields and value and target.get_role(int(value)) is None:
                        portable[key] = None
                    elif key in channel_fields and value and target.get_channel(int(value)) is None:
                        portable[key] = None
                    else:
                        portable[key] = value
                clean_settings, validation_error = dashboard._validate_settings(target, portable)
                if validation_error:
                    return dashboard._json_error(validation_error, 409)
                for key, value in clean_settings.items():
                    await bot.db.set_guild_config(target_id, key, value)
                for key, value in (source_snapshot.get("automod") or {}).items():
                    if key in dashboard.AUTOMOD_FIELDS:
                        await bot.db.set_automod(target_id, key, int(bool(value)))
                clean_ai, ai_error = dashboard._validate_ai(source_snapshot.get("ai") or {})
                if ai_error:
                    return dashboard._json_error(ai_error, 409)
                if clean_ai:
                    await bot.db.execute(
                        "INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",
                        (target_id, int(time.time())),
                    )
                    for key, value in clean_ai.items():
                        await bot.db.execute(
                            f"UPDATE ai_settings SET {key} = ?, updated_at = ? WHERE guild_id = ?",
                            (value, int(time.time()), target_id),
                        )
                try:
                    await ops._record_history(
                        dashboard, request, target_id, target_before,
                        list(clean_settings) + list((source_snapshot.get("automod") or {}).keys()) + list(clean_ai),
                    )
                except Exception:
                    logger.exception("Unable to record safe clone history.")
                return web.json_response({"ok": True, "message": "Configuration dupliquée avec adaptation des IDs Discord."})

            app.router.add_post("/api/guilds/{guild_id}/ops/clone-safe/{target_id}", clone_safe)
            return app

        build_app_with_safe_clone._sentrix_ops_fix_routes = True
        dashboard.build_app = build_app_with_safe_clone

    # Complete the requested dashboard feature set after compatibility hardening.  This
    # layer adds access tiers, searchable logs, dry-run previews and deeper health status.
    try:
        from web import dashboard_ops_suite_plus
        if not dashboard_ops_suite_plus.install(dashboard, ops):
            raise RuntimeError("Ops Suite Plus returned false")
    except Exception:
        logger.exception("Ops Suite Plus installation failed.")
        return False

    _INSTALLED = True
    logger.info("SentriX dashboard ops-suite compatibility fixes installed.")
    return True
