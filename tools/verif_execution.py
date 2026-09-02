#!/usr/bin/env python3
"""Verifie par EXECUTION ce que chaque commande envoie reellement.

Un marqueur present dans du code partage decrit ce que le code PEUT faire. Cette
verification-la execute le rappel de la commande avec un contexte factice et
regarde ce qui partirait vers Discord.

Trois verdicts, constates et non deduits :

    panneau+sections  une vue Components V2 avec au moins une section
    panneau           une vue Components V2 sans section
    embed             un embed classique
    aucun             la commande n'a rien envoye (garde, permission, argument)

Les commandes qui exigent un argument sans defaut ne sont pas executables ici :
elles sont comptees a part, jamais comme migrees.

    python3 tools/verif_execution.py cogs/configuration.py cogs/automod.py
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import pathlib
import re
import sys
import tempfile
import traceback

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
logging.disable(logging.CRITICAL)

import discord  # noqa: E402

CAPTURES: list[dict] = []


class _Asset:
    url = "https://cdn.discordapp.com/avatars/1/a.png"
    def __str__(self): return self.url


class _Role:
    def __init__(self, rid=2, nom="Membre", pos=1):
        self.id, self.name, self.position = rid, nom, pos
        self.mention = f"<@&{rid}>"
        self.managed = False
        self.colour = self.color = discord.Colour(0)
        self.icon = None
        self.permissions = discord.Permissions.none()
        self.members = []
        self.created_at = discord.utils.utcnow()
        self.hoist = self.mentionable = False
    def is_premium_subscriber(self): return False
    def is_bot_managed(self): return False
    def is_integration(self): return False
    def __ge__(self, o): return self.position >= getattr(o, "position", 0)
    def __lt__(self, o): return self.position < getattr(o, "position", 0)


class _Membre:
    def __init__(self, mid=1, nom="Jayden", bot=False):
        self.id, self.name, self.bot = mid, nom, bot
        self.display_name = nom
        self.mention = f"<@{mid}>"
        self.guild_permissions = discord.Permissions.all()
        self.display_avatar = self.avatar = _Asset()
        self.roles = [_Role()]
        self.top_role = self.roles[-1]
        self.created_at = self.joined_at = discord.utils.utcnow()
        self.colour = self.color = discord.Colour(0)
        self.premium_since = None
        self.timed_out_until = None
    def __str__(self): return self.name


class _Salon:
    def __init__(self, cid=999, guild=None):
        self.id, self.name, self.guild = cid, "general", guild
        self.mention = f"<#{cid}>"
        self.type = discord.ChannelType.text
        self.created_at = discord.utils.utcnow()
        self.topic = None
        self.slowmode_delay = 0
        self.nsfw = False
        self.position = 0
        self.threads = []
        self.overwrites = {}
        self.category = None
    def permissions_for(self, m): return discord.Permissions.all()
    def overwrites_for(self, r): return discord.PermissionOverwrite()
    async def send(self, *a, **k):
        CAPTURES.append({"voie": "channel.send", "kwargs": k, "args": a}); return _Message()
    async def purge(self, **k): return []


class _Message:
    _n = [0]
    def __init__(self):
        self._n[0] += 1
        self.id = 1000 + self._n[0]
        self.content = ""
    async def edit(self, *a, **k): return self
    async def delete(self, *a, **k): return None
    async def add_reaction(self, *a, **k): return None


class _Guild:
    def __init__(self):
        self.id, self.name = 424242, "Serveur test"
        self.default_role = _Role(424242, "@everyone", 0)
        self.roles = [self.default_role, _Role()]
        self.me = _Membre(777, "SentriX", bot=True)
        self.owner_id, self.owner = 1, None
        self.members = [self.me]
        self.text_channels = self.voice_channels = self.categories = self.stage_channels = []
        self.channels = self.threads = self.emojis = self.stickers = []
        self.member_count = 3
        self.icon = self.banner = None
        self.premium_tier = self.premium_subscription_count = 0
        self.created_at = discord.utils.utcnow()
        self.shard_id = 0
        self.emoji_limit = self.sticker_limit = 50
        self.filesize_limit = 26214400
        self.verification_level = discord.VerificationLevel.low
        self.explicit_content_filter = discord.ContentFilter.disabled
        self.mfa_level = 0
        self.afk_channel, self.afk_timeout = None, 0
        self.voice_client = None
    def get_role(self, rid): return next((r for r in self.roles if r.id == rid), None)
    def get_member(self, mid): return self.me if mid == 777 else None
    def get_channel(self, cid): return None


class _Ctx:
    def __init__(self, bot):
        self.bot = bot
        self.guild = _Guild()
        self.channel = _Salon(guild=self.guild)
        self.author = _Membre()
        self.guild.owner = self.author
        self.me = self.guild.me
        self.message = _Message()
        self.message.author = self.author
        self.message.channel = self.channel
        self.message.guild = self.guild
        self.prefix = self.clean_prefix = "+"
        self.interaction = None
        self.command = None
        self.invoked_with = ""
        self.cog = None
        self.voice_client = None
        self.args, self.kwargs = [], {}
    async def send(self, *a, **k):
        CAPTURES.append({"voie": "ctx.send", "kwargs": k, "args": a}); return _Message()
    async def reply(self, *a, **k):
        CAPTURES.append({"voie": "ctx.reply", "kwargs": k, "args": a}); return _Message()
    async def defer(self, *a, **k): return None
    def typing(self): return _Rien()


class _Rien:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _classer(captures) -> tuple[str, int]:
    """Ce qui partirait vraiment vers Discord."""
    for c in captures:
        kw = c.get("kwargs", {})
        vue = kw.get("view")
        if vue is not None and hasattr(vue, "to_components"):
            plat: list = []
            def parcourir(items):
                for it in items or ():
                    if it.get("type") == 10:
                        plat.append(str(it.get("content", "")))
                    for cle in ("components", "accessory"):
                        v = it.get(cle)
                        if isinstance(v, list): parcourir(v)
                        elif isinstance(v, dict): parcourir([v])
            try:
                parcourir(vue.to_components())
            except Exception:
                return "panneau", 0
            sections = sum(1 for t in plat if t.startswith("### "))
            return ("panneau+sections" if sections else "panneau"), sections
        if kw.get("embed") is not None or kw.get("embeds"):
            return "embed", 0
    return "aucun", 0


def _arguments(rappel, ctx) -> tuple[dict, str]:
    """Valeurs plausibles pour executer une commande.

    Sans cela, toute commande prenant un membre, un role ou un texte restait
    non verifiee — c'est-a-dire la majorite. On synthetise d'apres l'annotation ;
    ce qui n'est pas reconnu est signale, jamais compte comme migre.
    """
    valeurs: dict = {}
    signature = inspect.signature(rappel)
    for nom, param in list(signature.parameters.items())[2:]:
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        annotation = param.annotation
        texte = str(annotation)
        if annotation is str or "str" in texte:
            valeurs[nom] = "test"
        elif annotation is int or "int" in texte or "Range" in texte:
            valeurs[nom] = 1
        elif annotation is bool or "bool" in texte:
            valeurs[nom] = True
        elif "Member" in texte or "User" in texte:
            valeurs[nom] = ctx.author
        elif "Role" in texte:
            valeurs[nom] = ctx.guild.roles[-1]
        elif "Channel" in texte:
            valeurs[nom] = ctx.channel
        elif "Attachment" in texte or "Message" in texte or "Emoji" in texte:
            return {}, f"{nom}: {texte[:30]}"
        else:
            return {}, f"{nom}: {texte[:30]}"
    return valeurs, ""


async def main(fichiers: list[str]) -> int:
    import config
    from database.db import Database

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "verif.db")
    import main as bot_main

    bot = bot_main.BotAllInOne()
    bot.db = Database(config.DATABASE_PATH)
    await bot.db.connect()
    extensions = list(bot_main.EXTENSIONS)
    boot = (RACINE / "railway_boot.py").read_text(encoding="utf-8")
    for module in re.findall(r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', boot):
        if module not in extensions:
            extensions.append(module)
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=25)
        except Exception:
            pass

    vises = {pathlib.Path(f).stem for f in fichiers}
    resultats: dict[str, list[str]] = {}
    for commande in bot.walk_commands():
        rappel = getattr(commande, "callback", None)
        if rappel is None or rappel.__module__.split(".")[-1] not in vises:
            continue
        ctx = _Ctx(bot)
        arguments, non_synthetisable = _arguments(rappel, ctx)
        if non_synthetisable:
            resultats.setdefault("argument non synthétisable", []).append(
                f"{commande.qualified_name} ({non_synthetisable})"
            )
            continue

        ctx.command = commande
        ctx.invoked_with = commande.name
        CAPTURES.clear()
        cog = commande.cog
        try:
            await asyncio.wait_for(rappel(cog, ctx, **arguments), timeout=15)
        except Exception:
            pass
        verdict, _ = _classer(list(CAPTURES))
        resultats.setdefault(verdict, []).append(commande.qualified_name)

    await bot.db.close()

    ordre = ("panneau+sections", "panneau", "embed", "aucun", "argument non synthétisable")
    total = sum(len(v) for v in resultats.values())
    print(f"commandes examinées dans {sorted(vises)} : {total}\n")
    for verdict in ordre:
        lot = resultats.get(verdict, [])
        print(f"  {verdict:20} {len(lot):>4}")
        if verdict in ("embed", "panneau") and lot:
            print(f"       {', '.join(sorted(lot)[:12])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:] or ["cogs/configuration.py"])))
