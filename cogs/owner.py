"""
Cog PROPRIÉTAIRE DU BOT.
/bl /blinfo /unbl /editbl /syncbl /unsyncbl /setstatus /status-rotate
/footer /theme /set-bot /set-nickname /bot-servers /bot-leave /alias

Commandes de gestion globale du bot, réservées au propriétaire (OWNER_IDS dans .env)
sauf mention contraire. Toutes fonctionnent uniquement avec le préfixe (+), pas en slash,
pour ne pas consommer inutilement la limite de 100 commandes slash de Discord — ce sont
des commandes techniques utilisées rarement, la version + suffit largement.
"""

import asyncio
import json
import re

import discord
from discord.ext import commands, tasks

from utils import embeds, checks

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
ACTIVITY_TYPES = {
    "playing": discord.ActivityType.playing,
    "streaming": discord.ActivityType.streaming,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
}


def parse_color(value: str) -> int | None:
    m = HEX_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1), 16)


async def fetch_image_bytes(url: str) -> bytes | None:
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception:
        return None


class Owner(commands.Cog, name="Owner"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rotate_index = 0
        self.rotate_task.start()

    def cog_unload(self):
        self.rotate_task.cancel()

    # ---------------------------------------------------------------- LISTE NOIRE D'UTILISATION DU BOT

    @commands.hybrid_command(
        name="bl",
        description="Liste noire GLOBALE d'utilisation du bot (ajouter, ou afficher la liste si aucun membre donné).",
        with_app_command=False,
    )
    @checks.is_bot_owner()
    async def bl(self, ctx: commands.Context, utilisateur: discord.User = None, *, raison: str = "Aucune raison fournie"):
        if utilisateur is None:
            rows = await self.bot.db.blacklist_list()
            if not rows:
                return await ctx.send(embed=embeds.info("Aucun utilisateur sur la liste noire du bot."))
            lines = [f"`{r['user_id']}` — {r['reason'] or 'Aucune raison'}" for r in rows[:25]]
            return await ctx.send(embed=embeds.neutral("🚫 Liste noire d'utilisation du bot", "\n".join(lines)))

        if utilisateur.id == ctx.author.id:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas vous blacklister vous-même."))
        await self.bot.db.blacklist_add(utilisateur.id, raison, ctx.author.id)
        self.bot.blacklist_cache[utilisateur.id] = raison

        # Protection maximale (dans la limite de ce que l'API Discord permet — aucun bot,
        # même le mien, ne peut voir ou bannir par adresse IP, cette donnée n'est jamais
        # transmise par Discord) : on bannit tout de suite ce membre partout où il est
        # déjà présent, ET on le rebannira automatiquement s'il essaie de rejoindre
        # n'importe quel autre serveur du bot plus tard (voir on_member_join ci-dessous).
        banned_in = []
        failed_in = []  # (nom du serveur, raison lisible) — pour expliquer clairement quand le ban échoue
        for guild in self.bot.guilds:
            member = guild.get_member(utilisateur.id)
            if not member:
                continue
            if not guild.me.guild_permissions.ban_members:
                failed_in.append((guild.name, "il me manque la permission **Bannir des membres**"))
                continue
            if member.top_role >= guild.me.top_role and member.id != guild.owner_id:
                failed_in.append((guild.name, "mon rôle est trop bas dans la hiérarchie par rapport au sien"))
                continue
            try:
                await guild.ban(member, reason=f"Liste noire du bot : {raison}")
                banned_in.append(guild.name)
                await asyncio.sleep(0.5)
            except discord.HTTPException as exc:
                failed_in.append((guild.name, f"erreur Discord ({exc})"))
                continue

        description = f"**{utilisateur}** ne peut plus utiliser aucune commande du bot, sur aucun serveur.\nRaison : {raison}"
        if banned_in:
            description += f"\n\n🔨 Banni automatiquement sur : {', '.join(banned_in)}"
        if failed_in:
            details = "\n".join(f"• **{name}** : {reason}" for name, reason in failed_in)
            description += f"\n\n⚠️ Pas banni sur (à corriger si besoin) :\n{details}"
        description += (
            "\n🛡️ S'il essaie de rejoindre un autre serveur où je suis présent (avec la permission "
            "Bannir et un rôle assez haut), il sera banni automatiquement dès son arrivée."
        )
        await ctx.send(embed=embeds.success(description, title="🚫 Ajouté à la liste noire"))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Protection renforcée de /bl : si un membre blacklisté (bot-wide) rejoint N'IMPORTE
        QUEL serveur où le bot est présent, il est banni immédiatement, avant de pouvoir agir."""
        row = await self.bot.db.blacklist_get(member.id)
        if not row:
            return
        if not member.guild.me.guild_permissions.ban_members:
            return
        try:
            await member.guild.ban(member, reason=f"Liste noire du bot (protection automatique) : {row['reason'] or 'Aucune raison'}")
        except discord.HTTPException:
            pass

    @commands.hybrid_command(name="blinfo", description="Afficher les infos de liste noire d'un utilisateur.", with_app_command=False)
    @checks.is_bot_owner()
    async def blinfo(self, ctx: commands.Context, utilisateur: discord.User):
        row = await self.bot.db.blacklist_get(utilisateur.id)
        if not row:
            return await ctx.send(embed=embeds.info(f"**{utilisateur}** n'est pas sur la liste noire du bot."))
        e = embeds.neutral(f"🚫 Liste noire — {utilisateur}")
        e.add_field(name="Raison", value=row["reason"] or "Aucune raison", inline=False)
        e.add_field(name="Ajouté par", value=f"<@{row['blacklisted_by']}>" if row["blacklisted_by"] else "Inconnu", inline=True)
        e.add_field(name="Date", value=f"<t:{row['blacklisted_at']}:f>" if row["blacklisted_at"] else "Inconnue", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="unbl", description="Retirer un utilisateur de la liste noire du bot.", with_app_command=False)
    @checks.is_bot_owner()
    async def unbl(self, ctx: commands.Context, utilisateur: discord.User):
        await self.bot.db.blacklist_remove(utilisateur.id)
        self.bot.blacklist_cache.pop(utilisateur.id, None)
        await ctx.send(embed=embeds.success(f"**{utilisateur}** peut de nouveau utiliser le bot."))

    @commands.hybrid_command(name="editbl", description="Modifier la raison de liste noire d'un utilisateur.", with_app_command=False)
    @checks.is_bot_owner()
    async def editbl(self, ctx: commands.Context, utilisateur: discord.User, *, raison: str):
        row = await self.bot.db.blacklist_get(utilisateur.id)
        if not row:
            return await ctx.send(embed=embeds.error(f"**{utilisateur}** n'est pas sur la liste noire."))
        await self.bot.db.blacklist_add(utilisateur.id, raison, row["blacklisted_by"] or ctx.author.id)
        self.bot.blacklist_cache[utilisateur.id] = raison
        await ctx.send(embed=embeds.success(f"Raison mise à jour pour **{utilisateur}** : {raison}"))

    @commands.hybrid_command(
        name="syncbl",
        description="Bannir sur ce serveur tous les membres actuellement sur la liste noire du bot.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin()
    async def syncbl(self, ctx: commands.Context):
        if not ctx.guild.me.guild_permissions.ban_members:
            return await ctx.send(embed=embeds.error("Il me manque la permission **Bannir des membres** pour faire ça."))
        rows = await self.bot.db.blacklist_list()
        if not rows:
            return await ctx.send(embed=embeds.info("La liste noire du bot est vide, rien à synchroniser."))
        banned = []
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            if not member:
                continue
            try:
                await ctx.guild.ban(member, reason=f"Synchronisation liste noire du bot : {row['reason']}")
                banned.append(str(member))
                await asyncio.sleep(0.5)
            except discord.HTTPException:
                continue
        if not banned:
            return await ctx.send(embed=embeds.info("Aucun membre de la liste noire n'a été trouvé sur ce serveur."))
        await ctx.send(embed=embeds.success(f"**{len(banned)}** membre(s) banni(s) :\n" + "\n".join(banned)))

    @commands.hybrid_command(
        name="unsyncbl",
        description="Débannir sur ce serveur les membres bannis via /syncbl.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin()
    async def unsyncbl(self, ctx: commands.Context):
        if not ctx.guild.me.guild_permissions.ban_members:
            return await ctx.send(embed=embeds.error("Il me manque la permission **Bannir des membres** pour faire ça."))
        rows = await self.bot.db.blacklist_list()
        blacklisted_ids = {r["user_id"] for r in rows}
        if not blacklisted_ids:
            return await ctx.send(embed=embeds.info("La liste noire du bot est vide."))
        unbanned = []
        async for ban_entry in ctx.guild.bans():
            if ban_entry.user.id in blacklisted_ids:
                try:
                    await ctx.guild.unban(ban_entry.user, reason="Désynchronisation liste noire du bot")
                    unbanned.append(str(ban_entry.user))
                    await asyncio.sleep(0.5)
                except discord.HTTPException:
                    continue
        if not unbanned:
            return await ctx.send(embed=embeds.info("Aucun membre banni via la liste noire n'a été trouvé sur ce serveur."))
        await ctx.send(embed=embeds.success(f"**{len(unbanned)}** membre(s) débanni(s) :\n" + "\n".join(unbanned)))

    # ---------------------------------------------------------------- PRÉSENCE / STATUT

    @commands.hybrid_command(
        name="setstatus",
        description="Changer le statut du bot (playing/streaming/listening/watching/competing).",
        with_app_command=False,
    )
    @checks.is_bot_owner()
    async def setstatus(self, ctx: commands.Context, type: str, *, texte: str):
        activity_type = ACTIVITY_TYPES.get(type.lower())
        if not activity_type:
            return await ctx.send(embed=embeds.error(
                "Type invalide. Utilisez : `playing`, `streaming`, `listening`, `watching` ou `competing`."
            ))
        await self.bot.db.set_setting("rotate_enabled", "0")
        await self.bot.change_presence(activity=discord.Activity(type=activity_type, name=texte))
        await ctx.send(embed=embeds.success(f"Statut changé : **{type}** {texte}"))

    @commands.hybrid_command(
        name="status-rotate",
        description="Gérer une rotation automatique de statuts (add/remove/list/start/stop).",
        with_app_command=False,
    )
    @checks.is_bot_owner()
    async def status_rotate(self, ctx: commands.Context, action: str, type: str = None, *, texte: str = None):
        action = action.lower()
        raw = await self.bot.db.get_setting("rotate_statuses", "[]")
        statuses = json.loads(raw)

        if action == "add":
            activity_type = ACTIVITY_TYPES.get((type or "").lower())
            if not activity_type or not texte:
                return await ctx.send(embed=embeds.error(
                    "Utilisez : `+status-rotate add <playing|streaming|listening|watching|competing> <texte>`."
                ))
            statuses.append({"type": type.lower(), "text": texte})
            await self.bot.db.set_setting("rotate_statuses", json.dumps(statuses))
            return await ctx.send(embed=embeds.success(f"Statut ajouté à la rotation ({len(statuses)} au total)."))

        if action == "remove":
            try:
                index = int(type) - 1
                removed = statuses.pop(index)
            except (TypeError, ValueError, IndexError):
                return await ctx.send(embed=embeds.error("Index invalide. Utilisez `+status-rotate list` pour voir les numéros."))
            await self.bot.db.set_setting("rotate_statuses", json.dumps(statuses))
            return await ctx.send(embed=embeds.success(f"Statut retiré : {removed['type']} {removed['text']}"))

        if action == "list":
            if not statuses:
                return await ctx.send(embed=embeds.info("Aucun statut configuré pour la rotation."))
            lines = [f"**{i+1}.** {s['type']} — {s['text']}" for i, s in enumerate(statuses)]
            return await ctx.send(embed=embeds.neutral("🔁 Rotation de statuts", "\n".join(lines)))

        if action == "start":
            if not statuses:
                return await ctx.send(embed=embeds.error("Ajoutez au moins un statut avec `+status-rotate add` avant de démarrer."))
            await self.bot.db.set_setting("rotate_enabled", "1")
            return await ctx.send(embed=embeds.success(f"Rotation démarrée entre **{len(statuses)}** statut(s) (change toutes les 60s)."))

        if action == "stop":
            await self.bot.db.set_setting("rotate_enabled", "0")
            return await ctx.send(embed=embeds.success("Rotation arrêtée."))

        await ctx.send(embed=embeds.error("Action invalide. Utilisez `add`, `remove`, `list`, `start` ou `stop`."))

    @tasks.loop(seconds=60)
    async def rotate_task(self):
        try:
            enabled = await self.bot.db.get_setting("rotate_enabled", "0")
            if enabled != "1":
                return
            raw = await self.bot.db.get_setting("rotate_statuses", "[]")
            statuses = json.loads(raw)
            if not statuses:
                return
            item = statuses[self.rotate_index % len(statuses)]
            self.rotate_index += 1
            activity_type = ACTIVITY_TYPES.get(item.get("type", "playing"), discord.ActivityType.playing)
            await self.bot.change_presence(activity=discord.Activity(type=activity_type, name=item["text"]))
        except Exception:
            pass

    @rotate_task.before_loop
    async def before_rotate(self):
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------------- IDENTITÉ / BRANDING

    @commands.hybrid_command(name="footer", description="Changer le texte du footer affiché sur tous les embeds.", with_app_command=False)
    @checks.is_bot_owner()
    async def footer(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.set_setting("footer_text", texte)
        embeds.set_footer_text(texte)
        await ctx.send(embed=embeds.success(f"Footer changé pour : **{texte}**"))

    @commands.hybrid_command(name="theme", description="Changer la couleur d'accent des embeds (code hex, ex: #5847EB).", with_app_command=False)
    @checks.is_bot_owner()
    async def theme(self, ctx: commands.Context, couleur: str):
        color = parse_color(couleur)
        if color is None:
            return await ctx.send(embed=embeds.error("Couleur invalide. Utilisez un code hex, ex : `#5847EB`."))
        await self.bot.db.set_setting("brand_color", str(color))
        embeds.set_brand_color(color)
        await ctx.send(embed=embeds.success(f"Thème changé.", title="🎨 Couleur mise à jour"))

    @commands.hybrid_command(
        name="set-bot",
        description="Changer l'identité globale du bot (name/avatar/banner).",
        with_app_command=False,
    )
    @checks.is_bot_owner()
    async def set_bot(self, ctx: commands.Context, champ: str, *, valeur: str = None):
        champ = champ.lower()
        if champ == "name":
            if not valeur:
                return await ctx.send(embed=embeds.error("Précisez le nouveau nom : `+set-bot name <nom>`."))
            try:
                await self.bot.user.edit(username=valeur)
            except discord.HTTPException as exc:
                return await ctx.send(embed=embeds.error(f"Impossible de changer le nom (Discord limite les changements fréquents) : {exc}"))
            return await ctx.send(embed=embeds.success(f"Nom du bot changé pour **{valeur}**."))

        if champ in ("avatar", "banner"):
            url = valeur
            if ctx.message.attachments:
                url = ctx.message.attachments[0].url
            if not url:
                return await ctx.send(embed=embeds.error(f"Fournissez une image en pièce jointe, ou une URL : `+set-bot {champ} <url>`."))
            data = await fetch_image_bytes(url)
            if not data:
                return await ctx.send(embed=embeds.error("Impossible de télécharger cette image."))
            try:
                if champ == "avatar":
                    await self.bot.user.edit(avatar=data)
                else:
                    await self.bot.user.edit(banner=data)
            except discord.HTTPException as exc:
                return await ctx.send(embed=embeds.error(
                    f"Échec du changement ({exc}). Pour la bannière, il faut parfois passer par le "
                    "Developer Portal si le compte du bot n'a pas le niveau requis."
                ))
            return await ctx.send(embed=embeds.success(f"{champ.capitalize()} du bot mis à jour."))

        await ctx.send(embed=embeds.error("Champ invalide. Utilisez `name`, `avatar` ou `banner`."))

    @commands.hybrid_command(name="set-nickname", description="Changer le pseudo du bot sur ce serveur.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def set_nickname(self, ctx: commands.Context, *, pseudo: str = None):
        try:
            await ctx.guild.me.edit(nick=pseudo)
        except discord.Forbidden:
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission de changer mon pseudo sur ce serveur."))
        await ctx.send(embed=embeds.success(f"Pseudo changé pour **{pseudo}**." if pseudo else "Pseudo réinitialisé."))

    # ---------------------------------------------------------------- SERVEURS DU BOT

    @commands.hybrid_command(
        name="bot-servers",
        description="Lister les serveurs du bot, obtenir le lien d'invitation, ou voir l'icône/bannière d'un serveur.",
        with_app_command=False,
    )
    @checks.is_bot_owner()
    async def list_bot_servers(self, ctx: commands.Context, action: str = "list", serveur_id: str = None):
        action = action.lower()

        if action == "list":
            lines = [f"`{g.id}` — **{g.name}** ({g.member_count} membres)" for g in self.bot.guilds[:25]]
            return await ctx.send(embed=embeds.neutral(f"🌐 Serveurs du bot ({len(self.bot.guilds)})", "\n".join(lines) or "Aucun."))

        if action == "invite":
            url = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(administrator=True))
            return await ctx.send(embed=embeds.neutral("🔗 Lien d'invitation du bot", url))

        if action in ("icon", "pic", "banner"):
            if not serveur_id or not serveur_id.isdigit():
                return await ctx.send(embed=embeds.error(f"Précisez l'ID du serveur : `+bot-servers {action} <id>`."))
            guild = self.bot.get_guild(int(serveur_id))
            if not guild:
                return await ctx.send(embed=embeds.error("Je ne suis pas sur ce serveur."))
            asset = guild.icon if action in ("icon", "pic") else guild.banner
            if not asset:
                return await ctx.send(embed=embeds.info(f"Ce serveur n'a pas de {'icône' if action != 'banner' else 'bannière'}."))
            e = embeds.neutral(f"{'🖼️' if action != 'banner' else '🎞️'} {guild.name}")
            e.set_image(url=asset.url)
            return await ctx.send(embed=e)

        await ctx.send(embed=embeds.error("Action invalide. Utilisez `list`, `invite`, `icon` ou `banner`."))

    @commands.hybrid_command(name="bot-leave", description="Faire quitter le bot d'un serveur (par ID).", with_app_command=False)
    @checks.is_bot_owner()
    async def make_bot_leave(self, ctx: commands.Context, serveur_id: str):
        if not serveur_id.isdigit():
            return await ctx.send(embed=embeds.error("ID de serveur invalide."))
        guild = self.bot.get_guild(int(serveur_id))
        if not guild:
            return await ctx.send(embed=embeds.error("Je ne suis pas sur ce serveur."))
        name = guild.name
        await guild.leave()
        await ctx.send(embed=embeds.success(f"J'ai quitté **{name}**."))

    # ---------------------------------------------------------------- ALIAS DE COMMANDES (préfixe)

    @commands.hybrid_command(
        name="alias",
        description="Gérer des alias de commandes personnalisés sur ce serveur (add/remove/list).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin()
    async def alias(self, ctx: commands.Context, action: str, alias: str = None, *, commande: str = None):
        action = action.lower()

        if action == "add":
            if not alias or not commande:
                return await ctx.send(embed=embeds.error("Utilisez : `+alias add <alias> <commande>`."))
            real_command = self.bot.get_command(commande)
            if not real_command:
                return await ctx.send(embed=embeds.error(f"La commande `{commande}` n'existe pas."))
            if self.bot.get_command(alias.lower()):
                return await ctx.send(embed=embeds.error(f"`{alias}` est déjà le nom d'une commande existante."))
            await self.bot.db.add_alias(ctx.guild.id, alias.lower(), real_command.qualified_name)
            return await ctx.send(embed=embeds.success(f"Alias `{ctx.prefix}{alias}` → `{ctx.prefix}{real_command.qualified_name}` créé."))

        if action == "remove":
            if not alias:
                return await ctx.send(embed=embeds.error("Utilisez : `+alias remove <alias>`."))
            await self.bot.db.remove_alias(ctx.guild.id, alias.lower())
            return await ctx.send(embed=embeds.success(f"Alias `{alias}` supprimé (s'il existait)."))

        if action == "list":
            rows = await self.bot.db.list_aliases(ctx.guild.id)
            if not rows:
                return await ctx.send(embed=embeds.info("Aucun alias configuré sur ce serveur."))
            lines = [f"`{ctx.prefix}{r['alias']}` → `{ctx.prefix}{r['command_name']}`" for r in rows]
            return await ctx.send(embed=embeds.neutral("🔤 Alias de commandes", "\n".join(lines)))

        await ctx.send(embed=embeds.error("Action invalide. Utilisez `add`, `remove` ou `list`."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
