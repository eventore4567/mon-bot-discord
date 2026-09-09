"""/permissions explain — Core V2, Phase 3 (docs/core-v2-plan.md, section 6 de la
demande initiale).

Enveloppe fine autour de utils/access_matrix.py::evaluate() — LA décision unique
déjà utilisée par + et /. Aucune nouvelle logique de décision ici : ce module ne
fait qu'appeler evaluate() et METTRE EN FORME son résultat (verdict, policy déjà
structurée en tags comme "discord:ban_members" ou "setup:role:allow", et raison
déjà rédigée en français) avec quelques faits de contexte lus (jamais décidés)
directement sur les objets Discord — administrateur, permission Discord requise
possédée ou non, propriétaire du serveur.

Corrige une lacune confirmée par l'audit Core V2 (docs/core-v2-audit-technical-
debt.md, §17) : aucun outil interactif n'existait pour diagnostiquer une
permission en quelques secondes — seuls des scripts CI hors-ligne. Un tel outil
aurait immédiatement révélé le bug #1 du même audit (décorateur local jamais
balayé sur /sentrixpro) au lieu qu'il faille un audit complet pour le trouver.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import access_matrix
from utils import checks
from utils import sentrix_panels as panels

# Préfixes de policy -> libellé court, pour un affichage lisible sans dupliquer
# la logique de décision elle-même (le texte détaillé reste decision.reason).
_POLICY_LABELS: dict[str, str] = {
    "owner-global": "Propriétaire global SentriX",
    "owner-global-bypass": "Propriétaire global SentriX (accès total)",
    "public": "Commande publique",
    "public-dm": "Commande publique (message privé)",
    "guild-owner": "Propriétaire du serveur",
    "guild-owner-only": "Réservée au propriétaire du serveur",
    "guild-owner:setup-recovery": "Propriétaire du serveur (accès de récupération Setup)",
    "administrator": "Rôle Administrateur Discord",
    "staff-role": "Rôle staff configuré dans Setup",
    "embed-staff": "Rôle autorisé pour l'éditeur d'embeds",
    "fail-closed": "Aucune politique explicite (Administrateur requis par défaut)",
    "invalid": "Commande introuvable",
    "guild-required": "Nécessite un serveur",
    "global-blacklist": "Liste noire globale SentriX",
}


def _policy_label(policy: str) -> str:
    if policy in _POLICY_LABELS:
        return _POLICY_LABELS[policy]
    if policy.startswith("discord:"):
        return f"Permission Discord : {access_matrix.permission_label(policy.split(':', 1)[1])}"
    if policy.startswith("setup:") and policy.endswith(":allow"):
        return "Règle Setup — autorisation explicite pour ce rôle"
    if policy.startswith("setup:") and policy.endswith(":deny"):
        return "Règle Setup — refus explicite pour ce rôle"
    if policy.startswith("module:"):
        return "Module désactivé sur ce serveur"
    if policy.startswith("categorie:"):
        return f"Catégorie « {policy.split(':', 1)[1]} » (Administrateur ou rôle Setup)"
    if policy.startswith("ai:"):
        return "Fonctionnalité IA désactivée sur ce serveur"
    return policy or "Non déterminée"


class PermissionsExplain(commands.Cog, name="PermissionsExplain"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_group(name="permissions", description="Diagnostic des permissions SentriX (Core V2).")
    async def permissions(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Permissions",
                    sous_titre="Utilisez `/permissions explain <commande> [membre]` pour diagnostiquer un accès.",
                    kind="info",
                    pied="SentriX • Core V2, Phase 3",
                ),
            )

    @permissions.command(name="explain", description="Explique pourquoi une commande est autorisée ou refusée.")
    @app_commands.describe(
        commande="Nom de la commande à diagnostiquer (ex: ban, sentrixpro security)",
        membre="Le membre à vérifier (vous-même par défaut ; réservé aux administrateurs pour un autre membre)",
    )
    async def permissions_explain(
        self, ctx: commands.Context, commande: str, membre: discord.Member | None = None,
    ) -> None:
        cible = membre or ctx.author
        if membre is not None and membre.id != ctx.author.id:
            author_perms = getattr(ctx.author, "guild_permissions", None)
            est_admin = bool(author_perms and getattr(author_perms, "administrator", False))
            if not (est_admin or await checks.is_verified_bot_owner(ctx)):
                return await panels.envoyer(
                    ctx,
                    panels.Panneau(
                        titre="SentriX — Permissions",
                        sous_titre="Diagnostiquer l'accès d'un autre membre est réservé aux administrateurs.",
                        kind="danger",
                        pied="SentriX • Core V2, Phase 3",
                    ),
                    ephemere=True,
                )

        decision = await access_matrix.evaluate(
            self.bot, command_name=commande, author=cible, guild=ctx.guild,
        )

        contexte: list[panels.Ligne] = [
            panels.Ligne("Commande", f"`{access_matrix.normalise(commande) or commande}`"),
            panels.Ligne("Membre", getattr(cible, "mention", str(cible))),
            panels.Ligne("Décision finale", "✅ ACCORDÉ" if decision.allowed else "❌ REFUSÉ"),
            panels.Ligne("Politique appliquée", _policy_label(decision.policy)),
        ]

        cible_perms = getattr(cible, "guild_permissions", None)
        if cible_perms is not None and ctx.guild is not None:
            contexte.append(
                panels.Ligne("Administrateur Discord", "oui" if getattr(cible_perms, "administrator", False) else "non")
            )
            contexte.append(
                panels.Ligne("Propriétaire du serveur", "oui" if getattr(cible, "id", None) == ctx.guild.owner_id else "non")
            )

        root = access_matrix.normalise(commande).split(" ", 1)[0] if commande else ""
        required_perm = access_matrix.DISCORD_PERMISSION_COMMANDS.get(root)
        if required_perm and cible_perms is not None:
            possede = getattr(cible_perms, required_perm, False)
            contexte.append(
                panels.Ligne(
                    "Permission Discord requise",
                    access_matrix.permission_label(required_perm),
                    indice=f"Ce membre la possède : {'oui' if possede else 'non'}",
                )
            )

        sections = [panels.Section("Résultat", contexte)]
        if decision.reason:
            sections.append(panels.Section("Explication", [], texte=decision.reason))

        panneau = panels.Panneau(
            titre="SentriX — Permissions : explain",
            sous_titre=f"Diagnostic pour `{commande}`.",
            kind="success" if decision.allowed else "danger",
            sections=sections,
            pied="SentriX • Core V2, Phase 3 — source unique : utils/access_matrix.py",
        )
        await panels.envoyer(ctx, panneau, ephemere=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PermissionsExplain(bot))
