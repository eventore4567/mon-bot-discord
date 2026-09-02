"""
Cog TICKETS — système entièrement piloté par Discord (v2).

Rien n'est écrit en dur : chaque serveur peut créer autant de panels et de types de
tickets qu'il veut, avec son propre embed (titre/description/couleur/image/miniature/
footer), ses propres types (nom/emoji/rôle staff/catégorie/format de nom/formulaire),
ses propres questions de formulaire, et ses propres boutons staff (activés/désactivés,
libellé/emoji/couleur/rôle autorisé). Tout est en base de données (tables ticket_panels_v2,
ticket_types, ticket_form_questions, ticket_button_settings) et survit aux redémarrages.

Commandes :
+ticketsetup — menu de configuration privé (hub avec boutons vers chaque section)
+ticketpanel create/edit/delete/list/preview/send/duplicate
+tickettype add/edit/remove/list
+ticketform add/edit/remove
+ticketconfig — réglages généraux (boutons staff, délai de suppression, transcript, notes)
+ticketlogs /ticketlimit /ticketautoclose — raccourcis rapides par type
+tickettranscript /ticketstats /ticket-reopen

Aucun accès n'est jamais donné à @everyone par erreur : chaque salon de ticket part
toujours de view_channel=False pour @everyone, quoi qu'il arrive.
"""

import asyncio
import io
import json
import logging
import re
import time
import traceback

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import embeds, checks, helpers, design_system
from utils import sentrix_panels as sx_panels
from database.db import now

# Logs techniques dédiés aux tickets (diagnostic de "L'application ne répond plus" :
# ne remplace pas les erreurs affichées au membre, juste une trace complète côté serveur
# pour retrouver précisément quelle interaction a échoué, avec quel custom_id, et combien
# de temps le traitement a pris avant/après la réponse à Discord).
logger = logging.getLogger("bot.tickets")

TEXT_STYLES = {"court": discord.TextStyle.short, "long": discord.TextStyle.paragraph}
BUTTON_STYLES = {
    "bleu": discord.ButtonStyle.primary,
    "gris": discord.ButtonStyle.secondary,
    "vert": discord.ButtonStyle.success,
    "rouge": discord.ButtonStyle.danger,
}
BUTTON_STYLE_NAMES = list(BUTTON_STYLES.keys())
DEFAULT_BUTTON_STYLE = "bleu"

# Les 9 boutons staff configurables : clé interne -> (libellé par défaut, emoji par défaut).
# L'ordre ici est aussi l'ordre d'affichage par défaut dans le salon de ticket.
STAFF_BUTTONS = {
    "claim": ("Prendre en charge", "🙋"),
    "unclaim": ("Abandonner", "↩️"),
    "add": ("Ajouter un membre", "➕"),
    "remove": ("Retirer un membre", "➖"),
    "rename": ("Renommer", "✏️"),
    "transfer": ("Transférer", "🔀"),
    "note": ("Ajouter une note", "📝"),
    "bump": ("Relancer", "🔔"),
    "close": ("Fermer", "🔒"),
}
DEFAULT_ENABLED_BUTTONS = {"claim", "add", "remove", "rename", "note", "close"}


CUSTOM_COMPONENT_EMOJI_RE = re.compile(r"^<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>$")


def parse_component_emoji(value: str | None, bot=None):
    """Valide un emoji Unicode ou personnalisé Discord, animé ou non.

    Un texte libre placé dans `emoji=` fait refuser tout le composant par Discord avec
    l'erreur 50035. Les anciennes valeurs invalides sont donc ignorées proprement.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if CUSTOM_COMPONENT_EMOJI_RE.fullmatch(raw):
        emoji = discord.PartialEmoji.from_str(raw)
        if bot is not None and bot.get_emoji(emoji.id) is None:
            return None
        return emoji
    if len(raw) <= 16 and any(
        "\U0001F000" <= char <= "\U0001FAFF"
        or "\u2000" <= char <= "\u2BFF"
        or char in {"\uFE0F", "\u20E3"}
        for char in raw
    ):
        return raw
    return None


def default_button_settings() -> dict:
    return {
        key: {"enabled": key in DEFAULT_ENABLED_BUTTONS, "label": label, "emoji": emoji, "style": DEFAULT_BUTTON_STYLE, "role_id": None}
        for key, (label, emoji) in STAFF_BUTTONS.items()
    }


async def get_button_settings(bot, guild_id: int) -> dict:
    row = await bot.db.fetchone("SELECT config_json FROM ticket_button_settings WHERE guild_id = ?", (guild_id,))
    settings = default_button_settings()
    if row and row["config_json"]:
        try:
            saved = json.loads(row["config_json"])
            for key, cfg in saved.items():
                if key in settings:
                    settings[key].update(cfg)
        except (ValueError, TypeError):
            pass
    return settings


async def save_button_settings(bot, guild_id: int, settings: dict):
    await bot.db.execute(
        "INSERT INTO ticket_button_settings (guild_id, config_json) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET config_json = excluded.config_json",
        (guild_id, json.dumps(settings)),
    )


def slugify_channel_name(text: str, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9\-]+", "-", text.lower()).strip("-")
    return (text or fallback)[:90]


def format_channel_name(name_format: str, user: discord.abc.User, number: int) -> str:
    raw = (name_format or "ticket-{pseudo}").replace("{pseudo}", user.name).replace("{username}", user.name).replace("{numero}", str(number)).replace("{number}", str(number))
    return slugify_channel_name(raw, f"ticket-{number}")


# =============================================================================
# MODALS — chaque modal ne couvre qu'un petit groupe de champs (Discord limite un
# formulaire à 5 champs maximum), déclenchés depuis les boutons des vues d'édition.
# =============================================================================

class PanelTextModal(discord.ui.Modal, title="📝 Texte du panel"):
    def __init__(self, cog: "Tickets", panel):
        super().__init__()
        self.cog = cog
        self.panel_id = panel["id"]
        self.name = discord.ui.TextInput(label="Nom interne du panel", default=panel["name"], max_length=80, required=True)
        self.title_input = discord.ui.TextInput(label="Titre de l'embed", default=panel["title"], max_length=256, required=True)
        self.description = discord.ui.TextInput(
            label="Description", style=discord.TextStyle.paragraph, default=panel["description"], max_length=2000, required=True,
        )
        self.add_item(self.name)
        self.add_item(self.title_input)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.bot.db.execute(
            "UPDATE ticket_panels_v2 SET name = ?, title = ?, description = ? WHERE id = ?",
            (self.name.value, self.title_input.value, self.description.value, self.panel_id),
        )
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success('Texte du panel mis à jour.')), ephemere=True)


class PanelMediaModal(discord.ui.Modal, title="🖼️ Image, miniature et couleur"):
    def __init__(self, cog: "Tickets", panel):
        super().__init__()
        self.cog = cog
        self.panel_id = panel["id"]
        self.color = discord.ui.TextInput(
            label="Couleur (hex, ex: 5865F2)", default=(f"{panel['color']:06X}" if panel["color"] else ""), required=False, max_length=6,
        )
        self.image = discord.ui.TextInput(label="URL de l'image", default=panel["image_url"] or "", required=False, max_length=300)
        self.thumbnail = discord.ui.TextInput(label="URL de la miniature", default=panel["thumbnail_url"] or "", required=False, max_length=300)
        self.footer = discord.ui.TextInput(label="Texte du footer", default=panel["footer_text"] or "", required=False, max_length=200)
        self.add_item(self.color)
        self.add_item(self.image)
        self.add_item(self.thumbnail)
        self.add_item(self.footer)

    async def on_submit(self, interaction: discord.Interaction):
        color_value = None
        raw = self.color.value.strip().lstrip("#")
        if raw:
            try:
                color_value = int(raw, 16)
            except ValueError:
                return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Couleur invalide — utilisez un code hexadécimal, ex: `5865F2`.')), ephemere=True)
        await self.cog.bot.db.execute(
            "UPDATE ticket_panels_v2 SET color = ?, image_url = ?, thumbnail_url = ?, footer_text = ? WHERE id = ?",
            (color_value, self.image.value or None, self.thumbnail.value or None, self.footer.value or None, self.panel_id),
        )
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success('Apparence du panel mise à jour.')), ephemere=True)


class PanelMaxModal(discord.ui.Modal, title="🔢 Limite de tickets par membre"):
    def __init__(self, cog: "Tickets", panel):
        super().__init__()
        self.cog = cog
        self.panel_id = panel["id"]
        self.max_input = discord.ui.TextInput(label="Tickets simultanés max par membre", default=str(panel["max_per_member"]), max_length=3)
        self.add_item(self.max_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.max_input.value.strip().isdigit():
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('La limite doit être un nombre entier compris entre 1 et 20.')), ephemere=True)
        maximum = int(self.max_input.value)
        if not 1 <= maximum <= 20:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('La limite doit être comprise entre 1 et 20 tickets simultanés par membre.')), ephemere=True)
        await self.cog.bot.db.execute(
            "UPDATE ticket_panels_v2 SET max_per_member = ? WHERE id = ?", (maximum, self.panel_id)
        )
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Limite enregistrée : **{maximum}** ticket(s) simultané(s) maximum par membre.')), ephemere=True)


class PanelAddTypeModal(discord.ui.Modal, title="➕ Ajouter un type de ticket"):
    """Permet d'ajouter un type directement depuis l'éditeur de panel (bouton), sans avoir
    à taper `+tickettype add <panel> <nom>` dans une commande séparée."""

    def __init__(self, cog: "Tickets", panel_id: int, guild_id: int):
        super().__init__()
        self.cog = cog
        self.panel_id = panel_id
        self.guild_id = guild_id
        self.name = discord.ui.TextInput(label="Nom du type (ex: Support, Recrutement)", max_length=80)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip()
        if not name:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Le nom ne peut pas être vide.')), ephemere=True)
        if await self.cog.get_type_by_name(self.guild_id, name):
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error(f'Un type nommé « {name} » existe déjà sur ce serveur.')), ephemere=True)
        type_id = await self.cog.add_type(self.guild_id, self.panel_id, name)
        await interaction.response.send_message(
            embed=embeds.success(f"Type **{name}** créé (#{type_id}). Configurez-le ci-dessous, puis revenez sur l'éditeur du panel pour l'envoyer."),
            view=TypeEditView(self.cog, type_id, interaction.user.id),
            ephemeral=True,
        )


class TypeTextModal(discord.ui.Modal, title="📝 Type de ticket — Texte"):
    def __init__(self, cog: "Tickets", ticket_type):
        super().__init__()
        self.cog = cog
        self.type_id = ticket_type["id"]
        self.name = discord.ui.TextInput(label="Nom du type (ex: Support)", default=ticket_type["name"], max_length=80)
        self.description = discord.ui.TextInput(label="Description courte", default=ticket_type["description"] or "", required=False, max_length=150)
        self.emoji = discord.ui.TextInput(label="Emoji Unicode ou personnalisé", default=ticket_type["emoji"] or "", required=False, max_length=100)
        self.button_label = discord.ui.TextInput(label="Texte du bouton/option", default=ticket_type["button_label"] or "", required=False, max_length=80)
        self.name_format = discord.ui.TextInput(
            label="Format du nom de salon ({pseudo}/{numero})", default=ticket_type["name_format"], max_length=90,
        )
        self.add_item(self.name)
        self.add_item(self.description)
        self.add_item(self.emoji)
        self.add_item(self.button_label)
        self.add_item(self.name_format)

    async def on_submit(self, interaction: discord.Interaction):
        raw_emoji = self.emoji.value.strip()
        emoji = parse_component_emoji(raw_emoji, interaction.client)
        if raw_emoji and emoji is None:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('L’emoji indiqué n’est pas utilisable par le bot. Collez un emoji Unicode, ou un emoji personnalisé Discord complet comme `<:nom:id>` ou `<a:nom:id>`.')), ephemere=True)
        await self.cog.bot.db.execute(
            "UPDATE ticket_types SET name = ?, description = ?, emoji = ?, button_label = ?, name_format = ? WHERE id = ?",
            (self.name.value.strip(), self.description.value, str(emoji) if emoji else None, self.button_label.value, self.name_format.value, self.type_id),
        )
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success('Le type de ticket a été mis à jour. Le prochain envoi du panel utilisera ces réglages.')), ephemere=True)


class TypeOpenMessageModal(discord.ui.Modal, title="💬 Message d'ouverture"):
    def __init__(self, cog: "Tickets", ticket_type):
        super().__init__()
        self.cog = cog
        self.type_id = ticket_type["id"]
        self.message = discord.ui.TextInput(
            label="Message envoyé à l'ouverture du ticket", style=discord.TextStyle.paragraph,
            default=ticket_type["open_message"] or "", required=False, max_length=1000,
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.bot.db.execute("UPDATE ticket_types SET open_message = ? WHERE id = ?", (self.message.value, self.type_id))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success("Message d'ouverture mis à jour.")), ephemere=True)


class TypeNumbersModal(discord.ui.Modal, title="🔢 Limites du type de ticket"):
    def __init__(self, cog: "Tickets", ticket_type):
        super().__init__()
        self.cog = cog
        self.type_id = ticket_type["id"]
        self.max_per_member = discord.ui.TextInput(label="Tickets simultanés max par membre", default=str(ticket_type["max_per_member"]), max_length=3)
        self.autoclose = discord.ui.TextInput(
            label="Fermeture auto après (heures, 0 = désactivé)", default=str(ticket_type["autoclose_hours"]), max_length=4,
        )
        self.add_item(self.max_per_member)
        self.add_item(self.autoclose)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.max_per_member.value.strip().isdigit() or not self.autoclose.value.strip().isdigit():
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Les deux champs doivent contenir des nombres entiers, sans lettre ni symbole.')), ephemere=True)
        maximum = int(self.max_per_member.value)
        autoclose = int(self.autoclose.value)
        if not 1 <= maximum <= 20:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('La limite doit être comprise entre 1 et 20 tickets simultanés par membre.')), ephemere=True)
        if not 0 <= autoclose <= 720:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('La fermeture automatique doit être comprise entre 0 et 720 heures. Utilisez 0 pour la désactiver.')), ephemere=True)
        await self.cog.bot.db.execute(
            "UPDATE ticket_types SET max_per_member = ?, autoclose_hours = ? WHERE id = ?",
            (maximum, autoclose, self.type_id),
        )
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Limites enregistrées : **{maximum}** ticket(s) maximum par membre, fermeture automatique ' + (f'après **{autoclose} h**.' if autoclose else 'désactivée.'))), ephemere=True)


class FormQuestionModal(discord.ui.Modal, title="📋 Question du formulaire"):
    def __init__(self, cog: "Tickets", type_id: int, question=None):
        super().__init__()
        self.cog = cog
        self.type_id = type_id
        self.question_id = question["id"] if question else None
        self.label = discord.ui.TextInput(label="Intitulé de la question", default=question["label"] if question else "", max_length=45)
        self.placeholder = discord.ui.TextInput(
            label="Exemple / placeholder", default=(question["placeholder"] if question else ""), required=False, max_length=100,
        )
        self.style = discord.ui.TextInput(
            label="Style : court ou long", default=(question["style"] if question else "court"), max_length=5,
        )
        self.required = discord.ui.TextInput(
            label="Obligatoire ? (oui/non)", default=("oui" if (not question or question["required"]) else "non"), max_length=3,
        )
        self.lengths = discord.ui.TextInput(
            label="Longueur min-max (ex: 0-500)",
            default=(f"{question['min_length']}-{question['max_length']}" if question else "0-500"), max_length=10,
        )
        self.add_item(self.label)
        self.add_item(self.placeholder)
        self.add_item(self.style)
        self.add_item(self.required)
        self.add_item(self.lengths)

    async def on_submit(self, interaction: discord.Interaction):
        style = self.style.value.strip().lower()
        if style not in TEXT_STYLES:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Le style doit être `court` ou `long`.')), ephemere=True)
        required = self.required.value.strip().lower() in ("oui", "yes", "o", "y", "true", "1")
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", self.lengths.value)
        if not m:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Longueur invalide — format attendu : `min-max`, ex: `0-500`.')), ephemere=True)
        min_len, max_len = int(m.group(1)), int(m.group(2))
        if max_len < min_len or max_len > 4000 or max_len == 0:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('La longueur max doit être supérieure à 0, à la longueur min, et ≤ 4000.')), ephemere=True)

        if self.question_id:
            await self.cog.bot.db.execute(
                "UPDATE ticket_form_questions SET label=?, placeholder=?, style=?, required=?, min_length=?, max_length=? WHERE id=?",
                (self.label.value, self.placeholder.value, style, int(required), min_len, max_len, self.question_id),
            )
            msg = "Question mise à jour."
        else:
            count = await self.cog.bot.db.fetchone("SELECT COUNT(*) c FROM ticket_form_questions WHERE ticket_type_id = ?", (self.type_id,))
            if count["c"] >= 5:
                return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Un formulaire Discord ne peut pas dépasser **5 questions** (limite native des formulaires).')), ephemere=True)
            await self.cog.bot.db.execute(
                "INSERT INTO ticket_form_questions (ticket_type_id, position, label, placeholder, style, required, min_length, max_length) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.type_id, count["c"], self.label.value, self.placeholder.value, style, int(required), min_len, max_len),
            )
            await self.cog.bot.db.execute("UPDATE ticket_types SET use_form = 1 WHERE id = ?", (self.type_id,))
            msg = "Question ajoutée au formulaire."
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(msg)), ephemere=True)


class ButtonCustomizeModal(discord.ui.Modal, title="🔘 Personnaliser le bouton"):
    def __init__(self, cog: "Tickets", guild_id: int, key: str, cfg: dict, default_label: str, default_emoji: str):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.key = key
        self.label = discord.ui.TextInput(label="Libellé du bouton", default=cfg.get("label") or default_label, max_length=80)
        self.emoji = discord.ui.TextInput(label="Emoji Unicode ou personnalisé", default=cfg.get("emoji") or default_emoji, required=False, max_length=100)
        self.style = discord.ui.TextInput(
            label=f"Couleur ({'/'.join(BUTTON_STYLE_NAMES)})", default=cfg.get("style", DEFAULT_BUTTON_STYLE), max_length=5,
        )
        self.add_item(self.label)
        self.add_item(self.emoji)
        self.add_item(self.style)

    async def on_submit(self, interaction: discord.Interaction):
        style = self.style.value.strip().lower()
        if style not in BUTTON_STYLES:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error(f"Couleur invalide — choisissez parmi : {', '.join(BUTTON_STYLE_NAMES)}.")), ephemere=True)
        raw_emoji = self.emoji.value.strip()
        emoji = parse_component_emoji(raw_emoji, interaction.client)
        if raw_emoji and emoji is None:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('L’emoji indiqué n’est pas utilisable par le bot. Utilisez un emoji Unicode ou collez un emoji Discord complet, animé ou non.')), ephemere=True)
        settings = await get_button_settings(self.cog.bot, self.guild_id)
        settings[self.key]["label"] = self.label.value.strip()
        settings[self.key]["emoji"] = str(emoji) if emoji else None
        settings[self.key]["style"] = style
        await save_button_settings(self.cog.bot, self.guild_id, settings)
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Bouton **{self.label.value}** mis à jour.')), ephemere=True)


class CloseReasonModal(discord.ui.Modal, title="🔒 Fermer le ticket"):
    def __init__(self, cog: "Tickets", ticket_id: int):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id
        self.reason = discord.ui.TextInput(
            label="Raison de la fermeture (optionnel)", style=discord.TextStyle.paragraph, required=False, max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.cog.close_ticket(interaction, self.ticket_id, self.reason.value or "Aucune raison fournie")


class TicketNoteModal(discord.ui.Modal, title="📝 Note interne"):
    def __init__(self, cog: "Tickets", ticket_id: int):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id
        self.note = discord.ui.TextInput(label="Contenu de la note (invisible pour le membre)", style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.bot.db.execute(
            "INSERT INTO ticket_notes (ticket_id, author_id, note, timestamp) VALUES (?, ?, ?, ?)",
            (self.ticket_id, interaction.user.id, self.note.value, now()),
        )
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success('📝 Note interne enregistrée (invisible pour le membre).')), ephemere=True)


class TicketRenameModal(discord.ui.Modal, title="✏️ Renommer le ticket"):
    def __init__(self, cog: "Tickets", channel: discord.TextChannel):
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.new_name = discord.ui.TextInput(label="Nouveau nom du salon", default=channel.name, max_length=90)
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        name = slugify_channel_name(self.new_name.value, self.channel.name)
        await self.channel.edit(name=name)
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Salon renommé en **{name}**.')), ephemere=True)


# =============================================================================
# VUES — panel d'ouverture, contrôle du ticket, éditeurs de panel/type, hub /ticketsetup
# =============================================================================

class TicketOpenSelect(discord.ui.Select):
    def __init__(self, panel_id: int, types: list):
        options = [
            discord.SelectOption(
                label=(t["name"] or "Ticket")[:100], value=str(t["id"]),
                emoji=parse_component_emoji(t["emoji"]), description=(t["description"] or "")[:100] or None,
            )
            for t in types[:25]
        ]
        super().__init__(
            placeholder="🎫 Choisissez une catégorie pour ouvrir un ticket...",
            options=options, custom_id=f"ticket_open_select:{panel_id}", min_values=1, max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        await cog.start_ticket_flow(interaction, int(self.values[0]))


class TicketOpenButton(discord.ui.Button):
    def __init__(self, ticket_type):
        style = BUTTON_STYLES.get(ticket_type["button_style"], discord.ButtonStyle.primary)
        label = (ticket_type["button_label"] or ticket_type["name"] or "Ticket")[:80]
        super().__init__(label=label, emoji=parse_component_emoji(ticket_type["emoji"]), style=style, custom_id=f"ticket_open_btn:{ticket_type['id']}")
        self.ticket_type_id = ticket_type["id"]

    async def callback(self, interaction: discord.Interaction):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        await cog.start_ticket_flow(interaction, self.ticket_type_id)


class TicketPanelView(discord.ui.View):
    """Vue affichée dans le panel envoyé aux membres. Reconstruite dynamiquement depuis la
    base de données à chaque envoi ET après chaque redémarrage (Tickets.restore_panel_views),
    donc toujours à jour avec les types de tickets réellement configurés."""

    def __init__(self, panel, types: list):
        super().__init__(timeout=None)
        if not types:
            return
        if panel["style"] == "button":
            for t in types[:25]:
                self.add_item(TicketOpenButton(t))
        else:
            self.add_item(TicketOpenSelect(panel["id"], types))


class TicketControlButton(discord.ui.Button):
    def __init__(self, key: str, cfg: dict, default_label: str, default_emoji: str, row: int):
        super().__init__(
            label=(cfg.get("label") or default_label)[:80],
            emoji=parse_component_emoji(cfg.get("emoji")) or parse_component_emoji(default_emoji),
            style=BUTTON_STYLES.get(cfg.get("style", DEFAULT_BUTTON_STYLE), discord.ButtonStyle.primary),
            custom_id=f"ticket_ctrl_{key}",
            row=row,
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        await cog.handle_control_button(interaction, self.key)


class TicketControlView(discord.ui.View):
    """Vue de contrôle affichée dans chaque salon de ticket. `button_settings=None` sert
    UNIQUEMENT à l'enregistrement générique après redémarrage (voir main.py) : elle affiche
    alors tous les boutons pour que le routage des custom_id fonctionne quel que soit le
    serveur — les vraies vues envoyées aux salons utilisent toujours la config réelle."""

    def __init__(self, button_settings: dict | None = None):
        super().__init__(timeout=None)
        settings = button_settings if button_settings is not None else default_button_settings()
        row = 0
        count_in_row = 0
        for key, (default_label, default_emoji) in STAFF_BUTTONS.items():
            cfg = settings.get(key, {"enabled": key in DEFAULT_ENABLED_BUTTONS})
            if not cfg.get("enabled", True):
                continue
            self.add_item(TicketControlButton(key, cfg, default_label, default_emoji, row))
            count_in_row += 1
            if count_in_row >= 5:
                row += 1
                count_in_row = 0


class RatingView(discord.ui.View):
    """5 étoiles envoyées après la fermeture d'un ticket pour noter le support reçu."""

    def __init__(self, cog: "Tickets", ticket_id: int):
        super().__init__(timeout=86400)
        self.cog = cog
        self.ticket_id = ticket_id
        for i in range(1, 6):
            self.add_item(self._make_button(i))

    def _make_button(self, value: int) -> discord.ui.Button:
        btn = discord.ui.Button(label="⭐" * value, style=discord.ButtonStyle.secondary, custom_id=f"rate_{value}")

        async def callback(interaction: discord.Interaction):
            await self.cog.bot.db.execute("UPDATE tickets SET rating = ? WHERE id = ?", (value, self.ticket_id))
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content=f"Merci pour votre note : {'⭐' * value}", view=self)
            self.stop()

        btn.callback = callback
        return btn


class PanelEditView(discord.ui.View):
    """Chaque aspect du panel (texte, couleur/image, salon, style, limite) s'édite via son
    propre bouton — Discord limite un formulaire à 5 champs, impossible de tout regrouper."""

    def __init__(self, cog: "Tickets", panel_id: int, author_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.panel_id = panel_id
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seul l'auteur de la commande peut modifier ce panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Titre / Description", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = await self.cog.get_panel(self.panel_id)
        await interaction.response.send_modal(PanelTextModal(self.cog, panel))

    @discord.ui.button(label="Image / Couleur", style=discord.ButtonStyle.secondary, emoji="🎨", row=0)
    async def edit_media(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = await self.cog.get_panel(self.panel_id)
        await interaction.response.send_modal(PanelMediaModal(self.cog, panel))

    @discord.ui.button(label="Limite / membre", style=discord.ButtonStyle.secondary, emoji="🔢", row=0)
    async def edit_max(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = await self.cog.get_panel(self.panel_id)
        await interaction.response.send_modal(PanelMaxModal(self.cog, panel))

    @discord.ui.button(label="Style : menu ⇄ boutons", style=discord.ButtonStyle.secondary, emoji="🔘", row=1)
    async def toggle_style(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = await self.cog.get_panel(self.panel_id)
        new_style = "button" if panel["style"] == "select" else "select"
        await self.cog.bot.db.execute("UPDATE ticket_panels_v2 SET style = ? WHERE id = ?", (new_style, self.panel_id))
        label = "boutons" if new_style == "button" else "menu déroulant"
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Le panel affichera désormais un **{label}**.')), ephemere=True)

    @discord.ui.button(label="Aperçu", style=discord.ButtonStyle.primary, emoji="👁️", row=1)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_panel_preview(interaction, self.panel_id)

    @discord.ui.button(label="Ajouter un type de ticket", style=discord.ButtonStyle.secondary, emoji="🎫", row=1)
    async def add_type_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Corrige : avant, un panel sans type devait obligatoirement être configuré via la
        # commande séparée `+tickettype add <panel> <nom>` — impossible de le faire depuis
        # l'éditeur du panel lui-même. On peut maintenant ajouter un type directement ici.
        await interaction.response.send_modal(PanelAddTypeModal(self.cog, self.panel_id, interaction.guild.id))

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="📌 Choisir le salon où envoyer le panel", row=2)
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await self.cog.bot.db.execute("UPDATE ticket_panels_v2 SET channel_id = ? WHERE id = ?", (select.values[0].id, self.panel_id))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Salon de destination défini sur {select.values[0].mention}.')), ephemere=True)

    @discord.ui.button(label="📤 Envoyer / mettre à jour le panel", style=discord.ButtonStyle.success, row=3)
    async def send_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_panel(interaction, self.panel_id)


class TypeEditView(discord.ui.View):
    def __init__(self, cog: "Tickets", type_id: int, author_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.type_id = type_id
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seul l'auteur de la commande peut modifier ce type de ticket.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Texte / Nom / Emoji", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        await interaction.response.send_modal(TypeTextModal(self.cog, t))

    @discord.ui.button(label="Message d'ouverture", style=discord.ButtonStyle.secondary, emoji="💬", row=0)
    async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        await interaction.response.send_modal(TypeOpenMessageModal(self.cog, t))

    @discord.ui.button(label="Limites (max/autoclose)", style=discord.ButtonStyle.secondary, emoji="🔢", row=0)
    async def edit_numbers(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        await interaction.response.send_modal(TypeNumbersModal(self.cog, t))

    @discord.ui.button(label="Formulaire on/off", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def toggle_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        new_val = 0 if t["use_form"] else 1
        await self.cog.bot.db.execute("UPDATE ticket_types SET use_form = ? WHERE id = ?", (new_val, self.type_id))
        state = "activé (utilisez `+ticketform add` pour ajouter des questions)" if new_val else "désactivé"
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Formulaire {state}.')), ephemere=True)

    @discord.ui.button(label="Mention staff on/off", style=discord.ButtonStyle.secondary, emoji="🔔", row=1)
    async def toggle_mention(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        new_val = 0 if t["mention_staff"] else 1
        await self.cog.bot.db.execute("UPDATE ticket_types SET mention_staff = ? WHERE id = ?", (new_val, self.type_id))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f"Mention du rôle staff {('activée' if new_val else 'désactivée')} à l'ouverture.")), ephemere=True)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🛡️ Rôle staff à mentionner / autoriser", row=2)
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        await self.cog.bot.db.execute("UPDATE ticket_types SET staff_role_id = ? WHERE id = ?", (select.values[0].id, self.type_id))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Rôle staff défini sur {select.values[0].mention}.')), ephemere=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.category], placeholder="📂 Catégorie où créer les salons", row=3)
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await self.cog.bot.db.execute("UPDATE ticket_types SET category_id = ? WHERE id = ?", (select.values[0].id, self.type_id))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Catégorie définie sur **{select.values[0].name}**.')), ephemere=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="📄 Salon de logs pour ce type", row=4)
    async def select_logs(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await self.cog.bot.db.execute("UPDATE ticket_types SET log_channel_id = ? WHERE id = ?", (select.values[0].id, self.type_id))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'Salon de logs défini sur {select.values[0].mention}.')), ephemere=True)


class ButtonSettingsView(discord.ui.View):
    """Active/désactive et personnalise les 9 boutons staff, un par bouton (label court
    obligatoire côté Discord — pas la place de tout mettre sur une seule ligne)."""

    def __init__(self, cog: "Tickets", guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seul l'auteur de la commande peut modifier ces réglages.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="🔘 Choisir un bouton à activer / désactiver / personnaliser",
        options=[discord.SelectOption(label=label, value=key, emoji=emoji) for key, (label, emoji) in STAFF_BUTTONS.items()],
        row=0,
    )
    async def pick_button(self, interaction: discord.Interaction, select: discord.ui.Select):
        key = select.values[0]
        default_label, default_emoji = STAFF_BUTTONS[key]
        settings = await get_button_settings(self.cog.bot, self.guild_id)
        cfg = settings[key]
        view = discord.ui.View(timeout=120)

        toggle_btn = discord.ui.Button(
            label="Désactiver" if cfg["enabled"] else "Activer",
            style=discord.ButtonStyle.danger if cfg["enabled"] else discord.ButtonStyle.success,
        )

        async def toggle_cb(inter: discord.Interaction):
            settings2 = await get_button_settings(self.cog.bot, self.guild_id)
            settings2[key]["enabled"] = not settings2[key]["enabled"]
            await save_button_settings(self.cog.bot, self.guild_id, settings2)
            state = "activé ●" if settings2[key]["enabled"] else "désactivé ○"
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success(f'Bouton **{default_label}** {state}.')), ephemere=True)

        toggle_btn.callback = toggle_cb
        view.add_item(toggle_btn)

        customize_btn = discord.ui.Button(label="Personnaliser (libellé/emoji/couleur)", style=discord.ButtonStyle.secondary)

        async def customize_cb(inter: discord.Interaction):
            settings3 = await get_button_settings(self.cog.bot, self.guild_id)
            await inter.response.send_modal(ButtonCustomizeModal(self.cog, self.guild_id, key, settings3[key], default_label, default_emoji))

        customize_btn.callback = customize_cb
        view.add_item(customize_btn)

        role_select = discord.ui.RoleSelect(placeholder="🛡️ Restreindre à un rôle (optionnel)")

        async def role_cb(inter: discord.Interaction):
            settings4 = await get_button_settings(self.cog.bot, self.guild_id)
            settings4[key]["role_id"] = role_select.values[0].id
            await save_button_settings(self.cog.bot, self.guild_id, settings4)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success(f'Bouton **{default_label}** restreint au rôle {role_select.values[0].mention}.')), ephemere=True)

        role_select.callback = role_cb
        view.add_item(role_select)

        state_text = "● Activé" if cfg["enabled"] else "○ Désactivé"
        e = embeds.neutral(f"{cfg.get('emoji') or default_emoji} {cfg.get('label') or default_label}", f"État actuel : {state_text}")
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)


class TicketSetupHubView(discord.ui.View):
    """Vue affichée par +ticketsetup : point d'entrée unique vers toutes les sections."""

    def __init__(self, cog: "Tickets", author_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu est privé — relancez `+ticketsetup` pour avoir le vôtre.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Panels", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def panels_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.list_panels(interaction)

    @discord.ui.button(label="Types de tickets", style=discord.ButtonStyle.primary, emoji="🎫", row=0)
    async def types_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.list_types(interaction, panel_id=None)

    @discord.ui.button(label="Boutons staff", style=discord.ButtonStyle.primary, emoji="🔘", row=0)
    async def buttons_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = embeds.neutral("🔘 Boutons staff", "Choisissez un bouton dans le menu pour l'activer/désactiver ou le personnaliser.")
        await interaction.response.send_message(embed=e, view=ButtonSettingsView(self.cog, interaction.guild.id, interaction.user.id), ephemeral=True)

    @discord.ui.button(label="Statistiques", style=discord.ButtonStyle.secondary, emoji="📊", row=1)
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_stats(interaction)

    @discord.ui.button(label="Nouveau panel", style=discord.ButtonStyle.success, emoji="➕", row=1)
    async def new_panel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="➕ Nouveau panel")
        name_input = discord.ui.TextInput(label="Nom du panel", max_length=80)
        modal.add_item(name_input)

        async def on_submit(inter: discord.Interaction):
            panel_id = await self.cog.create_panel(inter.guild.id, name_input.value)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success(f'Panel **{name_input.value}** créé (#{panel_id}). Utilisez `+ticketpanel edit {name_input.value}` pour le configurer.')), ephemere=True)

        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)


# =============================================================================
# COG
# =============================================================================

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_autoclose.start()

    def cog_unload(self):
        self.check_autoclose.cancel()

    async def restore_panel_views(self) -> int:
        """Réenregistre une vue persistante pour chaque panel actif après un redémarrage,
        avec ses VRAIES options (types de tickets), pour que les menus/boutons déjà envoyés
        sur Discord continuent de fonctionner exactement comme avant l'arrêt du bot.
        Retourne le nombre de panels effectivement restaurés (utilisé pour le log de
        démarrage — voir main.py)."""
        panels = await self.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE enabled = 1 AND message_id IS NOT NULL")
        restored = 0
        for panel in panels:
            types = await self.get_panel_types(panel["id"])
            if not types:
                continue
            try:
                self.bot.add_view(TicketPanelView(panel, types), message_id=panel["message_id"])
                restored += 1
            except discord.HTTPException:
                pass
        return restored

    # ---------------------------------------------------------------- ACCÈS DB

    async def get_panel(self, panel_id: int):
        return await self.bot.db.fetchone("SELECT * FROM ticket_panels_v2 WHERE id = ?", (panel_id,))

    async def get_panel_by_name(self, guild_id: int, name: str):
        return await self.bot.db.fetchone(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)
        )

    async def get_panel_types(self, panel_id: int):
        return await self.bot.db.fetchall("SELECT * FROM ticket_types WHERE panel_id = ? ORDER BY position, id", (panel_id,))

    async def get_type(self, type_id: int):
        return await self.bot.db.fetchone("SELECT * FROM ticket_types WHERE id = ?", (type_id,))

    async def get_type_by_name(self, guild_id: int, name: str):
        return await self.bot.db.fetchone(
            "SELECT * FROM ticket_types WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)
        )

    async def get_ticket_by_channel(self, channel_id: int):
        return await self.bot.db.fetchone("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))

    async def create_panel(self, guild_id: int, name: str) -> int:
        cur = await self.bot.db.execute(
            "INSERT INTO ticket_panels_v2 (guild_id, name, title, description, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, name, f"🎫 {name}", "Choisissez une option ci-dessous pour ouvrir un ticket.", now()),
        )
        return cur.lastrowid

    async def add_type(self, guild_id: int, panel_id: int, name: str) -> int:
        """Logique partagée entre `+tickettype add` et le bouton "➕ Type de ticket" de
        l'éditeur de panel — un seul endroit pour créer un type, pour ne jamais désynchroniser
        les deux chemins."""
        count = await self.bot.db.fetchone("SELECT COUNT(*) c FROM ticket_types WHERE panel_id = ?", (panel_id,))
        cur = await self.bot.db.execute(
            "INSERT INTO ticket_types (panel_id, guild_id, name, name_format, position) VALUES (?, ?, ?, ?, ?)",
            (panel_id, guild_id, name, f"ticket-{{pseudo}}", count["c"]),
        )
        return cur.lastrowid

    # ---------------------------------------------------------------- LOGS

    async def log_action(self, guild: discord.Guild, embed: discord.Embed, log_channel_id: int | None = None):
        """Priorité 1 : salon dédié à CE type de ticket (+ticketlogs), inchangé — reste
        indépendant du réglage général ci-dessous, c'est un choix explicite déjà fait par
        un admin. Priorité 2 (repli) : catégorie "tickets" de /logsetup (utils/log_service),
        qui reprend automatiquement l'ancien réglage `ticket_log_channel` au premier accès
        (migration non destructive — voir log_service._migrate_from_legacy)."""
        if log_channel_id:
            channel = guild.get_channel(log_channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                    return
                except discord.HTTPException:
                    pass
        from utils import log_service
        await log_service.send_log(self.bot, guild, "tickets", embed)

    # ---------------------------------------------------------------- OUVERTURE

    def build_panel_embed(self, panel) -> discord.Embed:
        e = embeds.brand(panel["title"] or "🎫 Support", panel["description"] or "")
        if panel["color"]:
            e.color = panel["color"]
        if panel["image_url"]:
            e.set_image(url=panel["image_url"])
        if panel["thumbnail_url"]:
            e.set_thumbnail(url=panel["thumbnail_url"])
        if panel["footer_text"]:
            e.set_footer(text=panel["footer_text"])
        return e

    async def send_panel_preview(self, interaction: discord.Interaction, panel_id: int):
        panel = await self.get_panel(panel_id)
        types = await self.get_panel_types(panel_id)
        if not types:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.warning("Ce panel n'a aucun type de ticket — ajoutez-en avec `+tickettype add`.")), ephemere=True)
        await interaction.response.send_message(embed=self.build_panel_embed(panel), view=TicketPanelView(panel, types), ephemeral=True)

    async def send_panel(self, interaction: discord.Interaction, panel_id: int):
        panel = await self.get_panel(panel_id)
        types = await self.get_panel_types(panel_id)
        if not panel["channel_id"]:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error("Choisissez d'abord un salon de destination (menu déroulant du dessus).")), ephemere=True)
        if not types:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error("Ce panel n'a aucun type de ticket — ajoutez-en avec `+tickettype add` avant de l'envoyer.")), ephemere=True)
        channel = interaction.guild.get_channel(panel["channel_id"])
        if not channel:
            return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error("Le salon configuré n'existe plus.")), ephemere=True)

        await interaction.response.defer(ephemeral=True)
        old_message_id = panel["message_id"]
        if old_message_id:
            try:
                old = await channel.fetch_message(old_message_id)
                await old.delete()
            except discord.HTTPException:
                pass
        msg = await channel.send(embed=self.build_panel_embed(panel), view=TicketPanelView(panel, types))
        await self.bot.db.execute("UPDATE ticket_panels_v2 SET message_id = ?, channel_id = ? WHERE id = ?", (msg.id, channel.id, panel_id))
        await sx_panels.envoyer(interaction.followup, sx_panels.depuis_embed(embeds.success(f'📤 Panel envoyé dans {channel.mention}.')), ephemere=True)

    async def start_ticket_flow(self, interaction: discord.Interaction, type_id: int):
        started = time.monotonic()
        guild_id = interaction.guild.id if interaction.guild else None
        user_id = interaction.user.id if interaction.user else None
        try:
            ticket_type = await self.get_type(type_id)
            if not ticket_type:
                return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error("Ce type de ticket n'existe plus.")), ephemere=True)

            limit = ticket_type["max_per_member"] or 1
            open_count = await self.bot.db.fetchone(
                "SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND user_id = ? AND type_id = ? AND status = 'ouvert'",
                (interaction.guild.id, interaction.user.id, type_id),
            )
            if open_count["c"] >= limit:
                return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.warning(f"Vous avez déjà **{open_count['c']}** ticket(s) « {ticket_type['name']} » ouvert(s) (maximum : {limit}).")), ephemere=True)

            if ticket_type["use_form"]:
                questions = await self.bot.db.fetchall(
                    "SELECT * FROM ticket_form_questions WHERE ticket_type_id = ? ORDER BY position", (type_id,)
                )
                if questions:
                    return await interaction.response.send_modal(TicketFormModal(self, ticket_type, questions))

            await interaction.response.defer(ephemeral=True)
            await self.create_ticket(interaction, ticket_type, [])
        except discord.InteractionResponded:
            logger.info("Interaction déjà répondue pour l'ouverture du type #%s (guild=%s, user=%s).", type_id, guild_id, user_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
            logger.error("Erreur Discord à l'ouverture du ticket type #%s (guild=%s, user=%s) : %s", type_id, guild_id, user_id, e)
            if not interaction.response.is_done():
                try:
                    await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Une erreur Discord est survenue. Réessayez dans un instant.')), ephemere=True)
                except discord.HTTPException:
                    pass
        except Exception:
            logger.error(
                "Exception non gérée à l'ouverture du ticket type #%s (guild=%s, user=%s) :\n%s",
                type_id, guild_id, user_id, traceback.format_exc(),
            )
            try:
                if interaction.response.is_done():
                    await sx_panels.envoyer(interaction.followup, sx_panels.depuis_embed(embeds.error('Une erreur inattendue est survenue. Le staff a été informé.')), ephemere=True)
                else:
                    await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Une erreur inattendue est survenue. Le staff a été informé.')), ephemere=True)
            except discord.HTTPException:
                pass
        finally:
            elapsed = time.monotonic() - started
            level = logger.warning if elapsed > 2.0 else logger.info
            level("Ouverture ticket type #%s traitée en %.2fs (guild=%s, user=%s).", type_id, elapsed, guild_id, user_id)

    async def create_ticket(self, interaction: discord.Interaction, ticket_type, answers: list):
        guild = interaction.guild
        user = interaction.user

        count_row = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ?", (guild.id,))
        number = (count_row["c"] or 0) + 1
        channel_name = format_channel_name(ticket_type["name_format"], user, number)

        # @everyone n'a JAMAIS accès : c'est la toute première ligne des overwrites, quoi
        # qu'il arrive dans la configuration du type de ticket.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True),
        }
        staff_role = guild.get_role(ticket_type["staff_role_id"]) if ticket_type["staff_role_id"] else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        category = guild.get_channel(ticket_type["category_id"]) if ticket_type["category_id"] else None
        category = category if isinstance(category, discord.CategoryChannel) else None

        try:
            channel = await guild.create_text_channel(
                channel_name, overwrites=overwrites, category=category, reason=f"Ticket « {ticket_type['name']} » ouvert par {user}",
            )
        except discord.HTTPException:
            return await sx_panels.envoyer(interaction.followup, sx_panels.depuis_embed(embeds.error('Impossible de créer le salon (permissions du bot ou catégorie pleine).')), ephemere=True)

        cur = await self.bot.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, status, category, type_id, priority, created_at, last_activity_at) "
            "VALUES (?, ?, ?, 'ouvert', ?, ?, 'normale', ?, ?)",
            (guild.id, channel.id, user.id, ticket_type["name"], ticket_type["id"], now(), now()),
        )
        ticket_id = cur.lastrowid
        for label, value in answers:
            if value:
                await self.bot.db.execute(
                    "INSERT INTO ticket_answers (ticket_id, question_label, answer) VALUES (?, ?, ?)", (ticket_id, label, value[:1000])
                )

        # Fiche d'ouverture de ticket (Phase 3, design premium/sombre) — n'affecte QUE ce
        # message d'accueil, jamais TicketControlView ni les custom_id des boutons
        # persistants (ceux-ci restent inchangés pour ne rien casser après un redémarrage).
        style = design_system.CATEGORY_STYLES["tickets"]
        e = design_system.create_embed(
            title=f"{ticket_type['emoji'] or style['emoji']} {ticket_type['name']} — Ticket #{number}",
            description=ticket_type["open_message"] or f"Bonjour {user.mention}, le staff vous répondra bientôt.",
            colour=style["colour"],
            user=user,
            thumbnail=user.display_avatar.url,
            footer="SentriX",
        )
        e.add_field(name="👤 Ouvert par", value=user.mention, inline=True)
        e.add_field(name="📂 Type", value=ticket_type["name"], inline=True)
        for label, value in answers:
            if value:
                e.add_field(name=label[:256], value=helpers.truncate(value, 1024), inline=False)
        button_settings = await get_button_settings(self.bot, guild.id)
        content = user.mention
        if ticket_type["mention_staff"] and staff_role:
            content += f" {staff_role.mention}"
        # Ce message DOIT pinguer le membre et le role support : Discord refuse un
        # `content` sur un message Components V2, donc il reste un embed. Le ping
        # prime sur la banniere — c'est une exception assumee, pas un oubli.
        await channel.send(content=content, embed=e, view=TicketControlView(button_settings))

        await sx_panels.envoyer(
            interaction,
            sx_panels.Panneau(
                titre="SentriX — Ticket ouvert",
                sous_titre=f"Votre ticket est prêt dans {channel.mention}.",
                kind="success",
                sections=[
                    sx_panels.Section(
                        "Votre ticket",
                        [
                            sx_panels.Ligne("Salon", channel.mention),
                            sx_panels.Ligne("Numéro", f"#{number}"),
                            sx_panels.Ligne("Type", str(ticket_type["name"])),
                        ],
                    ),
                    sx_panels.Section(
                        "Ce qui suit",
                        [
                            sx_panels.Ligne(
                                "Le support a été prévenu",
                                "Décrivez votre demande dans le salon, un membre du staff répondra",
                            ),
                            sx_panels.Ligne(
                                "Fermeture",
                                "Le bouton **Fermer** du salon met fin au ticket",
                                indice="Un transcript peut vous être envoyé en message privé.",
                            ),
                        ],
                    ),
                ],
                pied="SentriX • Tickets",
            ),
            ephemere=True,
        )

        log_e = embeds.log_entry(
            "🎫 Ticket ouvert", 0x5865F2, cible=user,
            extra={"📂 Type": ticket_type["name"], "📌 Salon": channel.mention, "🔢 Numéro": f"#{number}"},
        )
        await self.log_action(guild, log_e, ticket_type["log_channel_id"])

    # ---------------------------------------------------------------- BOUTONS STAFF

    async def handle_control_button(self, interaction: discord.Interaction, key: str):
        # Log de diagnostic — voir en-tête du fichier : trace complète de chaque clic sur un
        # bouton de contrôle de ticket, pour retrouver précisément quelle interaction a
        # échoué (custom_id, utilisateur, serveur, ticket, durée) sans avoir à deviner.
        started = time.monotonic()
        guild_id = interaction.guild.id if interaction.guild else None
        user_id = interaction.user.id if interaction.user else None
        try:
            ticket = await self.get_ticket_by_channel(interaction.channel.id)
            if not ticket:
                return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error("Ce salon n'est pas (ou plus) un ticket.")), ephemere=True)
            if ticket["status"] != "ouvert" and key != "close":
                return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Ce ticket est fermé.')), ephemere=True)

            settings = await get_button_settings(self.bot, interaction.guild.id)
            cfg = settings.get(key, {})
            role_id = cfg.get("role_id")
            if role_id:
                role = interaction.guild.get_role(role_id)
                member = interaction.user
                allowed = (
                    (role and role in getattr(member, "roles", []))
                    or member.guild_permissions.manage_channels
                    or member.id == interaction.guild.owner_id
                )
                if not allowed:
                    return await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error(f"Seuls les membres avec le rôle {(role.mention if role else 'configuré')} peuvent utiliser ce bouton.")), ephemere=True)

            await self.touch_activity(ticket["id"])
            handler = getattr(self, f"btn_{key}", None)
            if handler:
                await handler(interaction, ticket)
            else:
                logger.warning(
                    "Bouton ticket_ctrl_%s cliqué mais aucun handler btn_%s n'existe (guild=%s, user=%s).",
                    key, key, guild_id, user_id,
                )
                if not interaction.response.is_done():
                    await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error("Ce bouton n'est pas encore relié à une action.")), ephemere=True)
        except discord.InteractionResponded:
            # Déjà répondu ailleurs (ex: double clic très rapide) — on ne relance jamais une
            # deuxième réponse dessus, Discord le refuserait de toute façon.
            logger.info("Interaction déjà répondue pour ticket_ctrl_%s (guild=%s, user=%s).", key, guild_id, user_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
            logger.error("Erreur Discord sur ticket_ctrl_%s (guild=%s, user=%s) : %s", key, guild_id, user_id, e)
            if not interaction.response.is_done():
                try:
                    await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Une erreur Discord est survenue. Réessayez dans un instant.')), ephemere=True)
                except discord.HTTPException:
                    pass
        except Exception:
            # Ne JAMAIS laisser une exception inattendue empêcher toute réponse à
            # l'interaction : c'est exactement ce qui produit "L'application ne répond
            # plus" côté membre, sans aucune erreur visible côté staff.
            logger.error(
                "Exception non gérée sur ticket_ctrl_%s (guild=%s, user=%s, channel=%s) :\n%s",
                key, guild_id, user_id, getattr(interaction.channel, "id", None), traceback.format_exc(),
            )
            if not interaction.response.is_done():
                try:
                    await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.error('Une erreur inattendue est survenue. Le staff a été informé.')), ephemere=True)
                except discord.HTTPException:
                    pass
        finally:
            elapsed = time.monotonic() - started
            if elapsed > 2.0:
                logger.warning("Bouton ticket_ctrl_%s traité en %.2fs (guild=%s, user=%s) — proche ou au-delà du délai Discord.", key, elapsed, guild_id, user_id)
            else:
                logger.info("Bouton ticket_ctrl_%s traité en %.2fs (guild=%s, user=%s).", key, elapsed, guild_id, user_id)

    async def touch_activity(self, ticket_id: int):
        await self.bot.db.execute("UPDATE tickets SET last_activity_at = ? WHERE id = ?", (now(), ticket_id))

    async def btn_claim(self, interaction: discord.Interaction, ticket):
        await self.bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE id = ?", (interaction.user.id, ticket["id"]))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success(f'🙋 {interaction.user.mention} a pris en charge ce ticket.')))

    async def btn_unclaim(self, interaction: discord.Interaction, ticket):
        await self.bot.db.execute("UPDATE tickets SET claimed_by = NULL WHERE id = ?", (ticket["id"],))
        await sx_panels.envoyer(interaction.response, sx_panels.depuis_embed(embeds.success('↩️ Prise en charge annulée.')))

    async def btn_add(self, interaction: discord.Interaction, ticket):
        select = discord.ui.UserSelect(placeholder="➕ Choisir le membre à ajouter")
        view = discord.ui.View(timeout=60)

        async def cb(inter: discord.Interaction):
            member = select.values[0]
            await inter.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success(f'➕ {member.mention} a été ajouté au ticket.')))

        select.callback = cb
        view.add_item(select)
        await interaction.response.send_message("Qui voulez-vous ajouter à ce ticket ?", view=view, ephemeral=True)

    async def btn_remove(self, interaction: discord.Interaction, ticket):
        select = discord.ui.UserSelect(placeholder="➖ Choisir le membre à retirer")
        view = discord.ui.View(timeout=60)

        async def cb(inter: discord.Interaction):
            member = select.values[0]
            if member.id == ticket["user_id"]:
                return await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.error('Impossible de retirer le créateur du ticket.')), ephemere=True)
            await inter.channel.set_permissions(member, overwrite=None)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success(f'➖ {member.mention} a été retiré du ticket.')))

        select.callback = cb
        view.add_item(select)
        await interaction.response.send_message("Qui voulez-vous retirer de ce ticket ?", view=view, ephemeral=True)

    async def btn_rename(self, interaction: discord.Interaction, ticket):
        await interaction.response.send_modal(TicketRenameModal(self, interaction.channel))

    async def btn_transfer(self, interaction: discord.Interaction, ticket):
        select = discord.ui.UserSelect(placeholder="🔀 Transférer à un membre du staff")
        view = discord.ui.View(timeout=60)

        async def cb(inter: discord.Interaction):
            member = select.values[0]
            await self.bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE id = ?", (member.id, ticket["id"]))
            await inter.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success(f'🔀 Ticket transféré à {member.mention}.')))

        select.callback = cb
        view.add_item(select)
        await interaction.response.send_message("À quel membre du staff transférer ce ticket ?", view=view, ephemeral=True)

    async def btn_note(self, interaction: discord.Interaction, ticket):
        await interaction.response.send_modal(TicketNoteModal(self, ticket["id"]))

    async def btn_bump(self, interaction: discord.Interaction, ticket):
        owner = interaction.guild.get_member(ticket["user_id"])
        await interaction.response.send_message(f"🔔 {owner.mention if owner else 'Utilisateur'}, rappel : nous attendons votre réponse sur ce ticket.")

    async def btn_close(self, interaction: discord.Interaction, ticket):
        await interaction.response.send_modal(CloseReasonModal(self, ticket["id"]))

    # ---------------------------------------------------------------- FERMETURE

    async def _fetch_transcript_text(self, channel: discord.TextChannel) -> str:
        lines = []
        async for msg in channel.history(limit=2000, oldest_first=True):
            lines.append(f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author} ({msg.author.id}): {msg.content}")
            for att in msg.attachments:
                lines.append(f"    [pièce jointe] {att.url}")
        return "\n".join(lines) or "Aucun message."

    def _transcript_file(self, channel: discord.TextChannel, text: str) -> discord.File:
        # Un discord.File ne peut servir qu'à UN SEUL envoi (son contenu est "consommé"
        # après le premier .send()) : on doit donc en recréer un pour chaque destinataire,
        # mais à partir du même texte déjà récupéré, plutôt que de relire tout l'historique.
        return discord.File(io.BytesIO(text.encode("utf-8")), filename=f"transcript-{channel.name}.txt")

    async def generate_transcript(self, channel: discord.TextChannel) -> discord.File:
        text = await self._fetch_transcript_text(channel)
        return self._transcript_file(channel, text)

    async def close_ticket(self, interaction: discord.Interaction, ticket_id: int, reason: str):
        ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            return
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not channel:
            return
        ticket_type = await self.get_type(ticket["type_id"]) if ticket["type_id"] else None
        conf = await self.bot.db.get_guild_config(interaction.guild.id)

        await self.bot.db.execute(
            "UPDATE tickets SET status = 'ferme', closed_at = ?, locked = 1 WHERE id = ?", (now(), ticket_id)
        )
        owner = interaction.guild.get_member(ticket["user_id"])
        if owner:
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            try:
                await channel.set_permissions(owner, overwrite=overwrite)
            except discord.HTTPException:
                pass

        # BUG CORRIGÉ (perf) : la transcription était relue 3 fois de suite (message du
        # salon, log, DM) via 3 lectures complètes et séparées de l'historique du salon —
        # jusqu'à 3x plus d'appels à l'API Discord que nécessaire à CHAQUE fermeture de
        # ticket. Sur un serveur de 200k membres où les tickets se ferment en continu, ça
        # représente une charge inutile. On ne lit l'historique qu'une seule fois maintenant.
        try:
            transcript_text = await self._fetch_transcript_text(channel)
        except discord.HTTPException:
            transcript_text = "Transcription indisponible (erreur lors de la lecture du salon)."

        delay = (conf["ticket_delete_delay"] if conf else 30) or 30

        # BUG CORRIGÉ (fiabilité) : cette suppression automatique est maintenant programmée
        # AVANT les envois qui suivent (message, log, DM), pas après. Avant, si l'envoi du DM
        # de transcription échouait pour une raison autre qu'un DM fermé (erreur réseau,
        # timeout Discord...), l'exception non rattrapée empêchait ce create_task de
        # s'exécuter : le salon du ticket restait alors ouvert indéfiniment, sans suppression
        # automatique et sans aucune erreur visible pour le staff.
        asyncio.create_task(self._auto_delete(channel, ticket_id, delay))

        try:
            await channel.send(embed=embeds.warning(
                f"🔒 Ticket fermé par {interaction.user.mention}.\nRaison : {reason}\n\n"
                f"Suppression automatique dans **{helpers.format_duration(delay)}**."
            ), file=self._transcript_file(channel, transcript_text))
        except discord.HTTPException:
            pass

        log_e = embeds.log_entry(
            "🔒 Ticket fermé", 0xED4245, cible=owner or ticket["user_id"], acteur=interaction.user, raison=reason,
            extra={"📌 Salon": channel.mention},
        )
        log_channel_id = ticket_type["log_channel_id"] if ticket_type else None
        target_channel = channel.guild.get_channel(log_channel_id) if log_channel_id else None
        if not target_channel:
            log_conf = await self.bot.db.get_guild_config(interaction.guild.id)
            fallback_id = log_conf["ticket_log_channel"] if log_conf else None
            target_channel = channel.guild.get_channel(fallback_id) if fallback_id else None
        if target_channel:
            try:
                await target_channel.send(embed=log_e, file=self._transcript_file(channel, transcript_text))
            except discord.HTTPException:
                await helpers.send_log(self.bot, interaction.guild, "moderation", log_e)
        else:
            await helpers.send_log(self.bot, interaction.guild, "moderation", log_e)

        if owner and (not conf or conf["ticket_transcript_dm"]):
            try:
                await owner.send(
                    embed=embeds.info(f"Voici la transcription de votre ticket sur **{interaction.guild.name}**."),
                    file=self._transcript_file(channel, transcript_text),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            if not conf or conf["ticket_rating_enabled"]:
                try:
                    await owner.send(
                        content="Pouvez-vous noter le support reçu ?", view=RatingView(self, ticket_id),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def _auto_delete(self, channel: discord.TextChannel, ticket_id: int, delay: int):
        await asyncio.sleep(delay)
        current = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not current or current["status"] != "ferme":
            return  # rouvert entre-temps (+ticket-reopen), on annule la suppression
        await self.bot.db.execute("UPDATE tickets SET status = 'supprime' WHERE id = ?", (ticket_id,))
        try:
            await channel.delete(reason="Ticket fermé : suppression automatique.")
        except discord.HTTPException:
            pass

    # ---------------------------------------------------------------- FERMETURE AUTOMATIQUE (INACTIVITÉ)

    @tasks.loop(minutes=15)
    async def check_autoclose(self):
        rows = await self.bot.db.fetchall(
            "SELECT t.*, tt.autoclose_hours, tt.log_channel_id FROM tickets t "
            "JOIN ticket_types tt ON tt.id = t.type_id "
            "WHERE t.status = 'ouvert' AND tt.autoclose_hours > 0"
        )
        for row in rows:
            if row["last_activity_at"] is None:
                continue
            elapsed = now() - row["last_activity_at"]
            if elapsed < row["autoclose_hours"] * 3600:
                continue
            guild = self.bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            if not guild or not channel:
                await self.bot.db.execute("UPDATE tickets SET status = 'supprime' WHERE id = ?", (row["id"],))
                continue
            await self.bot.db.execute("UPDATE tickets SET status = 'ferme', closed_at = ?, locked = 1 WHERE id = ?", (now(), row["id"]))
            transcript = await self.generate_transcript(channel)
            await channel.send(embed=embeds.warning("🔒 Ticket fermé automatiquement pour inactivité."), file=transcript)
            e = embeds.log_entry("🔒 Fermeture automatique (inactivité)", 0xFEE75C, extra={"📌 Salon": channel.name})
            await self.log_action(guild, e, row["log_channel_id"])
            conf = await self.bot.db.get_guild_config(guild.id)
            delay = (conf["ticket_delete_delay"] if conf else 30) or 30
            asyncio.create_task(self._auto_delete(channel, row["id"], delay))

    @check_autoclose.before_loop
    async def before_check_autoclose(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="ticket-reopen", description="Rouvrir un ticket fermé (avant sa suppression automatique).", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_reopen(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error("Ce salon n'est pas un ticket.")))
        if ticket["status"] != "ferme":
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error("Ce ticket n'est pas fermé.")))
        await self.bot.db.execute("UPDATE tickets SET status = 'ouvert', closed_at = NULL, locked = 0, last_activity_at = ? WHERE id = ?", (now(), ticket["id"]))
        owner = ctx.guild.get_member(ticket["user_id"])
        if owner:
            overwrite = ctx.channel.overwrites_for(owner)
            overwrite.send_messages = True
            await ctx.channel.set_permissions(owner, overwrite=overwrite)
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success('🔓 Le ticket a été rouvert.')))

    # ---------------------------------------------------------------- COMMANDES : OUVERTURE (MEMBRES)

    @commands.hybrid_command(name="ticket", description="Ouvrir un ticket de support.")
    async def ticket_cmd(self, ctx: commands.Context):
        """Point d'entrée pour un membre qui veut ouvrir un ticket sans passer par un panel
        déjà envoyé dans un salon. Tout vient de la base de données (panels/types actifs
        sur CE serveur) — rien n'est jamais écrit en dur, exactement comme les panels."""
        if not ctx.guild:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))

        panels = await self.bot.db.fetchall(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? AND enabled = 1", (ctx.guild.id,)
        )
        available = []
        for p in panels:
            types = await self.get_panel_types(p["id"])
            if types:
                available.append((p, types))

        if not available:
            # Impasse frequente : le membre veut de l'aide et tombe sur un refus.
            # Le panneau dit qui peut debloquer la situation et avec quoi.
            return await sx_panels.envoyer(
                ctx,
                sx_panels.Panneau(
                    titre="SentriX — Tickets",
                    sous_titre="Aucun panel de ticket n'est encore configuré sur ce serveur.",
                    kind="warning",
                    sections=[
                        sx_panels.Section(
                            "Ce que cela veut dire",
                            [
                                sx_panels.Ligne(
                                    "Pour vous",
                                    "Il n'y a pas encore de canal de support à ouvrir",
                                ),
                                sx_panels.Ligne(
                                    "Ce n'est pas une erreur",
                                    "Rien n'a échoué : la fonctionnalité n'est simplement pas activée",
                                ),
                            ],
                        ),
                        sx_panels.Section(
                            "Pour le staff",
                            [
                                sx_panels.Ligne("`+ticketsetup`", "Configuration guidée, la plus simple"),
                                sx_panels.Ligne("`+ticketpanel create`", "Création manuelle d'un panel"),
                            ],
                        ),
                    ],
                    pied="SentriX • Tickets",
                ),
                ephemere=bool(ctx.interaction),
            )

        if len(available) == 1:
            panel, types = available[0]
            return await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(self.build_panel_embed(panel)), TicketPanelView(panel, types)), ephemeral=True if ctx.interaction else False)

        # Plusieurs panels actifs sur ce serveur : on laisse d'abord choisir la catégorie
        # (les options du menu viennent toutes de la DB, jamais du code).
        e = embeds.neutral("🎫 Ouvrir un ticket", "Sélectionnez la catégorie correspondant à votre demande.")
        view = discord.ui.View(timeout=180)
        options = [
            discord.SelectOption(label=p["name"][:100], value=str(p["id"]), description=(p["description"] or "")[:100] or None)
            for p, _t in available[:25]
        ]
        select = discord.ui.Select(placeholder="Choisissez une catégorie", options=options)

        async def on_pick(inter: discord.Interaction):
            panel_id = int(select.values[0])
            panel, types = next((p, t) for p, t in available if p["id"] == panel_id)
            await inter.response.edit_message(embed=self.build_panel_embed(panel), view=TicketPanelView(panel, types))

        select.callback = on_pick
        view.add_item(select)
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), view), ephemeral=True if ctx.interaction else False)

    # ---------------------------------------------------------------- COMMANDES : HUB

    @commands.hybrid_command(name="ticketsetup", description="Ouvrir le menu de configuration complet du système de tickets.")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketsetup(self, ctx: commands.Context):
        e = embeds.brand(
            "🎫 Configuration des tickets",
            "Menu privé — utilisez les boutons ci-dessous pour gérer vos panels, types de tickets et boutons staff.\n\n"
            "Pour un contrôle plus fin, les commandes `+ticketpanel`, `+tickettype` et `+ticketform` sont aussi disponibles.",
        )
        panels = await self.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE guild_id = ?", (ctx.guild.id,))
        types = await self.bot.db.fetchall("SELECT * FROM ticket_types WHERE guild_id = ?", (ctx.guild.id,))
        open_tickets = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (ctx.guild.id,))
        e.add_field(name="📋 Panels", value=str(len(panels)), inline=True)
        e.add_field(name="🎫 Types de tickets", value=str(len(types)), inline=True)
        e.add_field(name="📬 Tickets ouverts", value=str(open_tickets["c"]), inline=True)
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), TicketSetupHubView(self, ctx.author.id)), ephemeral=True if ctx.interaction else False)

    # ---------------------------------------------------------------- COMMANDES : PANELS

    @commands.hybrid_group(name="ticketpanel", description="Gérer les panels de tickets.")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel(self, ctx: commands.Context):
        await self.list_panels(ctx)

    async def list_panels(self, ctx_or_interaction):
        guild = ctx_or_interaction.guild
        panels = await self.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE guild_id = ?", (guild.id,))
        e = embeds.neutral("📋 Panels de tickets")
        if not panels:
            e.description = "Aucun panel créé. Utilisez `+ticketpanel create <nom>` pour commencer."
        else:
            for p in panels:
                types_count = await self.bot.db.fetchone("SELECT COUNT(*) c FROM ticket_types WHERE panel_id = ?", (p["id"],))
                channel = guild.get_channel(p["channel_id"]) if p["channel_id"] else None
                state = "● Actif" if p["enabled"] else "⏸️ Désactivé"
                e.add_field(
                    name=f"{p['name']} (#{p['id']})",
                    value=f"{state} • {types_count['c']} type(s) • Salon : {channel.mention if channel else 'Non défini'}",
                    inline=False,
                )
        await self._reply(ctx_or_interaction, e)

    async def _reply(self, target, embed, view=None):
        """Reponse des commandes de tickets.

        Sans vue, l'embed devient un panneau : ses champs se transforment en
        sections. Avec une vue classique, il reste un embed — un message
        Components V2 ne peut pas porter de View, et la vue sert ici a agir sur
        le ticket. Perdre le bouton pour gagner une banniere serait un mauvais
        echange.
        """
        if view is not None:
            if isinstance(target, discord.Interaction):
                if target.response.is_done():
                    return await target.followup.send(embed=embed, view=view, ephemeral=True)
                return await target.response.send_message(embed=embed, view=view, ephemeral=True)
            return await target.send(embed=embed, view=view)

        panneau = sx_panels.depuis_embed(embed)
        return await sx_panels.envoyer(
            target, panneau, ephemere=isinstance(target, discord.Interaction)
        )

    @ticketpanel.command(name="create", description="Créer un nouveau panel de tickets.")
    @app_commands.describe(nom="Le nom interne du panel (pour le retrouver dans les autres commandes)")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_create(self, ctx: commands.Context, *, nom: str):
        if await self.get_panel_by_name(ctx.guild.id, nom):
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Un panel nommé « {nom} » existe déjà.')))
        panel_id = await self.create_panel(ctx.guild.id, nom)
        panel = await self.get_panel(panel_id)
        e = embeds.success(f"Panel **{nom}** créé (#{panel_id}). Configurez-le ci-dessous.")
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), PanelEditView(self, panel_id, ctx.author.id)))

    @ticketpanel.command(name="edit", description="Modifier un panel existant.")
    @app_commands.describe(nom="Le nom du panel à modifier")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_edit(self, ctx: commands.Context, *, nom: str):
        panel = await self.get_panel_by_name(ctx.guild.id, nom)
        if not panel:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {nom} ».')))
        e = embeds.neutral(f"⚙️ Modifier le panel « {panel['name']} »", "Choisissez ce que vous voulez modifier.")
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), PanelEditView(self, panel['id'], ctx.author.id)))

    @ticketpanel.command(name="delete", description="Supprimer un panel (et ses types de tickets).")
    @app_commands.describe(nom="Le nom du panel à supprimer")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_delete(self, ctx: commands.Context, *, nom: str):
        panel = await self.get_panel_by_name(ctx.guild.id, nom)
        if not panel:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {nom} ».')))
        types = await self.get_panel_types(panel["id"])
        view = helpers.ConfirmView(ctx.author.id)
        msg = await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(embeds.warning(f"Supprimer le panel **{panel['name']}** et ses **{len(types)}** type(s) de ticket associés ?")), view))
        await view.wait()
        if not view.value:
            return await msg.edit(embed=embeds.error("Suppression annulée."), view=None)
        type_ids = [t["id"] for t in types]
        for tid in type_ids:
            await self.bot.db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id = ?", (tid,))
        await self.bot.db.execute("DELETE FROM ticket_types WHERE panel_id = ?", (panel["id"],))
        await self.bot.db.execute("DELETE FROM ticket_panels_v2 WHERE id = ?", (panel["id"],))
        await msg.edit(embed=embeds.success(f"Panel **{panel['name']}** supprimé."), view=None)

    @ticketpanel.command(name="list", description="Lister tous les panels du serveur.")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_list(self, ctx: commands.Context):
        await self.list_panels(ctx)

    @ticketpanel.command(name="preview", description="Prévisualiser un panel (visible uniquement par vous).")
    @app_commands.describe(nom="Le nom du panel à prévisualiser")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_preview(self, ctx: commands.Context, *, nom: str):
        panel = await self.get_panel_by_name(ctx.guild.id, nom)
        if not panel:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {nom} ».')))
        types = await self.get_panel_types(panel["id"])
        if not types:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.warning("Ce panel n'a aucun type de ticket.")))
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(self.build_panel_embed(panel)), TicketPanelView(panel, types)), ephemeral=True if ctx.interaction else False)

    @ticketpanel.command(name="send", description="Envoyer (ou mettre à jour) un panel dans son salon configuré.")
    @app_commands.describe(nom="Le nom du panel à envoyer")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_send(self, ctx: commands.Context, *, nom: str):
        panel = await self.get_panel_by_name(ctx.guild.id, nom)
        if not panel:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {nom} ».')))
        if ctx.interaction:
            await self.send_panel(ctx.interaction, panel["id"])
        else:
            if not panel["channel_id"]:
                return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error("Choisissez d'abord un salon via `+ticketpanel edit`.")))
            types = await self.get_panel_types(panel["id"])
            if not types:
                return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error("Ce panel n'a aucun type de ticket.")))
            channel = ctx.guild.get_channel(panel["channel_id"])
            msg = await channel.send(embed=self.build_panel_embed(panel), view=TicketPanelView(panel, types))
            await self.bot.db.execute("UPDATE ticket_panels_v2 SET message_id = ? WHERE id = ?", (msg.id, panel["id"]))
            await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(f'📤 Panel envoyé dans {channel.mention}.')))

    @ticketpanel.command(name="duplicate", description="Dupliquer un panel existant (avec ses types de tickets).")
    @app_commands.describe(nom="Le nom du panel à dupliquer", nouveau_nom="Le nom du panel dupliqué")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_duplicate(self, ctx: commands.Context, nom: str, *, nouveau_nom: str):
        panel = await self.get_panel_by_name(ctx.guild.id, nom)
        if not panel:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {nom} ».')))
        if await self.get_panel_by_name(ctx.guild.id, nouveau_nom):
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Un panel nommé « {nouveau_nom} » existe déjà.')))
        cur = await self.bot.db.execute(
            "INSERT INTO ticket_panels_v2 (guild_id, name, title, description, color, image_url, thumbnail_url, footer_text, style, max_per_member, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ctx.guild.id, nouveau_nom, panel["title"], panel["description"], panel["color"], panel["image_url"],
             panel["thumbnail_url"], panel["footer_text"], panel["style"], panel["max_per_member"], now()),
        )
        new_panel_id = cur.lastrowid
        types = await self.get_panel_types(panel["id"])
        for t in types:
            cur2 = await self.bot.db.execute(
                "INSERT INTO ticket_types (panel_id, guild_id, name, description, emoji, button_label, button_style, staff_role_id, "
                "category_id, name_format, open_message, max_per_member, autoclose_hours, log_channel_id, mention_staff, use_form, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_panel_id, ctx.guild.id, t["name"], t["description"], t["emoji"], t["button_label"], t["button_style"],
                 t["staff_role_id"], t["category_id"], t["name_format"], t["open_message"], t["max_per_member"],
                 t["autoclose_hours"], t["log_channel_id"], t["mention_staff"], t["use_form"], t["position"]),
            )
            new_type_id = cur2.lastrowid
            questions = await self.bot.db.fetchall("SELECT * FROM ticket_form_questions WHERE ticket_type_id = ?", (t["id"],))
            for q in questions:
                await self.bot.db.execute(
                    "INSERT INTO ticket_form_questions (ticket_type_id, position, label, placeholder, style, required, min_length, max_length) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_type_id, q["position"], q["label"], q["placeholder"], q["style"], q["required"], q["min_length"], q["max_length"]),
                )
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(f'Panel **{nom}** dupliqué en **{nouveau_nom}** (#{new_panel_id}) avec {len(types)} type(s) de ticket.')))

    @commands.hybrid_command(name="ticketpanel-toggle", description="Activer ou désactiver un panel.", with_app_command=False)
    @app_commands.describe(nom="Le nom du panel")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketpanel_toggle(self, ctx: commands.Context, *, nom: str):
        panel = await self.get_panel_by_name(ctx.guild.id, nom)
        if not panel:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {nom} ».')))
        new_val = 0 if panel["enabled"] else 1
        await self.bot.db.execute("UPDATE ticket_panels_v2 SET enabled = ? WHERE id = ?", (new_val, panel["id"]))
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(f"Panel **{nom}** {('activé ●' if new_val else 'désactivé ⏸️')}.")))

    # ---------------------------------------------------------------- COMMANDES : TYPES

    @commands.hybrid_group(name="tickettype", description="Gérer les types de tickets.")
    @checks.is_owner_or_admin_for("tickets")
    async def tickettype(self, ctx: commands.Context):
        await self.list_types(ctx, panel_id=None)

    async def list_types(self, ctx_or_interaction, panel_id: int | None):
        guild = ctx_or_interaction.guild
        if panel_id:
            types = await self.get_panel_types(panel_id)
        else:
            types = await self.bot.db.fetchall("SELECT * FROM ticket_types WHERE guild_id = ? ORDER BY panel_id, position", (guild.id,))
        e = embeds.neutral("🎫 Types de tickets")
        if not types:
            e.description = "Aucun type de ticket créé. Utilisez `+tickettype add <panel> <nom>` pour commencer."
        else:
            for t in types:
                staff = f"<@&{t['staff_role_id']}>" if t["staff_role_id"] else "Aucun"
                e.add_field(
                    name=f"{t['emoji'] or '🎫'} {t['name']} (#{t['id']})",
                    value=f"Staff : {staff} • Formulaire : {'Oui' if t['use_form'] else 'Non'} • Max/membre : {t['max_per_member']}",
                    inline=False,
                )
        await self._reply(ctx_or_interaction, e)

    @tickettype.command(name="add", description="Ajouter un type de ticket à un panel.")
    @app_commands.describe(panel="Le nom du panel", nom="Le nom de ce type de ticket (ex: Support)")
    @checks.is_owner_or_admin_for("tickets")
    async def tickettype_add(self, ctx: commands.Context, panel: str, *, nom: str):
        panel_row = await self.get_panel_by_name(ctx.guild.id, panel)
        if not panel_row:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun panel nommé « {panel} ».')))
        if await self.get_type_by_name(ctx.guild.id, nom):
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Un type nommé « {nom} » existe déjà sur ce serveur.')))
        type_id = await self.add_type(ctx.guild.id, panel_row["id"], nom)
        e = embeds.success(f"Type **{nom}** créé sur le panel « {panel} » (#{type_id}). Configurez-le ci-dessous.")
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), TypeEditView(self, type_id, ctx.author.id)))

    @tickettype.command(name="edit", description="Modifier un type de ticket.")
    @app_commands.describe(nom="Le nom du type de ticket à modifier")
    @checks.is_owner_or_admin_for("tickets")
    async def tickettype_edit(self, ctx: commands.Context, *, nom: str):
        t = await self.get_type_by_name(ctx.guild.id, nom)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {nom} ».')))
        e = embeds.neutral(f"⚙️ Modifier le type « {t['name']} »", "Choisissez ce que vous voulez modifier.")
        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), TypeEditView(self, t['id'], ctx.author.id)))

    @tickettype.command(name="remove", description="Supprimer un type de ticket.")
    @app_commands.describe(nom="Le nom du type de ticket à supprimer")
    @checks.is_owner_or_admin_for("tickets")
    async def tickettype_remove(self, ctx: commands.Context, *, nom: str):
        t = await self.get_type_by_name(ctx.guild.id, nom)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {nom} ».')))
        view = helpers.ConfirmView(ctx.author.id)
        msg = await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(embeds.warning(f"Supprimer le type **{t['name']}** et son formulaire ?")), view))
        await view.wait()
        if not view.value:
            return await msg.edit(embed=embeds.error("Suppression annulée."), view=None)
        await self.bot.db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id = ?", (t["id"],))
        await self.bot.db.execute("DELETE FROM ticket_types WHERE id = ?", (t["id"],))
        await msg.edit(embed=embeds.success(f"Type **{t['name']}** supprimé."), view=None)

    @tickettype.command(name="list", description="Lister tous les types de tickets du serveur.")
    @checks.is_owner_or_admin_for("tickets")
    async def tickettype_list(self, ctx: commands.Context):
        await self.list_types(ctx, panel_id=None)

    # ---------------------------------------------------------------- COMMANDES : FORMULAIRES

    @commands.hybrid_group(name="ticketform", description="Gérer le formulaire d'un type de ticket.")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketform(self, ctx: commands.Context):
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.info('Utilisez `+ticketform add <type>`, `+ticketform edit <type> <question>` ou `+ticketform remove <type> <question>`.')))

    @ticketform.command(name="add", description="Ajouter une question au formulaire d'un type de ticket (max 5).")
    @app_commands.describe(type_ticket="Le nom du type de ticket")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketform_add(self, ctx: commands.Context, *, type_ticket: str):
        t = await self.get_type_by_name(ctx.guild.id, type_ticket)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {type_ticket} ».')))
        if ctx.interaction:
            await ctx.interaction.response.send_modal(FormQuestionModal(self, t["id"]))
        else:
            await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.warning('Utilisez la version slash `/ticketform add` pour ouvrir le formulaire (obligatoire pour un modal Discord).')))

    @ticketform.command(name="edit", description="Modifier une question existante.")
    @app_commands.describe(type_ticket="Le nom du type de ticket", position="La position de la question (1, 2, 3...)")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketform_edit(self, ctx: commands.Context, type_ticket: str, position: int):
        t = await self.get_type_by_name(ctx.guild.id, type_ticket)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {type_ticket} ».')))
        questions = await self.bot.db.fetchall("SELECT * FROM ticket_form_questions WHERE ticket_type_id = ? ORDER BY position", (t["id"],))
        if position < 1 or position > len(questions):
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Position invalide (ce type a {len(questions)} question(s)).')))
        question = questions[position - 1]
        if ctx.interaction:
            await ctx.interaction.response.send_modal(FormQuestionModal(self, t["id"], question=question))
        else:
            await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.warning('Utilisez la version slash `/ticketform edit` pour ouvrir le formulaire (obligatoire pour un modal Discord).')))

    @ticketform.command(name="remove", description="Supprimer une question du formulaire.")
    @app_commands.describe(type_ticket="Le nom du type de ticket", position="La position de la question (1, 2, 3...)")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketform_remove(self, ctx: commands.Context, type_ticket: str, position: int):
        t = await self.get_type_by_name(ctx.guild.id, type_ticket)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {type_ticket} ».')))
        questions = await self.bot.db.fetchall("SELECT * FROM ticket_form_questions WHERE ticket_type_id = ? ORDER BY position", (t["id"],))
        if position < 1 or position > len(questions):
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Position invalide (ce type a {len(questions)} question(s)).')))
        question = questions[position - 1]
        await self.bot.db.execute("DELETE FROM ticket_form_questions WHERE id = ?", (question["id"],))
        remaining = await self.bot.db.fetchall("SELECT * FROM ticket_form_questions WHERE ticket_type_id = ? ORDER BY position", (t["id"],))
        for i, q in enumerate(remaining):
            await self.bot.db.execute("UPDATE ticket_form_questions SET position = ? WHERE id = ?", (i, q["id"]))
        if not remaining:
            await self.bot.db.execute("UPDATE ticket_types SET use_form = 0 WHERE id = ?", (t["id"],))
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(f"Question « {question['label']} » supprimée.")))

    # ---------------------------------------------------------------- RÉGLAGES RAPIDES

    @commands.hybrid_command(name="ticketconfig", description="Réglages généraux du système de tickets (boutons, transcript, notes).", with_app_command=False)
    @checks.is_owner_or_admin_for("tickets")
    async def ticketconfig(self, ctx: commands.Context):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        e = embeds.neutral("⚙️ Réglages généraux des tickets")
        e.add_field(name="Délai avant suppression après fermeture", value=helpers.format_duration(conf["ticket_delete_delay"] or 30), inline=True)
        e.add_field(name="Transcript envoyé en DM au membre", value="Oui" if conf["ticket_transcript_dm"] else "Non", inline=True)
        e.add_field(name="Note de satisfaction demandée", value="Oui" if conf["ticket_rating_enabled"] else "Non", inline=True)
        e.description = "Utilisez les boutons ci-dessous pour changer ces réglages, ou `+ticketsetup` pour gérer les panels et boutons staff."
        view = discord.ui.View(timeout=180)

        toggle_dm = discord.ui.Button(label="Transcript DM on/off", style=discord.ButtonStyle.secondary)

        async def dm_cb(inter: discord.Interaction):
            c = await self.bot.db.get_guild_config(ctx.guild.id)
            await self.bot.db.set_guild_config(ctx.guild.id, "ticket_transcript_dm", 0 if c["ticket_transcript_dm"] else 1)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success('Réglage mis à jour.')), ephemere=True)

        toggle_dm.callback = dm_cb
        view.add_item(toggle_dm)

        toggle_rating = discord.ui.Button(label="Note de satisfaction on/off", style=discord.ButtonStyle.secondary)

        async def rating_cb(inter: discord.Interaction):
            c = await self.bot.db.get_guild_config(ctx.guild.id)
            await self.bot.db.set_guild_config(ctx.guild.id, "ticket_rating_enabled", 0 if c["ticket_rating_enabled"] else 1)
            await sx_panels.envoyer(inter.response, sx_panels.depuis_embed(embeds.success('Réglage mis à jour.')), ephemere=True)

        toggle_rating.callback = rating_cb
        view.add_item(toggle_rating)

        await sx_panels.envoyer(ctx, sx_panels.avec_composants(sx_panels.depuis_embed(e), view))

    @commands.hybrid_command(name="ticketlogs", description="Définir rapidement le salon de logs d'un type de ticket.", with_app_command=False)
    @app_commands.describe(type_ticket="Le nom du type de ticket", salon="Le salon de logs")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketlogs(self, ctx: commands.Context, type_ticket: str, salon: discord.TextChannel):
        t = await self.get_type_by_name(ctx.guild.id, type_ticket)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {type_ticket} ».')))
        await self.bot.db.execute("UPDATE ticket_types SET log_channel_id = ? WHERE id = ?", (salon.id, t["id"]))
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(f"Logs du type **{t['name']}** définis sur {salon.mention}.")))

    @commands.hybrid_command(name="ticketlimit", description="Définir rapidement la limite de tickets par membre d'un type.", with_app_command=False)
    @app_commands.describe(type_ticket="Le nom du type de ticket", nombre="Nombre maximum de tickets ouverts simultanément par membre")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketlimit(self, ctx: commands.Context, type_ticket: str, nombre: app_commands.Range[int, 1, 20]):
        t = await self.get_type_by_name(ctx.guild.id, type_ticket)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {type_ticket} ».')))
        await self.bot.db.execute("UPDATE ticket_types SET max_per_member = ? WHERE id = ?", (nombre, t["id"]))
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(f"Limite du type **{t['name']}** définie à **{nombre}** ticket(s) par membre.")))

    @commands.hybrid_command(name="ticketautoclose", description="Définir rapidement la fermeture automatique par inactivité d'un type.", with_app_command=False)
    @app_commands.describe(type_ticket="Le nom du type de ticket", heures="Heures d'inactivité avant fermeture (0 pour désactiver)")
    @checks.is_owner_or_admin_for("tickets")
    async def ticketautoclose(self, ctx: commands.Context, type_ticket: str, heures: app_commands.Range[int, 0, 720]):
        t = await self.get_type_by_name(ctx.guild.id, type_ticket)
        if not t:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error(f'Aucun type nommé « {type_ticket} ».')))
        await self.bot.db.execute("UPDATE ticket_types SET autoclose_hours = ? WHERE id = ?", (heures, t["id"]))
        msg = f"Fermeture automatique désactivée pour **{t['name']}**." if heures == 0 else f"**{t['name']}** se fermera après **{heures}h** d'inactivité (sans prise en charge, note ou relance)."
        await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.success(msg)))

    @commands.hybrid_command(name="tickettranscript", description="Générer la transcription de ce ticket sans le fermer.")
    @checks.has_permission_or_modrole("manage_channels")
    async def tickettranscript(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await sx_panels.envoyer(ctx, sx_panels.depuis_embed(embeds.error("Ce salon n'est pas un ticket.")))
        await ctx.defer() if ctx.interaction else None
        file = await self.generate_transcript(ctx.channel)
        await ctx.send(embed=embeds.success("📄 Transcription générée."), file=file)

    async def send_stats(self, ctx_or_interaction):
        guild = ctx_or_interaction.guild
        total = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ?", (guild.id,))
        open_ = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (guild.id,))
        closed = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND status = 'ferme'", (guild.id,))
        avg_rating = await self.bot.db.fetchone("SELECT AVG(rating) a FROM tickets WHERE guild_id = ? AND rating IS NOT NULL", (guild.id,))
        by_type = await self.bot.db.fetchall(
            "SELECT tt.name AS name, COUNT(*) AS c FROM tickets t JOIN ticket_types tt ON tt.id = t.type_id "
            "WHERE t.guild_id = ? GROUP BY tt.name ORDER BY c DESC LIMIT 10",
            (guild.id,),
        )
        e = embeds.neutral("📊 Statistiques des tickets")
        e.add_field(name="Total", value=total["c"], inline=True)
        e.add_field(name="Ouverts", value=open_["c"], inline=True)
        e.add_field(name="Fermés", value=closed["c"], inline=True)
        e.add_field(name="Note moyenne", value=f"{avg_rating['a']:.1f}/5 ⭐" if avg_rating["a"] else "N/A", inline=True)
        if by_type:
            e.add_field(name="Répartition par type", value="\n".join(f"**{r['name']}** : {r['c']}" for r in by_type), inline=False)
        await self._reply(ctx_or_interaction, e)

    @commands.hybrid_command(name="ticketstats", description="Afficher les statistiques des tickets du serveur.")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticketstats(self, ctx: commands.Context):
        await self.send_stats(ctx)


class TicketFormModal(discord.ui.Modal):
    """Formulaire présenté au membre avant l'ouverture du ticket, généré dynamiquement à
    partir des questions configurées par l'administrateur pour ce type (5 max, limite Discord)."""

    def __init__(self, cog: Tickets, ticket_type, questions: list):
        super().__init__(title=f"🎫 {ticket_type['name']}"[:45])
        self.cog = cog
        self.ticket_type = ticket_type
        self._inputs = []
        for q in questions[:5]:
            style = TEXT_STYLES.get(q["style"], discord.TextStyle.short)
            max_len = q["max_length"] or (4000 if style == discord.TextStyle.paragraph else 500)
            ti = discord.ui.TextInput(
                label=q["label"][:45],
                style=style,
                placeholder=(q["placeholder"] or "")[:100],
                required=bool(q["required"]),
                min_length=q["min_length"] or 0,
                max_length=min(max_len, 4000),
            )
            self.add_item(ti)
            self._inputs.append((q["label"], ti))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        answers = [(label, ti.value) for label, ti in self._inputs]
        await self.cog.create_ticket(interaction, self.ticket_type, answers)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
