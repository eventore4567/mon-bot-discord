"""Initialisation des extensions du dashboard SentriX."""

from . import dashboard as _dashboard
from . import embed_dashboard as _embed_dashboard
from . import channel_search_dashboard as _channel_search_dashboard
from . import exact_channel_match_dashboard as _exact_channel_match_dashboard

_embed_dashboard.install(_dashboard)
_channel_search_dashboard.install(_dashboard)
_exact_channel_match_dashboard.install(_dashboard)
