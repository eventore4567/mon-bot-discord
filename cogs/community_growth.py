"""Community Growth V2: candidatures staff et vocaux temporaires sans nouvelle commande publique."""
from __future__ import annotations

import json
import logging
from typing import Any

import discord
from discord.ext import commands

from database.db import now
from utils.instance_identity import brand_label

logger = logging.getLogger("bot.community-growth")

SCHEMA = """
CREATE TABLE IF NOT EXISTS community_growth_settings (
    guild_id INTEGER PRIMARY KEY,
    applications_enabled INTEGER NOT NULL DEFAULT 1,
    application_review_channel_id INTEGER,
    temp_voice_enabled INTEGER NOT NULL DEFAULT 0,
    temp_voice_lobby_id INTEGER,
    temp_voice_category_id INTEGER,
    temp_voice_user_limit INTEGER NOT NULL DEFAULT 0,
    temp_voice_name_template TEXT NOT NULL DEFAULT 'Vocal de {user}',
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS staff_application_forms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    questions_json TEXT NOT NULL DEFAULT '[]',
    accept_role_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staff_application_forms_guild ON staff_application_forms (guild_id, enabled, id DESC);
CREATE TABLE IF NOT EXISTS staff_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    form_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_id INTEGER,
    review_note TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_staff_applications_guild_status ON staff_applications (guild_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_staff_applications_user ON staff_applications (guild_id, user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS temporary_voice_channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_temporary_voice_channels_guild ON temporary_voice_channels (guild_id, owner_id);
"""


async def _ensure_schema(bot: commands.Bot) -> None:
    for statement in SCHEMA.split(";"):
        sql = statement.strip()
        if sql:
            await bot.db.execute(sql)


def _json_load(value: str | None, default: Any):
    try:
        return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default


class CommunityGrowth(commands.Cog):
    """Fonctions communautaires pilotées principalement depuis le dashboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._voice_creating: set[int] = set()

    async def ensure_settings(self, guild_id: int) -> None:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO community_growth_settings (guild_id, updated_at) VALUES (?, ?)",
            (int(guild_id), now()),
        )

    async def get_settings(self, guild_id: int) -> dict[str, Any]:
        await self.ensure_settings(guild_id)
        row = await self.bot.db.fetchone(
            "SELECT * FROM community_growth_settings WHERE guild_id=?", (int(guild_id),)
        )
        return dict(row) if row else {}

    async def update_settings(self, guild: discord.Guild, **values: Any) -> dict[str, Any]:
        allowed = {
            "applications_enabled", "application_review_channel_id", "temp_voice_enabled",
            "temp_voice_lobby_id", "temp_voice_category_id", "temp_voice_user_limit",
            "temp_voice_name_template",
        }
        clean = {k: v for k, v in values.items() if k in allowed}
        if "temp_voice_user_limit" in clean:
            clean["temp_voice_user_limit"] = max(0, min(int(clean["temp_voice_user_limit"] or 0), 99))
        if "temp_voice_name_template" in clean:
            template = str(clean["temp_voice_name_template"] or "Vocal de {user}").strip()
            clean["temp_voice_name_template"] = template[:80] or "Vocal de {user}"
        for field in ("application_review_channel_id", "temp_voice_lobby_id", "temp_voice_category_id"):
            if field in clean and clean[field] not in (None, "", 0, "0"):
                clean[field] = int(clean[field])
            elif field in clean:
                clean[field] = None
        for field in ("applications_enabled", "temp_voice_enabled"):
            if field in clean:
                clean[field] = int(bool(clean[field]))

        await self.ensure_settings(guild.id)
        if clean:
            parts = [f"{key}=?" for key in clean]
            params = list(clean.values()) + [now(), guild.id]
            await self.bot.db.execute(
                f"UPDATE community_growth_settings SET {', '.join(parts)}, updated_at=? WHERE guild_id=?",
                tuple(params),
            )
        return await self.get_settings(guild.id)

    # ------------------------------------------------------------ staff applications
    async def list_forms(self, guild_id: int, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = " AND enabled=1" if enabled_only else ""
        rows = await self.bot.db.fetchall(
            f"SELECT * FROM staff_application_forms WHERE guild_id=?{where} ORDER BY id DESC",
            (int(guild_id),),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["questions"] = _json_load(item.pop("questions_json", "[]"), [])
            result.append(item)
        return result

    async def get_form(self, guild_id: int, form_id: int, *, enabled_only: bool = False) -> dict[str, Any] | None:
        extra = " AND enabled=1" if enabled_only else ""
        row = await self.bot.db.fetchone(
            f"SELECT * FROM staff_application_forms WHERE guild_id=? AND id=?{extra}",
            (int(guild_id), int(form_id)),
        )
        if not row:
            return None
        item = dict(row)
        item["questions"] = _json_load(item.pop("questions_json", "[]"), [])
        return item

    async def save_form(self, guild: discord.Guild, actor_id: int, data: dict[str, Any]) -> int:
        title = str(data.get("title") or "Candidature staff").strip()[:100]
        description = str(data.get("description") or "").strip()[:1200]
        raw_questions = data.get("questions") if isinstance(data.get("questions"), list) else []
        questions = []
        for raw in raw_questions[:12]:
            text = str(raw.get("text") if isinstance(raw, dict) else raw).strip()[:300]
            if text:
                questions.append({"text": text, "required": bool(raw.get("required", True)) if isinstance(raw, dict) else True})
        if not questions:
            raise ValueError("Ajoutez au moins une question à la candidature.")
        role_id = data.get("accept_role_id")
        if role_id not in (None, "", 0, "0"):
            role_id = int(role_id)
            role = guild.get_role(role_id)
            if role is None or role.managed:
                raise ValueError("Le rôle attribué après acceptation est invalide.")
        else:
            role_id = None
        enabled = int(bool(data.get("enabled", True)))
        form_id = int(data.get("id") or 0)
        ts = now()
        payload = json.dumps(questions, ensure_ascii=False)
        if form_id:
            exists = await self.get_form(guild.id, form_id)
            if not exists:
                raise ValueError("Formulaire introuvable.")
            await self.bot.db.execute(
                "UPDATE staff_application_forms SET title=?,description=?,questions_json=?,accept_role_id=?,enabled=?,updated_at=? WHERE guild_id=? AND id=?",
                (title, description, payload, role_id, enabled, ts, guild.id, form_id),
            )
            return form_id
        cursor = await self.bot.db.execute(
            "INSERT INTO staff_application_forms (guild_id,title,description,questions_json,accept_role_id,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (guild.id, title, description, payload, role_id, enabled, int(actor_id), ts, ts),
        )
        return int(cursor.lastrowid)

    async def delete_form(self, guild_id: int, form_id: int) -> None:
        pending = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM staff_applications WHERE guild_id=? AND form_id=? AND status='pending'",
            (int(guild_id), int(form_id)),
        )
        if pending and int(pending["n"]):
            raise ValueError("Ce formulaire possède encore des candidatures en attente. Désactivez-le plutôt.")
        await self.bot.db.execute(
            "DELETE FROM staff_application_forms WHERE guild_id=? AND id=?", (int(guild_id), int(form_id))
        )

    async def submit_application(self, guild: discord.Guild, user_id: int, form_id: int, answers: list[Any]) -> int:
        settings = await self.get_settings(guild.id)
        if not int(settings.get("applications_enabled", 1)):
            raise ValueError("Les candidatures sont actuellement fermées.")
        form = await self.get_form(guild.id, form_id, enabled_only=True)
        if not form:
            raise ValueError("Ce formulaire n'est plus disponible.")
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except discord.HTTPException as exc:
                raise ValueError("Vous devez être membre de ce serveur.") from exc
        duplicate = await self.bot.db.fetchone(
            "SELECT id FROM staff_applications WHERE guild_id=? AND form_id=? AND user_id=? AND status='pending' LIMIT 1",
            (guild.id, form_id, int(user_id)),
        )
        if duplicate:
            raise ValueError("Vous avez déjà une candidature en attente pour ce formulaire.")
        questions = form.get("questions", [])
        clean_answers = []
        for index, question in enumerate(questions):
            answer = str(answers[index] if index < len(answers) else "").strip()[:1800]
            if question.get("required", True) and not answer:
                raise ValueError(f"Répondez à la question {index + 1}.")
            clean_answers.append({"question": question.get("text", ""), "answer": answer})
        ts = now()
        cursor = await self.bot.db.execute(
            "INSERT INTO staff_applications (guild_id,form_id,user_id,answers_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (guild.id, form_id, int(user_id), json.dumps(clean_answers, ensure_ascii=False), "pending", ts, ts),
        )
        application_id = int(cursor.lastrowid)
        review_channel = guild.get_channel(int(settings.get("application_review_channel_id") or 0))
        if isinstance(review_channel, discord.TextChannel):
            try:
                await review_channel.send(
                    f"Nouvelle candidature #{application_id} de {member.mention} pour **{form['title']}**. Consultez le dashboard pour la traiter.",
                    allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass
        return application_id

    async def list_applications(self, guild_id: int, status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [int(guild_id)]
        sql = (
            "SELECT a.*,f.title AS form_title,f.accept_role_id FROM staff_applications a "
            "JOIN staff_application_forms f ON f.id=a.form_id AND f.guild_id=a.guild_id WHERE a.guild_id=?"
        )
        if status and status != "all":
            sql += " AND a.status=?"
            params.append(str(status).casefold())
        sql += " ORDER BY a.created_at DESC LIMIT 250"
        rows = await self.bot.db.fetchall(sql, tuple(params))
        result = []
        for row in rows:
            item = dict(row)
            item["answers"] = _json_load(item.pop("answers_json", "[]"), [])
            result.append(item)
        return result

    async def review_application(self, guild: discord.Guild, application_id: int, reviewer_id: int, decision: str, note: str = "") -> dict[str, Any]:
        decision = str(decision).casefold()
        if decision not in {"accepted", "refused", "more_info"}:
            raise ValueError("Décision invalide.")
        row = await self.bot.db.fetchone(
            "SELECT a.*,f.title AS form_title,f.accept_role_id FROM staff_applications a JOIN staff_application_forms f ON f.id=a.form_id WHERE a.guild_id=? AND a.id=?",
            (guild.id, int(application_id)),
        )
        if not row:
            raise ValueError("Candidature introuvable.")
        ts = now()
        await self.bot.db.execute(
            "UPDATE staff_applications SET status=?,reviewer_id=?,review_note=?,updated_at=? WHERE guild_id=? AND id=?",
            (decision, int(reviewer_id), str(note or "")[:1800], ts, guild.id, int(application_id)),
        )
        member = guild.get_member(int(row["user_id"]))
        if decision == "accepted" and member and row["accept_role_id"]:
            role = guild.get_role(int(row["accept_role_id"]))
            if role and not role.managed and guild.me and role < guild.me.top_role:
                try:
                    await member.add_roles(role, reason=f"Candidature #{application_id} acceptée")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        user = member or self.bot.get_user(int(row["user_id"]))
        if user is not None:
            labels = {"accepted": "acceptée", "refused": "refusée", "more_info": "informations supplémentaires demandées"}
            message = f"Votre candidature **{row['form_title']}** sur **{guild.name}** a été {labels[decision]}."
            if note:
                message += f"\n\nNote du staff : {str(note)[:1500]}"
            try:
                await user.send(message)
            except (discord.Forbidden, discord.HTTPException):
                pass
        result = await self.bot.db.fetchone("SELECT * FROM staff_applications WHERE guild_id=? AND id=?", (guild.id, int(application_id)))
        return dict(result) if result else {}

    # ------------------------------------------------------------ temporary voice
    async def _tracked_voice(self, channel_id: int) -> dict[str, Any] | None:
        row = await self.bot.db.fetchone("SELECT * FROM temporary_voice_channels WHERE channel_id=?", (int(channel_id),))
        return dict(row) if row else None

    async def _cleanup_voice(self, channel: discord.VoiceChannel | discord.StageChannel | None) -> None:
        if not isinstance(channel, discord.VoiceChannel):
            return
        tracked = await self._tracked_voice(channel.id)
        if not tracked or channel.members:
            return
        try:
            await channel.delete(reason=f"{brand_label()} vocal temporaire vide")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await self.bot.db.execute("DELETE FROM temporary_voice_channels WHERE channel_id=?", (channel.id,))

    async def _create_temp_voice(self, member: discord.Member, lobby: discord.VoiceChannel, settings: dict[str, Any]) -> None:
        if member.id in self._voice_creating:
            return
        self._voice_creating.add(member.id)
        try:
            existing = await self.bot.db.fetchone(
                "SELECT channel_id FROM temporary_voice_channels WHERE guild_id=? AND owner_id=? ORDER BY created_at DESC LIMIT 1",
                (member.guild.id, member.id),
            )
            if existing:
                channel = member.guild.get_channel(int(existing["channel_id"]))
                if isinstance(channel, discord.VoiceChannel):
                    try:
                        await member.move_to(channel, reason="Retour dans son vocal temporaire")
                        return
                    except (discord.Forbidden, discord.HTTPException):
                        pass
            category_id = int(settings.get("temp_voice_category_id") or 0)
            category = member.guild.get_channel(category_id) if category_id else lobby.category
            if category is not None and not isinstance(category, discord.CategoryChannel):
                category = lobby.category
            template = str(settings.get("temp_voice_name_template") or "Vocal de {user}")
            safe_name = template.replace("{user}", member.display_name).replace("{username}", member.name)[:90]
            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
                member: discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=True, manage_channels=True,
                    move_members=True, mute_members=True, deafen_members=True,
                ),
            }
            channel = await member.guild.create_voice_channel(
                safe_name or f"Vocal de {member.display_name}",
                category=category,
                overwrites=overwrites,
                user_limit=max(0, min(int(settings.get("temp_voice_user_limit") or 0), 99)),
                reason=f"{brand_label()} vocal temporaire",
            )
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO temporary_voice_channels (channel_id,guild_id,owner_id,created_at) VALUES (?,?,?,?)",
                (channel.id, member.guild.id, member.id, now()),
            )
            try:
                await member.move_to(channel, reason="Création du vocal temporaire")
            except (discord.Forbidden, discord.HTTPException):
                await self._cleanup_voice(channel)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible de créer le vocal temporaire sur %s", member.guild.id)
        finally:
            self._voice_creating.discard(member.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        try:
            if before.channel and before.channel != after.channel:
                await self._cleanup_voice(before.channel)
            if member.bot or not isinstance(after.channel, discord.VoiceChannel):
                return
            settings = await self.get_settings(member.guild.id)
            if not int(settings.get("temp_voice_enabled", 0)):
                return
            lobby_id = int(settings.get("temp_voice_lobby_id") or 0)
            if lobby_id and after.channel.id == lobby_id:
                await self._create_temp_voice(member, after.channel, settings)
        except Exception:
            logger.exception("Erreur runtime vocal temporaire sur %s", member.guild.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if isinstance(channel, discord.VoiceChannel):
            await self.bot.db.execute("DELETE FROM temporary_voice_channels WHERE channel_id=?", (channel.id,))

    @commands.Cog.listener()
    async def on_ready(self):
        rows = await self.bot.db.fetchall("SELECT channel_id,guild_id FROM temporary_voice_channels")
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None or guild.get_channel(int(row["channel_id"])) is None:
                await self.bot.db.execute("DELETE FROM temporary_voice_channels WHERE channel_id=?", (int(row["channel_id"]),))


async def setup(bot: commands.Bot):
    await _ensure_schema(bot)
    if bot.get_cog("CommunityGrowth") is None:
        await bot.add_cog(CommunityGrowth(bot))
    logger.info("Community Growth V2 actif : candidatures staff et vocaux temporaires.")
