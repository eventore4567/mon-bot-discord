from __future__ import annotations

import logging
import secrets
import string
import time

import discord

from utils import sentrix_panels as panels

from . import honeypot_verification_v48 as legacy

logger = logging.getLogger("bot.security.verification-polish-v51")
_PATCHED = False


def _brand_avatar(bot) -> str | None:
    try:
        if bot.user:
            return str(bot.user.display_avatar.url)
    except Exception:
        pass
    return None


def _panel_embed(bot, guild: discord.Guild) -> discord.Embed:
    ref = f"SX-{guild.id % 1_000_000:06d}"
    embed = discord.Embed(
        title="🔐 PASSERELLE DE VÉRIFICATION",
        description=(
            "### Accès temporairement verrouillé\nPour protéger le serveur contre les **bots, raids et comptes automatisés**, SentriX doit valider votre accès avant d'ouvrir les salons.\n\n> **Un simple clic ne donne jamais accès au serveur.**"
        ),
        colour=0x5865F2,
    )
    avatar = _brand_avatar(bot)
    if avatar:
        embed.set_author(name="SentriX • Security Gateway", icon_url=avatar)
        embed.set_thumbnail(url=avatar)
    else:
        embed.set_author(name="SentriX • Security Gateway")

    embed.add_field(
        name="🛡️ CONTRÔLES",
        value=(
            "• règles Discord / Membership Screening\n"
            "• ancienneté minimale du compte\n"
            "• séquence interactive anti-automatisation\n"
            "• code unique + calcul à usage unique\n"
            "• détection des tentatives répétées"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 ACCÈS",
        value=(
            "Les salons normaux restent **inaccessibles** avec le rôle `Non vérifié`.\n"
            "Le rôle `Vérifié` est attribué **uniquement après réussite complète**."
        ),
        inline=False,
    )
    embed.add_field(
        name="⏱️ SESSION",
        value="Challenge valable **2 minutes** • nouvelle vérification requise après une nouvelle arrivée.",
        inline=False,
    )
    embed.set_footer(text=f"SentriX • Protection active • Référence {ref}")
    return embed


def _trap_embed(bot, verify_channel: discord.TextChannel, sanction: str) -> discord.Embed:
    action = "softban automatique" if sanction == "softban" else "expulsion automatique"
    embed = discord.Embed(
        title="🚨 SALON PIÈGE — NE PAS ÉCRIRE ICI",
        description=(
            "Ce salon est un **honeypot anti-bot**. Il sert à détecter les comptes automatisés "
            "qui publient dans tous les salons sans lire les avertissements.\n\n"
            f"Tout message envoyé ici par un membre non vérifié peut déclencher un **{action}**.\n\n"
            f"➡️ Pour accéder au serveur, utilise uniquement {verify_channel.mention}."
        ),
        colour=0xED4245,
    )
    avatar = _brand_avatar(bot)
    if avatar:
        embed.set_author(name="SentriX • Anti-Bot Honeypot", icon_url=avatar)
    embed.set_footer(text="SentriX • Security Gateway • Honeypot actif")
    return embed


def _info_embed() -> discord.Embed:
    embed = discord.Embed(
        title="ℹ️ Comment fonctionne la vérification ?",
        description=(
            "1. SentriX vérifie l'état Discord du compte.\n2. Vous reproduisez une **séquence aléatoire**.\n3. Un formulaire demande un **code unique** et un **petit calcul**.\n4. SentriX recontrôle vos rôles et votre état juste avant l'ouverture du serveur.\n\nAucune étape seule ne suffit pour obtenir l'accès."
        ),
        colour=0x5865F2,
    )
    embed.set_footer(text="SentriX • Vérification renforcée")
    return embed


def _status_embed(title: str, description: str, *, state: str = "info") -> discord.Embed:
    colours = {
        "ok": 0x57F287,
        "error": 0xED4245,
        "warn": 0xFEE75C,
        "info": 0x5865F2,
    }
    icons = {
        "ok": "✅",
        "error": "❌",
        "warn": "⚠️",
        "info": "🔐",
    }
    embed = discord.Embed(
        title=f"{icons.get(state, '🔐')} {title}",
        description=description,
        colour=colours.get(state, 0x5865F2),
    )
    embed.set_footer(text="SentriX • Security Gateway")
    return embed


def _challenge_embed(state: legacy.ChallengeState, account_age_days: int, position: int = 0) -> discord.Embed:
    progress = "●" * position + "○" * (len(state.sequence) - position)
    embed = discord.Embed(
        title="🧩 Étape 1/2 — Challenge anti-automatisation",
        description=(
            f"Compte Discord : **{account_age_days} jour(s)** • règles Discord : **validées**\n\n"
            f"### Ordre à reproduire\n**{'  →  '.join(state.sequence)}**\n\n"
            f"Progression : `{progress}`\n\n"
            "Après cette séquence, SentriX ouvrira automatiquement l'étape **code unique + calcul**."
        ),
        colour=0x5865F2,
    )
    embed.set_footer(text=f"Expire dans {legacy.CHALLENGE_TTL_SECONDS // 60} minutes • SentriX")
    return embed


class StyledSequenceButton(discord.ui.Button):
    def __init__(self, symbol: str):
        super().__init__(label=symbol, style=discord.ButtonStyle.secondary)
        self.symbol = symbol

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, StyledSequenceView):
            await view.press(interaction, self.symbol)


class StyledSequenceView(discord.ui.View):
    def __init__(self, cog, state: legacy.ChallengeState, math_question: str, account_age_days: int):
        super().__init__(timeout=legacy.CHALLENGE_TTL_SECONDS)
        self.cog = cog
        self.state = state
        self.math_question = math_question
        self.account_age_days = account_age_days
        self.position = 0

        symbols = list(legacy.VerificationSequenceView.SYMBOLS)
        secrets.SystemRandom().shuffle(symbols)
        for symbol in symbols:
            self.add_item(StyledSequenceButton(symbol))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.state.user_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Challenge réservé', 'Cette vérification appartient à un autre membre.', state='error')), ephemere=True)
            return False
        if interaction.guild is None or interaction.guild.id != self.state.guild_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Session invalide', 'Cette session ne correspond plus au serveur.', state='error')), ephemere=True)
            return False
        return True

    async def press(self, interaction: discord.Interaction, symbol: str):
        current = self.cog._challenges.get((self.state.guild_id, self.state.user_id))
        if current is None or current.token != self.state.token or time.time() > current.expires_at:
            self.stop()
            return await panels.editer(interaction.response, panels.depuis_embed(_status_embed('Session expirée', 'Cliquez de nouveau sur **Commencer** dans le panneau de vérification.', state='warn')))

        expected = current.sequence[self.position]
        if symbol != expected:
            await self.cog._record_failure(self.state.guild_id, self.state.user_id)
            self.cog._challenges.pop((self.state.guild_id, self.state.user_id), None)
            for child in self.children:
                child.disabled = True
            self.stop()
            return await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(_status_embed('Ordre incorrect', 'La tentative a été annulée. Utilisez **Relancer** pour obtenir un nouveau challenge.', state='error')), self))

        self.position += 1
        if self.position < len(current.sequence):
            return await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(_challenge_embed(current, self.account_age_days, self.position)), self))

        current.sequence_done = True
        self.stop()
        await interaction.response.send_modal(legacy.VerificationModal(self.cog, current, self.math_question))


class VerificationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Commencer",
        emoji="🔐",
        style=discord.ButtonStyle.primary,
        custom_id="sentrix:verification:v51:start",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog(legacy._COG_NAME)
        if cog is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Service indisponible', "La vérification SentriX n'est pas chargée pour le moment.", state='error')), ephemere=True)
        await cog.start_human_verification(interaction)

    @discord.ui.button(
        label="Relancer",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:verification:v51:restart",
    )
    async def restart(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog(legacy._COG_NAME)
        if cog is None or interaction.guild is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Impossible de relancer', 'La vérification est indisponible.', state='error')), ephemere=True)
        key = (interaction.guild.id, interaction.user.id)
        cog._challenges.pop(key, None)
        cog._last_start.pop(key, None)
        await cog.start_human_verification(interaction)

    @discord.ui.button(
        label="Comment ça marche ?",
        emoji="ℹ️",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:verification:v51:help",
    )
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await panels.envoyer(interaction.response, panels.depuis_embed(_info_embed()), ephemere=True)


async def _patched_start(self, interaction: discord.Interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Serveur requis', 'Cette vérification fonctionne uniquement dans un serveur.', state='error')), ephemere=True)

    guild = interaction.guild
    member = interaction.user
    conf = await self.config(guild.id)
    if not conf:
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Vérification désactivée', "Le portail n'est pas activé sur ce serveur.", state='warn')), ephemere=True)

    unverified = guild.get_role(conf["unverified_role_id"])
    verified = guild.get_role(conf["verified_role_id"])
    if unverified is None or verified is None:
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Configuration incomplète', 'Les rôles de vérification sont introuvables. Préviens un administrateur.', state='error')), ephemere=True)

    if verified in member.roles and unverified not in member.roles:
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Déjà vérifié', 'Votre accès au serveur est déjà validé.', state='ok')), ephemere=True)

    pending = await self._pending(guild.id, member.id)
    if unverified not in member.roles:
        try:
            await member.add_roles(unverified, reason="SentriX : démarrage manuel de la vérification")
        except (discord.Forbidden, discord.HTTPException):
            return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Rôle impossible à appliquer', 'SentriX ne peut pas placer votre compte en attente. Vérifiez la hiérarchie des rôles.', state='error')), ephemere=True)
    if not pending:
        await self._mark_pending(
            guild.id,
            member.id,
            int(time.time()) - legacy.MIN_JOIN_DELAY_SECONDS,
        )
        pending = await self._pending(guild.id, member.id)

    if bool(getattr(member, "pending", False)):
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Règles Discord requises', "Acceptez d'abord les **règles du serveur Discord**, puis relancez la vérification.", state='warn')), ephemere=True)

    account_age = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds()))
    if account_age < legacy.MIN_ACCOUNT_AGE_SECONDS:
        wait_seconds = legacy.MIN_ACCOUNT_AGE_SECONDS - account_age
        minutes = max(1, (wait_seconds + 59) // 60)
        await self._log(
            guild,
            "Vérification refusée — compte trop récent",
            f"{member.mention} (`{member.id}`) — compte âgé de seulement {account_age // 60} minute(s).",
            danger=True,
        )
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Compte trop récent', f'Réessayez dans environ **{minutes} min**. Cette limite réduit les comptes de raid jetables.', state='warn')), ephemere=True)

    joined_at = int(pending["joined_at"] if pending else time.time())
    joined_for = int(time.time()) - joined_at
    if joined_for < legacy.MIN_JOIN_DELAY_SECONDS:
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Patientez quelques secondes', f'Vous pourrez commencer dans **{legacy.MIN_JOIN_DELAY_SECONDS - joined_for}s**.', state='info')), ephemere=True)

    locked = self._seconds_locked(guild.id, member.id)
    if locked > 0:
        minutes = max(1, (locked + 59) // 60)
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Vérification temporairement verrouillée', f'Trop de tentatives incorrectes. Réessayez dans environ **{minutes} min**.', state='error')), ephemere=True)

    key = (guild.id, member.id)
    now_ts = time.time()
    if now_ts - self._last_start.get(key, 0.0) < legacy.START_COOLDOWN_SECONDS:
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Challenge déjà généré', "Une session vient d'être créée. Utilisez-la ou attendez quelques secondes avant de relancer.", state='info')), ephemere=True)
    self._last_start[key] = now_ts

    sequence = tuple(secrets.SystemRandom().sample(legacy.VerificationSequenceView.SYMBOLS, 3))
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    left = secrets.randbelow(13) + 3
    right = secrets.randbelow(9) + 2
    math_question = f"{left} + {right} = ?"
    token = secrets.token_urlsafe(18)
    state = legacy.ChallengeState(
        token=token,
        guild_id=guild.id,
        user_id=member.id,
        created_at=now_ts,
        expires_at=now_ts + legacy.CHALLENGE_TTL_SECONDS,
        code=code,
        math_answer=str(left + right),
        sequence=sequence,
    )
    self._challenges[key] = state
    age_days = account_age // 86400
    view = StyledSequenceView(self, state, math_question, age_days)
    await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(_challenge_embed(state, age_days, 0)), view), ephemere=True)


async def _patched_complete(self, interaction, token: str, typed_code: str, typed_math: str):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Session invalide', 'Impossible de valider cette vérification.', state='error')), ephemere=True)

    guild = interaction.guild
    member = interaction.user
    key = (guild.id, member.id)
    state = self._challenges.get(key)
    if (
        state is None
        or state.token != token
        or state.guild_id != guild.id
        or state.user_id != member.id
        or time.time() > state.expires_at
        or not state.sequence_done
    ):
        self._challenges.pop(key, None)
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Challenge expiré', "La session n'est plus valide. Recommencez depuis le panneau de vérification.", state='warn')), ephemere=True)

    if typed_code.strip().upper() != state.code or typed_math.strip() != state.math_answer:
        await self._record_failure(guild.id, member.id)
        self._challenges.pop(key, None)
        locked = self._seconds_locked(guild.id, member.id)
        if locked:
            description = "Réponse incorrecte. Trop d'échecs : la vérification est temporairement verrouillée."
        else:
            description = "Le code ou le calcul est incorrect. Utilise **Relancer** et recommence."
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Réponse incorrecte', description, state='error')), ephemere=True)

    conf = await self.config(guild.id)
    if not conf:
        self._challenges.pop(key, None)
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Vérification désactivée', 'Le portail a été désactivé pendant votre session.', state='warn')), ephemere=True)

    if bool(getattr(member, "pending", False)):
        self._challenges.pop(key, None)
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Règles Discord non validées', 'Acceptez les règles natives Discord puis recommencez.', state='warn')), ephemere=True)

    unverified = guild.get_role(conf["unverified_role_id"])
    verified = guild.get_role(conf["verified_role_id"])
    pending = await self._pending(guild.id, member.id)
    if unverified is None or verified is None or unverified not in member.roles or not pending:
        self._challenges.pop(key, None)
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('État de sécurité incohérent', "SentriX a refusé l'ouverture du serveur. Relancez une nouvelle session.", state='error')), ephemere=True)

    account_age = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds()))
    if account_age < legacy.MIN_ACCOUNT_AGE_SECONDS:
        self._challenges.pop(key, None)
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Compte trop récent', 'Votre compte ne remplit pas encore le délai minimum.', state='warn')), ephemere=True)

    self._verification_in_progress.add(key)
    try:
        if verified not in member.roles:
            await member.add_roles(verified, reason="SentriX : vérification renforcée V51 réussie")
        if unverified in member.roles:
            await member.remove_roles(unverified, reason="SentriX : vérification renforcée V51 réussie")
    except (discord.Forbidden, discord.HTTPException):
        return await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed("Impossible d'ouvrir l'accès", 'SentriX ne peut pas modifier vos rôles. Vérifiez la hiérarchie des rôles.', state='error')), ephemere=True)
    finally:
        self._verification_in_progress.discard(key)

    await self._clear_pending(guild.id, member.id)
    await self.bot.db.execute(
        "INSERT INTO honeypot_verified_members "
        "(guild_id, user_id, verified_at, method, account_age_seconds) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET verified_at=excluded.verified_at, "
        "method=excluded.method, account_age_seconds=excluded.account_age_seconds",
        (
            guild.id,
            member.id,
            int(time.time()),
            "membership_screening+sequence+code+math_v51",
            account_age,
        ),
    )
    try:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO verified_users (guild_id, user_id, verified_at) "
            "VALUES (?, ?, strftime('%s','now'))",
            (guild.id, member.id),
        )
    except Exception:
        pass

    self._challenges.pop(key, None)
    self._failures.pop(key, None)
    self._lock_until.pop(key, None)
    elapsed = max(1, int(time.time() - state.created_at))

    await panels.envoyer(interaction.response, panels.depuis_embed(_status_embed('Vérification réussie', f"{member.mention}, votre compte a été validé en **{elapsed}s**.\nLe rôle `Non vérifié` a été retiré et le rôle `Vérifié` vient d'être attribué.\n\n### ✅ Accès au serveur débloqué", state='ok')), ephemere=True, allowed_mentions=discord.AllowedMentions.none())
    await self._log(
        guild,
        "Membre vérifié — contrôle renforcé réussi",
        (
            f"{member.mention} (`{member.id}`)\n"
            f"Compte âgé de : **{account_age // 86400} jour(s)**\n"
            f"Challenge terminé en : **{elapsed}s**\n"
            "Contrôles : Membership Screening + séquence + code unique + calcul."
        ),
    )


def install(bot) -> None:
    global _PATCHED

    cls = legacy.HoneypotVerification
    if not getattr(cls, "_sentrix_verification_polish_v51", False):
        original_create = cls.create_or_refresh_system

        async def create_or_refresh_system_v51(self, guild: discord.Guild, *, sanction: str = "softban"):
            result, error = await original_create(self, guild, sanction=sanction)
            if error or not result:
                return result, error

            verify_channel = result["verify"]
            trap_channel = result["trap"]

            try:
                await verify_channel.purge(
                    limit=30,
                    check=lambda message: self.bot.user is not None and message.author.id == self.bot.user.id,
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            await panels.envoyer(verify_channel, panels.avec_composants(panels.depuis_embed(_panel_embed(self.bot, guild)), VerificationPanelView()), allowed_mentions=discord.AllowedMentions.none())

            try:
                await trap_channel.purge(
                    limit=30,
                    check=lambda message: self.bot.user is not None and message.author.id == self.bot.user.id,
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            await panels.envoyer(trap_channel, panels.depuis_embed(_trap_embed(self.bot, verify_channel, sanction)), allowed_mentions=discord.AllowedMentions.none())
            return result, error

        cls.create_or_refresh_system = create_or_refresh_system_v51
        cls.start_human_verification = _patched_start
        cls.complete_human_challenge = _patched_complete
        cls._sentrix_verification_polish_v51 = True
        _PATCHED = True

    if not getattr(bot, "_sentrix_verification_panel_v51_registered", False):
        try:
            bot.add_view(VerificationPanelView())
            bot._sentrix_verification_panel_v51_registered = True
        except Exception:
            logger.exception("Impossible d'enregistrer la vue persistante V51.")

    logger.info("Vérification V51 : panneau premium + réparation des sessions + challenge stylé actifs.")


__all__ = ["install", "VerificationPanelView", "StyledSequenceView"]
