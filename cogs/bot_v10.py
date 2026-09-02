"""Bot V10 — production quality layer for SentriX/Odboug.

Adds unified setup, diagnostics, server audit, economy insights, privacy retention,
operational signals, richer AI context, safer restore and custom-command hardening.
No new slash command roots are created.
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands, tasks

from database.db import now
from utils import checks, embeds, helpers
from utils import sentrix_panels as panels
from utils import helpers

logger = logging.getLogger("bot.v10")

SCHEMA = """
CREATE TABLE IF NOT EXISTS v10_server_audits (
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, actor_id INTEGER,
 total_score INTEGER NOT NULL, security_score INTEGER NOT NULL, configuration_score INTEGER NOT NULL,
 moderation_score INTEGER NOT NULL, operations_score INTEGER NOT NULL, economy_score INTEGER NOT NULL,
 engagement_score INTEGER NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v10_server_audits_guild_time ON v10_server_audits (guild_id, created_at DESC);
CREATE TABLE IF NOT EXISTS v10_privacy_policy (
 guild_id INTEGER PRIMARY KEY, retention_days INTEGER NOT NULL DEFAULT 90, updated_by INTEGER, updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS v10_privacy_cleanup_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, table_name TEXT NOT NULL,
 deleted_count INTEGER NOT NULL DEFAULT 0, cutoff_at INTEGER NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS v10_operational_signals (
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, signal_type TEXT NOT NULL,
 severity TEXT NOT NULL DEFAULT 'info', actor_id INTEGER, target_id INTEGER, score INTEGER NOT NULL DEFAULT 0,
 details_json TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v10_operational_signals_guild_time ON v10_operational_signals (guild_id, created_at DESC);
CREATE TABLE IF NOT EXISTS v10_custom_command_usage (
 guild_id INTEGER NOT NULL, command_name TEXT NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
 last_used_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, command_name)
);
"""

VALID_PROFILES = {"community", "gaming", "support", "creator"}
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 7
MAX_RETENTION_DAYS = 365
JOIN_BURST_WINDOW = 60.0
JOIN_BURST_THRESHOLD = 8
CUSTOM_COMMAND_COOLDOWN = 3.0
_REQUIRED_BOT_PERMS = {
 "manage_channels": "Gérer les salons", "manage_roles": "Gérer les rôles",
 "manage_messages": "Gérer les messages", "moderate_members": "Modérer les membres",
 "kick_members": "Expulser des membres", "ban_members": "Bannir des membres",
 "view_audit_log": "Voir les logs d'audit",
}
_RETENTION_TABLES = (
 ("ai_conversations", "created_at", "guild_id"),
 ("command_logs", "timestamp", "guild_id"),
 ("production_command_events_v9", "created_at", "guild_id"),
)


def _clamp(value: int, low: int, high: int) -> int:
 return max(low, min(high, int(value)))


async def _ensure_schema(bot: commands.Bot) -> None:
 conn = getattr(bot.db, "_conn", None)
 if conn is not None:
  await conn.executescript(SCHEMA); await conn.commit(); return
 for statement in SCHEMA.split(";"):
  if statement.strip(): await bot.db.execute(statement)


async def _count(bot, sql: str, params=()) -> int:
 try:
  row = await bot.db.fetchone(sql, params); return int(row["c"] or 0) if row else 0
 except Exception: return 0


class BotV10(commands.Cog, name="BotV10"):
 def __init__(self, bot: commands.Bot):
  self.bot = bot
  self._join_times: dict[int, deque[float]] = defaultdict(deque)
  self._custom_cooldowns: dict[tuple[int, int, str], float] = {}
  self._integration_lock = asyncio.Lock()

 async def cog_load(self):
  await _ensure_schema(self.bot); await self.ensure_integrations()
  if not self.integration_loop.is_running(): self.integration_loop.start()
  if not self.privacy_cleanup_loop.is_running(): self.privacy_cleanup_loop.start()

 def cog_unload(self):
  self.integration_loop.cancel(); self.privacy_cleanup_loop.cancel()

 async def ensure_integrations(self):
  async with self._integration_lock:
   self._patch_setup_auto(); self._patch_ai_context(); self._patch_backup_restore(); self._patch_custom_commands(); self._install_security_subcommands()

 @tasks.loop(seconds=60)
 async def integration_loop(self): await self.ensure_integrations()

 @integration_loop.before_loop
 async def before_integration_loop(self): await self.bot.wait_until_ready()

 def _patch_setup_auto(self):
  command = self.bot.get_command("setup")
  if command is None or getattr(command.callback, "_sentrix_setup_auto_v10", False): return
  original = command.callback
  async def wrapped(cog_self, ctx: commands.Context, *args, **kwargs):
   if ctx.interaction is None and ctx.message:
    content = (ctx.message.content or "").strip(); prefix = str(getattr(ctx, "clean_prefix", "+") or "+"); marker = f"{prefix}setup"
    if content.casefold().startswith(marker.casefold()):
     parts = content[len(marker):].strip().split()
     if parts and parts[0].casefold() == "auto":
      profile = parts[1].casefold() if len(parts) > 1 else "community"; return await self.run_auto_setup(ctx, profile)
   return await original(cog_self, ctx, *args, **kwargs)
  # _sentrix_original est la convention du depot pour rendre une enveloppe
  # tracable : sans elle, les portes d'analyse s'arretent ici et croient que
  # +setup n'a pas de rendu.
  wrapped._sentrix_setup_auto_v10 = True; wrapped._sentrix_original = original
  command.callback = wrapped

 def _patch_ai_context(self):
  try: from cogs import ai_context_v9
  except Exception: return
  current = ai_context_v9.build_server_context
  if getattr(current, "_sentrix_ai_context_v10", False): return
  async def richer_context(bot, guild_id: int | None, channel_id: int | None):
   base = await current(bot, guild_id, channel_id)
   if not guild_id: return base
   guild = bot.get_guild(int(guild_id))
   if guild is None: return base
   lines = []; channel = guild.get_channel(int(channel_id)) if channel_id else None
   if channel is not None:
    lines.append(f"Salon actuel: #{getattr(channel, 'name', 'inconnu')}")
    if getattr(channel, "category", None): lines.append(f"Catégorie: {channel.category.name}")
    topic = (getattr(channel, "topic", "") or "").strip()
    if topic: lines.append("Sujet du salon: " + topic[:240])
   try:
    automod = await bot.db.get_automod(guild.id)
    fields = ("antispam","antilink","antiinvite","antimention","anticaps","antiemoji","antiraid","antibot","antiaccount","antiscam","antinuke")
    active = sum(1 for field in fields if automod and field in automod.keys() and automod[field]); lines.append(f"Protections actives: {active}/{len(fields)}")
   except Exception: pass
   if channel is not None:
    try:
     ticket = await bot.db.fetchone("SELECT status,priority,category,claimed_by FROM tickets WHERE channel_id=? ORDER BY id DESC LIMIT 1", (channel.id,))
     if ticket: lines.append("Mode assistance staff/ticket: résumer les faits et proposer une réponse; toute sanction reste une décision humaine.")
    except Exception: pass
   addition = "\n".join(lines); return (base + ("\n" if base and addition else "") + addition)[:1800]
  richer_context._sentrix_ai_context_v10 = True; ai_context_v9.build_server_context = richer_context

 def _patch_backup_restore(self):
  platform = self.bot.get_cog("PlatformV4")
  if platform is None: return
  cls = type(platform); current = cls.restore_backup
  if getattr(current, "_sentrix_restore_safety_v10", False): return
  async def restore_with_safety(service, guild: discord.Guild, actor_id: int, backup_id: int):
   me = guild.me
   if me is None or not (me.guild_permissions.manage_channels and me.guild_permissions.manage_roles): raise ValueError("Permissions Gérer les salons et Gérer les rôles requises.")
   try: await service.create_backup(guild, actor_id, f"V10 safety before restore {backup_id}")
   except Exception as exc: raise ValueError("Impossible de créer la sauvegarde de sécurité préalable.") from exc
   return await current(service, guild, actor_id, backup_id)
  restore_with_safety._sentrix_restore_safety_v10 = True; cls.restore_backup = restore_with_safety

 def _patch_custom_commands(self):
  platform = self.bot.get_cog("PlatformV4")
  if platform is None: return
  for index, listener in enumerate(self.bot.extra_events.get("on_message", [])):
   if getattr(listener, "__self__", None) is not platform or getattr(listener, "__name__", "") != "on_message": continue
   if getattr(listener, "_sentrix_custom_commands_v10", False): return
   original = listener
   async def guarded(message: discord.Message, _original=original):
    if message.guild and not message.author.bot:
     try:
      conf = await self.bot.db.get_guild_config(message.guild.id); prefix = str(conf["prefix"] or "+") if conf else "+"
     except Exception: prefix = "+"
     if (message.content or "").startswith(prefix):
      raw_name = (message.content[len(prefix):].split(maxsplit=1) or [""])[0].casefold()
      try: row = await self.bot.db.fetchone("SELECT id FROM platform_custom_commands WHERE guild_id=? AND name=? AND enabled=1", (message.guild.id, raw_name)) if raw_name else None
      except Exception: row = None
      if row:
       key = (message.guild.id, message.author.id, raw_name); current_t = time.monotonic()
       if CUSTOM_COMMAND_COOLDOWN - (current_t - self._custom_cooldowns.get(key, 0.0)) > 0: return
       self._custom_cooldowns[key] = current_t
       await self.bot.db.execute("INSERT INTO v10_custom_command_usage (guild_id,command_name,uses,last_used_at) VALUES (?,?,1,?) ON CONFLICT(guild_id,command_name) DO UPDATE SET uses=uses+1,last_used_at=excluded.last_used_at", (message.guild.id, raw_name, now()))
    return await _original(message)
   guarded._sentrix_custom_commands_v10 = True; self.bot.extra_events["on_message"][index] = guarded; return

 def _install_security_subcommands(self):
  root = self.bot.get_command("security")
  if not isinstance(root, commands.Group): return
  if root.get_command("incidents") is None: root.add_command(commands.Command(self._operational_signals, name="incidents", help="Afficher les signaux opérationnels récents."))
  if root.get_command("overview") is None: root.add_command(commands.Command(self._security_overview, name="overview", help="Vue globale de la protection du serveur."))

 async def run_auto_setup(self, ctx: commands.Context, profile: str = "community"):
  profile = (profile or "community").casefold()
  if profile not in VALID_PROFILES: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Profil inconnu: community, gaming, support ou creator.')))
  platform = self.bot.get_cog("PlatformV4")
  if platform is None: return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Platform V4 se charge encore.')))
  try:
   result = await platform.quick_setup(ctx.guild, ctx.author.id, profile); audit = await self.server_audit_data(ctx.guild, actor_id=ctx.author.id, persist=True); missing = self.missing_bot_permissions(ctx.guild)
   e = embeds.success(f"Configuration automatique **{profile}** terminée.\nScore serveur: **{audit['total_score']}/100**.")
   result = result or {}; e.add_field(name="Créé", value=f"Salons: **{result.get('created_channels',0)}**\nCatégories: **{result.get('created_categories',0)}**\nRôles: **{result.get('created_roles',0)}**", inline=True)
   e.add_field(name="Permissions", value="OK" if not missing else "Manquantes: " + ", ".join(missing[:6]), inline=True)
   if audit["recommendations"]: e.add_field(name="À terminer", value="\n".join(f"• {item}" for item in audit["recommendations"][:5]), inline=False)
   await panels.envoyer(ctx, panels.depuis_embed(e))
  except (ValueError, discord.Forbidden, discord.HTTPException) as exc: await panels.envoyer(ctx, panels.depuis_embed(embeds.error(str(exc)[:900])))

 @commands.command(name="setup-auto", aliases=["autosetup"])
 @checks.is_owner_or_admin_for("configuration")
 async def setup_auto(self, ctx: commands.Context, profile: str = "community"): await self.run_auto_setup(ctx, profile)

 def missing_bot_permissions(self, guild: discord.Guild) -> list[str]:
  me = guild.me
  if me is None: return list(_REQUIRED_BOT_PERMS.values())
  return [label for attr,label in _REQUIRED_BOT_PERMS.items() if not getattr(me.guild_permissions, attr, False)]

 async def health_data(self, guild: discord.Guild) -> dict:
  runtime = self.bot.get_cog("CommandObservabilityV9"); v9 = {}
  if runtime:
   try: v9 = await runtime.refresh_health()
   except Exception: pass
  platform = self.bot.get_cog("PlatformV4"); platform_health = {}
  if platform:
   try: platform_health = await platform.health(guild)
   except Exception: pass
  missing = self.missing_bot_permissions(guild)
  return {"status": str(v9.get("status") or ("healthy" if not missing else "degraded")), "discord": v9.get("discord", {"ready": self.bot.is_ready(), "latency_ms": helpers.latence_ms(self.bot)}), "database": v9.get("database", {}), "openai": v9.get("openai", {}), "commands": v9.get("commands", {}), "platform": platform_health, "backups": await _count(self.bot,"SELECT COUNT(*) c FROM server_backups WHERE guild_id=?",(guild.id,)), "missing_permissions": missing}

 @commands.command(name="health")
 @checks.is_owner_or_admin_for("configuration")
 async def health_command(self, ctx: commands.Context):
  state = await self.health_data(ctx.guild); db = state.get("database") or {}; command_state = state.get("commands") or {}
  lines = [f"Discord: **{'OK' if state['discord'].get('ready') else 'ERREUR'}** — {state['discord'].get('latency_ms','?')} ms", f"SQLite: **{db.get('sqlite','inconnu')}** · PostgreSQL: **{db.get('postgres','inconnu')}** · Redis: **{db.get('redis','inconnu')}**", f"IA: **{(state.get('openai') or {}).get('state','inconnu')}**", f"Commandes: **{command_state.get('prefix_roots',len(self.bot.commands))}** préfixées · **{command_state.get('slash_roots',len(self.bot.tree.get_commands()))}** slash", f"Sauvegardes: **{state['backups']}**"]
  if state["missing_permissions"]: lines.append("Permissions manquantes: " + ", ".join(state["missing_permissions"]))
  await panels.envoyer(ctx, panels.depuis_embed(embeds.brand('Diagnostic complet — Bot V10', '\n'.join(lines))))

 async def server_audit_data(self, guild: discord.Guild, actor_id: int | None = None, *, persist: bool = False) -> dict:
  conf = await self.bot.db.get_guild_config(guild.id); automod = await self.bot.db.get_automod(guild.id); missing = self.missing_bot_permissions(guild)
  fields = ("antispam","antilink","antiinvite","antimention","anticaps","antiemoji","antiraid","antibot","antiaccount","antiscam","antinuke")
  active = sum(1 for field in fields if automod and field in automod.keys() and automod[field]); security = _clamp(20 + round(60*active/len(fields)) + (10 if automod and automod["escalation"] else 0) + (10 if not missing else 0),0,100)
  important = ("mod_role","welcome_channel","ticket_log_channel","log_moderation","log_automod","suggest_channel","announce_channel","giveaway_channel"); configured = sum(1 for field in important if conf and field in conf.keys() and conf[field]); configuration = _clamp(20+round(65*configured/len(important))+(5 if conf and conf["prefix"] else 0)+(10 if not missing else 0),0,100)
  moderation = _clamp(30+(20 if conf and conf["mod_role"] else 0)+(20 if conf and (conf["log_moderation"] or conf["log_channel"]) else 0)+(15 if automod and automod["escalation"] else 0)+15,0,100)
  backups = await _count(self.bot,"SELECT COUNT(*) c FROM server_backups WHERE guild_id=?",(guild.id,)); operations = _clamp(20+(25 if backups else 0)+(25 if self.bot.get_cog("CommandObservabilityV9") else 0)+(20 if self.bot.get_cog("PlatformV4") else 0)+(10 if not missing else 0),0,100)
  eco = await self.economy_insights(guild.id); economy = _clamp(35+(20 if eco["accounts"] else 0)+(25 if eco["ledger_available"] else 0)+(10 if eco["blocked_accounts"]==0 else 0)+(10 if eco["top10_concentration_pct"]<=80 or eco["accounts"]<10 else 0),0,100)
  engagement = 25 + (20 if await _count(self.bot,"SELECT COUNT(*) c FROM message_counts WHERE guild_id=?",(guild.id,)) else 0) + (15 if await _count(self.bot,"SELECT COUNT(*) c FROM suggestions WHERE guild_id=?",(guild.id,)) else 0) + (20 if conf and (conf["level_channel"] or conf["suggest_channel"]) else 0); engagement = _clamp(engagement,0,100)
  scores={"security_score":security,"configuration_score":configuration,"moderation_score":moderation,"operations_score":operations,"economy_score":economy,"engagement_score":engagement}; total=round(statistics.mean(scores.values())); recommendations=[]
  if security<85: recommendations.append("Lancez `+security all` puis vérifiez les exemptions.")
  if configuration<80: recommendations.append("Lancez `+setup auto community` ou ouvrez `/setup`.")
  if operations<80: recommendations.append("Créez une sauvegarde et vérifiez `+health`.")
  if economy<80: recommendations.append("Contrôlez `+economy-audit` et les alertes anti-abus.")
  if engagement<70: recommendations.append("Activez niveaux, suggestions, quêtes/saisons ou événements.")
  payload={"total_score":total,**scores,"recommendations":recommendations,"missing_permissions":missing,"generated_at":now()}
  if persist: await self.bot.db.execute("INSERT INTO v10_server_audits (guild_id,actor_id,total_score,security_score,configuration_score,moderation_score,operations_score,economy_score,engagement_score,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(guild.id,actor_id,total,security,configuration,moderation,operations,economy,engagement,json.dumps(payload,ensure_ascii=False),now()))
  return payload

 @commands.command(name="server-audit", aliases=["audit-server"])
 @checks.is_owner_or_admin_for("configuration")
 async def server_audit(self, ctx: commands.Context):
  data=await self.server_audit_data(ctx.guild,actor_id=ctx.author.id,persist=True); e=embeds.brand(f"Audit serveur — {data['total_score']}/100","Évaluation factuelle de la configuration; elle n'évalue pas les personnes.")
  for label,key in (("Sécurité","security_score"),("Configuration","configuration_score"),("Modération","moderation_score"),("Exploitation","operations_score"),("Économie","economy_score"),("Engagement","engagement_score")): e.add_field(name=label,value=f"**{data[key]}/100**",inline=True)
  if data["recommendations"]: e.add_field(name="Corrections recommandées",value="\n".join(f"• {x}" for x in data["recommendations"]),inline=False)
  await panels.envoyer(ctx, panels.depuis_embed(e))

 async def economy_insights(self,guild_id:int)->dict:
  rows=await self.bot.db.fetchall("SELECT cash,bank FROM economy WHERE guild_id=? ORDER BY (cash+bank) DESC",(guild_id,)); wealth=[max(0,int(r["cash"] or 0)+int(r["bank"] or 0)) for r in rows]; supply=sum(wealth); accounts=len(wealth); concentration=round((sum(wealth[:10])/supply)*100,1) if supply else 0.0; cutoff=now()-86400; ledger_available=True
  try: tx=await self.bot.db.fetchall("SELECT transaction_type,amount,sender_id,receiver_id FROM economy_transactions WHERE guild_id=? AND created_at>=?",(guild_id,cutoff))
  except Exception: tx=[]; ledger_available=False
  inflow=sum(max(0,int(r["amount"] or 0)) for r in tx if not r["sender_id"] and r["receiver_id"]); sinks=sum(max(0,int(r["amount"] or 0)) for r in tx if r["sender_id"] and not r["receiver_id"])
  return {"accounts":accounts,"total_supply":supply,"average_wealth":round(supply/accounts) if accounts else 0,"median_wealth":round(statistics.median(wealth)) if wealth else 0,"top10_concentration_pct":concentration,"transactions_24h":len(tx),"volume_24h":sum(abs(int(r["amount"] or 0)) for r in tx),"net_issuance_24h":inflow-sinks,"blocked_accounts":await _count(self.bot,"SELECT COUNT(*) c FROM economy_abuse_state WHERE guild_id=? AND blocked_until>?",(guild_id,now())),"ledger_available":ledger_available}

 @commands.command(name="economy-audit", aliases=["eco-audit"])
 @checks.is_owner_or_admin_for("economie")
 async def economy_audit(self,ctx:commands.Context):
  d=await self.economy_insights(ctx.guild.id); e=embeds.brand("Économie V3 — contrôle","Indicateurs factuels; aucune sanction automatique."); e.add_field(name="Masse monétaire",value=f"**{d['total_supply']:,}**",inline=True); e.add_field(name="Comptes",value=f"**{d['accounts']}**",inline=True); e.add_field(name="Médiane",value=f"**{d['median_wealth']:,}**",inline=True); e.add_field(name="Top 10",value=f"**{d['top10_concentration_pct']}%**",inline=True); e.add_field(name="24 h",value=f"**{d['transactions_24h']}** transactions\nVolume **{d['volume_24h']:,}**",inline=True); e.add_field(name="Émission nette 24 h",value=f"**{d['net_issuance_24h']:,}**",inline=True); e.add_field(name="Anti-abus",value=f"**{d['blocked_accounts']}** limitation(s) active(s)",inline=False); await panels.envoyer(ctx, panels.depuis_embed(e))

 async def get_privacy_policy(self,guild_id:int)->dict:
  await self.bot.db.execute("INSERT OR IGNORE INTO v10_privacy_policy (guild_id,retention_days,updated_at) VALUES (?,?,?)",(guild_id,DEFAULT_RETENTION_DAYS,now())); row=await self.bot.db.fetchone("SELECT * FROM v10_privacy_policy WHERE guild_id=?",(guild_id,)); return dict(row) if row else {"guild_id":guild_id,"retention_days":DEFAULT_RETENTION_DAYS}

 async def set_privacy_policy(self,guild_id:int,actor_id:int,days:int)->dict:
  days=_clamp(days,MIN_RETENTION_DAYS,MAX_RETENTION_DAYS); await self.bot.db.execute("INSERT INTO v10_privacy_policy (guild_id,retention_days,updated_by,updated_at) VALUES (?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET retention_days=excluded.retention_days,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(guild_id,days,actor_id,now())); return await self.get_privacy_policy(guild_id)

 @commands.command(name="privacy-policy")
 @checks.is_owner_or_admin_for("configuration")
 async def privacy_policy(self,ctx:commands.Context,days:int|None=None):
  policy=await self.set_privacy_policy(ctx.guild.id,ctx.author.id,days) if days is not None else await self.get_privacy_policy(ctx.guild.id); await panels.envoyer(ctx, panels.depuis_embed(embeds.brand('Politique de confidentialité V10', f"Télémétrie et mémoire IA non sensible: **{policy['retention_days']} jours**.\nLes sanctions, avertissements, journaux d'audit et transactions économiques ne sont pas purgés automatiquement.")))

 @tasks.loop(hours=6)
 async def privacy_cleanup_loop(self):
  policies=await self.bot.db.fetchall("SELECT guild_id,retention_days FROM v10_privacy_policy")
  for policy in policies:
   gid=int(policy["guild_id"]); cutoff=now()-_clamp(policy["retention_days"],MIN_RETENTION_DAYS,MAX_RETENTION_DAYS)*86400
   for table,time_col,guild_col in _RETENTION_TABLES:
    try:
     row=await self.bot.db.fetchone(f"SELECT COUNT(*) c FROM {table} WHERE {guild_col}=? AND {time_col}<?",(gid,cutoff)); count=int(row["c"] or 0) if row else 0
     if count: await self.bot.db.execute(f"DELETE FROM {table} WHERE {guild_col}=? AND {time_col}<?",(gid,cutoff))
     await self.bot.db.execute("INSERT INTO v10_privacy_cleanup_log (guild_id,table_name,deleted_count,cutoff_at,created_at) VALUES (?,?,?,?,?)",(gid,table,count,cutoff,now()))
    except Exception: logger.debug("V10 retention skipped for %s",table,exc_info=True)

 @privacy_cleanup_loop.before_loop
 async def before_privacy_cleanup(self): await self.bot.wait_until_ready()

 async def record_signal(self,guild_id:int,signal_type:str,*,severity:str="info",actor_id:int|None=None,target_id:int|None=None,score:int=0,details:dict|None=None): await self.bot.db.execute("INSERT INTO v10_operational_signals (guild_id,signal_type,severity,actor_id,target_id,score,details_json,created_at) VALUES (?,?,?,?,?,?,?,?)",(guild_id,signal_type[:80],severity[:16],actor_id,target_id,_clamp(score,0,100),json.dumps(details or {},ensure_ascii=False),now()))

 @commands.Cog.listener()
 async def on_member_join(self,member:discord.Member):
  if member.bot and self.bot.user and member.id==self.bot.user.id: return
  queue=self._join_times[member.guild.id]; current=time.monotonic(); queue.append(current)
  while queue and queue[0]<current-JOIN_BURST_WINDOW: queue.popleft()
  if len(queue)==JOIN_BURST_THRESHOLD:
   await self.record_signal(member.guild.id,"join_burst",severity="high",target_id=member.id,score=min(100,45+len(queue)*5),details={"joins_60s":len(queue)})
   try: await helpers.send_log(self.bot,member.guild,"automod",discord.Embed(title="Signal V10 — afflux inhabituel",description=f"**{len(queue)} arrivées** en moins de {int(JOIN_BURST_WINDOW)} secondes. Signal pour revue staff; aucune sanction supplémentaire n'est appliquée par V10.",colour=discord.Colour.orange()))
   except Exception: pass

 async def recent_signals(self,guild_id:int,limit:int=20)->list[dict]: return [dict(r) for r in await self.bot.db.fetchall("SELECT * FROM v10_operational_signals WHERE guild_id=? ORDER BY id DESC LIMIT ?",(guild_id,_clamp(limit,1,50)))]

 async def _operational_signals(self,ctx:commands.Context,limit:int=10):
  rows=await self.recent_signals(ctx.guild.id,limit)
  if not rows: return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun signal V10 enregistré.')))
  await panels.envoyer(ctx, panels.depuis_embed(embeds.brand('Signaux sécurité V10', '\n'.join((f"**#{r['id']} · {r['severity'].upper()} · {r['signal_type']}** — score {r['score']}/100 — <t:{r['created_at']}:R>" for r in rows)))))

 async def _security_overview(self,ctx:commands.Context):
  automod=await self.bot.db.get_automod(ctx.guild.id); fields=("antispam","antilink","antiinvite","antimention","anticaps","antiemoji","antiraid","antibot","antiaccount","antiscam","antinuke"); active=sum(1 for f in fields if automod and f in automod.keys() and automod[f]); count=await _count(self.bot,"SELECT COUNT(*) c FROM v10_operational_signals WHERE guild_id=? AND created_at>=?",(ctx.guild.id,now()-86400)); await panels.envoyer(ctx, panels.depuis_embed(embeds.brand('Sécurité V10 — vue globale', f'Protections AutoMod: **{active}/{len(fields)}**\nSignaux 24 h: **{count}**\nV10 ajoute des signaux et recommandations; la revue staff reste humaine.')))


async def setup(bot: commands.Bot):
 await bot.add_cog(BotV10(bot))
