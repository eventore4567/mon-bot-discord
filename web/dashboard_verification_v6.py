"""Real Discord verification controls for the SentriX dashboard.

This module exposes the existing V96 CAPTCHA verification engine through the authenticated
server dashboard. It does not introduce a second verification system: it reads/writes the
same guild_config keys and verification_panels_v96 table used by sentrix_verification_v96.
"""
from __future__ import annotations

import time
from aiohttp import web
import discord

DEFAULT_TITLE = "Règlement & vérification"
DEFAULT_RULES = (
    "Bienvenue sur le serveur.\n\n"
    "Merci de lire attentivement le règlement avant de continuer. "
    "En cliquant sur le bouton ci-dessous, vous certifiez avoir lu et accepté les règles. "
    "Un CAPTCHA vous sera ensuite demandé avant l'attribution du rôle vérifié."
)

VERIFY_CSS = r'''
<style id="sentrix-dashboard-verification-v6-css">
.sx-verify-v6{grid-column:1/-1;border:1px solid #255578;border-radius:15px;background:linear-gradient(180deg,#0e1d2a,#0a151f);padding:18px;margin-top:4px}.sx-verify-v6 h3{margin:0 0 5px;font-size:19px}.sx-verify-v6>p{margin:0 0 14px;color:#8fa1b7}.sx-verify-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.sx-verify-field{display:flex;flex-direction:column;gap:6px}.sx-verify-field.full{grid-column:1/-1}.sx-verify-field label{font-size:12px;font-weight:800;color:#cfe4f7}.sx-verify-field input,.sx-verify-field textarea{width:100%;box-sizing:border-box;background:#09141f;border:1px solid #29465f;border-radius:10px;color:#eef5ff;padding:10px 11px}.sx-verify-field textarea{min-height:125px;resize:vertical}.sx-verify-status{margin-top:13px;padding:12px;border:1px solid #203b50;border-radius:11px;background:#091723;color:#9fb5c8}.sx-verify-status.ok{border-color:#235b45;background:#0b2019;color:#8ce9bb}.sx-verify-status.bad{border-color:#713642;background:#241016;color:#ff9baa}.sx-verify-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:13px}.sx-verify-check{display:flex;align-items:center;gap:9px;color:#c7d9e8;font-size:12px}.sx-verify-check input{width:auto}.sx-verify-meta{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}.sx-verify-chip{padding:5px 8px;border-radius:999px;border:1px solid #2a465e;background:#0a1824;color:#a9c5da;font-size:11px;font-weight:800}@media(max-width:760px){.sx-verify-grid{grid-template-columns:1fr}.sx-verify-field.full{grid-column:auto}}
</style>
'''

VERIFY_JS = r'''
<script id="sentrix-dashboard-verification-v6-js">
(()=>{"use strict";if(window.__sentrixDashboardVerificationV6)return;window.__sentrixDashboardVerificationV6=true;
const $=id=>document.getElementById(id),esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const S=()=>{try{return state}catch(_){return null}},gid=()=>String(S()?.guildId||""),csrf=()=>String(S()?.csrf||"");
async function api(path,opt={}){const h={...(opt.headers||{})};if(opt.method&&opt.method!=="GET")h["X-CSRF-Token"]=csrf();if(opt.body)h["Content-Type"]="application/json";const r=await fetch(path,{credentials:"same-origin",cache:"no-store",...opt,headers:h});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw new Error(d.error||`Erreur HTTP ${r.status}`);return d}
function onVerification(){try{return S()?.tab==='verification'}catch(_){return false}}
function statusText(d){if(!d.configured)return 'Configuration incomplète : choisis le salon et le rôle de vérification ci-dessus.';if(d.published)return `Actif sur Discord · CAPTCHA ${d.captcha_enabled?'activé':'désactivé'}${d.channel_name?' · #'+d.channel_name:''}${d.role_name?' · @'+d.role_name:''}`;return 'Configuré mais aucun panneau de vérification n’est publié sur Discord.'}
async function refresh(){const id=gid(),box=$("sxVerifyV6Status");if(!id||!box)return;try{const d=await api(`/api/guilds/${encodeURIComponent(id)}/verification-v6`);box.className='sx-verify-status '+(d.published?'ok':d.configured?'':'bad');box.textContent=statusText(d);const t=$("sxVerifyV6Title"),r=$("sxVerifyV6Rules"),i=$("sxVerifyV6Image"),a=$("sxVerifyV6Auto");if(t&&!t.dataset.touched)t.value=d.title||'';if(r&&!r.dataset.touched)r.value=d.rules_text||'';if(i&&!i.dataset.touched)i.value=d.image_url||'';if(a&&!a.dataset.touched)a.checked=!!d.auto_access;const link=$("sxVerifyV6Open");if(link){link.hidden=!d.jump_url;link.href=d.jump_url||'#'}const btn=$("sxVerifyV6Publish");if(btn)btn.textContent=d.published?'Mettre à jour sur Discord':'Publier sur Discord';const meta=$("sxVerifyV6Meta");if(meta)meta.innerHTML=`<span class="sx-verify-chip">CAPTCHA réel</span><span class="sx-verify-chip">Rôle après réussite</span><span class="sx-verify-chip">${d.published?'Panneau actif':'Non publié'}</span>`}catch(e){box.className='sx-verify-status bad';box.textContent=e.message}}
async function publish(){const id=gid(),btn=$("sxVerifyV6Publish"),box=$("sxVerifyV6Status");if(!id||!btn)return;btn.disabled=true;if(box){box.className='sx-verify-status';box.textContent='Publication Discord en cours…'}try{const body={title:$("sxVerifyV6Title")?.value||'',rules_text:$("sxVerifyV6Rules")?.value||'',image_url:$("sxVerifyV6Image")?.value||'',auto_access:!!$("sxVerifyV6Auto")?.checked};const d=await api(`/api/guilds/${encodeURIComponent(id)}/verification-v6/publish`,{method:'POST',body:JSON.stringify(body)});window.toast?.(d.message||'Vérification publiée sur Discord.');for(const x of ['sxVerifyV6Title','sxVerifyV6Rules','sxVerifyV6Image','sxVerifyV6Auto'])$(x)?.removeAttribute('data-touched');await refresh()}catch(e){if(box){box.className='sx-verify-status bad';box.textContent=e.message}window.toast?.(e.message,true)}finally{btn.disabled=false}}
function mount(){if(!onVerification())return;const fields=$("fields");if(!fields||$("sxVerifyV6"))return;const s=document.createElement('section');s.id='sxVerifyV6';s.className='sx-verify-v6';s.innerHTML=`<h3>Vérification Discord réelle</h3><p>Publie le règlement dans Discord. Le membre clique sur le bouton, réussit le CAPTCHA SentriX, puis reçoit le rôle configuré.</p><div class="sx-verify-grid"><div class="sx-verify-field"><label>Titre du panneau</label><input id="sxVerifyV6Title" maxlength="100"></div><div class="sx-verify-field"><label>Image facultative (URL)</label><input id="sxVerifyV6Image" maxlength="500" placeholder="https://..."></div><div class="sx-verify-field full"><label>Règlement / message</label><textarea id="sxVerifyV6Rules" maxlength="4000"></textarea></div><label class="sx-verify-check full"><input id="sxVerifyV6Auto" type="checkbox"> Fermer automatiquement les espaces publics aux membres non vérifiés et les ouvrir au rôle vérifié</label></div><div id="sxVerifyV6Meta" class="sx-verify-meta"></div><div id="sxVerifyV6Status" class="sx-verify-status">Chargement…</div><div class="sx-verify-actions"><button class="btn primary" id="sxVerifyV6Publish" type="button">Publier sur Discord</button><button class="btn" id="sxVerifyV6Refresh" type="button">Actualiser</button><a class="btn" id="sxVerifyV6Open" target="_blank" rel="noopener" hidden>Ouvrir le panneau Discord</a></div>`;fields.appendChild(s);for(const x of ['sxVerifyV6Title','sxVerifyV6Rules','sxVerifyV6Image','sxVerifyV6Auto'])$(x)?.addEventListener('input',e=>e.currentTarget.dataset.touched='1');$("sxVerifyV6Publish")?.addEventListener('click',publish);$("sxVerifyV6Refresh")?.addEventListener('click',refresh);refresh()}
const run=()=>{setTimeout(mount,40);setTimeout(mount,180)};document.addEventListener('click',e=>{if(e.target?.closest?.('[data-tab="verification"]'))run()},true);new MutationObserver(()=>{if(onVerification())mount()}).observe(document.body,{subtree:true,childList:true});if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',run,{once:true});else run();
})();
</script>
'''


def _row(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key] if key in row.keys() else default
    except Exception:
        return default


async def _ensure_table(db) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_panels_v96 (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            rules_text TEXT NOT NULL,
            image_url TEXT,
            updated_at INTEGER NOT NULL
        )
        """
    )


async def _state(bot, guild: discord.Guild) -> dict:
    await _ensure_table(bot.db)
    conf = await bot.db.get_guild_config(guild.id)
    panel = await bot.db.fetchone("SELECT * FROM verification_panels_v96 WHERE guild_id = ?", (guild.id,))
    channel_id = _row(conf, "verification_channel") or _row(panel, "channel_id")
    role_id = _row(conf, "verify_role") or _row(conf, "verification_role") or _row(panel, "role_id")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    role = guild.get_role(int(role_id)) if role_id else None
    auto_raw = _row(conf, "verification_auto_access", 0)
    try:
        auto_access = bool(int(auto_raw or 0))
    except (TypeError, ValueError):
        auto_access = bool(auto_raw)
    published = bool(panel and guild.get_channel(int(_row(panel, "channel_id", 0) or 0)))
    jump_url = None
    if panel:
        pc = int(_row(panel, "channel_id", 0) or 0)
        pm = int(_row(panel, "message_id", 0) or 0)
        if pc and pm:
            jump_url = f"https://discord.com/channels/{guild.id}/{pc}/{pm}"
    return {
        "configured": isinstance(channel, discord.TextChannel) and isinstance(role, discord.Role),
        "published": published,
        "captcha_enabled": bool(_row(conf, "verify_captcha_enabled", 0)),
        "channel_id": getattr(channel, "id", None),
        "channel_name": getattr(channel, "name", None),
        "role_id": getattr(role, "id", None),
        "role_name": getattr(role, "name", None),
        "title": _row(panel, "title", DEFAULT_TITLE) or DEFAULT_TITLE,
        "rules_text": _row(panel, "rules_text", DEFAULT_RULES) or DEFAULT_RULES,
        "image_url": _row(panel, "image_url", None),
        "auto_access": auto_access,
        "jump_url": jump_url,
    }


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html or "</head>" not in html or "</body>" not in html:
        return False
    if 'id="sentrix-dashboard-verification-v6-css"' not in html:
        html = html.replace("</head>", VERIFY_CSS + "\n</head>", 1)
    if 'id="sentrix-dashboard-verification-v6-js"' not in html:
        html = html.replace("</body>", VERIFY_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html

    original_build = dashboard.build_app
    if getattr(original_build, "_sentrix_verification_v6_routes", False):
        return True

    def build_app_verification_v6(bot):
        app = original_build(bot)

        async def get_status(request: web.Request):
            try:
                guild_id = int(request.match_info["guild_id"])
            except (TypeError, ValueError):
                return dashboard._json_error("Serveur invalide.", 400)
            _session, guild, error = await dashboard._manageable_guild(request, guild_id)
            if error:
                return error
            return web.json_response(await _state(bot, guild))

        async def publish(request: web.Request):
            try:
                guild_id = int(request.match_info["guild_id"])
            except (TypeError, ValueError):
                return dashboard._json_error("Serveur invalide.", 400)
            session, guild, error = await dashboard._manageable_guild(request, guild_id)
            if error:
                return error
            csrf_error = dashboard._require_csrf(request, session)
            if csrf_error:
                return csrf_error
            try:
                payload = await request.json()
            except Exception:
                payload = {}

            conf = await bot.db.get_guild_config(guild.id)
            channel_id = _row(conf, "verification_channel")
            role_id = _row(conf, "verify_role") or _row(conf, "verification_role")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            role = guild.get_role(int(role_id)) if role_id else None
            if not isinstance(channel, discord.TextChannel):
                return dashboard._json_error("Choisis d'abord un salon de vérification valide puis enregistre la configuration.", 409)
            if not isinstance(role, discord.Role):
                return dashboard._json_error("Choisis d'abord le rôle attribué après vérification puis enregistre la configuration.", 409)

            from cogs.verification import VerifyView, role_grant_problem
            problem = role_grant_problem(guild, role)
            if problem:
                return dashboard._json_error(str(problem), 409)
            me = guild.me
            if me is None:
                return dashboard._json_error("SentriX n'est pas disponible dans le cache Discord de ce serveur.", 503)
            perms = channel.permissions_for(me)
            missing = [label for attr, label in (("view_channel", "Voir le salon"), ("send_messages", "Envoyer des messages"), ("embed_links", "Intégrer des liens")) if not bool(getattr(perms, attr, False))]
            if missing:
                return dashboard._json_error("Permissions manquantes pour SentriX : " + ", ".join(missing) + ".", 409)

            title = str(payload.get("title") or DEFAULT_TITLE).strip()[:100] or DEFAULT_TITLE
            rules = str(payload.get("rules_text") or DEFAULT_RULES).strip()[:4000] or DEFAULT_RULES
            image = str(payload.get("image_url") or "").strip()[:500] or None
            if image and not (image.startswith("https://") or image.startswith("http://")):
                return dashboard._json_error("L'image doit être une URL http:// ou https:// valide.", 400)
            auto_access = bool(payload.get("auto_access", False))

            cog = bot.get_cog("VerificationConfigV96")
            actor = guild.get_member(int(session["user"]["id"]))
            if auto_access:
                if cog is None:
                    return dashboard._json_error("Le moteur de vérification V96 n'est pas chargé. Réessaie après le démarrage complet de SentriX.", 503)
                issues = await cog._preflight(guild, channel=channel, role=role, auto_access=True)
                if issues:
                    return dashboard._json_error(" ".join(str(x) for x in issues), 409)
                if actor is None:
                    return dashboard._json_error("Ton membre Discord n'est pas disponible dans le cache du serveur ; actualise puis réessaie.", 409)

            embed = discord.Embed(title=title, description=rules, colour=discord.Colour.blurple())
            if image:
                embed.set_image(url=image)
            embed.set_footer(text="SentriX • Vérification sécurisée")

            await _ensure_table(bot.db)
            existing = await bot.db.fetchone("SELECT channel_id, message_id FROM verification_panels_v96 WHERE guild_id = ?", (guild.id,))
            sent = None
            old_message = None
            if existing:
                old_channel = guild.get_channel(int(existing["channel_id"]))
                if isinstance(old_channel, discord.TextChannel):
                    try:
                        old_message = await old_channel.fetch_message(int(existing["message_id"]))
                        if old_channel.id == channel.id:
                            await old_message.edit(embed=embed, view=VerifyView())
                            sent = old_message
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        old_message = None
            if sent is None:
                sent = await channel.send(embed=embed, view=VerifyView())

            await bot.db.set_guild_config(guild.id, "verify_role", role.id)
            await bot.db.set_guild_config(guild.id, "verification_role", role.id)
            await bot.db.set_guild_config(guild.id, "verification_channel", channel.id)
            await bot.db.set_guild_config(guild.id, "verify_captcha_enabled", 1)
            await bot.db.set_guild_config(guild.id, "verification_auto_access", int(auto_access))
            await bot.db.execute(
                "INSERT INTO verification_panels_v96(guild_id,channel_id,message_id,role_id,title,rules_text,image_url,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,message_id=excluded.message_id,role_id=excluded.role_id,title=excluded.title,rules_text=excluded.rules_text,image_url=excluded.image_url,updated_at=excluded.updated_at",
                (guild.id, channel.id, sent.id, role.id, title, rules, image, int(time.time())),
            )

            if auto_access:
                await cog._apply_auto_access(guild, verification_channel=channel, verified_role=role, actor=actor)
            if old_message is not None and getattr(old_message, "id", None) != sent.id:
                try:
                    await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

            return web.json_response({
                "ok": True,
                "message": "Vérification Discord publiée avec CAPTCHA actif.",
                "jump_url": sent.jump_url,
            })

        app.router.add_get("/api/guilds/{guild_id}/verification-v6", get_status)
        app.router.add_post("/api/guilds/{guild_id}/verification-v6/publish", publish)
        return app

    build_app_verification_v6._sentrix_verification_v6_routes = True
    dashboard.build_app = build_app_verification_v6
    return True
