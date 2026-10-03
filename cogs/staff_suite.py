"""Suite staff premium SentriX.

Objectif produit : les commandes sont des portes d'entrée vers des panneaux
interactifs, pas une collection de syntaxes à mémoriser. Le rendu s'appuie sur
utils.sentrix_panels (Components V2, style arrondi validé) et sur les icônes
d'application SentriX. Aucun salon ni rôle n'est créé automatiquement.

Cette couche complète les briques déjà présentes :
- sanctions / dossiers numérotés : cogs.moderation
- notes privées et preuves historiques : cogs.v17_moderation_security
- diagnostic serveur : commandes existantes
Elle ajoute les dossiers d'enquête, incidents, surveillances, absences,
handover, rappels staff et centres interactifs.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import helpers
from utils import sentrix_emojis as sxemoji
from utils import sentrix_panels as panels


def now() -> int:
    return int(time.time())


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS staff_cases_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'ouvert',
        assigned_to INTEGER,
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_case_items_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        content TEXT NOT NULL,
        author_id INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_incidents_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        member_id INTEGER,
        category TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'moyenne',
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ouvert',
        assigned_to INTEGER,
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_watches_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        events_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'actif',
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        end_at INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_watch_events_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        watch_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        channel_id INTEGER,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_absences_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        start_at INTEGER NOT NULL,
        return_at INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'en_attente',
        created_by INTEGER NOT NULL,
        handled_by INTEGER,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_handovers_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        summary TEXT NOT NULL,
        created_by INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS staff_reminders_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        created_by INTEGER NOT NULL,
        subject_type TEXT,
        subject_id TEXT,
        note TEXT NOT NULL,
        remind_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'actif',
        created_at INTEGER NOT NULL
    )
    """,
)


def _mention(user_id: int | None) -> str:
    return f"<@{int(user_id)}>" if user_id else "—"


def _trim(value: Any, limit: int = 900) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _relative(timestamp: int | None) -> str:
    return f"<t:{int(timestamp)}:R>" if timestamp else "—"


def _status_label(value: str | None) -> str:
    labels = {
        "ouvert": "Ouvert",
        "en_enquete": "En enquête",
        "en_attente": "En attente",
        "resolu": "Résolu",
        "archive": "Archivé",
        "actif": "Actif",
        "pause": "En pause",
        "termine": "Terminé",
        "acceptee": "Acceptée",
        "refusee": "Refusée",
    }
    return labels.get(str(value or ""), str(value or "—").replace("_", " ").title())


class OwnedView(discord.ui.View):
    def __init__(self, suite: "StaffSuite", owner_id: int, *, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.suite = suite
        self.owner_id = int(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Ce panneau appartient à un autre membre du staff.",
            ephemeral=True,
        )
        return False


class NoteModal(discord.ui.Modal, title="Note staff privée"):
    note = discord.ui.TextInput(
        label="Note",
        placeholder="Information interne utile au prochain modérateur…",
        style=discord.TextStyle.paragraph,
        max_length=1800,
    )

    def __init__(self, suite: "StaffSuite", guild_id: int, member_id: int):
        super().__init__()
        self.suite = suite
        self.guild_id = guild_id
        self.member_id = member_id

    async def on_submit(self, interaction: discord.Interaction):
        await self.suite.bot.db.execute(
            "INSERT INTO v17_staff_notes (guild_id,user_id,author_id,note,created_at) VALUES (?,?,?,?,?)",
            (self.guild_id, self.member_id, interaction.user.id, str(self.note.value)[:1800], now()),
        )
        await panels.texte_court(
            interaction.response,
            f"Note privée ajoutée pour <@{self.member_id}>.",
            ephemere=True,
        )


class CaseModal(discord.ui.Modal, title="Nouveau dossier staff"):
    title_input = discord.ui.TextInput(
        label="Titre",
        placeholder="Ex. Suspicion de scam",
        max_length=120,
    )
    reason = discord.ui.TextInput(
        label="Contexte / raison",
        placeholder="Décrivez le problème et ce que le staff doit vérifier.",
        style=discord.TextStyle.paragraph,
        max_length=1800,
    )

    def __init__(self, suite: "StaffSuite", guild_id: int, member_id: int):
        super().__init__()
        self.suite = suite
        self.guild_id = guild_id
        self.member_id = member_id

    async def on_submit(self, interaction: discord.Interaction):
        timestamp = now()
        await self.suite.bot.db.execute(
            "INSERT INTO staff_cases_v1 "
            "(guild_id,member_id,title,reason,status,assigned_to,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?, 'ouvert', ?, ?, ?, ?)",
            (
                self.guild_id,
                self.member_id,
                str(self.title_input.value)[:120],
                str(self.reason.value)[:1800],
                interaction.user.id,
                interaction.user.id,
                timestamp,
                timestamp,
            ),
        )
        row = await self.suite.bot.db.fetchone(
            "SELECT * FROM staff_cases_v1 WHERE guild_id=? AND member_id=? AND created_by=? "
            "ORDER BY id DESC LIMIT 1",
            (self.guild_id, self.member_id, interaction.user.id),
        )
        if row:
            await panels.envoyer(
                interaction.response,
                await self.suite.case_panel(interaction.guild, row, interaction.user.id),
                ephemere=True,
            )
        else:
            await panels.texte_court(interaction.response, "Dossier créé.", ephemere=True)


class EvidenceModal(discord.ui.Modal, title="Ajouter une preuve"):
    def __init__(self, suite: "StaffSuite", case_id: int):
        super().__init__()
        self.suite = suite
        self.case_id = case_id
        self.upload = discord.ui.FileUpload(
            custom_id=f"sentrix:staff:proof:{case_id}",
            required=False,
            min_values=0,
            max_values=1,
        )
        self.note = discord.ui.TextInput(
            required=False,
            max_length=900,
            style=discord.TextStyle.paragraph,
            placeholder="Contexte de la preuve (facultatif)",
        )
        self.add_item(
            discord.ui.Label(
                text="Fichier",
                description="Capture, image, vidéo ou document depuis votre appareil.",
                component=self.upload,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Commentaire",
                description="Expliquez brièvement ce que montre la preuve.",
                component=self.note,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        values = list(getattr(self.upload, "values", None) or [])
        attachment = values[0] if values else None
        note = str(self.note.value or "").strip()
        if attachment is None and not note:
            return await interaction.response.send_message(
                "Ajoutez un fichier ou un commentaire.",
                ephemeral=True,
            )
        parts = []
        if attachment is not None:
            stable = str(attachment.url).split("?", 1)[0]
            parts.append(f"[{attachment.filename}]({stable})")
        if note:
            parts.append(note)
        await self.suite.bot.db.execute(
            "INSERT INTO staff_case_items_v1 (case_id,kind,content,author_id,created_at) VALUES (?,?,?,?,?)",
            (self.case_id, "preuve", "\n".join(parts)[:1800], interaction.user.id, now()),
        )
        await panels.texte_court(
            interaction.response,
            f"Preuve ajoutée au dossier SC-{self.case_id:04d}.",
            ephemere=True,
        )


class WatchStartModal(discord.ui.Modal, title="Démarrer une surveillance"):
    reason = discord.ui.TextInput(
        label="Raison",
        placeholder="Pourquoi ce membre doit-il être surveillé ?",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )
    duration = discord.ui.TextInput(
        label="Durée",
        placeholder="Ex. 2h, 1j, 7j — vide = sans limite",
        required=False,
        max_length=20,
    )

    def __init__(self, view: "WatchSetupView"):
        super().__init__()
        self.setup_view = view

    async def on_submit(self, interaction: discord.Interaction):
        seconds = None
        raw_duration = str(self.duration.value or "").strip()
        if raw_duration:
            seconds = helpers.parse_duration(raw_duration)
            if not seconds:
                return await interaction.response.send_message(
                    "Durée invalide. Exemples : 2h, 1j, 7j.",
                    ephemeral=True,
                )
        events = sorted(self.setup_view.events or {"messages", "deleted", "edited"})
        timestamp = now()
        await self.setup_view.suite.bot.db.execute(
            "UPDATE staff_watches_v1 SET status='termine' "
            "WHERE guild_id=? AND member_id=? AND status IN ('actif','pause')",
            (self.setup_view.guild_id, self.setup_view.member_id),
        )
        await self.setup_view.suite.bot.db.execute(
            "INSERT INTO staff_watches_v1 "
            "(guild_id,member_id,reason,events_json,status,created_by,created_at,end_at) "
            "VALUES (?,?,?,?, 'actif', ?, ?, ?)",
            (
                self.setup_view.guild_id,
                self.setup_view.member_id,
                str(self.reason.value)[:900],
                json.dumps(events),
                interaction.user.id,
                timestamp,
                timestamp + seconds if seconds else None,
            ),
        )
        await self.setup_view.suite.reload_watch_cache()
        row = await self.setup_view.suite.active_watch(
            self.setup_view.guild_id, self.setup_view.member_id
        )
        if row:
            await panels.envoyer(
                interaction.response,
                await self.setup_view.suite.watch_panel(
                    interaction.guild, self.setup_view.member_id, interaction.user.id
                ),
                ephemere=True,
            )
        else:
            await panels.texte_court(interaction.response, "Surveillance démarrée.", ephemere=True)


class WatchEventSelect(discord.ui.Select):
    def __init__(self, owner: "WatchSetupView"):
        self.owner = owner
        options = [
            discord.SelectOption(label="Messages", value="messages"),
            discord.SelectOption(label="Messages supprimés", value="deleted"),
            discord.SelectOption(label="Messages modifiés", value="edited"),
            discord.SelectOption(label="Réactions", value="reactions"),
            discord.SelectOption(label="Salons vocaux", value="voice"),
            discord.SelectOption(label="Présence", value="presence"),
            discord.SelectOption(label="Pseudo / profil", value="profile"),
            discord.SelectOption(label="Rôles", value="roles"),
        ]
        super().__init__(
            placeholder="Événements à suivre",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.events = set(self.values)
        await interaction.response.defer()


class WatchSetupView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, guild_id: int, member_id: int):
        super().__init__(suite, owner_id)
        self.guild_id = guild_id
        self.member_id = member_id
        self.events: set[str] = {"messages", "deleted", "edited"}
        self.add_item(WatchEventSelect(self))

    @discord.ui.button(label="Démarrer", style=discord.ButtonStyle.success, row=1)
    async def start(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(WatchStartModal(self))


class MemberPanelView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, member_id: int):
        super().__init__(suite, owner_id)
        self.member_id = member_id

    @discord.ui.button(label="Historique", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("history"))
    async def history(self, interaction: discord.Interaction, _button: discord.ui.Button):
        member = interaction.guild.get_member(self.member_id)
        if member is None:
            return await interaction.response.send_message("Membre introuvable.", ephemeral=True)
        await panels.envoyer(
            interaction.response,
            await self.suite.history_panel(interaction.guild, member),
            ephemere=True,
        )

    @discord.ui.button(label="Note", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("note"))
    async def note(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            NoteModal(self.suite, interaction.guild.id, self.member_id)
        )

    @discord.ui.button(label="Dossier", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("case"))
    async def case(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            CaseModal(self.suite, interaction.guild.id, self.member_id)
        )

    @discord.ui.button(label="Surveiller", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("watch"))
    async def watch(self, interaction: discord.Interaction, _button: discord.ui.Button):
        active = await self.suite.active_watch(interaction.guild.id, self.member_id)
        if active:
            return await panels.envoyer(
                interaction.response,
                await self.suite.watch_panel(interaction.guild, self.member_id, interaction.user.id),
                ephemere=True,
            )
        view = WatchSetupView(self.suite, interaction.user.id, interaction.guild.id, self.member_id)
        embed = discord.Embed(
            title="Surveillance — configuration",
            description=(
                f"Cible : <@{self.member_id}>\n"
                "Choisissez uniquement les événements utiles, puis démarrez la surveillance."
            ),
            colour=discord.Colour.blurple(),
        )
        await panels.envoyer(
            interaction.response,
            panels.avec_composants(panels.depuis_embed(embed), view),
            ephemere=True,
        )


class CaseActionsView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, case_id: int, *, resolved: bool = False):
        super().__init__(suite, owner_id)
        self.case_id = case_id
        self.resolve.disabled = resolved

    @discord.ui.button(label="Ajouter une preuve", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("evidence"))
    async def evidence(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(EvidenceModal(self.suite, self.case_id))

    @discord.ui.button(label="Résoudre", style=discord.ButtonStyle.success, emoji=sxemoji.partiel("success"))
    async def resolve(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.suite.bot.db.execute(
            "UPDATE staff_cases_v1 SET status='resolu', updated_at=? WHERE id=? AND guild_id=?",
            (now(), self.case_id, interaction.guild.id),
        )
        row = await self.suite.bot.db.fetchone(
            "SELECT * FROM staff_cases_v1 WHERE id=? AND guild_id=?",
            (self.case_id, interaction.guild.id),
        )
        if row:
            await panels.editer(
                interaction.response,
                await self.suite.case_panel(interaction.guild, row, interaction.user.id),
            )


class CaseMemberSelect(discord.ui.UserSelect):
    def __init__(self, owner: "CaseCenterView"):
        self.owner = owner
        super().__init__(
            placeholder="Choisir le membre du nouveau dossier",
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.member_id = self.values[0].id
        await interaction.response.defer()


class CaseCenterView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, guild_id: int):
        super().__init__(suite, owner_id)
        self.guild_id = guild_id
        self.member_id: int | None = None
        self.add_item(CaseMemberSelect(self))

    @discord.ui.button(label="Nouveau dossier", style=discord.ButtonStyle.primary, row=1, emoji=sxemoji.partiel("case"))
    async def create_case(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.member_id:
            return await interaction.response.send_message(
                "Choisissez d’abord le membre concerné.",
                ephemeral=True,
            )
        await interaction.response.send_modal(
            CaseModal(self.suite, self.guild_id, self.member_id)
        )


class IncidentModal(discord.ui.Modal, title="Nouvel incident"):
    category = discord.ui.TextInput(
        label="Catégorie",
        placeholder="raid, scam, conflit, problème staff…",
        max_length=60,
    )
    severity = discord.ui.TextInput(
        label="Gravité",
        placeholder="faible / moyenne / élevée / critique",
        default="moyenne",
        max_length=20,
    )
    member_id = discord.ui.TextInput(
        label="ID du membre concerné (facultatif)",
        required=False,
        max_length=22,
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=1800,
    )

    def __init__(self, suite: "StaffSuite", guild_id: int):
        super().__init__()
        self.suite = suite
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        target = None
        raw = str(self.member_id.value or "").strip()
        if raw:
            try:
                target = int(raw)
            except ValueError:
                return await interaction.response.send_message(
                    "L’identifiant du membre doit être numérique.",
                    ephemeral=True,
                )
        severity = str(self.severity.value or "moyenne").strip().casefold()
        if severity not in {"faible", "moyenne", "élevée", "elevee", "critique"}:
            return await interaction.response.send_message(
                "Gravité attendue : faible, moyenne, élevée ou critique.",
                ephemeral=True,
            )
        severity = "élevée" if severity == "elevee" else severity
        timestamp = now()
        await self.suite.bot.db.execute(
            "INSERT INTO staff_incidents_v1 "
            "(guild_id,member_id,category,severity,description,status,assigned_to,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'ouvert',?,?,?,?)",
            (
                self.guild_id,
                target,
                str(self.category.value)[:60],
                severity,
                str(self.description.value)[:1800],
                interaction.user.id,
                interaction.user.id,
                timestamp,
                timestamp,
            ),
        )
        await panels.texte_court(interaction.response, "Incident enregistré.", ephemere=True)


class IncidentCenterView(OwnedView):
    @discord.ui.button(label="Nouvel incident", style=discord.ButtonStyle.primary, emoji=sxemoji.partiel("alert"))
    async def create(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(IncidentModal(self.suite, interaction.guild.id))


class AbsenceModal(discord.ui.Modal, title="Déclarer une absence"):
    duration = discord.ui.TextInput(
        label="Durée",
        placeholder="Ex. 1j, 3j, 1w",
        max_length=20,
    )
    reason = discord.ui.TextInput(
        label="Raison",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )

    def __init__(self, suite: "StaffSuite", guild_id: int, member_id: int):
        super().__init__()
        self.suite = suite
        self.guild_id = guild_id
        self.member_id = member_id

    async def on_submit(self, interaction: discord.Interaction):
        seconds = helpers.parse_duration(str(self.duration.value))
        if not seconds:
            return await interaction.response.send_message(
                "Durée invalide. Exemples : 1j, 3j, 1w.",
                ephemeral=True,
            )
        timestamp = now()
        await self.suite.bot.db.execute(
            "INSERT INTO staff_absences_v1 "
            "(guild_id,member_id,start_at,return_at,reason,status,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'en_attente',?,?,?)",
            (
                self.guild_id,
                self.member_id,
                timestamp,
                timestamp + seconds,
                str(self.reason.value)[:900],
                interaction.user.id,
                timestamp,
                timestamp,
            ),
        )
        await panels.texte_court(
            interaction.response,
            "Demande d’absence enregistrée et mise en attente.",
            ephemere=True,
        )


class AbsenceSelect(discord.ui.Select):
    def __init__(self, owner: "AbsenceCenterView", rows):
        self.owner = owner
        options = []
        for row in rows[:25]:
            options.append(
                discord.SelectOption(
                    label=f"#{row['id']} · {row['member_id']}",
                    value=str(row["id"]),
                    description=f"Retour {_relative(row['return_at'])}"[:100],
                )
            )
        super().__init__(
            placeholder="Demande à traiter" if options else "Aucune demande en attente",
            min_values=1 if options else 0,
            max_values=1 if options else 0,
            options=options or [discord.SelectOption(label="Aucune demande", value="0")],
            disabled=not bool(options),
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.absence_id = int(self.values[0])
        await interaction.response.defer()


class AbsenceCenterView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, pending_rows):
        super().__init__(suite, owner_id)
        self.absence_id: int | None = None
        self.add_item(AbsenceSelect(self, pending_rows))

    @discord.ui.button(label="Déclarer mon absence", style=discord.ButtonStyle.primary, row=1, emoji=sxemoji.partiel("absence"))
    async def declare(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            AbsenceModal(self.suite, interaction.guild.id, interaction.user.id)
        )

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, row=1, emoji=sxemoji.partiel("success"))
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._review(interaction, "acceptee")

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, row=1, emoji=sxemoji.partiel("error"))
    async def refuse(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._review(interaction, "refusee")

    async def _review(self, interaction: discord.Interaction, status: str):
        if not self.absence_id:
            return await interaction.response.send_message(
                "Choisissez une demande à traiter.",
                ephemeral=True,
            )
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and (perms.manage_guild or perms.administrator)):
            return await interaction.response.send_message(
                "Il faut la permission Gérer le serveur pour valider les absences.",
                ephemeral=True,
            )
        await self.suite.bot.db.execute(
            "UPDATE staff_absences_v1 SET status=?, handled_by=?, updated_at=? "
            "WHERE id=? AND guild_id=? AND status='en_attente'",
            (status, interaction.user.id, now(), self.absence_id, interaction.guild.id),
        )
        await panels.texte_court(
            interaction.response,
            "Absence acceptée." if status == "acceptee" else "Absence refusée.",
            ephemere=True,
        )


class WatchControlView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, watch_id: int, member_id: int, status: str):
        super().__init__(suite, owner_id)
        self.watch_id = watch_id
        self.member_id = member_id
        self.pause.label = "Reprendre" if status == "pause" else "Pause"

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("pause"))
    async def pause(self, interaction: discord.Interaction, _button: discord.ui.Button):
        row = await self.suite.bot.db.fetchone(
            "SELECT status FROM staff_watches_v1 WHERE id=? AND guild_id=?",
            (self.watch_id, interaction.guild.id),
        )
        new_status = "actif" if row and row["status"] == "pause" else "pause"
        await self.suite.bot.db.execute(
            "UPDATE staff_watches_v1 SET status=? WHERE id=? AND guild_id=?",
            (new_status, self.watch_id, interaction.guild.id),
        )
        await self.suite.reload_watch_cache()
        await panels.editer(
            interaction.response,
            await self.suite.watch_panel(interaction.guild, self.member_id, interaction.user.id),
        )

    @discord.ui.button(label="Terminer", style=discord.ButtonStyle.danger, emoji=sxemoji.partiel("stop"))
    async def stop(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.suite.bot.db.execute(
            "UPDATE staff_watches_v1 SET status='termine' WHERE id=? AND guild_id=?",
            (self.watch_id, interaction.guild.id),
        )
        await self.suite.reload_watch_cache()
        await panels.texte_court(interaction.response, "Surveillance terminée.", ephemere=True)


class EmergencyConfirmView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, channel_id: int, action: str):
        super().__init__(suite, owner_id, timeout=60)
        self.channel_id = channel_id
        self.action = action

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Salon introuvable.", ephemeral=True)
        perms = interaction.user.guild_permissions
        if not (perms.manage_channels or perms.administrator):
            return await interaction.response.send_message(
                "Permission manquante : Gérer les salons.",
                ephemeral=True,
            )
        me = interaction.guild.me
        if me is None or not channel.permissions_for(me).manage_channels:
            return await interaction.response.send_message(
                "SentriX n’a pas la permission Gérer les salons ici.",
                ephemeral=True,
            )
        everyone = interaction.guild.default_role
        if self.action == "lock":
            await channel.set_permissions(
                everyone,
                send_messages=False,
                reason=f"Urgence SentriX confirmée par {interaction.user}",
            )
            message = f"{channel.mention} est verrouillé."
        elif self.action == "unlock":
            overwrite = channel.overwrites_for(everyone)
            overwrite.send_messages = None
            await channel.set_permissions(
                everyone,
                overwrite=overwrite,
                reason=f"Fin urgence SentriX par {interaction.user}",
            )
            message = f"{channel.mention} est déverrouillé."
        else:
            await channel.edit(
                slowmode_delay=10,
                reason=f"Urgence SentriX confirmée par {interaction.user}",
            )
            message = f"Mode lent 10 s activé dans {channel.mention}."
        await panels.texte_court(interaction.response, message, ephemere=True)


class EmergencyView(OwnedView):
    def __init__(self, suite: "StaffSuite", owner_id: int, channel_id: int):
        super().__init__(suite, owner_id)
        self.channel_id = channel_id

    async def _ask(self, interaction: discord.Interaction, action: str, label: str):
        embed = discord.Embed(
            title="Confirmation d’urgence",
            description=(
                f"Action : **{label}**\n"
                "Cette action modifie immédiatement le salon actuel. Confirmez une seconde fois."
            ),
            colour=discord.Colour.orange(),
        )
        await panels.envoyer(
            interaction.response,
            panels.avec_composants(
                panels.depuis_embed(embed),
                EmergencyConfirmView(self.suite, interaction.user.id, self.channel_id, action),
            ),
            ephemere=True,
        )

    @discord.ui.button(label="Verrouiller ce salon", style=discord.ButtonStyle.danger, emoji=sxemoji.partiel("lock"))
    async def lock(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._ask(interaction, "lock", "Verrouiller ce salon")

    @discord.ui.button(label="Mode lent 10 s", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("clock"))
    async def slow(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._ask(interaction, "slow", "Activer le mode lent 10 s")

    @discord.ui.button(label="Déverrouiller", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("unlock"))
    async def unlock(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._ask(interaction, "unlock", "Déverrouiller ce salon")


class StaffCenterView(OwnedView):
    @discord.ui.button(label="Dossiers", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("case"))
    async def cases(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await panels.envoyer(
            interaction.response,
            await self.suite.cases_center_panel(interaction.guild, interaction.user.id),
            ephemere=True,
        )

    @discord.ui.button(label="Incidents", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("alert"))
    async def incidents(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await panels.envoyer(
            interaction.response,
            await self.suite.incident_center_panel(interaction.guild, interaction.user.id),
            ephemere=True,
        )

    @discord.ui.button(label="Surveillances", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("watch"))
    async def watches(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await panels.envoyer(
            interaction.response,
            await self.suite.watches_center_panel(interaction.guild),
            ephemere=True,
        )

    @discord.ui.button(label="Absences", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("absence"))
    async def absences(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self.suite.send_absence_center(interaction.response, interaction.guild, interaction.user.id)

    @discord.ui.button(label="Rapport", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("chart"))
    async def report(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await panels.envoyer(
            interaction.response,
            await self.suite.report_panel(interaction.guild, days=7),
            ephemere=True,
        )

    @discord.ui.button(label="Handover", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("history"))
    async def handover(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await panels.envoyer(
            interaction.response,
            await self.suite.handover_panel(interaction.guild, interaction.user),
            ephemere=True,
        )

    @discord.ui.button(label="Diagnostic", style=discord.ButtonStyle.secondary, emoji=sxemoji.partiel("tools"))
    async def diagnostic(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await panels.envoyer(
            interaction.response,
            await self.suite.audit_panel(interaction.guild),
            ephemere=True,
        )


class StaffSuite(commands.Cog, name="StaffSuite"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._watch_cache: dict[tuple[int, int], list[dict[str, Any]]] = {}

    async def cog_load(self):
        for statement in SCHEMA:
            await self.bot.db.execute(statement)
        await self.reload_watch_cache()
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    async def reload_watch_cache(self):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM staff_watches_v1 WHERE status IN ('actif','pause')"
        )
        cache: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for row in rows:
            data = dict(row)
            try:
                data["events"] = set(json.loads(row["events_json"] or "[]"))
            except Exception:
                data["events"] = {"messages", "deleted", "edited"}
            cache.setdefault((int(row["guild_id"]), int(row["member_id"])), []).append(data)
        self._watch_cache = cache

    async def active_watch(self, guild_id: int, member_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM staff_watches_v1 WHERE guild_id=? AND member_id=? "
            "AND status IN ('actif','pause') ORDER BY id DESC LIMIT 1",
            (guild_id, member_id),
        )

    async def _watch_event(
        self,
        guild_id: int,
        member_id: int,
        event_type: str,
        summary: str,
        *,
        channel_id: int | None = None,
    ):
        watches = self._watch_cache.get((guild_id, member_id), ())
        if not watches:
            return
        timestamp = now()
        changed = False
        for watch in list(watches):
            if watch.get("status") != "actif":
                continue
            end_at = watch.get("end_at")
            if end_at and int(end_at) <= timestamp:
                await self.bot.db.execute(
                    "UPDATE staff_watches_v1 SET status='termine' WHERE id=?",
                    (watch["id"],),
                )
                changed = True
                continue
            if event_type not in watch.get("events", set()):
                continue
            await self.bot.db.execute(
                "INSERT INTO staff_watch_events_v1 "
                "(watch_id,event_type,summary,channel_id,created_at) VALUES (?,?,?,?,?)",
                (watch["id"], event_type, _trim(summary, 900), channel_id, timestamp),
            )
        if changed:
            await self.reload_watch_cache()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        await self._watch_event(
            message.guild.id,
            message.author.id,
            "messages",
            f"{message.channel.mention} · {_trim(message.content or '[pièce jointe]', 500)}",
            channel_id=message.channel.id,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        await self._watch_event(
            message.guild.id,
            message.author.id,
            "deleted",
            f"Message supprimé dans {message.channel.mention} · {_trim(message.content or '[contenu indisponible]', 500)}",
            channel_id=message.channel.id,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is None or after.author.bot or before.content == after.content:
            return
        await self._watch_event(
            after.guild.id,
            after.author.id,
            "edited",
            f"{after.channel.mention} · {_trim(before.content, 260)} → {_trim(after.content, 260)}",
            channel_id=after.channel.id,
        )

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user):
        message = reaction.message
        if message.guild is None or getattr(user, "bot", False):
            return
        await self._watch_event(
            message.guild.id,
            user.id,
            "reactions",
            f"Réaction {reaction.emoji} sur un message dans {message.channel.mention}",
            channel_id=message.channel.id,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            old = {r.id for r in before.roles}
            new = {r.id for r in after.roles}
            added = [r.mention for r in after.roles if r.id in new - old]
            removed = [r.mention for r in before.roles if r.id in old - new]
            detail = []
            if added:
                detail.append("Ajout : " + ", ".join(added))
            if removed:
                detail.append("Retrait : " + ", ".join(removed))
            await self._watch_event(after.guild.id, after.id, "roles", " · ".join(detail))
        if before.display_name != after.display_name or before.display_avatar.url != after.display_avatar.url:
            await self._watch_event(
                after.guild.id,
                after.id,
                "profile",
                f"Profil modifié · {before.display_name} → {after.display_name}",
            )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if before.channel == after.channel:
            return
        await self._watch_event(
            member.guild.id,
            member.id,
            "voice",
            f"Vocal : {getattr(before.channel, 'mention', 'aucun')} → {getattr(after.channel, 'mention', 'aucun')}",
            channel_id=getattr(after.channel or before.channel, "id", None),
        )

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if before.status == after.status:
            return
        await self._watch_event(
            after.guild.id,
            after.id,
            "presence",
            f"Présence : {before.status} → {after.status}",
        )

    async def member_panel(self, guild: discord.Guild, member: discord.Member, owner_id: int):
        sanctions = await self._safe_count(
            "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        tickets = await self._safe_count(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        notes = await self._safe_count(
            "SELECT COUNT(*) AS n FROM v17_staff_notes WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        cases = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_cases_v1 WHERE guild_id=? AND member_id=?",
            (guild.id, member.id),
        )
        watch = await self.active_watch(guild.id, member.id)
        incidents = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_incidents_v1 WHERE guild_id=? AND member_id=?",
            (guild.id, member.id),
        )
        created = int(member.created_at.timestamp())
        joined = int(member.joined_at.timestamp()) if member.joined_at else None
        sections = [
            panels.Section(
                "Identité",
                [
                    panels.Ligne("Membre", f"{member.mention} · `{member.id}`"),
                    panels.Ligne("Compte créé", f"<t:{created}:D> · <t:{created}:R>"),
                    panels.Ligne("Arrivée", f"<t:{joined}:D> · <t:{joined}:R>" if joined else "Inconnue"),
                    panels.Ligne("Rôle principal", member.top_role.mention),
                ],
            ),
            panels.Section(
                "Historique SentriX",
                [
                    panels.Ligne("Sanctions", str(sanctions)),
                    panels.Ligne("Tickets", str(tickets)),
                    panels.Ligne("Notes staff", str(notes)),
                    panels.Ligne("Dossiers", str(cases)),
                    panels.Ligne("Incidents", str(incidents)),
                    panels.Ligne("Surveillance", _status_label(watch["status"]) if watch else "Aucune"),
                ],
                aligne=True,
            ),
        ]
        timeout = getattr(member, "timed_out_until", None)
        if timeout and timeout > discord.utils.utcnow():
            sections.append(
                panels.Section(
                    "État actuel",
                    [panels.Ligne("Timeout", f"Jusqu’à <t:{int(timeout.timestamp())}:R>")],
                )
            )
        panel = panels.Panneau(
            titre="Membre — centre staff",
            sous_titre="Toutes les informations utiles avant d’agir.",
            kind="moderation",
            vignette=member.display_avatar.url,
            sections=sections,
            pied=f"SentriX • Staff · consulté par {_mention(owner_id)}",
        )
        return panels.avec_composants(panel, MemberPanelView(self, owner_id, member.id))

    async def history_panel(self, guild: discord.Guild, member: discord.Member):
        timeline: list[tuple[int, str]] = []
        try:
            sanctions = await self.bot.db.get_sanction_history(guild.id, member.id, limit=10)
            for row in sanctions:
                timeline.append(
                    (int(row["created_at"]), f"Sanction **{row['action']}** · dossier #{row['case_number']}")
                )
        except Exception:
            sanctions = []
        for table, query, formatter in (
            (
                "notes",
                "SELECT * FROM v17_staff_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 8",
                lambda r: f"Note staff #{r['id']} · par {_mention(r['author_id'])}",
            ),
            (
                "cases",
                "SELECT * FROM staff_cases_v1 WHERE guild_id=? AND member_id=? ORDER BY created_at DESC LIMIT 8",
                lambda r: f"Dossier SC-{r['id']:04d} · {_status_label(r['status'])}",
            ),
            (
                "incidents",
                "SELECT * FROM staff_incidents_v1 WHERE guild_id=? AND member_id=? ORDER BY created_at DESC LIMIT 8",
                lambda r: f"Incident #{r['id']} · {r['category']} · {_status_label(r['status'])}",
            ),
            (
                "watches",
                "SELECT * FROM staff_watches_v1 WHERE guild_id=? AND member_id=? ORDER BY created_at DESC LIMIT 8",
                lambda r: f"Surveillance #{r['id']} · {_status_label(r['status'])}",
            ),
        ):
            try:
                rows = await self.bot.db.fetchall(query, (guild.id, member.id))
            except Exception:
                rows = []
            for row in rows:
                timeline.append((int(row["created_at"]), formatter(row)))
        timeline.sort(key=lambda item: item[0], reverse=True)
        text = "\n".join(f"<t:{ts}:R> · {label}" for ts, label in timeline[:20]) or "Aucun événement enregistré."
        return panels.Panneau(
            titre=f"Historique — {member.display_name}",
            sous_titre=f"{member.mention} · `{member.id}`",
            kind="moderation",
            vignette=member.display_avatar.url,
            sections=[panels.Section("Timeline", texte=text)],
            pied="SentriX • Historique staff",
        )

    async def case_panel(self, guild: discord.Guild, row, owner_id: int):
        items = await self.bot.db.fetchall(
            "SELECT * FROM staff_case_items_v1 WHERE case_id=? ORDER BY created_at DESC LIMIT 8",
            (row["id"],),
        )
        proof_lines = [
            f"<t:{item['created_at']}:R> · {_trim(item['content'], 400)}"
            for item in items
            if item["kind"] == "preuve"
        ]
        panel = panels.Panneau(
            titre=f"Dossier SC-{row['id']:04d} — {row['title']}",
            sous_titre=f"{_mention(row['member_id'])} · {_status_label(row['status'])}",
            kind="moderation",
            sections=[
                panels.Section(
                    "Dossier",
                    [
                        panels.Ligne("Membre", _mention(row["member_id"])),
                        panels.Ligne("Responsable", _mention(row["assigned_to"])),
                        panels.Ligne("Créé par", _mention(row["created_by"])),
                        panels.Ligne("Création", _relative(row["created_at"])),
                        panels.Ligne("Statut", _status_label(row["status"])),
                    ],
                ),
                panels.Section("Contexte", texte=row["reason"] or "Aucun contexte."),
                panels.Section("Preuves", texte="\n".join(proof_lines) if proof_lines else "Aucune preuve enregistrée."),
            ],
            pied="SentriX • Dossier staff",
        )
        return panels.avec_composants(
            panel,
            CaseActionsView(
                self,
                owner_id,
                int(row["id"]),
                resolved=str(row["status"]) in {"resolu", "archive"},
            ),
        )

    async def watch_panel(self, guild: discord.Guild, member_id: int, owner_id: int):
        row = await self.active_watch(guild.id, member_id)
        if not row:
            member = guild.get_member(member_id)
            return panels.Panneau(
                titre="Surveillance",
                sous_titre=f"Aucune surveillance active pour {member.mention if member else _mention(member_id)}.",
                kind="moderation",
                sections=(),
                pied="SentriX • Surveillance",
            )
        events = await self.bot.db.fetchall(
            "SELECT * FROM staff_watch_events_v1 WHERE watch_id=? ORDER BY created_at DESC LIMIT 12",
            (row["id"],),
        )
        lines = [
            f"<t:{event['created_at']}:R> · **{event['event_type']}** · {_trim(event['summary'], 460)}"
            for event in events
        ]
        try:
            types = json.loads(row["events_json"] or "[]")
        except Exception:
            types = []
        panel = panels.Panneau(
            titre=f"Surveillance #{row['id']}",
            sous_titre=f"{_mention(member_id)} · {_status_label(row['status'])}",
            kind="moderation",
            sections=[
                panels.Section(
                    "Configuration",
                    [
                        panels.Ligne("Raison", row["reason"]),
                        panels.Ligne("Démarrée par", _mention(row["created_by"])),
                        panels.Ligne("Début", _relative(row["created_at"])),
                        panels.Ligne("Fin", _relative(row["end_at"]) if row["end_at"] else "Sans limite"),
                        panels.Ligne("Événements", ", ".join(types) or "—"),
                    ],
                ),
                panels.Section("Activité récente", texte="\n".join(lines) if lines else "Aucun événement enregistré pour l’instant."),
            ],
            pied="SentriX • Surveillance",
        )
        return panels.avec_composants(
            panel,
            WatchControlView(self, owner_id, int(row["id"]), member_id, str(row["status"])),
        )

    async def watches_center_panel(self, guild: discord.Guild):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM staff_watches_v1 WHERE guild_id=? AND status IN ('actif','pause') ORDER BY created_at DESC LIMIT 20",
            (guild.id,),
        )
        text = "\n".join(
            f"**#{r['id']}** · {_mention(r['member_id'])} · {_status_label(r['status'])} · {_relative(r['created_at'])}"
            for r in rows
        ) or "Aucune surveillance active."
        return panels.Panneau(
            titre="Surveillances actives",
            kind="moderation",
            sections=[panels.Section("En cours", texte=text)],
            pied="SentriX • Staff",
        )

    async def cases_center_panel(self, guild: discord.Guild, owner_id: int):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM staff_cases_v1 WHERE guild_id=? ORDER BY "
            "CASE status WHEN 'ouvert' THEN 0 WHEN 'en_enquete' THEN 1 WHEN 'en_attente' THEN 2 ELSE 3 END, "
            "updated_at DESC LIMIT 20",
            (guild.id,),
        )
        text = "\n".join(
            f"**SC-{r['id']:04d}** · {_mention(r['member_id'])} · **{_status_label(r['status'])}** · {_trim(r['title'], 90)}"
            for r in rows
        ) or "Aucun dossier staff."
        panel = panels.Panneau(
            titre="Dossiers staff",
            sous_titre="Sélectionnez un membre puis créez un dossier, ou consultez un dossier existant avec +case <numéro>.",
            kind="moderation",
            sections=[panels.Section("Dossiers récents", texte=text)],
            pied="SentriX • Dossiers",
        )
        return panels.avec_composants(panel, CaseCenterView(self, owner_id, guild.id))

    async def incident_center_panel(self, guild: discord.Guild, owner_id: int):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM staff_incidents_v1 WHERE guild_id=? ORDER BY updated_at DESC LIMIT 20",
            (guild.id,),
        )
        text = "\n".join(
            f"**#{r['id']}** · {r['severity']} · {r['category']} · **{_status_label(r['status'])}**"
            + (f" · {_mention(r['member_id'])}" if r["member_id"] else "")
            for r in rows
        ) or "Aucun incident enregistré."
        panel = panels.Panneau(
            titre="Incidents",
            sous_titre="Raid, scam, conflit, problème staff ou autre événement à tracer.",
            kind="moderation",
            sections=[panels.Section("Historique récent", texte=text)],
            pied="SentriX • Incidents",
        )
        return panels.avec_composants(panel, IncidentCenterView(self, owner_id))

    async def send_absence_center(self, destination, guild: discord.Guild, owner_id: int):
        pending = await self.bot.db.fetchall(
            "SELECT * FROM staff_absences_v1 WHERE guild_id=? AND status='en_attente' ORDER BY created_at ASC LIMIT 25",
            (guild.id,),
        )
        active = await self.bot.db.fetchall(
            "SELECT * FROM staff_absences_v1 WHERE guild_id=? AND status='acceptee' AND return_at>? ORDER BY return_at ASC LIMIT 20",
            (guild.id, now()),
        )
        sections = [
            panels.Section(
                "En attente",
                texte="\n".join(
                    f"**#{r['id']}** · {_mention(r['member_id'])} · retour {_relative(r['return_at'])} · {_trim(r['reason'], 160)}"
                    for r in pending
                ) or "Aucune demande.",
            ),
            panels.Section(
                "Absences actives",
                texte="\n".join(
                    f"**#{r['id']}** · {_mention(r['member_id'])} · retour {_relative(r['return_at'])}"
                    for r in active
                ) or "Aucune absence active.",
            ),
        ]
        panel = panels.Panneau(
            titre="Absences staff",
            kind="moderation",
            sections=sections,
            pied="SentriX • Staff",
        )
        await panels.envoyer(
            destination,
            panels.avec_composants(panel, AbsenceCenterView(self, owner_id, pending)),
            ephemere=isinstance(destination, discord.InteractionResponse),
        )

    async def staff_center_panel(self, guild: discord.Guild, owner_id: int):
        open_cases = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_cases_v1 WHERE guild_id=? AND status NOT IN ('resolu','archive')",
            (guild.id,),
        )
        incidents = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_incidents_v1 WHERE guild_id=? AND status='ouvert'",
            (guild.id,),
        )
        watches = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_watches_v1 WHERE guild_id=? AND status IN ('actif','pause')",
            (guild.id,),
        )
        absences = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_absences_v1 WHERE guild_id=? AND status='en_attente'",
            (guild.id,),
        )
        panel = panels.Panneau(
            titre="Centre Staff",
            sous_titre="Un point d’entrée unique pour les dossiers, surveillances, absences et transmissions.",
            kind="moderation",
            sections=[
                panels.Section(
                    "À traiter",
                    [
                        panels.Ligne("Dossiers ouverts", str(open_cases)),
                        panels.Ligne("Incidents ouverts", str(incidents)),
                        panels.Ligne("Surveillances", str(watches)),
                        panels.Ligne("Absences en attente", str(absences)),
                    ],
                    aligne=True,
                )
            ],
            pied="SentriX • Staff",
        )
        return panels.avec_composants(panel, StaffCenterView(self, owner_id))

    async def handover_panel(self, guild: discord.Guild, author):
        cases = await self.bot.db.fetchall(
            "SELECT * FROM staff_cases_v1 WHERE guild_id=? AND status NOT IN ('resolu','archive') ORDER BY updated_at DESC LIMIT 10",
            (guild.id,),
        )
        incidents = await self.bot.db.fetchall(
            "SELECT * FROM staff_incidents_v1 WHERE guild_id=? AND status='ouvert' ORDER BY updated_at DESC LIMIT 10",
            (guild.id,),
        )
        watches = await self.bot.db.fetchall(
            "SELECT * FROM staff_watches_v1 WHERE guild_id=? AND status IN ('actif','pause') ORDER BY created_at DESC LIMIT 10",
            (guild.id,),
        )
        absences = await self.bot.db.fetchall(
            "SELECT * FROM staff_absences_v1 WHERE guild_id=? AND status='acceptee' AND return_at>? ORDER BY return_at ASC LIMIT 10",
            (guild.id, now()),
        )
        summary_lines = [
            f"Dossiers : {len(cases)}",
            f"Incidents : {len(incidents)}",
            f"Surveillances : {len(watches)}",
            f"Absences actives : {len(absences)}",
        ]
        await self.bot.db.execute(
            "INSERT INTO staff_handovers_v1 (guild_id,summary,created_by,created_at) VALUES (?,?,?,?)",
            (guild.id, " · ".join(summary_lines), author.id, now()),
        )
        sections = [
            panels.Section(
                "Dossiers ouverts",
                texte="\n".join(
                    f"SC-{r['id']:04d} · {_mention(r['member_id'])} · {_trim(r['title'], 100)}"
                    for r in cases
                ) or "Aucun.",
            ),
            panels.Section(
                "Incidents",
                texte="\n".join(
                    f"#{r['id']} · {r['severity']} · {r['category']}"
                    for r in incidents
                ) or "Aucun.",
            ),
            panels.Section(
                "Surveillances",
                texte="\n".join(
                    f"#{r['id']} · {_mention(r['member_id'])} · {_status_label(r['status'])}"
                    for r in watches
                ) or "Aucune.",
            ),
            panels.Section(
                "Absences",
                texte="\n".join(
                    f"{_mention(r['member_id'])} · retour {_relative(r['return_at'])}"
                    for r in absences
                ) or "Aucune.",
            ),
        ]
        return panels.Panneau(
            titre="Handover staff",
            sous_titre=f"Transmission générée par {author.mention}.",
            kind="moderation",
            sections=sections,
            pied="SentriX • Transmission",
        )

    async def report_panel(self, guild: discord.Guild, *, days: int = 7):
        days = max(1, min(30, int(days)))
        since = now() - days * 86400
        sanctions = await self._safe_count(
            "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND created_at>=?",
            (guild.id, since),
        )
        tickets = await self._safe_count(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND created_at>=?",
            (guild.id, since),
        )
        cases = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_cases_v1 WHERE guild_id=? AND created_at>=?",
            (guild.id, since),
        )
        incidents = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_incidents_v1 WHERE guild_id=? AND created_at>=?",
            (guild.id, since),
        )
        watches = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_watches_v1 WHERE guild_id=? AND created_at>=?",
            (guild.id, since),
        )
        return panels.Panneau(
            titre=f"Rapport staff — {days} jour(s)",
            kind="moderation",
            sections=[
                panels.Section(
                    "Activité",
                    [
                        panels.Ligne("Sanctions", str(sanctions)),
                        panels.Ligne("Tickets", str(tickets)),
                        panels.Ligne("Dossiers créés", str(cases)),
                        panels.Ligne("Incidents", str(incidents)),
                        panels.Ligne("Surveillances", str(watches)),
                    ],
                    aligne=True,
                )
            ],
            pied=f"SentriX • Depuis <t:{since}:D>",
        )

    async def audit_panel(self, guild: discord.Guild):
        me = guild.me
        if me is None:
            return panels.Panneau(
                titre="Audit SentriX",
                sous_titre="Impossible de résoudre le membre du bot sur ce serveur.",
                kind="warning",
            )
        perms = me.guild_permissions
        checks = [
            ("Voir les salons", perms.view_channel),
            ("Envoyer des messages", perms.send_messages),
            ("Gérer les messages", perms.manage_messages),
            ("Modérer les membres", perms.moderate_members),
            ("Expulser des membres", perms.kick_members),
            ("Bannir des membres", perms.ban_members),
            ("Gérer les salons", perms.manage_channels),
            ("Gérer les rôles", perms.manage_roles),
            ("Voir le journal d’audit", perms.view_audit_log),
        ]
        issues = [label for label, ok in checks if not ok]
        modules = [
            panels.Ligne(label, "OK" if ok else "Manquante")
            for label, ok in checks
        ]
        open_cases = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_cases_v1 WHERE guild_id=? AND status NOT IN ('resolu','archive')",
            (guild.id,),
        )
        incidents = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_incidents_v1 WHERE guild_id=? AND status='ouvert'",
            (guild.id,),
        )
        return panels.Panneau(
            titre="Audit SentriX",
            sous_titre=(
                "Configuration utilisable."
                if not issues
                else f"{len(issues)} permission(s) nécessitent votre attention."
            ),
            kind="warning" if issues else "success",
            sections=[
                panels.Section("Permissions du bot", modules),
                panels.Section(
                    "État staff",
                    [
                        panels.Ligne("Dossiers ouverts", str(open_cases)),
                        panels.Ligne("Incidents ouverts", str(incidents)),
                        panels.Ligne("Rôle SentriX", me.top_role.mention),
                    ],
                ),
            ],
            pied="SentriX • Audit non destructif",
        )

    async def _safe_count(self, query: str, params: tuple) -> int:
        try:
            row = await self.bot.db.fetchone(query, params)
            return int(row["n"] if row else 0)
        except Exception:
            return 0

    @commands.hybrid_command(name="member", description="Ouvrir la fiche staff interactive d'un membre.")
    @app_commands.describe(membre="Le membre à consulter")
    async def member(self, ctx: commands.Context, membre: discord.Member):
        await panels.envoyer(ctx, await self.member_panel(ctx.guild, membre, ctx.author.id))

    @commands.hybrid_command(name="note", description="Consulter ou ajouter une note staff privée.")
    @app_commands.describe(membre="Le membre concerné")
    async def note(self, ctx: commands.Context, membre: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM v17_staff_notes WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 12",
            (ctx.guild.id, membre.id),
        )
        embed = discord.Embed(
            title=f"Notes staff — {membre.display_name}",
            description="\n".join(
                f"**#{r['id']}** · {_relative(r['created_at'])} · {_mention(r['author_id'])}\n{_trim(r['note'], 300)}"
                for r in rows
            ) or "Aucune note privée.",
            colour=discord.Colour.blurple(),
        )
        view = MemberPanelView(self, ctx.author.id, membre.id)
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))

    @commands.hybrid_command(name="history", aliases=["historique"], description="Afficher la timeline staff complète d'un membre.")
    @app_commands.describe(membre="Le membre à consulter")
    async def history(self, ctx: commands.Context, membre: discord.Member):
        await panels.envoyer(ctx, await self.history_panel(ctx.guild, membre))

    @commands.hybrid_command(name="proof", aliases=["preuve"], description="Gérer les preuves d'un dossier staff.", with_app_command=False)
    async def proof(self, ctx: commands.Context, case_id: int):
        row = await self.bot.db.fetchone(
            "SELECT * FROM staff_cases_v1 WHERE id=? AND guild_id=?",
            (case_id, ctx.guild.id),
        )
        if not row:
            return await panels.texte_court(ctx, f"Dossier SC-{case_id:04d} introuvable.", ephemere=True)
        await panels.envoyer(ctx, await self.case_panel(ctx.guild, row, ctx.author.id))

    @commands.hybrid_command(name="incident", description="Ouvrir le centre des incidents staff.")
    async def incident(self, ctx: commands.Context):
        await panels.envoyer(ctx, await self.incident_center_panel(ctx.guild, ctx.author.id))

    @commands.hybrid_command(name="watch", aliases=["surveillance"], description="Gérer la surveillance d'un membre.")
    @app_commands.describe(membre="Le membre concerné (facultatif)")
    async def watch(self, ctx: commands.Context, membre: discord.Member | None = None):
        if membre is None:
            return await panels.envoyer(ctx, await self.watches_center_panel(ctx.guild))
        active = await self.active_watch(ctx.guild.id, membre.id)
        if active:
            return await panels.envoyer(
                ctx,
                await self.watch_panel(ctx.guild, membre.id, ctx.author.id),
            )
        view = WatchSetupView(self, ctx.author.id, ctx.guild.id, membre.id)
        embed = discord.Embed(
            title="Surveillance — configuration",
            description=f"Cible : {membre.mention}\nChoisissez les événements à suivre puis démarrez.",
            colour=discord.Colour.blurple(),
        )
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))

    @commands.hybrid_command(name="staff", description="Ouvrir le centre staff SentriX.")
    @app_commands.describe(membre="Afficher les statistiques d'un membre du staff (facultatif)")
    async def staff(self, ctx: commands.Context, membre: discord.Member | None = None):
        if membre is None:
            return await panels.envoyer(
                ctx,
                await self.staff_center_panel(ctx.guild, ctx.author.id),
            )
        sanctions = await self._safe_count(
            "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND moderator_id=?",
            (ctx.guild.id, membre.id),
        )
        notes = await self._safe_count(
            "SELECT COUNT(*) AS n FROM v17_staff_notes WHERE guild_id=? AND author_id=?",
            (ctx.guild.id, membre.id),
        )
        cases = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_cases_v1 WHERE guild_id=? AND created_by=?",
            (ctx.guild.id, membre.id),
        )
        incidents = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_incidents_v1 WHERE guild_id=? AND created_by=?",
            (ctx.guild.id, membre.id),
        )
        watches = await self._safe_count(
            "SELECT COUNT(*) AS n FROM staff_watches_v1 WHERE guild_id=? AND created_by=?",
            (ctx.guild.id, membre.id),
        )
        panel = panels.Panneau(
            titre=f"Fiche staff — {membre.display_name}",
            sous_titre=membre.mention,
            kind="moderation",
            vignette=membre.display_avatar.url,
            sections=[
                panels.Section(
                    "Activité",
                    [
                        panels.Ligne("Sanctions", str(sanctions)),
                        panels.Ligne("Notes ajoutées", str(notes)),
                        panels.Ligne("Dossiers créés", str(cases)),
                        panels.Ligne("Incidents", str(incidents)),
                        panels.Ligne("Surveillances", str(watches)),
                    ],
                    aligne=True,
                )
            ],
            pied="SentriX • Staff",
        )
        await panels.envoyer(ctx, panel)

    @commands.hybrid_command(name="handover", description="Générer la transmission pour l'équipe suivante.", with_app_command=False)
    async def handover(self, ctx: commands.Context):
        await panels.envoyer(ctx, await self.handover_panel(ctx.guild, ctx.author))

    @commands.hybrid_command(name="urgence", aliases=["emergency"], description="Ouvrir les actions d'urgence du salon.", with_app_command=False)
    async def urgence(self, ctx: commands.Context):
        panel = panels.Panneau(
            titre="Mode urgence",
            sous_titre=f"Salon actuel : {ctx.channel.mention}",
            kind="warning",
            sections=[
                panels.Section(
                    "Actions",
                    texte=(
                        "Chaque action sensible demande une seconde confirmation. "
                        "Aucun salon n'est créé, aucune action globale n'est lancée automatiquement."
                    ),
                )
            ],
            pied="SentriX • Sécurité",
        )
        await panels.envoyer(
            ctx,
            panels.avec_composants(panel, EmergencyView(self, ctx.author.id, ctx.channel.id)),
        )

    @commands.hybrid_command(name="audit", description="Auditer la configuration staff et les permissions SentriX.")
    async def audit(self, ctx: commands.Context):
        await panels.envoyer(ctx, await self.audit_panel(ctx.guild))

    @commands.hybrid_command(name="diagnostic", description="Ouvrir le diagnostic SentriX du serveur.")
    async def diagnostic(self, ctx: commands.Context):
        await panels.envoyer(ctx, await self.audit_panel(ctx.guild))

    @commands.hybrid_command(name="report", aliases=["rapport"], description="Générer un rapport staff sur une période.")
    @app_commands.describe(jours="Nombre de jours à analyser (1 à 30)")
    async def report(self, ctx: commands.Context, jours: int = 7):
        await panels.envoyer(ctx, await self.report_panel(ctx.guild, days=jours))

    @commands.hybrid_command(name="absence", description="Gérer les absences du staff.")
    async def absence(self, ctx: commands.Context):
        await self.send_absence_center(ctx, ctx.guild, ctx.author.id)

    @commands.hybrid_command(name="staff-reminder", aliases=["rappel-staff"], description="Créer un rappel staff lié à un dossier ou une tâche.", with_app_command=False)
    async def staff_reminder(
        self,
        ctx: commands.Context,
        duree: str,
        *,
        note: str,
    ):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await panels.texte_court(
                ctx,
                "Durée invalide. Exemples : 30m, 2h, 1j.",
                ephemere=True,
            )
        timestamp = now()
        await self.bot.db.execute(
            "INSERT INTO staff_reminders_v1 "
            "(guild_id,created_by,note,remind_at,status,created_at) VALUES (?,?,?,?,'actif',?)",
            (ctx.guild.id, ctx.author.id, note[:900], timestamp + seconds, timestamp),
        )
        await panels.texte_court(
            ctx,
            f"Rappel staff programmé pour <t:{timestamp + seconds}:R>.",
            ephemere=bool(ctx.interaction),
        )

    @tasks.loop(seconds=60)
    async def reminder_loop(self):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM staff_reminders_v1 WHERE status='actif' AND remind_at<=? ORDER BY remind_at LIMIT 25",
            (now(),),
        )
        for row in rows:
            user = self.bot.get_user(int(row["created_by"]))
            if user is None:
                try:
                    user = await self.bot.fetch_user(int(row["created_by"]))
                except Exception:
                    user = None
            if user is not None:
                try:
                    await user.send(
                        f"**SentriX · Rappel staff**\n{row['note']}\n"
                        f"Serveur : `{row['guild_id']}`"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await self.bot.db.execute(
                "UPDATE staff_reminders_v1 SET status='envoye' WHERE id=?",
                (row["id"],),
            )

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    async def open_case_center(self, ctx: commands.Context):
        await panels.envoyer(ctx, await self.cases_center_panel(ctx.guild, ctx.author.id))

    async def open_case_if_exists(self, ctx: commands.Context, case_id: int) -> bool:
        row = await self.bot.db.fetchone(
            "SELECT * FROM staff_cases_v1 WHERE id=? AND guild_id=?",
            (case_id, ctx.guild.id),
        )
        if not row:
            return False
        await panels.envoyer(ctx, await self.case_panel(ctx.guild, row, ctx.author.id))
        return True


async def setup(bot: commands.Bot):
    if bot.get_cog("StaffSuite") is None:
        await bot.add_cog(StaffSuite(bot))
