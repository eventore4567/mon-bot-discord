"""
Cog VÉRIFICATION / RÔLES.
/verify-setup /verify-panel /rolepanel create|add|remove|list|delete
/reactionrole-add /reactionrole-remove /reactionrole-list (compatibilité)
/giverole /removerole /roleall /massrole
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks, design_system
from database.db import now


def _emoji_parts(raw: str) -> tuple[str, str, discord.PartialEmoji]:
    """Retourne (clé stable, affichage, emoji Discord), y compris pour les GIF animés."""
    emoji = discord.PartialEmoji.from_str(raw.strip())
    if not emoji.name:
        raise ValueError("emoji vide")
    if emoji.id:
        return f"custom:{emoji.id}", str(emoji), emoji
    return f"unicode:{emoji.name}", emoji.name, emoji


def _payload_emoji_key(emoji: discord.PartialEmoji) -> str:
    return f"custom:{emoji.id}" if emoji.id else f"unicode:{emoji.name}"


def _self_role_error(guild: discord.Guild, role: discord.Role) -> str | None:
    if role.is_default():
        return "Le rôle @everyone ne peut pas être distribué par réaction."
    if role.managed:
        return "Ce rôle est géré par Discord ou une intégration."
    bot_member = guild.me
    if bot_member is None or role >= bot_member.top_role:
        return "Placez ce rôle sous le rôle du bot dans Paramètres du serveur > Rôles."
    permissions = role.permissions
    if (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_roles
        or permissions.manage_channels
        or permissions.ban_members
        or permissions.kick_members
        or permissions.moderate_members
        or permissions.manage_webhooks
    ):
        return "Les rôles d'administration ou de modération ne peuvent pas être obtenus automatiquement."
    return None


class VerifyView(discord.ui.View):
    """Vue persistante affichée sur le panneau de vérification (bouton pour obtenir le rôle vérifié)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="● Je certifie avoir lu les règles", style=discord.ButtonStyle.success, custom_id="verify_panel_btn")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Verification" = interaction.client.get_cog("Verification")
        await cog.do_verify(interaction)


class Verification(commands.Cog, name="Verification"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _embed(self, guild_id: int, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed cohérent avec +designsetup (catégorie CATEGORY_STYLES["verification"])."""
        style = design_system.CATEGORY_STYLES["verification"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

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
        await interaction.response.send_message("● Vous avez été vérifié avec succès !", ephemeral=True)

    @commands.hybrid_command(name="verify-setup", description="Définir le rôle attribué lors de la vérification.")
    @app_commands.describe(role="Le rôle à attribuer aux membres vérifiés")
    @checks.is_owner_or_admin()
    async def verify_setup(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "verify_role", role.id)
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Rôle défini", description=f"Rôle de vérification défini sur {role.mention}.", kind="success"))

    @commands.hybrid_command(name="verify-panel", description="Poster le panneau de vérification dans ce salon.")
    @checks.is_owner_or_admin()
    async def verify_panel(self, ctx: commands.Context):
        e = await self._embed(ctx.guild.id, title="Vérification", description="Cliquez sur le bouton ci-dessous après avoir lu les règles du serveur pour obtenir l'accès complet.")
        await ctx.send(embed=e, view=VerifyView())

    async def _panel_and_message(self, guild: discord.Guild, message_id: int):
        panel = await self.bot.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (guild.id, message_id),
        )
        if not panel:
            return None, None
        channel = guild.get_channel(panel["channel_id"]) or self.bot.get_channel(panel["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(panel["channel_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return panel, None
        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return panel, None
        return panel, message

    async def _refresh_role_panel(self, guild: discord.Guild, panel, message: discord.Message):
        # La commande historique +reactionrole-add peut viser un message écrit par un
        # membre. Les réactions fonctionnent dessus, mais le bot ne doit pas tenter de
        # modifier un message qui ne lui appartient pas.
        if self.bot.user is None or message.author.id != self.bot.user.id:
            return
        rows = await self.bot.db.fetchall(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? ORDER BY rowid ASC",
            (guild.id, message.id),
        )
        description = panel["description"] or "Réagissez avec l'emoji correspondant pour recevoir ou retirer un rôle."
        lines = []
        for row in rows:
            role = guild.get_role(row["role_id"])
            role_text = role.mention if role else "Rôle supprimé"
            label = row["label"] or (role.name if role else "Indisponible")
            lines.append(f"{row['emoji']} **{label}** — {role_text}")
        listing = "\n".join(lines) if lines else "Aucun rôle n'est encore configuré."
        embed = await self._embed(
            guild.id,
            title=panel["title"],
            description=f"{description}\n\n**Rôles disponibles**\n{listing}"[:4096],
        )
        try:
            await message.edit(embed=embed)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return

    async def _register_panel_if_needed(self, ctx: commands.Context, message: discord.Message):
        panel = await self.bot.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message.id),
        )
        if panel:
            return panel
        title = message.embeds[0].title if message.embeds and message.embeds[0].title else "Choisissez vos rôles"
        await self.bot.db.execute(
            "INSERT INTO reaction_role_panels "
            "(guild_id, channel_id, message_id, title, description, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild.id,
                message.channel.id,
                message.id,
                title[:256],
                "Réagissez avec l'emoji correspondant pour recevoir ou retirer un rôle.",
                ctx.author.id,
                now(),
            ),
        )
        return await self.bot.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message.id),
        )

    async def _add_reaction_role(
        self,
        ctx: commands.Context,
        message: discord.Message,
        emoji_text: str,
        role: discord.Role,
        label: str = "",
    ):
        role_error = _self_role_error(ctx.guild, role)
        if role_error:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id, title="Rôle refusé", description=role_error, kind="danger"
            ))
        try:
            emoji_key, emoji_display, emoji = _emoji_parts(emoji_text)
        except ValueError:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id, title="Emoji invalide", description="Utilisez un emoji Unicode ou un emoji personnalisé du serveur.", kind="danger"
            ))
        count_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS total FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message.id),
        )
        existing = await self.bot.db.fetchone(
            "SELECT rowid FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji_key = ?",
            (ctx.guild.id, message.id, emoji_key),
        )
        if not existing and count_row and count_row["total"] >= 20:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id, title="Limite atteinte", description="Un panneau Discord accepte au maximum 20 réactions différentes.", kind="danger"
            ))
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id,
                title="Emoji refusé",
                description=f"Discord refuse cet emoji. Vérifiez qu'il appartient à un serveur accessible au bot et qu'il n'a pas été supprimé. (`{exc}`)",
                kind="danger",
            ))
        panel = await self._register_panel_if_needed(ctx, message)
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (ctx.guild.id, message.id, emoji_key, emoji_display),
        )
        await self.bot.db.execute(
            "INSERT INTO reaction_roles "
            "(guild_id, channel_id, message_id, emoji, emoji_key, role_id, label, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild.id,
                message.channel.id,
                message.id,
                emoji_display,
                emoji_key,
                role.id,
                (label.strip() or role.name)[:100],
                ctx.author.id,
            ),
        )
        await self._refresh_role_panel(ctx.guild, panel, message)
        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="Rôle ajouté au panneau",
            description=f"{emoji_display} donnera ou retirera automatiquement {role.mention}.",
            kind="success",
        ))

    @commands.group(name="rolepanel", aliases=["rolespanel", "role-menu"], invoke_without_command=True)
    async def rolepanel(self, ctx: commands.Context):
        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="Configuration des rôles automatiques",
            description=(
                "`+rolepanel create Choisissez vos rôles`\n"
                "`+rolepanel add <message_id> 🎁 @Ping-Giveaways`\n"
                "`+rolepanel add <message_id> 📣 @Ping-Annonces`\n"
                "`+rolepanel remove <message_id> 🎁`\n"
                "`+rolepanel list`\n"
                "`+rolepanel delete <message_id>`\n\n"
                "Ajouter la réaction donne le rôle ; retirer la réaction retire le rôle."
            ),
        ))

    @rolepanel.command(name="create", aliases=["creer"])
    @checks.is_owner_or_admin()
    async def rolepanel_create(self, ctx: commands.Context, *, title: str = "Choisissez vos rôles"):
        title = title.strip()[:256] or "Choisissez vos rôles"
        description = "Réagissez avec l'emoji correspondant pour recevoir ou retirer un rôle."
        embed = await self._embed(
            ctx.guild.id,
            title=title,
            description=f"{description}\n\n**Rôles disponibles**\nAucun rôle n'est encore configuré.",
        )
        message = await ctx.send(embed=embed)
        await self.bot.db.execute(
            "INSERT INTO reaction_role_panels "
            "(guild_id, channel_id, message_id, title, description, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ctx.guild.id, ctx.channel.id, message.id, title, description, ctx.author.id, now()),
        )
        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="Panneau créé",
            description=f"Identifiant du panneau : `{message.id}`\nAjoutez un rôle avec `+rolepanel add {message.id} 🎁 @rôle`.",
            kind="success",
        ), delete_after=45)

    @rolepanel.command(name="add", aliases=["ajouter"])
    @checks.is_owner_or_admin()
    async def rolepanel_add(
        self,
        ctx: commands.Context,
        message_id: int,
        emoji: str,
        role: discord.Role,
        *,
        label: str = "",
    ):
        panel, message = await self._panel_and_message(ctx.guild, message_id)
        if not panel:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id, title="Panneau inconnu", description="Créez d'abord le panneau avec `+rolepanel create`.", kind="danger"
            ))
        if message is None:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id, title="Message introuvable", description="Le message du panneau a été supprimé ou n'est plus accessible.", kind="danger"
            ))
        await self._add_reaction_role(ctx, message, emoji, role, label)

    @rolepanel.command(name="remove", aliases=["retirer"])
    @checks.is_owner_or_admin()
    async def rolepanel_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        try:
            emoji_key, emoji_display, parsed_emoji = _emoji_parts(emoji)
        except ValueError:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Emoji invalide", kind="danger"))
        panel, message = await self._panel_and_message(ctx.guild, message_id)
        if not panel:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Panneau inconnu", kind="danger"))
        cursor = await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (ctx.guild.id, message_id, emoji_key, emoji_display),
        )
        if cursor.rowcount < 1:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Association introuvable", kind="danger"))
        if message:
            try:
                await message.clear_reaction(parsed_emoji)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            await self._refresh_role_panel(ctx.guild, panel, message)
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Association retirée", kind="success"))

    @rolepanel.command(name="list", aliases=["liste"])
    @checks.is_owner_or_admin()
    async def rolepanel_list(self, ctx: commands.Context):
        panels = await self.bot.db.fetchall(
            "SELECT p.*, COUNT(r.message_id) AS role_count FROM reaction_role_panels p "
            "LEFT JOIN reaction_roles r ON r.guild_id = p.guild_id AND r.message_id = p.message_id "
            "WHERE p.guild_id = ? GROUP BY p.id ORDER BY p.id DESC",
            (ctx.guild.id,),
        )
        if not panels:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucun panneau configuré"))
        lines = [
            f"<#{panel['channel_id']}> — **{panel['title']}** — `{panel['message_id']}` — {panel['role_count']} rôle(s)"
            for panel in panels
        ]
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Panneaux de rôles", description="\n".join(lines)))

    @rolepanel.command(name="delete", aliases=["supprimer"])
    @checks.is_owner_or_admin()
    async def rolepanel_delete(self, ctx: commands.Context, message_id: int):
        panel, message = await self._panel_and_message(ctx.guild, message_id)
        if not panel:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Panneau inconnu", kind="danger"))
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message_id),
        )
        await self.bot.db.execute(
            "DELETE FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message_id),
        )
        if message:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Panneau supprimé", kind="success"))

    @commands.hybrid_command(name="reactionrole-add", description="Ajouter un rôle sur réaction à un message.")
    @app_commands.describe(message_id="L'identifiant du message", emoji="L'emoji à utiliser", role="Le rôle à attribuer")
    @checks.is_owner_or_admin()
    async def reactionrole_add(self, ctx: commands.Context, message_id: str, emoji: str, role: discord.Role):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Identifiant invalide", description="Identifiant de message invalide.", kind="danger"))
        try:
            msg = await ctx.channel.fetch_message(mid)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Message introuvable", description="Message introuvable dans ce salon.", kind="danger"))
        await self._add_reaction_role(ctx, msg, emoji, role)

    @commands.hybrid_command(name="reactionrole-remove", description="Retirer une association rôle/réaction.", with_app_command=False)
    @app_commands.describe(message_id="L'identifiant du message", emoji="L'emoji concerné")
    @checks.is_owner_or_admin()
    async def reactionrole_remove(self, ctx: commands.Context, message_id: str, emoji: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Identifiant invalide", description="Identifiant de message invalide.", kind="danger"))
        try:
            emoji_key, emoji_display, _ = _emoji_parts(emoji)
        except ValueError:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Emoji invalide", kind="danger"))
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (ctx.guild.id, mid, emoji_key, emoji_display),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Association retirée", kind="success"))

    @commands.hybrid_command(name="reactionrole-list", description="Lister les rôles sur réaction configurés.", with_app_command=False)
    async def reactionrole_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM reaction_roles WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucune association", description="Aucun rôle sur réaction configuré."))
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            lines.append(f"{r['emoji']} → {role.mention if role else 'Rôle supprimé'} (msg `{r['message_id']}`)")
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Rôles sur réaction", description="\n".join(lines)))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member is None or payload.member.bot:
            return
        emoji_key = _payload_emoji_key(payload.emoji)
        row = await self.bot.db.fetchone(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (payload.guild_id, payload.message_id, emoji_key, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(row["role_id"]) if guild else None
        if role:
            try:
                await payload.member.add_roles(role, reason="Rôle sur réaction")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        emoji_key = _payload_emoji_key(payload.emoji)
        row = await self.bot.db.fetchone(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (payload.guild_id, payload.message_id, emoji_key, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if member.bot:
            return
        role = guild.get_role(row["role_id"])
        if member and role:
            try:
                await member.remove_roles(role, reason="Retrait rôle sur réaction")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # Note : configurer le rôle automatique se fait via /setautorole (cog Configuration)
    # ou directement dans l'assistant /setup — pas besoin d'une commande en double ici.

    @commands.hybrid_command(name="giverole", aliases=["addrole"], description="Donner un rôle à un membre.")
    @app_commands.describe(membre="Le membre visé", role="Le rôle à donner")
    @checks.has_permission_or_modrole("manage_roles")
    async def giverole(self, ctx: commands.Context, membre: discord.Member, role: discord.Role):
        # check_hierarchy bloque toute action "sur soi-même" — pertinent pour une sanction
        # (on ne se bannit pas soi-même), mais pas pour un rôle : un membre autorisé à gérer
        # les rôles doit pouvoir se donner un rôle à lui-même (rôle couleur, self-service...).
        # On ne saute le contrôle QUE quand la cible est l'auteur ; toute autre cible reste
        # protégée par la hiérarchie normale.
        error = None
        if membre.id != ctx.author.id and isinstance(ctx.author, discord.Member):
            error = checks.check_hierarchy(ctx.author, membre)
        if error and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Action refusée", description=error, kind="danger"))
        try:
            await membre.add_roles(role, reason=f"Ajouté par {ctx.author}")
        except discord.Forbidden:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Permission manquante", description="Je n'ai pas la permission d'attribuer ce rôle.", kind="danger"))
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Rôle attribué", description=f"Rôle {role.mention} donné à {membre.mention}.", kind="success"))

    @commands.hybrid_command(name="removerole", aliases=["delrole"], description="Retirer un rôle à un membre.")
    @app_commands.describe(membre="Le membre visé", role="Le rôle à retirer")
    @checks.has_permission_or_modrole("manage_roles")
    async def removerole(self, ctx: commands.Context, membre: discord.Member, role: discord.Role):
        try:
            await membre.remove_roles(role, reason=f"Retiré par {ctx.author}")
        except discord.Forbidden:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Permission manquante", description="Je n'ai pas la permission de retirer ce rôle.", kind="danger"))
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Rôle retiré", description=f"Rôle {role.mention} retiré à {membre.mention}.", kind="success"))

    @commands.hybrid_command(name="roleall", description="Donner un rôle à tous les membres du serveur.", with_app_command=False)
    @app_commands.describe(role="Le rôle à attribuer à tout le monde")
    @checks.is_owner_or_admin()
    async def roleall(self, ctx: commands.Context, role: discord.Role):
        # Sur un très gros serveur (ex: 200 000 membres), traiter les membres un par un,
        # en attendant chaque requête l'une après l'autre, prendrait des HEURES (chaque
        # aller-retour vers Discord coûte ~200-300ms). On traite donc les membres par
        # petits lots envoyés en concurrence : Discord limite toujours le débit global,
        # mais son limiteur interne (discord.py) répartit ces lots bien plus efficacement
        # qu'une file strictement séquentielle.
        BATCH_SIZE = 15
        progress_msg = await ctx.send(embed=await self._embed(
            ctx.guild.id, title="Attribution en cours",
            description=(
                f"⏳ Attribution du rôle {role.mention} à ~{ctx.guild.member_count} membres en cours. "
                "Sur un très gros serveur, ça peut prendre un moment — un message de progression "
                "s'affichera régulièrement, merci de patienter..."
            ),
        ))
        count = 0
        failed = 0
        processed = 0

        async def apply_role(member: discord.Member):
            nonlocal count, failed
            if member.bot or role in member.roles:
                return
            try:
                await member.add_roles(role, reason=f"Attribution en masse par {ctx.author}")
                count += 1
            except discord.HTTPException:
                failed += 1

        batch = []
        async for member in ctx.guild.fetch_members(limit=None):
            batch.append(member)
            if len(batch) >= BATCH_SIZE:
                await asyncio.gather(*(apply_role(m) for m in batch))
                processed += len(batch)
                batch = []
                if processed % 2000 == 0:
                    try:
                        await progress_msg.edit(embed=await self._embed(
                            ctx.guild.id, title="Progression",
                            description=(
                                f"⏳ Progression : **{processed}/{ctx.guild.member_count}** membres traités, "
                                f"**{count}** rôle(s) attribué(s) jusqu'ici..."
                            ),
                        ))
                    except discord.HTTPException:
                        pass
        if batch:
            await asyncio.gather(*(apply_role(m) for m in batch))

        result = await self._embed(ctx.guild.id, title="Attribution terminée", description=f"Rôle {role.mention} attribué à **{count}** membre(s).", kind="success")
        if failed:
            result.add_field(name="⚠️ Échecs", value=f"{failed} membre(s) n'ont pas pu recevoir le rôle (permissions insuffisantes).", inline=False)
        await ctx.send(embed=result)

    @commands.hybrid_command(name="massrole", description="Ajouter ou retirer un rôle sur une liste de membres.", with_app_command=False)
    @app_commands.describe(role="Le rôle concerné", action="add ou remove", membres="Membres séparés par des espaces (mentions)")
    @app_commands.choices(action=[app_commands.Choice(name="Ajouter", value="add"), app_commands.Choice(name="Retirer", value="remove")])
    @checks.is_owner_or_admin()
    async def massrole(self, ctx: commands.Context, role: discord.Role, action: str, membres: commands.Greedy[discord.Member]):
        if not membres:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Membres manquants", description="Mentionnez au moins un membre.", kind="danger"))
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
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Massrole terminé", description=f"Rôle {role.mention} {verb} pour **{count}** membre(s).", kind="success"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
