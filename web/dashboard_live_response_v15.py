"""Request-time authority for the browser-visible SentriX dashboard.

V9-V14 proved that mutating ``dashboard.INDEX_HTML`` during startup is not enough evidence
that the same bytes are returned by the live ``/app`` route. V15 wraps the handler that is
actually registered by aiohttp, patches the HTML response itself, and records exactly what
was sent. The native V2 NAV/render switch is extended directly; no late DOM overlay is
required for the new pages or the V96 CAPTCHA label.
"""
from __future__ import annotations

import logging
from aiohttp import web

logger = logging.getLogger("bot.dashboard-live-response-v15")

BUILD = "v15-live-response"
MARKER = "__sentrixLiveResponseV15"

_NATIVE_JS = r'''
function v15Empty(msg){return `<div class="empty">${esc(msg)}</div>`}
function v15Rows(items,fn){return items.length?items.map(fn).join(''):v15Empty('Aucune donnée disponible.')}
async function renderStatsV15(){const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/growth/stats`);$('content').innerHTML=`<div class="grid">${card('Statistiques SentriX','Données réelles du serveur.',`<div class="metrics" style="margin:0"><div class="metric"><small>Membres</small><strong>${number(d.members)}</strong></div><div class="metric"><small>Salons</small><strong>${number(d.channels)}</strong></div><div class="metric"><small>Rôles</small><strong>${number(d.roles)}</strong></div><div class="metric"><small>Actions staff 24 h</small><strong>${number(d.staff_actions_24h)}</strong></div></div>`,'full')}${card('Structure Discord','Inventaire en temps réel.',`<div class="list"><div class="row"><div class="row-main"><b>Salons texte</b></div><strong>${number(d.text_channels)}</strong></div><div class="row"><div class="row-main"><b>Salons vocaux</b></div><strong>${number(d.voice_channels)}</strong></div><div class="row"><div class="row-main"><b>Catégories</b></div><strong>${number(d.categories)}</strong></div></div>`)}${card('État du bot','Connexion actuelle.',`<div class="list"><div class="row"><div class="row-main"><b>Discord</b><small>${d.discord_ready?'Gateway connecté':'Gateway indisponible'}</small></div><span class="badge ${d.discord_ready?'ok':'bad'}">${d.discord_ready?'EN LIGNE':'HORS LIGNE'}</span></div><div class="row"><div class="row-main"><b>Latence</b></div><strong>${d.latency_ms==null?'—':d.latency_ms+' ms'}</strong></div></div>`)}</div>`}
async function renderInvitesV15(){const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/growth/invitations`);$('content').innerHTML=`<div class="grid">${card('Invitations Discord',`${number(d.items.length)} lien(s) · ${number(d.total_uses)} utilisation(s).`,`<div class="list">${v15Rows(d.items,i=>`<div class="row"><div class="row-main"><b>${esc(i.code)}</b><small>#${esc(i.channel_name||'inconnu')} · créé par ${esc(i.inviter_name||'inconnu')}</small></div><strong>${number(i.uses)} utilisation(s)</strong></div>`)}</div>`,'full')}</div>`}
let v15EmojiDraft=[];
function v15DrawEmoji(){const box=$('v15EmojiList');if(box)box.innerHTML=v15EmojiDraft.length?v15EmojiDraft.map((x,i)=>`<button class="btn" data-v15-rm="${i}">${esc(x)} ×</button>`).join(''):'<span class="hint">Aucun emoji choisi.</span>'}
function v15ReadEmoji(){const el=$('v15EmojiInput');const raw=el?.value.trim()||'';for(const x of raw.split(/[\s,]+/).filter(Boolean)){if(v15EmojiDraft.length>=8)break;if(!v15EmojiDraft.includes(x))v15EmojiDraft.push(x)}if(el)el.value='';v15DrawEmoji()}
async function renderAutoReactV15(){const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/automation/reactions`);$('content').innerHTML=`<div class="grid">${card('Réactions automatiques','Choisis toi-même les emojis ajoutés par SentriX.',`<div class="fields"><div class="field"><label>Salon</label><select id="v15ReactChannel">${channelOptions('')}</select></div><div class="field"><label>Mode</label><select id="v15ReactMode"><option value="all">Tous les messages</option><option value="keyword">Mot-clé</option></select></div><div class="field full"><label>Mot-clé si nécessaire</label><input id="v15ReactKeyword" maxlength="80" placeholder="gg"></div><div class="field full"><label>Emojis choisis — 8 maximum</label><div class="toolbar"><input id="v15EmojiInput" placeholder="❤️ 🔥 👀 ou <:emoji:123...>"><button class="btn" id="v15EmojiAdd">Ajouter</button></div><div class="toolbar" id="v15EmojiList" style="margin-top:8px"></div></div><label class="switch-row field full"><span class="switch-copy"><b>Ignorer les bots</b><span>Évite les boucles de réactions.</span></span><input class="switch" id="v15IgnoreBots" type="checkbox" checked></label></div><button class="btn primary" id="v15ReactCreate" style="margin-top:12px">Créer la règle</button>`,'full')}<section class="card full"><div class="card-head"><div><h2>Règles configurées</h2><p>${number(d.items.length)} règle(s)</p></div></div><div class="list">${v15Rows(d.items,r=>`<div class="row"><div class="row-main"><b>#${esc(r.channel_name||r.channel_id)}</b><small>${r.mode==='keyword'?'Mot-clé « '+esc(r.keyword)+' »':'Tous les messages'} · ${r.emojis.map(esc).join(' ')}</small></div><div class="row-actions"><label><input class="switch" type="checkbox" data-v15-toggle="${r.id}" ${r.enabled?'checked':''}></label><button class="btn danger" data-v15-delete="${r.id}">Supprimer</button></div></div>`)}</div></section></div>`;v15EmojiDraft=[];v15DrawEmoji();$('v15EmojiAdd').onclick=v15ReadEmoji;$('v15EmojiInput').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();v15ReadEmoji()}};$('v15EmojiList').onclick=e=>{const b=e.target.closest('[data-v15-rm]');if(!b)return;v15EmojiDraft.splice(Number(b.dataset.v15Rm),1);v15DrawEmoji()};$('v15ReactCreate').onclick=async()=>{v15ReadEmoji();if(!$('v15ReactChannel').value)return toast('Choisis un salon.',true);if(!v15EmojiDraft.length)return toast('Choisis au moins un emoji.',true);try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/automation/reactions`,{method:'POST',body:JSON.stringify({action:'create',channel_id:$('v15ReactChannel').value,mode:$('v15ReactMode').value,keyword:$('v15ReactKeyword').value.trim(),emojis:v15EmojiDraft,ignore_bots:$('v15IgnoreBots').checked})});toast('Réaction automatique créée.');await renderAutoReactV15()}catch(e){toast(e.message,true)}};$('content').querySelectorAll('[data-v15-toggle]').forEach(x=>x.onchange=async()=>{try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/automation/reactions`,{method:'POST',body:JSON.stringify({action:'toggle',id:Number(x.dataset.v15Toggle),enabled:x.checked})})}catch(e){x.checked=!x.checked;toast(e.message,true)}});$('content').querySelectorAll('[data-v15-delete]').forEach(x=>x.onclick=async()=>{try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/automation/reactions`,{method:'POST',body:JSON.stringify({action:'delete',id:Number(x.dataset.v15Delete)})});await renderAutoReactV15()}catch(e){toast(e.message,true)}})}
async function v15Ops(){return api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/overview`)}
async function renderAutomationsV15(){const [o,r]=await Promise.all([v15Ops(),api(`/api/guilds/${encodeURIComponent(state.guildId)}/automation/reactions`)]);$('content').innerHTML=`<div class="grid">${card('Automatisations','Centre des règles automatiques SentriX.',`<div class="list"><div class="row"><div class="row-main"><b>Réactions automatiques</b><small>Règles actives sur les messages</small></div><strong>${number(r.items.filter(x=>x.enabled).length)}</strong></div><div class="row"><div class="row-main"><b>Politiques de commandes</b><small>Restrictions par salon</small></div><strong>${number((o.policies||[]).length)}</strong></div><div class="row"><div class="row-main"><b>Maintenance</b></div><span class="badge ${o.maintenance?.enabled?'warn':'ok'}">${o.maintenance?.enabled?'ACTIVE':'NORMALE'}</span></div></div><button class="btn" id="v15GoReact" style="margin-top:10px">Configurer les réactions</button>`,'full')}</div>`;$('v15GoReact').onclick=()=>go('autoreact')}
async function renderStaffV15(){const o=await v15Ops(),rows=o.staff||[];$('content').innerHTML=`<div class="grid">${card('Activité staff','Actions enregistrées durant les dernières 24 heures.',`<div class="list">${v15Rows(rows,(s,i)=>`<div class="row"><div class="row-main"><b>#${i+1} · ${esc(s.username||s.user_id)}</b><small>Activité SentriX</small></div><strong>${number(s.actions)} action(s)</strong></div>`)}</div>`,'full')}</div>`}
async function renderAuditV15(){const o=await v15Ops(),rows=o.history||[];$('content').innerHTML=`<div class="grid">${card('Historique & audit','Versions de configuration enregistrées.',`<div class="list">${v15Rows(rows,h=>`<div class="row"><div class="row-main"><b>${esc((h.changed_keys||[]).join(', ')||'Configuration')}</b><small>${h.created_at?new Date(Number(h.created_at)*1000).toLocaleString('fr-FR'):'—'} · ${esc(h.username||h.user_id||'utilisateur')}</small></div><button class="btn" data-v15-rollback="${h.id}">Restaurer</button></div>`)}</div>`,'full')}</div>`;$('content').querySelectorAll('[data-v15-rollback]').forEach(b=>b.onclick=async()=>{if(!confirm('Restaurer cette version ?'))return;try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/history/${b.dataset.v15Rollback}/rollback`,{method:'POST',body:'{}'});toast('Configuration restaurée.');await selectGuild(state.guildId)}catch(e){toast(e.message,true)}})}
async function renderBackupsV15(){$('content').innerHTML=`<div class="grid">${card('Sauvegardes','Export et import de la configuration réelle.',`<div class="toolbar"><button class="btn primary" id="v15Export">Exporter</button><button class="btn" id="v15Import">Importer</button></div><div class="field" style="margin-top:10px"><label>Configuration JSON</label><textarea id="v15Json" style="min-height:280px" placeholder="L’export apparaîtra ici."></textarea></div>`,'full')}</div>`;$('v15Export').onclick=async()=>{try{const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/export`);$('v15Json').value=JSON.stringify(d.config,null,2);toast('Export généré.')}catch(e){toast(e.message,true)}};$('v15Import').onclick=async()=>{let cfg;try{cfg=JSON.parse($('v15Json').value)}catch(_){return toast('JSON invalide.',true)}if(!confirm('Importer cette configuration ?'))return;try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/import`,{method:'POST',body:JSON.stringify(cfg)});toast('Configuration importée.');await selectGuild(state.guildId)}catch(e){toast(e.message,true)}}}
async function renderMaintenanceV15(){const o=await v15Ops(),m=o.maintenance||{};$('content').innerHTML=`<div class="grid">${card('Mode maintenance','Coupe les commandes concernées sans arrêter SentriX.',`<div class="field"><label>Raison</label><input id="v15MaintenanceReason" maxlength="180" value="${esc(m.reason||'')}"></div><div class="toolbar" style="margin-top:10px"><button id="v15Maintenance" class="btn ${m.enabled?'danger':'primary'}">${m.enabled?'Désactiver':'Activer'} la maintenance</button><span class="badge ${m.enabled?'warn':'ok'}">${m.enabled?'ACTIVE':'MODE NORMAL'}</span></div>`,'full')}</div>`;$('v15Maintenance').onclick=async()=>{try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/maintenance`,{method:'POST',body:JSON.stringify({enabled:!m.enabled,reason:$('v15MaintenanceReason').value})});await renderMaintenanceV15()}catch(e){toast(e.message,true)}}}
async function renderIntegrationsV15(){const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/growth/webhooks`);$('content').innerHTML=`<div class="grid">${card('Webhooks & intégrations','Inventaire Discord sans exposer les tokens.',`<div class="list">${v15Rows(d.items,w=>`<div class="row"><div class="row-main"><b>${esc(w.name||'Webhook')}</b><small>#${esc(w.channel_name||'inconnu')} · ${esc(w.type||'webhook')}</small></div><span class="badge blue">${esc(w.id)}</span></div>`)}</div>`,'full')}</div>`}
'''


def _patch_native(html: str) -> str:
    if MARKER in html:
        return html
    tag = '<script id="sentrix-dashboard-unified-v2">'
    start = html.find(tag)
    if start < 0:
        return html
    body_start = start + len(tag)
    end = html.find("</script>", body_start)
    if end < 0:
        return html
    body = html[body_start:end]

    # Native navigation: these replacements target the original V2 array itself.
    body = body.replace('["levels","Niveaux","NV"]', '["levels","Niveaux","NV"],["stats","Statistiques","ST"]', 1)
    body = body.replace('["notifications","Notifications","NO"]', '["notifications","Notifications","NO"],["invites","Invitations","IN"],["autoreact","Réactions automatiques","RA"]', 1)
    body = body.replace('["embeds","Embeds & design","EM"]', '["embeds","Embeds & design","EM"],["automations","Automatisations","AU"]', 1)
    body = body.replace('["diagnostic","Diagnostic","DG"]', '["diagnostic","Diagnostic","DG"],["staffactivity","Activité staff","AS"],["audit","Historique & audit","HA"],["backups","Sauvegardes","SV"],["maintenance","Maintenance","MT"],["integrations","Webhooks & intégrations","WI"]', 1)

    meta_needle = "diagnostic:[\"Diagnostic\",\"Permissions, ressources cassées et état des modules.\"],"
    meta_extra = meta_needle + 'stats:["Statistiques","Activité et santé réelle du serveur."],invites:["Invitations","Liens Discord actifs et utilisations."],autoreact:["Réactions automatiques","Choisis les emojis ajoutés automatiquement."],automations:["Automatisations","Règles automatiques SentriX."],staffactivity:["Activité staff","Actions staff des dernières 24 heures."],audit:["Historique & audit","Versions de configuration et rollback."],backups:["Sauvegardes","Import et export JSON de la configuration."],maintenance:["Maintenance","Contrôle opérationnel du serveur."],integrations:["Webhooks & intégrations","Webhooks Discord accessibles à SentriX."],'
    body = body.replace(meta_needle, meta_extra, 1)

    # V96 is rendered by the native verification page, not by a decorative overlay.
    body = body.replace('<b>CAPTCHA</b><span>Demande le code visuel avant d’attribuer le rôle.</span>', '<b>CAPTCHA V96 RÉEL</b><span>Le membre doit résoudre le code visuel avant que SentriX attribue le rôle.</span>', 1)
    body = body.replace("card('Règlement & vérification','Écrivez le texte exact présenté aux membres.'", "card('Vérification Discord réelle · CAPTCHA V96','Écrivez le règlement puis publiez le vrai panneau Discord.'", 1)
    body = body.replace('>Enregistrer et publier</button>', '>Enregistrer et publier sur Discord</button>', 1)

    render_needle = "async function render(force=false){"
    if render_needle in body:
        body = body.replace(render_needle, f"window.{MARKER}=true;\n" + _NATIVE_JS + "\n" + render_needle, 1)
    switch_needle = "case'diagnostic':await renderDiagnostic();break;default:await renderOverview()"
    switch_extra = "case'diagnostic':await renderDiagnostic();break;case'stats':await renderStatsV15();break;case'invites':await renderInvitesV15();break;case'autoreact':await renderAutoReactV15();break;case'automations':await renderAutomationsV15();break;case'staffactivity':await renderStaffV15();break;case'audit':await renderAuditV15();break;case'backups':await renderBackupsV15();break;case'maintenance':await renderMaintenanceV15();break;case'integrations':await renderIntegrationsV15();break;default:await renderOverview()"
    body = body.replace(switch_needle, switch_extra, 1)

    html = html[:body_start] + body + html[end:]
    if 'name="sentrix-dashboard-build"' not in html:
        html = html.replace("</head>", f'<meta name="sentrix-dashboard-build" content="{BUILD}">\n</head>', 1)
    return html


def patch_html(html: str) -> str:
    return _patch_native(str(html or ""))


def install(dashboard) -> bool:
    previous = dashboard.handle_index
    if getattr(previous, "_sentrix_live_response_v15", False):
        return True

    async def live_index(request: web.Request):
        response = await previous(request)
        if request.path != "/app" or not isinstance(response, web.Response) or response.status >= 300:
            return response
        source = response.text if isinstance(response.text, str) else str(getattr(dashboard, "INDEX_HTML", "") or "")
        html = patch_html(source)
        has_nav = all(x in html for x in ("Réactions automatiques", "Statistiques", "Webhooks & intégrations"))
        has_captcha = "CAPTCHA V96 RÉEL" in html
        has_marker = MARKER in html
        headers = dict(response.headers)
        for key in ("Content-Type", "Content-Length"):
            headers.pop(key, None)
        headers.update({
            "Cache-Control": "private, no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-SentriX-Dashboard-Build": BUILD,
            "X-SentriX-Dashboard-Nav": "1" if has_nav else "0",
            "X-SentriX-Dashboard-Captcha": "1" if has_captcha else "0",
        })
        logger.warning(
            "SERVE /app %s bytes=%s native_marker=%s nav=%s captcha=%s source_bytes=%s",
            BUILD, len(html.encode("utf-8")), has_marker, has_nav, has_captcha,
            len(source.encode("utf-8")),
        )
        return web.Response(text=html, status=response.status, content_type="text/html", headers=headers)

    live_index._sentrix_live_response_v15 = True
    live_index._sentrix_previous_handler = previous
    dashboard.handle_index = live_index
    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
    ok = MARKER in dashboard.INDEX_HTML and "CAPTCHA V96 RÉEL" in dashboard.INDEX_HTML and "Réactions automatiques" in dashboard.INDEX_HTML
    logger.warning("Dashboard Live Response V15 installed=%s: /app response-time native authority armed.", ok)
    return ok


__all__ = ["install", "patch_html", "BUILD", "MARKER"]
