"""Initialisation des extensions du dashboard SentriX."""

from . import dashboard as _dashboard
from . import embed_dashboard as _embed_dashboard

_embed_dashboard.install(_dashboard)
