"""Initialisation des extensions stables du dashboard SentriX."""

from . import dashboard as _dashboard
from . import embed_dashboard as _embed_dashboard
from . import channel_search_dashboard as _channel_search_dashboard
from . import exact_channel_match_dashboard as _exact_channel_match_dashboard
from . import config_status_dashboard as _config_status_dashboard

# Ces extensions ont déjà été validées en production.
_embed_dashboard.install(_dashboard)
_channel_search_dashboard.install(_dashboard)
_exact_channel_match_dashboard.install(_dashboard)
_config_status_dashboard.install(_dashboard)

# Les nouveaux centres Setup/Design restent présents dans le dépôt, mais ne sont pas
# chargés tant que leur injection JavaScript n'a pas été reconstruite de façon isolée.
# Cela évite qu'une erreur dans un nouvel onglet bloque tout le dashboard.
