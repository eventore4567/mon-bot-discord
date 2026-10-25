"""Le piège honeypot ne vise jamais le propriétaire du bot, et un softban sans
ban posé ne plante pas (mesuré le 25/10 : 3 « Unknown Ban » en production)."""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import discord

from cogs import security_verification_v71 as module

SALON_PIEGE = 77


class _Guild:
    def __init__(self):
        self.id = 1
        self.owner_id = 999
        self.me = SimpleNamespace(top_role=10)
        self.bans, self.unbans = [], []

    async def ban(self, member, **_):
        self.bans.append(member.id)

    async def unban(self, member, **_):
        self.unbans.append(member.id)
        response = SimpleNamespace(status=404, reason="Not Found")
        raise discord.NotFound(response, {"code": 10026, "message": "Unknown Ban"})


class _Membre(discord.Member):
    # discord.Member expose ces attributs en propriétés : on les surcharge.
    id = 42
    bot = False
    mention = "<@42>"
    top_role = 1
    roles = []
    guild_permissions = discord.Permissions.none()

    def __init__(self, guild):
        self.guild = guild


def _scenario(monkeypatch, *, proprietaire):
    guild = _Guild()
    membre = _Membre(guild)

    async def is_owner(_user):
        return proprietaire

    bot = SimpleNamespace(user=SimpleNamespace(id=1000), is_owner=is_owner, get_cog=lambda _name: None)
    runtime = module.SecurityVerificationRuntimeV71(bot)

    async def actif(*_args):
        return True

    async def conf_piege(_guild_id):
        return {"trap_channel_id": SALON_PIEGE}

    async def reglages(_bot, _guild_id):
        return {"honeypot_enabled": True, "honeypot_delete_message": False,
                "honeypot_action": "softban", "honeypot_mute_minutes": 10}

    from cogs import setup_v2_core as core
    monkeypatch.setattr(core, "module_enabled", actif)
    monkeypatch.setattr(runtime, "_legacy_config", conf_piege)
    monkeypatch.setattr(runtime, "_staff_bypass", lambda *_args: False)
    monkeypatch.setattr(module, "settings", reglages)

    message = SimpleNamespace(guild=guild, author=membre, channel=SimpleNamespace(id=SALON_PIEGE))
    asyncio.run(runtime.on_message(message))
    return guild


def test_proprietaire_du_bot_jamais_sanctionne(monkeypatch):
    guild = _scenario(monkeypatch, proprietaire=True)
    assert guild.bans == [] and guild.unbans == []


def test_softban_sans_ban_pose_ne_plante_pas(monkeypatch, caplog):
    guild = _scenario(monkeypatch, proprietaire=False)
    assert guild.bans == [42] and guild.unbans == [42]
    assert "sanction honeypot impossible" not in caplog.text
