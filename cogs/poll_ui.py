"""Créateur interactif de sondages natifs Discord pour SentriX."""

from __future__ import annotations

import datetime
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels


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
    embed.set_footer(text=f"{len(answers)}/10 réponses • Modifiez les options puis cliquez sur Publier")
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
            return await interaction.response.send_message(
                "Seule la personne qui a lancé le créateur peut continuer.",
                ephemeral=True,
            )

        answers = _clean_answers([
            self.answer_1.value,
            self.answer_2.value,
            self.answer_3.value,
            self.answer_4.value,
        ])
        error = _answers_error(answers)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        view = PollBuilderView(
            self.bot,
            author_id=self.author_id,
            question=str(self.question.value).strip(),
            answers=answers,
        )
        embed = _builder_embed(view.question, view.answers, view.duration_hours, view.multiple)
        if self.direct_from_slash:
            await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embed), view), ephemere=True)
        else:
            await interaction.response.edit_message(embed=embed, view=view)


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
            return await interaction.response.send_message(
                "Seule la personne qui a lancé le créateur peut continuer.",
                ephemeral=True,
            )

        additions = _clean_answers([item.value for item in self.inputs])
        candidate = [*self.builder.answers, *additions]
        error = _answers_error(candidate)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

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
        self.add_item(DurationSelect())
        self.add_item(VoteModeSelect())
        self._update_buttons()

    def _update_buttons(self):
        self.add_answers.disabled = len(self.answers) >= 10
        self.remove_answer.disabled = len(self.answers) <= 2

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne qui a lancé le créateur peut modifier ce sondage.",
                ephemeral=True,
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        self._update_buttons()
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(_builder_embed(self.question, self.answers, self.duration_hours, self.multiple)), self))

    @discord.ui.button(label="Ajouter des réponses", emoji="➕", style=discord.ButtonStyle.secondary, row=2)
    async def add_answers(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.answers) >= 10:
            return await interaction.response.send_message(
                "Le sondage contient déjà 10 réponses.",
                ephemeral=True,
            )
        await interaction.response.send_modal(AddAnswersModal(self))

    @discord.ui.button(label="Retirer la dernière", emoji="➖", style=discord.ButtonStyle.secondary, row=2)
    async def remove_answer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.answers) > 2:
            self.answers.pop()
        await self.refresh(interaction)

    @discord.ui.button(label="Publier", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild = interaction.guild
        if channel is None or guild is None or guild.me is None:
            return await interaction.response.send_message(
                "Ce sondage doit être publié dans un salon de serveur.",
                ephemeral=True,
            )

        permissions = channel.permissions_for(guild.me)
        if not permissions.send_messages or not getattr(permissions, "create_polls", True):
            return await interaction.response.send_message(
                "SentriX doit avoir les permissions **Envoyer des messages** et **Créer des sondages** dans ce salon.",
                ephemeral=True,
            )

        poll = discord.Poll(
            question=self.question,
            duration=datetime.timedelta(hours=self.duration_hours),
            multiple=self.multiple,
        )
        for answer in self.answers:
            poll.add_answer(text=answer)

        try:
            message = await channel.send(poll=poll)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Discord a refusé l'envoi. Vérifiez les permissions de SentriX.",
                ephemeral=True,
            )
        except (discord.HTTPException, ValueError):
            return await interaction.response.send_message(
                "Discord n'a pas pu créer ce sondage. Vérifiez les réponses et réessayez.",
                ephemeral=True,
            )

        success = embeds.success(
            f"Sondage publié dans {channel.mention}.\n[Voir le sondage]({message.jump_url})"
        )
        await panels.editer(interaction.response, panels.depuis_embed(success))
        self.stop()

    @discord.ui.button(label="Annuler", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await panels.editer(interaction.response, panels.depuis_embed(embeds.error('Création du sondage annulée.')))
        self.stop()


class PollLauncherView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne qui a utilisé `+poll` peut ouvrir ce créateur.",
                ephemeral=True,
            )
            return False
        return True

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
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))

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
            error = _answers_error(answers)
            if not poll_question or len(poll_question) > 300 or not 1 <= duration_hours <= 168 or error:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le sondage écrit est invalide. Utilisez simplement `+poll` pour ouvrir le créateur interactif.')))

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
            try:
                return await ctx.send(**kwargs)
            except (discord.Forbidden, discord.HTTPException, ValueError):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Discord a refusé ce sondage. Vérifiez les permissions du bot.')))

        if ctx.interaction is not None:
            return await ctx.interaction.response.send_modal(
                PollSetupModal(self.bot, ctx.author.id, direct_from_slash=True)
            )

        embed = embeds.brand(
            "📊 Créer un sondage",
            "Cliquez sur le bouton ci-dessous. Une fenêtre Discord vous demandera la question et les réponses. "
            "Vous pourrez ensuite choisir la durée et publier le sondage.",
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
