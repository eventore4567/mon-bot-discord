"""SentriX V2.4 Intelligent UX — actions naturelles sans doubler les réponses IA.

Cette couche n'ajoute aucune commande publique. Elle transforme uniquement des demandes
naturelles explicites en appels vers les commandes SentriX existantes. Les actions
sensibles exigent toujours une confirmation et réutilisent les permissions des commandes.

Le routage est exclusif : dès qu'un message appartient à une commande SentriX (commande
préfixée ou commande demandée en langage naturel), le pipeline IA passif ne peut plus
répondre derrière. Cette protection couvre tout le catalogue existant via walk_commands(),
pas seulement une liste de commandes codée en dur.
"""
from __future__ import annotations

import logging
import re
import time
import types

import discord
from discord.ext import commands

import config
from database.db import now
from utils import embeds
from utils.instance_identity import wake_words
from utils.intelligent_ux import (
    NaturalAction,
    classify_ticket_priority,
    parse_natural_action,
    summarize_ticket,
)

logger = logging.getLogger("bot.intelligent-ux-v24")


async def _send_reply(
    message: discord.Message,
    *,
    embed: discord.Embed,
    view: discord.ui.View | None = None,
):
    try:
        sent = await message.channel.send(
            embed=embed,
            view=view,
            reference=message,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        sent = await message.channel.send(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    if view is not None and hasattr(view, "message"):
        view.message = sent
    return sent


async def _resolve_target(bot: commands.Bot, message: discord.Message) -> discord.Member | None:
    if message.guild is None:
        return None

    for member in getattr(message, "mentions", []):
        if member.id not in {message.author.id, getattr(getattr(bot, "user", None), "id", 0)}:
            return member

    reference = getattr(message, "reference", None)
    resolved = getattr(reference, "resolved", None) if reference else None
    if isinstance(resolved, discord.Message):
        author = resolved.author
        if isinstance(author, discord.Member) and not author.bot and author.id != message.author.id:
            return author

    message_id = getattr(reference, "message_id", None) if reference else None
    if message_id:
        try:
            referenced = await message.channel.fetch_message(message_id)
        except discord.HTTPException:
            referenced = None
        if referenced and isinstance(referenced.author, discord.Member):
            author = referenced.author
            if not author.bot and author.id != message.author.id:
                return author
    return None


def _action_details(plan: NaturalAction, target: discord.Member | None) -> str:
    lines = [f"**Action :** {plan.label}"]
    if target is not None:
        lines.append(f"**Membre :** {target.mention}")
    if plan.duration:
        lines.append(f"**Durée :** {plan.duration}")
    if plan.amount:
        lines.append(f"**Montant :** {plan.amount}")
    if plan.reason and plan.reason != "Aucune raison fournie":
        lines.append(f"**Raison :** {plan.reason}")
    return "\n".join(lines)


def _message_claim_cache(bot: commands.Bot) -> dict[int, float]:
    cache = getattr(bot, "_sentrix_v24_claimed_messages", None)
    if not isinstance(cache, dict):
        cache = {}
        bot._sentrix_v24_claimed_messages = cache
    return cache


def _cleanup_claim_cache(cache: dict[int, float]) -> None:
    current = time.monotonic()
    if len(cache) <= 2000:
        return
    for key, saved_at in list(cache.items()):
        if current - float(saved_at) > 180:
            cache.pop(key, None)


def _message_is_claimed(bot: commands.Bot, message_id: int) -> bool:
    cache = _message_claim_cache(bot)
    _cleanup_claim_cache(cache)
    return int(message_id) in cache


def _claim_natural_message(bot: commands.Bot, message_id: int) -> bool:
    """Réserve atomiquement un message afin qu'un seul pipeline SentriX puisse le traiter."""
    cache = _message_claim_cache(bot)
    _cleanup_claim_cache(cache)
    message_id = int(message_id)
    if message_id in cache:
        return False
    cache[message_id] = time.monotonic()
    return True


def _guild_prefix(bot: commands.Bot, guild_id: int) -> str:
    if hasattr(bot, "prefix_cache"):
        value = bot.prefix_cache.get(guild_id, config.DEFAULT_PREFIX)
    else:
        value = config.DEFAULT_PREFIX
    return str(value or config.DEFAULT_PREFIX)


def _extract_explicit_question(bot: commands.Bot, message: discord.Message) -> str | None:
    """Extrait le texte après une mention ou un mot de réveil explicite du bot."""
    content = str(getattr(message, "content", "") or "").strip()
    if not content:
        return None

    user = bot.user
    if user is not None:
        mention_match = re.match(rf"^<@!?{user.id}>\s*", content)
        if mention_match:
            return content[mention_match.end():].lstrip(" ,;:!?.-").strip()

    words = set(wake_words())
    words.update({"SentriX", "SSentriX", "Sentri", "Snetri", "SnentriX"})
    for word in sorted((str(item) for item in words if str(item).strip()), key=len, reverse=True):
        match = re.match(
            rf"^{re.escape(word)}(?=$|[\s,;:!?.-])",
            content,
            flags=re.IGNORECASE,
        )
        if match:
            return content[match.end():].lstrip(" ,;:!?.-").strip()
    return None


async def _invoke_existing_command(
    bot: commands.Bot,
    message: discord.Message,
    plan: NaturalAction,
    target: discord.Member | None,
):
    command = bot.get_command(plan.command)
    if command is None or not command.enabled:
        return await _send_reply(
            message,
            embed=embeds.warning(
                "Cette action existe dans SentriX mais n'est pas disponible sur cette instance.",
                title="Action indisponible",
            ),
        )

    ctx = await bot.get_context(message)
    ctx.command = command
    ctx.invoked_with = command.name

    try:
        allowed = await command.can_run(ctx)
        if not allowed:
            raise commands.CheckFailure("Action non autorisée.")
    except commands.CommandError as exc:
        try:
            return await bot.on_command_error(ctx, exc)
        except Exception:
            return await _send_reply(
                message,
                embed=embeds.error("Vous n'avez pas les permissions nécessaires pour cette action."),
            )

    kwargs = {}
    if plan.command == "pay":
        kwargs = {"membre": target, "montant": plan.amount or "0"}
    elif plan.command == "rob":
        kwargs = {"membre": target}
    elif plan.command in {"ban", "kick", "warn", "unmute"}:
        kwargs = {"membre": target, "raison": plan.reason or "Aucune raison fournie"}
    elif plan.command in {"mute", "tempban"}:
        kwargs = {
            "membre": target,
            "duree": plan.duration or ("10m" if plan.command == "mute" else "1h"),
            "raison": plan.reason or "Aucune raison fournie",
        }

    try:
        return await ctx.invoke(command, **kwargs)
    except commands.CommandError as exc:
        try:
            return await bot.on_command_error(ctx, exc)
        except Exception:
            logger.exception("V2.4 : erreur de commande naturelle %s", plan.command)
    except Exception:
        logger.exception("V2.4 : action naturelle %s interrompue", plan.command)
        return await _send_reply(
            message,
            embed=embeds.error(
                "L'action n'a pas pu être terminée. Rien d'autre n'a été exécuté.",
                title="Action interrompue",
            ),
        )


class NaturalActionConfirmView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        source_message: discord.Message,
        plan: NaturalAction,
        target: discord.Member | None,
    ):
        super().__init__(timeout=35)
        self.bot = bot
        self.source_message = source_message
        self.plan = plan
        self.target = target
        self.author_id = source_message.author.id
        self.message: discord.Message | None = None
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne qui a demandé l'action peut confirmer.",
                ephemeral=True,
            )
            return False
        return True

    def _disable(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Confirmer l'action", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if self.used:
            return await interaction.response.send_message(
                "Cette action a déjà été traitée.", ephemeral=True
            )
        self.used = True
        self._disable()
        await interaction.response.edit_message(
            embed=embeds.info(
                _action_details(self.plan, self.target),
                title="Action confirmée — exécution",
            ),
            view=self,
        )
        self.stop()
        await _invoke_existing_command(self.bot, self.source_message, self.plan, self.target)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if self.used:
            return await interaction.response.send_message(
                "Cette action a déjà été traitée.", ephemeral=True
            )
        self.used = True
        self._disable()
        await interaction.response.edit_message(
            embed=embeds.info("Aucune action n'a été exécutée.", title="Action annulée"),
            view=self,
        )
        self.stop()

    async def on_timeout(self):
        self._disable()
        if self.message:
            try:
                await self.message.edit(
                    embed=embeds.info(
                        "La confirmation a expiré. Aucune action n'a été exécutée.",
                        title="Confirmation expirée",
                    ),
                    view=self,
                )
            except discord.HTTPException:
                pass


async def _handle_plan(bot: commands.Bot, message: discord.Message, plan: NaturalAction):
    if message.guild is None:
        return await _send_reply(
            message,
            embed=embeds.warning(
                "Cette action doit être utilisée dans un serveur Discord.",
                title="Serveur requis",
            ),
        )

    target = await _resolve_target(bot, message) if plan.target_required else None
    if plan.target_required and target is None:
        return await _send_reply(
            message,
            embed=embeds.warning(
                'Mentionnez le membre concerné **ou réponds directement à son message**, puis reformule votre demande.',
                title="Membre à préciser",
            ),
        )

    if plan.sensitive:
        view = NaturalActionConfirmView(bot, message, plan, target)
        return await _send_reply(
            message,
            embed=embeds.warning(
                _action_details(plan, target) + '\n\nVérifiez les informations avant de confirmer.',
                title="Confirmation obligatoire",
            ),
            view=view,
        )
    return await _invoke_existing_command(bot, message, plan, target)


def _install_natural_router(bot: commands.Bot) -> bool:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None:
        return False

    current = ai_cog.send_sentrix_reply
    if getattr(current, "_sentrix_intelligent_ux_v24", False):
        return True

    async def intelligent_reply(
        self,
        destination,
        author,
        question: str,
        *,
        reply_to: discord.Message | None = None,
    ):
        # Une autre couche a déjà décidé que ce message était une commande : elle possède
        # le message, donc l'IA ne doit surtout pas produire une seconde réponse.
        if reply_to is not None and _message_is_claimed(bot, reply_to.id):
            return None

        plan = parse_natural_action(question)
        if plan is None or reply_to is None or reply_to.author.id != author.id:
            return await current(destination, author, question, reply_to=reply_to)

        if not _claim_natural_message(bot, reply_to.id):
            return None

        try:
            return await _handle_plan(bot, reply_to, plan)
        except Exception:
            logger.exception("V2.4 : routeur naturel en échec.")
            return await _send_reply(
                reply_to,
                embed=embeds.error(
                    "Je n'ai pas pu préparer cette action. Aucune action n'a été exécutée ; réessaie dans un instant.",
                    title="Action interrompue",
                ),
            )

    intelligent_reply._sentrix_intelligent_ux_v24 = True
    ai_cog.send_sentrix_reply = types.MethodType(intelligent_reply, ai_cog)
    bot._sentrix_intelligent_router_ready = True
    logger.info("SentriX V2.4 : routeur d'actions naturelles installé.")
    return True


def _install_primary_ai_listener_guard(bot: commands.Bot) -> bool:
    """Donne une propriété exclusive du message à une commande avant le pipeline IA.

    Cette garde couvre :
    - toutes les commandes préfixées (`+...`) ;
    - toutes les actions V2.4 sensibles ou simples ;
    - toutes les commandes reconnues par le moteur naturel de cogs.ai, lequel parcourt
      dynamiquement bot.walk_commands() ;
    - les doublons accidentels de listeners après reload.

    Une vraie question qui n'est pas une commande continue vers un seul listener IA.
    """
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None:
        return False

    previous_guard = getattr(bot, "_sentrix_v24_primary_ai_listener_guard_fn", None)
    guarded_cog = getattr(bot, "_sentrix_v24_guarded_ai_cog", None)
    if guarded_cog is ai_cog and previous_guard is not None:
        return True

    if previous_guard is not None:
        try:
            bot.remove_listener(previous_guard, "on_message")
        except Exception:
            pass

    events = getattr(bot, "extra_events", {})
    listeners = list(events.get("on_message", [])) if isinstance(events, dict) else []
    originals = [
        listener
        for listener in listeners
        if getattr(listener, "__self__", None) is ai_cog
        and getattr(listener, "__name__", "") == "on_message"
    ]
    if not originals:
        return False

    # Plusieurs références identiques peuvent exister après un reload. On les retire
    # toutes, mais une seule version canonique sera appelée pour les vraies questions.
    for listener in originals:
        bot.remove_listener(listener, "on_message")
    primary = originals[0]

    async def guarded_ai_on_message(message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        # Si un autre routeur a déjà réclamé le message, ce listener IA n'a rien à faire.
        if _message_is_claimed(bot, message.id):
            return

        content = str(getattr(message, "content", "") or "").strip()
        prefix = _guild_prefix(bot, message.guild.id)

        # Les commandes `+...` appartiennent au CommandProcessor Discord.py. Même si elles
        # échouent ou sont mal écrites, elles ne doivent jamais être envoyées à l'IA passive.
        if content.startswith(prefix):
            return

        question = _extract_explicit_question(bot, message)
        if question is None:
            return await primary(message)

        # 1) Actions V2.4 structurées (pay, modération, profil, économie, etc.).
        plan = parse_natural_action(question)
        if plan is not None:
            if not _claim_natural_message(bot, message.id):
                return
            try:
                await _handle_plan(bot, message, plan)
            except Exception:
                logger.exception("V2.4 : action naturelle interceptée en échec.")
                await _send_reply(
                    message,
                    embed=embeds.error(
                        "Je n'ai pas pu terminer cette action. Aucune autre réponse IA n'a été envoyée.",
                        title="Action interrompue",
                    ),
                )
            return

        # 2) Toutes les autres commandes existantes reconnues en langage naturel.
        # _natural_command_line() s'appuie sur bot.walk_commands(), donc une nouvelle
        # commande existante est automatiquement couverte sans modifier cette garde.
        command_line = ai_cog._natural_command_line(
            question,
            prefix,
            has_attachment=bool(getattr(message, "attachments", None)),
        )
        if command_line:
            if not _claim_natural_message(bot, message.id):
                return
            try:
                invoked = await ai_cog._invoke_natural_command(message, question, prefix)
            except Exception:
                logger.exception("V2.4 : commande naturelle globale en échec.")
                invoked = False
            if not invoked:
                await _send_reply(
                    message,
                    embed=embeds.warning(
                        "J'ai reconnu une commande SentriX, mais elle n'est pas disponible actuellement.",
                        title="Commande indisponible",
                    ),
                )
            return

        # 3) Ce n'est pas une commande : une seule vraie réponse IA est autorisée.
        return await primary(message)

    guarded_ai_on_message._sentrix_v24_primary_guard = True
    bot.add_listener(guarded_ai_on_message, "on_message")
    bot._sentrix_v24_primary_ai_listener_guard_fn = guarded_ai_on_message
    bot._sentrix_v24_guarded_ai_cog = ai_cog
    bot._sentrix_v24_primary_ai_listener_guard = True
    logger.info(
        "SentriX V2.4 : garde globale activée pour toutes les commandes et réponses IA."
    )
    return True


def _install_ticket_intelligence(bot: commands.Bot) -> bool:
    tickets = bot.get_cog("Tickets")
    if tickets is None:
        return False

    current = tickets.create_ticket
    if getattr(current, "_sentrix_intelligent_ticket_v24", False):
        return True

    async def intelligent_create(
        this,
        interaction: discord.Interaction,
        ticket_type,
        answers: list,
    ):
        result = await current(interaction, ticket_type, answers)
        try:
            if interaction.guild is None:
                return result

            row = await bot.db.fetchone(
                "SELECT id,created_at FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? ORDER BY id DESC LIMIT 1",
                (interaction.guild.id, interaction.user.id, int(ticket_type["id"])),
            )
            if not row or int(row["created_at"] or 0) < now() - 180:
                return result

            ticket_id = int(row["id"])
            duplicate = await bot.db.fetchone(
                "SELECT id FROM ticket_notes WHERE ticket_id=? AND note LIKE '[SentriX Auto]%' LIMIT 1",
                (ticket_id,),
            )
            if duplicate:
                return result

            summary = summarize_ticket(ticket_type["name"], answers)
            joined_text = " ".join(str(value or "") for _label, value in answers)
            _priority_key, priority_label = classify_ticket_priority(joined_text)
            sanctions = await bot.db.fetchone(
                "SELECT COUNT(*) AS c FROM sanctions WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            sanction_count = int(sanctions["c"] if sanctions else 0)
            note = (
                f"[SentriX Auto] Résumé : {summary}\n"
                f"Priorité suggérée : {priority_label}.\n"
                f"Contexte modération : {sanction_count} sanction(s) enregistrée(s) sur ce serveur."
            )[:1000]
            await bot.db.execute(
                "INSERT INTO ticket_notes (ticket_id, author_id, note, timestamp) VALUES (?, ?, ?, ?)",
                (
                    ticket_id,
                    getattr(getattr(bot, "user", None), "id", 0) or 0,
                    note,
                    now(),
                ),
            )
        except Exception:
            logger.exception("V2.4 : impossible d'ajouter le résumé interne du ticket.")
        return result

    intelligent_create._sentrix_intelligent_ticket_v24 = True
    tickets.create_ticket = types.MethodType(intelligent_create, tickets)
    bot._sentrix_intelligent_tickets_ready = True
    logger.info("SentriX V2.4 : résumés et priorité suggérée des tickets activés.")
    return True


def install(bot: commands.Bot) -> None:
    """Installation idempotente, rappelée après chaque extension par le finaliseur."""
    router = _install_natural_router(bot)
    listener_guard = _install_primary_ai_listener_guard(bot)
    tickets = _install_ticket_intelligence(bot)

    bot._sentrix_intelligent_ux_state = {
        "new_commands": 0,
        "natural_router": bool(router),
        "primary_listener_guard": bool(listener_guard),
        "global_command_exclusivity": True,
        "reload_safe_listener_guard": True,
        "ticket_intelligence": bool(tickets),
        "sensitive_confirmation": True,
        "permission_reuse": True,
        "deduplicated_messages": True,
    }
