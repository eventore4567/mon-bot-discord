"""Historique des membres et débannissement sécurisé pour les logs Components V2."""
from __future__ import annotations

import datetime as dt
import logging
import re

import discord
from discord.ext import commands

from utils import access_matrix
from utils.wide_logs import fetch_log_history, safe_text

logger = logging.getLogger("bot.log-center")
NO_MENTIONS = discord.AllowedMentions.none()
PER_PAGE = 4

TYPES = {
    "member_warn": ("Avertissement", "⚠️"),
    "member_timeout": ("Timeout", "⏱️"),
    "member_untimeout": ("Fin de timeout", "✅"),
    "member_ban": ("Bannissement", "🚫"),
    "member_unban": ("Débannissement", "🛡️"),
    "member_kick": ("Expulsion", "🚪"),
    "member_leave": ("Départ", "📤"),
    "member_join": ("Arrivée", "📥"),
    "role_add": ("Rôle ajouté", "➕"),
    "role_remove": ("Rôle retiré", "➖"),
    "member_roles": ("Rôles modifiés", "🛡️"),
    "message_delete": ("Message supprimé", "🗑️"),
    "message_edit": ("Message modifié", "✏️"),
}
COUNTERS = {
    "warn": {"member_warn"},
    "mute": {"member_timeout"},
    "ban": {"member_ban"},
    "kick": {"member_kick"},
}


def _member_is_staff(user: discord.abc.User) -> bool:
    perms = getattr(user, "guild_permissions", None)
    return bool(perms and (
        perms.administrator or perms.manage_guild or perms.ban_members
        or perms.moderate_members
    ))


async def _access(interaction: discord.Interaction, *, unban: bool = False) -> str | None:
    guild = interaction.guild
    if guild is None or interaction.user is None:
        return "Cette action est uniquement disponible sur un serveur."
    if not _member_is_staff(interaction.user):
        return "Vous devez faire partie de la modération pour consulter ce dossier."
    if unban:
        perms = getattr(interaction.user, "guild_permissions", None)
        if not getattr(perms, "ban_members", False) and not getattr(perms, "administrator", False):
            return "La permission Discord Bannir des membres est obligatoire."
        me = guild.me
        if me is None or not me.guild_permissions.ban_members:
            return "SentriX n'a pas la permission Bannir des membres."
        try:
            decision = await access_matrix.evaluate(
                interaction.client,
                command_name="unban",
                author=interaction.user,
                guild=guild,
            )
        except Exception:
            logger.exception("Contrôle des permissions SentriX impossible")
            return "Impossible de vérifier les permissions SentriX."
        if not decision.allowed:
            return safe_text(decision.message or "Action refusée par les permissions SentriX.")
    return None


def _date(timestamp: int) -> str:
    try:
        return discord.utils.format_dt(
            dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc), style="f"
        )
    except (ValueError, OverflowError, TypeError):
        return "Date inconnue"


class MemberHistoryView(discord.ui.LayoutView):
    """Dossier privé paginé ; le sélecteur permet de changer de membre."""

    def __init__(self, *, author_id: int, guild_id: int, target_id: int):
        super().__init__(timeout=300)
        self.author_id = int(author_id)
        self.guild_id = int(guild_id)
        self.target_id = int(target_id)
        self.page = 0
        self.records: list[dict] = []
        self.selector: discord.ui.UserSelect | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seul le modérateur ayant ouvert ce dossier peut le modifier.",
                ephemeral=True,
            )
            return False
        denied = await _access(interaction)
        if denied:
            await interaction.response.send_message(denied, ephemeral=True)
            return False
        return True

    async def render(self, guild: discord.Guild) -> None:
        self.records = await fetch_log_history(self.guild_id, self.target_id, limit=50)
        self.clear_items()
        page_count = max(1, (len(self.records) + PER_PAGE - 1) // PER_PAGE)
        self.page = max(0, min(self.page, page_count - 1))
        member = guild.get_member(self.target_id)
        username = safe_text(member.display_name if member else str(self.target_id))
        counters = {
            key: sum(1 for record in self.records if record["log_type"] in events)
            for key, events in COUNTERS.items()
        }
        container = discord.ui.Container(accent_colour=discord.Colour(0x879BFF))
        container.add_item(discord.ui.TextDisplay(
            "## 🛡️ SENTRIX · HISTORIQUE DU MEMBRE\n"
            f"### {username}\n"
            "-# Dossier de modération • Les événements sont conservés sans référence publique."
        ))
        container.add_item(discord.ui.TextDisplay(
            f"**{counters['warn']}** avertissements   ·   "
            f"**{counters['mute']}** timeouts   ·   "
            f"**{counters['ban']}** bans   ·   **{counters['kick']}** exclusions"
        ))
        container.add_item(discord.ui.Separator())
        subset = self.records[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        if not subset:
            container.add_item(discord.ui.TextDisplay(
                "Aucun événement enregistré pour ce membre."
            ))
        for record in subset:
            title, icon = TYPES.get(record["log_type"], (safe_text(record["title"]) or "Événement", "📋"))
            moderator = (
                f" • Par <@{record['moderator_id']}>"
                if record.get("moderator_id") else ""
            )
            detail = safe_text(record.get("description") or "")
            if len(detail) > 250:
                detail = detail[:247] + "…"
            container.add_item(discord.ui.TextDisplay(
                f"**{icon} {title}**  ·  {_date(record['created_at'])}"
                f"{moderator}\n{detail or 'Aucun détail enregistré.'}"
            ))
        container.add_item(discord.ui.TextDisplay(
            f"-# Page {self.page + 1}/{page_count} · {len(self.records)} événements consultables"
        ))
        selector = discord.ui.UserSelect(
            placeholder="Choisir un autre membre du serveur…",
            min_values=1,
            max_values=1,
        )
        selector.callback = self._change_target
        self.selector = selector
        container.add_item(discord.ui.ActionRow(selector))
        previous = discord.ui.Button(
            label="Précédent", style=discord.ButtonStyle.secondary, disabled=self.page == 0
        )
        following = discord.ui.Button(
            label="Suivant", style=discord.ButtonStyle.secondary,
            disabled=self.page >= page_count - 1,
        )
        previous.callback = self._previous
        following.callback = self._following
        container.add_item(discord.ui.ActionRow(previous, following))
        self.add_item(container)

    async def _change_target(self, interaction: discord.Interaction) -> None:
        if not self.selector or not self.selector.values:
            return
        self.target_id = int(self.selector.values[0].id)
        self.page = 0
        await self.render(interaction.guild)
        await interaction.response.edit_message(view=self)

    async def _previous(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        await self.render(interaction.guild)
        await interaction.response.edit_message(view=self)

    async def _following(self, interaction: discord.Interaction) -> None:
        self.page += 1
        await self.render(interaction.guild)
        await interaction.response.edit_message(view=self)


class ConfirmUnban(discord.ui.View):
    def __init__(self, *, author_id: int, guild_id: int, target_id: int):
        super().__init__(timeout=90)
        self.author_id = int(author_id)
        self.guild_id = int(guild_id)
        self.target_id = int(target_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seul le modérateur ayant demandé cette confirmation peut répondre.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirmer le débannissement", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        denied = await _access(interaction, unban=True)
        if denied:
            await interaction.response.send_message(denied, ephemeral=True)
            return
        guild = interaction.guild
        if guild.id != self.guild_id:
            await interaction.response.send_message("Ce bouton n'appartient pas à ce serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await guild.fetch_ban(discord.Object(id=self.target_id))
        except discord.NotFound:
            await interaction.edit_original_response(
                content="Ce membre n'est déjà plus banni.", view=None
            )
            return
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="SentriX ne peut pas vérifier ce bannissement.", view=None
            )
            return
        except discord.HTTPException:
            await interaction.edit_original_response(
                content="Discord ne répond pas. Réessayez plus tard.", view=None
            )
            return
        try:
            await guild.unban(
                discord.Object(id=self.target_id),
                reason=f"Débannissement confirmé par {interaction.user} (ID {interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Débannissement impossible guild=%s target=%s", guild.id, self.target_id)
            await interaction.edit_original_response(
                content="Discord a refusé le débannissement. Vérifiez les permissions de SentriX.",
                view=None,
            )
            return
        # on_member_unban émet le nouveau log et archive l'action sans supprimer le ban initial.
        await interaction.edit_original_response(
            content=f"✅ <@{self.target_id}> a été débanni par <@{interaction.user.id}>.",
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Débannissement annulé.", view=None)
        self.stop()


class PremiumLogAction(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"sentrix:premiumlog:(?P<action>history|unban):(?P<guild_id>[0-9]{15,22}):(?P<target_id>[0-9]{15,22})",
):
    """Boutons persistants, y compris après un redémarrage Railway."""

    def __init__(self, action: str, guild_id: int, target_id: int):
        self.action = action
        self.guild_id = int(guild_id)
        self.target_id = int(target_id)
        super().__init__(discord.ui.Button(
            label="Historique" if action == "history" else "Débannir",
            emoji="📜" if action == "history" else "🛡️",
            style=discord.ButtonStyle.secondary if action == "history" else discord.ButtonStyle.success,
            custom_id=f"sentrix:premiumlog:{action}:{guild_id}:{target_id}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match, /):
        return cls(match["action"], int(match["guild_id"]), int(match["target_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Ce log appartient à un autre serveur.", ephemeral=True)
            return
        denied = await _access(interaction, unban=self.action == "unban")
        if denied:
            await interaction.response.send_message(denied, ephemeral=True)
            return
        if self.action == "history":
            try:
                panel = MemberHistoryView(
                    author_id=interaction.user.id,
                    guild_id=self.guild_id,
                    target_id=self.target_id,
                )
                await panel.render(interaction.guild)
            except Exception:
                logger.exception("Ouverture du dossier impossible")
                await interaction.response.send_message(
                    "Impossible de charger l'historique pour le moment.", ephemeral=True,
                )
                return
            await interaction.response.send_message(view=panel, ephemeral=True)
            return
        view = ConfirmUnban(
            author_id=interaction.user.id,
            guild_id=self.guild_id,
            target_id=self.target_id,
        )
        await interaction.response.send_message(
            f"**Confirmer le débannissement de <@{self.target_id}> ?**\n"
            "Cette opération sera enregistrée dans les logs.",
            view=view,
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )


class LogHistoryCenter(commands.Cog, name="LogHistoryCenter"):
    """Extension légère : les boutons persistants sont enregistrés dans setup_hook."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LogHistoryCenter(bot))
