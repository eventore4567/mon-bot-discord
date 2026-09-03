"""SentriX Control Center V3.

Autorité finale pour les surfaces demandées dans +setup :
- rendu Setup large et cohérent, sans rangée de boutons de navigation ;
- petit bouton unique Activer/Désactiver par module ;
- vérification renforcée + honeypot via le moteur sécurité existant ;
- panel de choix de rôles configurable ;
- accueil/départ visible unique et placeholders cohérents ;
- classification succès/erreur sémantique sans faux positifs par sous-chaîne.

Cette couche ne remplace pas les moteurs métier : elle consolide leur UI et neutralise les
anciens doublons visibles. Les listeners de logs, niveaux, invitations, sécurité et rétention
restent actifs.
"""
from __future__ import annotations

import logging
import re
import types
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service, premium_style
from utils.instance_identity import brand_label
from . import honeypot_verification_v48 as honeypot_v50
from . import setup_control_center as setup_ui
from . import setup_v2_core
from . import verification as verification_module
# « panels » designe deja les panneaux de roles ici.
from utils import sentrix_panels as sx_panels

logger = logging.getLogger("bot.control-center-v3")

_SELF_ROLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS self_role_setup_v3 (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0
)
"""

# ---------------------------------------------------------------------------
# Success / error semantics
# ---------------------------------------------------------------------------
_RED = {0xED4245, 0xF23F43, 0xE74C3C}
_YELLOW = {0xFEE75C, 0xF0B232, 0xF39C12}
_GREEN = {0x57F287, 0x23A559, 0x2ECC71, 0x2FBF71}

_DANGER_RE = re.compile(
    r"\b(erreur|impossible|refus[ée]|interdit|introuvable|[ée]chec|[ée]chou[ée]|permission(?:s)? manquante(?:s)?|"
    r"acc[èe]s bloqu[ée]|action bloqu[ée]|commande bloqu[ée])\b",
    re.IGNORECASE,
)
_WARNING_RE = re.compile(
    r"\b(attention|avertissement|[àa] v[ée]rifier|d[ée]j[àa]|recharge|cooldown)\b",
    re.IGNORECASE,
)
_SUCCESS_RE = re.compile(
    r"\b(succ[èe]s|r[ée]ussi(?:e)?|termin[ée]e?|enregistr[ée]e?|cr[ée][ée]e?|activ[ée]e?|ajout[ée]e?|"
    r"envoy[ée]e?|configur[ée]e?|effectu[ée]e?|d[ée]bloqu[ée]e?|d[ée]banni(?:e)?|d[ée]bannissement)\b",
    re.IGNORECASE,
)


def semantic_kind(embed: discord.Embed | None = None, content: str = "") -> str:
    """Déduit l'état sans confondre « débloqué » avec « bloqué ».

    Une couleur sémantique explicite gagne toujours. Pour les anciens embeds non typés,
    les phrases d'échec sont testées avant les mots de succès afin que
    « impossible de débannir » reste une erreur.
    """
    value = getattr(getattr(embed, "colour", None), "value", 0) if embed else 0
    if value in _RED:
        return "danger"
    if value in _YELLOW:
        return "warning"
    if value in _GREEN:
        return "success"

    text = " ".join(
        str(part) for part in (
            getattr(embed, "title", None) if embed else None,
            getattr(embed, "description", None) if embed else None,
            content,
        ) if part
    )
    if _DANGER_RE.search(text):
        return "danger"
    if _WARNING_RE.search(text):
        return "warning"
    if _SUCCESS_RE.search(text):
        return "success"
    return "info"


def _install_semantic_renderer() -> None:
    if getattr(premium_style, "_sentrix_control_center_v3_semantics", False):
        return
    semantic_kind._sentrix_original = premium_style.infer_kind
    premium_style.infer_kind = semantic_kind
    premium_style._sentrix_control_center_v3_semantics = True


# ---------------------------------------------------------------------------
# Canonical welcome / goodbye renderer
# ---------------------------------------------------------------------------

def render_member_template(text: str, member: discord.Member) -> str:
    replacements = {
        "{member}": member.mention,
        "{membre}": member.mention,
        "{mention}": member.mention,
        "{user}": member.mention,
        "(user)": member.mention,
        "[user]": member.mention,
        "<user>": member.mention,
        "{username}": member.name,
        "{display_name}": member.display_name,
        "{server}": member.guild.name,
        "{serveur}": member.guild.name,
        "{member_count}": str(member.guild.member_count or 0),
    }
    value = str(text or "")
    for placeholder, replacement in replacements.items():
        value = value.replace(placeholder, replacement)
    return value


def _is_primary_sentrix_service() -> bool:
    """Évite un deuxième message si deux services Railway utilisent le même bot SentriX."""
    if str(brand_label()).casefold() != "sentrix":
        return True
    try:
        from . import passive_ai_single_reply_final as passive_ai
        checker = getattr(passive_ai, "_is_primary_service", None)
        return bool(checker()) if callable(checker) else True
    except Exception:
        return True


# _install_presence_renderer et _remove_visible_presence_listeners ont été retirés :
# ce fichier assignait bot.on_member_join/on_member_remove (un attribut) EN PLUS du
# listener add_listener() posé par cogs/setup_v2_completion.py — discord.py déclenche
# les deux mécanismes séparément (Bot.dispatch appelle self.on_member_join ET chaque
# listener de extra_events), donc CHAQUE arrivée envoyait deux messages de bienvenue
# différents (titre, ping et respect du module "welcome" divergents), et le nettoyage
# heuristique par inspection de code source ne retirait jamais l'autre système (son
# listener appelle un helper _send_welcome() dont le corps ne contient littéralement ni
# "welcome_channel" ni ".send("). cogs/setup_v2_completion.py::_send_welcome est
# maintenant l'unique émetteur — c'est aussi lui qui alimente le bouton "Tester la
# bienvenue" du setup, donc l'aperçu et le message réel sont enfin garantis identiques.
# render_member_template et _is_primary_sentrix_service restent définis ci-dessus : ils
# sont réutilisés par setup_v2_completion.py (alias de variables + garde anti-doublon HA).


# ---------------------------------------------------------------------------
# Reinforced verification / honeypot – use existing V50 engine, no duplicate UI patch
# ---------------------------------------------------------------------------

async def _install_honeypot_runtime(bot: commands.Bot) -> None:
    await bot.db.execute(honeypot_v50._SCHEMA)
    await bot.db.execute(honeypot_v50._PENDING_SCHEMA)
    await bot.db.execute(honeypot_v50._VERIFIED_SCHEMA)
    if bot.get_cog(honeypot_v50._COG_NAME) is None:
        await bot.add_cog(honeypot_v50.HoneypotVerification(bot))
    if not getattr(bot, "_sentrix_honeypot_verify_view_registered", False):
        bot.add_view(honeypot_v50.HoneypotVerifyView())
        bot._sentrix_honeypot_verify_view_registered = True
    bot._sentrix_honeypot_verification_v50 = True


# ---------------------------------------------------------------------------
# Configurable self-role panel
# ---------------------------------------------------------------------------

async def _self_role_settings(bot: commands.Bot, guild_id: int) -> dict[str, Any]:
    row = await bot.db.fetchone("SELECT * FROM self_role_setup_v3 WHERE guild_id=?", (guild_id,))
    return dict(row) if row else {"guild_id": guild_id, "channel_id": None, "enabled": 1}


async def _configured_role_ids(bot: commands.Bot, guild_id: int, panel_message_id: int = 0) -> list[int]:
    rows = await bot.db.fetchall(
        "SELECT role_id FROM self_role_items WHERE guild_id=? AND panel_message_id=? ORDER BY role_id",
        (guild_id, panel_message_id),
    )
    if not rows and panel_message_id:
        rows = await bot.db.fetchall(
            "SELECT role_id FROM self_role_items WHERE guild_id=? AND panel_message_id=0 ORDER BY role_id",
            (guild_id,),
        )
    return [int(row["role_id"]) for row in rows]


async def _publish_or_refresh_role_panel(bot: commands.Bot, guild: discord.Guild, actor_id: int = 0) -> None:
    cog = bot.get_cog("Verification")
    if cog is None:
        return
    settings = await _self_role_settings(bot, guild.id)
    if not int(settings.get("enabled", 1)) or not settings.get("channel_id"):
        return
    channel = guild.get_channel(int(settings["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return

    panels = await bot.db.fetchall(
        "SELECT * FROM self_role_panels WHERE guild_id=? ORDER BY created_at DESC", (guild.id,)
    )
    target = next((panel for panel in panels if int(panel["channel_id"]) == channel.id), None)
    if target:
        await cog._refresh_self_role_panel(guild, int(target["message_id"]))
        return

    options = await cog._self_role_options(guild, 0)
    panel_data = {"title": "Choisissez vos rôles"}
    message = await sx_panels.envoyer(channel, sx_panels.avec_composants(sx_panels.depuis_embed(await cog._self_role_embed(guild, panel_data, options)), verification_module.SelfRolePublicView(options)))
    await bot.db.execute(
        "INSERT INTO self_role_panels (guild_id,channel_id,message_id,title,created_by,created_at) "
        "VALUES (?,?,?,?,?,strftime('%s','now'))",
        (guild.id, channel.id, message.id, "Choisissez vos rôles", int(actor_id or 0)),
    )


def _install_self_role_backend(bot: commands.Bot) -> None:
    cog = bot.get_cog("Verification")
    if cog is None or getattr(cog, "_sentrix_control_center_v3_roles", False):
        return

    original_options = cog._self_role_options

    async def configured_options(this, guild: discord.Guild, panel_message_id: int):
        ids = await _configured_role_ids(bot, guild.id, int(panel_message_id or 0))
        if ids:
            options = []
            for role_id in ids[:25]:
                role = guild.get_role(role_id)
                if role is None or verification_module._self_role_error(guild, role):
                    continue
                options.append(discord.SelectOption(label=role.name[:100], value=str(role.id)))
            return options
        # Compatibilité : tant qu'aucun choix explicite n'a été enregistré, les anciens
        # panels basés sur les rôles Ping/Notif continuent de fonctionner.
        return await original_options(guild, panel_message_id)

    async def configured_selection(this, interaction: discord.Interaction, raw_role_ids: list[str]):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Ce menu fonctionne uniquement dans un serveur.", ephemeral=True)
        panel = await bot.db.fetchone(
            "SELECT 1 FROM self_role_panels WHERE guild_id=? AND message_id=?",
            (interaction.guild.id, interaction.message.id),
        )
        if not panel:
            return await interaction.response.send_message("Ce panneau n'est plus configuré.", ephemeral=True)
        allowed = {int(option.value) for option in await this._self_role_options(interaction.guild, interaction.message.id)}
        chosen = []
        for raw in raw_role_ids:
            try:
                role_id = int(raw)
            except (TypeError, ValueError):
                continue
            role = interaction.guild.get_role(role_id)
            if role_id in allowed and role and not verification_module._self_role_error(interaction.guild, role):
                chosen.append(role)
        if not chosen:
            return await interaction.response.send_message("Aucun de ces rôles n'est disponible.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        added = [role for role in chosen if role not in interaction.user.roles]
        removed = [role for role in chosen if role in interaction.user.roles]
        try:
            if added:
                await interaction.user.add_roles(*added, reason="Choix dans le panel SentriX")
            if removed:
                await interaction.user.remove_roles(*removed, reason="Choix dans le panel SentriX")
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.followup.send(
                'Discord refuse un de ces rôles. Placez le rôle SentriX au-dessus des rôles du panel.', ephemeral=True
            )
        result = []
        if added:
            result.append("Ajouté : " + ", ".join(role.mention for role in added))
        if removed:
            result.append("Retiré : " + ", ".join(role.mention for role in removed))
        await interaction.followup.send("\n".join(result), ephemeral=True)

    cog._self_role_options = types.MethodType(configured_options, cog)
    cog.handle_self_role_selection = types.MethodType(configured_selection, cog)
    cog._sentrix_control_center_v3_roles = True


# ---------------------------------------------------------------------------
# Setup V3 controls
# ---------------------------------------------------------------------------

class V3CategorySelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        options = [discord.SelectOption(label="Accueil", value="__home__", description="Vue générale du Control Center")]
        for key in setup_ui.CATEGORY_ORDER:
            if key not in setup_ui.CATEGORIES:
                continue
            label, description = setup_ui.CATEGORIES[key]
            options.append(discord.SelectOption(label=label, value=key, description=description[:100]))
        if "security" in setup_ui.CATEGORIES:
            options.append(discord.SelectOption(label="Sécurité — Vérification", value="security_verification", description="Vérification renforcée et honeypot anti-bot"))
        if "roles" in setup_ui.CATEGORIES:
            options.append(discord.SelectOption(label="Rôles — Panel de choix", value="roles_panel", description="Salon et rôles proposés aux membres"))
            options.append(discord.SelectOption(label="Rôles — Règles & CAPTCHA", value="roles_rules", description="Salon des règles, rôle donné et CAPTCHA de vérification"))
        super().__init__(placeholder="Choisir une page du Control Center", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.owner._v3_subpage = None
        if value == "__home__":
            self.owner.category = None
        elif value == "security_verification":
            self.owner.category = "security"
            self.owner._v3_subpage = "verification"
        elif value == "roles_panel":
            self.owner.category = "roles"
            self.owner._v3_subpage = "panel"
        elif value == "roles_rules":
            self.owner.category = "roles"
            self.owner._v3_subpage = "rules"
        else:
            self.owner.category = value
        self.owner.selected_log = self.owner.selected_ticket = self.owner.selected_notification = None
        await self.owner.refresh(interaction)


class ModuleToggle(discord.ui.Button):
    def __init__(self, owner, module: str, enabled: bool):
        self.owner = owner
        self.module = module
        super().__init__(
            label="Désactiver" if enabled else "Activer",
            style=discord.ButtonStyle.secondary if enabled else discord.ButtonStyle.success,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        enabled = await setup_v2_core.module_enabled(self.owner.bot, self.owner.guild.id, self.module)
        await setup_v2_core.set_module_enabled(
            self.owner.bot, self.owner.guild.id, self.module, not enabled, actor_id=interaction.user.id
        )
        if self.module == "levels":
            await setup_v2_core.set_module_enabled(
                self.owner.bot, self.owner.guild.id, "economy", not enabled, actor_id=interaction.user.id
            )
        await self.owner.refresh(interaction)


class SecurityVerificationSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Configurer la vérification et le honeypot",
            options=[
                discord.SelectOption(label="Activer / actualiser — Softban", value="softban", description="Challenge complet + softban si le piège est déclenché"),
                discord.SelectOption(label="Activer / actualiser — Expulsion", value="kick", description="Challenge complet + expulsion si le piège est déclenché"),
                discord.SelectOption(label="Désactiver", value="disable", description='Désactivez le portail sans supprimer sa configuration'),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        cog = self.owner.bot.get_cog(honeypot_v50._COG_NAME)
        if cog is None:
            return await interaction.response.send_message("Le moteur de vérification n'est pas chargé.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        value = self.values[0]
        if value == "disable":
            _ok, message = await cog.disable_system(self.owner.guild)
        else:
            result, error = await cog.create_or_refresh_system(self.owner.guild, sanction=value)
            if error:
                return await interaction.followup.send(error, ephemeral=True)
            message = f"Vérification renforcée active : {result['verify'].mention} • Honeypot : {result['trap'].mention}."
        self.owner.render()
        await interaction.edit_original_response(embed=await self.owner.build_embed(), view=self.owner)
        await interaction.followup.send(message, ephemeral=True)


class RolePanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Salon du panel de choix des rôles",
            min_values=0,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        channel_id = self.values[0].id if self.values else None
        await self.owner.bot.db.execute(
            "INSERT INTO self_role_setup_v3(guild_id,channel_id,enabled,updated_by,updated_at) VALUES(?,?,1,?,strftime('%s','now')) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (self.owner.guild.id, channel_id, interaction.user.id),
        )
        if channel_id:
            await _publish_or_refresh_role_panel(self.owner.bot, self.owner.guild, interaction.user.id)
        await self.owner.refresh(interaction)


class RolePanelRolesSelect(discord.ui.RoleSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(placeholder="Rôles proposés dans le panel", min_values=0, max_values=25, row=3)

    async def callback(self, interaction: discord.Interaction):
        valid = []
        rejected = []
        for role in self.values:
            error = verification_module._self_role_error(self.owner.guild, role)
            if error:
                rejected.append(role.name)
            else:
                valid.append(role)
        await self.owner.bot.db.execute(
            "DELETE FROM self_role_items WHERE guild_id=? AND panel_message_id=0", (self.owner.guild.id,)
        )
        for role in valid:
            await self.owner.bot.db.execute(
                "INSERT OR IGNORE INTO self_role_items(guild_id,panel_message_id,role_id) VALUES(?,0,?)",
                (self.owner.guild.id, role.id),
            )
        await _publish_or_refresh_role_panel(self.owner.bot, self.owner.guild, interaction.user.id)
        await self.owner.refresh(interaction)
        if rejected:
            await interaction.followup.send(
                "Rôles ignorés car non attribuables : " + ", ".join(rejected[:10]), ephemeral=True
            )


class CaptchaToggleButton(discord.ui.Button):
    """Active/désactive le CAPTCHA de vérification. Le libellé réel (ON/OFF) est corrigé
    juste avant l'envoi par _v3_refresh, comme ModuleToggle : impossible de lire la DB
    depuis __init__ (synchrone)."""

    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="CAPTCHA : …", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        conf = await self.owner.bot.db.get_guild_config(self.owner.guild.id)
        enabled = bool(setup_ui._get(conf, "verify_captcha_enabled", 1))
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "verify_captcha_enabled", int(not enabled))
        await self.owner.audit(interaction.user.id, "verify_captcha_enabled", int(not enabled))
        await self.owner.refresh(interaction)


class CaptchaMaxAttemptsModal(discord.ui.Modal, title="Tentatives CAPTCHA"):
    attempts = discord.ui.TextInput(label="Tentatives maximum (1 à 10)", default="3", max_length=2)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = max(1, min(10, int(str(self.attempts.value).strip())))
        except ValueError:
            return await interaction.response.send_message("Utilisez un nombre entre 1 et 10.", ephemeral=True)
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "verify_captcha_max_attempts", value)
        await self.owner.audit(interaction.user.id, "verify_captcha_max_attempts", value)
        self.owner.render()
        await interaction.response.edit_message(embed=await self.owner.build_embed(), view=self.owner)


class CaptchaMaxAttemptsButton(discord.ui.Button):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="Tentatives max.", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CaptchaMaxAttemptsModal(self.owner))


class SendRulesPanelButton(discord.ui.Button):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="Envoyer / recréer le panneau", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction):
        conf = await self.owner.bot.db.get_guild_config(self.owner.guild.id)
        channel_id = setup_ui._get(conf, "rules_channel")
        channel = self.owner.guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            return await interaction.response.send_message(
                "Choisissez d'abord un salon des règles ci-dessus.", ephemeral=True,
            )
        role_id = setup_ui._get(conf, "verify_role") or setup_ui._get(conf, "verification_role")
        role = self.owner.guild.get_role(int(role_id)) if role_id else None
        problem = verification_module.role_grant_problem(self.owner.guild, role)
        if problem:
            return await interaction.response.send_message(
                f"Panneau non envoyé : {problem}", ephemeral=True,
            )
        cog = self.owner.bot.get_cog("Verification")
        if cog is None:
            return await interaction.response.send_message(
                "Le module de vérification n'est pas chargé pour le moment.", ephemeral=True,
            )
        embed = await cog._embed(
            self.owner.guild.id,
            title="Vérification",
            description="Cliquez sur le bouton ci-dessous après avoir lu les règles du serveur pour obtenir l'accès complet.",
        )
        try:
            await sx_panels.envoyer(channel, sx_panels.avec_composants(sx_panels.depuis_embed(embed), verification_module.VerifyView()))
        except (discord.Forbidden, discord.HTTPException) as exc:
            return await interaction.response.send_message(f"Discord a refusé l'envoi : {exc}", ephemeral=True)
        await interaction.response.send_message(f"Panneau envoyé dans {channel.mention}.", ephemeral=True)


class AiActionSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Configuration IA",
            options=[discord.SelectOption(label="Modifier cooldown et limites", value="limits")],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(setup_ui.AiModal(self.owner))


class LogActionSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="État du type de log sélectionné",
            options=[
                discord.SelectOption(label="Activer ce type", value="on"),
                discord.SelectOption(label="Désactiver ce type", value="off"),
            ],
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.owner.selected_log:
            return await interaction.response.send_message("Choisissez d'abord un type de log.", ephemeral=True)
        # Point d'écriture unique : plus de SQL direct sur log_settings (table archivée).
        try:
            await log_service.set_log_enabled(
                self.owner.bot, self.owner.guild.id, self.owner.selected_log,
                self.values[0] == "on",
            )
        except ValueError:
            return await interaction.response.send_message(
                "Choisissez d'abord un salon pour ce type de log avant de l'activer.",
                ephemeral=True,
            )
        await self.owner.refresh(interaction)


async def _module_state(bot: commands.Bot, guild_id: int, category: str) -> bool:
    if category == "levels":
        return await setup_v2_core.module_enabled(bot, guild_id, "levels")
    return await setup_v2_core.module_enabled(bot, guild_id, category)


def _state_text(active: bool) -> str:
    return "ACTIF" if active else "INACTIF"


async def _v3_build_embed(self) -> discord.Embed:
    # Unknown/dynamically injected pages (notably Permissions V3) keep their own backend
    # and renderer so the access matrix UI remains authoritative.
    if self.category is not None and self.category not in setup_ui.CATEGORIES:
        return await self._sentrix_v3_original_build_embed()

    conf = await self.bot.db.get_guild_config(self.guild.id)
    statuses = await setup_ui.module_statuses(self.bot, self.guild, conf)
    subpage = getattr(self, "_v3_subpage", None)

    if self.category is None:
        active = 0
        for key in statuses:
            if await _module_state(self.bot, self.guild.id, key):
                active += 1
        panel = embeds.brand(
            "SentriX — Control Center",
            'Configuration complète du serveur. Choisissez une page dans le menu sous le panneau.',
        )
        panel.add_field(name="Serveur", value=f"**{self.guild.name}**\n{self.guild.member_count or 0} membre(s)", inline=True)
        panel.add_field(name="Configuration", value=f"**{setup_ui._completion(statuses)} %**\n{active}/{len(statuses)} modules activés", inline=True)
        errors = [(key, data) for key, data in statuses.items() if data[0] == setup_ui.ConfigState.ERROR]
        panel.add_field(name="État général", value="À corriger" if errors else "Opérationnel", inline=True)

        def line(key: str) -> str:
            state = statuses[key][0].value if key in statuses else "NON CONFIGURÉ"
            return f"**{setup_ui.CATEGORIES[key][0]}** — {state}"

        panel.add_field(name="Protection", value="\n".join(line(k) for k in ("moderation", "security", "logs")), inline=True)
        panel.add_field(name="Communauté", value="\n".join(line(k) for k in ("tickets", "welcome", "roles")), inline=True)
        panel.add_field(name="Systèmes", value="\n".join(line(k) for k in ("levels", "notifications", "ai")), inline=True)
        if errors:
            panel.add_field(
                name="Problèmes détectés",
                value="\n".join(f"**{setup_ui.CATEGORIES[key][0]}** — {data[2][0]}" for key, data in errors)[:1024],
                inline=False,
            )
        return panel

    title, description = setup_ui.CATEGORIES[self.category]
    module_on = await _module_state(self.bot, self.guild.id, self.category)
    state, summary, problems = statuses[self.category]
    shown_state = "INACTIF" if not module_on else state.value
    page_title = title
    if self.category == "security" and subpage == "verification":
        page_title = "Sécurité — Vérification"
    elif self.category == "roles" and subpage == "panel":
        page_title = "Rôles — Panel de choix"
    elif self.category == "roles" and subpage == "rules":
        page_title = "Rôles — Règles & CAPTCHA"

    panel = embeds.brand(f"SentriX — {page_title}", description)
    panel.add_field(name="État", value=f"**{shown_state}**", inline=True)
    panel.add_field(name="Configuration", value=summary, inline=True)
    panel.add_field(name="Module", value=_state_text(module_on), inline=True)

    if self.category == "security" and subpage == "verification":
        cog = self.bot.get_cog(honeypot_v50._COG_NAME)
        hp = await cog.config(self.guild.id, enabled_only=False) if cog else None
        if hp and int(hp["enabled"]):
            verify = setup_ui._channel(self.guild, hp["verify_channel_id"])
            trap = setup_ui._channel(self.guild, hp["trap_channel_id"])
            sanction = "Softban" if str(hp["sanction"]) == "softban" else "Expulsion"
            value = f"**Vérification :** {verify}\n**Honeypot :** {trap}\n**Sanction :** {sanction}"
        else:
            value = "Vérification renforcée et honeypot désactivés."
        panel.add_field(name="Portail de vérification", value=value, inline=False)
        panel.add_field(
            name="Contrôles",
            value=(
                "Membership Screening Discord\n"
                f"Âge minimum du compte : {honeypot_v50.MIN_ACCOUNT_AGE_SECONDS // 60} min\n"
                "Challenge interactif anti-automatisation\nCode unique + calcul à usage unique\n"
                f"Verrouillage après {honeypot_v50.MAX_FAILURES} échecs"
            ),
            inline=True,
        )
        panel.add_field(name="Honeypot", value="Un message dans le salon piège déclenche l'action configurée.\nLes administrateurs sont exemptés.", inline=True)
    elif self.category == "security":
        row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id=?", (self.guild.id,))
        items = [f"**{label}** — {'ACTIF' if setup_ui._get(row, field, 0) else 'INACTIF'}" for field, label in setup_ui.AUTOMOD]
        half = (len(items) + 1) // 2
        panel.add_field(name="Protections automatiques", value="\n".join(items[:half]), inline=True)
        panel.add_field(name="Protections avancées", value="\n".join(items[half:]) or "—", inline=True)
        hp = await self.bot.db.fetchone("SELECT enabled,sanction FROM honeypot_verification WHERE guild_id=?", (self.guild.id,))
        panel.add_field(name="Vérification & Honeypot", value="ACTIF" if hp and int(hp["enabled"]) else "INACTIF", inline=False)
    elif self.category == "roles" and subpage == "panel":
        settings = await _self_role_settings(self.bot, self.guild.id)
        ids = await _configured_role_ids(self.bot, self.guild.id, 0)
        roles = [self.guild.get_role(role_id) for role_id in ids]
        roles = [role for role in roles if role]
        panel.add_field(name="Salon", value=setup_ui._channel(self.guild, settings.get("channel_id")), inline=True)
        panel.add_field(name="Rôles proposés", value=f"**{len(roles)}** / 25", inline=True)
        panel.add_field(name="Panel", value=_state_text(bool(int(settings.get("enabled", 1)))), inline=True)
        panel.add_field(name="Sélection actuelle", value="\n".join(role.mention for role in roles[:20]) or "Aucun rôle sélectionné.", inline=False)
        me = self.guild.me
        role_ok = bool(me and me.guild_permissions.manage_roles)
        panel.add_field(name="Vérification technique", value="Gérer les rôles : OK" if role_ok else "Gérer les rôles : MANQUANT", inline=False)
    elif self.category == "roles" and subpage == "rules":
        role_id = setup_ui._get(conf, "verify_role") or setup_ui._get(conf, "verification_role")
        role = self.guild.get_role(int(role_id)) if role_id else None
        captcha_on = bool(setup_ui._get(conf, "verify_captcha_enabled", 1))
        max_attempts = setup_ui._get(conf, "verify_captcha_max_attempts", 3)
        # Une couche partagée bien plus en aval du setup (setup_oxyde_v69.py::_build_page,
        # limit=4 -- pas 5, pas 6, un plafond DIFFERENT de celui de setup_polish_v70.py sur
        # la MEME chaine) plafonne chaque page à 4 champs propres, quelle que soit la
        # catégorie -- pas seulement celle-ci. Mesuré en instrumentant add_field() sur un
        # boot complet : un 5e champ ("Vérification technique" à part) disparaissait
        # silencieusement. On fusionne donc le diagnostic dans le champ du rôle plutôt que
        # de lui laisser son propre champ, pour rester à 4 sans rien perdre.
        problem = verification_module.role_grant_problem(self.guild, role)
        role_value = setup_ui._role(self.guild, role_id)
        if problem:
            role_value += f"\n⚠️ {problem}"
        panel.add_field(name="Salon des règles", value=setup_ui._channel(self.guild, setup_ui._get(conf, "rules_channel")), inline=True)
        panel.add_field(name="Rôle donné", value=role_value, inline=True)
        panel.add_field(name="CAPTCHA", value=_state_text(captcha_on), inline=True)
        panel.add_field(name="Tentatives max.", value=f"**{max_attempts}**", inline=True)
    elif self.category == "roles":
        rewards = await self.bot.db.fetchall("SELECT level,role_id FROM level_roles WHERE guild_id=? ORDER BY level", (self.guild.id,))
        panel.add_field(
            name="Rôles principaux",
            value=(
                f"**Autorole :** {setup_ui._role(self.guild, setup_ui._get(conf, 'autorole'))}\n"
                f"**Vérifié :** {setup_ui._role(self.guild, setup_ui._get(conf, 'verify_role') or setup_ui._get(conf, 'verification_role'))}\n"
                f"**Membre principal :** {setup_ui._role(self.guild, setup_ui._get(conf, 'member_role'))}"
            ),
            inline=False,
        )
        panel.add_field(name="Récompenses de niveau", value="\n".join(f"Niveau **{row['level']}** → {setup_ui._role(self.guild, row['role_id'])}" for row in rewards[:15]) or "Aucune récompense configurée.", inline=False)
    elif self.category == "welcome":
        panel.add_field(name="Bienvenue", value=setup_ui._channel(self.guild, setup_ui._get(conf, "welcome_channel")), inline=True)
        panel.add_field(name="Départ", value=setup_ui._channel(self.guild, setup_ui._get(conf, "goodbye_channel")), inline=True)
        panel.add_field(name="Autorole", value=setup_ui._role(self.guild, setup_ui._get(conf, "autorole")), inline=True)
        panel.add_field(name="Variables", value="`{mention}` `{member}` `{user}` `{username}` `{display_name}` `{server}` `{member_count}`", inline=False)
    elif self.category == "moderation":
        panel.add_field(name="Rôle staff", value=setup_ui._role(self.guild, setup_ui._get(conf, "mod_role")), inline=True)
        panel.add_field(name="Rôle mute", value=setup_ui._role(self.guild, setup_ui._get(conf, "mute_role")), inline=True)
        panel.add_field(name="Rôle warn", value=setup_ui._role(self.guild, setup_ui._get(conf, "warn_role")), inline=True)
        panel.add_field(name="Fonctions", value="Warn • Mute • Unmute • Kick • Ban • Unban • Clear • Nickname • Lock", inline=False)
    elif self.category == "logs":
        lines = []
        for log_type, meta in setup_ui.log_service.LOG_TYPES.items():
            if not meta.get("emits"):
                continue
            setting = await setup_ui.log_service.get_log_setting(self.bot, self.guild.id, log_type)
            lines.append(f"**{meta['category']}** — {'ACTIF' if setting.get('enabled') else 'INACTIF'} — {setup_ui._channel(self.guild, setting.get('channel_id'))}")
        panel.add_field(name="Routage", value="\n".join(lines[:12])[:1024] or "Aucun log configuré.", inline=False)
    elif self.category == "levels":
        economy_on = await setup_v2_core.module_enabled(self.bot, self.guild.id, "economy")
        currency = await setup_v2_core.economy_settings(self.bot, self.guild.id)
        panel.add_field(name="Niveaux", value=f"**{_state_text(module_on)}**\nSalon : {setup_ui._channel(self.guild, setup_ui._get(conf, 'level_channel'))}", inline=True)
        panel.add_field(name="Économie", value=f"**{_state_text(economy_on)}**\nMonnaie : {currency['currency_plural']} {currency['currency_symbol']}", inline=True)
    elif self.category == "notifications":
        rows = await self.bot.db.fetchall("SELECT platform,discord_channel_id,role_id,enabled FROM social_notifications WHERE guild_id=? ORDER BY id", (self.guild.id,))
        panel.add_field(name="Sources", value="\n".join(f"**{str(row['platform']).title()}** — {'ACTIF' if row['enabled'] else 'INACTIF'} — {setup_ui._channel(self.guild, row['discord_channel_id'])}" for row in rows[:15]) or "Aucune source configurée.", inline=False)
    elif self.category == "ai":
        ai = await self.bot.db.fetchone("SELECT * FROM ai_settings WHERE guild_id=?", (self.guild.id,))
        panel.add_field(name="Assistant", value=f"**{_state_text(bool(setup_ui._get(ai, 'enabled', 1)))}**\nDéclencheur naturel : `sentrix salut`", inline=True)
        panel.add_field(name="Limites", value=f"Cooldown : {setup_ui._get(ai, 'cooldown_seconds', 8)} s\nMinute : {setup_ui._get(ai, 'per_minute_limit', 6)}\nJour : {setup_ui._get(ai, 'daily_limit', 50)}", inline=True)

    me = self.guild.me
    perms = me.guild_permissions if me else discord.Permissions.none()
    required = setup_ui.BOT_PERMS.get(self.category, ())
    if required:
        lines = [f"{setup_ui.PERM_LABELS.get(name, name)} : {'OK' if getattr(perms, name, False) else 'MANQUANT'}" for name in required]
        panel.add_field(name="Permissions du bot", value="\n".join(lines), inline=False)
    if problems:
        panel.add_field(name="Problèmes détectés", value="\n".join(problems)[:1024], inline=False)
    return panel


def _v3_render(self) -> None:
    if self.category is not None and self.category not in setup_ui.CATEGORIES:
        self._sentrix_v3_original_render()
        # Uniformise au moins la navigation des pages injectées dynamiquement sans toucher
        # à leurs contrôles métier.
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and child.label in {"Accueil", "Actualiser", "Fermer"}:
                self.remove_item(child)
        return

    self.clear_items()
    self.add_item(V3CategorySelect(self))
    if self.category is None:
        return

    # Le seul bouton permanent sous une page est le petit toggle du module.
    # Les autres configurations utilisent des selects.
    # État chargé de façon asynchrone dans build_embed ; le callback relit toujours la DB.
    toggle = ModuleToggle(self, self.category, True)
    self.add_item(toggle)

    subpage = getattr(self, "_v3_subpage", None)
    if self.category == "moderation":
        self.add_item(setup_ui.FieldRoleSelect(self, "mod_role", "Rôle staff", 2))
        self.add_item(setup_ui.FieldRoleSelect(self, "mute_role", "Rôle mute", 3))
        self.add_item(setup_ui.FieldRoleSelect(self, "warn_role", "Rôle warn", 4))
    elif self.category == "security" and subpage == "verification":
        self.add_item(SecurityVerificationSelect(self))
    elif self.category == "security":
        self.add_item(setup_ui.AutomodSelect(self))
    elif self.category == "welcome":
        self.add_item(setup_ui.FieldChannelSelect(self, "welcome_channel", "Salon de bienvenue", 2))
        self.add_item(setup_ui.FieldChannelSelect(self, "goodbye_channel", "Salon de départ", 3))
        self.add_item(setup_ui.FieldRoleSelect(self, "autorole", "Rôle automatique", 4))
    elif self.category == "roles" and subpage == "panel":
        self.add_item(RolePanelChannelSelect(self))
        self.add_item(RolePanelRolesSelect(self))
    elif self.category == "roles" and subpage == "rules":
        self.add_item(setup_ui.FieldChannelSelect(self, "rules_channel", "Salon des règles", 2))
        self.add_item(setup_ui.FieldRoleSelect(self, "verify_role", "Rôle donné après vérification", 3))
        self.add_item(CaptchaToggleButton(self))
        self.add_item(CaptchaMaxAttemptsButton(self))
        self.add_item(SendRulesPanelButton(self))
    elif self.category == "roles":
        self.add_item(setup_ui.FieldRoleSelect(self, "autorole", "Autorole", 2))
        self.add_item(setup_ui.FieldRoleSelect(self, "member_role", "Rôle membre principal", 3))
    elif self.category == "levels":
        self.add_item(setup_ui.FieldChannelSelect(self, "level_channel", "Salon des niveaux", 2))
    elif self.category == "logs":
        self.add_item(setup_ui.LogSelect(self))
        if self.selected_log:
            self.add_item(setup_ui.LogChannelSelect(self))
            self.add_item(LogActionSelect(self))
    elif self.category == "ai":
        self.add_item(AiActionSelect(self))


async def _v3_refresh(self, interaction: discord.Interaction):
    self.render()
    # Corrige le libellé du petit toggle avec l'état DB réel juste avant l'envoi.
    if self.category in setup_v2_core.MODULES:
        enabled = await _module_state(self.bot, self.guild.id, self.category)
        for child in self.children:
            if isinstance(child, ModuleToggle):
                child.label = "Désactiver" if enabled else "Activer"
                child.style = discord.ButtonStyle.secondary if enabled else discord.ButtonStyle.success
    if self.category == "roles" and getattr(self, "_v3_subpage", None) == "rules":
        conf = await self.bot.db.get_guild_config(self.guild.id)
        captcha_on = bool(setup_ui._get(conf, "verify_captcha_enabled", 1))
        for child in self.children:
            if isinstance(child, CaptchaToggleButton):
                child.label = "CAPTCHA : Activé" if captcha_on else "CAPTCHA : Désactivé"
                child.style = discord.ButtonStyle.success if captcha_on else discord.ButtonStyle.secondary
    await interaction.response.edit_message(embed=await self.build_embed(), view=self)


def _install_setup_v3(bot: commands.Bot) -> None:
    cls = setup_ui.SetupView
    if getattr(cls, "_sentrix_control_center_v3", False):
        return
    cls._sentrix_v3_original_render = cls.render
    cls._sentrix_v3_original_build_embed = cls.build_embed
    cls._sentrix_v3_original_refresh = cls.refresh
    cls.render = _v3_render
    cls.build_embed = _v3_build_embed
    cls.refresh = _v3_refresh
    cls._sentrix_control_center_v3 = True


# ---------------------------------------------------------------------------
# Compact achievement UX
# ---------------------------------------------------------------------------

def _install_compact_achievement_messages() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_control_center_v3_achievements", False):
        return

    async def compact_send(self: commands.Context, *args, **kwargs):
        embed = kwargs.get("embed")
        if isinstance(embed, discord.Embed):
            combined = " ".join(str(x or "") for x in (embed.title, embed.description)).casefold()
            if "succès débloqué" in combined or "première commande" in combined:
                # La récompense est déjà enregistrée par son moteur. On garde une notification
                # courte au lieu d'un deuxième grand panneau qui ressemble à une réponse.
                title = str(embed.title or "Succès débloqué").strip()
                description = str(embed.description or "").strip()
                kwargs.pop("embed", None)
                compact = f"**{title}**"
                if description:
                    first = description.splitlines()[0].strip()
                    if first:
                        compact += f" — {first}"
                kwargs["content"] = compact[:1900]
        return await current(self, *args, **kwargs)

    compact_send._sentrix_control_center_v3_achievements = True
    compact_send._sentrix_original = current
    commands.Context.send = compact_send


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_control_center_v3_installed", False):
        return

    await setup_v2_core.ensure_schema(bot)
    await bot.db.execute(_SELF_ROLE_SCHEMA)
    # Tables historiques : les créations sont additives et ne suppriment aucune donnée.
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS self_role_items (guild_id INTEGER NOT NULL,panel_message_id INTEGER NOT NULL,role_id INTEGER NOT NULL,PRIMARY KEY(guild_id,panel_message_id,role_id))"
    )

    _install_semantic_renderer()
    await _install_honeypot_runtime(bot)
    _install_self_role_backend(bot)
    _install_setup_v3(bot)
    _install_compact_achievement_messages()

    bot._sentrix_control_center_v3_installed = True
    logger.info(
        "Control Center V3 actif : Setup premium, sécurité/honeypot, rôles et rendu sémantique."
    )
