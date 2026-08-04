"""
Cog CRÉATEUR D'EMBEDS — +embed.

Éditeur interactif complet pour construire, sauvegarder, envoyer et réutiliser des embeds
Discord professionnels sans toucher au code. Rien n'est écrit en dur : chaque modèle est
séparé par guild_id en base (table embed_templates), exactement comme les panels de tickets.

Commandes :
+embed                          — ouvre un éditeur pour un nouvel embed (brouillon, non sauvegardé)
+embed create <nom>             — crée immédiatement un modèle nommé et ouvre l'éditeur dessus
+embed list                     — liste les modèles sauvegardés sur ce serveur
+embed edit <nom>                — réouvre l'éditeur sur un modèle existant
+embed preview <nom>            — aperçu privé d'un modèle sauvegardé
+embed send <nom> [#salon]      — envoie un modèle sauvegardé
+embed delete <nom>             — supprime un modèle (confirmation)
+embed duplicate <nom> <nouveau> — duplique un modèle
+embed rename <ancien> <nouveau> — renomme un modèle
+embed export <nom>             — génère un fichier JSON (aucune donnée sensible)
+embed import                   — importe un fichier JSON (validation + confirmation)
+embed message <lien>           — édite un message déjà envoyé par SentriX
+embedconfig addrole/removerole/list — rôles supplémentaires autorisés à utiliser +embed

Sécurité : permissions vérifiées à chaque commande ET à chaque interaction (auteur du
panneau uniquement), AllowedMentions sûres par défaut (jamais @everyone/@here sans la
permission Discord correspondante), toutes les limites Discord (titre/description/champs/
boutons/URLs) validées avant tout envoi, jamais de code arbitraire exécutable par un membre.
"""

import io
import json
import logging
import re
import time
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks, design_system
from database.db import now

logger = logging.getLogger("bot.embeds")

# ---------------------------------------------------------------- LIMITES DISCORD (source unique)

MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_FOOTER = 2048
MAX_AUTHOR_NAME = 256
MAX_TOTAL = 6000
MAX_FIELDS = 25
MAX_BUTTONS = 25
MAX_CONTENT = 2000
MAX_URL_LEN = 2000
DRAFT_TIMEOUT = 600  # secondes avant qu'un brouillon non sauvegardé n'expire (configurable ici)

COLOR_PRESETS = [
    ("blue", "🔵 Bleu", 0x5865F2),
    ("purple", "🟣 Violet", 0x9B59B6),
    ("green", "🟢 Vert", 0x2ECC71),
    ("yellow", "🟡 Jaune", 0xF1C40F),
    ("orange", "🟠 Orange", 0xE67E22),
    ("red", "🔴 Rouge", 0xE74C3C),
    ("black", "⚫ Noir", 0x23272A),
    ("white", "⚪ Blanc", 0xFFFFFF),
    ("custom", "🎨 Personnalisée", None),
]

HEX_RE = re.compile(r"^(?:0x|#)?([0-9a-fA-F]{6})$")


def parse_colour(text: str) -> int | None:
    if not text:
        return None
    m = HEX_RE.match(text.strip())
    if not m:
        return None
    return int(m.group(1), 16)


def valid_url(text: str) -> bool:
    if not text:
        return True  # vide = pas d'URL, ce n'est pas une erreur
    text = text.strip()
    if len(text) > MAX_URL_LEN:
        return False
    return text.startswith("http://") or text.startswith("https://")


def yesno(value: bool) -> str:
    return "oui" if value else "non"


def parse_yesno(text: str, default: bool = False) -> bool:
    if not text:
        return default
    return text.strip().lower() in {"oui", "o", "yes", "y", "true", "1", "vrai"}


async def _report_ui_error(interaction: discord.Interaction, error: Exception, where: str):
    """Filet de sécurité commun à TOUTES les vues/modals de +embed. BUG CORRIGÉ : sans ceci,
    une exception imprévue dans un bouton laissait l'interaction sans aucune réponse — Discord
    affiche alors ce bouton bloqué en chargement (●●●) indéfiniment côté membre, sans aucun
    message d'erreur ni log exploitable. Cette fonction garantit qu'une réponse ephemeral est
    TOUJOURS envoyée (avec le détail technique réel, pour diagnostiquer immédiatement un futur
    cas), et est branchée via on_error() sur chaque vue/modal ci-dessous."""
    logger.error("Exception non gérée dans le créateur d'embeds (%s) :\n%s", where, traceback.format_exc())
    message = f"Une erreur inattendue est survenue ({where}).\nDétail technique : `{type(error).__name__}: {error}`"[:300]
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embeds.error(message), ephemeral=True)
        else:
            await interaction.response.send_message(embed=embeds.error(message), ephemeral=True)
    except discord.HTTPException:
        pass


# ---------------------------------------------------------------- MODÈLE DE BROUILLON

class EmbedDraft:
    """État en mémoire d'un embed en cours de construction. Rien n'est persisté tant que
    l'utilisateur ne clique pas sur "Sauvegarder" (ou "Envoyer" pour un envoi direct)."""

    def __init__(self):
        self.content: str | None = None
        self.title: str | None = None
        self.description: str | None = None
        self.colour: int | None = 0x5865F2
        self.author_name: str | None = None
        self.author_icon_url: str | None = None
        self.thumbnail_url: str | None = None
        self.image_url: str | None = None
        self.footer_text: str | None = None
        self.footer_icon_url: str | None = None
        self.timestamp_enabled: bool = False
        self.fields: list[dict] = []
        self.buttons: list[dict] = []
        self.template_id: int | None = None
        self.template_name: str | None = None
        self.target_message_id: int | None = None
        self.target_channel_id: int | None = None
        self.dirty: bool = False

    # ---------- validation ----------

    def total_chars(self) -> int:
        n = len(self.title or "") + len(self.description or "") + len(self.footer_text or "") + len(self.author_name or "")
        for f in self.fields:
            n += len(f["name"]) + len(f["value"])
        return n

    def is_empty(self) -> bool:
        return not any([
            self.title, self.description, self.fields, self.image_url,
            self.thumbnail_url, self.author_name, self.footer_text,
        ])

    def validate(self) -> list[str]:
        errors = []
        if self.title and len(self.title) > MAX_TITLE:
            errors.append(f"Le titre dépasse la limite Discord ({len(self.title)}/{MAX_TITLE}).")
        if self.description and len(self.description) > MAX_DESCRIPTION:
            errors.append(f"La description dépasse la limite Discord ({len(self.description)}/{MAX_DESCRIPTION}).")
        if self.footer_text and len(self.footer_text) > MAX_FOOTER:
            errors.append(f"Le footer dépasse la limite Discord ({len(self.footer_text)}/{MAX_FOOTER}).")
        if self.author_name and len(self.author_name) > MAX_AUTHOR_NAME:
            errors.append(f"Le nom d'auteur dépasse la limite Discord ({len(self.author_name)}/{MAX_AUTHOR_NAME}).")
        if self.content and len(self.content) > MAX_CONTENT:
            errors.append(f"Le texte au-dessus de l'embed dépasse la limite Discord ({len(self.content)}/{MAX_CONTENT}).")
        if len(self.fields) > MAX_FIELDS:
            errors.append(f"Trop de champs ({len(self.fields)}/{MAX_FIELDS}).")
        for f in self.fields:
            if len(f["name"]) > MAX_FIELD_NAME:
                errors.append(f"Le champ « {f['name'][:30]}… » a un nom trop long ({len(f['name'])}/{MAX_FIELD_NAME}).")
            if len(f["value"]) > MAX_FIELD_VALUE:
                errors.append(f"Le champ « {f['name'][:30]} » a un contenu trop long ({len(f['value'])}/{MAX_FIELD_VALUE}).")
        if self.total_chars() > MAX_TOTAL:
            errors.append(f"Le contenu total de l'embed dépasse la limite Discord ({self.total_chars()}/{MAX_TOTAL}).")
        for url_name, url in (("image", self.image_url), ("miniature", self.thumbnail_url),
                               ("icône d'auteur", self.author_icon_url), ("icône de footer", self.footer_icon_url)):
            if url and not valid_url(url):
                errors.append(f"L'URL de {url_name} n'est pas valide (doit commencer par http:// ou https://).")
        if len(self.buttons) > MAX_BUTTONS:
            errors.append(f"Trop de boutons ({len(self.buttons)}/{MAX_BUTTONS}).")
        for b in self.buttons:
            if not valid_url(b.get("url", "")):
                errors.append(f"Le bouton « {b.get('label', '?')} » a une URL invalide.")
        if self.is_empty() and not self.content:
            errors.append("L'embed est complètement vide — ajoutez au moins un titre, une description, un champ ou une image.")
        return errors

    # ---------- rendu ----------

    def to_embed(self) -> discord.Embed | None:
        if self.is_empty():
            return None
        # BUG CORRIGÉ : `discord.Embed.Empty` n'existe plus depuis discord.py 2.0 (remplacé
        # par `None`, qui est déjà géré nativement par le constructeur). L'ancienne ligne
        # levait une AttributeError dès qu'un embed sans couleur explicite était construit —
        # c'était la cause du "Une erreur inattendue est survenue. Rien n'a été envoyé."
        e = discord.Embed(
            title=self.title or None,
            description=self.description or None,
            colour=self.colour,
        )
        if self.author_name:
            e.set_author(name=self.author_name, icon_url=self.author_icon_url or None)
        if self.thumbnail_url:
            e.set_thumbnail(url=self.thumbnail_url)
        if self.image_url:
            e.set_image(url=self.image_url)
        if self.footer_text or self.footer_icon_url:
            e.set_footer(text=self.footer_text or None, icon_url=self.footer_icon_url or None)
        for f in self.fields[:MAX_FIELDS]:
            e.add_field(name=f["name"] or "​", value=f["value"] or "​", inline=bool(f.get("inline", True)))
        if self.timestamp_enabled:
            import datetime
            e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        return e

    def build_link_view(self) -> discord.ui.View | None:
        if not self.buttons:
            return None
        view = discord.ui.View(timeout=None)
        for b in self.buttons[:MAX_BUTTONS]:
            if not valid_url(b.get("url", "")):
                continue
            view.add_item(discord.ui.Button(
                label=(b.get("label") or "Lien")[:80],
                emoji=(b.get("emoji") or None) or None,
                url=b["url"],
                style=discord.ButtonStyle.link,
            ))
        return view if view.children else None

    def status_summary(self) -> str:
        lines = [
            f"**Titre :** {('configuré (' + str(len(self.title)) + ' car.)') if self.title else 'vide'}",
            f"**Description :** {('configurée (' + str(len(self.description)) + ' car.)') if self.description else 'vide'}",
            f"**Couleur :** #{self.colour:06X}" if self.colour is not None else "**Couleur :** aucune",
            f"**Champs :** {len(self.fields)}/{MAX_FIELDS}",
            f"**Boutons :** {len(self.buttons)}/{MAX_BUTTONS}",
            f"**Image :** {yesno(bool(self.image_url))} • **Miniature :** {yesno(bool(self.thumbnail_url))}",
            f"**Total :** {self.total_chars()}/{MAX_TOTAL} caractères",
        ]
        if self.template_name:
            lines.append(f"**Modèle :** 🟢 « {self.template_name} » (enregistré)" if not self.dirty else f"**Modèle :** 🟠 « {self.template_name} » — modifications non enregistrées")
        else:
            lines.append("**Modèle :** 🟠 Non sauvegardé")
        return "\n".join(lines)

    # ---------- (dé)sérialisation ----------

    def to_dict(self) -> dict:
        return {
            "content": self.content, "title": self.title, "description": self.description,
            "colour": self.colour, "author_name": self.author_name, "author_icon_url": self.author_icon_url,
            "thumbnail_url": self.thumbnail_url, "image_url": self.image_url, "footer_text": self.footer_text,
            "footer_icon_url": self.footer_icon_url, "timestamp_enabled": self.timestamp_enabled,
            "fields": self.fields, "buttons": self.buttons,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmbedDraft":
        d = cls()
        d.content = data.get("content")
        d.title = data.get("title")
        d.description = data.get("description")
        d.colour = data.get("colour")
        d.author_name = data.get("author_name")
        d.author_icon_url = data.get("author_icon_url")
        d.thumbnail_url = data.get("thumbnail_url")
        d.image_url = data.get("image_url")
        d.footer_text = data.get("footer_text")
        d.footer_icon_url = data.get("footer_icon_url")
        d.timestamp_enabled = bool(data.get("timestamp_enabled"))
        d.fields = list(data.get("fields") or [])[:MAX_FIELDS]
        d.buttons = list(data.get("buttons") or [])[:MAX_BUTTONS]
        return d

    @classmethod
    def from_row(cls, row) -> "EmbedDraft":
        d = cls.from_dict({
            "content": row["content"], "title": row["title"], "description": row["description"],
            "colour": row["colour"], "author_name": row["author_name"], "author_icon_url": row["author_icon_url"],
            "thumbnail_url": row["thumbnail_url"], "image_url": row["image_url"], "footer_text": row["footer_text"],
            "footer_icon_url": row["footer_icon_url"], "timestamp_enabled": row["timestamp_enabled"],
            "fields": json.loads(row["fields_json"] or "[]"), "buttons": json.loads(row["buttons_json"] or "[]"),
        })
        d.template_id = row["id"]
        d.template_name = row["name"]
        return d

    @classmethod
    def from_discord_embed(cls, embed: discord.Embed, content: str | None) -> "EmbedDraft":
        d = cls()
        d.content = content or None
        d.title = embed.title or None
        d.description = embed.description or None
        d.colour = embed.colour.value if embed.colour else None
        if embed.author:
            d.author_name = embed.author.name or None
            d.author_icon_url = embed.author.icon_url or None
        if embed.thumbnail:
            d.thumbnail_url = embed.thumbnail.url or None
        if embed.image:
            d.image_url = embed.image.url or None
        if embed.footer:
            d.footer_text = embed.footer.text or None
            d.footer_icon_url = embed.footer.icon_url or None
        d.fields = [{"name": f.name, "value": f.value, "inline": f.inline} for f in embed.fields][:MAX_FIELDS]
        return d


# ---------------------------------------------------------------- MODALS

class EmbedTextModal(discord.ui.Modal, title="📝 Modifier le texte"):
    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view
        d = view.draft
        self.content_input = discord.ui.TextInput(
            label="Texte au-dessus de l'embed", style=discord.TextStyle.paragraph,
            default=d.content or "", required=False, max_length=MAX_CONTENT,
        )
        self.title_input = discord.ui.TextInput(
            label="Titre", default=d.title or "", required=False, max_length=MAX_TITLE,
        )
        self.description_input = discord.ui.TextInput(
            label="Description", style=discord.TextStyle.paragraph,
            default=d.description or "", required=False, max_length=MAX_DESCRIPTION,
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer", default=d.footer_text or "", required=False, max_length=MAX_FOOTER,
        )
        self.author_input = discord.ui.TextInput(
            label="Texte de l'auteur", default=d.author_name or "", required=False, max_length=MAX_AUTHOR_NAME,
        )
        for item in (self.content_input, self.title_input, self.description_input, self.footer_input, self.author_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        d = self.view_ref.draft
        d.content = self.content_input.value or None
        d.title = self.title_input.value or None
        d.description = self.description_input.value or None
        d.footer_text = self.footer_input.value or None
        d.author_name = self.author_input.value or None
        d.dirty = True
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_ui_error(interaction, error, "modal Modifier le texte")


class EmbedColourModal(discord.ui.Modal, title="🎨 Couleur personnalisée"):
    def __init__(self, view: "EmbedAppearanceView"):
        super().__init__()
        self.view_ref = view
        self.colour_input = discord.ui.TextInput(
            label="Couleur (hex)", placeholder="#5865F2, 5865F2 ou 0x5865F2",
            default=(f"{view.draft.colour:06X}" if view.draft.colour is not None else ""), max_length=8,
        )
        self.add_item(self.colour_input)

    async def on_submit(self, interaction: discord.Interaction):
        parsed = parse_colour(self.colour_input.value)
        if parsed is None:
            return await interaction.response.send_message(
                embed=embeds.error("Couleur invalide — exemples acceptés : `#5865F2`, `5865F2`, `0x5865F2`."), ephemeral=True,
            )
        self.view_ref.draft.colour = parsed
        self.view_ref.draft.dirty = True
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_ui_error(interaction, error, "modal Couleur personnalisée")


class EmbedImagesModal(discord.ui.Modal, title="🖼️ Images"):
    def __init__(self, view: "EmbedBuilderView"):
        super().__init__()
        self.view_ref = view
        d = view.draft
        self.image_input = discord.ui.TextInput(label="URL de la grande image", default=d.image_url or "", required=False, max_length=MAX_URL_LEN)
        self.thumb_input = discord.ui.TextInput(label="URL de la miniature", default=d.thumbnail_url or "", required=False, max_length=MAX_URL_LEN)
        self.author_icon_input = discord.ui.TextInput(label="URL de l'icône d'auteur", default=d.author_icon_url or "", required=False, max_length=MAX_URL_LEN)
        self.footer_icon_input = discord.ui.TextInput(label="URL de l'icône du footer", default=d.footer_icon_url or "", required=False, max_length=MAX_URL_LEN)
        for item in (self.image_input, self.thumb_input, self.author_icon_input, self.footer_icon_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        bad = [u for u in (self.image_input.value, self.thumb_input.value, self.author_icon_input.value, self.footer_icon_input.value) if u and not valid_url(u)]
        if bad:
            return await interaction.response.send_message(
                embed=embeds.error("Une ou plusieurs URLs ne commencent pas par `http://` ou `https://` — rien n'a été modifié, corrigez-les et réessayez."),
                ephemeral=True,
            )
        d = self.view_ref.draft
        d.image_url = self.image_input.value or None
        d.thumbnail_url = self.thumb_input.value or None
        d.author_icon_url = self.author_icon_input.value or None
        d.footer_icon_url = self.footer_icon_input.value or None
        d.dirty = True
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_ui_error(interaction, error, "modal Images")


class EmbedFieldModal(discord.ui.Modal, title="➕ Champ personnalisé"):
    def __init__(self, view: "EmbedBuilderView", index: int | None = None):
        super().__init__(title="✏️ Modifier le champ" if index is not None else "➕ Ajouter un champ")
        self.view_ref = view
        self.index = index
        existing = view.draft.fields[index] if index is not None else {"name": "", "value": "", "inline": True}
        self.name_input = discord.ui.TextInput(label="Nom du champ", default=existing["name"], max_length=MAX_FIELD_NAME)
        self.value_input = discord.ui.TextInput(label="Contenu du champ", style=discord.TextStyle.paragraph, default=existing["value"], max_length=MAX_FIELD_VALUE)
        self.inline_input = discord.ui.TextInput(label="Affichage en ligne ? (oui/non)", default=yesno(existing.get("inline", True)), max_length=3)
        for item in (self.name_input, self.value_input, self.inline_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        d = self.view_ref.draft
        if self.index is None and len(d.fields) >= MAX_FIELDS:
            return await interaction.response.send_message(embed=embeds.error(f"Limite atteinte : {MAX_FIELDS} champs maximum par embed."), ephemeral=True)
        field = {"name": self.name_input.value or "​", "value": self.value_input.value or "​", "inline": parse_yesno(self.inline_input.value, True)}
        if self.index is None:
            d.fields.append(field)
        else:
            d.fields[self.index] = field
        d.dirty = True
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_ui_error(interaction, error, "modal Champ personnalisé")


class EmbedButtonModal(discord.ui.Modal, title="🔘 Bouton lien"):
    def __init__(self, view: "EmbedBuilderView", index: int | None = None):
        super().__init__(title="✏️ Modifier le bouton" if index is not None else "🔘 Ajouter un bouton lien")
        self.view_ref = view
        self.index = index
        existing = view.draft.buttons[index] if index is not None else {"label": "", "emoji": "", "url": ""}
        self.label_input = discord.ui.TextInput(label="Texte du bouton", default=existing.get("label", ""), max_length=80)
        self.emoji_input = discord.ui.TextInput(label="Emoji (optionnel)", default=existing.get("emoji", ""), required=False, max_length=10)
        self.url_input = discord.ui.TextInput(label="URL (https://...)", default=existing.get("url", ""), max_length=MAX_URL_LEN)
        for item in (self.label_input, self.emoji_input, self.url_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not valid_url(self.url_input.value):
            return await interaction.response.send_message(embed=embeds.error("URL invalide — elle doit commencer par `http://` ou `https://`."), ephemeral=True)
        d = self.view_ref.draft
        if self.index is None and len(d.buttons) >= MAX_BUTTONS:
            return await interaction.response.send_message(embed=embeds.error(f"Limite atteinte : {MAX_BUTTONS} boutons maximum."), ephemeral=True)
        button = {"label": self.label_input.value or "Lien", "emoji": self.emoji_input.value or None, "url": self.url_input.value, "style": "link"}
        if self.index is None:
            d.buttons.append(button)
        else:
            d.buttons[self.index] = button
        d.dirty = True
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_ui_error(interaction, error, "modal Bouton lien")


class EmbedSaveModal(discord.ui.Modal, title="💾 Sauvegarder le modèle"):
    def __init__(self, cog: "EmbedBuilder", view: "EmbedBuilderView"):
        super().__init__()
        self.cog = cog
        self.view_ref = view
        self.name_input = discord.ui.TextInput(
            label="Nom du modèle", placeholder="ex: annonce-animation, reglement-principal",
            default=view.draft.template_name or "", max_length=80,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        if not name:
            return await interaction.response.send_message(embed=embeds.error("Le nom ne peut pas être vide."), ephemeral=True)
        d = self.view_ref.draft
        errors = d.validate()
        if errors:
            return await interaction.response.send_message(embed=embeds.error("Corrigez d'abord :\n• " + "\n• ".join(errors[:10])), ephemeral=True)
        existing = await self.cog.get_template(interaction.guild.id, name)
        if existing and existing["id"] != d.template_id:
            return await interaction.response.send_message(embed=embeds.error(f"Un modèle nommé « {name} » existe déjà sur ce serveur."), ephemeral=True)
        if d.template_id and existing:
            await self.cog.update_template(d.template_id, d)
        else:
            d.template_id = await self.cog.create_template(interaction.guild.id, interaction.user.id, name, d)
        d.template_name = name
        d.dirty = False
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await _report_ui_error(interaction, error, "modal Sauvegarder le modèle")


# ---------------------------------------------------------------- SOUS-VUES

class EmbedAppearanceView(discord.ui.View):
    """Sous-écran "🎨 Apparence" : couleurs prédéfinies + personnalisée + date automatique."""

    def __init__(self, view: "EmbedBuilderView"):
        super().__init__(timeout=180)
        self.parent = view
        self.draft = view.draft

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cet éditeur."), ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="Choisir une couleur prédéfinie ou personnalisée",
        options=[discord.SelectOption(label=label, value=key) for key, label, _ in COLOR_PRESETS],
        row=0,
    )
    async def pick_colour(self, interaction: discord.Interaction, select: discord.ui.Select):
        key = select.values[0]
        if key == "custom":
            return await interaction.response.send_modal(EmbedColourModal(self))
        for k, _label, value in COLOR_PRESETS:
            if k == key:
                self.draft.colour = value
                break
        self.draft.dirty = True
        await self.refresh(interaction)

    @discord.ui.button(label="Date automatique : activer/désactiver", style=discord.ButtonStyle.secondary, emoji="🕒", row=1)
    async def toggle_timestamp(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.draft.timestamp_enabled = not self.draft.timestamp_enabled
        self.draft.dirty = True
        await self.refresh(interaction)

    @discord.ui.button(label="◀ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction):
        embeds_list = self.parent.build_panel_embeds()
        await interaction.response.edit_message(embeds=embeds_list, view=self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "vue Apparence")


class EmbedFieldsManageView(discord.ui.View):
    """Sous-écran "📋 Gérer les champs" : voir/modifier/supprimer/réordonner/vider."""

    def __init__(self, view: "EmbedBuilderView"):
        super().__init__(timeout=180)
        self.parent = view
        self.draft = view.draft
        self.selected: int | None = None
        self._rebuild_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cet éditeur."), ephemeral=True)
            return False
        return True

    def _rebuild_select(self):
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)
        if not self.draft.fields:
            return
        options = [
            discord.SelectOption(label=f"{i + 1}. {f['name'][:90] or 'Sans nom'}", value=str(i))
            for i, f in enumerate(self.draft.fields[:25])
        ]
        select = discord.ui.Select(placeholder="Choisir un champ", options=options, row=0)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                self.selected = int(item.values[0])
        await self.refresh(interaction)

    def list_text(self) -> str:
        if not self.draft.fields:
            return "Aucun champ pour l'instant."
        lines = []
        for i, f in enumerate(self.draft.fields):
            marker = "➡️ " if i == self.selected else ""
            lines.append(f"{marker}**{i + 1}.** {f['name'][:60] or 'Sans nom'}")
        return "\n".join(lines)

    @discord.ui.button(label="Modifier", style=discord.ButtonStyle.primary, emoji="✏️", row=1)
    async def edit_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected is None:
            return await interaction.response.send_message(embed=embeds.error("Choisissez d'abord un champ dans le menu."), ephemeral=True)
        await interaction.response.send_modal(EmbedFieldModal(self.parent, index=self.selected))

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected is None:
            return await interaction.response.send_message(embed=embeds.error("Choisissez d'abord un champ dans le menu."), ephemeral=True)
        del self.draft.fields[self.selected]
        self.selected = None
        self.draft.dirty = True
        self._rebuild_select()
        await self.refresh(interaction)

    @discord.ui.button(label="Monter", style=discord.ButtonStyle.secondary, emoji="⬆️", row=2)
    async def move_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected is None or self.selected == 0:
            return await interaction.response.send_message(embed=embeds.error("Impossible de monter ce champ."), ephemeral=True)
        i = self.selected
        self.draft.fields[i - 1], self.draft.fields[i] = self.draft.fields[i], self.draft.fields[i - 1]
        self.selected -= 1
        self.draft.dirty = True
        self._rebuild_select()
        await self.refresh(interaction)

    @discord.ui.button(label="Descendre", style=discord.ButtonStyle.secondary, emoji="⬇️", row=2)
    async def move_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected is None or self.selected >= len(self.draft.fields) - 1:
            return await interaction.response.send_message(embed=embeds.error("Impossible de descendre ce champ."), ephemeral=True)
        i = self.selected
        self.draft.fields[i + 1], self.draft.fields[i] = self.draft.fields[i], self.draft.fields[i + 1]
        self.selected += 1
        self.draft.dirty = True
        self._rebuild_select()
        await self.refresh(interaction)

    @discord.ui.button(label="Vider tous les champs", style=discord.ButtonStyle.danger, emoji="🧹", row=3)
    async def clear_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.draft.fields:
            return await interaction.response.send_message(embed=embeds.warning("Il n'y a déjà aucun champ."), ephemeral=True)
        confirm = helpers_confirm_view(self.parent.author_id)
        await interaction.response.send_message(embed=embeds.warning(f"Supprimer les **{len(self.draft.fields)}** champ(s) ? Cette action est irréversible."), view=confirm, ephemeral=True)
        await confirm.wait()
        if confirm.value:
            self.draft.fields.clear()
            self.selected = None
            self.draft.dirty = True
            self._rebuild_select()

    @discord.ui.button(label="◀ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction):
        e = embeds.neutral(f"📋 Champs ({len(self.draft.fields)}/{MAX_FIELDS})", self.list_text())
        if interaction.response.is_done():
            await interaction.followup.send(embed=e, ephemeral=True)
        else:
            await interaction.response.edit_message(embeds=[e], view=self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "vue Gérer les champs")


class EmbedButtonsManageView(discord.ui.View):
    """Sous-écran "🔘 Boutons" : ajouter/modifier/supprimer des boutons-liens."""

    def __init__(self, view: "EmbedBuilderView"):
        super().__init__(timeout=180)
        self.parent = view
        self.draft = view.draft
        self.selected: int | None = None
        self._rebuild_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cet éditeur."), ephemeral=True)
            return False
        return True

    def _rebuild_select(self):
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)
        if not self.draft.buttons:
            return
        options = [
            discord.SelectOption(label=f"{i + 1}. {b['label'][:90] or 'Lien'}", value=str(i))
            for i, b in enumerate(self.draft.buttons[:25])
        ]
        select = discord.ui.Select(placeholder="Choisir un bouton", options=options, row=0)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                self.selected = int(item.values[0])
        await self.refresh(interaction)

    def list_text(self) -> str:
        if not self.draft.buttons:
            return "Aucun bouton pour l'instant."
        return "\n".join(f"**{i + 1}.** {b.get('emoji') or ''} {b['label']} → {b['url']}" for i, b in enumerate(self.draft.buttons))

    @discord.ui.button(label="Ajouter", style=discord.ButtonStyle.success, emoji="➕", row=1)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.draft.buttons) >= MAX_BUTTONS:
            return await interaction.response.send_message(embed=embeds.error(f"Limite atteinte : {MAX_BUTTONS} boutons maximum."), ephemeral=True)
        await interaction.response.send_modal(EmbedButtonModal(self.parent, index=None))

    @discord.ui.button(label="Modifier", style=discord.ButtonStyle.primary, emoji="✏️", row=1)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected is None:
            return await interaction.response.send_message(embed=embeds.error("Choisissez d'abord un bouton dans le menu."), ephemeral=True)
        await interaction.response.send_modal(EmbedButtonModal(self.parent, index=self.selected))

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selected is None:
            return await interaction.response.send_message(embed=embeds.error("Choisissez d'abord un bouton dans le menu."), ephemeral=True)
        del self.draft.buttons[self.selected]
        self.selected = None
        self.draft.dirty = True
        self._rebuild_select()
        await self.refresh(interaction)

    @discord.ui.button(label="◀ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction):
        # BUG CORRIGÉ : cette méthode s'était retrouvée orpheline dans setup() lors d'une
        # précédente correction (jamais rattachée à la classe) — chaque clic sur un bouton
        # dans le menu "Boutons" (sélection ou suppression) plantait avec une AttributeError
        # car EmbedButtonsManageView.refresh() n'existait pas.
        e = embeds.neutral(f"🔘 Boutons ({len(self.draft.buttons)}/{MAX_BUTTONS})", self.list_text())
        await interaction.response.edit_message(embeds=[e], view=self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "vue Boutons")


# ---------------------------------------------------------------- VUE PRINCIPALE

class EmbedBuilderView(discord.ui.View):
    """Panneau principal de +embed — visible uniquement par son auteur, modifie toujours le
    même message (jamais de nouveau message à chaque clic)."""

    def __init__(self, cog: "EmbedBuilder", draft: EmbedDraft, author_id: int):
        super().__init__(timeout=DRAFT_TIMEOUT)
        self.cog = cog
        self.draft = draft
        self.author_id = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cet éditeur."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                for item in self.children:
                    item.disabled = True
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def build_panel_embeds(self) -> list[discord.Embed]:
        status = design_system.create_embed(
            title="✨ Créateur d'embed SentriX",
            description="Créez et personnalisez votre message professionnel avec les options ci-dessous.\n\n" + self.draft.status_summary(),
            colour=self.draft.colour if self.draft.colour is not None else design_system.COLORS.primary,
        )
        result = [status]
        preview = self.draft.to_embed()
        if preview:
            result.append(preview)
        return result[:10]

    async def refresh(self, interaction: discord.Interaction):
        if interaction.response.is_done():
            await interaction.edit_original_response(embeds=self.build_panel_embeds(), view=self)
        else:
            await interaction.response.edit_message(embeds=self.build_panel_embeds(), view=self)

    @discord.ui.button(label="Modifier le texte", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedTextModal(self))

    @discord.ui.button(label="Apparence", style=discord.ButtonStyle.secondary, emoji="🎨", row=0)
    async def open_appearance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embeds=self.build_panel_embeds(), view=EmbedAppearanceView(self))

    @discord.ui.button(label="Images", style=discord.ButtonStyle.secondary, emoji="🖼️", row=0)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedImagesModal(self))

    @discord.ui.button(label="Ajouter un champ", style=discord.ButtonStyle.secondary, emoji="➕", row=1)
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.draft.fields) >= MAX_FIELDS:
            return await interaction.response.send_message(embed=embeds.error(f"Limite atteinte : {MAX_FIELDS} champs maximum par embed."), ephemeral=True)
        await interaction.response.send_modal(EmbedFieldModal(self, index=None))

    @discord.ui.button(label="Gérer les champs", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
    async def manage_fields(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmbedFieldsManageView(self)
        e = embeds.neutral(f"📋 Champs ({len(self.draft.fields)}/{MAX_FIELDS})", view.list_text())
        await interaction.response.edit_message(embeds=[e], view=view)

    @discord.ui.button(label="Boutons", style=discord.ButtonStyle.secondary, emoji="🔘", row=1)
    async def manage_buttons(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmbedButtonsManageView(self)
        e = embeds.neutral(f"🔘 Boutons ({len(self.draft.buttons)}/{MAX_BUTTONS})", view.list_text())
        await interaction.response.edit_message(embeds=[e], view=view)

    @discord.ui.button(label="Prévisualiser", style=discord.ButtonStyle.primary, emoji="👁️", row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        preview_embed = self.draft.to_embed()
        link_view = self.draft.build_link_view()
        if not preview_embed:
            return await interaction.response.send_message(embed=embeds.warning("L'embed est vide pour l'instant — rien à prévisualiser."), ephemeral=True)
        await interaction.response.send_message(
            content=self.draft.content or None, embed=preview_embed, view=link_view or discord.utils.MISSING, ephemeral=True,
        )

    @discord.ui.button(label="Sauvegarder", style=discord.ButtonStyle.success, emoji="💾", row=2)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        errors = self.draft.validate()
        if errors:
            return await interaction.response.send_message(embed=embeds.error("Corrigez d'abord :\n• " + "\n• ".join(errors[:10])), ephemeral=True)
        if self.draft.template_name:
            await self.cog.update_template(self.draft.template_id, self.draft)
            self.draft.dirty = False
            return await self.refresh(interaction)
        await interaction.response.send_modal(EmbedSaveModal(self.cog, self))

    @discord.ui.button(label="Envoyer", style=discord.ButtonStyle.success, emoji="📨", row=3)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button):
        errors = self.draft.validate()
        if errors:
            return await interaction.response.send_message(embed=embeds.error("Corrigez d'abord :\n• " + "\n• ".join(errors[:10])), ephemeral=True)
        if self.draft.target_message_id:
            # On édite un message déjà envoyé par le bot (+embed message <lien>), pas un
            # nouvel envoi — pas besoin de re-choisir un salon, juste une confirmation.
            confirm = helpers_confirm_view(self.author_id)
            await interaction.response.send_message(embed=embeds.warning("Mettre à jour ce message existant avec les modifications ?"), view=confirm, ephemeral=True)
            await confirm.wait()
            if confirm.value:
                await self.cog.do_edit_message(interaction, self.draft)
            return
        await interaction.response.edit_message(embeds=self.build_panel_embeds(), view=EmbedSendView(self))

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger, emoji="❌", row=3)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # BUG CORRIGÉ : ce bouton s'était retrouvé orphelin dans setup() (jamais rattaché à
        # la classe EmbedBuilderView) lors d'une précédente correction — le panneau principal
        # n'avait alors plus aucun moyen de fermer l'éditeur proprement.
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embeds=[embeds.neutral("❌ Éditeur fermé", "Les modifications non sauvegardées ont été abandonnées.")], view=self)
        self.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "panneau principal +embed")


MESSAGE_LINK_RE = re.compile(r"(?:https?://)?(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")


class EmbedImportConfirmView(discord.ui.View):
    """Confirmation avant l'enregistrement d'un import JSON — jamais enregistré sans ce clic."""

    def __init__(self, cog: "EmbedBuilder", author_id: int, draft: EmbedDraft, name: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = author_id
        self.draft = draft
        self.name = name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à confirmer cet import."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Confirmer l'import", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = await self.cog.get_template(interaction.guild.id, self.name)
        if existing:
            return await interaction.response.edit_message(embed=embeds.error(f"Un modèle nommé « {self.name} » existe déjà — supprimez-le ou choisissez un autre nom."), view=None)
        await self.cog.create_template(interaction.guild.id, interaction.user.id, self.name, self.draft)
        await interaction.response.edit_message(embed=embeds.success(f"Modèle **{self.name}** importé et sauvegardé."), view=None)

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=embeds.error("Import annulé."), view=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "confirmation d'import")


# =============================================================================
# COG
# =============================================================================

class EmbedBuilder(commands.Cog, name="EmbedBuilder"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- ACCÈS DB

    async def get_template(self, guild_id: int, name: str):
        return await self.bot.db.fetchone(
            "SELECT * FROM embed_templates WHERE guild_id = ? AND LOWER(name) = LOWER(?)", (guild_id, name)
        )

    async def get_template_by_id(self, template_id: int):
        return await self.bot.db.fetchone("SELECT * FROM embed_templates WHERE id = ?", (template_id,))

    async def list_templates(self, guild_id: int):
        return await self.bot.db.fetchall("SELECT * FROM embed_templates WHERE guild_id = ? ORDER BY name", (guild_id,))

    async def create_template(self, guild_id: int, author_id: int, name: str, draft: EmbedDraft) -> int:
        cur = await self.bot.db.execute(
            "INSERT INTO embed_templates (guild_id, name, content, title, description, colour, author_name, "
            "author_icon_url, thumbnail_url, image_url, footer_text, footer_icon_url, timestamp_enabled, "
            "fields_json, buttons_json, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, name, draft.content, draft.title, draft.description, draft.colour, draft.author_name,
             draft.author_icon_url, draft.thumbnail_url, draft.image_url, draft.footer_text, draft.footer_icon_url,
             int(draft.timestamp_enabled), json.dumps(draft.fields), json.dumps(draft.buttons), author_id, now(), now()),
        )
        return cur.lastrowid

    async def update_template(self, template_id: int, draft: EmbedDraft):
        await self.bot.db.execute(
            "UPDATE embed_templates SET content = ?, title = ?, description = ?, colour = ?, author_name = ?, "
            "author_icon_url = ?, thumbnail_url = ?, image_url = ?, footer_text = ?, footer_icon_url = ?, "
            "timestamp_enabled = ?, fields_json = ?, buttons_json = ?, updated_at = ? WHERE id = ?",
            (draft.content, draft.title, draft.description, draft.colour, draft.author_name, draft.author_icon_url,
             draft.thumbnail_url, draft.image_url, draft.footer_text, draft.footer_icon_url, int(draft.timestamp_enabled),
             json.dumps(draft.fields), json.dumps(draft.buttons), now(), template_id),
        )

    async def delete_template(self, template_id: int):
        await self.bot.db.execute("DELETE FROM embed_templates WHERE id = ?", (template_id,))

    # ---------------------------------------------------------------- OUVERTURE DE L'ÉDITEUR

    async def open_builder(self, ctx: commands.Context, draft: EmbedDraft | None = None):
        draft = draft or EmbedDraft()
        view = EmbedBuilderView(self, draft, ctx.author.id)
        msg = await ctx.send(embeds=view.build_panel_embeds(), view=view, ephemeral=True if ctx.interaction else False)
        view.message = msg if not ctx.interaction else await ctx.interaction.original_response()

    # ---------------------------------------------------------------- ENVOI RÉEL

    async def do_send(self, interaction: discord.Interaction, draft: EmbedDraft, channel: discord.TextChannel, allow_mentions: bool):
        started = time.monotonic()
        try:
            if not channel.permissions_for(interaction.guild.me).view_channel or not channel.permissions_for(interaction.guild.me).send_messages:
                return await interaction.response.edit_message(embed=embeds.error(f"Je n'ai pas la permission de voir/écrire dans {channel.mention}."), view=None)
            if not channel.permissions_for(interaction.guild.me).embed_links:
                return await interaction.response.edit_message(embed=embeds.error(f"Il me manque la permission **Intégrer des liens** dans {channel.mention} pour envoyer un embed."), view=None)

            allowed = discord.AllowedMentions(everyone=allow_mentions, roles=allow_mentions, users=True)
            embed = draft.to_embed()
            view = draft.build_link_view()
            msg = await channel.send(content=draft.content or None, embed=embed, view=view or discord.utils.MISSING, allowed_mentions=allowed)
            await interaction.response.edit_message(embed=embeds.success(f"📨 Embed envoyé dans {channel.mention}."), view=None)
            logger.info("Embed envoyé par %s dans #%s (guild=%s) en %.2fs.", interaction.user.id, channel.id, interaction.guild.id, time.monotonic() - started)
        except discord.Forbidden:
            await self._safe_edit_error(interaction, "Permission refusée par Discord au moment de l'envoi.")
        except discord.NotFound:
            await self._safe_edit_error(interaction, "Le salon n'existe plus.")
        except discord.HTTPException as e:
            await self._safe_edit_error(interaction, f"Discord a refusé l'envoi : `{e}`")
        except Exception as e:
            # Le détail exact (tronqué) est aussi affiché au staff qui utilise +embed — pas
            # juste "une erreur inattendue" sans plus d'info — pour qu'un futur bug puisse
            # être diagnostiqué directement depuis Discord, sans devoir relire les logs.
            logger.error("Exception non gérée lors de l'envoi d'un embed (guild=%s, user=%s) :\n%s", interaction.guild.id if interaction.guild else None, interaction.user.id, traceback.format_exc())
            await self._safe_edit_error(interaction, f"Une erreur inattendue est survenue. Rien n'a été envoyé.\nDétail technique : `{type(e).__name__}: {e}`"[:300])

    async def do_edit_message(self, interaction: discord.Interaction, draft: EmbedDraft):
        try:
            channel = interaction.guild.get_channel(draft.target_channel_id)
            if not channel:
                return await interaction.followup.send(embed=embeds.error("Le salon d'origine n'existe plus."), ephemeral=True)
            msg = await channel.fetch_message(draft.target_message_id)
            if msg.author.id != self.bot.user.id:
                return await interaction.followup.send(embed=embeds.error("Ce message n'appartient pas à SentriX — impossible de le modifier."), ephemeral=True)
            embed = draft.to_embed()
            view = draft.build_link_view()
            await msg.edit(content=draft.content or None, embed=embed, view=view or discord.utils.MISSING)
            await interaction.followup.send(embed=embeds.success("✅ Message mis à jour."), ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send(embed=embeds.error("Le message a été supprimé entre-temps."), ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(embed=embeds.error("Permission refusée pour modifier ce message."), ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(embed=embeds.error(f"Discord a refusé la modification : `{e}`"), ephemeral=True)
        except Exception as e:
            logger.error("Exception non gérée lors de l'édition d'un message (guild=%s) :\n%s", interaction.guild.id if interaction.guild else None, traceback.format_exc())
            await interaction.followup.send(embed=embeds.error(f"Une erreur inattendue est survenue.\nDétail technique : `{type(e).__name__}: {e}`"[:300]), ephemeral=True)

    async def _safe_edit_error(self, interaction: discord.Interaction, message: str):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embeds.error(message), ephemeral=True)
            else:
                await interaction.response.edit_message(embed=embeds.error(message), view=None)
        except discord.HTTPException:
            pass

    # ---------------------------------------------------------------- COMMANDES

    @commands.hybrid_group(name="embed", description="Créer un embed personnalisé pour ce serveur.")
    @checks.has_embed_permission()
    async def embed_group(self, ctx: commands.Context):
        await self.open_builder(ctx)

    @embed_group.command(name="create", description="Créer un nouveau modèle d'embed nommé.")
    @app_commands.describe(nom="Le nom du modèle à créer")
    @checks.has_embed_permission()
    async def embed_create(self, ctx: commands.Context, *, nom: str):
        if await self.get_template(ctx.guild.id, nom):
            return await ctx.send(embed=embeds.error(f"Un modèle nommé « {nom} » existe déjà sur ce serveur."))
        draft = EmbedDraft()
        draft.template_name = nom
        draft.template_id = await self.create_template(ctx.guild.id, ctx.author.id, nom, draft)
        await self.open_builder(ctx, draft)

    @embed_group.command(name="list", description="Lister les modèles d'embeds sauvegardés sur ce serveur.")
    @checks.has_embed_permission()
    async def embed_list(self, ctx: commands.Context):
        rows = await self.list_templates(ctx.guild.id)
        e = embeds.neutral("📨 Modèles d'embeds")
        if not rows:
            e.description = "Aucun modèle sauvegardé. Utilisez `+embed create <nom>` pour commencer."
        else:
            e.description = "\n".join(f"• **{r['name']}** (#{r['id']})" for r in rows[:25])
        await ctx.send(embed=e)

    @embed_group.command(name="edit", description="Rouvrir l'éditeur sur un modèle existant.")
    @app_commands.describe(nom="Le nom du modèle à modifier")
    @checks.has_embed_permission()
    async def embed_edit(self, ctx: commands.Context, *, nom: str):
        row = await self.get_template(ctx.guild.id, nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {nom} »."))
        draft = EmbedDraft.from_row(row)
        await self.open_builder(ctx, draft)

    @embed_group.command(name="preview", description="Aperçu privé d'un modèle sauvegardé.")
    @app_commands.describe(nom="Le nom du modèle à prévisualiser")
    @checks.has_embed_permission()
    async def embed_preview(self, ctx: commands.Context, *, nom: str):
        row = await self.get_template(ctx.guild.id, nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {nom} »."))
        draft = EmbedDraft.from_row(row)
        preview = draft.to_embed()
        if not preview:
            return await ctx.send(embed=embeds.warning("Ce modèle est vide."))
        await ctx.send(content=draft.content or None, embed=preview, view=draft.build_link_view() or discord.utils.MISSING, ephemeral=True if ctx.interaction else False)

    @embed_group.command(name="send", description="Envoyer un modèle sauvegardé dans un salon.")
    @app_commands.describe(nom="Le nom du modèle à envoyer", salon="Le salon de destination")
    @checks.has_embed_permission()
    async def embed_send(self, ctx: commands.Context, nom: str, salon: discord.TextChannel = None):
        row = await self.get_template(ctx.guild.id, nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {nom} »."))
        channel = salon or ctx.channel
        draft = EmbedDraft.from_row(row)
        errors = draft.validate()
        if errors:
            return await ctx.send(embed=embeds.error("Ce modèle contient des erreurs :\n• " + "\n• ".join(errors[:10])))
        if not channel.permissions_for(ctx.guild.me).send_messages or not channel.permissions_for(ctx.guild.me).embed_links:
            return await ctx.send(embed=embeds.error(f"Il me manque des permissions dans {channel.mention} (Envoyer des messages / Intégrer des liens)."))
        allowed = discord.AllowedMentions(everyone=False, roles=False, users=True)
        await channel.send(content=draft.content or None, embed=draft.to_embed(), view=draft.build_link_view() or discord.utils.MISSING, allowed_mentions=allowed)
        await ctx.send(embed=embeds.success(f"📨 Modèle **{nom}** envoyé dans {channel.mention}."))

    @embed_group.command(name="delete", description="Supprimer un modèle d'embed.")
    @app_commands.describe(nom="Le nom du modèle à supprimer")
    @checks.has_embed_permission()
    async def embed_delete(self, ctx: commands.Context, *, nom: str):
        row = await self.get_template(ctx.guild.id, nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {nom} »."))
        view = helpers_confirm_view(ctx.author.id)
        msg = await ctx.send(embed=embeds.warning(f"Supprimer le modèle **{nom}** ? Cette action est irréversible."), view=view)
        await view.wait()
        if not view.value:
            return await msg.edit(embed=embeds.error("Suppression annulée."), view=None)
        await self.delete_template(row["id"])
        await msg.edit(embed=embeds.success(f"Modèle **{nom}** supprimé."), view=None)

    @embed_group.command(name="duplicate", description="Dupliquer un modèle d'embed existant.")
    @app_commands.describe(nom="Le nom du modèle à dupliquer", nouveau_nom="Le nom du modèle dupliqué")
    @checks.has_embed_permission()
    async def embed_duplicate(self, ctx: commands.Context, nom: str, *, nouveau_nom: str):
        row = await self.get_template(ctx.guild.id, nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {nom} »."))
        if await self.get_template(ctx.guild.id, nouveau_nom):
            return await ctx.send(embed=embeds.error(f"Un modèle nommé « {nouveau_nom} » existe déjà."))
        draft = EmbedDraft.from_row(row)
        await self.create_template(ctx.guild.id, ctx.author.id, nouveau_nom, draft)
        await ctx.send(embed=embeds.success(f"Modèle **{nom}** dupliqué en **{nouveau_nom}**."))

    @embed_group.command(name="rename", description="Renommer un modèle d'embed.")
    @app_commands.describe(ancien_nom="Le nom actuel", nouveau_nom="Le nouveau nom")
    @checks.has_embed_permission()
    async def embed_rename(self, ctx: commands.Context, ancien_nom: str, *, nouveau_nom: str):
        row = await self.get_template(ctx.guild.id, ancien_nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {ancien_nom} »."))
        if await self.get_template(ctx.guild.id, nouveau_nom):
            return await ctx.send(embed=embeds.error(f"Un modèle nommé « {nouveau_nom} » existe déjà."))
        await self.bot.db.execute("UPDATE embed_templates SET name = ?, updated_at = ? WHERE id = ?", (nouveau_nom, now(), row["id"]))
        await ctx.send(embed=embeds.success(f"Modèle **{ancien_nom}** renommé en **{nouveau_nom}**."))

    @embed_group.command(name="export", description="Exporter un modèle d'embed en fichier JSON.")
    @app_commands.describe(nom="Le nom du modèle à exporter")
    @checks.has_embed_permission()
    async def embed_export(self, ctx: commands.Context, *, nom: str):
        row = await self.get_template(ctx.guild.id, nom)
        if not row:
            return await ctx.send(embed=embeds.error(f"Aucun modèle nommé « {nom} »."))
        draft = EmbedDraft.from_row(row)
        # Uniquement la configuration de l'embed — jamais de token, secret, ID interne de
        # base de données ou autre information privée du serveur.
        data = draft.to_dict()
        data["_sentrix_embed_export"] = True
        data["_name"] = nom
        buf = io.BytesIO(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
        await ctx.send(embed=embeds.success(f"Export du modèle **{nom}**."), file=discord.File(buf, filename=f"{nom}.json"))

    @embed_group.command(name="import", description="Importer un modèle d'embed depuis un fichier JSON.")
    @app_commands.describe(fichier="Le fichier JSON exporté par +embed export")
    @checks.has_embed_permission()
    async def embed_import(self, ctx: commands.Context, fichier: discord.Attachment = None):
        attachment = fichier or (ctx.message.attachments[0] if ctx.message and ctx.message.attachments else None)
        if not attachment:
            return await ctx.send(embed=embeds.error("Joignez un fichier JSON exporté avec `+embed export`."))
        if not attachment.filename.lower().endswith(".json") or attachment.size > 256_000:
            return await ctx.send(embed=embeds.error("Fichier invalide — un fichier `.json` de moins de 256 Ko est attendu."))
        try:
            raw = await attachment.read()
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return await ctx.send(embed=embeds.error("Le fichier n'est pas un JSON valide."))
        if not isinstance(data, dict):
            return await ctx.send(embed=embeds.error("Format invalide — un objet JSON est attendu."))
        name = (data.get("_name") or "").strip()
        if not name:
            return await ctx.send(embed=embeds.error("Ce fichier ne contient pas de nom de modèle (`_name`) — il ne vient probablement pas de `+embed export`."))
        draft = EmbedDraft.from_dict(data)
        errors = draft.validate()
        if errors:
            return await ctx.send(embed=embeds.error("Ce fichier contient des données invalides :\n• " + "\n• ".join(errors[:10])))
        preview = draft.to_embed()
        e = embeds.warning(f"Importer le modèle **{name}** ?", "Vérifiez l'aperçu ci-dessous avant de confirmer.")
        await ctx.send(embed=e)
        if preview:
            await ctx.send(embed=preview)
        await ctx.send(view=EmbedImportConfirmView(self, ctx.author.id, draft, name))

    @embed_group.command(name="message", description="Éditer un message déjà envoyé par SentriX.")
    @app_commands.describe(lien="Le lien du message à éditer")
    @checks.has_embed_permission()
    async def embed_message(self, ctx: commands.Context, *, lien: str):
        m = MESSAGE_LINK_RE.search(lien)
        if not m:
            return await ctx.send(embed=embeds.error("Lien de message invalide. Clic droit sur le message → Copier le lien."))
        guild_id, channel_id, message_id = (int(x) for x in m.groups())
        if guild_id != ctx.guild.id:
            return await ctx.send(embed=embeds.error("Ce message appartient à un autre serveur."))
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            return await ctx.send(embed=embeds.error("Le salon de ce message n'existe plus (ou je ne le vois pas)."))
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await ctx.send(embed=embeds.error("Message introuvable — il a peut-être été supprimé."))
        except discord.Forbidden:
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission de lire ce salon."))
        if message.author.id != self.bot.user.id:
            return await ctx.send(embed=embeds.error("Je ne peux modifier que les messages envoyés par SentriX."))
        if not message.embeds:
            return await ctx.send(embed=embeds.error("Ce message ne contient aucun embed à éditer."))
        draft = EmbedDraft.from_discord_embed(message.embeds[0], message.content)
        draft.target_message_id = message.id
        draft.target_channel_id = channel.id
        await self.open_builder(ctx, draft)

    # ---------------------------------------------------------------- CONFIGURATION DES RÔLES AUTORISÉS

    @commands.hybrid_group(name="embedconfig", description="Configurer les rôles autorisés à utiliser +embed.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def embedconfig(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT role_id FROM embed_allowed_roles WHERE guild_id = ?", (ctx.guild.id,))
        roles = [ctx.guild.get_role(r["role_id"]) for r in rows]
        roles = [r for r in roles if r]
        e = embeds.neutral(
            "📨 Rôles autorisés — créateur d'embeds",
            "Gérer les messages, Gérer le serveur et les gestionnaires du bot ont TOUJOURS accès, "
            "en plus des rôles ci-dessous.\n\n" + ("\n".join(r.mention for r in roles) if roles else "Aucun rôle supplémentaire configuré."),
        )
        await ctx.send(embed=e)

    @embedconfig.command(name="addrole", description="Autoriser un rôle à utiliser +embed.")
    @app_commands.describe(role="Le rôle à autoriser")
    @checks.is_owner_or_admin()
    async def embedconfig_addrole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.execute("INSERT OR IGNORE INTO embed_allowed_roles (guild_id, role_id) VALUES (?, ?)", (ctx.guild.id, role.id))
        await ctx.send(embed=embeds.success(f"{role.mention} peut désormais utiliser `+embed`."))

    @embedconfig.command(name="removerole", description="Retirer l'autorisation d'utiliser +embed à un rôle.")
    @app_commands.describe(role="Le rôle à retirer")
    @checks.is_owner_or_admin()
    async def embedconfig_removerole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.execute("DELETE FROM embed_allowed_roles WHERE guild_id = ? AND role_id = ?", (ctx.guild.id, role.id))
        await ctx.send(embed=embeds.success(f"{role.mention} ne peut plus utiliser `+embed` (sauf s'il a Gérer les messages/le serveur)."))

    @embedconfig.command(name="list", description="Lister les rôles autorisés à utiliser +embed.")
    @checks.is_owner_or_admin()
    async def embedconfig_list(self, ctx: commands.Context):
        await self.embedconfig.callback(self, ctx)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))


def helpers_confirm_view(author_id: int):
    """Petit ConfirmView local (Oui/Non) — évite une dépendance croisée avec utils/helpers
    pour un composant aussi simple, tout en gardant le même comportement (wait() + .value)."""

    class _Confirm(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.value = None

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return interaction.user.id == author_id

        @discord.ui.button(label="Oui, confirmer", style=discord.ButtonStyle.danger)
        async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = True
            await interaction.response.edit_message(view=None)
            self.stop()

        @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
        async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = False
            await interaction.response.edit_message(view=None)
            self.stop()

        async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
            await _report_ui_error(interaction, error, "confirmation")

    return _Confirm()


class EmbedSendConfirmView(discord.ui.View):
    """Dernier écran avant l'envoi réel — résumé + Confirmer/Retour/Annuler, exactement
    comme demandé (jamais d'envoi direct sans ce dernier accord explicite)."""

    def __init__(self, view: "EmbedBuilderView", channel: discord.TextChannel, allow_mentions: bool):
        super().__init__(timeout=120)
        self.parent = view
        self.channel = channel
        self.allow_mentions = allow_mentions

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cet éditeur."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Confirmer l'envoi", style=discord.ButtonStyle.success, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent.cog.do_send(interaction, self.parent.draft, self.channel, self.allow_mentions)

    @discord.ui.button(label="◀ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embeds=self.parent.build_panel_embeds(), view=EmbedSendView(self.parent))

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "confirmation d'envoi")


class EmbedSendView(discord.ui.View):
    """Sous-écran "📨 Envoyer" : choix du salon puis mentions, avant le résumé final."""

    def __init__(self, view: "EmbedBuilderView"):
        super().__init__(timeout=180)
        self.parent = view
        self.draft = view.draft
        self.channel: discord.TextChannel | None = None
        self.allow_mentions = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.parent.author_id:
            await interaction.response.send_message(embed=embeds.error("Vous n'êtes pas autorisé à utiliser cet éditeur."), ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="📌 Choisir le salon de destination", row=0)
    async def pick_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        # BUG CORRIGÉ : discord.ui.ChannelSelect renvoie des app_commands.AppCommandChannel
        # (objets partiels, sans permissions_for()) et non de vrais discord.TextChannel — il
        # faut résoudre le salon réel via le cache de la guilde pour pouvoir vérifier les
        # permissions du bot au moment de l'envoi. Sans ça : "AttributeError: 'AppCommandChannel'
        # object has no attribute 'permissions_for'" au clic sur Envoyer.
        picked = select.values[0]
        self.channel = interaction.guild.get_channel(picked.id) or picked
        await interaction.response.edit_message(embeds=self.parent.build_panel_embeds(), view=self)

    @discord.ui.button(label="Autoriser les mentions @everyone/@here (réservé)", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_mentions(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.guild_permissions.mention_everyone:
            return await interaction.response.send_message(
                embed=embeds.error("Seuls les membres ayant la permission **Mentionner tout le monde** peuvent activer ceci."), ephemeral=True,
            )
        self.allow_mentions = not self.allow_mentions
        await interaction.response.edit_message(embeds=self.parent.build_panel_embeds(), view=self)

    @discord.ui.button(label="Continuer", style=discord.ButtonStyle.success, row=2)
    async def proceed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.channel:
            return await interaction.response.send_message(embed=embeds.error("Choisissez d'abord un salon dans le menu."), ephemeral=True)
        errors = self.draft.validate()
        if errors:
            return await interaction.response.send_message(embed=embeds.error("Corrigez d'abord :\n• " + "\n• ".join(errors[:10])), ephemeral=True)
        summary = (
            f"**Salon :** {self.channel.mention}\n"
            f"**Titre :** {self.draft.title or 'Aucun'}\n"
            f"**Mentions :** {'autorisées (@everyone/@here)' if self.allow_mentions else 'désactivées'}\n"
            f"**Modèle sauvegardé :** {yesno(bool(self.draft.template_name and not self.draft.dirty))}"
        )
        e = embeds.warning("📨 Confirmer l'envoi ?", summary)
        await interaction.response.edit_message(embeds=[e], view=EmbedSendConfirmView(self.parent, self.channel, self.allow_mentions))

    @discord.ui.button(label="◀ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        await _report_ui_error(interaction, error, "vue Envoyer")
