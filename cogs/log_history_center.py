"""Historique des membres et débannissement sécurisé pour les logs Components V2."""
from __future__ import annotations

import datetime as dt
import logging
import re

import discord
from discord.ext import commands

from utils import access_matrix
from utils.wide_logs import fetch_log_history_page, safe_text
from services import voice_history
from utils import log_service
from utils import sentrix_panels

logger = logging.getLogger("bot.log-center")
NO_MENTIONS = discord.AllowedMentions.none()
PER_PAGE = 2

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
    "voice_join": ("Entrée en vocal", "🎧"),
    "voice_leave": ("Sortie du vocal", "🔊"),
    "voice_move": ("Déplacement vocal", "🔁"),
    "voice_state": ("État micro/casque", "🎙️"),
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
    "voice": ("voice_join", "voice_leave", "voice_move", "voice_state"),
}
FILTER_LABELS = {
    "all": "Tout", "warn": "Warns", "mute": "Mutes", "ban": "Bans",
    "kick": "Kicks", "roles": "Rôles", "messages": "Messages", "members": "Membres",
    "voice": "Vocal",
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
    """Normalise les données historiques sans perdre leur contenu.

    Chaque ligne est présentée en Markdown Discord (labels gras, citations,
    mentions natives). On retire les doublons de salon mais jamais le contenu
    de preuve.
    """
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
        line = re.sub(
            r"^(Salon\s*:\s*<#[0-9]+>)\s*[·•]\s*." + chr(96) +
            r"?#[^\n" + chr(96) + r"]+" + chr(96) + r"?\s*$",
            r"\1", line, flags=re.I,
        )
        match = re.match(
            r"^(Salon|Rôle|Rôles avant le départ|Role|Contenu|Motif|Raison|"
            r"Présence|Durée de la session|Temps dans le salon précédent|"
            r"Supprimé par|Modifié par|Ajouté par|Retiré par|Avant|Après)"
            r"\s*:\s*(.*)$", line, flags=re.I,
        )
        if match:
            label, value = match.groups()
            mapped = {
                "rôles avant le départ": "Rôles avant le départ",
                "présence": "Présence sur le serveur",
                "durée de la session": "Durée vocale",
            }.get(label.casefold(), label)
            if label.casefold() == "contenu":
                line = f"**Contenu**\n> {value or 'Message vide'}"
            else:
                line = f"**{mapped}** · {value}"
        lines.append(line)
        if len("\n".join(lines)) > 950:
            break
    result = "\n".join(lines).strip()
    return result[:897] + "…" if len(result) > 900 else (result or "Aucun détail supplémentaire enregistré.")


def _history_event_block(record: dict, *, index: int) -> str:
    """Un événement lisible, compatible avec les anciens journaux."""
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
        f"**{emoji} {title}** · {relative}\n"
        f"-# Événement {index:02d} · {when}\n\n"
        f"{moderator}{detail}"
    )


def _member_display_name(user: object | None, fallback_id: int) -> str:
    name = (
        getattr(user, "global_name", None)
        or getattr(user, "display_name", None)
        or getattr(user, "name", None)
        or "Utilisateur Discord"
    )
    name = discord.utils.escape_markdown(safe_text(name)[:80])
    return name or f"Utilisateur {fallback_id}"


def _history_member_header(
    username: str,
    counters: dict[str, int],
    *,
    total: int,
    member: discord.abc.User | None,
    target_id: int | None = None,
) -> discord.ui.Container:
    """En-tête avec mention réelle, pseudo, petit ID et avatar si connu.

    Discord peut ne pas résoudre la mention d'un membre ayant quitté le serveur.
    Son pseudo API reste visible, sans remplacer le nom par son seul snowflake.
    """
    panel = discord.ui.Container()
    mention = f"<@{int(target_id)}>" if target_id else ""
    account_name = safe_text(getattr(member, "name", "") or "").strip()
    account_label = (
        chr(96) + "@" + account_name[:32].replace(chr(96), "") + chr(96)
        if account_name else "Compte Discord non résolu"
    )
    id_label = (chr(96) + str(target_id) + chr(96)) if target_id else "ID indisponible"
    header = (
        "## 🛡️ SentriX · Dossier du membre\n"
        f"**{username}**  {mention}\n"
        f"-# Pseudo du compte : {account_label} · ID : {id_label}\n"
        "-# Historique privé · Consultation réservée à la modération"
    )
    avatar = getattr(getattr(member, "display_avatar", None), "url", None)
    if avatar:
        panel.add_item(discord.ui.Section(
            discord.ui.TextDisplay(header),
            accessory=discord.ui.Thumbnail(str(avatar)),
        ))
    else:
        panel.add_item(discord.ui.TextDisplay(header))
    panel.add_item(discord.ui.Separator())
    panel.add_item(discord.ui.TextDisplay(
        "**Modération · Récapitulatif**\n"
        f"{counters['warn']} avert. · {counters['mute']} timeouts · "
        f"{counters['ban']} bans · {counters['kick']} kicks · "
        f"{total} événements"
    ))
    return panel


def _history_brief(record: dict) -> str:
    """Extrait concis, avec citations et labels natifs Discord, jamais un pavé."""
    detail = _history_detail(record.get("description"))
    lines = detail.splitlines()
    if not lines:
        return "-# Aucun détail associé"
    # Priorité au salon, au rôle ou au motif ; ne pas afficher une citation
    # de message supprimé brute comme titre d'un événement.
    chosen = next((line for line in lines if line.startswith("**") and line != "**Contenu**"), None)
    if not chosen:
        chosen = next((line for line in lines if not line.startswith(">")), "")
    if not chosen:
        chosen = lines[0]
    return chosen[:160] + "…" if len(chosen) > 161 else chosen


def _history_event_panel(
    record: dict, *, index: int, expanded: bool, toggle,
) -> discord.ui.Container:
    """Une carte = un événement, avec son propre bouton Détails."""
    log_type = str(record.get("log_type") or "")
    emoji_title = TYPES.get(log_type, (safe_text(record.get("title")) or "Événement", "📋"))
    title, emoji = emoji_title
    # Le gris neutre domine ; les types importants restent identifiables
    # sans multiplier les couleurs criardes.
    accent = (
        0xB5846F if log_type.startswith("message_")
        else 0x647CA3 if log_type.startswith("voice_")
        else 0x798B71 if log_type.startswith("role_") or log_type == "member_roles"
        else 0x7B8199
    )
    panel = discord.ui.Container()
    timestamp = int(record["created_at"])
    panel.add_item(discord.ui.TextDisplay(
        f"**{emoji} {title}**   ·   <t:{timestamp}:R>\n"
        f"-# <t:{timestamp}:f> · #{index:02d}"
    ))
    panel.add_item(discord.ui.Separator())
    if expanded:
        detail = _history_detail(record.get("description"))
        moderator = (
            f"**👮 Responsable** · <@{record['moderator_id']}>\n"
            if record.get("moderator_id") else ""
        )
        panel.add_item(discord.ui.TextDisplay(
            f"{moderator}{detail}"
        ))
    else:
        panel.add_item(discord.ui.TextDisplay(_history_brief(record)))
    button = discord.ui.Button(
        label="Masquer les détails" if expanded else "Voir les détails",
        emoji="🔼" if expanded else "🔎",
        style=discord.ButtonStyle.secondary,
    )
    button.callback = toggle
    panel.add_item(discord.ui.ActionRow(button))
    return panel


class MemberHistoryView(discord.ui.LayoutView):
    """Dossier V4 Components V2 : 4 onglets et détails repliables."""

    SANCTION_EVENTS = (
        "member_warn", "member_timeout", "member_untimeout",
        "member_ban", "member_unban", "member_kick",
    )

    def __init__(self, *, author_id: int, guild_id: int, target_id: int, bot=None):
        super().__init__(timeout=600)
        self.author_id, self.guild_id = int(author_id), int(guild_id)
        self.target_id = int(target_id)
        self.bot = bot
        self.tab = "journal"
        self.page = 0
        self.expanded: int | None = None
        self.records: list[dict] = []
        self.counts: dict[str, int] = {}
        self.filter = "all"
        self.selector: discord.ui.UserSelect | None = None
        self._banner_attached = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Ce dossier appartient au modérateur qui l'a ouvert.", ephemeral=True
            )
            return False
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Autre serveur : accès refusé.", ephemeral=True)
            return False
        denied = await _access(interaction)
        if denied:
            await interaction.response.send_message(denied, ephemeral=True)
            return False
        return True

    async def _resolve_target_user(self, guild):
        """Résout le vrai pseudo Discord, même si le membre a quitté le serveur."""
        cached_member = guild.get_member(self.target_id)
        if cached_member is not None:
            return cached_member
        if getattr(self, "_resolved_user_id", None) == self.target_id:
            return getattr(self, "_resolved_user", None)
        client = self.bot
        resolved = None
        if client is not None:
            getter = getattr(client, "get_user", None)
            if callable(getter):
                resolved = getter(self.target_id)
            if resolved is None:
                fetch = getattr(client, "fetch_user", None)
                if callable(fetch):
                    try:
                        resolved = await fetch(self.target_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        logger.info(
                            "Impossible de résoudre le profil Discord %s : ID toujours affiché",
                            self.target_id,
                        )
        self._resolved_user_id = self.target_id
        self._resolved_user = resolved
        return resolved

    async def render(self, guild: discord.Guild) -> None:
        event_types = (
            FILTERS["voice"] if self.tab == "voice"
            else self.SANCTION_EVENTS if self.tab == "sanctions"
            else FILTERS[self.filter] if self.tab == "journal"
            else None
        )
        records, total, counts = await fetch_log_history_page(
            self.guild_id, self.target_id,
            offset=self.page * PER_PAGE if self.tab != "settings" else 0,
            limit=PER_PAGE, event_types=event_types,
        )
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        self.page = max(0, min(self.page, pages - 1))
        if total and not records and self.tab != "settings":
            records, total, _ = await fetch_log_history_page(
                self.guild_id, self.target_id,
                offset=self.page * PER_PAGE, limit=PER_PAGE,
                event_types=event_types,
            )
        self.records, self.counts = records, counts
        self.clear_items()
        # Pas de simple snowflake à la place d'un pseudo : un membre parti
        # peut être trouvé par get_user / fetch_user grâce à l'API Discord.
        member = await self._resolve_target_user(guild)
        username = _member_display_name(member, self.target_id)
        counters = {
            key: sum(counts.get(event, 0) for event in events)
            for key, events in COUNTERS.items()
        }
        profile = _history_member_header(
            username, counters, total=sum(counts.values()),
            member=member, target_id=self.target_id,
        )
        self._banner_attached = sentrix_panels.poser_bandeau(profile, "moderation")
        self.add_item(profile)

        names = {
            "journal": ("📋 Journal d'activité", "Tous les événements du membre"),
            "voice": ("🎧 Activité vocale", "Entrées, sorties, déplacements et durées"),
            "sanctions": ("⚖️ Sanctions", "Historique des sanctions appliquées"),
            "settings": ("⚙️ Surveillance", "Options du suivi privé des membres"),
        }
        title, subtitle = names[self.tab]
        body = discord.ui.Container()
        body.add_item(discord.ui.TextDisplay(f"**{title}** · {subtitle}"))

        voice_summary = None
        if self.tab in {"voice", "settings"} and self.bot is not None:
            try:
                voice_summary = await voice_history.get_member_summary(
                    self.bot, self.guild_id, self.target_id,
                )
            except Exception:
                logger.exception("Historique vocal inaccessible")

        if self.tab == "voice" and voice_summary:
            session = voice_summary.get("session")
            status = (
                f"🟢 Dans <#{session['channel_id']}>"
                f" depuis <t:{int(session['started_at'])}:R>"
                if session else "⚪ Aucune session active connue"
            )
            body.add_item(discord.ui.Separator())
            body.add_item(discord.ui.TextDisplay(
                f"**📊 {int(voice_summary['completed_sessions'])} session(s)**"
                f" · **{voice_history.duration_label(voice_summary['seconds'])}** cumulées\n"
                f"{status}\n"
                f"-# Suivi {'activé' if voice_summary['enabled'] else 'désactivé'}"
                " · Durées observées uniquement · Jamais d'audio"
            ))
        elif self.tab == "settings":
            body.add_item(discord.ui.Separator())
            if voice_summary:
                route = None
                try:
                    route = await log_service.get_log_setting(
                        self.bot, self.guild_id, "voice"
                    )
                except Exception:
                    logger.exception("Configuration des logs vocaux inaccessible")
                where = (
                    f"<#{route['channel_id']}>"
                    if route and route.get("channel_id") else "Non configuré"
                )
                body.add_item(discord.ui.TextDisplay(
                    "**👁️ Surveillance vocale**\n"
                    f"• Entrées et sorties : **{'Oui' if voice_summary['enabled'] else 'Non'}**\n"
                    f"• Déplacements : **{'Oui' if voice_summary['track_moves'] else 'Non'}**\n"
                    f"• Durées : **{'Oui' if voice_summary['track_duration'] else 'Non'}**\n"
                    f"• Salon de publication : {where}\n\n"
                    "Configuration : " + chr(96) + "/config accueil → Surveillance" + chr(96) + "\n"
                    "-# Aucun enregistrement audio. Les journaux de salon sont indépendants."
                ))
            else:
                body.add_item(discord.ui.TextDisplay(
                    "Statut indisponible. Essayez /config accueil → Surveillance."
                ))

        if self.tab != "settings" and not records:
            body.add_item(discord.ui.Separator())
            body.add_item(discord.ui.TextDisplay(
                "📭 Aucun événement enregistré pour cette catégorie."
            ))
        self.add_item(body)

        if self.tab != "settings":
            for index, event in enumerate(records):
                event_id = int(event["id"])

                async def toggle_detail(interaction: discord.Interaction, *, eid=event_id):
                    self.expanded = None if self.expanded == eid else eid
                    await self.render(interaction.guild)
                    await interaction.response.edit_message(
                        view=self, allowed_mentions=NO_MENTIONS,
                    )

                self.add_item(_history_event_panel(
                    event, index=self.page * PER_PAGE + index + 1,
                    expanded=self.expanded == event_id, toggle=toggle_detail,
                ))

        nav = discord.ui.Container()
        tabs = []
        for tab, label in (
            ("journal", "📋 Journal"), ("voice", "🎧 Vocal"),
            ("sanctions", "⚖️ Sanctions"), ("settings", "⚙️ Réglages"),
        ):
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if tab == self.tab else discord.ButtonStyle.secondary,
            )

            async def go_tab(interaction: discord.Interaction, *, value=tab):
                self.tab, self.page, self.expanded = value, 0, None
                await self.render(interaction.guild)
                await interaction.response.edit_message(
                    view=self, allowed_mentions=NO_MENTIONS,
                )

            button.callback = go_tab
            tabs.append(button)
        nav.add_item(discord.ui.ActionRow(*tabs))

        if self.tab == "journal":
            select = discord.ui.Select(
                placeholder="🔎 Filtrer l'historique",
                options=[
                    discord.SelectOption(
                        label=FILTER_LABELS[key], value=key,
                        default=self.filter == key,
                    )
                    for key in FILTERS
                ],
            )

            async def choose_filter(interaction: discord.Interaction):
                new_filter = interaction.data["values"][0]
                if new_filter not in FILTERS:
                    return await interaction.response.send_message(
                        "Filtre invalide.", ephemeral=True,
                    )
                self.filter, self.page, self.expanded = new_filter, 0, None
                await self.render(interaction.guild)
                await interaction.response.edit_message(
                    view=self, allowed_mentions=NO_MENTIONS,
                )

            select.callback = choose_filter
            nav.add_item(discord.ui.ActionRow(select))

        if self.tab == "settings":
            config_button = discord.ui.Button(
                label="👁️ Ouvrir Surveillance",
                style=discord.ButtonStyle.secondary,
            )

            async def go_config(interaction: discord.Interaction):
                from cogs.voice_history_config import open_voice_history_config
                if self.bot is None:
                    return await interaction.response.send_message(
                        "Configuration non disponible ici.", ephemeral=True,
                    )
                await open_voice_history_config(self.bot, interaction)

            config_button.callback = go_config
            nav.add_item(discord.ui.ActionRow(config_button))

        selector = discord.ui.UserSelect(
            placeholder="👤 Consulter un autre membre…",
            min_values=1, max_values=1,
        )
        selector.callback = self._change_target
        self.selector = selector
        nav.add_item(discord.ui.ActionRow(selector))

        if self.tab != "settings":
            previous = discord.ui.Button(
                label="◀ Précédent", style=discord.ButtonStyle.secondary,
                disabled=self.page == 0,
            )
            following = discord.ui.Button(
                label="Suivant ▶", style=discord.ButtonStyle.secondary,
                disabled=self.page >= pages - 1,
            )
            previous.callback, following.callback = self._previous, self._following
            nav.add_item(discord.ui.TextDisplay(
                f"-# Page {self.page + 1}/{pages} · {total} événement(s)"
            ))
            nav.add_item(discord.ui.ActionRow(previous, following))
        nav.add_item(discord.ui.TextDisplay(
            "-# Dossier privé réservé au staff · Aucun ping de notification"
        ))
        self.add_item(nav)

    async def _change_target(self, interaction: discord.Interaction) -> None:
        if not self.selector or not self.selector.values:
            return
        self.target_id = int(self.selector.values[0].id)
        self.page = 0
        self.expanded = None
        await self.render(interaction.guild)
        await interaction.response.edit_message(view=self, allowed_mentions=NO_MENTIONS)

    async def _previous(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self.expanded = None
        await self.render(interaction.guild)
        await interaction.response.edit_message(view=self, allowed_mentions=NO_MENTIONS)

    async def _following(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self.expanded = None
        await self.render(interaction.guild)
        await interaction.response.edit_message(view=self, allowed_mentions=NO_MENTIONS)


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
    template=r"sentrix:premiumlog:(?P<action>history|unban|transcript):(?P<guild_id>[0-9]{15,22}):(?P<target_id>[0-9]{15,22})",
):
    """Boutons persistants, y compris après un redémarrage Railway."""

    def __init__(self, action: str, guild_id: int, target_id: int):
        self.action = action
        self.guild_id = int(guild_id)
        self.target_id = int(target_id)
        super().__init__(discord.ui.Button(
            label={"history": "Historique", "unban": "Débannir", "transcript": "Transcript"}[action],
            emoji={"history": "📜", "unban": "🛡️", "transcript": "📄"}[action],
            style=discord.ButtonStyle.success if action == "unban" else discord.ButtonStyle.secondary,
            custom_id=f"sentrix:premiumlog:{action}:{guild_id}:{target_id}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match, /):
        return cls(match["action"], int(match["guild_id"]), int(match["target_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            await interaction.response.send_message("Ce log appartient à un autre serveur.", ephemeral=True)
            return
        if self.action == "transcript":
            message = getattr(interaction, "message", None)
            transcript = next((
                item for item in getattr(message, "attachments", ())
                if str(getattr(item, "filename", "")).endswith("-transcript.txt")
            ), None)
            if transcript is None:
                await interaction.response.send_message(
                    "Ce journal ne contient pas de transcript joint. Les nouveaux journaux de messages en proposent un.",
                    ephemeral=True, allowed_mentions=NO_MENTIONS,
                )
                return
            view = discord.ui.View(timeout=120)
            view.add_item(discord.ui.Button(
                label="Télécharger le transcript", emoji="📄", url=transcript.url,
            ))
            await interaction.response.send_message(
                "Texte intégral du message, sans coupure.", view=view,
                ephemeral=True, allowed_mentions=NO_MENTIONS,
            )
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
                    bot=interaction.client,
                )
                await panel.render(interaction.guild)
            except Exception:
                logger.exception("Ouverture du dossier impossible")
                await interaction.response.send_message(
                    "Impossible de charger l'historique pour le moment.", ephemeral=True,
                )
                return
            await interaction.response.send_message(
                view=panel, ephemeral=True, allowed_mentions=NO_MENTIONS,
                files=(sentrix_panels.pieces_jointes_de_famille("moderation")
                       if panel._banner_attached else []),
            )
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
