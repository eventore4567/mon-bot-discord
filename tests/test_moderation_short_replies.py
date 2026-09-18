"""Modération : réponses courtes, déduplication et implémentation unique de +clear.

Avant cette refonte :
- chaque sanction répondait par un panneau complet (bannière + fiche) DANS le salon de
  la commande, en plus du même panneau dans les logs ;
- la déduplication des doubles clics vivait dans un wrapper générique
  (cogs/v17_moderation_security) posé APRÈS la construction des commandes slash, ce qui
  faisait diverger le callback `/` du callback `+` ;
- +clear avait trois implémentations concurrentes (cogs/moderation.py, help_clear_fix_v80,
  utils/sentrix_runtime._patch_clear), la dernière posée gagnant sans journal.

Désormais : une ligne de texte dans le salon, la fiche complète dans les logs, et une
seule implémentation par commande dans cogs/moderation.py.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

from cogs import moderation as moderation_module  # noqa: E402
from cogs import runtime_consistency_v57, v17_moderation_security  # noqa: E402
from cogs.moderation import Moderation  # noqa: E402
from utils import log_service, sentrix_panels as panels  # noqa: E402


def _cog() -> Moderation:
    cog = Moderation.__new__(Moderation)
    cog.bot = Mock()
    cog._recent_sanctions = {}
    return cog


def _ctx(*, interaction=None, guild_id: int = 42) -> Mock:
    ctx = Mock(spec=commands.Context)
    ctx.guild = Mock(id=guild_id)
    ctx.author = Mock(id=1, mention="<@1>")
    ctx.interaction = interaction
    ctx.message = None
    channel = Mock(spec=discord.TextChannel)
    channel.id = 999
    channel.name = "général"
    channel.mention = "<#999>"
    ctx.channel = channel
    return ctx


# ------------------------------------------------------------------ dédoublonnage

def test_double_sanction_bloquee_dans_la_fenetre_puis_autorisee():
    cog = _cog()
    ctx = _ctx()
    assert cog._sanction_duplicate(ctx, "ban", 7) is False
    assert cog._sanction_duplicate(ctx, "ban", 7) is True
    # Une autre cible ou une autre action n'est pas concernée.
    assert cog._sanction_duplicate(ctx, "ban", 8) is False
    assert cog._sanction_duplicate(ctx, "kick", 7) is False
    # Un autre serveur non plus.
    assert cog._sanction_duplicate(_ctx(guild_id=43), "ban", 7) is False


def test_dedoublonnage_expire_apres_la_fenetre():
    cog = _cog()
    ctx = _ctx()
    cog._sanction_duplicate(ctx, "warn", 7)
    cog._recent_sanctions[(42, "warn", 7)] -= Moderation.SANCTION_DUPLICATE_TTL + 1
    assert cog._sanction_duplicate(ctx, "warn", 7) is False


def test_les_wrappers_externes_de_sanction_sont_retires():
    """Ni v17 ni v57 ne remplacent plus les callbacks : plus de divergence + / possible."""
    assert "_sentrix_v17_dedupe" not in inspect.getsource(v17_moderation_security)
    assert "_install_mute_duration_compat" not in inspect.getsource(runtime_consistency_v57)
    from cogs import help_clear_fix_v80
    from utils import sentrix_runtime
    assert "_clear_v80" not in inspect.getsource(help_clear_fix_v80)
    assert "_patch_clear" not in inspect.getsource(sentrix_runtime)


# ------------------------------------------------------------------ durée naturelle

def test_mute_accepte_une_duree_francaise_en_deux_mots():
    assert Moderation._normalise_prefix_duration("10", "minutes") == ("10 minutes", "Aucune raison")
    assert Moderation._normalise_prefix_duration("2", "heures spam répété") == ("2 heures", "spam répété")
    assert Moderation._normalise_prefix_duration("10m", "spam") == ("10m", "spam")


# ------------------------------------------------------------------ réponses courtes

@pytest.mark.asyncio
async def test_ban_repond_par_une_ligne_et_journalise_la_fiche_complete():
    cog = _cog()
    cog._ack = AsyncMock()
    cog._get_sanction_dm_template = AsyncMock(return_value=None)
    cog.log_sanction = AsyncMock(return_value=discord.Embed(title="fiche"))
    ctx = _ctx()
    membre = Mock(spec=discord.Member)
    membre.id = 7
    membre.mention = "<@7>"
    outcome = SimpleNamespace(executed=True, hierarchy_error=None, case_number=12)

    with patch.object(moderation_module.moderation_service, "ban", AsyncMock(return_value=outcome)), \
         patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(panels, "envoyer", AsyncMock()) as envoyer:
        await Moderation.ban.callback(cog, ctx, membre, raison="spam")

    cog.log_sanction.assert_awaited_once()
    court.assert_awaited_once()
    assert court.await_args.args[1] == "<@7> a été banni."
    envoyer.assert_not_awaited()


@pytest.mark.asyncio
async def test_refus_hierarchie_est_une_erreur_courte_ephemere():
    cog = _cog()
    cog._ack = AsyncMock()
    cog._get_sanction_dm_template = AsyncMock(return_value=None)
    cog.log_sanction = AsyncMock()
    ctx = _ctx()
    membre = Mock(spec=discord.Member)
    membre.id = 7
    membre.mention = "<@7>"
    outcome = SimpleNamespace(executed=False, hierarchy_error="Ce membre est au-dessus de vous.")

    with patch.object(moderation_module.moderation_service, "kick", AsyncMock(return_value=outcome)), \
         patch.object(panels, "texte_court", AsyncMock()) as court:
        await Moderation.kick.callback(cog, ctx, membre, raison="x")

    cog.log_sanction.assert_not_awaited()
    assert court.await_args.args[1] == "Ce membre est au-dessus de vous."
    assert court.await_args.kwargs.get("ephemere") is True


@pytest.mark.asyncio
async def test_second_appel_immediat_ne_sanctionne_pas_deux_fois():
    cog = _cog()
    cog._ack = AsyncMock()
    cog._get_sanction_dm_template = AsyncMock(return_value=None)
    cog.log_sanction = AsyncMock(return_value=discord.Embed())
    ctx = _ctx()
    membre = Mock(spec=discord.Member)
    membre.id = 7
    membre.mention = "<@7>"
    outcome = SimpleNamespace(executed=True, hierarchy_error=None, case_number=1)
    service = AsyncMock(return_value=outcome)

    with patch.object(moderation_module.moderation_service, "warn", service), \
         patch.object(panels, "texte_court", AsyncMock()):
        cog.bot.db.get_guild_config = AsyncMock(return_value=None)
        outcome.role_assigned = False
        outcome.role_error = None
        outcome.total_warnings = 1
        outcome.auto_ban_triggered = False
        await Moderation.warn.callback(cog, ctx, membre, raison="a")
        await Moderation.warn.callback(cog, ctx, membre, raison="a")

    assert service.await_count == 1


# ------------------------------------------------------------------ texte_court

@pytest.mark.asyncio
async def test_texte_court_ne_notifie_jamais_et_suit_la_surface():
    ctx = SimpleNamespace(interaction=None, send=AsyncMock())
    await panels.texte_court(ctx, "<@7> a été banni.", supprimer_apres=4)
    kwargs = ctx.send.await_args.kwargs
    assert kwargs["content"] == "<@7> a été banni."
    assert kwargs["allowed_mentions"].users is False
    assert kwargs["delete_after"] == 4.0

    response = Mock(spec=discord.InteractionResponse)
    response.is_done.return_value = True
    parent = SimpleNamespace(followup=SimpleNamespace(send=AsyncMock()))
    response._parent = parent
    await panels.texte_court(response, "ok", ephemere=True)
    assert parent.followup.send.await_args.kwargs["ephemeral"] is True


# ------------------------------------------------------------------ clear

def _message(message_id: int, *, age_jours: int = 0) -> Mock:
    message = Mock(spec=discord.Message)
    message.id = message_id
    message.created_at = discord.utils.utcnow() - timedelta(days=age_jours)
    message.delete = AsyncMock()
    message.content = f"m{message_id}"
    message.author = Mock(display_name="a", id=5)
    message.attachments = []
    return message


def _clear_ctx(messages: list, *, interaction=None) -> Mock:
    ctx = _ctx(interaction=interaction)

    async def historique(limit=None):
        for message in messages[:limit]:
            yield message

    ctx.channel.history = historique
    ctx.channel.purge = AsyncMock(return_value=list(messages))
    ctx.channel.delete_messages = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_clear_repond_avant_le_journal_marque_les_purges_et_supprime_sans_relire():
    cog = _cog()
    messages = [_message(i) for i in range(1, 11)]
    ctx = _clear_ctx(messages)
    ordre: list[str] = []

    async def faux_texte(*args, **kwargs):
        ordre.append("reponse")

    async def faux_log(contexte, msgs, *, requested):
        ordre.append("journal")

    with patch.object(panels, "texte_court", faux_texte), patch.object(cog, "_send_clear_log", faux_log):
        await Moderation.clear.callback(cog, ctx, 10)
        await asyncio.sleep(0.05)

    assert ordre == ["reponse", "journal"]
    ctx.channel.delete_messages.assert_awaited_once()
    ctx.channel.purge.assert_not_awaited()
    assert all(log_service.is_purged(m.id) for m in messages)


@pytest.mark.asyncio
async def test_clear_un_message_ou_trop_vieux():
    cog = _cog()
    cog._send_clear_log = AsyncMock()
    seul = [_message(1)]
    with patch.object(panels, "texte_court", AsyncMock()):
        ctx = _clear_ctx(seul)
        await Moderation.clear.callback(cog, ctx, 1)
    seul[0].delete.assert_awaited_once()
    ctx.channel.delete_messages.assert_not_awaited()

    vieux = [_message(2, age_jours=20), _message(3)]
    ctx = _clear_ctx(vieux)
    with patch.object(panels, "texte_court", AsyncMock()):
        await Moderation.clear.callback(cog, ctx, 2)
    ctx.channel.purge.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_slash_est_ephemere_et_prefixe_temporaire():
    cog = _cog()
    cog._send_clear_log = AsyncMock()
    interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: False, defer=AsyncMock()))
    ctx = _clear_ctx([_message(1), _message(2)], interaction=interaction)
    with patch.object(panels, "texte_court", AsyncMock()) as court:
        await Moderation.clear.callback(cog, ctx, 2)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    assert court.await_args.kwargs.get("ephemere") is True
    assert court.await_args.args[1] == "2 message(s) supprimé(s)."

    ctx = _clear_ctx([_message(1), _message(2), _message(3)])
    ctx.message = SimpleNamespace(id=3)
    with patch.object(panels, "texte_court", AsyncMock()) as court:
        await Moderation.clear.callback(cog, ctx, 2)
    # Le message de commande est exclu du compte ; la confirmation est temporaire.
    assert court.await_args.args[1] == "2 message(s) supprimé(s)."
    assert court.await_args.kwargs.get("supprimer_apres") == 4


@pytest.mark.asyncio
async def test_un_journal_en_erreur_ne_remonte_pas_a_l_utilisateur():
    cog = _cog()
    cog._send_clear_log = AsyncMock(side_effect=RuntimeError("transport HS"))
    ctx = _clear_ctx([_message(1)])
    await cog._log_clear_safely(ctx, [], 1)  # ne lève pas


def test_les_logs_ignorent_les_messages_purges():
    log_service.mark_purged([111, 112])
    assert log_service.is_purged(111)
    assert not log_service.is_purged(113)
    log_service._purged_message_ids[112] = 0.0  # expiré
    assert not log_service.is_purged(112)
