"""Le salon que SentriX peut choisir tout seul (10/11/2026).

« Fais que la configuration ne porte que sur ce que le bot ne peut pas décider
par lui-même. » Le Setup demandait un salon de bienvenue même quand Discord en
désigne déjà un : ``guild.system_channel`` est le salon que le serveur a LUI-MÊME
déclaré pour les arrivées, et c'est là que Discord publie ses propres messages
de bienvenue. Demander à nouveau, c'est poser une question dont la réponse est
déjà écrite.

Ce module ne décide rien tout seul et n'écrit rien : il PROPOSE un salon, que le
Setup offre en un clic. Un salon n'est proposé que si SentriX peut vraiment y
écrire — proposer un salon interdit serait pire que ne rien proposer.
"""
from __future__ import annotations

import discord

#: Noms reconnus par usage, sans accent ni séparateur, pour chaque besoin.
NOMS = {
    "bienvenue": ("bienvenue", "welcome", "arrivees", "arrivals", "joins", "general", "chat"),
    "depart": ("departs", "goodbye", "aurevoir", "farewell", "leaves", "bienvenue", "welcome"),
    "logs": ("logs", "logsmoderation", "modlogs", "journal", "logsentrix", "sentrixlogs", "audit"),
}


def _compact(nom: str) -> str:
    texte = str(nom or "").casefold()
    for accent, simple in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ç", "c"), ("ô", "o")):
        texte = texte.replace(accent, simple)
    return "".join(c for c in texte if c.isalnum())


def peut_ecrire(guild: discord.Guild, salon) -> bool:
    moi = getattr(guild, "me", None)
    if moi is None or salon is None:
        return False
    try:
        permissions = salon.permissions_for(moi)
    except Exception:  # noqa: BLE001 — salon partiel : traité comme inutilisable
        return False
    return bool(permissions.view_channel and permissions.send_messages and permissions.embed_links)


def salon_evident(guild: discord.Guild, besoin: str):
    """Le salon que SentriX utiliserait, ou ``None`` s'il n'y en a pas d'évident.

    Pour les arrivées et les départs, le salon système de Discord passe avant
    tout : c'est le serveur lui-même qui l'a désigné.
    """
    if guild is None:
        return None
    if besoin in {"bienvenue", "depart"}:
        systeme = getattr(guild, "system_channel", None)
        if peut_ecrire(guild, systeme):
            return systeme
    salons = [c for c in getattr(guild, "text_channels", []) or [] if peut_ecrire(guild, c)]
    if not salons:
        return None
    attendus = NOMS.get(besoin, ())
    for attendu in attendus:
        for salon in salons:
            if _compact(salon.name) == attendu:
                return salon
    for attendu in attendus:
        for salon in salons:
            if attendu in _compact(salon.name):
                return salon
    return None


def pourquoi(guild: discord.Guild, besoin: str, salon) -> str:
    """La phrase qui explique le choix. Vide si rien n'est proposé."""
    if salon is None:
        return ""
    if besoin in {"bienvenue", "depart"} and salon == getattr(guild, "system_channel", None):
        return f"{salon.mention} est le salon d'arrivée déclaré par le serveur."
    return f"{salon.mention} porte déjà le nom qui convient."


__all__ = ["NOMS", "peut_ecrire", "pourquoi", "salon_evident"]
