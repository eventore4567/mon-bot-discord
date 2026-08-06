"""
Cog SÉCURITÉ ET AUTOMOD.
/blacklist-add /blacklist-remove /blacklist-list /blacklist-user /unblacklist-user
/blacklist-users /antispam /antilink /antiinvite /antimention /anticaps /antiemoji
/antiraid /antibot /antiaccount /antiscam /antinuke /automod-status /whitelist-domain
/unwhitelist-domain /security-level /antinuke-whitelist-add /antinuke-whitelist-remove
/antinuke-whitelist-list /lockdown-server /unlock-server /automod-escalation
/automod-exempt-role-add /automod-exempt-role-remove /automod-history

Un seul écouteur on_message applique tous les filtres actifs. Un salon ignoré via
/ignorechannel est désormais bien respecté par AutoMod (avant, ce n'était pas le cas).
Aucune adresse IP n'est collectée : seuls les identifiants Discord sont utilisés.

Escalade automatique des sanctions : chaque infraction (suppression de message par un
filtre) est comptabilisée sur une fenêtre glissante d'1h. Au-delà de certains seuils,
le membre est automatiquement mute (3), expulsé (5) puis banni (7) — sans intervention
manuelle. Désactivable via /automod-escalation. Historique consultable via /automod-history
et /automod-status (statistiques des dernières 24h par filtre).

Exemptions : administrateurs, propriétaire(s) du bot, rôle staff (/setmodrole) et tout
rôle ajouté via /automod-exempt-role-add ne sont jamais filtrés par AutoMod.

Le filtre multilingue intégré analyse 2 663 termes, 1 200 phrases et 120 groupes de
mots dans 28 langues. Une détection supprime le message et applique immédiatement une
exclusion temporaire de 10 minutes, sans attendre l'escalade des autres filtres.

L'anti-nuke (/antinuke) protège contre un compte compromis (staff ou même le bot)
qui tenterait de détruire le serveur : suppression massive de salons/rôles ou
bannissements en rafale. Si le seuil est dépassé, le responsable est immédiatement
privé de ses rôles dangereux et expulsé, et le propriétaire du serveur est alerté.
"""

import asyncio
import logging
import re
import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, checks, helpers
from utils.moderation_dataset import MultilingualModerationDataset

logger = logging.getLogger("bot")

INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\S+", re.IGNORECASE)
_COMMON_TLDS = (
    "com|net|org|gg|io|co|fr|ma|me|tv|ly|be|dev|app|ai|xyz|info|biz|online|"
    "site|shop|store|tech|pro|cc|ru|de|uk|us|ca|eu|ch|it|es|pt|nl|se|no|fi|"
    "pl|tr|in|jp|cn|kr|au|nz|br|mx|ar|za|tk|to|link|club|live|news|cloud|"
    "digital|world|vip|fun|games|social"
)
LINK_RE = re.compile(
    rf"""
    (?:
        \b(?:https?|hxxps?)://[^\s<]+
        | \bwww\.[^\s<]+
        | (?<![\w@])
          (?:[a-z0-9](?:[a-z0-9-]{{0,62}}[a-z0-9])?\.)+
          (?:{_COMMON_TLDS})\b
          (?::\d{{2,5}})?
          (?:/[^\s<]*)?
        | \b(?:\d{{1,3}}\.){{3}}\d{{1,3}}(?::\d{{2,5}})?(?:/[^\s<]*)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize_link_text(content: str) -> str:
    """Normalise les séparateurs utilisés pour contourner l'anti-lien."""
    value = content.casefold()
    value = re.sub(r"\s*(?:\[\.\]|\(\.\)|\bdot\b)\s*", ".", value)
    return value
SCAM_KEYWORDS = [
    "free nitro", "nitro gratuit", "steamcommunity", "airdrop gratuit", "crypto giveaway",
    "discord nitro free", "gagnez des nitro", "claim your nitro", "gift nitro free",
    "double your crypto", "investissement garanti", "steam gift free",
]

# ---------------------------------------------------------------- ESCALADE DES SANCTIONS
# Au-delà d'un simple "suppression + avertissement", AutoMod suit désormais le nombre
# d'infractions d'un même membre sur une fenêtre glissante et escalade automatiquement
# la sanction si ça continue — sans qu'un modérateur ait besoin d'intervenir à la main.
# Le compteur est remis à zéro dès qu'une sanction est appliquée (on ne cumule pas
# plusieurs sanctions pour la même série d'infractions).
ESCALATION_WINDOW = 3600  # fenêtre glissante d'une heure
ESCALATION_RULES = [  # (seuil d'infractions atteint, action) — évalué du plus haut au plus bas
    (7, "ban"),
    (5, "kick"),
    (3, "mute"),
]
MUTE_ESCALATION_SECONDS = 600  # 10 minutes
DATASET_TIMEOUT_SECONDS = 600  # sanction directe du filtre multilingue
ESCALATION_LABELS = {"mute": "🔇 Mute 10 minutes", "kick": "👢 Expulsion", "ban": "🔨 Bannissement"}


def _domain_allowed(content_lower: str, allowed_domains: list[str]) -> bool:
    """Vérifie qu'un domaine autorisé apparaît vraiment comme domaine dans le message,
    pas juste comme sous-chaîne. Avant, whitelister "yt.com" aurait aussi laissé passer
    "evil-yt.com.ru" puisque la vérification était un simple `in` sur la chaîne complète."""
    for domain in allowed_domains:
        if re.search(rf"(?<![\w.-]){re.escape(domain)}(?![\w-])", content_lower):
            return True
    return False


TOGGLE_FIELDS = [
    "antispam", "antilink", "antiinvite", "antimention", "anticaps",
    "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
]

# Libellés lisibles des filtres AutoMod — réutilisés par /automod-status ET par la page
# "Sécurité" de /setup, pour ne jamais avoir deux endroits à maintenir séparément.
AUTOMOD_TOGGLE_LABELS = {
    "antispam": "Anti-spam (messages répétés)",
    "antilink": "Anti-liens (tous les formats)",
    "antiinvite": "Anti-invitations Discord",
    "antimention": "Anti-mentions massives",
    "anticaps": "Anti-majuscules (SPAM CAPS)",
    "antiemoji": "Anti-spam d'émojis",
    "antiraid": "Anti-raid (afflux de comptes)",
    "antibot": "Anti-bots non autorisés",
    "antiaccount": "Anti-comptes très récents",
    "antiscam": "Anti-arnaques",
    "antinuke": "Anti-nuke (compte compromis)",
}

# Préréglages du niveau de sécurité global (/security-level et page "Sécurité" de /setup).
SECURITY_PRESETS = {
    "faible": {"antispam": 0, "antilink": 0, "antiinvite": 0, "antiraid": 0, "antiscam": 1, "antinuke": 1},
    "moyen": {"antispam": 1, "antilink": 0, "antiinvite": 1, "antiraid": 1, "antiscam": 1, "antinuke": 1},
    "eleve": {
        "antispam": 1, "antilink": 1, "antiinvite": 1, "antiraid": 1, "antiscam": 1,
        "antimention": 1, "antiaccount": 1, "antinuke": 1,
    },
}

TOGGLE_CHOICES = [
    app_commands.Choice(name="Activer", value="on"),
    app_commands.Choice(name="Désactiver", value="off"),
]

DANGEROUS_PERMS = ["administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members", "kick_members"]
NUKE_ACTION_WINDOW = 30  # secondes
NUKE_ACTION_THRESHOLD = 3  # actions destructrices avant déclenchement


class AutoMod(commands.Cog, name="Automod"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_tracker: dict[tuple[int, int], list[float]] = {}
        self.join_tracker: dict[int, list[float]] = {}
        self.nuke_tracker: dict[tuple[int, int], list[float]] = {}
        self.infraction_tracker: dict[tuple[int, int], list[float]] = {}
        self.moderation_dataset = MultilingualModerationDataset()
        # Caches mémoire : évitent des allers-retours en base de données à CHAQUE
        # message (ce qui ralentissait le bot sur un salon actif). Invalidés dès
        # qu'une commande change un réglage.
        self.automod_cache: dict[int, dict] = {}
        self.blacklist_words_cache: dict[int, list[str]] = {}
        self.blacklist_users_cache: dict[int, set[int]] = {}
        self.whitelist_domains_cache: dict[int, list[str]] = {}
        self.exempt_roles_cache: dict[int, set[int]] = {}
        self.ignored_channels_cache: dict[int, set[int]] = {}

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        # Utilise le salon "logs-securite" dédié s'il existe (via /create-logs), sinon
        # retombe sur le salon de logs général — jamais de log perdu.
        await helpers.send_log(self.bot, guild, "automod", embed)

    # ---------------------------------------------------------------- CACHES

    async def get_automod_cached(self, guild_id: int) -> dict:
        if guild_id not in self.automod_cache:
            conf = await self.bot.db.get_automod(guild_id)
            self.automod_cache[guild_id] = dict(conf) if conf else {}
        return self.automod_cache[guild_id]

    async def get_blacklist_words_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.blacklist_words_cache:
            rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (guild_id,))
            self.blacklist_words_cache[guild_id] = [r["word"] for r in rows]
        return self.blacklist_words_cache[guild_id]

    async def get_blacklist_users_cached(self, guild_id: int) -> set:
        if guild_id not in self.blacklist_users_cache:
            rows = await self.bot.db.fetchall("SELECT user_id FROM blacklist_users WHERE guild_id = ?", (guild_id,))
            self.blacklist_users_cache[guild_id] = {r["user_id"] for r in rows}
        return self.blacklist_users_cache[guild_id]

    async def get_whitelist_domains_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.whitelist_domains_cache:
            rows = await self.bot.db.fetchall("SELECT domain FROM whitelist_domains WHERE guild_id = ?", (guild_id,))
            self.whitelist_domains_cache[guild_id] = [r["domain"] for r in rows]
        return self.whitelist_domains_cache[guild_id]

    async def get_exempt_roles_cached(self, guild_id: int) -> set[int]:
        if guild_id not in self.exempt_roles_cache:
            rows = await self.bot.db.list_automod_exempt_roles(guild_id)
            self.exempt_roles_cache[guild_id] = {r["role_id"] for r in rows}
        return self.exempt_roles_cache[guild_id]

    async def get_ignored_channels_cached(self, guild_id: int) -> set[int]:
        if guild_id not in self.ignored_channels_cache:
            rows = await self.bot.db.fetchall("SELECT channel_id FROM ignored_channels WHERE guild_id = ?", (guild_id,))
            self.ignored_channels_cache[guild_id] = {r["channel_id"] for r in rows}
        return self.ignored_channels_cache[guild_id]

    async def is_automod_exempt(self, member: discord.abc.User) -> bool:
        """Vrai uniquement pour les exemptions sûres : propriétaire du serveur,
        propriétaire du bot, ou rôle explicitement autorisé avec
        +automod-exempt-role-add. Les administrateurs et modérateurs ordinaires restent
        protégés, car leur compte peut lui aussi être compromis."""
        if not isinstance(member, discord.Member):
            return False
        # La sécurité doit aussi protéger contre un compte staff/admin compromis.
        # Seuls le propriétaire du serveur, le propriétaire du bot et les rôles
        # explicitement ajoutés à la liste d'exemption échappent aux filtres.
        if member.id == member.guild.owner_id or member.id in config.OWNER_IDS:
            return True
        exempt_ids = await self.get_exempt_roles_cached(member.guild.id)
        if exempt_ids and any(r.id in exempt_ids for r in member.roles):
            return True
        return False

    async def _maybe_escalate(self, guild: discord.Guild, member: discord.Member, reason: str) -> tuple[str | None, int]:
        """Enregistre une infraction pour ce membre et, si le nombre d'infractions récentes
        dépasse un des seuils d'ESCALATION_RULES, applique automatiquement une sanction plus
        sévère (mute → kick → ban). Retourne (action_prise_ou_None, nombre_d_infractions)."""
        key = (guild.id, member.id)
        t = time.time()
        hits = self.infraction_tracker.setdefault(key, [])
        hits.append(t)
        self.infraction_tracker[key] = [x for x in hits if t - x < ESCALATION_WINDOW]
        count = len(self.infraction_tracker[key])

        conf = await self.get_automod_cached(guild.id)
        if not conf.get("escalation", 1):
            return None, count

        action_to_take = None
        for threshold, action in ESCALATION_RULES:
            if count >= threshold:
                action_to_take = action
                break  # ESCALATION_RULES est trié du seuil le plus haut au plus bas

        if action_to_take is None:
            return None, count
        if member.id == guild.owner_id or member.top_role >= guild.me.top_role:
            return None, count  # hors de portée du bot, inutile d'essayer

        try:
            if action_to_take == "mute":
                until = discord.utils.utcnow() + timedelta(seconds=MUTE_ESCALATION_SECONDS)
                await member.timeout(until, reason=f"AutoMod : escalade ({count} infractions/1h) — {reason}")
            elif action_to_take == "kick":
                await member.kick(reason=f"AutoMod : escalade ({count} infractions/1h) — {reason}")
            elif action_to_take == "ban":
                await member.ban(reason=f"AutoMod : escalade ({count} infractions/1h) — {reason}", delete_message_seconds=0)
            self.infraction_tracker[key] = []  # repart à zéro après une sanction
            return action_to_take, count
        except discord.Forbidden:
            return None, count

    async def toggle(self, ctx: commands.Context, field: str, etat: str):
        value = 1 if etat == "on" else 0
        await self.bot.db.set_automod(ctx.guild.id, field, value)
        self.automod_cache.pop(ctx.guild.id, None)
        state_text = "ACTIF" if value else "INACTIF"
        label = "L'escalade automatique" if field == "escalation" else f"Le filtre **{AUTOMOD_TOGGLE_LABELS.get(field, field)}**"
        await ctx.send(embed=embeds.success(f"{label} est maintenant {state_text}."))

    # ---------------------------------------------------------------- TOGGLES (10 commandes explicites)

    @commands.hybrid_command(name="antispam", description="Activer/désactiver la protection anti-spam.")
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antispam(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antispam", etat)

    @commands.hybrid_command(name="antilink", description="Bloquer tous les formats de liens.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antilink(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antilink", etat)

    @commands.hybrid_command(name="antiinvite", description="Activer/désactiver le blocage des invitations Discord.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiinvite(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiinvite", etat)

    @commands.hybrid_command(name="antimention", description="Activer/désactiver la protection anti-mention massive.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antimention(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antimention", etat)

    @commands.hybrid_command(name="anticaps", description="Activer/désactiver le filtre anti-majuscules.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def anticaps(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "anticaps", etat)

    @commands.hybrid_command(name="antiemoji", description="Activer/désactiver le filtre anti-spam d'émojis.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiemoji(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiemoji", etat)

    @commands.hybrid_command(name="antiraid", description="Activer/désactiver la protection anti-raid.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiraid(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiraid", etat)

    @commands.hybrid_command(name="antibot", description="Activer/désactiver le blocage automatique des bots non autorisés.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antibot(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antibot", etat)

    @commands.hybrid_command(name="antiaccount", description="Activer/désactiver le filtre anti-comptes récents.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiaccount(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiaccount", etat)

    @commands.hybrid_command(name="antiscam", description="Activer/désactiver la détection de liens/messages d'arnaque.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiscam(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiscam", etat)

    @commands.hybrid_command(name="antinuke", description="Activer/désactiver la protection anti-nuke (compte compromis).")
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antinuke(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antinuke", etat)

    @commands.hybrid_command(name="antinuke-whitelist-add", description="Exempter un membre de confiance de l'anti-nuke.", with_app_command=False)
    @app_commands.describe(membre="Le membre à exempter")
    @checks.is_owner_or_admin_for("securite")
    async def antinuke_whitelist_add(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} est maintenant exempté de l'anti-nuke."))

    @commands.hybrid_command(name="antinuke-whitelist-remove", description="Retirer un membre de la liste blanche anti-nuke.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def antinuke_whitelist_remove(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} a été retiré de la liste blanche anti-nuke."))

    @commands.hybrid_command(name="antinuke-whitelist-list", description="Afficher les membres exemptés de l'anti-nuke.", with_app_command=False)
    @checks.is_owner_or_admin_for("securite")
    async def antinuke_whitelist_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM antinuke_whitelist WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun membre exempté (seul le propriétaire du serveur est protégé par défaut)."))
        lines = [f"<@{r['user_id']}>" for r in rows]
        await ctx.send(embed=embeds.neutral("🛡️ Liste blanche anti-nuke", "\n".join(lines)))

    @commands.hybrid_command(name="lockdown-server", description="[Sécurité] Verrouiller tous les salons textuels du serveur.")
    @checks.is_owner_or_admin_for("securite")
    async def lockdown_server(self, ctx: commands.Context):
        await ctx.send(embed=embeds.warning("🔒 Verrouillage de tous les salons en cours, merci de patienter..."))
        count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role, send_messages=False, reason=f"Verrouillage du serveur par {ctx.author}"
                )
                count += 1
            except discord.Forbidden:
                pass
        e = embeds.log_entry(
            "🔒 Verrouillage du serveur", config.COLOR_ERROR, acteur=ctx.author,
            acteur_label="🛠️ Verrouillé par", extra={"📊 Salons verrouillés": str(count)},
        )
        await self.log_action(ctx.guild, e)
        await ctx.send(embed=embeds.success(f"🔒 {count} salon(s) verrouillé(s). Utilisez `/unlock-server` pour déverrouiller."))

    @commands.hybrid_command(name="unlock-server", description="[Sécurité] Déverrouiller tous les salons textuels du serveur.")
    @checks.is_owner_or_admin_for("securite")
    async def unlock_server(self, ctx: commands.Context):
        await ctx.send(embed=embeds.info("🔓 Déverrouillage en cours, merci de patienter..."))
        count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role, send_messages=None, reason=f"Déverrouillage du serveur par {ctx.author}"
                )
                count += 1
            except discord.Forbidden:
                pass
        e = embeds.log_entry(
            "🔓 Déverrouillage du serveur", config.COLOR_SUCCESS, acteur=ctx.author,
            acteur_label="🛠️ Déverrouillé par", extra={"📊 Salons déverrouillés": str(count)},
        )
        await self.log_action(ctx.guild, e)
        await ctx.send(embed=embeds.success(f"🔓 {count} salon(s) déverrouillé(s)."))

    @commands.hybrid_command(name="automod-status", description="Afficher l'état de tous les filtres automod, avec les statistiques des dernières 24h.")
    async def automod_status(self, ctx: commands.Context):
        conf = await self.bot.db.get_automod(ctx.guild.id)
        since_24h = int(time.time() - 86400)
        stats_rows = await self.bot.db.automod_stats_since(ctx.guild.id, since_24h)
        stats_by_filter = {r["filter_name"]: r["c"] for r in stats_rows}
        total_24h = sum(stats_by_filter.values())

        e = embeds.brand(
            "État de l'AutoMod",
            f"**{total_24h}** action(s) déclenchée(s) sur les dernières 24h. "
            f"Escalade automatique : {'ACTIVE' if (conf and conf['escalation']) else 'INACTIVE'} "
            f"(`/automod-escalation`).",
        )
        lines = []
        for field, label in AUTOMOD_TOGGLE_LABELS.items():
            value = conf[field] if conf else 0
            state = "ACTIF" if value else "INACTIF"
            count = stats_by_filter.get(field, 0)
            count_txt = f" — `{count}` déclenchement(s)/24h" if count else ""
            lines.append(f"**{label}** : {state}{count_txt}")
        dataset_count = sum(self.moderation_dataset.source_counts.values())
        dataset_state = "ACTIF" if self.moderation_dataset.loaded else "ERREUR DE CHARGEMENT"
        dataset_hits = stats_by_filter.get("multilingual_toxicity", 0)
        dataset_hits_text = f" — `{dataset_hits}` déclenchement(s)/24h" if dataset_hits else ""
        lines.insert(
            0,
            f"**Filtre multilingue ({len(self.moderation_dataset.languages)} langues, "
            f"{dataset_count} entrées, mute 10 min)** : {dataset_state}{dataset_hits_text}",
        )
        e.add_field(name="Filtres", value="\n".join(lines), inline=False)
        exempt_rows = await self.bot.db.list_automod_exempt_roles(ctx.guild.id)
        if exempt_rows:
            mentions = ", ".join(f"<@&{r['role_id']}>" for r in exempt_rows)
            e.add_field(name="Rôles exemptés", value=mentions, inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(
        name="security-check",
        description="Diagnostiquer la configuration et les permissions du système de sécurité.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("securite")
    async def security_check(self, ctx: commands.Context):
        conf = await self.bot.db.get_automod(ctx.guild.id)
        me = ctx.guild.me
        perms = me.guild_permissions
        required = {
            "Gérer les messages": perms.manage_messages,
            "Voir les logs d'audit": perms.view_audit_log,
            "Exclure des membres": perms.kick_members,
            "Bannir des membres": perms.ban_members,
            "Modérer les membres": perms.moderate_members,
            "Gérer les rôles": perms.manage_roles,
            "Gérer les salons": perms.manage_channels,
        }
        permission_lines = [f"**{name}** : {'Accordée' if ok else 'Manquante'}" for name, ok in required.items()]
        filter_lines = [
            f"**{label}** : {'Actif' if conf and conf[field] else 'Inactif'}"
            for field, label in AUTOMOD_TOGGLE_LABELS.items()
        ]
        e = embeds.brand(
            "Diagnostic de sécurité",
            "Ce diagnostic vérifie les réglages enregistrés et les permissions réellement "
            "accordées au bot. Une permission manquante empêche la protection associée.",
        )
        e.add_field(name="Protections", value="\n".join(filter_lines), inline=False)
        e.add_field(name="Permissions du bot", value="\n".join(permission_lines), inline=False)
        e.add_field(
            name="Test conseillé",
            value=(
                "Utilisez `+security-level eleve`, puis testez avec un compte qui n'est pas "
                "propriétaire du serveur. Le propriétaire reste toujours exempté pour éviter "
                "qu'un mauvais réglage ne le bloque."
            ),
            inline=False,
        )
        await ctx.send(embed=e)

    @commands.hybrid_command(name="automod-escalation", description="Activer/désactiver l'escalade automatique des sanctions AutoMod.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver l'escalade")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def automod_escalation(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "escalation", etat)

    @commands.hybrid_command(name="automod-exempt-role-add", description="Exempter un rôle des filtres AutoMod (jamais sanctionné).", with_app_command=False)
    @app_commands.describe(role="Le rôle à exempter")
    @checks.is_owner_or_admin_for("securite")
    async def automod_exempt_role_add(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.add_automod_exempt_role(ctx.guild.id, role.id)
        self.exempt_roles_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Les membres avec le rôle {role.mention} ne seront plus jamais filtrés par AutoMod."))

    @commands.hybrid_command(name="automod-exempt-role-remove", description="Retirer un rôle de la liste des rôles exemptés d'AutoMod.", with_app_command=False)
    @app_commands.describe(role="Le rôle à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def automod_exempt_role_remove(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.remove_automod_exempt_role(ctx.guild.id, role.id)
        self.exempt_roles_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le rôle {role.mention} n'est plus exempté d'AutoMod."))

    @commands.hybrid_command(name="automod-history", description="Afficher l'historique récent des actions AutoMod (globalement ou pour un membre).", with_app_command=False)
    @app_commands.describe(membre="Filtrer sur un membre précis (optionnel)")
    @checks.is_owner_or_admin_for("securite")
    async def automod_history(self, ctx: commands.Context, membre: discord.Member = None):
        if membre:
            rows = await self.bot.db.automod_history_for_user(ctx.guild.id, membre.id, limit=10)
            title = f"📜 Historique AutoMod — {membre.display_name}"
        else:
            rows = await self.bot.db.automod_recent(ctx.guild.id, limit=10)
            title = "📜 Historique AutoMod — Serveur"
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune action AutoMod enregistrée pour l'instant."))
        lines = []
        for r in rows:
            who = f"<@{r['user_id']}>" if r["user_id"] else "—"
            lines.append(f"<t:{r['timestamp']}:R> — {who} — `{r['filter_name']}` → **{r['action']}**\n╰ {r['reason']}")
        await ctx.send(embed=embeds.neutral(title, "\n\n".join(lines)))

    @commands.hybrid_command(name="security-level", description="Définir le niveau de sécurité global du serveur.")
    @app_commands.describe(niveau="Niveau de sécurité")
    @app_commands.choices(niveau=[
        app_commands.Choice(name="Faible", value="faible"),
        app_commands.Choice(name="Moyen", value="moyen"),
        app_commands.Choice(name="Élevé", value="eleve"),
    ])
    @checks.is_owner_or_admin_for("securite")
    async def security_level(self, ctx: commands.Context, niveau: str):
        await self.bot.db.set_guild_config(ctx.guild.id, "security_level", niveau)
        for field, value in SECURITY_PRESETS.get(niveau, {}).items():
            await self.bot.db.set_automod(ctx.guild.id, field, value)
        self.automod_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Niveau de sécurité réglé sur **{niveau}**. Les filtres associés ont été ajustés."))

    # ---------------------------------------------------------------- BLACKLIST MOTS

    @commands.hybrid_command(name="blacklist-add", description="Ajouter un mot à la liste noire.")
    @app_commands.describe(mot="Le mot ou l'expression à interdire")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_add(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)", (ctx.guild.id, mot.lower())
        )
        self.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le mot `{mot}` a été ajouté à la liste noire."))

    @commands.hybrid_command(name="blacklist-remove", description="Retirer un mot de la liste noire.", with_app_command=False)
    @app_commands.describe(mot="Le mot à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_remove(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, mot.lower())
        )
        self.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le mot `{mot}` a été retiré de la liste noire."))

    @commands.hybrid_command(name="blacklist-list", description="Afficher la liste des mots interdits.")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun mot interdit configuré."))
        words = ", ".join(f"`{r['word']}`" for r in rows)
        await ctx.send(embed=embeds.neutral("🚫 Mots interdits", words))

    # ---------------------------------------------------------------- BLACKLIST UTILISATEURS

    @commands.hybrid_command(name="blacklist-user", description="Ajouter un utilisateur à la liste noire du serveur.", with_app_command=False)
    @app_commands.describe(membre="Le membre à mettre en liste noire", raison="La raison")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_user(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            return await ctx.send(embed=embeds.error(err))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist_users (guild_id, user_id, reason) VALUES (?, ?, ?)",
            (ctx.guild.id, membre.id, raison),
        )
        self.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été ajouté à la liste noire.\nRaison : {raison}"))

    @commands.hybrid_command(name="unblacklist-user", description="Retirer un utilisateur de la liste noire.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer de la liste noire")
    @checks.is_owner_or_admin_for("securite")
    async def unblacklist_user(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM blacklist_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        self.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été retiré de la liste noire."))

    @commands.hybrid_command(name="blacklist-users", description="Afficher tous les utilisateurs en liste noire.", with_app_command=False)
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM blacklist_users WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun utilisateur en liste noire."))
        e = embeds.neutral("🚫 Utilisateurs en liste noire")
        for row in rows[:20]:
            e.add_field(name=f"ID: {row['user_id']}", value=row["reason"] or "Aucune raison", inline=False)
        await ctx.send(embed=e)

    # ---------------------------------------------------------------- WHITELIST DOMAINES

    @commands.hybrid_command(name="whitelist-domain", description="Autoriser un nom de domaine malgré l'antilink.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à autoriser (ex: youtube.com)")
    @checks.is_owner_or_admin_for("securite")
    async def whitelist_domain(self, ctx: commands.Context, domaine: str):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO whitelist_domains (guild_id, domain) VALUES (?, ?)",
            (ctx.guild.id, domaine.lower()),
        )
        self.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le domaine `{domaine}` est maintenant autorisé."))

    @commands.hybrid_command(name="unwhitelist-domain", description="Retirer un domaine de la liste blanche.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def unwhitelist_domain(self, ctx: commands.Context, domaine: str):
        await self.bot.db.execute(
            "DELETE FROM whitelist_domains WHERE guild_id = ? AND domain = ?", (ctx.guild.id, domaine.lower())
        )
        self.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le domaine `{domaine}` a été retiré de la liste blanche."))

    # ---------------------------------------------------------------- ÉCOUTEURS

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Correction : un salon mis en "ignoré" via /ignorechannel n'était en réalité
        # JAMAIS respecté par AutoMod (seules certaines commandes le vérifiaient) — les
        # filtres continuaient de supprimer des messages dans un salon censé être exempté.
        ignored = await self.get_ignored_channels_cached(message.guild.id)
        if message.channel.id in ignored:
            return

        # Correction : la liste noire de MOTS doit s'appliquer à TOUT LE MONDE, y compris
        # le staff/les administrateurs — contrairement aux autres filtres (spam, liens...)
        # qui exemptent volontairement le staff pour ne pas gêner la modération. Avant, ce
        # test passait APRÈS is_automod_exempt() : un admin qui testait "+blacklist-add mot"
        # puis tapait le mot lui-même voyait le message ne JAMAIS être supprimé, donnant
        # l'impression trompeuse que le filtre ne marchait pas du tout.
        content_lower = message.content.lower()
        link_content = _normalize_link_text(message.content)
        words = await self.get_blacklist_words_cached(message.guild.id)
        for word in words:
            if word in content_lower:
                return await self._delete_and_warn(message, "Mot interdit détecté.", "blacklist_word")

        if await self.is_automod_exempt(message.author):
            return

        dataset_match = self.moderation_dataset.match(message.content)
        if dataset_match:
            return await self._delete_and_timeout(
                message,
                "Contenu offensant détecté par le filtre multilingue.",
                detection_kind=dataset_match.kind,
            )

        conf = await self.get_automod_cached(message.guild.id)
        if not conf:
            return

        blacklisted_users = await self.get_blacklist_users_cached(message.guild.id)
        if message.author.id in blacklisted_users:
            self._mark_xp_skip(message.id)
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        if conf["antiscam"] and any(k in content_lower for k in SCAM_KEYWORDS):
            return await self._delete_and_warn(message, "Message d'arnaque potentiel détecté.", "antiscam")

        if conf["antiinvite"] and INVITE_RE.search(link_content):
            return await self._delete_and_warn(message, "Lien d'invitation Discord non autorisé.", "antiinvite")

        if conf["antilink"] and LINK_RE.search(link_content):
            allowed = await self.get_whitelist_domains_cached(message.guild.id)
            if not _domain_allowed(link_content, allowed):
                return await self._delete_and_warn(message, "Lien non autorisé.", "antilink")

        if conf["antimention"] and len(message.mentions) >= 5:
            return await self._delete_and_warn(message, "Mention massive détectée.", "antimention")

        if conf["anticaps"] and len(message.content) >= 10:
            letters = [c for c in message.content if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
                return await self._delete_and_warn(message, "Trop de majuscules (SPAM CAPS).", "anticaps")

        if conf["antiemoji"]:
            emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF]", message.content))
            if emoji_count > 10:
                return await self._delete_and_warn(message, "Spam d'émojis détecté.", "antiemoji")

        if conf["antispam"]:
            key = (message.guild.id, message.author.id)
            timestamps = self.spam_tracker.setdefault(key, [])
            t = time.time()
            timestamps.append(t)
            self.spam_tracker[key] = [x for x in timestamps if t - x < 6]
            if len(self.spam_tracker[key]) >= 5:
                self.spam_tracker[key] = []
                return await self._delete_and_warn(message, "Spam de messages détecté.", "antispam")

    def _mark_xp_skip(self, message_id: int):
        """Empêche cogs/levels.py d'accorder de l'XP pour ce message : AutoMod vient de
        décider de le supprimer (spam, lien interdit, mot blacklisté, arnaque...). Voir la
        vérification correspondante dans Levels._process_xp(). Le marqueur s'auto-nettoie
        après 10 secondes pour ne jamais laisser cet ensemble grossir indéfiniment.

        Best-effort : les deux écouteurs on_message (celui-ci et celui de Levels) sont
        indépendants et tournent en parallèle, donc cette protection couvre la grande
        majorité des cas réels mais n'offre pas une garantie absolue à la microseconde
        près sur un serveur extrêmement chargé."""
        skip_ids = getattr(self.bot, "_xp_skip_ids", None)
        if skip_ids is None:
            skip_ids = self.bot._xp_skip_ids = set()
        skip_ids.add(message_id)
        asyncio.get_event_loop().call_later(10, skip_ids.discard, message_id)

    async def _delete_and_warn(self, message: discord.Message, reason: str, filter_name: str = "automod"):
        self._mark_xp_skip(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            note = await message.channel.send(
                embed=embeds.warning(f"{message.author.mention}, votre message a été supprimé.\nRaison : {reason}")
            )
            await note.delete(delay=6)
        except discord.HTTPException:
            pass

        await self.bot.db.log_automod_action(message.guild.id, message.author.id, filter_name, "suppression", reason)
        escalation_action, infraction_count = await self._maybe_escalate(message.guild, message.author, reason)

        title = "🛡️ Action AutoMod"
        color = config.COLOR_WARNING
        extra = {
            "📍 Salon": f"{message.channel.mention}\n`ID: {message.channel.id}`",
            "🔢 Infractions (1h)": str(infraction_count),
        }
        if escalation_action:
            extra["⚔️ Escalade automatique"] = ESCALATION_LABELS.get(escalation_action, escalation_action)
            title = "🚨 Action AutoMod — escalade déclenchée"
            color = config.COLOR_ERROR if escalation_action in ("kick", "ban") else config.COLOR_WARNING
            await self.bot.db.log_automod_action(message.guild.id, message.author.id, filter_name, escalation_action, reason)

        e = embeds.log_entry(title, color, cible=message.author, cible_label="👤 Membre", raison=reason, extra=extra)
        await self.log_action(message.guild, e)

    async def _delete_and_timeout(
        self,
        message: discord.Message,
        reason: str,
        *,
        detection_kind: str,
    ):
        """Supprime le message et applique immédiatement un timeout de 10 minutes."""
        self._mark_xp_skip(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        member = message.author
        timeout_applied = False
        timeout_status = "Impossible à appliquer : permission ou hiérarchie insuffisante."
        if isinstance(member, discord.Member):
            me = message.guild.me
            until = discord.utils.utcnow() + timedelta(seconds=DATASET_TIMEOUT_SECONDS)
            current_timeout = member.timed_out_until
            if current_timeout and current_timeout > until:
                timeout_applied = True
                timeout_status = "Un timeout plus long était déjà actif; il a été conservé."
            elif (
                member.id != message.guild.owner_id
                and me is not None
                and me.guild_permissions.moderate_members
                and member.top_role < me.top_role
            ):
                try:
                    await member.timeout(
                        until,
                        reason="AutoMod : contenu offensant détecté par le filtre multilingue",
                    )
                    timeout_applied = True
                    timeout_status = "Exclusion temporaire appliquée pendant 10 minutes."
                except (discord.Forbidden, discord.HTTPException):
                    pass

        public_status = (
            "Sanction : exclusion temporaire de 10 minutes."
            if timeout_applied
            else "Le message a été bloqué, mais le bot n’a pas pu appliquer le mute. "
                 "Vérifiez la permission Modérer les membres et la hiérarchie des rôles."
        )
        try:
            note = await message.channel.send(
                embed=embeds.warning(
                    f"{message.author.mention}, votre message a été supprimé.\n"
                    f"Raison : contenu offensant détecté.\n{public_status}"
                )
            )
            await note.delete(delay=8)
        except discord.HTTPException:
            pass

        action = "mute" if timeout_applied else "suppression"
        await self.bot.db.log_automod_action(
            message.guild.id,
            message.author.id,
            "multilingual_toxicity",
            action,
            reason,
        )
        e = embeds.log_entry(
            "Action AutoMod — filtre multilingue",
            config.COLOR_WARNING,
            cible=message.author,
            cible_label="Membre",
            raison=reason,
            extra={
                "Salon": f"{message.channel.mention}\n`ID: {message.channel.id}`",
                "Type de détection": detection_kind.replace("_", " "),
                "Sanction": timeout_status,
            },
        )
        await self.log_action(message.guild, e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        conf = await self.get_automod_cached(member.guild.id)
        if not conf:
            return

        if conf["antibot"] and member.bot:
            try:
                await member.kick(reason="AutoMod : bot non autorisé")
                e = embeds.log_entry(
                    "🛡️ AutoMod - Antibot", config.COLOR_ERROR,
                    cible=member, cible_label="🤖 Bot expulsé", raison="Bot non autorisé sur ce serveur",
                )
                await self.log_action(member.guild, e)
            except discord.HTTPException:
                pass
            return

        if conf["antiaccount"]:
            account_age = (discord.utils.utcnow() - member.created_at).days
            if account_age < 7:
                try:
                    await member.kick(reason="AutoMod : compte créé il y a moins de 7 jours")
                    e = embeds.log_entry(
                        "🛡️ AutoMod - Antiaccount", config.COLOR_ERROR,
                        cible=member, cible_label="👤 Membre expulsé",
                        raison="Compte créé il y a moins de 7 jours",
                        extra={"📅 Âge du compte": f"{account_age} jour(s)"},
                    )
                    await self.log_action(member.guild, e)
                except discord.HTTPException:
                    pass
                return

        if conf["antiraid"]:
            joins = self.join_tracker.setdefault(member.guild.id, [])
            t = time.time()
            joins.append(t)
            self.join_tracker[member.guild.id] = [x for x in joins if t - x < 10]
            if len(self.join_tracker[member.guild.id]) >= 8:
                e = embeds.log_entry(
                    "🚨 Raid potentiel détecté", config.COLOR_WARNING,
                    raison="Afflux massif de nouveaux membres observé",
                    extra={"📊 Arrivées en 10s": str(len(self.join_tracker[member.guild.id]))},
                )
                await self.log_action(member.guild, e)
                # Réponse automatique : relever le niveau de vérification du serveur
                # freine immédiatement les faux comptes fraîchement créés, sans avoir
                # à verrouiller manuellement tous les salons.
                try:
                    if member.guild.verification_level != discord.VerificationLevel.highest:
                        await member.guild.edit(
                            verification_level=discord.VerificationLevel.highest,
                            reason="AutoMod : raid détecté, niveau de vérification relevé automatiquement",
                        )
                        await self.log_action(
                            member.guild,
                            embeds.log_entry(
                                "🔒 Niveau de vérification relevé", config.COLOR_WARNING,
                                raison="Relevé automatiquement suite à un raid détecté",
                            ),
                        )
                except discord.Forbidden:
                    pass
                # Évite de redéclencher la même alerte à chaque nouvel arrivant tant que le raid dure.
                self.join_tracker[member.guild.id] = []

    # ---------------------------------------------------------------- ANTI-NUKE

    async def record_nuke_action(self, guild: discord.Guild, actor_id: int) -> bool:
        """Retourne True si le seuil d'actions destructrices est dépassé pour cet auteur."""
        key = (guild.id, actor_id)
        t = time.time()
        actions = self.nuke_tracker.setdefault(key, [])
        actions.append(t)
        self.nuke_tracker[key] = [x for x in actions if t - x < NUKE_ACTION_WINDOW]
        return len(self.nuke_tracker[key]) >= NUKE_ACTION_THRESHOLD

    async def get_audit_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None):
        """Retrouve l'auteur d'une action récente via les logs d'audit (nécessite la permission adéquate).

        BUG CORRIGÉ : cette fonction ne rattrapait avant que discord.Forbidden (permission
        manquante). Or elle est appelée par TOUS les écouteurs de logs (salon créé/supprimé,
        rôle créé/supprimé, membre expulsé, anti-nuke...) AVANT l'envoi du log lui-même. La
        moindre erreur réseau/API Discord (429, 5xx, timeout) pendant guild.audit_logs()
        faisait planter silencieusement l'écouteur entier : le log correspondant n'était
        alors JAMAIS envoyé, sans aucune trace nulle part. C'est une cause plausible des
        "logs qui ne marchent pas de temps en temps" signalés sans réussir à reproduire.
        On rattrape maintenant discord.HTTPException (qui couvre aussi Forbidden) et on
        trace l'échec dans les logs du process, comme le fait déjà helpers.send_log()."""
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > 15:
                    continue
                if target_id is None or (entry.target and getattr(entry.target, "id", None) == target_id):
                    return entry.user
        except discord.HTTPException as exc:
            logger.warning(
                "get_audit_actor: échec de lecture de l'audit log ('%s') sur %s (%s) : %s. "
                "Le log correspondant sera envoyé sans auteur identifié plutôt que d'être perdu.",
                action, guild.name, guild.id, exc,
            )
            return None
        return None

    async def is_antinuke_exempt(self, guild: discord.Guild, actor: discord.abc.User) -> bool:
        # Sans auteur fiable dans l'audit log, ne sanctionne personne au hasard.
        if actor is None:
            return True
        # Le bot SentriX peut effectuer des actions légitimes. En revanche, les autres
        # bots ne sont plus exemptés automatiquement : un bot malveillant peut nuker.
        if self.bot.user and actor.id == self.bot.user.id:
            return True
        if actor.id == guild.owner_id:
            return True
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (guild.id, actor.id)
        )
        return row is not None

    async def punish_nuker(self, guild: discord.Guild, actor_id: int, reason: str):
        member = guild.get_member(actor_id)
        action_taken = "aucune action possible (permissions insuffisantes)"
        if member:
            dangerous_roles = [
                r for r in member.roles
                if r != guild.default_role and any(getattr(r.permissions, p, False) for p in DANGEROUS_PERMS)
            ]
            try:
                if dangerous_roles:
                    await member.remove_roles(*dangerous_roles, reason=f"AutoMod anti-nuke : {reason}")
            except discord.Forbidden:
                pass
            # Un nuke en cours justifie une réponse décisive : on bannit directement
            # (empêche de revenir avec une nouvelle invitation), avec repli sur un kick
            # si le bot n'a pas la permission de bannir.
            try:
                await guild.ban(discord.Object(id=actor_id), reason=f"AutoMod anti-nuke : {reason}", delete_message_seconds=3600)
                action_taken = "banni du serveur"
            except discord.Forbidden:
                try:
                    await member.kick(reason=f"AutoMod anti-nuke : {reason}")
                    action_taken = "expulsé du serveur (le bot n'a pas la permission de bannir)"
                except discord.Forbidden:
                    action_taken = "rôles à risque retirés, mais impossible de le sanctionner davantage (permissions insuffisantes)"
        e = embeds.log_entry(
            "🚨 ANTI-NUKE DÉCLENCHÉ", config.COLOR_ERROR,
            cible=member or actor_id, cible_label="👤 Auteur suspecté",
            raison=reason,
            extra={"⚔️ Action prise": action_taken, "🔗 ID": f"`{actor_id}`"},
        )
        await self.log_action(guild, e)
        try:
            owner = guild.owner or await guild.fetch_member(guild.owner_id)
            if owner:
                await owner.send(embed=e)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        conf = await self.get_automod_cached(channel.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if await self.is_antinuke_exempt(channel.guild, actor):
            return
        if await self.record_nuke_action(channel.guild, actor.id):
            await self.punish_nuker(channel.guild, actor.id, "Suppression massive de salons")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        conf = await self.get_automod_cached(role.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        if await self.is_antinuke_exempt(role.guild, actor):
            return
        if await self.record_nuke_action(role.guild, actor.id):
            await self.punish_nuker(role.guild, actor.id, "Suppression massive de rôles")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        # Un "nuke" ne supprime pas forcément les salons : il arrive très souvent qu'il les
        # renomme en masse (ex: "NUKED-BY-...") sans rien supprimer, ce qui passait avant
        # complètement inaperçu par l'anti-nuke (qui ne regardait que les suppressions).
        if before.name == after.name:
            return
        conf = await self.get_automod_cached(after.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
        if await self.is_antinuke_exempt(after.guild, actor):
            return
        if await self.record_nuke_action(after.guild, actor.id):
            await self.punish_nuker(after.guild, actor.id, "Renommage massif de salons")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        # Même logique que ci-dessus, pour les rôles : renommage massif ou octroi soudain
        # de permissions dangereuses (élévation de privilèges avant un nuke).
        name_changed = before.name != after.name
        perms_escalated = before.permissions != after.permissions and any(
            not getattr(before.permissions, p, False) and getattr(after.permissions, p, False) for p in DANGEROUS_PERMS
        )
        if not name_changed and not perms_escalated:
            return
        conf = await self.get_automod_cached(after.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(after.guild, discord.AuditLogAction.role_update, after.id)
        if await self.is_antinuke_exempt(after.guild, actor):
            return
        reason = "Élévation de permissions suspecte sur un rôle" if perms_escalated else "Renommage massif de rôles"
        if await self.record_nuke_action(after.guild, actor.id):
            await self.punish_nuker(after.guild, actor.id, reason)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        conf = await self.get_automod_cached(guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(guild, discord.AuditLogAction.ban, user.id)
        if await self.is_antinuke_exempt(guild, actor):
            return
        if await self.record_nuke_action(guild, actor.id):
            await self.punish_nuker(guild, actor.id, "Bannissements massifs")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
