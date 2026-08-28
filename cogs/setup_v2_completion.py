"""Compléments de sûreté/UX pour Setup V2.

Cette couche ferme les écarts qui ne sont pas détectés par les audits statiques :
validation avant activation, reset explicite, pagination notifications, test d'envoi,
accueil riche configurable et maintenance create-server strictement opt-in.
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from utils import checks, embeds, log_service
from . import setup_control_center as setup_ui
from . import setup_v2_core as core
from . import setup_v2_ui as v2ui
from . import server_builder
from . import server_builder_existing_bootstrap as managed_builder

logger = logging.getLogger("bot.setup-v2-completion")

WELCOME_DEFAULT_TITLE = "Bienvenue sur {server}"
WELCOME_DEFAULT_TEXT = "Bienvenue {member} ! Content de t’accueillir parmi nous sur **{server}**."


async def ensure_schema(bot) -> None:
    await core.ensure_schema(bot)
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS welcome_presentation_v2 (
            guild_id INTEGER PRIMARY KEY,
            title TEXT,
            show_avatar INTEGER NOT NULL DEFAULT 1,
            show_member_count INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL
        )
        """
    )
    await managed_builder.ensure_managed_schema(bot)


def _conf_value(conf, key, default=None):
    try:
        value = conf[key] if conf else None
    except (KeyError, IndexError, TypeError):
        value = None
    return default if value is None else value


async def _welcome_presentation(bot, guild_id: int) -> dict:
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT title,show_avatar,show_member_count FROM welcome_presentation_v2 WHERE guild_id=?",
        (guild_id,),
    )
    if row is None:
        return {"title": WELCOME_DEFAULT_TITLE, "show_avatar": True, "show_member_count": True}
    return {
        "title": str(row["title"] or WELCOME_DEFAULT_TITLE),
        "show_avatar": bool(row["show_avatar"]),
        "show_member_count": bool(row["show_member_count"]),
    }


async def _save_welcome_presentation(bot, guild_id: int, *, title: str | None, show_avatar: bool, show_member_count: bool, actor_id: int) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO welcome_presentation_v2 "
        "(guild_id,title,show_avatar,show_member_count,updated_by,updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET title=excluded.title,show_avatar=excluded.show_avatar,"
        "show_member_count=excluded.show_member_count,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (guild_id, title or None, int(show_avatar), int(show_member_count), actor_id, int(time.time())),
    )


def _format_welcome(value: str, member: discord.Member) -> str:
    guild = member.guild
    return (str(value).replace("{member}", member.mention).replace("{username}", member.display_name)
            .replace("{server}", guild.name).replace("{member_count}", str(guild.member_count or 0)))


async def _welcome_destination(bot, guild: discord.Guild):
    conf = await bot.db.get_guild_config(guild.id)
    channel_id = _conf_value(conf, "welcome_channel")
    channel = guild.get_channel(int(channel_id)) if channel_id else guild.system_channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None, "Aucun salon de bienvenue n’est configuré et le salon système n’est pas utilisable."
    me = guild.me
    if me is None:
        return None, "SentriX n’est pas disponible dans le cache du serveur."
    perms = channel.permissions_for(me)
    missing = []
    if not perms.view_channel: missing.append("Voir le salon")
    if not perms.send_messages: missing.append("Envoyer des messages")
    if not perms.embed_links: missing.append("Intégrer des liens")
    if missing:
        return None, f"Permissions manquantes dans {channel.mention} : **{', '.join(missing)}**."
    return channel, None


async def _send_welcome(bot, member: discord.Member, *, test: bool = False) -> tuple[bool, str]:
    if not test and not await core.module_enabled(bot, member.guild.id, "welcome"):
        return False, "Le module Bienvenue est désactivé."
    channel, error = await _welcome_destination(bot, member.guild)
    if channel is None:
        return False, error or "Salon de bienvenue indisponible."
    conf = await bot.db.get_guild_config(member.guild.id)
    presentation = await _welcome_presentation(bot, member.guild.id)
    panel = embeds.brand(
        _format_welcome(presentation["title"], member),
        _format_welcome(_conf_value(conf, "welcome_message", WELCOME_DEFAULT_TEXT), member),
    )
    if presentation["show_avatar"]:
        panel.set_thumbnail(url=member.display_avatar.url)
    if presentation["show_member_count"]:
        panel.add_field(name="Membres", value=f"{member.guild.member_count or 0} membre(s)", inline=True)
    image_url = _conf_value(conf, "welcome_image_url")
    if image_url and str(image_url).startswith(("https://", "http://")):
        panel.set_image(url=str(image_url))
    try:
        await channel.send(
            content=None if test else member.mention,
            embed=panel,
            allowed_mentions=(discord.AllowedMentions.none() if test else discord.AllowedMentions(users=[member], roles=False, everyone=False)),
        )
    except discord.HTTPException as exc:
        return False, f"Discord a refusé l’envoi : {exc}"
    return True, f"Test envoyé dans {channel.mention}." if test else "Bienvenue envoyée."


async def _send_goodbye(bot, member: discord.Member) -> None:
    if not await core.module_enabled(bot, member.guild.id, "welcome"):
        return
    conf = await bot.db.get_guild_config(member.guild.id)
    channel_id = _conf_value(conf, "goodbye_channel")
    if not channel_id:
        return
    channel = member.guild.get_channel(int(channel_id))
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return
    template = _conf_value(conf, "goodbye_message", "**{username}** a quitté **{server}**.")
    panel = embeds.neutral("Départ d’un membre", _format_welcome(template, member))
    presentation = await _welcome_presentation(bot, member.guild.id)
    if presentation["show_avatar"]:
        panel.set_thumbnail(url=member.display_avatar.url)
    try:
        await channel.send(embed=panel, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


def _replace_welcome_listeners(bot) -> None:
    for event_name, wanted_name in (("on_member_join", "on_member_join_v2"), ("on_member_remove", "on_member_remove_v2")):
        listeners = list(getattr(bot, "extra_events", {}).get(event_name, ()) or ())
        kept = []
        for listener in listeners:
            function = getattr(listener, "__func__", listener)
            module = str(getattr(function, "__module__", "") or "")
            name = str(getattr(function, "__name__", "") or "")
            if module.endswith("setup_v2_core") and name == wanted_name:
                continue
            kept.append(listener)
        if kept: bot.extra_events[event_name] = kept
        else: bot.extra_events.pop(event_name, None)

    async def on_member_join(member: discord.Member):
        conf = await bot.db.get_guild_config(member.guild.id)
        if await core.module_enabled(bot, member.guild.id, "roles"):
            role_id = _conf_value(conf, "autorole")
            role = member.guild.get_role(int(role_id)) if role_id else None
            me = member.guild.me
            if role and me and me.guild_permissions.manage_roles and role < me.top_role:
                try: await member.add_roles(role, reason="Autorole SentriX")
                except discord.HTTPException: pass
        await _send_welcome(bot, member)

    async def on_member_remove(member: discord.Member):
        await _send_goodbye(bot, member)

    bot.add_listener(on_member_join, "on_member_join")
    bot.add_listener(on_member_remove, "on_member_remove")


class WelcomeSettingsModal(discord.ui.Modal, title="Bienvenue / départ"):
    def __init__(self, owner, *, conf, presentation):
        super().__init__()
        self.owner = owner
        self.title_input = discord.ui.TextInput(label="Titre de bienvenue", default=str(presentation["title"] or WELCOME_DEFAULT_TITLE)[:200], max_length=200)
        self.welcome_input = discord.ui.TextInput(label="Message de bienvenue", default=str(_conf_value(conf, "welcome_message", WELCOME_DEFAULT_TEXT))[:1000], max_length=1000, style=discord.TextStyle.paragraph)
        self.goodbye_input = discord.ui.TextInput(label="Message de départ", default=str(_conf_value(conf, "goodbye_message", "{username} a quitté {server}."))[:1000], max_length=1000, style=discord.TextStyle.paragraph)
        self.image_input = discord.ui.TextInput(label="URL bannière / image (facultatif)", default=str(_conf_value(conf, "welcome_image_url", "") or "")[:400], required=False, max_length=400)
        self.options_input = discord.ui.TextInput(label="Options : avatar=on/off ; membres=on/off", default=f"avatar={'on' if presentation['show_avatar'] else 'off'}; membres={'on' if presentation['show_member_count'] else 'off'}", max_length=80)
        for child in (self.title_input, self.welcome_input, self.goodbye_input, self.image_input, self.options_input):
            self.add_item(child)

    async def on_submit(self, interaction):
        image = str(self.image_input.value).strip() or None
        if image and not image.startswith(("https://", "http://")):
            return await interaction.response.send_message("L’image doit utiliser une URL http/https.", ephemeral=True)
        options = str(self.options_input.value).casefold().replace(" ", "")
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "welcome_message", str(self.welcome_input.value).strip() or None)
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "goodbye_message", str(self.goodbye_input.value).strip() or None)
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "welcome_image_url", image)
        await _save_welcome_presentation(
            self.owner.bot, self.owner.guild.id,
            title=str(self.title_input.value).strip() or WELCOME_DEFAULT_TITLE,
            show_avatar="avatar=off" not in options,
            show_member_count=not ("membres=off" in options or "members=off" in options),
            actor_id=interaction.user.id,
        )
        await interaction.response.send_message(
            embed=embeds.success("Bienvenue enregistrée. Le test n’effectue aucun ping.", title="Configuration bienvenue"),
            view=WelcomeTestView(self.owner.bot, self.owner.guild, interaction.user.id), ephemeral=True,
        )


class WelcomeTestView(discord.ui.View):
    def __init__(self, bot, guild, author_id: int):
        super().__init__(timeout=180); self.bot = bot; self.guild = guild; self.author_id = author_id
    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce test ne vous appartient pas.", ephemeral=True); return False
        return True
    @discord.ui.button(label="Tester la bienvenue", style=discord.ButtonStyle.secondary)
    async def test(self, interaction, _button):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Membre Discord introuvable.", ephemeral=True)
        ok, message = await _send_welcome(self.bot, interaction.user, test=True)
        await interaction.response.send_message(embed=embeds.success(message) if ok else embeds.error(message), ephemeral=True)


class PaginatedNotificationSelect(discord.ui.Select):
    def __init__(self, view, rows):
        self.owner = view
        if not hasattr(view, "notification_page"): view.notification_page = 0
        total = len(rows); page_count = max(1, (total + 22) // 23)
        page = max(0, int(view.notification_page)) % page_count; view.notification_page = page
        chunk = rows[page * 23:page * 23 + 23]
        options = [discord.SelectOption(label=f"{str(row['platform']).title()} #{row['id']}"[:100], value=str(row["id"]), description=str(row["source_url"])[:100]) for row in chunk]
        if page_count > 1:
            options += [
                discord.SelectOption(label=f"← Page précédente ({page + 1}/{page_count})", value="__prev__"),
                discord.SelectOption(label=f"Page suivante → ({page + 1}/{page_count})", value="__next__"),
            ]
        if not options: options = [discord.SelectOption(label="Aucune notification", value="__none__")]
        super().__init__(placeholder="Choisir une notification", options=options[:25], row=2)
    async def callback(self, interaction):
        value = self.values[0]
        if value == "__next__": self.owner.notification_page += 1; self.owner.selected_notification = None
        elif value == "__prev__": self.owner.notification_page -= 1; self.owner.selected_notification = None
        elif value != "__none__": self.owner.selected_notification = int(value)
        await self.owner.refresh(interaction)


class NotificationManageViewV3(discord.ui.View):
    def __init__(self, owner, author_id: int):
        super().__init__(timeout=240); self.owner = owner; self.author_id = author_id
    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True); return False
        return True
    def _selected_id(self): return getattr(self.owner, "selected_notification", None)
    @discord.ui.button(label="Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, _button): await interaction.response.send_modal(v2ui.NotificationSourceModal(self.owner, "add"))
    @discord.ui.button(label="Modifier", style=discord.ButtonStyle.secondary, row=0)
    async def edit(self, interaction, _button):
        if not self._selected_id(): return await interaction.response.send_message("Sélectionnez d’abord une source dans +setup.", ephemeral=True)
        await interaction.response.send_modal(v2ui.NotificationSourceModal(self.owner, "edit"))
    @discord.ui.button(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=1)
    async def toggle(self, interaction, _button):
        selected = self._selected_id()
        if not selected: return await interaction.response.send_message("Sélectionnez d’abord une source.", ephemeral=True)
        row = await self.owner.bot.db.fetchone("SELECT enabled FROM social_notifications WHERE guild_id=? AND id=?", (self.owner.guild.id, selected))
        if row is None: return await interaction.response.send_message("Source introuvable.", ephemeral=True)
        await self.owner.bot.db.execute("UPDATE social_notifications SET enabled=? WHERE guild_id=? AND id=?", (0 if row["enabled"] else 1, self.owner.guild.id, selected))
        await interaction.response.send_message(f"Source #{selected} : {'INACTIF' if row['enabled'] else 'ACTIF'}.", ephemeral=True)
    @discord.ui.button(label="Tester", style=discord.ButtonStyle.secondary, row=1)
    async def test(self, interaction, _button):
        selected = self._selected_id()
        if not selected: return await interaction.response.send_message("Sélectionnez d’abord une source.", ephemeral=True)
        row = await self.owner.bot.db.fetchone("SELECT * FROM social_notifications WHERE guild_id=? AND id=?", (self.owner.guild.id, selected))
        if row is None: return await interaction.response.send_message("Source introuvable.", ephemeral=True)
        channel = self.owner.guild.get_channel(int(row["discord_channel_id"])); role = self.owner.guild.get_role(int(row["role_id"]))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)) or role is None:
            return await interaction.response.send_message("Le salon ou le rôle de cette source n’existe plus.", ephemeral=True)
        me = self.owner.guild.me; perms = channel.permissions_for(me) if me else discord.Permissions.none()
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await interaction.response.send_message(f"SentriX n’a pas les permissions d’envoi complètes dans {channel.mention}.", ephemeral=True)
        panel = embeds.brand(f"Test notification — {row['platform']}", row["custom_text"] or "Test de livraison SentriX : aucune publication réelle n’est créée.")
        if row["image_url"]: panel.set_image(url=row["image_url"])
        try:
            await channel.send(content=role.mention, embed=panel, allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=[role], replied_user=False))
        except discord.HTTPException as exc:
            return await interaction.response.send_message(f"Échec du test : {exc}", ephemeral=True)
        await interaction.response.send_message(f"Test de la source #{selected} envoyé dans {channel.mention}.", ephemeral=True)
    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction, _button):
        selected = self._selected_id()
        if not selected: return await interaction.response.send_message("Sélectionnez d’abord une source.", ephemeral=True)
        await self.owner.bot.db.execute("DELETE FROM social_notifications WHERE guild_id=? AND id=?", (self.owner.guild.id, selected))
        self.owner.selected_notification = None
        await interaction.response.send_message(f"Source #{selected} supprimée ; les autres sources sont intactes.", ephemeral=True)


async def _module_enable_errors(bot, guild: discord.Guild, category: str) -> list[str]:
    errors = []; me = guild.me
    if me is None: return ["SentriX n’est pas disponible dans le cache de ce serveur."]
    permissions = getattr(me, "guild_permissions", discord.Permissions.none()); labels = getattr(setup_ui, "PERM_LABELS", {})
    for permission in setup_ui.BOT_PERMS.get(category, ()):
        if not getattr(permissions, permission, False): errors.append(f"Permission du bot manquante : **{labels.get(permission, permission)}**.")
    if category == "logs":
        active = 0
        for log_type, meta in log_service.LOG_TYPES.items():
            if not meta.get("emits"): continue
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
            if not setting.get("enabled"): continue
            active += 1; ok, reason = log_service.validate_channel(guild, setting.get("channel_id"))
            if not ok: errors.append(f"{meta.get('category', log_type)} : {reason}.")
        if active == 0: errors.append("Activez au moins **un type de log** et choisissez son salon avant d’activer le module Logs.")
    elif category == "welcome":
        channel, error = await _welcome_destination(bot, guild)
        if channel is None: errors.append(error or "Choisissez un salon de bienvenue.")
    elif category == "notifications":
        rows = await bot.db.fetchall("SELECT discord_channel_id,role_id FROM social_notifications WHERE guild_id=? AND enabled=1", (guild.id,))
        if not rows: errors.append("Ajoutez et activez au moins **une source de notification**.")
        for row in rows:
            if guild.get_channel(int(row["discord_channel_id"])) is None: errors.append("Une source active pointe vers un salon supprimé.")
            if guild.get_role(int(row["role_id"])) is None: errors.append("Une source active pointe vers un rôle supprimé.")
    elif category == "roles":
        conf = await bot.db.get_guild_config(guild.id)
        configured = any(_conf_value(conf, key) for key in ("autorole", "verify_role", "member_role", "booster_role"))
        if configured and not permissions.manage_roles: errors.append("Accordez **Gérer les rôles** à SentriX et placez son rôle au-dessus des rôles gérés.")
    return errors


async def _reset_config(bot, guild: discord.Guild, target: str) -> str:
    aliases = {"modération":"moderation","moderation":"moderation","sécurité":"security","securite":"security","security":"security","logs":"logs","tickets":"tickets","bienvenue":"welcome","welcome":"welcome","rôles":"roles","roles":"roles","niveaux":"levels","levels":"levels","économie":"economy","economie":"economy","economy":"economy","notifications":"notifications","ia":"ai","ai":"ai","permissions":"permissions","tout":"all","all":"all"}
    target = aliases.get(target.casefold().strip(), target.casefold().strip())
    if target not in set(core.MODULES) | {"permissions", "all"}: raise ValueError("module_inconnu")
    targets = list(core.MODULES) + ["permissions"] if target == "all" else [target]; gid = guild.id
    for item in targets:
        if item in core.MODULES: await bot.db.execute("DELETE FROM module_settings WHERE guild_id=? AND module=?", (gid, item))
        if item == "permissions": await bot.db.execute("DELETE FROM command_role_permissions WHERE guild_id=?", (gid,))
        elif item == "security":
            await bot.db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (gid,))
            await bot.db.execute("UPDATE automod_settings SET antispam=0,antilink=0,antiinvite=0,antimention=0,anticaps=0,antiemoji=0,antiraid=0,antibot=0,antiaccount=0,antiscam=0,antinuke=0 WHERE guild_id=?", (gid,))
            await bot.db.execute("DELETE FROM trusted_members WHERE guild_id=?", (gid,)); await bot.db.execute("DELETE FROM antinuke_whitelist WHERE guild_id=?", (gid,))
        elif item == "logs":
            await bot.db.execute("UPDATE log_settings SET enabled=0,channel_id=NULL,updated_at=? WHERE guild_id=?", (int(time.time()), gid))
            for key in ("log_channel","log_messages","log_members","log_voice","log_roles","log_server","log_automod","log_moderation","ticket_log_channel"): await bot.db.set_guild_config(gid, key, None)
        elif item == "notifications": await bot.db.execute("DELETE FROM social_notifications WHERE guild_id=?", (gid,))
        elif item == "welcome":
            for key in ("welcome_channel","welcome_message","welcome_image_url","goodbye_channel","goodbye_message"): await bot.db.set_guild_config(gid, key, None)
            await bot.db.execute("DELETE FROM welcome_presentation_v2 WHERE guild_id=?", (gid,))
        elif item == "roles":
            for key in ("autorole","verify_role","verification_role","member_role","booster_role"): await bot.db.set_guild_config(gid, key, None)
            await bot.db.execute("DELETE FROM level_roles WHERE guild_id=?", (gid,))
        elif item == "levels": await bot.db.set_guild_config(gid, "level_channel", None)
        elif item == "economy": await bot.db.execute("DELETE FROM economy_settings_v2 WHERE guild_id=?", (gid,))
        elif item == "ai": await bot.db.execute("DELETE FROM ai_feature_settings_v2 WHERE guild_id=?", (gid,))
        elif item == "moderation":
            for key in ("mod_role","mute_role","warn_role"): await bot.db.set_guild_config(gid, key, None)
    return target


class ResetConfigModal(discord.ui.Modal, title="Réinitialiser une configuration"):
    target = discord.ui.TextInput(label="Module (ou « tout »)", placeholder="logs, bienvenue, notifications, permissions…", max_length=30)
    confirm = discord.ui.TextInput(label="Tapez RESET pour confirmer", placeholder="RESET", max_length=10)
    def __init__(self, owner): super().__init__(); self.owner = owner
    async def on_submit(self, interaction):
        if str(self.confirm.value).strip().upper() != "RESET": return await interaction.response.send_message("Confirmation incorrecte : aucun réglage n’a été modifié.", ephemeral=True)
        try: target = await _reset_config(self.owner.bot, self.owner.guild, str(self.target.value))
        except ValueError: return await interaction.response.send_message("Module inconnu. Utilisez par exemple `logs`, `bienvenue`, `notifications`, `permissions` ou `tout`.", ephemeral=True)
        await interaction.response.send_message(embed=embeds.success(f"Configuration **{target}** réinitialisée. Les données utilisateur (XP, argent, historique) ont été conservées."), ephemeral=True)


def _patch_setup_render() -> None:
    current = setup_ui.SetupView.render
    if getattr(current, "_sentrix_v2_completion", False): return
    def render_completion(self):
        current(self)
        if self.category in v2ui.MODULE_BY_CATEGORY:
            module = v2ui.MODULE_BY_CATEGORY[self.category]
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label == "Activer / Désactiver le module":
                    async def toggle_checked(interaction, _module=module, _category=self.category):
                        enabled = await core.module_enabled(self.bot, self.guild.id, _module)
                        if not enabled:
                            errors = await _module_enable_errors(self.bot, self.guild, _category)
                            if errors: return await interaction.response.send_message(embed=embeds.error("\n".join(f"• {line}" for line in errors)[:3900], title="Impossible d’activer ce module"), ephemeral=True)
                        await core.set_module_enabled(self.bot, self.guild.id, _module, not enabled, actor_id=interaction.user.id)
                        await self.audit(interaction.user.id, f"module:{_module}", "on" if not enabled else "off"); await self.refresh(interaction)
                    item.callback = toggle_checked; break
        if self.category is None:
            reset = discord.ui.Button(label="Réinitialiser configuration", style=discord.ButtonStyle.danger, row=1)
            async def reset_cb(interaction): await interaction.response.send_modal(ResetConfigModal(self))
            reset.callback = reset_cb; self.add_item(reset)
        if self.category == "welcome":
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label == "Texte / image de bienvenue":
                    async def welcome_settings_cb(interaction):
                        conf = await self.bot.db.get_guild_config(self.guild.id); presentation = await _welcome_presentation(self.bot, self.guild.id)
                        await interaction.response.send_modal(WelcomeSettingsModal(self, conf=conf, presentation=presentation))
                    item.callback = welcome_settings_cb; break
    render_completion._sentrix_v2_completion = True; render_completion._sentrix_previous = current; setup_ui.SetupView.render = render_completion


def _patch_setup_embed() -> None:
    current = setup_ui.SetupView.build_embed
    if getattr(current, "_sentrix_v2_completion", False): return
    async def build_embed_completion(self):
        panel = await current(self)
        if self.category == "welcome":
            p = await _welcome_presentation(self.bot, self.guild.id)
            panel.add_field(name="Affichage de bienvenue", value=f"**Titre :** {p['title']}\n**Avatar :** {'ACTIF' if p['show_avatar'] else 'INACTIF'}\n**Nombre de membres :** {'ACTIF' if p['show_member_count'] else 'INACTIF'}\nLe bouton **Texte / image de bienvenue** permet aussi d’envoyer un test.", inline=False)
        elif self.category == "notifications":
            row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM social_notifications WHERE guild_id=?", (self.guild.id,)); count = int(row["n"] if row else 0)
            page = int(getattr(self, "notification_page", 0)) + 1; pages = max(1, (count + 22) // 23)
            panel.add_field(name="Navigation des sources", value=f"**{count} source(s)** • page **{min(page, pages)}/{pages}** • aucune source n’est masquée après la 25e.", inline=False)
        return panel
    build_embed_completion._sentrix_v2_completion = True; build_embed_completion._sentrix_previous = current; setup_ui.SetupView.build_embed = build_embed_completion


def _install_server_builder_minimal_profile() -> None:
    if "minimal" in server_builder.SERVER_TEMPLATES: return
    roles = [
        server_builder._role("Fondateur", discord.Color.dark_red(), server_builder.FOUNDER_PERMISSIONS, hoist=True),
        server_builder._role("Administrateur", discord.Color.orange(), server_builder.ADMIN_PERMISSIONS, hoist=True),
        server_builder._role("Modérateur", discord.Color.from_rgb(240,165,70), server_builder.MODERATOR_PERMISSIONS, hoist=True),
        server_builder._role("Support", discord.Color.teal(), server_builder.SUPPORT_PERMISSIONS, hoist=True),
        server_builder._role("Membre", discord.Color.from_rgb(120,135,160)), server_builder._role("Muet", discord.Color.dark_grey()),
    ]
    categories = [
        {"name":"ACCUEIL","privacy":"public","channels":[("annonces","readonly"),("règlement","readonly"),("bienvenue","text"),("départs","text"),("choix-des-rôles","readonly")]},
        {"name":"COMMUNAUTÉ","privacy":"public","channels":[("général","text"),("suggestions","text"),("commandes-bot","text")]},
        {"name":"SUPPORT","privacy":"public","channels":[("ouvrir-un-ticket","readonly")]},
        {"name":"TICKETS OUVERTS","privacy":"tickets","channels":[]},
        {"name":"STAFF","privacy":"staff","channels":[("staff-général","text"),("signalements","text")]},
        {"name":"LOGS","privacy":"staff","channels":[("logs-messages","readonly"),("logs-membres","readonly"),("logs-modération","readonly"),("logs-rôles","readonly"),("logs-salons","readonly"),("logs-vocaux","readonly"),("logs-tickets","readonly"),("logs-sécurité","readonly"),("logs-ressources","readonly")]},
    ]
    profile = {"label":"Essentiel / Minimal","description":"Structure propre et courte : accueil, communauté, support, staff et logs utiles.","roles":roles,"staff_role_name":"Modérateur","member_role_name":"Membre","categories":categories,"accent":discord.Color.blurple(),"announcement_title":"Serveur prêt","welcome_text":"Les salons essentiels sont prêts sans créer des dizaines de rôles ou catégories inutiles.","ticket_title":"Support","ticket_description":"Choisissez le motif de votre demande."}
    previous = dict(server_builder.SERVER_TEMPLATES); server_builder.SERVER_TEMPLATES.clear(); server_builder.SERVER_TEMPLATES["minimal"] = profile; server_builder.SERVER_TEMPLATES.update(previous)
    server_builder.TICKET_TYPES_BY_TEMPLATE["minimal"] = [
        {"name":"Support général","description":"Question ou demande d’aide.","button_style":"bleu","name_format":"support-{pseudo}","open_message":"Décrivez précisément votre demande."},
        {"name":"Signalement","description":"Signaler un membre ou un comportement.","button_style":"rouge","name_format":"signalement-{pseudo}","open_message":"Expliquez les faits et joignez les preuves utiles."},
    ]


def _install_managed_mode_command(bot) -> None:
    if bot.get_command("server-managed") is not None: return
    async def callback(ctx: commands.Context, mode: str = "status"):
        if ctx.guild is None: return await ctx.send(embed=embeds.error("Cette commande doit être utilisée dans un serveur."))
        normalized = str(mode or "status").casefold().strip()
        if normalized in {"status","etat","état"}:
            enabled = await managed_builder.is_managed(bot, ctx.guild.id)
            return await ctx.send(embed=embeds.info(f"Maintenance automatique create-server : **{'ACTIVE' if enabled else 'INACTIVE'}**.\nINACTIVE signifie qu’aucun redémarrage de SentriX ne modifiera la structure du serveur.", title="Mode serveur géré"))
        if normalized not in {"on","off","actif","inactif","enable","disable"}: return await ctx.send(embed=embeds.error("Utilisez `+server-managed on`, `off` ou `status`."))
        enabled = normalized in {"on","actif","enable"}; await managed_builder.set_managed(bot, ctx.guild.id, enabled, actor_id=ctx.author.id)
        await ctx.send(embed=embeds.success(f"Maintenance automatique : **{'ACTIVE' if enabled else 'INACTIVE'}**.\n" + ("SentriX pourra entretenir uniquement sa structure déjà créée." if enabled else "Aucun redémarrage ne modifiera automatiquement les salons/rôles.")))
    callback = checks.is_owner_or_admin_for("configuration")(callback)
    bot.add_command(commands.hybrid_command(name="server-managed", description="Activer ou couper la maintenance automatique d’une structure SentriX.")(callback))


def install(bot) -> None:
    if getattr(bot, "_sentrix_setup_v2_completion", False): return
    setup_ui.NotificationSelect = PaginatedNotificationSelect
    v2ui.NotificationManageView = NotificationManageViewV3
    _patch_setup_render(); _patch_setup_embed(); _replace_welcome_listeners(bot); _install_server_builder_minimal_profile(); _install_managed_mode_command(bot)
    bot._sentrix_setup_v2_completion = True
    logger.info("Setup V2 completion installé : validation, reset, pagination, bienvenue et mode géré.")


__all__ = ["ensure_schema", "install"]