"""Thème unique V60 pour toutes les pages d'administration secondaires.

Le dashboard principal ``/app`` possède déjà son identité V60. Historiquement, les pages
isolées (Centre Setup, créateur d'embeds, Feature Suite, Operations, Community, etc.) ont
conservé plusieurs anciens thèmes violets et des formes différentes. Cette couche ne touche
à aucune route/API : elle ajoute uniquement la feuille de style V60 au document HTML final
de chaque page secondaire chargée par :mod:`web`.

Le CSS est volontairement injecté en dernier et emploie ``!important`` uniquement pour les
propriétés de thème/forme. Cela permet d'écraser les anciennes couches visuelles sans casser
leurs composants, scripts, formulaires ou protections serveur.
"""
from __future__ import annotations

import logging
from types import ModuleType

logger = logging.getLogger("bot.dashboard-v60-secondary-theme")

V60_SECONDARY_CSS = r'''
<style id="sentrix-v60-secondary-theme">
/* -------------------------------------------------------------------------- */
/* SentriX V60 — identité visuelle commune à toutes les pages secondaires.    */
/* Palette identique à /app : charbon + gris + accent corail/orange.          */
/* -------------------------------------------------------------------------- */
:root{
  --sx-top:#1f2226;
  --sx-rail:#20242a;
  --sx-side:#2c3035;
  --sx-side2:#292d32;
  --sx-content:#383c42;
  --sx-card:#34383e;
  --sx-card2:#2e3237;
  --sx-field:#292d31;
  --sx-line:#484d53;
  --sx-line2:#3f444a;
  --sx-text:#f5f5f5;
  --sx-muted:#a9aaad;
  --sx-faint:#777b81;
  --sx-accent:#d66f55;
  --sx-accent2:#ef8568;
  --sx-ok:#35d66f;
  --sx-bad:#e36b78;
  --sx-warn:#e9bd67;

  /* Alias historiques utilisés par les anciens centres. */
  --bg:var(--sx-content)!important;
  --panel:var(--sx-card)!important;
  --panel2:var(--sx-card2)!important;
  --line:var(--sx-line)!important;
  --text:var(--sx-text)!important;
  --muted:var(--sx-muted)!important;
  --brand:var(--sx-accent)!important;
  --brand2:var(--sx-accent2)!important;
  --accent:var(--sx-accent)!important;
  --accent2:var(--sx-accent2)!important;
  --ok:var(--sx-ok)!important;
  --bad:var(--sx-bad)!important;
  --warn:var(--sx-warn)!important;
}

html,body{
  background:var(--sx-content)!important;
  color:var(--sx-text)!important;
  color-scheme:dark;
}
body{
  background-image:none!important;
  font:15px Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif!important;
}
body::before,body::after{background-image:none!important}

/* En-tête : même barre sombre et plate que /app. */
.top,.topbar,header.top,header.topbar,.header,.page-top,.sx-topbar{
  background:var(--sx-top)!important;
  background-image:none!important;
  border-color:#ffffff12!important;
  border-radius:0!important;
  box-shadow:none!important;
  backdrop-filter:none!important;
}
.brand,.top .brand,.topbar .brand{
  color:var(--sx-text)!important;
  font-weight:900!important;
  letter-spacing:.01em!important;
}

/* Le titre de page n'est plus enfermé dans une grosse carte violette. */
.head,.hero,.page-head,.setup-head{
  background:transparent!important;
  background-image:none!important;
  border:0!important;
  border-radius:0!important;
  box-shadow:none!important;
}
.head h1,.hero h1,.page-head h1{color:var(--sx-text)!important;letter-spacing:-.02em!important}
.head p,.hero p,.page-head p{color:#c0c1c3!important}

/* Panneaux et cartes : rectangles gris, rayon faible, profondeur discrète. */
.panel,.card,.box,.section,.surface,.container-card,
.sx-system-tile,.sx-sec-stat,.sx-sec-box,.sx-v37-entry,
.metric,.item,.action-card,.template-bar,.switch,.check,
.exclusive-help,.dm-card,.embed-card,.feature-card{
  background:var(--sx-card)!important;
  background-image:none!important;
  border:1px solid var(--sx-line)!important;
  border-radius:7px!important;
  box-shadow:none!important;
}
.panel-head,.card-head,.section-head,.surface-head{
  background:var(--sx-card2)!important;
  background-image:none!important;
  border-color:var(--sx-line)!important;
  border-radius:0!important;
}
.content,.panel-content,.card-content{background:transparent!important}

/* Onglets : formes plates proches de la navigation du dashboard principal. */
.tabs{gap:7px!important}
.tab,.tabs .tab{
  min-height:44px!important;
  background:var(--sx-card2)!important;
  background-image:none!important;
  color:#e7e8e9!important;
  border:1px solid var(--sx-line)!important;
  border-radius:6px!important;
  box-shadow:none!important;
  transform:none!important;
  transition:background .14s ease,border-color .14s ease,color .14s ease!important;
}
.tab:hover,.tabs .tab:hover{
  background:#292c31!important;
  border-color:#737980!important;
  color:#fff!important;
  transform:none!important;
}
.tab.active,.tabs .tab.active{
  background:#292c31!important;
  background-image:none!important;
  color:var(--sx-accent2)!important;
  border-color:var(--sx-accent)!important;
  box-shadow:inset 4px 0 0 var(--sx-accent)!important;
  transform:none!important;
}

/* Champs : exactement le gris des champs /app, sans halo violet. */
input,select,textarea,.select,
.field input,.field select,.field textarea{
  background:var(--sx-field)!important;
  background-image:none!important;
  color:var(--sx-text)!important;
  border:1px solid #4a4e52!important;
  border-radius:5px!important;
  box-shadow:none!important;
  outline:0!important;
}
input:focus,select:focus,textarea:focus,.select:focus,
.field input:focus,.field select:focus,.field textarea:focus{
  border-color:var(--sx-accent)!important;
  box-shadow:0 0 0 2px #d66f5520!important;
}
input[type="checkbox"],input[type="radio"]{accent-color:var(--sx-accent)!important}
select[multiple] option:checked{
  color:#fff!important;
  background:var(--sx-accent)!important;
  background-image:none!important;
}
.field label{color:#d6d7d8!important}
.field small,.hint,.muted,.description,.subtext{color:var(--sx-muted)!important}

/* Boutons : corail pour l'action principale, gris pour le reste. */
.btn,button.btn,.button,.top a,.actions a{
  background:#2a2e33!important;
  background-image:none!important;
  color:#f3f4f5!important;
  border:1px solid #50565c!important;
  border-radius:6px!important;
  box-shadow:none!important;
  transform:none!important;
}
.btn:hover,button.btn:hover,.button:hover,.top a:hover,.actions a:hover{
  background:#30353a!important;
  border-color:#737980!important;
  transform:none!important;
}
.btn.primary,button.btn.primary,.button.primary{
  background:var(--sx-accent)!important;
  background-image:none!important;
  border-color:var(--sx-accent)!important;
  color:#fff!important;
  box-shadow:none!important;
}
.btn.primary:hover,button.btn.primary:hover,.button.primary:hover{
  background:var(--sx-accent2)!important;
  border-color:var(--sx-accent2)!important;
}
.btn.danger,button.btn.danger,.button.danger{
  background:#48282c!important;
  border-color:#7e424a!important;
  color:#ffb2ba!important;
}

/* Switches et gros toggles des anciens écrans. */
.sx-big-toggle,.toggle,.switch-control{
  background:#b4b5b6!important;
  background-image:none!important;
  border-color:#8b8d90!important;
  border-radius:999px!important;
  box-shadow:none!important;
}
.sx-big-toggle.on,.toggle.on,.switch-control.on,
.sx-big-toggle[aria-checked="true"]{
  background:var(--sx-accent)!important;
  border-color:var(--sx-accent)!important;
  box-shadow:none!important;
}
.sx-big-toggle::after{border-radius:50%!important;background:#fff!important;box-shadow:0 1px 3px #0005!important}

/* Composants spécifiques Setup/Security. */
.sx-system-tile::before{background:var(--sx-accent)!important}
.sx-system-tile.off{
  background:var(--sx-card)!important;
  border-color:var(--sx-line)!important;
}
.sx-system-tile.off::before{background:#777b81!important}
.sx-chip,.exclusive-count{
  background:#292d31!important;
  border-color:#50555b!important;
  color:#c9cbcd!important;
  border-radius:5px!important;
}
.exclusive-count.active{
  background:#3d2d29!important;
  border-color:var(--sx-accent)!important;
  color:var(--sx-accent2)!important;
}
.sx-system-state,.state.on{
  background:#1d3a2c!important;
  border-color:#3f7057!important;
  color:#8ce0b2!important;
}
.sx-system-state.off,.state:not(.on){
  background:#30353a!important;
  border-color:#50555b!important;
  color:#c9cbcd!important;
}
.sx-sec-owner{
  background:#3a3024!important;
  border-color:#6f5c3d!important;
  color:#e7c987!important;
  border-radius:6px!important;
}
.sx-sec-good{color:#8ce0b2!important}.sx-sec-warn{color:#e9bd67!important}.sx-sec-bad{color:#ff9da8!important}

/* Notifications et barre d'enregistrement. */
.savebar{
  background:#2c3035!important;
  background-image:none!important;
  border:1px solid var(--sx-line)!important;
  border-radius:7px!important;
  box-shadow:none!important;
  backdrop-filter:none!important;
}
.status,.toast{
  border-radius:7px!important;
  box-shadow:0 14px 34px #0007!important;
}
.status:not(.bad),.toast:not(.bad){
  background:#1d3a2c!important;
  border-color:#3f7057!important;
  color:#9ee3bd!important;
}
.status.bad,.toast.bad{
  background:#422328!important;
  border-color:#7b4149!important;
  color:#ffb0b8!important;
}

/* Feature Suite V37 / listes / métriques. */
.state{border-radius:999px!important}
.metric{background:var(--sx-card2)!important}
.issue{
  background:#3a3024!important;
  border-color:#6f5c3d!important;
  color:#e7c987!important;
  border-radius:6px!important;
}
.item{background:var(--sx-card2)!important}

/* Suppression des anciens halos et gradients violets imbriqués. */
[style*="linear-gradient"],[style*="radial-gradient"]{
  --sx-inline-gradient-disabled:1;
}

@media(max-width:900px){
  .head,.hero,.page-head{padding-left:0!important;padding-right:0!important}
}
</style>
'''


def apply_secondary_theme(html: str) -> str:
    """Ajoute le thème V60 à un document HTML complet, de manière idempotente."""
    if not isinstance(html, str) or not html:
        return html
    if 'id="sentrix-v60-secondary-theme"' in html:
        return html
    lower = html.lstrip().lower()
    if not (lower.startswith("<!doctype html") or lower.startswith("<html")):
        return html
    if "</head>" not in html or "<body" not in lower:
        return html
    return html.replace("</head>", V60_SECONDARY_CSS + "\n</head>", 1)


def _theme_module(module: ModuleType) -> int:
    """Thème tous les documents HTML complets conservés dans les globals d'un module."""
    changed = 0
    for name, value in list(vars(module).items()):
        if not isinstance(value, str):
            continue
        themed = apply_secondary_theme(value)
        if themed == value:
            continue
        setattr(module, name, themed)
        changed += 1
    return changed


def install(*modules: ModuleType) -> int:
    """Applique le thème V60 aux pages secondaires déjà construites.

    ``/app`` n'est jamais fourni à cette fonction : le shell principal reste donc strictement
    inchangé. Le compteur retourné permet aux tests et aux logs Railway de vérifier qu'au
    moins une page autonome a réellement été harmonisée.
    """
    total = 0
    details: list[str] = []
    seen: set[int] = set()
    for module in modules:
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        count = _theme_module(module)
        if count:
            total += count
            details.append(f"{module.__name__}:{count}")
    logger.info(
        "Dashboard V60 : thème secondaire unifié sur %s document(s) (%s).",
        total,
        ", ".join(details) if details else "aucun document détecté",
    )
    return total


__all__ = ["V60_SECONDARY_CSS", "apply_secondary_theme", "install"]
