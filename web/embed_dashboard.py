"""Extension du dashboard SentriX : créateur d'embeds Discord."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard.embeds")
_INSTALLED = False


def _valid_https_url(value: str) -> bool:
    if not value:
        return True
    try:
        parsed = urlparse(value.strip())
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and len(value) <= 2048
    )


def _clean_text(payload: dict, key: str, maximum: int) -> tuple[str, str | None]:
    value = str(payload.get(key) or "").strip()
    if len(value) > maximum:
        return "", f"Le champ {key} ne peut pas dépasser {maximum} caractères."
    return value, None


async def handle_send_embed(request: web.Request) -> web.Response:
    dashboard = request.app["dashboard_module"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return dashboard._json_error("Identifiant de serveur invalide.", 400)

    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return error
    csrf_error = dashboard._require_csrf(request, session)
    if csrf_error:
        return csrf_error

    rate_key = (request.cookies.get(dashboard.SESSION_COOKIE), guild_id, "embed-send")
    if time.time() - request.app["write_limits"].get(rate_key, 0) < 2:
        return dashboard._json_error("Attendez un instant avant d'envoyer un autre embed.", 429)

    try:
        payload = await request.json()
    except Exception:
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
    if not isinstance(payload, dict):
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

    try:
        channel_id = int(payload.get("channel_id"))
    except (TypeError, ValueError):
        return dashboard._json_error("Choisissez un salon textuel.", 400)
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return dashboard._json_error("Le salon choisi n'est pas un salon textuel de ce serveur.", 400)

    bot_member = guild.me
    if bot_member is None:
        return dashboard._json_error("SentriX n'est pas disponible sur ce serveur.", 503)
    permissions = channel.permissions_for(bot_member)
    if not permissions.send_messages or not permissions.embed_links:
        return dashboard._json_error(
            "SentriX doit avoir les permissions Envoyer des messages et Intégrer des liens dans ce salon.",
            403,
        )

    limits = {
        "content": 2000,
        "title": 256,
        "description": 4096,
        "url": 2048,
        "author_name": 256,
        "author_url": 2048,
        "author_icon_url": 2048,
        "footer_text": 2048,
        "footer_icon_url": 2048,
        "image_url": 2048,
        "thumbnail_url": 2048,
    }
    clean: dict[str, str] = {}
    for key, maximum in limits.items():
        clean[key], text_error = _clean_text(payload, key, maximum)
        if text_error:
            return dashboard._json_error(text_error, 400)

    for key in (
        "url", "author_url", "author_icon_url", "footer_icon_url",
        "image_url", "thumbnail_url",
    ):
        if clean[key] and not _valid_https_url(clean[key]):
            return dashboard._json_error(f"Le champ {key} doit être une URL HTTPS valide.", 400)

    colour_value = str(payload.get("color") or "#5865F2").strip()
    if colour_value.startswith("#"):
        colour_value = colour_value[1:]
    if len(colour_value) != 6:
        return dashboard._json_error("La couleur doit être au format #RRGGBB.", 400)
    try:
        colour = int(colour_value, 16)
    except ValueError:
        return dashboard._json_error("La couleur doit être au format #RRGGBB.", 400)

    raw_fields = payload.get("fields", [])
    if raw_fields is None:
        raw_fields = []
    if not isinstance(raw_fields, list) or len(raw_fields) > 25:
        return dashboard._json_error("Un embed peut contenir au maximum 25 champs.", 400)

    fields: list[tuple[str, str, bool]] = []
    total_characters = len(clean["title"]) + len(clean["description"]) + len(clean["footer_text"]) + len(clean["author_name"])
    for index, field in enumerate(raw_fields, start=1):
        if not isinstance(field, dict):
            return dashboard._json_error(f"Le champ #{index} est invalide.", 400)
        name = str(field.get("name") or "").strip()
        value = str(field.get("value") or "").strip()
        if not name and not value:
            continue
        if not name or not value:
            return dashboard._json_error(f"Le champ #{index} doit avoir un nom et un contenu.", 400)
        if len(name) > 256 or len(value) > 1024:
            return dashboard._json_error(
                f"Le champ #{index} dépasse la limite Discord (256 caractères pour le nom, 1 024 pour le contenu).",
                400,
            )
        fields.append((name, value, bool(field.get("inline"))))
        total_characters += len(name) + len(value)

    if total_characters > 6000:
        return dashboard._json_error("L'embed dépasse la limite totale de 6 000 caractères.", 400)
    if not any((clean["content"], clean["title"], clean["description"], clean["image_url"], fields)):
        return dashboard._json_error("Ajoutez au moins un titre, une description, une image, un champ ou un message.", 400)

    timestamp = datetime.now(timezone.utc) if bool(payload.get("timestamp")) else None
    embed = discord.Embed(
        title=clean["title"] or None,
        description=clean["description"] or None,
        colour=discord.Colour(colour),
        url=clean["url"] or None,
        timestamp=timestamp,
    )
    if clean["author_name"]:
        embed.set_author(
            name=clean["author_name"],
            url=clean["author_url"] or None,
            icon_url=clean["author_icon_url"] or None,
        )
    if clean["footer_text"] or clean["footer_icon_url"]:
        embed.set_footer(
            text=clean["footer_text"] or " ",
            icon_url=clean["footer_icon_url"] or None,
        )
    if clean["image_url"]:
        embed.set_image(url=clean["image_url"])
    if clean["thumbnail_url"]:
        embed.set_thumbnail(url=clean["thumbnail_url"])
    for name, value, inline in fields:
        embed.add_field(name=name, value=value, inline=inline)

    try:
        message = await channel.send(
            content=clean["content"] or None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.Forbidden:
        return dashboard._json_error("Discord a refusé l'envoi. Vérifiez les permissions de SentriX.", 403)
    except discord.HTTPException:
        logger.exception("Envoi d'embed impossible depuis le dashboard.")
        return dashboard._json_error("Discord n'a pas pu envoyer cet embed. Vérifiez les URLs et réessayez.", 502)

    request.app["write_limits"][rate_key] = time.time()
    logger.info(
        "Dashboard : %s (%s) a envoyé l'embed %s dans #%s (%s) sur %s (%s).",
        session["user"]["username"], session["user"]["id"], message.id,
        channel.name, channel.id, guild.name, guild.id,
    )
    return web.json_response({
        "ok": True,
        "message": f"Embed envoyé dans #{channel.name}.",
        "message_id": str(message.id),
        "message_url": f"https://discord.com/channels/{guild.id}/{channel.id}/{message.id}",
    })


EMBED_CSS = r"""
    .embed-builder{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1.05fr) minmax(320px,.95fr);gap:20px;width:100%}.embed-editor{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-content:start}.embed-editor .full{grid-column:1/-1}.embed-preview-wrap{position:sticky;top:24px;align-self:start}.embed-preview-title{font-size:12px;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:9px}.discord-preview{background:#313338;border-radius:10px;padding:18px;color:#f2f3f5;min-height:180px}.discord-message{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 10px;color:#dbdee1}.discord-embed{position:relative;background:#2b2d31;border-radius:4px;padding:14px 16px 14px 18px;overflow:hidden;box-shadow:0 1px 2px #0005}.discord-embed:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--embed-colour,#5865f2)}.embed-author{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;margin-bottom:8px}.embed-author img,.embed-footer img{width:22px;height:22px;border-radius:50%;object-fit:cover}.embed-title{font-weight:700;margin-bottom:8px;overflow-wrap:anywhere}.embed-description{line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere;color:#dbdee1}.embed-thumbnail{float:right;width:80px;height:80px;object-fit:cover;border-radius:4px;margin-left:16px}.embed-image{display:block;max-width:100%;max-height:320px;border-radius:4px;margin-top:14px;object-fit:contain}.embed-preview-fields{display:grid;grid-template-columns:repeat(12,1fr);gap:10px;margin-top:12px}.embed-preview-field{grid-column:span 12;min-width:0}.embed-preview-field.inline{grid-column:span 4}.embed-preview-field b,.embed-preview-field span{display:block;overflow-wrap:anywhere}.embed-preview-field span{color:#dbdee1;white-space:pre-wrap;margin-top:3px;line-height:1.35}.embed-footer{display:flex;align-items:center;gap:7px;color:#b5bac1;font-size:12px;margin-top:12px}.embed-fields-list{display:grid;gap:10px}.embed-field-row{display:grid;grid-template-columns:1fr 1.4fr auto;gap:8px;padding:11px;background:#0d111c;border:1px solid #222940;border-radius:12px}.embed-inline{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;white-space:nowrap}.embed-inline input{width:auto}.embed-field-actions{display:flex;align-items:center;gap:8px;grid-column:1/-1}.embed-field-actions .btn{padding:8px 11px}.colour-row{display:grid;grid-template-columns:54px 1fr;gap:8px}.colour-row input[type=color]{height:44px;padding:4px}.embed-result{grid-column:1/-1;padding:12px 14px;border:1px solid #284d43;background:#13352d;border-radius:11px;color:#8be4c3}.embed-result a{text-decoration:underline;font-weight:800}
    @media(max-width:980px){.embed-builder{grid-template-columns:1fr}.embed-preview-wrap{position:relative;top:auto}.embed-preview-field.inline{grid-column:span 6}}
    @media(max-width:620px){.embed-editor{grid-template-columns:1fr}.embed-editor .full{grid-column:auto}.embed-field-row{grid-template-columns:1fr}.embed-preview-field.inline{grid-column:span 12}}
"""


EMBED_JS = r"""
    function embedText(value){return esc(value||"").replace(/\n/g,"<br>");}
    function renderEmbeds(){
      const textChannels=state.guildData.channels.filter(c=>["text","news"].includes(c.type));
      const channelOptions='<option value="">Choisissez un salon</option>'+textChannels.map(c=>`<option value="${esc(c.id)}">#${esc(c.name)}</option>`).join("");
      $("fields").innerHTML=`<div class="embed-builder"><div class="embed-editor">
        <div class="field full"><label>Salon d'envoi</label><select class="select" id="embedChannel">${channelOptions}</select></div>
        <div class="field full"><label>Message au-dessus de l'embed (facultatif)</label><textarea id="embedContent" maxlength="2000" placeholder="Texte normal envoyé avec l'embed"></textarea><div class="hint">Les mentions sont affichées mais ne déclenchent aucun ping depuis le dashboard.</div></div>
        <div class="field"><label>Titre</label><input id="embedTitle" maxlength="256" placeholder="Titre de l'embed"></div>
        <div class="field"><label>Lien du titre (facultatif)</label><input id="embedUrl" type="url" placeholder="https://..."></div>
        <div class="field full"><label>Description</label><textarea id="embedDescription" maxlength="4096" placeholder="Écrivez le contenu de votre embed..."></textarea></div>
        <div class="field"><label>Couleur</label><div class="colour-row"><input id="embedColorPicker" type="color" value="#5865f2"><input id="embedColor" value="#5865F2" maxlength="7"></div></div>
        <div class="field"><label>Miniature (facultative)</label><input id="embedThumbnail" type="url" placeholder="https://.../image.png"></div>
        <div class="field full"><label>Grande image ou GIF (facultatif)</label><input id="embedImage" type="url" placeholder="https://.../image.png"></div>
        <div class="field"><label>Nom de l'auteur (facultatif)</label><input id="embedAuthorName" maxlength="256"></div>
        <div class="field"><label>Icône de l'auteur (facultative)</label><input id="embedAuthorIcon" type="url" placeholder="https://..."></div>
        <div class="field full"><label>Lien de l'auteur (facultatif)</label><input id="embedAuthorUrl" type="url" placeholder="https://..."></div>
        <div class="field"><label>Footer (facultatif)</label><input id="embedFooter" maxlength="2048"></div>
        <div class="field"><label>Icône du footer (facultative)</label><input id="embedFooterIcon" type="url" placeholder="https://..."></div>
        <label class="switch full"><div><b>Afficher la date et l'heure</b><span>Ajoute l'heure exacte de l'envoi dans le footer Discord.</span></div><input id="embedTimestamp" type="checkbox"></label>
        <div class="field full"><label>Champs de l'embed</label><div id="embedFieldsList" class="embed-fields-list"></div><button class="btn" id="addEmbedField" type="button">+ Ajouter un champ</button><div class="hint">Maximum 25 champs. Le mode « côte à côte » place jusqu'à trois champs sur une ligne.</div></div>
        <div id="embedResult" class="embed-result hidden"></div>
      </div><div class="embed-preview-wrap"><div class="embed-preview-title">Aperçu Discord en direct</div><div class="discord-preview"><div id="previewContent" class="discord-message hidden"></div><div id="previewEmbed" class="discord-embed"><img id="previewThumbnail" class="embed-thumbnail hidden" alt=""><div id="previewAuthor" class="embed-author hidden"></div><div id="previewTitle" class="embed-title">Votre titre</div><div id="previewDescription" class="embed-description">Votre description apparaîtra ici.</div><div id="previewFields" class="embed-preview-fields"></div><img id="previewImage" class="embed-image hidden" alt=""><div id="previewFooter" class="embed-footer hidden"></div></div></div></div></div>`;
      $("addEmbedField").addEventListener("click",()=>addEmbedField());
      $("embedColorPicker").addEventListener("input",e=>{$("embedColor").value=e.target.value.toUpperCase();updateEmbedPreview();});
      $("embedColor").addEventListener("input",e=>{if(/^#[0-9a-f]{6}$/i.test(e.target.value))$("embedColorPicker").value=e.target.value;updateEmbedPreview();});
      $("fields").querySelectorAll("input,textarea,select").forEach(el=>el.addEventListener("input",updateEmbedPreview));
      addEmbedField(false);
      updateEmbedPreview();
    }
    function addEmbedField(focus=true){
      const list=$("embedFieldsList");if(!list||list.children.length>=25){toast("Un embed ne peut pas dépasser 25 champs.",true);return;}
      const row=document.createElement("div");row.className="embed-field-row";row.innerHTML=`<input class="embedFieldName" maxlength="256" placeholder="Nom du champ"><textarea class="embedFieldValue" maxlength="1024" placeholder="Contenu du champ"></textarea><button class="btn danger embedFieldDelete" type="button">Supprimer</button><div class="embed-field-actions"><label class="embed-inline"><input class="embedFieldInline" type="checkbox"> Côte à côte</label></div>`;
      row.querySelector(".embedFieldDelete").addEventListener("click",()=>{row.remove();updateEmbedPreview();});
      row.querySelectorAll("input,textarea").forEach(el=>el.addEventListener("input",updateEmbedPreview));list.appendChild(row);if(focus)row.querySelector("input").focus();
    }
    function embedFieldValues(){return [...document.querySelectorAll(".embed-field-row")].map(row=>({name:row.querySelector(".embedFieldName").value.trim(),value:row.querySelector(".embedFieldValue").value.trim(),inline:row.querySelector(".embedFieldInline").checked})).filter(field=>field.name||field.value);}
    function safePreviewImage(elementId,url){const el=$(elementId);if(/^https:\/\//i.test(url||"")){el.src=url;el.classList.remove("hidden");el.onerror=()=>el.classList.add("hidden");}else{el.removeAttribute("src");el.classList.add("hidden");}}
    function updateEmbedPreview(){
      const content=$("embedContent")?.value||"",title=$("embedTitle")?.value||"",description=$("embedDescription")?.value||"",author=$("embedAuthorName")?.value||"",authorIcon=$("embedAuthorIcon")?.value||"",footer=$("embedFooter")?.value||"",footerIcon=$("embedFooterIcon")?.value||"",colour=$("embedColor")?.value||"#5865F2";
      $("previewEmbed").style.setProperty("--embed-colour",/^#[0-9a-f]{6}$/i.test(colour)?colour:"#5865F2");$("previewContent").innerHTML=embedText(content);$("previewContent").classList.toggle("hidden",!content);$("previewTitle").innerHTML=embedText(title||"Votre titre");$("previewDescription").innerHTML=embedText(description||"Votre description apparaîtra ici.");
      if(author){$("previewAuthor").innerHTML=`${/^https:\/\//i.test(authorIcon)?`<img src="${esc(authorIcon)}" alt="">`:""}<span>${embedText(author)}</span>`;$("previewAuthor").classList.remove("hidden");}else $("previewAuthor").classList.add("hidden");
      const fields=embedFieldValues();$("previewFields").innerHTML=fields.map(field=>`<div class="embed-preview-field${field.inline?" inline":""}"><b>${embedText(field.name||"Nom du champ")}</b><span>${embedText(field.value||"Contenu du champ")}</span></div>`).join("");
      const footerParts=[];if(/^https:\/\//i.test(footerIcon))footerParts.push(`<img src="${esc(footerIcon)}" alt="">`);if(footer)footerParts.push(`<span>${embedText(footer)}</span>`);if($("embedTimestamp")?.checked)footerParts.push(`<span>${footer?"• ":""}Aujourd'hui à ${new Date().toLocaleTimeString("fr-FR",{hour:"2-digit",minute:"2-digit"})}</span>`);$("previewFooter").innerHTML=footerParts.join("");$("previewFooter").classList.toggle("hidden",!footerParts.length);safePreviewImage("previewThumbnail",$("embedThumbnail")?.value);safePreviewImage("previewImage",$("embedImage")?.value);
      state.dirty=true;$("saveStatus").textContent="Embed prêt à être envoyé";
    }
    function collectEmbedPayload(){return {channel_id:$("embedChannel").value,content:$("embedContent").value,title:$("embedTitle").value,description:$("embedDescription").value,color:$("embedColor").value,url:$("embedUrl").value,author_name:$("embedAuthorName").value,author_url:$("embedAuthorUrl").value,author_icon_url:$("embedAuthorIcon").value,footer_text:$("embedFooter").value,footer_icon_url:$("embedFooterIcon").value,image_url:$("embedImage").value,thumbnail_url:$("embedThumbnail").value,timestamp:$("embedTimestamp").checked,fields:embedFieldValues()};}
    async function sendEmbed(){
      const payload=collectEmbedPayload();if(!payload.channel_id){toast("Choisissez le salon où envoyer l'embed.",true);return;}$("settingsForm").classList.add("loading");try{const result=await json(`/api/guilds/${state.guildId}/embeds`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(payload)});toast(result.message);state.dirty=false;$("saveStatus").textContent="Embed envoyé";const box=$("embedResult");box.innerHTML=`Embed envoyé avec succès. <a href="${esc(result.message_url)}" target="_blank" rel="noopener">Voir le message sur Discord</a>`;box.classList.remove("hidden");}catch(e){toast(e.message,true);$("saveStatus").textContent="Envoi impossible";}finally{$("settingsForm").classList.remove("loading");}
    }
"""


def _replace_once(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        logger.warning("Dashboard embeds : point d'insertion introuvable (%s).", label)
        return html
    return html.replace(old, new, 1)


def _patch_html(html: str) -> str:
    html = _replace_once(
        html,
        "    .sanction-more{justify-self:center}\n",
        "    .sanction-more{justify-self:center}\n" + EMBED_CSS,
        "css",
    )
    html = _replace_once(
        html,
        '        <button data-tab="notifications">Notifications</button>\n',
        '        <button data-tab="notifications">Notifications</button>\n        <button data-tab="embeds">Embeds</button>\n',
        "navigation",
    )
    html = _replace_once(
        html,
        '      notifications:{title:"Notifications sociales",description:"Publiez automatiquement les nouveautés de vos créateurs préférés dans Discord.",notifications:true,fields:[]},\n',
        '''      notifications:{title:"Notifications sociales",description:"Publiez automatiquement les nouveautés de vos créateurs préférés dans Discord.",notifications:true,fields:[]},\n      embeds:{title:"Créateur d'embed",description:"Créez un message professionnel, prévisualisez-le puis envoyez-le dans un salon Discord.",embeds:true,fields:[]},\n''',
        "tab",
    )
    html = _replace_once(
        html,
        "    function renderTab(){",
        EMBED_JS + "\n    function renderTab(){",
        "javascript",
    )
    old_render = '    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else $("fields").innerHTML=tab.fields.map(fieldHTML).join("");$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));$("saveButton").textContent=tab.notifications?"Ajouter la notification":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions)return;state.dirty=true;$("saveStatus").textContent="Modifications non enregistrées";}));}\n'
    new_render = '''    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else if(tab.embeds)renderEmbeds();else $("fields").innerHTML=tab.fields.map(fieldHTML).join("");$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));$("saveButton").textContent=tab.notifications?"Ajouter la notification":tab.embeds?"Envoyer l'embed":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":tab.embeds?"Aperçu en direct":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions)return;state.dirty=true;if(!tab.embeds)$("saveStatus").textContent="Modifications non enregistrées";}));}\n'''
    html = _replace_once(html, old_render, new_render, "renderTab")
    old_save = '    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}const values={};'
    new_save = '    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}if(tab.embeds){await sendEmbed();return;}const values={};'
    html = _replace_once(html, old_save, new_save, "save")
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    dashboard.INDEX_HTML = _patch_html(dashboard.INDEX_HTML)

    original_security_headers = dashboard.security_headers

    @web.middleware
    async def security_headers(request: web.Request, handler):
        response = await original_security_headers(request, handler)
        csp = response.headers.get("Content-Security-Policy", "")
        response.headers["Content-Security-Policy"] = csp.replace(
            "img-src 'self' https://cdn.discordapp.com data:",
            "img-src 'self' https: data:",
        )
        return response

    dashboard.security_headers = security_headers
    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_post("/api/guilds/{guild_id}/embeds", handle_send_embed)
        return app

    dashboard.build_app = build_app
    logger.info("Extension dashboard Embeds chargée.")
