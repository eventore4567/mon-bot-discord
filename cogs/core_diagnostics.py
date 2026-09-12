"""/corediag — Core V2, Phase 1 (docs/core-v2-plan.md, section 9 de la demande).

Nommée volontairement différemment de +diagnostic/+diag : ce nom-là est déjà
disputé par au moins trois modules qui réécrivent son callback (voir
docs/core-v2-audit-technical-debt.md §7 et cogs/final_stability_guard.py /
cogs/v17_health.py) — y ajouter une quatrième couche aurait été exactement le
problème que Core V2 cherche à faire disparaître, pas une solution. /corediag
est un panneau neuf, propriétaire de Core V2 uniquement, qui ne touche à rien
d'existant. Une fois les données qu'il affiche jugées fiables, il pourra
remplacer +diagnostic (Phase 6) — pas avant.

Lecture seule, réservé au propriétaire global : les métriques exposées ici sont
globales au processus (pas de scope par serveur), donc pas adaptées à un accès
administrateur-par-serveur pour l'instant — voir la section 9 de la demande
initiale, qui prévoyait déjà cette distinction.
"""
from __future__ import annotations

import sys
import time

import discord
from discord.ext import commands

from utils import checks
from utils import sentrix_panels as panels
from core.observability import metrics

_LOADED_AT = time.time()


def _format_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}min"
    if minutes:
        return f"{minutes}min {secs}s"
    return f"{secs}s"


class CoreDiagnostics(commands.Cog, name="CoreDiagnostics"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="corediag",
        description="Diagnostic technique SentriX (Core V2) — réservé au propriétaire global.",
    )
    @checks.is_bot_owner()
    async def corediag(self, ctx: commands.Context) -> None:
        bot_section = [
            panels.Ligne("Python", sys.version.split()[0]),
            panels.Ligne("discord.py", discord.__version__),
            panels.Ligne("Actif depuis", _format_uptime(time.time() - _LOADED_AT)),
        ]

        discord_section = [
            panels.Ligne("Connecté", "Oui" if self.bot.is_ready() and not self.bot.is_closed() else "Non"),
            panels.Ligne("Latence gateway", f"{round(self.bot.latency * 1000)} ms"),
            panels.Ligne("Serveurs", str(len(self.bot.guilds))),
        ]

        commandes = list(self.bot.walk_commands())
        try:
            racines_slash = len(self.bot.tree.get_commands())
        except Exception:
            racines_slash = 0
        commandes_section = [
            panels.Ligne("Texte/hybrides chargées", str(len(commandes))),
            panels.Ligne("Racines slash", str(racines_slash)),
        ]

        snapshot = metrics.snapshot()
        sections = [
            panels.Section("SentriX", bot_section),
            panels.Section("Discord", discord_section),
            panels.Section("Commandes", commandes_section),
        ]

        if snapshot:
            top = sorted(snapshot.values(), key=lambda s: s.count, reverse=True)[:10]
            lignes = [
                panels.Ligne(
                    stats.command,
                    f"{stats.success_rate * 100:.1f}% réussite",
                    indice=(
                        f"P50 {stats.p50_ms:.0f}ms · P95 {stats.p95_ms:.0f}ms · "
                        f"P99 {stats.p99_ms:.0f}ms · échecs récents : {stats.recent_failures}"
                    ),
                )
                for stats in top
            ]
            restantes = max(0, len(snapshot) - len(top))
            titre = "Observabilité (top 10 par volume)" if restantes else "Observabilité"
            if restantes:
                lignes.append(panels.Ligne("Autres commandes suivies", str(restantes)))
            sections.append(panels.Section(titre, lignes))
        else:
            sections.append(
                panels.Section(
                    "Observabilité",
                    [],
                    texte="Aucune commande observée depuis le dernier redémarrage.",
                )
            )

        panneau = panels.Panneau(
            titre="SentriX — Diagnostic Core V2",
            sous_titre="Lecture seule. Métriques depuis le dernier redémarrage du processus.",
            kind="info",
            sections=sections,
            pied="SentriX • Core V2, Phase 1",
        )
        await panels.envoyer(ctx, panneau, ephemere=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoreDiagnostics(bot))
