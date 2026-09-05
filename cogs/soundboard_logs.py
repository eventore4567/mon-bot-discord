"""Journalisation Soundboard isolée et intégrée au routage canonique SentriX.

Le module ne crée aucune nouvelle colonne SQL : la catégorie ``soundboard`` utilise
``log_config`` comme les autres catégories modernes. Les anciennes configurations restent
donc intactes et aucun log Soundboard n'est envoyé tant qu'un salon n'est pas choisi.

Discord ne livre ``on_voice_channel_effect`` au bot que pour un salon vocal auquel le bot
est connecté. Le log de lecture respecte cette limite et ne prétend jamais couvrir les
autres salons vocaux.
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.soundboard-logs")


def _short(value: object, limit: int = 1000) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _user_ref(user_id: int | None) -> str:
    return f"<@{int(user_id)}>" if user_id else "Inconnu"


def _channel_ref(channel_id: int | None) -> str:
    return f"<#{int(channel_id)}>" if channel_id else "Inconnu"


def _sound_name(sound: object) -> str:
    name = _short(getattr(sound, "name", ""), 100)
    return name or "Son sans nom"


def _sound_id(sound: object) -> int | None:
    try:
        return int(getattr(sound, "id", 0) or 0) or None
    except (TypeError, ValueError):
        return None


def _volume_text(sound: object) -> str | None:
    volume = getattr(sound, "volume", None)
    if volume is None:
        return None
    try:
        return f"{round(float(volume) * 100)} %"
    except (TypeError, ValueError):
        return None


def _emoji_text(sound: object) -> str:
    emoji = getattr(sound, "emoji", None)
    return str(emoji) if emoji else "Aucun"


def _base_sound_fields(sound: object) -> list[tuple[str, str, bool]]:
    sound_id = _sound_id(sound)
    fields: list[tuple[str, str, bool]] = [
        ("Son", f"`{_sound_name(sound)}`", True),
    ]
    if sound_id:
        fields.append(("ID", f"`{sound_id}`", True))
    fields.append(("Emoji", _emoji_text(sound), True))
    volume = _volume_text(sound)
    if volume is not None:
        fields.append(("Volume", volume, True))
    return fields


def _panel(title: str, fields=(), description: str = "") -> discord.Embed:
    return embeds.canonical_log_embed(title, fields=fields, description=description)


class SoundboardLogs(commands.Cog, name="SoundboardLogs"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _audit_actor(
        self,
        guild: discord.Guild,
        action_name: str,
        target_id: int | None,
        *,
        max_age_seconds: int = 12,
    ):
        """Corrèle strictement action + cible + âge ; l'absence d'Audit Log est normale."""
        if not target_id or guild.me is None or not guild.me.guild_permissions.view_audit_log:
            return None, None
        action = getattr(discord.AuditLogAction, action_name, None)
        if action is None:
            return None, None
        now = discord.utils.utcnow()
        try:
            async for entry in guild.audit_logs(limit=10, action=action):
                if getattr(entry.target, "id", None) != target_id:
                    continue
                if abs((now - entry.created_at).total_seconds()) > max_age_seconds:
                    continue
                return entry.user, entry
        except (discord.Forbidden, discord.HTTPException):
            return None, None
        return None, None

    async def _send(
        self,
        guild: discord.Guild,
        log_type: str,
        panel: discord.Embed,
        *,
        ids: list[tuple[str, int]] | None = None,
        event_key: str | None = None,
    ) -> bool:
        return await log_service.send_log(
            self.bot,
            guild,
            log_type,
            panel,
            view=log_service.log_actions(ids=ids or []),
            event_key=event_key,
        )

    @commands.Cog.listener()
    async def on_soundboard_sound_create(self, sound):
        guild = getattr(sound, "guild", None)
        sound_id = _sound_id(sound)
        if guild is None or sound_id is None:
            return

        actor, audit = await self._audit_actor(
            guild, "soundboard_sound_create", sound_id
        )
        fields = _base_sound_fields(sound)
        uploader = getattr(sound, "user", None)
        responsible = actor or uploader
        if responsible is not None and getattr(responsible, "id", None):
            fields.append(("Ajouté par", _user_ref(responsible.id), True))

        ids = [("Copier l'ID du son", sound_id)]
        if responsible is not None and getattr(responsible, "id", None):
            ids.append(("Copier l'ID du responsable", responsible.id))
        key = log_service.make_event_key(
            guild.id,
            "soundboard_create",
            target_id=sound_id,
            executor_id=getattr(responsible, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            guild,
            "soundboard_create",
            _panel("Son Soundboard ajouté", fields),
            ids=ids,
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_soundboard_sound_update(self, before, after):
        guild = getattr(after, "guild", None) or getattr(before, "guild", None)
        sound_id = _sound_id(after) or _sound_id(before)
        if guild is None or sound_id is None:
            return

        changes: list[tuple[str, str, bool]] = [
            ("Son", f"`{_sound_name(after)}`", True),
            ("ID", f"`{sound_id}`", True),
        ]
        if getattr(before, "name", None) != getattr(after, "name", None):
            changes.append(("Nom", f"`{_short(getattr(before, 'name', ''), 400)}` → `{_short(getattr(after, 'name', ''), 400)}`", False))
        if getattr(before, "emoji", None) != getattr(after, "emoji", None):
            changes.append(("Emoji", f"{_emoji_text(before)} → {_emoji_text(after)}", False))
        if getattr(before, "volume", None) != getattr(after, "volume", None):
            changes.append(("Volume", f"{_volume_text(before) or 'Inconnu'} → {_volume_text(after) or 'Inconnu'}", False))
        if len(changes) == 2:
            return

        actor, audit = await self._audit_actor(
            guild, "soundboard_sound_update", sound_id
        )
        if actor is not None and getattr(actor, "id", None):
            changes.append(("Modifié par", _user_ref(actor.id), True))

        ids = [("Copier l'ID du son", sound_id)]
        if actor is not None and getattr(actor, "id", None):
            ids.append(("Copier l'ID du responsable", actor.id))
        discriminator = "|".join(str(field[1]) for field in changes)
        key = log_service.make_event_key(
            guild.id,
            "soundboard_update",
            target_id=sound_id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
            discriminator=discriminator,
        )
        await self._send(
            guild,
            "soundboard_update",
            _panel("Son Soundboard modifié", changes),
            ids=ids,
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_soundboard_sound_delete(self, sound):
        guild = getattr(sound, "guild", None)
        sound_id = _sound_id(sound)
        if guild is None or sound_id is None:
            return

        actor, audit = await self._audit_actor(
            guild, "soundboard_sound_delete", sound_id
        )
        fields = _base_sound_fields(sound)
        if actor is not None and getattr(actor, "id", None):
            fields.append(("Supprimé par", _user_ref(actor.id), True))

        ids = [("Copier l'ID du son", sound_id)]
        if actor is not None and getattr(actor, "id", None):
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            guild.id,
            "soundboard_delete",
            target_id=sound_id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            guild,
            "soundboard_delete",
            _panel("Son Soundboard supprimé", fields),
            ids=ids,
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_voice_channel_effect(self, effect):
        """Log réel d'une lecture, uniquement là où Discord livre l'événement au bot."""
        channel = getattr(effect, "channel", None)
        guild = getattr(channel, "guild", None)
        played = getattr(effect, "sound", None)
        if guild is None or channel is None or played is None:
            return

        sound_id = _sound_id(played)
        if sound_id is None:
            return
        cached = None
        try:
            cached = guild.get_soundboard_sound(sound_id)
        except (AttributeError, TypeError):
            cached = None
        user = getattr(effect, "user", None)
        user_id = getattr(user, "id", None)
        name = _sound_name(cached) if cached is not None else f"Son {sound_id}"

        fields = [
            ("Son", f"`{name}`", True),
            ("ID", f"`{sound_id}`", True),
            ("Utilisateur", _user_ref(user_id), True),
            ("Salon vocal", _channel_ref(getattr(channel, "id", None)), True),
        ]
        volume = _volume_text(played)
        if volume is not None:
            fields.append(("Volume", volume, True))

        ids = [("Copier l'ID du son", sound_id)]
        if user_id:
            ids.append(("Copier l'ID de l'utilisateur", user_id))
        key = log_service.make_event_key(
            guild.id,
            "soundboard_play",
            target_id=sound_id,
            executor_id=user_id,
            discriminator=f"{getattr(channel, 'id', 0)}:{time.time_ns()}",
        )
        await self._send(
            guild,
            "soundboard_play",
            _panel("Son Soundboard joué", fields),
            ids=ids,
            event_key=key,
        )


def _install_setup_logs_entry(bot: commands.Bot) -> bool:
    """Ajoute l'accès au configurateur par catégorie depuis la page Logs de /setup.

    On enveloppe uniquement ``SetupView.render_page`` et on garde son rendu historique.
    Le bouton supplémentaire ouvre le même ``LogsSetupView`` que +logsetup, donc il n'y a
    qu'une seule logique de configuration et Soundboard apparaît automatiquement via le
    registre canonique.
    """
    try:
        from cogs.configuration import SETUP_STEPS, SetupView
    except ImportError:
        logger.exception("Impossible de relier Soundboard à la page Logs de /setup.")
        return False

    current = SetupView.render_page
    if getattr(current, "_sentrix_soundboard_setup_entry", False):
        return True

    def render_page_with_log_categories(view_self):
        current(view_self)
        page = getattr(view_self, "page", -1)
        if page < 0 or page >= len(SETUP_STEPS):
            return
        if SETUP_STEPS[page].get("key") != "logs":
            return

        detail_btn = discord.ui.Button(
            label="Configurer les catégories",
            style=discord.ButtonStyle.secondary,
            row=0,
        )

        async def open_categories(interaction: discord.Interaction):
            configuration = bot.get_cog("Configuration")
            if configuration is None:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Le module de configuration n'est pas chargé.")),
                    ephemere=True,
                )
            e, detail_view = await configuration._build_logs_home(view_self.guild_id)
            detail_view.author_id = interaction.user.id
            await panels.envoyer(
                interaction.response,
                panels.avec_composants(panels.depuis_embed(e), detail_view),
                ephemere=True,
            )

        detail_btn.callback = open_categories
        view_self.add_item(detail_btn)

    render_page_with_log_categories._sentrix_soundboard_setup_entry = True
    render_page_with_log_categories._sentrix_original = current
    SetupView.render_page = render_page_with_log_categories
    logger.info("Entrée des catégories de logs installée dans la page Logs de /setup.")
    return True


async def setup(bot: commands.Bot) -> None:
    _install_setup_logs_entry(bot)
    await bot.add_cog(SoundboardLogs(bot))
