"""Explications détaillées et recherche globale des salons du dashboard principal."""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.help-search")
_INSTALLED = False


DASHBOARD_HELP_UI = r"""
<style>
  .dashboard-guide{
    grid-column:1/-1;
    padding:16px 17px;
    border:1px solid #35405f;
    border-left:4px solid var(--brand);
    border-radius:14px;
    background:linear-gradient(135deg,#151a2a,#0e1320);
  }
  .dashboard-guide h3{margin:0 0 7px;font-size:16px}
  .dashboard-guide p{margin:0;color:var(--muted);line-height:1.55}
  .dashboard-guide ul{margin:10px 0 0;padding-left:19px;color:#cbd1e3;line-height:1.55}
  .dashboard-guide .guide-warning{
    margin-top:11px;padding:9px 11px;border-radius:9px;
    border:1px solid #5b4f2c;background:#2b2413;color:#f3d68d;font-size:12px;
  }
  .dashboard-extra-hint{
    margin-top:7px;color:#aeb7cf;font-size:12px;line-height:1.5;
    padding:8px 9px;border-radius:9px;background:#0d111c;border:1px dashed #303950;
  }
  .dashboard-channel-search{position:relative;margin:0 0 8px}
  .dashboard-channel-search input{padding-left:38px}
  .dashboard-channel-search::before{
    content:"⌕";position:absolute;left:13px;top:50%;transform:translateY(-50%);
    color:var(--muted);font-size:18px;pointer-events:none;
  }
  .dashboard-channel-search-status{margin:5px 0 8px;color:var(--muted);font-size:12px;min-height:17px}
  .dashboard-channel-search-status.exact{color:var(--ok);font-weight:800}
</style>
<script>
(() => {
  const guides = {
    general:{title:"Réglages généraux du serveur",text:"Ces options contrôlent le fonctionnement de base de SentriX.",items:["Le préfixe sert aux commandes écrites comme +help.","Le niveau de sécurité ajuste la sévérité générale des protections.","Le seuil d’avertissements peut déclencher automatiquement un bannissement."],warning:"Cliquez sur Enregistrer après chaque modification. Les changements non enregistrés sont perdus en quittant l’onglet."},
    security:{title:"Sécurité et AutoMod",text:"Activez seulement les protections utiles à votre serveur, puis testez-les dans un salon privé.",items:["Anti-spam et anti-mentions limitent les abus de messages.","Anti-lien, anti-invitation et anti-arnaque contrôlent les contenus dangereux.","Anti-raid et anti-nuke demandent au bot des permissions suffisantes et un rôle bien placé."],warning:"Placez le rôle SentriX au-dessus des rôles qu’il doit sanctionner. Les exemptions se règlent dans le Centre Setup."},
    sanctions:{title:"Historique des sanctions",text:"Cette page affiche les bannissements, mutes et avertissements enregistrés par SentriX.",items:["Utilisez la recherche par ID Discord pour retrouver un membre précis.","Les actions de retrait sont immédiatement appliquées au serveur.","Une raison claire est recommandée pour conserver un historique compréhensible."],warning:"Vérifiez toujours l’ID du membre avant un déban, un démute ou une suppression d’avertissements."},
    logs:{title:"Configuration des logs",text:"Chaque événement peut être envoyé dans un salon différent pour garder les journaux lisibles.",items:["Messages : suppressions et modifications de messages.","Membres, rôles, vocal et serveur : changements administratifs correspondants.","Le salon général sert de solution de secours si une catégorie spécialisée n’est pas configurée."],warning:"Les salons de logs doivent être privés et SentriX doit pouvoir y voir et envoyer des messages."},
    welcome:{title:"Accueil des membres",text:"Personnalisez l’arrivée, le départ et le rôle attribué automatiquement.",items:["Les variables comme {member}, {username}, {server} et {member_count} sont remplacées automatiquement.","L’image doit être une URL HTTPS directe vers une image ou un GIF.","Le rôle automatique doit être placé sous le rôle SentriX."],warning:"Testez le message avec un compte secondaire ou dans un serveur de test avant de l’utiliser publiquement."},
    levels:{title:"Niveaux et expérience",text:"Ces réglages contrôlent la vitesse de progression et le salon des annonces.",items:["Un multiplicateur supérieur à 1 accélère la progression.","Le salon de niveaux reçoit les annonces de montée de niveau.","Le message doit rester court pour éviter le spam dans les salons actifs."],warning:"Un multiplicateur très élevé peut déséquilibrer rapidement le classement."},
    tickets:{title:"Tickets de support",text:"Définissez où les tickets sont créés et comment ils sont archivés.",items:["La catégorie regroupe les nouveaux tickets.","Le salon de logs reçoit les ouvertures, fermetures et transcripts.","Le délai avant suppression laisse le temps de lire le message de fermeture."],warning:"SentriX doit pouvoir gérer les salons dans la catégorie choisie."},
    ai:{title:"Intelligence artificielle",text:"Réglez la vitesse, les limites et la mémoire de l’IA SentriX.",items:["Luna est le modèle le plus rapide pour les demandes simples.","Les limites évitent qu’un membre consomme toutes les ressources.","La mémoire conserve temporairement le contexte, séparément par membre et salon."],warning:"La journalisation enregistre les compteurs d’utilisation, pas le contenu des conversations."},
    notifications:{title:"Notifications sociales",text:"Publiez automatiquement les nouvelles vidéos, lives ou publications dans un salon choisi.",items:["Choisissez la plateforme, le lien du créateur et le salon de destination.","Le rôle à mentionner est facultatif.","Utilisez un message clair pour éviter les notifications trompeuses."],warning:"Vérifiez le lien du créateur avant d’activer la notification."},
    roles:{title:"Rôles et salons utilisés par SentriX",text:"Reliez les fonctions du bot aux rôles et salons déjà présents sur votre serveur.",items:["Les rôles de modération déterminent qui peut utiliser certaines commandes.","Les salons choisis servent aux règles, annonces, vérification, suggestions et signalements.","Une option laissée sur Non configuré reste inactive ou utilise le comportement par défaut."],warning:"Le rôle SentriX doit être placé au-dessus des rôles qu’il doit donner, retirer ou gérer."},
    embeds:{title:"Créateur d’embeds",text:"Préparez un message enrichi avec titre, description, image, champs et footer.",items:["Choisissez le salon de destination avec la barre de recherche.","L’aperçu permet de vérifier le rendu avant l’envoi.","Les mentions sont désactivées par défaut pour éviter les pings accidentels."],warning:"Relisez le message et vérifiez les liens avant de publier."}
  };

  const fieldHints = {
    prefix:"Entre 1 et 5 caractères. Évitez un préfixe déjà utilisé par plusieurs autres bots.",
    security_level:"Faible convient aux petits serveurs calmes ; moyen est recommandé ; élevé est plus strict.",
    warn_ban_threshold:"Quand ce nombre est atteint, SentriX peut appliquer la sanction automatique configurée.",
    log_messages:"Choisissez un salon réservé au staff pour les messages supprimés ou modifiés.",
    log_members:"Arrivées, départs et changements concernant les membres.",
    log_voice:"Entrées, sorties et déplacements dans les salons vocaux.",
    log_roles:"Créations, suppressions et modifications de rôles.",
    log_server:"Modifications générales du serveur et de ses paramètres.",
    log_automod:"Infractions et actions déclenchées automatiquement par l’AutoMod.",
    log_moderation:"Bans, mutes, avertissements et autres actions de modération.",
    log_channel:"Salon de secours utilisé quand aucun salon spécialisé n’est défini.",
    welcome_channel:"Salon où SentriX publiera le message lorsqu’un membre rejoint.",
    welcome_message:"Exemple : Bienvenue {member} sur {server} ! Nous sommes maintenant {member_count} membres.",
    welcome_image_url:"Utilisez un lien direct se terminant généralement par .png, .jpg, .webp ou .gif.",
    goodbye_channel:"Salon où les départs seront annoncés.",
    goodbye_message:"Exemple : {member} a quitté {server}. À bientôt !",
    autorole:"Ce rôle est donné automatiquement. Il doit rester sous le rôle du bot.",
    xp_multiplier:"1 = vitesse normale, 2 = deux fois plus d’XP, 0,5 = progression deux fois plus lente.",
    level_channel:"Laissez vide pour utiliser le comportement par défaut du module de niveaux.",
    level_message:"Le membre est mentionné automatiquement ; évitez d’ajouter @everyone ou @here.",
    ticket_category:"SentriX créera les salons privés des tickets dans cette catégorie.",
    ticket_log_channel:"Conservez ce salon privé, car les transcripts peuvent contenir des informations sensibles.",
    ticket_delete_delay:"0 supprime immédiatement ; une valeur comme 10 laisse dix secondes avant suppression.",
    ticket_transcript_dm:"Envoie au membre une copie de la discussion lors de la fermeture.",
    ticket_rating_enabled:"Permet au membre d’évaluer la qualité du support après la fermeture.",
    mod_role:"Rôle principal autorisé à utiliser les commandes de modération.",
    admin_role:"Rôle ayant accès aux réglages administratifs du bot.",
    mute_role:"Utilisé uniquement par les systèmes nécessitant encore un rôle muet.",
    member_role:"Rôle normal attribué aux membres vérifiés ou acceptés.",
    verification_role:"Rôle donné après la vérification. Il doit être attribuable par SentriX.",
    rules_channel:"Salon contenant le règlement du serveur.",
    verification_channel:"Salon où le panneau de vérification est publié.",
    bot_commands_channel:"Salon recommandé pour limiter les commandes et éviter le spam.",
    announce_channel:"Salon utilisé pour les annonces automatiques ou administratives.",
    report_channel:"Salon privé où le staff reçoit les signalements.",
    error_channel:"Salon privé destiné aux erreurs et alertes techniques du bot."
  };

  const originalOptions = new WeakMap();

  function normalise(value){return String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();}
  function levenshtein(a,b){if(a===b)return 0;if(!a.length)return b.length;if(!b.length)return a.length;const p=Array.from({length:b.length+1},(_,i)=>i),c=new Array(b.length+1);for(let i=1;i<=a.length;i++){c[0]=i;for(let j=1;j<=b.length;j++){const cost=a[i-1]===b[j-1]?0:1;c[j]=Math.min(c[j-1]+1,p[j]+1,p[j-1]+cost);}for(let j=0;j<=b.length;j++)p[j]=c[j];}return p[b.length];}
  function score(name,query){if(name===query)return -1000;if(name.startsWith(query))return -500+name.length-query.length;const index=name.indexOf(query);if(index>=0)return -300+index;const qw=query.split(" ").filter(Boolean),nw=name.split(" ").filter(Boolean);let total=0;for(const word of qw){let best=Infinity;for(const candidate of nw){best=Math.min(best,candidate.startsWith(word)?0:candidate.includes(word)?1:levenshtein(word,candidate));}total+=best;}return total*20+levenshtein(query,name);}

  function isChannelSelect(select){
    if(!(select instanceof HTMLSelectElement))return false;
    const key=`${select.dataset.key||""} ${select.id||""}`.toLowerCase();
    const label=(select.closest(".field")?.querySelector("label")?.textContent||"").toLowerCase();
    if(/channel|salon|category|categorie|catégorie/.test(`${key} ${label}`))return true;
    return [...select.options].some(option=>/\s—\s(text|voice|category|news|stage|forum)/i.test(option.textContent||""));
  }

  function remember(select){if(originalOptions.has(select))return;originalOptions.set(select,[...select.options].map((option,index)=>({value:String(option.value),text:option.textContent||"",index})));}
  function restore(select){const entries=originalOptions.get(select)||[];const selected=new Set([...select.selectedOptions].map(option=>String(option.value)));select.replaceChildren();for(const entry of entries){const option=document.createElement("option");option.value=entry.value;option.textContent=entry.text;option.selected=selected.has(entry.value);select.appendChild(option);}}

  function filterSelect(select,input,status){
    remember(select);const query=normalise(input.value);const selected=new Set([...select.selectedOptions].map(option=>String(option.value)));
    if(!query){restore(select);status.textContent=`${select.options.length} choix disponibles`;status.classList.remove("exact");return;}
    const entries=(originalOptions.get(select)||[]).filter(entry=>entry.value).map(entry=>({...entry,name:normalise(entry.text),score:score(normalise(entry.text),query)})).sort((a,b)=>a.score-b.score||a.index-b.index);
    const exact=entries.find(entry=>entry.name===query);const limit=query.length<=3?45:Math.max(35,query.length*18);let matches=entries.filter(entry=>entry.score<0||entry.score<=limit).slice(0,8);if(!matches.length)matches=entries.slice(0,Math.min(6,entries.length));
    const keep=new Set([...matches.map(entry=>entry.value),...selected]);select.replaceChildren();for(const entry of entries){if(!keep.has(entry.value))continue;const option=document.createElement("option");option.value=entry.value;option.textContent=entry.text;option.selected=selected.has(entry.value);select.appendChild(option);}if(!select.multiple){const empty=document.createElement("option");empty.value="";empty.textContent="Non configuré";if(!selected.size)empty.selected=true;select.insertBefore(empty,select.firstChild);}
    status.textContent=exact?"✓ Salon exact trouvé":`${matches.length} résultat${matches.length>1?"s":""} proche${matches.length>1?"s":""}`;status.classList.toggle("exact",Boolean(exact));select.dataset.bestMatch=matches[0]?.value||"";
  }

  function bindChannelSearch(select){
    if(!isChannelSelect(select)||select.dataset.dashboardSearchReady==="1")return;select.dataset.dashboardSearchReady="1";const field=select.closest(".field")||select.parentElement;if(!field)return;
    const label=field.querySelector("label")?.textContent?.trim()||"ce salon";const wrapper=document.createElement("div");wrapper.className="dashboard-channel-search";const input=document.createElement("input");input.type="search";input.placeholder=`Rechercher : ${label.toLowerCase()}…`;input.autocomplete="off";input.spellcheck=false;wrapper.appendChild(input);const status=document.createElement("div");status.className="dashboard-channel-search-status";field.insertBefore(wrapper,select);field.insertBefore(status,select.nextSibling);
    input.addEventListener("input",()=>filterSelect(select,input,status));input.addEventListener("keydown",event=>{if(event.key!=="Enter")return;event.preventDefault();const best=select.dataset.bestMatch;if(!best)return;select.value=best;select.dispatchEvent(new Event("change",{bubbles:true}));select.dispatchEvent(new Event("input",{bubbles:true}));input.value="";filterSelect(select,input,status);});filterSelect(select,input,status);
  }

  function ensureGuide(){
    const fields=document.getElementById("fields");if(!fields)return;const tab=(typeof state!=="undefined"&&state.tab)||"general";const data=guides[tab]||guides.general;let guide=document.getElementById("dashboardHelpGuide");if(!guide){guide=document.createElement("section");guide.id="dashboardHelpGuide";guide.className="dashboard-guide";fields.prepend(guide);}guide.innerHTML=`<h3>💡 ${data.title}</h3><p>${data.text}</p><ul>${data.items.map(item=>`<li>${item}</li>`).join("")}</ul><div class="guide-warning">${data.warning}</div>`;if(fields.firstElementChild!==guide)fields.prepend(guide);
  }

  function addFieldHints(){document.querySelectorAll("#fields [data-key]").forEach(control=>{const key=control.dataset.key,explanation=fieldHints[key];if(!explanation)return;const field=control.closest(".field")||control.closest(".switch");if(!field||field.querySelector(`.dashboard-extra-hint[data-key="${key}"]`))return;const hint=document.createElement("div");hint.className="dashboard-extra-hint";hint.dataset.key=key;hint.textContent=explanation;field.appendChild(hint);});}

  function enhance(){ensureGuide();addFieldHints();document.querySelectorAll("select").forEach(bindChannelSearch);}
  const observer=new MutationObserver(()=>queueMicrotask(enhance));observer.observe(document.body,{childList:true,subtree:true});document.addEventListener("click",event=>{if(event.target.closest("[data-tab]"))setTimeout(enhance,0);});enhance();
})();
</script>
"""


def _inject(html: str) -> str:
    marker = "</body>"
    if marker not in html:
        logger.warning("Dashboard : insertion des explications impossible.")
        return html
    return html.replace(marker, DASHBOARD_HELP_UI + "\n" + marker, 1)


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Explications et recherche globale des salons chargées dans le dashboard.")
