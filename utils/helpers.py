"""Fonctions utilitaires génériques réutilisées dans plusieurs cogs."""

import logging
import re
import discord

from utils import embeds

logger = logging.getLogger("bot")

LOG_KIND_COLUMNS = {
    "messages": "log_messages",
    "members": "log_members",
    "voice": "log_voice",
    "roles": "log_roles",
    "server": "log_server",
    "automod": "log_automod",
    "moderation": "log_moderation",
    "tickets": "ticket_log_channel",
}

_SNOWFLAKE_RE = re.compile(r"(?<!\d)(\d{15,22})(?!\d)")
_MESSAGE_URL_RE = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/\d+/\d+/\d+"
)


def _first_id(value: object) -> int | None:
    match = _SNOWFLAKE_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _derive_log_view(embed: discord.Embed):
    """Construit les boutons sûrs pour les anciens logs encore migrés.

    Aucune action administrative n'est créée : uniquement ouverture de message et
    récupération éphémère d'identifiants.
    """
    from utils import log_service

    ids: list[tuple[str, int]] = []
    seen: set[int] = set()
    jump_url = None

    def add(label: str, entity_id: int | None):
        if entity_id is None or entity_id in seen or len(ids) >= 4:
            return
        seen.add(entity_id)
        ids.append((label, entity_id))

    all_text = [str(embed.description or "")]
    for field in embed.fields:
        name = embeds.clean_ui_text(field.name, 80).casefold()
        value = str(field.value or "")
        all_text.append(value)
        entity_id = _first_id(value)
        if not entity_id:
            continue
        if any(token in name for token in ("modérateur", "moderateur", "responsable", "staff", "acteur", "organisé", "organise")):
            add("Copier l'ID du modérateur", entity_id)
        elif "rôle" in name or "role" in name:
            add("Copier l'ID du rôle", entity_id)
        elif "message" in name and ("id" in name or "identifiant" in name):
            add("Copier l'ID du message", entity_id)
        elif "auteur" in name:
            add("Copier l'ID de l'auteur", entity_id)
        elif any(token in name for token in ("membre", "utilisateur", "cible", "créateur", "createur")):
            add("Copier l'ID du membre", entity_id)

    joined = "\n".join(all_text)
    url_match = _MESSAGE_URL_RE.search(joined)
    if url_match:
        jump_url = url_match.group(0)

    return log_service.log_actions(jump_url=jump_url, ids=ids)


def _normalize_log_kind(kind: str, embed: discord.Embed) -> str:
    """Répare les anciens appelants qui classaient un log ticket en modération.

    Certaines branches historiques de fermeture de ticket appelaient
    `helpers.send_log(..., "moderation", ticket_embed)`. Le titre métier permet de les
    router sans ambiguïté vers le logger `tickets`, sans toucher aux vrais logs de modération.
    """
    normalized = str(kind or "").strip().casefold()
    title = embeds.clean_ui_text(embed.title or "", 120).casefold()
    if normalized == "moderation" and "ticket" in title:
        return "tickets"
    return normalized


async def send_log(
    bot,
    guild: discord.Guild,
    kind: str,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> None:
    """Point de compatibilité : tous les anciens appelants passent par le logger officiel."""
    from utils import log_service

    kind = _normalize_log_kind(kind, embed)
    if view is None:
        view = _derive_log_view(embed)
    await log_service.send_log(
        bot,
        guild,
        kind,
        embed,
        view=view,
        event_key=event_key,
    )


DURATION_RE = re.compile(r"(\d+)\s*(s|sec|m|min|h|heure|heures|j|jour|jours|d|w|sem|semaine)", re.IGNORECASE)
UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "m": 60,
    "min": 60,
    "h": 3600,
    "heure": 3600,
    "heures": 3600,
    "j": 86400,
    "jour": 86400,
    "jours": 86400,
    "d": 86400,
    "w": 604800,
    "sem": 604800,
    "semaine": 604800,
}


def parse_duration(text: str) -> int | None:
    text = text.strip().lower()
    total = 0
    matches = DURATION_RE.findall(text)
    if not matches:
        return None
    for value, unit in matches:
        total += int(value) * UNIT_SECONDS.get(unit, 0)
    return total if total > 0 else None


def format_duration(seconds: int) -> str:
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


def confirm_embed(message: str, *, state: str = "pending") -> discord.Embed:
    """Petite box SentriX officielle pour confirmations partagées."""
    if state == "confirmed":
        return embeds.success(message, title="Action confirmée")
    if state == "cancelled":
        return embeds.info(message, title="Action annulée")
    if state == "expired":
        return embeds.warning(message, title="Confirmation expirée")
    return embeds.warning(message, title="Confirmation requise")


def latence_ms(bot, defaut: int = 0) -> int:
    """Latence de la passerelle en millisecondes, jamais NaN.

    `bot.latency` vaut `nan` tant que la passerelle n'a pas recu son premier
    battement — juste apres un demarrage ou une reconnexion. Or `round(nan)` leve
    ValueError, et le repli habituel `float(bot.latency or 0.0)` ne protege PAS :
    NaN est vrai en Python, donc `or` ne se declenche jamais.

    Cinq commandes plantaient ainsi dans les premieres secondes de vie du bot,
    dont +ping — celle qu'on tape justement pour verifier qu'il repond.
    """
    try:
        valeur = float(getattr(bot, "latency", 0.0))
    except (TypeError, ValueError):
        return defaut
    if valeur != valeur or valeur in (float("inf"), float("-inf")):  # NaN ou infini
        return defaut
    return max(0, round(valeur * 1000))


class ConfirmView(discord.ui.View):
    """Confirmation partagée par tout le bot.

    Trois moments etaient muets et le sont moins :

    - une AUTRE personne clique : elle recevait « Seule la personne à l'origine
      peut confirmer » sans savoir quoi faire ; elle sait maintenant que la
      commande lui est ouverte si elle la lance elle-meme ;
    - le delai expire : rien ne se passait, les boutons restaient actifs a l'ecran
      alors qu'ils ne repondaient plus. Ils se desactivent, et le message dit que
      rien n'a ete fait ;
    - apres un clic : les boutons se desactivent aussi, pour qu'on voie que la
      decision est prise.

    `message` est facultatif : renseigne-le apres l'envoi pour que l'expiration
    puisse modifier le message. Sans lui, le comportement reste celui d'avant.
    """

    def __init__(self, author_id: int, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            from utils import sentrix_panels as panels

            await panels.envoyer(
                interaction,
                panels.Panneau(
                    titre="SentriX — Confirmation",
                    sous_titre="Cette confirmation appartient à une autre personne.",
                    kind="warning",
                    sections=[
                        panels.Section(
                            "Pourquoi",
                            [
                                panels.Ligne(
                                    "Sécurité",
                                    "Seul l'auteur d'une commande peut en valider l'effet",
                                    indice="Cela évite qu'un tiers déclenche une action à sa place.",
                                )
                            ],
                        ),
                        panels.Section(
                            "Que faire",
                            [panels.Ligne("Lancez la commande vous-même", "Vous obtiendrez votre propre confirmation")],
                        ),
                    ],
                    pied="SentriX • Confirmation",
                ),
                ephemere=True,
            )
            return False
        return True

    def _figer(self) -> None:
        """Desactive les boutons : une decision prise ne doit plus paraitre cliquable."""
        for enfant in self.children:
            if hasattr(enfant, "disabled"):
                enfant.disabled = True

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self._figer()
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self._figer()
        self.stop()
        await interaction.response.defer()

    async def on_timeout(self) -> None:
        """Le silence n'est pas une reponse : on le dit."""
        self.value = False
        self._figer()
        if self.message is None:
            return
        from utils import sentrix_panels as panels

        expire = panels.Panneau(
            titre="SentriX — Confirmation expirée",
            sous_titre="Aucune action n'a été effectuée.",
            kind="neutral",
            sections=[
                panels.Section(
                    "Ce qui s'est passé",
                    [
                        panels.Ligne("Délai", "La confirmation a expiré sans réponse"),
                        panels.Ligne("Effet", "**Aucun** — rien n'a été modifié"),
                        panels.Ligne("Reprendre", "Relancez la commande pour obtenir une nouvelle confirmation"),
                    ],
                )
            ],
            pied="SentriX • Confirmation",
        )
        try:
            await self.message.edit(
                content=None, embeds=[], view=expire, attachments=expire.fichiers()
            )
        except discord.HTTPException:
            logger.debug("Confirmation expirée : message non modifiable.", exc_info=True)


class PaginatorView(discord.ui.View):
    """Pagination générique qui modifie le message existant."""

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
                embed=embeds.error("Seule la personne à l'origine de la commande peut naviguer."),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.embeds) - 1, self.index + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)
