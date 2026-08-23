"""Runtime V37 des fonctions configurables depuis le dashboard.

Aucune commande publique n'est ajoutée. Les systèmes sont pilotés par le dashboard :
automatisations, recrutements, vocaux temporaires, surveillance, planning staff,
événements, FAQ, santé serveur, sticky roles et panneaux personnalisés.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import discord

logger = logging.getLogger("bot.feature-suite-v37")
_BOT = None
_INSTALLED = False
_EVENT_TASK: asyncio.Task | None = None
_CACHE: dict[tuple[int, str], tuple[float, dict]] = {}

FEATURES = (
    "automations", "recruitment", "temp_voice", "surveillance", "staff_planning",
    "events", "faq", "health", "sticky_roles", "panels",
)

DEFAULTS: dict[str, dict[str, Any]] = {
    "automations": {"enabled": False},
    "recruitment": {"enabled": False, "review_channel_id": 0, "accepted_role_id": 0},
    "temp_voice": {"enabled": False, "lobby_channel_id": 0, "category_id": 0, "default_limit": 0, "name_template": "Vocal de {user}"},
    "surveillance": {"enabled": False, "log_channel_id": 0, "include_message_content": False},
    "staff_planning": {"enabled": False},
    "events": {"enabled": False, "default_channel_id": 0, "default_reminder_minutes": 30},
    "faq": {"enabled": False, "channel_id": 0, "minimum_score": 1},
    "health": {"enabled": True},
    "sticky_roles": {"enabled": False, "excluded_role_ids": []},
    "panels": {"enabled": False},
}


def _loads(value, fallback):
    try:
        data = json.loads(value or "")
        return data if isinstance(data, type(fallback)) else fallback
    except Exception:
        return fallback


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def ensure_tables(bot=None) -> None:
    bot = bot or _BOT
    if bot is None or not getattr(bot, "db", None):
        return
    statements = [
        """CREATE TABLE IF NOT EXISTS feature_suite_configs (
            guild_id INTEGER NOT NULL, feature TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL DEFAULT '{}', updated_by INTEGER, updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, feature)
        )""",
        """CREATE TABLE IF NOT EXISTS feature_suite_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, kind TEXT NOT NULL,
            name TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_feature_suite_items_guild_kind
            ON feature_suite_items(guild_id, kind, enabled)""",
        """CREATE TABLE IF NOT EXISTS feature_suite_watchlist (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, level TEXT NOT NULL DEFAULT 'normal',
            reason TEXT NOT NULL DEFAULT '', added_by INTEGER, created_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS feature_suite_sticky_roles (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, roles_json TEXT NOT NULL DEFAULT '[]',
            updated_at INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS feature_suite_temp_voice (
            channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS feature_suite_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, form_item_id INTEGER,
            user_id INTEGER NOT NULL, answers_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        )""",
    ]
    for sql in statements:
        await bot.db.execute(sql)


async def get_config(guild_id: int, feature: str, *, fresh: bool = False) -> dict:
    if feature not in FEATURES:
        raise ValueError("Fonction inconnue.")
    bot = _BOT
    if bot is None:
        return dict(DEFAULTS[feature])
    key = (int(guild_id), feature)
    cached = _CACHE.get(key)
    if not fresh and cached and cached[0] > time.monotonic():
        return dict(cached[1])
    await ensure_tables(bot)
    row = await bot.db.fetchone(
        "SELECT enabled, data_json FROM feature_suite_configs WHERE guild_id = ? AND feature = ?",
        (int(guild_id), feature),
    )
    result = dict(DEFAULTS[feature])
    if row:
        result.update(_loads(row["data_json"], {}))
        result["enabled"] = bool(row["enabled"])
    _CACHE[key] = (time.monotonic() + 20.0, dict(result))
    return result


def invalidate(guild_id: int, feature: str | None = None) -> None:
    gid = int(guild_id)
    if feature:
        _CACHE.pop((gid, feature), None)
    else:
        for key in list(_CACHE):
            if key[0] == gid:
                _CACHE.pop(key, None)


async def save_config(guild_id: int, feature: str, enabled: bool, data: dict, actor_id: int = 0) -> dict:
    if feature not in FEATURES or not isinstance(data, dict):
        raise ValueError("Configuration invalide.")
    await ensure_tables()
    clean = dict(DEFAULTS[feature])
    clean.update(data)
    clean["enabled"] = bool(enabled)
    payload = {k: v for k, v in clean.items() if k != "enabled"}
    now = int(time.time())
    await _BOT.db.execute(
        "INSERT INTO feature_suite_configs (guild_id, feature, enabled, data_json, updated_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, feature) DO UPDATE SET "
        "enabled=excluded.enabled, data_json=excluded.data_json, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (int(guild_id), feature, int(bool(enabled)), _dumps(payload), int(actor_id or 0), now),
    )
    invalidate(guild_id, feature)
    return await get_config(guild_id, feature, fresh=True)


async def list_items(guild_id: int, kind: str | None = None) -> list[dict]:
    await ensure_tables()
    if kind:
        rows = await _BOT.db.fetchall(
            "SELECT * FROM feature_suite_items WHERE guild_id = ? AND kind = ? ORDER BY id DESC",
            (int(guild_id), str(kind)),
        )
    else:
        rows = await _BOT.db.fetchall(
            "SELECT * FROM feature_suite_items WHERE guild_id = ? ORDER BY kind, id DESC",
            (int(guild_id),),
        )
    out = []
    for row in rows:
        item = dict(row)
        item["data"] = _loads(item.pop("data_json", "{}"), {})
        item["enabled"] = bool(item.get("enabled"))
        out.append(item)
    return out


async def get_item(guild_id: int, item_id: int) -> dict | None:
    await ensure_tables()
    row = await _BOT.db.fetchone(
        "SELECT * FROM feature_suite_items WHERE guild_id = ? AND id = ?",
        (int(guild_id), int(item_id)),
    )
    if not row:
        return None
    item = dict(row)
    item["data"] = _loads(item.pop("data_json", "{}"), {})
    item["enabled"] = bool(item.get("enabled"))
    return item


async def save_item(guild_id: int, kind: str, name: str, data: dict, actor_id: int = 0, *, item_id: int = 0, enabled: bool = True) -> int:
    if kind not in {"automation", "recruitment", "staff_shift", "event", "faq", "panel"}:
        raise ValueError("Type d'élément invalide.")
    if not isinstance(data, dict):
        raise ValueError("Données invalides.")
    await ensure_tables()
    now = int(time.time())
    if item_id:
        row = await _BOT.db.fetchone("SELECT id FROM feature_suite_items WHERE guild_id = ? AND id = ?", (int(guild_id), int(item_id)))
        if not row:
            raise ValueError("Élément introuvable.")
        await _BOT.db.execute(
            "UPDATE feature_suite_items SET kind=?, name=?, data_json=?, enabled=?, updated_at=? WHERE guild_id=? AND id=?",
            (kind, str(name)[:120], _dumps(data), int(bool(enabled)), now, int(guild_id), int(item_id)),
        )
        return int(item_id)
    await _BOT.db.execute(
        "INSERT INTO feature_suite_items (guild_id, kind, name, data_json, enabled, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (int(guild_id), kind, str(name)[:120], _dumps(data), int(bool(enabled)), int(actor_id or 0), now, now),
    )
    row = await _BOT.db.fetchone("SELECT last_insert_rowid() AS id")
    return int(row["id"] if row else 0)


async def delete_item(guild_id: int, item_id: int) -> None:
    await ensure_tables()
    await _BOT.db.execute("DELETE FROM feature_suite_items WHERE guild_id = ? AND id = ?", (int(guild_id), int(item_id)))


async def list_watch(guild_id: int) -> list[dict]:
    await ensure_tables()
    rows = await _BOT.db.fetchall(
        "SELECT user_id, level, reason, added_by, created_at FROM feature_suite_watchlist WHERE guild_id = ? ORDER BY created_at DESC",
        (int(guild_id),),
    )
    return [dict(r) for r in rows]


async def set_watch(guild_id: int, user_id: int, level: str, reason: str, actor_id: int) -> None:
    await ensure_tables()
    if level not in {"low", "normal", "high"}:
        level = "normal"
    await _BOT.db.execute(
        "INSERT INTO feature_suite_watchlist (guild_id,user_id,level,reason,added_by,created_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id,user_id) DO UPDATE SET level=excluded.level, reason=excluded.reason, added_by=excluded.added_by, created_at=excluded.created_at",
        (int(guild_id), int(user_id), level, str(reason)[:1000], int(actor_id), int(time.time())),
    )


async def remove_watch(guild_id: int, user_id: int) -> None:
    await ensure_tables()
    await _BOT.db.execute("DELETE FROM feature_suite_watchlist WHERE guild_id=? AND user_id=?", (int(guild_id), int(user_id)))


async def _is_watched(guild_id: int, user_id: int):
    await ensure_tables()
    return await _BOT.db.fetchone(
        "SELECT level, reason FROM feature_suite_watchlist WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )


async def _log_watch(member: discord.abc.User, guild: discord.Guild, text: str) -> None:
    conf = await get_config(guild.id, "surveillance")
    if not conf.get("enabled"):
        return
    row = await _is_watched(guild.id, member.id)
    if not row:
        return
    channel = guild.get_channel(int(conf.get("log_channel_id") or 0))
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(
                f"Surveillance {str(row['level']).upper()} — {member.mention} (`{member.id}`)\n{text[:1700]}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", str(value).casefold())}


async def _faq_reply(message: discord.Message) -> bool:
    conf = await get_config(message.guild.id, "faq")
    if not conf.get("enabled") or int(conf.get("channel_id") or 0) != message.channel.id:
        return False
    items = await list_items(message.guild.id, "faq")
    query = _tokens(message.content)
    best = None
    best_score = 0
    for item in items:
        if not item["enabled"]:
            continue
        data = item["data"]
        corpus = _tokens(item["name"] + " " + str(data.get("keywords") or "") + " " + str(data.get("question") or ""))
        score = len(query & corpus)
        if score > best_score:
            best, best_score = item, score
    if best and best_score >= max(1, int(conf.get("minimum_score") or 1)):
        answer = str(best["data"].get("answer") or "").strip()
        if answer:
            try:
                await message.reply(answer[:1900], mention_author=False, allowed_mentions=discord.AllowedMentions.none())
                return True
            except discord.HTTPException:
                pass
    return False


async def _run_automations(trigger: str, guild: discord.Guild, member: discord.Member | None = None, message: discord.Message | None = None) -> None:
    conf = await get_config(guild.id, "automations")
    if not conf.get("enabled"):
        return
    for item in await list_items(guild.id, "automation"):
        if not item["enabled"]:
            continue
        data = item["data"]
        if str(data.get("trigger") or "") != trigger:
            continue
        keyword = str(data.get("keyword") or "").casefold().strip()
        if trigger == "message_keyword" and keyword and (not message or keyword not in message.content.casefold()):
            continue
        action = str(data.get("action") or "send_channel")
        target_member = member or (message.author if message and isinstance(message.author, discord.Member) else None)
        try:
            if action == "send_channel":
                channel = guild.get_channel(int(data.get("channel_id") or 0))
                if isinstance(channel, discord.TextChannel):
                    text = str(data.get("message") or "Automatisation SentriX").replace("{member}", target_member.mention if target_member else "membre")
                    await channel.send(text[:1900], allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            elif action in {"add_role", "remove_role"} and target_member:
                role = guild.get_role(int(data.get("role_id") or 0))
                if role and guild.me and role < guild.me.top_role:
                    if action == "add_role":
                        await target_member.add_roles(role, reason="Automatisation SentriX V37")
                    else:
                        await target_member.remove_roles(role, reason="Automatisation SentriX V37")
            elif action == "dm" and target_member:
                await target_member.send(str(data.get("message") or "Message automatique SentriX")[:1900])
        except (discord.HTTPException, discord.Forbidden):
            logger.warning("Automatisation V37 impossible sur %s (%s)", guild.name, item["id"])


async def _on_member_remove(member: discord.Member):
    if member.bot:
        return
    conf = await get_config(member.guild.id, "sticky_roles")
    if conf.get("enabled"):
        excluded = {int(x) for x in conf.get("excluded_role_ids", []) if str(x).isdigit()}
        roles = [r.id for r in member.roles if not r.is_default() and not r.managed and r.id not in excluded]
        await ensure_tables()
        await _BOT.db.execute(
            "INSERT INTO feature_suite_sticky_roles (guild_id,user_id,roles_json,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET roles_json=excluded.roles_json, updated_at=excluded.updated_at",
            (member.guild.id, member.id, _dumps(roles), int(time.time())),
        )
    await _run_automations("member_leave", member.guild, member=member)
    await _log_watch(member, member.guild, "Le membre a quitté le serveur.")


async def _on_member_join(member: discord.Member):
    if member.bot:
        return
    conf = await get_config(member.guild.id, "sticky_roles")
    if conf.get("enabled"):
        await ensure_tables()
        row = await _BOT.db.fetchone("SELECT roles_json FROM feature_suite_sticky_roles WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
        if row:
            roles = []
            for role_id in _loads(row["roles_json"], []):
                role = member.guild.get_role(int(role_id))
                if role and not role.managed and member.guild.me and role < member.guild.me.top_role:
                    roles.append(role)
            if roles:
                try:
                    await member.add_roles(*roles, reason="Sticky Roles SentriX V37")
                except discord.HTTPException:
                    pass
    await _run_automations("member_join", member.guild, member=member)
    await _log_watch(member, member.guild, "Le membre a rejoint le serveur.")


async def _on_message(message: discord.Message):
    if not message.guild or message.author.bot:
        return
    conf = await get_config(message.guild.id, "surveillance")
    if conf.get("enabled") and await _is_watched(message.guild.id, message.author.id):
        detail = f"Message envoyé dans {message.channel.mention}."
        if conf.get("include_message_content"):
            detail += f"\nContenu : {message.content[:1400]}"
        await _log_watch(message.author, message.guild, detail)
    await _faq_reply(message)
    await _run_automations("message_keyword", message.guild, message=message)


async def _on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or before.author.bot or before.content == after.content:
        return
    conf = await get_config(before.guild.id, "surveillance")
    if conf.get("enabled") and conf.get("include_message_content") and await _is_watched(before.guild.id, before.author.id):
        await _log_watch(before.author, before.guild, f"Message modifié dans {before.channel.mention}.\nAvant : {before.content[:650]}\nAprès : {after.content[:650]}")


async def _on_message_delete(message: discord.Message):
    if not message.guild or message.author.bot:
        return
    conf = await get_config(message.guild.id, "surveillance")
    if conf.get("enabled") and await _is_watched(message.guild.id, message.author.id):
        detail = f"Message supprimé dans {message.channel.mention}."
        if conf.get("include_message_content"):
            detail += f"\nContenu : {message.content[:1400]}"
        await _log_watch(message.author, message.guild, detail)


async def _on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return
    conf = await get_config(member.guild.id, "temp_voice")
    if conf.get("enabled") and after.channel and after.channel.id == int(conf.get("lobby_channel_id") or 0):
        category = member.guild.get_channel(int(conf.get("category_id") or 0))
        if not isinstance(category, discord.CategoryChannel):
            category = after.channel.category
        name = str(conf.get("name_template") or "Vocal de {user}").replace("{user}", member.display_name)[:90]
        limit = max(0, min(99, int(conf.get("default_limit") or 0)))
        try:
            channel = await member.guild.create_voice_channel(name=name, category=category, user_limit=limit, reason="Vocal temporaire SentriX V37")
            await channel.set_permissions(member, view_channel=True, connect=True, speak=True, move_members=True, manage_channels=True)
            await ensure_tables()
            await _BOT.db.execute(
                "INSERT OR REPLACE INTO feature_suite_temp_voice (channel_id,guild_id,owner_id,created_at) VALUES (?,?,?,?)",
                (channel.id, member.guild.id, member.id, int(time.time())),
            )
            await member.move_to(channel, reason="Création vocal temporaire SentriX V37")
        except discord.HTTPException:
            logger.warning("Création vocal temporaire impossible sur %s", member.guild.name)
    if before.channel and (not after.channel or before.channel.id != after.channel.id):
        await ensure_tables()
        row = await _BOT.db.fetchone("SELECT channel_id FROM feature_suite_temp_voice WHERE channel_id=?", (before.channel.id,))
        if row and not before.channel.members:
            try:
                await before.channel.delete(reason="Vocal temporaire vide SentriX V37")
            except discord.HTTPException:
                pass
            await _BOT.db.execute("DELETE FROM feature_suite_temp_voice WHERE channel_id=?", (before.channel.id,))


class RecruitmentModal(discord.ui.Modal):
    def __init__(self, guild_id: int, item: dict):
        super().__init__(title=str(item["name"])[:45] or "Candidature")
        self.guild_id = int(guild_id)
        self.item = item
        questions = item["data"].get("questions") or ["Pourquoi voulez-vous rejoindre le staff ?", "Parlez-nous de votre expérience."]
        self.inputs = []
        for index, question in enumerate(list(questions)[:5]):
            field = discord.ui.TextInput(label=str(question)[:45], style=discord.TextStyle.paragraph, required=True, max_length=1000, custom_id=f"q{index}")
            self.add_item(field)
            self.inputs.append((str(question), field))

    async def on_submit(self, interaction: discord.Interaction):
        answers = [{"question": q, "answer": str(field.value)} for q, field in self.inputs]
        now = int(time.time())
        await ensure_tables()
        await _BOT.db.execute(
            "INSERT INTO feature_suite_applications (guild_id,form_item_id,user_id,answers_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (self.guild_id, int(self.item["id"]), interaction.user.id, _dumps(answers), "pending", now, now),
        )
        conf = await get_config(self.guild_id, "recruitment")
        review_id = int(self.item["data"].get("review_channel_id") or conf.get("review_channel_id") or 0)
        channel = interaction.guild.get_channel(review_id) if interaction.guild else None
        if isinstance(channel, discord.TextChannel):
            description = "\n\n".join(f"**{a['question']}**\n{a['answer'][:700]}" for a in answers)
            embed = discord.Embed(title=f"Candidature — {self.item['name']}", description=description[:3900], color=0x5865F2)
            embed.add_field(name="Membre", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
        await interaction.response.send_message("Votre candidature a bien été envoyée au staff.", ephemeral=True)


async def publish_recruitment(guild: discord.Guild, item: dict) -> int:
    data = item["data"]
    channel = guild.get_channel(int(data.get("channel_id") or 0))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Choisissez un salon textuel valide pour le panel de recrutement.")
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label=str(data.get("button_label") or "Postuler")[:80], style=discord.ButtonStyle.primary, custom_id=f"sentrix:v37:recruit:{item['id']}"))
    embed = discord.Embed(title=str(item["name"])[:256], description=str(data.get("description") or "Les candidatures sont ouvertes.")[:4000], color=0x5865F2)
    sent = await channel.send(embed=embed, view=view)
    return sent.id


async def publish_event(guild: discord.Guild, item: dict) -> int:
    data = item["data"]
    channel = guild.get_channel(int(data.get("channel_id") or 0))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Choisissez un salon textuel valide pour l'événement.")
    starts = int(data.get("starts_at") or 0)
    desc = str(data.get("description") or "")
    if starts:
        desc += f"\n\nDébut : <t:{starts}:F> (<t:{starts}:R>)"
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Participer", style=discord.ButtonStyle.success, custom_id=f"sentrix:v37:event:{item['id']}:join"))
    view.add_item(discord.ui.Button(label="Se retirer", style=discord.ButtonStyle.secondary, custom_id=f"sentrix:v37:event:{item['id']}:leave"))
    embed = discord.Embed(title=str(item["name"])[:256], description=desc[:4000], color=0x5865F2)
    sent = await channel.send(embed=embed, view=view)
    data["message_id"] = sent.id
    data["participants"] = data.get("participants") or []
    await save_item(guild.id, "event", item["name"], data, item_id=item["id"], enabled=item["enabled"])
    return sent.id


async def publish_panel(guild: discord.Guild, item: dict) -> int:
    data = item["data"]
    channel = guild.get_channel(int(data.get("channel_id") or 0))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Choisissez un salon textuel valide pour le panneau.")
    view = discord.ui.View(timeout=None)
    buttons = data.get("buttons") or []
    for idx, button in enumerate(buttons[:5]):
        action = str(button.get("action") or "message")
        if action == "link" and str(button.get("url") or "").startswith(("https://", "http://")):
            view.add_item(discord.ui.Button(label=str(button.get("label") or "Ouvrir")[:80], style=discord.ButtonStyle.link, url=str(button["url"])))
        else:
            view.add_item(discord.ui.Button(label=str(button.get("label") or "Action")[:80], style=discord.ButtonStyle.secondary, custom_id=f"sentrix:v37:panel:{item['id']}:{idx}"))
    embed = discord.Embed(title=str(item["name"])[:256], description=str(data.get("description") or "")[:4000], color=int(data.get("color") or 0x5865F2))
    sent = await channel.send(embed=embed, view=view)
    return sent.id


async def _handle_panel_interaction(interaction: discord.Interaction, item_id: int, idx: int):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    item = await get_item(interaction.guild.id, item_id)
    if not item or item["kind"] != "panel" or not item["enabled"]:
        return await interaction.response.send_message("Ce panneau n'est plus actif.", ephemeral=True)
    buttons = item["data"].get("buttons") or []
    if idx < 0 or idx >= len(buttons):
        return await interaction.response.send_message("Action introuvable.", ephemeral=True)
    button = buttons[idx]
    action = str(button.get("action") or "message")
    try:
        if action in {"add_role", "remove_role", "toggle_role"}:
            role = interaction.guild.get_role(int(button.get("role_id") or 0))
            if not role or role.managed or not interaction.guild.me or role >= interaction.guild.me.top_role:
                raise ValueError("Ce rôle n'est pas attribuable par SentriX.")
            if action == "add_role":
                await interaction.user.add_roles(role, reason="Panneau SentriX V37")
                text = f"Le rôle {role.name} a été ajouté."
            elif action == "remove_role":
                await interaction.user.remove_roles(role, reason="Panneau SentriX V37")
                text = f"Le rôle {role.name} a été retiré."
            elif role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Panneau SentriX V37")
                text = f"Le rôle {role.name} a été retiré."
            else:
                await interaction.user.add_roles(role, reason="Panneau SentriX V37")
                text = f"Le rôle {role.name} a été ajouté."
        else:
            text = str(button.get("message") or "Action effectuée.")[:1900]
        await interaction.response.send_message(text, ephemeral=True)
    except (discord.HTTPException, ValueError) as exc:
        await interaction.response.send_message(str(exc)[:500] or "Action impossible.", ephemeral=True)


async def _handle_event_interaction(interaction: discord.Interaction, item_id: int, action: str):
    if not interaction.guild:
        return
    item = await get_item(interaction.guild.id, item_id)
    if not item or item["kind"] != "event" or not item["enabled"]:
        return await interaction.response.send_message("Cet événement n'est plus actif.", ephemeral=True)
    data = item["data"]
    participants = [int(x) for x in data.get("participants", []) if str(x).isdigit()]
    uid = interaction.user.id
    if action == "join":
        maximum = max(0, int(data.get("max_participants") or 0))
        if uid in participants:
            text = "Vous êtes déjà inscrit."
        elif maximum and len(participants) >= maximum:
            text = "L'événement est complet."
        else:
            participants.append(uid)
            text = "Inscription enregistrée."
    else:
        if uid in participants:
            participants.remove(uid)
            text = "Vous avez quitté l'événement."
        else:
            text = "Vous n'étiez pas inscrit."
    data["participants"] = participants
    await save_item(interaction.guild.id, "event", item["name"], data, item_id=item_id, enabled=item["enabled"])
    await interaction.response.send_message(f"{text} Participants : {len(participants)}.", ephemeral=True)


async def _on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component or not interaction.guild:
        return
    custom_id = str((interaction.data or {}).get("custom_id") or "")
    if custom_id.startswith("sentrix:v37:recruit:"):
        try:
            item_id = int(custom_id.rsplit(":", 1)[1])
        except ValueError:
            return
        conf = await get_config(interaction.guild.id, "recruitment")
        item = await get_item(interaction.guild.id, item_id)
        if not conf.get("enabled") or not item or item["kind"] != "recruitment" or not item["enabled"]:
            return await interaction.response.send_message("Les candidatures sont actuellement fermées.", ephemeral=True)
        return await interaction.response.send_modal(RecruitmentModal(interaction.guild.id, item))
    if custom_id.startswith("sentrix:v37:panel:"):
        parts = custom_id.split(":")
        if len(parts) == 5 and parts[3].isdigit() and parts[4].isdigit():
            return await _handle_panel_interaction(interaction, int(parts[3]), int(parts[4]))
    if custom_id.startswith("sentrix:v37:event:"):
        parts = custom_id.split(":")
        if len(parts) == 5 and parts[3].isdigit() and parts[4] in {"join", "leave"}:
            return await _handle_event_interaction(interaction, int(parts[3]), parts[4])


async def _event_loop(bot):
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = int(time.time())
        try:
            await ensure_tables(bot)
            rows = await bot.db.fetchall("SELECT id,guild_id,name,data_json,enabled FROM feature_suite_items WHERE kind='event' AND enabled=1")
            for row in rows:
                guild = bot.get_guild(int(row["guild_id"]))
                if not guild:
                    continue
                conf = await get_config(guild.id, "events")
                if not conf.get("enabled"):
                    continue
                data = _loads(row["data_json"], {})
                starts = int(data.get("starts_at") or 0)
                reminder = max(0, int(data.get("reminder_minutes") or conf.get("default_reminder_minutes") or 30))
                if not starts or data.get("reminder_sent") or now < starts - reminder * 60 or now >= starts:
                    continue
                channel = guild.get_channel(int(data.get("channel_id") or conf.get("default_channel_id") or 0))
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(f"Rappel : **{str(row['name'])[:150]}** commence <t:{starts}:R>.")
                        data["reminder_sent"] = True
                        await save_item(guild.id, "event", str(row["name"]), data, item_id=int(row["id"]), enabled=True)
                    except discord.HTTPException:
                        pass
        except Exception:
            logger.exception("Boucle événements V37 en erreur.")
        await asyncio.sleep(60)


def install(bot) -> None:
    global _BOT, _INSTALLED, _EVENT_TASK
    _BOT = bot
    if _INSTALLED:
        return
    _INSTALLED = True
    bot.add_listener(_on_member_join, "on_member_join")
    bot.add_listener(_on_member_remove, "on_member_remove")
    bot.add_listener(_on_message, "on_message")
    bot.add_listener(_on_message_edit, "on_message_edit")
    bot.add_listener(_on_message_delete, "on_message_delete")
    bot.add_listener(_on_voice_state_update, "on_voice_state_update")
    bot.add_listener(_on_interaction, "on_interaction")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ensure_tables(bot))
        _EVENT_TASK = loop.create_task(_event_loop(bot))
    except RuntimeError:
        pass
    logger.info("Feature Suite V37 installée : 10 systèmes configurables sans commandes publiques.")
