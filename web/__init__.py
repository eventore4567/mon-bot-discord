"""Initialisation des extensions du dashboard SentriX."""

from . import dashboard as _dashboard
from . import embed_dashboard as _embed_dashboard
from . import channel_search_dashboard as _channel_search_dashboard

_embed_dashboard.install(_dashboard)
_channel_search_dashboard.install(_dashboard)
