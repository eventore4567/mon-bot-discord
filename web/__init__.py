"""Initialisation sécurisée du dashboard SentriX.

Le dashboard principal reste inchangé. Les réglages avancés sont chargés dans une page
séparée afin qu'une erreur du Centre Setup ne puisse jamais bloquer les boutons principaux.
"""

from . import dashboard as _dashboard
from . import setup_dashboard as _setup_dashboard
from . import design_setup_dashboard as _design_setup_dashboard
from . import setup_center as _setup_center
from . import setup_center_exclusive as _setup_center_exclusive


_original_handle_index = _dashboard.handle_index


async def _handle_index_without_cache(request):
    """Force le navigateur à récupérer la dernière interface après un correctif."""
    response = await _original_handle_index(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


_dashboard.handle_index = _handle_index_without_cache
_setup_center_exclusive.install(_setup_center, _setup_dashboard)
_setup_center.install(_dashboard, _setup_dashboard, _design_setup_dashboard)
