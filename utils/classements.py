"""Les classements du serveur, lus au même endroit (10/11/2026).

« Fais un classement invitations et un classement vocal. » Le classement des
invitations existait déjà (`/invite-leaderboard`), mais la production dit qu'il
n'a servi à personne en trente jours : perdu parmi 357 commandes. Le vocal, lui,
n'était visible que dans sa propre fiche de profil.

Ce module rend chaque classement sous la même forme — (identifiant, valeur) trié —
à partir des tables qui existent déjà. Aucune nouvelle donnée n'est collectée.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from utils import stats_service


@dataclass(frozen=True)
class Categorie:
    cle: str
    titre: str
    description: str
    icone: str
    unite: Callable[[int], str]


def _nombre(valeur: int) -> str:
    return stats_service.format_number(int(valeur))


CATEGORIES: tuple[Categorie, ...] = (
    Categorie("niveaux", "Niveaux", "Les plus hauts niveaux", "level",
              lambda v: f"Niv. {v // 1_000_000} · {_nombre(v % 1_000_000)} XP"),
    Categorie("messages", "Messages", "Les plus bavards", "message",
              lambda v: f"{_nombre(v)} messages"),
    Categorie("vocal", "Vocal", "Le plus de temps en vocal", "voice",
              lambda v: stats_service.format_duration(v)),
    Categorie("invitations", "Invitations", "Les plus gros recruteurs", "member_join",
              lambda v: f"{_nombre(v)} invitation{'s' if v > 1 else ''}"),
    Categorie("economie", "Économie", "Les plus riches", "wallet",
              lambda v: f"{_nombre(v)} pièces"),
)
PAR_CLE = {c.cle: c for c in CATEGORIES}
DEFAUT = "niveaux"
#: Le niveau prime sur l'XP : un seul entier trié permet de partager le même code.
NIVEAU_FACTEUR = 1_000_000


async def lire(bot, guild_id: int, categorie: str, limite: int = 100) -> list[tuple[int, int]]:
    """(user_id, valeur) du plus grand au plus petit. Jamais d'exception de table."""
    db = bot.db
    if categorie == "niveaux":
        lignes = await db.fetchall(
            "SELECT user_id, level, xp FROM levels WHERE guild_id = ? "
            "ORDER BY level DESC, xp DESC LIMIT ?", (guild_id, limite),
        )
        return [(int(l["user_id"]), int(l["level"]) * NIVEAU_FACTEUR + int(l["xp"])) for l in lignes]
    if categorie == "messages":
        lignes = await db.fetchall(
            "SELECT user_id, count FROM message_counts WHERE guild_id = ? AND count > 0 "
            "ORDER BY count DESC LIMIT ?", (guild_id, limite),
        )
        return [(int(l["user_id"]), int(l["count"])) for l in lignes]
    if categorie == "vocal":
        lignes = await db.fetchall(
            "SELECT user_id, seconds FROM voice_totals WHERE guild_id = ? AND seconds > 0 "
            "ORDER BY seconds DESC LIMIT ?", (guild_id, limite),
        )
        return [(int(l["user_id"]), int(l["seconds"])) for l in lignes]
    if categorie == "invitations":
        lignes = await db.get_invite_leaderboard_credited(guild_id, limite)
        return [(int(uid), int(b["credited"])) for uid, b in lignes if int(b["credited"]) > 0]
    if categorie == "economie":
        lignes = await db.fetchall(
            "SELECT user_id, cash + bank AS total FROM economy WHERE guild_id = ? AND cash + bank > 0 "
            "ORDER BY total DESC LIMIT ?", (guild_id, limite),
        )
        return [(int(l["user_id"]), int(l["total"])) for l in lignes]
    return []


def sans_les_bots(guild, lignes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Un membre absent du cache est gardé : il n'a pas forcément quitté le serveur."""
    gardees = []
    for user_id, valeur in lignes:
        membre = guild.get_member(user_id) if guild is not None else None
        if membre is not None and membre.bot:
            continue
        gardees.append((user_id, valeur))
    return gardees


def rang_de(lignes: list[tuple[int, int]], user_id: int) -> int | None:
    for position, (uid, _valeur) in enumerate(lignes, start=1):
        if uid == int(user_id):
            return position
    return None


def podium(position: int) -> str:
    """🥇 🥈 🥉 puis « ` 4.` » à largeur fixe : les noms restent alignés."""
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(position, f"`{position:>2}.`")


def lignes_du_top(categorie: Categorie, lignes: list[tuple[int, int]], combien: int = 10) -> list[str]:
    return [
        f"{podium(i)} <@{uid}> · **{categorie.unite(valeur)}**"
        for i, (uid, valeur) in enumerate(lignes[:combien], start=1)
    ]


def ma_position(categorie: Categorie, lignes: list[tuple[int, int]], user_id: int) -> str:
    rang = rang_de(lignes, user_id)
    if rang is None:
        return "Vous n'êtes pas encore classé."
    return f"**#{rang}** sur {len(lignes)} · **{categorie.unite(lignes[rang - 1][1])}**"


__all__ = [
    "CATEGORIES", "Categorie", "DEFAUT", "NIVEAU_FACTEUR", "PAR_CLE",
    "lignes_du_top", "lire", "ma_position", "podium", "rang_de", "sans_les_bots",
]
