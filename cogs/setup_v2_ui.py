"""Extension du centre +setup officiel pour les réglages V2.

Le panneau historique reste propriétaire du message ; cette couche ajoute les contrôles
manquants sans créer un deuxième setup concurrent.
"""
from __future__ import annotations

import json
import re
import time

import discord

from utils import embeds, log_service
from utils import sentrix_panels as panels
from . import permission_guard
from . import setup_control_center as setup_ui
from . import setup_v2_core as core
from . import channel_message_rules

MODULE_BY_CATEGORY = {
    "moderation": "moderation",
    "security": "security",
    "logs": "logs",
    "tickets": "tickets",
    "welcome": "welcome",
    "roles": "roles",
    "levels": "levels",
    "notifications": "notifications",
    "ai": "ai",
}

SCOPE_LABELS = {
    "public": "Membres / utilitaires",
    "moderation": "Modération",
    "securite": "Sécurité",
    "security": "Sécurité",
    "tickets": "Tickets",
    "economie": "Économie / gestion",
    "economy": "Économie membres",
    "levels": "Niveaux",
    "ai": "IA",
    "configuration": "Configuration",
    "notifications": "Notifications",
    "complete": "Administration avancée",
    "other": "Autres",
}


async def ensure_ui_schema(bot) -> None:
    await core.ensure_schema(bot)
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_feature_settings_v2 (
            guild_id INTEGER PRIMARY KEY,
            natural_enabled INTEGER NOT NULL DEFAULT 1,
            commands_enabled INTEGER NOT NULL DEFAULT 1,
            image_analysis_enabled INTEGER NOT NULL DEFAULT 1,
            image_generation_enabled INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL
        )
        """
    )


async def get_ai_features(bot, guild_id: int) -> dict:
    await ensure_ui_schema(bot)
    row = await bot.db.fetchone("SELECT * FROM ai_feature_settings_v2 WHERE guild_id=?", (guild_id,))
    if row is None:
        return {
            "natural_enabled": True,
            "commands_enabled": True,
            "image_analysis_enabled": True,
            "image_generation_enabled": True,
        }
    return {
        "natural_enabled": bool(row["natural_enabled"]),
        "commands_enabled": bool(row["commands_enabled"]),
        "image_analysis_enabled": bool(row["image_analysis_enabled"]),
        "image_generation_enabled": bool(row["image_generation_enabled"]),
    }


async def set_ai_feature(bot, guild_id: int, key: str, value: bool, actor_id: int) -> None:
    allowed = {"natural_enabled", "commands_enabled", "image_analysis_enabled", "image_generation_enabled"}
    if key not in allowed:
        raise ValueError("feature IA invalide")
    await ensure_ui_schema(bot)
    await bot.db.execute(
        "INSERT INTO ai_feature_settings_v2 (guild_id, updated_by, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(guild_id) DO NOTHING",
        (guild_id, actor_id, int(time.time())),
    )
    await bot.db.execute(
        f"UPDATE ai_feature_settings_v2 SET {key}=?, updated_by=?, updated_at=? WHERE guild_id=?",
        (1 if value else 0, actor_id, int(time.time()), guild_id),
    )


class PermissionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(placeholder="Rôle à configurer (sinon @everyone)", min_values=1, max_values=1, row=2)

    async def callback(self, interaction):
        self.owner.selected_permission_role = self.values[0].id
        self.owner.selected_permission_command = None
        self.owner.permission_page = 0
        await self.owner.refresh(interaction)


class PermissionScopeSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        scopes = []
        for scope in (
            "public", "moderation", "securite", "tickets", "economy", "economie",
            "levels", "ai", "notifications", "configuration", "complete", "other",
        ):
            if core.commands_for_scope(owner.bot, scope):
                scopes.append(discord.SelectOption(label=SCOPE_LABELS.get(scope, scope.title()), value=scope))
        super().__init__(placeholder="Groupe de commandes", options=scopes[:25], row=3)

    async def callback(self, interaction):
        self.owner.selected_permission_scope = self.values[0]
        self.owner.selected_permission_command = None
        self.owner.permission_page = 0
        await self.owner.refresh(interaction)


class PermissionCommandSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        scope = getattr(owner, "selected_permission_scope", "public")
        commands = core.commands_for_scope(owner.bot, scope)
        page = max(0, int(getattr(owner, "permission_page", 0)))
        page_count = max(1, (len(commands) + 23) // 24)
        page %= page_count
        owner.permission_page = page
        start = page * 24
        chunk = commands[start:start + 24]
        options = [discord.SelectOption(label=f"+{name} / /{name}"[:100], value=name) for name in chunk]
        if len(commands) > 24:
            options.append(discord.SelectOption(label=f"Page suivante ({page + 1}/{page_count})", value="__next__"))
        if not options:
            options = [discord.SelectOption(label="Aucune commande dans ce groupe", value="__none__")]
        super().__init__(placeholder="Commande à configurer", options=options, row=4)

    async def callback(self, interaction):
        value = self.values[0]
        if value == "__next__":
            self.owner.permission_page = int(getattr(self.owner, "permission_page", 0)) + 1
            self.owner.selected_permission_command = None
        elif value != "__none__":
            self.owner.selected_permission_command = value
        await self.owner.refresh(interaction)


class WhitelistUserSelect(discord.ui.UserSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(placeholder="Membre, modérateur, admin ou bot de confiance", min_values=1, max_values=1, row=3)

    async def callback(self, interaction):
        self.owner.selected_whitelist_user = self.values[0].id
        await self.owner.refresh(interaction)


class CurrencyModal(discord.ui.Modal, title="Nom de la monnaie"):
    singular = discord.ui.TextInput(label="Singulier", placeholder="Coin", max_length=32)
    plural = discord.ui.TextInput(label="Pluriel", placeholder="Coins", max_length=32)
    symbol = discord.ui.TextInput(label="Symbole / emoji", placeholder="🪙", max_length=16)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction):
        await core.set_currency(
            self.owner.bot,
            self.owner.guild.id,
            str(self.singular.value),
            str(self.plural.value),
            str(self.symbol.value),
            actor_id=interaction.user.id,
        )
        await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success('Nom de la monnaie mis à jour.')), ephemere=True)


class EconomyManageView(discord.ui.View):
    def __init__(self, setup_view, author_id: int):
        super().__init__(timeout=180)
        self.setup_view = setup_view
        self.bot = setup_view.bot
        self.guild = setup_view.guild
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Activer / Désactiver l’économie", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction, _button):
        current = await core.module_enabled(self.bot, self.guild.id, "economy")
        await core.set_module_enabled(self.bot, self.guild.id, "economy", not current, actor_id=interaction.user.id)
        await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success(f"Économie {('activée' if not current else 'désactivée')}. Les soldes sont conservés.")), ephemere=True)

    @discord.ui.button(label="Changer le nom de l’argent", style=discord.ButtonStyle.secondary, row=0)
    async def currency(self, interaction, _button):
        await interaction.response.send_modal(CurrencyModal(self.setup_view))


class LevelRewardModal(discord.ui.Modal, title="Récompense de niveau"):
    level = discord.ui.TextInput(label="Niveau", placeholder="10", max_length=5)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction):
        try:
            level = int(str(self.level.value).strip())
        except ValueError:
            return await interaction.response.send_message("Le niveau doit être un nombre entier.", ephemeral=True)
        if not 1 <= level <= 100000:
            return await interaction.response.send_message("Choisissez un niveau entre 1 et 100000.", ephemeral=True)
        await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.info(f'Choisissez le rôle à donner au **niveau {level}**.')), RewardRoleView(self.owner, interaction.user.id, level)), ephemere=True)


class RewardRoleView(discord.ui.View):
    def __init__(self, owner, author_id: int, level: int):
        super().__init__(timeout=180)
        self.owner = owner
        self.author_id = author_id
        self.level = level
        self.role_id = None
        select = discord.ui.RoleSelect(placeholder="Rôle récompense", min_values=1, max_values=1, row=0)
        async def select_cb(interaction):
            self.role_id = select.values[0].id
            await interaction.response.send_message("Rôle sélectionné. Cliquez sur Enregistrer.", ephemeral=True)
        select.callback = select_cb
        self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Enregistrer", style=discord.ButtonStyle.success, row=1)
    async def save(self, interaction, _button):
        if not self.role_id:
            return await interaction.response.send_message("Choisissez d’abord un rôle.", ephemeral=True)
        await self.owner.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id=excluded.role_id",
            (self.owner.guild.id, self.level, self.role_id),
        )
        await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success(f'Récompense du niveau {self.level} enregistrée.')), ephemere=True)

    @discord.ui.button(label="Supprimer ce palier", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction, _button):
        await self.owner.bot.db.execute(
            "DELETE FROM level_roles WHERE guild_id=? AND level=?",
            (self.owner.guild.id, self.level),
        )
        await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success(f'Palier niveau {self.level} supprimé.')), ephemere=True)


class WelcomeTextModal(discord.ui.Modal, title="Messages de bienvenue et départ"):
    welcome = discord.ui.TextInput(
        label="Message de bienvenue",
        placeholder="Bienvenue {member} sur {server} !",
        required=False,
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )
    goodbye = discord.ui.TextInput(
        label="Message de départ",
        placeholder="{username} a quitté {server}.",
        required=False,
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction):
        gid = self.owner.guild.id
        welcome = str(self.welcome.value).strip() or None
        goodbye = str(self.goodbye.value).strip() or None
        await self.owner.bot.db.set_guild_config(gid, "welcome_message", welcome)
        await self.owner.bot.db.set_guild_config(gid, "goodbye_message", goodbye)
        await panels.envoyer(
            interaction.response,
            panels.depuis_embed(
                embeds.success(
                    "Messages enregistrés. Les fonds se choisissent dans le dashboard parmi les 3 modèles SentriX."
                )
            ),
            ephemere=True,
        )


class AiFeatureView(discord.ui.View):
    def __init__(self, owner, author_id: int):
        super().__init__(timeout=180)
        self.owner = owner
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction, key, label):
        values = await get_ai_features(self.owner.bot, self.owner.guild.id)
        new_value = not values[key]
        await set_ai_feature(self.owner.bot, self.owner.guild.id, key, new_value, interaction.user.id)
        await interaction.response.send_message(f"{label} : {'ACTIF' if new_value else 'INACTIF'}", ephemeral=True)

    @discord.ui.button(label="Conversation naturelle", style=discord.ButtonStyle.secondary, row=0)
    async def natural(self, interaction, _button):
        await self._toggle(interaction, "natural_enabled", "Conversation naturelle")

    @discord.ui.button(label="Commandes IA", style=discord.ButtonStyle.secondary, row=0)
    async def commands(self, interaction, _button):
        await self._toggle(interaction, "commands_enabled", "Commandes IA")

    @discord.ui.button(label="Analyse d’images", style=discord.ButtonStyle.secondary, row=1)
    async def analysis(self, interaction, _button):
        await self._toggle(interaction, "image_analysis_enabled", "Analyse d’images")

    @discord.ui.button(label="Génération d’images", style=discord.ButtonStyle.secondary, row=1)
    async def generation(self, interaction, _button):
        await self._toggle(interaction, "image_generation_enabled", "Génération d’images")


class NotificationSourceModal(discord.ui.Modal, title="Source de notification"):
    url = discord.ui.TextInput(label="Lien YouTube / TikTok / Twitch", max_length=500)
    text = discord.ui.TextInput(label="Texte personnalisé (facultatif)", required=False, max_length=600, style=discord.TextStyle.paragraph)
    image = discord.ui.TextInput(label="URL d’image facultative", required=False, max_length=500)

    def __init__(self, owner, mode: str):
        super().__init__()
        self.owner = owner
        self.mode = mode

    async def on_submit(self, interaction):
        from . import notifications as notif_mod
        source_url = str(self.url.value).strip()
        if not notif_mod._is_supported_social_url(source_url):
            return await interaction.response.send_message("Lien social HTTPS non reconnu.", ephemeral=True)
        source_url = notif_mod._normalize_source_url(source_url)
        text = str(self.text.value).strip() or None
        image = str(self.image.value).strip() or None
        if image and not notif_mod._valid_https_url(image):
            return await interaction.response.send_message("L’URL d’image doit être HTTPS.", ephemeral=True)
        if self.mode == "edit" and self.owner.selected_notification:
            duplicate = await self.owner.bot.db.fetchone(
                "SELECT id FROM social_notifications WHERE guild_id=? AND source_url=? AND id<>?",
                (self.owner.guild.id, source_url, self.owner.selected_notification),
            )
            if duplicate:
                return await interaction.response.send_message("Cette source existe déjà sur ce serveur.", ephemeral=True)
            platform, _ = notif_mod._platform_details(source_url)
            await self.owner.bot.db.execute(
                "UPDATE social_notifications SET source_url=?, platform=?, custom_text=?, image_url=? WHERE guild_id=? AND id=?",
                (source_url, platform, text, image, self.owner.guild.id, self.owner.selected_notification),
            )
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success('Source modifiée sans toucher aux autres notifications.')), ephemere=True)
        await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.info('Choisissez maintenant le salon et le rôle. La nouvelle source sera ajoutée sans remplacer les autres.')), NotificationDraftView(self.owner, interaction.user.id, source_url, text, image)), ephemere=True)


class NotificationDraftView(discord.ui.View):
    def __init__(self, owner, author_id: int, source_url: str, text: str | None, image: str | None):
        super().__init__(timeout=240)
        self.owner = owner
        self.author_id = author_id
        self.source_url = source_url
        self.text = text
        self.image = image
        self.channel_id = None
        self.role_id = None
        channel_select = discord.ui.ChannelSelect(
            placeholder="Salon de la notification", min_values=1, max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=0,
        )
        role_select = discord.ui.RoleSelect(placeholder="Rôle à ping", min_values=1, max_values=1, row=1)
        async def channel_cb(interaction):
            self.channel_id = channel_select.values[0].id
            await interaction.response.send_message("Salon sélectionné.", ephemeral=True)
        async def role_cb(interaction):
            self.role_id = role_select.values[0].id
            await interaction.response.send_message("Rôle sélectionné.", ephemeral=True)
        channel_select.callback = channel_cb
        role_select.callback = role_cb
        self.add_item(channel_select)
        self.add_item(role_select)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Enregistrer la nouvelle source", style=discord.ButtonStyle.success, row=2)
    async def save(self, interaction, _button):
        if not self.channel_id or not self.role_id:
            return await interaction.response.send_message("Choisissez un salon et un rôle.", ephemeral=True)
        from . import notifications as notif_mod
        existing = await self.owner.bot.db.fetchone(
            "SELECT id FROM social_notifications WHERE guild_id=? AND source_url=?",
            (self.owner.guild.id, self.source_url),
        )
        if existing:
            return await interaction.response.send_message("Cette source existe déjà. Sélectionnez-la pour la modifier.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            latest = await notif_mod._extract_latest(self.source_url)
        except Exception:
            latest = None
        platform, _ = notif_mod._platform_details(self.source_url)
        latest_id = str(latest.get("id") or "") if latest else ""
        latest_url = notif_mod._item_url(platform, self.source_url, latest or {}) if latest else self.source_url
        now = int(time.time())
        await self.owner.bot.db.execute(
            "INSERT INTO social_notifications "
            "(guild_id, source_url, platform, discord_channel_id, role_id, custom_text, image_url, "
            "last_item_id, last_item_url, enabled, created_at, last_checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                self.owner.guild.id, self.source_url, platform, self.channel_id, self.role_id,
                self.text, self.image, latest_id or None, latest_url, now, now,
            ),
        )
        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success('Nouvelle source ajoutée. Les sources précédentes sont inchangées.')), ephemere=True)


class NotificationManageView(discord.ui.View):
    def __init__(self, owner, author_id: int):
        super().__init__(timeout=180)
        self.owner = owner
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, _button):
        await interaction.response.send_modal(NotificationSourceModal(self.owner, "add"))

    @discord.ui.button(label="Modifier la source sélectionnée", style=discord.ButtonStyle.secondary, row=0)
    async def edit(self, interaction, _button):
        if not self.owner.selected_notification:
            return await interaction.response.send_message("Sélectionnez d’abord une notification dans +setup.", ephemeral=True)
        await interaction.response.send_modal(NotificationSourceModal(self.owner, "edit"))

    @discord.ui.button(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=1)
    async def toggle(self, interaction, _button):
        if not self.owner.selected_notification:
            return await interaction.response.send_message("Sélectionnez d’abord une notification.", ephemeral=True)
        row = await self.owner.bot.db.fetchone(
            "SELECT enabled FROM social_notifications WHERE guild_id=? AND id=?",
            (self.owner.guild.id, self.owner.selected_notification),
        )
        if row is None:
            return await interaction.response.send_message("Notification introuvable.", ephemeral=True)
        await self.owner.bot.db.execute(
            "UPDATE social_notifications SET enabled=? WHERE guild_id=? AND id=?",
            (0 if row["enabled"] else 1, self.owner.guild.id, self.owner.selected_notification),
        )
        await interaction.response.send_message("État modifié. Les autres sources ne changent pas.", ephemeral=True)

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction, _button):
        if not self.owner.selected_notification:
            return await interaction.response.send_message("Sélectionnez d’abord une notification.", ephemeral=True)
        await self.owner.bot.db.execute(
            "DELETE FROM social_notifications WHERE guild_id=? AND id=?",
            (self.owner.guild.id, self.owner.selected_notification),
        )
        self.owner.selected_notification = None
        await interaction.response.send_message("Source supprimée. Les autres notifications restent intactes.", ephemeral=True)


async def _permission_decision_for_view(view) -> str | None:
    role_id = int(getattr(view, "selected_permission_role", view.guild.default_role.id))
    command_name = getattr(view, "selected_permission_command", None)
    if not command_name:
        return None
    await core.ensure_schema(view.bot)
    row = await view.bot.db.fetchone(
        "SELECT decision FROM command_role_permissions WHERE guild_id=? AND role_id=? AND command_name=?",
        (view.guild.id, role_id, command_name),
    )
    return str(row["decision"]) if row else None


def _patch_can_setup() -> None:
    current = setup_ui._can_setup
    if getattr(current, "_sentrix_v2", False):
        return
    async def can_setup_v2(bot, member, guild):
        if await current(bot, member, guild):
            return True
        if guild is None or member is None:
            return False
        decision = await permission_guard.evaluate_command_access(
            bot, command_name="setup", author=member, guild=guild,
        )
        return bool(decision.allowed)
    can_setup_v2._sentrix_v2 = True
    setup_ui._can_setup = can_setup_v2



async def ensure_automation_schema(bot) -> None:
    """Même table de réactions que le dashboard + règles de salons partagées."""
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_auto_reaction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            emojis_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            mode TEXT NOT NULL DEFAULT 'all',
            keyword TEXT NOT NULL DEFAULT '',
            ignore_bots INTEGER NOT NULL DEFAULT 1,
            created_by BIGINT,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL
        )
        """
    )
    await channel_message_rules.ensure_schema(bot)


def _automation_emoji_valid(token: str) -> bool:
    value = str(token or "").strip()
    if not value or len(value) > 100:
        return False
    if re.fullmatch(r"<a?:[A-Za-z0-9_]{2,32}:\d{5,25}>", value):
        return True
    return not value.startswith("<") and not value.endswith(">")


async def _automation_reaction_rows(bot, guild_id: int):
    await ensure_automation_schema(bot)
    return await bot.db.fetchall(
        "SELECT id,channel_id,emojis_json,enabled,mode,keyword,ignore_bots "
        "FROM sentrix_dashboard_auto_reaction WHERE guild_id=? "
        "ORDER BY updated_at DESC,id DESC LIMIT 25",
        (guild_id,),
    )


class AutoReactionModal(discord.ui.Modal, title="Réaction automatique"):
    emojis = discord.ui.TextInput(
        label="Emojis",
        placeholder="👍 👎 ou emojis du serveur",
        max_length=400,
    )
    keyword = discord.ui.TextInput(
        label="Mot-clé (seulement si mode mot-clé)",
        placeholder="gg",
        required=False,
        max_length=80,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction):
        if not self.owner.channel_id:
            return await interaction.response.send_message("Choisissez d’abord un salon.", ephemeral=True)
        raw = str(self.emojis.value or "").replace(",", " ").split()
        emojis = []
        for value in raw:
            token = value.strip()
            if token and token not in emojis:
                if not _automation_emoji_valid(token):
                    return await interaction.response.send_message(f"Emoji invalide : {token[:30]}", ephemeral=True)
                emojis.append(token)
            if len(emojis) >= 8:
                break
        if not emojis:
            return await interaction.response.send_message("Ajoutez au moins un emoji.", ephemeral=True)
        keyword = str(self.keyword.value or "").strip()
        if self.owner.mode == "keyword" and not keyword:
            return await interaction.response.send_message("Ajoutez le mot-clé à détecter.", ephemeral=True)
        await ensure_automation_schema(self.owner.bot)
        now = int(time.time())
        await self.owner.bot.db.execute(
            "INSERT INTO sentrix_dashboard_auto_reaction "
            "(guild_id,channel_id,emojis_json,enabled,mode,keyword,ignore_bots,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                self.owner.guild.id,
                self.owner.channel_id,
                json.dumps(emojis, ensure_ascii=False),
                1,
                self.owner.mode,
                keyword[:80],
                1,
                interaction.user.id,
                now,
                now,
            ),
        )
        await panels.envoyer(
            interaction.response,
            panels.depuis_embed(embeds.success("Réaction automatique enregistrée.")),
            ephemere=True,
        )


class AutoReactionSetupView(discord.ui.View):
    def __init__(self, setup_view, author_id: int, rows):
        super().__init__(timeout=180)
        self.setup_view = setup_view
        self.bot = setup_view.bot
        self.guild = setup_view.guild
        self.author_id = int(author_id)
        self.channel_id = None
        self.mode = "all"
        self.selected_rule_id = None

        channel = discord.ui.ChannelSelect(
            placeholder="Salon des réactions automatiques",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )
        async def channel_cb(interaction):
            self.channel_id = channel.values[0].id
            await interaction.response.send_message("Salon sélectionné.", ephemeral=True)
        channel.callback = channel_cb
        self.add_item(channel)

        mode = discord.ui.Select(
            placeholder="Quand réagir ?",
            options=[
                discord.SelectOption(label="Tous les messages", value="all"),
                discord.SelectOption(label="Si le message contient un mot-clé", value="keyword"),
            ],
            row=1,
        )
        async def mode_cb(interaction):
            self.mode = mode.values[0]
            await interaction.response.send_message("Mode sélectionné.", ephemeral=True)
        mode.callback = mode_cb
        self.add_item(mode)

        if rows:
            options = []
            for row in rows[:25]:
                channel_obj = self.guild.get_channel(int(row["channel_id"]))
                try:
                    emojis = " ".join(json.loads(row["emojis_json"] or "[]")[:4])
                except Exception:
                    emojis = ""
                options.append(discord.SelectOption(
                    label=f"#{getattr(channel_obj, 'name', row['channel_id'])}"[:100],
                    value=str(row["id"]),
                    description=(f"{'Mot-clé' if row['mode'] == 'keyword' else 'Tous'} · {emojis}")[:100],
                ))
            existing = discord.ui.Select(
                placeholder="Règle existante à gérer",
                options=options,
                row=2,
            )
            async def existing_cb(interaction):
                self.selected_rule_id = int(existing.values[0])
                await interaction.response.send_message("Règle sélectionnée.", ephemeral=True)
            existing.callback = existing_cb
            self.add_item(existing)

        add = discord.ui.Button(label="Ajouter la réaction", style=discord.ButtonStyle.success, row=3)
        toggle = discord.ui.Button(label="Activer / Désactiver", style=discord.ButtonStyle.secondary, row=3)
        delete = discord.ui.Button(label="Supprimer", style=discord.ButtonStyle.danger, row=3)

        async def add_cb(interaction):
            if not self.channel_id:
                return await interaction.response.send_message("Choisissez d’abord un salon.", ephemeral=True)
            await interaction.response.send_modal(AutoReactionModal(self))

        async def toggle_cb(interaction):
            if not self.selected_rule_id:
                return await interaction.response.send_message("Choisissez une règle existante.", ephemeral=True)
            row = await self.bot.db.fetchone(
                "SELECT enabled FROM sentrix_dashboard_auto_reaction WHERE guild_id=? AND id=?",
                (self.guild.id, self.selected_rule_id),
            )
            if not row:
                return await interaction.response.send_message("Règle introuvable.", ephemeral=True)
            enabled = 0 if bool(row["enabled"]) else 1
            await self.bot.db.execute(
                "UPDATE sentrix_dashboard_auto_reaction SET enabled=?,updated_at=? WHERE guild_id=? AND id=?",
                (enabled, int(time.time()), self.guild.id, self.selected_rule_id),
            )
            await interaction.response.send_message(
                f"Réaction automatique {'activée' if enabled else 'désactivée'}.",
                ephemeral=True,
            )

        async def delete_cb(interaction):
            if not self.selected_rule_id:
                return await interaction.response.send_message("Choisissez une règle existante.", ephemeral=True)
            await self.bot.db.execute(
                "DELETE FROM sentrix_dashboard_auto_reaction WHERE guild_id=? AND id=?",
                (self.guild.id, self.selected_rule_id),
            )
            await interaction.response.send_message("Réaction automatique supprimée.", ephemeral=True)

        add.callback = add_cb
        toggle.callback = toggle_cb
        delete.callback = delete_cb
        self.add_item(add)
        self.add_item(toggle)
        self.add_item(delete)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


class MusicSystemSetupView(discord.ui.View):
    def __init__(self, setup_view, author_id: int, settings: dict):
        super().__init__(timeout=180)
        self.setup_view = setup_view
        self.bot = setup_view.bot
        self.guild = setup_view.guild
        self.author_id = int(author_id)
        self.channel_id = settings.get("voice_channel_id")

        channel = discord.ui.ChannelSelect(
            placeholder="Choisir le vocal musique",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.voice],
            row=0,
        )

        async def channel_cb(interaction):
            self.channel_id = channel.values[0].id
            await interaction.response.send_message(
                f"Vocal sélectionné : {channel.values[0].mention}.",
                ephemeral=True,
            )

        channel.callback = channel_cb
        self.add_item(channel)

        activate = discord.ui.Button(label="Activer", style=discord.ButtonStyle.success, row=1)
        disable = discord.ui.Button(label="Désactiver", style=discord.ButtonStyle.danger, row=1)

        async def activate_cb(interaction):
            if not self.channel_id:
                return await interaction.response.send_message(
                    "Choisissez d’abord le vocal musique.",
                    ephemeral=True,
                )
            music = self.bot.get_cog("Music")
            if music is None:
                return await interaction.response.send_message(
                    "Le module musique n’est pas chargé.",
                    ephemeral=True,
                )
            try:
                await music.configure_system(
                    self.guild,
                    enabled=True,
                    voice_channel_id=self.channel_id,
                    actor_id=interaction.user.id,
                )
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            await interaction.response.send_message(
                "Système musique activé. Quand un membre rejoint ce vocal, SentriX affiche le lecteur dans le chat du vocal.",
                ephemeral=True,
            )

        async def disable_cb(interaction):
            music = self.bot.get_cog("Music")
            if music is None:
                return await interaction.response.send_message(
                    "Le module musique n’est pas chargé.",
                    ephemeral=True,
                )
            await music.configure_system(
                self.guild,
                enabled=False,
                voice_channel_id=self.channel_id,
                actor_id=interaction.user.id,
            )
            await interaction.response.send_message(
                "Système musique désactivé. SentriX quitte aussi le vocal et arrête la session en cours.",
                ephemeral=True,
            )

        activate.callback = activate_cb
        disable.callback = disable_cb
        self.add_item(activate)
        self.add_item(disable)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


class ChannelRuleSetupView(discord.ui.View):
    def __init__(self, setup_view, author_id: int, rows):
        super().__init__(timeout=180)
        self.setup_view = setup_view
        self.bot = setup_view.bot
        self.guild = setup_view.guild
        self.author_id = int(author_id)
        self.channel_id = None
        self.mode = "images_only"
        self.selected_channel_id = None

        channel = discord.ui.ChannelSelect(
            placeholder="Salon à protéger",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )
        async def channel_cb(interaction):
            self.channel_id = channel.values[0].id
            await interaction.response.send_message("Salon sélectionné.", ephemeral=True)
        channel.callback = channel_cb
        self.add_item(channel)

        mode = discord.ui.Select(
            placeholder="Règle du salon",
            options=[
                discord.SelectOption(
                    label="Images uniquement",
                    value="images_only",
                    description="Image obligatoire et aucun texte.",
                ),
                discord.SelectOption(
                    label="Messages interdits",
                    value="blocked",
                    description="Les messages des membres sont supprimés.",
                ),
            ],
            row=1,
        )
        async def mode_cb(interaction):
            self.mode = mode.values[0]
            await interaction.response.send_message("Règle sélectionnée.", ephemeral=True)
        mode.callback = mode_cb
        self.add_item(mode)

        if rows:
            options = []
            for row in rows[:25]:
                options.append(discord.SelectOption(
                    label=f"#{row.get('channel_name') or row.get('channel_id')}"[:100],
                    value=str(row.get("channel_id")),
                    description=("Images uniquement" if row.get("mode") == "images_only" else "Messages interdits"),
                ))
            existing = discord.ui.Select(
                placeholder="Règle existante à supprimer",
                options=options,
                row=2,
            )
            async def existing_cb(interaction):
                self.selected_channel_id = int(existing.values[0])
                await interaction.response.send_message("Règle sélectionnée.", ephemeral=True)
            existing.callback = existing_cb
            self.add_item(existing)

        save = discord.ui.Button(label="Enregistrer la règle", style=discord.ButtonStyle.success, row=3)
        delete = discord.ui.Button(label="Supprimer la règle", style=discord.ButtonStyle.danger, row=3)

        async def save_cb(interaction):
            if not self.channel_id:
                return await interaction.response.send_message("Choisissez d’abord un salon.", ephemeral=True)
            try:
                await channel_message_rules.save_rule(
                    self.bot,
                    self.guild,
                    self.channel_id,
                    self.mode,
                    actor_id=interaction.user.id,
                )
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            await interaction.response.send_message("Règle de salon enregistrée.", ephemeral=True)

        async def delete_cb(interaction):
            if not self.selected_channel_id:
                return await interaction.response.send_message("Choisissez une règle existante.", ephemeral=True)
            await channel_message_rules.delete_rule(
                self.bot,
                self.guild.id,
                self.selected_channel_id,
            )
            await interaction.response.send_message("Règle de salon supprimée.", ephemeral=True)

        save.callback = save_cb
        delete.callback = delete_cb
        self.add_item(save)
        self.add_item(delete)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


def _patch_statuses() -> None:
    current = setup_ui.module_statuses
    if getattr(current, "_sentrix_v2", False):
        return
    async def statuses_v2(bot, guild, conf):
        await core.ensure_schema(bot)
        # L'interrupteur des modules (désactivé / non configuré) est déjà croisé dans
        # setup_control_center.module_statuses ; cette couche n'ajoute que Permissions.
        result = await current(bot, guild, conf)
        count = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM command_role_permissions WHERE guild_id=?",
            (guild.id,),
        )
        result["permissions"] = (
            setup_ui.ConfigState.ACTIVE,
            f"{int(count['n'] if count else 0)} règle(s) personnalisée(s) • mêmes droits pour + et /.",
            (),
        )
        await ensure_automation_schema(bot)
        reactions = await bot.db.fetchall(
            "SELECT channel_id,enabled FROM sentrix_dashboard_auto_reaction WHERE guild_id=?",
            (guild.id,),
        )
        channel_rules = await channel_message_rules.list_rules(bot, guild)
        problems = []
        for row in reactions:
            if guild.get_channel(int(row["channel_id"])) is None:
                problems.append("Une réaction automatique pointe vers un salon supprimé.")
        for row in channel_rules:
            if guild.get_channel(int(row["channel_id"])) is None:
                problems.append("Une règle de salon pointe vers un salon supprimé.")
        active = sum(bool(row["enabled"]) for row in reactions) + sum(bool(row["enabled"]) for row in channel_rules)
        configured = len(reactions) + len(channel_rules)
        result["automation"] = (
            setup_ui.ConfigState.ERROR if problems else
            setup_ui.ConfigState.ACTIVE if active else
            setup_ui.ConfigState.INACTIVE if configured else
            setup_ui.ConfigState.UNCONFIGURED,
            f"{len(reactions)} réaction(s) automatique(s) • {len(channel_rules)} règle(s) de salon.",
            tuple(problems),
        )

        music = bot.get_cog("Music")
        if music is None:
            result["music"] = (
                setup_ui.ConfigState.ERROR,
                "Le moteur musique n’est pas chargé.",
                ("Module Music indisponible.",),
            )
        else:
            settings = await music.get_system_settings(guild.id)
            channel_id = settings.get("voice_channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            music_problems = []
            if channel_id and channel is None:
                music_problems.append("Le vocal musique configuré a été supprimé.")
            state = (
                setup_ui.ConfigState.ERROR if music_problems else
                setup_ui.ConfigState.ACTIVE if settings.get("enabled") else
                setup_ui.ConfigState.INACTIVE if channel_id else
                setup_ui.ConfigState.UNCONFIGURED
            )
            result["music"] = (
                state,
                (
                    f"Système {'activé' if settings.get('enabled') else 'désactivé'}"
                    + (f" • vocal : {channel.mention}" if channel else " • aucun vocal configuré")
                ),
                tuple(music_problems),
            )
        return result
    statuses_v2._sentrix_v2 = True
    setup_ui.module_statuses = statuses_v2


def _patch_render() -> None:
    current = setup_ui.SetupView.render
    if getattr(current, "_sentrix_v2", False):
        return

    def render_v2(self):
        if not hasattr(self, "selected_permission_role"):
            self.selected_permission_role = self.guild.default_role.id
            self.selected_permission_scope = "public"
            self.selected_permission_command = None
            self.permission_page = 0
            self.selected_whitelist_user = None
        current(self)
        category = self.category

        module = MODULE_BY_CATEGORY.get(category)
        if module:
            toggle_module = discord.ui.Button(label="Activer / Désactiver le module", style=discord.ButtonStyle.primary, row=1)
            async def toggle_module_cb(interaction, _module=module):
                value = await core.module_enabled(self.bot, self.guild.id, _module)
                await core.set_module_enabled(self.bot, self.guild.id, _module, not value, actor_id=interaction.user.id)
                await self.audit(interaction.user.id, f"module:{_module}", "on" if not value else "off")
                await self.refresh(interaction)
            toggle_module.callback = toggle_module_cb
            self.add_item(toggle_module)

        if category == "permissions":
            members = discord.ui.Button(label="Cible : @everyone (membres)", style=discord.ButtonStyle.secondary, row=1)
            access = discord.ui.Button(label="Changer l’accès : défaut → oui → non", style=discord.ButtonStyle.secondary, row=1)
            async def members_cb(interaction):
                self.selected_permission_role = self.guild.default_role.id
                await self.refresh(interaction)
            async def access_cb(interaction):
                command_name = self.selected_permission_command
                if not command_name:
                    return await interaction.response.send_message("Choisissez d’abord une commande.", ephemeral=True)
                current_decision = await _permission_decision_for_view(self)
                next_decision = "allow" if current_decision is None else "deny" if current_decision == "allow" else None
                await core.set_role_command_decision(
                    self.bot, self.guild.id, self.selected_permission_role, command_name,
                    next_decision, actor_id=interaction.user.id,
                )
                await self.refresh(interaction)
            members.callback = members_cb
            access.callback = access_cb
            self.add_item(members)
            self.add_item(access)
            self.add_item(PermissionRoleSelect(self))
            self.add_item(PermissionScopeSelect(self))
            self.add_item(PermissionCommandSelect(self))

        elif category == "music":
            configure_music = discord.ui.Button(
                label="Configurer la musique",
                style=discord.ButtonStyle.primary,
                row=1,
            )

            async def configure_music_cb(interaction):
                music = self.bot.get_cog("Music")
                if music is None:
                    return await interaction.response.send_message(
                        "Le module musique n’est pas chargé.",
                        ephemeral=True,
                    )
                settings = await music.get_system_settings(self.guild.id)
                channel = self.guild.get_channel(settings.get("voice_channel_id")) if settings.get("voice_channel_id") else None
                panel = embeds.info(
                    (
                        f"**État :** {'ACTIF' if settings.get('enabled') else 'INACTIF'}\n"
                        f"**Vocal musique :** {channel.mention if channel else 'Non configuré'}\n\n"
                        "Choisissez un vocal puis activez le système. Quand un membre rejoint ce vocal, "
                        "SentriX le mentionne dans le chat du vocal et affiche un petit lecteur pour choisir une musique."
                    ),
                    title="Musique SentriX",
                )
                await panels.envoyer(
                    interaction.response,
                    panels.avec_composants(
                        panels.depuis_embed(panel),
                        MusicSystemSetupView(self, interaction.user.id, settings),
                    ),
                    ephemere=True,
                )

            configure_music.callback = configure_music_cb
            self.add_item(configure_music)

        elif category == "automation":
            reactions = discord.ui.Button(label="Réactions automatiques", style=discord.ButtonStyle.secondary, row=1)
            channel_rules_button = discord.ui.Button(label="Règles de salons", style=discord.ButtonStyle.secondary, row=1)

            async def reactions_cb(interaction):
                rows = await _automation_reaction_rows(self.bot, self.guild.id)
                panel = embeds.info(
                    "Choisissez un salon, puis si SentriX doit réagir à tous les messages ou seulement à un mot-clé. "
                    "Les bots sont ignorés pour éviter les boucles.",
                    title="Réactions automatiques",
                )
                await panels.envoyer(
                    interaction.response,
                    panels.avec_composants(
                        panels.depuis_embed(panel),
                        AutoReactionSetupView(self, interaction.user.id, rows),
                    ),
                    ephemere=True,
                )

            async def channel_rules_cb(interaction):
                rows = await channel_message_rules.list_rules(self.bot, self.guild)
                panel = embeds.info(
                    "**Images uniquement** : au moins une image jointe, aucun texte et aucun autre fichier.\n"
                    "**Messages interdits** : les messages des membres sont supprimés.\n\n"
                    "Bots et staff avec Gérer les messages/Gérer le serveur/Admin ne sont pas bloqués.",
                    title="Règles de salons",
                )
                await panels.envoyer(
                    interaction.response,
                    panels.avec_composants(
                        panels.depuis_embed(panel),
                        ChannelRuleSetupView(self, interaction.user.id, rows),
                    ),
                    ephemere=True,
                )

            reactions.callback = reactions_cb
            channel_rules_button.callback = channel_rules_cb
            self.add_item(reactions)
            self.add_item(channel_rules_button)

        elif category == "security":
            self.add_item(WhitelistUserSelect(self))
            add = discord.ui.Button(label="Whitelister globalement", style=discord.ButtonStyle.success, row=4)
            remove = discord.ui.Button(label="Retirer de la whitelist", style=discord.ButtonStyle.danger, row=4)
            async def add_cb(interaction):
                if not self.selected_whitelist_user:
                    return await interaction.response.send_message("Choisissez un membre ou bot.", ephemeral=True)
                await core.add_trusted(self.bot, self.guild.id, self.selected_whitelist_user, interaction.user.id)
                await self.refresh(interaction)
            async def remove_cb(interaction):
                if not self.selected_whitelist_user:
                    return await interaction.response.send_message("Choisissez un membre ou bot.", ephemeral=True)
                await core.remove_trusted(self.bot, self.guild.id, self.selected_whitelist_user)
                await self.refresh(interaction)
            add.callback = add_cb
            remove.callback = remove_cb
            self.add_item(add); self.add_item(remove)

        elif category == "logs" and self.selected_log:
            test = discord.ui.Button(label="Tester ce log", style=discord.ButtonStyle.secondary, row=4)
            async def test_cb(interaction):
                ok, text = await log_service.send_test_log(self.bot, self.guild, self.selected_log, interaction.user)
                await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success(text) if ok else embeds.error(text)), ephemere=True)
            test.callback = test_cb
            self.add_item(test)

        elif category == "roles":
            reward = discord.ui.Button(label="Ajouter / modifier une récompense", style=discord.ButtonStyle.secondary, row=1)
            async def reward_cb(interaction):
                await interaction.response.send_modal(LevelRewardModal(self))
            reward.callback = reward_cb
            self.add_item(reward)

        elif category == "levels":
            economy = discord.ui.Button(label="Économie / nom de l’argent", style=discord.ButtonStyle.secondary, row=1)
            async def economy_cb(interaction):
                settings = await core.economy_settings(self.bot, self.guild.id)
                enabled = await core.module_enabled(self.bot, self.guild.id, "economy")
                panel = embeds.info(
                    f"**Économie :** {'ACTIF' if enabled else 'INACTIF'}\n"
                    f"**Monnaie :** {settings['currency_singular']} / {settings['currency_plural']} {settings['currency_symbol']}\n\n"
                    "Désactiver l’économie ne supprime aucun solde, aucune banque et aucun achat.",
                    title="Économie SentriX",
                )
                await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(panel), EconomyManageView(self, interaction.user.id)), ephemere=True)
            economy.callback = economy_cb
            self.add_item(economy)

        elif category == "welcome":
            text_button = discord.ui.Button(label="Texte / image de bienvenue", style=discord.ButtonStyle.secondary, row=1)
            async def text_cb(interaction):
                await interaction.response.send_modal(WelcomeTextModal(self))
            text_button.callback = text_cb
            self.add_item(text_button)

        elif category == "notifications":
            manage = discord.ui.Button(label="Ajouter / modifier des sources", style=discord.ButtonStyle.secondary, row=1)
            async def manage_cb(interaction):
                await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.info('Ajoutez une nouvelle source ou modifiez uniquement celle sélectionnée. Aucune autre source n’est écrasée.')), NotificationManageView(self, interaction.user.id)), ephemere=True)
            manage.callback = manage_cb
            self.add_item(manage)

        elif category == "ai":
            features = discord.ui.Button(label="Fonctions IA", style=discord.ButtonStyle.secondary, row=1)
            async def features_cb(interaction):
                values = await get_ai_features(self.bot, self.guild.id)
                panel = embeds.info(
                    "\n".join([
                        f"Conversation naturelle : {'ACTIF' if values['natural_enabled'] else 'INACTIF'}",
                        f"Commandes IA : {'ACTIF' if values['commands_enabled'] else 'INACTIF'}",
                        f"Analyse d’images : {'ACTIF' if values['image_analysis_enabled'] else 'INACTIF'}",
                        f"Génération d’images : {'ACTIF' if values['image_generation_enabled'] else 'INACTIF'}",
                    ]),
                    title="Fonctions IA",
                )
                await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(panel), AiFeatureView(self, interaction.user.id)), ephemere=True)
            features.callback = features_cb
            self.add_item(features)

    render_v2._sentrix_v2 = True
    setup_ui.SetupView.render = render_v2


def _patch_build_embed() -> None:
    current = setup_ui.SetupView.build_embed
    if getattr(current, "_sentrix_v2", False):
        return

    async def build_embed_v2(self):
        await ensure_ui_schema(self.bot)
        panel = await current(self)
        # Le bloc historique décrit les permissions que LE BOT possède, pas les droits utilisateur.
        for index, field in enumerate(list(panel.fields)):
            if field.name == "Permissions SentriX":
                panel.set_field_at(index, name="Permissions du bot", value=field.value, inline=field.inline)

        if self.category in MODULE_BY_CATEGORY:
            module = MODULE_BY_CATEGORY[self.category]
            enabled = await core.module_enabled(self.bot, self.guild.id, module)
            panel.add_field(
                name="État du module",
                value=("ACTIF" if enabled else "INACTIF — configuration conservée"),
                inline=False,
            )

        if self.category == "music":
            music = self.bot.get_cog("Music")
            if music is None:
                panel.add_field(
                    name="Système musique",
                    value="Le moteur musique n’est pas chargé.",
                    inline=False,
                )
            else:
                settings = await music.get_system_settings(self.guild.id)
                channel = self.guild.get_channel(settings.get("voice_channel_id")) if settings.get("voice_channel_id") else None
                panel.add_field(
                    name="Système musique",
                    value=(
                        f"**État :** {'ACTIF' if settings.get('enabled') else 'INACTIF'}\n"
                        f"**Vocal :** {channel.mention if channel else 'Non configuré'}\n"
                        "Quand le système est actif, le chat du vocal affiche le lecteur aux membres qui le rejoignent."
                    ),
                    inline=False,
                )

        if self.category == "automation":
            reactions = await self.bot.db.fetchall(
                "SELECT enabled FROM sentrix_dashboard_auto_reaction WHERE guild_id=?",
                (self.guild.id,),
            )
            rules = await channel_message_rules.list_rules(self.bot, self.guild)
            panel.add_field(
                name="Automatisations configurées",
                value=(
                    f"**Réactions automatiques :** {sum(bool(row['enabled']) for row in reactions)}/{len(reactions)} actives\n"
                    f"**Règles de salons :** {sum(bool(row['enabled']) for row in rules)}/{len(rules)} actives"
                ),
                inline=False,
            )
            panel.add_field(
                name="Règles de contenu",
                value=(
                    "**Images uniquement** bloque le texte et les fichiers non-images.\n"
                    "**Messages interdits** supprime les messages membres. Aucun salon n'est créé automatiquement."
                ),
                inline=False,
            )

        if self.category == "permissions":
            role_id = int(getattr(self, "selected_permission_role", self.guild.default_role.id))
            role = self.guild.get_role(role_id)
            command_name = getattr(self, "selected_permission_command", None)
            decision = await _permission_decision_for_view(self)
            decision_text = {None: "DÉFAUT", "allow": "AUTORISÉ", "deny": "REFUSÉ"}[decision]
            panel.add_field(
                name="Cible",
                value=(role.mention if role else f"Rôle introuvable `{role_id}`") +
                      (" — membres du serveur" if role_id == self.guild.default_role.id else ""),
                inline=False,
            )
            panel.add_field(name="Groupe", value=SCOPE_LABELS.get(self.selected_permission_scope, self.selected_permission_scope), inline=True)
            panel.add_field(name="Commande", value=f"`+{command_name}` / `/{command_name}`" if command_name else "Choisissez une commande", inline=True)
            panel.add_field(name="Accès", value=decision_text, inline=True)
            panel.add_field(
                name="Règle importante",
                value="Une seule règle est utilisée pour les commandes **+** et **/**. Modifier ici change les deux en même temps.",
                inline=False,
            )

        elif self.category == "security":
            rows = await self.bot.db.fetchall(
                "SELECT user_id, added_by FROM trusted_members WHERE guild_id=? ORDER BY added_at LIMIT 15",
                (self.guild.id,),
            )
            panel.add_field(
                name="Whitelist globale",
                value="\n".join(
                    f"<@{row['user_id']}> — ajouté par " + (f"<@{row['added_by']}>" if row['added_by'] else "migration")
                    for row in rows
                ) or "Aucun membre de confiance configuré.",
                inline=False,
            )
            panel.add_field(
                name="Effet",
                value="Une personne whitelistée est ignorée par les protections automatiques SentriX concernées, notamment AutoMod, anti-raid et anti-nuke.",
                inline=False,
            )

        elif self.category == "levels":
            settings = await core.economy_settings(self.bot, self.guild.id)
            economy_on = await core.module_enabled(self.bot, self.guild.id, "economy")
            panel.add_field(
                name="Économie",
                value=f"**État :** {'ACTIF' if economy_on else 'INACTIF'}\n"
                      f"**Monnaie :** {settings['currency_singular']} / {settings['currency_plural']} {settings['currency_symbol']}\n"
                      "Les soldes restent sauvegardés quand le module est désactivé.",
                inline=False,
            )

        elif self.category == "welcome":
            panel.add_field(
                name="Comportement par défaut",
                value="Même sans texte personnalisé, SentriX envoie un vrai message avec le pseudo, la mention, l’avatar et le nom du serveur. Aucun salon n’est créé automatiquement.",
                inline=False,
            )

        elif self.category == "notifications":
            if self.selected_notification:
                row = await self.bot.db.fetchone(
                    "SELECT source_url, custom_text, enabled FROM social_notifications WHERE guild_id=? AND id=?",
                    (self.guild.id, self.selected_notification),
                )
                if row:
                    panel.add_field(
                        name=f"Source #{self.selected_notification}",
                        value=f"**État :** {'ACTIF' if row['enabled'] else 'INACTIF'}\n**Lien :** {row['source_url']}\n"
                              f"**Texte :** {row['custom_text'] or 'Automatique'}",
                        inline=False,
                    )
            panel.add_field(
                name="Sources indépendantes",
                value="Ajouter un TikTok, YouTube ou Twitch crée une nouvelle entrée. Modifier une source ne change jamais les autres.",
                inline=False,
            )

        elif self.category == "ai":
            values = await get_ai_features(self.bot, self.guild.id)
            panel.add_field(
                name="Sous-fonctions",
                value="\n".join([
                    f"**Conversation naturelle :** {'ACTIF' if values['natural_enabled'] else 'INACTIF'}",
                    f"**Commandes IA :** {'ACTIF' if values['commands_enabled'] else 'INACTIF'}",
                    f"**Analyse d’images :** {'ACTIF' if values['image_analysis_enabled'] else 'INACTIF'}",
                    f"**Génération d’images :** {'ACTIF' if values['image_generation_enabled'] else 'INACTIF'}",
                ]),
                inline=False,
            )

        elif self.category == "logs" and self.selected_log:
            meta = log_service.LOG_TYPES.get(self.selected_log, {})
            panel.add_field(
                name="Type sélectionné",
                value=f"**{meta.get('category', self.selected_log)}** — choisissez son salon, activez/désactivez-le puis utilisez **Tester ce log**.",
                inline=False,
            )
        return panel

    build_embed_v2._sentrix_v2 = True
    setup_ui.SetupView.build_embed = build_embed_v2


def install(bot) -> None:
    if getattr(bot, "_sentrix_setup_v2_ui", False):
        return
    setup_ui.CATEGORIES["permissions"] = (
        "Permissions",
        "Accès des membres, modérateurs, administrateurs et rôles personnalisés aux commandes + et /.",
    )
    setup_ui.CATEGORIES["automation"] = (
        "Automatisations",
        "Réactions automatiques et règles de contenu par salon.",
    )
    setup_ui.CATEGORIES["music"] = (
        "Musique",
        "Activer le système musique, choisir son vocal et afficher le lecteur dans le chat vocal.",
    )
    setup_ui.BOT_PERMS["automation"] = ("view_channel", "manage_messages", "add_reactions")
    setup_ui.BOT_PERMS["music"] = ("view_channel", "connect", "speak", "send_messages")
    setup_ui.PERM_LABELS["add_reactions"] = "Ajouter des réactions"
    order = list(setup_ui.CATEGORY_ORDER)
    if "permissions" not in order:
        index = order.index("moderation") + 1 if "moderation" in order else 0
        order.insert(index, "permissions")
    if "automation" not in order:
        index = order.index("security") + 1 if "security" in order else len(order)
        order.insert(index, "automation")
    if "music" not in order:
        index = order.index("automation") + 1 if "automation" in order else len(order)
        order.insert(index, "music")
    setup_ui.CATEGORY_ORDER = tuple(order)
    setup_ui.BOT_PERMS["permissions"] = tuple()
    _patch_can_setup()
    _patch_statuses()
    _patch_render()
    _patch_build_embed()
    bot._sentrix_setup_v2_ui = True


__all__ = ["get_ai_features", "set_ai_feature", "install"]
