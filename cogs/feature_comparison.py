"""Compare les fonctionnalités publiques déclarées d'autres bots à celles de SentriX.

Le comparateur ne lit pas les bots tiers, ne copie pas leur code et ne modifie
aucune protection du serveur. Il propose les modules SentriX à examiner.
"""
import json
import logging
import re
import time
import unicodedata

import discord

logger = logging.getLogger("bot.feature-comparison")
_INSTALLED = False

KEYWORDS = {
    "security": ("anti raid", "anti spam", "anti nuke", "anti link", "anti lien", "antispam", "antiraid", "automod", "protection"),
    "surveillance": ("logs", "log", "journal", "invitation", "tracking"),
    "moderation": ("moderation", "warn", "warnings", "ban", "kick", "mute", "timeout", "sanction", "sanctions"),
    "verification": ("captcha", "verification", "verify", "reglement"),
    "tickets": ("ticket", "tickets", "support", "transcript", "transcripts"),
    "staff": ("staff", "permissions", "recrutement"),
    "welcome_goodbye": ("bienvenue", "depart", "welcome", "goodbye", "autorole"),
    "economy": ("economie", "economy", "bank", "banque", "piece", "pieces", "coin", "coins", "boutique"),
    "xp": ("xp", "niveau", "niveaux", "level", "levels", "experience"),
    "games": ("jeu", "jeux", "game", "quiz"),
    "music": ("musique", "music", "playlist", "playlists"),
    "events": ("giveaway", "concours", "evenement"),
    "ai": ("intelligence artificielle", "chatbot", "ia", "ai"),
    "automations": ("automatisation", "reaction", "twitch", "youtube", "tiktok"),
    "advanced": ("suggestion", "backup", "sauvegarde", "starboard", "sticky"),
}
DISPLAY = {
    "security": "Sécurité", "surveillance": "Surveillance",
    "moderation": "Modération", "verification": "Vérification",
    "tickets": "Tickets", "staff": "Staff",
    "welcome_goodbye": "Bienvenue / Départ", "economy": "Économie",
    "xp": "XP", "games": "Jeux", "music": "Musique",
    "events": "Événements", "ai": "IA",
    "automations": "Automatisations", "advanced": "Avancés",
}
SCHEMA = """CREATE TABLE IF NOT EXISTS feature_comparison_reports (
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id BIGINT NOT NULL,
 actor_id BIGINT NOT NULL, source_name TEXT NOT NULL,
 report_json TEXT NOT NULL, created_at BIGINT NOT NULL
)"""


def normalize(value):
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    clean = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[-_]+", " ", clean).split())


def compare_features(raw):
    """Return each feature and suggested modules, plus unsupported requests."""
    if len(str(raw).encode("utf-8")) > 12000:
        raise ValueError("Liste trop longue.")
    features = [x.strip(" \t\r\n-*•") for x in re.split(r"[\n;,]+", str(raw)) if x.strip()]
    if not features:
        raise ValueError("Indiquez au moins une fonctionnalité.")
    if len(features) > 45:
        raise ValueError("Maximum 45 fonctionnalités par comparaison.")
    matched, unknown, seen = [], [], set()
    for feature in features:
        label = feature[:110]
        normalized = " " + normalize(label) + " "
        if normalized in seen:
            continue
        seen.add(normalized)
        module_names = tuple(
            key for key, phrases in KEYWORDS.items()
            if any(re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
                             normalized) for phrase in phrases)
        )
        if module_names:
            matched.append((label, module_names[:3]))
        else:
            unknown.append(label)
    return matched, unknown


def allowed(interaction, guild_id, owner_id):
    member = interaction.user
    return bool(interaction.guild and interaction.guild_id == guild_id
                and member.id == owner_id and
                (interaction.guild.owner_id == member.id
                 or getattr(member.guild_permissions, "administrator", False)))


class ComparisonView(discord.ui.View):
    def __init__(self, bot, guild_id, user_id, name, matched, unknown):
        super().__init__(timeout=300)
        self.bot, self.guild_id, self.user_id = bot, guild_id, user_id
        self.name, self.matched, self.unknown = name, matched, unknown
        self.saved = False

    async def interaction_check(self, interaction):
        if not allowed(interaction, self.guild_id, self.user_id):
            await interaction.response.send_message("Accès administrateur requis.", ephemeral=True)
            return False
        return True

    def embed(self):
        grouped = {}
        for feature, modules in self.matched:
            for module in modules:
                grouped.setdefault(module, []).append(feature)
        lines = []
        for module, features in grouped.items():
            labels = ", ".join(features[:3])
            if len(features) > 3:
                labels += f" (+{len(features)-3})"
            lines.append(f"**{DISPLAY.get(module, module)} :** {discord.utils.escape_markdown(labels)}")
        intro = (
            f"Bot indiqué : **{discord.utils.escape_markdown(self.name)}**\n"
            f"Associations : **{len(self.matched)}** · À étudier : **{len(self.unknown)}**\n\n"
            "Une association indique seulement un module à comparer : "
            "les fonctions exactes ne sont pas automatiquement copiées.\n\n"
            "Modules à consulter dans /setup :\n"
            + ("\n".join(lines)[:2600] or "Aucun module correspondant.")
        )
        e = discord.Embed(title="Comparaison des fonctionnalités",
                          description=intro, colour=discord.Colour.blurple())
        if self.unknown:
            e.add_field(
                name="Fonctions à étudier",
                value="\n".join("• " + discord.utils.escape_markdown(s)
                                for s in self.unknown)[:1024],
                inline=False,
            )
        e.set_footer(text="Aucune configuration du serveur n'a été modifiée.")
        return e

    @discord.ui.button(label="Enregistrer le rapport", style=discord.ButtonStyle.primary)
    async def save(self, interaction, button):
        if self.saved:
            return await interaction.response.send_message("Déjà enregistré.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        payload = json.dumps({"matched": self.matched, "unknown": self.unknown},
                             ensure_ascii=False)
        try:
            await self.bot.db.execute(SCHEMA)
            await self.bot.db.execute(
                "INSERT INTO feature_comparison_reports "
                "(guild_id,actor_id,source_name,report_json,created_at) VALUES (?,?,?,?,?)",
                (self.guild_id, self.user_id, self.name, payload, int(time.time())),
            )
        except Exception:
            logger.exception("Enregistrement de comparaison impossible")
            return await interaction.followup.send("Enregistrement impossible.", ephemeral=True)
        self.saved = True
        button.disabled = True
        await interaction.followup.send(
            "Rapport enregistré. Examinez les modules suggérés dans /setup.",
            ephemeral=True,
        )


class CompareModal(discord.ui.Modal, title="Comparer un bot à SentriX"):
    source_name = discord.ui.TextInput(label="Nom du bot", max_length=80,
                                      placeholder="Ex. DraftBot ou RaidProtect")
    features = discord.ui.TextInput(
        label="Liste des fonctions (une par ligne)",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        placeholder="anti-raid\nlogs de modération\ntickets\nboutique de rôles",
    )

    def __init__(self, bot, guild_id, owner_id):
        super().__init__()
        self.bot, self.guild_id, self.owner_id = bot, guild_id, owner_id

    async def on_submit(self, interaction):
        if not allowed(interaction, self.guild_id, self.owner_id):
            return await interaction.response.send_message(
                "Accès administrateur requis.", ephemeral=True
            )
        try:
            matched, unknown = compare_features(self.features.value)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        view = ComparisonView(self.bot, self.guild_id, self.owner_id,
                              str(self.source_name.value), matched, unknown)
        await interaction.response.send_message(
            embed=view.embed(), view=view, ephemeral=True
        )


def install_for_bot(bot):
    """Expose le comparateur depuis l'accueil réel de /setup, après V117."""
    global _INSTALLED
    if _INSTALLED:
        return
    from cogs.configuration import SetupView
    if getattr(SetupView, "_comparison_installed", False):
        _INSTALLED = True
        return
    previous = SetupView.render_page

    def render(view):
        result = previous(view)
        if getattr(view, "page", None) == -1 and len(view.children) < 25:
            button = discord.ui.Button(
                label="Comparer un autre bot",
                style=discord.ButtonStyle.secondary,
                custom_id="sentrix:setup:compare-features",
            )
            async def callback(interaction):
                if not allowed(interaction, view.guild_id, interaction.user.id):
                    return await interaction.response.send_message(
                        "Accès administrateur requis.", ephemeral=True
                    )
                await interaction.response.send_modal(
                    CompareModal(view.bot, view.guild_id, interaction.user.id)
                )
            button.callback = callback
            try:
                view.add_item(button)
            except ValueError:
                logger.warning("Comparateur non affiché : /setup est plein.")
        return result

    SetupView.render_page = render
    SetupView._comparison_installed = True
    _INSTALLED = True
