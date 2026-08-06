"""Extension du dashboard SentriX : réglages de +designsetup."""

from __future__ import annotations

import logging

from aiohttp import web

from database.db import MANAGER_CATEGORIES as DB_MANAGER_CATEGORIES

logger = logging.getLogger("bot.dashboard.design-setup")
_INSTALLED = False


async def _context(request: web.Request, *, write: bool = False):
    dashboard = request.app["dashboard_module"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return dashboard, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return dashboard, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return dashboard, None, None, csrf_error
    return dashboard, session, guild, None


async def handle_get_design(request: web.Request) -> web.Response:
    dashboard, _session, guild, error = await _context(request)
    if error:
        return error
    settings = await request.app["bot"].db.get_design_settings(guild.id)
    return web.json_response({"ok": True, "design": settings})


async def handle_save_design(request: web.Request) -> web.Response:
    dashboard, session, guild, error = await _context(request, write=True)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
    if not isinstance(payload, dict):
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

    colours = {}
    for field in ("primary_color", "secondary_color", "success_color", "warning_color", "danger_color"):
        raw = str(payload.get(field, "")).strip().removeprefix("#")
        if len(raw) != 6:
            return dashboard._json_error(f"La couleur {field} doit être au format #RRGGBB.", 400)
        try:
            colours[field] = int(raw, 16)
        except ValueError:
            return dashboard._json_error(f"La couleur {field} doit être au format #RRGGBB.", 400)

    footer = str(payload.get("footer") or "").strip()
    if not 1 <= len(footer) <= 100:
        return dashboard._json_error("Le footer doit contenir entre 1 et 100 caractères.", 400)
    try:
        progress_length = int(payload.get("progress_length", 10))
    except (TypeError, ValueError):
        return dashboard._json_error("La longueur de la barre doit être un nombre entier.", 400)
    if not 3 <= progress_length <= 30:
        return dashboard._json_error("La longueur de la barre doit être comprise entre 3 et 30.", 400)

    progress_filled = str(payload.get("progress_filled") or "").strip()
    progress_empty = str(payload.get("progress_empty") or "").strip()
    if not progress_filled or not progress_empty or len(progress_filled) > 16 or len(progress_empty) > 16:
        return dashboard._json_error(
            "Les symboles de progression doivent contenir entre 1 et 16 caractères.", 400
        )

    updates = {
        **colours,
        "footer": footer,
        "progress_length": progress_length,
        "progress_filled": progress_filled,
        "progress_empty": progress_empty,
        "show_avatars": bool(payload.get("show_avatars")),
        "compact_mode": bool(payload.get("compact_mode")),
        "charts_enabled": bool(payload.get("charts_enabled")),
    }
    db = request.app["bot"].db
    await db.set_design_settings(guild.id, updates)
    saved = await db.get_design_settings(guild.id)
    await db.log_setup_history(
        guild.id,
        int(session["user"]["id"]),
        "design",
        "Mise à jour depuis le dashboard",
        None,
        "designsetup",
    )
    return web.json_response({
        "ok": True,
        "message": "Design de SentriX enregistré.",
        "design": saved,
    })


DESIGN_CSS = r"""
    .design-setup-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;width:100%}
    .design-setup-grid .full{grid-column:1/-1}
    .design-colours{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .design-colour-input{display:grid;grid-template-columns:54px 1fr;gap:8px}
    .design-colour-input input[type=color]{height:44px;padding:4px}
    .design-preview{padding:17px;border:1px solid #2a3350;border-left:5px solid var(--design-primary,#5865f2);border-radius:12px;background:#111725}
    .design-preview h3{margin:0 0 8px}.design-preview p{margin:0;color:var(--muted)}
    .design-progress{display:flex;gap:2px;margin-top:12px;font-size:18px;overflow-wrap:anywhere}
    @media(max-width:850px){.design-setup-grid,.design-colours{grid-template-columns:1fr}.design-setup-grid .full{grid-column:auto}}
"""


DESIGN_JS = r"""
    state.designSetup=null;
    async function loadDesignSetup(force=false){
      if(!state.guildId)return null;
      if(!state.designSetup||force){const result=await json(`/api/guilds/${state.guildId}/design`);state.designSetup=result.design;}
      return state.designSetup;
    }
    function designHex(value){return `#${Number(value||0).toString(16).padStart(6,"0").slice(-6)}`;}
    function updateDesignPreview(){
      const box=$("designPreview");if(!box)return;
      const primary=$("design_primary_color")?.value||"#5865F2";box.style.setProperty("--design-primary",primary);
      $("designPreviewFooter").textContent=$("design_footer")?.value||"SentriX";
      const length=Math.max(3,Math.min(30,Number($("design_progress_length")?.value||10)));
      const filled=$("design_progress_filled")?.value||"🟪",empty=$("design_progress_empty")?.value||"⬛";
      const active=Math.max(1,Math.round(length*.7));$("designPreviewProgress").textContent=filled.repeat(active)+empty.repeat(length-active);
    }
    async function renderDesignSetup(){
      $("fields").innerHTML='<div class="setup-empty">Chargement du design…</div>';
      const g=await loadDesignSetup();if(state.tab!=="designSetup")return;
      const colours=[["primary_color","Couleur principale"],["secondary_color","Couleur secondaire"],["success_color","Couleur succès"],["warning_color","Couleur avertissement"],["danger_color","Couleur erreur"]];
      $("fields").innerHTML=`<div class="design-setup-grid">
        <section class="setup-card full"><h3>Couleurs de SentriX</h3><p>Tous les réglages de +designsetup sont séparés pour ce serveur.</p><div class="design-colours">${colours.map(([key,label])=>{const value=designHex(g[key]);return `<div class="field"><label>${label}</label><div class="design-colour-input"><input id="design_picker_${key}" data-design-picker="${key}" type="color" value="${value}"><input id="design_${key}" data-design-key="${key}" value="${value}" maxlength="7"></div></div>`;}).join("")}</div></section>
        <div class="field full"><label>Footer</label><input id="design_footer" data-design-key="footer" maxlength="100" value="${esc(g.footer||"SentriX")}"></div>
        <div class="field"><label>Longueur de la barre de progression</label><input id="design_progress_length" data-design-key="progress_length" type="number" min="3" max="30" value="${esc(g.progress_length||10)}"></div>
        <div class="field"><label>Symbole rempli</label><input id="design_progress_filled" data-design-key="progress_filled" maxlength="16" value="${esc(g.progress_filled||"🟪")}"></div>
        <div class="field"><label>Symbole vide</label><input id="design_progress_empty" data-design-key="progress_empty" maxlength="16" value="${esc(g.progress_empty||"⬛")}"></div>
        ${[["show_avatars","Afficher les avatars"],["compact_mode","Mode compact"],["charts_enabled","Activer les graphiques"]].map(([key,label])=>`<label class="switch"><input data-design-key="${key}" type="checkbox" ${g[key]?"checked":""}><span></span><b>${label}</b></label>`).join("")}
        <div id="designPreview" class="design-preview full"><h3>Aperçu du design</h3><p>Exemple d'affichage • <span id="designPreviewFooter"></span></p><div id="designPreviewProgress" class="design-progress"></div></div>
      </div>`;
      document.querySelectorAll("[data-design-picker]").forEach(picker=>picker.addEventListener("input",()=>{const input=$(`design_${picker.dataset.designPicker}`);if(input)input.value=picker.value.toUpperCase();state.dirty=true;$("saveStatus").textContent="Modifications non enregistrées";updateDesignPreview();}));
      $("fields").querySelectorAll("[data-design-key]").forEach(el=>el.addEventListener("input",()=>{if(el.dataset.designKey.endsWith("_color")){const picker=$(`design_picker_${el.dataset.designKey}`);if(picker&&/^#[0-9a-f]{6}$/i.test(el.value))picker.value=el.value;}state.dirty=true;$("saveStatus").textContent="Modifications non enregistrées";updateDesignPreview();}));
      updateDesignPreview();
    }
    function collectDesignSetup(){const out={};document.querySelectorAll("[data-design-key]").forEach(el=>{out[el.dataset.designKey]=el.type==="checkbox"?el.checked:el.value;});return out;}
    async function saveDesignSetup(){
      $("settingsForm").classList.add("loading");try{const result=await json(`/api/guilds/${state.guildId}/design`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(collectDesignSetup())});toast(result.message);state.designSetup=result.design;state.dirty=false;$("saveStatus").textContent="Design configuré";renderDesignSetup();}catch(e){toast(e.message,true);}finally{$("settingsForm").classList.remove("loading");}
    }
"""


def _replace_once(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        logger.warning("Dashboard design setup : point d'insertion introuvable (%s).", label)
        return html
    return html.replace(old, new, 1)


def _patch_html(html: str) -> str:
    html = _replace_once(html, "  </style>", DESIGN_CSS + "\n  </style>", "css")
    html = _replace_once(
        html,
        '        <button data-tab="gamesSetup">Mini-jeux</button>\n        <button data-tab="setupTools">Setup avancé</button>\n',
        '        <button data-tab="gamesSetup">Mini-jeux</button>\n        <button data-tab="designSetup">Design</button>\n        <button data-tab="setupTools">Setup avancé</button>\n',
        "navigation",
    )
    html = _replace_once(
        html,
        '      gamesSetup:{title:"Configuration des mini-jeux",description:"Toutes les options de +gamesetup directement depuis le dashboard.",gamesSetup:true,fields:[]},\n      setupTools:',
        '      gamesSetup:{title:"Configuration des mini-jeux",description:"Toutes les options de +gamesetup directement depuis le dashboard.",gamesSetup:true,fields:[]},\n      designSetup:{title:"Design de SentriX",description:"Couleurs, footer, progression et options de +designsetup.",designSetup:true,fields:[]},\n      setupTools:',
        "tab",
    )
    html = _replace_once(html, "    function renderTab(){", DESIGN_JS + "\n    function renderTab(){", "javascript")
    old_render = '''    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else if(tab.embeds)renderEmbeds();else if(tab.gamesSetup)renderGamesSetup();else if(tab.setupTools)renderSetupTools();else $("fields").innerHTML=tab.fields.map(fieldHTML).join("");$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions||tab.setupTools));$("saveButton").textContent=tab.notifications?"Ajouter la notification":tab.embeds?"Envoyer l'embed":tab.gamesSetup?"Enregistrer les mini-jeux":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":tab.embeds?"Aperçu en direct":tab.gamesSetup?"Configuration complète":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions||tab.setupTools)return;state.dirty=true;if(!tab.embeds)$("saveStatus").textContent="Modifications non enregistrées";}));}\n'''
    new_render = '''    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else if(tab.embeds)renderEmbeds();else if(tab.gamesSetup)renderGamesSetup();else if(tab.designSetup)renderDesignSetup();else if(tab.setupTools)renderSetupTools();else $("fields").innerHTML=tab.fields.map(fieldHTML).join("");$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions||tab.setupTools));$("saveButton").textContent=tab.notifications?"Ajouter la notification":tab.embeds?"Envoyer l'embed":tab.gamesSetup?"Enregistrer les mini-jeux":tab.designSetup?"Enregistrer le design":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":tab.embeds?"Aperçu en direct":tab.gamesSetup?"Configuration complète":tab.designSetup?"Personnalisation visuelle":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions||tab.setupTools)return;state.dirty=true;if(!tab.embeds)$("saveStatus").textContent="Modifications non enregistrées";}));}\n'''
    html = _replace_once(html, old_render, new_render, "renderTab")
    old_save = '    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}if(tab.embeds){await sendEmbed();return;}if(tab.gamesSetup){await saveGamesSetup();return;}if(tab.setupTools){return;}const values={};'
    new_save = '    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}if(tab.embeds){await sendEmbed();return;}if(tab.gamesSetup){await saveGamesSetup();return;}if(tab.designSetup){await saveDesignSetup();return;}if(tab.setupTools){return;}const values={};'
    html = _replace_once(html, old_save, new_save, "save")
    html = html.replace(
        'state.guildData=await json(`/api/guilds/${value}`);state.setupTools=null;const d=state.guildData;',
        'state.guildData=await json(`/api/guilds/${value}`);state.setupTools=null;state.designSetup=null;const d=state.guildData;',
        1,
    )
    html = html.replace(
        '["roles","Rôles et salons"],["gamesSetup","Mini-jeux"]',
        '["roles","Rôles et salons"],["gamesSetup","Mini-jeux"],["designSetup","Design"]',
        1,
    )
    html = html.replace(
        "Autorisez un membre sans lui donner accès aux autres serveurs.",
        "Autorisez un membre à utiliser certaines commandes de gestion. L’accès au dashboard reste réservé aux administrateurs du serveur.",
        1,
    )
    return html


def install(dashboard, setup_dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    setup_dashboard.MANAGER_CATEGORIES.clear()
    setup_dashboard.MANAGER_CATEGORIES.update(DB_MANAGER_CATEGORIES)
    dashboard.INDEX_HTML = _patch_html(dashboard.INDEX_HTML)
    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/api/guilds/{guild_id}/design", handle_get_design)
        app.router.add_put("/api/guilds/{guild_id}/design", handle_save_design)
        return app

    dashboard.build_app = build_app
    logger.info("Configuration +designsetup du dashboard chargée.")
