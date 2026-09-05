"""La racine `+giveaway` annoncée par le catalogue n'existait plus.

``cogs/command_catalog_cleanup.py`` fusionne six commandes ``giveaway-*`` vers une
racine ``giveaway``, exactement comme ``ticket``, ``security`` et ``setup``. Cette
racine venait de ``cogs/command_giveaway_center_v3.py``, supprimé par le commit
2a130d7 en même temps que d'authentiques modules morts. Le catalogue et l'aide
renvoyaient donc vers ``+giveaway``, qui répondait « commande inconnue », alors que
les six implémentations, elles, existaient toujours.

Elle est rétablie en dispatcher fin vers le moteur existant — pas en dupliquant la
logique, et pas en restaurant l'ancien fichier.

Le test le plus important ici est celui des permissions : ``ctx.invoke`` n'exécute
PAS les checks de la commande appelée. Une racine qui déléguerait sans porter ses
propres contrôles serait un contournement d'autorisation ouvert à tous.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

from discord.ext import commands  # noqa: E402

import main as bot_main  # noqa: E402
from cogs import giveaway_center  # noqa: E402


def _cog() -> giveaway_center.GiveawayCenter:
    return giveaway_center.GiveawayCenter(Mock())


def test_l_extension_est_chargee_apres_le_moteur():
    """L'ordre compte : le dispatcher délègue à des commandes de cogs.events."""
    extensions = list(bot_main.EXTENSIONS)
    assert "cogs.giveaway_center" in extensions, "la racine +giveaway ne serait pas installée"
    assert extensions.index("cogs.giveaway_center") > extensions.index("cogs.events")


def test_toutes_les_cibles_de_fusion_du_catalogue_sont_couvertes():
    """Chaque commande que le catalogue redirige doit avoir sa sous-commande."""
    from cogs.command_catalog_cleanup import GIVEAWAY_MERGED_COMMANDS

    couvertes = set(giveaway_center._CIBLES.values())
    manquantes = set(GIVEAWAY_MERGED_COMMANDS) - couvertes
    assert not manquantes, f"sous-commandes absentes du centre : {sorted(manquantes)}"


def test_chaque_sous_commande_sensible_porte_son_controle_d_acces():
    """ctx.invoke saute les checks de la cible : le dispatcher doit avoir les siens."""
    groupe = giveaway_center.GiveawayCenter.giveaway
    sensibles = {"create", "end", "reroll", "cancel", "blacklist", "unblacklist"}
    for sous in groupe.commands:
        if sous.name in sensibles:
            assert sous.checks, (
                f"+giveaway {sous.name} n'a aucun check : la racine deviendrait un "
                "contournement de permissions"
            )


def test_la_consultation_reste_ouverte():
    """`list` n'avait pas de check sur la commande historique : on ne durcit pas."""
    groupe = giveaway_center.GiveawayCenter.giveaway
    liste = next(c for c in groupe.commands if c.name == "list")
    assert not liste.checks


async def _delegue_vers_la_bonne_commande():
    cog = _cog()
    cible = Mock(name="giveaway-list")
    cog.bot.get_command = Mock(return_value=cible)
    ctx = Mock(spec=commands.Context)
    ctx.invoke = AsyncMock()

    await cog._deleguer(ctx, "list")

    cog.bot.get_command.assert_called_once_with("giveaway-list")
    ctx.invoke.assert_awaited_once_with(cible)


def test_la_delegation_appelle_bien_la_commande_historique():
    asyncio.run(_delegue_vers_la_bonne_commande())


async def _delegue_avec_arguments():
    cog = _cog()
    cible = Mock()
    cog.bot.get_command = Mock(return_value=cible)
    ctx = Mock(spec=commands.Context)
    ctx.invoke = AsyncMock()

    await cog._deleguer(ctx, "end", message_id="12345")
    ctx.invoke.assert_awaited_once_with(cible, message_id="12345")


def test_les_arguments_sont_transmis_tels_quels():
    asyncio.run(_delegue_avec_arguments())


async def _moteur_absent_repond_proprement():
    cog = _cog()
    cog.bot.get_command = Mock(return_value=None)
    ctx = Mock(spec=commands.Context)
    ctx.invoke = AsyncMock()

    envois = []

    async def faux_envoyer(destination, panneau, **kwargs):
        envois.append(panneau)

    original = giveaway_center.panels.envoyer
    giveaway_center.panels.envoyer = faux_envoyer
    try:
        await cog._deleguer(ctx, "create")
    finally:
        giveaway_center.panels.envoyer = original

    assert len(envois) == 1, "l'utilisateur doit être prévenu, pas laissé sans réponse"
    ctx.invoke.assert_not_awaited()


def test_un_moteur_non_charge_ne_provoque_pas_de_silence():
    asyncio.run(_moteur_absent_repond_proprement())


async def _pas_de_double_racine():
    bot = Mock()
    bot.get_cog = Mock(return_value=None)
    bot.get_command = Mock(return_value=Mock())  # une racine existe déjà
    bot.add_cog = AsyncMock()

    await giveaway_center.setup(bot)
    bot.add_cog.assert_not_awaited(), "ne jamais doubler une racine déjà fournie"


def test_le_centre_ne_double_jamais_une_racine_existante():
    asyncio.run(_pas_de_double_racine())
