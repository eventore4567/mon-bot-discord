"""Initialisation sécurisée du dashboard SentriX.

Le dashboard principal reste stable. Les améliorations visuelles et les outils avancés sont
chargés par des modules séparés afin qu'une erreur reste isolée.
"""

from . import dashboard as _dashboard
from . import setup_dashboard as _setup_dashboard
from . import design_setup_dashboard as _design_setup_dashboard
from . import setup_center as _setup_center
from . import setup_center_exclusive as _setup_center_exclusive
from . import setup_center_search as _setup_center_search
from . import dashboard_explanations_search as _dashboard_explanations_search
from . import setup_center_explanations as _setup_center_explanations
from . import embed_center as _embed_center
from . import dashboard_polish as _dashboard_polish
from . import persistent_dashboard_sessions as _persistent_dashboard_sessions
from . import admin_only_dashboard as _admin_only_dashboard


_original_handle_index = _dashboard.handle_index


async def _handle_index_without_cache(request):
    """Force le navigateur à récupérer la dernière interface après un correctif."""
    response = await _original_handle_index(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


_dashboard.handle_index = _handle_index_without_cache
_dashboard_explanations_search.install(_dashboard)
_setup_center_exclusive.install(_setup_center, _setup_dashboard)
_setup_center_search.install(_setup_center)
_setup_center_explanations.install(_setup_center)
_setup_center.install(_dashboard, _setup_dashboard, _design_setup_dashboard)
_embed_center.install(_dashboard)

# Le clic est géré par le script du créateur. Le bouton ne soumet donc pas une seconde fois
# le formulaire, ce qui empêche l'envoi accidentel de deux messages Discord identiques.
_embed_center.EMBED_CENTER_HTML = _embed_center.EMBED_CENTER_HTML.replace(
    'id="saveButton" class="btn primary" type="submit"',
    'id="saveButton" class="btn primary" type="button"',
    1,
)
# Un modèle rempli par JavaScript doit lui aussi être conservé immédiatement dans le
# brouillon, même si l'utilisateur n'a pas encore retouché un champ à la main.
_embed_center.EMBED_CENTER_HTML = _embed_center.EMBED_CENTER_HTML.replace(
    '$("applyTemplate").addEventListener("click",applyTemplate);',
    '$("applyTemplate").addEventListener("click",()=>{applyTemplate();scheduleDraft();});',
    1,
)

# Petits correctifs appliqués avant l'injection : les éléments techniques restent dans le
# body et l'annulation d'un changement de serveur restaure réellement l'ancienne valeur.
_dashboard_polish.POLISH_JS = _dashboard_polish.POLISH_JS.replace(
    'document.documentElement.append(progress, offline);\n  document.body.appendChild(health);',
    'document.body.append(progress, offline, health);',
    1,
)
_dashboard_polish.POLISH_JS = _dashboard_polish.POLISH_JS.replace(
    'if (!confirmServerChange(event)) return;\n      if (event.target.value',
    'if (!confirmServerChange(event)) {\n        event.target.value = localStorage.getItem(storageKey("guild")) || "";\n        return;\n      }\n      if (event.target.value',
    1,
)
_dashboard_polish.install(_dashboard, _setup_center, _embed_center)

# La connexion Discord reste mémorisée 30 jours, y compris après un redémarrage Railway.
# Cette couche doit être installée AVANT le verrou Administrateur afin de restaurer la
# session depuis SQLite avant toute vérification des permissions du serveur.
_persistent_dashboard_sessions.install(_dashboard)

# Le créateur d'embeds est une page privée au même titre que le dashboard principal.
_admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/embed-builder")
# Doit rester en dernier pour protéger également toutes les routes ajoutées ci-dessus.
_admin_only_dashboard.install(_dashboard)
