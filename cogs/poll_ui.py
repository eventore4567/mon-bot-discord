"""Créateur interactif de sondages natifs Discord pour SentriX."""

from __future__ import annotations

import asyncio
import datetime
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels


logger = logging.getLogger("bot.poll-ui")

_DURATION_RE = re.compile(r"^\[(\d{1,3})h\]\s*", re.IGNORECASE)
_DURATION_LABELS = {
    1: "1 heure",
    4: "4 heures",
    8: "8 heures",
    12: "12 heures",
    24: "1 jour",
    72: "3 jours",
    168: "7 jours",
}


def _clean_answers(values: list[str]) -> list[str]:
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _answers_error(answers: list[str]) -> str | None:
    if not 2 <= len(answers) <= 10:
        return "Un sondage doit contenir entre **2 et 10 réponses**."
    if any(len(answer) > 55 for answer in answers):
        return "Chaque réponse doit contenir au maximum **55 caractères**."
    normalised = [answer.casefold() for answer in answers]
    if len(set(normalised)) != len(normalised):
        return "Chaque réponse doit être différente."
    return None


def _poll_error(question: str, answers: list[str], duration_hours: int) -> str | None:
    question = str(question or "").strip()
    if not question:
        return "La question du sondage ne peut pas être vide."
    if len(question) > 300:
        return "La question doit contenir au maximum **300 caractères**."
    if not 1 <= duration_hours <= 168:
        return "La durée doit être comprise entre **1 heure et 7 jours**."
    return _answers_error(answers)


async def _interaction_notice(interaction: discord.Interaction, message: str):
    """Répond sans jamais laisser Discord afficher « Action interrompue ».

    Une interaction Discord n'accepte qu'une réponse initiale. Après un ``defer``
    (utilisé pendant la publication du sondage), les erreurs doivent donc passer
    par le follow-up. Ce helper choisit automatiquement la bonne surface.
    """
    response = interaction.response
    try:
        if not response.is_done():
            return await response.send_message(message, ephemeral=True)
    except discord.InteractionResponded:
        pass
    except Exception as exc:
        logger.warning("Réponse initiale Poll impossible: %s", exc)

    try:
        return await interaction.followup.send(message, ephemeral=True)
    except Exception as exc:
        logger.warning("Follow-up Poll impossible: %s", exc)
        return None


async def _defer_component(interaction: discord.Interaction) -> None:
    """Acquitte immédiatement un clic avant un appel réseau potentiellement lent."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.InteractionResponded:
        pass


async def _report_interaction_error(interaction: discord.Interaction, error: Exception) -> None:
    logger.error(
        "Erreur inattendue dans l'interface Poll",
        exc_info=(type(error), error, error.__traceback__),
    )
    await _interaction_notice(
        interaction,
        "Une erreur inattendue a interrompu cette action. Le créateur reste ouvert : réessayez dans quelques secondes.",
    )


def _builder_embed(question: str, answers: list[str], duration_hours: int, multiple: bool) -> discord.Embed:
    answer_lines = "\n".join(f"**{index}.** {answer}" for index, answer in enumerate(answers, start=1))
    embed = embeds.brand(
        "📊 Créateur de sondage",
        f"**Question**\n{question}\n\n**Réponses**\n{answer_lines}",
    )
    embed.add_field(
        name="Durée",
        value=_DURATION_LABELS.get(duration_hours, f"{duration_hours} heures"),
        inline=True,
    )
    embed.add_field(
        name="Choix autorisés",
        value="Plusieurs réponses" if multiple else "Une seule réponse",
        inline=True,
    )
    embed.set_footer(
        text=f"{len(answers)}/10 réponses • Question, réponses, durée et mode restent modifiables avant publication"
    )
    return embed


class PollSetupModal(discord.ui.Modal, title="Créer un sondage"):
    question = discord.ui.TextInput(
        label="Question",
        placeholder="Exemple : Événement Valorant ce soir ?",
        max_length=300,
    )
    answer_1 = discord.ui.TextInput(
        label="Réponse 1",
        placeholder="Oui, ça va être super",
        max_length=55,
    )
    answer_2 = discord.ui.TextInput(
        label="Réponse 2",
        placeholder="Non",
        max_length=55,
    )
    answer_3 = discord.ui.TextInput(
        label="Réponse 3 (facultative)",
        required=False,
        max_length=55,
    )
    answer_4 = discord.ui.TextInput(
        label="Réponse 4 (facultative)",
        required=False,
        max_length=55,
    )

    def __init__(self, bot: commands.Bot, author_id: int, *, direct_from_slash: bool):
        super().__init__()
        self.bot = bot
        self.author_id = author_id
        self.direct_from_slash = direct_from_slash

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await _interaction_notice(
                interaction,
                "Seule la personne qui a lancé le créateur peut continuer.",
            )

        answers = _clean_answers([
            self.answer_1.value,
            self.answer_2.value,
            self.answer_3.value,
            self.answer_4.value,
        ])
        question = str(self.question.value).strip()
        error = _poll_error(question, answers, 24)
        if error:
            return await _interaction_notice(interaction, error)

        view = PollBuilderView(
            self.bot,
            author_id=self.author_id,
            question=question,
            answers=answers,
        )
        embed = _builder_embed(view.question, view.answers, view.duration_hours, view.multiple)
        if self.direct_from_slash:
            await panels.envoyer(
                interaction.response,
                panels.avec_composants(panels.depuis_embed(embed), view),
                ephemere=True,
            )
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_interaction_error(interaction, error)


class AddAnswersModal(discord.ui.Modal, title="Ajouter des réponses"):
    def __init__(self, builder: "PollBuilderView"):
        super().__init__()
        self.builder = builder
        self.inputs: list[discord.ui.TextInput] = []
        remaining = min(5, 10 - len(builder.answers))
        for offset in range(remaining):
            number = len(builder.answers) + offset + 1
            field = discord.ui.TextInput(
                label=f"Réponse {number}",
                required=offset == 0,
                max_length=55,
            )
            self.inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.builder.author_id:
            return await _interaction_notice(
                interaction,
                "Seule la personne qui a lancé le créateur peut continuer.",
            )

        additions = _clean_answers([item.value for item in self.inputs])
        candidate = [*self.builder.answers, *additions]
        error = _poll_error(self.builder.question, candidate, self.builder.duration_hours)
        if error:
            return await _interaction_notice(interaction, error)

        self.builder.answers = candidate
        await interaction.response.edit_message(
            embed=_builder_embed(
                self.builder.question,
                self.builder.answers,
                self.builder.duration_hours,
                self.builder.multiple,
            ),
            view=self.builder,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_interaction_error(interaction, error)


class EditQuestionModal(discord.ui.Modal, title="Modifier la question"):
    def __init__(self, builder: "PollBuilderView"):
        super().__init__()
        self.builder = builder
        self.question = discord.ui.TextInput(
            label="Question",
            default=builder.question,
            max_length=300,
        )
        self.add_item(self.question)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.builder.author_id:
            return await _interaction_notice(
                interaction,
                "Seule la personne qui a lancé le créateur peut continuer.",
            )

        question = str(self.question.value).strip()
        error = _poll_error(
            question,
            self.builder.answers,
            self.builder.duration_hours,
        )
        if error:
            return await _interaction_notice(interaction, error)

        self.builder.question = question
        await self.builder.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_interaction_error(interaction, error)


class DurationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=str(hours), default=hours == 24)
            for hours, label in _DURATION_LABELS.items()
        ]
        super().__init__(
            placeholder="Choisir la durée du sondage",
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        builder: PollBuilderView = self.view  # type: ignore[assignment]
        builder.duration_hours = int(self.values[0])
        for option in self.options:
            option.default = option.value == self.values[0]
        await builder.refresh(interaction)


class VoteModeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choisir le type de vote",
            options=[
                discord.SelectOption(
                    label="Une seule réponse",
                    description="Chaque membre choisit une seule option",
                    value="single",
                    default=True,
                ),
                discord.SelectOption(
                    label="Plusieurs réponses",
                    description="Chaque membre peut choisir plusieurs options",
                    value="multiple",
                ),
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        builder: PollBuilderView = self.view  # type: ignore[assignment]
        builder.multiple = self.values[0] == "multiple"
        for option in self.options:
            option.default = option.value == self.values[0]
        await builder.refresh(interaction)


class PollBuilderView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        author_id: int,
        question: str,
        answers: list[str],
    ):
        super().__init__(timeout=600)
        self.bot = bot
        self.author_id = author_id
        self.question = question
        self.answers = answers
        self.duration_hours = 24
        self.multiple = False
        self._publish_lock = asyncio.Lock()
        self.add_item(DurationSelect())
        self.add_item(VoteModeSelect())
        self._update_buttons()

    def _update_buttons(self):
        self.add_answers.disabled = len(self.answers) >= 10
        self.remove_answer.disabled = len(self.answers) <= 2

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await _interaction_notice(
                interaction,
                "Seule la personne qui a lancé le créateur peut modifier ce sondage.",
            )
            return False
        if self._publish_lock.locked():
            await _interaction_notice(
                interaction,
                "La publication du sondage est déjà en cours.",
            )
            return False
        return True

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        await _report_interaction_error(interaction, error)

    async def refresh(self, interaction: discord.Interaction):
        self._update_buttons()
        await panels.editer(
            interaction.response,
            panels.avec_composants(
                panels.depuis_embed(
                    _builder_embed(
                        self.question,
                        self.answers,
                        self.duration_hours,
                        self.multiple,
                    )
                ),
                self,
            ),
        )

    @discord.ui.button(label="Ajouter des réponses", emoji="➕", style=discord.ButtonStyle.secondary, row=2)
    async def add_answers(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.answers) >= 10:
            return await _interaction_notice(
                interaction,
                "Le sondage contient déjà 10 réponses.",
            )
        await interaction.response.send_modal(AddAnswersModal(self))

    @discord.ui.button(label="Retirer la dernière", emoji="➖", style=discord.ButtonStyle.secondary, row=2)
    async def remove_answer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.answers) > 2:
            self.answers.pop()
        await self.refresh(interaction)

    @discord.ui.button(label="Modifier question", emoji="✏️", style=discord.ButtonStyle.secondary, row=2)
    async def edit_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditQuestionModal(self))

    @discord.ui.button(label="Publier", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild = interaction.guild
        if channel is None or guild is None or guild.me is None:
            return await _interaction_notice(
                interaction,
                "Ce sondage doit être publié dans un salon de serveur.",
            )

        if self._publish_lock.locked():
            return await _interaction_notice(
                interaction,
                "La publication du sondage est déjà en cours.",
            )

        permissions = channel.permissions_for(guild.me)
        if not permissions.send_messages or not getattr(permissions, "create_polls", True):
            return await _interaction_notice(
                interaction,
                "SentriX doit avoir les permissions **Envoyer des messages** et **Créer des sondages** dans ce salon.",
            )

        error = _poll_error(self.question, self.answers, self.duration_hours)
        if error:
            return await _interaction_notice(interaction, error)

        async with self._publish_lock:
            # Discord exige un ACK très rapidement. On répond AVANT ``channel.send`` :
            # un pic réseau ne peut donc plus se transformer en « Action interrompue ».
            await _defer_component(interaction)
            try:
                poll = discord.Poll(
                    question=self.question,
                    duration=datetime.timedelta(hours=self.duration_hours),
                    multiple=self.multiple,
                )
                for answer in self.answers:
                    poll.add_answer(text=answer)
                message = await channel.send(poll=poll)
            except discord.Forbidden:
                return await _interaction_notice(
                    interaction,
                    "Discord a refusé l'envoi. Vérifiez les permissions de SentriX.",
                )
            except discord.HTTPException as exc:
                logger.warning("Publication Poll refusée par Discord: status=%s", getattr(exc, "status", "?"))
                return await _interaction_notice(
                    interaction,
                    "Discord n'a pas pu créer ce sondage pour le moment. Réessayez dans quelques secondes.",
                )
            except (ValueError, TypeError, AttributeError):
                return await _interaction_notice(
                    interaction,
                    "Discord n'a pas pu créer ce sondage. Vérifiez la question et les réponses puis réessayez.",
                )

            success = embeds.success(
                f"Sondage publié dans {channel.mention}.\n[Voir le sondage]({message.jump_url})"
            )
            await panels.editer(interaction, panels.depuis_embed(success))
            self.stop()

    @discord.ui.button(label="Annuler", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._publish_lock.locked():
            return await _interaction_notice(
                interaction,
                "La publication du sondage est déjà en cours.",
            )
        await panels.editer(
            interaction.response,
            panels.depuis_embed(embeds.error("Création du sondage annulée.")),
        )
        self.stop()


class PollLauncherView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await _interaction_notice(
                interaction,
                "Seule la personne qui a utilisé `+poll` peut ouvrir ce créateur.",
            )
            return False
        return True

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        await _report_interaction_error(interaction, error)

    @discord.ui.button(label="Créer le sondage", emoji="📊", style=discord.ButtonStyle.primary)
    async def create_poll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            PollSetupModal(self.bot, self.author_id, direct_from_slash=False)
        )


class PollUI(commands.Cog, name="PollUI"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="poll",
        description="Créer facilement un sondage natif Discord avec un menu interactif.",
    )
    @app_commands.describe(
        question="Facultatif : laissez vide pour ouvrir le créateur interactif"
    )
    async def poll(self, ctx: commands.Context, *, question: str = None):
        if ctx.guild is None:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("Cette commande doit être utilisée sur un serveur.")),
            )

        raw = str(question or "").strip()
        if raw:
            duration_hours = 24
            duration_match = _DURATION_RE.match(raw)
            if duration_match:
                duration_hours = int(duration_match.group(1))
                raw = raw[duration_match.end():].strip()
            parts = [part.strip() for part in raw.split("|")]
            poll_question = parts[0] if parts else ""
            answers = _clean_answers(parts[1:] if len(parts) > 1 else ["Oui", "Non"])
            error = _poll_error(poll_question, answers, duration_hours)
            if error:
                return await panels.envoyer(
                    ctx,
                    panels.depuis_embed(
                        embeds.error(
                            f"{error}\nUtilisez simplement `+poll` pour ouvrir le créateur interactif."
                        )
                    ),
                )

            try:
                poll = discord.Poll(
                    question=poll_question,
                    duration=datetime.timedelta(hours=duration_hours),
                    multiple=False,
                )
                for answer in answers:
                    poll.add_answer(text=answer)
                kwargs = {"poll": poll}
                if ctx.interaction is None:
                    kwargs["reference"] = None
                    kwargs["mention_author"] = False
                return await ctx.send(**kwargs)
            except (discord.Forbidden, discord.HTTPException, ValueError, TypeError, AttributeError):
                return await panels.envoyer(
                    ctx,
                    panels.depuis_embed(
                        embeds.error("Discord a refusé ce sondage. Vérifiez les permissions du bot.")
                    ),
                )

        if ctx.interaction is not None:
            return await ctx.interaction.response.send_modal(
                PollSetupModal(self.bot, ctx.author.id, direct_from_slash=True)
            )

        embed = embeds.brand(
            "📊 Créer un sondage",
            "Cliquez sur le bouton ci-dessous. Une fenêtre Discord vous demandera la question et les réponses. "
            "Vous pourrez ensuite modifier la question, ajouter ou retirer des réponses, choisir la durée et publier.",
        )
        # reference=None / mention_author=False etaient les valeurs par defaut :
        # sans reponse citee, mention_author n'a aucun effet.
        await panels.envoyer(
            ctx,
            panels.avec_composants(
                panels.depuis_embed(embed),
                PollLauncherView(self.bot, ctx.author.id),
            ),
        )


async def install_poll_ui(bot: commands.Bot):
    """Remplace l'ancienne commande de réactions par le créateur interactif."""
    existing = bot.get_cog("PollUI")
    if existing is not None:
        await bot.remove_cog("PollUI")

    old_command = bot.remove_command("poll")
    if old_command is not None:
        old_command.hidden = True
    bot.tree.remove_command("poll", type=discord.AppCommandType.chat_input)

    await bot.add_cog(PollUI(bot))

    try:
        from . import utility as utility_module

        utility_module.CATEGORY_LABELS["PollUI"] = "📊 Sondages"
    except Exception:
        pass