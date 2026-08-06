"""Accès direct au dashboard depuis le profil Discord et les panneaux d'aide."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands
from discord.http import Route

import config

logger = logging.getLogger("bot.dashboard-access")

_MAX_APPLICATION_DESCRIPTION = 400
_DEFAULT_PROFILE_DESCRIPTION = (
    "SentriX protège, modère et anime votre serveur Discord : sécurité, tickets, "
    "niveaux, économie, mini-jeux et configuration complète."
)


def dashboard_url() -> str:
    """Retourne toujours la page publique du dashboard, jamais la callback OAuth."""
    configured = str(getattr(config, "DASHBOARD_APP_URL", "") or "").strip()
    if configured:
        return configured

    base = str(getattr(config, "DASHBOARD_PUBLIC_URL", "") or "").strip().rstrip("/")
    for suffix in ("/oauth/callback", "/app"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
    return f"{base}/app" if base else "https://mon-bot-discord-production-8944.up.railway.app/app"


def _profile_description(current: str) -> str:
    """Conserve la description existante et remplace les anciens liens techniques."""
    url = dashboard_url()
    clean_lines: list[str] = []
    for raw_line in str(current or "").splitlines():
        line = raw_line.strip()
        lowered = line.casefold()
        if not line:
            continue
        if "/oauth/callback" in lowered:
            continue
        if "dashboard" in lowered and ("http://" in lowered or "https://" in lowered):
            continue
        clean_lines.append(line)

    base = "\n".join(clean_lines).strip() or _DEFAULT_PROFILE_DESCRIPTION
    dashboard_line = f"🌐 Dashboard SentriX : {url}"
    available = _MAX_APPLICATION_DESCRIPTION - len(dashboard_line) - 2
    base = base[: max(0, available)].rstrip()
    return f"{base}\n\n{dashboard_line}" if base else dashboard_line


def _dashboard_button(*, row: int) -> discord.ui.Button:
    return discord.ui.Button(
        label="Ouvrir le dashboard",
        emoji="🌐",
        style=discord.ButtonStyle.link,
        url=dashboard_url(),
        row=row,
    )


def _has_dashboard_button(view: discord.ui.View) -> bool:
    url = dashboard_url()
    return any(
        isinstance(item, discord.ui.Button)
        and item.style is discord.ButtonStyle.link
        and getattr(item, "url", None) == url
        for item in view.children
    )


def _patch_help_interface() -> None:
    """Ajoute le lien sans réécrire le gros module utilitaire."""
    from . import utility as utility_module

    if getattr(utility_module, "_sentrix_dashboard_access_installed", False):
        return
    utility_module._sentrix_dashboard_access_installed = True

    original_help_home = utility_module.build_help_home

    def build_help_home_with_dashboard(bot, guild, prefix, is_staff):
        embed = original_help_home(bot, guild, prefix, is_staff)
        embed.add_field(
            name="🌐 Dashboard",
            value=(
                "Configurez SentriX depuis votre navigateur sans retenir de commande : "
                f"[ouvrir le dashboard]({dashboard_url()})."
            ),
            inline=False,
        )
        return embed

    utility_module.build_help_home = build_help_home_with_dashboard

    original_help_view_init = utility_module.HelpView.__init__

    def help_view_init(self, *args, **kwargs):
        original_help_view_init(self, *args, **kwargs)
        if not _has_dashboard_button(self):
            self.add_item(_dashboard_button(row=1))

    utility_module.HelpView.__init__ = help_view_init

    original_category_view_init = utility_module.CategoryHelpView.__init__

    def category_view_init(self, *args, **kwargs):
        original_category_view_init(self, *args, **kwargs)
        if not _has_dashboard_button(self):
            self.add_item(_dashboard_button(row=2))

    utility_module.CategoryHelpView.__init__ = category_view_init


class DashboardAccess(commands.Cog, name="DashboardAccess"):
    """Synchronise le lien public avec le profil de l'application Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _sync_application_profile(self) -> None:
        attempts = int(getattr(self.bot, "_dashboard_profile_sync_attempts", 0))
        if getattr(self.bot, "_dashboard_profile_synced", False) or attempts >= 3:
            return
        self.bot._dashboard_profile_sync_attempts = attempts + 1

        try:
            application = await self.bot.application_info()
            current = str(getattr(application, "description", "") or "")
            desired = _profile_description(current)
            if current.strip() != desired.strip():
                await self.bot.http.request(
                    Route("PATCH", "/applications/@me"),
                    json={"description": desired},
                )
                logger.info("Lien du dashboard ajouté au profil Discord de SentriX.")
            else:
                logger.info("Le profil Discord contient déjà le bon lien du dashboard.")
            self.bot._dashboard_profile_synced = True
        except discord.HTTPException as exc:
            logger.warning(
                "Impossible de mettre à jour le profil Discord du bot (tentative %s/3) : %s",
                attempts + 1,
                exc,
            )
        except Exception:
            logger.exception("Erreur inattendue pendant la mise à jour du profil Discord.")

    @commands.Cog.listener()
    async def on_ready(self):
        # Laisse l'événement principal terminer son initialisation, puis modifie uniquement
        # les métadonnées de l'application. Les reconnexions ne provoquent pas de spam API.
        await asyncio.sleep(1)
        await self._sync_application_profile()


async def install_dashboard_access(bot: commands.Bot) -> None:
    """Installe les boutons et le synchroniseur après le chargement de cogs.utility."""
    _patch_help_interface()
    if bot.get_cog("DashboardAccess") is None:
        await bot.add_cog(DashboardAccess(bot))
