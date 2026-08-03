"""
Cog VÉRIFICATION / RÔLES.
/verify-setup /verify-panel /reactionrole-add /reactionrole-remove /reactionrole-list
/giverole /removerole /roleall /massrole
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks


class VerifyView(discord.ui.View):
    """Vue persistante affichée sur le panneau de vérification (bouton pour obtenir le rôle vérifié)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Je certifie avoir lu les règles", style=discord.ButtonStyle.success, custom_id="verify_panel_btn")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Verification" = interaction.client.get_cog("Verification")
        await cog.do_verify(interaction)


class Verification(commands.Cog, name="Verification"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def do_verify(self, interaction: discord.Interaction):
        conf = await self.bot.db.get_guild_config(interaction.guild.id)
        role_id = conf["verify_role"] if conf else None
        if not role_id:
            return await interaction.response.send_message("Aucun rôle de vérification n'est configuré sur ce serveur.", ephemeral=True)
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.send_message("Le rôle de vérification configuré est introuvable.", ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message("Vous êtes déjà vérifié !", ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Vérification via panneau")
        except discord.Forbidden:
            return await interaction.response.send_message("Je n'ai pas la permission d'attribuer ce rôle.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO verified_users (guild_id, user_id, verified_at) VALUES (?, ?, strftime('%s','now'))",
            (interaction.guild.id, interaction.user.id),
        )
        await interaction.response.send_message("✅ Vous avez été vérifié avec succès !", ephemeral=True)

    @commands.hybrid_command(name="verify-setup", description="Définir le rôle attribué lors de la vérification.")
    @app_commands.describe(role="Le rôle à attribuer aux membres vérifiés")
    @checks.is_owner_or_admin()
    async def verify_setup(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "verify_role", role.id)
        await ctx.send(embed=embeds.success(f"Rôle de vérification défini sur {role.mention}."))

    @commands.hybrid_command(name="verify-panel", description="Poster le panneau de vérification dans ce salon.")
    @checks.is_owner_or_admin()
    async def verify_panel(self, ctx: commands.Context):
        e = embeds.neutral("✅ Vérification", "Cliquez sur le bouton ci-dessous après avoir lu les règles du serveur pour obtenir l'accès complet.")
        await ctx.send(embed=e, view=VerifyView())

    @commands.hybrid_command(name="reactionrole-add", description="Ajouter un rôle sur réaction à un message.")
    @app_commands.describe(message_id="L'identifiant du message", emoji="L'emoji à utiliser", role="Le rôle à attribuer")
    @checks.is_owner_or_admin()
    async def reactionrole_add(self, ctx: commands.Context, message_id: str, emoji: str, role: discord.Role):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("Identifiant de message invalide."))
        try:
            msg = await ctx.channel.fetch_message(mid)
        except discord.NotFound:
            return await ctx.send(embed=embeds.error("Message introuvable dans ce salon."))
        await msg.add_reaction(emoji)
        await self.bot.db.execute(
            "INSERT INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?)",
            (ctx.guild.id, mid, emoji, role.id),
        )
        await ctx.send(embed=embeds.success(f"Rôle {role.mention} lié à {emoji} sur ce message."))

    @commands.hybrid_command(name="reactionrole-remove", description="Retirer une association rôle/réaction.", with_app_command=False)
    @app_commands.describe(message_id="L'identifiant du message", emoji="L'emoji concerné")
    @checks.is_owner_or_admin()
    async def reactionrole_remove(self, ctx: commands.Context, message_id: str, emoji: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("Identifiant de message invalide."))
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?", (ctx.guild.id, mid, emoji)
        )
        await ctx.send(embed=embeds.success("Association retirée."))

    @commands.hybrid_command(name="reactionrole-list", description="Lister les rôles sur réaction configurés.", with_app_command=False)
    async def reactionrole_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM reaction_roles WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun rôle sur réaction configuré."))
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            lines.append(f"{r['emoji']} → {role.mention if role else 'Rôle supprimé'} (msg `{r['message_id']}`)")
        await ctx.send(embed=embeds.neutral("🎭 Rôles sur réaction", "\n".join(lines)))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member is None or payload.member.bot:
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(row["role_id"]) if guild else None
        if role:
            try:
                await payload.member.add_roles(role, reason="Rôle sur réaction")
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        row = await self.bot.db.fetchone(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(row["role_id"])
        if member and role:
            try:
                await member.remove_roles(role, reason="Retrait rôle sur réaction")
            except discord.Forbidden:
                pass

    # Note : configurer le rôle automatique se fait via /setautorole (cog Configuration)
    # ou directement dans l'assistant /setup — pas besoin d'une commande en double ici.

    @commands.hybrid_command(name="giverole", aliases=["addrole"], description="Donner un rôle à un membre.")
    @app_commands.describe(membre="Le membre visé", role="Le rôle à donner")
    @checks.has_permission_or_modrole("manage_roles")
    async def giverole(self, ctx: commands.Context, membre: discord.Member, role: discord.Role):
        error = checks.check_hierarchy(ctx.author, membre) if isinstance(ctx.author, discord.Member) else None
        if error and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=embeds.error(error))
        try:
            await membre.add_roles(role, reason=f"Ajouté par {ctx.author}")
        except discord.Forbidden:
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission d'attribuer ce rôle."))
        await ctx.send(embed=embeds.success(f"Rôle {role.mention} donné à {membre.mention}."))

    @commands.hybrid_command(name="removerole", aliases=["delrole"], description="Retirer un rôle à un membre.")
    @app_commands.describe(membre="Le membre visé", role="Le rôle à retirer")
    @checks.has_permission_or_modrole("manage_roles")
    async def removerole(self, ctx: commands.Context, membre: discord.Member, role: discord.Role):
        try:
            await membre.remove_roles(role, reason=f"Retiré par {ctx.author}")
        except discord.Forbidden:
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission de retirer ce rôle."))
        await ctx.send(embed=embeds.success(f"Rôle {role.mention} retiré à {membre.mention}."))

    @commands.hybrid_command(name="roleall", description="Donner un rôle à tous les membres du serveur.", with_app_command=False)
    @app_commands.describe(role="Le rôle à attribuer à tout le monde")
    @checks.is_owner_or_admin()
    async def roleall(self, ctx: commands.Context, role: discord.Role):
        # Sur un gros serveur (dizaines de milliers de membres), on avertit que
        # l'opération prendra du temps : Discord limite le rythme des requêtes,
        # donc on ne peut pas attribuer un rôle à 20 000 membres instantanément.
        estimate_min = max(1, ctx.guild.member_count // 1000)
        await ctx.send(embed=embeds.info(
            f"⏳ Attribution du rôle {role.mention} à ~{ctx.guild.member_count} membres. "
            f"Cela peut prendre plusieurs minutes (estimation : ~{estimate_min} min) sur un gros serveur, merci de patienter..."
        ))
        count = 0
        async for member in ctx.guild.fetch_members(limit=None):
            if role not in member.roles and not member.bot:
                try:
                    await member.add_roles(role, reason=f"Attribution en masse par {ctx.author}")
                    count += 1
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    await asyncio.sleep(2)
        await ctx.send(embed=embeds.success(f"Rôle {role.mention} attribué à **{count}** membres."))

    @commands.hybrid_command(name="massrole", description="Ajouter ou retirer un rôle sur une liste de membres.", with_app_command=False)
    @app_commands.describe(role="Le rôle concerné", action="add ou remove", membres="Membres séparés par des espaces (mentions)")
    @app_commands.choices(action=[app_commands.Choice(name="Ajouter", value="add"), app_commands.Choice(name="Retirer", value="remove")])
    @checks.is_owner_or_admin()
    async def massrole(self, ctx: commands.Context, role: discord.Role, action: str, membres: commands.Greedy[discord.Member]):
        if not membres:
            return await ctx.send(embed=embeds.error("Mentionnez au moins un membre."))
        count = 0
        for m in membres:
            try:
                if action == "add":
                    await m.add_roles(role, reason=f"Massrole par {ctx.author}")
                else:
                    await m.remove_roles(role, reason=f"Massrole par {ctx.author}")
                count += 1
            except discord.Forbidden:
                pass
        verb = "ajouté" if action == "add" else "retiré"
        await ctx.send(embed=embeds.success(f"Rôle {role.mention} {verb} pour **{count}** membre(s)."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
