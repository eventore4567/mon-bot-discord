"""UX média SentriX : upload Discord natif au lieu de demander des URLs d'images.

Les URLs métier qui représentent réellement un lien (YouTube/TikTok, boutons de lien,
etc.) restent des URLs. Cette couche ne cible que les médias visuels configurables.

Discord.py 2.7 apporte le composant FileUpload dans les modals. Les anciennes valeurs URL
déjà enregistrées restent lisibles : si aucun nouveau fichier n'est envoyé, elles sont
conservées. Quand un fichier Discord est choisi, on stocke son URL CDN sans paramètres
signés ; Discord sait rafraîchir automatiquement ces URLs quand elles sont utilisées dans
les champs image/thumbnail d'un embed.
"""
from __future__ import annotations

import logging
import re

import discord

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.media-upload-runtime")

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_PATCHED: set[str] = set()


def _is_image(attachment: discord.Attachment) -> bool:
    content_type = str(getattr(attachment, "content_type", "") or "").casefold()
    filename = str(getattr(attachment, "filename", "") or "").casefold()
    return content_type.startswith("image/") or filename.endswith(_IMAGE_EXTENSIONS)


def _stable_url(attachment: discord.Attachment) -> str:
    """URL Discord réutilisable dans un champ image d'embed.

    Les query params `ex/is/hm` expirent. Discord recommande de passer l'URL CDN sans
    paramètres dans les champs API d'image afin qu'elle soit rafraîchie automatiquement.
    """
    return str(attachment.url).split("?", 1)[0]


def _one_upload(upload) -> discord.Attachment | None:
    values = list(getattr(upload, "values", None) or [])
    return values[0] if values else None


def _remove_tokens(value: str) -> set[str]:
    raw = str(value or "").casefold().strip()
    if not raw or raw in {"non", "no", "aucun", "rien", "garder"}:
        return set()
    raw = raw.replace("é", "e").replace("è", "e").replace("à", "a")
    return {part for part in re.split(r"[\s,;/+]+", raw) if part}


def _label(text: str, component, description: str | None = None):
    return discord.ui.Label(text=text, description=description, component=component)


def _install_ticket_uploads() -> bool:
    try:
        from . import tickets as tickets_mod
    except Exception:
        return False

    current = getattr(tickets_mod, "PanelMediaModal", None)
    if current is None:
        return False
    if getattr(current, "_sentrix_native_media_upload", False):
        return True

    class PanelMediaUploadModal(discord.ui.Modal, title="🖼️ Média du panel"):
        _sentrix_native_media_upload = True

        def __init__(self, cog, panel):
            super().__init__()
            self.cog = cog
            self.panel_id = int(panel["id"])
            self.old_image = panel["image_url"] or None
            self.old_thumbnail = panel["thumbnail_url"] or None

            self.color = discord.ui.TextInput(
                default=(f"{panel['color']:06X}" if panel["color"] else ""),
                required=False,
                max_length=6,
                placeholder="5865F2",
            )
            self.footer = discord.ui.TextInput(
                default=panel["footer_text"] or "",
                required=False,
                max_length=200,
                placeholder="Texte affiché en bas du panel",
            )
            self.image_upload = discord.ui.FileUpload(
                custom_id=f"sx:ticket:image:{self.panel_id}",
                required=False,
                min_values=0,
                max_values=1,
            )
            self.thumbnail_upload = discord.ui.FileUpload(
                custom_id=f"sx:ticket:thumb:{self.panel_id}",
                required=False,
                min_values=0,
                max_values=1,
            )
            self.remove = discord.ui.TextInput(
                default="non",
                required=False,
                max_length=30,
                placeholder="non / image / miniature / tout",
            )

            self.add_item(_label("Couleur", self.color, "Code hexadécimal, sans #."))
            self.add_item(_label("Footer", self.footer, "Laissez vide pour ne pas afficher de footer."))
            self.add_item(_label("Grande image", self.image_upload, "Choisissez directement une image depuis votre appareil."))
            self.add_item(_label("Miniature", self.thumbnail_upload, "Choisissez directement une image depuis votre appareil."))
            self.add_item(_label("Supprimer un média ?", self.remove, "non, image, miniature ou tout"))

        async def on_submit(self, interaction: discord.Interaction):
            raw_color = str(self.color.value or "").strip().lstrip("#")
            color_value = None
            if raw_color:
                try:
                    color_value = int(raw_color, 16)
                except ValueError:
                    return await panels.envoyer(interaction.response, panels.depuis_embed(tickets_mod.embeds.error('Couleur invalide. Utilisez un code hexadécimal comme `5865F2`.')), ephemere=True)

            image = _one_upload(self.image_upload)
            thumbnail = _one_upload(self.thumbnail_upload)
            for attachment, label in ((image, "grande image"), (thumbnail, "miniature")):
                if attachment is not None and not _is_image(attachment):
                    return await panels.envoyer(interaction.response, panels.depuis_embed(tickets_mod.embeds.error(f"Le fichier choisi pour **{label}** n'est pas une image. Formats acceptés : PNG, JPG, WEBP ou GIF.")), ephemere=True)

            image_url = _stable_url(image) if image else self.old_image
            thumbnail_url = _stable_url(thumbnail) if thumbnail else self.old_thumbnail
            remove = _remove_tokens(self.remove.value)
            if "tout" in remove or "all" in remove:
                image_url = None
                thumbnail_url = None
            else:
                if {"image", "grande", "grand"} & remove:
                    image_url = None
                if {"miniature", "thumb", "thumbnail"} & remove:
                    thumbnail_url = None

            await self.cog.bot.db.execute(
                "UPDATE ticket_panels_v2 SET color = ?, image_url = ?, thumbnail_url = ?, "
                "footer_text = ? WHERE id = ?",
                (
                    color_value,
                    image_url,
                    thumbnail_url,
                    str(self.footer.value or "") or None,
                    self.panel_id,
                ),
            )
            await panels.envoyer(interaction.response, panels.depuis_embed(tickets_mod.embeds.success('Apparence mise à jour. Les images sont maintenant importées directement depuis Discord : aucune URL à copier.')), ephemere=True)

    tickets_mod.PanelMediaModal = PanelMediaUploadModal
    logger.info("Tickets : URL image/miniature remplacées par FileUpload Discord.")
    return True


def _install_embed_uploads() -> bool:
    try:
        from . import embed_builder as embed_mod
    except Exception:
        return False

    current = getattr(embed_mod, "EmbedImagesModal", None)
    if current is None:
        return False
    if getattr(current, "_sentrix_native_media_upload", False):
        return True

    class EmbedImagesUploadModal(discord.ui.Modal, title="🖼️ Images"):
        _sentrix_native_media_upload = True

        def __init__(self, view):
            super().__init__()
            self.view_ref = view
            self.image_upload = discord.ui.FileUpload(
                custom_id="sx:embed:image", required=False, min_values=0, max_values=1
            )
            self.thumb_upload = discord.ui.FileUpload(
                custom_id="sx:embed:thumb", required=False, min_values=0, max_values=1
            )
            self.author_upload = discord.ui.FileUpload(
                custom_id="sx:embed:author", required=False, min_values=0, max_values=1
            )
            self.footer_upload = discord.ui.FileUpload(
                custom_id="sx:embed:footer", required=False, min_values=0, max_values=1
            )
            self.remove = discord.ui.TextInput(
                default="non",
                required=False,
                max_length=60,
                placeholder="non / image / miniature / auteur / footer / tout",
            )

            self.add_item(_label("Grande image", self.image_upload, "Sélectionnez une image depuis votre appareil."))
            self.add_item(_label("Miniature", self.thumb_upload, "Sélectionnez une image depuis votre appareil."))
            self.add_item(_label("Icône auteur", self.author_upload, "Optionnel : avatar affiché à côté de l'auteur."))
            self.add_item(_label("Icône footer", self.footer_upload, "Optionnel : petite image du footer."))
            self.add_item(_label("Supprimer un média ?", self.remove, "Séparez plusieurs choix par une virgule."))

        async def on_submit(self, interaction: discord.Interaction):
            uploads = {
                "image_url": _one_upload(self.image_upload),
                "thumbnail_url": _one_upload(self.thumb_upload),
                "author_icon_url": _one_upload(self.author_upload),
                "footer_icon_url": _one_upload(self.footer_upload),
            }
            for attachment in uploads.values():
                if attachment is not None and not _is_image(attachment):
                    return await panels.envoyer(interaction.response, panels.depuis_embed(embed_mod.embeds.error('Tous les fichiers doivent être des images PNG, JPG, WEBP ou GIF.')), ephemere=True)

            draft = self.view_ref.draft
            for attr, attachment in uploads.items():
                if attachment is not None:
                    setattr(draft, attr, _stable_url(attachment))

            remove = _remove_tokens(self.remove.value)
            if "tout" in remove or "all" in remove:
                draft.image_url = None
                draft.thumbnail_url = None
                draft.author_icon_url = None
                draft.footer_icon_url = None
            else:
                if "image" in remove or "grande" in remove:
                    draft.image_url = None
                if {"miniature", "thumb", "thumbnail"} & remove:
                    draft.thumbnail_url = None
                if {"auteur", "author"} & remove:
                    draft.author_icon_url = None
                if "footer" in remove:
                    draft.footer_icon_url = None

            draft.dirty = True
            await self.view_ref.refresh(interaction)

        async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
            await embed_mod._report_ui_error(interaction, error, "modal Upload images")

    embed_mod.EmbedImagesModal = EmbedImagesUploadModal
    logger.info("Créateur d'embeds : 4 champs URL média remplacés par FileUpload Discord.")
    return True


def _install_notification_attachment_only(bot) -> bool:
    try:
        from . import notifications as notifications_mod
    except Exception:
        return False

    if getattr(notifications_mod, "_sentrix_attachment_only_media", False):
        return True

    old_attachment_image = notifications_mod._attachment_image

    def attachment_image_only(ctx):
        value = old_attachment_image(ctx)
        if not value:
            return None
        return str(value).split("?", 1)[0]

    image_flag_re = re.compile(r"(?:^|\s)--image(?:\s+\S+)?", re.IGNORECASE)

    def no_image_url_flag(text: str):
        """Ancien --image URL supprimé : le média doit être joint directement au message."""
        cleaned = image_flag_re.sub("", str(text or ""), count=1).strip()
        return cleaned, None

    notifications_mod._attachment_image = attachment_image_only
    notifications_mod._extract_image_flag = no_image_url_flag
    notifications_mod._sentrix_attachment_only_media = True

    for command_name in ("notifs-ping", "welcome-config"):
        command = bot.get_command(command_name)
        if command is not None:
            command.help = (
                "Pour ajouter une image, joignez directement le fichier à votre message. "
                "Aucune URL d'image n'est nécessaire."
            )

    logger.info("Notifications/bienvenue : médias configurables en pièce jointe uniquement.")
    return True


def install(bot, extension_name: str) -> None:
    """Active les uploads natifs quand les cogs concernés viennent d'être chargés."""
    if not hasattr(discord.ui, "FileUpload"):
        logger.error(
            "FileUpload Discord indisponible. SentriX requiert discord.py >= 2.7 pour l'UX média."
        )
        return

    name = str(extension_name or "")
    if name == "cogs.tickets" or name.endswith(".tickets"):
        if _install_ticket_uploads():
            _PATCHED.add("tickets")
    if name == "cogs.embed_builder" or name.endswith(".embed_builder"):
        if _install_embed_uploads():
            _PATCHED.add("embed_builder")
    if name == "cogs.notifications" or name.endswith(".notifications"):
        if _install_notification_attachment_only(bot):
            _PATCHED.add("notifications")


__all__ = ["install"]
