"""Rôles d'arrivée multiples et variables de date — sans bot ni réseau."""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import discord

from cogs import control_center_v3
from utils import welcome_autoroles as wa


class FakeRole:
    def __init__(self, role_id, position, *, perms=0, managed=False, default=False):
        self.id = role_id
        self.position = position
        self.permissions = discord.Permissions(perms)
        self.managed = managed
        self._default = default
        self.mention = f"<@&{role_id}>"

    def is_default(self):
        return self._default

    def __ge__(self, other):
        return self.position >= other.position


def guild(bot_position=10, manage_roles=True):
    top = FakeRole(999, bot_position)
    perms = discord.Permissions(manage_roles=manage_roles)
    return SimpleNamespace(me=SimpleNamespace(top_role=top, guild_permissions=perms))


def test_un_role_ordinaire_est_accepte():
    assert wa.role_problem(guild(), FakeRole(1, 2)) is None


def test_mentionner_everyone_ne_bloque_pas():
    """Discord met cette permission dans tout rôle créé : la refuser casserait les rôles « Membre »."""
    assert wa.role_problem(guild(), FakeRole(1, 2, perms=discord.Permissions(mention_everyone=True).value)) is None


def test_roles_refuses():
    g = guild()
    assert "Administrateur" in wa.role_problem(g, FakeRole(1, 2, perms=discord.Permissions(administrator=True).value))
    assert "Bannir" in wa.role_problem(g, FakeRole(1, 2, perms=discord.Permissions(ban_members=True).value))
    assert "géré" in wa.role_problem(g, FakeRole(1, 2, managed=True))
    assert "@everyone" in wa.role_problem(g, FakeRole(1, 0, default=True))
    assert "au-dessus" in wa.role_problem(g, FakeRole(1, 10))
    assert "Gérer les rôles" in wa.role_problem(guild(manage_roles=False), FakeRole(1, 2))
    assert wa.role_problem(g, None) == "Ce rôle n'existe plus."


class FakeDB:
    def __init__(self, autorole=None):
        self.conf = {"autorole": autorole}
        self.rows: list[tuple[int, int, int]] = []

    async def get_guild_config(self, guild_id):
        return self.conf

    async def set_guild_config(self, guild_id, key, value):
        self.conf[key] = value

    async def execute(self, query, params=()):
        if query.startswith("DELETE FROM welcome_autoroles"):
            self.rows = [r for r in self.rows if r[0] != params[0]]
        elif query.startswith("INSERT INTO welcome_autoroles"):
            self.rows.append(tuple(params))

    async def fetchall(self, query, params=()):
        return [{"role_id": r[1]} for r in sorted(self.rows, key=lambda r: r[2]) if r[0] == params[0]]


def test_le_premier_role_reste_dans_guild_config():
    bot = SimpleNamespace(db=FakeDB())
    ids = asyncio.run(wa.save(bot, 1, [5, 6, 7]))
    assert ids == [5, 6, 7]
    assert bot.db.conf["autorole"] == 5
    assert asyncio.run(wa.configured_ids(bot, 1)) == [5, 6, 7]


def test_un_ancien_reglage_simple_est_lu_sans_migration():
    bot = SimpleNamespace(db=FakeDB(autorole=42))
    assert asyncio.run(wa.configured_ids(bot, 1)) == [42]


def test_doublons_et_limite():
    bot = SimpleNamespace(db=FakeDB())
    assert asyncio.run(wa.save(bot, 1, [5, 5, "6", None, 7, 8, 9, 10])) == [5, 6, 7, 8, 9]
    assert asyncio.run(wa.save(bot, 1, [])) == []
    assert bot.db.conf["autorole"] is None and asyncio.run(wa.configured_ids(bot, 1)) == []


def test_variables_de_date():
    created = dt.datetime(2020, 5, 1, tzinfo=dt.timezone.utc)
    joined = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)
    member = SimpleNamespace(
        mention="<@1>", name="nom", display_name="Affiché", created_at=created, joined_at=joined,
        guild=SimpleNamespace(name="Serveur", member_count=12),
    )
    text = control_center_v3.render_member_template("{created_at}|{joined_at}|{member_count}|{display_name}", member)
    assert text == f"<t:{int(created.timestamp())}:D>|<t:{int(joined.timestamp())}:D>|12|Affiché"


def test_date_d_arrivee_inconnue():
    member = SimpleNamespace(
        mention="<@1>", name="n", display_name="n", created_at=None, joined_at=None,
        guild=SimpleNamespace(name="S", member_count=1),
    )
    assert control_center_v3.render_member_template("{joined_at}", member) == "—"
