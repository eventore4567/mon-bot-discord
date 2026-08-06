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
_dashboard_polish.install(_dashboard, _setup_center, _embed_center)

# Le créateur d'embeds est une page privée au même titre que le dashboard principal.
_admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/embed-builder")
# Doit rester en dernier pour protéger également toutes les routes ajoutées ci-dessus.
_admin_only_dashboard.install(_dashboard)
