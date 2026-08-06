"""Mode de récupération du dashboard SentriX.

Le dashboard de base reste la seule interface chargée tant que les extensions injectant
du JavaScript n'ont pas été validées séparément. Les fichiers des extensions et toutes
les données enregistrées sont conservés.
"""

from . import dashboard as _dashboard


_original_handle_index = _dashboard.handle_index


async def _handle_index_without_cache(request):
    """Force le navigateur à récupérer la dernière interface après un correctif."""
    response = await _original_handle_index(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


_dashboard.handle_index = _handle_index_without_cache
