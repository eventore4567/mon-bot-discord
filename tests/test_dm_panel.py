"""Message privé à un membre : commande +dm et panneau DM du Dashboard.

La diffusion à tout le serveur (+dmall, /dm/all, /dm/job) a été retirée. Il reste un seul
chemin d'envoi (cogs/direct_message.envoyer_prive), utilisé par la commande et par le
Dashboard, réservé au propriétaire du serveur ou de SentriX.
"""
from __future__ import annotations

import ast
import asyncio
import os
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import direct_message  # noqa: E402
from utils import access_matrix as M  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402
from web import dm_panel  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- dmall n'existe plus
def test_dmall_n_existe_plus_nulle_part():
    assert not (ROOT / "sentrix_broadcast_dmall_visual.py").exists()
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    extensions = next(
        ast.literal_eval(n.value) for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXTENSIONS" for t in n.targets)
    )
    assert "sentrix_broadcast_dmall_visual" not in extensions
    assert "cogs.direct_message" in extensions
    assert "dmall" not in M.KNOWN_COMMANDS
    assert "dmall" not in M.GUILD_OWNER_COMMANDS
    for source in ("cogs/direct_message.py", "web/dm_panel.py", "web/dashboard_unified_runtime_v2.py"):
        text = (ROOT / source).read_text(encoding="utf-8")
        assert "dm/all" not in text and "dmAll" not in text, source


def test_dm_est_reserve_au_proprietaire_du_serveur():
    assert "dm" in M.KNOWN_COMMANDS
    assert "dm" in M.GUILD_OWNER_COMMANDS
    assert M.access_tier("dm") == "guild-owner"


# ---------------------------------------------------------------- moteur unique
def _guild(proprietaire: int = 1) -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.id = 4242
    guild.name = "Serveur"
    guild.owner_id = proprietaire
    guild.icon = None
    return guild


def _membre(bot: bool = False) -> Mock:
    membre = Mock(spec=discord.Member)
    membre.id = 7
    membre.bot = bot
    membre.mention = "<@7>"
    membre.display_name = "Alice"
    return membre


@pytest.mark.asyncio
async def test_envoyer_prive_distingue_dm_ferme_et_echec():
    guild, membre = _guild(), _membre()
    with patch.object(panels, "envoyer", AsyncMock()) as envoyer:
        assert await direct_message.envoyer_prive(guild, membre, "salut") == "envoye"
        envoyer.assert_awaited_once()
    with patch.object(panels, "envoyer", AsyncMock(side_effect=discord.Forbidden(Mock(status=403), "fermé"))):
        assert await direct_message.envoyer_prive(guild, membre, "salut") == "dm_ferme"
    with patch.object(panels, "envoyer", AsyncMock(side_effect=discord.HTTPException(Mock(status=500), "panne"))):
        assert await direct_message.envoyer_prive(guild, membre, "salut") == "echec"


@pytest.mark.asyncio
async def test_la_commande_dm_fonctionne_et_repond_court():
    bot = SimpleNamespace(is_owner=AsyncMock(return_value=False))
    cog = direct_message.DirectMessage(bot)
    guild = _guild(proprietaire=1)
    ctx = SimpleNamespace(guild=guild, author=SimpleNamespace(id=1), interaction=None, send=AsyncMock())
    membre = _membre()
    with patch.object(direct_message, "envoyer_prive", AsyncMock(return_value="envoye")) as envoi:
        await direct_message.DirectMessage.dm.callback(cog, ctx, membre, message="  bonjour ")
    envoi.assert_awaited_once_with(guild, membre, "bonjour")
    assert ctx.send.await_args.kwargs["content"] == "Message privé envoyé à <@7>."


@pytest.mark.asyncio
async def test_la_commande_dm_refuse_un_administrateur_ordinaire_et_les_bots():
    bot = SimpleNamespace(is_owner=AsyncMock(return_value=False))
    cog = direct_message.DirectMessage(bot)
    ctx = SimpleNamespace(guild=_guild(proprietaire=1), author=SimpleNamespace(id=99), interaction=None, send=AsyncMock())
    with patch.object(direct_message, "envoyer_prive", AsyncMock()) as envoi:
        await direct_message.DirectMessage.dm.callback(cog, ctx, _membre(), message="x")
        envoi.assert_not_awaited()
        ctx2 = SimpleNamespace(guild=_guild(proprietaire=1), author=SimpleNamespace(id=1), interaction=None, send=AsyncMock())
        await direct_message.DirectMessage.dm.callback(cog, ctx2, _membre(bot=True), message="x")
        envoi.assert_not_awaited()


# ---------------------------------------------------------------- dashboard : autorisation
def _requete(session_user_id: int, methode: str = "POST") -> Mock:
    requete = Mock()
    requete.method = methode
    requete.app = {"bot": Mock()}
    requete.get = Mock(return_value={"user": {"id": str(session_user_id)}})
    return requete


async def _autorise(session_user_id: int, proprietaire: int, est_owner_bot: bool) -> bool:
    requete = _requete(session_user_id)
    requete.app["bot"].is_owner = AsyncMock(return_value=est_owner_bot)
    return await dm_panel._peut_ecrire(requete, _guild(proprietaire=proprietaire))


def test_le_proprietaire_du_serveur_est_autorise():
    assert asyncio.run(_autorise(1, 1, False)) is True


def test_le_proprietaire_de_sentrix_est_autorise():
    assert asyncio.run(_autorise(7, 1, True)) is True


def test_un_administrateur_ordinaire_est_refuse():
    assert asyncio.run(_autorise(99, 1, False)) is False


def test_une_session_sans_utilisateur_est_refusee():
    requete = _requete(0)
    requete.get = Mock(return_value={})
    assert asyncio.run(dm_panel._peut_ecrire(requete, _guild())) is False


def test_les_routes_dm_sont_reduites_au_message_individuel():
    from web import dashboard

    chemins = {chemin for _m, chemin, _h in dashboard.DM_PANEL_ROUTES}
    assert chemins == {"/api/guilds/{guild_id}/dm/apercu", "/api/guilds/{guild_id}/dm/user"}


def test_le_panneau_dm_ne_reimplemente_pas_le_moteur():
    source = (ROOT / "web/dm_panel.py").read_text(encoding="utf-8")
    assert "envoyer_prive(" in source
    assert "panels.envoyer(" not in source


# ---------------------------------------------------------------- interface unifiée
def _html() -> str:
    import sentrix_product_update
    from web import dashboard

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return dashboard.INDEX_HTML


def test_l_onglet_dm_est_servi_sans_diffusion_globale():
    html = _html()
    assert "['dm', 'Message privé']" in html
    assert "dm: renderDM" in html
    assert "async function renderDM()" in html
    for element in ("dmOneUser", "dmOneMessage", "dmPreview", "dmOneSend"):
        assert element in html, f"élément d'interface manquant : {element}"
    assert "/dm/apercu" in html and "/dm/user" in html
    assert "/dm/all" not in html and "/dm/job" not in html and "dmAll" not in html
    assert "discord.com/api" not in html


def test_l_envoi_est_neutralise_avant_le_premier_aller_retour():
    html = _html()
    bloc = html.split("$('dmOneSend').onclick = async () => {")[1].split("};")[0]
    assert bloc.index("b.disabled = true") < bloc.index("await gpost('/dm/user'")
