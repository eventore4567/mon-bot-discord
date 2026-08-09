"""Centre de commandes Sécurité V3 pour SentriX.

Cette couche ne remplace pas les moteurs AutoMod/anti-nuke : elle remplace leur surface
utilisateur par une famille cohérente `+security ...`. Les anciennes commandes restent
chargées pour compatibilité avec les serveurs existants, mais sont masquées de +help.

Objectifs :
- une seule racine facile à retenir ;
- diagnostics et états lisibles ;
- FR/EN par serveur ;
- validation stricte des noms de filtres, domaines et états ;
- opérations anti-nuke/exemptions/PANIC réservées au propriétaire ;
- aucune régression sur la logique de sécurité déjà testée.
"""
from __future__ import annotations

import re
import time
from typing import Iterable

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
    "faible": {"antispam": 0, "antilink": 0, "antiinvite": 0, "antiraid": 0, "antiscam": 1, "antinuke": 1},
    "moyen": {"antispam": 1, "antilink": 0, "antiinvite": 1, "antiraid": 1, "antiscam": 1, "antinuke": 1},
    "eleve": {
        "antispam": 1, "antilink": 1, "antiinvite": 1, "antiraid": 1, "antiscam": 1,
        "antimention": 1, "antiaccount": 1, "antinuke": 1,
    },
}

LEGACY_SECURITY_ROOTS = {
    "antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji",
    "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
    "antinuke-whitelist-add", "antinuke-whitelist-remove", "antinuke-whitelist-list",
    "automod-status", "automod-escalation", "automod-exempt-role-add",
    "automod-exempt-role-remove", "automod-history", "security-check", "security-level",
    "security-repair", "blacklist-add", "blacklist-remove", "blacklist-list",
    "blacklist-user", "unblacklist-user", "blacklist-users", "whitelist-domain",
    "unwhitelist-domain", "lockdown-server", "unlock-server", "panic",
}

_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)


def _normalize(value: str) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _state(value: str) -> bool | None:
    raw = _normalize(value)
    if raw in {"on", "enable", "enabled", "actif", "active", "activer", "1", "true", "yes", "oui"}:
        return True
    if raw in {"off", "disable", "disabled", "inactif", "inactive", "desactiver", "désactiver", "0", "false", "no", "non"}:
        return False
    return None


def _clean_domain(value: str) -> str | None:
    value = _normalize(value)
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0].split(":", 1)[0].strip(".")
    return value if _DOMAIN_RE.fullmatch(value) else None


class SecurityCommandCenter(commands.Cog, name="Security"):
    """Interface canonique de toutes les commandes de sécurité SentriX."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _lang(self, ctx: commands.Context) -> str:
        return await language_runtime.get_language(self.bot, ctx.guild.id if ctx.guild else None)

    async def _t(self, ctx: commands.Context, fr: str, en: str) -> str:
        return en if await self._lang(ctx) == language_runtime.LANG_EN else fr

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
                    "Cette action peut modifier une protection critique. Seul le propriétaire du serveur ou du bot peut l'utiliser.",
                    "This action can change a critical protection. Only the server or bot owner can use it.",
                ),
                color=0xED4245,
            )
        )
        return False

    def _automod(self):
        return self.bot.get_cog("Automod")

    async def _conf(self, guild_id: int) -> dict:
        conf = await self.bot.db.get_automod(guild_id)
        return dict(conf) if conf else {}

    async def _set_filter(self, guild_id: int, field: str, enabled: bool) -> None:
        await self.bot.db.set_automod(guild_id, field, 1 if enabled else 0)
        automod = self._automod()
        if automod is not None:
            automod.automod_cache.pop(guild_id, None)

    async def _status_embed(self, ctx: commands.Context) -> discord.Embed:
        lang = await self._lang(ctx)
        conf = await self._conf(ctx.guild.id)
        since = int(time.time()) - 86400
        try:
            rows = await self.bot.db.automod_stats_since(ctx.guild.id, since)
            stats = {str(r["filter_name"]): int(r["c"]) for r in rows}
        except Exception:
            stats = {}

        on_count = sum(1 for key in SECURITY_FILTERS if bool(conf.get(key, 0)))
        total = len(SECURITY_FILTERS)
        level = str((await self.bot.db.get_guild_config(ctx.guild.id) or {}).get("security_level", "moyen")) if hasattr((await self.bot.db.get_guild_config(ctx.guild.id) or {}), "get") else "moyen"
        if lang == language_runtime.LANG_EN:
            title = "SENTRIX / SECURITY"
            desc = f"{on_count}/{total} protection modules enabled. {sum(stats.values())} AutoMod action(s) in the last 24 hours."
            enabled_word, disabled_word = "ON", "OFF"
            modules_title = "Protection modules"
            level_title = "Security level"
        else:
            title = "SENTRIX / SÉCURITÉ"
            desc = f"{on_count}/{total} modules de protection actifs. {sum(stats.values())} action(s) AutoMod sur les dernières 24 h."
            enabled_word, disabled_word = "ACTIF", "INACTIF"
            modules_title = "Modules de protection"
            level_title = "Niveau de sécurité"

        embed = discord.Embed(title=title, description=desc, color=0x6D5DFB, timestamp=discord.utils.utcnow())
        lines = []
        for key, labels in SECURITY_FILTERS.items():
            label = labels[1] if lang == language_runtime.LANG_EN else labels[0]
            state = enabled_word if conf.get(key, 0) else disabled_word
            hits = stats.get(key, 0)
            suffix = f" · {hits}/24h" if hits else ""
            lines.append(f"**{label}** — {state}{suffix}")
        embed.add_field(name=modules_title, value="\n".join(lines)[:1024], inline=False)
        embed.add_field(name=level_title, value=f"`{level}`", inline=True)
        embed.set_footer(text="SentriX Security V3")
        return embed

    @commands.group(name="security", aliases=["securite", "sécurité"], invoke_without_command=True)
    @commands.guild_only()
    @checks.is_owner_or_admin_for("securite")
    async def security(self, ctx: commands.Context):
        """Centre de contrôle de toute la sécurité du serveur."""
        embed = await self._status_embed(ctx)
        embed.add_field(
            name=await self._t(ctx, "Commandes principales", "Main commands"),
            value=await self._t(
                ctx,
                "`+security status` · `level` · `filter` · `scan` · `repair`\n"
                "`+security whitelist` · `blacklist` · `history` · `panic`",
                "`+security status` · `level` · `filter` · `scan` · `repair`\n"
                "`+security whitelist` · `blacklist` · `history` · `panic`",
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @security.command(name="status", aliases=["etat", "state", "overview"])
    async def security_status(self, ctx: commands.Context):
        """Affiche l'état complet des protections."""
        await ctx.send(embed=await self._status_embed(ctx))

    @security.command(name="filter", aliases=["module", "protection", "filtre"])
    async def security_filter(self, ctx: commands.Context, filtre: str | None = None, etat: str | None = None):
        """Affiche ou modifie un module de protection."""
        if not filtre:
            names = ", ".join(sorted(SECURITY_FILTERS))
            return await ctx.send(embed=discord.Embed(
                title=await self._t(ctx, "Modules disponibles", "Available modules"),
                description=f"`{names}`\n\n`+security filter <module> <on/off>`",
                color=0x6D5DFB,
            ))

        field = FILTER_ALIASES.get(_normalize(filtre))
        if field is None:
            return await ctx.send(embed=discord.Embed(
                title=await self._t(ctx, "Module inconnu", "Unknown module"),
                description=await self._t(ctx, "Utilise `+security filter` pour voir les modules disponibles.", "Use `+security filter` to list available modules."),
                color=0xED4245,
            ))

        conf = await self._conf(ctx.guild.id)
        if etat is None:
            label = SECURITY_FILTERS[field][1 if await self._lang(ctx) == language_runtime.LANG_EN else 0]
            enabled = bool(conf.get(field, 0))
            return await ctx.send(embed=discord.Embed(
                title=label,
                description=await self._t(ctx, f"État actuel : **{'ACTIF' if enabled else 'INACTIF'}**", f"Current state: **{'ON' if enabled else 'OFF'}**"),
                color=0x57F287 if enabled else 0x747F8D,
            ))

        enabled = _state(etat)
        if enabled is None:
            return await ctx.send(embed=discord.Embed(
                title=await self._t(ctx, "État invalide", "Invalid state"),
                description="`on` / `off`",
                color=0xED4245,
            ))
        if field == "antinuke" and not await self._critical_owner(ctx):
            return

        await self._set_filter(ctx.guild.id, field, enabled)
        label = SECURITY_FILTERS[field][1 if await self._lang(ctx) == language_runtime.LANG_EN else 0]
        await ctx.send(embed=discord.Embed(
            title=await self._t(ctx, "Protection mise à jour", "Protection updated"),
            description=f"**{label}** — {'ON' if enabled else 'OFF'}",
            color=0x57F287 if enabled else 0x747F8D,
        ))

    @security.command(name="level", aliases=["niveau"])
    async def security_level(self, ctx: commands.Context, niveau: str | None = None):
        """Applique un profil faible, moyen ou élevé."""
        if niveau is None:
            conf = await self.bot.db.get_guild_config(ctx.guild.id)
            try:
                current = conf["security_level"] or "moyen"
            except Exception:
                current = "moyen"
            return await ctx.send(embed=discord.Embed(
                title=await self._t(ctx, "Niveau de sécurité", "Security level"),
                description=f"**{current}**\n`+security level faible|moyen|eleve`",
                color=0x6D5DFB,
            ))

        level = LEVEL_ALIASES.get(_normalize(niveau))
        if level is None:
            return await ctx.send(embed=discord.Embed(
                title=await self._t(ctx, "Niveau invalide", "Invalid level"),
                description="`faible` · `moyen` · `eleve` / `low` · `medium` · `high`",
                color=0xED4245,
            ))
        await self.bot.db.set_guild_config(ctx.guild.id, "security_level", level)
        for field, value in SECURITY_PRESETS[level].items():
            await self._set_filter(ctx.guild.id, field, bool(value))
        await ctx.send(embed=discord.Embed(
            title=await self._t(ctx, "Profil de sécurité appliqué", "Security profile applied"),
            description=f"**{level.upper()}**",
            color=0x57F287,
        ))

    @security.command(name="scan", aliases=["check", "diagnostic", "audit"])
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
        missing = [name for name, ok in required.items() if not ok]
        active = sum(1 for key in SECURITY_FILTERS if conf.get(key, 0))
        score = round(((active / len(SECURITY_FILTERS)) * 70) + (((len(required) - len(missing)) / len(required)) * 30))
        color = 0x57F287 if score >= 85 else 0xFEE75C if score >= 60 else 0xED4245
        embed = discord.Embed(
            title=await self._t(ctx, "SENTRIX / ANALYSE SÉCURITÉ", "SENTRIX / SECURITY SCAN"),
            description=await self._t(ctx, f"Score estimé : **{score}/100**", f"Estimated score: **{score}/100**"),
            color=color,
        )
        embed.add_field(name=await self._t(ctx, "Modules actifs", "Active modules"), value=f"{active}/{len(SECURITY_FILTERS)}", inline=True)
        embed.add_field(name=await self._t(ctx, "Permissions manquantes", "Missing permissions"), value=str(len(missing)), inline=True)
        if missing:
            embed.add_field(name=await self._t(ctx, "À corriger", "Needs attention"), value="\n".join(f"- {x}" for x in missing), inline=False)
        embed.add_field(name=await self._t(ctx, "Action rapide", "Quick action"), value="`+security repair`", inline=False)
        await ctx.send(embed=embed)

    @security.command(name="repair", aliases=["fix", "reparer", "réparer"])
    async def security_repair(self, ctx: commands.Context):
        """Active le profil recommandé et vérifie les permissions du bot."""
        result = await apply_recommended_security(self.bot, ctx.guild)
        missing = result.get("missing_permissions", [])
        embed = discord.Embed(
            title=await self._t(ctx, "Sécurité réparée", "Security repaired"),
            description=await self._t(ctx, "Le profil recommandé SentriX est maintenant appliqué.", "The recommended SentriX profile is now applied."),
            color=0x57F287 if not missing else 0xFEE75C,
        )
        if missing:
            embed.add_field(name=await self._t(ctx, "Permissions manquantes", "Missing permissions"), value="\n".join(f"- {x}" for x in missing)[:1024], inline=False)
        await ctx.send(embed=embed)

    @security.command(name="history", aliases=["historique", "logs"])
    async def security_history(self, ctx: commands.Context, membre: discord.Member | None = None):
        """Affiche les dernières actions AutoMod."""
        if membre:
            rows = await self.bot.db.automod_history_for_user(ctx.guild.id, membre.id, limit=15)
        else:
            rows = await self.bot.db.automod_recent(ctx.guild.id, limit=15)
        if not rows:
            return await ctx.send(embed=discord.Embed(
                title=await self._t(ctx, "Historique sécurité", "Security history"),
                description=await self._t(ctx, "Aucune action enregistrée.", "No recorded action."),
                color=0x747F8D,
            ))
        lines = []
        for row in rows:
            who = f"<@{row['user_id']}>" if row["user_id"] else "-"
            lines.append(f"<t:{row['timestamp']}:R> · {who} · `{row['filter_name']}` → **{row['action']}**")
        await ctx.send(embed=discord.Embed(
            title=await self._t(ctx, "Historique sécurité", "Security history"),
            description="\n".join(lines)[:4000],
            color=0x6D5DFB,
        ))

    @security.command(name="panic", aliases=["emergency", "urgence"])
    async def security_panic(self, ctx: commands.Context, action: str = "status"):
        """Active, restaure ou affiche le mode d'urgence PANIC."""
        if not await self._critical_owner(ctx):
            return
        hardening = self.bot.get_cog("SecurityHardening")
        if hardening is None:
            return await ctx.send(embed=discord.Embed(
                title="PANIC",
                description=await self._t(ctx, "Le moteur d'urgence n'est pas chargé.", "Emergency engine is not loaded."),
                color=0xED4245,
            ))
        mode = _normalize(action)
        if mode in {"on", "start", "enable", "activer"}:
            return await hardening._activate_panic(ctx)
        if mode in {"off", "stop", "restore", "restaurer", "désactiver", "desactiver"}:
            return await hardening._deactivate_panic(ctx)
        if mode not in {"status", "state", "etat", "état"}:
            return await ctx.send(embed=discord.Embed(title="PANIC", description="`+security panic on|off|status`", color=0xED4245))
        row = await hardening._panic_row(ctx.guild.id)
        if row:
            desc = await self._t(ctx, f"ACTIF depuis <t:{row['created_at']}:R> · activé par <@{row['created_by']}>", f"ACTIVE since <t:{row['created_at']}:R> · enabled by <@{row['created_by']}>")
            color = 0xED4245
        else:
            desc = await self._t(ctx, "INACTIF", "INACTIVE")
            color = 0x57F287
        await ctx.send(embed=discord.Embed(title="SENTRIX / PANIC", description=desc, color=color))

    @security.group(name="whitelist", aliases=["allowlist", "liste-blanche"], invoke_without_command=True)
    async def security_whitelist(self, ctx: commands.Context):
        """Gère les exemptions anti-nuke, AutoMod et domaines autorisés."""
        await ctx.send(embed=discord.Embed(
            title=await self._t(ctx, "SENTRIX / LISTE BLANCHE", "SENTRIX / ALLOWLIST"),
            description=(
                "`+security whitelist user-add @membre`\n"
                "`+security whitelist user-remove @membre`\n"
                "`+security whitelist users`\n"
                "`+security whitelist role-add @role`\n"
                "`+security whitelist role-remove @role`\n"
                "`+security whitelist roles`\n"
                "`+security whitelist domain-add example.com`\n"
                "`+security whitelist domain-remove example.com`\n"
                "`+security whitelist domains`"
            ),
            color=0x6D5DFB,
        ))

    @security_whitelist.command(name="user-add", aliases=["add-user", "membre-add"])
    async def whitelist_user_add(self, ctx: commands.Context, membre: discord.Member):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.execute("INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, membre.id))
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Exemption anti-nuke ajoutée", "Anti-nuke exemption added"), description=membre.mention, color=0x57F287))

    @security_whitelist.command(name="user-remove", aliases=["remove-user", "membre-remove"])
    async def whitelist_user_remove(self, ctx: commands.Context, membre: discord.Member):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.execute("DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id))
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Exemption anti-nuke retirée", "Anti-nuke exemption removed"), description=membre.mention, color=0x57F287))

    @security_whitelist.command(name="users", aliases=["members", "membres"])
    async def whitelist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT user_id FROM antinuke_whitelist WHERE guild_id = ? ORDER BY user_id", (ctx.guild.id,))
        text = "\n".join(f"<@{r['user_id']}> · `{r['user_id']}`" for r in rows) if rows else await self._t(ctx, "Aucun membre exempté.", "No exempted member.")
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Exemptions anti-nuke", "Anti-nuke exemptions"), description=text[:4000], color=0x6D5DFB))

    @security_whitelist.command(name="role-add", aliases=["add-role"])
    async def whitelist_role_add(self, ctx: commands.Context, role: discord.Role):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.add_automod_exempt_role(ctx.guild.id, role.id)
        automod = self._automod()
        if automod is not None:
            automod.exempt_roles_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Rôle exempté", "Role exempted"), description=role.mention, color=0x57F287))

    @security_whitelist.command(name="role-remove", aliases=["remove-role"])
    async def whitelist_role_remove(self, ctx: commands.Context, role: discord.Role):
        if not await self._critical_owner(ctx):
            return
        await self.bot.db.remove_automod_exempt_role(ctx.guild.id, role.id)
        automod = self._automod()
        if automod is not None:
            automod.exempt_roles_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Exemption de rôle retirée", "Role exemption removed"), description=role.mention, color=0x57F287))

    @security_whitelist.command(name="roles")
    async def whitelist_roles(self, ctx: commands.Context):
        rows = await self.bot.db.list_automod_exempt_roles(ctx.guild.id)
        text = "\n".join(f"<@&{r['role_id']}> · `{r['role_id']}`" for r in rows) if rows else await self._t(ctx, "Aucun rôle exempté.", "No exempted role.")
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Rôles exemptés", "Exempted roles"), description=text[:4000], color=0x6D5DFB))

    @security_whitelist.command(name="domain-add", aliases=["add-domain", "domaine-add"])
    async def whitelist_domain_add(self, ctx: commands.Context, domaine: str):
        domain = _clean_domain(domaine)
        if domain is None:
            return await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Domaine invalide", "Invalid domain"), description="`example.com`", color=0xED4245))
        await self.bot.db.execute("INSERT OR IGNORE INTO whitelist_domains (guild_id, domain) VALUES (?, ?)", (ctx.guild.id, domain))
        automod = self._automod()
        if automod is not None:
            automod.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Domaine autorisé", "Domain allowed"), description=f"`{domain}`", color=0x57F287))

    @security_whitelist.command(name="domain-remove", aliases=["remove-domain", "domaine-remove"])
    async def whitelist_domain_remove(self, ctx: commands.Context, domaine: str):
        domain = _clean_domain(domaine)
        if domain is None:
            return await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Domaine invalide", "Invalid domain"), description="`example.com`", color=0xED4245))
        await self.bot.db.execute("DELETE FROM whitelist_domains WHERE guild_id = ? AND domain = ?", (ctx.guild.id, domain))
        automod = self._automod()
        if automod is not None:
            automod.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Domaine retiré", "Domain removed"), description=f"`{domain}`", color=0x57F287))

    @security_whitelist.command(name="domains", aliases=["domain-list", "domaines"])
    async def whitelist_domains(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT domain FROM whitelist_domains WHERE guild_id = ? ORDER BY domain", (ctx.guild.id,))
        text = "\n".join(f"`{r['domain']}`" for r in rows) if rows else await self._t(ctx, "Aucun domaine autorisé.", "No allowed domain.")
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Domaines autorisés", "Allowed domains"), description=text[:4000], color=0x6D5DFB))

    @security.group(name="blacklist", aliases=["blocklist", "liste-noire"], invoke_without_command=True)
    async def security_blacklist(self, ctx: commands.Context):
        """Gère les mots et utilisateurs bloqués."""
        await ctx.send(embed=discord.Embed(
            title=await self._t(ctx, "SENTRIX / LISTE NOIRE", "SENTRIX / BLOCKLIST"),
            description=(
                "`+security blacklist word-add <mot/phrase>`\n"
                "`+security blacklist word-remove <mot/phrase>`\n"
                "`+security blacklist words`\n"
                "`+security blacklist user-add @membre [raison]`\n"
                "`+security blacklist user-remove @membre`\n"
                "`+security blacklist users`"
            ),
            color=0x6D5DFB,
        ))

    @security_blacklist.command(name="word-add", aliases=["add-word", "mot-add"])
    async def blacklist_word_add(self, ctx: commands.Context, *, mot: str):
        word = " ".join(mot.casefold().split())[:200]
        if not word:
            return
        exists = await self.bot.db.fetchone("SELECT 1 FROM blacklist_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, word))
        if not exists:
            await self.bot.db.execute("INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)", (ctx.guild.id, word))
        automod = self._automod()
        if automod is not None:
            automod.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Mot bloqué", "Blocked word"), description=f"`{word}`", color=0x57F287))

    @security_blacklist.command(name="word-remove", aliases=["remove-word", "mot-remove"])
    async def blacklist_word_remove(self, ctx: commands.Context, *, mot: str):
        word = " ".join(mot.casefold().split())[:200]
        await self.bot.db.execute("DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, word))
        automod = self._automod()
        if automod is not None:
            automod.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Mot débloqué", "Word unblocked"), description=f"`{word}`", color=0x57F287))

    @security_blacklist.command(name="words", aliases=["word-list", "mots"])
    async def blacklist_words(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ? ORDER BY word", (ctx.guild.id,))
        text = " · ".join(f"`{r['word']}`" for r in rows) if rows else await self._t(ctx, "Aucun mot bloqué.", "No blocked word.")
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Mots bloqués", "Blocked words"), description=text[:4000], color=0x6D5DFB))

    @security_blacklist.command(name="user-add", aliases=["add-user", "membre-add"])
    async def blacklist_user_add(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            return await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Action refusée", "Action denied"), description=err, color=0xED4245))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist_users (guild_id, user_id, reason) VALUES (?, ?, ?)",
            (ctx.guild.id, membre.id, raison[:500]),
        )
        automod = self._automod()
        if automod is not None:
            automod.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Utilisateur bloqué", "User blocked"), description=f"{membre.mention}\n{raison[:1000]}", color=0x57F287))

    @security_blacklist.command(name="user-remove", aliases=["remove-user", "membre-remove"])
    async def blacklist_user_remove(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute("DELETE FROM blacklist_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id))
        automod = self._automod()
        if automod is not None:
            automod.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Utilisateur débloqué", "User unblocked"), description=membre.mention, color=0x57F287))

    @security_blacklist.command(name="users", aliases=["members", "membres"])
    async def blacklist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT user_id, reason FROM blacklist_users WHERE guild_id = ? ORDER BY user_id", (ctx.guild.id,))
        if not rows:
            text = await self._t(ctx, "Aucun utilisateur bloqué.", "No blocked user.")
        else:
            text = "\n".join(f"<@{r['user_id']}> · `{r['user_id']}` — {r['reason'] or '-'}" for r in rows[:30])
        await ctx.send(embed=discord.Embed(title=await self._t(ctx, "Utilisateurs bloqués", "Blocked users"), description=text[:4000], color=0x6D5DFB))


def _hide_legacy_security_commands(bot: commands.Bot) -> None:
    """Conserve les anciens noms comme compatibilité silencieuse."""
    for name in LEGACY_SECURITY_ROOTS:
        command = bot.get_command(name)
        if command is not None:
            command.hidden = True


async def install(bot: commands.Bot) -> None:
    if bot.get_cog("Automod") is None:
        return
    if bot.get_cog("Security") is None:
        await bot.add_cog(SecurityCommandCenter(bot))
    _hide_legacy_security_commands(bot)
    bot._sentrix_security_command_center_v3 = True
