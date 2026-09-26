"""Liste publique des commandes SentriX.

Cette page avait sa propre palette (``--bg:#080a11``, ``--brand:#7566ff``),
différente à la fois du moteur partagé (``#070b14``) et de la landing : le
sol changeait de couleur en naviguant. Elle passe sur la coquille commune
de ``marketing_growth_v40`` et récupère au passage la navigation complète,
qu'elle n'avait pas — elle n'offrait qu'un « Retour au hub ».
"""
from __future__ import annotations

import html
from aiohttp import web

_INSTALLED = False


def _clean(value, fallback="") -> str:
    text = str(value or fallback).strip()
    return " ".join(text.split())


def _prefix_commands(bot) -> list[dict]:
    rows = []
    seen = set()
    for command in list(getattr(bot, "commands", []) or []):
        if getattr(command, "hidden", False) or not getattr(command, "enabled", True):
            continue
        name = _clean(getattr(command, "qualified_name", None) or getattr(command, "name", "")).lower()
        if not name or name in seen:
            continue
        seen.add(name)
        description = _clean(
            getattr(command, "help", None)
            or getattr(command, "brief", None)
            or getattr(command, "description", None),
            "Commande SentriX.",
        )
        signature = _clean(getattr(command, "signature", ""))
        usage = f"+{name}" + (f" {signature}" if signature else "")
        cog = _clean(getattr(command, "cog_name", None), "Autres")
        rows.append({"kind": "prefix", "name": name, "usage": usage, "description": description, "category": cog})
    return sorted(rows, key=lambda item: item["name"])


def _slash_commands(bot) -> list[dict]:
    tree = getattr(bot, "tree", None)
    if tree is None:
        return []
    rows = []
    seen = set()
    try:
        commands = list(tree.get_commands())
    except Exception:
        commands = []
    for command in commands:
        name = _clean(getattr(command, "qualified_name", None) or getattr(command, "name", "")).lower()
        if not name or name in seen:
            continue
        seen.add(name)
        description = _clean(getattr(command, "description", None), "Commande SentriX.")
        rows.append({"kind": "slash", "name": name, "usage": f"/{name}", "description": description, "category": "Slash"})
    return sorted(rows, key=lambda item: item["name"])


def _command_card(item: dict) -> str:
    usage = html.escape(item["usage"])
    description = html.escape(item["description"])
    category = html.escape(item["category"])
    kind = html.escape(item["kind"])
    searchable = html.escape(f"{item['name']} {item['description']} {item['category']} {item['usage']}".lower(), quote=True)
    badge = "/ Slash" if item["kind"] == "slash" else "+ Préfixe"
    return (
        f'<article class="cmd" data-kind="{kind}" data-search="{searchable}">'
        f'<div class="cmd-tete"><code>{usage}</code><span class="cmd-type">{html.escape(badge)}</span></div>'
        f'<p>{description}</p><small>{category}</small></article>'
    )


# Volontairement ``.cmd`` et non ``.card`` : la coquille attache l'inclinaison
# 3D à chaque ``.card`` et leur donne une animation d'entrée. Sur une page qui
# en liste plusieurs centaines, cela ferait autant d'écouteurs de pointeur et
# autant d'animations au chargement, pour un effet que personne ne remarque
# dans une grille aussi dense. Même verre, même palette, sans le coût.
_STYLES = """
.cmd-outils{display:grid;grid-template-columns:1fr auto;gap:12px;margin:8px 0 14px}
.cmd-outils input{width:100%;background:var(--panneau);border:1px solid var(--ligne);
 color:var(--texte);border-radius:12px;padding:13px 15px;font:inherit;outline:none;
 transition:border-color .18s ease,box-shadow .18s ease}
.cmd-outils input::placeholder{color:var(--doux)}
.cmd-outils input:focus-visible{border-color:var(--bleu);box-shadow:0 0 0 3px rgba(77,163,255,.26)}
.cmd-filtres{display:flex;gap:7px;flex-wrap:wrap}
.cmd-filtres button{border:1px solid var(--ligne);background:var(--panneau);color:var(--texte);
 padding:11px 14px;border-radius:11px;font:inherit;font-weight:700;cursor:pointer;
 transition:border-color .18s ease,background .18s ease}
.cmd-filtres button:hover{border-color:rgba(140,203,255,.40)}
.cmd-filtres button:focus-visible{outline:2px solid var(--bleu2);outline-offset:2px}
.cmd-filtres button[aria-pressed="true"]{background:rgba(111,125,255,.22);border-color:rgba(140,203,255,.46)}
.cmd-compte{margin:0 0 18px;color:var(--doux);font-size:13.5px}
.cmd-grille{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}
.cmd{border:1px solid var(--ligne);border-radius:14px;padding:16px;min-width:0;
 background:linear-gradient(168deg,rgba(26,36,58,.66),rgba(12,18,32,.62));
 box-shadow:inset 0 1px 0 rgba(160,200,255,.06)}
.cmd-tete{display:flex;justify-content:space-between;gap:12px;align-items:center}
.cmd code{font:700 15px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--bleu2);overflow-wrap:anywhere}
.cmd-type{font-size:11px;color:var(--doux);border:1px solid var(--ligne);border-radius:999px;
 padding:4px 8px;white-space:nowrap}
.cmd p{color:var(--doux);line-height:1.55;margin:11px 0}
.cmd small{color:#78849a}
.cmd-vide{display:none;text-align:center;border:1px dashed var(--ligne);border-radius:14px;
 padding:28px;color:var(--doux)}
@media(max-width:760px){.cmd-outils{grid-template-columns:1fr}.cmd-grille{grid-template-columns:1fr}
 .cmd-tete{align-items:flex-start;flex-direction:column;gap:7px}}
"""

# Le compteur est annoncé via aria-live : sans cela, filtrer la liste au
# clavier ne produit aucun retour pour un lecteur d'écran.
_SCRIPT = """<script>
(() => {
 "use strict";
 const recherche=document.getElementById("cmdRecherche"),
       cartes=[...document.querySelectorAll(".cmd")],
       vide=document.getElementById("cmdVide"),
       compte=document.getElementById("cmdCompte"),
       boutons=[...document.querySelectorAll("[data-filter]")];
 let filtre="all";
 const rendre=()=>{
  const q=recherche.value.trim().toLowerCase();let vus=0;
  cartes.forEach(c=>{
   const okType=filtre==="all"||c.dataset.kind===filtre;
   const okTexte=!q||c.dataset.search.includes(q);
   const montrer=okType&&okTexte;
   c.hidden=!montrer;if(montrer)vus++;
  });
  vide.style.display=vus?"none":"block";
  compte.textContent=vus+(vus>1?" commandes affichées":" commande affichée");
 };
 recherche.addEventListener("input",rendre);
 boutons.forEach(b=>b.addEventListener("click",()=>{
  boutons.forEach(x=>x.setAttribute("aria-pressed",String(x===b)));
  filtre=b.dataset.filter;rendre();
 }));
})();
</script>"""


def _page(bot, dashboard, request: web.Request) -> str:
    del dashboard  # la coquille partagée calcule elle-même l'URL canonique
    from .marketing_growth_v40 import coquille_publique

    slash = _slash_commands(bot)
    prefix = _prefix_commands(bot)
    toutes = slash + prefix
    cartes = "".join(_command_card(item) for item in toutes)
    corps = (
        '<div class="cmd-outils">'
        '<label><span class="sx-sr">Rechercher une commande</span>'
        '<input id="cmdRecherche" type="search" autocomplete="off"'
        ' placeholder="Rechercher ban, ticket, niveau, IA…"></label>'
        '<div class="cmd-filtres" role="group" aria-label="Filtrer par type de commande">'
        '<button type="button" data-filter="all" aria-pressed="true">Toutes</button>'
        '<button type="button" data-filter="slash" aria-pressed="false">Slash /</button>'
        '<button type="button" data-filter="prefix" aria-pressed="false">Préfixe +</button>'
        "</div></div>"
        f'<p class="cmd-compte" id="cmdCompte" role="status" aria-live="polite">'
        f"{len(toutes)} commandes affichées · {len(slash)} slash / · {len(prefix)} préfixe +</p>"
        f'<section class="cmd-grille" id="cmdGrille">{cartes}</section>'
        '<div class="cmd-vide" id="cmdVide">Aucune commande trouvée.</div>'
    )
    return coquille_publique(
        request,
        title="Commandes SentriX — Slash / et préfixe +",
        description=(
            "Les commandes slash / et les commandes avec le préfixe + de SentriX, "
            "avec une recherche instantanée."
        ),
        heading="Commandes SentriX",
        body=corps,
        styles_extra=_STYLES,
        script_extra=_SCRIPT,
    )


async def commands_page(request: web.Request) -> web.Response:
    dashboard = request.app.get("dashboard_module")
    bot = request.app.get("bot")
    if dashboard is None or bot is None:
        raise web.HTTPServiceUnavailable(text="SentriX démarre")
    return web.Response(
        text=_page(bot, dashboard, request),
        content_type="text/html",
        headers={"Cache-Control": "public, max-age=60", "X-Robots-Tag": "index, follow"},
    )


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get("/commands", commands_page)
        return app

    dashboard.build_app = build_app
