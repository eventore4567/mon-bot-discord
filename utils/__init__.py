"""Utilitaires partagés de SentriX.

Le thème des commandes est activé dès le chargement du package afin que les anciennes
fabriques d'embeds et les cogs chargés ensuite utilisent tous la même identité visuelle.
"""

from . import command_style_v2 as _command_style_v2

_command_style_v2.install()
