"""/setupdiag — Milestone 2 (Configuration Platform), priorité P1 : rendre
visible le registre central des modules (core/modules/registry.py), sans
toucher au rendu de /setup lui-même.

Pourquoi une commande séparée plutôt qu'ajouter ceci dans le panneau /setup
(cogs/setup_control_center.py::SetupView) : sa page d'accueil a déjà SA
PROPRE fonction module_statuses() (locale, indépendante), et cogs/
sentrix_ultimate.py a ENCORE une troisième liste de modules pour
+sentrixpro modules. Éditer le rendu de SetupView reviendrait à toucher la
fonction que 12 couches de monkeypatch (setup_simple_v68, setup_oxyde_v69,
setup_polish_v70, security_verification_v71, setup_ticket_autoconfig_v72,
permission_setup_hardening_v65...) composent ensemble, pour un gain
incertain (la donnée resterait un TROISIÈME calcul, pas le registre lui-même,
sans un travail de fond plus large de dédoublonnage — hors périmètre ici).
Un nouveau cog autonome (même forme que cogs/permissions_explain.py) rend le
nouveau registre visible dès maintenant, avec zéro risque sur la chaîne
existante.

Suit exactement le gabarit de cogs/permissions_explain.py : cog autonome,
propre fichier, aucune modification d'un système existant, sortie via
panels.Panneau. Le garde de permission réutilise VERBATIM
cogs.setup_control_center._can_setup — le même que /setup lui-même — pour ne
jamais diverger de qui peut déjà ouvrir la configuration du serveur.
"""
from __future__ import annotations

from discord.ext import commands

from core.modules import registry
from utils import sentrix_panels as panels

from .setup_control_center import _can_setup, _permission_error

def _module_line(status: registry.ModuleStatus, label: str) -> panels.Ligne:
    icon = "🟢" if status.configured else ("🟡" if status.enabled else "⚪")
    indice = f"{len(status.issues)} point(s) à corriger" if status.issues else None
    return panels.Ligne(f"{icon} {label}", status.summary, indice=indice)


class SetupDiagnostics(commands.Cog, name="SetupDiagnostics"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="setupdiag",
        description="État réel de chaque module SentriX sur ce serveur (registre central).",
    )
    async def setupdiag(self, ctx: commands.Context) -> None:
        if not await _can_setup(self.bot, ctx.author, ctx.guild):
            return await _permission_error(ctx)

        statuses = await registry.all_statuses(self.bot, ctx.guild.id)
        definitions = {d.key: d for d in registry.all_modules()}

        lignes = [
            _module_line(status, definitions[key].label if key in definitions else key)
            for key, status in statuses.items()
        ]
        a_corriger = sum(1 for status in statuses.values() if status.issues)

        sections = [panels.Section("Modules", lignes)]
        sous_titre = (
            f"{len(statuses) - a_corriger}/{len(statuses)} modules sans point à corriger."
            if statuses else "Aucun module enregistré."
        )

        panneau = panels.Panneau(
            titre="SentriX — État des modules",
            sous_titre=sous_titre,
            kind="warning" if a_corriger else "success",
            sections=sections,
            pied="SentriX • Registre central des modules (Core V2, Milestone 2)",
        )
        await panels.envoyer(ctx, panneau, ephemere=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupDiagnostics(bot))
