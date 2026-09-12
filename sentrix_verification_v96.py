"""SentriX V96 — configuration guidée du règlement + CAPTCHA de vérification.

Ce module complète le cog historique ``cogs.verification`` sans recopier son moteur
CAPTCHA. Il remplace les anciennes entrées +verify-panel / +verify-setup par un seul
assistant de configuration : salon, rôle, texte du règlement, image facultative,
aperçu, diagnostic, permissions automatiques facultatives puis publication.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata

import discord
from discord.ext import commands

logger = logging.getLogger("bot.verification-v96")

_SETUP_TIMEOUT = 10 * 60
_DEFAULT_TITLE = "Règlement & vérification"
_DEFAULT_RULES = (
    "Bienvenue sur le serveur.\n\n"
    "Merci de lire attentivement le règlement avant de continuer. "
    "En cliquant sur le bouton ci-dessous, vous certifiez avoir lu et accepté les règles. "
    "Un CAPTCHA vous sera ensuite demandé avant l'attribution du rôle vérifié."
)
_IMAGE_RE = re.compile(r"^https?://[^\s]+$", re.I)
_SENSITIVE_CHANNEL_WORDS = frozenset(
    {
        "admin",
        "admins",
        "administration",
        "audit",
        "audits",
        "direction",
        "fondateur",
        "fondateurs",
        "log",
        "logs",
        "moderation",
        "modo",
        "modos",
        "owner",
        "owners",
        "prive",
        "private",
        "staff",
        "team",
        "transcript",
        "transcripts",
    }
)


def _normalized_words(value: str) -> set[str]:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9]+", text))


def _sensitive_surface(channel: discord.abc.GuildChannel) -> bool:
    """Protège les espaces staff/logs/admin même s'ils ont été rendus publics par erreur."""
    return bool(_normalized_words(getattr(channel, "name", "")) & _SENSITIVE_CHANNEL_WORDS)


def _clone_overwrite(overwrite: discord.PermissionOverwrite) -> discord.PermissionOverwrite:
    allow, deny = overwrite.pair()
    return discord.PermissionOverwrite.from_pair(allow, deny)


def _row_value(row, key: str, default=None):
    if row is None:
        return default
    try:
        keys = row.keys()
    except Exception:
        keys = ()
    try:
        return row[key] if key in keys else default
    except Exception:
        return default


class VerificationRulesModal(discord.ui.Modal, title="Configurer le règlement"):
    panel_title = discord.ui.TextInput(
        label="Titre de l'embed",
        max_length=100,
        required=True,
        default=_DEFAULT_TITLE,
    )
    rules = discord.ui.TextInput(
        label="Règlement / message",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
        default=_DEFAULT_RULES,
    )
    image_url = discord.ui.TextInput(
        label="Image (URL) — facultatif",
        placeholder="https://.../image.png",
        max_length=500,
        required=False,
    )

    def __init__(self, view: "VerificationSetupView") -> None:
        super().__init__()
        self.setup_view = view
        self.panel_title.default = view.panel_title
        self.rules.default = view.rules_text
        self.image_url.default = view.image_url or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        image = str(self.image_url.value or "").strip()
        if image and not _IMAGE_RE.fullmatch(image):
            return await interaction.response.send_message(
                "L'image doit être une URL `http://` ou `https://` valide, ou être laissée vide.",
                ephemeral=True,
            )

        self.setup_view.panel_title = str(self.panel_title.value).strip()[:100] or _DEFAULT_TITLE
        self.setup_view.rules_text = str(self.rules.value).strip()[:4000] or _DEFAULT_RULES
        self.setup_view.image_url = image or None
        self.setup_view._sync_controls()
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, setup_view: "VerificationSetupView") -> None:
        self.setup_view = setup_view
        super().__init__(
            placeholder="1. Choisir le salon du règlement / CAPTCHA",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        self.setup_view.channel_id = int(channel.id)
        self.setup_view._sync_controls()
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationRoleSelect(discord.ui.RoleSelect):
    def __init__(self, setup_view: "VerificationSetupView") -> None:
        self.setup_view = setup_view
        super().__init__(
            placeholder="2. Choisir le rôle donné après vérification",
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        role = self.values[0]
        self.setup_view.role_id = int(role.id)
        self.setup_view._sync_controls()
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationSetupView(discord.ui.View):
    def __init__(
        self,
        cog: "VerificationConfigV96",
        guild_id: int,
        author_id: int,
        *,
        channel_id: int | None = None,
        role_id: int | None = None,
        panel_title: str = _DEFAULT_TITLE,
        rules_text: str = _DEFAULT_RULES,
        image_url: str | None = None,
        auto_access: bool = False,
        has_existing_panel: bool = False,
    ) -> None:
        super().__init__(timeout=_SETUP_TIMEOUT)
        self.cog = cog
        self.bot = cog.bot
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)
        self.channel_id = int(channel_id) if channel_id else None
        self.role_id = int(role_id) if role_id else None
        self.panel_title = str(panel_title or _DEFAULT_TITLE)[:100]
        self.rules_text = str(rules_text or _DEFAULT_RULES)[:4000]
        self.image_url = str(image_url).strip() if image_url else None
        self.auto_access = bool(auto_access)
        self.has_existing_panel = bool(has_existing_panel)
        self._publishing = False

        self.add_item(VerificationChannelSelect(self))
        self.add_item(VerificationRoleSelect(self))
        self._sync_controls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne qui a lancé cette configuration peut la modifier.",
                ephemeral=True,
            )
            return False
        return True

    def _guild(self) -> discord.Guild | None:
        return self.bot.get_guild(self.guild_id)

    def _resolved(self) -> tuple[discord.Guild | None, discord.TextChannel | None, discord.Role | None]:
        guild = self._guild()
        channel = guild.get_channel(self.channel_id) if guild and self.channel_id else None
        role = guild.get_role(self.role_id) if guild and self.role_id else None
        return (
            guild,
            channel if isinstance(channel, discord.TextChannel) else None,
            role if isinstance(role, discord.Role) else None,
        )

    def _ready(self) -> bool:
        _guild, channel, role = self._resolved()
        return channel is not None and role is not None and bool(self.rules_text.strip())

    def _sync_controls(self) -> None:
        access = getattr(self, "toggle_auto_access", None)
        if access is not None:
            access.label = "4. Accès salons : OUI" if self.auto_access else "4. Accès salons : NON"
            access.style = (
                discord.ButtonStyle.success if self.auto_access else discord.ButtonStyle.secondary
            )

        publish = getattr(self, "publish", None)
        if publish is not None:
            publish.disabled = (not self._ready()) or self._publishing
            if self._publishing:
                publish.label = "Publication..."
            elif self.has_existing_panel:
                publish.label = "Mettre à jour"
            else:
                publish.label = "Publier"

    def configuration_embed(self) -> discord.Embed:
        _guild, channel, role = self._resolved()
        ready = channel is not None and role is not None and bool(self.rules_text.strip())

        embed = discord.Embed(
            title="SentriX — Configuration de la vérification",
            description=(
                "Configurez le panneau dans l'ordre. Rien n'est publié avant le bouton **Publier**.\n\n"
                "Après le clic sur **● Je certifie avoir lu les règles**, le membre reçoit le CAPTCHA. "
                "Le rôle choisi est attribué uniquement après réussite du CAPTCHA."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="1 • Salon",
            value=channel.mention if channel else "Non choisi",
            inline=False,
        )
        embed.add_field(
            name="2 • Rôle après vérification",
            value=role.mention if role else "Non choisi",
            inline=False,
        )
        embed.add_field(
            name="3 • Règlement",
            value=(self.rules_text[:700] + ("…" if len(self.rules_text) > 700 else "")),
            inline=False,
        )
        if self.image_url:
            embed.add_field(
                name="Image facultative",
                value=self.image_url,
                inline=False,
            )
        embed.add_field(
            name="4 • Accès automatiques aux salons",
            value=(
                "**ACTIVÉ** — SentriX cachera les espaces publics aux membres non vérifiés, "
                "les ouvrira au rôle choisi et laissera le salon de vérification visible. "
                "Les espaces déjà privés et les salons/catégories staff, admin, modération, logs et audits restent intacts."
                if self.auto_access
                else (
                    "**DÉSACTIVÉ** — aucune nouvelle permission ne sera modifiée. "
                    "Les permissions configurées lors d'une ancienne publication ne sont pas restaurées automatiquement."
                )
            ),
            inline=False,
        )
        embed.add_field(
            name="État",
            value=(
                "**PRÊT À PUBLIER** — le diagnostic complet sera refait juste avant la publication."
                if ready
                else "**À COMPLÉTER** — choisissez au minimum le salon et le rôle."
            ),
            inline=False,
        )
        embed.set_footer(text="SentriX • Vérification • CAPTCHA activé")
        return embed

    def final_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.panel_title,
            description=self.rules_text,
            colour=discord.Colour.blurple(),
        )
        if self.image_url:
            embed.set_image(url=self.image_url)
        embed.set_footer(text="SentriX • Vérification sécurisée")
        return embed

    @discord.ui.button(label="3. Modifier le règlement", style=discord.ButtonStyle.secondary, row=2)
    async def edit_rules(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self._publishing:
            return await interaction.response.send_message(
                "Une publication est déjà en cours.", ephemeral=True
            )
        await interaction.response.send_modal(VerificationRulesModal(self))

    @discord.ui.button(label="Aperçu", style=discord.ButtonStyle.primary, row=2)
    async def preview(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from cogs.verification import VerifyView

        await interaction.response.send_message(
            content="**Aperçu exact du panneau qui sera publié :**",
            embed=self.final_embed(),
            view=VerifyView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Diagnostic", style=discord.ButtonStyle.secondary, row=2)
    async def diagnostic(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild, channel, role = self._resolved()
        issues: list[str] = []
        if guild is None:
            issues.append("Serveur introuvable.")
        if channel is None:
            issues.append("Salon du règlement non choisi ou supprimé.")
        if role is None:
            issues.append("Rôle de vérification non choisi ou supprimé.")
        if guild is not None and channel is not None and role is not None:
            issues.extend(
                await self.cog._preflight(
                    guild,
                    channel=channel,
                    role=role,
                    auto_access=self.auto_access,
                )
            )

        embed = discord.Embed(
            title="Diagnostic de la vérification",
            colour=discord.Colour.green() if not issues else discord.Colour.orange(),
        )
        if issues:
            embed.description = "La configuration n'est pas encore prête."
            embed.add_field(
                name="À corriger",
                value="\n".join(f"• {item}" for item in issues)[:1024],
                inline=False,
            )
        else:
            embed.description = "La configuration est prête à être publiée."
            embed.add_field(name="Salon", value=channel.mention, inline=True)
            embed.add_field(name="Rôle", value=role.mention, inline=True)
            embed.add_field(name="CAPTCHA", value="Activé", inline=True)
            embed.add_field(
                name="Accès salons",
                value="Automatiques" if self.auto_access else "Inchangés",
                inline=True,
            )
        embed.set_footer(text="SentriX • Diagnostic vérification")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Publier", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self._publishing:
            return await interaction.response.send_message(
                "Une publication est déjà en cours. Patientez quelques secondes.",
                ephemeral=True,
            )

        guild, channel, role = self._resolved()
        if guild is None:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        if channel is None:
            return await interaction.response.send_message(
                "Choisissez d'abord le salon où publier le règlement.", ephemeral=True
            )
        if role is None:
            return await interaction.response.send_message(
                "Choisissez d'abord le rôle à donner après la vérification.", ephemeral=True
            )

        issues = await self.cog._preflight(
            guild,
            channel=channel,
            role=role,
            auto_access=self.auto_access,
        )
        if issues:
            embed = discord.Embed(
                title="Publication impossible",
                description="Corrigez ces points puis réessayez.",
                colour=discord.Colour.orange(),
            )
            embed.add_field(
                name="Diagnostic",
                value="\n".join(f"• {item}" for item in issues)[:1024],
                inline=False,
            )
            embed.set_footer(text="SentriX • Vérification")
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        self._publishing = True
        self._sync_controls()
        await interaction.response.defer(ephemeral=True, thinking=True)

        from cogs.verification import VerifyView

        old_message_to_delete: discord.Message | None = None
        try:
            await self.cog._ensure_table()
            await self.cog._ensure_auto_access_column()

            await self.bot.db.set_guild_config(guild.id, "verify_role", role.id)
            await self.bot.db.set_guild_config(guild.id, "verification_role", role.id)
            await self.bot.db.set_guild_config(guild.id, "verification_channel", channel.id)
            await self.bot.db.set_guild_config(guild.id, "verify_captcha_enabled", 1)
            await self.bot.db.set_guild_config(
                guild.id, "verification_auto_access", int(self.auto_access)
            )

            existing = await self.bot.db.fetchone(
                "SELECT channel_id, message_id FROM verification_panels_v96 WHERE guild_id = ?",
                (guild.id,),
            )
            sent: discord.Message | None = None
            if existing:
                old_channel = guild.get_channel(int(existing["channel_id"]))
                if isinstance(old_channel, discord.TextChannel):
                    try:
                        old_message = await old_channel.fetch_message(int(existing["message_id"]))
                        if old_channel.id == channel.id:
                            await old_message.edit(embed=self.final_embed(), view=VerifyView())
                            sent = old_message
                        else:
                            old_message_to_delete = old_message
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass

            if sent is None:
                sent = await channel.send(embed=self.final_embed(), view=VerifyView())

            await self.bot.db.execute(
                "INSERT INTO verification_panels_v96(guild_id,channel_id,message_id,role_id,title,rules_text,image_url,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id, "
                "role_id=excluded.role_id, title=excluded.title, rules_text=excluded.rules_text, "
                "image_url=excluded.image_url, updated_at=excluded.updated_at",
                (
                    guild.id,
                    channel.id,
                    sent.id,
                    role.id,
                    self.panel_title,
                    self.rules_text,
                    self.image_url,
                    int(time.time()),
                ),
            )

            access_text = "Désactivés — permissions Discord inchangées."
            changed = 0
            protected = 0
            if self.auto_access:
                changed, protected = await self.cog._apply_auto_access(
                    guild,
                    verification_channel=channel,
                    verified_role=role,
                    actor=interaction.user,
                )
                access_text = (
                    f"Activés — {changed} espace(s) public(s) configuré(s), "
                    f"{protected} espace(s) privé(s)/sensible(s) conservé(s)."
                )

            if old_message_to_delete is not None:
                try:
                    await old_message_to_delete.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "Ancien panneau de vérification impossible à supprimer guild=%s message=%s",
                        guild.id,
                        getattr(old_message_to_delete, "id", None),
                    )

            self.has_existing_panel = True

            success = discord.Embed(
                title="Vérification publiée",
                description="Le système de vérification est actif et prêt à être utilisé.",
                colour=discord.Colour.green(),
            )
            success.add_field(name="Salon", value=channel.mention, inline=True)
            success.add_field(name="Rôle attribué", value=role.mention, inline=True)
            success.add_field(name="CAPTCHA", value="Activé", inline=True)
            success.add_field(name="Accès salons", value=access_text, inline=False)
            success.add_field(
                name="Panneau",
                value=f"[Ouvrir le panneau]({sent.jump_url})",
                inline=False,
            )
            success.set_footer(text="SentriX • Vérification sécurisée")
            await interaction.followup.send(embed=success, ephemeral=True)

        except Exception as exc:
            logger.exception(
                "Publication vérification échouée guild=%s channel=%s role=%s auto_access=%s",
                guild.id,
                channel.id,
                role.id,
                self.auto_access,
            )
            failure = discord.Embed(
                title="Publication interrompue",
                description=(
                    "SentriX n'a pas pu terminer la publication. "
                    "La cause a été enregistrée dans les logs pour éviter un échec silencieux."
                ),
                colour=discord.Colour.red(),
            )
            failure.add_field(
                name="Détail technique",
                value=f"`{type(exc).__name__}: {str(exc)[:700]}`",
                inline=False,
            )
            failure.set_footer(text="SentriX • Vérification")
            await interaction.followup.send(embed=failure, ephemeral=True)
        finally:
            self._publishing = False
            self._sync_controls()

    @discord.ui.button(label="4. Accès salons : NON", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_auto_access(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if self._publishing:
            return await interaction.response.send_message(
                "Une publication est déjà en cours.", ephemeral=True
            )
        self.auto_access = not self.auto_access
        self._sync_controls()
        await interaction.response.edit_message(
            embed=self.configuration_embed(),
            view=self,
        )


class VerificationConfigV96(commands.Cog, name="VerificationConfigV96"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self._ensure_table()
        from cogs.verification import VerifyView

        if not getattr(self.bot, "_sentrix_verify_view_registered_v96", False):
            self.bot.add_view(VerifyView())
            self.bot._sentrix_verify_view_registered_v96 = True

    async def _ensure_auto_access_column(self) -> None:
        """Répare le schéma guild_config après restauration d'un ancien snapshot HA."""
        columns = await self.bot.db.fetchall("PRAGMA table_info(guild_config)")
        if any(str(row[1]) == "verification_auto_access" for row in columns):
            return
        try:
            await self.bot.db.execute(
                "ALTER TABLE guild_config ADD COLUMN verification_auto_access INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            columns = await self.bot.db.fetchall("PRAGMA table_info(guild_config)")
            if not any(str(row[1]) == "verification_auto_access" for row in columns):
                raise
        cache = getattr(self.bot.db, "_guild_config_cache", None)
        if isinstance(cache, dict):
            cache.clear()
        logger.info("Schéma vérification confirmé : verification_auto_access disponible.")

    async def _ensure_table(self) -> None:
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_panels_v96 (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                rules_text TEXT NOT NULL,
                image_url TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )
        await self._ensure_auto_access_column()

    async def _preflight(
        self,
        guild: discord.Guild,
        *,
        channel: discord.TextChannel,
        role: discord.Role,
        auto_access: bool,
    ) -> list[str]:
        """Valide toute la chaîne avant une publication pour éviter les états partiels."""
        from cogs.verification import role_grant_problem

        issues: list[str] = []
        problem = role_grant_problem(guild, role)
        if problem:
            issues.append(problem)

        me = guild.me
        if me is None:
            issues.append("SentriX n'est pas disponible dans le cache de ce serveur.")
            return issues

        channel_permissions = channel.permissions_for(me)
        required_channel_permissions = (
            ("view_channel", "Voir le salon"),
            ("send_messages", "Envoyer des messages"),
            ("embed_links", "Intégrer des liens"),
        )
        missing = [
            label
            for attr, label in required_channel_permissions
            if not bool(getattr(channel_permissions, attr, False))
        ]
        if missing:
            issues.append(
                "Permissions manquantes dans le salon : " + ", ".join(f"**{item}**" for item in missing) + "."
            )

        if auto_access:
            guild_permissions = me.guild_permissions
            missing_auto = []
            if not guild_permissions.manage_channels:
                missing_auto.append("Gérer les salons")
            if not guild_permissions.manage_roles:
                missing_auto.append("Gérer les rôles")
            if missing_auto:
                issues.append(
                    "Accès automatiques impossibles sans "
                    + " et ".join(f"**{item}**" for item in missing_auto)
                    + "."
                )

        return issues

    async def _load_setup_state(self, guild: discord.Guild) -> dict:
        """Recharge la configuration existante afin que +verification serve aussi d'éditeur."""
        await self._ensure_table()
        conf = await self.bot.db.get_guild_config(guild.id)
        panel = await self.bot.db.fetchone(
            "SELECT * FROM verification_panels_v96 WHERE guild_id = ?",
            (guild.id,),
        )

        channel_id = _row_value(conf, "verification_channel") or _row_value(panel, "channel_id")
        role_id = (
            _row_value(conf, "verify_role")
            or _row_value(conf, "verification_role")
            or _row_value(panel, "role_id")
        )
        auto_raw = _row_value(conf, "verification_auto_access", 0)
        try:
            auto_access = bool(int(auto_raw or 0))
        except (TypeError, ValueError):
            auto_access = bool(auto_raw)

        return {
            "channel_id": int(channel_id) if channel_id else None,
            "role_id": int(role_id) if role_id else None,
            "panel_title": _row_value(panel, "title", _DEFAULT_TITLE) or _DEFAULT_TITLE,
            "rules_text": _row_value(panel, "rules_text", _DEFAULT_RULES) or _DEFAULT_RULES,
            "image_url": _row_value(panel, "image_url"),
            "auto_access": auto_access,
            "has_existing_panel": panel is not None,
        }

    async def _apply_auto_access(
        self,
        guild: discord.Guild,
        *,
        verification_channel: discord.TextChannel,
        verified_role: discord.Role,
        actor: discord.abc.User,
    ) -> tuple[int, int]:
        """Ferme les espaces publics à @everyone et les ouvre au rôle vérifié.

        Les espaces déjà privés et les surfaces sensibles (staff/admin/modération/logs/audits)
        ne sont jamais modifiés. Le salon de vérification reste visible avant le CAPTCHA.
        Si Discord refuse une écriture, les changements déjà effectués sont restaurés.
        """
        everyone = guild.default_role
        channels = list(guild.channels)
        public_before = {
            item.id: bool(item.permissions_for(everyone).view_channel)
            for item in channels
        }
        sensitive_ids = {item.id for item in channels if _sensitive_surface(item)}

        category_targets: set[int] = set()
        protected_ids: set[int] = set()
        for category in guild.categories:
            children = list(category.channels)
            risky_child = any(
                child.id != verification_channel.id
                and (child.id in sensitive_ids or not public_before.get(child.id, False))
                for child in children
            )
            if (
                not public_before.get(category.id, False)
                or category.id in sensitive_ids
                or risky_child
            ):
                protected_ids.add(category.id)
                continue
            category_targets.add(category.id)

        surfaces: list[discord.abc.GuildChannel] = []
        surfaces.extend(category for category in guild.categories if category.id in category_targets)

        for item in channels:
            if isinstance(item, discord.CategoryChannel):
                continue
            if item.id == verification_channel.id:
                continue
            if item.id in sensitive_ids or not public_before.get(item.id, False):
                protected_ids.add(item.id)
                continue
            parent = getattr(item, "category", None)
            covered_by_category = (
                parent is not None
                and parent.id in category_targets
                and bool(getattr(item, "permissions_synced", False))
            )
            if not covered_by_category:
                surfaces.append(item)

        surfaces.append(verification_channel)

        operations: list[
            tuple[
                discord.abc.GuildChannel,
                discord.Role,
                bool,
                discord.PermissionOverwrite,
                discord.PermissionOverwrite,
            ]
        ] = []
        seen: set[tuple[int, int]] = set()

        def plan(
            surface: discord.abc.GuildChannel,
            target: discord.Role,
            *,
            view_channel: bool,
        ) -> None:
            key = (surface.id, target.id)
            if key in seen:
                return
            seen.add(key)
            old = surface.overwrites_for(target)
            new = _clone_overwrite(old)
            new.view_channel = view_channel
            had_overwrite = target in surface.overwrites
            operations.append((surface, target, had_overwrite, old, new))

        for surface in surfaces:
            if surface.id == verification_channel.id:
                plan(surface, everyone, view_channel=True)
                plan(surface, verified_role, view_channel=True)
            else:
                plan(surface, everyone, view_channel=False)
                plan(surface, verified_role, view_channel=True)

        changed: list[
            tuple[
                discord.abc.GuildChannel,
                discord.Role,
                bool,
                discord.PermissionOverwrite,
                discord.PermissionOverwrite,
            ]
        ] = []
        reason = f"SentriX vérification : accès automatiques configurés par {actor} ({actor.id})"
        try:
            for surface, target, had_overwrite, old, new in operations:
                await surface.set_permissions(target, overwrite=new, reason=reason)
                changed.append((surface, target, had_overwrite, old, new))
        except (discord.Forbidden, discord.HTTPException) as exc:
            rollback_reason = "SentriX vérification : annulation après échec de configuration automatique"
            for surface, target, had_overwrite, old, _new in reversed(changed):
                try:
                    await surface.set_permissions(
                        target,
                        overwrite=old if had_overwrite else None,
                        reason=rollback_reason,
                    )
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception(
                        "Rollback permission impossible sur %s pour %s",
                        getattr(surface, "id", "?"),
                        getattr(target, "id", "?"),
                    )
            raise RuntimeError(f"Discord a refusé une permission sur {surface!s}") from exc

        changed_surfaces = {surface.id for surface, *_rest in changed}
        protected_ids.discard(verification_channel.id)
        return len(changed_surfaces), len(protected_ids)

    @commands.hybrid_command(
        name="verification",
        aliases=["verify-panel", "verify-setup", "verify-config", "verification-config"],
        description="Configurer le règlement, le CAPTCHA et le rôle de vérification.",
        with_app_command=False,
    )
    @commands.guild_only()
    async def verification_setup(self, ctx: commands.Context) -> None:
        from utils import checks

        predicate = checks.is_owner_or_admin().predicate
        if not await predicate(ctx):
            return

        state = await self._load_setup_state(ctx.guild)
        view = VerificationSetupView(
            self,
            ctx.guild.id,
            ctx.author.id,
            **state,
        )
        await ctx.send(embed=view.configuration_embed(), view=view)


async def _attach(bot: commands.Bot) -> None:
    if bot.get_cog("VerificationConfigV96") is not None:
        return

    for legacy in ("verify-panel", "verify-setup"):
        command = bot.get_command(legacy)
        if command is not None:
            bot.remove_command(command.name)

    await bot.add_cog(VerificationConfigV96(bot))

    try:
        import main

        main.CATEGORY_COMMANDS["configuration"] = (
            main.CATEGORY_COMMANDS.get("configuration", frozenset()) | frozenset({"verification"})
        )
        main.KNOWN_PERMISSION_COMMANDS = main.KNOWN_PERMISSION_COMMANDS | frozenset({"verification"})
        main.PRUNED_COMMANDS = frozenset(
            name for name in main.PRUNED_COMMANDS if name not in {"verification", "verify-panel", "verify-setup"}
        )
    except Exception:
        logger.exception("Impossible de réaffirmer la politique de permission vérification V96.")


def _install_v95_route() -> None:
    try:
        import sentrix_v95_runtime as v95
    except Exception:
        return
    current = v95._special_group
    if getattr(current, "_sentrix_verification_v96", False):
        return

    def special_group_v96(command):
        name = str(getattr(command, "name", "") or "").casefold()
        if name == "verification":
            return "roles", "verification"
        return current(command)

    special_group_v96._sentrix_verification_v96 = True
    special_group_v96._sentrix_original = current
    v95._special_group = special_group_v96


def install() -> None:
    """Branche V96 juste après le chargement du cog de vérification historique."""
    _install_v95_route()
    current = commands.Bot.load_extension
    if getattr(current, "_sentrix_verification_v96", False):
        return

    async def load_extension_v96(self, name, *args, **kwargs):
        result = await current(self, name, *args, **kwargs)
        if str(name) == "cogs.verification":
            await _attach(self)
        return result

    load_extension_v96._sentrix_verification_v96 = True
    load_extension_v96._sentrix_original = current
    commands.Bot.load_extension = load_extension_v96
    logger.info("V96 : assistant règlement + CAPTCHA branché sur cogs.verification.")


__all__ = ["VerificationConfigV96", "VerificationSetupView", "install"]
