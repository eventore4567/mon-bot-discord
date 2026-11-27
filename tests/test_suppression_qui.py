"""Qui a supprimé un message : entrées d'audit regroupées par Discord (27/11/2026).

« Après un clear, ça dit l'auteur lui-même » : Discord regroupe les suppressions
successives d'un même exécuteur (même auteur, même salon) dans UNE entrée dont
le compteur monte. Le code ignorait tout compteur > 1 : chaque suppression
après la première restait « sans exécuteur ».
"""
import asyncio
import datetime as dt
import os
from types import SimpleNamespace

import discord

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.logs import Logs  # noqa: E402


def test_les_suppressions_regroupees_gardent_leur_executeur():
    moderateur = SimpleNamespace(id=42, mention="<@42>", display_name="modo")
    debut = discord.utils.utcnow() - dt.timedelta(seconds=30)
    entree = SimpleNamespace(id=900, _target_id=7, created_at=debut, user=moderateur,
                             extra=SimpleNamespace(channel=SimpleNamespace(id=5), count=1))

    def audit_logs(*, limit=20, action=None):
        async def gen():
            if action == discord.AuditLogAction.message_delete:
                yield entree
        return gen()

    guild = SimpleNamespace(
        id=1, me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=audit_logs, get_member=lambda _id: None,
    )
    cog = SimpleNamespace(bot=SimpleNamespace(), _delete_audit_seen={}, _delete_audit_counts={})

    async def scenario():
        # 1re suppression : entrée fraîche, compteur 1.
        entree.created_at = discord.utils.utcnow()
        acteur, _ = await Logs._message_delete_actor(cog, guild, 7, 5, message_id=1)
        assert acteur is moderateur
        # 2e et 3e : même entrée (date de la 1re), compteur qui monte.
        entree.created_at = debut
        for compte in (2, 3):
            entree.extra.count = compte
            acteur, _ = await Logs._message_delete_actor(cog, guild, 7, 5, message_id=compte)
            assert acteur is moderateur, f"compteur {compte} : exécuteur perdu"

    asyncio.run(scenario())


def test_une_entree_sentrix_regroupee_ne_designe_pas_sentrix_pour_l_auteur():
    """Revue Codex (PR #733) : la hausse du compteur d'une entrée de SentriX (sa
    propre suppression, déjà attribuée localement) ne sert jamais de preuve."""
    sentrix = SimpleNamespace(id=999, mention="<@999>", display_name="SentriX")
    entree = SimpleNamespace(id=901, _target_id=7, created_at=discord.utils.utcnow(), user=sentrix,
                             extra=SimpleNamespace(channel=SimpleNamespace(id=5), count=1))

    def audit_logs(*, limit=20, action=None):
        async def gen():
            if action == discord.AuditLogAction.message_delete:
                yield entree
        return gen()

    guild = SimpleNamespace(
        id=1, me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=audit_logs, get_member=lambda _id: None,
    )
    cog = SimpleNamespace(bot=SimpleNamespace(user=sentrix), _delete_audit_seen={}, _delete_audit_counts={})

    async def scenario():
        await Logs._message_delete_actor(cog, guild, 7, 5, message_id=1)  # compteur 1 vu
        entree.extra.count = 2  # SentriX supprime encore (attribuée localement ailleurs)
        acteur, _ = await Logs._message_delete_actor(cog, guild, 7, 5, message_id=2)
        assert acteur is None, "SentriX désigné pour une suppression qu'il n'a pas faite"

    asyncio.run(scenario())


def test_deux_lots_du_meme_salon_ne_partagent_pas_l_executeur():
    """Revue Codex (PR #733) : l'entrée d'un lot déjà traité n'est pas réutilisée."""
    premier = SimpleNamespace(id=1, mention="<@1>")
    entree = SimpleNamespace(id=950, _target_id=5, created_at=discord.utils.utcnow(),
                             user=premier, extra=SimpleNamespace(count=6))

    def audit_logs(*, limit=10, action=None):
        async def gen():
            if action == discord.AuditLogAction.message_bulk_delete:
                yield entree
        return gen()

    guild = SimpleNamespace(id=1, me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
                            audit_logs=audit_logs)
    cog = SimpleNamespace(bot=SimpleNamespace())

    async def scenario():
        assert await Logs._bulk_delete_actor(cog, guild, 5, 6) is premier
        # Second lot, entrée du second exécuteur pas encore écrite : inconnu, pas « premier ».
        assert await Logs._bulk_delete_actor(cog, guild, 5, 6) is None

    asyncio.run(scenario())
