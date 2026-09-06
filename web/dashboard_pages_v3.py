"""Entrée de compatibilité du dashboard SentriX V56.

Historique : le HTML de base était successivement réécrit par plusieurs générations de
présentation (Oxyde, V5, fiabilité, clarté, compact, puis des hotfixes). Ces transformations
se dépendaient de chaînes HTML exactes et finissaient par produire un frontend très gros,
difficile à raisonner et fragile au moindre changement.

V56 conserve le backend/API et le routeur de données existants, mais publie UNE seule source
frontend : le dashboard canonique défini dans ``web.dashboard.INDEX_HTML``. Les extensions
produit pré-start (Tickets, Embeds, ping rôle) restent installées ensuite au point prévu par
``sentrix_product_update`` et le snapshot V55 empêche toute réécriture tardive après le bind
HTTP.
"""

from .dashboard_oxyde_hotfix import patch_dashboard_runtime
from .dashboard_frontend_freeze_v55 import install_product_prestart_hook


# Cette correction concerne uniquement le lecteur backend des données serveur : elle protège
# le dashboard lorsqu'une table secondaire/optionnelle n'existe pas. Elle ne réécrit pas l'UI.
patch_dashboard_runtime()

# Le gel V55 reste l'autorité après les extensions produit pré-start : le document réellement
# lié à /app ne peut plus être remplacé par un cog chargé plus tard.
install_product_prestart_hook()


def apply_dashboard_pages(html: str) -> str:
    """Retourne le frontend canonique sans empiler d'anciennes transformations visuelles."""
    return html


__all__ = ["apply_dashboard_pages"]
