"""Correctifs serveur du dashboard qui ne doivent jamais réécrire son JavaScript.

Le dashboard possède désormais une chaîne de démarrage canonique dans ``web/dashboard.py``
(``loadSession -> loadGuilds -> selectGuild``) avec ``AbortController``. Ce module est
chargé tard dans le runtime : il doit donc uniquement conserver la politique d'accès
Discord et surtout ne plus remplacer les fonctions frontend déjà corrigées.
"""
from __future__ import annotations

import logging

import discord


logger = logging.getLogger("bot.dashboard-runtime-patch")
MANAGE_GUILD = 1 << 5


async def _manager_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    """Accès dashboard : propriétaire, Administrateur ou Gérer le serveur."""
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    perms = member.guild_permissions
    if guild.owner_id == user_id or perms.administrator or perms.manage_guild:
        return member
    return None


def install() -> None:
    """Installe uniquement la politique d'accès serveur.

    Historique important : cette extension réécrivait auparavant ``loadSession()``,
    ``loadGuilds()`` et ``selectGuild()`` dans ``dashboard.INDEX_HTML``. Comme elle est
    installée après les correctifs du dashboard, elle annulait le nouveau
    ``AbortController`` et réintroduisait une seconde implémentation de chargement.
    Symptômes observés en production : titre « Chargement du serveur… » bloqué,
    nombreuses réponses HTTP 499 et contenu central vide malgré des réponses API 200.

    La logique de chargement appartient maintenant exclusivement à ``web/dashboard.py``.
    """
    from web import dashboard

    if getattr(dashboard, "_sentrix_runtime_patch_installed", False):
        return

    # Le filtre OAuth utilisait seulement le bit Administrateur. Avec ce masque, la
    # condition existante accepte aussi « Gérer le serveur » ; les propriétaires restent
    # acceptés par le test owner déjà présent.
    dashboard.ADMINISTRATOR = (1 << 3) | MANAGE_GUILD

    # Toutes les lectures/écritures API repassent ensuite par cette vérification live ;
    # perdre la permission retire donc immédiatement l'accès, même avec une session ouverte.
    dashboard._administrator_member = _manager_member

    # Ne jamais toucher à dashboard.INDEX_HTML ici. La chaîne frontend canonique et son
    # AbortController doivent rester la dernière autorité, y compris après le chargement
    # de cette extension tardive.
    dashboard._sentrix_runtime_patch_installed = True
    logger.info(
        "Dashboard runtime patch actif : permissions live uniquement, "
        "aucune réécriture de loadSession/loadGuilds/selectGuild."
    )
