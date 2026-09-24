"""Bot Experience V6 — intentions rapides sans doublon d'interface.

Cette couche améliore les demandes courtes dans Discord sans ajouter de commande slash :
- une simple mention reste une réponse compacte du pipeline V5 ;
- aide, jeux, économie, profil et IA ouvrent le centre +help officiel au lieu d'un
  second panneau d'accueil qui dupliquait l'interface et vieillissait séparément ;
- ping reste traité localement, sans appel OpenAI ;
- les commandes utilisées récemment restent comptabilisées en mémoire pour la télémétrie UX.

Elle se branche après Bot Core V5 et ne modifie ni le dashboard, ni les permissions, ni les
secrets, ni le catalogue slash.
"""
from __future__ import annotations

import logging
import re
import types
import unicodedata
from collections import Counter
import discord

from utils import helpers
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

        # Une mention seule ne doit plus ouvrir l'ancien gros panneau
        # "SentriX — Accueil". Le pipeline V5 renvoie déjà une réponse compacte et
        # unique avec le vrai +help.
        if bot_experience_v5._is_bare_trigger(self.bot, reply_to):
            return await original(destination, author, question, reply_to=reply_to)

        intent = _quick_intent(question)

        # Les anciens mini-menus V6 (Accueil / Jeux / Économie / IA / Profil /
        # raccourcis) dupliquaient le centre d'aide officiel et pouvaient afficher des
        # commandes obsolètes. Une demande courte ouvre désormais l'unique +help
        # canonique, éventuellement filtré sur la catégorie demandée.
        if intent in {"home", "games", "economy", "profile", "ai"} and reply_to is not None:
            help_queries = {
                "home": "",
                "games": "jeux",
                "economy": "économie",
                "profile": "profil",
                "ai": "ia",
            }
            suffix = help_queries[intent]
            command_line = f"{prefix}help" + (f" {suffix}" if suffix else "")
            invoke = getattr(self, "_invoke_command_line", None)
            if callable(invoke):
                try:
                    if await invoke(reply_to, command_line):
                        return None
                except Exception:
                    logger.exception("Bot Experience V6 : ouverture du help canonique impossible.")
            return await original(destination, author, question, reply_to=reply_to)

        if intent == "ping":
            latency = helpers.latence_ms(self.bot)
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

        return await original(destination, author, question, reply_to=reply_to)

    ai_cog.send_sentrix_reply = types.MethodType(polished_send_sentrix_reply, ai_cog)
    ai_cog._sentrix_experience_v6_pipeline = True
    logger.info("Bot Experience V6 : accueil interactif et intentions rapides activés pour %s.", brand_label())


def install(bot: commands.Bot) -> None:
    """Installation idempotente, retentée jusqu'au chargement du cog IA."""
    _install_usage_memory(bot)
    _install_fast_home(bot)
