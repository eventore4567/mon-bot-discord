"""Progression de l'économie SentriX (07/11/2026 : « le système d'économie est nul »).

Avant : un +daily fixe à 200, un +work au hasard entre 50 et 250 avec un métier tiré
au sort, et rien qui donne envie de revenir. Désormais :

- **métiers avec promotions** : chaque +work compte ; Stagiaire → Employé → Technicien
  → Manager → Directeur → PDG, avec un salaire qui monte à chaque palier ;
- **événements au travail** : pourboire, prime de performance, ou journée ratée ;
- **série quotidienne et intérêts** : le +daily affiche la série (bonus qui grimpe) et
  verse 1 % d'intérêts sur la banque (plafonnés), dans le MÊME panneau ;
- la fiche +balance montre le métier, la série et quand revenir.

Aucune nouvelle table : le nombre de travaux vient de economy_transactions, la série
de member_engagement (cogs/community_v3).
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Metier:
    nom: str
    emoji: str
    seuil: int          # travaux nécessaires pour l'obtenir
    salaire_min: int
    salaire_max: int
    taches: tuple[str, ...]


METIERS: tuple[Metier, ...] = (
    Metier("Stagiaire", "🧃", 0, 40, 120, (
        "a fait les photocopies de tout l'étage", "a apporté les cafés sans en renverser un seul",
        "a classé 300 dossiers par ordre alphabétique",
    )),
    Metier("Employé", "💼", 10, 80, 200, (
        "a bouclé un dossier en avance", "a répondu à 40 mails clients", "a sauvé une réunion qui partait mal",
    )),
    Metier("Technicien", "🔧", 30, 140, 300, (
        "a réparé le serveur en panne", "a installé tout le nouveau matériel", "a trouvé le bug que personne ne voyait",
    )),
    Metier("Manager", "📊", 60, 220, 420, (
        "a mené son équipe à l'objectif du mois", "a signé un gros contrat", "a recruté un excellent profil",
    )),
    Metier("Directeur", "🏢", 100, 320, 600, (
        "a présenté les résultats au conseil", "a ouvert une nouvelle agence", "a négocié un partenariat",
    )),
    Metier("PDG", "👑", 175, 500, 900, (
        "a fait entrer l'entreprise en bourse", "a racheté un concurrent", "a fait la une des journaux économiques",
    )),
)

#: (probabilité, multiplicateur, texte) — tirés dans l'ordre.
EVENEMENTS = (
    (0.05, 2.0, "🌟 Prime de performance : salaire doublé !"),
    (0.12, 1.5, "💸 Gros pourboire : +50 % !"),
    (0.06, 0.5, "😴 Journée ratée : moitié du salaire seulement."),
)

INTERET_TAUX = 0.01
INTERET_MAX = 1000
SERIE_BONUS_PAR_JOUR = 25
SERIE_BONUS_MAX_JOURS = 10
SERIE_PALIER_JOURS = 7
SERIE_PALIER_BONUS = 500


def metier_pour(travaux: int) -> Metier:
    actuel = METIERS[0]
    for metier in METIERS:
        if travaux >= metier.seuil:
            actuel = metier
    return actuel


def prochain_metier(travaux: int) -> Metier | None:
    for metier in METIERS:
        if travaux < metier.seuil:
            return metier
    return None


def barre(actuel: int, total: int, largeur: int = 10) -> str:
    total = max(1, int(total))
    plein = max(0, min(largeur, round(largeur * int(actuel) / total)))
    return "▰" * plein + "▱" * (largeur - plein)


def progression_metier(travaux: int) -> str:
    """« ▰▰▰▱▱▱▱▱▱▱ 3/10 → 💼 Employé » ou « Sommet atteint »."""
    actuel, suivant = metier_pour(travaux), prochain_metier(travaux)
    if suivant is None:
        return "👑 Sommet de la carrière atteint"
    fait, total = travaux - actuel.seuil, suivant.seuil - actuel.seuil
    return f"{barre(fait, total)} {fait}/{total} → {suivant.emoji} {suivant.nom}"


def tirer_salaire(travaux: int, alea: random.Random | None = None) -> tuple[int, str | None, Metier, str]:
    """(salaire, événement éventuel, métier, tâche du jour)."""
    alea = alea or random
    metier = metier_pour(travaux)
    salaire = alea.randint(metier.salaire_min, metier.salaire_max)
    evenement = None
    tirage = alea.random()
    cumul = 0.0
    for proba, multiplicateur, texte in EVENEMENTS:
        cumul += proba
        if tirage < cumul:
            salaire = max(1, int(salaire * multiplicateur))
            evenement = texte
            break
    return salaire, evenement, metier, alea.choice(metier.taches)


def interets(banque: int) -> int:
    return max(0, min(INTERET_MAX, int(int(banque or 0) * INTERET_TAUX)))


def bonus_serie(serie: int) -> int:
    """Bonus de série : +25 par jour (10 jours max), +500 à chaque palier de 7 jours."""
    serie = max(0, int(serie))
    bonus = min(serie, SERIE_BONUS_MAX_JOURS) * SERIE_BONUS_PAR_JOUR
    if serie and serie % SERIE_PALIER_JOURS == 0:
        bonus += SERIE_PALIER_BONUS
    return bonus


def flammes(serie: int) -> str:
    return "🔥" * max(1, min(5, (int(serie) + 1) // 2)) if serie else "—"


async def nombre_de_travaux(db, guild_id: int, user_id: int) -> int:
    try:
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM economy_transactions "
            "WHERE guild_id = ? AND receiver_id = ? AND transaction_type = 'work'",
            (int(guild_id), int(user_id)),
        )
        return int((row["n"] if row else 0) or 0)
    except Exception:  # noqa: BLE001 — sans historique lisible, on reste stagiaire
        return 0


__all__ = [
    "METIERS", "Metier", "metier_pour", "prochain_metier", "progression_metier", "tirer_salaire",
    "interets", "bonus_serie", "flammes", "barre", "nombre_de_travaux",
]
