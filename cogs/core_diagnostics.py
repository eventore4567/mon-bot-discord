"""+health / corediag — diagnostic compact de SentriX, réservé au propriétaire global.

Lecture seule, métriques globales au processus (jamais scopées par serveur). Cinq
blocs : BOT, SYSTÈME, DISCORD, TÂCHES DE FOND, ÉTAT. Le but est de savoir en dix
secondes si SentriX va bien, pas de remplacer un système de supervision.
"""
from __future__ import annotations

import asyncio
import sys
import time

import discord
from discord.ext import commands, tasks

from utils import checks
from utils import sentrix_panels as panels
from core.observability import metrics

_LOADED_AT = time.time()


def _format_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}j {hours}h {minutes}min"
    if hours:
        return f"{hours}h {minutes}min"
    if minutes:
        return f"{minutes}min {secs}s"
    return f"{secs}s"


async def _database_ping_ms(bot: commands.Bot) -> float | None:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(bot.db.fetchone("SELECT 1 AS ok"), timeout=3.0)
    except Exception:
        return None
    return (time.perf_counter() - started) * 1000


def _cache_sizes() -> dict[str, int]:
    sizes: dict[str, int] = {}
    try:
        from cogs import setup_v2_core

        sizes["modules"] = len(setup_v2_core._MODULE_ROW_CACHE)
    except Exception:
        pass
    return sizes


def _cog_loops(bot: commands.Bot) -> tuple[int, list[str]]:
    """(boucles actives, boucles déclarées mais arrêtées) sur les cogs chargés."""
    running = 0
    stopped: list[str] = []
    for cog in bot.cogs.values():
        for attr in dir(cog):
            if attr.startswith("__"):
                continue
            try:
                value = getattr(cog, attr)
            except Exception:
                continue
            if isinstance(value, tasks.Loop):
                if value.is_running():
                    running += 1
                else:
                    stopped.append(f"{type(cog).__name__}.{attr}")
    return running, stopped


class CoreDiagnostics(commands.Cog, name="CoreDiagnostics"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="health",
        aliases=["corediag", "sante", "santé"],
        description="État technique compact de SentriX — réservé au propriétaire global.",
    )
    @checks.is_bot_owner()
    async def health(self, ctx: commands.Context) -> None:
        problems: list[str] = []

        # BOT
        latency_ms = round(self.bot.latency * 1000) if self.bot.latency == self.bot.latency else None
        if latency_ms is None or latency_ms > 1000:
            problems.append("latence gateway élevée" if latency_ms else "latence gateway inconnue")
        bot_section = [
            panels.Ligne("Latence", f"{latency_ms} ms" if latency_ms is not None else "inconnue"),
            panels.Ligne("Actif depuis", _format_uptime(time.time() - _LOADED_AT)),
            panels.Ligne("Runtime", f"Python {sys.version.split()[0]} · discord.py {discord.__version__}"),
        ]

        # SYSTÈME
        db_ms = await _database_ping_ms(self.bot)
        if db_ms is None:
            problems.append("base de données injoignable")
        elif db_ms > 250:
            problems.append(f"base de données lente ({db_ms:.0f} ms)")
        caches = _cache_sizes()
        system_section = [
            panels.Ligne("Base de données", f"{db_ms:.1f} ms" if db_ms is not None else "ERREUR"),
            panels.Ligne("Cache modules", f"{caches.get('modules', 0)} entrée(s)"),
        ]

        # DISCORD
        # « attendues » = la liste main.EXTENSIONS ; le total chargé peut être plus grand
        # (extensions ajoutées par les couches runtime, ex. cogs.help). On n'affiche donc
        # jamais « 52 / 50 » : on compte ce qui MANQUE dans la liste attendue.
        loaded = len(self.bot.extensions)
        try:
            import main as _main
            attendues = list(getattr(_main, "EXTENSIONS", []))
        except Exception:
            attendues = []
        manquantes = [name for name in attendues if name not in self.bot.extensions]
        if manquantes:
            problems.append(f"{len(manquantes)} extension(s) non chargée(s) : {', '.join(manquantes[:3])}")
        ready = self.bot.is_ready() and not self.bot.is_closed()
        if not ready:
            problems.append("gateway non prête")
        try:
            slash_roots = len(self.bot.tree.get_commands())
        except Exception:
            slash_roots = 0
        discord_section = [
            panels.Ligne("Connecté", "Oui" if ready else "Non"),
            panels.Ligne("Serveurs", str(len(self.bot.guilds))),
            panels.Ligne("Extensions", f"{loaded} chargées" + (f" · {len(manquantes)} manquante(s)" if manquantes else "")),
            panels.Ligne("Commandes", f"{len(list(self.bot.walk_commands()))} texte · {slash_roots} racines slash"),
        ]

        # TÂCHES DE FOND
        loops_running, loops_stopped = _cog_loops(self.bot)
        all_tasks = [t for t in asyncio.all_tasks() if not t.done()]
        if loops_stopped:
            problems.append(f"{len(loops_stopped)} boucle(s) de cog arrêtée(s)")
        snapshot = metrics.snapshot()
        recent_failures = sum(int(getattr(s, "recent_failures", 0) or 0) for s in snapshot.values())
        background_section = [
            panels.Ligne("Tâches asyncio actives", str(len(all_tasks))),
            panels.Ligne("Boucles de cogs", f"{loops_running} active(s) · {len(loops_stopped)} arrêtée(s)"),
            panels.Ligne("Échecs de commandes récents", str(recent_failures)),
        ]
        if loops_stopped:
            background_section.append(panels.Ligne("Arrêtées", ", ".join(loops_stopped[:6])))

        # ÉTAT
        degraded = bool(problems)
        status_section = [
            panels.Ligne("État", "DÉGRADÉ" if degraded else "SAIN"),
        ]
        if problems:
            status_section.append(panels.Ligne("Raisons", " · ".join(problems[:5])))

        panneau = panels.Panneau(
            titre="SentriX — État technique",
            sous_titre="Lecture seule, métriques du processus courant.",
            kind="warning" if degraded else "success",
            sections=[
                panels.Section("Bot", bot_section, aligne=True),
                panels.Section("Système", system_section, aligne=True),
                panels.Section("Discord", discord_section, aligne=True),
                panels.Section("Tâches de fond", background_section, aligne=True),
                panels.Section("État", status_section, aligne=True),
            ],
            pied="SentriX • Diagnostic propriétaire",
        )
        await panels.envoyer(ctx, panneau, ephemere=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoreDiagnostics(bot))
