"""
Cog INVITATIONS.
/invites (alias +i) /invite-leaderboard /invited-by

Détecte automatiquement quelle invitation a été utilisée à chaque arrivée (en comparant
le nombre d'utilisations avant/après), enregistre qui a invité qui, et suit les départs
pour distinguer les invitations "actives" des invitations "reparties".

⚠️ Détection de "doubles comptes" : Discord ne transmet JAMAIS l'adresse IP à un bot,
donc aucune détection fiable de multi-compte n'est possible. Ce cog applique seulement
une heuristique (plusieurs comptes très récents invités par la même personne en peu de
temps) qui peut se tromper — à traiter comme une alerte à vérifier, pas une preuve.
"""

import time

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, helpers

# Fenêtre et seuil de l'heuristique "comptes suspects" : si le même invitant amène au
# moins ce nombre de comptes créés depuis moins de 3 jours, en moins de 10 minutes.
SUSPECT_WINDOW = 600
SUSPECT_THRESHOLD = 3
SUSPECT_ACCOUNT_AGE_DAYS = 3


class Invites(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}
        self.recent_new_accounts: dict[tuple[int, int], list[float]] = {}

    async def cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in invites}
        except discord.Forbidden:
            self.invite_cache[guild.id] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    async def find_used_invite(self, guild: discord.Guild) -> discord.Invite | None:
        """Compare le nombre d'utilisations de chaque invitation avec le cache précédent :
        celle qui a augmenté est celle qui vient d'être utilisée. Nécessite que le bot ait
        la permission Gérer le serveur, sinon on ne peut simplement pas savoir (limite Discord)."""
        try:
            current = await guild.invites()
        except discord.Forbidden:
            return None
        cached = self.invite_cache.get(guild.id, {})
        used = None
        for inv in current:
            if (inv.uses or 0) > cached.get(inv.code, 0):
                used = inv
                break
        self.invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in current}
        return used

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        invite = await self.find_used_invite(guild)
        inviter_id = invite.inviter.id if invite and invite.inviter else None
        code = invite.code if invite else None
        await self.bot.db.record_invite_join(guild.id, member.id, inviter_id, code)

        if not inviter_id:
            return
        account_age_days = (discord.utils.utcnow() - member.created_at).days
        if account_age_days >= SUSPECT_ACCOUNT_AGE_DAYS:
            return

        key = (guild.id, inviter_id)
        t = time.time()
        hits = self.recent_new_accounts.setdefault(key, [])
        hits.append(t)
        self.recent_new_accounts[key] = [x for x in hits if t - x < SUSPECT_WINDOW]
        if len(self.recent_new_accounts[key]) >= SUSPECT_THRESHOLD:
            e = embeds.log_entry(
                "🕵️ Comptes suspects invités en rafale",
                config.COLOR_WARNING,
                cible=member,
                cible_label="👤 Dernier arrivant",
                extra={
                    "🔗 Invité par": f"<@{inviter_id}>\n`ID: {inviter_id}`",
                    "📊 Comptes très récents (< 3 jours) invités en 10 min": str(len(self.recent_new_accounts[key])),
                    "⚠️ Important": (
                        "Ceci est une estimation basée sur l'âge des comptes, PAS une preuve : "
                        "Discord ne transmet jamais l'adresse IP à un bot. Vérifiez manuellement "
                        "avant de sanctionner."
                    ),
                },
            )
            await helpers.send_log(self.bot, guild, "automod", e)
            self.recent_new_accounts[key] = []

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        await self.bot.db.mark_invite_left(member.guild.id, member.id)

    @commands.hybrid_command(
        name="invites",
        aliases=["i"],
        description="Afficher le nombre d'invitations d'un membre (actives / reparties).",
    )
    @app_commands.describe(membre="Le membre à consulter (vous par défaut)")
    async def invites_cmd(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        stats = await self.bot.db.get_invite_stats(ctx.guild.id, membre.id)
        e = embeds.neutral(
            f"📨 Invitations de {membre.display_name}",
            f"**{stats['active']}** invitation(s) active(s) sur **{stats['total']}** au total "
            f"({stats['left']} reparti(s) depuis).",
        )
        e.set_thumbnail(url=membre.display_avatar.url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="invite-leaderboard", description="Classement des membres ayant le plus invité.")
    async def invite_leaderboard(self, ctx: commands.Context):
        rows = await self.bot.db.get_invite_leaderboard(ctx.guild.id, 10)
        if not rows:
            return await ctx.send(embed=embeds.info("Personne n'a encore d'invitation enregistrée sur ce serveur."))
        lines = []
        for i, row in enumerate(rows, start=1):
            lines.append(f"**{i}.** <@{row['inviter_id']}> — **{row['active']}** active(s) ({row['total']} au total)")
        await ctx.send(embed=embeds.neutral("🏆 Classement des invitations", "\n".join(lines)))

    @commands.hybrid_command(name="invited-by", description="Voir qui a invité un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à consulter")
    async def invited_by(self, ctx: commands.Context, membre: discord.Member):
        row = await self.bot.db.get_invited_by(ctx.guild.id, membre.id)
        if not row or not row["inviter_id"]:
            return await ctx.send(embed=embeds.info(f"Je ne sais pas qui a invité {membre.mention} (invitation inconnue ou lien de vanité)."))
        await ctx.send(embed=embeds.neutral(
            "🔗 Origine de l'invitation",
            f"{membre.mention} a été invité par <@{row['inviter_id']}> le <t:{row['joined_at']}:D>.",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
