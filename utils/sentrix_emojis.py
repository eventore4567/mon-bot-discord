"""Bibliothèque d'icônes SentriX — résolution centrale et synchronisation.

**Pourquoi des emojis d'APPLICATION et non des emojis de serveur.** SentriX
tourne sur 28 serveurs. Téléverser 119 icônes sur chacun consommerait leurs
emplacements d'emojis, demanderait une permission intrusive, et laisserait les
nouveaux serveurs sans icônes jusqu'à ce que quelqu'un y pense. Un emoji
d'application appartient au bot : il est téléversé UNE fois et s'affiche
partout où SentriX écrit, y compris en message privé.

**Pourquoi un point de résolution unique.** Un emoji personnalisé s'écrit
``<:nom:identifiant>``, et cet identifiant n'existe qu'après le téléversement.
Le coder en dur dans chaque cog le rendrait impossible à régénérer. Ici, le
code appelle ``emoji("ticket_claim")`` et ne connaît jamais d'identifiant.

**Le repli n'est pas optionnel.** Entre le premier démarrage et la fin de la
synchronisation, aucune icône n'existe. Si la résolution échouait, chaque
panneau afficherait ``<:sentrix_ticket:None>``. Toute fonction de ce module
rend donc quelque chose d'affichable, toujours.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import re

import discord

logger = logging.getLogger("bot.sentrix-emojis")

RACINE = pathlib.Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "assets" / "sentrix_emojis"

#: Préfixe obligatoire. Il sert de frontière : la politique visuelle interdit
#: les emojis Unicode décoratifs sur les boutons, mais autorise les icônes
#: SentriX. C'est ce préfixe qui permet de distinguer les deux sans ambiguïté.
PREFIXE = "sentrix_"

#: Les seuls noms autorisés à être animés. Jayden : « ne mets pas des
#: animations partout » — une interface qui bouge en permanence fatigue.
#: Une animation ne se justifie que pour un état VIVANT : quelque chose est en
#: cours, ou vient de changer.
ANIMES_AUTORISES = frozenset({
    "sentrix_loading", "sentrix_scan", "sentrix_live", "sentrix_success",
    "sentrix_alert", "sentrix_lock", "sentrix_unlock", "sentrix_upload",
    "sentrix_download", "sentrix_sync", "sentrix_typing", "sentrix_processing",
    "sentrix_ai",
})

#: Repli affiché tant que l'icône n'est pas disponible. Volontairement sobre :
#: ce sont des caractères typographiques, pas des emojis colorés, pour que le
#: repli ne contredise pas l'identité qu'il remplace. Un nom absent de cette
#: table rend une chaîne vide, ce qui est toujours préférable à un marqueur
#: cassé.
REPLIS: dict[str, str] = {
    "sentrix_success": "✓",
    "sentrix_verified": "✓",
    "sentrix_error": "✕",
    "sentrix_close": "✕",
    "sentrix_warning": "!",
    "sentrix_alert": "!",
    "sentrix_info": "·",
    "sentrix_loading": "…",
    "sentrix_more": "…",
    "sentrix_return": "←",
    "sentrix_priority": "▲",
}

#: Emojis Unicode que le pack sait remplacer. Construit sur une mesure : ce
#: sont ceux qui reviennent le plus dans les titres, libellés et descriptions
#: du bot. Un emoji absent de cette table garde sa forme Unicode — le
#: remplacement est progressif, et rien ne disparaît faute d'équivalent.
#:
#: Ne s'applique QU'À l'habillage SentriX : un journal qui cite un message
#: supprimé contenant « 🎁 » doit le montrer tel quel, pas le réécrire.
EQUIVALENCES: dict[str, str] = {
    "🎫": "ticket", "🎟": "ticket", "🎟️": "ticket",
    "🛡": "security", "🛡️": "security",
    "🔨": "ban", "👢": "kick", "🔇": "mute", "🔊": "voice",
    "⚠": "warning", "⚠️": "warning",
    "✅": "success", "☑": "success", "☑️": "success",
    "❌": "error", "✖": "error", "✖️": "error",
    "📝": "note", "✏": "message_edit", "✏️": "message_edit",
    "🗑": "trash", "🗑️": "trash",
    "🔎": "search", "🔍": "search",
    "👁": "eye", "👁️": "eye",
    "👤": "user", "👥": "users",
    "🏆": "trophy", "🎉": "party", "🎁": "gift",
    "💰": "wallet", "🪙": "coin", "💳": "bank",
    "📈": "chart", "📊": "chart",
    "🔄": "sync", "🔁": "sync",
    "💾": "backup", "🗄": "database", "🗄️": "database",
    "🛠": "tools", "🛠️": "tools", "⚙": "settings", "⚙️": "settings",
    "📋": "logs", "📁": "file", "📂": "file", "📄": "file",
    "🔒": "lock", "🔓": "unlock",
    "⏱": "clock", "⏱️": "clock", "🕐": "clock",
    "🎮": "gamepad", "🎲": "dice", "🎰": "slot",
    "🤖": "bot", "🧠": "ai",
    "📬": "ticket_open", "📭": "ticket_close",
    "⭐": "level", "🌟": "level",
    "ℹ": "info", "ℹ️": "info",
    "📥": "member_join", "📤": "member_leave",
}

#: Version du pack. À incrémenter dès que les FICHIERS changent d'apparence.
#:
#: Sans ce numéro, la synchronisation voit les anciennes icônes « déjà en
#: place » et garde indéfiniment la version précédente : un emoji
#: d'application ne porte ni date ni empreinte, donc rien ne permet de savoir
#: que le fichier local a changé.
VERSION_PACK = 2

#: Icône témoin. Sa présence signifie « ce compte porte déjà cette version ».
#: Elle occupe un emplacement sur 2000 et n'est jamais affichée — c'est le
#: prix d'une migration qui ne se rejoue pas à chaque démarrage.
TEMOIN = f"sentrix_pack_v{VERSION_PACK}"

#: nom -> marquage « <:nom:id> », rempli par synchroniser().
_RESOLUS: dict[str, str] = {}
_SYNCHRONISE = False

# Discord custom/application emoji markup. Generic string slicing inside one
# of these tokens exposes broken text instead of rendering an emoji.
_EMOJI_MARKUP_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]{5,}>")

def tronquer(texte: object, limite: int, *, suffixe: str = "…") -> str:
    """Truncate text without splitting a Discord custom emoji markup."""
    valeur = str(texte if texte is not None else "")
    limite = max(0, int(limite))
    if len(valeur) <= limite:
        return valeur
    if limite <= 0:
        return ""

    suffixe = str(suffixe or "")
    if len(suffixe) >= limite:
        return suffixe[:limite]

    cible = limite - len(suffixe)
    coupure = cible
    for match in _EMOJI_MARKUP_RE.finditer(valeur):
        if match.start() < coupure < match.end():
            coupure = match.start()
            break

    rendu = valeur[:coupure].rstrip()
    return (rendu + suffixe)[:limite]


# ---------------------------------------------------------------------------
# Lecture du pack sur disque
# ---------------------------------------------------------------------------

def _normaliser(nom: str) -> str:
    """Accepte « ticket_claim » comme « sentrix_ticket_claim »."""
    nom = str(nom or "").strip().lower()
    if not nom:
        return ""
    return nom if nom.startswith(PREFIXE) else PREFIXE + nom


def fichier(nom: str) -> pathlib.Path | None:
    """Fichier source de l'icône, ou ``None`` si le pack ne la contient pas.

    Le GIF n'est préféré que pour les noms de ``ANIMES_AUTORISES``. Huit
    icônes existent dans les deux formats, et toutes sont des états vivants —
    mais s'en remettre à cette coïncidence rendrait n'importe quel GIF ajouté
    plus tard animé par accident, alors que la consigne est de n'animer que ce
    qui bouge vraiment. La règle est donc écrite, pas déduite.

    Un nom animé sans version statique garde son GIF ; un nom animé AVEC une
    version statique peut y retomber par ``statique()``.
    """
    nom = _normaliser(nom)
    if not nom:
        return None
    ordre = (".gif", ".png") if nom in ANIMES_AUTORISES else (".png", ".gif")
    for extension in ordre:
        chemin = DOSSIER / f"{nom}{extension}"
        if chemin.is_file():
            return chemin
    return None


def statique(nom: str) -> pathlib.Path | None:
    """Version non animée, quand elle existe.

    Sert de repli propre là où une animation serait déplacée — une liste
    longue, un récapitulatif imprimé, un contexte qui n'accepte pas le GIF.
    """
    nom = _normaliser(nom)
    chemin = DOSSIER / f"{nom}.png"
    return chemin if chemin.is_file() else None


def noms_disponibles() -> list[str]:
    """Tous les noms présents dans le pack, triés."""
    if not DOSSIER.is_dir():
        return []
    return sorted({
        p.stem for p in DOSSIER.iterdir()
        if p.suffix.lower() in (".png", ".gif") and p.stem.startswith(PREFIXE)
    })


# ---------------------------------------------------------------------------
# Résolution — ce que le reste du bot utilise
# ---------------------------------------------------------------------------

def emoji(nom: str) -> str:
    """Marquage de l'icône SentriX, ou un repli sobre.

    Rend toujours une chaîne affichable : jamais ``None``, jamais un marqueur
    à moitié formé. Tant que la synchronisation n'a pas eu lieu, c'est le
    repli de ``REPLIS`` — ou une chaîne vide, ce qui ne casse aucun affichage.
    """
    nom = _normaliser(nom)
    resolu = _RESOLUS.get(nom)
    if resolu:
        return resolu
    return REPLIS.get(nom, "")


def partiel(nom: str) -> discord.PartialEmoji | None:
    """Icône pour un bouton ou une option de menu.

    Discord n'accepte pas de marquage texte à cet endroit : il lui faut un
    objet. Rend ``None`` si l'icône n'est pas disponible, et un bouton sans
    emoji reste parfaitement valide — c'est le repli correct ici.
    """
    nom = _normaliser(nom)
    resolu = _RESOLUS.get(nom)
    if not resolu:
        return None
    try:
        partiel = discord.PartialEmoji.from_str(resolu)
    except Exception:
        logger.debug("Icône %s non convertible en PartialEmoji.", nom, exc_info=True)
        return None
    # from_str n'échoue PAS sur un marquage malformé : il rend un emoji dont
    # le nom est la chaîne entière et dont l'identifiant est None. Discord
    # refuserait ce bouton, et la cause serait introuvable. Un emoji
    # personnalisé a forcément un identifiant.
    if partiel.id is None:
        logger.debug("Marquage d'icône malformé pour %s : %r", nom, resolu)
        return None
    return partiel


def titre(nom: str, texte: str) -> str:
    """« icône texte », ou « texte » seul quand l'icône manque.

    Évite le défaut classique du repli vide : ``f"{emoji(x)} {t}"`` laisse une
    espace en tête quand l'icône est absente, et tous les titres du panneau se
    retrouvent décalés d'un cran.
    """
    icone = emoji(nom)
    texte = str(texte or "")
    return f"{icone} {texte}".strip() if icone else texte


def traduire(texte: str) -> str:
    """Remplace les emojis Unicode connus par leur icône SentriX.

    À n'appliquer QU'À l'habillage du bot — titres de panneau, titres de
    section, libellés. Jamais au contenu rapporté : un journal qui cite un
    message supprimé doit le montrer tel qu'il était.

    Un emoji sans équivalent, ou dont l'icône n'est pas encore téléversée,
    reste intact. Le texte n'est donc jamais dégradé, seulement enrichi.
    """
    valeur = str(texte or "")
    if not valeur or not _RESOLUS:
        return valeur
    # Les clés les plus longues d'abord : « ⚠️ » contient « ⚠ » suivi d'un
    # sélecteur de variante invisible. Traiter la version courte en premier
    # remplaçait l'emoji et laissait le sélecteur orphelin derrière l'icône.
    for unicode_, nom in sorted(EQUIVALENCES.items(), key=lambda kv: -len(kv[0])):
        if unicode_ not in valeur:
            continue
        icone = _RESOLUS.get(_normaliser(nom))
        if icone:
            valeur = valeur.replace(unicode_, icone)
    return valeur


def est_sentrix(valeur: object) -> bool:
    """Ce marquage est-il une icône SentriX ?

    Sert à la politique visuelle : les emojis Unicode décoratifs restent
    interdits sur les boutons, les icônes SentriX sont autorisées. Sans cette
    distinction, la règle devrait choisir entre tout interdire et tout
    permettre.
    """
    if isinstance(valeur, discord.PartialEmoji | discord.Emoji):
        return str(getattr(valeur, "name", "") or "").startswith(PREFIXE)
    return PREFIXE in str(valeur or "")


# ---------------------------------------------------------------------------
# Synchronisation — téléversement idempotent
# ---------------------------------------------------------------------------

#: Pause entre deux téléversements. Le premier démarrage en pousse 119 : sans
#: ce délai, Discord répond 429 et la moitié du pack manque, en silence.
DELAI_ENTRE_ENVOIS = 0.6


async def synchroniser(bot, *, forcer: bool = False) -> dict[str, int]:
    """Synchronise le pack sans supprimer toutes les icônes en premier.

    Pendant une migration, chaque ancienne icône est remplacée séparément.
    Un échec n'empêche pas le bot de démarrer et n'invalide pas tout le pack.
    Le témoin de version n'est posé QUE quand tous les fichiers sont présents.
    """
    global _SYNCHRONISE
    if _SYNCHRONISE and not forcer:
        return {"deja_fait": 1}

    bilan = {"existants": 0, "envoyes": 0, "echecs": 0, "absents_du_pack": 0, "remplaces": 0}
    try:
        existants = await bot.fetch_application_emojis()
    except Exception:
        logger.warning("Icônes SentriX : lecture impossible, cache/replis conservés.", exc_info=True)
        return bilan

    deja = {str(getattr(i, "name", "") or ""): i for i in existants}
    # Reconstruire le cache depuis Discord : une relance forcée ne doit pas
    # conserver un ID d'emoji supprimé entretemps par un autre processus.
    _RESOLUS.clear()
    for nom, item in deja.items():
        if nom.startswith(PREFIXE):
            _RESOLUS[nom] = str(item)
            bilan["existants"] += 1

    version_installee = TEMOIN in deja
    noms = noms_disponibles()
    for nom in noms:
        chemin = fichier(nom)
        if chemin is None:
            bilan["absents_du_pack"] += 1
            continue

        ancien = deja.get(nom)
        if ancien is not None and version_installee:
            continue

        if ancien is not None:
            # Ne JAMAIS supprimer le pack entier avant de le reconstruire :
            # une panne réseau après trois créations cassait les 116 autres.
            try:
                await ancien.delete()
                bilan["remplaces"] += 1
                _RESOLUS.pop(nom, None)
            except Exception:
                bilan["echecs"] += 1
                logger.warning("Ancienne icône %s non remplaçable : conservée.", nom, exc_info=True)
                continue
            await asyncio.sleep(DELAI_ENTRE_ENVOIS)

        try:
            cree = await bot.create_application_emoji(name=nom, image=chemin.read_bytes())
            _RESOLUS[nom] = str(cree)
            bilan["envoyes"] += 1
        except Exception:
            bilan["echecs"] += 1
            # Si l'ancien emoji a été effacé, ne pas laisser un ID périmé
            # dans le cache : employer le repli typographique à la place.
            _RESOLUS.pop(nom, None)
            logger.warning("Icône %s non téléversée ; reprise au prochain essai.", nom, exc_info=True)
        await asyncio.sleep(DELAI_ENTRE_ENVOIS)

    complete = bool(noms) and all(n in _RESOLUS for n in noms)
    sans_erreur = bilan["echecs"] == 0 and bilan["absents_du_pack"] == 0

    if not version_installee and complete and sans_erreur:
        # Le témoin est le commit logique de la migration. Le placer à
        # moitié du pack bloquait les tentatives de reprise après un crash.
        try:
            marque = fichier("home")
            if marque is None:
                bilan["absents_du_pack"] += 1
            else:
                cree = await bot.create_application_emoji(name=TEMOIN, image=marque.read_bytes())
                _RESOLUS[TEMOIN] = str(cree)
        except Exception:
            bilan["echecs"] += 1
            logger.warning("Témoin du pack v%s non posé ; reprise ultérieure.", VERSION_PACK, exc_info=True)

    _SYNCHRONISE = complete and sans_erreur and TEMOIN in _RESOLUS
    logger.info(
        "Icônes SentriX v%s : %s déjà en place, %s remplacées, %s téléversées, %s échecs, terminé=%s.",
        VERSION_PACK, bilan["existants"], bilan["remplaces"], bilan["envoyes"],
        bilan["echecs"], _SYNCHRONISE,
    )
    return bilan


def amorcer(resolus: dict[str, str]) -> None:
    """Pose un cache déjà connu — pour les tests, sans appel réseau."""
    _RESOLUS.update({_normaliser(k): v for k, v in resolus.items()})


def reinitialiser() -> None:
    """Vide le cache. Réservé aux tests."""
    global _SYNCHRONISE
    _RESOLUS.clear()
    _SYNCHRONISE = False


__all__ = [
    "ANIMES_AUTORISES",
    "DOSSIER",
    "PREFIXE",
    "REPLIS",
    "amorcer",
    "emoji",
    "est_sentrix",
    "fichier",
    "noms_disponibles",
    "statique",
    "partiel",
    "reinitialiser",
    "synchroniser",
    "titre",
    "traduire",
    "tronquer",
]
