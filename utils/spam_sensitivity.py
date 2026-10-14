"""Réactivité de l'anti-spam : souple, normale, stricte, ou seuils choisis par le serveur.

Le niveau de sécurité du serveur (/security-level, page Sécurité du dashboard)
ne faisait qu'allumer ou éteindre des filtres : tous les serveurs avaient les
mêmes seuils (5 messages en 6 s). Il règle maintenant aussi la réactivité :

    faible -> souple   : 7 messages en 6 s, 5 copies, 7 comptes coordonnés
    moyen  -> normale  : 5 messages en 6 s, 4 copies, 5 comptes (l'ancien comportement)
    eleve  -> stricte  : 4 messages en 5 s, 3 copies, 4 comptes

Un serveur sans niveau choisi reste en réactivité normale. Un administrateur
peut fixer ses propres seuils de rafale (« Personnalisé ») sans toucher aux
interrupteurs des filtres.

Renfort anti-raid : quand plusieurs membres déclenchent l'anti-spam en même
temps, le serveur passe en réactivité stricte pendant 10 minutes, puis revient
seul à son niveau. Il rend la détection plus rapide ; il ne durcit pas les
sanctions, qui suivent toujours la progression rappel → avertissement → mute.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Seuils:
    messages: int          # messages dans la fenêtre avant incident
    secondes: int          # durée de la fenêtre de rafale
    repetitions: int       # même message répété avant incident
    comptes_coordonnes: int  # comptes postant le même message avant incident

    def plus_strict(self, autre: "Seuils") -> "Seuils":
        return Seuils(
            messages=min(self.messages, autre.messages),
            secondes=max(self.secondes, autre.secondes),
            repetitions=min(self.repetitions, autre.repetitions),
            comptes_coordonnes=min(self.comptes_coordonnes, autre.comptes_coordonnes),
        )

    def phrase(self) -> str:
        return f"{self.messages} messages en {self.secondes} s"


NIVEAUX = {
    "souple": Seuils(messages=7, secondes=6, repetitions=5, comptes_coordonnes=7),
    "normale": Seuils(messages=5, secondes=6, repetitions=4, comptes_coordonnes=5),
    "stricte": Seuils(messages=4, secondes=5, repetitions=3, comptes_coordonnes=4),
}
NIVEAU_DEPUIS_SECURITE = {"faible": "souple", "moyen": "normale", "eleve": "stricte"}
NIVEAU_PAR_DEFAUT = "normale"

# Bornes des seuils personnalisés : en dessous de 3 messages, une conversation
# animée devient du spam ; au-delà de 30 s, la fenêtre ne voit plus une rafale.
MESSAGES_MIN, MESSAGES_MAX = 3, 20
SECONDES_MIN, SECONDES_MAX = 3, 30
FENETRE_MAX = SECONDES_MAX  # fenêtre du compteur partagé (cogs/automod.py)

RENFORT_SECONDES = 600
RENFORT_SPAMMEURS = 3   # membres distincts en incident anti-spam...
RENFORT_FENETRE = 30    # ...dans ces secondes

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_spam_thresholds (
    guild_id INTEGER PRIMARY KEY,
    messages INTEGER NOT NULL,
    seconds INTEGER NOT NULL,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class Reglage:
    niveau: str            # souple / normale / stricte / personnalisée
    seuils: Seuils
    personnalise: bool = False


async def _ensure_schema(db) -> None:
    if getattr(db, "_sentrix_spam_thresholds_ready", False):
        return
    await db.execute(SCHEMA)
    try:
        db._sentrix_spam_thresholds_ready = True
    except AttributeError:
        pass


async def lire(bot, guild_id: int) -> Reglage:
    """Le réglage du serveur. Toute erreur de lecture retombe sur la réactivité normale."""
    db = bot.db
    niveau = NIVEAU_PAR_DEFAUT
    try:
        conf = await db.get_guild_config(guild_id)
        securite = conf["security_level"] if conf is not None else None
        niveau = NIVEAU_DEPUIS_SECURITE.get(str(securite or "").lower(), NIVEAU_PAR_DEFAUT)
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    base = NIVEAUX[niveau]
    try:
        await _ensure_schema(db)
        row = await db.fetchone(
            "SELECT messages, seconds FROM sentrix_spam_thresholds WHERE guild_id = ?", (int(guild_id),)
        )
    except AttributeError:
        row = None
    if row:
        seuils = replace(
            base,
            messages=_borne(row["messages"], MESSAGES_MIN, MESSAGES_MAX),
            secondes=_borne(row["seconds"], SECONDES_MIN, SECONDES_MAX),
        )
        return Reglage("personnalisée", seuils, personnalise=True)
    return Reglage(niveau, base)


async def personnaliser(bot, guild_id: int, messages: int, secondes: int, auteur_id: int | None) -> Seuils:
    messages = _borne(messages, MESSAGES_MIN, MESSAGES_MAX)
    secondes = _borne(secondes, SECONDES_MIN, SECONDES_MAX)
    await _ensure_schema(bot.db)
    await bot.db.execute(
        "INSERT INTO sentrix_spam_thresholds (guild_id, messages, seconds, updated_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET messages = excluded.messages, "
        "seconds = excluded.seconds, updated_by = excluded.updated_by, updated_at = excluded.updated_at",
        (int(guild_id), messages, secondes, auteur_id, int(time.time())),
    )
    return (await lire(bot, guild_id)).seuils


async def oublier_personnalisation(bot, guild_id: int) -> None:
    await _ensure_schema(bot.db)
    await bot.db.execute("DELETE FROM sentrix_spam_thresholds WHERE guild_id = ?", (int(guild_id),))


def _borne(valeur, minimum: int, maximum: int) -> int:
    try:
        nombre = int(valeur)
    except (TypeError, ValueError):
        nombre = minimum
    return max(minimum, min(maximum, nombre))


__all__ = [
    "Seuils", "Reglage", "NIVEAUX", "NIVEAU_DEPUIS_SECURITE", "NIVEAU_PAR_DEFAUT",
    "MESSAGES_MIN", "MESSAGES_MAX", "SECONDES_MIN", "SECONDES_MAX", "FENETRE_MAX",
    "RENFORT_SECONDES", "RENFORT_SPAMMEURS", "RENFORT_FENETRE",
    "lire", "personnaliser", "oublier_personnalisation",
]
