"""Fonctions utilitaires génériques réutilisées dans plusieurs cogs."""

import logging
import re
import discord

logger = logging.getLogger("bot")

# Historique (pré-refonte logs indépendants) : colonnes de guild_config pour chaque type
# de log spécialisé. N'est plus utilisé par send_log() ci-dessous (voir utils/log_service.py
# et sa migration automatique depuis ces mêmes colonnes) — conservé pour référence/lecture.
LOG_KIND_COLUMNS = {
    "messages": "log_messages",
    "members": "log_members",
    "voice": "log_voice",
    "roles": "log_roles",
    "server": "log_server",
    "automod": "log_automod",
    "moderation": "log_moderation",
}


async def send_log(bot, guild: discord.Guild, kind: str, embed: discord.Embed) -> None:
    """Compatibilité : délègue désormais entièrement à utils/log_service.py (refonte des
    logs indépendants on/off — voir ce fichier pour la logique réelle). Signature et
    comportement d'appel INCHANGÉS pour tous les appelants existants (configuration.py,
    automod.py, moderation.py, events.py, security_tools.py, tickets.py...) : aucun de
    ces fichiers n'a besoin d'être modifié pour bénéficier du nouveau système on/off,
    puisque `kind` correspond exactement à un `log_type` de log_service.LOG_TYPES."""
    from utils import log_service
    await log_service.send_log(bot, guild, kind, embed)

DURATION_RE = re.compile(r"(\d+)\s*(s|sec|m|min|h|heure|heures|j|jour|jours|d|w|sem|semaine)", re.IGNORECASE)

UNIT_SECONDS = {
    "s": 1, "sec": 1,
    "m": 60, "min": 60,
    "h": 3600, "heure": 3600, "heures": 3600,
    "j": 86400, "jour": 86400, "jours": 86400, "d": 86400,
    "w": 604800, "sem": 604800, "semaine": 604800,
}


def parse_duration(text: str) -> int | None:
    """Convertit '10m', '2h', '1j', '30s' en secondes. Retourne None si invalide."""
    text = text.strip().lower()
    total = 0
    matches = DURATION_RE.findall(text)
    if not matches:
        return None
    for value, unit in matches:
        total += int(value) * UNIT_SECONDS.get(unit, 0)
    return total if total > 0 else None


def format_duration(seconds: int) -> str:
    """Formate un nombre de secondes en texte lisible en français."""
    if seconds <= 0:
        return "0 seconde"
    units = [("jour", 86400), ("heure", 3600), ("minute", 60), ("seconde", 1)]
    parts = []
    remaining = seconds
    for name, size in units:
        value = remaining // size
        if value > 0:
            parts.append(f"{value} {name}{'s' if value > 1 else ''}")
            remaining -= value * size
    return ", ".join(parts[:2]) if parts else "0 seconde"


def truncate(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class ConfirmView(discord.ui.View):
    """Vue de confirmation générique (bouton Oui / Non) utilisée pour les actions sensibles."""

    def __init__(self, author_id: int, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne à l'origine de la commande peut confirmer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="●")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="○")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


class PaginatorView(discord.ui.View):
    """Vue de pagination générique pour les embeds (listes, classements, aide, etc.)."""

    def __init__(self, embeds: list[discord.Embed], author_id: int, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.index = 0
        self._update_buttons()

    def _update_buttons(self):
        self.previous_page.disabled = self.index == 0
        self.next_page.disabled = self.index >= len(self.embeds) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne à l'origine de la commande peut naviguer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.embeds) - 1, self.index + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)
