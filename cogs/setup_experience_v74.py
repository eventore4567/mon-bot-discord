"""SentriX V74 — Setup simplifié, permissions Discord natives et tickets complets.

Objectifs :
- Sécurité : un seul bouton Activer / Désactiver. SentriX applique son profil recommandé.
- Permissions : aucune ACL manuelle dans le Setup principal ; les commandes s'appuient sur
  les permissions Discord réelles et la hiérarchie des rôles.
- Tickets : activation manuelle + accès direct à l'éditeur complet existant
  (texte, image, couleur, types/boutons, formulaires, support, salons, logs, etc.).
- Modération : plus de "rôle staff" ambigu. On peut préparer un vrai rôle Discord de
  modération avec un profil de permissions et, optionnellement, l'attribuer à un membre.
  Les rôles "mute" et "warn" deviennent des badges automatiques réellement utilisés.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import discord
from discord.ext import commands

from cogs import language_runtime
from utils import ai_service, embeds
from utils import sentrix_panels as panels
from . import security_verification_v71 as security_v71
from . import setup_components_v73 as v73
from . import setup_control_center as setup_ui
from . import setup_ticket_autoconfig_v72 as v72
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-experience-v74")

RUNTIME_MARKER = "Setup Experience V74"

CATEGORY_ORDER = (
    "moderation",
    "security",
    "tickets",
    "welcome",
    "goodbye",
    "roles",
    "logs",
    "levels",
    "economy",
    "notifications",
    "music",
    "ai",
)

CATEGORY_META = dict(v73.CATEGORY_META)
CATEGORY_META["moderation"] = (
    "🛡️",
    "Modération",
    "Permissions Discord réelles, profils de modération et badges de sanctions.",
)
CATEGORY_META["security"] = (
    "🔒",
    "Sécurité",
    "Choisissez les protections adaptées à votre serveur dans la page Sécurité.",
)
CATEGORY_META["music"] = (
    "🎵",
    "Musique",
    "Choisissez le vocal musique puis activez le lecteur SentriX.",
)
CATEGORY_META["tickets"] = (
    "🎫",
    "Tickets",
    "Activation manuelle et personnalisation complète du panel et de ses boutons.",
)

CATEGORY_META["levels"] = ("📈", "Niveaux & réputation", "XP, activité, vocal, progression et récompenses de niveau.")
CATEGORY_META["economy"] = ("💰", "Économie", "Monnaie, récompenses, métiers, banque, boutique et jeux.")

SECURITY_BOT_PERMISSIONS = (
    ("view_channel", "Voir les salons"),
    ("send_messages", "Envoyer des messages"),
    ("embed_links", "Intégrer des liens"),
    ("read_message_history", "Voir l’historique"),
    ("manage_messages", "Gérer les messages"),
    ("moderate_members", "Exclure temporairement des membres"),
    ("kick_members", "Expulser des membres"),
    ("ban_members", "Bannir des membres"),
    ("manage_channels", "Gérer les salons"),
    ("manage_roles", "Gérer les rôles"),
    ("manage_guild", "Gérer le serveur"),
    ("manage_webhooks", "Gérer les webhooks"),
    ("view_audit_log", "Voir le journal d’audit"),
)

MODERATION_PROFILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "helper": (
        "Helper",
        (
            "manage_messages",
            "manage_nicknames",
        ),
    ),
    "moderator": (
        "Modérateur",
        (
            "manage_messages",
            "manage_nicknames",
            "moderate_members",
            "kick_members",
            "move_members",
        ),
    ),
    "senior": (
        "Responsable modération",
        (
            "manage_messages",
            "manage_nicknames",
            "moderate_members",
            "kick_members",
            "ban_members",
            "move_members",
            "manage_channels",
        ),
    ),
}


def _bot_permission_audit(guild: discord.Guild) -> tuple[list[str], list[str]]:
    me = guild.me
    if me is None:
        return [], ["SentriX n’est pas visible comme membre du serveur."]
    ok: list[str] = []
    missing: list[str] = []
    perms = me.guild_permissions
    for attr, label in SECURITY_BOT_PERMISSIONS:
        (ok if getattr(perms, attr, False) else missing).append(label)
    return ok, missing


def _role_from_config(guild: discord.Guild, value: Any) -> discord.Role | None:
    try:
        role = guild.get_role(int(value)) if value else None
    except (TypeError, ValueError):
        return None
    if role is None or role.is_default() or role.managed:
        return None
    return role


async def _set_optional_role(view: "SentriXSetupV74", field: str, role: discord.Role | None) -> None:
    await view.bot.db.set_guild_config(view.guild.id, field, role.id if role else None)


class IdentiteBotModal(discord.ui.Modal, title="SentriX sur ce serveur"):
    """Avatar et bannière de SentriX **pour ce serveur uniquement**.

    Discord distingue deux identités pour une application :

    - l'identité GLOBALE (`bot.user.edit`), partagée par les 37 serveurs. Un
      administrateur ne doit pas pouvoir la changer : il modifierait
      l'apparence de SentriX chez tous les autres. Elle reste réservée au
      propriétaire, via `+set-bot` ;
    - le PROFIL DE SERVEUR (`guild.me.edit`), propre à ce serveur seul. Les
      autres continuent de voir l'original. C'est celui-ci qu'on édite ici,
      et c'est pour ça que l'administrateur du serveur y a droit.

    Les deux champs sont facultatifs : seuls ceux qui sont remplis sont
    appliqués. Un échec sur l'un n'empêche pas les autres, et le compte rendu
    nomme la cause — une réponse « ça n'a pas marché » serait inutilisable
    pour une image hébergée ailleurs.
    """

    avatar = discord.ui.TextInput(
        label="URL de l'avatar (vide = inchangé)",
        required=False, placeholder="https://…", max_length=500,
    )
    banniere = discord.ui.TextInput(
        label="URL de la bannière", required=False, placeholder="https://…", max_length=500,
    )
    def __init__(self, vue):
        super().__init__()
        self.vue = vue

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.owner import fetch_image_bytes

        moi = interaction.guild.me if interaction.guild else None
        if moi is None:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Cette action s'utilise sur un serveur.")),
                ephemere=True,
            )
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        faits, echecs = [], []
        changements = {}
        for champ, saisie in (("avatar", self.avatar), ("bannière", self.banniere)):
            url = str(saisie.value or "").strip()
            if not url:
                continue
            donnees = await fetch_image_bytes(url)
            if not donnees:
                echecs.append(f"{champ} (image introuvable à cette adresse)")
                continue
            changements["avatar" if champ == "avatar" else "banner"] = donnees
        for cle, valeur in changements.items():
            nom = {"avatar": "avatar", "banner": "bannière"}[cle]
            try:
                await moi.edit(**{cle: valeur})
                faits.append(nom)
            except discord.HTTPException as exc:
                echecs.append(f"{nom} ({exc.text or exc})")

        if not faits and not echecs:
            texte = "Aucun champ rempli : rien n'a été changé."
        else:
            lignes = []
            if faits:
                lignes.append(
                    "✅ Mis à jour **sur ce serveur uniquement** : " + ", ".join(faits)
                )
                lignes.append(
                    "-# Les autres serveurs continuent de voir l'apparence d'origine."
                )
            if echecs:
                lignes.append("❌ Échec : " + " · ".join(echecs))
            texte = "\n".join(lignes)
        await panels.envoyer(
            interaction.followup,
            panels.depuis_embed(embeds.info(texte, title="SentriX sur ce serveur")),
            ephemere=True,
        )


#: Configuration guidée (brief V6, point 20) : les pages EXISTANTES dans cet
#: ordre. Ouvrir une page n'active rien ; chaque page garde son propre bouton
#: d'activation explicite. L'étape est enregistrée : on quitte et on reprend.
GUIDE: tuple[tuple[str, str], ...] = (
    ("security", "Sécurité"),
    ("logs", "Logs"),
    ("tickets", "Tickets"),
    ("welcome", "Bienvenue"),
    ("roles", "Rôles"),
)
_GUIDE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS setup_guide_progress ("
    "guild_id INTEGER PRIMARY KEY, step INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
)


async def guide_step_saved(bot, guild_id: int) -> int | None:
    await bot.db.execute(_GUIDE_SCHEMA)
    row = await bot.db.fetchone("SELECT step FROM setup_guide_progress WHERE guild_id=?", (int(guild_id),))
    if row is None:
        return None
    step = int(row["step"])
    return step if 0 <= step < len(GUIDE) else None


async def guide_save_step(bot, guild_id: int, step: int | None) -> None:
    import time as _time

    await bot.db.execute(_GUIDE_SCHEMA)
    if step is None:
        await bot.db.execute("DELETE FROM setup_guide_progress WHERE guild_id=?", (int(guild_id),))
        return
    await bot.db.execute(
        "INSERT INTO setup_guide_progress (guild_id, step, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET step=excluded.step, updated_at=excluded.updated_at",
        (int(guild_id), int(step), int(_time.time())),
    )


#: 22/11/2026 : les 22 réglages de l'ancien menu, rangés en six sections.
#: (clé, nom, nom anglais, icône SentriX, description, description anglaise, pages)
SECTIONS = (
    ("securite", "Sécurité", "Security", "security",
     "Anti-raid, anti-nuke, AutoMod et vérification des arrivants.",
     "Anti-raid, anti-nuke, AutoMod and member verification.",
     ("security", "rules_access")),
    ("moderation", "Modération", "Moderation", "mod",
     "Sanctions, journaux et suivi des invitations.",
     "Sanctions, logs and invite tracking.",
     ("moderation", "logs", "invitations")),
    ("communaute", "Communauté", "Community", "member_join",
     "Accueil, départs, rôles, suggestions et notifications.",
     "Welcome, goodbye, roles, suggestions and notifications.",
     ("welcome", "goodbye", "roles", "suggestions", "notifications")),
    ("engagement", "Engagement", "Engagement", "level",
     "Niveaux, économie et musique.",
     "Levels, economy and music.",
     ("levels", "economy", "music")),
    ("outils", "Outils", "Tools", "tools",
     "Tickets, embeds, commandes et messages automatiques.",
     "Tickets, embeds, commands and automatic messages.",
     ("tickets", "embeds", "custom_commands", "snippets", "recurring_messages", "automation")),
    ("systeme", "Système", "System", "settings",
     "Intelligence artificielle, préfixes et langue.",
     "Artificial intelligence, prefixes and language.",
     ("ai", "prefixes", "language")),
)

#: Réglages hors modules : nom, description, nom anglais, description anglaise.
EXTRAS = {
    "rules_access": ("Règlement et vérification", "Règles, CAPTCHA, rôles et accès aux salons",
                     "Rules & verification", "Rules, CAPTCHA, roles and channel access"),
    "suggestions": ("Suggestions", "Salon, votes et modération des idées",
                    "Suggestions", "Channel, voting and moderation"),
    "embeds": ("Créer un embed", "Texte, images, couleurs et boutons",
               "Embed builder", "Text, images, colours and buttons"),
    "custom_commands": ("Commandes personnalisées", "Créer ses propres commandes",
                        "Custom commands", "Create your own commands"),
    "prefixes": ("Préfixes", "Préfixes officiels et personnalisés, séparés",
                 "Prefixes", "Separate official and custom prefixes"),
    "snippets": ("Messages enregistrés", "Préparer des messages à réutiliser",
                 "Saved messages", "Prepare reusable messages"),
    "recurring_messages": ("Messages programmés", "Réglages des publications automatiques",
                           "Scheduled messages", "Automatic posts"),
    "automation": ("Automatisations", "Règles et actions automatiques",
                   "Automations", "Automation rules and actions"),
    "language": ("Langue du serveur", "Français ou English",
                 "Server language", "French or English"),
}

NOMS_EN = {
    "security": "Security", "moderation": "Moderation", "roles": "Roles", "ai": "AI",
    "levels": "Levels", "economy": "Economy", "welcome": "Welcome", "goodbye": "Goodbye",
    "antispam": "Anti-spam", "tickets": "Tickets", "logs": "Logs",
    "notifications": "Notifications", "music": "Music", "invitations": "Invites",
}


class SentriXSetupV74(v73.SentriXSetupV73):
    """Dernière façade du Setup : simple pour la sécurité, complète pour les tickets."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild, author_id: int):
        super().__init__(bot, guild, author_id)
        self._author_member = guild.get_member(int(author_id))
        self.moderation_role_id: int | None = None
        self.moderation_member_id: int | None = None
        self.moderation_profile = "moderator"
        self.avance = False
        self._category_meta = CATEGORY_META
        self._separate_economy = True
        self.guide_step: int | None = None

    async def rebuild(self) -> None:
        await super().rebuild()
        # Le Setup est reconstruit après chaque clic. Sans cette passe finale,
        # certaines pages repassaient en français après avoir choisi English.
        language = await language_runtime.get_language(self.bot, self.guild.id)
        if language == language_runtime.LANG_EN:
            # Le nom du serveur est protégé ICI aussi : cette passe est plus
            # proche que le transport, donc c'est elle qui décide. Sans ça,
            # « Serveur test » devenait « Server test » dans +setup — la
            # traduction écrivait dans une donnée de l'utilisateur.
            protection = tuple(
                v for v in (
                    getattr(self.guild, "name", None),
                    getattr(getattr(self.guild, "me", None), "display_name", None),
                ) if v
            )
            language_runtime.translate_view_in_place(self, setup=True, protect=protection)

    async def _effective_states(self) -> dict[str, str]:
        states = await super()._effective_states()

        states["moderation"] = (
            "● ACTIF"
            if await core.module_enabled(self.bot, self.guild.id, "moderation")
            else "○ INACTIF"
        )
        states["security"] = (
            "○ INACTIF"
            if not await core.module_enabled(self.bot, self.guild.id, "security")
            else "● ACTIF"
            if await setup_ui.security_protections_actives(self.bot, self.guild.id)
            else "— À CONFIGURER"
        )
        if await core.module_enabled(self.bot, self.guild.id, "tickets"):
            states["tickets"] = (
                "● ACTIF"
                if await v72.ticket_configuration_ready(self.bot, self.guild)
                else "— À CONFIGURER"
            )
        else:
            states["tickets"] = "○ INACTIF"
        music = self.bot.get_cog("Music")
        if music is None:
            states["music"] = "! À CORRIGER"
        else:
            music_settings = await music.get_system_settings(self.guild.id)
            states["music"] = (
                "● ACTIF"
                if music_settings.get("enabled")
                else "○ INACTIF"
                if music_settings.get("voice_channel_id")
                else "— À CONFIGURER"
            )
        states.pop("permissions", None)
        return states

    async def _est_proprietaire_du_bot(self) -> bool:
        """Le propriétaire de SentriX, pas l'administrateur du serveur.

        Rendre False en cas de doute : mieux vaut ne pas afficher le bouton
        que de laisser un admin changer l'apparence globale du bot.
        """
        try:
            from config import OWNER_IDS
            from database.db import PRIMARY_CREATOR_ID

            uid = int(self.author_id)
            if uid == PRIMARY_CREATOR_ID or uid in OWNER_IDS:
                return True
            return bool(await self.bot.db.is_bot_creator(uid))
        except Exception:
            logger.debug("Propriétaire du bot indéterminé.", exc_info=True)
            return False

    async def _open_embed_builder(self, interaction: discord.Interaction) -> None:
        """L'éditeur de +embed, ouvert en privé depuis le Setup."""
        cog = self.bot.get_cog("EmbedBuilder")
        if cog is None:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.warning("L’éditeur d’embeds n’est pas chargé.")),
                ephemere=True,
            )
        await cog.open_builder_from_interaction(interaction)

    async def _build_home(self) -> None:
        """Accueil : l'état du serveur, six sections, et un bouton pour tout protéger.

        22/11/2026 : « refais tout le setup, plus simple, plus beau ». L'accueil
        alignait un menu de 22 entrées sans ordre. Les mêmes pages sont rangées
        en six sections ; chaque section liste ses réglages avec leur état.
        Aucun réglage n'a changé de place : seul le chemin pour y arriver.
        """
        from utils import sentrix_emojis as icons
        from . import securite_simple

        english = (
            await language_runtime.get_language(self.bot, self.guild.id)
            == language_runtime.LANG_EN
        )
        self.backend.category = None
        self.avance = False
        self._section = None

        states = await setup_ui.module_switch_states(self.bot, self.guild.id)
        labels = dict(setup_ui.MODULE_SWITCHES)
        actifs = [key for key in labels if states.get(key) == "enabled"]
        a_terminer = [key for key in labels if states.get(key) in {"empty", "not_configured"}]
        resume = await self._resume_protection(english)
        protegees, total = resume["protegees"], resume["total"]

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(
                (
                    "# SentriX setup\n"
                    f"**{self.guild.name}** · {len(actifs)} of {len(labels)} modules enabled"
                ) if english else (
                    "# Configuration SentriX\n"
                    f"**{self.guild.name}** · {len(actifs)} modules actifs sur {len(labels)}"
                )
            ),
            accessory=v73._thumbnail(self.bot),
        ))
        container.add_item(discord.ui.Separator())

        lignes = [
            ("### 🛡️ Protection" if english else "### 🛡️ Protection du serveur"),
            resume["ligne"],
        ]
        if a_terminer:
            noms = ", ".join(self._nom_cle(key, english) for key in a_terminer)
            lignes.append(("-# To finish: " if english else "-# À terminer : ") + noms)
        container.add_item(discord.ui.TextDisplay("\n".join(lignes)))
        container.add_item(discord.ui.Separator())

        boutons = []
        for cle, nom_fr, nom_en, icone, _desc_fr, _desc_en, _pages in SECTIONS:
            bouton = discord.ui.Button(
                label=nom_en if english else nom_fr,
                style=discord.ButtonStyle.secondary,
                emoji=icons.partiel(icone) or None,
            )

            async def ouvrir_section(interaction: discord.Interaction, _cle=cle):
                self._section = _cle
                self.page = f"section:{_cle}"
                self.backend = self._new_backend(None)
                await self.refresh(interaction)

            bouton.callback = ouvrir_section
            boutons.append(bouton)
        container.add_item(discord.ui.ActionRow(*boutons[:3]))
        container.add_item(discord.ui.ActionRow(*boutons[3:]))
        container.add_item(discord.ui.Separator())

        tout = discord.ui.Button(
            label=(
                ("All protections on" if english else "Toutes les protections sont actives")
                if protegees == total
                else ("Turn on every protection" if english else "Activer toutes les protections")
            ),
            style=discord.ButtonStyle.success,
            emoji=icons.partiel("security") or None,
            disabled=protegees == total,
        )

        async def tout_activer(interaction: discord.Interaction):
            await securite_simple._activer(self, interaction)

        tout.callback = tout_activer
        close = discord.ui.Button(
            label="Close" if english else "Fermer",
            style=discord.ButtonStyle.secondary,
            emoji=icons.partiel("close"),
        )

        async def fermer(interaction: discord.Interaction):
            await self._close(interaction)

        close.callback = fermer
        container.add_item(discord.ui.ActionRow(tout, close))
        self.add_item(container)

    async def _resume_protection(self, english: bool) -> dict:
        """État de protection du serveur, lu comme il agit vraiment.

        Partagé par l'accueil et la section Sécurité : module compris (revue
        Codex PR #714) et permissions de SentriX comprises (même diagnostic que
        la page Sécurité) — on ne dit « protégé » que si tout est opérationnel.
        """
        from utils.protection_requirements import diagnostic
        from . import securite_simple

        protections = await securite_simple.etats(self)
        protegees = sum(1 for actif in protections.values() if actif)
        total = len(protections) or 1
        permissions = self.guild.me.guild_permissions if self.guild.me else discord.Permissions.none()
        inertes, degradees = diagnostic(permissions, {cle for cle, actif in protections.items() if actif})
        bridees = len(inertes) + len(degradees)
        pleins = round(10 * protegees / total)
        barre = "🟩" * pleins + "⬜" * (10 - pleins)
        if protegees == total and bridees:
            verdict = (
                f"⚠️ {bridees} limited by SentriX's missing permissions (see Security)." if english
                else f"⚠️ {bridees} bridée(s) par des permissions manquantes de SentriX (voir Sécurité)."
            )
        elif protegees == total:
            verdict = "Server protected." if english else "Serveur protégé."
        else:
            verdict = (
                f"{total - protegees} protection(s) off." if english
                else f"{total - protegees} protection(s) coupée(s)."
            )
        return {
            "protections": protections, "protegees": protegees, "total": total,
            "bridees": bridees, "inertes": inertes, "degradees": degradees,
            "ligne": f"{barre}  **{protegees}/{total}** · {verdict}",
        }

    def _nom_cle(self, cle: str, english: bool) -> str:
        if cle in EXTRAS:
            return EXTRAS[cle][2] if english else EXTRAS[cle][0]
        nom = CATEGORY_META.get(cle, ("", cle))[1]
        return NOMS_EN.get(cle, nom) if english else nom

    async def _build_section(self, cle: str) -> None:
        """Une section : ses réglages, chacun avec son état et un bouton Ouvrir."""
        from utils import sentrix_emojis as icons

        section = next((s for s in SECTIONS if s[0] == cle), None)
        if section is None:
            self.page = None
            return await self._build_home()
        # Toute entrée dans une section la mémorise (pas seulement le bouton de
        # l'accueil) : « Retour » depuis un réglage doit y revenir.
        self._section = cle
        _cle, nom_fr, nom_en, icone, desc_fr, desc_en, pages = section
        english = (
            await language_runtime.get_language(self.bot, self.guild.id)
            == language_runtime.LANG_EN
        )
        if cle == "securite":
            return await self._build_section_securite(english)
        if cle == "moderation":
            return await self._build_section_moderation(english)
        states = await setup_ui.module_switch_states(self.bot, self.guild.id)
        etats_detail = await self._effective_states()

        def etat(page: str) -> str:
            value = states.get(page)
            if value is None and page in etats_detail:
                detail = str(etats_detail.get(page, "")).upper()
                value = "disabled" if "INACTIF" in detail else ("enabled" if "ACTIF" in detail else "not_configured")
            if value is None:
                return ""
            return {
                "enabled": ("🟢 Enabled", "🟢 Actif"),
                "disabled": ("⚪ Disabled", "⚪ Désactivé"),
                "empty": ("🟠 To set up", "🟠 À configurer"),
                "not_configured": ("🟠 To set up", "🟠 À configurer"),
            }[value][0 if english else 1]

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(discord.ui.TextDisplay(
            f"# {icons.titre(icone, nom_en if english else nom_fr)}\n"
            + (desc_en if english else desc_fr)
        ))
        container.add_item(discord.ui.Separator())
        for page in pages:
            if page in EXTRAS:
                description = EXTRAS[page][3] if english else EXTRAS[page][1]
            else:
                description = CATEGORY_META.get(page, ("", page, ""))[2]
                if english:
                    description = language_runtime.english_ui_text(description, setup=True) or description
            statut = etat(page)
            texte = f"**{self._nom_cle(page, english)}**" + (f" · {statut}" if statut else "")
            texte += f"\n-# {description}"
            ouvrir = discord.ui.Button(label="Open" if english else "Ouvrir", style=discord.ButtonStyle.primary)

            async def aller(interaction: discord.Interaction, _page=page):
                await self._ouvrir_page(interaction, _page, english)

            ouvrir.callback = aller
            container.add_item(discord.ui.Section(discord.ui.TextDisplay(texte), accessory=ouvrir))

        retour = discord.ui.Button(label="Back" if english else "Retour", style=discord.ButtonStyle.secondary, emoji="↩️")

        async def accueil(interaction: discord.Interaction):
            self._section = None
            self.page = None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        retour.callback = accueil
        fermer = discord.ui.Button(label="Close" if english else "Fermer", style=discord.ButtonStyle.secondary)

        async def clore(interaction: discord.Interaction):
            await self._close(interaction)

        fermer.callback = clore
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(retour, fermer))
        self.add_item(container)

    async def _build_section_securite(self, english: bool) -> None:
        """Section Sécurité, tout-en-un (22/11/2026, étape 2 de la refonte).

        Avant : Accueil → Sécurité → « Ouvrir » → panneau → « Personnaliser » →
        protection → « Activer ». Ici, les huit protections sont des boutons :
        un clic les allume ou les coupe. Le mode raid, les mots bloqués, les
        réglages avancés et la vérification sont à un clic.
        """
        from utils import sentrix_emojis as icons
        from . import securite_simple

        self._securite_mode = "simple"  # « Réglages avancés » ne doit pas rester collé
        resume = await self._resume_protection(english)
        protections = resume["protections"]
        module = await securite_simple._module_securite_actif(self)
        arme = securite_simple._raid_arme(self)

        container = discord.ui.Container(accent_colour=0xED4245 if arme else 0x6C57CC)
        v73.poser_banniere(container)
        lignes = [f"# {icons.titre('security', 'Security' if english else 'Sécurité')}", resume["ligne"]]
        if not module:
            lignes.append(
                "-# The Security module is off: no protection runs. « Turn on every protection » restores it."
                if english else
                "-# Le module Sécurité est coupé : aucune protection ne tourne. « Activer toutes les protections » le rallume."
            )
        if arme:
            lignes.append(
                "🔴 **Raid mode ARMED** — every new member is kicked." if english
                else "🔴 **Mode raid ARMÉ** — chaque nouvel arrivant est expulsé."
            )
        container.add_item(discord.ui.TextDisplay("\n".join(lignes)))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "### Protections\n-# Green = on. One click turns it on or off." if english
            else "### Protections\n-# Vert = active. Un clic l'allume ou la coupe."
        ))

        boutons = []
        for cle, nom in securite_simple.PROTECTION_RECOMMANDEE:
            court = dict(securite_simple.PROTECTION_COURTE).get(cle, cle)
            actif = protections.get(cle, False)
            bouton = discord.ui.Button(
                label=court[:1].upper() + court[1:],
                style=discord.ButtonStyle.success if actif else discord.ButtonStyle.secondary,
                emoji="✅" if actif else None,
            )

            async def basculer(interaction: discord.Interaction, _cle=cle, _actif=actif):
                if not interaction.response.is_done():
                    await interaction.response.defer()
                await securite_simple.basculer_protection(
                    self, _cle, not _actif, actor_id=interaction.user.id,
                )
                await self.refresh(interaction)

            bouton.callback = basculer
            boutons.append(bouton)
        container.add_item(discord.ui.ActionRow(*boutons[:4]))
        container.add_item(discord.ui.ActionRow(*boutons[4:8]))
        container.add_item(discord.ui.Separator())

        tout = discord.ui.Button(
            label="Turn on every protection" if english else "Activer toutes les protections",
            style=discord.ButtonStyle.success,
            emoji=icons.partiel("security") or None,
            disabled=module and resume["protegees"] == resume["total"],
        )

        async def tout_activer(interaction: discord.Interaction):
            await securite_simple._activer(self, interaction)

        tout.callback = tout_activer
        raid = discord.ui.Button(
            label=("Raid mode: ARMED" if english else "Mode raid : ARMÉ") if arme else ("Raid mode" if english else "Mode raid"),
            style=discord.ButtonStyle.danger if arme else discord.ButtonStyle.secondary,
            emoji=icons.partiel("shield") or None,
        )

        async def basculer_raid(interaction: discord.Interaction):
            await securite_simple._basculer_mode_raid(self, interaction)

        raid.callback = basculer_raid
        mots = discord.ui.Button(label="Blocked words" if english else "Mots bloqués", style=discord.ButtonStyle.secondary)

        async def ouvrir_mots(interaction: discord.Interaction):
            from . import mots_bloques

            await mots_bloques.ouvrir(interaction, self.guild)

        mots.callback = ouvrir_mots
        container.add_item(discord.ui.ActionRow(tout, raid, mots))

        avance = discord.ui.Button(
            label="Advanced settings" if english else "Réglages avancés",
            style=discord.ButtonStyle.secondary, emoji=icons.partiel("settings") or None,
        )

        async def ouvrir_avance(interaction: discord.Interaction):
            # Le panneau complet, directement sur l'écran « Personnaliser » :
            # exceptions, sanctions, admins épargnés, liste blanche anti-nuke…
            self._securite_mode = "detail"
            await self._ouvrir_page(interaction, "security", english)

        avance.callback = ouvrir_avance
        verification = discord.ui.Button(
            label=self._nom_cle("rules_access", english),
            style=discord.ButtonStyle.secondary, emoji=icons.partiel("note") or None,
        )

        async def ouvrir_verification(interaction: discord.Interaction):
            await self._ouvrir_page(interaction, "rules_access", english)

        verification.callback = ouvrir_verification
        container.add_item(discord.ui.ActionRow(avance, verification))

        retour = discord.ui.Button(label="Back" if english else "Retour", style=discord.ButtonStyle.secondary, emoji="↩️")

        async def accueil(interaction: discord.Interaction):
            self._section = None
            self.page = None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        retour.callback = accueil
        fermer = discord.ui.Button(label="Close" if english else "Fermer", style=discord.ButtonStyle.secondary)

        async def clore(interaction: discord.Interaction):
            await self._close(interaction)

        fermer.callback = clore
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(retour, fermer))
        self.add_item(container)

    async def _build_section_moderation(self, english: bool) -> None:
        """Section Modération (22/11/2026, étape 3 de la refonte).

        Les trois pages (Modération, Logs, Invitations) font déjà 22 à 25
        composants chacune : les fusionner dépasserait la limite Discord de 40.
        La section résume donc chacune, avec ses réglages les plus utiles sur
        place, et un bouton vers le détail :
        - le seuil de ban automatique, réglable ici ;
        - « Envoyer tous les logs non configurés dans… » : un seul choix au lieu
          d'aller-retours catégorie par catégorie ;
        - l'état des deux salons d'invitations.
        """
        from utils import log_service, sentrix_emojis as icons
        from . import invite_tracker_runtime as invitations, setup_moderation_clear_v76 as moderation

        t = (lambda fr, en: en) if english else (lambda fr, en: fr)
        conf = await self.bot.db.get_guild_config(self.guild.id)
        try:
            seuil = int(setup_ui._get(conf, "warn_ban_threshold") or 0)
        except (TypeError, ValueError):
            seuil = 0
        dm_rows = await moderation._dm_settings(self)
        dm_actifs = sum(
            1 for action, _label in moderation.DM_ACTIONS
            if action not in dm_rows or bool(moderation._row_value(dm_rows.get(action), "enabled", 1))
        )

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(discord.ui.TextDisplay(
            f"# {icons.titre('mod', t('Modération', 'Moderation'))}\n"
            + t("Sanctions, journaux et suivi des invitations.", "Sanctions, logs and invite tracking.")
        ))

        # — Modération
        container.add_item(discord.ui.Separator())
        texte_seuil = (
            t(f"ban automatique après **{seuil} avertissements**", f"automatic ban after **{seuil} warnings**")
            if seuil > 0 else t("ban automatique **désactivé**", "automatic ban **off**")
        )
        messages = discord.ui.Button(label=t("Messages de sanction", "Sanction messages"), style=discord.ButtonStyle.secondary)

        async def ouvrir_moderation(interaction: discord.Interaction):
            await self._ouvrir_page(interaction, "moderation", english)

        messages.callback = ouvrir_moderation
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(
                f"### ⚖️ {t('Sanctions', 'Sanctions')}\n"
                f"{texte_seuil[:1].upper() + texte_seuil[1:]} · "
                + t(f"MP de sanction : **{dm_actifs}/{len(moderation.DM_ACTIONS)}**",
                    f"Sanction DMs: **{dm_actifs}/{len(moderation.DM_ACTIONS)}**")
            ),
            accessory=messages,
        ))
        seuil_select = discord.ui.Select(
            placeholder=t("Ban automatique après…", "Automatic ban after…"),
            options=[
                discord.SelectOption(label=t("Désactivé", "Off"), value="0", default=seuil == 0),
                *(
                    discord.SelectOption(
                        label=t(f"{n} avertissements", f"{n} warnings"), value=str(n), default=seuil == n,
                    )
                    for n in (2, 3, 4, 5)
                ),
            ],
        )

        async def regler_seuil(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self.bot.db.set_guild_config(self.guild.id, "warn_ban_threshold", int(seuil_select.values[0]))
            await self.refresh(interaction)

        seuil_select.callback = regler_seuil
        container.add_item(discord.ui.ActionRow(seuil_select))

        # — Logs
        container.add_item(discord.ui.Separator())
        reglages = {
            cle: await log_service.get_log_setting(self.bot, self.guild.id, cle)
            for cle in log_service.CATEGORY_KEYS
        }
        configurees = [cle for cle, r in reglages.items() if r.get("channel_id") and r.get("enabled")]
        manquantes = [cle for cle in log_service.CATEGORY_KEYS if cle not in configurees]
        detail = discord.ui.Button(label=t("Réglages détaillés", "Detailed settings"), style=discord.ButtonStyle.secondary)

        async def ouvrir_logs(interaction: discord.Interaction):
            await self._ouvrir_page(interaction, "logs", english)

        detail.callback = ouvrir_logs
        ligne_logs = t(
            f"**{len(configurees)}/{len(reglages)}** catégories envoyées dans un salon.",
            f"**{len(configurees)}/{len(reglages)}** categories sent to a channel.",
        )
        if manquantes:
            noms = ", ".join(log_service.CATEGORIES.get(cle, cle) for cle in manquantes[:6])
            ligne_logs += "\n-# " + t("Sans salon : ", "No channel: ") + noms + ("…" if len(manquantes) > 6 else "")
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(f"### 📜 {t('Logs du serveur', 'Server logs')}\n{ligne_logs}"),
            accessory=detail,
        ))
        if manquantes:
            tous = discord.ui.ChannelSelect(
                placeholder=t(
                    f"Envoyer les {len(manquantes)} catégories sans salon dans…",
                    f"Send the {len(manquantes)} unconfigured categories to…",
                ),
                min_values=1, max_values=1,
                channel_types=[discord.ChannelType.text],
            )

            async def tout_router(interaction: discord.Interaction):
                await self._router_logs_manquants(interaction, tous.values[0].id, manquantes, english)

            tous.callback = tout_router
            container.add_item(discord.ui.ActionRow(tous))

        # — Invitations
        container.add_item(discord.ui.Separator())
        await invitations.ensure_schema(self.bot)
        flux = await invitations.get_feed_setting(self.bot, self.guild.id)
        logs_invit = await log_service.get_log_setting(self.bot, self.guild.id, invitations.CATEGORY)

        def salon(identifiant) -> str:
            canal = self.guild.get_channel(int(identifiant)) if identifiant else None
            return canal.mention if canal else t("aucun", "none")

        ouvrir_invit = discord.ui.Button(label=t("Ouvrir", "Open"), style=discord.ButtonStyle.secondary)

        async def ouvrir_invitations(interaction: discord.Interaction):
            await self._ouvrir_page(interaction, "invitations", english)

        ouvrir_invit.callback = ouvrir_invitations
        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(
                f"### 🔗 {t('Invitations', 'Invites')}\n"
                + t("Salon public : ", "Public channel: ") + salon(flux.get("feed_channel_id"))
                + (" 🟢" if flux.get("feed_enabled") and flux.get("feed_channel_id") else " ⚪")
                + " · " + t("Logs : ", "Logs: ") + salon(logs_invit.get("channel_id"))
            ),
            accessory=ouvrir_invit,
        ))

        retour = discord.ui.Button(label=t("Retour", "Back"), style=discord.ButtonStyle.secondary, emoji="↩️")

        async def accueil(interaction: discord.Interaction):
            self._section = None
            self.page = None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        retour.callback = accueil
        fermer = discord.ui.Button(label=t("Fermer", "Close"), style=discord.ButtonStyle.secondary)

        async def clore(interaction: discord.Interaction):
            await self._close(interaction)

        fermer.callback = clore
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(retour, fermer))
        self.add_item(container)

    async def _router_logs_manquants(
        self, interaction: discord.Interaction, salon_id: int, categories: list[str], english: bool,
    ) -> None:
        """Envoie toutes les catégories de logs sans salon dans le salon choisi."""
        from utils import log_service
        from . import setup_v2_core

        if not interaction.response.is_done():
            await interaction.response.defer()
        faites, refusees = [], []
        for cle in categories:
            ok, raison = log_service.validate_channel(self.guild, salon_id, needs_file=(cle == "files"))
            if not ok:
                refusees.append((cle, raison))
                continue
            await log_service.set_log_channel(self.bot, self.guild.id, cle, salon_id)
            faites.append(cle)
        if faites:
            await setup_v2_core.enable_module_if_unset(
                self.bot, self.guild.id, "logs", actor_id=interaction.user.id,
            )
        await self.refresh(interaction)
        if refusees:
            raison = refusees[0][1]
            noms = ", ".join(log_service.CATEGORIES.get(cle, cle) for cle, _ in refusees)
            message = (
                f"{len(faites)} categories set. Not set ({noms}): {raison}." if english
                else f"{len(faites)} catégories réglées. Non réglées ({noms}) : {raison}."
            )
            try:
                await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException:
                pass

    async def _ouvrir_page(self, interaction: discord.Interaction, selected: str, english: bool) -> None:
        """Ouvre un réglage, avec les deux cas particuliers de l'ancien menu."""
        if selected == "embeds":
            return await self._open_embed_builder(interaction)
        if selected == "language":
            from .language_official_bridge import OfficialLanguageSelect
            panneau = discord.ui.LayoutView(timeout=180)
            bloc = discord.ui.Container(accent_colour=0x6C57CC)
            v73.poser_banniere(bloc)
            bloc.add_item(discord.ui.TextDisplay(
                "## Server language" if english else "## Langue du serveur"
            ))
            bloc.add_item(discord.ui.Separator())
            bloc.add_item(discord.ui.ActionRow(OfficialLanguageSelect(self.backend)))
            panneau.add_item(bloc)
            return await interaction.response.send_message(
                **v73.joindre_banniere({"view": panneau}), ephemeral=True,
            )
        self.page = selected
        self.backend = self._new_backend(self.page)
        await self.refresh(interaction)

    async def _build_home_complet(self) -> None:
        """Ancienne vue d'ensemble (toutes les catégories) — derrière « Paramètres avancés »."""
        states = await self._effective_states()
        active = sum(
            "ACTIF" in value and "INACTIF" not in value
            for key, value in states.items()
            if key in CATEGORY_ORDER
        )
        problems = sum("CORRIGER" in states.get(key, "") for key in CATEGORY_ORDER)

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# Configuration de SentriX — paramètres avancés\n"
                    f"**{active}/{len(CATEGORY_ORDER)} modules actifs**"
                    + (f" · **{problems} à corriger**" if problems else "")
                    + "\nLes permissions des commandes sont vérifiées directement avec Discord."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )

        # Une section + texte + bouton par catégorie coûtait 33 composants pour 11
        # catégories : l'écran dépassait la limite Discord de 40 et le bouton
        # « Paramètres avancés » échouait (« Échec de l'interaction », mesuré par
        # tools/setup_sweep.py). La liste tient en un texte, l'accès en un menu.
        lignes = []
        for key in CATEGORY_ORDER:
            emoji, label, description = CATEGORY_META[key]
            state = v73._short_state(states.get(key, "—"))
            lignes.append(f"{emoji} **{label}** · {state}\n-# {description}")
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("\n".join(lignes)[:3900]))

        menu = discord.ui.Select(
            placeholder="Ouvrir une catégorie…",
            options=[
                discord.SelectOption(label=CATEGORY_META[key][1][:100], value=key, emoji=CATEGORY_META[key][0])
                for key in CATEGORY_ORDER
            ][:25],
        )

        async def open_page(interaction: discord.Interaction):
            category = menu.values[0]
            self.page = category
            self.backend = self._new_backend(category)
            await self.refresh(interaction)

        menu.callback = open_page
        container.add_item(discord.ui.ActionRow(menu))

        simple = discord.ui.Button(label="Écran simple", style=discord.ButtonStyle.primary)
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def voir_simple(interaction: discord.Interaction):
            self.avance = False
            await self.refresh(interaction)

        async def do_refresh(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def do_close(interaction: discord.Interaction):
            await self._close(interaction)

        simple.callback = voir_simple
        refresh.callback = do_refresh
        close.callback = do_close
        container.add_item(discord.ui.ActionRow(simple, refresh, close))
        self.add_item(container)

    async def _build_page(self, page: str) -> None:
        if page.startswith("section:"):
            return await self._build_section(page.split(":", 1)[1])
        if page in {"welcome", "goodbye"}:
            from .complete_welcome_setup import build_welcome_page
            return await build_welcome_page(self, page)
        if page in {"snippets", "word_reactions", "recurring_messages"}:
            from . import setup_automation_extras
            return await setup_automation_extras.build_page(self, page)
        if page == "custom_commands":
            from . import setup_custom_commands
            if not setup_custom_commands.is_admin(self, SimpleNamespace(user=self._author_member or self.guild.get_member(self.author_id), guild=self.guild)):
                box = discord.ui.Container()
                box.add_item(discord.ui.TextDisplay("# Commandes personnalisées\nSeuls les administrateurs peuvent créer et modifier des commandes personnalisées."))
                self._add_navigation(box)
                self.add_item(box)
                return
            return await setup_custom_commands.build_page(self)
        if page == "prefixes":
            from . import setup_custom_commands
            return await setup_custom_commands.build_prefix_page(self)
        if page == "rules_access":
            return await self._build_rules_access()
        if page == "automation":
            return await self._build_automation()
        if page == "suggestions":
            return await self._build_suggestions()
        if page == "security":
            return await self._build_security()
        if page == "tickets":
            return await self._build_tickets()
        if page == "moderation":
            return await self._build_moderation()
        if page == "music":
            return await self._build_music()
        if page == "ai":
            return await self._build_ai()
        if page == "economy":
            from .economy_setup import EconomySetupView
            subview = await EconomySetupView(self.bot, self.guild, self.author_id).build()
            for item in list(subview.children):
                subview.remove_item(item)
                self._add_navigation(item)
                self.add_item(item)
            return
        if page == "roles":
            return await self._build_roles()
        return await super()._build_page(page)

    async def _build_roles(self) -> None:
        """Rôles automatiques : chaque règle « action → rôle » au même endroit.

        Elles étaient éparpillées (arrivée ici, vérification dans Règlement,
        avertissement et mute dans Modération, exclusion des giveaways ailleurs).
        Chaque sélecteur montre le réglage en cours et écrit au MÊME endroit
        qu'avant : aucune donnée ne bouge. Un rôle impossible à donner (au-dessus
        de SentriX, géré par une intégration, @everyone) est refusé avec la raison.
        """
        from utils import welcome_autoroles
        from . import automatic_role_rules
        from . import setup_v2_ui

        conf = await self.bot.db.get_guild_config(self.guild.id)
        enabled = await core.module_enabled(self.bot, self.guild.id, "roles")
        arrival_ids = await welcome_autoroles.configured_ids(self.bot, self.guild.id)
        giveaway_id = await automatic_role_rules.giveaway_role_id(self.bot, self.guild.id)
        rewards = await self.bot.db.fetchall(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level", (self.guild.id,)
        )

        def current(field: str):
            if field == "giveaway_block_role":
                return giveaway_id
            value = setup_ui._get(conf, field)
            if field == "verify_role" and not value:
                value = setup_ui._get(conf, "verification_role")
            return int(value) if value else None

        def mention(role_id) -> str:
            role = self.guild.get_role(int(role_id)) if role_id else None
            return role.mention if role else "Aucun"

        rules = (
            ("verify_role", "Vérification", "donné quand un membre réussit la vérification"),
            ("warn_role", "Avertissement", "donné à un membre averti, retiré quand il n'a plus d'avertissement"),
            ("mute_role", "Mute", "donné pendant un mute, retiré à la fin du mute"),
        )
        lines = [
            f"**Arrivée** → {' '.join(mention(i) for i in arrival_ids) or 'Aucun'} · donné à chaque nouveau membre",
        ]
        lines += [f"**{label}** → {mention(current(field))} · {hint}" for field, label, hint in rules]
        if rewards:
            shown = ", ".join(f"niv. {r['level']} → {mention(r['role_id'])}" for r in rewards[:6])
            more = f" (+{len(rewards) - 6})" if len(rewards) > 6 else ""
            lines.append(f"**Récompenses de niveau** → {shown}{more}")
        else:
            lines.append("**Récompenses de niveau** → Aucune")

        toggle = discord.ui.Button(
            label="Désactiver" if enabled else "Activer",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )

        async def toggle_module(interaction: discord.Interaction):
            try:
                await core.set_module_enabled(
                    self.bot, self.guild.id, "roles", not enabled, actor_id=interaction.user.id
                )
            except core.ModuleSetupRequired as exc:
                return await setup_ui._refuse(interaction, str(exc))
            await self.refresh(interaction)

        toggle.callback = toggle_module

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🏷️ Rôles automatiques\n"
                    "Un rôle n'est donné que si vous l'avez choisi ici. SentriX ne crée aucun rôle, "
                    "respecte la hiérarchie, et à la levée d'une sanction ne retire que le rôle "
                    "qu'il a lui-même donné — jamais un rôle posé à la main."
                ),
                accessory=toggle,
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("### Règles en place\n" + "\n".join(lines)))
        container.add_item(discord.ui.Separator())

        owner = self.backend

        arrival = discord.ui.RoleSelect(
            placeholder="Arrivée : rôles donnés à chaque nouveau membre (5 max.)",
            min_values=0,
            max_values=welcome_autoroles.MAX_ROLES,
            default_values=[discord.Object(id=i) for i in arrival_ids if self.guild.get_role(i)],
        )

        async def save_arrival(interaction: discord.Interaction):
            for role in arrival.values:
                problem = welcome_autoroles.role_problem(self.guild, self.guild.get_role(role.id))
                if problem:
                    return await setup_ui._refuse(interaction, problem)
            ids = await welcome_autoroles.save(self.bot, self.guild.id, [r.id for r in arrival.values])
            await owner.audit(interaction.user.id, "autorole", ",".join(map(str, ids)) or None)
            await self.refresh(interaction)

        arrival.callback = save_arrival
        container.add_item(discord.ui.ActionRow(arrival))

        for field, label, _hint in rules:
            role_id = current(field)
            select = discord.ui.RoleSelect(
                placeholder=f"{label} : choisir le rôle (vide = aucun)",
                min_values=0,
                max_values=1,
                default_values=[discord.Object(id=role_id)] if role_id and self.guild.get_role(role_id) else [],
            )

            async def save(interaction: discord.Interaction, *, _field=field, _select=select):
                role = _select.values[0] if _select.values else None
                reason = setup_ui.validate_role_choice(self.guild, role, _field)
                if reason:
                    return await setup_ui._refuse(interaction, reason)
                value = role.id if role else None
                if _field == "giveaway_block_role":
                    await automatic_role_rules.set_giveaway_role(self.bot, self.guild.id, value)
                else:
                    await self.bot.db.set_guild_config(self.guild.id, _field, value)
                await owner.audit(interaction.user.id, _field, value)
                await self.refresh(interaction)

            select.callback = save
            container.add_item(discord.ui.ActionRow(select))

        async def open_role_panels(interaction):
            from .reaction_role_setup import RolePanelHubView
            await interaction.response.send_message(view=RolePanelHubView(self.bot,self.guild,interaction.user.id),ephemeral=True)

        role_panels = discord.ui.Button(label="Panneaux de rôles", style=discord.ButtonStyle.primary)
        role_panels.callback = open_role_panels
        container.add_item(discord.ui.ActionRow(role_panels))

        reward = discord.ui.Button(label="Ajouter / modifier une récompense de niveau", style=discord.ButtonStyle.secondary)

        async def open_reward(interaction: discord.Interaction):
            await interaction.response.send_modal(setup_v2_ui.LevelRewardModal(owner))

        reward.callback = open_reward
        container.add_item(discord.ui.ActionRow(reward))

        self._add_navigation(container)
        self.add_item(container)

    async def _build_ai(self) -> None:
        settings = await ai_service.get_settings(self.bot, self.guild.id)
        allowed_ids = [int(value) for value in settings.get("allowed_channel_ids", [])]
        allowed_channels = [
            self.guild.get_channel(channel_id)
            for channel_id in allowed_ids
            if self.guild.get_channel(channel_id) is not None
        ]

        language = await language_runtime.get_language(self.bot, self.guild.id)
        english = language == language_runtime.LANG_EN
        if allowed_channels:
            channel_text = ", ".join(channel.mention for channel in allowed_channels[:12])
            if len(allowed_channels) > 12:
                channel_text += f" +{len(allowed_channels) - 12}"
        else:
            channel_text = "All channels" if english else "Tous les salons"

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    (
                        "# 🤖 AI\nChoose exactly where SentriX may answer. "
                        "Natural replies and AI commands use the same channel list."
                        if english
                        else "# 🤖 IA\nChoisissez exactement où SentriX peut répondre. "
                        "Les réponses naturelles et les commandes IA utilisent la même liste de salons."
                    )
                    + "\n\n"
                    + (
                        f"**State:** {'Enabled' if settings['enabled'] else 'Disabled'}\n"
                        f"**Allowed channels:** {channel_text}\n"
                        f"**Limits:** {settings['cooldown_seconds']} s · "
                        f"{settings['per_minute_limit']}/min · {settings['daily_limit']}/day"
                        if english
                        else f"**État :** {'Activée' if settings['enabled'] else 'Désactivée'}\n"
                        f"**Salons autorisés :** {channel_text}\n"
                        f"**Limites :** {settings['cooldown_seconds']} s · "
                        f"{settings['per_minute_limit']}/min · {settings['daily_limit']}/jour"
                    )
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        channels = discord.ui.ChannelSelect(
            placeholder=(
                "Select one or more AI channels (empty = all)"
                if english
                else "Choisir un ou plusieurs salons IA (vide = tous)"
            ),
            min_values=0,
            max_values=25,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        )

        async def choose_channels(interaction: discord.Interaction):
            ids = [int(channel.id) for channel in channels.values]
            await ai_service.update_setting(
                self.bot,
                self.guild.id,
                "allowed_channel_ids",
                json.dumps(ids),
            )
            try:
                await self.backend.audit(
                    interaction.user.id,
                    "ai:allowed_channels",
                    ",".join(map(str, ids)) if ids else "all",
                )
            except Exception:
                logger.debug("Audit salons IA indisponible", exc_info=True)
            await self.refresh(interaction)

        channels.callback = choose_channels
        container.add_item(discord.ui.ActionRow(channels))

        toggle = discord.ui.Button(
            label=(
                ("Disable AI" if settings["enabled"] else "Enable AI")
                if english
                else ("Désactiver l’IA" if settings["enabled"] else "Activer l’IA")
            ),
            style=discord.ButtonStyle.danger if settings["enabled"] else discord.ButtonStyle.success,
        )
        limits = discord.ui.Button(
            label="Edit limits" if english else "Modifier les limites",
            style=discord.ButtonStyle.secondary,
        )

        async def toggle_ai(interaction: discord.Interaction):
            await ai_service.update_setting(
                self.bot,
                self.guild.id,
                "enabled",
                0 if settings["enabled"] else 1,
            )
            await self.refresh(interaction)

        async def edit_limits(interaction: discord.Interaction):
            row = await self.bot.db.fetchone(
                "SELECT cooldown_seconds,per_minute_limit,daily_limit FROM ai_settings WHERE guild_id=?",
                (self.guild.id,),
            )
            await interaction.response.send_modal(v73.V73AiLimitsModal(self, row))

        toggle.callback = toggle_ai
        limits.callback = edit_limits
        container.add_item(discord.ui.ActionRow(toggle, limits))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_suggestions(self) -> None:
        from cogs import suggestions

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        for item in await suggestions.setup_page_items(self):
            container.add_item(item)
        self._add_navigation(container)
        self.add_item(container)

    async def _build_rules_access(self) -> None:
        from . import verify_setup_interactive_v78 as rules_setup

        await self.bot.db.execute(rules_setup._SCHEMA)
        conf = await self.bot.db.get_guild_config(self.guild.id)
        row = await self.bot.db.fetchone(
            "SELECT rules_text,image_url,message_id FROM dashboard_verification_panels WHERE guild_id=?",
            (self.guild.id,),
        )
        row = dict(row) if row else {}

        def conf_value(key: str, default=None):
            try:
                value = conf[key] if conf is not None else default
            except (KeyError, IndexError, TypeError):
                return default
            return default if value is None else value

        channel_id = conf_value("verification_channel")
        role_id = conf_value("verify_role", conf_value("verification_role"))
        channel = self.guild.get_channel(int(channel_id)) if channel_id else None
        role = self.guild.get_role(int(role_id)) if role_id else None
        rules_text = str(row.get("rules_text") or "").strip()
        published = bool(row.get("message_id"))

        language = await language_runtime.get_language(self.bot, self.guild.id)
        english = language == language_runtime.LANG_EN

        title = "Rules & access" if english else "Règlement & accès"
        intro = (
            "Configure the rules channel, Verified role, rules text, optional image and simple CAPTCHA from one place."
            if english
            else "Configurez le salon du règlement, le rôle Vérifié, le texte, l’image facultative et le CAPTCHA simple au même endroit."
        )
        status_lines = (
            f"**Channel:** {channel.mention if channel else 'Not configured'}\n"
            f"**Verified role:** {role.mention if role else 'Not configured'}\n"
            f"**Rules text:** {'Configured' if rules_text else 'Not configured'}\n"
            f"**Public panel:** {'Published' if published else 'Not published'}"
            if english
            else
            f"**Salon :** {channel.mention if channel else 'Non configuré'}\n"
            f"**Rôle Vérifié :** {role.mention if role else 'Non configuré'}\n"
            f"**Règlement :** {'Configuré' if rules_text else 'Non configuré'}\n"
            f"**Panneau public :** {'Publié' if published else 'Non publié'}"
        )

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(f"# 📜 {title}\n{intro}\n\n{status_lines}"),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        configure = discord.ui.Button(
            label="Configure rules" if english else "Configurer le règlement",
            style=discord.ButtonStyle.primary,
        )

        async def open_configurator(interaction: discord.Interaction):
            view = await rules_setup.build_setup_view(
                self.bot,
                self.guild,
                interaction.user.id,
            )
            await panels.envoyer(
                interaction.response,
                view.panel(),
                ephemere=True,
            )
            try:
                view.message = await interaction.original_response()
            except (discord.NotFound, discord.HTTPException):
                view.message = None

        configure.callback = open_configurator
        boutons = [configure]
        if published:
            supprimer = discord.ui.Button(
                label="Delete rules" if english else "Supprimer le règlement",
                emoji="🗑️", style=discord.ButtonStyle.danger,
            )

            async def delete_rules(interaction: discord.Interaction):
                await interaction.response.defer()
                await rules_setup.delete_published_rules(self.bot, self.guild)
                await self.refresh(interaction)
                await interaction.followup.send(
                    "🗑️ Règlement retiré. Les permissions des salons n’ont pas changé : "
                    "republiez un règlement pour que les nouveaux puissent se vérifier.",
                    ephemeral=True,
                )

            supprimer.callback = delete_rules
            boutons.append(supprimer)
        container.add_item(discord.ui.ActionRow(*boutons))
        # Plus de bouton de verrouillage : publier le règlement configure les
        # salons tout seul, avec 10 secondes pour annuler.
        container.add_item(discord.ui.TextDisplay(
            "-# En publiant le règlement, SentriX configure les salons tout seul : "
            "les nouveaux ne voient que le règlement, puis les salons membres une fois "
            "vérifiés. 10 secondes pour annuler."
        ))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_automation(self) -> None:
        from . import setup_v2_ui as automation_ui

        language = await language_runtime.get_language(self.bot, self.guild.id)
        reactions = await automation_ui._automation_reaction_rows(self.bot, self.guild.id)
        rules = await automation_ui.channel_message_rules.list_rules(self.bot, self.guild)
        active_reactions = sum(bool(row["enabled"]) for row in reactions)
        active_rules = sum(bool(row.get("enabled")) for row in rules)

        title = "Automations" if language == language_runtime.LANG_EN else "Automatisations"
        description = (
            "Configure automatic reactions and per-channel content rules."
            if language == language_runtime.LANG_EN
            else "Configurez les réactions automatiques et les règles de contenu par salon."
        )

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"# ⚙️ {title}\n{description}\n\n"
                    + (
                        f"**Active reactions:** {active_reactions}\n**Active rules:** {active_rules}"
                        if language == language_runtime.LANG_EN
                        else f"**Réactions actives :** {active_reactions}\n**Règles actives :** {active_rules}"
                    )
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        reactions_button = discord.ui.Button(
            label="Automatic reactions" if language == language_runtime.LANG_EN else "Réactions automatiques",
            style=discord.ButtonStyle.primary,
        )
        rules_button = discord.ui.Button(
            label="Channel rules" if language == language_runtime.LANG_EN else "Règles des salons",
            style=discord.ButtonStyle.secondary,
        )

        async def open_reactions(interaction: discord.Interaction):
            rows = await automation_ui._automation_reaction_rows(self.bot, self.guild.id)
            panel = embeds.info(
                (
                    "Choose a channel, all messages or a keyword, then up to 8 emojis."
                    if language == language_runtime.LANG_EN
                    else "Choisissez un salon, tous les messages ou un mot-clé, puis jusqu’à 8 emojis."
                ),
                title="Automatic reactions" if language == language_runtime.LANG_EN else "Réactions automatiques",
            )
            source = SimpleNamespace(bot=self.bot, guild=self.guild)
            await panels.envoyer(
                interaction.response,
                panels.avec_composants(
                    panels.depuis_embed(panel),
                    automation_ui.AutoReactionSetupView(source, interaction.user.id, rows),
                ),
                ephemere=True,
            )

        async def open_rules(interaction: discord.Interaction):
            rows = await automation_ui.channel_message_rules.list_rules(self.bot, self.guild)
            panel = embeds.info(
                (
                    "**Images only** blocks text and other file types.\n"
                    "**Messages blocked** removes member messages from the channel."
                    if language == language_runtime.LANG_EN
                    else "**Images uniquement** bloque le texte et les autres fichiers.\n"
                    "**Messages interdits** supprime les messages des membres dans le salon."
                ),
                title="Channel rules" if language == language_runtime.LANG_EN else "Règles des salons",
            )
            source = SimpleNamespace(bot=self.bot, guild=self.guild)
            await panels.envoyer(
                interaction.response,
                panels.avec_composants(
                    panels.depuis_embed(panel),
                    automation_ui.ChannelRuleSetupView(source, interaction.user.id, rows),
                ),
                ephemere=True,
            )

        reactions_button.callback = open_reactions
        rules_button.callback = open_rules
        container.add_item(discord.ui.ActionRow(reactions_button, rules_button))

        word_button = discord.ui.Button(label="Réactions à des mots", style=discord.ButtonStyle.secondary)
        async def open_word_reactions(interaction: discord.Interaction):
            self.page = "word_reactions"
            await self.refresh(interaction)
        word_button.callback = open_word_reactions

        # 06/11/2026 : le compteur infini se configure aussi depuis /setup.
        compteur_button = discord.ui.Button(
            label="Infinite counter" if language == language_runtime.LANG_EN else "Compteur infini",
            style=discord.ButtonStyle.secondary,
        )

        async def open_counter(interaction: discord.Interaction):
            from . import infinite_counter

            cog = self.bot.get_cog("InfiniteCounter")
            if cog is None:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Le compteur infini n'est pas chargé.")),
                    ephemere=True,
                )
            source = SimpleNamespace(guild=self.guild, author=interaction.user)
            vue = infinite_counter.InfiniteSetupView(cog, source)
            await panels.envoyer(
                interaction.response,
                panels.avec_composants(panels.depuis_embed(vue.embed()), vue),
                ephemere=True,
            )

        compteur_button.callback = open_counter
        container.add_item(discord.ui.ActionRow(word_button, compteur_button))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_music(self) -> None:
        music = self.bot.get_cog("Music")
        settings = await music.get_system_settings(self.guild.id) if music else {
            "enabled": False,
            "voice_channel_id": None,
        }
        channel = (
            self.guild.get_channel(int(settings["voice_channel_id"]))
            if settings.get("voice_channel_id")
            else None
        )
        status = discord.ui.Button(
            label="Activé" if settings.get("enabled") else "Désactivé",
            style=discord.ButtonStyle.success if settings.get("enabled") else discord.ButtonStyle.secondary,
            disabled=True,
        )
        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🎵 Musique\n"
                    "Choisissez le **vocal musique** puis activez le système. "
                    "Quand un membre rejoint ce vocal, SentriX le mentionne dans le chat du vocal "
                    "et affiche le petit lecteur musique.\n\n"
                    f"Vocal actuel : **{channel.mention if channel else 'Non configuré'}**"
                ),
                accessory=status,
            )
        )
        container.add_item(discord.ui.Separator())

        voice_select = discord.ui.ChannelSelect(
            placeholder="Choisir le vocal musique",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.voice],
        )

        async def choose_voice(interaction: discord.Interaction):
            runtime = self.bot.get_cog("Music")
            if runtime is None:
                return await interaction.response.send_message("Le module musique n’est pas chargé.", ephemeral=True)
            chosen = voice_select.values[0]
            current = await runtime.get_system_settings(self.guild.id)
            try:
                await runtime.configure_system(
                    self.guild,
                    enabled=bool(current.get("enabled")),
                    voice_channel_id=chosen.id,
                    actor_id=interaction.user.id,
                )
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            await self.refresh(interaction)

        voice_select.callback = choose_voice
        container.add_item(discord.ui.ActionRow(voice_select))

        activate = discord.ui.Button(label="Activer la musique", style=discord.ButtonStyle.success)
        disable = discord.ui.Button(label="Désactiver la musique", style=discord.ButtonStyle.danger)

        async def activate_music(interaction: discord.Interaction):
            runtime = self.bot.get_cog("Music")
            if runtime is None:
                return await interaction.response.send_message("Le module musique n’est pas chargé.", ephemeral=True)
            current = await runtime.get_system_settings(self.guild.id)
            if not current.get("voice_channel_id"):
                return await interaction.response.send_message("Choisissez d’abord le vocal musique.", ephemeral=True)
            try:
                await runtime.configure_system(
                    self.guild,
                    enabled=True,
                    voice_channel_id=int(current["voice_channel_id"]),
                    actor_id=interaction.user.id,
                )
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            await self.refresh(interaction)

        async def disable_music(interaction: discord.Interaction):
            runtime = self.bot.get_cog("Music")
            if runtime is None:
                return await interaction.response.send_message("Le module musique n’est pas chargé.", ephemeral=True)
            current = await runtime.get_system_settings(self.guild.id)
            await runtime.configure_system(
                self.guild,
                enabled=False,
                voice_channel_id=current.get("voice_channel_id"),
                actor_id=interaction.user.id,
            )
            await self.refresh(interaction)

        activate.callback = activate_music
        disable.callback = disable_music
        container.add_item(discord.ui.ActionRow(activate, disable))
        self._add_navigation(container)
        self.add_item(container)

    async def _guide_aller(self, interaction: discord.Interaction, step: int | None) -> None:
        """Ouvre l'étape ``step`` du guide (None = quitter) et l'enregistre."""
        self.guide_step = step
        await guide_save_step(self.bot, self.guild.id, step)
        self.page = GUIDE[step][0] if step is not None else None
        self.backend = self._new_backend(self.page)
        await self.refresh(interaction)

    def _add_guide_navigation(self, container: discord.ui.Container) -> None:
        step = int(self.guide_step or 0)
        cle, libelle = GUIDE[step]
        suite = GUIDE[step + 1][1] if step + 1 < len(GUIDE) else None
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"🧭 **Configuration guidée — étape {step + 1}/{len(GUIDE)} : {libelle}**\n"
            + (f"-# Ensuite : {suite}. Rien n'est activé sans votre clic." if suite
               else "-# Dernière étape. Rien n'est activé sans votre clic.")
        ))
        precedent = discord.ui.Button(label="Étape précédente", style=discord.ButtonStyle.secondary,
                                      disabled=step == 0)
        suivant = discord.ui.Button(label="Étape suivante" if suite else "Terminer",
                                    style=discord.ButtonStyle.primary)
        quitter = discord.ui.Button(label="Quitter le guide", style=discord.ButtonStyle.secondary)

        async def aller_precedent(interaction: discord.Interaction):
            await self._guide_aller(interaction, max(0, step - 1))

        async def aller_suivant(interaction: discord.Interaction):
            await self._guide_aller(interaction, step + 1 if suite else None)

        async def quitter_guide(interaction: discord.Interaction):
            # L'étape reste enregistrée : « Reprendre » sur l'accueil y ramène.
            self.guide_step = None
            self.page = None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        precedent.callback = aller_precedent
        suivant.callback = aller_suivant
        quitter.callback = quitter_guide
        container.add_item(discord.ui.ActionRow(precedent, suivant, quitter))

    def _add_navigation(self, container: discord.ui.Container) -> None:
        if self.guide_step is not None and self.page == GUIDE[self.guide_step][0]:
            return self._add_guide_navigation(container)
        back = discord.ui.Button(label="Retour", style=discord.ButtonStyle.primary, emoji="↩️")
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_back(interaction: discord.Interaction):
            # Ouverte depuis une section : on y revient, pas à l'accueil.
            section = getattr(self, "_section", None)
            self.page = f"section:{section}" if section else None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        async def do_refresh(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def do_close(interaction: discord.Interaction):
            await self._close(interaction)

        back.callback = go_back
        refresh.callback = do_refresh
        close.callback = do_close
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(back, refresh, close))

    async def _set_security_profile(self, enabled: bool, actor_id: int) -> None:
        await self.bot.db.execute(
            "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
            (self.guild.id,),
        )
        columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
        values = tuple(1 if enabled else 0 for _ in setup_ui.AUTOMOD)
        await self.bot.db.execute(
            f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
            (*values, self.guild.id),
        )
        await security_v71.ensure_schema(self.bot)
        # Salon piège et vérification n'agissent qu'avec le système de vérification
        # installé : sans lui, « Activer la sécurité » les cochait pour rien.
        from . import setup_security_choice_v75 as v75

        extras = int(enabled and await v75._honeypot_resources_ready(self))
        await security_v71.update_setting(
            self.bot, self.guild.id, "honeypot_enabled", extras, actor_id
        )
        await security_v71.update_setting(
            self.bot, self.guild.id, "verification_enabled", extras, actor_id
        )
        if enabled:
            await security_v71.update_setting(
                self.bot, self.guild.id, "raid_intensity", "normal", actor_id
            )
            await security_v71.update_setting(
                self.bot,
                self.guild.id,
                "verification_threshold",
                security_v71.DEFAULT_SCORE_THRESHOLD,
                actor_id,
            )
        await self.bot.db.execute(
            "INSERT INTO honeypot_verification(guild_id,enabled,created_at) "
            "VALUES(?,?,strftime('%s','now')) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (self.guild.id, int(enabled)),
        )
        security_v71._invalidate_automod(self.bot, self.guild.id)
        await core.set_module_enabled(
            self.bot,
            self.guild.id,
            "security",
            enabled,
            actor_id=actor_id,
        )
        runtime = getattr(self.bot, "_sentrix_security_v71_runtime", None)
        if runtime is not None:
            try:
                await runtime.refresh_gateway_panels(self.guild)
            except Exception:
                logger.debug("Rafraîchissement des panneaux sécurité indisponible", exc_info=True)

    async def _build_security(self) -> None:
        # Module allumé sans aucune protection = rien ne tourne : le bouton
        # propose d'activer, comme si la sécurité était coupée.
        enabled = (
            await core.module_enabled(self.bot, self.guild.id, "security")
            and await setup_ui.security_protections_actives(self.bot, self.guild.id) > 0
        )
        _ok, missing = _bot_permission_audit(self.guild)
        status = discord.ui.Button(
            label="Activé" if enabled else "Désactivé",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
            disabled=True,
        )
        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🔒 Sécurité\n"
                    "Ici il n’y a plus 15 menus : **un seul bouton**.\n"
                    "Les protections de sécurité sont choisies individuellement dans la couche finale. "
                    "anti-spam, anti-raid, anti-liens, anti-invitations, anti-bot, anti-scam, "
                    "anti-nuke, honeypot et vérification.\n\n"
                    "Les utilisateurs sont autorisés selon leurs **permissions Discord réelles** "
                    "et la hiérarchie des rôles."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        perm_text = (
            "### Permissions du bot\n✅ Les permissions nécessaires sont disponibles."
            if not missing
            else "### Permissions du bot\n⚠️ Il manque : " + ", ".join(missing[:12])
        )
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(perm_text), accessory=status))

        # Le bulletin de sécurité, ici plutôt que seulement dans les journaux.
        # Mesuré le 23/10/2026 : 22 serveurs sur 36 n'ont AUCUN salon de
        # journaux configuré, donc la carte poussée ne les atteint jamais. Cet
        # écran, lui, est forcément ouvert par un admin — c'est la seule voie
        # qui marche partout. Deux composants seulement : le panneau plafonne
        # à 40, et l'écran avancé en frôle déjà la limite.
        try:
            from utils import security_advisory

            constats = await security_advisory.analyser_complet(self.guild)
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.TextDisplay(security_advisory.texte_compact(constats))
            )
        except Exception:
            # Un bulletin indisponible ne doit jamais empêcher d'ouvrir la page
            # Sécurité : sans ce garde, un serveur illisible rendait le réglage
            # de la sécurité inaccessible.
            logger.exception("Bulletin de sécurité indisponible guild=%s", self.guild.id)

        toggle = discord.ui.Button(
            label="Désactiver la sécurité" if enabled else "Activer la sécurité",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )

        async def toggle_security(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self._set_security_profile(not enabled, interaction.user.id)
            await self.refresh(interaction)

        toggle.callback = toggle_security
        container.add_item(discord.ui.ActionRow(toggle))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_tickets(self) -> None:
        enabled = await core.module_enabled(self.bot, self.guild.id, "tickets")
        ready = await v72.ticket_configuration_ready(self.bot, self.guild)
        panneaux, panel, types = await v72._existing_ticket_rows(self.bot, self.guild.id)
        status_label = "Activé" if enabled and ready else "À configurer" if enabled else "Désactivé"
        status_style = (
            discord.ButtonStyle.success
            if enabled and ready
            else discord.ButtonStyle.secondary
        )
        status = discord.ui.Button(label=status_label, style=status_style, disabled=True)
        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🎫 Tickets\n"
                    "Un type de ticket = un bouton du panneau (25 au maximum)."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        summary = (
            f"### Configuration actuelle\n"
            f"Panels : **{len(panneaux)}** · Types/boutons : **{len(types)}**\n"
            + (
                f"Panel principal : **{v72._row_get(panel, 'name', 'Panel')}**"
                if panel is not None
                else "Aucun panel créé."
            )
        )
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(summary), accessory=status))

        full = discord.ui.Button(
            label="Tout personnaliser",
            style=discord.ButtonStyle.primary,
            emoji="🛠️",
        )
        toggle = discord.ui.Button(
            label="Désactiver", style=discord.ButtonStyle.danger,
        ) if enabled else None

        async def full_config(interaction: discord.Interaction):
            ticket_cog = self.bot.get_cog("Tickets")
            if ticket_cog is None:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Le module Tickets n’est pas chargé.')), ephemere=True)
            ticket_runtime = v72._tickets_module()
            panel_embed = embeds.neutral(
                "Configuration complète des tickets",
                "Créez autant de panneaux et de types que nécessaire. "
                "Vous pouvez modifier le texte, l’image, la couleur, les boutons, "
                "les formulaires, les salons et les rôles.",
            )
            await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(panel_embed), ticket_runtime.TicketSetupHubView(ticket_cog, interaction.user.id)), ephemere=True)

        async def toggle_tickets(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            await core.set_module_enabled(
                self.bot,
                self.guild.id,
                "tickets",
                not enabled,
                actor_id=interaction.user.id,
            )
            await self.refresh(interaction)

        full.callback = full_config
        if toggle is not None:
            toggle.callback = toggle_tickets
            container.add_item(discord.ui.ActionRow(full, toggle))
        else:
            container.add_item(discord.ui.ActionRow(full))
        self._add_navigation(container)
        self.add_item(container)

    async def _build_moderation(self) -> None:
        enabled = await core.module_enabled(self.bot, self.guild.id, "moderation")
        conf = await self.bot.db.get_guild_config(self.guild.id)
        mute_role = _role_from_config(self.guild, setup_ui._get(conf, "mute_role"))
        warn_role = _role_from_config(self.guild, setup_ui._get(conf, "warn_role"))
        status = discord.ui.Button(
            label="Activé" if enabled else "Désactivé",
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
            disabled=True,
        )

        container = discord.ui.Container(accent_colour=0x6C57CC)
        v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 🛡️ Modération\n"
                    "Le vieux **« Rôle staff »** n’est plus demandé. SentriX décide l’accès avec "
                    "les permissions Discord réelles : timeout, kick, ban, gérer les messages, "
                    "les salons, les rôles, etc.\n\n"
                    "Vous pouvez aussi préparer un rôle avec un profil de permissions ci-dessous "
                    "et l’attribuer directement à un membre."
                ),
                accessory=v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        badge_text = (
            "### Badges automatiques de sanction\n"
            f"Rôle après mute : **{mute_role.name if mute_role else 'Aucun'}**\n"
            f"Rôle après warn : **{warn_role.name if warn_role else 'Aucun'}**\n"
            "Le rôle mute est retiré automatiquement avec `unmute`."
        )
        container.add_item(discord.ui.Section(discord.ui.TextDisplay(badge_text), accessory=status))

        toggle = discord.ui.Button(
            label="Désactiver la modération" if enabled else "Activer la modération",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
        )

        async def toggle_moderation(interaction: discord.Interaction):
            if not interaction.response.is_done():
                await interaction.response.defer()
            await core.set_module_enabled(
                self.bot,
                self.guild.id,
                "moderation",
                not enabled,
                actor_id=interaction.user.id,
            )
            await self.refresh(interaction)

        toggle.callback = toggle_moderation
        container.add_item(discord.ui.ActionRow(toggle))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("### Configurer un rôle de modération existant"))

        role_select = discord.ui.RoleSelect(
            placeholder="1. Rôle Discord à configurer",
            min_values=1,
            max_values=1,
        )
        profile_select = discord.ui.Select(
            placeholder="2. Niveau de permissions",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description=(
                        "Messages et pseudos"
                        if key == "helper"
                        else "Mute, kick, messages, vocal"
                        if key == "moderator"
                        else "Modération complète sans Administrateur"
                    ),
                )
                for key, (label, _flags) in MODERATION_PROFILES.items()
            ],
        )
        member_select = discord.ui.UserSelect(
            placeholder="3. Membre à ajouter au rôle (optionnel)",
            min_values=0,
            max_values=1,
        )

        async def pick_role(interaction: discord.Interaction):
            self.moderation_role_id = role_select.values[0].id
            await interaction.response.defer()

        async def pick_profile(interaction: discord.Interaction):
            self.moderation_profile = profile_select.values[0]
            await interaction.response.defer()

        async def pick_member(interaction: discord.Interaction):
            self.moderation_member_id = member_select.values[0].id if member_select.values else None
            await interaction.response.defer()

        role_select.callback = pick_role
        profile_select.callback = pick_profile
        member_select.callback = pick_member
        container.add_item(discord.ui.ActionRow(role_select))
        container.add_item(discord.ui.ActionRow(profile_select))
        container.add_item(discord.ui.ActionRow(member_select))

        apply_profile = discord.ui.Button(
            label="Appliquer les permissions et attribuer le rôle",
            style=discord.ButtonStyle.success,
        )

        async def apply_moderation_profile(interaction: discord.Interaction):
            role = self.guild.get_role(self.moderation_role_id) if self.moderation_role_id else None
            if role is None or role.is_default() or role.managed:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Choisissez un rôle Discord modifiable.')), ephemere=True)
            me = self.guild.me
            if me is None or not me.guild_permissions.manage_roles:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('SentriX a besoin de **Gérer les rôles** pour faire cela.')), ephemere=True)
            if role >= me.top_role:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Placez le rôle SentriX au-dessus du rôle à configurer.')), ephemere=True)

            _label, flags = MODERATION_PROFILES.get(
                self.moderation_profile,
                MODERATION_PROFILES["moderator"],
            )
            missing_for_bot = [flag for flag in flags if not getattr(me.guild_permissions, flag, False)]
            if missing_for_bot:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('SentriX ne peut pas accorder des permissions qu’il ne possède pas lui-même : ' + ', '.join(missing_for_bot))), ephemere=True)

            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            permissions = role.permissions
            permissions.update(**{flag: True for flag in flags})
            try:
                await role.edit(
                    permissions=permissions,
                    reason=f"SentriX V74 : profil {self.moderation_profile}",
                )
                await self.bot.db.set_guild_config(self.guild.id, "mod_role", role.id)
                assigned = False
                if self.moderation_member_id:
                    member = self.guild.get_member(self.moderation_member_id)
                    if member is not None and role not in member.roles:
                        await member.add_roles(role, reason="SentriX V74 : attribution du rôle de modération")
                        assigned = True
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(f'Le rôle **{role.name}** utilise maintenant le profil **{MODERATION_PROFILES[self.moderation_profile][0]}**.' + (' Il a aussi été attribué au membre choisi.' if assigned else ''))), ephemere=True)
            except discord.HTTPException:
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('Discord a refusé la modification du rôle. Vérifiez la hiérarchie.')), ephemere=True)

        apply_profile.callback = apply_moderation_profile
        container.add_item(discord.ui.ActionRow(apply_profile))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("### Rôles automatiques après sanction (optionnels)"))

        mute_select = discord.ui.RoleSelect(
            placeholder="Rôle à donner pendant un mute",
            min_values=0,
            max_values=1,
        )
        warn_select = discord.ui.RoleSelect(
            placeholder="Rôle à donner après un warn",
            min_values=0,
            max_values=1,
        )

        async def set_mute_role(interaction: discord.Interaction):
            role = mute_select.values[0] if mute_select.values else None
            # Même vérification que la page Rôles automatiques : avant, n'importe quel
            # rôle était accepté (@everyone, rôle au-dessus de SentriX…) et échouait en silence.
            reason = setup_ui.validate_role_choice(self.guild, role, "mute_role")
            if reason:
                return await setup_ui._refuse(interaction, reason)
            await _set_optional_role(self, "mute_role", role)
            await self.refresh(interaction)

        async def set_warn_role(interaction: discord.Interaction):
            role = warn_select.values[0] if warn_select.values else None
            reason = setup_ui.validate_role_choice(self.guild, role, "warn_role")
            if reason:
                return await setup_ui._refuse(interaction, reason)
            await _set_optional_role(self, "warn_role", role)
            await self.refresh(interaction)

        mute_select.callback = set_mute_role
        warn_select.callback = set_warn_role
        container.add_item(discord.ui.ActionRow(mute_select))
        container.add_item(discord.ui.ActionRow(warn_select))

        self._add_navigation(container)
        self.add_item(container)


async def _send_setup_v74(self, target):
    guild = getattr(target, "guild", None)
    member = getattr(target, "author", None) or getattr(target, "user", None)
    if guild is None or member is None:  # /setup s'ouvre pour tous (lecture seule)
        return await setup_ui._permission_error(target)

    view = SentriXSetupV74(self.bot, guild, member.id)
    view._author_member = member
    await view.prepare()

    if isinstance(target, commands.Context):
        # Le préfixe + ne peut pas afficher d'éphémère : aucun message
        # "Information" ou panneau sensible ne doit rester dans le salon.
        try:
            await target.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        try:
            return await member.send(
                "Ouvrez **/setup** dans le serveur pour accéder au centre privé de SentriX."
            )
        except (discord.Forbidden, discord.HTTPException):
            return await target.send(
                "Utilisez /setup pour la configuration privée.",
                delete_after=6,
                allowed_mentions=discord.AllowedMentions.none(),
            )
    if target.response.is_done():
        return await target.followup.send(**v73.joindre_banniere({"view": view}), ephemeral=True)
    # joindre_banniere consulte la MÊME condition que poser_banniere : la
    # galerie et la pièce jointe ne peuvent plus diverger. Les éditions de
    # navigation passent par le refresh hérité de V73.
    return await target.response.send_message(**v73.joindre_banniere({"view": view}), ephemeral=True)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_experience_v74", False):
        return

    current = setup_ui.OfficialSetup.send_setup
    if not getattr(current, "_sentrix_setup_v74", False):
        _send_setup_v74._sentrix_setup_v74 = True
        _send_setup_v74._sentrix_previous = current
        setup_ui.OfficialSetup.send_setup = _send_setup_v74

    bot._sentrix_setup_experience_v74 = True
    logger.info(
        "%s installé : sécurité simple, permissions Discord natives, tickets complets et modération claire.",
        RUNTIME_MARKER,
    )


__all__ = ["SentriXSetupV74", "install"]
