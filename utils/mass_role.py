"""Moteur unique des rôles en masse : +massrole add/del et /role mass.

Avant le 02/11/2026, deux moteurs coexistaient : +massrole (cogs/server_choice_roles)
n'affichait une progression que tous les 2000 membres, et /role mass
(cogs/role_mass_target) n'affichait rien avant le MP final. Les deux passent
maintenant ici et montrent la même progression : traités / total, restants,
pourcentage, barre, vitesse moyenne, temps écoulé, temps restant estimé et heure
de fin estimée (horodatage Discord : chacun la lit dans son fuseau).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import discord

from utils import sentrix_panels as panels
from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.mass-role")

#: Rafraîchissement du panneau : assez souvent pour suivre, assez peu pour ne pas
#: consommer la limite d'édition de Discord pendant que les rôles sont posés.
INTERVALLE_RAFRAICHISSEMENT = 3.0
#: Membres traités en parallèle. discord.py respecte de toute façon la limite
#: Discord de la route des rôles ; au-delà, on ne va pas plus vite.
TAILLE_LOT = 5
LARGEUR_BARRE = 16

CIBLES = {"members", "bots", "all"}


def _duree(secondes: float, english: bool = False) -> str:
    secondes = max(0, int(round(secondes)))
    heures, reste = divmod(secondes, 3600)
    minutes, sec = divmod(reste, 60)
    if heures:
        return f"{heures} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {sec:02d} s"
    return f"{sec} s"


def _nombre(valeur: float | int) -> str:
    return f"{int(valeur):,}".replace(",", " ")


@dataclass
class Progression:
    action: str  # « add » ou « remove »
    role_mention: str
    cible: str = "members"
    total: int = 0
    traites: int = 0
    modifies: int = 0
    ignores: int = 0
    echecs: int = 0
    proteges: int = 0
    english: bool = False
    liste_partielle: bool = False
    #: Faux tant que la liste des membres n'est pas récupérée (total inconnu).
    pret: bool = False
    termine: bool = False
    interrompu: str | None = None
    debut: float = field(default_factory=time.monotonic)
    debut_horloge: float = field(default_factory=time.time)
    fin: float | None = None

    # ------------------------------------------------------------ mesures
    @property
    def ecoule(self) -> float:
        return max(0.0, (self.fin or time.monotonic()) - self.debut)

    @property
    def restants(self) -> int:
        return max(0, self.total - self.traites)

    @property
    def pourcentage(self) -> int:
        if self.total <= 0:
            return 100 if self.termine else 0
        return min(100, int(self.traites * 100 / self.total))

    @property
    def vitesse(self) -> float:
        """Membres traités par seconde, en moyenne depuis le début."""
        ecoule = self.ecoule
        return self.traites / ecoule if ecoule > 0 else 0.0

    @property
    def eta(self) -> float | None:
        """Secondes restantes estimées, ou None tant qu'aucune mesure n'est fiable."""
        if self.termine or self.restants == 0:
            return 0.0
        vitesse = self.vitesse
        return self.restants / vitesse if vitesse > 0 else None

    def barre(self, largeur: int = LARGEUR_BARRE) -> str:
        pleins = round(largeur * self.pourcentage / 100)
        return "█" * pleins + "░" * (largeur - pleins)

    # ------------------------------------------------------------ rendu
    def panneau(self) -> panels.Panneau:
        en = self.english
        verbe = ("Adding" if self.action == "add" else "Removing") if en else (
            "Ajout de" if self.action == "add" else "Retrait de"
        )
        cible = {
            "members": ("human members", "membres humains"),
            "bots": ("bots", "bots"),
            "all": ("everyone", "tous les membres"),
        }[self.cible][0 if en else 1]
        if self.interrompu:
            etat, kind = ("stopped", "danger") if en else ("interrompu", "danger")
        elif self.termine:
            etat, kind = ("done", "success") if en else ("terminé", "success")
        else:
            etat, kind = ("in progress", "moderation") if en else ("en cours", "moderation")

        if not self.pret and not self.termine and not self.interrompu:
            return panels.Panneau(
                titre=("Bulk roles · " if en else "Rôles en masse · ") + etat,
                sous_titre=f"{verbe} {self.role_mention} · {cible}",
                kind=kind,
                banniere=True,
                sections=[panels.Section(
                    "Preparing" if en else "Préparation",
                    texte=("Fetching the member list from Discord…" if en
                           else "Récupération de la liste des membres auprès de Discord…"),
                )],
            )

        avancement = [
            panels.Ligne("Processed" if en else "Traités", f"{_nombre(self.traites)} / {_nombre(self.total)}"),
            panels.Ligne("Remaining" if en else "Restants", _nombre(self.restants)),
            panels.Ligne(
                "Result" if en else "Résultat",
                (f"{_nombre(self.modifies)} changed · {_nombre(self.ignores)} skipped · {_nombre(self.echecs)} failed"
                 if en else
                 f"{_nombre(self.modifies)} modifiés · {_nombre(self.ignores)} ignorés · {_nombre(self.echecs)} échecs"),
            ),
        ]
        if self.proteges:
            avancement.append(panels.Ligne(
                "Protected" if en else "Protégés",
                _nombre(self.proteges),
                indice=("SentriX owner accounts are never deranked." if en
                        else "Les comptes propriétaires de SentriX ne sont jamais retirés."),
            ))

        vitesse = self.vitesse
        temps = [
            panels.Ligne("Elapsed" if en else "Temps écoulé", _duree(self.ecoule, en)),
            panels.Ligne(
                "Average speed" if en else "Vitesse moyenne",
                (f"{vitesse:.1f} members/s" if en else f"{vitesse:.1f} membres/s".replace(".", ","))
                if vitesse else "—",
            ),
        ]
        if not self.termine and not self.interrompu:
            eta = self.eta
            if eta is None:
                temps.append(panels.Ligne("Time left" if en else "Temps restant", "estimating…" if en else "estimation…"))
            else:
                fin = int(time.time() + eta)
                temps.append(panels.Ligne("Time left" if en else "Temps restant estimé", _duree(eta, en)))
                temps.append(panels.Ligne(
                    "Estimated end" if en else "Fin estimée", f"<t:{fin}:T> (<t:{fin}:R>)",
                ))
        else:
            temps[0] = panels.Ligne("Total time" if en else "Durée totale", _duree(self.ecoule, en))

        sections = [
            panels.Section(
                "Progress" if en else "Progression",
                texte=f"`{self.barre()}` **{self.pourcentage} %**",
                lignes=avancement,
            ),
            panels.Section("Time" if en else "Temps", lignes=temps),
        ]
        if self.liste_partielle:
            sections.append(panels.Section(
                "Note",
                texte=("Discord did not return the full member list: only cached members were processed."
                       if en else
                       "Discord n'a pas fourni la liste complète : seuls les membres en cache ont été traités."),
            ))
        if self.interrompu:
            sections.append(panels.Section("Error" if en else "Erreur", texte=self.interrompu))

        return panels.Panneau(
            titre=("Bulk roles · " if en else "Rôles en masse · ") + etat,
            sous_titre=f"{verbe} {self.role_mention} · {cible}",
            kind=kind,
            banniere=True,
            sections=sections,
        )


def concerne(membre: Any, cible: str) -> bool:
    est_bot = bool(getattr(membre, "bot", False))
    if cible == "members":
        return not est_bot
    if cible == "bots":
        return est_bot
    return True


async def membres_du_serveur(guild: Any) -> tuple[list[Any], bool]:
    """Liste complète via l'API, sinon le cache (signalé comme partiel)."""
    try:
        return [m async for m in guild.fetch_members(limit=None)], False
    except (discord.Forbidden, discord.HTTPException):
        return list(getattr(guild, "members", ()) or ()), True


async def executer(
    guild: Any,
    role: Any,
    *,
    action: str,
    cible: str,
    raison: str,
    progression: Progression,
    rafraichir: Callable[[Progression], Awaitable[Any]] | None = None,
    intervalle: float = INTERVALLE_RAFRAICHISSEMENT,
    lot: int = TAILLE_LOT,
) -> Progression:
    """Applique le rôle et tient `progression` à jour ; `rafraichir` affiche l'état."""
    async def afficher(force: bool = False) -> None:
        nonlocal dernier
        if rafraichir is None:
            return
        maintenant = time.monotonic()
        if not force and maintenant - dernier < intervalle:
            return
        dernier = maintenant
        try:
            await rafraichir(progression)
        except Exception:  # un affichage raté ne doit jamais arrêter l'opération
            logger.debug("Progression des rôles en masse non affichée.", exc_info=True)

    async def appliquer(membre: Any) -> None:
        a_le_role = role in getattr(membre, "roles", ())
        if (action == "add" and a_le_role) or (action == "remove" and not a_le_role):
            progression.ignores += 1
            return
        if action == "remove" and is_bot_owner_id(getattr(membre, "id", 0)):
            progression.proteges += 1
            return
        try:
            if action == "add":
                await membre.add_roles(role, reason=raison)
            else:
                await membre.remove_roles(role, reason=raison)
            progression.modifies += 1
        except (discord.Forbidden, discord.HTTPException):
            progression.echecs += 1

    dernier = 0.0
    membres, partielle = await membres_du_serveur(guild)
    cibles = [m for m in membres if concerne(m, cible)]
    progression.total = len(cibles)
    progression.liste_partielle = partielle
    progression.pret = True
    progression.debut = time.monotonic()
    await afficher(force=True)
    try:
        for index in range(0, len(cibles), max(1, lot)):
            paquet = cibles[index:index + max(1, lot)]
            await asyncio.gather(*(appliquer(m) for m in paquet))
            progression.traites += len(paquet)
            await afficher()
    except Exception as exc:
        logger.exception("Rôles en masse interrompus guild=%s", getattr(guild, "id", None))
        progression.interrompu = (
            "The operation stopped unexpectedly." if progression.english
            else "L'opération s'est arrêtée de façon inattendue."
        )
        progression.fin = time.monotonic()
        await afficher(force=True)
        raise exc
    progression.termine = True
    progression.fin = time.monotonic()
    await afficher(force=True)
    return progression


__all__ = ["CIBLES", "Progression", "concerne", "executer", "membres_du_serveur"]
