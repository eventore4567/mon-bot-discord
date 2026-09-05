"""+clear et /clear mettaient 5,72 s à répondre.

Le chemin réel en production (cogs/help_clear_fix_v80.py) faisait, AVANT de
répondre à l'utilisateur :

1. une lecture complète de l'historique du salon ;
2. ``purge()``, qui **relit** exactement le même historique — un aller-retour en
   double ;
3. l'envoi du journal de purge, qui construit une transcription, la téléverse,
   puis traverse tout le transport de logs avec sa bannière — soit deux uploads
   de fichiers sur le chemin critique.

L'utilisateur attendait donc la totalité avant le moindre retour.

Ces tests verrouillent les deux corrections : plus de double lecture, et le
journal envoyé APRÈS la réponse — sans jamais perdre le journal ni son contenu.
"""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import help_clear_fix_v80 as v80  # noqa: E402


def _message(message_id: int, *, age_jours: int = 0) -> Mock:
    message = Mock(spec=discord.Message)
    message.id = message_id
    message.created_at = discord.utils.utcnow() - timedelta(days=age_jours)
    message.delete = AsyncMock()
    return message


def _contexte(messages: list, *, interaction=None) -> Mock:
    canal = Mock(spec=discord.TextChannel)
    canal.id = 999
    canal.mention = "<#999>"

    async def historique(limit=None):
        for message in messages[:limit]:
            yield message

    canal.history = historique
    canal.purge = AsyncMock(return_value=list(messages))
    canal.delete_messages = AsyncMock()

    ctx = Mock(spec=commands_context_spec())
    ctx.channel = canal
    ctx.interaction = interaction
    ctx.message = None
    ctx.author = Mock(id=1, mention="<@1>")
    ctx.guild = Mock(id=42)
    return ctx


def commands_context_spec():
    from discord.ext import commands

    return commands.Context


async def _executer(messages: list):
    """Joue _clear_v80 et renvoie (ordre des étapes, contexte)."""
    ctx = _contexte(messages)
    cog = Mock()
    cog.bot = Mock()
    ordre: list[str] = []

    async def faux_envoyer(*args, **kwargs):
        ordre.append("reponse")

    async def faux_log(bot, contexte, msgs, requested):
        ordre.append("journal")

    with patch.object(v80.panels, "envoyer", faux_envoyer), \
         patch.object(v80, "_send_clear_log", faux_log), \
         patch.object(v80, "_mark_suppressed", Mock()), \
         patch.object(v80, "_release_suppressed", AsyncMock()):
        await v80._clear_v80(cog, ctx, len(messages))
        # Laisse la tâche de journalisation s'exécuter.
        await asyncio.sleep(0.05)

    return ordre, ctx


async def _la_reponse_precede_le_journal():
    ordre, _ = await _executer([_message(i) for i in range(10)])
    assert ordre[0] == "reponse", f"la réponse doit partir en premier, ordre obtenu : {ordre}"
    assert "journal" in ordre, "le journal doit tout de même être envoyé"


def test_la_reponse_utilisateur_precede_le_journal_de_purge():
    asyncio.run(_la_reponse_precede_le_journal())


async def _pas_de_seconde_lecture_d_historique():
    messages = [_message(i) for i in range(10)]
    _, ctx = await _executer(messages)
    assert ctx.channel.purge.await_count == 0, "purge() relirait l'historique une seconde fois"
    ctx.channel.delete_messages.assert_awaited_once()


def test_les_messages_recents_sont_supprimes_sans_relire_l_historique():
    asyncio.run(_pas_de_seconde_lecture_d_historique())


async def _un_seul_message_est_supprime_directement():
    messages = [_message(1)]
    _, ctx = await _executer(messages)
    # delete_messages exige au moins deux messages : un seul passe par delete().
    ctx.channel.delete_messages.assert_not_awaited()
    messages[0].delete.assert_awaited_once()
    assert ctx.channel.purge.await_count == 0


def test_un_message_unique_ne_declenche_pas_de_purge():
    asyncio.run(_un_seul_message_est_supprime_directement())


async def _messages_anciens_repassent_par_purge():
    # Plus de 14 jours : la suppression groupée est refusée par Discord.
    messages = [_message(1, age_jours=20), _message(2)]
    _, ctx = await _executer(messages)
    ctx.channel.purge.assert_awaited_once()
    ctx.channel.delete_messages.assert_not_awaited()


def test_les_messages_de_plus_de_14_jours_utilisent_toujours_purge():
    asyncio.run(_messages_anciens_repassent_par_purge())


async def _echec_de_suppression_groupee_retombe_sur_purge():
    messages = [_message(i) for i in range(5)]
    ctx = _contexte(messages)
    ctx.channel.delete_messages = AsyncMock(side_effect=discord.HTTPException(Mock(status=400), "refus"))

    resultat = await v80._supprimer_messages(ctx, messages, len(messages))
    ctx.channel.purge.assert_awaited_once()
    assert resultat == messages, "le salon ne doit pas rester à moitié nettoyé"


def test_un_echec_de_suppression_groupee_retombe_sur_purge():
    asyncio.run(_echec_de_suppression_groupee_retombe_sur_purge())


async def _un_journal_en_erreur_ne_casse_pas_la_commande():
    bot = Mock()
    ctx = _contexte([_message(1)])
    with patch.object(v80, "_send_clear_log", AsyncMock(side_effect=RuntimeError("transport HS"))):
        # Ne doit pas lever : la purge a déjà eu lieu et l'utilisateur a été servi.
        await v80._journaliser_clear(bot, ctx, [], 1)


def test_un_journal_en_erreur_ne_remonte_pas_a_l_utilisateur():
    asyncio.run(_un_journal_en_erreur_ne_casse_pas_la_commande())
