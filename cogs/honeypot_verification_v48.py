from __future__ import annotations

import asyncio
import logging
import secrets
import string
import time
from dataclasses import dataclass

import discord
from discord.ext import commands

from utils import helpers
from utils import sentrix_panels as panels, rules_flow

logger = logging.getLogger("bot.security.honeypot-v50")
_COG_NAME = "HoneypotVerification"

# Protection volontairement conservatrice : un compte créé à l'instant ne peut pas
# traverser le portail immédiatement. Ce seuil bloque surtout les comptes de raid jetables
# sans pénaliser les comptes Discord normaux.
MIN_ACCOUNT_AGE_SECONDS = 30 * 60
MIN_JOIN_DELAY_SECONDS = 8
CHALLENGE_TTL_SECONDS = 120
START_COOLDOWN_SECONDS = 12
FAILURE_WINDOW_SECONDS = 10 * 60
FAILURE_LOCK_SECONDS = 10 * 60
MAX_FAILURES = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS honeypot_verification (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER,
    trap_channel_id INTEGER,
    verify_channel_id INTEGER,
    unverified_role_id INTEGER,
    verified_role_id INTEGER,
    sanction TEXT NOT NULL DEFAULT 'softban',
    created_at INTEGER NOT NULL
)
"""

_PENDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS honeypot_pending_members (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
)
"""

_VERIFIED_SCHEMA = """
CREATE TABLE IF NOT EXISTS honeypot_verified_members (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    verified_at INTEGER NOT NULL,
    method TEXT NOT NULL,
    account_age_seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
"""


_MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_runtime_migrations (
    name TEXT PRIMARY KEY,
    applied_at INTEGER NOT NULL
)
"""

_WEB_CLEANUP_MIGRATION = "verification_web_v120_cleanup_1"


async def _web_panel(bot: commands.Bot, guild: discord.Guild):
    from cogs import language_runtime
    from web.public_verification_v120 import verification_url

    language = await language_runtime.get_language(bot, guild.id)
    english = language == language_runtime.LANG_EN
    embed = discord.Embed(
        title="SentriX Web Verification" if english else "Vérification web SentriX",
        description=(
            "Verification now happens on the secure SentriX website.\n\n"
            "The site checks your Discord identity, server membership, account age, "
            "current rules and a human CAPTCHA. Once approved, SentriX unlocks your role "
            "and sends you a confirmation DM."
            if english
            else
            "La vérification se fait maintenant sur le site sécurisé SentriX.\n\n"
            "Le site contrôle ton identité Discord, ton appartenance au serveur, "
            "l'ancienneté du compte, le règlement actuel et un CAPTCHA humain. "
            "Une fois validé, SentriX débloque ton rôle et t'envoie un MP de confirmation."
        ),
        colour=discord.Color.blurple(),
    )
    embed.set_footer(
        text="SentriX • Web Verification" if english else "SentriX • Vérification web"
    )
    return panels.depuis_embed(
        embed,
        boutons=(
            panels.Bouton(
                libelle="Verify on SentriX" if english else "Se vérifier sur SentriX",
                url=verification_url(guild.id),
            ),
        ),
    )


def _trap_embed(verify_channel: discord.TextChannel, sanction: str) -> discord.Embed:
    sanction_label = "softban automatique" if sanction == "softban" else "expulsion automatique"
    embed = discord.Embed(
        title="NE PAS ENVOYER DE MESSAGE DANS CE SALON",
        description=(
            "Ce salon est le honeypot SentriX réservé aux comptes non vérifiés.\n"
            f"Écrire ici peut entraîner un **{sanction_label}**.\n\n"
            f"Utilise {verify_channel.mention} pour ouvrir le site de vérification."
        ),
        colour=discord.Color.red(),
    )
    embed.set_footer(text="SentriX • Honeypot anti-bot")
    return embed


async def _purge_bot_messages(channel: discord.TextChannel, bot_user_id: int | None) -> int:
    if not bot_user_id:
        return 0
    deleted = 0
    try:
        async for message in channel.history(limit=100):
            if getattr(message.author, "id", None) != bot_user_id:
                continue
            try:
                await message.delete()
                deleted += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
    except (discord.Forbidden, discord.HTTPException):
        pass
    return deleted


@dataclass
class ChallengeState:
    token: str
    guild_id: int
    user_id: int
    created_at: float
    expires_at: float
    code: str
    math_answer: str
    sequence: tuple[str, ...]
    sequence_done: bool = False


class VerificationModal(discord.ui.Modal):
    def __init__(self, cog: "HoneypotVerification", state: ChallengeState, math_question: str):
        super().__init__(title="SentriX • Vérification humaine", timeout=CHALLENGE_TTL_SECONDS)
        self.cog = cog
        self.state = state

        self.code_input = discord.ui.TextInput(
            label=f"Recopie exactement : {state.code}",
            placeholder="Code affiché ci-dessus",
            min_length=len(state.code),
            max_length=len(state.code),
            required=True,
        )
        self.math_input = discord.ui.TextInput(
            label=f"Calcul rapide : {math_question}",
            placeholder="Réponse en chiffres",
            min_length=1,
            max_length=4,
            required=True,
        )
        self.add_item(self.code_input)
        self.add_item(self.math_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.complete_human_challenge(
            interaction,
            self.state.token,
            str(self.code_input.value),
            str(self.math_input.value),
        )


class SequenceButton(discord.ui.Button):
    def __init__(self, symbol: str):
        super().__init__(label=symbol, style=discord.ButtonStyle.secondary, row=0)
        self.symbol = symbol

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, VerificationSequenceView):
            return
        await view.press(interaction, self.symbol)


class VerificationSequenceView(discord.ui.View):
    """Étape 1 : mini challenge interactif individuel, impossible à valider par un clic unique."""

    SYMBOLS = ("1", "2", "3", "4", "5")

    def __init__(self, cog: "HoneypotVerification", state: ChallengeState, math_question: str):
        super().__init__(timeout=CHALLENGE_TTL_SECONDS)
        self.cog = cog
        self.state = state
        self.math_question = math_question
        self.position = 0

        symbols = list(self.SYMBOLS)
        secrets.SystemRandom().shuffle(symbols)
        for symbol in symbols:
            self.add_item(SequenceButton(symbol))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.state.user_id:
            await interaction.response.send_message(
                "Cette vérification appartient à un autre membre.",
                ephemeral=True,
            )
            return False
        if interaction.guild is None or interaction.guild.id != self.state.guild_id:
            await interaction.response.send_message("Vérification invalide.", ephemeral=True)
            return False
        return True

    async def press(self, interaction: discord.Interaction, symbol: str):
        current = self.cog._challenges.get((self.state.guild_id, self.state.user_id))
        if current is None or current.token != self.state.token or time.time() > current.expires_at:
            self.stop()
            return await interaction.response.edit_message(
                content='⌛ Cette vérification a expiré. Cliquez de nouveau sur **Commencer la vérification**.',
                view=None,
            )

        expected = current.sequence[self.position]
        if symbol != expected:
            await self.cog._record_failure(self.state.guild_id, self.state.user_id)
            self.cog._challenges.pop((self.state.guild_id, self.state.user_id), None)
            for child in self.children:
                child.disabled = True
            self.stop()
            return await interaction.response.edit_message(
                content=(
                    '❌ Mauvais ordre. La tentative a été annulée.\nCliquez de nouveau sur **Commencer la vérification** pour obtenir un nouveau challenge.'
                ),
                view=self,
            )

        self.position += 1
        if self.position < len(current.sequence):
            progress = "●" * self.position + "○" * (len(current.sequence) - self.position)
            return await interaction.response.edit_message(
                content=(
                    f"**Étape 1/2 — challenge anti-automatisation**\nCliquez dans cet ordre : **{' → '.join(current.sequence)}**\nProgression : {progress}"
                ),
                view=self,
            )

        current.sequence_done = True
        self.stop()
        await interaction.response.send_modal(VerificationModal(self.cog, current, self.math_question))


class HoneypotVerifyView(discord.ui.View):
    """Compatibilité avec les anciens panels Discord.

    Les anciens boutons persistants ne lancent plus aucun challenge dans Discord :
    ils renvoient uniquement vers le site web, puis les nouveaux panels utilisent
    directement un bouton-lien.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Se vérifier",
        style=discord.ButtonStyle.success,
        custom_id="sentrix:honeypot:verify",
    )
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Cette vérification doit être ouverte depuis un serveur Discord.",
                ephemeral=True,
            )
        from web.public_verification_v120 import verification_url
        view = discord.ui.View(timeout=60)
        view.add_item(
            discord.ui.Button(
                label="Ouvrir la vérification SentriX",
                url=verification_url(interaction.guild.id),
            )
        )
        await interaction.response.send_message(
            "La vérification se fait maintenant sur le site SentriX.",
            view=view,
            ephemeral=True,
        )


class HoneypotVerification(commands.Cog, name=_COG_NAME):
    """Vérification renforcée + salon piège anti-bot, configurable uniquement via +setup."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._trap_locks: set[tuple[int, int]] = set()
        self._verification_in_progress: set[tuple[int, int]] = set()
        self._challenges: dict[tuple[int, int], ChallengeState] = {}
        self._last_start: dict[tuple[int, int], float] = {}
        self._failures: dict[tuple[int, int], list[float]] = {}
        self._lock_until: dict[tuple[int, int], float] = {}

    async def config(self, guild_id: int, *, enabled_only: bool = True):
        query = "SELECT * FROM honeypot_verification WHERE guild_id = ?"
        if enabled_only:
            query += " AND enabled = 1"
        return await self.bot.db.fetchone(query, (guild_id,))

    async def _pending(self, guild_id: int, user_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM honeypot_pending_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def _mark_pending(self, guild_id: int, user_id: int, joined_at: int | None = None):
        await self.bot.db.execute(
            "INSERT INTO honeypot_pending_members (guild_id, user_id, joined_at) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET joined_at=excluded.joined_at",
            (guild_id, user_id, int(joined_at or time.time())),
        )

    async def _clear_pending(self, guild_id: int, user_id: int):
        await self.bot.db.execute(
            "DELETE FROM honeypot_pending_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    async def _record_failure(self, guild_id: int, user_id: int):
        now_ts = time.time()
        key = (guild_id, user_id)
        failures = self._failures.setdefault(key, [])
        failures.append(now_ts)
        failures[:] = [stamp for stamp in failures if now_ts - stamp <= FAILURE_WINDOW_SECONDS]
        if len(failures) >= MAX_FAILURES:
            self._lock_until[key] = now_ts + FAILURE_LOCK_SECONDS
            self._failures[key] = []

    def _seconds_locked(self, guild_id: int, user_id: int) -> int:
        remaining = self._lock_until.get((guild_id, user_id), 0.0) - time.time()
        return max(0, int(remaining))

    async def _log(self, guild: discord.Guild, title: str, description: str, *, danger: bool = False):
        embed = discord.Embed(
            title=title,
            description=description,
            colour=discord.Color.red() if danger else discord.Color.blurple(),
        )
        embed.set_footer(text="SentriX • Vérification renforcée & Honeypot")
        try:
            await helpers.send_log(self.bot, guild, "automod", embed)
        except Exception:
            logger.exception("Impossible d'envoyer le log honeypot sur %s.", guild.id)

    def _missing_permissions(self, guild: discord.Guild, sanction: str) -> list[str]:
        me = guild.me
        if me is None:
            return ["SentriX n'est pas disponible dans le cache Discord"]
        checks_map = {
            "Gérer les rôles": me.guild_permissions.manage_roles,
            "Gérer les salons": me.guild_permissions.manage_channels,
            "Gérer les messages": me.guild_permissions.manage_messages,
        }
        if sanction == "softban":
            checks_map["Bannir des membres"] = me.guild_permissions.ban_members
        elif sanction == "kick":
            checks_map["Expulser des membres"] = me.guild_permissions.kick_members
        return [label for label, allowed in checks_map.items() if not allowed]

    async def _find_or_create_role(self, guild: discord.Guild, name: str) -> discord.Role:
        existing = discord.utils.get(guild.roles, name=name)
        if existing is not None and not existing.managed:
            return existing
        return await guild.create_role(
            name=name,
            permissions=discord.Permissions.none(),
            reason="SentriX : configuration vérification renforcée depuis +setup",
        )

    @staticmethod
    def _unverified_overwrite() -> discord.PermissionOverwrite:
        return discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            add_reactions=False,
            create_public_threads=False,
            create_private_threads=False,
            connect=False,
            speak=False,
        )

    async def _lock_existing_channels(
        self,
        guild: discord.Guild,
        unverified: discord.Role,
        excluded_ids: set[int],
    ) -> None:
        overwrite = self._unverified_overwrite()
        for channel in list(guild.channels):
            if channel.id in excluded_ids:
                continue
            try:
                await channel.set_permissions(
                    unverified,
                    overwrite=overwrite,
                    reason="SentriX : accès interdit avant vérification complète",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Impossible de verrouiller %s sur %s.", channel.id, guild.id)
            await asyncio.sleep(0.05)

    async def create_or_refresh_system(self, guild: discord.Guild, *, sanction: str = "softban"):
        if sanction not in {"softban", "kick"}:
            sanction = "softban"

        missing = self._missing_permissions(guild, sanction)
        if missing:
            return None, "Permissions manquantes : " + ", ".join(missing)

        old = await self.config(guild.id, enabled_only=False)
        unverified = await self._find_or_create_role(guild, "Non vérifié")

        # Une seule source de vérité pour le rôle final : si /setup ou le règlement a déjà
        # choisi verify_role, la vérification renforcée réutilise exactement ce rôle au lieu
        # de créer un deuxième rôle "Vérifié".
        verified = None
        try:
            guild_conf = await self.bot.db.get_guild_config(guild.id)
            configured_role_id = guild_conf["verify_role"] if guild_conf else None
            if configured_role_id:
                candidate = guild.get_role(int(configured_role_id))
                if candidate is not None and not candidate.managed and not candidate.is_default():
                    verified = candidate
        except Exception:
            logger.debug("Lecture du rôle Vérifié configuré impossible guild=%s", guild.id, exc_info=True)
        if verified is None:
            old_verified_id = old["verified_role_id"] if old and old["verified_role_id"] else None
            verified = guild.get_role(int(old_verified_id)) if old_verified_id else None
        if verified is None or verified.managed or verified.is_default():
            verified = await self._find_or_create_role(guild, "Vérifié")
        try:
            await self.bot.db.set_guild_config(guild.id, "verify_role", verified.id)
            await self.bot.db.set_guild_config(guild.id, "verification_role", verified.id)
        except Exception:
            logger.debug("Synchronisation du rôle Vérifié impossible guild=%s", guild.id, exc_info=True)

        me = guild.me
        if me is None:
            return None, "SentriX est introuvable sur ce serveur."

        if unverified >= me.top_role or verified >= me.top_role:
            return None, (
                "Les rôles `Non vérifié` et `Vérifié` doivent être placés sous le rôle SentriX. "
                "Déplace-les puis réessaie depuis +setup."
            )

        category = guild.get_channel(old["category_id"]) if old and old["category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category(
                "SentriX • Vérification",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    unverified: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_channels=True,
                        manage_messages=True,
                    ),
                },
                reason="SentriX : vérification renforcée + honeypot depuis +setup",
            )

        verify_channel = guild.get_channel(old["verify_channel_id"]) if old and old["verify_channel_id"] else None
        if not isinstance(verify_channel, discord.TextChannel):
            verify_channel = await guild.create_text_channel(
                "verification",
                category=category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    unverified: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    ),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                },
                reason="SentriX : salon de vérification renforcée",
            )

        trap_channel = guild.get_channel(old["trap_channel_id"]) if old and old["trap_channel_id"] else None
        if not isinstance(trap_channel, discord.TextChannel):
            trap_channel = await guild.create_text_channel(
                "stay-muted",
                category=category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    unverified: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        add_reactions=False,
                    ),
                    verified: discord.PermissionOverwrite(view_channel=False),
                    me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                    ),
                },
                reason="SentriX : salon piège anti-bot",
            )

        rules_channel_id = await rules_flow.rules_channel_id(self.bot, guild.id)
        rules_channel = guild.get_channel(rules_channel_id) if rules_channel_id else None
        excluded_ids = {category.id, verify_channel.id, trap_channel.id}
        if isinstance(rules_channel, discord.TextChannel):
            excluded_ids.add(rules_channel.id)
            try:
                await rules_channel.set_permissions(
                    unverified,
                    view_channel=True,
                    read_message_history=True,
                    send_messages=False,
                    add_reactions=False,
                    create_public_threads=False,
                    create_private_threads=False,
                    reason="SentriX : le règlement doit rester lisible avant la vérification",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Impossible de rendre le règlement visible aux non vérifiés guild=%s.", guild.id)

        await self._lock_existing_channels(
            guild,
            unverified,
            excluded_ids,
        )

        bot_user_id = getattr(getattr(self.bot, "user", None), "id", None)
        await _purge_bot_messages(verify_channel, bot_user_id)
        await _purge_bot_messages(trap_channel, bot_user_id)
        await panels.envoyer(verify_channel, await _web_panel(self.bot, guild))
        await panels.envoyer(
            trap_channel,
            panels.depuis_embed(_trap_embed(verify_channel, sanction)),
        )

        await self.bot.db.execute(
            "INSERT INTO honeypot_verification "
            "(guild_id, enabled, category_id, trap_channel_id, verify_channel_id, "
            "unverified_role_id, verified_role_id, sanction, created_at) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "enabled=1, category_id=excluded.category_id, trap_channel_id=excluded.trap_channel_id, "
            "verify_channel_id=excluded.verify_channel_id, unverified_role_id=excluded.unverified_role_id, "
            "verified_role_id=excluded.verified_role_id, sanction=excluded.sanction",
            (
                guild.id,
                category.id,
                trap_channel.id,
                verify_channel.id,
                unverified.id,
                verified.id,
                sanction,
                int(time.time()),
            ),
        )

        return {
            "category": category,
            "verify": verify_channel,
            "trap": trap_channel,
            "unverified": unverified,
            "verified": verified,
            "sanction": sanction,
        }, None

    async def refresh_existing_panels(self, guild: discord.Guild) -> tuple[dict | None, str | None]:
        """Replace verification/honeypot panels in the channels already configured.

        This method is intentionally non-creative: if a channel was deleted, nothing is
        recreated. It only cleans SentriX messages and publishes one current panel.
        """
        conf = await self.config(guild.id, enabled_only=True)
        if not conf:
            return None, "La vérification renforcée n'est pas active sur ce serveur."

        verify_channel = guild.get_channel(int(conf["verify_channel_id"] or 0))
        trap_channel = guild.get_channel(int(conf["trap_channel_id"] or 0))
        if not isinstance(verify_channel, discord.TextChannel):
            return None, "Le salon de vérification configuré a été supprimé. SentriX ne le recrée pas automatiquement."
        if not isinstance(trap_channel, discord.TextChannel):
            return None, "Le salon stay-muted configuré a été supprimé. SentriX ne le recrée pas automatiquement."

        bot_user_id = getattr(getattr(self.bot, "user", None), "id", None)
        removed_verify = await _purge_bot_messages(verify_channel, bot_user_id)
        removed_trap = await _purge_bot_messages(trap_channel, bot_user_id)

        await panels.envoyer(verify_channel, await _web_panel(self.bot, guild))
        await panels.envoyer(
            trap_channel,
            panels.depuis_embed(_trap_embed(verify_channel, str(conf["sanction"] or "softban"))),
        )
        return {
            "verify": verify_channel,
            "trap": trap_channel,
            "removed_verify_messages": removed_verify,
            "removed_trap_messages": removed_trap,
        }, None

    async def disable_system(self, guild: discord.Guild) -> tuple[bool, str]:
        conf = await self.config(guild.id, enabled_only=False)
        if not conf:
            return True, "Le système était déjà désactivé."

        await self.bot.db.execute(
            "UPDATE honeypot_verification SET enabled = 0 WHERE guild_id = ?",
            (guild.id,),
        )
        await self.bot.db.execute(
            "DELETE FROM honeypot_pending_members WHERE guild_id = ?",
            (guild.id,),
        )

        unverified = guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        if unverified is not None:
            for channel in list(guild.channels):
                try:
                    overwrite = channel.overwrites_for(unverified)
                    if not overwrite.is_empty():
                        await channel.set_permissions(
                            unverified,
                            overwrite=None,
                            reason="SentriX : désactivation vérification/honeypot depuis +setup",
                        )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                await asyncio.sleep(0.03)

            for member in list(unverified.members):
                try:
                    await member.remove_roles(
                        unverified,
                        reason="SentriX : vérification/honeypot désactivé",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                await asyncio.sleep(0.03)

        return True, "Vérification renforcée + salon piège désactivés. Les salons ont été conservés."

    async def start_human_verification(self, interaction: discord.Interaction):
        # V120 : aucune étape de vérification ne se déroule plus dans Discord.
        # Cette méthode reste uniquement pour compatibilité avec d'anciens callbacks.
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Cette vérification fonctionne uniquement dans un serveur.", ephemeral=True
            )
        from web.public_verification_v120 import verification_url
        view = discord.ui.View(timeout=60)
        view.add_item(
            discord.ui.Button(
                label="Se vérifier sur SentriX",
                url=verification_url(interaction.guild.id),
            )
        )
        return await interaction.response.send_message(
            "La vérification complète se fait maintenant sur le site SentriX.",
            view=view,
            ephemeral=True,
        )


        member = interaction.user
        conf = await self.config(interaction.guild.id)
        if not conf:
            return await interaction.response.send_message(
                "Le système de vérification n'est pas activé sur ce serveur.", ephemeral=True
            )

        unverified = interaction.guild.get_role(conf["unverified_role_id"])
        verified = interaction.guild.get_role(conf["verified_role_id"])
        if unverified is None or verified is None:
            return await interaction.response.send_message(
                "La configuration des rôles est incomplète. Préviens un administrateur.", ephemeral=True
            )
        if unverified not in member.roles:
            if verified in member.roles:
                return await interaction.response.send_message('Vous êtes déjà vérifié.', ephemeral=True)
            return await interaction.response.send_message(
                "Votre accès n'est pas marqué comme étant en attente de vérification.", ephemeral=True
            )

        # Le règlement SentriX et la vérification renforcée sont deux systèmes séparés mais
        # chaînés. Si un règlement public existe, la version actuelle doit avoir été acceptée
        # avant de lancer le challenge de sécurité.
        try:
            accepted = await rules_flow.has_accepted_current_rules(self.bot, interaction.guild.id, member.id)
        except Exception:
            logger.exception("Lecture acceptation règlement impossible guild=%s user=%s", interaction.guild.id, member.id)
            accepted = False
        if not accepted:
            rules_channel_id = await rules_flow.rules_channel_id(self.bot, interaction.guild.id)
            rules_channel = interaction.guild.get_channel(rules_channel_id) if rules_channel_id else None
            destination = rules_channel.mention if isinstance(rules_channel, discord.TextChannel) else "le salon du règlement"
            return await interaction.response.send_message(
                f"Lis et accepte d'abord le règlement dans {destination}, puis recommence la vérification.",
                ephemeral=True,
            )

        # Discord Membership Screening : lorsqu'il est activé sur le serveur, Member.pending
        # reste vrai tant que les règles natives Discord n'ont pas été acceptées.
        if bool(getattr(member, "pending", False)):
            return await interaction.response.send_message(
                "⚠️ Vous devez d'abord accepter les **règles Discord du serveur**. Une fois fait, relance la vérification.",
                ephemeral=True,
            )

        account_age = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds()))
        if account_age < MIN_ACCOUNT_AGE_SECONDS:
            wait_seconds = MIN_ACCOUNT_AGE_SECONDS - account_age
            minutes = max(1, (wait_seconds + 59) // 60)
            await self._log(
                interaction.guild,
                "Vérification refusée — compte trop récent",
                f"{member.mention} (`{member.id}`) — compte âgé de seulement {account_age // 60} minute(s).",
                danger=True,
            )
            return await interaction.response.send_message(
                f'🛡️ Votre compte Discord est trop récent pour la vérification automatique. Réessayez dans environ **{minutes} min**.',
                ephemeral=True,
            )

        pending = await self._pending(interaction.guild.id, member.id)
        if not pending:
            await self._mark_pending(interaction.guild.id, member.id)
            pending = await self._pending(interaction.guild.id, member.id)

        joined_at = int(pending["joined_at"] if pending else time.time())
        joined_for = int(time.time()) - joined_at
        if joined_for < MIN_JOIN_DELAY_SECONDS:
            return await interaction.response.send_message(
                f"⏳ Attends encore **{MIN_JOIN_DELAY_SECONDS - joined_for}s** avant de commencer la vérification.",
                ephemeral=True,
            )

        locked = self._seconds_locked(interaction.guild.id, member.id)
        if locked > 0:
            minutes = max(1, (locked + 59) // 60)
            return await interaction.response.send_message(
                f'🔒 Trop de tentatives incorrectes. Réessayez dans environ **{minutes} min**.',
                ephemeral=True,
            )

        key = (interaction.guild.id, member.id)
        now_ts = time.time()
        if now_ts - self._last_start.get(key, 0.0) < START_COOLDOWN_SECONDS:
            return await interaction.response.send_message(
                "⏳ Une vérification vient déjà d'être générée. Attendez quelques secondes.",
                ephemeral=True,
            )
        self._last_start[key] = now_ts

        sequence = tuple(secrets.SystemRandom().sample(VerificationSequenceView.SYMBOLS, 3))
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        left = secrets.randbelow(13) + 3
        right = secrets.randbelow(9) + 2
        math_question = f"{left} + {right} = ?"
        token = secrets.token_urlsafe(18)
        state = ChallengeState(
            token=token,
            guild_id=interaction.guild.id,
            user_id=member.id,
            created_at=now_ts,
            expires_at=now_ts + CHALLENGE_TTL_SECONDS,
            code=code,
            math_answer=str(left + right),
            sequence=sequence,
        )
        self._challenges[key] = state
        view = VerificationSequenceView(self, state, math_question)

        age_days = account_age // 86400
        await interaction.response.send_message(
            (
                f"**Étape 1/2 — challenge anti-automatisation**\nCompte Discord : **{age_days} jour(s)** · règles Discord : **validées**\n\nCliquez dans cet ordre : **{' → '.join(sequence)}**\nEnsuite SentriX ouvrira une seconde vérification avec un code unique et un calcul.\nLe challenge expire dans **{CHALLENGE_TTL_SECONDS // 60} minutes**."
            ),
            view=view,
            ephemeral=True,
        )

    async def complete_human_challenge(
        self,
        interaction: discord.Interaction,
        token: str,
        typed_code: str,
        typed_math: str,
    ):
        # Les anciens modals persistants peuvent encore être soumis quelques instants après
        # un déploiement. Ils ne doivent jamais attribuer le rôle : on renvoie vers le web.
        del token, typed_code, typed_math
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Vérification invalide.", ephemeral=True)
        from web.public_verification_v120 import verification_url
        view = discord.ui.View(timeout=60)
        view.add_item(
            discord.ui.Button(
                label="Ouvrir la vérification SentriX",
                url=verification_url(interaction.guild.id),
            )
        )
        return await interaction.response.send_message(
            "Cette ancienne vérification Discord n'est plus utilisée. Continue sur le site SentriX.",
            view=view,
            ephemeral=True,
        )


        key = (interaction.guild.id, interaction.user.id)
        state = self._challenges.get(key)
        if (
            state is None
            or state.token != token
            or state.guild_id != interaction.guild.id
            or state.user_id != interaction.user.id
            or time.time() > state.expires_at
            or not state.sequence_done
        ):
            self._challenges.pop(key, None)
            return await interaction.response.send_message(
                '⌛ Challenge expiré ou invalide. Recommencez depuis le panneau de vérification.',
                ephemeral=True,
            )

        normalized_code = typed_code.strip().upper()
        normalized_math = typed_math.strip()
        if normalized_code != state.code or normalized_math != state.math_answer:
            await self._record_failure(interaction.guild.id, interaction.user.id)
            self._challenges.pop(key, None)
            locked = self._seconds_locked(interaction.guild.id, interaction.user.id)
            if locked:
                text = "❌ Réponse incorrecte. Trop d'échecs : vérification temporairement verrouillée."
            else:
                text = "❌ Code ou calcul incorrect. Recommence depuis **Commencer la vérification**."
            return await interaction.response.send_message(text, ephemeral=True)

        # Revalidation finale : aucune information du premier clic n'est considérée comme
        # suffisante. On vérifie de nouveau l'état Discord et les rôles juste avant l'accès.
        conf = await self.config(interaction.guild.id)
        if not conf:
            self._challenges.pop(key, None)
            return await interaction.response.send_message("La vérification a été désactivée.", ephemeral=True)

        member = interaction.user
        if bool(getattr(member, "pending", False)):
            self._challenges.pop(key, None)
            return await interaction.response.send_message(
                '⚠️ Les règles Discord du serveur ne sont plus validées. Acceptez-les puis recommencez.',
                ephemeral=True,
            )

        # Le règlement peut être modifié pendant qu'un challenge est ouvert. On revalide la
        # version juste avant d'accorder l'accès pour qu'une ancienne acceptation ne suffise
        # jamais après une mise à jour des règles.
        try:
            accepted = await rules_flow.has_accepted_current_rules(self.bot, interaction.guild.id, member.id)
        except Exception:
            accepted = False
        if not accepted:
            self._challenges.pop(key, None)
            rules_channel_id = await rules_flow.rules_channel_id(self.bot, interaction.guild.id)
            rules_channel = interaction.guild.get_channel(rules_channel_id) if rules_channel_id else None
            destination = rules_channel.mention if isinstance(rules_channel, discord.TextChannel) else "le salon du règlement"
            return await interaction.response.send_message(
                f"Le règlement a changé ou n'a pas encore été accepté. Retourne dans {destination}, accepte-le, puis recommence.",
                ephemeral=True,
            )

        unverified = interaction.guild.get_role(conf["unverified_role_id"])
        verified = interaction.guild.get_role(conf["verified_role_id"])
        pending = await self._pending(interaction.guild.id, member.id)
        if unverified is None or verified is None or unverified not in member.roles or not pending:
            self._challenges.pop(key, None)
            return await interaction.response.send_message(
                "La session de vérification n'est plus cohérente. Recommencez depuis le panneau.",
                ephemeral=True,
            )

        account_age = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds()))
        if account_age < MIN_ACCOUNT_AGE_SECONDS:
            self._challenges.pop(key, None)
            return await interaction.response.send_message(
                'Votre compte est encore trop récent pour être validé.', ephemeral=True
            )

        self._verification_in_progress.add(key)
        try:
            if verified not in member.roles:
                await member.add_roles(verified, reason="SentriX : vérification renforcée réussie")
            if unverified in member.roles:
                await member.remove_roles(unverified, reason="SentriX : vérification renforcée réussie")
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message(
                'SentriX ne peut pas modifier vos rôles. Préviens un administrateur.', ephemeral=True
            )
        finally:
            self._verification_in_progress.discard(key)

        await self._clear_pending(interaction.guild.id, member.id)
        await self.bot.db.execute(
            "INSERT INTO honeypot_verified_members "
            "(guild_id, user_id, verified_at, method, account_age_seconds) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET verified_at=excluded.verified_at, "
            "method=excluded.method, account_age_seconds=excluded.account_age_seconds",
            (
                interaction.guild.id,
                member.id,
                int(time.time()),
                "membership_screening+sequence+code+math",
                account_age,
            ),
        )
        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO verified_users (guild_id, user_id, verified_at) "
                "VALUES (?, ?, strftime('%s','now'))",
                (interaction.guild.id, member.id),
            )
        except Exception:
            logger.warning("Étape non critique ignorée dans complete_human_challenge", exc_info=True)

        self._challenges.pop(key, None)
        self._failures.pop(key, None)
        self._lock_until.pop(key, None)

        elapsed = max(1, int(time.time() - state.created_at))
        await interaction.response.send_message(
            "✅ **Vérification complète réussie.** Votre accès au serveur vient d'être débloqué.",
            ephemeral=True,
        )
        await self._log(
            interaction.guild,
            "Membre vérifié — contrôle renforcé réussi",
            (
                f"{member.mention} (`{member.id}`)\n"
                f"Compte âgé de : **{account_age // 86400} jour(s)**\n"
                f"Challenge terminé en : **{elapsed}s**\n"
                "Contrôles : règlement SentriX courant + Membership Screening + séquence + code unique + calcul."
            ),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        conf = await self.config(member.guild.id)
        if not conf:
            return
        unverified = member.guild.get_role(conf["unverified_role_id"])
        if unverified is None:
            return

        # Chaque nouvelle entrée exige une nouvelle vérification, même si le membre avait
        # déjà été vérifié lors d'un précédent passage sur le serveur.
        await self._mark_pending(member.guild.id, member.id, int(time.time()))
        try:
            await member.add_roles(
                unverified,
                reason="SentriX : vérification complète obligatoire à l'arrivée",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible d'ajouter Non vérifié à %s sur %s.", member.id, member.guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            await self._clear_pending(member.guild.id, member.id)
        except Exception:
            logger.warning("Étape non critique ignorée dans on_member_remove", exc_info=True)
        key = (member.guild.id, member.id)
        self._challenges.pop(key, None)
        self._last_start.pop(key, None)
        self._failures.pop(key, None)
        self._lock_until.pop(key, None)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        key = (after.guild.id, after.id)
        if key in self._verification_in_progress:
            return
        conf = await self.config(after.guild.id)
        if not conf:
            return
        pending = await self._pending(after.guild.id, after.id)
        if not pending:
            return

        unverified = after.guild.get_role(conf["unverified_role_id"])
        verified = after.guild.get_role(conf["verified_role_id"])
        if unverified is None or verified is None:
            return

        # Tant que la DB dit "en attente", aucun retrait manuel du rôle bloquant ni ajout
        # du rôle Vérifié ne doit contourner le portail SentriX.
        try:
            if verified in after.roles:
                await after.remove_roles(verified, reason="SentriX : vérification non terminée")
            if unverified not in after.roles:
                await after.add_roles(unverified, reason="SentriX : vérification non terminée")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible de restaurer l'état Non vérifié de %s.", after.id)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        """Un salon créé après le setup ne doit jamais devenir une porte de contournement."""
        conf = await self.config(channel.guild.id)
        if not conf:
            return
        excluded = {
            int(conf["category_id"] or 0),
            int(conf["verify_channel_id"] or 0),
            int(conf["trap_channel_id"] or 0),
        }
        rules_channel_id = await rules_flow.rules_channel_id(self.bot, channel.guild.id)
        if rules_channel_id:
            excluded.add(int(rules_channel_id))
        if channel.id in excluded:
            return
        unverified = channel.guild.get_role(conf["unverified_role_id"])
        if unverified is None:
            return
        try:
            await channel.set_permissions(
                unverified,
                overwrite=self._unverified_overwrite(),
                reason="SentriX : nouveau salon inaccessible avant vérification",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible de verrouiller le nouveau salon %s.", channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.guild is None
            or message.author.bot
            or not isinstance(message.author, discord.Member)
        ):
            return

        conf = await self.config(message.guild.id)
        if not conf or message.channel.id != conf["trap_channel_id"]:
            return

        member = message.author
        if member.id == message.guild.owner_id or member.guild_permissions.administrator:
            return

        unverified = message.guild.get_role(conf["unverified_role_id"])
        if unverified is None or unverified not in member.roles:
            return

        lock_key = (message.guild.id, member.id)
        if lock_key in self._trap_locks:
            return
        self._trap_locks.add(lock_key)

        try:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            sanction = str(conf["sanction"] or "softban")
            action_label = "aucune sanction appliquée"

            if sanction == "kick":
                try:
                    await member.kick(reason="SentriX honeypot : message envoyé dans le salon piège")
                    action_label = "expulsé automatiquement"
                except (discord.Forbidden, discord.HTTPException):
                    action_label = "expulsion impossible (permissions/hiérarchie)"
            else:
                try:
                    await message.guild.ban(
                        member,
                        reason="SentriX honeypot : compte automatisé suspecté",
                        delete_message_seconds=0,
                    )
                    await asyncio.sleep(1.0)
                    await message.guild.unban(
                        discord.Object(id=member.id),
                        reason="SentriX honeypot : fin du softban automatique",
                    )
                    action_label = "softban automatique"
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    action_label = "softban impossible (permissions/hiérarchie)"

            try:
                await self.bot.db.record_sanction(
                    message.guild.id,
                    member.id,
                    self.bot.user.id if self.bot.user else 0,
                    "honeypot_kick" if sanction == "kick" else "honeypot_softban",
                    "Message envoyé dans le salon piège anti-bot SentriX",
                )
            except Exception:
                logger.warning("Étape non critique ignorée dans on_message", exc_info=True)

            await self._log(
                message.guild,
                "Honeypot déclenché",
                (
                    f"Compte : {member.mention} (`{member.id}`)\n"
                    f"Salon : {message.channel.mention}\n"
                    f"Action : **{action_label}**\n"
                    "Raison : message envoyé dans le salon piège anti-bot."
                ),
                danger=True,
            )
        finally:
            self._trap_locks.discard(lock_key)


async def _patch_setup_when_available(bot: commands.Bot) -> None:
    """Attend Configuration puis injecte la vérification renforcée dans +setup > Sécurité."""
    for _ in range(240):
        if bot.get_cog("Configuration") is not None:
            break
        await asyncio.sleep(0.5)
    else:
        logger.warning("Configuration non chargée : intégration vérification +setup reportée.")
        return

    try:
        from cogs import configuration as configuration_module
    except Exception:
        logger.exception("Impossible d'importer cogs.configuration pour la vérification.")
        return

    setup_cls = getattr(configuration_module, "SetupView", None)
    steps = getattr(configuration_module, "SETUP_STEPS", None)
    if setup_cls is None or not steps:
        logger.warning("SetupView/SETUP_STEPS introuvable pour l'intégration vérification.")
        return
    if getattr(setup_cls, "_sentrix_honeypot_setup_v50", False):
        return

    original_render_page = setup_cls.render_page
    original_build_embed = setup_cls.build_embed

    def render_page_with_honeypot(self):
        original_render_page(self)
        if self.page == -1:
            return
        try:
            step = configuration_module.SETUP_STEPS[self.page]
        except Exception:
            return
        if step.get("key") != "security":
            return

        menu = discord.ui.Select(
            placeholder="Vérification web + honeypot",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Activer — Web + Softban",
                    description="Site SentriX + CAPTCHA + softban du honeypot.",
                    value="enable_softban",
                ),
                discord.SelectOption(
                    label="Activer — Web + Expulsion",
                    description="Site SentriX + CAPTCHA + kick du honeypot.",
                    value="enable_kick",
                ),
                discord.SelectOption(
                    label="Désactiver",
                    description='Désactivez le portail et libère les membres en attente.',
                    value="disable",
                ),
            ],
            row=3,
        )

        async def callback(interaction: discord.Interaction):
            honeypot = self.bot.get_cog(_COG_NAME)
            if honeypot is None:
                return await interaction.response.send_message(
                    "Le module de vérification renforcée n'est pas chargé.", ephemeral=True
                )
            if not interaction.guild:
                return await interaction.response.send_message(
                    "Cette option fonctionne uniquement dans un serveur.", ephemeral=True
                )

            value = menu.values[0] if menu.values else ""
            await interaction.response.defer(ephemeral=True, thinking=True)

            if value == "disable":
                _ok, message = await honeypot.disable_system(interaction.guild)
                try:
                    await self.bot.db.log_setup_history(
                        self.guild_id,
                        interaction.user.id,
                        "Sécurité",
                        "vérification web + honeypot désactivés",
                        new_value="off",
                    )
                except Exception:
                    logger.warning("Étape non critique ignorée dans callback", exc_info=True)
                self.render_page()
                await self._refresh_message(interaction)
                return await interaction.followup.send(message, ephemeral=True)

            sanction = "kick" if value == "enable_kick" else "softban"
            current_conf = await honeypot.config(interaction.guild.id, enabled_only=False)
            if current_conf and current_conf["enabled"]:
                # Mise à jour d'un système actif : ne recrée jamais un salon/catégorie
                # supprimé. On change le réglage puis on remplace uniquement les panels
                # dans les deux salons encore existants.
                await self.bot.db.execute(
                    "UPDATE honeypot_verification SET sanction=? WHERE guild_id=?",
                    (sanction, interaction.guild.id),
                )
                result, error = await honeypot.refresh_existing_panels(interaction.guild)
                action_label = "vérification web mise à jour"
            else:
                # Seule une activation explicite d'un système inactif peut créer la
                # structure initiale.
                result, error = await honeypot.create_or_refresh_system(
                    interaction.guild,
                    sanction=sanction,
                )
                action_label = "vérification web activée"

            if error:
                return await interaction.followup.send(f"⚠️ {error}", ephemeral=True)

            try:
                await self.bot.db.log_setup_history(
                    self.guild_id,
                    interaction.user.id,
                    "Sécurité",
                    action_label,
                    new_value=sanction,
                )
            except Exception:
                logger.warning("Étape non critique ignorée dans callback", exc_info=True)

            self.security_touched = True
            self.render_page()
            await self._refresh_message(interaction)
            await interaction.followup.send(
                (
                    f"**{action_label.capitalize()}.**\n"
                    f"Portail : {result['verify'].mention}\n"
                    f"Piège : {result['trap'].mention}\n"
                    f"Sanction honeypot : **{'Softban' if sanction == 'softban' else 'Expulsion'}**\n"
                    "Accès : OAuth Discord + règlement + contrôle du compte + CAPTCHA web + calcul. "
                    "Une mise à jour ne crée aucun nouveau salon."
                ),
                ephemeral=True,
            )

        menu.callback = callback
        try:
            self.add_item(menu)
        except ValueError:
            logger.warning("Impossible d'ajouter la vérification renforcée à +setup : composants pleins.")

    async def build_embed_with_honeypot(self):
        embed = await original_build_embed(self)
        if self.page == -1:
            return embed
        try:
            step = configuration_module.SETUP_STEPS[self.page]
        except Exception:
            return embed
        if step.get("key") != "security":
            return embed

        honeypot = self.bot.get_cog(_COG_NAME)
        if honeypot is None:
            return embed
        conf = await honeypot.config(self.guild_id, enabled_only=False)
        if not conf or not conf["enabled"]:
            value = "○ Désactivée"
        else:
            verify = f"<#{conf['verify_channel_id']}>" if conf["verify_channel_id"] else "introuvable"
            trap = f"<#{conf['trap_channel_id']}>" if conf["trap_channel_id"] else "introuvable"
            sanction = "Softban" if str(conf["sanction"]) == "softban" else "Expulsion"
            value = (
                f"● **Web** — Honeypot : **{sanction}**\n"
                f"Vérification : {verify}\n"
                f"Salon piège : {trap}\n"
                "Contrôles : OAuth Discord + règlement + âge du compte + CAPTCHA web + calcul"
            )
        embed.add_field(name="🔐 Vérification d'accès", value=value, inline=False)
        return embed

    setup_cls.render_page = render_page_with_honeypot
    setup_cls.build_embed = build_embed_with_honeypot
    setup_cls._sentrix_honeypot_setup_v50 = True
    logger.info("Vérification renforcée V50 intégrée dans +setup > Sécurité.")


async def _has_sentrix_panel(
    channel: discord.TextChannel | None,
    bot_user_id: int | None,
    *,
    title_contains: str,
) -> bool:
    if not isinstance(channel, discord.TextChannel) or not bot_user_id:
        return False
    expected = str(title_contains or "").casefold()
    try:
        async for message in channel.history(limit=20):
            if getattr(message.author, "id", None) != bot_user_id:
                continue
            for embed in getattr(message, "embeds", ()):
                if expected in str(getattr(embed, "title", "") or "").casefold():
                    return True
    except (discord.Forbidden, discord.HTTPException):
        return False
    return False


async def _channel_is_bot_only(channel: discord.TextChannel, bot_user_id: int | None) -> bool:
    """Only delete duplicate channels when recent history is empty or entirely SentriX-owned."""
    if not bot_user_id:
        return False
    try:
        messages = [message async for message in channel.history(limit=60)]
    except (discord.Forbidden, discord.HTTPException):
        return False
    return all(getattr(message.author, "id", None) == bot_user_id for message in messages)


async def _cleanup_spam_verification_channels(bot: commands.Bot) -> None:
    """One-time cleanup for duplicate channels created by the old verification spam bug.

    Current configured channel/category IDs are always preserved. Extra channels are
    deleted only when they live under a SentriX verification category, use the exact
    verification/stay-muted names and contain no user messages.
    """
    await bot.wait_until_ready()
    await bot.db.execute(_MIGRATION_SCHEMA)
    done = await bot.db.fetchone(
        "SELECT applied_at FROM sentrix_runtime_migrations WHERE name=?",
        (_WEB_CLEANUP_MIGRATION,),
    )
    if done:
        return

    cog = bot.get_cog(_COG_NAME)
    if cog is None:
        return
    bot_user_id = getattr(getattr(bot, "user", None), "id", None)
    deleted_channels = 0
    deleted_categories = 0
    failures = 0

    for guild in list(bot.guilds):
        try:
            conf = await cog.config(guild.id, enabled_only=False)
            keep_ids = set()
            if conf:
                for key in ("category_id", "verify_channel_id", "trap_channel_id"):
                    raw = conf[key]
                    if raw:
                        keep_ids.add(int(raw))

            for channel in list(guild.text_channels):
                if channel.id in keep_ids:
                    continue
                if channel.name.casefold() not in {"verification", "stay-muted"}:
                    continue
                category = channel.category
                category_name = (getattr(category, "name", "") or "").casefold()
                if "sentrix" not in category_name or (
                    "vérification" not in category_name and "verification" not in category_name
                ):
                    continue
                if not await _channel_is_bot_only(channel, bot_user_id):
                    logger.warning(
                        "Canal doublon conservé guild=%s channel=%s : messages utilisateur présents.",
                        guild.id,
                        channel.id,
                    )
                    continue
                try:
                    await channel.delete(
                        reason="SentriX V120 : nettoyage d'un doublon de vérification créé par l'ancien bug"
                    )
                    deleted_channels += 1
                except (discord.Forbidden, discord.HTTPException):
                    failures += 1
                await asyncio.sleep(0.08)

            for category in list(guild.categories):
                if category.id in keep_ids:
                    continue
                name = category.name.casefold()
                if "sentrix" not in name or (
                    "vérification" not in name and "verification" not in name
                ):
                    continue
                if category.channels:
                    continue
                try:
                    await category.delete(
                        reason="SentriX V120 : suppression d'une catégorie de vérification doublon vide"
                    )
                    deleted_categories += 1
                except (discord.Forbidden, discord.HTTPException):
                    failures += 1
                await asyncio.sleep(0.08)
        except Exception:
            failures += 1
            logger.exception("Nettoyage vérification V120 impossible guild=%s.", guild.id)

    if failures == 0:
        await bot.db.execute(
            "INSERT INTO sentrix_runtime_migrations(name,applied_at) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET applied_at=excluded.applied_at",
            (_WEB_CLEANUP_MIGRATION, int(time.time())),
        )
    logger.warning(
        "Nettoyage vérification V120 : %s salon(s), %s catégorie(s) doublon supprimés, %s échec(s).",
        deleted_channels,
        deleted_categories,
        failures,
    )


async def _repair_enabled_systems(bot: commands.Bot) -> None:
    """Replace panels only in already-existing active verification channels.

    No channel, category or role is ever created from this startup task. If an admin
    deleted one of the configured channels, SentriX leaves the server untouched.
    """
    await bot.wait_until_ready()
    cog = bot.get_cog(_COG_NAME)
    if cog is None:
        return

    for guild in list(bot.guilds):
        try:
            conf = await cog.config(guild.id, enabled_only=True)
            if not conf:
                continue
            verify_channel = guild.get_channel(int(conf["verify_channel_id"] or 0))
            trap_channel = guild.get_channel(int(conf["trap_channel_id"] or 0))
            if not isinstance(verify_channel, discord.TextChannel) or not isinstance(
                trap_channel, discord.TextChannel
            ):
                logger.info(
                    "V120 : vérification active mais salon supprimé guild=%s ; aucune recréation.",
                    guild.id,
                )
                continue

            result, error = await cog.refresh_existing_panels(guild)
            if error:
                logger.warning("V120 : panel non actualisé guild=%s : %s", guild.id, error)
            else:
                logger.info(
                    "V120 : ancien(s) panel(s) remplacé(s) par un seul panel web guild=%s "
                    "(verify=%s trap=%s).",
                    guild.id,
                    result["removed_verify_messages"],
                    result["removed_trap_messages"],
                )
            await asyncio.sleep(0.2)
        except Exception:
            logger.exception("Actualisation panel web impossible guild=%s.", guild.id)


async def install(bot: commands.Bot) -> None:
    """Installe le runtime sans créer aucune nouvelle commande publique."""
    if getattr(bot, "_sentrix_honeypot_verification_v50", False):
        return

    await bot.db.execute(_SCHEMA)
    await bot.db.execute(_PENDING_SCHEMA)
    await bot.db.execute(_VERIFIED_SCHEMA)
    await bot.db.execute(_MIGRATION_SCHEMA)

    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(HoneypotVerification(bot))

    if not getattr(bot, "_sentrix_honeypot_verify_view_registered", False):
        bot.add_view(HoneypotVerifyView())
        bot._sentrix_honeypot_verify_view_registered = True

    task = asyncio.create_task(_patch_setup_when_available(bot))
    bot._sentrix_honeypot_setup_task = task
    if not getattr(bot, "_sentrix_honeypot_repair_task_started", False):
        bot._sentrix_honeypot_repair_task_started = True
        bot._sentrix_honeypot_repair_task = asyncio.create_task(
            _repair_enabled_systems(bot),
            name="sentrix-honeypot-repair",
        )
    if not getattr(bot, "_sentrix_honeypot_cleanup_v120_started", False):
        bot._sentrix_honeypot_cleanup_v120_started = True
        bot._sentrix_honeypot_cleanup_v120_task = asyncio.create_task(
            _cleanup_spam_verification_channels(bot),
            name="sentrix-honeypot-cleanup-v120",
        )
    bot._sentrix_honeypot_verification_v50 = True
    logger.info("Vérification renforcée V50 chargée ; configuration via +setup uniquement.")
