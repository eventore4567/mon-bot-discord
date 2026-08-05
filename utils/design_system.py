"""
Système de design central de SentriX (identité visuelle futuriste/premium/sombre).

Phase 1 de la refonte visuelle demandée par Jayden : ce fichier est le SOCLE partagé par
toutes les futures fiches visuelles (modération, sécurité, tickets, économie, niveaux,
giveaways, musique...). Il ne remplace PAS utils/embeds.py — les 258 commandes existantes
continuent de fonctionner exactement comme avant tant qu'elles n'ont pas été migrées une
par une (Phases 2 à 5). utils/embeds.py reste la source utilisée par le code non migré.

Les couleurs par défaut (COLORS) reprennent volontairement les mêmes valeurs que
config.COLOR_* pour que l'identité visuelle reste cohérente pendant la transition.

Rien ici n'invente de donnée : toute valeur numérique affichée par les fonctions de ce
fichier doit être fournie par l'appelant (utils/stats_service.py ou une requête directe
à la base) — voir la règle 19 de la demande ("ne crée aucune donnée fictive").
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import discord


# =============================================================================
# 1. Couleurs
# =============================================================================

@dataclass(frozen=True)
class SentriXColors:
    primary: int = 0x5865F2
    secondary: int = 0x7C5CFC
    success: int = 0x23A559
    warning: int = 0xF0B232
    danger: int = 0xF23F43
    neutral: int = 0x5847EB
    economy: int = 0xF1C40F
    moderation: int = 0xE74C3C
    security: int = 0x9B59B6
    tickets: int = 0x3498DB
    levels: int = 0x2ECC71
    music: int = 0xE91E63
    giveaways: int = 0xF39C12
    invites: int = 0x1ABC9C
    games: int = 0x00BCD4
    ai: int = 0x8E44AD
    verification: int = 0x2ECC71


COLORS = SentriXColors()

# Réglages par défaut du système de design — remplacés à l'exécution par les valeurs
# enregistrées via +designsetup (voir database/db.py::get_design_settings). Toujours
# utiliser get_design_settings(guild_id) plutôt que ces constantes directement dans une
# commande, pour respecter la personnalisation par serveur.
DEFAULT_DESIGN_SETTINGS = {
    "primary_color": COLORS.primary,
    "secondary_color": COLORS.secondary,
    "success_color": COLORS.success,
    "warning_color": COLORS.warning,
    "danger_color": COLORS.danger,
    "footer": "SentriX",
    "show_avatars": True,
    "progress_length": 10,
    "progress_filled": "🟪",
    "progress_empty": "⬛",
    "compact_mode": False,
    "charts_enabled": True,
}

# Modèle visuel par catégorie de commandes (emoji + couleur). Une commande migrée choisit
# sa couleur ici plutôt qu'en dur, pour que toute la catégorie reste cohérente si Jayden
# change une couleur via +designsetup plus tard (évolution possible d'une phase future).
CATEGORY_STYLES = {
    "moderation": {"emoji": "🛡️", "colour": COLORS.moderation},
    "security": {"emoji": "🔐", "colour": COLORS.security},
    "tickets": {"emoji": "🎫", "colour": COLORS.tickets},
    "economy": {"emoji": "💰", "colour": COLORS.economy},
    "levels": {"emoji": "📈", "colour": COLORS.levels},
    "music": {"emoji": "🎵", "colour": COLORS.music},
    "giveaways": {"emoji": "🎉", "colour": COLORS.giveaways},
    "invites": {"emoji": "🔗", "colour": COLORS.invites},
    "utility": {"emoji": "🧰", "colour": COLORS.primary},
    "games": {"emoji": "🎮", "colour": COLORS.games},
    "ai": {"emoji": "🧠", "colour": COLORS.ai},
    "verification": {"emoji": "●", "colour": COLORS.verification},
}

# Icône affichée dans le titre d'un embed selon son état (kind), plutôt que toujours
# l'emoji de la catégorie — sinon un refus/erreur affiché avec ● (emoji de la catégorie
# "verification" par exemple) donne l'impression trompeuse d'une réussite. Seul le kind
# "primary" (information neutre) garde l'emoji de catégorie ; les autres états ont leur
# propre icône universelle, reconnaissable quelle que soit la commande.
KIND_EMOJI = {
    "success": "●",
    "warning": "⚠️",
    "danger": "○",
}


def kind_title(title: str, *, kind: str, category_emoji: str) -> str:
    """Préfixe `title` avec l'icône correspondant à `kind` (●/⚠️/○), ou l'emoji de la
    catégorie si `kind` est "primary" (information neutre, pas de succès/échec à signaler)."""
    emoji = KIND_EMOJI.get(kind, category_emoji)
    return f"{emoji} {title}"


# =============================================================================
# 2. Nombres, dates, barres de progression
# =============================================================================

def format_number(value) -> str:
    """Sépare les milliers par une espace : 1000 -> '1 000'. Fonction UNIQUE à utiliser
    partout — voir aussi utils/stats_service.format_number (identique, conservée pour
    compatibilité avec le code déjà migré en Phase précédente)."""
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    return f"{value:,}".replace(",", " ")


def progress_bar(current: float, maximum: float, length: int = 10, filled: str = "🟪", empty: str = "⬛") -> str:
    if maximum <= 0:
        return empty * length
    ratio = max(0.0, min(current / maximum, 1.0))
    filled_count = round(ratio * length)
    return filled * filled_count + empty * (length - filled_count)


def percentage(current: float, maximum: float) -> int:
    if maximum <= 0:
        return 0
    return max(0, min(round((current / maximum) * 100), 100))


def format_relative_date(dt: Optional[datetime]) -> str:
    """Date Discord dynamique (<t:...:R> ou :D>), robuste si `dt` est None (donnée
    manquante) — dans ce cas on retourne "Inconnu" plutôt qu'une fausse date."""
    if dt is None:
        return "Inconnu"
    return f"<t:{int(dt.timestamp())}:D>"


def format_relative_time(dt: Optional[datetime]) -> str:
    if dt is None:
        return "Inconnu"
    return f"<t:{int(dt.timestamp())}:R>"


# =============================================================================
# 3. Embeds de base
# =============================================================================

def create_embed(
    *,
    title: str,
    description: Optional[str] = None,
    colour: int = COLORS.primary,
    user: Optional[discord.abc.User] = None,
    thumbnail: Optional[str] = None,
    footer: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        colour=discord.Colour(colour),
        timestamp=datetime.now(timezone.utc),
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if user:
        embed.set_footer(text=footer or f"SentriX • demandé par {user}", icon_url=user.display_avatar.url)
    else:
        embed.set_footer(text=footer or "SentriX")
    return embed


def success_embed(message: str, user=None, *, title: str = "● Action réussie") -> discord.Embed:
    return create_embed(title=title, description=message, colour=COLORS.success, user=user)


def error_embed(message: str, user=None, *, title: str = "○ Une erreur est survenue") -> discord.Embed:
    return create_embed(title=title, description=message, colour=COLORS.danger, user=user)


def warning_embed(message: str, user=None, *, title: str = "⚠️ Attention") -> discord.Embed:
    return create_embed(title=title, description=message, colour=COLORS.warning, user=user)


def info_embed(message: str, user=None, *, title: str = "ℹ️ Information") -> discord.Embed:
    return create_embed(title=title, description=message, colour=COLORS.primary, user=user)


def category_embed(category: str, *, title: str, description: Optional[str] = None, user=None, thumbnail=None) -> discord.Embed:
    """Embed pré-coloré selon CATEGORY_STYLES — permet à une commande migrée de ne pas
    avoir à connaître la couleur exacte de sa catégorie."""
    style = CATEGORY_STYLES.get(category, {"emoji": "", "colour": COLORS.primary})
    return create_embed(title=title, description=description, colour=style["colour"], user=user, thumbnail=thumbnail)


# =============================================================================
# 4. Vues interactives communes
# =============================================================================

class SentriXView(discord.ui.View):
    """Vue de base pour tout panneau non-persistant (survit uniquement tant que le bot
    ne redémarre pas — pour les panneaux qui DOIVENT survivre à un redémarrage, garder le
    pattern déjà utilisé par les tickets/vérification/giveaways : custom_id fixe +
    bot.add_view() dans main.py::setup_hook, ou discord.ui.DynamicItem comme /setup).

    Par défaut, seul l'auteur (`author_id`) peut interagir ; si `allowed_staff` est vrai,
    un membre avec la permission "Gérer le serveur" peut aussi utiliser le panneau. Toute
    autre personne reçoit un refus PRIVÉ (ephemeral), jamais visible des autres."""

    def __init__(self, *, author_id: int, allowed_staff: bool = True, timeout: Optional[float] = 180):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.allowed_staff = allowed_staff
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        if self.allowed_staff and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message(
            embed=error_embed("Vous n'êtes pas autorisé à utiliser ce panneau.", interaction.user),
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class CooldownButton(discord.ui.Button):
    """Bouton avec cooldown par utilisateur (ex: 🔄 Actualiser) — évite qu'un membre
    spam-clique et surcharge la base de données. Le cooldown est en mémoire (par
    instance de vue), volontairement simple : pas besoin de le persister en base."""

    def __init__(self, *, cooldown_seconds: float = 5.0, **kwargs):
        super().__init__(**kwargs)
        self.cooldown_seconds = cooldown_seconds
        self._last_use: dict[int, float] = {}

    def is_on_cooldown(self, user_id: int) -> Optional[float]:
        last = self._last_use.get(user_id)
        if last is None:
            return None
        remaining = self.cooldown_seconds - (time.monotonic() - last)
        return remaining if remaining > 0 else None

    def mark_used(self, user_id: int) -> None:
        self._last_use[user_id] = time.monotonic()


class PaginatorView(SentriXView):
    """Pagination générique (◀️ Précédent / ▶️ Suivant / numéro de page) pour toute liste
    trop longue pour un seul embed (ex: listes de paliers, historiques, participants).
    `pages` est une liste d'discord.Embed déjà construits par l'appelant — ce fichier ne
    devine jamais le contenu, il ne fait qu'afficher la page courante."""

    def __init__(self, *, pages: list[discord.Embed], author_id: int, allowed_staff: bool = True, timeout: Optional[float] = 180):
        super().__init__(author_id=author_id, allowed_staff=allowed_staff, timeout=timeout)
        self.pages = pages
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.previous_page.disabled = self.index <= 0
        self.next_page.disabled = self.index >= len(self.pages) - 1
        self.page_label.label = f"{self.index + 1} / {len(self.pages)}"

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)
