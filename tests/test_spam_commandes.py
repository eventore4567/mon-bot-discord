"""Spam de commandes / : les réponses des bots comptent pour celui qui les lance.

22/11/2026 : « est-ce que l'anti-spam peut détecter les commandes, genre si un
mec spam les commandes / ». Une commande / ne produit AUCUN message du membre,
seulement la réponse du bot. Pour un bot installé sur le serveur (pas une
application « APP » installée par un utilisateur, déjà traitée), AutoMod
ignorait cette réponse en entier : un membre pouvait lancer cinquante
commandes en une minute sans jamais être vu.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import automod as automod_module  # noqa: E402
from tests.test_automod_external_app_raid import _cog_complet  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402


def _reponse(guild, lanceur, numero, *, interaction=None, contenu="Votre récompense : 50 pièces", user_install=False):
    meta = SimpleNamespace(
        id=interaction if interaction is not None else 10_000 + numero,
        user=SimpleNamespace(id=lanceur.id),
        is_user_integration=lambda: user_install,
    )
    message = Mock(spec=discord.Message)
    message.id = 5_000 + numero
    message.guild = guild
    message.author = SimpleNamespace(id=900, bot=True, name="Bot du serveur")
    message.webhook_id = None
    message.interaction_metadata = meta
    message.content = contenu
    message.embeds = []
    message.attachments = []
    message.mentions = []
    message.mention_everyone = False
    message.role_mentions = []
    message.created_at = discord.utils.utcnow()
    message.channel = Mock(id=55, mention="<#55>")
    message.channel.send = AsyncMock()
    message.delete = AsyncMock()
    return message


def _envoyer(cog, messages):
    async def scenario():
        for message in messages:
            await cog.on_message(message)
        await asyncio.sleep(0.05)

    with patch.object(panels, "texte_court", AsyncMock()), \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        asyncio.run(scenario())


def test_une_rafale_de_commandes_est_vue_comme_du_spam_du_lanceur():
    cog, guild, membre = _cog_complet({"antispam": 1})
    messages = [_reponse(guild, membre, i) for i in range(12)]
    _envoyer(cog, messages)

    incident = cog.incidents.get((guild.id, membre.id))
    assert incident is not None and incident.filter_name == "antispam", (
        "aucun incident anti-spam pour douze commandes en une seconde"
    )
    # Le membre sanctionné est le lanceur, jamais le bot qui a répondu.
    assert (guild.id, 900) not in cog.incidents


def test_quelques_commandes_espacees_ne_declenchent_rien():
    cog, guild, membre = _cog_complet({"antispam": 1})
    _envoyer(cog, [_reponse(guild, membre, i) for i in range(2)])
    assert (guild.id, membre.id) not in cog.incidents


def test_une_commande_en_plusieurs_messages_ne_compte_qu_une_fois():
    """Un bot qui répond en douze messages à UNE commande n'est pas un spam du membre."""
    cog, guild, membre = _cog_complet({"antispam": 1})
    _envoyer(cog, [_reponse(guild, membre, i, interaction=777) for i in range(12)])
    assert (guild.id, membre.id) not in cog.incidents


def test_le_contenu_de_la_reponse_n_est_pas_filtre_contre_le_lanceur():
    """La réponse d'un bot du serveur est écrite par le bot : un mot interdit
    dedans ne doit pas sanctionner le membre qui a tapé la commande."""
    cog, guild, membre = _cog_complet({"antispam": 1, "antiinsult": 1})
    message = _reponse(guild, membre, 1, contenu="Le mot arnaqueur est interdit ici")
    _envoyer(cog, [message])
    message.delete.assert_not_awaited()
    assert (guild.id, membre.id) not in cog.incidents


def test_anti_spam_coupe_rien_ne_change():
    cog, guild, membre = _cog_complet({"antispam": 0})
    _envoyer(cog, [_reponse(guild, membre, i) for i in range(12)])
    assert (guild.id, membre.id) not in cog.incidents


def test_le_proprietaire_du_serveur_n_est_pas_vise():
    cog, guild, membre = _cog_complet({"antispam": 1})
    guild.owner_id = membre.id
    _envoyer(cog, [_reponse(guild, membre, i) for i in range(12)])
    assert (guild.id, membre.id) not in cog.incidents
