"""Artisanat de ``+potion`` — consommation et création d'objets atomiques.

Tout passe par la vraie table ``inventory``, celle du magasin et de ``+inv`` :
un stock parallèle réservé aux potions finirait par diverger de ce que le
joueur voit, et deux inventaires qui se contredisent est pire que pas
d'artisanat du tout.

Une fabrication touche plusieurs lignes. Si la troisième échoue, les deux
premières doivent revenir en arrière — sans quoi le joueur perd ses
ingrédients sans rien recevoir. Tout tient donc dans une seule transaction,
avec ``rollback`` sur la moindre anomalie, et chaque retrait est conditionnel
(``WHERE quantity >= ?`` puis contrôle du ``rowcount``) : deux fabrications
simultanées sur le dernier ingrédient ne peuvent pas réussir toutes les deux.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("bot.crafting")

# Prix de repli de services.economy.atomic_sell pour un objet hors boutique.
# Il fixe la valeur de revente d'un ingrédient comme d'une potion, et c'est lui
# qui rend vérifiable l'absence de boucle « fabriquer puis revendre ».
VALEUR_REVENTE = 10


@dataclass(frozen=True)
class Ingredient:
    cle: str
    nom: str
    emoji: str
    poids: int      # fréquence relative à la récolte


INGREDIENTS: dict[str, Ingredient] = {
    "herbe": Ingredient("herbe", "Herbe de lune", "🌿", 40),
    "rosee": Ingredient("rosee", "Rosée d'aube", "💧", 30),
    "champignon": Ingredient("champignon", "Champignon bleu", "🍄", 20),
    "eclat": Ingredient("eclat", "Éclat de quartz", "✨", 10),
}


@dataclass(frozen=True)
class Recette:
    cle: str
    nom: str
    emoji: str
    ingredients: tuple[tuple[str, int], ...]
    multiplicateur_argent: float
    multiplicateur_xp: float
    duree: int          # secondes
    description: str

    @property
    def cout_total(self) -> int:
        return sum(quantite for _cle, quantite in self.ingredients)


RECETTES: dict[str, Recette] = {
    "vigueur": Recette(
        "vigueur", "Potion de vigueur", "🧪",
        (("herbe", 2), ("rosee", 1)),
        1.25, 1.0, 1800,
        "Vos gains d'argent augmentent d'un quart pendant trente minutes.",
    ),
    "savoir": Recette(
        "savoir", "Élixir de savoir", "🔮",
        (("champignon", 2), ("rosee", 1)),
        1.0, 1.30, 1800,
        "Votre expérience monte d'un tiers plus vite pendant trente minutes.",
    ),
    "fortune": Recette(
        "fortune", "Philtre d'or", "🌟",
        (("herbe", 2), ("champignon", 1), ("eclat", 1)),
        1.50, 1.50, 1200,
        "Argent et expérience d'un coup, pendant vingt minutes.",
    ),
}

RECOLTE_MIN, RECOLTE_MAX = 2, 4      # unités ramenées par récolte


def nom_objet(cle: str) -> str:
    """Nom stocké en base pour un ingrédient ou une potion.

    L'émoji fait partie du nom : ``+inv`` et la boutique affichent la colonne
    telle quelle, et une ligne « Herbe de lune » sans pictogramme se noierait
    au milieu des objets du magasin.
    """
    if cle in INGREDIENTS:
        ing = INGREDIENTS[cle]
        return f"{ing.emoji} {ing.nom}"
    recette = RECETTES[cle]
    return f"{recette.emoji} {recette.nom}"


async def _fetchone(conn, requete: str, params: tuple = ()):
    curseur = await conn.execute(requete, params)
    try:
        return await curseur.fetchone()
    finally:
        await curseur.close()


async def stock(db, guild_id: int, user_id: int) -> dict[str, int]:
    """Quantités possédées, par clé d'ingrédient et de potion."""
    noms = {nom_objet(cle): cle for cle in list(INGREDIENTS) + list(RECETTES)}
    try:
        lignes = await db.fetchall(
            "SELECT item_name, quantity FROM inventory WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
    except Exception:
        logger.debug("Inventaire illisible pour %s/%s.", guild_id, user_id, exc_info=True)
        return {}
    resultat: dict[str, int] = {}
    for ligne in lignes or ():
        cle = noms.get(ligne["item_name"])
        if cle is not None:
            resultat[cle] = max(0, int(ligne["quantity"] or 0))
    return resultat


def recettes_realisables(stocks: dict[str, int]) -> list[Recette]:
    return [r for r in RECETTES.values()
            if all(stocks.get(cle, 0) >= q for cle, q in r.ingredients)]


def manquants(recette: Recette, stocks: dict[str, int]) -> list[tuple[str, int]]:
    return [(cle, q - stocks.get(cle, 0))
            for cle, q in recette.ingredients if stocks.get(cle, 0) < q]


async def _crediter(conn, guild_id: int, user_id: int, nom: str, quantite: int) -> None:
    await conn.execute(
        "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET "
        "quantity=inventory.quantity+excluded.quantity",
        (guild_id, user_id, nom, int(quantite)),
    )


async def recolter(db, guild_id: int, user_id: int, tirages: list[tuple[str, int]]):
    """Ajoute les ingrédients ramenés. Retourne ("ok", tirages) ou (statut, []).

    Les tirages sont décidés par l'appelant et passés ici déjà figés : la
    couche base ne doit pas tirer au sort, sinon le résultat affiché au joueur
    et celui écrit en base pourraient différer.
    """
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable", []
    if not tirages:
        return "invalid", []
    async with db._economy_lock:
        try:
            for cle, quantite in tirages:
                if cle not in INGREDIENTS or quantite <= 0:
                    await conn.rollback()
                    return "invalid", []
                await _crediter(conn, guild_id, user_id, nom_objet(cle), quantite)
            await conn.commit()
            return "ok", list(tirages)
        except Exception:
            await conn.rollback()
            logger.exception("Récolte annulée pour %s/%s.", guild_id, user_id)
            return "error", []


async def fabriquer(db, guild_id: int, user_id: int, cle_recette: str) -> str:
    """Consomme les ingrédients et crée la potion, tout ou rien.

    Retourne "ok", "missing" (ingrédients insuffisants), "invalid",
    "unavailable" ou "error". Le retrait est conditionnel puis vérifié par son
    ``rowcount`` : c'est ce contrôle, et non le verrou, qui garantit qu'une
    seule de deux fabrications simultanées sur le dernier ingrédient aboutit.
    """
    recette = RECETTES.get(cle_recette)
    if recette is None:
        return "invalid"
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable"
    async with db._economy_lock:
        try:
            for cle, quantite in recette.ingredients:
                curseur = await conn.execute(
                    "UPDATE inventory SET quantity=quantity-? "
                    "WHERE guild_id=? AND user_id=? AND item_name=? AND quantity>=?",
                    (quantite, guild_id, user_id, nom_objet(cle), quantite),
                )
                if curseur.rowcount < 1:
                    await conn.rollback()
                    return "missing"
            await conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND quantity<=0",
                (guild_id, user_id),
            )
            await _crediter(conn, guild_id, user_id, nom_objet(recette.cle), 1)
            await conn.commit()
            return "ok"
        except Exception:
            await conn.rollback()
            logger.exception("Fabrication annulée pour %s/%s (%s).",
                             guild_id, user_id, cle_recette)
            return "error"


async def boire(db, guild_id: int, user_id: int, cle_recette: str):
    """Consomme une potion et active son effet. Retourne (statut, boost|None).

    La potion est retirée AVANT d'accorder le boost, et remise si l'octroi
    échoue : accorder d'abord laisserait un effet actif payé par une potion
    jamais consommée.
    """
    recette = RECETTES.get(cle_recette)
    if recette is None:
        return "invalid", None
    conn = getattr(db, "_conn", None)
    if conn is None:
        return "unavailable", None
    nom = nom_objet(recette.cle)
    async with db._economy_lock:
        try:
            curseur = await conn.execute(
                "UPDATE inventory SET quantity=quantity-1 "
                "WHERE guild_id=? AND user_id=? AND item_name=? AND quantity>=1",
                (guild_id, user_id, nom),
            )
            if curseur.rowcount < 1:
                await conn.rollback()
                return "missing", None
            await conn.execute(
                "DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_name=? "
                "AND quantity<=0", (guild_id, user_id, nom),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            logger.exception("Potion non consommée pour %s/%s.", guild_id, user_id)
            return "error", None

    from utils import temporary_boosts
    try:
        boost, _nouveau = await temporary_boosts.grant_quest_boost(
            db, guild_id, user_id,
            money_multiplier=recette.multiplicateur_argent,
            xp_multiplier=recette.multiplicateur_xp,
            duration_seconds=recette.duree,
            source=f"potion:{recette.cle}",
            now_ts=int(time.time()),
        )
        return "ok", boost
    except Exception:
        logger.exception("Boost refusé après consommation : potion rendue (%s).", recette.cle)
        async with db._economy_lock:
            try:
                await _crediter(conn, guild_id, user_id, nom, 1)
                await conn.commit()
            except Exception:
                await conn.rollback()
                logger.exception("Potion perdue sans effet pour %s/%s.", guild_id, user_id)
        return "error", None
