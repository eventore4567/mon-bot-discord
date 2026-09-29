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

    @commands.hybrid_group(name="permissions", description="Comprendre qui peut utiliser une commande, et pourquoi.")
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

    @permissions.command(
        name="liste",
        aliases=["audit", "list"],
        description="Lister qui peut lancer quoi : chaque commande et la permission qu'elle exige.",
    )
    @app_commands.describe(
        filtre="Ne garder que les commandes dont le nom contient ce texte (facultatif)",
    )
    async def permissions_liste(self, ctx: commands.Context, *, filtre: str = "") -> None:
        """La vue d'ensemble qui manquait.

        Deux surfaces existaient déjà, et aucune ne répondait à la question
        « qui peut lancer quoi ? » :

        * ``+permissions explain <commande>`` diagnostique UNE commande pour UN
          membre — parfait pour comprendre un refus précis, inutile pour relire
          la politique du bot ;
        * ``+security permissions`` (alias ``permission-audit``) audite les
          permissions Discord dangereuses des RÔLES du serveur — qui possède
          Administrateur — ce qui est une autre question.

        Celle-ci liste la surface entière, groupée par niveau d'accès, telle que
        ``utils/access_matrix`` la décide. Aucune logique de décision ici : les
        libellés viennent de ``access_tier()`` et ``help_requirement()``, les
        mêmes que ``+help``. Une divergence entre cette vue et un refus réel
        serait donc un défaut de la matrice, pas de l'affichage — et c'est
        précisément ce qu'on veut pouvoir constater.

        Réservée aux administrateurs : la liste complète révèle la surface
        d'administration du serveur, y compris des commandes qu'un membre ne
        voit jamais dans ``+help``.
        """
        author_perms = getattr(ctx.author, "guild_permissions", None)
        est_admin = bool(author_perms and getattr(author_perms, "administrator", False))
        est_proprietaire = bool(
            ctx.guild is not None and getattr(ctx.author, "id", None) == ctx.guild.owner_id
        )
        if not (est_admin or est_proprietaire or await checks.is_verified_bot_owner(ctx)):
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Permissions",
                    sous_titre=(
                        "La liste complète est réservée aux administrateurs. "
                        "Utilisez `+permissions explain <commande>` pour votre propre accès."
                    ),
                    kind="danger",
                    pied="SentriX • Audit des permissions",
                ),
                ephemere=True,
            )

        # Les racines réellement chargées, pas une liste écrite à la main : une
        # liste figée mentirait dès la première commande ajoutée, et c'est
        # exactement le genre d'écart qu'un audit doit rendre visible.
        recherche = access_matrix.normalise(filtre)
        racines = sorted({
            commande.qualified_name
            for commande in self.bot.walk_commands()
            if not getattr(commande, "hidden", False)
        })
        if recherche:
            racines = [nom for nom in racines if recherche in access_matrix.normalise(nom)]

        if not racines:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Permissions : liste",
                    sous_titre=f"Aucune commande ne correspond à « {filtre} ».",
                    kind="warning",
                    pied="SentriX • Audit des permissions",
                ),
                ephemere=True,
            )

        # Regroupé par exigence, pas par ordre alphabétique : la question est
        # « qui peut lancer quoi », donc c'est l'exigence qui doit organiser la
        # lecture.
        par_exigence: dict[str, list[str]] = {}
        for nom in racines:
            par_exigence.setdefault(access_matrix.help_requirement(nom), []).append(nom)

        # Du plus ouvert au plus fermé : on lit d'abord ce que tout le monde
        # peut faire, on finit par ce que personne ne peut faire sans être
        # propriétaire. Une exigence inconnue se place avant le propriétaire
        # plutôt qu'en tête, pour ne pas passer pour une commande publique.
        ORDRE = (
            "Tout le monde",
            "Gérer les messages / Gérer le serveur / rôle +embed",
            "Administrateur (ou rôle autorisé dans Setup)",
            "Administrateur (commande non classée)",
            "Propriétaire du serveur uniquement",
            "Propriétaire global SentriX",
        )

        def rang(exigence: str) -> tuple[int, str]:
            if exigence in ORDRE:
                return ORDRE.index(exigence), exigence
            # Les permissions Discord nommées (« Bannir des membres (ou rôle
            # autorisé dans Setup) ») se rangent entre le public et l'admin.
            return 1, exigence

        sections: list[panels.Section] = []
        for exigence in sorted(par_exigence, key=rang):
            noms = sorted(par_exigence[exigence])
            # Tronqué, et ON LE DIT. Une liste coupée en silence se lit comme
            # une liste complète, et l'audit deviendrait trompeur.
            affiches = noms[:40]
            texte = " ".join(f"`{n}`" for n in affiches)
            if len(noms) > len(affiches):
                texte += f" … **+{len(noms) - len(affiches)} autres**"
            sections.append(
                panels.Section(
                    f"{exigence} — {len(noms)}",
                    [],
                    texte=texte,
                )
            )

        non_classees = len(par_exigence.get("Administrateur (commande non classée)", ()))
        sous_titre = f"{len(racines)} commande(s)"
        if recherche:
            sous_titre += f" correspondant à « {filtre} »"
        if non_classees:
            # Une non classée n'est pas refusée à tout le monde : le
            # propriétaire du serveur et les administrateurs passent (étapes 7
            # et 8 de la matrice, avant le refus final). Elle est refusée à tout
            # le reste, y compris à un modérateur portant la permission Discord
            # qui devrait suffire — c'est ça qu'il faut corriger.
            sous_titre += (
                f" · ⚠️ {non_classees} non classée(s) : accessibles seulement "
                "aux administrateurs, même à un modérateur qui devrait y avoir droit"
            )

        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Permissions : qui peut lancer quoi",
                sous_titre=sous_titre,
                kind="info",
                sections=sections,
                pied="SentriX • Source unique : utils/access_matrix.py (la même que +help et le garde)",
            ),
            ephemere=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PermissionsExplain(bot))
