"""Bot Experience V6 — accueil interactif et raccourcis instantanés.

Cette couche améliore ce que les membres voient immédiatement dans Discord sans ajouter de
nouvelle commande slash :
- une simple mention / un simple mot de réveil ouvre un vrai panneau d'accueil interactif ;
- les demandes très courtes (aide, jeux, économie, profil, ping) sont traitées localement,
  donc sans latence OpenAI ni coût API ;
- les boutons donnent des parcours courts et propres vers les fonctions les plus utiles ;
- les commandes utilisées récemment servent à proposer des raccourcis personnels en mémoire.

Elle se branche après Bot Core V5 et ne modifie ni le dashboard, ni les permissions, ni les
secrets, ni le catalogue slash.
"""
from __future__ import annotations

import logging
import re
import types
import unicodedata
from collections import Counter
from typing import Any

import discord

from utils import sentrix_panels as panels
from discord.ext import commands

import config
from utils.instance_identity import brand_label

from . import bot_experience_v5

logger = logging.getLogger("bot.experience-v6")

_ACCENT = 0x5865F2
_FILLER_WORDS = {"stp", "svp", "please", "pls", "merci", "vite", "moi"}


def _prefix_for(bot: commands.Bot, message: discord.Message | None = None) -> str:
    if message is not None and message.guild is not None and hasattr(bot, "prefix_cache"):
        return str(bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX))
    return str(config.DEFAULT_PREFIX)


def _normalise(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9 ]+", " ", value).casefold()
    words = [word for word in value.split() if word not in _FILLER_WORDS]
    return " ".join(words).strip()


def _quick_intent(question: str) -> str | None:
    """Reconnaît uniquement des demandes courtes et sans ambiguïté.

    On reste volontairement conservateur : une vraie question continue vers l'IA. Le but est
    seulement d'éviter un appel modèle pour des actions évidentes qui doivent être instantanées.
    """
    value = _normalise(question)
    if not value or len(value) > 60:
        return None

    if value in {
        "aide", "help", "menu", "commande", "commandes", "tes commandes",
        "tu peux faire quoi", "que peux tu faire", "que fais tu", "comment t utiliser",
        "comment utiliser le bot", "demarrer", "start", "accueil",
    }:
        return "home"
    if value in {"jeu", "jeux", "game", "games", "mini jeux", "minijeux", "jouer", "on joue"}:
        return "games"
    if value in {"economie", "eco", "argent", "money", "monnaie", "boutique", "shop"}:
        return "economy"
    if value in {"profil", "profile", "niveau", "level", "xp", "reputation", "rep"}:
        return "profile"
    if value in {"ia", "ai", "intelligence artificielle", "parler", "discussion"}:
        return "ai"
    if value in {"ping", "latence", "latency"}:
        return "ping"
    return None


def _usage_store(bot: commands.Bot) -> dict[tuple[int, int], Counter[str]]:
    store = getattr(bot, "_sentrix_v6_usage", None)
    if not isinstance(store, dict):
        store = {}
        bot._sentrix_v6_usage = store
    return store


def _top_commands(bot: commands.Bot, guild_id: int, user_id: int, prefix: str, limit: int = 3) -> list[str]:
    counter = _usage_store(bot).get((int(guild_id), int(user_id)))
    if counter:
        names = [name for name, _count in counter.most_common(limit)]
        if names:
            return [f"{prefix}{name}" for name in names]
    return [f"{prefix}help", f"{prefix}profile", f"{prefix}daily"][:limit]


def _home_embed(bot: commands.Bot, author: discord.abc.User, prefix: str, guild_id: int = 0) -> discord.Embed:
    brand = brand_label()
    display_name = getattr(author, "display_name", None) or getattr(author, "name", None) or "membre"
    shortcuts = "  •  ".join(f"`{name}`" for name in _top_commands(bot, guild_id, author.id, prefix))
    embed = discord.Embed(
        title=f"{brand} — Accueil",
        description=(
            f"Salut **{display_name}**. Choisissez un bouton ci-dessous ou parle-moi directement.\nExemple : `{('Odboug' if 'odboug' in brand.casefold() else 'SentriX')} explique-moi comment fonctionne Discord`."
        ),
        color=_ACCENT,
    )
    embed.add_field(
        name="Commencer rapidement",
        value=(
            f"**Commandes :** `{prefix}help`\n"
            f"**Jeux :** `{prefix}blackjack`, `{prefix}connect4`, `{prefix}trivia`\n"
            f"**Économie :** `{prefix}daily`, `{prefix}work`, `{prefix}shop`\n"
            f"**Profil :** `{prefix}profile`, `{prefix}level`"
        ),
        inline=False,
    )
    embed.add_field(name='Vos raccourcis', value=shortcuts, inline=False)
    embed.add_field(
        name="Conversation naturelle",
        value="Vous pouvez aussi répondre directement à l'un de mes messages : pas besoin de répéter mon nom à chaque fois.",
        inline=False,
    )
    embed.set_footer(text="Les boutons répondent seulement à la personne qui clique pour éviter de spammer le salon.")
    return embed


def _guide_embed(kind: str, prefix: str, *, bot: commands.Bot | None = None, user_id: int = 0, guild_id: int = 0) -> discord.Embed:
    brand = brand_label()
    if kind == "games":
        title = "Jeux"
        description = "Des jeux rapides, des duels et des modes plus longs."
        lines = [
            f"`{prefix}blackjack` — blackjack",
            f"`{prefix}connect4` — puissance 4",
            f"`{prefix}trivia` — questions rapides",
            f"`{prefix}wordrace` — course de mots",
            f"`{prefix}adventure` — aventure",
            f"`{prefix}fishing` — pêche",
            f"`{prefix}dailygames` — récompenses jeux du jour",
        ]
    elif kind == "economy":
        title = "Économie"
        description = "Le parcours le plus simple pour commencer et progresser."
        lines = [
            f"`{prefix}daily` puis `{prefix}weekly` — récompenses",
            f"`{prefix}work` — gagner de l'argent",
            f"`{prefix}balance` — voir ton solde",
            f"`{prefix}shop` — ouvrir la boutique",
            f"`{prefix}buy` — acheter",
            f"`{prefix}inventory` — voir tes objets",
        ]
    elif kind == "profile":
        title = "Profil et progression"
        description = "Tout ce qui concerne ton niveau, ton activité et ta réputation."
        lines = [
            f"`{prefix}profile` — profil complet",
            f"`{prefix}level` — niveau et XP",
            f"`{prefix}reputation` — réputation",
            f"`{prefix}rep` — donner une réputation",
            f"`{prefix}voice-time` — temps passé en vocal",
        ]
    elif kind == "ai":
        title = "Intelligence artificielle"
        description = "Parle au bot comme à une personne, sans apprendre une syntaxe compliquée."
        wake = "Odboug" if "odboug" in brand.casefold() else "SentriX"
        lines = [
            f"`{wake} explique-moi ...` — conversation naturelle",
            "Réponds directement à un message du bot pour continuer la discussion.",
            f"`{prefix}ai` — commande IA",
            f"`{prefix}image` — générer une image",
            f"`{prefix}summarize` — résumer un texte",
        ]
    elif kind == "shortcuts" and bot is not None:
        title = "Tes raccourcis"
        description = "Basé sur les commandes que tu utilises le plus depuis le dernier redémarrage."
        lines = [f"`{name}`" for name in _top_commands(bot, guild_id, user_id, prefix, limit=5)]
    else:
        title = "Commandes"
        description = "Le menu d'aide contient toutes les commandes, rangées par catégories."
        lines = [
            f"`{prefix}help` — ouvrir l'aide complète",
            f"`{prefix}botinfo` — infos sur le bot",
            f"`{prefix}ping` — latence",
            f"`{prefix}profile` — ton profil",
            f"`{prefix}dailygames` — activités du jour",
        ]

    embed = discord.Embed(title=f"{brand} — {title}", description=description, color=_ACCENT)
    embed.add_field(name="À essayer", value="\n".join(lines), inline=False)
    return embed


class QuickHomeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix

    async def _reply(self, interaction: discord.Interaction, kind: str) -> None:
        guild_id = interaction.guild.id if interaction.guild else 0
        embed = _guide_embed(
            kind,
            self.prefix,
            bot=self.bot,
            user_id=interaction.user.id,
            guild_id=guild_id,
        )
        await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)

    @discord.ui.button(label="Commandes", style=discord.ButtonStyle.primary, row=0)
    async def commands_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "commands")

    @discord.ui.button(label="Jeux", style=discord.ButtonStyle.secondary, row=0)
    async def games_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "games")

    @discord.ui.button(label="Économie", style=discord.ButtonStyle.secondary, row=0)
    async def economy_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "economy")

    @discord.ui.button(label="IA", style=discord.ButtonStyle.secondary, row=0)
    async def ai_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "ai")

    @discord.ui.button(label="Profil", style=discord.ButtonStyle.secondary, row=1)
    async def profile_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "profile")

    @discord.ui.button(label="Mes raccourcis", style=discord.ButtonStyle.secondary, row=1)
    async def shortcuts_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._reply(interaction, "shortcuts")


async def _send_panel(
    bot: commands.Bot,
    destination: Any,
    author: discord.abc.User,
    *,
    prefix: str,
    reply_to: discord.Message | None,
    kind: str = "home",
):
    guild_id = reply_to.guild.id if reply_to is not None and reply_to.guild is not None else 0
    if kind == "home":
        embed = _home_embed(bot, author, prefix, guild_id)
        view: discord.ui.View | None = QuickHomeView(bot, prefix)
    else:
        embed = _guide_embed(kind, prefix, bot=bot, user_id=author.id, guild_id=guild_id)
        view = None

    kwargs: dict[str, Any] = {
        "embed": embed,
        "view": view,
        "allowed_mentions": discord.AllowedMentions(everyone=False, roles=False, users=False, replied_user=False),
    }
    if reply_to is not None:
        kwargs["reference"] = reply_to
        kwargs["mention_author"] = False
    try:
        return await destination.send(**kwargs)
    except (discord.HTTPException, TypeError):
        kwargs.pop("reference", None)
        kwargs.pop("mention_author", None)
        return await destination.send(**kwargs)


def _install_usage_memory(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_experience_v6_usage_installed", False):
        return

    async def remember_command(ctx: commands.Context):
        command = ctx.command
        if command is None or ctx.author.bot:
            return
        name = str(command.qualified_name or command.name).strip()
        if not name:
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        key = (guild_id, ctx.author.id)
        store = _usage_store(bot)
        counter = store.setdefault(key, Counter())
        counter[name] += 1
        # Empêche cette petite mémoire UX de grossir sans limite sur un très gros bot.
        if len(counter) > 30:
            store[key] = Counter(dict(counter.most_common(20)))
        if len(store) > 5000:
            # Le classement est uniquement un confort local ; supprimer les plus anciennes
            # entrées n'affecte aucune donnée métier ni progression persistante.
            for old_key in list(store)[:1000]:
                store.pop(old_key, None)

    bot.add_listener(remember_command, "on_command_completion")
    bot._sentrix_experience_v6_usage_installed = True
    logger.info("Bot Experience V6 : raccourcis personnels en mémoire activés.")


def _install_fast_home(bot: commands.Bot) -> None:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None or getattr(ai_cog, "_sentrix_experience_v6_pipeline", False):
        return

    original = ai_cog.send_sentrix_reply

    async def polished_send_sentrix_reply(
        self,
        destination,
        author,
        question: str,
        *,
        reply_to: discord.Message | None = None,
    ):
        prefix = _prefix_for(self.bot, reply_to)

        if bot_experience_v5._is_bare_trigger(self.bot, reply_to):
            return await _send_panel(self.bot, destination, author, prefix=prefix, reply_to=reply_to, kind="home")

        intent = _quick_intent(question)
        if intent == "ping":
            latency = max(0, round(float(getattr(self.bot, "latency", 0.0)) * 1000))
            embed = discord.Embed(
                title=f"{brand_label()} — Latence",
                description=f"Discord : **{latency} ms**",
                color=_ACCENT,
            )
            kwargs = {
                "embed": embed,
                "allowed_mentions": discord.AllowedMentions.none(),
            }
            if reply_to is not None:
                kwargs["reference"] = reply_to
                kwargs["mention_author"] = False
            try:
                return await destination.send(**kwargs)
            except (discord.HTTPException, TypeError):
                kwargs.pop("reference", None)
                kwargs.pop("mention_author", None)
                return await destination.send(**kwargs)

        if intent is not None:
            return await _send_panel(self.bot, destination, author, prefix=prefix, reply_to=reply_to, kind=intent)

        return await original(destination, author, question, reply_to=reply_to)

    ai_cog.send_sentrix_reply = types.MethodType(polished_send_sentrix_reply, ai_cog)
    ai_cog._sentrix_experience_v6_pipeline = True
    logger.info("Bot Experience V6 : accueil interactif et intentions rapides activés pour %s.", brand_label())


def install(bot: commands.Bot) -> None:
    """Installation idempotente, retentée jusqu'au chargement du cog IA."""
    _install_usage_memory(bot)
    _install_fast_home(bot)
