"""Suggestions — boîte à idées du serveur, votes et décisions du staff.

Ce cog affiche et écoute ; la logique et le stockage vivent dans
services/suggestions.py, testé sans bot.

Parcours d'un membre
--------------------
1. Il clique « Créer une suggestion » sous le panneau du serveur, ou tape
   /suggestions submit : un formulaire s'ouvre (titre, description, image
   facultative).
2. La suggestion est publiée dans le salon configuré, numérotée (#0001) et
   munie de quatre boutons : Pour, Contre, Gérer, Créer une suggestion.
3. Recliquer sur son vote le retire ; cliquer sur l'autre le bascule.

Parcours du staff
-----------------
« Gérer » ouvre un formulaire : statut (en attente, prévue, acceptée, réalisée,
refusée) et réponse publique. La carte se met à jour sur place, et la décision
part dans les journaux.

Ce qui survit à un redémarrage
------------------------------
Tout. Les boutons portent des identifiants fixes (`sentrix:suggestions:…`) et
sont traités par un écouteur `on_interaction`, sans vue enregistrée en mémoire ;
la suggestion est retrouvée par l'identifiant du message, et les votes sont en
base.

Permissions
-----------
Une seule décision, celle de `utils.access_matrix.evaluate` : soumettre est
public, configurer demande « Gérer le serveur », trancher demande « Gérer les
messages » (ou le rôle staff de SentriX, ou une règle de Setup > Permissions).
Les boutons appellent la même décision que les commandes.

Langue
------
Les textes sont choisis au RENDU selon la langue du serveur. La traduction
générale de SentriX agit au transport, dans le contexte d'une commande ; une
carte publiée depuis un bouton ou un formulaire n'en a pas, et serait partie en
français sur un serveur anglophone.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services import suggestions as svc
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.suggestions")

PREFIX = "sentrix:suggestions:"
ID_NEW = PREFIX + "new"
ID_UP = PREFIX + "up"
ID_DOWN = PREFIX + "down"
ID_MANAGE = PREFIX + "manage"

STATUS_KIND: dict[str, str] = {
    "pending": "info",
    "planned": "info",
    "accepted": "success",
    "implemented": "success",
    "rejected": "danger",
}

TEXTS: dict[str, dict[str, Any]] = {
    "fr": {
        "status": {
            "pending": "En attente", "planned": "Prévue", "accepted": "Acceptée",
            "implemented": "Réalisée", "rejected": "Refusée",
        },
        "card_title": "Suggestion #{number:04d}",
        "proposal": "Proposition",
        "details": "Détails",
        "author": "Auteur",
        "anonymous": "Anonyme",
        "votes": "Votes",
        "votes_value": "Pour **{up}** · Contre **{down}**",
        "status_label": "Statut",
        "staff_answer": "Réponse du staff",
        "by": "Par",
        "btn_up": "Pour {n}",
        "btn_down": "Contre {n}",
        "btn_manage": "Gérer",
        "btn_new": "Créer une suggestion",
        "box_title": "Boîte à suggestions",
        "box_subtitle": "Une idée pour améliorer le serveur ? Proposez-la ici.",
        "box_how": "Comment ça marche",
        "box_text": (
            "Cliquez sur le bouton ci-dessous et décrivez votre idée. "
            "Les membres votent, puis le staff répond."
        ),
        "modal_submit": "Nouvelle suggestion",
        "field_title": "Titre",
        "field_title_hint": "En une phrase",
        "field_body": "Description",
        "field_body_hint": "Ce que vous proposez, et pourquoi.",
        "field_image": "Image (facultatif)",
        "modal_manage": "Gérer la suggestion",
        "field_status": "Statut",
        "field_answer": "Réponse publique (facultative)",
        "published": "Suggestion **#{number:04d}** publiée : {url}",
        "decided": "Suggestion **#{number:04d}** : {status}.",
        "decided_missing": " Le message d'origine est introuvable.",
        "guild_only": "Les suggestions s'utilisent sur un serveur.",
        "no_access": "Vous n'avez pas accès à cette action.",
        "cannot_write": "SentriX ne peut pas écrire dans {channel}.",
        "unknown_number": "Aucune suggestion #{number:04d}.",
        "unknown_status": "Statut inconnu. Choisissez : {choices}.",
        "box_published": "Boîte à suggestions publiée : {url}",
        "setup_title": "Suggestions configurées",
        "setup_settings": "Réglages",
        "setup_channel": "Salon",
        "setup_cooldown": "Délai entre deux idées",
        "setup_anonymous": "Auteur masqué",
        "setup_threads": "Fil de discussion",
        "setup_next": "Ensuite",
        "setup_next_text": "Publiez la boîte à suggestions avec `/suggestions panel`.",
        "yes": "Oui",
        "no": "Non",
        "minutes": "{n} min",
        "cooldown": "Vous venez déjà de proposer une idée. Réessayez dans **{delay}**.",
        "errors": {
            "not_configured": (
                "Les suggestions ne sont pas encore configurées sur ce serveur. "
                "Un administrateur peut choisir le salon avec `/suggestions setup`."
            ),
            "empty": "Votre suggestion est vide.",
            "closed": "Cette suggestion a déjà été tranchée : les votes sont fermés.",
            "invalid_status": "Statut inconnu.",
            "invalid_cooldown": "Le délai doit être compris entre 0 et 1440 minutes.",
            "missing": "Cette suggestion n'existe plus.",
            "channel_gone": (
                "Le salon des suggestions n'existe plus ou SentriX n'y a pas accès. "
                "Un administrateur peut en choisir un autre avec `/suggestions setup`."
            ),
        },
    },
    "en": {
        "status": {
            "pending": "Pending", "planned": "Planned", "accepted": "Accepted",
            "implemented": "Implemented", "rejected": "Rejected",
        },
        "card_title": "Suggestion #{number:04d}",
        "proposal": "Proposal",
        "details": "Details",
        "author": "Author",
        "anonymous": "Anonymous",
        "votes": "Votes",
        "votes_value": "For **{up}** · Against **{down}**",
        "status_label": "Status",
        "staff_answer": "Staff response",
        "by": "By",
        "btn_up": "For {n}",
        "btn_down": "Against {n}",
        "btn_manage": "Manage",
        "btn_new": "Create a suggestion",
        "box_title": "Suggestion box",
        "box_subtitle": "Got an idea to improve the server? Share it here.",
        "box_how": "How it works",
        "box_text": "Click the button below and describe your idea. Members vote, then the staff answers.",
        "modal_submit": "New suggestion",
        "field_title": "Title",
        "field_title_hint": "In one sentence",
        "field_body": "Description",
        "field_body_hint": "What you suggest, and why.",
        "field_image": "Image (optional)",
        "modal_manage": "Manage the suggestion",
        "field_status": "Status",
        "field_answer": "Public response (optional)",
        "published": "Suggestion **#{number:04d}** posted: {url}",
        "decided": "Suggestion **#{number:04d}**: {status}.",
        "decided_missing": " The original message is gone.",
        "guild_only": "Suggestions work in a server.",
        "no_access": "You don't have access to this.",
        "cannot_write": "SentriX can't write in {channel}.",
        "unknown_number": "No suggestion #{number:04d}.",
        "unknown_status": "Unknown status. Choose: {choices}.",
        "box_published": "Suggestion box posted: {url}",
        "setup_title": "Suggestions set up",
        "setup_settings": "Settings",
        "setup_channel": "Channel",
        "setup_cooldown": "Time between two ideas",
        "setup_anonymous": "Hide the author",
        "setup_threads": "Discussion thread",
        "setup_next": "Next",
        "setup_next_text": "Post the suggestion box with `/suggestions panel`.",
        "yes": "Yes",
        "no": "No",
        "minutes": "{n} min",
        "cooldown": "You just shared an idea. Try again in **{delay}**.",
        "errors": {
            "not_configured": (
                "Suggestions are not set up on this server yet. "
                "An admin can choose the channel with `/suggestions setup`."
            ),
            "empty": "Your suggestion is empty.",
            "closed": "This suggestion has been decided: voting is closed.",
            "invalid_status": "Unknown status.",
            "invalid_cooldown": "The cooldown must be between 0 and 1440 minutes.",
            "missing": "This suggestion no longer exists.",
            "channel_gone": (
                "The suggestion channel is gone or SentriX can't access it. "
                "An admin can choose another one with `/suggestions setup`."
            ),
        },
    },
}


def _now() -> int:
    return int(time.time())


async def lang_of(bot: Any, guild_id: int | None) -> dict[str, Any]:
    try:
        from cogs import language_runtime

        code = await language_runtime.get_language(bot, guild_id)
    except Exception:  # noqa: BLE001 — la langue ne doit jamais bloquer une suggestion
        logger.debug("Langue du serveur indisponible, repli sur le français.", exc_info=True)
        code = "fr"
    return TEXTS.get(code, TEXTS["fr"])


def _error_text(t: dict[str, Any], error: svc.SuggestionError) -> str:
    if error.code == "cooldown":
        seconds = int(error.details.get("seconds", 0))
        minutes, rest = divmod(seconds, 60)
        delay = f"{minutes} min {rest:02d} s" if minutes else f"{rest} s"
        return t["cooldown"].format(delay=delay)
    return t["errors"].get(error.code, t["no_access"])


async def _say(interaction: discord.Interaction, text: str, *, kind: str = "danger") -> None:
    """Réponse privée et courte. Fonctionne avant ou après un defer."""
    panneau = panels.depuis_embed(
        embeds.error(text) if kind == "danger" else embeds.success(text)
    )
    # envoyer() choisit seul : réponse directe, édition du « réfléchit… », ou suivi.
    await panels.envoyer(interaction, panneau, ephemere=True)


async def _allowed(bot: Any, interaction: discord.Interaction, command_name: str) -> bool:
    """LA décision de permission, identique à celle des commandes + et /."""
    from utils import access_matrix

    decision = await access_matrix.evaluate(
        bot, command_name=command_name, author=interaction.user, guild=interaction.guild
    )
    if decision.allowed:
        return True
    t = await lang_of(bot, getattr(interaction.guild, "id", None))
    await _say(interaction, decision.message or decision.reason or t["no_access"])
    return False


# --------------------------------------------------------------------------
# Rendu
# --------------------------------------------------------------------------

def render(suggestion: svc.Suggestion, up: int, down: int, t: dict[str, Any] = TEXTS["fr"]) -> panels.Panneau:
    """La carte publique d'une suggestion."""
    closed = suggestion.status in ("accepted", "implemented", "rejected")
    author = t["anonymous"] if suggestion.anonymous else f"<@{suggestion.author_id}>"
    sections = [
        panels.Section(t["proposal"], texte=suggestion.content),
        panels.Section(
            t["details"],
            lignes=[
                panels.Ligne(t["author"], author),
                panels.Ligne(t["votes"], t["votes_value"].format(up=up, down=down)),
                panels.Ligne(t["status_label"], t["status"].get(suggestion.status, suggestion.status)),
            ],
        ),
    ]
    if suggestion.staff_response or suggestion.staff_id:
        lignes = [panels.Ligne(t["by"], f"<@{suggestion.staff_id}>")] if suggestion.staff_id else []
        sections.append(
            panels.Section(t["staff_answer"], texte=suggestion.staff_response or None, lignes=lignes)
        )
    boutons = [
        panels.Bouton(t["btn_up"].format(n=up), custom_id=ID_UP, style=discord.ButtonStyle.success, desactive=closed),
        panels.Bouton(t["btn_down"].format(n=down), custom_id=ID_DOWN, style=discord.ButtonStyle.danger, desactive=closed),
        panels.Bouton(t["btn_manage"], custom_id=ID_MANAGE, style=discord.ButtonStyle.secondary),
        panels.Bouton(t["btn_new"], custom_id=ID_NEW, style=discord.ButtonStyle.primary),
    ]
    return panels.Panneau(
        titre=t["card_title"].format(number=suggestion.number),
        sous_titre=suggestion.title or None,
        sections=sections,
        kind=STATUS_KIND.get(suggestion.status, "info"),
        boutons=boutons,
        image=suggestion.attachment_url or None,
        pied="SentriX • Suggestions",
    )


def render_box(t: dict[str, Any] = TEXTS["fr"]) -> panels.Panneau:
    """Le panneau « boîte à suggestions » posé dans un salon par le staff."""
    return panels.Panneau(
        titre=t["box_title"],
        sous_titre=t["box_subtitle"],
        sections=[panels.Section(t["box_how"], texte=t["box_text"])],
        kind="info",
        boutons=[panels.Bouton(t["btn_new"], custom_id=ID_NEW, style=discord.ButtonStyle.primary)],
        pied="SentriX • Suggestions",
    )


# --------------------------------------------------------------------------
# Formulaires
# --------------------------------------------------------------------------

class SubmitModal(discord.ui.Modal):
    def __init__(self, cog: "Suggestions", t: dict[str, Any]) -> None:
        super().__init__(title=t["modal_submit"], timeout=900)
        self.cog = cog
        self.titre = discord.ui.TextInput(
            custom_id=PREFIX + "title", placeholder=t["field_title_hint"],
            max_length=svc.MAX_TITLE, required=True,
        )
        self.description = discord.ui.TextInput(
            custom_id=PREFIX + "body",
            style=discord.TextStyle.paragraph,
            placeholder=t["field_body_hint"],
            max_length=svc.MAX_CONTENT,
            required=True,
        )
        self.image = discord.ui.FileUpload(custom_id=PREFIX + "file", required=False, max_values=1)
        self.add_item(discord.ui.Label(text=t["field_title"], component=self.titre))
        self.add_item(discord.ui.Label(text=t["field_body"], component=self.description))
        self.add_item(discord.ui.Label(text=t["field_image"], component=self.image))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = list(self.image.values or [])
        await self.cog.submit(
            interaction,
            title=str(self.titre.value or ""),
            content=str(self.description.value or ""),
            attachment=values[0] if values else None,
        )


class ManageModal(discord.ui.Modal):
    def __init__(self, cog: "Suggestions", suggestion: svc.Suggestion, t: dict[str, Any]) -> None:
        super().__init__(title=t["modal_manage"], timeout=900)
        self.cog = cog
        self.suggestion_id = suggestion.id
        self.status = discord.ui.Select(
            custom_id=PREFIX + "status",
            options=[
                discord.SelectOption(label=label, value=value, default=value == suggestion.status)
                for value, label in t["status"].items()
            ],
        )
        self.response = discord.ui.TextInput(
            custom_id=PREFIX + "response",
            style=discord.TextStyle.paragraph,
            default=suggestion.staff_response or None,
            max_length=svc.MAX_RESPONSE,
            required=False,
        )
        self.add_item(discord.ui.Label(text=t["field_status"], component=self.status))
        self.add_item(discord.ui.Label(text=t["field_answer"], component=self.response))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        status = (self.status.values or ["pending"])[0]
        await self.cog.decide(interaction, self.suggestion_id, status, str(self.response.value or ""))


# --------------------------------------------------------------------------
# Cog
# --------------------------------------------------------------------------

class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await svc.ensure_schema(self.bot.db)

    # ---------------------------------------------------------- soumission

    async def submit(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        content: str,
        attachment: discord.Attachment | None = None,
    ) -> None:
        t = await lang_of(self.bot, getattr(interaction.guild, "id", None))
        if interaction.guild is None:
            return await _say(interaction, t["guild_only"])
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.publish(
            interaction.guild,
            author=interaction.user,
            title=title,
            content=content,
            attachment=attachment,
            actor=interaction,
        )
        if isinstance(result, str):
            return await _say(interaction, result)
        suggestion, message = result
        await _say(interaction, t["published"].format(number=suggestion.number, url=message.jump_url), kind="success")

    async def publish(
        self,
        guild: discord.Guild,
        *,
        author: discord.abc.User,
        title: str,
        content: str,
        attachment: discord.Attachment | None,
        actor: Any,
    ) -> tuple[svc.Suggestion, discord.Message] | str:
        """Enregistre puis publie. Rend un message d'erreur, ou (suggestion, message)."""
        db = self.bot.db
        t = await lang_of(self.bot, guild.id)
        settings = await svc.get_settings(db, guild.id)
        try:
            suggestion = await svc.create(
                db, settings, author_id=author.id, title=title, content=content, now=_now(),
            )
        except svc.SuggestionError as error:
            return _error_text(t, error)

        channel = guild.get_channel(settings.channel_id) if settings.channel_id else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await svc.discard(db, suggestion.id)
            return t["errors"]["channel_gone"]

        files: list[discord.File] = []
        if attachment is not None and (attachment.content_type or "").startswith("image/"):
            # L'URL d'un fichier envoyé par formulaire expire : on le réhéberge
            # sur le message de la suggestion. Un échec n'empêche pas la publication.
            try:
                files.append(await attachment.to_file())
                await db.execute(
                    "UPDATE suggestions SET attachment_url = ? WHERE id = ?",
                    (f"attachment://{files[0].filename}", suggestion.id),
                )
                suggestion = await svc.get(db, suggestion.id) or suggestion
            except (discord.HTTPException, OSError):
                logger.warning("Image de suggestion non récupérée.", exc_info=True)
                files = []

        try:
            message = await panels.envoyer(channel, render(suggestion, 0, 0, t), files=files or None)
        except discord.HTTPException:
            logger.warning("Suggestion #%s non publiée dans %s.", suggestion.number, channel.id, exc_info=True)
            await svc.discard(db, suggestion.id)
            return t["errors"]["channel_gone"]

        thread_id = None
        if settings.threads and isinstance(channel, discord.TextChannel):
            try:
                thread = await message.create_thread(name=t["card_title"].format(number=suggestion.number)[:100])
                thread_id = thread.id
            except discord.HTTPException:
                logger.info("Fil de discussion non créé pour la suggestion #%s.", suggestion.number)
        await svc.attach_message(db, suggestion.id, channel_id=channel.id, message_id=message.id, thread_id=thread_id)

        await self._log(
            actor,
            "suggestion_created",
            "💡 Nouvelle suggestion",
            {
                "🔢 Numéro": f"#{suggestion.number:04d}",
                "📝 Titre": suggestion.title or "—",
                "🔗 Message": message.jump_url,
            },
        )
        return suggestion, message

    # --------------------------------------------------------------- votes

    async def _vote(self, interaction: discord.Interaction, value: int) -> None:
        t = await lang_of(self.bot, interaction.guild.id)
        message = interaction.message
        suggestion = await svc.by_message(self.bot.db, message.id) if message else None
        if suggestion is None:
            return await _say(interaction, t["errors"]["missing"])
        if not await _allowed(self.bot, interaction, "suggest"):
            return
        try:
            await svc.vote(self.bot.db, suggestion, interaction.user.id, value, _now())
        except svc.SuggestionError as error:
            return await _say(interaction, _error_text(t, error))
        up, down = await svc.counts(self.bot.db, suggestion.id)
        # Une seule réponse : la carte mise à jour sur place, sans message en plus.
        await interaction.response.edit_message(
            view=render(suggestion, up, down, t), allowed_mentions=discord.AllowedMentions.none()
        )

    # ------------------------------------------------------------ décision

    async def decide(self, interaction: discord.Interaction, suggestion_id: int, status: str, response: str) -> None:
        t = await lang_of(self.bot, getattr(interaction.guild, "id", None))
        if not await _allowed(self.bot, interaction, "suggestion-status"):
            return
        suggestion = await svc.get(self.bot.db, suggestion_id)
        if suggestion is None:
            return await _say(interaction, t["errors"]["missing"])
        try:
            updated = await svc.set_status(
                self.bot.db, suggestion, status=status, staff_id=interaction.user.id,
                response=response, now=_now(),
            )
        except svc.SuggestionError as error:
            return await _say(interaction, _error_text(t, error))
        up, down = await svc.counts(self.bot.db, updated.id)
        if interaction.message is not None and interaction.message.id == updated.message_id:
            await interaction.response.edit_message(
                view=render(updated, up, down, t), allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            edited = await self._refresh(updated, up, down)
            await _say(
                interaction,
                t["decided"].format(number=updated.number, status=t["status"][updated.status].lower())
                + ("" if edited else t["decided_missing"]),
                kind="success",
            )
        await self._log_decision(interaction, updated)

    async def _refresh(self, suggestion: svc.Suggestion, up: int, down: int) -> bool:
        """Met à jour la carte publiée. Rend False si le message n'existe plus."""
        guild = self.bot.get_guild(suggestion.guild_id)
        channel = guild.get_channel_or_thread(suggestion.channel_id) if guild and suggestion.channel_id else None
        if channel is None or suggestion.message_id is None:
            return False
        t = await lang_of(self.bot, suggestion.guild_id)
        try:
            message = channel.get_partial_message(suggestion.message_id)
            await message.edit(view=render(suggestion, up, down, t), allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            return False

    async def _log(self, actor: Any, event: str, title: str, fields: dict[str, str]) -> None:
        from utils.audit_trail import journaliser

        await journaliser(self.bot, actor, event, title, fields)

    async def _log_decision(self, actor: Any, suggestion: svc.Suggestion) -> None:
        await self._log(
            actor,
            "suggestion_status",
            "🗳️ Suggestion tranchée",
            {
                "🔢 Numéro": f"#{suggestion.number:04d}",
                "📌 Statut": TEXTS["fr"]["status"].get(suggestion.status, suggestion.status),
                "💬 Réponse": suggestion.staff_response or "—",
            },
        )

    # ------------------------------------------------------------- boutons

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        data = interaction.data if isinstance(interaction.data, dict) else {}
        custom_id = str(data.get("custom_id") or "")
        if interaction.type is not discord.InteractionType.component or not custom_id.startswith(PREFIX):
            return
        if interaction.response.is_done() or interaction.guild is None:
            return
        try:
            if custom_id == ID_NEW:
                if await _allowed(self.bot, interaction, "suggest"):
                    t = await lang_of(self.bot, interaction.guild.id)
                    await interaction.response.send_modal(SubmitModal(self, t))
            elif custom_id == ID_UP:
                await self._vote(interaction, 1)
            elif custom_id == ID_DOWN:
                await self._vote(interaction, -1)
            elif custom_id == ID_MANAGE:
                t = await lang_of(self.bot, interaction.guild.id)
                suggestion = await svc.by_message(self.bot.db, interaction.message.id) if interaction.message else None
                if suggestion is None:
                    return await _say(interaction, t["errors"]["missing"])
                if await _allowed(self.bot, interaction, "suggestion-status"):
                    await interaction.response.send_modal(ManageModal(self, suggestion, t))
        except discord.HTTPException:
            logger.warning("Bouton de suggestion %s : réponse Discord refusée.", custom_id, exc_info=True)

    # ------------------------------------------------------------ commandes

    async def _reply(self, ctx: commands.Context, text: str, *, ok: bool = True) -> None:
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(text) if ok else embeds.error(text)))

    @commands.command(name="suggest", help="Proposer une idée pour le serveur.")
    @commands.guild_only()
    async def suggest(self, ctx: commands.Context, *, texte: str | None = None) -> None:
        t = await lang_of(self.bot, ctx.guild.id)
        if not texte:
            return await panels.envoyer(ctx, render_box(t))
        result = await self.publish(
            ctx.guild, author=ctx.author, title="", content=texte, attachment=None, actor=ctx,
        )
        if isinstance(result, str):
            return await self._reply(ctx, result, ok=False)
        suggestion, message = result
        await self._reply(ctx, t["published"].format(number=suggestion.number, url=message.jump_url))

    @commands.command(name="suggestion-setup", help="Choisir le salon et les réglages des suggestions.")
    @commands.guild_only()
    async def suggestion_setup(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        cooldown: int = svc.DEFAULT_COOLDOWN_SECONDS // 60,
        anonymous: bool = False,
        threads: bool = False,
    ) -> None:
        t = await lang_of(self.bot, ctx.guild.id)
        me = ctx.guild.me
        perms = channel.permissions_for(me) if me else None
        if perms is None or not (perms.view_channel and perms.send_messages):
            return await self._reply(ctx, t["cannot_write"].format(channel=channel.mention), ok=False)
        try:
            settings = await svc.save_settings(
                self.bot.db, ctx.guild.id, actor_id=ctx.author.id, now=_now(),
                channel_id=channel.id, cooldown_seconds=max(0, int(cooldown)) * 60,
                anonymous=anonymous, threads=threads,
            )
        except svc.SuggestionError as error:
            return await self._reply(ctx, _error_text(t, error), ok=False)
        yes_no = lambda flag: t["yes"] if flag else t["no"]  # noqa: E731
        minutes = t["minutes"].format(n=settings.cooldown_seconds // 60)
        await self._log(
            ctx, "config_update", "⚙️ Suggestions configurées",
            {"📍 Salon": channel.mention, "⏱️ Délai": minutes,
             "🕶️ Anonyme": yes_no(settings.anonymous), "🧵 Fils": yes_no(settings.threads)},
        )
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre=t["setup_title"],
                kind="success",
                sections=[
                    panels.Section(
                        t["setup_settings"],
                        lignes=[
                            panels.Ligne(t["setup_channel"], channel.mention),
                            panels.Ligne(t["setup_cooldown"], minutes),
                            panels.Ligne(t["setup_anonymous"], yes_no(settings.anonymous)),
                            panels.Ligne(t["setup_threads"], yes_no(settings.threads)),
                        ],
                    ),
                    panels.Section(t["setup_next"], texte=t["setup_next_text"]),
                ],
            ),
        )

    @commands.command(name="suggestion-panel", help="Publier la boîte à suggestions dans un salon.")
    @commands.guild_only()
    async def suggestion_panel(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        t = await lang_of(self.bot, ctx.guild.id)
        target = channel or ctx.channel
        try:
            message = await panels.envoyer(target, render_box(t))
        except discord.HTTPException:
            return await self._reply(ctx, t["cannot_write"].format(channel=target.mention), ok=False)
        await self._log(ctx, "config_update", "⚙️ Boîte à suggestions publiée", {"📍 Salon": target.mention})
        if target != ctx.channel:
            await self._reply(ctx, t["box_published"].format(url=message.jump_url))

    @commands.command(name="suggestion-status", help="Changer le statut d'une suggestion.")
    @commands.guild_only()
    async def suggestion_status(
        self, ctx: commands.Context, number: int, status: str, *, response: str | None = None,
    ) -> None:
        t = await lang_of(self.bot, ctx.guild.id)
        status = str(status or "").casefold().strip()
        if status not in svc.STATUSES:
            choices = ", ".join(f"`{s}`" for s in svc.STATUSES)
            return await self._reply(ctx, t["unknown_status"].format(choices=choices), ok=False)
        suggestion = await svc.by_number(self.bot.db, ctx.guild.id, number)
        if suggestion is None:
            return await self._reply(ctx, t["unknown_number"].format(number=number), ok=False)
        updated = await svc.set_status(
            self.bot.db, suggestion, status=status, staff_id=ctx.author.id, response=response, now=_now(),
        )
        up, down = await svc.counts(self.bot.db, updated.id)
        edited = await self._refresh(updated, up, down)
        await self._log_decision(ctx, updated)
        await self._reply(
            ctx,
            t["decided"].format(number=updated.number, status=t["status"][updated.status].lower())
            + ("" if edited else t["decided_missing"]),
        )


def _native_submit(bot: commands.Bot) -> app_commands.Command:
    """/suggestions submit : ouvre le formulaire AVANT tout defer."""

    async def callback(interaction: discord.Interaction) -> None:
        cog = bot.get_cog("Suggestions")
        t = await lang_of(bot, getattr(interaction.guild, "id", None))
        if cog is None or interaction.guild is None:
            return await _say(interaction, t["guild_only"])
        if not await _allowed(bot, interaction, "suggest"):
            return
        settings = await svc.get_settings(bot.db, interaction.guild.id)
        if not settings.configured:
            return await _say(interaction, t["errors"]["not_configured"])
        await interaction.response.send_modal(SubmitModal(cog, t))

    callback._sentrix_original_command = "suggest"
    return app_commands.Command(name="submit", description="Submit a suggestion.", callback=callback)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestions(bot))
    from utils import slash_catalog

    slash_catalog.register_native("suggest", _native_submit)
