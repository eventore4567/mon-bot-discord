"""/setup : une configuration manifestement cassée n'est pas enregistrée.

Rôle au-dessus de SentriX, rôle géré par une intégration, salon où SentriX ne peut
pas écrire : la réponse est immédiate et courte, et la base n'est pas touchée.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import setup_control_center as setup_ui  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402


def _guild(*, manage_roles=True, bot_top=10):
    guild = Mock(spec=discord.Guild)
    me = Mock()
    me.guild_permissions = Mock(manage_roles=manage_roles, administrator=False)
    me.top_role = Mock(position=bot_top)
    me.top_role.__ge__ = lambda self, other: False
    guild.me = me
    return guild


def _role(position, *, managed=False, default=False):
    role = Mock(spec=discord.Role)
    role.position = position
    role.managed = managed
    role.mention = "@role"
    role.is_default = Mock(return_value=default)
    return role


def test_un_role_au_dessus_de_sentrix_est_refuse_pour_l_autorole():
    guild = _guild(bot_top=10)
    high = _role(20)
    high.__ge__ = lambda self, other: True
    assert "au-dessus" in setup_ui.validate_role_choice(guild, high, "autorole")
    low = _role(5)
    low.__ge__ = lambda self, other: False
    assert setup_ui.validate_role_choice(guild, low, "autorole") is None


def test_role_gere_par_integration_et_everyone_refuses():
    guild = _guild()
    managed = _role(1, managed=True)
    assert "intégration" in setup_ui.validate_role_choice(guild, managed, "mute_role")
    everyone = _role(0, default=True)
    assert "@everyone" in setup_ui.validate_role_choice(guild, everyone, "autorole")


def test_sans_gerer_les_roles_le_choix_est_refuse():
    guild = _guild(manage_roles=False)
    role = _role(1)
    role.__ge__ = lambda self, other: False
    assert "Gérer les rôles" in setup_ui.validate_role_choice(guild, role, "autorole")


def test_un_salon_sans_permission_d_ecrire_est_refuse():
    guild = _guild()
    channel = Mock(spec=discord.TextChannel)
    channel.mention = "#accueil"
    channel.permissions_for = Mock(return_value=Mock(view_channel=True, send_messages=False, embed_links=True, attach_files=True))
    reason = setup_ui.validate_channel_choice(guild, channel, "welcome_channel")
    assert "Envoyer des messages" in reason
    channel.permissions_for = Mock(return_value=Mock(view_channel=True, send_messages=True, embed_links=True, attach_files=False))
    assert setup_ui.validate_channel_choice(guild, channel, "welcome_channel") is None
    assert "Joindre des fichiers" in setup_ui.validate_channel_choice(guild, channel, "log_channel")


@pytest.mark.asyncio
async def test_le_select_refuse_sans_ecrire_en_base():
    guild = _guild()
    owner = SimpleNamespace(guild=guild, bot=SimpleNamespace(db=SimpleNamespace(set_guild_config=AsyncMock())), audit=AsyncMock(), refresh=AsyncMock())
    select = setup_ui.FieldRoleSelect.__new__(setup_ui.FieldRoleSelect)
    select.owner, select.field = owner, "autorole"
    high = _role(20)
    high.__ge__ = lambda self, other: True
    interaction = Mock()
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(type(select), "values", property(lambda self: [high])):
        await setup_ui.FieldRoleSelect.callback(select, interaction)
    owner.bot.db.set_guild_config.assert_not_awaited()
    owner.refresh.assert_not_awaited()
    assert court.await_args.kwargs.get("ephemere") is True
