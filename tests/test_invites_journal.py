"""Suivi des invitations : arrivée journalisée, invitant jamais inventé.

Le suivi persistant existait déjà (table ``member_invites``, cache d'invitations,
comparaison des compteurs d'utilisation), mais l'arrivée n'était **jamais annoncée**
dans un salon : seule l'alerte « comptes suspects » partait. Le salon d'invitations
restait donc vide.

Deux règles priment et sont verrouillées ici :

1. **Ne jamais inventer un invitant.** Quand Discord ne permet pas de savoir —
   permission manquante, lien vanity, deux arrivées simultanées — le journal dit
   « Inconnu » au lieu d'attribuer l'arrivée à quelqu'un au hasard. Une fausse
   attribution serait pire que pas d'information du tout.
2. **Le salon n'est jamais codé en dur.** Le log passe par la route configurable
   « dossiers », que le Setup relie au salon voulu.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import invites as mod_invites  # noqa: E402


def _cog(breakdown: dict | None = None):
    bot = Mock()
    bot.db = Mock()
    bot.db.record_invite_join = AsyncMock()
    bot.db.mark_invite_left = AsyncMock()
    bot.db.get_invite_breakdown = AsyncMock(
        return_value=breakdown or {"credited": 7, "real": 7, "fake": 0, "left": 0, "bonus": 0, "total": 7}
    )
    return mod_invites.Invites(bot)


def _membre(identifiant: int = 55, *, bot: bool = False) -> Mock:
    membre = Mock(spec=discord.Member)
    membre.id = identifiant
    membre.bot = bot
    membre.created_at = discord.utils.utcnow()
    guild = Mock(spec=discord.Guild)
    guild.id = 4242
    guild.features = ()
    membre.guild = guild
    return membre


async def _journalise(inviter_id, code, breakdown=None):
    cog = _cog(breakdown)
    membre = _membre()
    envois = []

    async def faux_send_log(bot, guild, kind, embed, **kwargs):
        envois.append({"kind": kind, "embed": embed, "kwargs": kwargs})

    original = mod_invites.helpers.send_log
    mod_invites.helpers.send_log = faux_send_log
    try:
        await cog._journaliser_arrivee(membre, code, inviter_id)
    finally:
        mod_invites.helpers.send_log = original
    return envois


def _champs(embed) -> dict:
    # log_entry retire les emojis de tete des noms de champs.
    return {f.name: f.value for f in embed.fields}


def test_l_arrivee_part_dans_la_route_configurable():
    envois = asyncio.run(_journalise(inviter_id=9, code="abc123"))
    assert len(envois) == 1, "l'arrivée doit être journalisée"
    assert envois[0]["kind"] == "dossiers", "le salon passe par une route configurable"
    # Aucun identifiant de salon en dur nulle part.
    assert "channel" not in envois[0]["kwargs"]


def test_l_invitant_connu_est_affiche_avec_son_total():
    envois = asyncio.run(_journalise(inviter_id=9, code="abc123"))
    champs = _champs(envois[0]["embed"])
    assert "<@9>" in champs["Invité par"]
    assert "7" in champs["Total de l'invitant"]
    assert "abc123" in champs["Invitation utilisée"]


def test_un_invitant_inconnu_n_est_jamais_invente():
    """Le point le plus important : mieux vaut « Inconnu » qu'une fausse attribution."""
    envois = asyncio.run(_journalise(inviter_id=None, code=None))
    champs = _champs(envois[0]["embed"])
    assert champs["Invité par"] == "Inconnu"
    assert "Non attribué" in champs["Total de l'invitant"]
    assert champs["Invitation utilisée"] == "Inconnue"


def test_aucun_appel_de_comptage_quand_l_invitant_est_inconnu():
    cog = _cog()
    membre = _membre()

    async def faux_send_log(*a, **k):
        return None

    original = mod_invites.helpers.send_log
    mod_invites.helpers.send_log = faux_send_log
    try:
        asyncio.run(cog._journaliser_arrivee(membre, None, None))
    finally:
        mod_invites.helpers.send_log = original
    cog.bot.db.get_invite_breakdown.assert_not_awaited()


def test_la_cle_d_evenement_empeche_un_double_log():
    envois = asyncio.run(_journalise(inviter_id=9, code="abc"))
    cle = envois[0]["kwargs"].get("event_key")
    assert cle == "invite-join:4242:55", "une clé stable évite le double comptage d'un même join"


def test_un_journal_en_echec_ne_casse_pas_l_arrivee():
    """L'arrivée est déjà persistée : un salon injoignable ne doit rien interrompre."""
    cog = _cog()
    membre = _membre()

    async def send_log_casse(*a, **k):
        raise RuntimeError("salon injoignable")

    original = mod_invites.helpers.send_log
    mod_invites.helpers.send_log = send_log_casse
    try:
        asyncio.run(cog._journaliser_arrivee(membre, "abc", 9))  # ne doit pas lever
    finally:
        mod_invites.helpers.send_log = original


# ------------------------------------------------------------------ vanity
def _guild_vanity(features=("VANITY_URL",), uses=5, code="sentrix"):
    guild = Mock(spec=discord.Guild)
    guild.id = 4242
    guild.features = features
    vanity = Mock(spec=discord.Invite)
    vanity.code = code
    vanity.uses = uses
    vanity.inviter = None
    guild.vanity_invite = AsyncMock(return_value=vanity)
    return guild, vanity


def test_une_arrivee_par_lien_vanity_est_detectee():
    cog = _cog()
    guild, vanity = _guild_vanity(uses=5)
    cog.invite_cache[guild.id] = {"vanity:sentrix": 4}
    trouve = asyncio.run(cog._invitation_vanity(guild))
    assert trouve is vanity
    assert cog.invite_cache[guild.id]["vanity:sentrix"] == 5, "le compteur doit être mémorisé"


def test_un_vanity_inchange_n_est_pas_attribue():
    cog = _cog()
    guild, _ = _guild_vanity(uses=4)
    cog.invite_cache[guild.id] = {"vanity:sentrix": 4}
    assert asyncio.run(cog._invitation_vanity(guild)) is None


def test_un_serveur_sans_vanity_n_appelle_pas_l_api():
    cog = _cog()
    guild, _ = _guild_vanity(features=())
    assert asyncio.run(cog._invitation_vanity(guild)) is None
    guild.vanity_invite.assert_not_awaited()


def test_un_vanity_refuse_ne_leve_pas():
    cog = _cog()
    guild, _ = _guild_vanity()
    guild.vanity_invite = AsyncMock(side_effect=discord.Forbidden(Mock(status=403), "non"))
    assert asyncio.run(cog._invitation_vanity(guild)) is None


def test_un_bot_qui_rejoint_n_est_jamais_compte():
    cog = _cog()
    membre = _membre(bot=True)
    asyncio.run(cog.on_member_join(membre))
    cog.bot.db.record_invite_join.assert_not_awaited()
