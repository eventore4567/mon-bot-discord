"""Ce qu'une carte de log AutoMod doit dire d'un incident, sans rien cacher.

Demande de Jayden du 29/10/2026 : des logs AutoMod complets et lisibles —
membre, salon (accès direct), date exacte, protection, règle, motif, contenu
neutralisé, action, durée, récidives — et la différence entre une détection,
une action réussie, un blocage et une erreur.

Ce module ne fait que décrire : ``cogs/automod._flush_incident_log`` remplit
les champs, ``utils/wide_logs`` les met en page. Un contenu trop long n'est pas
tronqué en silence : il part en fichier joint.
"""
from __future__ import annotations

import io
import re
from collections import OrderedDict

import discord

#: filtre -> (protection, règle). La protection est le module que le staff
#: active ; la règle est le critère précis qui a déclenché.
PROTECTIONS: dict[str, tuple[str, str]] = {
    "antilink": ("Anti-liens", "Lien hors de la liste blanche du serveur"),
    "blacklist_link": ("Anti-liens", "Lien de la liste noire du serveur"),
    "blacklist_word_link": ("Anti-liens", "Lien contenant un mot interdit"),
    "antiinvite": ("Anti-invitations", "Invitation vers un autre serveur Discord"),
    "antiscam": ("Anti-arnaques", "Arnaque ou hameçonnage reconnu"),
    "blacklist_word": ("Mots interdits", "Mot de la liste du serveur"),
    "antiinsult": ("Anti-insultes", "Contenu offensant"),
    "antimention": ("Anti-mentions", "Trop de mentions dans un message"),
    "antispam": ("Anti-spam", "Messages trop rapprochés"),
    "antispam_duplicate": ("Anti-spam", "Même message répété"),
    "anticaps": ("Anti-majuscules", "Message presque entièrement en majuscules"),
    "antiemoji": ("Anti-émojis", "Trop d'émojis dans un message"),
}

#: Statut de l'incident, toujours affiché en premier.
STATUTS = {
    "reussie": "Action réussie — message retiré et sanction appliquée",
    "bloque": "Message bloqué — retiré, sans sanction",
    "detection": "Détection seule — aucun message retiré",
    "erreur": "Échec — l'action prévue n'a pas pu être appliquée",
}

#: Libellés sans émoji Discord classique (les icônes SentriX sont posées par la carte).
ACTIONS = {
    "mute": "Exclusion temporaire",
    "warn": "Avertissement enregistré",
    "kick": "Expulsion",
    "ban": "Bannissement",
    "derank": "Rôles à risque retirés",
    "warning_ping": "Rappel anti-spam",
    "mute_failed": "Exclusion temporaire prévue, non appliquée",
}
SANCTIONS = frozenset({"mute", "warn", "kick", "ban", "derank"})

#: Au-delà, le contenu complet part en fichier joint.
LIMITE_CONTENU = 900

_URL_RE = re.compile(r"\b((?:https?|hxxps?)://)([^\s/<>()]+)([^\s<>()]*)", re.IGNORECASE)
_INVITE_RE = re.compile(
    r"\b(discord(?:app)?\.(?:gg|com|io|me|li)|dsc\.gg)(/(?:invite/)?[A-Za-z0-9-]+)", re.IGNORECASE
)
_MENTION_RE = re.compile(r"<@[!&]?\d+>")


def _point_neutre(hote: str) -> str:
    return hote.replace(".", "[.]")


def neutraliser(texte: str) -> str:
    """Rend le texte inoffensif dans un log : liens et invitations non cliquables,
    @everyone/@here inertes, aucun bloc de code qui se refermerait."""
    texte = str(texte or "")
    texte = _URL_RE.sub(
        lambda m: m.group(1).lower().replace("http", "hxxp") + _point_neutre(m.group(2)) + m.group(3), texte
    )
    texte = _INVITE_RE.sub(lambda m: _point_neutre(m.group(1)) + m.group(2), texte)
    texte = texte.replace("@everyone", "@​everyone").replace("@here", "@​here")
    return texte.replace("```", "ʼʼʼ")


def elements_detectes(filter_name: str, contenu: str) -> str:
    """L'élément précis visé, neutralisé : domaine, invitation, nombre de mentions."""
    contenu = str(contenu or "")
    if filter_name in {"antilink", "blacklist_link", "blacklist_word_link", "antiscam"}:
        hotes = []
        for m in _URL_RE.finditer(contenu):
            hote = _point_neutre(m.group(2).lower())
            if hote not in hotes:
                hotes.append(hote)
        return ", ".join(f"`{h}`" for h in hotes[:5])
    if filter_name == "antiinvite":
        codes = []
        for m in _INVITE_RE.finditer(contenu):
            code = _point_neutre(m.group(1).lower()) + m.group(2)
            if code not in codes:
                codes.append(code)
        return ", ".join(f"`{c}`" for c in codes[:5])
    if filter_name == "antimention":
        n = len(_MENTION_RE.findall(contenu)) + contenu.count("@everyone") + contenu.count("@here")
        return f"{n} mentions" if n else ""
    return ""


def statut(deleted_ok: bool | None, action: str | None) -> str:
    if action == "mute_failed" or deleted_ok is False:
        return "erreur"
    if action in SANCTIONS:
        return "reussie"
    if deleted_ok:
        return "bloque"
    return "detection"


def libelle_action(action: str | None, deleted_ok: bool | None) -> str:
    morceaux = []
    if deleted_ok:
        morceaux.append("Message supprimé")
    elif deleted_ok is False:
        morceaux.append("Suppression du message refusée par Discord")
    if action:
        morceaux.append(ACTIONS.get(action, action))
    return " · ".join(morceaux) or "Aucune action (détection seule)"


def libelle_duree(secondes: int | None, debut: float) -> str:
    if not secondes:
        return ""
    if secondes % 3600 == 0:
        texte = f"{secondes // 3600} h"
    elif secondes % 60 == 0:
        texte = f"{secondes // 60} min"
    else:
        texte = f"{secondes} s"
    return f"{texte} · jusqu'à <t:{int(debut + secondes)}:t>"


def champs(*, filter_name: str, reason: str, guild_id: int, channel_id: int, message_id: int,
           created_at: float, contenu: str, deleted: int, deleted_ok: bool | None,
           action: str | None, duree_s: int | None, infractions: int, spam_stage: int,
           memoire: str, ref: str) -> tuple["OrderedDict[str, str]", discord.File | None]:
    """Champs ordonnés de la carte + fichier joint si le contenu est trop long."""
    protection, regle = PROTECTIONS.get(filter_name, ("AutoMod", filter_name or "Filtre SentriX"))
    out: OrderedDict[str, str] = OrderedDict()
    out["Statut"] = STATUTS[statut(deleted_ok, action)]
    out["Protection"] = protection
    out["Règle"] = regle
    if reason:
        out["Motif"] = reason
    element = elements_detectes(filter_name, contenu)
    if element:
        out["Élément détecté"] = element
    out["Salon"] = f"<#{channel_id}> · [ouvrir](https://discord.com/channels/{guild_id}/{channel_id})"
    ts = int(created_at)
    out["Date"] = f"<t:{ts}:F> · <t:{ts}:R>"
    out["Action"] = libelle_action(action, deleted_ok)
    duree = libelle_duree(duree_s, created_at) if action == "mute" else ""
    if duree:
        out["Durée"] = duree
    if deleted > 1:
        out["Messages supprimés"] = str(deleted)
    if spam_stage:
        out["Niveau anti-spam"] = str(spam_stage)
    if infractions:
        out["Infractions (1 h)"] = str(infractions)
    if memoire:
        out["Récidive"] = memoire
    fichier = None
    propre = neutraliser(contenu).strip()
    if propre:
        if len(propre) > LIMITE_CONTENU:
            out["Contenu"] = (f"```\n{propre[:LIMITE_CONTENU].rstrip()}…\n```\n"
                              f"-# Contenu complet ({len(propre)} caractères) dans le fichier joint.")
            nom = f"automod-{ref or message_id or ts}.txt"
            corps = (f"Incident AutoMod {ref}\nProtection : {protection}\nRègle : {regle}\n"
                     f"Motif : {reason}\nSalon : {channel_id}\nMessage : {message_id}\n\n{propre}\n")
            fichier = discord.File(io.BytesIO(corps.encode("utf-8")), filename=nom)
        else:
            out["Contenu"] = f"```\n{propre}\n```"
    return out, fichier
