"""Compatibility hardening for the SentriX dashboard operations suite."""
from __future__ import annotations
import logging
import time
from aiohttp import web
logger = logging.getLogger("bot.dashboard.ops-suite-fix")
_INSTALLED = False
PATCH_JS = r'''<script id="sentrix-ops-suite-fix-js">(()=>{"use strict";if(window.__sentrixOpsSuiteFix)return;window.__sentrixOpsSuiteFix=true;const b=id=>document.getElementById(id),c=()=>{try{return String(state?.csrf||"")}catch(_){return""}};document.addEventListener("click",async e=>{const x=e.target?.closest?.("#sxCloneConfig");if(!x)return;e.preventDefault();e.stopImmediatePropagation();let s="";try{s=String(state?.guildId||"")}catch(_){}const t=String(b("sxCloneTarget")?.value||"");if(!s||!t){window.toast?.("Choisis un serveur cible.",true);return}x.disabled=true;try{const r=await fetch(`/api/guilds/${encodeURIComponent(s)}/ops/clone-safe/${encodeURIComponent(t)}`,{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"X-CSRF-Token":c(),"Content-Type":"application/json"},body:"{}"});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw new Error(d.error||`Erreur HTTP ${r.status}`);window.toast?.("Configuration copiée vers le serveur cible.")}catch(err){window.toast?.(err.message||"Duplication impossible.",true)}finally{x.disabled=false}},true)})();</script>'''
def install(dashboard, ops) -> bool:
    global _INSTALLED
    if _INSTALLED:return True
    async def clean_snapshot(_dashboard,db,guild_id:int)->dict:
        conf=await db.get_guild_config(guild_id);automod=await db.get_automod(guild_id);ai=await db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?",(guild_id,));cd=dict(conf) if conf else {};ad=dict(automod) if automod else {};aid=dict(ai) if ai else {}
        allowed=(set(getattr(dashboard,"TEXT_FIELDS",{}))|set(getattr(dashboard,"URL_FIELDS",set()))|set(getattr(dashboard,"ROLE_FIELDS",set()))|set(getattr(dashboard,"CHANNEL_FIELDS",set()))|set(getattr(dashboard,"BOOL_FIELDS",set()))|set(getattr(dashboard,"INT_FIELDS",{}))|{"security_level","xp_multiplier","ticket_category"});aai=set(getattr(dashboard,"AI_BOOL_FIELDS",set()))|set(getattr(dashboard,"AI_INT_FIELDS",{}))|set(getattr(dashboard,"AI_CHOICE_FIELDS",{}))
        return {"settings":{k:cd.get(k) for k in allowed if k in cd},"automod":{k:ad.get(k) for k in getattr(dashboard,"AUTOMOD_FIELDS",set()) if k in ad},"ai":{k:aid.get(k) for k in aai if k in aid}}
    ops._snapshot=clean_snapshot
    original_policy_installer=ops._install_runtime_policy
    def safe_policy_installer(bot):
        try:return original_policy_installer(bot)
        except Exception:logger.exception("Slash policy guard could not be installed; dashboard remains available.");return None
    ops._install_runtime_policy=safe_policy_installer
    html=str(getattr(dashboard,"INDEX_HTML","") or "")
    if 'id="sentrix-ops-suite-fix-js"' not in html:dashboard.INDEX_HTML=html.replace("</body>",PATCH_JS+"\n</body>",1)
    original_build=dashboard.build_app
    if not getattr(original_build,"_sentrix_ops_fix_routes",False):
        def build_app_with_safe_clone(bot):
            app=original_build(bot)
            async def clone_safe(request:web.Request):
                try:source_id=int(request.match_info["guild_id"]);target_id=int(request.match_info["target_id"])
                except (TypeError,ValueError):return dashboard._json_error("Serveur invalide.",400)
                session,source,error=await dashboard._manageable_guild(request,source_id)
                if error:return error
                csrf_error=dashboard._require_csrf(request,session)
                if csrf_error:return csrf_error
                target=bot.get_guild(target_id)
                if target is None:return dashboard._json_error("Serveur cible introuvable.",404)
                user_id=int(session["user"]["id"])
                if await dashboard._administrator_member(target,user_id) is None:return dashboard._json_error("Tu dois aussi être administrateur du serveur cible.",403)
                snap=await clean_snapshot(dashboard,bot.db,source_id);before=await clean_snapshot(dashboard,bot.db,target_id);portable={};roles=set(getattr(dashboard,"ROLE_FIELDS",set()));channels=set(getattr(dashboard,"CHANNEL_FIELDS",set()))|{"ticket_category"}
                for key,value in (snap.get("settings") or {}).items():
                    if key in roles and value and target.get_role(int(value)) is None:portable[key]=None
                    elif key in channels and value and target.get_channel(int(value)) is None:portable[key]=None
                    else:portable[key]=value
                clean,msg=dashboard._validate_settings(target,portable)
                if msg:return dashboard._json_error(msg,409)
                for key,value in clean.items():await bot.db.set_guild_config(target_id,key,value)
                for key,value in (snap.get("automod") or {}).items():
                    if key in dashboard.AUTOMOD_FIELDS:await bot.db.set_automod(target_id,key,int(bool(value)))
                cai,msg=dashboard._validate_ai(snap.get("ai") or {})
                if msg:return dashboard._json_error(msg,409)
                if cai:
                    await bot.db.execute("INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",(target_id,int(time.time())))
                    for key,value in cai.items():await bot.db.execute(f"UPDATE ai_settings SET {key} = ?, updated_at = ? WHERE guild_id = ?",(value,int(time.time()),target_id))
                try:await ops._record_history(dashboard,request,target_id,before,list(clean)+list((snap.get("automod") or {}).keys())+list(cai))
                except Exception:logger.exception("Unable to record safe clone history.")
                return web.json_response({"ok":True,"message":"Configuration dupliquée avec adaptation des IDs Discord."})
            app.router.add_post("/api/guilds/{guild_id}/ops/clone-safe/{target_id}",clone_safe);return app
        build_app_with_safe_clone._sentrix_ops_fix_routes=True;dashboard.build_app=build_app_with_safe_clone
    contract=("_manageable_guild","_require_session","_json_error","_require_csrf","_invite_url","_administrator_member","handle_guilds","build_app")
    if all(hasattr(dashboard,n) for n in contract):
        try:
            from web import dashboard_ops_suite_plus
            if not dashboard_ops_suite_plus.install(dashboard,ops):raise RuntimeError("Ops Suite Plus returned false")
            from web import dashboard_control_center_v3
            if not dashboard_control_center_v3.install(dashboard):raise RuntimeError("Control Center V3 returned false")
        except Exception:logger.exception("Advanced dashboard installation failed.");return False
    _INSTALLED=True;logger.info("SentriX dashboard ops-suite compatibility fixes installed.");return True
