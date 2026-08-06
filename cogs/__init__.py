"""Initialisation commune des cogs SentriX.

Ce module installe le nouveau sondage natif Discord juste après le chargement du cog
``cogs.utility``. Cela permet de conserver toute la structure actuelle du bot tout en
remplaçant proprement l'ancien sondage basé sur les réactions 👍/👎.
"""

from __future__ import annotations

import datetime
import re

import discord
from discord.ext import commands


_DURATION_RE = re.compile(r"^\[(\d{1,3})h\]\s*", re.IGNORECASE)
_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension


async def _native_poll_callback(self, ctx: commands.Context, *, question: str):
    """Crée un vrai sondage Discord avec deux à dix réponses.

    Syntaxe simple :
        +poll Question | Réponse 1 | Réponse 2 | Réponse 3

    Sans séparateur, le sondage utilise automatiquement Oui et Non.
    Une durée peut être placée au début : [48h].
    """
    guild_id = ctx.guild.id if ctx.guild else None
    raw = str(question or "").strip()
    if not raw:
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Sondage incomplet",
                description="Ajoutez une question au sondage.",
                kind="danger",
            )
        )

    duration_hours = 24
    duration_match = _DURATION_RE.match(raw)
    if duration_match:
        duration_hours = int(duration_match.group(1))
        raw = raw[duration_match.end():].strip()
        if not 1 <= duration_hours <= 168:
            return await ctx.send(
                embed=await self._embed(
                    guild_id,
                    title="Durée invalide",
                    description="La durée doit être comprise entre **1 heure** et **168 heures (7 jours)**.",
                    kind="danger",
                )
            )

    parts = [part.strip() for part in raw.split("|")]
    poll_question = parts[0] if parts else ""
    answers = parts[1:] if len(parts) > 1 else ["Oui", "Non"]

    usage = (
        "**Exemple avec plusieurs réponses :**\n"
        "`+poll Événement Valorant ? | Oui ça va être super | Oui | Ça peut être bien | Non`\n\n"
        "**Durée personnalisée :**\n"
        "`+poll [48h] Votre question | Réponse 1 | Réponse 2`"
    )

    if not poll_question:
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Question manquante",
                description=usage,
                kind="danger",
            )
        )
    if len(poll_question) > 300:
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Question trop longue",
                description="La question d'un sondage Discord ne peut pas dépasser **300 caractères**.",
                kind="danger",
            )
        )
    if any(not answer for answer in answers):
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Réponse vide",
                description=f"Chaque réponse doit contenir du texte.\n\n{usage}",
                kind="danger",
            )
        )
    if not 2 <= len(answers) <= 10:
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Nombre de réponses invalide",
                description=f"Ajoutez entre **2 et 10 réponses**.\n\n{usage}",
                kind="danger",
            )
        )

    too_long = next((answer for answer in answers if len(answer) > 55), None)
    if too_long is not None:
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Réponse trop longue",
                description=(
                    "Chaque réponse d'un sondage Discord ne peut pas dépasser **55 caractères**.\n"
                    f"Réponse concernée : `{too_long[:55]}…`"
                ),
                kind="danger",
            )
        )

    normalised_answers = [answer.casefold() for answer in answers]
    if len(set(normalised_answers)) != len(normalised_answers):
        return await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Réponses identiques",
                description="Chaque choix doit être différent.",
                kind="danger",
            )
        )

    poll = discord.Poll(
        question=poll_question,
        duration=datetime.timedelta(hours=duration_hours),
        multiple=False,
    )
    for answer in answers:
        poll.add_answer(text=answer)

    send_kwargs = {"poll": poll}
    if ctx.interaction is None:
        # Le sondage doit apparaître comme un message autonome, comme dans l'interface
        # Discord native, et non comme une réponse qui ping l'auteur de la commande.
        send_kwargs["reference"] = None
        send_kwargs["mention_author"] = False

    try:
        await ctx.send(**send_kwargs)
    except discord.Forbidden:
        await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Permission manquante",
                description=(
                    "SentriX ne peut pas créer le sondage dans ce salon. "
                    "Vérifiez les permissions **Envoyer des messages** et **Créer des sondages**."
                ),
                kind="danger",
            )
        )
    except (discord.HTTPException, ValueError):
        await ctx.send(
            embed=await self._embed(
                guild_id,
                title="Sondage impossible",
                description="Discord a refusé ce sondage. Vérifiez la question, les réponses et la durée.",
                kind="danger",
            )
        )


async def _load_extension_with_native_poll(
    bot: commands.Bot,
    name: str,
    *,
    package: str | None = None,
):
    result = await _ORIGINAL_LOAD_EXTENSION(bot, name, package=package)

    if name == "cogs.utility" or name.endswith(".utility"):
        command = bot.get_command("poll")
        if command is not None:
            command.callback = _native_poll_callback
            command.description = "Créer un sondage natif Discord avec jusqu'à 10 réponses."
            app_command = getattr(command, "app_command", None)
            if app_command is not None:
                app_command._callback = _native_poll_callback
                app_command.description = "Créer un sondage natif Discord avec jusqu'à 10 réponses."

    return result


if not getattr(commands.Bot, "_sentrix_native_poll_loader", False):
    commands.Bot.load_extension = _load_extension_with_native_poll
    commands.Bot._sentrix_native_poll_loader = True
