"""Centre de commandes Sécurité V3 de SentriX.

Les moteurs de protection restent dans AutoMod, SecurityHardening et security_tools.
Ce module reconstruit leur interface autour d'une racine simple et cohérente :
`+security ...`. Les anciens noms restent disponibles pour compatibilité, mais sont
masqués de +help afin que les membres du staff n'aient plus des dizaines de commandes
éparpillées à mémoriser.
"""
from __future__ import annotations

import re
import time

import discord
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID
from utils import checks
from . import language_runtime
from .security_runtime_hardening import apply_recommended_security


SECURITY_FILTERS: dict[str, tuple[str, str]] = {
    "antispam": ("Anti-spam", "Anti-spam"),
    "antilink": ("Anti-liens", "Anti-links"),
    "antiinvite": ("Anti-invitations", "Anti-invites"),
    "antimention": ("Anti-mentions", "Anti-mentions"),
    "anticaps": ("Anti-majuscules", "Anti-caps"),
    "antiemoji": ("Anti-émojis", "Anti-emoji"),
    "antiraid": ("Anti-raid", "Anti-raid"),
    "antibot": ("Anti-bots", "Anti-bots"),
    "antiaccount": ("Anti-comptes récents", "Anti-new-accounts"),
    "antiscam": ("Anti-arnaques", "Anti-scam"),
    "antinuke": ("Anti-nuke", "Anti-nuke"),
    "escalation": ("Escalade automatique", "Automatic escalation"),
}

FILTER_ALIASES = {
    "spam": "antispam", "antispam": "antispam",
    "link": "antilink", "links": "antilink", "lien": "antilink", "liens": "antilink", "antilink": "antilink",
    "invite": "antiinvite", "invites": "antiinvite", "invitation": "antiinvite", "invitations": "antiinvite", "antiinvite": "antiinvite",
    "mention": "antimention", "mentions": "antimention", "antimention": "antimention",
    "caps": "anticaps", "maj": "anticaps", "majuscules": "anticaps", "anticaps": "anticaps",
    "emoji": "antiemoji", "emojis": "antiemoji", "antiemoji": "antiemoji",
    "raid": "antiraid", "antiraid": "antiraid",
    "bot": "antibot", "bots": "antibot", "antibot": "antibot",
    "account": "antiaccount", "accounts": "antiaccount", "compte": "antiaccount", "comptes": "antiaccount", "antiaccount": "antiaccount",
    "scam": "antiscam", "arnaque": "antiscam", "arnaques": "antiscam", "antiscam": "antiscam",
    "nuke": "antinuke", "antinuke": "antinuke",
    "escalation": "escalation", "escalade": "escalation",
}

LEVEL_ALIASES = {
    "low": "faible", "faible": "faible",
    "medium": "moyen", "mid": "moyen", "moyen": "moyen",
    "high": "eleve", "elevé": "eleve", "élevé": "eleve", "eleve": "eleve", "fort": "eleve",
}

SECURITY_PRESETS = {
    "faible": {
        "antispam": 0, "antilink": 0, "antiinvite": 0,
        "antiraid": 0, "antiscam": 1, "antinuke": 1,
    },
    "moyen": {
        "antispam": 1, "antilink": 0, "antiinvite": 1,
        "antiraid": 1, "antiscam": 1, "antinuke": 1,
    },
    "eleve": {
        "antispam": 1, "antilink": 1, "antiinvite": 1,
        "antiraid": 1, "antiscam": 1, "antimention": 1,
        "antiaccount": 1, "antinuke": 1,
    },
}

# Compatibilité : ces commandes continuent d'exister, mais +help présente désormais la
# nouvelle famille +security à leur place.
LEGACY_SECURITY_ROOTS = {
    "antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji",
    "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
    "antinuke-whitelist-add", "antinuke-whitelist-remove", "antinuke-whitelist-list",
    "automod-status", "automod-escalation", "automod-exempt-role-add",
    "automod-exempt-role-remove", "automod-history", "security-check", "security-level",
    "security-repair", "blacklist-add", "blacklist-remove", "blacklist-list",
    "blacklist-user", "unblacklist-user", "blacklist-users", "whitelist-domain",
    "unwhitelist-domain", "lockdown-server", "unlock-server", "panic",
    "quarantine", "unquarantine", "role-snapshot", "role-restore", "permission-audit",
    "server-backup", "server-restore",
}

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)


def _norm(value: str) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _parse_state(value: str) -> bool | None:
    raw = _norm(value)
    if raw in {"on", "enable", "enabled", "actif", "active", "activer", "1", "true", "yes", "oui"}:
        return True
    if raw in {"off", "disable", "disabled", "inactif", "inactive", "desactiver", "désactiver", "0", "false", "no", "non"}:
        return False
    return None


def _clean_domain(value: str) -> str | None:
    value = _norm(value)
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0].split(":", 1)[0].strip(".")
    return value if _DOMAIN_RE.fullmatch(value) else None


class SecurityCommandCenter(commands.Cog, name="SecurityCommandCenter"):
    """Interface canonique des outils de sécurité SentriX."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _lang(self, ctx: commands.Context) -> str:
        return await language_runtime.get_language(
            self.bot,
            ctx.guild.id if ctx.guild else None,
        )

    async def _t(self, ctx: commands.Context, fr: str, en: str) -> str:
        return en if await self._lang(ctx) == language_runtime.LANG_EN else fr

    def _automod(self):
        return self.bot.get_cog("Automod")

    async def _critical_owner(self, ctx: commands.Context) -> bool:
        if ctx.guild and ctx.author.id == ctx.guild.owner_id:
            return True
        if ctx.author.id == PRIMARY_CREATOR_ID or ctx.author.id in config.OWNER_IDS:
            return True
        try:
            if await self.bot.db.is_bot_creator(ctx.author.id):
                return True
        except Exception:
            pass

        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Accès propriétaire requis", "Owner access required"),
                description=await self._t(
                    ctx,
                    "Cette action modifie une protection critique. Seul le propriétaire du serveur ou du bot peut l'utiliser.",
                    "This action changes a critical protection. Only the server or bot owner can use it.",
                ),
                color=0xED4245,
            )
        )
        return False

    async def _conf(self, guild_id: int) -> dict:
        row = await self.bot.db.get_automod(guild_id)
        return dict(row) if row else {}

    async def _level(self, guild_id: int) -> str:
        row = await self.bot.db.get_guild_config(guild_id)
        try:
            return str(row["security_level"] or "moyen")
        except Exception:
            return "moyen"

    async def _set_filter(self, guild_id: int, field: str, enabled: bool) -> None:
        await self.bot.db.set_automod(guild_id, field, 1 if enabled else 0)
        automod = self._automod()
        if automod is not None:
            automod.automod_cache.pop(guild_id, None)

    async def _status_embed(self, ctx: commands.Context) -> discord.Embed:
        lang = await self._lang(ctx)
        conf = await self._conf(ctx.guild.id)
        try:
            rows = await self.bot.db.automod_stats_since(
                ctx.guild.id,
                int(time.time()) - 86400,
            )
            stats = {str(row["filter_name"]): int(row["c"]) for row in rows}
        except Exception:
            stats = {}

        active = sum(1 for key in SECURITY_FILTERS if bool(conf.get(key, 0)))
        if lang == language_runtime.LANG_EN:
            title = "SENTRIX / SECURITY"
            description = (
                f"{active}/{len(SECURITY_FILTERS)} protection modules enabled. "
                f"{sum(stats.values())} AutoMod action(s) in the last 24 hours."
            )
            on_text, off_text = "ON", "OFF"
            modules_name, level_name = "Protection modules", "Security level"
        else:
            title = "SENTRIX / SÉCURITÉ"
            description = (
                f"{active}/{len(SECURITY_FILTERS)} modules de protection actifs. "
                f"{sum(stats.values())} action(s) AutoMod sur les dernières 24 h."
            )
            on_text, off_text = "ACTIF", "INACTIF"
            modules_name, level_name = "Modules de protection", "Niveau de sécurité"

        lines = []
        for key, labels in SECURITY_FILTERS.items():
            label = labels[1] if lang == language_runtime.LANG_EN else labels[0]
            hits = stats.get(key, 0)
            suffix = f" · {hits}/24h" if hits else ""
            state = on_text if conf.get(key, 0) else off_text
            lines.append(f"**{label}** — {state}{suffix}")

        embed = discord.Embed(
            title=title,
            description=description,
            color=0x6D5DFB,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name=modules_name, value="\n".join(lines)[:1024], inline=False)
        embed.add_field(name=level_name, value=f"`{await self._level(ctx.guild.id)}`", inline=True)
        embed.set_footer(text="SentriX Security V3")
        return embed

    async def _legacy(self, ctx: commands.Context, name: str, /, *args, **kwargs):
        command = self.bot.get_command(name)
        if command is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Module indisponible", "Module unavailable"),
                    description=await self._t(
                        ctx,
                        "La commande interne correspondante n'est pas chargée.",
                        "The matching internal command is not loaded.",
                    ),
                    color=0xED4245,
                )
            )
        return await ctx.invoke(command, *args, **kwargs)

    # ------------------------------------------------------------------ CENTRE

    @commands.group(
        name="security",
        aliases=["securite", "sécurité"],
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def security(self, ctx: commands.Context):
        """Centre de contrôle de toute la sécurité du serveur."""
        embed = await self._status_embed(ctx)
        embed.add_field(
            name=await self._t(ctx, "Commandes principales", "Main commands"),
            value=(
                "`+security status` · `level` · `filter` · `scan` · `repair`\n"
                "`+security whitelist` · `blacklist` · `history` · `panic`\n"
                "`+security quarantine` · `roles` · `permissions` · `backup`"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @security.command(name="status", aliases=["etat", "state", "overview"])
    @checks.is_owner_or_admin_for("securite")
    async def security_status(self, ctx: commands.Context):
        """Affiche l'état complet des protections."""
        await ctx.send(embed=await self._status_embed(ctx))

    @security.command(name="filter", aliases=["module", "protection", "filtre"])
    @checks.is_owner_or_admin_for("securite")
    async def security_filter(
        self,
        ctx: commands.Context,
        filtre: str | None = None,
        etat: str | None = None,
    ):
        """Affiche ou modifie un module de protection."""
        if not filtre:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Modules disponibles", "Available modules"),
                    description=(
                        f"`{', '.join(sorted(SECURITY_FILTERS))}`\n\n"
                        "`+security filter <module> <on/off>`"
                    ),
                    color=0x6D5DFB,
                )
            )

        field = FILTER_ALIASES.get(_norm(filtre))
        if field is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Module inconnu", "Unknown module"),
                    description=await self._t(
                        ctx,
                        "Utilise `+security filter` pour afficher la liste.",
                        "Use `+security filter` to list modules.",
                    ),
                    color=0xED4245,
                )
            )

        conf = await self._conf(ctx.guild.id)
        label = SECURITY_FILTERS[field][
            1 if await self._lang(ctx) == language_runtime.LANG_EN else 0
        ]
        if etat is None:
            enabled = bool(conf.get(field, 0))
            return await ctx.send(
                embed=discord.Embed(
                    title=label,
                    description=await self._t(
                        ctx,
                        f"État actuel : **{'ACTIF' if enabled else 'INACTIF'}**",
                        f"Current state: **{'ON' if enabled else 'OFF'}**",
                    ),
                    color=0x57F287 if enabled else 0x747F8D,
                )
            )

        enabled = _parse_state(etat)
        if enabled is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "État invalide", "Invalid state"),
                    description="`on` / `off`",
                    color=0xED4245,
                )
            )
        if field == "antinuke" and not await self._critical_owner(ctx):
            return

        await self._set_filter(ctx.guild.id, field, enabled)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Protection mise à jour", "Protection updated"),
                description=f"**{label}** — {'ON' if enabled else 'OFF'}",
                color=0x57F287 if enabled else 0x747F8D,
            )
        )

    @security.command(name="level", aliases=["niveau"])
    @checks.is_owner_or_admin_for("securite")
    async def security_level(self, ctx: commands.Context, niveau: str | None = None):
        """Applique un profil faible, moyen ou élevé."""
        if niveau is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Niveau de sécurité", "Security level"),
                    description=(
                        f"**{await self._level(ctx.guild.id)}**\n"
                        "`+security level faible|moyen|eleve`"
                    ),
                    color=0x6D5DFB,
                )
            )

        level = LEVEL_ALIASES.get(_norm(niveau))
        if level is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Niveau invalide", "Invalid level"),
                    description=(
                        "`faible` · `moyen` · `eleve` / "
                        "`low` · `medium` · `high`"
                    ),
                    color=0xED4245,
                )
            )

        await self.bot.db.set_guild_config(ctx.guild.id, "security_level", level)
        for field, value in SECURITY_PRESETS[level].items():
            await self._set_filter(ctx.guild.id, field, bool(value))

        await ctx.send(
            embed=discord.Embed(
                title=await self._t(
                    ctx,
                    "Profil de sécurité appliqué",
                    "Security profile applied",
                ),
                description=f"**{level.upper()}**",
                color=0x57F287,
            )
        )

    @security.command(name="scan", aliases=["check", "diagnostic", "audit"])
    @checks.is_owner_or_admin_for("securite")
    async def security_scan(self, ctx: commands.Context):
        """Analyse les protections et permissions nécessaires."""
        conf = await self._conf(ctx.guild.id)
        me = ctx.guild.me
        if me is None:
            return await ctx.send("SentriX n'est pas disponible dans le cache du serveur.")

        perms = me.guild_permissions
        required = {
            "Manage Messages": perms.manage_messages,
            "View Audit Log": perms.view_audit_log,
            "Kick Members": perms.kick_members,
            "Ban Members": perms.ban_members,
            "Moderate Members": perms.moderate_members,
            "Manage Roles": perms.manage_roles,
            "Manage Channels": perms.manage_channels,
        }
        missing = [name for name, allowed in required.items() if not allowed]
        active = sum(1 for key in SECURITY_FILTERS if conf.get(key, 0))
        score = round(
            (active / len(SECURITY_FILTERS)) * 70
            + ((len(required) - len(missing)) / len(required)) * 30
        )
        color = 0x57F287 if score >= 85 else 0xFEE75C if score >= 60 else 0xED4245

        embed = discord.Embed(
            title=await self._t(
                ctx,
                "SENTRIX / ANALYSE SÉCURITÉ",
                "SENTRIX / SECURITY SCAN",
            ),
            description=await self._t(
                ctx,
                f"Score estimé : **{score}/100**",
                f"Estimated score: **{score}/100**",
            ),
            color=color,
        )
        embed.add_field(
            name=await self._t(ctx, "Modules actifs", "Active modules"),
            value=f"{active}/{len(SECURITY_FILTERS)}",
            inline=True,
        )
        embed.add_field(
            name=await self._t(ctx, "Permissions manquantes", "Missing permissions"),
            value=str(len(missing)),
            inline=True,
        )
        if missing:
            embed.add_field(
                name=await self._t(ctx, "À corriger", "Needs attention"),
                value="\n".join(f"- {item}" for item in missing),
                inline=False,
            )
        embed.add_field(
            name=await self._t(ctx, "Audit avancé", "Advanced audit"),
            value="`+security permissions`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @security.command(name="repair", aliases=["fix", "reparer", "réparer"])
    @checks.is_owner_or_admin_for("securite")
    async def security_repair(self, ctx: commands.Context):
        """Active le profil recommandé et vérifie les permissions du bot."""
        result = await apply_recommended_security(self.bot, ctx.guild)
        missing = result.get("missing_permissions", [])
        embed = discord.Embed(
            title=await self._t(ctx, "Sécurité réparée", "Security repaired"),
            description=await self._t(
                ctx,
                "Le profil recommandé SentriX est maintenant appliqué.",
                "The recommended SentriX profile is now applied.",
            ),
            color=0x57F287 if not missing else 0xFEE75C,
        )
        if missing:
            embed.add_field(
                name=await self._t(ctx, "Permissions manquantes", "Missing permissions"),
                value="\n".join(f"- {item}" for item in missing)[:1024],
                inline=False,
            )
        await ctx.send(embed=embed)

    @security.command(name="history", aliases=["historique", "logs"])
    @checks.is_owner_or_admin_for("securite")
    async def security_history(
        self,
        ctx: commands.Context,
        membre: discord.Member | None = None,
    ):
        """Affiche les dernières actions AutoMod."""
        if membre is not None:
            rows = await self.bot.db.automod_history_for_user(
                ctx.guild.id,
                membre.id,
                limit=15,
            )
        else:
            rows = await self.bot.db.automod_recent(ctx.guild.id, limit=15)

        if not rows:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Historique sécurité", "Security history"),
                    description=await self._t(
                        ctx,
                        "Aucune action enregistrée.",
                        "No recorded action.",
                    ),
                    color=0x747F8D,
                )
            )

        lines = []
        for row in rows:
            who = f"<@{row['user_id']}>" if row["user_id"] else "-"
            lines.append(
                f"<t:{row['timestamp']}:R> · {who} · "
                f"`{row['filter_name']}` → **{row['action']}**"
            )
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Historique sécurité", "Security history"),
                description="\n".join(lines)[:4000],
                color=0x6D5DFB,
            )
        )

    @security.command(name="panic", aliases=["emergency", "urgence"])
    async def security_panic(self, ctx: commands.Context, action: str = "status"):
        """Active, restaure ou affiche le mode d'urgence PANIC."""
        if not await self._critical_owner(ctx):
            return

        hardening = self.bot.get_cog("SecurityHardening")
        if hardening is None:
            return await ctx.send(
                embed=discord.Embed(
                    title="PANIC",
                    description=await self._t(
                        ctx,
                        "Moteur d'urgence indisponible.",
                        "Emergency engine unavailable.",
                    ),
                    color=0xED4245,
                )
            )

        mode = _norm(action)
        if mode in {"on", "start", "enable", "activer"}:
            return await hardening._activate_panic(ctx)
        if mode in {"off", "stop", "restore", "restaurer", "desactiver", "désactiver"}:
            return await hardening._deactivate_panic(ctx)
        if mode not in {"status", "state", "etat", "état"}:
            return await ctx.send(
                embed=discord.Embed(
                    title="PANIC",
                    description="`+security panic on|off|status`",
                    color=0xED4245,
                )
            )

        row = await hardening._panic_row(ctx.guild.id)
        if row:
            description = await self._t(
                ctx,
                f"ACTIF depuis <t:{row['created_at']}:R> · activé par <@{row['created_by']}>",
                f"ACTIVE since <t:{row['created_at']}:R> · enabled by <@{row['created_by']}>",
            )
            color = 0xED4245
        else:
            description = await self._t(ctx, "INACTIF", "INACTIVE")
            color = 0x57F287
        await ctx.send(
            embed=discord.Embed(
                title="SENTRIX / PANIC",
                description=description,
                color=color,
            )
        )

    # -------------------------------------------------------------- LISTE BLANCHE

    @security.group(
        name="whitelist",
        aliases=["allowlist", "liste-blanche"],
        invoke_without_command=True,
    )
    @checks.is_owner_or_admin_for("securite")
    async def security_whitelist(self, ctx: commands.Context):
        """Gère les exemptions et domaines autorisés."""
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(
                    ctx,
                    "SENTRIX / LISTE BLANCHE",
                    "SENTRIX / ALLOWLIST",
                ),
                description=(
                    "`+security whitelist user-add @membre` · `user-remove` · `users`\n"
                    "`+security whitelist role-add @role` · `role-remove` · `roles`\n"
                    "`+security whitelist domain-add example.com` · `domain-remove` · `domains`"
                ),
                color=0x6D5DFB,
            )
        )

    @security_whitelist.command(name="user-add", aliases=["add-user", "membre-add"])
    async def whitelist_user_add(self, ctx: commands.Context, membre: discord.Member):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)",
            (ctx.guild.id, membre.id),
        )
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(
                    ctx,
                    "Exemption anti-nuke ajoutée",
                    "Anti-nuke exemption added",
                ),
                description=membre.mention,
                color=0x57F287,
            )
        )

    @security_whitelist.command(name="user-remove", aliases=["remove-user", "membre-remove"])
    async def whitelist_user_remove(self, ctx: commands.Context, membre: discord.Member):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.execute(
            "DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, membre.id),
        )
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(
                    ctx,
                    "Exemption anti-nuke retirée",
                    "Anti-nuke exemption removed",
                ),
                description=membre.mention,
                color=0x57F287,
            )
        )

    @security_whitelist.command(name="users", aliases=["members", "membres"])
    async def whitelist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT user_id FROM antinuke_whitelist WHERE guild_id = ? ORDER BY user_id",
            (ctx.guild.id,),
        )
        if rows:
            text = "\n".join(
                f"<@{row['user_id']}> · `{row['user_id']}`" for row in rows
            )
        else:
            text = await self._t(ctx, "Aucun membre exempté.", "No exempted member.")
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Exemptions anti-nuke", "Anti-nuke exemptions"),
                description=text[:4000],
                color=0x6D5DFB,
            )
        )

    @security_whitelist.command(name="role-add", aliases=["add-role"])
    async def whitelist_role_add(self, ctx: commands.Context, role: discord.Role):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.add_automod_exempt_role(ctx.guild.id, role.id)
        automod = self._automod()
        if automod is not None:
            automod.exempt_roles_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Rôle exempté", "Role exempted"),
                description=role.mention,
                color=0x57F287,
            )
        )

    @security_whitelist.command(name="role-remove", aliases=["remove-role"])
    async def whitelist_role_remove(self, ctx: commands.Context, role: discord.Role):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.remove_automod_exempt_role(ctx.guild.id, role.id)
        automod = self._automod()
        if automod is not None:
            automod.exempt_roles_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(
                    ctx,
                    "Exemption de rôle retirée",
                    "Role exemption removed",
                ),
                description=role.mention,
                color=0x57F287,
            )
        )

    @security_whitelist.command(name="roles")
    async def whitelist_roles(self, ctx: commands.Context):
        rows = await self.bot.db.list_automod_exempt_roles(ctx.guild.id)
        if rows:
            text = "\n".join(
                f"<@&{row['role_id']}> · `{row['role_id']}`" for row in rows
            )
        else:
            text = await self._t(ctx, "Aucun rôle exempté.", "No exempted role.")
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Rôles exemptés", "Exempted roles"),
                description=text[:4000],
                color=0x6D5DFB,
            )
        )

    @security_whitelist.command(name="domain-add", aliases=["add-domain", "domaine-add"])
    async def whitelist_domain_add(self, ctx: commands.Context, domaine: str):
        domain = _clean_domain(domaine)
        if domain is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Domaine invalide", "Invalid domain"),
                    description="`example.com`",
                    color=0xED4245,
                )
            )
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO whitelist_domains (guild_id, domain) VALUES (?, ?)",
            (ctx.guild.id, domain),
        )
        automod = self._automod()
        if automod is not None:
            automod.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Domaine autorisé", "Domain allowed"),
                description=f"`{domain}`",
                color=0x57F287,
            )
        )

    @security_whitelist.command(name="domain-remove", aliases=["remove-domain", "domaine-remove"])
    async def whitelist_domain_remove(self, ctx: commands.Context, domaine: str):
        domain = _clean_domain(domaine)
        if domain is None:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Domaine invalide", "Invalid domain"),
                    description="`example.com`",
                    color=0xED4245,
                )
            )
        await self.bot.db.execute(
            "DELETE FROM whitelist_domains WHERE guild_id = ? AND domain = ?",
            (ctx.guild.id, domain),
        )
        automod = self._automod()
        if automod is not None:
            automod.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Domaine retiré", "Domain removed"),
                description=f"`{domain}`",
                color=0x57F287,
            )
        )

    @security_whitelist.command(name="domains", aliases=["domain-list", "domaines"])
    async def whitelist_domains(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT domain FROM whitelist_domains WHERE guild_id = ? ORDER BY domain",
            (ctx.guild.id,),
        )
        if rows:
            text = "\n".join(f"`{row['domain']}`" for row in rows)
        else:
            text = await self._t(ctx, "Aucun domaine autorisé.", "No allowed domain.")
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Domaines autorisés", "Allowed domains"),
                description=text[:4000],
                color=0x6D5DFB,
            )
        )

    # ----------------------------------------------------------------- LISTE NOIRE

    @security.group(
        name="blacklist",
        aliases=["blocklist", "liste-noire"],
        invoke_without_command=True,
    )
    @checks.is_owner_or_admin_for("securite")
    async def security_blacklist(self, ctx: commands.Context):
        """Gère les mots et utilisateurs bloqués."""
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(
                    ctx,
                    "SENTRIX / LISTE NOIRE",
                    "SENTRIX / BLOCKLIST",
                ),
                description=(
                    "`+security blacklist word-add <mot>` · `word-remove` · `words`\n"
                    "`+security blacklist user-add @membre [raison]` · `user-remove` · `users`"
                ),
                color=0x6D5DFB,
            )
        )

    @security_blacklist.command(name="word-add", aliases=["add-word", "mot-add"])
    async def blacklist_word_add(self, ctx: commands.Context, *, mot: str):
        word = " ".join(mot.casefold().split())[:200]
        if not word:
            return
        exists = await self.bot.db.fetchone(
            "SELECT 1 FROM blacklist_words WHERE guild_id = ? AND word = ?",
            (ctx.guild.id, word),
        )
        if not exists:
            await self.bot.db.execute(
                "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)",
                (ctx.guild.id, word),
            )
        automod = self._automod()
        if automod is not None:
            automod.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Mot bloqué", "Blocked word"),
                description=f"`{word}`",
                color=0x57F287,
            )
        )

    @security_blacklist.command(name="word-remove", aliases=["remove-word", "mot-remove"])
    async def blacklist_word_remove(self, ctx: commands.Context, *, mot: str):
        word = " ".join(mot.casefold().split())[:200]
        await self.bot.db.execute(
            "DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?",
            (ctx.guild.id, word),
        )
        automod = self._automod()
        if automod is not None:
            automod.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Mot débloqué", "Word unblocked"),
                description=f"`{word}`",
                color=0x57F287,
            )
        )

    @security_blacklist.command(name="words", aliases=["word-list", "mots"])
    async def blacklist_words(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id = ? ORDER BY word",
            (ctx.guild.id,),
        )
        if rows:
            text = " · ".join(f"`{row['word']}`" for row in rows)
        else:
            text = await self._t(ctx, "Aucun mot bloqué.", "No blocked word.")
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Mots bloqués", "Blocked words"),
                description=text[:4000],
                color=0x6D5DFB,
            )
        )

    @security_blacklist.command(name="user-add", aliases=["add-user", "membre-add"])
    async def blacklist_user_add(
        self,
        ctx: commands.Context,
        membre: discord.Member,
        *,
        raison: str = "Aucune raison fournie",
    ):
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            return await ctx.send(
                embed=discord.Embed(
                    title=await self._t(ctx, "Action refusée", "Action denied"),
                    description=err,
                    color=0xED4245,
                )
            )
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist_users "
            "(guild_id, user_id, reason) VALUES (?, ?, ?)",
            (ctx.guild.id, membre.id, raison[:500]),
        )
        automod = self._automod()
        if automod is not None:
            automod.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Utilisateur bloqué", "User blocked"),
                description=f"{membre.mention}\n{raison[:1000]}",
                color=0x57F287,
            )
        )

    @security_blacklist.command(name="user-remove", aliases=["remove-user", "membre-remove"])
    async def blacklist_user_remove(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM blacklist_users WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, membre.id),
        )
        automod = self._automod()
        if automod is not None:
            automod.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Utilisateur débloqué", "User unblocked"),
                description=membre.mention,
                color=0x57F287,
            )
        )

    @security_blacklist.command(name="users", aliases=["members", "membres"])
    async def blacklist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT user_id, reason FROM blacklist_users "
            "WHERE guild_id = ? ORDER BY user_id",
            (ctx.guild.id,),
        )
        if rows:
            text = "\n".join(
                f"<@{row['user_id']}> · `{row['user_id']}` — {row['reason'] or '-'}"
                for row in rows[:30]
            )
        else:
            text = await self._t(ctx, "Aucun utilisateur bloqué.", "No blocked user.")
        await ctx.send(
            embed=discord.Embed(
                title=await self._t(ctx, "Utilisateurs bloqués", "Blocked users"),
                description=text[:4000],
                color=0x6D5DFB,
            )
        )

    # ------------------------------------------------------------ OUTILS AVANCÉS
    # Ces wrappers réutilisent les implémentations déjà éprouvées de security_tools.

    @security.command(name="quarantine", aliases=["isolate", "isoler"])
    @checks.has_permission_or_modrole("moderate_members")
    async def security_quarantine(
        self,
        ctx: commands.Context,
        membre: discord.Member,
        duree: str,
        *,
        raison: str = "Aucune raison fournie",
    ):
        """Isole temporairement un membre et sauvegarde ses rôles."""
        await self._legacy(ctx, "quarantine", membre, duree, raison=raison)

    @security.command(name="unquarantine", aliases=["unisolate", "liberer"])
    @checks.has_permission_or_modrole("moderate_members")
    async def security_unquarantine(self, ctx: commands.Context, membre: discord.Member):
        """Lève immédiatement une quarantaine."""
        await self._legacy(ctx, "unquarantine", membre)

    @security.command(name="role-snapshot", aliases=["roles-save", "snapshot-roles"])
    @checks.has_permission_or_modrole("manage_roles")
    async def security_role_snapshot(self, ctx: commands.Context, membre: discord.Member):
        """Sauvegarde les rôles actuels d'un membre."""
        await self._legacy(ctx, "role-snapshot", membre)

    @security.command(name="role-restore", aliases=["roles-restore", "restore-roles"])
    @checks.has_permission_or_modrole("manage_roles")
    async def security_role_restore(
        self,
        ctx: commands.Context,
        membre: discord.Member,
        snapshot_id: int,
    ):
        """Restaure les rôles d'un membre depuis un snapshot."""
        await self._legacy(ctx, "role-restore", membre, snapshot_id)

    @security.command(name="permissions", aliases=["permission-audit", "perms"])
    @checks.is_owner_or_admin_for("securite")
    async def security_permissions(self, ctx: commands.Context):
        """Lance l'audit avancé des permissions dangereuses."""
        await self._legacy(ctx, "permission-audit")

    @security.command(name="backup", aliases=["server-backup", "sauvegarde"])
    @checks.is_owner_or_admin_for("securite")
    async def security_backup(self, ctx: commands.Context, *, label: str = ""):
        """Sauvegarde rôles, catégories et salons du serveur."""
        await self._legacy(ctx, "server-backup", label=label)

    @security.command(name="restore", aliases=["server-restore", "restaurer"])
    @checks.is_owner_or_admin_for("securite")
    async def security_restore(self, ctx: commands.Context, backup_id: int):
        """Restaure les éléments manquants d'une sauvegarde serveur."""
        await self._legacy(ctx, "server-restore", backup_id)


def _hide_legacy_security_commands(bot: commands.Bot) -> None:
    for name in LEGACY_SECURITY_ROOTS:
        command = bot.get_command(name)
        if command is not None:
            command.hidden = True


def _remove_security_alias_collisions() -> None:
    # L'ancien +security-check pouvait réclamer l'alias +security via les couches de noms
    # familiers. V3 possède maintenant officiellement cette racine.
    language_runtime.EN_COMMAND_NAMES.pop("security-check", None)
    language_runtime.FR_COMMAND_NAMES.pop("security-check", None)
    try:
        from . import common_command_names
        common_command_names.PREFERRED_COMMAND_NAMES.pop("security-check", None)
    except Exception:
        pass


async def install(bot: commands.Bot) -> None:
    """Installe le centre V3 et masque les anciens noms déjà chargés."""
    if bot.get_cog("Automod") is None:
        return
    _remove_security_alias_collisions()
    if bot.get_cog("SecurityCommandCenter") is None:
        await bot.add_cog(SecurityCommandCenter(bot))
    _hide_legacy_security_commands(bot)
    bot._sentrix_security_command_center_v3 = True
