"""
Cog NIVEAUX / COMMUNAUTÉ.
/rank /leaderboard-levels /set-level-role /remove-level-role /level-roles
/set-xp /add-xp /reset-levels /profile /me /set-bio /voice-time
"""

import asyncio
import random
import time
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks

XP_MIN, XP_MAX = 10, 25
XP_COOLDOWN = 60


def xp_for_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100


def xp_bar(current: int, needed: int, length: int = 12) -> str:
    ratio = current / needed if needed else 0
    filled = max(0, min(length, round(length * ratio)))
    return "🟩" * filled + "⬛" * (length - filled)


class Levels(commands.Cog, name="Levels"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns: dict[tuple, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.guild.id, message.author.id)
        last = self.cooldowns.get(key, 0)
        if time.time() - last < XP_COOLDOWN:
            return
        self.cooldowns[key] = time.time()

        # On lance le traitement XP/niveau en tâche de fond : les écritures en base
        # (et leur commit disque) ne doivent jamais retarder le traitement du message
        # lui-même ni des autres commandes en cours. C'est ce qui causait la lenteur
        # ressentie sur un serveur actif.
        asyncio.create_task(self._process_xp(message))

    async def _process_xp(self, message: discord.Message):
        try:
            # Une seule requête (UPSERT) au lieu de deux : moins d'allers-retours vers la base.
            await self.bot.db.execute(
                "INSERT INTO message_counts (guild_id, user_id, count) VALUES (?, ?, 1) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1",
                (message.guild.id, message.author.id),
            )
            gained = random.randint(XP_MIN, XP_MAX)
            # get_level() s'occupe déjà de créer la ligne si besoin, pas la peine de le faire deux fois.
            row = await self.bot.db.get_level(message.guild.id, message.author.id)
            new_xp = row["xp"] + gained
            level = row["level"]
            needed = xp_for_level(level)
            leveled_up = False
            while new_xp >= needed:
                new_xp -= needed
                level += 1
                needed = xp_for_level(level)
                leveled_up = True
            await self.bot.db.execute(
                "UPDATE levels SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
                (new_xp, level, message.guild.id, message.author.id),
            )
            if leveled_up:
                conf = await self.bot.db.get_guild_config(message.guild.id)
                channel = message.guild.get_channel(conf["level_channel"]) if conf and conf["level_channel"] else message.channel
                if channel:
                    try:
                        await channel.send(embed=embeds.success(f"🎉 {message.author.mention} passe au niveau **{level}** !"))
                    except discord.HTTPException:
                        pass
                role_row = await self.bot.db.fetchone(
                    "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (message.guild.id, level)
                )
                if role_row:
                    role = message.guild.get_role(role_row["role_id"])
                    if role:
                        try:
                            await message.author.add_roles(role, reason=f"Niveau {level} atteint")
                        except discord.Forbidden:
                            pass
        except Exception:
            # Une erreur dans le traitement XP en tâche de fond ne doit jamais faire planter le bot.
            import logging
            logging.getLogger("discord-bot").exception("Erreur lors du traitement XP en tâche de fond")

    @commands.hybrid_command(name="rank", description="Afficher votre niveau ou celui d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def rank(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        row = await self.bot.db.get_level(ctx.guild.id, membre.id)
        needed = xp_for_level(row["level"])
        rank_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))",
            (ctx.guild.id, row["level"], row["level"], row["xp"]),
        )
        rank = (rank_row["n"] if rank_row else 0) + 1
        e = embeds.neutral(f"📈 Niveau de {membre.display_name}")
        e.add_field(name="Niveau", value=row["level"], inline=True)
        e.add_field(name="Classement", value=f"#{rank}", inline=True)
        e.add_field(name="Progression XP", value=f"{xp_bar(row['xp'], needed)}\n{row['xp']}/{needed} XP", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="leaderboard-levels", description="Afficher le classement des niveaux.")
    async def leaderboard_levels(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 10", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune donnée de niveau pour l'instant."))
        lines = []
        for i, r in enumerate(rows, 1):
            member = ctx.guild.get_member(r["user_id"])
            name = member.display_name if member else f"Utilisateur {r['user_id']}"
            lines.append(f"**{i}.** {name} — Niveau {r['level']} ({r['xp']} XP)")
        await ctx.send(embed=embeds.neutral("🏆 Classement des niveaux", "\n".join(lines)))

    @commands.hybrid_command(name="set-level-role", description="[Admin] Associer un rôle à un niveau.", with_app_command=False)
    @app_commands.describe(niveau="Le niveau requis", role="Le rôle à attribuer")
    @checks.is_owner_or_admin()
    async def set_level_role(self, ctx: commands.Context, niveau: int, role: discord.Role):
        await self.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (ctx.guild.id, niveau, role.id),
        )
        await ctx.send(embed=embeds.success(f"Le rôle {role.mention} sera attribué au niveau **{niveau}**."))

    @commands.hybrid_command(name="remove-level-role", description="[Admin] Retirer l'association d'un rôle de niveau.", with_app_command=False)
    @app_commands.describe(niveau="Le niveau concerné")
    @checks.is_owner_or_admin()
    async def remove_level_role(self, ctx: commands.Context, niveau: int):
        await self.bot.db.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (ctx.guild.id, niveau))
        await ctx.send(embed=embeds.success(f"Association de rôle retirée pour le niveau **{niveau}**."))

    @commands.hybrid_command(name="level-roles", description="Lister les rôles de niveau configurés.", with_app_command=False)
    async def level_roles(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun rôle de niveau configuré."))
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            lines.append(f"Niveau **{r['level']}** → {role.mention if role else 'Rôle supprimé'}")
        await ctx.send(embed=embeds.neutral("🎖️ Rôles de niveau", "\n".join(lines)))

    @commands.hybrid_command(name="set-xp", description="[Admin] Définir l'XP d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", xp="La valeur d'XP")
    @checks.is_owner_or_admin()
    async def set_xp(self, ctx: commands.Context, membre: discord.Member, xp: int):
        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        await self.bot.db.execute("UPDATE levels SET xp = ? WHERE guild_id = ? AND user_id = ?", (xp, ctx.guild.id, membre.id))
        await ctx.send(embed=embeds.success(f"XP de {membre.mention} défini à **{xp}**."))

    @commands.hybrid_command(name="add-xp", description="[Admin] Ajouter de l'XP à un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", xp="La quantité d'XP à ajouter")
    @checks.is_owner_or_admin()
    async def add_xp(self, ctx: commands.Context, membre: discord.Member, xp: int):
        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        await self.bot.db.execute(
            "UPDATE levels SET xp = xp + ? WHERE guild_id = ? AND user_id = ?", (xp, ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"**{xp} XP** ajoutés à {membre.mention}."))

    @commands.hybrid_command(name="reset-levels", description="[Admin] Réinitialiser tous les niveaux du serveur.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def reset_levels(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM levels WHERE guild_id = ?", (ctx.guild.id,))
        await ctx.send(embed=embeds.success("Tous les niveaux du serveur ont été réinitialisés."))

    @commands.hybrid_command(name="profile", description="Afficher votre profil communautaire.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def profile(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        level_row = await self.bot.db.get_level(ctx.guild.id, membre.id)
        bio_row = await self.bot.db.fetchone(
            "SELECT * FROM profiles WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        msg_row = await self.bot.db.fetchone(
            "SELECT count FROM message_counts WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        e = embeds.neutral(f"🪪 Profil de {membre.display_name}")
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="Niveau", value=level_row["level"], inline=True)
        e.add_field(name="Messages", value=msg_row["count"] if msg_row else 0, inline=True)
        e.add_field(name="Bio", value=(bio_row["bio"] if bio_row and bio_row["bio"] else "Aucune bio définie."), inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="me", description="Afficher toutes vos statistiques personnelles sur ce serveur.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def me(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author

        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        level_row = await self.bot.db.get_level(ctx.guild.id, membre.id)
        needed = xp_for_level(level_row["level"])
        rank_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))",
            (ctx.guild.id, level_row["level"], level_row["level"], level_row["xp"]),
        )
        rank = (rank_row["n"] if rank_row else 0) + 1

        msg_row = await self.bot.db.fetchone(
            "SELECT count FROM message_counts WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        voice_row = await self.bot.db.fetchone(
            "SELECT seconds FROM voice_totals WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        seconds = voice_row["seconds"] if voice_row else 0
        h, m = seconds // 3600, (seconds % 3600) // 60

        await self.bot.db.ensure_economy(ctx.guild.id, membre.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, membre.id)

        e = embeds.neutral(f"📋 Statistiques de {membre.display_name}")
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="📈 Niveau", value=str(level_row["level"]), inline=True)
        e.add_field(name="🏆 Classement", value=f"#{rank}", inline=True)
        e.add_field(name="💬 Messages envoyés", value=str(msg_row["count"] if msg_row else 0), inline=True)
        e.add_field(name="✨ Progression XP", value=f"{xp_bar(level_row['xp'], needed)}\n{level_row['xp']}/{needed} XP", inline=False)
        e.add_field(name="🔊 Temps en vocal", value=f"{h}h {m}m", inline=True)
        e.add_field(name="💰 Argent", value=f"{bal['cash']} 🪙 (+ {bal['bank']} 🏦 en banque)", inline=True)
        e.add_field(
            name="📅 Sur le serveur depuis",
            value=f"<t:{int(membre.joined_at.timestamp())}:D>" if membre.joined_at else "Inconnu",
            inline=True,
        )
        await ctx.send(embed=e)

    @commands.hybrid_command(name="set-bio", description="Définir votre biographie de profil.", with_app_command=False)
    @app_commands.describe(texte="Votre biographie (200 caractères max)")
    async def set_bio(self, ctx: commands.Context, *, texte: str):
        texte = texte[:200]
        await self.bot.db.execute(
            "INSERT INTO profiles (guild_id, user_id, bio) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET bio = excluded.bio",
            (ctx.guild.id, ctx.author.id, texte),
        )
        await ctx.send(embed=embeds.success("Votre bio a été mise à jour."))

    @commands.hybrid_command(name="voice-time", description="Afficher le temps passé en vocal par un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def voice_time(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        row = await self.bot.db.fetchone(
            "SELECT seconds FROM voice_totals WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        seconds = row["seconds"] if row else 0
        h, m = seconds // 3600, (seconds % 3600) // 60
        await ctx.send(embed=embeds.info(f"🔊 {membre.display_name} a passé **{h}h{m}m** en vocal."))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        if before.channel is None and after.channel is not None:
            self.bot._voice_join_times = getattr(self.bot, "_voice_join_times", {})
            self.bot._voice_join_times[member.id] = time.time()
        elif before.channel is not None and after.channel is None:
            join_times = getattr(self.bot, "_voice_join_times", {})
            start = join_times.pop(member.id, None)
            if start:
                elapsed = int(time.time() - start)
                await self.bot.db.execute(
                    "INSERT INTO voice_totals (guild_id, user_id, seconds) VALUES (?, ?, ?) "
                    "ON CONFLICT(guild_id, user_id) DO UPDATE SET seconds = seconds + excluded.seconds",
                    (member.guild.id, member.id, elapsed),
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
