"""Historique des membres et débannissement sécurisé pour les logs Components V2."""
from __future__ import annotations

import datetime as dt
import logging
import re

import discord
from discord.ext import commands

from utils import access_matrix
from utils.wide_logs import fetch_log_history_page, safe_text

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
FILTERS = {
    "all": None,
    "warn": ("member_warn",),
    "mute": ("member_timeout", "member_untimeout"),
    "ban": ("member_ban", "member_unban"),
    "kick": ("member_kick",),
    "roles": ("role_add", "role_remove", "member_roles"),
    "messages": ("message_delete", "message_edit", "message_bulk"),
    "members": ("member_join", "member_leave"),
}
FILTER_LABELS = {
    "all": "Tout", "warn": "Warns", "mute": "Mutes", "ban": "Bans",
    "kick": "Kicks", "roles": "Rôles", "messages": "Messages", "members": "Membres",
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


def _history_detail(description: object) -> str:
    """Lisible : labels structurés, suppression des doublons de salons."""
    lines: list[str] = []
    for index, raw in enumerate(safe_text(description).splitlines()):
        line = raw.strip()
        if not line:
            continue
        key = re.sub(r"[*_]", "", line).strip()
        if index == 0 and line.startswith("**") and line.endswith("**"):
            continue
        if re.match(
            r"^(?:ID|Réf(?:érence)?|Dossier|Membre|Modérateur|Moderateur|Auteur|Cible|Historique)\s*[:#]",
            key, re.I,
        ):
            continue
        if re.search(r"\b(?:SX-[A-Z0-9]+|(?:BAN|WARN|MUTE|KICK)-\d+)\b", key, re.I):
            continue
        # Ne garder qu'une mention de salon : l'ancien log répète aussi son nom.
        line = re.sub(
            r"^(Salon\s*:\s*<#[0-9]+>)\s*[·•]\s*." + chr(96) +
            r"?#[^\n" + chr(96) + r"]+" + chr(96) + r"?\s*$",
            r"\1", line, flags=re.I,
        )
        match = re.match(
            r"^(Salon|Rôle|Role|Contenu|Motif|Raison|Supprimé par|Modifié par|"
            r"Ajouté par|Retiré par)\s*:\s*(.*)$", line, flags=re.I,
        )
        if match:
            label, value = match.groups()
            if label.casefold() == "contenu":
                line = f"**Contenu**\n> {value or 'Message vide'}"
            else:
                line = f"**{label}** · {value}"
        lines.append(line)
        if len("\n".join(lines)) > 520:
            break
    result = "\n".join(lines).strip()
    return result[:467] + "…" if len(result) > 470 else (result or "Aucun détail supplémentaire enregistré.")


def _history_event_block(record: dict, *, index: int) -> str:
    """Un événement, un bloc distinct : date, acteur, motif et contenu."""
    title, emoji = TYPES.get(
        record["log_type"],
        (safe_text(record.get("title")) or "Événement", "📋"),
    )
    when = _date(record["created_at"])
    timestamp = int(record["created_at"])
    relative = f"<t:{timestamp}:R>" if timestamp > 0 else ""
    moderator = (
        f"**Responsable** · <@{record['moderator_id']}>\n"
        if record.get("moderator_id") else ""
    )
    detail = _history_detail(record.get("description") or "")
    return (
        f"**{emoji} {title}**   ·   {relative}\n"
        f"-# Événement {index:02d} · {when}\n\n"
        f"{moderator}{detail}"
    )


def _history_member_header(
    username: str,
    counters: dict[str, int],
    *,
    total: int,
    member: discord.Member | None,
) -> discord.ui.Container:
    """Bande d'identité large sans image-galerie et sans espace vide."""
    panel = discord.ui.Container(accent_colour=discord.Colour(0x737C90))
    heading = (
        "## 🛡️ SentriX · Historique du membre\n"
        f"### {username}\n"
        "-# Dossier de modération réservé au staff · Journal du serveur"
    )
    avatar = getattr(getattr(member, "display_avatar", None), "url", None)
    if avatar:
        panel.add_item(discord.ui.Section(
            discord.ui.TextDisplay(heading),
            accessory=discord.ui.Thumbnail(str(avatar)),
        ))
    else:
        panel.add_item(discord.ui.TextDisplay(heading))
    panel.add_item(discord.ui.Separator())
    panel.add_item(discord.ui.TextDisplay(
        "**📊 Vue d'ensemble des sanctions**\n"
        f"⚠️ **{counters['warn']}** avertissements   ·   "
        f"🔇 **{counters['mute']}** timeouts   ·   "
        f"🚫 **{counters['ban']}** bans   ·   "
        f"🚪 **{counters['kick']}** expulsions\n"
        f"-# {total} événement(s) dans le filtre · Lecture seule"
    ))
    return panel


class MemberHistoryView(discord.ui.LayoutView):
    """Dossier privé paginé ; le sélecteur permet de changer de membre."""

    def __init__(self, *, author_id: int, guild_id: int, target_id: int):
        super().__init__(timeout=300)
        self.author_id = int(author_id)
        self.guild_id = int(guild_id)
        self.target_id = int(target_id)
        self.page = 0
        self.records: list[dict] = []
        self.counts: dict[str, int] = {}
        self.filter = "all"
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
        filtered = FILTERS[self.filter]
        records, total, counts = await fetch_log_history_page(
            self.guild_id,
            self.target_id,
            offset=self.page * PER_PAGE,
            limit=PER_PAGE,
            event_types=filtered,
        )
        self.counts = counts
        page_count = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        self.page = max(0, min(self.page, page_count - 1))
        if total and not records:
            records, total, _ = await fetch_log_history_page(
                self.guild_id,
                self.target_id,
                offset=self.page * PER_PAGE,
                limit=PER_PAGE,
                event_types=filtered,
            )
        self.records = records
        self.clear_items()
        member = guild.get_member(self.target_id)
        username = safe_text(member.display_name if member else str(self.target_id))
        counters = {
            key: sum(counts.get(event, 0) for event in events)
            for key, events in COUNTERS.items()
        }
        # Trois zones avec marges natives : identité, événements et navigation.
        header = _history_member_header(
            username, counters, total=total, member=member,
        )
        self.add_item(header)

        # Tous les événements restent dans un même conteneur pour partager
        # sa largeur, même quand un événement est très court.
        journal = discord.ui.Container(accent_colour=discord.Colour(0x515A6A))
        journal.add_item(discord.ui.TextDisplay(
            "### 📋 Activité du membre\n"
            "-# Historique classé du plus récent au plus ancien"
        ))
        journal.add_item(discord.ui.Separator())
        if not records:
            journal.add_item(discord.ui.TextDisplay(
                "📭 Aucun événement enregistré dans cette catégorie."
            ))
        else:
            for i, record in enumerate(records):
                journal.add_item(discord.ui.TextDisplay(
                    _history_event_block(
                        record, index=self.page * PER_PAGE + i + 1,
                    )
                ))
                if i < len(records) - 1:
                    journal.add_item(discord.ui.Separator())
        self.add_item(journal)

        navigation = discord.ui.Container()
        navigation.add_item(discord.ui.TextDisplay(
            "**🧭 Filtres et navigation**\n"
            f"-# {FILTER_LABELS[self.filter]} · Page {self.page + 1}/{page_count}"
            f" · {total} événement(s) dans cette catégorie"
        ))
        for choices in (("all", "warn", "mute", "ban"), ("kick", "roles", "messages", "members")):
            buttons = []
            for key in choices:
                button = discord.ui.Button(
                    label=FILTER_LABELS[key],
                    style=discord.ButtonStyle.primary if self.filter == key else discord.ButtonStyle.secondary,
                )

                async def selected(interaction: discord.Interaction, *, value: str = key):
                    self.filter = value
                    self.page = 0
                    await self.render(interaction.guild)
                    await interaction.response.edit_message(view=self)

                button.callback = selected
                buttons.append(button)
            navigation.add_item(discord.ui.ActionRow(*buttons))
        selector = discord.ui.UserSelect(
            placeholder="🔎 Choisir un autre membre du serveur…",
            min_values=1,
            max_values=1,
        )
        selector.callback = self._change_target
        self.selector = selector
        navigation.add_item(discord.ui.ActionRow(selector))
        previous = discord.ui.Button(
            label="◀ Précédent", style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
        )
        following = discord.ui.Button(
            label="Suivant ▶", style=discord.ButtonStyle.secondary,
            disabled=self.page >= page_count - 1,
        )
        previous.callback = self._previous
        following.callback = self._following
        navigation.add_item(discord.ui.ActionRow(previous, following))
        self.add_item(navigation)

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
