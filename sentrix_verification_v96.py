"""SentriX V96 — configuration guidée du règlement + CAPTCHA de vérification.

Ce module complète le cog historique ``cogs.verification`` sans recopier son moteur
CAPTCHA. Il remplace les anciennes entrées +verify-panel / +verify-setup par un seul
assistant de configuration : salon, rôle, texte du règlement, image facultative,
apercu, permissions automatiques facultatives puis publication.
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
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationSetupView(discord.ui.View):
    def __init__(self, cog: "VerificationConfigV96", guild_id: int, author_id: int) -> None:
        super().__init__(timeout=_SETUP_TIMEOUT)
        self.cog = cog
        self.bot = cog.bot
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)
        self.channel_id: int | None = None
        self.role_id: int | None = None
        self.panel_title = _DEFAULT_TITLE
        self.rules_text = _DEFAULT_RULES
        self.image_url: str | None = None
        self.auto_access = False

        self.add_item(VerificationChannelSelect(self))
        self.add_item(VerificationRoleSelect(self))

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

    def configuration_embed(self) -> discord.Embed:
        guild = self._guild()
        channel = guild.get_channel(self.channel_id) if guild and self.channel_id else None
        role = guild.get_role(self.role_id) if guild and self.role_id else None
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
            value=channel.mention if isinstance(channel, discord.TextChannel) else "Non choisi",
            inline=False,
        )
        embed.add_field(
            name="2 • Rôle après vérification",
            value=role.mention if isinstance(role, discord.Role) else "Non choisi",
            inline=False,
        )
        embed.add_field(
            name="3 • Règlement",
            value=(self.rules_text[:700] + ("…" if len(self.rules_text) > 700 else "")),
            inline=False,
        )
        embed.add_field(
            name="4 • Image",
            value=self.image_url or "Aucune image — facultatif",
            inline=False,
        )
        embed.add_field(
            name="5 • Accès automatiques aux salons",
            value=(
                "**ACTIVÉ** — SentriX cachera les espaces publics aux membres non vérifiés, "
                "les ouvrira au rôle choisi et laissera le salon de vérification visible. "
                "Les espaces déjà privés et les salons/catégories staff, admin, modération, logs et audits restent intacts."
                if self.auto_access
                else "**DÉSACTIVÉ** — les permissions des salons ne seront pas modifiées."
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

    @discord.ui.button(label="Publier", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = self._guild()
        if guild is None:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        channel = guild.get_channel(self.channel_id) if self.channel_id else None
        role = guild.get_role(self.role_id) if self.role_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Choisissez d'abord le salon où publier le règlement.", ephemeral=True
            )
        if not isinstance(role, discord.Role):
            return await interaction.response.send_message(
                "Choisissez d'abord le rôle à donner après la vérification.", ephemeral=True
            )

        from cogs.verification import VerifyView, role_grant_problem

        problem = role_grant_problem(guild, role)
        if problem:
            return await interaction.response.send_message(
                f"Impossible d'utiliser ce rôle : {problem}", ephemeral=True
            )
        permissions = channel.permissions_for(guild.me) if guild.me else None
        if permissions is None or not permissions.send_messages or not permissions.embed_links:
            return await interaction.response.send_message(
                "SentriX doit pouvoir **Voir le salon**, **Envoyer des messages** et **Intégrer des liens** dans ce salon.",
                ephemeral=True,
            )
        if self.auto_access:
            bot_permissions = guild.me.guild_permissions if guild.me else None
            if (
                bot_permissions is None
                or not bot_permissions.manage_channels
                or not bot_permissions.manage_roles
            ):
                return await interaction.response.send_message(
                    "Pour configurer automatiquement les accès, SentriX doit avoir **Gérer les salons** "
                    "et **Gérer les rôles**. Désactivez l'option d'accès automatique ou donnez ces permissions au bot.",
                    ephemeral=True,
                )

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog._ensure_table()

        # Les clés historiques sont maintenues pour toutes les couches Setup existantes.
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
                        await old_message.delete()
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

        access_message = "Accès automatiques désactivés : permissions Discord inchangées."
        if self.auto_access:
            try:
                changed, protected = await self.cog._apply_auto_access(
                    guild,
                    verification_channel=channel,
                    verified_role=role,
                    actor=interaction.user,
                )
            except Exception as exc:
                logger.exception("Échec de la configuration automatique des accès de vérification.")
                return await interaction.followup.send(
                    "Le panneau de vérification a bien été publié, mais **les accès automatiques n'ont pas été appliqués**. "
                    "SentriX a annulé les modifications de permissions déjà commencées afin d'éviter un serveur partiellement configuré.\n"
                    f"Détail : `{type(exc).__name__}: {str(exc)[:500]}`",
                    ephemeral=True,
                )
            access_message = (
                f"Accès automatiques appliqués sur **{changed}** catégorie(s)/salon(s) public(s). "
                f"**{protected}** espace(s) privé(s) ou sensible(s) ont été laissés intacts."
            )

        await interaction.followup.send(
            f"Vérification configurée et publiée dans {channel.mention}.\n"
            f"Après le règlement + CAPTCHA, le membre recevra {role.mention}.\n"
            f"{access_message}",
            ephemeral=True,
        )

    @discord.ui.button(label="5. Accès salons : NON", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_auto_access(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.auto_access = not self.auto_access
        button.label = "5. Accès salons : OUI" if self.auto_access else "5. Accès salons : NON"
        button.style = (
            discord.ButtonStyle.success if self.auto_access else discord.ButtonStyle.secondary
        )
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

    async def _apply_auto_access(
        self,
        guild: discord.Guild,
        *,
        verification_channel: discord.TextChannel,
        verified_role: discord.Role,
        actor: discord.abc.User,
    ) -> tuple[int, int]:
        """Ferme uniquement les espaces actuellement publics et protège les espaces privés.

        La modification est transactionnelle au mieux : si Discord refuse une écriture,
        toutes les permissions déjà modifiées pendant cette passe sont restaurées.
        """
        everyone = guild.default_role
        channels = list(guild.channels)
        public_before = {
            item.id: bool(item.permissions_for(everyone).view_channel)
            for item in channels
        }
        sensitive_ids = {
            item.id for item in channels if _sensitive_surface(item)
        }

        category_targets: set[int] = set()
        protected_ids: set[int] = set()
        for category in guild.categories:
            children = list(category.channels)
            risky_child = any(
                child.id != verification_channel.id
                and (
                    child.id in sensitive_ids
                    or not public_before.get(child.id, False)
                )
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
        surfaces.extend(
            category for category in guild.categories if category.id in category_targets
        )

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

        # Le salon de vérification doit toujours rester visible avant le CAPTCHA, même si
        # sa catégorie vient d'être fermée à @everyone.
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
        # Check explicite ici pour que la commande reste protégée même si une ancienne
        # couche de permissions est rechargée dans un ordre différent.
        from utils import checks

        predicate = checks.is_owner_or_admin().predicate
        if not await predicate(ctx):
            return
        view = VerificationSetupView(self, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=view.configuration_embed(), view=view)


async def _attach(bot: commands.Bot) -> None:
    if bot.get_cog("VerificationConfigV96") is not None:
        return

    # Les anciennes commandes existaient séparément. On les remplace par l'assistant
    # unique tout en gardant leurs noms comme alias préfixés.
    for legacy in ("verify-panel", "verify-setup"):
        command = bot.get_command(legacy)
        if command is not None:
            bot.remove_command(command.name)

    await bot.add_cog(VerificationConfigV96(bot))

    # Politique centrale : une seule commande configuration, admin uniquement.
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
