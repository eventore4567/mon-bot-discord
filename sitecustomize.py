"""Protection de sortie logs pour SentriX sur Railway.

Python importe automatiquement ``sitecustomize`` au demarrage (sauf ``-S``). Le garde
est volontairement limite a Railway : en local et dans les tests, la configuration de
logging historique reste inchangee.

Objectifs :
- conserver toutes les erreurs importantes ;
- reduire les bibliotheques tierces tres bavardes ;
- empecher une boucle INFO/WARNING identique de depasser la limite de logs Railway ;
- ignorer uniquement les faux positifs connus d'un standby HA volontairement non connecte ;
- installer le routage dashboard leader-aware avant la construction aiohttp ;
- installer les raffinements visuels du dashboard apres les couches principales ;
- préparer la passerelle musique YouTube/Spotify/Deezer avant le chargement des Cogs.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _running_on_railway() -> bool:
    return any(name.startswith("RAILWAY_") for name in os.environ)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _truthy_env(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _expected_ha_standby_not_ready(record: logging.LogRecord, message: str) -> bool:
    """Reconnait le faux ERROR V45 attendu sur une instance standby passive.

    Le standby HA doit rester vivant sans ouvrir Discord tant que le primary detient le
    lease Redis. L'ancien audit V45, concu avant le failover, considere encore cette
    absence de on_ready apres 90 s comme une erreur. On ne masque ce message que lorsque
    le mode HA est explicitement actif ET que l'instance est explicitement standby.
    """
    if not _truthy_env("SENTRIX_FAILOVER_ENABLED"):
        return False
    if (os.getenv("SENTRIX_FAILOVER_ROLE", "") or "").strip().lower() != "standby":
        return False
    return (
        record.name == "bot.dashboard.health-runtime-v45"
        and "Discord n'est pas devenu pret en 90 secondes" in message
    )


@dataclass
class _RepeatState:
    started_at: float
    count: int = 0


class _RailwayFloodFilter(logging.Filter):
    """Laisse passer les vraies ERROR+, mais bride les floods de faible priorite."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._second_started = time.monotonic()
        self._low_priority_count = 0
        self._repeats: dict[tuple[str, int, str], _RepeatState] = {}

        self._max_low_priority_per_second = _env_int(
            "SENTRIX_LOG_MAX_PER_SECOND", 100, 20, 300
        )
        self._repeat_window = _env_int("SENTRIX_LOG_REPEAT_WINDOW", 10, 2, 60)
        self._info_repeat_limit = _env_int("SENTRIX_LOG_INFO_REPEAT_LIMIT", 6, 1, 50)
        self._warning_repeat_limit = _env_int(
            "SENTRIX_LOG_WARNING_REPEAT_LIMIT", 20, 2, 100
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        if _expected_ha_standby_not_ready(record, message):
            return False
        if record.levelno >= logging.ERROR:
            return True

        now = time.monotonic()
        key = (record.name, record.levelno, message)

        with self._lock:
            if now - self._second_started >= 1.0:
                self._second_started = now
                self._low_priority_count = 0

            state = self._repeats.get(key)
            if state is None or now - state.started_at >= self._repeat_window:
                state = _RepeatState(started_at=now)
                self._repeats[key] = state
            state.count += 1

            repeat_limit = (
                self._warning_repeat_limit
                if record.levelno >= logging.WARNING
                else self._info_repeat_limit
            )
            if state.count > repeat_limit:
                return False

            if record.levelno < logging.WARNING:
                self._low_priority_count += 1
                if self._low_priority_count > self._max_low_priority_per_second:
                    return False

            if len(self._repeats) > 5000:
                cutoff = now - self._repeat_window
                self._repeats = {
                    item_key: item_state
                    for item_key, item_state in self._repeats.items()
                    if item_state.started_at >= cutoff
                }

        return True


def _configure_railway_logging() -> None:
    if not _running_on_railway():
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)

    flood_filter = _RailwayFloodFilter()
    for handler in root.handlers:
        if not any(isinstance(current, _RailwayFloodFilter) for current in handler.filters):
            handler.addFilter(flood_filter)

    for logger_name in (
        "aiohttp.access",
        "aiosqlite",
        "asyncio",
        "discord.gateway",
        "discord.http",
        "httpcore",
        "httpx",
        "openai",
        "urllib3",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _install_railway_dashboard_ha_proxy() -> None:
    """Branche le proxy avant que railway_boot construise l'application dashboard."""
    if not _running_on_railway() or not _truthy_env("SENTRIX_FAILOVER_ENABLED"):
        return
    try:
        from web import dashboard as dashboard_web
        from web.dashboard_ha_proxy_v1 import install

        install(dashboard_web)
    except Exception:
        logging.getLogger("bot.dashboard-ha-proxy").exception(
            "Installation precoce du proxy dashboard HA impossible."
        )


def _install_railway_dashboard_focus_ui() -> None:
    """Ajoute le loader direct et replie les outils serveur dans une fenetre dediee."""
    if not _running_on_railway():
        return
    try:
        from web import dashboard as dashboard_web
        from web.dashboard_focus_loading_v1 import install

        install(dashboard_web)
    except Exception:
        logging.getLogger("bot.dashboard-focus-loading").exception(
            "Installation de l'interface dashboard focalisee impossible."
        )


def _install_sentrix_v95() -> None:
    """Prépare V95 sans rendre Python dépendant de discord.py pour les audits statiques.

    Certains jobs CI exécutent Python avant ``pip install -r requirements.txt``. Dans ce
    cas, l'absence temporaire de discord.py est normale : l'installation V95 se fera dans
    le processus runtime, où la dépendance est présente.
    """
    try:
        from sentrix_v95_bootstrap import install
    except (ImportError, ModuleNotFoundError):
        return
    try:
        install()
    except Exception:
        logging.getLogger("bot.v95-bootstrap").exception(
            "Installation précoce de SentriX V95 impossible."
        )


def _install_sentrix_verification_v96() -> None:
    """Branche l'assistant de vérification et sécurise la publication après restauration DB."""
    try:
        import discord
        from sentrix_verification_v96 import (
            VerificationConfigV96,
            VerificationSetupView,
            _clone_overwrite,
            _sensitive_surface,
            install,
        )
    except (ImportError, ModuleNotFoundError):
        return

    # Les snapshots PostgreSQL peuvent restaurer une ancienne SQLite après le pre-deploy.
    # On garantit donc la colonne au moment réel où V96 prépare une publication.
    if not getattr(VerificationConfigV96, "_sentrix_auto_access_schema_fix", False):
        original_ensure_table = VerificationConfigV96._ensure_table

        async def ensure_table_with_auto_access(self) -> None:
            await original_ensure_table(self)
            columns = await self.bot.db.fetchall("PRAGMA table_info(guild_config)")
            names = {
                str(row["name"] if hasattr(row, "keys") and "name" in row.keys() else row[1])
                for row in columns
            }
            if "verification_auto_access" not in names:
                await self.bot.db.execute(
                    "ALTER TABLE guild_config ADD COLUMN verification_auto_access INTEGER NOT NULL DEFAULT 0"
                )
                self.bot.db._guild_config_cache.clear()
                logging.getLogger("bot.verification-v96").warning(
                    "Migration runtime appliquée : guild_config.verification_auto_access ajouté."
                )

        VerificationConfigV96._ensure_table = ensure_table_with_auto_access
        VerificationConfigV96._sentrix_auto_access_schema_fix = True

    # Interface plus propre : on n'affiche pas une étape Image vide. L'accès salons devient
    # l'étape 4 lorsqu'aucune image n'est configurée, et l'étape 5 uniquement si une image existe.
    if not getattr(VerificationSetupView, "_sentrix_clean_steps_fix", False):
        def clean_configuration_embed(self):
            guild = self._guild()
            channel = guild.get_channel(self.channel_id) if guild and self.channel_id else None
            role = guild.get_role(self.role_id) if guild and self.role_id else None
            embed = discord.Embed(
                title="SentriX — Configuration de la vérification",
                description=(
                    "Configurez le panneau puis cliquez sur **Publier**.\n\n"
                    "Le membre accepte le règlement, réussit le CAPTCHA, puis reçoit le rôle choisi."
                ),
                colour=discord.Colour.blurple(),
            )
            embed.add_field(
                name="1 • Salon",
                value=channel.mention if isinstance(channel, discord.TextChannel) else "Non choisi",
                inline=False,
            )
            embed.add_field(
                name="2 • Rôle après vérification",
                value=role.mention if isinstance(role, discord.Role) else "Non choisi",
                inline=False,
            )
            embed.add_field(
                name="3 • Règlement",
                value=self.rules_text[:700] + ("…" if len(self.rules_text) > 700 else ""),
                inline=False,
            )
            access_step = 4
            if self.image_url:
                embed.add_field(name="4 • Image", value=self.image_url, inline=False)
                access_step = 5
            embed.add_field(
                name=f"{access_step} • Accès automatiques aux salons",
                value=(
                    "**ACTIVÉ** — tous les salons publics seront cachés à `@everyone` et visibles par le rôle vérifié. "
                    "Le salon de vérification restera visible. Les espaces privés et les salons staff/admin/modération/logs/audits restent intacts."
                    if self.auto_access
                    else "**DÉSACTIVÉ** — les permissions des salons ne seront pas modifiées."
                ),
                inline=False,
            )
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label and "Accès salons" in item.label:
                    item.label = f"{access_step}. Accès salons : {'OUI' if self.auto_access else 'NON'}"
            embed.set_footer(text="SentriX • Vérification • CAPTCHA activé")
            return embed

        VerificationSetupView.configuration_embed = clean_configuration_embed
        VerificationSetupView._sentrix_clean_steps_fix = True

    # Accès automatiques : chaque salon public est traité individuellement. On ne touche pas
    # aux espaces sensibles ni aux salons déjà privés, afin d'éviter d'ouvrir tickets/staff.
    if not getattr(VerificationConfigV96, "_sentrix_per_channel_access_fix", False):
        async def apply_per_channel_access(
            self,
            guild,
            *,
            verification_channel,
            verified_role,
            actor,
        ):
            everyone = guild.default_role
            operations = []
            protected_ids = set()
            seen = set()

            def plan(surface, target, *, view_channel: bool):
                key = (surface.id, target.id)
                if key in seen:
                    return
                seen.add(key)
                old = surface.overwrites_for(target)
                new = _clone_overwrite(old)
                new.view_channel = view_channel
                had_overwrite = target in surface.overwrites
                operations.append((surface, target, had_overwrite, old, new))

            for surface in guild.channels:
                if isinstance(surface, discord.CategoryChannel):
                    continue
                if surface.id == verification_channel.id:
                    plan(surface, everyone, view_channel=True)
                    plan(surface, verified_role, view_channel=True)
                    continue
                if _sensitive_surface(surface):
                    protected_ids.add(surface.id)
                    continue
                if not surface.permissions_for(everyone).view_channel:
                    protected_ids.add(surface.id)
                    continue
                plan(surface, everyone, view_channel=False)
                plan(surface, verified_role, view_channel=True)

            changed = []
            reason = f"SentriX vérification : accès salons configurés par {actor} ({actor.id})"
            try:
                for surface, target, had_overwrite, old, new in operations:
                    await surface.set_permissions(target, overwrite=new, reason=reason)
                    changed.append((surface, target, had_overwrite, old, new))
            except (discord.Forbidden, discord.HTTPException) as exc:
                rollback_reason = "SentriX vérification : rollback après échec permissions"
                for surface, target, had_overwrite, old, _new in reversed(changed):
                    try:
                        await surface.set_permissions(
                            target,
                            overwrite=old if had_overwrite else None,
                            reason=rollback_reason,
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        logging.getLogger("bot.verification-v96").exception(
                            "Rollback impossible sur salon=%s rôle=%s",
                            getattr(surface, "id", "?"),
                            getattr(target, "id", "?"),
                        )
                raise RuntimeError(f"Discord a refusé une permission sur {surface!s}") from exc

            changed_surfaces = {surface.id for surface, *_rest in changed}
            return len(changed_surfaces), len(protected_ids)

        VerificationConfigV96._apply_auto_access = apply_per_channel_access
        VerificationConfigV96._sentrix_per_channel_access_fix = True

    try:
        install()
    except Exception:
        logging.getLogger("bot.verification-v96").exception(
            "Installation précoce de la vérification V96 impossible."
        )


def _install_sentrix_music_v102() -> None:
    """Prépare le support YouTube/Spotify/Deezer avant que ``cogs.music`` soit ajouté."""
    try:
        from sentrix_music_providers_v102 import install
    except (ImportError, ModuleNotFoundError):
        return
    try:
        install()
    except Exception:
        logging.getLogger("bot.music-v102").exception(
            "Installation précoce de la passerelle musique V102 impossible."
        )


_configure_railway_logging()
_install_railway_dashboard_ha_proxy()
_install_railway_dashboard_focus_ui()
_install_sentrix_v95()
_install_sentrix_verification_v96()
_install_sentrix_music_v102()
