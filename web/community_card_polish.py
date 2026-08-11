"""Expose clairement Community et Engagement V3 depuis le dashboard principal."""
from __future__ import annotations


_OLD_SIMPLE_CARD = '''<article class="sx-simple-card"><div><div class="sx-simple-kicker">Communauté</div><h3>Accueil et tickets</h3><p>Configurez l'arrivée des membres puis le système de support.</p></div><div><button class="btn" type="button" data-sx-destination="welcome">Accueil</button> <button class="btn" type="button" data-sx-destination="tickets">Tickets</button></div></article>'''

_NEW_SIMPLE_CARD = '''<article class="sx-simple-card sx-community-main-card"><div><div class="sx-simple-kicker">Communauté</div><h3>Accueil, tickets et communauté</h3><p>Gérez l'arrivée des membres, le support, les automatisations, les candidatures staff et les vocaux temporaires.</p></div><div class="sx-community-actions"><button class="btn" type="button" data-sx-destination="welcome">Accueil</button><button class="btn" type="button" data-sx-destination="tickets">Tickets</button><a class="btn" href="/community">Centre communauté</a><a class="btn primary" href="/engagement" data-sx-engagement-link="1">Engagement V3</a></div><div class="sx-community-features"><span>Automatisations</span><span>Candidatures staff</span><span>Vocaux temporaires</span><span>Onboarding V2</span><span>Quêtes & saisons</span><span>Suggestions V2</span><span>Starboard</span><span>IA tickets</span></div></article>'''


_VISIBILITY_JS = r'''
<script id="sentrix-engagement-visibility-js">
(() => {
  "use strict";
  if (window.__sentrixEngagementVisibility) return;
  window.__sentrixEngagementVisibility = true;

  function ensureEngagementVisible(){
    const controls = document.getElementById("sxSimpleControls");
    if (controls && !controls.querySelector("[data-sx-engagement-quick]")) {
      const link = document.createElement("a");
      link.id = "sxEngagementQuick";
      link.className = "btn primary";
      link.href = "/engagement";
      link.setAttribute("data-sx-engagement-quick", "1");
      link.textContent = "Engagement V3 — profils, quêtes, saisons, suggestions, starboard et IA";
      controls.appendChild(link);
    }

    const actions = document.querySelector(".sx-community-main-card .sx-community-actions");
    if (actions && !actions.querySelector('[href="/engagement"]')) {
      const link = document.createElement("a");
      link.className = "btn primary";
      link.href = "/engagement";
      link.setAttribute("data-sx-engagement-link", "1");
      link.textContent = "Engagement V3";
      actions.appendChild(link);
    }

    const grid = document.querySelector("#sxSimpleHome .sx-simple-grid");
    if (grid && !document.getElementById("sxEngagementCard")) {
      const card = document.createElement("article");
      card.id = "sxEngagementCard";
      card.className = "sx-simple-card sx-engagement-card";
      card.innerHTML = '<div><div class="sx-simple-kicker">Nouveautés V3</div><h3>Engagement V3</h3><p>Onboarding, profils membres, quêtes quotidiennes et hebdomadaires, saisons, suggestions, starboard, modération contextuelle et IA tickets.</p></div><div class="sx-community-features"><span>Profils</span><span>6 quêtes</span><span>10 succès</span><span>Saisons</span><span>Suggestions</span><span>Starboard</span></div><a class="btn primary" href="/engagement">Ouvrir Engagement V3</a>';
      grid.appendChild(card);
    }
  }

  ensureEngagementVisible();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureEngagementVisible, {once:true});
  }
  const observer = new MutationObserver(ensureEngagementVisible);
  observer.observe(document.documentElement, {childList:true, subtree:true});
  setTimeout(() => observer.disconnect(), 15000);
})();
</script>
'''


def install(dashboard) -> None:
    """Affiche toujours Community + Engagement V3, quel que soit l'ordre des couches UI.

    Le dashboard simple est construit dynamiquement. Un remplacement HTML seul peut donc
    être écrasé ou arriver avant la création des cartes. On conserve le remplacement
    statique puis on ajoute un petit filet de sécurité côté navigateur : dès que le mode
    simple apparaît, un accès Engagement V3 est ajouté dans les contrôles ET sous forme de
    carte. Le lien reste aussi visible lorsque l'utilisateur passe en mode avancé puisque
    la barre de contrôles n'est pas supprimée.
    """
    css = r'''
<style id="sentrix-community-card-style">
.quick-card{display:flex;flex-direction:column;gap:5px;margin:14px 0;padding:15px 16px;border:1px solid var(--line,#252b3a);border-radius:14px;background:linear-gradient(145deg,rgba(22,27,40,.95),rgba(13,16,24,.95));color:var(--text,#f4f6fb);text-decoration:none;transition:transform .16s ease,border-color .16s ease,background .16s ease}.quick-card:hover{transform:translateY(-1px);border-color:var(--accent,#7d8cff);background:linear-gradient(145deg,rgba(29,35,52,.98),rgba(15,19,28,.98))}.quick-card strong{font-size:14px}.quick-card span{font-size:12px;color:var(--muted,#949caf);line-height:1.45}
.sx-community-actions{display:flex;gap:8px;flex-wrap:wrap}.sx-community-actions a.btn{text-decoration:none;display:inline-flex;align-items:center;justify-content:center}.sx-community-features{display:flex;gap:7px;flex-wrap:wrap;margin-top:1px}.sx-community-features span{font-size:11px;color:var(--muted,#949caf);border:1px solid var(--line,#252b3a);background:#0d111c;border-radius:999px;padding:5px 8px}
#sxEngagementQuick{display:flex;align-items:center;justify-content:center;text-decoration:none;text-align:center;min-height:42px;border-color:var(--brand2,#7d8cff);box-shadow:0 8px 24px rgba(90,105,255,.15)}
.sx-engagement-card{border-color:rgba(125,140,255,.65)!important;background:linear-gradient(145deg,rgba(27,32,54,.98),rgba(14,18,29,.98))!important}.sx-engagement-card>a.btn{text-decoration:none;display:inline-flex;align-items:center;justify-content:center;justify-self:start}
</style>
'''
    html = getattr(dashboard, "INDEX_HTML", "")
    if not isinstance(html, str):
        return

    if 'id="sentrix-community-card-style"' not in html and "</head>" in html:
        html = html.replace("</head>", css + "\n</head>", 1)

    if _OLD_SIMPLE_CARD in html:
        html = html.replace(_OLD_SIMPLE_CARD, _NEW_SIMPLE_CARD, 1)

    if 'id="sentrix-engagement-visibility-js"' not in html and "</body>" in html:
        html = html.replace("</body>", _VISIBILITY_JS + "\n</body>", 1)

    dashboard.INDEX_HTML = html
    dashboard._sentrix_community_card_polish = True
