"""Commandes personnalisées à actions, gérées en « / » (30/10/2026).

Demande de Jayden, sur le modèle de DraftBot : le préfixe « + » est retiré
pour les commandes de SentriX mais reste pour les commandes PERSONNALISÉES du
serveur (préfixe réglable), et une commande peut enchaîner des actions :
message, ajout ou retrait de rôles, rôle temporaire, argent, XP. Le message
qui a déclenché la commande peut être supprimé.

La commande elle-même (nom, message) reste dans ``platform_custom_commands``
(cogs/platform_v4, partagée avec le dashboard). Ce module ajoute les actions
et l'exécute depuis ``PlatformV4.on_message`` (pas d'écouteur de plus).
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks
from utils.command_prefixes import get_custom_prefix

from utils import checks, helpers
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.custom-commands")

TABLES = (
    """
    CREATE TABLE IF NOT EXISTS custom_command_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        value INTEGER NOT NULL DEFAULT 0,
        duration_s INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_temp_roles (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        PRIMARY KEY (guild_id, user_id, role_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_command_settings (
        guild_id INTEGER PRIMARY KEY,
        delete_trigger INTEGER NOT NULL DEFAULT 0
    )
    """,
)

#: Au plus 10 actions par commande, comme un enchaînement lisible.
MAX_ACTIONS = 10
LIBELLES = {
    "role_add": "Ajouter le rôle",
    "role_remove": "Retirer le rôle",
    "role_temp": "Rôle temporaire",
    "money": "Ajouter de l'argent",
    "xp": "Ajouter de l'XP",
}


def decrire(action) -> str:
    kind, value, duree = action["kind"], int(action["value"]), int(action["duration_s"])
    if kind in ("role_add", "role_remove"):
        return f"{LIBELLES[kind]} <@&{value}>"
    if kind == "role_temp":
        return f"{LIBELLES[kind]} <@&{value}> pendant {helpers.format_duration(duree)}"
    if kind == "money":
        return f"{LIBELLES[kind]} : {value}"
    return f"{LIBELLES.get(kind, kind)} : {value}"


async def actions_de(db, guild_id: int, name: str) -> list:
    return list(await db.fetchall(
        "SELECT * FROM custom_command_actions WHERE guild_id=? AND name=? ORDER BY id",
        (int(guild_id), str(name)),
    ))


async def supprimer_declencheur(db, guild_id: int) -> bool:
    row = await db.fetchone("SELECT delete_trigger FROM custom_command_settings WHERE guild_id=?", (int(guild_id),))
    return bool(row and row["delete_trigger"])


async def executer_actions(bot, message: discord.Message, name: str) -> list[str]:
    """Exécute les actions de la commande pour l'auteur du message. Rend les échecs."""
    member = message.author
    guild = message.guild
    echecs: list[str] = []
    for action in await actions_de(bot.db, guild.id, name):
        kind, value = action["kind"], int(action["value"])
        try:
            if kind in ("role_add", "role_remove", "role_temp"):
                role = guild.get_role(value)
                if role is None or guild.me is None or role >= guild.me.top_role or role.managed:
                    echecs.append(f"rôle <@&{value}> introuvable ou au-dessus de SentriX")
                    continue
                if kind == "role_remove":
                    await member.remove_roles(role, reason=f"Commande personnalisée {name}")
                else:
                    await member.add_roles(role, reason=f"Commande personnalisée {name}")
                if kind == "role_temp":
                    await bot.db.execute(
                        "INSERT INTO custom_temp_roles(guild_id,user_id,role_id,expires_at) VALUES(?,?,?,?) "
                        "ON CONFLICT(guild_id,user_id,role_id) DO UPDATE SET expires_at=excluded.expires_at",
                        (guild.id, member.id, role.id, int(time.time()) + int(action["duration_s"])),
                    )
            elif kind == "money":
                from cogs.setup_v2_core import module_enabled
                if not await module_enabled(bot, guild.id, "economy"):
                    echecs.append("module économie désactivé")
                    continue
                await bot.db.add_balance(guild.id, member.id, value)
            elif kind == "xp":
                from cogs.setup_v2_core import module_enabled
                if not await module_enabled(bot, guild.id, "levels"):
                    echecs.append("module niveaux désactivé")
                    continue
                levels = bot.get_cog("Levels")
                if levels is None or not hasattr(levels, "_apply_xp_delta"):
                    echecs.append("module niveaux indisponible")
                    continue
                await levels._apply_xp_delta(guild.id, member.id, value)
        except discord.HTTPException:
            echecs.append(f"{LIBELLES.get(kind, kind)} refusé par Discord")
        except Exception:
            logger.exception("Action personnalisée %s échouée guild=%s", kind, guild.id)
            echecs.append(f"{LIBELLES.get(kind, kind)} impossible")
    return echecs


def _role_id(texte: str) -> int:
    chiffres = "".join(c for c in str(texte) if c.isdigit())
    return int(chiffres) if chiffres else 0


class CustomCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        db = getattr(self.bot, "db", None)
        if db is not None:
            for table in TABLES:
                await db.execute(table)
        # PlatformV4 (stockage + exécution des commandes personnalisées) n'était
        # chargé qu'au démarrage du dashboard web : sans lui, aucune commande
        # personnalisée ne répondait. Le chargeur du dashboard vérifie sa présence.
        if self.bot.get_cog("PlatformV4") is None:
            try:
                from cogs import platform_v4

                await platform_v4.setup(self.bot)
            except Exception:
                logger.exception("PlatformV4 indisponible : commandes personnalisées inactives.")
        self.retirer_roles_temporaires.start()

    def cog_unload(self) -> None:
        self.retirer_roles_temporaires.cancel()

    @tasks.loop(minutes=1)
    async def retirer_roles_temporaires(self) -> None:
        db = getattr(self.bot, "db", None)
        if db is None:
            return
        rows = await db.fetchall("SELECT * FROM custom_temp_roles WHERE expires_at <= ?", (int(time.time()),))
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            member = guild.get_member(int(row["user_id"])) if guild else None
            role = guild.get_role(int(row["role_id"])) if guild else None
            if member is not None and role is not None and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Rôle temporaire expiré (commande personnalisée)")
                except discord.HTTPException:
                    continue
            await db.execute(
                "DELETE FROM custom_temp_roles WHERE guild_id=? AND user_id=? AND role_id=?",
                (row["guild_id"], row["user_id"], row["role_id"]),
            )

    @retirer_roles_temporaires.before_loop
    async def _avant(self) -> None:
        await self.bot.wait_until_ready()

    def _platform(self):
        return self.bot.get_cog("PlatformV4")

    async def _commande(self, guild_id: int, nom: str):
        return await self.bot.db.fetchone(
            "SELECT * FROM platform_custom_commands WHERE guild_id=? AND name=?", (guild_id, nom.lower().lstrip("+"))
        )

    async def _ajouter_action(self, ctx, nom: str, kind: str, value: int, duree: int = 0):
        row = await self._commande(ctx.guild.id, nom)
        if row is None:
            return await panels.envoyer(ctx, panels.Panneau(
                titre="Commande introuvable", sous_titre=f"Créez-la d'abord avec `/custom create`.", kind="danger"))
        if len(await actions_de(self.bot.db, ctx.guild.id, row["name"])) >= MAX_ACTIONS:
            return await panels.envoyer(ctx, panels.Panneau(
                titre="Trop d'actions", sous_titre=f"{MAX_ACTIONS} actions au plus par commande.", kind="warning"))
        await self.bot.db.execute(
            "INSERT INTO custom_command_actions(guild_id,name,kind,value,duration_s) VALUES(?,?,?,?,?)",
            (ctx.guild.id, row["name"], kind, int(value), int(duree)),
        )
        await self._montrer(ctx, row["name"], titre="Action ajoutée")

    async def _montrer(self, ctx, nom: str, *, titre: str | None = None):
        row = await self._commande(ctx.guild.id, nom)
        if row is None:
            return await panels.envoyer(ctx, panels.Panneau(titre="Commande introuvable", sous_titre=nom, kind="danger"))
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        prefixe = await get_custom_prefix(self.bot, ctx.guild.id)
        actions = await actions_de(self.bot.db, ctx.guild.id, row["name"])
        lignes = [panels.Ligne("Déclencheur", f"`{prefixe}{row['name']}`"),
                  panels.Ligne("Message", str(row["response"])[:300])]
        for i, action in enumerate(actions, 1):
            lignes.append(panels.Ligne(f"Action {i}", decrire(action)))
        await panels.envoyer(ctx, panels.Panneau(
            titre=titre or f"Commande {prefixe}{row['name']}",
            sections=[panels.Section("Commande personnalisée", lignes)], kind="success" if titre else "info"))

    @commands.group(name="customcmd", invoke_without_command=True,
                    help="Commandes personnalisées du serveur (avec actions).")
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def customcmd(self, ctx: commands.Context):
        await self.customcmd_list(ctx)

    @customcmd.command(name="create", help="Créer ou modifier une commande personnalisée.")
    async def customcmd_create(self, ctx: commands.Context, nom: str, *, message: str):
        platform = self._platform()
        if platform is None:
            return await panels.envoyer(ctx, panels.Panneau(titre="Indisponible", sous_titre="Module des commandes personnalisées absent.", kind="danger"))
        existant = await self._commande(ctx.guild.id, nom)
        try:
            await platform.save_custom_command(ctx.guild, ctx.author.id, {
                "id": existant["id"] if existant else 0, "name": nom, "response": message,
            })
        except ValueError as exc:
            return await panels.envoyer(ctx, panels.Panneau(titre="Commande refusée", sous_titre=str(exc), kind="danger"))
        await self._montrer(ctx, nom, titre="Commande enregistrée")

    @customcmd.command(name="role-add", help="Action : donner un rôle à la personne.")
    async def customcmd_role_add(self, ctx: commands.Context, nom: str, role: discord.Role):
        await self._ajouter_action(ctx, nom, "role_add", role.id)

    @customcmd.command(name="role-remove", help="Action : retirer un rôle à la personne.")
    async def customcmd_role_remove(self, ctx: commands.Context, nom: str, role: discord.Role):
        await self._ajouter_action(ctx, nom, "role_remove", role.id)

    @customcmd.command(name="role-temp", help="Action : donner un rôle pour une durée (ex. 1h, 2j).")
    async def customcmd_role_temp(self, ctx: commands.Context, nom: str, role: discord.Role, duree: str):
        secondes = helpers.parse_duration(duree) or 0
        if secondes < 60 or secondes > 90 * 86400:
            return await panels.envoyer(ctx, panels.Panneau(titre="Durée invalide", sous_titre="Entre 1 min et 90 j (ex. 30m, 2h, 7j).", kind="danger"))
        await self._ajouter_action(ctx, nom, "role_temp", role.id, secondes)

    @customcmd.command(name="money", help="Action : ajouter de l'argent à la personne.")
    async def customcmd_money(self, ctx: commands.Context, nom: str, montant: int):
        if not 1 <= montant <= 1_000_000:
            return await panels.envoyer(ctx, panels.Panneau(titre="Montant invalide", sous_titre="Entre 1 et 1 000 000.", kind="danger"))
        await self._ajouter_action(ctx, nom, "money", montant)

    @customcmd.command(name="xp", help="Action : ajouter de l'XP à la personne.")
    async def customcmd_xp(self, ctx: commands.Context, nom: str, montant: int):
        if not 1 <= montant <= 100_000:
            return await panels.envoyer(ctx, panels.Panneau(titre="XP invalide", sous_titre="Entre 1 et 100 000.", kind="danger"))
        await self._ajouter_action(ctx, nom, "xp", montant)

    @customcmd.command(name="clear-actions", help="Retirer toutes les actions d'une commande.")
    async def customcmd_clear_actions(self, ctx: commands.Context, nom: str):
        await self.bot.db.execute("DELETE FROM custom_command_actions WHERE guild_id=? AND name=?",
                                  (ctx.guild.id, nom.lower().lstrip("+")))
        await self._montrer(ctx, nom, titre="Actions retirées")

    @customcmd.command(name="show", help="Voir une commande et ses actions.")
    async def customcmd_show(self, ctx: commands.Context, nom: str):
        await self._montrer(ctx, nom)

    @customcmd.command(name="list", help="Lister les commandes personnalisées.")
    async def customcmd_list(self, ctx: commands.Context):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        prefixe = await get_custom_prefix(self.bot, ctx.guild.id)
        rows = await self.bot.db.fetchall(
            "SELECT name FROM platform_custom_commands WHERE guild_id=? ORDER BY name", (ctx.guild.id,))
        efface = await supprimer_declencheur(self.bot.db, ctx.guild.id)
        lignes = [panels.Ligne("Préfixe", f"`{prefixe}`"),
                  panels.Ligne("Suppression du message", "activée" if efface else "désactivée")]
        texte = " · ".join(f"`{prefixe}{r['name']}`" for r in rows) or "Aucune commande personnalisée. `/custom create` pour en créer une."
        await panels.envoyer(ctx, panels.Panneau(
            titre="Commandes personnalisées", sous_titre=texte[:1500],
            sections=[panels.Section("Réglages", lignes)], kind="info"))

    @customcmd.command(name="delete", help="Supprimer une commande personnalisée.")
    async def customcmd_delete(self, ctx: commands.Context, nom: str):
        row = await self._commande(ctx.guild.id, nom)
        platform = self._platform()
        if row is None or platform is None:
            return await panels.envoyer(ctx, panels.Panneau(titre="Commande introuvable", sous_titre=nom, kind="danger"))
        await platform.delete_custom_command(ctx.guild.id, ctx.author.id, int(row["id"]))
        await self.bot.db.execute("DELETE FROM custom_command_actions WHERE guild_id=? AND name=?", (ctx.guild.id, row["name"]))
        await panels.envoyer(ctx, panels.Panneau(titre="Commande supprimée", sous_titre=f"`{row['name']}`", kind="success"))

    @customcmd.command(name="prefix", help="Préfixe des commandes personnalisées (ex. ! ou +).")
    async def customcmd_prefix(self, ctx: commands.Context, prefixe: str):
        prefixe = prefixe.strip()
        if not 1 <= len(prefixe) <= 3 or " " in prefixe or prefixe.startswith("/"):
            return await panels.envoyer(ctx, panels.Panneau(titre="Préfixe invalide", sous_titre="1 à 3 caractères, sans espace ni « / ».", kind="danger"))
        from utils.command_prefixes import set_custom_prefix
        await set_custom_prefix(self.bot, ctx.guild.id, prefixe)
        await panels.envoyer(
            ctx, panels.Panneau(
                titre="Préfixe des commandes personnalisées",
                sous_titre=f"Préfixe personnalisé : `{prefixe}`. Il ne lance aucune commande officielle.",
                kind="success",
            )
        )

    @customcmd.command(name="delete-trigger", help="Supprimer le message qui lance la commande (on/off).")
    async def customcmd_delete_trigger(self, ctx: commands.Context, etat: str):
        actif = etat.strip().casefold() in {"on", "oui", "activer", "true", "1"}
        await self.bot.db.execute(
            "INSERT INTO custom_command_settings(guild_id, delete_trigger) VALUES(?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET delete_trigger=excluded.delete_trigger",
            (ctx.guild.id, int(actif)),
        )
        await panels.envoyer(ctx, panels.Panneau(
            titre="Suppression du message " + ("activée" if actif else "désactivée"), kind="success" if actif else "neutral"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CustomCommands(bot))
