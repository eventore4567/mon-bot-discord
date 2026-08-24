"""Community+ parity pack for SentriX.

Adds the community features SentriX did not already have: anonymous confessions,
ghost-ping logging, booster rewards, protected-role anti-ping, attachment-only
channels, role nickname prefixes, auto reactions, trigger replies, Roblox lookup
and recruitment/application panels.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import sys
import time
from collections import OrderedDict, deque

import aiohttp
import discord
from discord.ext import commands

log = logging.getLogger("sentrix.community_plus")
PURPLE, GREEN, RED, ORANGE = 0x7657FF, 0x2FBF71, 0xED4245, 0xF0B232


def emb(title: str, text: str = "", color: int = PURPLE) -> discord.Embed:
    e = discord.Embed(title=f"SentriX • {title}", description=text or None, colour=color)
    e.set_footer(text="SentriX • Community+")
    return e


def ch(guild: discord.Guild | None, cid):
    return guild.get_channel(int(cid)) if guild and cid else None


class ConfessionModal(discord.ui.Modal, title="Confession anonyme"):
    text = discord.ui.TextInput(label="Ta confession", style=discord.TextStyle.paragraph, min_length=2, max_length=1800)
    def __init__(self, cog):
        super().__init__(timeout=300); self.cog = cog
    async def on_submit(self, it: discord.Interaction):
        await self.cog.send_confession(it, str(self.text.value))


class ConfessionView(discord.ui.View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    @discord.ui.button(label="Envoyer une confession", style=discord.ButtonStyle.primary, custom_id="sentrix:cp:confess")
    async def submit(self, it: discord.Interaction, _):
        cog = self.bot.get_cog("CosmosParity")
        if not cog: return await it.response.send_message("Module indisponible.", ephemeral=True)
        await it.response.send_modal(ConfessionModal(cog))


class ApplicationModal(discord.ui.Modal):
    def __init__(self, cog, title: str, questions: list[str]):
        super().__init__(title=title[:45], timeout=600); self.cog = cog; self.questions = questions[:5]; self.fields = []
        for q in self.questions:
            field = discord.ui.TextInput(label=q[:45], style=discord.TextStyle.paragraph, max_length=800)
            self.fields.append(field); self.add_item(field)
    async def on_submit(self, it: discord.Interaction):
        await self.cog.send_application(it, self.questions, [str(x.value) for x in self.fields])


class ApplicationView(discord.ui.View):
    def __init__(self, bot): super().__init__(timeout=None); self.bot = bot
    @discord.ui.button(label="Postuler", style=discord.ButtonStyle.success, custom_id="sentrix:cp:apply")
    async def submit(self, it: discord.Interaction, _):
        if not it.guild: return await it.response.send_message("Serveur uniquement.", ephemeral=True)
        cog = self.bot.get_cog("CosmosParity")
        cfg = await cog.cfg(it.guild.id, "application") if cog else None
        if not cfg: return await it.response.send_message("Les candidatures ne sont pas configurées.", ephemeral=True)
        qs = await cog.rules(it.guild.id, "appq")
        questions = [r["value"] for r in qs][:5] or ["Pourquoi veux-tu rejoindre l'équipe ?", "Quelle est ton expérience ?", "Quelles sont tes disponibilités ?"]
        await it.response.send_modal(ApplicationModal(cog, cfg.get("title", "Candidature"), questions))


class CosmosParity(commands.Cog, name="CosmosParity"):
    def __init__(self, bot):
        self.bot = bot; self.ghost = OrderedDict(); self.strikes = {}; self.http = None

    async def cog_load(self):
        await self.bot.db.execute("CREATE TABLE IF NOT EXISTS sx_cp_config (guild_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(guild_id,key))")
        await self.bot.db.execute("CREATE TABLE IF NOT EXISTS sx_cp_rules (guild_id INTEGER NOT NULL, kind TEXT NOT NULL, key1 TEXT NOT NULL, key2 TEXT NOT NULL DEFAULT '', value TEXT NOT NULL DEFAULT '', PRIMARY KEY(guild_id,kind,key1,key2))")
        runtime = sys.modules.get("__main__")
        if runtime:
            for attr in ("PUBLIC_COMMANDS", "KNOWN_PERMISSION_COMMANDS"):
                old = getattr(runtime, attr, frozenset()); setattr(runtime, attr, frozenset(set(old) | {"confess", "roblox"}))
        self.bot.add_view(ConfessionView(self.bot)); self.bot.add_view(ApplicationView(self.bot))
        try:
            from . import utility
            utility.CATEGORY_LABELS.setdefault("CosmosParity", "Communauté+")
        except Exception: pass

    async def cog_unload(self):
        if self.http and not self.http.closed: await self.http.close()

    async def cfg(self, gid: int, key: str):
        row = await self.bot.db.fetchone("SELECT value FROM sx_cp_config WHERE guild_id=? AND key=?", (gid, key))
        if not row: return None
        try: return json.loads(row["value"])
        except Exception: return None

    async def setcfg(self, gid: int, key: str, value):
        data = json.dumps(value, ensure_ascii=False)
        await self.bot.db.execute("INSERT OR REPLACE INTO sx_cp_config(guild_id,key,value) VALUES(?,?,?)", (gid, key, data))

    async def rules(self, gid: int, kind: str):
        return await self.bot.db.fetchall("SELECT key1,key2,value FROM sx_cp_rules WHERE guild_id=? AND kind=?", (gid, kind))

    async def rule_add(self, gid: int, kind: str, key1, key2="", value=""):
        await self.bot.db.execute("INSERT OR REPLACE INTO sx_cp_rules(guild_id,kind,key1,key2,value) VALUES(?,?,?,?,?)", (gid, kind, str(key1), str(key2), str(value)))

    async def rule_del(self, gid: int, kind: str, key1, key2=None):
        if key2 is None: await self.bot.db.execute("DELETE FROM sx_cp_rules WHERE guild_id=? AND kind=? AND key1=?", (gid, kind, str(key1)))
        else: await self.bot.db.execute("DELETE FROM sx_cp_rules WHERE guild_id=? AND kind=? AND key1=? AND key2=?", (gid, kind, str(key1), str(key2)))

    @commands.command(name="confessionsetup")
    @commands.has_permissions(manage_guild=True)
    async def confessionsetup(self, ctx, channel: discord.TextChannel, logs: discord.TextChannel | None = None):
        await self.setcfg(ctx.guild.id, "confession", {"channel": channel.id, "logs": logs.id if logs else 0})
        await ctx.send(embed=emb("Confessions configurées", f"Publication : {channel.mention}\nLogs privés : {logs.mention if logs else 'désactivés'}", GREEN))

    @commands.command(name="confessionpanel")
    @commands.has_permissions(manage_guild=True)
    async def confessionpanel(self, ctx):
        await ctx.send(embed=emb("Confessions anonymes", "Clique sur le bouton pour envoyer une confession. Ton identité n'est jamais affichée publiquement."), view=ConfessionView(self.bot))

    @commands.command(name="confess")
    async def confess(self, ctx, *, text: str):
        class FakeResponse:
            async def send_message(_, content=None, **kwargs): await ctx.send(content or "Envoyé.")
        class FakeIT:
            guild, user, response = ctx.guild, ctx.author, FakeResponse()
        await self.send_confession(FakeIT(), text)

    async def send_confession(self, it, text: str):
        if not it.guild: return await it.response.send_message("Serveur uniquement.", ephemeral=True)
        cfg = await self.cfg(it.guild.id, "confession")
        out = ch(it.guild, cfg.get("channel")) if cfg else None
        if not isinstance(out, discord.TextChannel): return await it.response.send_message("Les confessions ne sont pas configurées.", ephemeral=True)
        number = int(time.time()) % 1000000
        await out.send(embed=emb(f"Confession #{number:06d}", text[:1800]))
        logs = ch(it.guild, cfg.get("logs"))
        if isinstance(logs, discord.TextChannel):
            await logs.send(embed=emb("Trace confession", f"Auteur : {it.user.mention} (`{it.user.id}`)\nConfession :\n{text[:1400]}", ORANGE), allowed_mentions=discord.AllowedMentions.none())
        await it.response.send_message("Confession envoyée anonymement.", ephemeral=True)

    @commands.command(name="ghostping")
    @commands.has_permissions(manage_guild=True)
    async def ghostping(self, ctx, mode: str, logs: discord.TextChannel | None = None):
        enabled = mode.lower() in {"on", "oui", "true", "actif"}
        if mode.lower() not in {"on","off","oui","non","true","false","actif","inactif"}: return await ctx.send("Utilise `+ghostping on #logs` ou `+ghostping off`.")
        old = await self.cfg(ctx.guild.id, "ghostping") or {}
        await self.setcfg(ctx.guild.id, "ghostping", {"enabled": enabled, "logs": logs.id if logs else old.get("logs", 0)})
        await ctx.send(embed=emb("Ghost ping", f"Détection : **{'activée' if enabled else 'désactivée'}**.", GREEN if enabled else ORANGE))

    @commands.command(name="boostsetup")
    @commands.has_permissions(manage_guild=True)
    async def boostsetup(self, ctx, channel: discord.TextChannel, logs: discord.TextChannel | None = None):
        old = await self.cfg(ctx.guild.id, "boost") or {}
        old.update({"channel": channel.id, "logs": logs.id if logs else 0, "message": old.get("message", "Merci {user} pour ton boost sur **{server}** ! Nous avons maintenant **{count} boosts**.")})
        await self.setcfg(ctx.guild.id, "boost", old); await ctx.send(embed=emb("Boosts configurés", f"Annonces : {channel.mention}", GREEN))

    @commands.command(name="boostmessage")
    @commands.has_permissions(manage_guild=True)
    async def boostmessage(self, ctx, *, template: str):
        cfg = await self.cfg(ctx.guild.id, "boost") or {"channel": 0, "logs": 0}
        cfg["message"] = template[:1800]; await self.setcfg(ctx.guild.id, "boost", cfg)
        await ctx.send(embed=emb("Message de boost", "Message enregistré. Variables : `{user}` `{server}` `{count}`.", GREEN))

    @commands.group(name="boostreward", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def boostreward(self, ctx): await ctx.send("`+boostreward add @rôle [permanent]` • `+boostreward remove @rôle`")

    @boostreward.command(name="add")
    async def boostreward_add(self, ctx, role: discord.Role, permanent: bool = False):
        await self.rule_add(ctx.guild.id, "boostrole", role.id, "", "1" if permanent else "0"); await ctx.send(embed=emb("Récompense boost", f"{role.mention} ajouté. Permanent : **{'oui' if permanent else 'non'}**.", GREEN))

    @boostreward.command(name="remove")
    async def boostreward_remove(self, ctx, role: discord.Role):
        await self.rule_del(ctx.guild.id, "boostrole", role.id); await ctx.send(embed=emb("Récompense boost", f"{role.mention} retiré.", ORANGE))

    @commands.group(name="protectping", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def protectping(self, ctx): await ctx.send("`+protectping add/remove @rôle` • `bypass/unbypass @rôle` • `logs #salon`")

    @protectping.command(name="add")
    async def pp_add(self, ctx, role: discord.Role): await self.rule_add(ctx.guild.id, "protect", role.id); await ctx.send(f"{role.mention} est maintenant protégé.")
    @protectping.command(name="remove")
    async def pp_remove(self, ctx, role: discord.Role): await self.rule_del(ctx.guild.id, "protect", role.id); await ctx.send(f"Protection retirée pour {role.mention}.")
    @protectping.command(name="bypass")
    async def pp_bypass(self, ctx, role: discord.Role): await self.rule_add(ctx.guild.id, "bypass", role.id); await ctx.send(f"{role.mention} peut ping les rôles protégés.")
    @protectping.command(name="unbypass")
    async def pp_unbypass(self, ctx, role: discord.Role): await self.rule_del(ctx.guild.id, "bypass", role.id); await ctx.send(f"Bypass retiré à {role.mention}.")
    @protectping.command(name="logs")
    async def pp_logs(self, ctx, channel: discord.TextChannel): await self.setcfg(ctx.guild.id, "protectping", {"logs": channel.id}); await ctx.send(f"Logs anti-ping : {channel.mention}.")

    @commands.group(name="attachmentonly", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def attachmentonly(self, ctx): await ctx.send("`+attachmentonly add #salon` • `+attachmentonly remove #salon`")
    @attachmentonly.command(name="add")
    async def ao_add(self, ctx, channel: discord.TextChannel): await self.rule_add(ctx.guild.id, "attach", channel.id); await ctx.send(f"{channel.mention} accepte maintenant uniquement les messages avec fichier/image.")
    @attachmentonly.command(name="remove")
    async def ao_remove(self, ctx, channel: discord.TextChannel): await self.rule_del(ctx.guild.id, "attach", channel.id); await ctx.send(f"Restriction retirée de {channel.mention}.")

    @commands.group(name="roleprefix", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def roleprefix(self, ctx): await ctx.send("`+roleprefix set @rôle [TAG]` • `+roleprefix remove @rôle`")
    @roleprefix.command(name="set")
    async def rp_set(self, ctx, role: discord.Role, *, prefix: str): await self.rule_add(ctx.guild.id, "prefix", role.id, "", prefix[:18]); await ctx.send(f"Préfixe `{prefix[:18]}` associé à {role.mention}.")
    @roleprefix.command(name="remove")
    async def rp_remove(self, ctx, role: discord.Role): await self.rule_del(ctx.guild.id, "prefix", role.id); await ctx.send(f"Préfixe retiré de {role.mention}.")

    @commands.group(name="autoreact", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def autoreact(self, ctx): await ctx.send("`+autoreact add mot 😀` • `+autoreact globaladd mot 😀` • `+autoreact remove mot`")
    async def _add_react(self, ctx, trigger, emoji, cid):
        try: await ctx.message.add_reaction(emoji); await ctx.message.remove_reaction(emoji, self.bot.user)
        except Exception: return await ctx.send("Emoji invalide ou inaccessible.")
        await self.rule_add(ctx.guild.id, "react", trigger.lower(), cid, emoji); await ctx.send(f"Réaction `{emoji}` ajoutée pour `{trigger}`.")
    @autoreact.command(name="add")
    async def ar_add(self, ctx, trigger: str, emoji: str): await self._add_react(ctx, trigger, emoji, ctx.channel.id)
    @autoreact.command(name="globaladd")
    async def ar_global(self, ctx, trigger: str, emoji: str): await self._add_react(ctx, trigger, emoji, 0)
    @autoreact.command(name="remove")
    async def ar_remove(self, ctx, trigger: str): await self.rule_del(ctx.guild.id, "react", trigger.lower()); await ctx.send(f"Auto-réactions `{trigger}` supprimées.")

    @commands.group(name="triggerword", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def triggerword(self, ctx): await ctx.send("`+triggerword add mot | réponse` • `globaladd mot | réponse` • `remove mot`")
    async def _add_trigger(self, ctx, raw: str, cid: int):
        if "|" not in raw: return await ctx.send("Format : `mot | réponse`.")
        trigger, response = [x.strip() for x in raw.split("|", 1)]
        if not trigger or not response: return await ctx.send("Le mot et la réponse sont obligatoires.")
        await self.rule_add(ctx.guild.id, "trigger", trigger.lower(), cid, response[:1200]); await ctx.send(f"Réponse automatique ajoutée pour `{trigger}`.")
    @triggerword.command(name="add")
    async def tw_add(self, ctx, *, raw: str): await self._add_trigger(ctx, raw, ctx.channel.id)
    @triggerword.command(name="globaladd")
    async def tw_global(self, ctx, *, raw: str): await self._add_trigger(ctx, raw, 0)
    @triggerword.command(name="remove")
    async def tw_remove(self, ctx, *, trigger: str): await self.rule_del(ctx.guild.id, "trigger", trigger.lower()); await ctx.send(f"Déclencheurs `{trigger}` supprimés.")

    @commands.command(name="roblox", aliases=["rbxlookup"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def roblox(self, ctx, *, username: str):
        if not self.http or self.http.closed: self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8))
        try:
            async with self.http.post("https://users.roblox.com/v1/usernames/users", json={"usernames":[username],"excludeBannedUsers":False}) as r: data = await r.json()
            if not data.get("data"): return await ctx.send(embed=emb("Roblox", "Utilisateur introuvable.", RED))
            u = data["data"][0]; uid = int(u["id"])
            async with self.http.get(f"https://users.roblox.com/v1/users/{uid}") as r: profile = await r.json()
            async with self.http.post("https://presence.roblox.com/v1/presence/users", json={"userIds":[uid]}) as r: presence = await r.json()
            async with self.http.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={uid}&size=420x420&format=Png&isCircular=false") as r: thumbs = await r.json()
            p = (presence.get("userPresences") or [{}])[0]; states = {0:"Hors ligne",1:"En ligne",2:"En jeu",3:"Dans Studio"}
            e = emb("Profil Roblox", f"**{profile.get('displayName',u['name'])}** • `@{u['name']}`\nID : `{uid}`\nStatut : **{states.get(p.get('userPresenceType'), 'Inconnu')}**\nCréé : `{str(profile.get('created','?'))[:10]}`")
            img = (thumbs.get("data") or [{}])[0].get("imageUrl")
            if img: e.set_thumbnail(url=img)
            if profile.get("description"): e.add_field(name="Description", value=str(profile["description"])[:500], inline=False)
            await ctx.send(embed=e)
        except Exception:
            log.exception("Roblox lookup failed"); await ctx.send(embed=emb("Roblox", "L'API Roblox ne répond pas pour le moment.", RED))

    @commands.command(name="applicationsetup")
    @commands.has_permissions(manage_guild=True)
    async def applicationsetup(self, ctx, channel: discord.TextChannel, *, title: str = "Candidature staff"):
        await self.setcfg(ctx.guild.id, "application", {"channel": channel.id, "title": title[:45]}); await ctx.send(embed=emb("Candidatures configurées", f"Réponses : {channel.mention}\nTitre : **{title[:45]}**", GREEN))

    @commands.group(name="applicationquestion", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def applicationquestion(self, ctx): await ctx.send("`+applicationquestion add Question` • `+applicationquestion clear`")
    @applicationquestion.command(name="add")
    async def aq_add(self, ctx, *, question: str):
        rows = await self.rules(ctx.guild.id, "appq")
        if len(rows) >= 5: return await ctx.send("Maximum 5 questions (limite des modals Discord).")
        await self.rule_add(ctx.guild.id, "appq", len(rows)+1, "", question[:45]); await ctx.send(f"Question ajoutée : **{question[:45]}**")
    @applicationquestion.command(name="clear")
    async def aq_clear(self, ctx): await self.bot.db.execute("DELETE FROM sx_cp_rules WHERE guild_id=? AND kind='appq'", (ctx.guild.id,)); await ctx.send("Questions supprimées.")

    @commands.command(name="applicationpanel")
    @commands.has_permissions(manage_guild=True)
    async def applicationpanel(self, ctx):
        cfg = await self.cfg(ctx.guild.id, "application")
        if not cfg: return await ctx.send("Configure d'abord `+applicationsetup #salon`.")
        await ctx.send(embed=emb(cfg.get("title", "Candidatures"), "Clique sur **Postuler** pour remplir le formulaire."), view=ApplicationView(self.bot))

    async def send_application(self, it: discord.Interaction, questions, answers):
        cfg = await self.cfg(it.guild.id, "application") if it.guild else None
        out = ch(it.guild, cfg.get("channel")) if cfg else None
        if not isinstance(out, discord.TextChannel): return await it.response.send_message("Salon de candidatures introuvable.", ephemeral=True)
        e = emb("Nouvelle candidature", f"Candidat : {it.user.mention} (`{it.user.id}`)")
        for q, a in zip(questions, answers): e.add_field(name=q[:256], value=a[:1000] or "—", inline=False)
        await out.send(embed=e, allowed_mentions=discord.AllowedMentions.none()); await it.response.send_message("Candidature envoyée.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if not msg.guild or msg.author.bot: return
        if msg.mentions or msg.role_mentions or msg.mention_everyone:
            self.ghost[msg.id] = {"gid":msg.guild.id,"cid":msg.channel.id,"uid":msg.author.id,"content":msg.content[:1500],"mentions":[u.id for u in msg.mentions],"roles":[r.id for r in msg.role_mentions],"everyone":msg.mention_everyone}
            while len(self.ghost) > 4000: self.ghost.popitem(last=False)

        attaches = {int(r["key1"]) for r in await self.rules(msg.guild.id, "attach")}
        if msg.channel.id in attaches and not msg.attachments and not msg.content.startswith(getattr(self.bot, "command_prefix", "+") if isinstance(getattr(self.bot,"command_prefix","+"),str) else "+"):
            if not msg.author.guild_permissions.manage_messages:
                try: await msg.delete(); w = await msg.channel.send(f"{msg.author.mention}, ce salon accepte uniquement les fichiers/images."); await w.delete(delay=6)
                except Exception: pass
                return

        protected = {int(r["key1"]) for r in await self.rules(msg.guild.id, "protect")}
        hit = [r for r in msg.role_mentions if r.id in protected]
        if hit:
            bypass = {int(r["key1"]) for r in await self.rules(msg.guild.id, "bypass")}
            if not msg.author.guild_permissions.manage_messages and not any(r.id in bypass for r in msg.author.roles):
                await self.block_ping(msg, hit); return

        lower = msg.content.lower()
        if not lower: return
        for r in (await self.rules(msg.guild.id, "react"))[:30]:
            if int(r["key2"] or 0) in {0,msg.channel.id} and r["key1"].lower() in lower:
                try: await msg.add_reaction(r["value"])
                except Exception: pass
        sent = 0
        for r in (await self.rules(msg.guild.id, "trigger"))[:30]:
            if sent >= 3: break
            if int(r["key2"] or 0) in {0,msg.channel.id} and r["key1"].lower() in lower:
                try: await msg.reply(r["value"][:1200], mention_author=False, allowed_mentions=discord.AllowedMentions.none()); sent += 1
                except Exception: pass

    async def block_ping(self, msg, roles):
        try: await msg.delete()
        except Exception: pass
        key = (msg.guild.id, msg.author.id); q = self.strikes.setdefault(key, deque()); now=time.monotonic(); q.append(now)
        while q and now-q[0] > 60: q.popleft()
        text = f"{msg.author.mention}, tu ne peux pas mentionner " + ", ".join(r.mention for r in roles) + "."
        if len(q) >= 3 and msg.guild.me and msg.guild.me.guild_permissions.moderate_members:
            try: await msg.author.timeout(discord.utils.utcnow()+dt.timedelta(seconds=60), reason="SentriX • ping protégé répété"); text += "\nTimeout : **60 s**."; q.clear()
            except Exception: pass
        try: w=await msg.channel.send(text, allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False)); await w.delete(delay=8)
        except Exception: pass
        cfg = await self.cfg(msg.guild.id, "protectping") or {}; out = ch(msg.guild, cfg.get("logs"))
        if isinstance(out, discord.TextChannel):
            try: await out.send(embed=emb("Ping protégé bloqué", f"Auteur : {msg.author.mention}\nSalon : {msg.channel.mention}\nRôles : {', '.join(r.mention for r in roles)}", ORANGE), allowed_mentions=discord.AllowedMentions.none())
            except Exception: pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        data = self.ghost.pop(payload.message_id, None)
        if not data or not payload.guild_id: return
        cfg = await self.cfg(payload.guild_id, "ghostping")
        if not cfg or not cfg.get("enabled"): return
        guild = self.bot.get_guild(payload.guild_id); out = ch(guild, cfg.get("logs"))
        if not guild or not isinstance(out, discord.TextChannel): return
        names = (["@everyone/@here"] if data["everyone"] else []) + [f"<@{x}>" for x in data["mentions"]] + [f"<@&{x}>" for x in data["roles"]]
        author = guild.get_member(data["uid"]); channel = guild.get_channel(data["cid"])
        try: await out.send(embed=emb("Ghost ping détecté", f"Auteur : {author.mention if author else '`'+str(data['uid'])+'`'}\nSalon : {channel.mention if channel else '`'+str(data['cid'])+'`'}\nMentions supprimées : {' '.join(names)[:700]}\n\nContenu : {data['content'] or '*sans texte*'}", ORANGE), allowed_mentions=discord.AllowedMentions.none())
        except Exception: pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if {r.id for r in before.roles} != {r.id for r in after.roles}: await self.apply_prefix(after)
        if before.premium_since is None and after.premium_since is not None: await self.boost_event(after, True)
        elif before.premium_since is not None and after.premium_since is None: await self.boost_event(after, False)

    @commands.Cog.listener()
    async def on_member_join(self, member): await self.apply_prefix(member)

    async def apply_prefix(self, member: discord.Member):
        rows = await self.rules(member.guild.id, "prefix"); chosen = None
        for r in rows:
            role = member.guild.get_role(int(r["key1"]))
            if role in member.roles and (not chosen or role.position > chosen[0].position): chosen = (role, r["value"])
        if not chosen or not member.guild.me or member.top_role >= member.guild.me.top_role: return
        prefix = chosen[1].strip(); base = re.sub(r"^\[[^\]]{1,20}\]\s*", "", member.display_name).strip()
        nick = f"{prefix} {base}"[:32]
        if nick != member.display_name:
            try: await member.edit(nick=nick, reason="SentriX • préfixe de rôle")
            except Exception: pass

    async def boost_event(self, member: discord.Member, started: bool):
        rows = await self.rules(member.guild.id, "boostrole"); changed=[]
        for r in rows:
            role=member.guild.get_role(int(r["key1"])); permanent = r["value"] == "1"
            if not role: continue
            try:
                if started and role not in member.roles: await member.add_roles(role, reason="SentriX • récompense boost"); changed.append(role)
                elif not started and not permanent and role in member.roles: await member.remove_roles(role, reason="SentriX • fin boost"); changed.append(role)
            except Exception: pass
        cfg = await self.cfg(member.guild.id, "boost")
        if not cfg: return
        if started:
            out=ch(member.guild,cfg.get("channel")); template=cfg.get("message","Merci {user} pour ton boost sur **{server}** !")
            if isinstance(out,discord.TextChannel):
                text=template.replace("{user}",member.mention).replace("{server}",member.guild.name).replace("{count}",str(member.guild.premium_subscription_count or 0))
                try: await out.send(text[:1900],allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False))
                except Exception: pass
        logs=ch(member.guild,cfg.get("logs"))
        if isinstance(logs,discord.TextChannel):
            try: await logs.send(embed=emb("Boost serveur",f"{member.mention} {'a boosté' if started else 'ne booste plus'} le serveur.\nRôles : {', '.join(r.mention for r in changed) or 'aucun changement'}",GREEN if started else ORANGE),allowed_mentions=discord.AllowedMentions.none())
            except Exception: pass


async def setup(bot: commands.Bot):
    await bot.add_cog(CosmosParity(bot))
