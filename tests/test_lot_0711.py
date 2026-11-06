"""Retours des tests du 07/11/2026."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import automod as am  # noqa: E402


def test_tes_permissions_va_a_l_ia_et_pas_a_la_commande():
    from utils import ai_command_router as r

    commande = SimpleNamespace(qualified_name="permissions", aliases=[], clean_params={})
    bot = SimpleNamespace(walk_commands=lambda: [commande])
    assert r.natural_command_line(bot, "fais-moi la liste de tes permissions", "+", has_attachment=False) is None
    assert r.natural_command_line(bot, "fais permissions", "+", has_attachment=False) == "+permissions"


def test_la_raison_d_un_avertissement_de_suivi_est_lisible():
    from utils import sentrix_trace

    commande, arguments = sentrix_trace.suite_command("automod", "warn", 7, "SX-ABC")
    assert commande == "warn"
    assert "Comportement relevé par l'AutoMod (réf. SX-ABC)" in arguments
    assert "Suite de l'incident" not in arguments


def test_deux_avertissements_avant_le_mute_pour_le_spam():
    assert am.SPAM_PREMIER_PALIER == 1   # rappel, avertissement, puis mute


@pytest.mark.parametrize("texte", ["ntmmm", "slp", "t'es une slp", "ta grand mère c'est ma chienne"])
def test_les_insultes_ratees_le_07_11_sont_detectees(texte):
    from utils.moderation_dataset import MultilingualModerationDataset

    assert MultilingualModerationDataset().match(texte) is not None


def test_un_mot_interdit_passe_par_le_contexte_avant_toute_censure():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    bloc = source[source.index("        if word_applies:\n            # 07/11/2026"):]
    bloc = bloc[: bloc.index('"blacklist_word",')]
    assert "await self._insulte_selon_contexte(message) is False" in bloc
    assert "self._delete_and_timeout(" in bloc


def test_la_censure_n_utilise_plus_de_cases_blanches():
    assert am._censor_blacklist_word("salut con ça va", "con") == r"salut \*\*\* ça va"
    assert am._censor_links("vois https://x.y/z") == "vois *(lien retiré)*"


def test_une_ligne_de_log_groupee_donne_le_nom_du_salon():
    from cogs import v17_tickets_logs as v17

    embed = discord.Embed(title="Salon créé")
    embed.add_field(name="Salon", value="`général`")
    assert "`général`" in v17._line_from_embed(embed, None, None)


def test_les_mp_d_alerte_n_ont_plus_de_banniere_en_bas():
    vue = am.carte_alerte_admin(SimpleNamespace(name="Serveur"), SimpleNamespace(id=1, mention="<@1>"))
    assert vue.avec_banniere is False
    simple = am.carte_mp_simple("Titre", "Texte", 0xED4245)
    assert not any(isinstance(c, discord.ui.MediaGallery) for c in simple.children[0].children)


def _guild_regles(regles, *, manage_guild=True):
    me = SimpleNamespace(id=9, guild_permissions=SimpleNamespace(manage_guild=manage_guild))
    return SimpleNamespace(
        id=1, me=me, fetch_automod_rules=AsyncMock(return_value=regles),
        create_automod_rule=AsyncMock(),
    )


def _cog_conf(antimention):
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(db=SimpleNamespace(get_automod=AsyncMock(return_value={"antimention": antimention})))
    cog._native_policy_exemptions = AsyncMock(return_value=None)
    return cog


def test_la_regle_discord_anti_everyone_est_creee_quand_l_anti_mention_est_actif():
    guild = _guild_regles([])
    assert asyncio.run(_cog_conf(1)._sync_native_antieveryone_rule(guild)) is True
    kwargs = guild.create_automod_rule.await_args.kwargs
    assert kwargs["name"] == am.NATIVE_ANTIEVERYONE_RULE_NAME
    assert kwargs["trigger"].regex_patterns == [r"@(everyone|here)"]


def test_la_regle_est_retiree_quand_l_anti_mention_est_coupe():
    existante = SimpleNamespace(name=am.NATIVE_ANTIEVERYONE_RULE_NAME, creator_id=9, delete=AsyncMock())
    guild = _guild_regles([existante])
    assert asyncio.run(_cog_conf(0)._sync_native_antieveryone_rule(guild)) is True
    existante.delete.assert_awaited_once()
    guild.create_automod_rule.assert_not_awaited()


def test_sans_gerer_le_serveur_pas_de_regle():
    guild = _guild_regles([], manage_guild=False)
    assert asyncio.run(_cog_conf(1)._sync_native_antieveryone_rule(guild)) is False


def test_un_blocage_discord_anti_everyone_compte_pour_la_sanction():
    cog = am.AutoMod.__new__(am.AutoMod)
    membre = SimpleNamespace(id=5)
    salon = SimpleNamespace(id=3)
    guild = SimpleNamespace(get_member=lambda _u: membre, get_channel=lambda _c: salon)
    cog.bot = SimpleNamespace(get_guild=lambda _g: guild)
    cog._nom_regle_native = AsyncMock(return_value=am.NATIVE_ANTIEVERYONE_RULE_NAME)
    cog._sanction_everyone = AsyncMock(return_value="warn")
    execution = SimpleNamespace(
        action=SimpleNamespace(type=discord.AutoModRuleActionType.block_message),
        guild_id=1, rule_id=2, user_id=5, channel_id=3,
    )
    asyncio.run(cog.on_automod_action(execution))
    cog._sanction_everyone.assert_awaited_once_with(guild, membre, salon)
