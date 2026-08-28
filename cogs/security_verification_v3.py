"""Vérification renforcée et honeypot SentriX, configurables dans +setup > Sécurité.

La vérification attribue un rôle uniquement après les contrôles configurés. Le honeypot
est un piège explicite : seuls les comptes NON vérifiés et NON whitelistés qui y écrivent
peuvent recevoir l'action configurée. Les previews ne déclenchent aucune sanction.
"""
from __future__ import annotations

import secrets
import string
import time

import discord
from discord.ext import commands

import config
from utils import embeds, helpers
from . import setup_control_center as setup_ui
from . import setup_v2_core as core

_ALLOWED_ACTIONS = {"none", "kick", "softban"}
_DEFAULTS = {
    "verification_enabled": False,
    "verification_channel_id": None,
    "verified_role_id": None,
    "min_account_age_hours": 24,
    "require_membership_screening": True,
    "challenge_enabled": True,
    "max_attempts": 3,
    "challenge_timeout_seconds": 180,
    "failure_action": "none",
    "honeypot_enabled": False,
    "honeypot_channel_id": None,
    "honeypot_action": "softban",
    "verification_panel_message_id": None,
    "honeypot_panel_message_id": None,
}


async def ensure_schema(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_security_verification_v3_schema", False):
        return
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_verification_v3 (
            guild_id INTEGER PRIMARY KEY,
            verification_enabled INTEGER NOT NULL DEFAULT 0,
            verification_channel_id INTEGER,
            verified_role_id INTEGER,
            min_account_age_hours INTEGER NOT NULL DEFAULT 24,
            require_membership_screening INTEGER NOT NULL DEFAULT 1,
            challenge_enabled INTEGER NOT NULL DEFAULT 1,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            challenge_timeout_seconds INTEGER NOT NULL DEFAULT 180,
            failure_action TEXT NOT NULL DEFAULT 'none',
            honeypot_enabled INTEGER NOT NULL DEFAULT 0,
            honeypot_channel_id INTEGER,
            honeypot_action TEXT NOT NULL DEFAULT 'softban',
            verification_panel_message_id INTEGER,
            honeypot_panel_message_id INTEGER,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_verification_challenges_v3 (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            expected_answer INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_verified_members_v3 (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            verified_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    bot._sentrix_security_verification_v3_schema = True


async def get_security_settings(bot: commands.Bot, guild_id: int) -> dict:
    await ensure_schema(bot)
    row = await bot.db.fetchone("SELECT * FROM security_verification_v3 WHERE guild_id=?", (guild_id,))
    if row is None:
        return dict(_DEFAULTS)
    values = dict(_DEFAULTS)
    values.update({
        "verification_enabled": bool(row["verification_enabled"]),
        "verification_channel_id": row["verification_channel_id"],
        "verified_role_id": row["verified_role_id"],
        "min_account_age_hours": int(row["min_account_age_hours"]),
        "require_membership_screening": bool(row["require_membership_screening"]),
        "challenge_enabled": bool(row["challenge_enabled"]),
        "max_attempts": int(row["max_attempts"]),
        "challenge_timeout_seconds": int(row["challenge_timeout_seconds"]),
        "failure_action": str(row["failure_action"] or "none"),
        "honeypot_enabled": bool(row["honeypot_enabled"]),
        "honeypot_channel_id": row["honeypot_channel_id"],
        "honeypot_action": str(row["honeypot_action"] or "softban"),
        "verification_panel_message_id": row["verification_panel_message_id"],
        "honeypot_panel_message_id": row["honeypot_panel_message_id"],
    })
    return values


async def _ensure_settings_row(bot: commands.Bot, guild_id: int, actor_id: int | None = None) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT OR IGNORE INTO security_verification_v3 (guild_id,updated_by,updated_at) VALUES (?,?,?)",
        (guild_id, actor_id, int(time.time())),
    )


async def update_security_setting(
    bot: commands.Bot,
    guild_id: int,
    field: str,
    value,
    actor_id: int | None,
) -> None:
    allowed = {
        "verification_enabled", "verification_channel_id", "verified_role_id",
        "min_account_age_hours", "require_membership_screening", "challenge_enabled",
        "max_attempts", "challenge_timeout_seconds", "failure_action",
        "honeypot_enabled", "honeypot_channel_id", "honeypot_action",
        "verification_panel_message_id", "honeypot_panel_message_id",
    }
    if field not in allowed:
        raise ValueError("réglage de sécurité invalide")
    if field in {"failure_action", "honeypot_action"} and str(value) not in _ALLOWED_ACTIONS:
        raise ValueError("action de sécurité invalide")
    await _ensure_settings_row(bot, guild_id, actor_id)
    await bot.db.execute(
        f"UPDATE security_verification_v3 SET {field}=?,updated_by=?,updated_at=? WHERE guild_id=?",
        (value, actor_id, int(time.time()), guild_id),
    )


def verification_panel_embed(guild: discord.Guild, settings: dict) -> discord.Embed:
    age = int(settings["min_account_age_hours"])
    age_text = f"{age // 24} jour(s)" if age and age % 24 == 0 else f"{age} heure(s)"
    e = discord.Embed(
        title="Vérification renforcée SentriX",
        description=(
            "L’accès configuré par le serveur reste bloqué tant que la vérification complète n’est pas terminée.\n\n"
            "**SentriX contrôle :**\n"
            + ("• les règles Discord / Membership Screening ;\n" if settings["require_membership_screening"] else "")
            + f"• l’ancienneté minimale du compte : **{age_text}** ;\n"
            + ("• un challenge interactif anti-automatisation ;\n• un code unique + un calcul à usage unique ;\n" if settings["challenge_enabled"] else "")
            + f"• les tentatives répétées (maximum **{settings['max_attempts']}**).\n\n"
            "Clique sur **Commencer la vérification**. Un simple clic ne donne jamais accès au serveur."
        ),
        colour=discord.Colour.orange(),
    )
    e.set_footer(text="SentriX • Vérification renforcée")
    return e


def honeypot_panel_embed(guild: discord.Guild, settings: dict) -> discord.Embed:
    verification_channel = guild.get_channel(settings.get("verification_channel_id"))
    verification_text = verification_channel.mention if verification_channel else "le salon de vérification"
    action = {"none": "journalisation", "kick": "expulsion", "softban": "softban automatique"}.get(
        settings["honeypot_action"], settings["honeypot_action"]
    )
    e = discord.Embed(
        title="NE PAS ENVOYER DE MESSAGE DANS CE SALON",
        description=(
            "Ce salon sert de **honeypot anti-bot** pour repérer les comptes automatisés et spam-bots.\n"
            f"Tout message d’un compte non vérifié et non whitelisté peut entraîner : **{action}**.\n\n"
            f"Pour accéder normalement au serveur, termine la vérification dans {verification_text}."
        ),
        colour=discord.Colour.orange(),
    )
    e.set_footer(text="SentriX • Honeypot anti-bot")
    return e


class VerificationChallengeModal(discord.ui.Modal):
    def __init__(self, runtime: "SecurityVerificationRuntime", guild_id: int, user_id: int, code: str, left: int, right: int):
        super().__init__(title="Vérification SentriX")
        self.runtime = runtime
        self.guild_id = guild_id
        self.user_id = user_id
        self.code_input = discord.ui.TextInput(
            label=f"Recopie le code : {code}",
            placeholder=code,
            min_length=len(code),
            max_length=len(code),
        )
        self.math_input = discord.ui.TextInput(
            label=f"Combien font {left} + {right} ?",
            placeholder="Réponse en chiffres",
            max_length=4,
        )
        self.add_item(self.code_input)
        self.add_item(self.math_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.runtime.complete_challenge(
            interaction,
            str(self.code_input.value).strip().upper(),
            str(self.math_input.value).strip(),
        )


class VerificationPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Commencer la vérification",
        style=discord.ButtonStyle.success,
        custom_id="sentrix:security:v3:start-verification",
    )
    async def start(self, interaction: discord.Interaction, _button: discord.ui.Button):
        runtime = getattr(self.bot, "_sentrix_security_verification_v3_runtime", None)
        if runtime is None:
            return await interaction.response.send_message(
                "La vérification est momentanément indisponible.", ephemeral=True
            )
        await runtime.start_verification(interaction)


class SecurityVerificationRuntime:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._honeypot_busy: set[tuple[int, int]] = set()

    async def is_trusted(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id == guild.owner_id or user_id in config.OWNER_IDS:
            return True
        if self.bot.user and user_id == self.bot.user.id:
            return True
        return await core.is_trusted(self.bot, guild.id, user_id)

    async def is_verified(self, member: discord.Member, settings: dict | None = None) -> bool:
        settings = settings or await get_security_settings(self.bot, member.guild.id)
        role_id = settings.get("verified_role_id")
        if role_id and any(role.id == int(role_id) for role in member.roles):
            return True
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM security_verified_members_v3 WHERE guild_id=? AND user_id=?",
            (member.guild.id, member.id),
        )
        return row is not None

    async def _log(self, guild: discord.Guild, title: str, description: str, member: discord.Member | None = None) -> None:
        e = discord.Embed(title=title, description=description, colour=discord.Colour.orange())
        if member is not None:
            e.add_field(name="Membre", value=f"{member.mention}\n`{member.id}`", inline=False)
        e.set_footer(text="SentriX • Sécurité")
        await helpers.send_log(self.bot, guild, "automod", e)

    async def _grant_verified(self, interaction: discord.Interaction, member: discord.Member, settings: dict) -> bool:
        role_id = settings.get("verified_role_id")
        role = member.guild.get_role(int(role_id)) if role_id else None
        if role is None or role.is_default() or role.managed:
            await interaction.response.send_message(
                "Le rôle vérifié est introuvable ou non attribuable. Préviens un administrateur.",
                ephemeral=True,
            )
            return False
        me = member.guild.me
        if me is None or role >= me.top_role:
            await interaction.response.send_message(
                "SentriX ne peut pas attribuer le rôle vérifié : place ce rôle sous le rôle du bot.",
                ephemeral=True,
            )
            return False
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="Vérification renforcée SentriX réussie")
            except (discord.Forbidden, discord.HTTPException):
                await interaction.response.send_message(
                    "Discord refuse l’attribution du rôle vérifié. Préviens un administrateur.",
                    ephemeral=True,
                )
                return False
        await self.bot.db.execute(
            "INSERT INTO security_verified_members_v3 (guild_id,user_id,verified_at) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET verified_at=excluded.verified_at",
            (member.guild.id, member.id, int(time.time())),
        )
        await self.bot.db.execute(
            "DELETE FROM security_verification_challenges_v3 WHERE guild_id=? AND user_id=?",
            (member.guild.id, member.id),
        )
        await interaction.response.send_message(
            embed=embeds.success(f"Vérification terminée. Le rôle {role.mention} a été attribué."),
            ephemeral=True,
        )
        await self._log(member.guild, "Vérification réussie", "Tous les contrôles configurés sont validés.", member)
        return True

    async def start_verification(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Cette vérification fonctionne uniquement sur un serveur.", ephemeral=True)
        if not await core.module_enabled(self.bot, interaction.guild.id, "security"):
            return await interaction.response.send_message("Le module Sécurité est désactivé sur ce serveur.", ephemeral=True)
        settings = await get_security_settings(self.bot, interaction.guild.id)
        if not settings["verification_enabled"]:
            return await interaction.response.send_message("La vérification renforcée est désactivée.", ephemeral=True)
        if settings["verification_channel_id"] and interaction.channel_id != settings["verification_channel_id"]:
            return await interaction.response.send_message("Utilise le panneau dans le salon de vérification configuré.", ephemeral=True)
        if await self.is_trusted(interaction.guild, interaction.user.id):
            return await interaction.response.send_message("Ce compte est whitelisté et n’a pas besoin de passer le challenge.", ephemeral=True)
        if await self.is_verified(interaction.user, settings):
            return await interaction.response.send_message("Tu es déjà vérifié sur ce serveur.", ephemeral=True)
        if settings["require_membership_screening"] and bool(getattr(interaction.user, "pending", False)):
            return await interaction.response.send_message(
                "Accepte d’abord les règles Discord / Membership Screening du serveur, puis réessaie.",
                ephemeral=True,
            )
        age_seconds = max(0.0, (discord.utils.utcnow() - interaction.user.created_at).total_seconds())
        required = int(settings["min_account_age_hours"]) * 3600
        if age_seconds < required:
            remaining = max(1, int((required - age_seconds + 3599) // 3600))
            return await interaction.response.send_message(
                f"Ton compte est trop récent pour ce serveur. Réessaie dans environ **{remaining} heure(s)**.",
                ephemeral=True,
            )
        if not settings["challenge_enabled"]:
            return await self._grant_verified(interaction, interaction.user, settings)

        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(5))
        left = 2 + secrets.randbelow(11)
        right = 2 + secrets.randbelow(11)
        expected = left + right
        expires_at = int(time.time()) + int(settings["challenge_timeout_seconds"])
        await self.bot.db.execute(
            "INSERT INTO security_verification_challenges_v3 (guild_id,user_id,code,expected_answer,expires_at,attempts) "
            "VALUES (?,?,?,?,?,0) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "code=excluded.code,expected_answer=excluded.expected_answer,expires_at=excluded.expires_at,attempts=0",
            (interaction.guild.id, interaction.user.id, code, expected, expires_at),
        )
        await interaction.response.send_modal(
            VerificationChallengeModal(self, interaction.guild.id, interaction.user.id, code, left, right)
        )

    async def complete_challenge(self, interaction: discord.Interaction, code: str, answer_text: str) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Challenge invalide.", ephemeral=True)
        settings = await get_security_settings(self.bot, interaction.guild.id)
        row = await self.bot.db.fetchone(
            "SELECT * FROM security_verification_challenges_v3 WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        if row is None or int(row["expires_at"]) < int(time.time()):
            if row is not None:
                await self.bot.db.execute(
                    "DELETE FROM security_verification_challenges_v3 WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, interaction.user.id),
                )
            return await interaction.response.send_message(
                "Ce challenge a expiré. Clique de nouveau sur **Commencer la vérification**.", ephemeral=True
            )
        try:
            answer = int(answer_text)
        except ValueError:
            answer = None
        if code == str(row["code"]).upper() and answer == int(row["expected_answer"]):
            return await self._grant_verified(interaction, interaction.user, settings)

        attempts = int(row["attempts"]) + 1
        remaining = max(0, int(settings["max_attempts"]) - attempts)
        await self.bot.db.execute(
            "UPDATE security_verification_challenges_v3 SET attempts=? WHERE guild_id=? AND user_id=?",
            (attempts, interaction.guild.id, interaction.user.id),
        )
        if remaining > 0:
            return await interaction.response.send_message(
                f"Code ou calcul incorrect. **{remaining} tentative(s)** restante(s). Relance le challenge pour obtenir un nouveau code.",
                ephemeral=True,
            )

        await self.bot.db.execute(
            "DELETE FROM security_verification_challenges_v3 WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, interaction.user.id),
        )
        await interaction.response.send_message(
            "Nombre maximal de tentatives atteint. La politique de sécurité configurée va s’appliquer.",
            ephemeral=True,
        )
        await self._log(interaction.guild, "Échec de vérification", f"{attempts} tentative(s) incorrecte(s).", interaction.user)
        await self.apply_action(interaction.user, settings["failure_action"], "Échecs répétés de vérification SentriX")

    async def apply_action(self, member: discord.Member, action: str, reason: str) -> bool:
        if action not in _ALLOWED_ACTIONS or action == "none":
            return False
        if await self.is_trusted(member.guild, member.id):
            return False
        me = member.guild.me
        if me is None or member.id == member.guild.owner_id or member.top_role >= me.top_role:
            return False
        try:
            if action == "kick":
                await member.kick(reason=reason)
            elif action == "softban":
                # Softban sans suppression de messages : aucune donnée XP/économie SentriX
                # n'est touchée. La persistance utilisateur reste indépendante de ce flux.
                await member.guild.ban(member, reason=reason, delete_message_seconds=0)
                await member.guild.unban(discord.Object(id=member.id), reason="Fin du softban SentriX")
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.webhook_id is not None:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return
        if not isinstance(message.author, discord.Member):
            return
        if not await core.module_enabled(self.bot, message.guild.id, "security"):
            return
        settings = await get_security_settings(self.bot, message.guild.id)
        if not settings["honeypot_enabled"] or message.channel.id != settings["honeypot_channel_id"]:
            return
        if await self.is_trusted(message.guild, message.author.id) or await self.is_verified(message.author, settings):
            return

        key = (message.guild.id, message.author.id)
        if key in self._honeypot_busy:
            return
        self._honeypot_busy.add(key)
        try:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            try:
                await message.author.send(
                    f"Ton compte a déclenché le honeypot anti-bot de **{message.guild.name}**. "
                    "Utilise le salon de vérification prévu par le serveur."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            applied = await self.apply_action(
                message.author,
                settings["honeypot_action"],
                "Honeypot anti-bot SentriX : message envoyé dans le salon piège",
            )
            action_label = settings["honeypot_action"] if applied else "journalisation uniquement"
            await self._log(
                message.guild,
                "Honeypot déclenché",
                f"Un compte non vérifié a écrit dans {message.channel.mention}. Action : **{action_label}**.",
                message.author,
            )
        finally:
            self._honeypot_busy.discard(key)

    async def on_member_join(self, member: discord.Member) -> None:
        # Une vérification réussie peut survivre à un départ/ban : le rôle est restauré
        # uniquement si le serveur conserve la même configuration et si Discord Screening
        # n'est pas encore en attente.
        settings = await get_security_settings(self.bot, member.guild.id)
        if not settings["verification_enabled"] or bool(getattr(member, "pending", False)):
            return
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM security_verified_members_v3 WHERE guild_id=? AND user_id=?",
            (member.guild.id, member.id),
        )
        role = member.guild.get_role(settings["verified_role_id"]) if settings["verified_role_id"] else None
        me = member.guild.me
        if row and role and me and not role.managed and role < me.top_role and role not in member.roles:
            try:
                await member.add_roles(role, reason="Restauration de la vérification SentriX")
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def publish_panels(self, guild: discord.Guild, actor_id: int) -> tuple[bool, str]:
        settings = await get_security_settings(self.bot, guild.id)
        created = []
        if settings["verification_channel_id"]:
            channel = guild.get_channel(int(settings["verification_channel_id"]))
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return False, "Le salon de vérification configuré est introuvable."
            message = None
            old_id = settings.get("verification_panel_message_id")
            if old_id:
                try:
                    message = await channel.fetch_message(int(old_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            if message:
                await message.edit(embed=verification_panel_embed(guild, settings), view=VerificationPanelView(self.bot))
            else:
                message = await channel.send(embed=verification_panel_embed(guild, settings), view=VerificationPanelView(self.bot))
                await update_security_setting(self.bot, guild.id, "verification_panel_message_id", message.id, actor_id)
            created.append("vérification")

        if settings["honeypot_channel_id"]:
            channel = guild.get_channel(int(settings["honeypot_channel_id"]))
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return False, "Le salon honeypot configuré est introuvable."
            message = None
            old_id = settings.get("honeypot_panel_message_id")
            if old_id:
                try:
                    message = await channel.fetch_message(int(old_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None
            if message:
                await message.edit(embed=honeypot_panel_embed(guild, settings))
            else:
                message = await channel.send(embed=honeypot_panel_embed(guild, settings))
                await update_security_setting(self.bot, guild.id, "honeypot_panel_message_id", message.id, actor_id)
            created.append("honeypot")

        if not created:
            return False, "Choisissez au moins un salon de vérification ou honeypot."
        return True, "Panneau(x) publié(s)/actualisé(s) : " + ", ".join(created) + "."


class SecurityRulesModal(discord.ui.Modal, title="Règles vérification / honeypot"):
    min_age = discord.ui.TextInput(label="Âge minimum du compte (heures)", default="24", max_length=5)
    max_attempts = discord.ui.TextInput(label="Tentatives max du challenge", default="3", max_length=2)
    timeout = discord.ui.TextInput(label="Expiration du challenge (secondes)", default="180", max_length=4)
    failure_action = discord.ui.TextInput(label="Échec vérification : none / kick / softban", default="none", max_length=8)
    honeypot_action = discord.ui.TextInput(label="Honeypot : none / kick / softban", default="softban", max_length=8)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            min_age = max(0, min(8760, int(str(self.min_age.value))))
            attempts = max(1, min(10, int(str(self.max_attempts.value))))
            timeout = max(30, min(600, int(str(self.timeout.value))))
        except ValueError:
            return await interaction.response.send_message("Les trois premiers champs doivent être des nombres entiers.", ephemeral=True)
        failure = str(self.failure_action.value).strip().lower()
        honeypot = str(self.honeypot_action.value).strip().lower()
        if failure not in _ALLOWED_ACTIONS or honeypot not in _ALLOWED_ACTIONS:
            return await interaction.response.send_message("Actions autorisées : `none`, `kick` ou `softban`.", ephemeral=True)
        gid = self.owner.guild.id
        for field, value in (
            ("min_account_age_hours", min_age),
            ("max_attempts", attempts),
            ("challenge_timeout_seconds", timeout),
            ("failure_action", failure),
            ("honeypot_action", honeypot),
        ):
            await update_security_setting(self.owner.bot, gid, field, value, interaction.user.id)
        await interaction.response.send_message(embed=embeds.success("Règles de sécurité enregistrées."), ephemeral=True)


class SecurityProtectionView(discord.ui.View):
    def __init__(self, setup_view, author_id: int):
        super().__init__(timeout=300)
        self.setup_view = setup_view
        self.bot = setup_view.bot
        self.guild = setup_view.guild
        self.author_id = author_id

        verify_channel = discord.ui.ChannelSelect(
            placeholder="Salon de vérification",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=2,
        )
        honeypot_channel = discord.ui.ChannelSelect(
            placeholder="Salon honeypot anti-bot",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=3,
        )
        verified_role = discord.ui.RoleSelect(
            placeholder="Rôle attribué après vérification",
            min_values=1,
            max_values=1,
            row=4,
        )

        async def verify_channel_cb(interaction: discord.Interaction):
            await update_security_setting(
                self.bot, self.guild.id, "verification_channel_id", verify_channel.values[0].id, interaction.user.id
            )
            await interaction.response.send_message(f"Salon de vérification : {verify_channel.values[0].mention}.", ephemeral=True)

        async def honeypot_channel_cb(interaction: discord.Interaction):
            await update_security_setting(
                self.bot, self.guild.id, "honeypot_channel_id", honeypot_channel.values[0].id, interaction.user.id
            )
            await interaction.response.send_message(f"Salon honeypot : {honeypot_channel.values[0].mention}.", ephemeral=True)

        async def role_cb(interaction: discord.Interaction):
            role = verified_role.values[0]
            if role.is_default() or role.managed:
                return await interaction.response.send_message("Choisissez un rôle normal attribuable par SentriX.", ephemeral=True)
            await update_security_setting(self.bot, self.guild.id, "verified_role_id", role.id, interaction.user.id)
            await interaction.response.send_message(f"Rôle vérifié : {role.mention}.", ephemeral=True)

        verify_channel.callback = verify_channel_cb
        honeypot_channel.callback = honeypot_channel_cb
        verified_role.callback = role_cb
        self.add_item(verify_channel)
        self.add_item(honeypot_channel)
        self.add_item(verified_role)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Vérification ON / OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle_verification(self, interaction: discord.Interaction, _button: discord.ui.Button):
        settings = await get_security_settings(self.bot, self.guild.id)
        if not settings["verification_enabled"] and (not settings["verification_channel_id"] or not settings["verified_role_id"]):
            return await interaction.response.send_message(
                "Configure d’abord le salon de vérification et le rôle vérifié.", ephemeral=True
            )
        await update_security_setting(
            self.bot, self.guild.id, "verification_enabled", 0 if settings["verification_enabled"] else 1, interaction.user.id
        )
        await interaction.response.send_message(
            f"Vérification renforcée : {'INACTIF' if settings['verification_enabled'] else 'ACTIF'}.", ephemeral=True
        )

    @discord.ui.button(label="Honeypot ON / OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle_honeypot(self, interaction: discord.Interaction, _button: discord.ui.Button):
        settings = await get_security_settings(self.bot, self.guild.id)
        if not settings["honeypot_enabled"] and not settings["honeypot_channel_id"]:
            return await interaction.response.send_message("Configure d’abord le salon honeypot.", ephemeral=True)
        await update_security_setting(
            self.bot, self.guild.id, "honeypot_enabled", 0 if settings["honeypot_enabled"] else 1, interaction.user.id
        )
        await interaction.response.send_message(
            f"Honeypot : {'INACTIF' if settings['honeypot_enabled'] else 'ACTIF'}.", ephemeral=True
        )

    @discord.ui.button(label="Challenge ON / OFF", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_challenge(self, interaction: discord.Interaction, _button: discord.ui.Button):
        settings = await get_security_settings(self.bot, self.guild.id)
        await update_security_setting(
            self.bot, self.guild.id, "challenge_enabled", 0 if settings["challenge_enabled"] else 1, interaction.user.id
        )
        await interaction.response.send_message(
            f"Challenge interactif : {'INACTIF' if settings['challenge_enabled'] else 'ACTIF'}.", ephemeral=True
        )

    @discord.ui.button(label="Screening Discord ON / OFF", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_screening(self, interaction: discord.Interaction, _button: discord.ui.Button):
        settings = await get_security_settings(self.bot, self.guild.id)
        await update_security_setting(
            self.bot, self.guild.id, "require_membership_screening",
            0 if settings["require_membership_screening"] else 1,
            interaction.user.id,
        )
        await interaction.response.send_message(
            f"Contrôle Membership Screening : {'INACTIF' if settings['require_membership_screening'] else 'ACTIF'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Règles / sanctions", style=discord.ButtonStyle.secondary, row=1)
    async def rules(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(SecurityRulesModal(self.setup_view))

    @discord.ui.button(label="Publier / actualiser les panneaux", style=discord.ButtonStyle.success, row=1)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button):
        runtime = getattr(self.bot, "_sentrix_security_verification_v3_runtime", None)
        if runtime is None:
            return await interaction.response.send_message("Runtime de sécurité indisponible.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, text = await runtime.publish_panels(self.guild, interaction.user.id)
        await interaction.followup.send(embed=embeds.success(text) if ok else embeds.error(text), ephemeral=True)


async def _security_summary(bot: commands.Bot, guild: discord.Guild) -> str:
    settings = await get_security_settings(bot, guild.id)
    verify_channel = guild.get_channel(settings["verification_channel_id"]) if settings["verification_channel_id"] else None
    honeypot_channel = guild.get_channel(settings["honeypot_channel_id"]) if settings["honeypot_channel_id"] else None
    role = guild.get_role(settings["verified_role_id"]) if settings["verified_role_id"] else None
    problems = []
    if settings["verification_enabled"] and verify_channel is None:
        problems.append("salon de vérification introuvable")
    if settings["verification_enabled"] and role is None:
        problems.append("rôle vérifié introuvable")
    if settings["honeypot_enabled"] and honeypot_channel is None:
        problems.append("salon honeypot introuvable")
    state = "ERREUR DE CONFIGURATION — " + ", ".join(problems) if problems else "Configuration exploitable"
    return (
        f"**Vérification renforcée :** {'ACTIF' if settings['verification_enabled'] else 'INACTIF'}\n"
        f"**Salon :** {verify_channel.mention if verify_channel else 'Non configuré'} • "
        f"**Rôle :** {role.mention if role else 'Non configuré'}\n"
        f"**Honeypot :** {'ACTIF' if settings['honeypot_enabled'] else 'INACTIF'} • "
        f"**Salon :** {honeypot_channel.mention if honeypot_channel else 'Non configuré'} • "
        f"**Action :** `{settings['honeypot_action']}`\n"
        f"**Contrôle :** {state}"
    )


def _patch_setup() -> None:
    current_render = setup_ui.SetupView.render
    if not getattr(current_render, "_sentrix_security_verification_v3", False):
        def render_security_v3(self):
            current_render(self)
            if self.category != "security":
                return
            button = discord.ui.Button(
                label="Vérification & Honeypot",
                style=discord.ButtonStyle.secondary,
                row=1,
            )

            async def callback(interaction: discord.Interaction):
                await interaction.response.send_message(
                    embed=embeds.info(
                        await _security_summary(self.bot, self.guild)
                        + "\n\nLes tests et aperçus ne sanctionnent jamais personne.",
                        title="Vérification renforcée & Honeypot",
                    ),
                    view=SecurityProtectionView(self, interaction.user.id),
                    ephemeral=True,
                )

            button.callback = callback
            self.add_item(button)

        render_security_v3._sentrix_security_verification_v3 = True
        setup_ui.SetupView.render = render_security_v3

    current_build = setup_ui.SetupView.build_embed
    if not getattr(current_build, "_sentrix_security_verification_v3", False):
        async def build_security_v3(self):
            panel = await current_build(self)
            if self.category == "security":
                panel.add_field(
                    name="Vérification renforcée & Honeypot",
                    value=await _security_summary(self.bot, self.guild),
                    inline=False,
                )
            return panel

        build_security_v3._sentrix_security_verification_v3 = True
        setup_ui.SetupView.build_embed = build_security_v3


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_security_verification_v3_installed", False):
        return
    await ensure_schema(bot)
    runtime = SecurityVerificationRuntime(bot)
    bot._sentrix_security_verification_v3_runtime = runtime
    bot.add_listener(runtime.on_message, "on_message")
    bot.add_listener(runtime.on_member_join, "on_member_join")
    bot.add_view(VerificationPanelView(bot))
    _patch_setup()
    bot._sentrix_security_verification_v3_installed = True


__all__ = ["get_security_settings", "update_security_setting", "install"]
