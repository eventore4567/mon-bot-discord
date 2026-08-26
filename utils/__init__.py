"""Utilitaires partagés de SentriX.

Les transports Discord ne sont volontairement pas patchés depuis ce package. Le rendu
des commandes est centralisé par ``cogs.plain_response_policy`` et le thème final par
``utils.command_style_v2``. Garder ce fichier neutre évite les doubles wrappers et les
régressions sur les commandes.
"""
