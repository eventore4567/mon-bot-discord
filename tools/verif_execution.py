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
    def is_animated(self): return False
    async def read(self): return b"\x89PNG\r\n\x1a\n"
    def with_size(self, *a, **k): return self
    def with_format(self, *a, **k): return self
    def with_static_format(self, *a, **k): return self
    def replace(self, *a, **k): return self

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
    def is_default(self): return self.id == 424242
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
        self.voice = None
        self.guild = None  # renseigne par _Ctx
        self.nick = None
        self.status = discord.Status.online
        self.activities = ()
    def __str__(self): return self.name
    async def add_roles(self, *a, **k): return None
    async def remove_roles(self, *a, **k): return None
    async def edit(self, *a, **k): return None
    async def kick(self, *a, **k): return None
    async def ban(self, *a, **k): return None
    async def timeout(self, *a, **k): return None
    async def send(self, *a, **k):
        CAPTURES.append({"voie": "dm.send", "kwargs": k, "args": a}); return _Message()


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
        self.text_channels = []
        self.voice_channels = []
        self.members = []
    def permissions_for(self, m): return discord.Permissions.all()
    def overwrites_for(self, r): return discord.PermissionOverwrite()
    async def send(self, *a, **k):
        # Le salon de la COMMANDE est visible par l'utilisateur : +suggest, +announce
        # et +shoppanel y publient leur livrable. Un autre salon est un journal.
        voie = "ctx.channel.send" if getattr(self, "est_salon_courant", False) else "channel.send"
        CAPTURES.append({"voie": voie, "kwargs": k, "args": a}); return _Message()
    async def purge(self, **k): return []
    async def flatten(self): return []
    async def fetch(self, *a, **k): return _Message()
    def history(self, **k):
        # Certaines commandes lisent l'historique avant de repondre (+clear). Sans
        # lui, elles echouaient avant l'envoi et la mesure etait fausse.
        async def _vide():
            for _ in ():
                yield None
        return _vide()
    async def fetch_message(self, *a, **k): return _Message()
    async def set_permissions(self, *a, **k): return None
    async def edit(self, *a, **k): return None


class _Message:
    guild = None
    channel = None
    _n = [0]
    def __init__(self):
        self._n[0] += 1
        self.id = 1000 + self._n[0]
        self.content = ""
    async def edit(self, *a, **k): return self
    async def delete(self, *a, **k): return None
    async def add_reaction(self, *a, **k): return None


class _Reponse404:
    status = 404
    reason = "Not Found"


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

    async def fetch_members(self, *a, **k):
        """Itere les membres comme le fait la vraie passerelle."""
        for membre in self.members:
            yield membre
        self.afk_channel, self.afk_timeout = None, 0
        self.voice_client = None
        self.system_channel = None
        self.rules_channel = None
        self.features = []
        self.premium_subscribers = []
    def get_role(self, rid): return next((r for r in self.roles if r.id == rid), None)
    def get_member(self, mid): return self.me if mid == 777 else None
    def get_channel(self, cid): return None
    async def create_role(self, **k): return _Role(99, k.get("name", "Nouveau"), 2)
    async def create_category(self, *a, **k): return _Salon(998, self)
    async def create_text_channel(self, *a, **k): return _Salon(997, self)
    async def create_voice_channel(self, *a, **k): return _Salon(996, self)
    async def create_custom_emoji(self, *a, **k):
        emoji = _Role(88, k.get("name", "emoji"), 0)
        emoji.url = "https://cdn.discordapp.com/emojis/88.png"
        emoji.animated = False
        return emoji
    async def fetch_ban(self, *a, **k): raise discord.NotFound(_Reponse404(), "inconnu")
    async def bans(self, *a, **k): return []
    async def fetch_member(self, mid): return self.me
    def get_member_named(self, nom): return None


class _Reponse:
    def is_done(self): return False
    async def send_message(self, *a, **k):
        CAPTURES.append({"voie": "ctx.send", "kwargs": k, "args": a})
    async def defer(self, *a, **k): return None
    async def edit_message(self, *a, **k):
        CAPTURES.append({"voie": "ctx.send", "kwargs": k, "args": a})
    async def send_modal(self, *a, **k): return None


class _Followup:
    async def send(self, *a, **k):
        CAPTURES.append({"voie": "ctx.send", "kwargs": k, "args": a}); return _Message()


class _Ctx:
    def __init__(self, bot):
        self.bot = bot
        self.guild = _Guild()
        self.channel = _Salon(guild=self.guild)
        self.channel.est_salon_courant = True
        self.author = _Membre()
        self.guild.owner = self.author
        self.me = self.guild.me
        self.author.guild = self.guild
        self.guild.me.guild = self.guild
        self.message = _Message()
        self.message.attachments = []
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
    # Certaines commandes testent `isinstance(target, commands.Context)` et, faute
    # d'en etre un, traitent le contexte comme une Interaction. On expose donc les
    # deux surfaces : ce qui compte est ce que l'utilisateur recevrait.
    @property
    def response(self): return _Reponse()
    @property
    def followup(self): return _Followup()
    async def invoke(self, commande, *a, **k):
        rappel = getattr(commande, "callback", commande)
        return await rappel(getattr(commande, "cog", None), self, *a, **k)
    @property
    def invoked_subcommand(self): return None
    @property
    def valid(self): return True


class _Rien:
    """Objet neutre : `async with ctx.typing()` ET `await ctx.typing()` existent
    tous les deux dans le depot. Sans les deux formes, 21 commandes echouaient
    avant d'envoyer quoi que ce soit, et paraissaient donc non migrees."""
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def __await__(self):
        async def _rien(): return self
        return _rien().__await__()


# Un envoi vers `channel.send` peut viser un AUTRE salon que celui de la commande —
# un journal, une annonce. Les journaux gardent volontairement leur rendu grand
# format : les compter comme la reponse de la commande donnerait un faux negatif.
VOIES_REPONSE = ("ctx.send", "ctx.reply", "ctx.channel.send")


DERNIERE_VUE = ""


def _classer(captures) -> tuple[str, int]:
    """Ce que l'UTILISATEUR verrait, par ordre de proximite.

    1. une reponse directe (ctx.send / ctx.reply, ou la surface d'interaction) ;
    2. sinon, une publication dans le salon de la commande — +suggest, +announce
       et +shoppanel y deposent leur livrable ;
    3. jamais un envoi vers un AUTRE salon : c'est un journal, et les journaux
       gardent volontairement leur format grand large.
    """
    directes = [c for c in captures if c.get("voie") in ("ctx.send", "ctx.reply")]
    salon = [c for c in captures if c.get("voie") in ("ctx.channel.send", "dm.send")]
    retenues = directes or salon
    if not retenues:
        return "aucun", 0

    # Un embed visible reste un embed, MEME accompagne d'une vue : une View
    # classique porte des boutons a cote du message, elle n'est pas le message.
    # Seule une LayoutView est le corps compose. Confondre les deux comptait
    # `+aisetup` (embed + AiSetupView) comme migre.
    for c in retenues:
        kw = c.get("kwargs", {})
        if kw.get("embed") is not None or kw.get("embeds"):
            vue = kw.get("view")
            global DERNIERE_VUE
            DERNIERE_VUE = type(vue).__name__ if vue is not None else ""
            return "embed", 0

    for c in retenues:
        kw = c.get("kwargs", {})
        vue = kw.get("view")
        if isinstance(vue, discord.ui.LayoutView):
            plat: list = []

            def parcourir(items):
                for it in items or ():
                    if it.get("type") == 10:
                        plat.append(str(it.get("content", "")))
                    for cle in ("components", "accessory"):
                        v = it.get(cle)
                        if isinstance(v, list):
                            parcourir(v)
                        elif isinstance(v, dict):
                            parcourir([v])

            try:
                parcourir(vue.to_components())
            except Exception:
                return "panneau", 0
            sections = sum(1 for t in plat if t.startswith("### "))
            return ("panneau+sections" if sections else "panneau"), sections

    # Reste du texte nu : +say repete le message d'un membre, l'IA rend sa reponse
    # en texte. Les habiller les denaturerait — c'est un choix, pas un manque.
    for c in retenues:
        if c.get("args") or c.get("kwargs", {}).get("content"):
            return "texte volontaire", 0
    return "aucun", 0


def _arguments(rappel, ctx) -> tuple[dict, str]:
    """Valeurs plausibles pour executer une commande.

    Sans cela, toute commande prenant un membre, un role ou un texte restait
    non verifiee — c'est-a-dire la majorite. On synthetise d'apres l'annotation ;
    ce qui n'est pas reconnu est signale, jamais compte comme migre.
    """
    valeurs: dict = {}
    signature = inspect.signature(rappel)
    parametres = list(signature.parameters.items())
    depart = 2 if parametres and parametres[0][0] in ("self", "cog", "_self", "cog_self") else 1
    for nom, param in parametres[depart:]:
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        annotation = param.annotation
        texte = str(annotation)
        # Greedy[X] attend une LISTE : passer une valeur seule fait echouer
        # l'iteration dans la commande (« _Role object is not iterable »).
        if "Greedy" in texte:
            if "Member" in texte or "User" in texte:
                valeurs[nom] = [ctx.author]
            elif "Role" in texte:
                valeurs[nom] = [ctx.guild.roles[-1]]
            elif "Channel" in texte:
                valeurs[nom] = [ctx.channel]
            else:
                valeurs[nom] = ["test"]
            continue
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
    # `bot.user` vaut None tant que le client n'est pas connecte : plusieurs
    # commandes lisent son avatar et echouaient avant d'envoyer. On renseigne
    # l'etat interne plutot que de contourner l'API.
    try:
        bot._connection.user = _Membre(777, "SentriX", bot=True)
        bot._connection.application_id = 111222333
        # bot.is_ready() lit _ready.is_set() ; hors connexion c'est un sentinelle.
        pret = asyncio.Event()
        pret.set()
        bot._connection._ready = pret
        bot._ready = pret
        # Une extension chargee plus tard peut reinitialiser _ready ; en production
        # une commande ne s'execute que sur un bot pret, donc on fige la reponse.
        type(bot).is_ready = lambda self: True
        bot._connection.loop = asyncio.get_event_loop()
        type(bot).loop = property(lambda self: asyncio.get_event_loop())
        # is_owner() interroge application_info() par HTTP quand owner_id est
        # inconnu. On le renseigne avec un identifiant qui n'est PAS celui de
        # l'auteur simule : la garde « proprietaire du bot » reste donc fausse,
        # et les commandes qui en dependent sont bien refusees comme en vrai.
        bot.owner_id = 999_999_999
        bot.owner_ids = set()
    except Exception:
        pass
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
        cause = ""
        # Une commande installee a l'execution peut etre une fermeture qui ne prend
        # PAS `self` : la signature decide, pas une supposition.
        parametres = list(inspect.signature(rappel).parameters)
        prend_cog = bool(parametres) and parametres[0] in ("self", "cog", "_self", "cog_self")
        try:
            if prend_cog:
                await asyncio.wait_for(rappel(cog, ctx, **arguments), timeout=15)
            else:
                await asyncio.wait_for(rappel(ctx, **arguments), timeout=15)
        except Exception as erreur:
            # La cause explique POURQUOI une commande n'a rien envoye. Sans elle,
            # « aucun envoi » ne dit pas s'il faut preparer un etat en base ou si
            # une garde a fait son travail.
            cause = f"{type(erreur).__name__}: {str(erreur)[:90]}"
            if os.environ.get("TRACE_COMMANDES"):
                import traceback
                print(f"\n--- {commande.qualified_name} ---")
                traceback.print_exc()
        globals()["DERNIERE_VUE"] = ""
        verdict, _ = _classer(list(CAPTURES))
        etiquette = commande.qualified_name
        if verdict == "embed" and DERNIERE_VUE:
            etiquette = f"{commande.qualified_name}  [{DERNIERE_VUE}]"
        if verdict == "aucun" and cause:
            etiquette = f"{commande.qualified_name}  ←  {cause}"
        elif cause:
            # Elle a repondu, puis a plante. L'utilisateur voit un debut de
            # reponse et rien apres : c'est un bug, pas un succes.
            resultats.setdefault("repond puis plante", []).append(
                f"{commande.qualified_name}  ←  {cause}"
            )
        resultats.setdefault(verdict, []).append(etiquette)

    await bot.db.close()

    ordre = ("panneau+sections", "panneau", "texte volontaire", "embed", "aucun",
             "argument non synthétisable", "repond puis plante")
    total = sum(len(v) for v in resultats.values())
    print(f"commandes examinées dans {sorted(vises)} : {total}\n")
    for verdict in ordre:
        lot = resultats.get(verdict, [])
        print(f"  {verdict:20} {len(lot):>4}")
        if verdict in ("embed", "aucun", "texte volontaire",
                       "argument non synthétisable", "repond puis plante") and lot:
            for nom in sorted(lot):
                print(f"       {nom}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:] or ["cogs/configuration.py"])))
