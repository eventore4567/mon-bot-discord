"""Engagement V3 — onboarding, profils, quêtes, saisons, suggestions, starboard et IA staff.

Cette suite est volontairement pilotée par listeners + dashboard afin de ne pas consommer
le budget des 100 commandes slash. Elle fonctionne sur SentriX et Bot'Odboug avec la même
base de code et respecte l'identité de l'instance au runtime.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import discord

from utils import sentrix_panels as panels
from discord.ext import commands

from database.db import now
from utils.instance_identity import brand_label

logger = logging.getLogger("bot.engagement-v3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS engagement_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    onboarding_enabled INTEGER NOT NULL DEFAULT 0,
    onboarding_channel_id INTEGER,
    onboarding_role_ids TEXT NOT NULL DEFAULT '[]',
    profiles_enabled INTEGER NOT NULL DEFAULT 1,
    quests_enabled INTEGER NOT NULL DEFAULT 1,
    suggestions_enabled INTEGER NOT NULL DEFAULT 0,
    suggestions_channel_id INTEGER,
    starboard_enabled INTEGER NOT NULL DEFAULT 0,
    starboard_channel_id INTEGER,
    starboard_emoji TEXT NOT NULL DEFAULT '⭐',
    starboard_threshold INTEGER NOT NULL DEFAULT 5,
    context_review_enabled INTEGER NOT NULL DEFAULT 0,
    context_review_channel_id INTEGER,
    ticket_ai_enabled INTEGER NOT NULL DEFAULT 1,
    season_length_days INTEGER NOT NULL DEFAULT 30,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS engagement_members (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'fr',
    points INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    voice_seconds INTEGER NOT NULL DEFAULT 0,
    reactions_received INTEGER NOT NULL DEFAULT 0,
    suggestions_count INTEGER NOT NULL DEFAULT 0,
    quests_completed INTEGER NOT NULL DEFAULT 0,
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    joined_at INTEGER NOT NULL DEFAULT 0,
    last_seen_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS engagement_achievements (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    achievement_key TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, achievement_key)
);
CREATE TABLE IF NOT EXISTS engagement_quest_progress (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    period_key TEXT NOT NULL,
    quest_key TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    target INTEGER NOT NULL,
    reward INTEGER NOT NULL,
    claimed INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, period_key, quest_key)
);
CREATE TABLE IF NOT EXISTS engagement_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_engagement_seasons_guild ON engagement_seasons (guild_id, status, ends_at DESC);
CREATE TABLE IF NOT EXISTS engagement_season_scores (
    guild_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, season_id, user_id)
);
CREATE TABLE IF NOT EXISTS engagement_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    staff_note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_engagement_suggestions_guild ON engagement_suggestions (guild_id, status, created_at DESC);
CREATE TABLE IF NOT EXISTS engagement_starboard (
    guild_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    source_channel_id INTEGER NOT NULL,
    starboard_message_id INTEGER,
    score INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, source_message_id)
);
CREATE TABLE IF NOT EXISTS engagement_context_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_engagement_context_reviews_guild ON engagement_context_reviews (guild_id, status, created_at DESC);
CREATE TABLE IF NOT EXISTS engagement_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""

QUESTS = {
    "daily_messages": {"period": "daily", "stat": "message_count", "target": 20, "reward": 120, "label": "Envoyer 20 messages"},
    "daily_voice": {"period": "daily", "stat": "voice_seconds", "target": 900, "reward": 160, "label": "Passer 15 min en vocal"},
    "daily_reactions": {"period": "daily", "stat": "reactions_received", "target": 3, "reward": 90, "label": "Recevoir 3 réactions"},
    "weekly_messages": {"period": "weekly", "stat": "message_count", "target": 100, "reward": 550, "label": "Envoyer 100 messages"},
    "weekly_voice": {"period": "weekly", "stat": "voice_seconds", "target": 7200, "reward": 650, "label": "Passer 2 h en vocal"},
    "weekly_suggestion": {"period": "weekly", "stat": "suggestions_count", "target": 1, "reward": 260, "label": "Proposer une suggestion"},
}

ACHIEVEMENTS = {
    "first_message": ("message_count", 1, "Premier message"),
    "chatty_100": ("message_count", 100, "Bavard — 100 messages"),
    "chatty_1000": ("message_count", 1000, "Pilier du chat — 1 000 messages"),
    "voice_hour": ("voice_seconds", 3600, "Habitué du vocal — 1 h"),
    "voice_10h": ("voice_seconds", 36000, "Voix de la communauté — 10 h"),
    "popular_25": ("reactions_received", 25, "Populaire — 25 réactions"),
    "suggestion_first": ("suggestions_count", 1, "Première suggestion"),
    "quest_10": ("quests_completed", 10, "Mission accomplie — 10 quêtes"),
    "points_1000": ("points", 1000, "1 000 points d'engagement"),
    "points_10000": ("points", 10000, "10 000 points d'engagement"),
}

_TOXIC_WORDS = {
    "fdp", "pute", "connard", "connasse", "batard", "bâtard", "encule", "enculé",
    "ntm", "salope", "merde", "fuck you", "motherfucker", "bitch", "nigger", "kys",
}


def _loads(value: str | None, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


def _daily_key(ts: int | None = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), timezone.utc)
    return f"d:{dt:%Y-%m-%d}"


def _weekly_key(ts: int | None = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"w:{year}-{week:02d}"


def _profile_url(guild_id: int) -> str | None:
    base = (os.getenv("DASHBOARD_PUBLIC_URL") or "").strip().rstrip("/")
    if base.startswith(("https://", "http://")):
        return f"{base}/engagement/profile/{guild_id}"
    return None


class OnboardingMemberView(discord.ui.View):
    def __init__(self, service: "EngagementSuite", member: discord.Member, settings: dict[str, Any]):
        super().__init__(timeout=300)
        self.service = service
        self.member = member
        self.settings = settings

        language = discord.ui.Select(
            placeholder='Langue de votre profil / Profile language',
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Français", value="fr"),
                discord.SelectOption(label="English", value="en"),
            ],
            row=0,
        )

        async def language_callback(interaction: discord.Interaction):
            if interaction.user.id != self.member.id:
                return await interaction.response.send_message("Ce panneau appartient à un autre membre.", ephemeral=True)
            await self.service.set_preferred_language(self.member.guild.id, self.member.id, language.values[0])
            await interaction.response.send_message("Langue enregistrée.", ephemeral=True)

        language.callback = language_callback
        self.add_item(language)

        role_ids = [int(x) for x in _loads(settings.get("onboarding_role_ids"), []) if str(x).isdigit()]
        role_options = []
        for role_id in role_ids[:20]:
            role = member.guild.get_role(role_id)
            if role and not role.managed:
                role_options.append(discord.SelectOption(label=role.name[:100], value=str(role.id)))
        if role_options:
            roles = discord.ui.Select(
                placeholder='Choisissez vos rôles / interests',
                min_values=0,
                max_values=min(5, len(role_options)),
                options=role_options,
                row=1,
            )

            async def role_callback(interaction: discord.Interaction):
                if interaction.user.id != self.member.id:
                    return await interaction.response.send_message("Ce panneau appartient à un autre membre.", ephemeral=True)
                me = self.member.guild.me
                configured = {int(o.value) for o in role_options}
                selected = {int(v) for v in roles.values}
                to_add = []
                to_remove = []
                for role_id in configured:
                    role = self.member.guild.get_role(role_id)
                    if role is None or role.managed or me is None or role >= me.top_role:
                        continue
                    if role_id in selected and role not in self.member.roles:
                        to_add.append(role)
                    elif role_id not in selected and role in self.member.roles:
                        to_remove.append(role)
                try:
                    if to_add:
                        await self.member.add_roles(*to_add, reason=f"Onboarding {brand_label()}")
                    if to_remove:
                        await self.member.remove_roles(*to_remove, reason=f"Onboarding {brand_label()}")
                    await interaction.response.send_message('Vos rôles ont été mis à jour.', ephemeral=True)
                except (discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message("Je n'ai pas la permission de modifier un de ces rôles.", ephemeral=True)

            roles.callback = role_callback
            self.add_item(roles)

        finish = discord.ui.Button(label="J'accepte le règlement et je termine", style=discord.ButtonStyle.success, row=2)

        async def finish_callback(interaction: discord.Interaction):
            if interaction.user.id != self.member.id:
                return await interaction.response.send_message("Ce panneau appartient à un autre membre.", ephemeral=True)
            first = await self.service.complete_onboarding(self.member)
            text = "Onboarding terminé. Bienvenue dans la communauté !"
            if first:
                text += " Tu gagnes 100 points d'engagement."
            url = _profile_url(self.member.guild.id)
            if url:
                text += f"\nTon profil : {url}"
            await interaction.response.edit_message(content=text, embed=None, view=None)

        finish.callback = finish_callback
        self.add_item(finish)


class OnboardingStartView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        start = discord.ui.Button(
            label="Commencer mon onboarding",
            style=discord.ButtonStyle.primary,
            custom_id="sentrix:engagement:onboarding:start",
        )

        async def start_callback(interaction: discord.Interaction):
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return await interaction.response.send_message("Ce bouton fonctionne uniquement dans un serveur.", ephemeral=True)
            service = self.bot.get_cog("EngagementSuite")
            if service is None:
                return await interaction.response.send_message('Le module communauté démarre. Réessayez dans quelques secondes.', ephemeral=True)
            settings = await service.get_settings(interaction.guild.id)
            await interaction.response.send_message(
                'Configurez votre profil, choisis vos rôles puis validez le règlement.',
                view=OnboardingMemberView(service, interaction.user, settings),
                ephemeral=True,
            )

        start.callback = start_callback
        self.add_item(start)


class EngagementSuite(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._message_points_at: dict[tuple[int, int], float] = {}
        self._voice_started: dict[tuple[int, int], float] = {}
        self._recent_messages: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(lambda: deque(maxlen=8))

    async def ensure_settings(self, guild_id: int) -> None:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO engagement_settings (guild_id,updated_at) VALUES (?,?)",
            (int(guild_id), now()),
        )

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        await self.ensure_settings(guild_id)
        row = await self.bot.db.fetchone("SELECT * FROM engagement_settings WHERE guild_id=?", (int(guild_id),))
        return dict(row) if row else {}

    async def update_settings(self, guild: discord.Guild, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "enabled", "onboarding_enabled", "onboarding_channel_id", "onboarding_role_ids",
            "profiles_enabled", "quests_enabled", "suggestions_enabled", "suggestions_channel_id",
            "starboard_enabled", "starboard_channel_id", "starboard_emoji", "starboard_threshold",
            "context_review_enabled", "context_review_channel_id", "ticket_ai_enabled", "season_length_days",
        }
        clean = {k: v for k, v in values.items() if k in allowed}
        for key in ("enabled", "onboarding_enabled", "profiles_enabled", "quests_enabled", "suggestions_enabled", "starboard_enabled", "context_review_enabled", "ticket_ai_enabled"):
            if key in clean:
                clean[key] = int(bool(clean[key]))
        for key in ("onboarding_channel_id", "suggestions_channel_id", "starboard_channel_id", "context_review_channel_id"):
            if key in clean:
                value = clean[key]
                clean[key] = int(value) if value not in (None, "", "0", 0) else None
        if "onboarding_role_ids" in clean:
            raw = clean["onboarding_role_ids"] if isinstance(clean["onboarding_role_ids"], list) else []
            ids = []
            for value in raw[:20]:
                try:
                    role = guild.get_role(int(value))
                except (TypeError, ValueError):
                    role = None
                if role and not role.managed and not role.is_default():
                    ids.append(role.id)
            clean["onboarding_role_ids"] = json.dumps(ids)
        if "starboard_threshold" in clean:
            clean["starboard_threshold"] = max(2, min(50, int(clean["starboard_threshold"] or 5)))
        if "starboard_emoji" in clean:
            clean["starboard_emoji"] = str(clean["starboard_emoji"] or "⭐")[:80]
        if "season_length_days" in clean:
            clean["season_length_days"] = max(7, min(120, int(clean["season_length_days"] or 30)))
        await self.ensure_settings(guild.id)
        if clean:
            parts = [f"{k}=?" for k in clean]
            await self.bot.db.execute(
                f"UPDATE engagement_settings SET {', '.join(parts)},updated_at=? WHERE guild_id=?",
                tuple(clean.values()) + (now(), guild.id),
            )
        return await self.get_settings(guild.id)

    async def _ensure_member(self, guild_id: int, user_id: int, *, joined_at: int = 0) -> None:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO engagement_members (guild_id,user_id,joined_at,last_seen_at) VALUES (?,?,?,?)",
            (int(guild_id), int(user_id), int(joined_at or 0), now()),
        )

    async def set_preferred_language(self, guild_id: int, user_id: int, language: str) -> None:
        await self._ensure_member(guild_id, user_id)
        value = "en" if language == "en" else "fr"
        await self.bot.db.execute(
            "UPDATE engagement_members SET preferred_language=?,last_seen_at=? WHERE guild_id=? AND user_id=?",
            (value, now(), int(guild_id), int(user_id)),
        )

    async def _active_season(self, guild_id: int) -> dict[str, Any]:
        settings = await self.get_settings(guild_id)
        ts = now()
        row = await self.bot.db.fetchone(
            "SELECT * FROM engagement_seasons WHERE guild_id=? AND status='active' ORDER BY id DESC LIMIT 1",
            (int(guild_id),),
        )
        if row and int(row["ends_at"]) > ts:
            return dict(row)
        if row:
            await self.bot.db.execute("UPDATE engagement_seasons SET status='closed' WHERE id=?", (int(row["id"]),))
        days = max(7, min(120, int(settings.get("season_length_days") or 30)))
        cursor = await self.bot.db.execute(
            "INSERT INTO engagement_seasons (guild_id,starts_at,ends_at,status) VALUES (?,?,?,'active')",
            (int(guild_id), ts, ts + days * 86400),
        )
        return {"id": int(cursor.lastrowid), "guild_id": int(guild_id), "starts_at": ts, "ends_at": ts + days * 86400, "status": "active"}

    async def add_points(self, guild_id: int, user_id: int, amount: int) -> None:
        amount = max(0, int(amount))
        if not amount:
            return
        await self._ensure_member(guild_id, user_id)
        await self.bot.db.execute(
            "UPDATE engagement_members SET points=points+?,last_seen_at=? WHERE guild_id=? AND user_id=?",
            (amount, now(), int(guild_id), int(user_id)),
        )
        season = await self._active_season(guild_id)
        await self.bot.db.execute(
            "INSERT INTO engagement_season_scores (guild_id,season_id,user_id,points) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,season_id,user_id) DO UPDATE SET points=points+excluded.points",
            (int(guild_id), int(season["id"]), int(user_id), amount),
        )
        await self._check_achievements(guild_id, user_id)

    async def _check_achievements(self, guild_id: int, user_id: int) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM engagement_members WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        if not row:
            return
        for key, (field, threshold, _label) in ACHIEVEMENTS.items():
            if int(row[field] or 0) < threshold:
                continue
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO engagement_achievements (guild_id,user_id,achievement_key,unlocked_at) VALUES (?,?,?,?)",
                (guild_id, user_id, key, now()),
            )

    async def _advance_quests(self, guild_id: int, user_id: int, stat: str, amount: int) -> None:
        settings = await self.get_settings(guild_id)
        if not int(settings.get("quests_enabled", 1)):
            return
        for quest_key, quest in QUESTS.items():
            if quest["stat"] != stat:
                continue
            period_key = _daily_key() if quest["period"] == "daily" else _weekly_key()
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO engagement_quest_progress (guild_id,user_id,period_key,quest_key,progress,target,reward,claimed,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (guild_id, user_id, period_key, quest_key, 0, quest["target"], quest["reward"], 0, now()),
            )
            await self.bot.db.execute(
                "UPDATE engagement_quest_progress SET progress=MIN(target,progress+?),updated_at=? WHERE guild_id=? AND user_id=? AND period_key=? AND quest_key=?",
                (int(amount), now(), guild_id, user_id, period_key, quest_key),
            )
            progress = await self.bot.db.fetchone(
                "SELECT * FROM engagement_quest_progress WHERE guild_id=? AND user_id=? AND period_key=? AND quest_key=?",
                (guild_id, user_id, period_key, quest_key),
            )
            if progress and int(progress["progress"]) >= int(progress["target"]) and not int(progress["claimed"]):
                await self.bot.db.execute(
                    "UPDATE engagement_quest_progress SET claimed=1,updated_at=? WHERE guild_id=? AND user_id=? AND period_key=? AND quest_key=?",
                    (now(), guild_id, user_id, period_key, quest_key),
                )
                await self.bot.db.execute(
                    "UPDATE engagement_members SET quests_completed=quests_completed+1 WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                await self.add_points(guild_id, user_id, int(progress["reward"]))

    async def advance_stat(self, guild_id: int, user_id: int, field: str, amount: int, *, points: int = 0) -> None:
        if field not in {"message_count", "voice_seconds", "reactions_received", "suggestions_count"}:
            return
        await self._ensure_member(guild_id, user_id)
        await self.bot.db.execute(
            f"UPDATE engagement_members SET {field}={field}+?,last_seen_at=? WHERE guild_id=? AND user_id=?",
            (max(0, int(amount)), now(), guild_id, user_id),
        )
        await self._advance_quests(guild_id, user_id, field, max(0, int(amount)))
        if points:
            await self.add_points(guild_id, user_id, points)
        else:
            await self._check_achievements(guild_id, user_id)

    async def complete_onboarding(self, member: discord.Member) -> bool:
        await self._ensure_member(member.guild.id, member.id, joined_at=int(member.joined_at.timestamp()) if member.joined_at else now())
        row = await self.bot.db.fetchone("SELECT onboarding_done FROM engagement_members WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
        first = not row or not int(row["onboarding_done"])
        await self.bot.db.execute(
            "UPDATE engagement_members SET onboarding_done=1,last_seen_at=? WHERE guild_id=? AND user_id=?",
            (now(), member.guild.id, member.id),
        )
        if first:
            await self.add_points(member.guild.id, member.id, 100)
        return first

    async def profile(self, guild: discord.Guild, user_id: int) -> dict[str, Any]:
        await self._ensure_member(guild.id, user_id)
        row = await self.bot.db.fetchone("SELECT * FROM engagement_members WHERE guild_id=? AND user_id=?", (guild.id, user_id))
        member = guild.get_member(user_id)
        achievements_rows = await self.bot.db.fetchall(
            "SELECT achievement_key,unlocked_at FROM engagement_achievements WHERE guild_id=? AND user_id=? ORDER BY unlocked_at DESC",
            (guild.id, user_id),
        )
        achievements = [
            {"key": r["achievement_key"], "label": ACHIEVEMENTS.get(r["achievement_key"], (None, None, r["achievement_key"]))[2], "unlocked_at": int(r["unlocked_at"])}
            for r in achievements_rows
        ]
        quests = []
        for quest_key, quest in QUESTS.items():
            period_key = _daily_key() if quest["period"] == "daily" else _weekly_key()
            progress = await self.bot.db.fetchone(
                "SELECT * FROM engagement_quest_progress WHERE guild_id=? AND user_id=? AND period_key=? AND quest_key=?",
                (guild.id, user_id, period_key, quest_key),
            )
            quests.append({
                "key": quest_key, "label": quest["label"], "period": quest["period"],
                "progress": int(progress["progress"]) if progress else 0,
                "target": int(quest["target"]), "reward": int(quest["reward"]),
                "claimed": bool(progress and int(progress["claimed"])),
            })
        season = await self._active_season(guild.id)
        score = await self.bot.db.fetchone(
            "SELECT points FROM engagement_season_scores WHERE guild_id=? AND season_id=? AND user_id=?",
            (guild.id, season["id"], user_id),
        )
        rank = await self.bot.db.fetchone(
            "SELECT 1+COUNT(*) AS rank FROM engagement_season_scores WHERE guild_id=? AND season_id=? AND points>?",
            (guild.id, season["id"], int(score["points"]) if score else 0),
        )
        return {
            "member": dict(row) if row else {},
            "display_name": member.display_name if member else str(user_id),
            "avatar_url": member.display_avatar.url if member else "",
            "achievements": achievements,
            "quests": quests,
            "season": {**season, "points": int(score["points"]) if score else 0, "rank": int(rank["rank"]) if rank else None},
        }

    async def leaderboard(self, guild_id: int, limit: int = 25) -> list[dict[str, Any]]:
        season = await self._active_season(guild_id)
        rows = await self.bot.db.fetchall(
            "SELECT user_id,points FROM engagement_season_scores WHERE guild_id=? AND season_id=? ORDER BY points DESC,user_id ASC LIMIT ?",
            (guild_id, season["id"], max(1, min(100, int(limit)))),
        )
        return [{"user_id": int(r["user_id"]), "points": int(r["points"])} for r in rows]

    async def list_suggestions(self, guild_id: int, status: str = "all") -> list[dict[str, Any]]:
        params: list[Any] = [guild_id]
        sql = "SELECT * FROM engagement_suggestions WHERE guild_id=?"
        if status != "all":
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT 250"
        return [dict(r) for r in await self.bot.db.fetchall(sql, tuple(params))]

    async def review_suggestion(self, guild: discord.Guild, suggestion_id: int, status: str, note: str) -> dict[str, Any]:
        if status not in {"pending", "accepted", "refused", "in_progress", "done"}:
            raise ValueError("Statut invalide.")
        row = await self.bot.db.fetchone("SELECT * FROM engagement_suggestions WHERE guild_id=? AND id=?", (guild.id, suggestion_id))
        if not row:
            raise ValueError("Suggestion introuvable.")
        await self.bot.db.execute(
            "UPDATE engagement_suggestions SET status=?,staff_note=?,updated_at=? WHERE guild_id=? AND id=?",
            (status, str(note or "")[:1200], now(), guild.id, suggestion_id),
        )
        channel = guild.get_channel(int(row["channel_id"]))
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(int(row["message_id"]))
                embed = message.embeds[0] if message.embeds else discord.Embed()
                embed.title = f"Suggestion #{suggestion_id} — {status.replace('_', ' ').title()}"
                embed.color = discord.Color.green() if status in {"accepted", "done"} else (discord.Color.red() if status == "refused" else discord.Color.blurple())
                if note:
                    existing = [f for f in embed.fields if f.name != "Réponse du staff"]
                    embed.clear_fields()
                    for field in existing:
                        embed.add_field(name=field.name, value=field.value, inline=field.inline)
                    embed.add_field(name="Réponse du staff", value=str(note)[:1024], inline=False)
                await message.edit(embed=embed)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        result = await self.bot.db.fetchone("SELECT * FROM engagement_suggestions WHERE guild_id=? AND id=?", (guild.id, suggestion_id))
        return dict(result) if result else {}

    async def list_reviews(self, guild_id: int, status: str = "pending") -> list[dict[str, Any]]:
        params: list[Any] = [guild_id]
        sql = "SELECT * FROM engagement_context_reviews WHERE guild_id=?"
        if status != "all":
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT 250"
        rows = await self.bot.db.fetchall(sql, tuple(params))
        result = []
        for row in rows:
            item = dict(row)
            item["reasons"] = _loads(item.pop("reasons_json", "[]"), [])
            result.append(item)
        return result

    async def resolve_review(self, guild_id: int, review_id: int, status: str) -> None:
        if status not in {"ignored", "reviewed", "action_taken"}:
            raise ValueError("Statut invalide.")
        await self.bot.db.execute(
            "UPDATE engagement_context_reviews SET status=?,updated_at=? WHERE guild_id=? AND id=?",
            (status, now(), guild_id, review_id),
        )

    async def summarize_ticket(self, channel: discord.TextChannel, actor_id: int) -> str:
        settings = await self.get_settings(channel.guild.id)
        if not int(settings.get("ticket_ai_enabled", 1)):
            raise ValueError("Le résumé IA des tickets est désactivé.")
        messages = []
        try:
            async for message in channel.history(limit=80, oldest_first=True):
                if not message.content or message.author.bot:
                    continue
                clean = " ".join(message.content.split())[:900]
                messages.append(f"{message.author.display_name}: {clean}")
        except (discord.Forbidden, discord.HTTPException) as exc:
            raise ValueError("Je ne peux pas lire l'historique de ce salon.") from exc
        if not messages:
            raise ValueError("Aucun message utilisateur à résumer dans ce salon.")
        from utils import ai_service
        prompt = (
            "Résume ce ticket Discord pour un membre du staff. Donne : 1) problème principal, "
            "2) faits importants, 3) actions déjà tentées, 4) prochaine action conseillée. "
            "Reste neutre, n'invente rien et signale les informations manquantes.\n\n" + "\n".join(messages)
        )
        result = await ai_service.generate(
            prompt,
            model_key=ai_service.MODEL_TERRA,
            reasoning_effort="low",
            guild_id=channel.guild.id,
            channel_id=channel.id,
            user_id=actor_id,
            command="ticket-ai-summary",
        )
        if not result.ok:
            raise ValueError(ai_service.error_message(result.error))
        return (result.text or "Résumé indisponible.")[:7000]

    async def list_changelog(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = await self.bot.db.fetchall("SELECT * FROM engagement_changelog ORDER BY created_at DESC,id DESC LIMIT ?", (max(1, min(100, limit)),))
        return [dict(r) for r in rows]

    async def add_changelog(self, version: str, title: str, body: str) -> int:
        cursor = await self.bot.db.execute(
            "INSERT INTO engagement_changelog (version,title,body,created_at) VALUES (?,?,?,?)",
            (str(version)[:40], str(title)[:120], str(body)[:4000], now()),
        )
        return int(cursor.lastrowid)

    async def _handle_suggestion(self, message: discord.Message, settings: dict[str, Any]) -> bool:
        if not int(settings.get("suggestions_enabled", 0)):
            return False
        channel_id = int(settings.get("suggestions_channel_id") or 0)
        if not channel_id or message.channel.id != channel_id or not message.content.strip():
            return False
        prefix = getattr(self.bot, "prefix_cache", {}).get(message.guild.id, "+")
        if message.content.startswith(prefix):
            return False
        cursor = await self.bot.db.execute(
            "INSERT INTO engagement_suggestions (guild_id,user_id,channel_id,message_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,'pending',?,?)",
            (message.guild.id, message.author.id, message.channel.id, 0, message.content[:3500], now(), now()),
        )
        suggestion_id = int(cursor.lastrowid)
        embed = discord.Embed(
            title=f"Suggestion #{suggestion_id} — En attente",
            description=message.content[:3900],
            color=discord.Color.blurple(),
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"{brand_label()} / Suggestions")
        sent = await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await self.bot.db.execute("UPDATE engagement_suggestions SET message_id=? WHERE id=?", (sent.id, suggestion_id))
        for emoji in ("👍", "👎"):
            try:
                await sent.add_reaction(emoji)
            except discord.HTTPException:
                pass
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass
        await self.advance_stat(message.guild.id, message.author.id, "suggestions_count", 1, points=25)
        return True

    async def _context_review(self, message: discord.Message, settings: dict[str, Any]) -> None:
        if not int(settings.get("context_review_enabled", 0)) or not message.content:
            return
        key = (message.guild.id, message.author.id)
        content = " ".join(message.content.casefold().split())[:1000]
        recent = self._recent_messages[key]
        ts = time.monotonic()
        recent.append((ts, content))
        reasons = []
        score = 0
        hits = sum(1 for word in _TOXIC_WORDS if word in content)
        if hits:
            score += min(5, hits * 2)
            reasons.append(f"langage agressif détecté ({hits})")
        alpha = [c for c in message.content if c.isalpha()]
        if len(alpha) >= 20 and sum(c.isupper() for c in alpha) / len(alpha) >= 0.8:
            score += 1
            reasons.append("message presque entièrement en majuscules")
        if len(message.mentions) >= 6:
            score += 2
            reasons.append("mentions nombreuses")
        same_recent = sum(1 for stamp, text in recent if ts - stamp <= 20 and text == content)
        if same_recent >= 3:
            score += 3
            reasons.append("répétition rapide du même message")
        toxic_recent = sum(1 for stamp, text in recent if ts - stamp <= 45 and any(word in text for word in _TOXIC_WORDS))
        if toxic_recent >= 3:
            score += 2
            reasons.append("agressivité répétée sur plusieurs messages")
        if score < 4:
            return
        exists = await self.bot.db.fetchone("SELECT id FROM engagement_context_reviews WHERE guild_id=? AND message_id=?", (message.guild.id, message.id))
        if exists:
            return
        cursor = await self.bot.db.execute(
            "INSERT INTO engagement_context_reviews (guild_id,user_id,channel_id,message_id,score,reasons_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,'pending',?,?)",
            (message.guild.id, message.author.id, message.channel.id, message.id, score, json.dumps(reasons, ensure_ascii=False), now(), now()),
        )
        review_id = int(cursor.lastrowid)
        channel = message.guild.get_channel(int(settings.get("context_review_channel_id") or 0))
        if isinstance(channel, discord.TextChannel):
            embed = discord.Embed(
                title=f"Révision contextuelle #{review_id}",
                description=(
                    f"Message de {message.author.mention} à vérifier par le staff.\n"
                    f"Score : **{score}**\nRaisons : " + ", ".join(reasons) +
                    f"\n[Lien vers le message]({message.jump_url})"
                ),
                color=discord.Color.orange(),
            )
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    async def _handle_starboard(self, payload: discord.RawReactionActionEvent, settings: dict[str, Any]) -> None:
        if not int(settings.get("starboard_enabled", 0)):
            return
        if str(payload.emoji) != str(settings.get("starboard_emoji") or "⭐"):
            return
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        target = payload.guild_id and self.bot.get_guild(payload.guild_id)
        if target is None:
            return
        starboard_channel = target.get_channel(int(settings.get("starboard_channel_id") or 0))
        if not isinstance(starboard_channel, discord.TextChannel) or starboard_channel.id == channel.id:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        reaction = next((r for r in message.reactions if str(r.emoji) == str(payload.emoji)), None)
        score = int(reaction.count) if reaction else 0
        threshold = max(2, int(settings.get("starboard_threshold") or 5))
        if score < threshold:
            return
        row = await self.bot.db.fetchone("SELECT * FROM engagement_starboard WHERE guild_id=? AND source_message_id=?", (target.id, message.id))
        embed = discord.Embed(description=message.content[:3900] or "Message sans texte", color=discord.Color.gold(), timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        if message.attachments:
            first = message.attachments[0]
            if first.content_type and first.content_type.startswith("image/"):
                embed.set_image(url=first.url)
        embed.add_field(name="Source", value=f"[Voir le message]({message.jump_url})", inline=False)
        embed.set_footer(text=f"{score} {payload.emoji} / {brand_label()} Starboard")
        star_message = None
        if row and row["starboard_message_id"]:
            try:
                star_message = await starboard_channel.fetch_message(int(row["starboard_message_id"]))
                await star_message.edit(embed=embed)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                star_message = None
        if star_message is None:
            try:
                star_message = await panels.envoyer(starboard_channel, panels.depuis_embed(embed))
            except discord.HTTPException:
                return
        await self.bot.db.execute(
            "INSERT INTO engagement_starboard (guild_id,source_message_id,source_channel_id,starboard_message_id,score,updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,source_message_id) DO UPDATE SET starboard_message_id=excluded.starboard_message_id,score=excluded.score,updated_at=excluded.updated_at",
            (target.id, message.id, channel.id, star_message.id, score, now()),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        await self._ensure_member(member.guild.id, member.id, joined_at=now())
        settings = await self.get_settings(member.guild.id)
        if not int(settings.get("onboarding_enabled", 0)):
            return
        channel = member.guild.get_channel(int(settings.get("onboarding_channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(
            title=f"Bienvenue sur {member.guild.name}",
            description=(
                f'{member.mention}, utilise le bouton ci-dessous pour choisir votre langue de profil, vos rôles et valider le règlement.'
            ),
            color=discord.Color.blurple(),
        )
        try:
            await channel.send(
                content=member.mention,
                embed=embed,
                view=OnboardingStartView(self.bot),
                allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        settings = await self.get_settings(message.guild.id)
        if not int(settings.get("enabled", 1)):
            return
        try:
            if await self._handle_suggestion(message, settings):
                return
        except Exception:
            logger.exception("Suggestion V3 impossible sur %s", message.guild.id)
        await self.advance_stat(message.guild.id, message.author.id, "message_count", 1)
        key = (message.guild.id, message.author.id)
        stamp = time.monotonic()
        if stamp - self._message_points_at.get(key, 0.0) >= 30:
            self._message_points_at[key] = stamp
            await self.add_points(message.guild.id, message.author.id, 2)
        try:
            await self._context_review(message, settings)
        except Exception:
            logger.exception("Révision contextuelle impossible sur %s", message.guild.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == getattr(self.bot.user, "id", None):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        settings = await self.get_settings(guild.id)
        try:
            await self._handle_starboard(payload, settings)
        except Exception:
            logger.exception("Starboard V3 impossible sur %s", guild.id)
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        if message.author.bot or message.author.id == payload.user_id:
            return
        await self.advance_stat(guild.id, message.author.id, "reactions_received", 1, points=2)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        key = (member.guild.id, member.id)
        if before.channel is None and after.channel is not None:
            self._voice_started[key] = time.monotonic()
            return
        if before.channel is not None and after.channel is None:
            started = self._voice_started.pop(key, None)
            if started is not None:
                seconds = max(0, int(time.monotonic() - started))
                if seconds >= 30:
                    await self.advance_stat(member.guild.id, member.id, "voice_seconds", seconds, points=max(1, seconds // 300))
            return
        if before.channel != after.channel and after.channel is not None:
            started = self._voice_started.get(key)
            if started is not None:
                seconds = max(0, int(time.monotonic() - started))
                if seconds >= 30:
                    await self.advance_stat(member.guild.id, member.id, "voice_seconds", seconds, points=max(1, seconds // 300))
            self._voice_started[key] = time.monotonic()

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.ensure_settings(guild.id)
            await self._active_season(guild.id)


async def _ensure_schema(bot: commands.Bot) -> None:
    for statement in SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            await bot.db.execute(sql)
    row = await bot.db.fetchone("SELECT id FROM engagement_changelog LIMIT 1")
    if not row:
        await bot.db.execute(
            "INSERT INTO engagement_changelog (version,title,body,created_at) VALUES (?,?,?,?)",
            (
                "V3",
                "Engagement V3",
                "Onboarding, profils membres, quêtes quotidiennes et hebdomadaires, saisons, suggestions, starboard, révision contextuelle, résumé IA des tickets et centre de changelog.",
                now(),
            ),
        )


async def setup(bot: commands.Bot):
    await _ensure_schema(bot)
    if bot.get_cog("EngagementSuite") is None:
        await bot.add_cog(EngagementSuite(bot))
    try:
        bot.add_view(OnboardingStartView(bot))
    except Exception:
        logger.debug("Vue onboarding persistante déjà enregistrée.", exc_info=True)
    logger.info("Engagement V3 actif pour %s.", brand_label())
