"""SentriX Core — composition officielle des réponses structurées de commandes.

Le rendu Components V2 suit une grammaire propre à SentriX : bannière de domaine,
signature Core, titre, sections numérotées, contenu, signature de fin et actions.
Les confirmations d'une ligne restent volontairement en texte brut.

Les bannières sont générées au démarrage par ``utils/log_banners`` et jointes au
message (``attachment://``). Elles ne dépendent donc pas du dépôt distant.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import re as _re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import discord

import config as _config
from utils.log_banners import (
    BANNER_DIR, ensure_banners, family_for_command, nom_fichier,
)

logger = logging.getLogger("bot.panels")

# Intentions -> couleur d'accent du conteneur et bannière correspondante.
# Les noms de bannière sont ceux de utils/log_banners.COLORS.
# Deux familles d'intentions.
#
#   Les ETATS disent ce qui vient de se passer : reussite, refus, avertissement.
#   Les DOMAINES disent de quoi on parle, quand l'etat n'apporte rien — une fiche
#   de moderation reussie n'est pas « verte », elle est « moderation ». Une
#   sanction affichee en vert de reussite serait un contresens.
INTENTIONS: dict[str, tuple[int, str]] = {
    # Etats : la couleur vient de config.py, comme les embeds. Le liseré du conteneur
    # et le trait de la bannière sont alors exactement le même rouge, vert ou ambre.
    "success": (int(_config.COLOR_SUCCESS), "success"),
    "danger": (int(_config.COLOR_ERROR), "error"),
    "warning": (int(_config.COLOR_WARNING), "warning"),
    "info": (int(_config.COLOR_INFO), "info"),
    "brand": (int(_config.COLOR_BRAND), "special"),
    "neutral": (int(_config.COLOR_INFO), "info"),
    # Domaines : la teinte est celle de la famille de bannière (utils/log_banners).
    "moderation": (0xFF6B6B, "moderation"),
    "securite": (0x22D3EE, "security"),
    "tickets": (0x2DD4BF, "tickets"),
    "economie": (0xF5C542, "economy"),
    "niveaux": (0xA3E635, "levels"),
    "musique": (0xFF5FC8, "music"),
    "jeux": (0xFF8A3D, "games"),
    "ia": (0xA855F7, "ai"),
    "configuration": (0xC084FC, "config"),
    "bienvenue": (0x34D399, "welcome"),
    # Giveaways, concours, évènements. Même indigo que leur bannière : le liseré
    # du conteneur et le trait de la bannière doivent être la même couleur, sinon
    # la carte a deux teintes qui se disputent.
    "evenements": (0x818CF8, "events"),
    "depart": (0xFF6A3D, "goodbye"),
}

# Intentions qui ne disent rien du domaine : pour celles-la, la banniere prend la
# couleur de la commande en cours (+play en rose musique, +balance en or economie)
# plutot que le meme bleu d'information pour tout le bot. Un etat explicite —
# reussite, refus, avertissement — garde evidemment sa couleur.
INTENTIONS_NEUTRES = frozenset({"info", "neutral", "brand"})

# SentriX Core n'utilise ni chevrons ni puces héritées : chaque bloc reçoit
# un numéro stable et lisible ("01 · Identité", "02 · Activité", ...).
CORE_NAME = "SENTRIX CORE"

#: Les bandeaux décoratifs sont retirés de l'interface. Le premium vient des
#: composants, des icônes et de la hiérarchie du texte — pas d'une image qui
#: occupe le tiers du message sans rien apprendre au lecteur.
#:
#: Un seul interrupteur, et il gouverne les DEUX côtés : `poser_bandeau`
#: n'affiche plus de galerie, donc `pieces_jointes_de_famille` ne joint plus
#: de fichier, puisque les deux consultent la même condition. Les séparer
#: serait dangereux : une galerie sans sa pièce jointe fait REFUSER le message
#: entier par Discord, pas afficher une image cassée.
#:
#: La plomberie reste en place et testée. Un écran qui aurait réellement
#: besoin d'un bandeau n'a que cette ligne à changer.
BANDEAUX_ACTIFS = False

#: Icône de chaque domaine. Toute commande appartient à une famille, donc
#: toute réponse peut porter son icône — sans qu'on ait à écrire un emoji
#: dans chaque titre, ni à modifier le moindre cog.
#:
#: C'est ce qui rend l'identité SentriX visible PARTOUT et pas seulement là
#: où quelqu'un avait pensé à mettre un emoji.
ICONES_FAMILLES: dict[str, str] = {
    "moderation": "mod",
    "security": "security",
    "tickets": "ticket",
    "economy": "wallet",
    "levels": "level",
    "music": "voice",
    "games": "games",
    "ai": "ai",
    "config": "settings",
    "welcome": "member_join",
    "goodbye": "member_leave",
    "events": "event",
    "info": "info",
    "success": "success",
    "error": "error",
    "warning": "warning",
    "special": "home",
}

_FAMILY_LABELS = {
    "success": "Succès",
    "error": "Erreur",
    "warning": "Attention",
    "info": "Information",
    "special": "SentriX",
    "events": "Évènements",
    "moderation": "Modération",
    "security": "Sécurité",
    "tickets": "Tickets",
    "economy": "Économie",
    "levels": "Niveaux",
    "music": "Musique",
    "games": "Jeux",
    "ai": "IA",
    "config": "Configuration",
    "welcome": "Bienvenue",
    "goodbye": "Départ",
}

_STATE_LABELS = {
    "success": "Succès",
    "danger": "Erreur",
    "warning": "Attention",
}
_STATE_KINDS = frozenset(_STATE_LABELS)
_LEGACY_BRAND_TITLE_RE = _re.compile(
    r"^(?:sentrix(?:\s+core)?)(?:\s*[—–-]\s*|\s*[•·:]\s*)+",
    _re.IGNORECASE,
)


def titre_core(value: object) -> str:
    """Nettoie seulement la marque héritée répétée dans un titre.

    La marque vit déjà dans la signature SENTRIX CORE. On garde en revanche les
    mots métier et les emojis utiles : le but est d'enlever "SentriX — SentriX —",
    pas de rendre les cartes fades.
    """
    raw = str(value or "").strip()
    previous = None
    while raw and raw != previous:
        previous = raw
        raw = _LEGACY_BRAND_TITLE_RE.sub("", raw).strip()
    return raw or "SentriX"


def _core_family_label(family: str) -> str:
    """Étiquette de domaine, ou chaîne vide s'il n'y en a pas.

    Le défaut était « SentriX », ce qui donnait la signature
    « SENTRIX CORE · SentriX » — le produit nommé deux fois, ce qui se lit
    comme un bug. Sans domaine, la signature se contente de « SENTRIX CORE ».
    """
    brut = str(family or "").strip()
    if not brut:
        return ""
    etiquette = _FAMILY_LABELS.get(brut.casefold(), brut.replace("_", " ").title())
    # Un domaine qui répète le nom du produit n'apporte rien.
    return "" if etiquette.casefold() in {"sentrix", "sentrix core"} else etiquette


def _core_command_name() -> str:
    name, _cog = _commande_en_cours()
    if not name:
        return ""
    try:
        from cogs import common_command_names

        # Le contexte donne le qualified_name interne ; le nom court reste
        # l'interface conseillée, mais le panneau ne dépend jamais de sa présence.
        ctx = None
        try:
            from cogs.final_interaction_policy import _COMMAND_CONTEXT
            ctx = _COMMAND_CONTEXT.get()
        except Exception:
            pass
        command = getattr(ctx, "command", None) if ctx is not None else None
        if command is not None:
            return common_command_names.display_name(command)
    except Exception:
        pass
    return str(name)


def _core_signature(family: str, state_kind: str | None = None) -> str:
    parts = [CORE_NAME, _core_family_label(family)]
    state_label = _STATE_LABELS.get(str(state_kind or "").casefold())
    if state_label and state_label != parts[-1]:
        parts.append(state_label)
    command = _core_command_name()
    if command:
        parts.append(command)
    # Un morceau vide produirait « SENTRIX CORE ·  · profil ».
    return " · ".join(p for p in parts if p)


def _core_footer(
    family: str,
    footer: str | None = None,
    state_kind: str | None = None,
) -> str:
    raw = str(footer or "").strip()
    raw = _re.sub(
        r"^SentriX(?:\s*Core)?(?:\s*[•·:—–-]\s*)+",
        "",
        raw,
        flags=_re.IGNORECASE,
    ).strip()
    if raw.casefold() in {"sentrix", "sentrix core"}:
        raw = ""
    base = _core_signature(family, state_kind)
    return f"{base} · {raw}" if raw else base


def signature_core(family: str, state_kind: str | None = None) -> str:
    """Signature publique du design de commandes SentriX Core."""
    return _core_signature(family, state_kind)


def pied_core(
    family: str,
    footer: str | None = None,
    state_kind: str | None = None,
) -> str:
    """Pied public SentriX Core, en conservant une information métier utile."""
    return _core_footer(family, footer, state_kind)

_LIMITE_LIGNE = 240
_LIMITE_BLOC = 3800


def _texte(valeur: Any, limite: int = _LIMITE_LIGNE) -> str:
    brut = str(valeur if valeur is not None else "").strip()
    # Un emoji Discord custom est un token texte assez long (<:nom:id>).
    # Le couper avec [:N] l'affiche littéralement "à moitié" au lieu de le rendre.
    from utils.sentrix_emojis import tronquer
    return tronquer(brut, limite)


@dataclass
class Ligne:
    """Une donnée : son libellé, sa valeur, et de quoi la lire."""

    label: str
    valeur: Any
    # Un indice s'affiche en petit sous la valeur — pour ce que le chiffre seul ne dit pas.
    indice: str | None = None


@dataclass
class Section:
    """Un bloc du panneau. Chaque section est séparée des autres par un filet.

    ``aligne=True`` rend les lignes dans un bloc de code à chasse fixe : les
    colonnes s'alignent vraiment. À réserver aux données purement numériques —
    dans un bloc de code, une mention ou un horodatage Discord ne s'affiche plus.
    """

    titre: str
    lignes: Sequence[Ligne] = field(default_factory=tuple)
    texte: str | None = None
    aligne: bool = False

    def rendu(self, index: int | None = None) -> str:
        numero = f"{int(index):02d} · " if index is not None else ""
        # Traduction dans l'habillage SEULEMENT : un titre de section est
        # écrit par SentriX, donc on peut y poser nos icônes. Le corps, lui,
        # peut citer le message d'un membre — on n'y touche pas.
        entete = f"### {numero}{_icones(_texte(self.titre, 80))}"
        corps: list[str] = []

        if self.texte:
            corps.append(_texte(self.texte, _LIMITE_BLOC))

        if self.lignes:
            corps.append(_aligne(self.lignes) if self.aligne else _libelle_valeur(self.lignes))

        return "\n".join([entete, *[c for c in corps if c]])


def _libelle_valeur(lignes: Iterable[Ligne]) -> str:
    """Libellé en gras, valeur à droite. Les mentions et horodatages restent vivants."""
    rendu: list[str] = []
    for ligne in lignes:
        valeur = _texte(ligne.valeur) or "—"
        rendu.append(f"**{_texte(ligne.label, 40)}** · {valeur}")
        if ligne.indice:
            rendu.append(f"-# {_texte(ligne.indice, 120)}")
    return "\n".join(rendu)


def _aligne(lignes: Iterable[Ligne]) -> str:
    """Colonnes réellement alignées, via une chasse fixe.

    Discord rend le texte en police proportionnelle : remplir de espaces hors
    d'un bloc de code n'aligne rien. Ce mode est donc le seul qui tienne la
    promesse d'un tableau — au prix des mentions, d'où son usage restreint.
    """
    lignes = list(lignes)
    if not lignes:
        return ""
    largeur = max(len(_texte(l.label, 40)) for l in lignes)
    corps = "\n".join(
        f"{_texte(l.label, 40).ljust(largeur)}   {_texte(l.valeur, 60) or '—'}"
        for l in lignes
    )
    indices = [f"-# {_texte(l.indice, 120)}" for l in lignes if l.indice]
    return "\n".join([f"```\n{corps}\n```", *indices])


@dataclass
class Bouton:
    """Un bouton de navigation ou d'action du panneau.

    Le callback permet aux panneaux Components V2 natifs d'être réellement
    interactifs sans retomber sur un vieux discord.ui.View séparé.
    """

    libelle: str
    custom_id: str | None = None
    url: str | None = None
    style: discord.ButtonStyle = discord.ButtonStyle.secondary
    emoji: str | None = None
    desactive: bool = False
    callback: Any = None


def _commande_en_cours() -> tuple[str, str]:
    """(nom de la commande, nom du cog) de la commande en train de répondre.

    Le contexte est posé par cogs/final_interaction_policy (préfixe et slash) ;
    hors commande — un log automatique, par exemple — on ne renvoie rien et la
    bannière garde la couleur demandée par l'appelant.
    """
    try:
        from cogs.final_interaction_policy import _COMMAND_CONTEXT, _COMMAND_ROOT

        ctx = _COMMAND_CONTEXT.get()
        commande = getattr(ctx, "command", None) if ctx is not None else None
        nom = str(getattr(commande, "qualified_name", "") or _COMMAND_ROOT.get() or "")
        return nom, str(getattr(commande, "cog_name", "") or "")
    except Exception:
        return "", ""


# Commandes dont la réponse EST du texte libre : une réponse de l'IA, une traduction,
# un résumé. Le contenu y tient tout seul et n'a pas de structure à annoncer — un
# bandeau de 1024x110 au-dessus de trois lignes écrites par l'IA n'ajoute rien, il
# éloigne juste la réponse. Ces commandes gardent leur panneau (titre, sections,
# boutons) mais sans bannière.
COMMANDES_TEXTE_LIBRE = frozenset({
    "ai", "ask", "chat", "chat-reset", "sentrix", "summarize", "explain", "rewrite",
    "fact-check", "improve", "correct", "ai-translate", "code", "image-prompt",
    "translate", "aitrad",
})


# Marqueur posé autour de l'envoi d'une réponse en texte libre. Sans lui, la règle
# « pas de bannière » s'appliquait à TOUT ce qui partait pendant la commande — y
# compris la carte « Mission terminée » envoyée juste après par un autre module,
# qui perdait sa bannière alors qu'elle n'a rien de libre.
REPONSE_LIBRE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sentrix_reponse_texte_libre", default=False
)


@contextlib.contextmanager
def reponse_en_texte_libre():
    """Bloc dont les panneaux n'auront pas de bannière (la réponse de l'IA, sa
    traduction, son résumé). Tout ce qui part en dehors garde la sienne."""
    jeton = REPONSE_LIBRE.set(True)
    try:
        yield
    finally:
        REPONSE_LIBRE.reset(jeton)


def commande_en_texte_libre() -> bool:
    """Vrai quand le message en cours d'envoi EST une réponse en texte libre.

    Deux conditions : la commande appartient à la famille texte libre ET on est
    bien dans l'envoi de sa réponse — pas dans une notification déclenchée au
    passage (mission, montée de niveau, avertissement…), qui garde sa bannière.
    """
    if not REPONSE_LIBRE.get():
        return False
    nom, _cog = _commande_en_cours()
    racine = str(nom or "").strip().casefold().lstrip("+/").split(" ")[0]
    return bool(racine) and racine in COMMANDES_TEXTE_LIBRE

def famille_de_la_commande() -> str | None:
    """Famille de bannière qui va avec la commande en cours, ou None."""
    nom, cog = _commande_en_cours()
    if not nom and not cog:
        return None
    return family_for_command(nom, cog)


# Couleur d'accent du conteneur pour une famille de bannière : le liseré Discord et
# la bannière doivent être de la même couleur, sinon le panneau jure avec sa bannière.
ACCENTS_PAR_FAMILLE: dict[str, int] = {
    style: couleur for couleur, style in INTENTIONS.values()
}


def accord_commande(kind: str) -> tuple[int, str]:
    """(couleur d'accent, famille de bannière) pour une intention donnée."""
    accent, style = INTENTIONS.get(kind, INTENTIONS["info"])
    if kind in INTENTIONS_NEUTRES:
        famille = famille_de_la_commande()
        if famille:
            return ACCENTS_PAR_FAMILLE.get(famille, accent), famille
    return accent, style


def nom_banniere(kind: str) -> str:
    """Fichier de bannière correspondant à l'intention, accordé à la commande."""
    return nom_fichier(accord_commande(kind)[1])


def fichier_banniere(kind: str) -> discord.File | None:
    """Bannière prête à joindre pour une intention. ``None`` si la génération a échoué."""
    return fichier_de_famille(accord_commande(kind)[1])


def famille_joignable(famille: str) -> bool:
    """La bannière de cette famille est-elle réellement joignable ?

    Condition UNIQUE que la galerie et la pièce jointe consultent toutes les
    deux. Une galerie qui référence ``attachment://banner_X.webp`` sans que le
    fichier accompagne le message ne « casse » pas l'image — Discord refuse le
    message ENTIER :

        Invalid Form Body — The referenced attachment was not found.

    C'est arrivé en production sur /setup : la commande ne répondait plus du
    tout. Les deux décisions étaient prises à deux endroits sans lien, et
    divergeaient.

    La bannière manquante est GÉNÉRÉE ici. ``.gitignore`` ignore
    ``assets/log_banners/banner_*.webp`` : aucune n'est versionnée, donc le
    dossier est vide sur un conteneur fraîchement déployé. Un simple test
    d'existence aurait servi des écrans sans bandeau.
    """
    # Politique produit globale : un ancien appel explicite ne doit plus
    # pouvoir générer, référencer ou joindre un bandeau décoratif.
    if not BANDEAUX_ACTIFS:
        return False
    chemin = BANNER_DIR / nom_fichier(famille)
    if chemin.exists():
        return True
    try:
        ensure_banners(force=True)
    except Exception:
        logger.exception("Génération des bannières impossible.")
        return False
    return chemin.exists()


def poser_bandeau(container, famille: str) -> bool:
    """Pose le bandeau de CETTE famille en tête de conteneur, ou ne pose rien.

    La famille est passée, jamais re-décidée : ``accord_commande`` consulte le
    contexte de commande en cours, qui est parfois déjà retombé au moment de
    l'envoi. Construire la galerie avec une famille et joindre le fichier
    d'une autre est le second chemin vers le même refus de Discord.

    Rend ``True`` si le bandeau est posé, pour que l'appelant sache quoi
    joindre.
    """
    # Les bandeaux sont retirés de l'interface. On rend False AVANT toute
    # autre chose : c'est ce qui garantit que la pièce jointe disparaît avec
    # la galerie, puisque `pieces_jointes_de_famille` consulte la même
    # condition. Retirer la galerie sans la pièce jointe serait sans effet ;
    # retirer la pièce jointe sans la galerie ferait REFUSER le message entier
    # par Discord.
    #
    # La plomberie est conservée et testée : un écran qui aurait réellement
    # besoin d'un bandeau n'a qu'une ligne à changer.
    if not BANDEAUX_ACTIFS:
        return False
    if not famille_joignable(famille):
        # L'alerte ne vaut que si un bandeau était attendu ; au-dessus,
        # BANDEAUX_ACTIFS a déjà rendu False sans bruit dans le cas normal.
        logger.warning(
            "Bannière %s indisponible : panneau servi sans bandeau plutôt que refusé.",
            famille,
        )
        return False
    galerie = discord.ui.MediaGallery()
    galerie.add_item(media=f"attachment://{nom_fichier(famille)}")
    container.add_item(galerie)
    return True


def pieces_jointes_de_famille(famille: str) -> list:
    """Pièces jointes correspondant au bandeau de CETTE famille.

    Un fichier NEUF à chaque appel : un ``discord.File`` est consommé après un
    envoi et arriverait vide au suivant — donc une pièce jointe absente, donc
    le même refus.
    """
    if not BANDEAUX_ACTIFS or not famille_joignable(famille):
        return []
    fichier = fichier_de_famille(famille)
    return [fichier] if fichier is not None else []


def fichier_de_famille(famille: str) -> discord.File | None:
    """Bannière prête à joindre pour une famille déjà décidée.

    Le panneau décide sa famille à la construction et joint CE fichier-là :
    ré-décider au moment de l'envoi pourrait renvoyer une autre famille (le
    contexte de commande est alors parfois déjà retombé) et la galerie
    référencerait une pièce jointe absente — donc une bannière vide.
    """
    if not BANDEAUX_ACTIFS:
        return None
    nom = nom_fichier(famille)
    chemin = BANNER_DIR / nom
    if not chemin.exists():
        try:
            ensure_banners(force=True)
        except Exception:
            logger.exception("Génération des bannières impossible.")
            return None
    if not chemin.exists():
        return None
    try:
        return discord.File(str(chemin), filename=nom)
    except Exception:
        logger.exception("Bannière %s illisible.", nom)
        return None


class Panneau(discord.ui.LayoutView):
    """Panneau SentriX complet : bannière, titre, sections séparées, boutons."""

    def __init__(
        self,
        *,
        titre: str,
        sous_titre: str | None = None,
        sections: Sequence[Section] = (),
        kind: str = "info",
        vignette: str | None = None,
        boutons: Sequence[Bouton] = (),
        pied: str | None = None,
        # ``None`` = « comme le produit l'a décidé », c'est-à-dire
        # BANDEAUX_ACTIFS. Un défaut écrit en dur ici créerait un SECOND
        # interrupteur : basculer la constante ne changerait rien, puisque le
        # panneau n'appellerait même pas la pose. Un écran peut toujours
        # forcer True ou False explicitement.
        banniere: bool | None = None,
        image: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.kind = kind if kind in INTENTIONS else "info"
        self.titre = titre_core(titre)
        self.sous_titre = str(sous_titre or "") if sous_titre else ""
        self.sections_source = tuple(sections)
        self.boutons_source = tuple(boutons)
        self.pied_source = str(pied or "") if pied else ""
        # Direction produit : aucune bannière décorative, même si un ancien
        # appelant passe encore banniere=True. On garde l'argument uniquement pour
        # compatibilité API, mais le rendu et les pièces jointes restent désactivés.
        self.avec_banniere = False
        banniere = False
        # La bannière/liseré exprime l'ÉTAT (succès, erreur, attention), tandis que
        # la signature conserve le DOMAINE de la commande. Ainsi une réussite
        # économique reste immédiatement identifiable comme Économie, sans perdre
        # son vert de confirmation.
        accent, self.famille = accord_commande(self.kind)
        command_family = famille_de_la_commande()
        self.identite_famille = (
            command_family
            if self.kind in _STATE_KINDS and command_family
            else self.famille
        )
        self.etat_core = self.kind if self.kind in _STATE_KINDS else None

        # Pas d'accent_colour : il dessine un trait vertical coloré sur tout le flanc
        # gauche du message. Le domaine est déjà annoncé par la signature
        # « SENTRIX CORE · … » et par l'icône ; le trait ne fait que répéter en
        # couleur ce que le texte dit déjà, et il casse la sobriété recherchée.
        conteneur = discord.ui.Container()

        # 1 — bannière pleine largeur, en TÊTE. C'est ce qu'un embed ne sait pas faire.
        #     Pas de description= : elle ferait apparaître un badge « ALT » par-dessus.
        #
        # poser_bandeau rend False quand la bannière n'est pas joignable, et
        # avec_banniere devient alors la vérité unique que fichiers() consulte :
        # posé ⇔ joint. Une galerie posée sans sa pièce jointe ne dégrade pas
        # l'image — Discord refuse le message ENTIER, et le panneau ne s'affiche
        # plus du tout. C'est arrivé en production sur /setup.
        if banniere:
            self.avec_banniere = poser_bandeau(conteneur, self.famille)

        # Le panneau commence directement par l'information utile. L'ancienne
        # signature « SENTRIX CORE · domaine · commande » surchargeait le haut
        # de chaque carte et répétait une identité déjà visible via le bot.
        #
        # 2 — titre et sous-titre. La vignette, quand il y en a une, se place à
        #     droite du titre plutôt qu'en médaillon perdu dans un coin.
        # L'icône du domaine en tête, SAUF si le titre en porte déjà une :
        # « 🎫 Ticket #42 » devient une icône de ticket par traduction, en
        # ajouter une seconde ferait doublon.
        titre_rendu = _icones(_texte(self.titre, 200))
        entete = f"## {_icone_de_famille(self.identite_famille, titre_rendu)}"
        if sous_titre:
            entete += f"\n{_texte(sous_titre, 400)}"
        pose = False
        if vignette:
            try:
                conteneur.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(entete),
                        accessory=discord.ui.Thumbnail(str(vignette)),
                    )
                )
                pose = True
            except Exception:
                logger.exception("Vignette de panneau refusée.")
        if not pose:
            conteneur.add_item(discord.ui.TextDisplay(entete))

        # 3 — sections, chacune précédée de son filet.
        #
        # Le numéro n'est posé que s'il y a plusieurs sections à distinguer :
        # un « ### 01 · Résumé » solitaire numérote une liste de un, ce qui
        # n'apporte aucune information et donne au panneau l'air d'un gabarit.
        # Un marqueur numéroté dit « ceci est une séquence » ; il ne doit le
        # dire que quand c'est vrai.
        visibles = [s for s in sections if s.rendu(None)]
        for section in visibles:
            # Pas de « 01 · / 02 · » : le titre de section suffit et rend les
            # panneaux plus naturels, surtout sur mobile.
            rendu = section.rendu(None)
            if not rendu:
                continue
            conteneur.add_item(discord.ui.TextDisplay(rendu[:_LIMITE_BLOC]))

        # 4 — pied de page en petit, comme la signature d'un document.
        if image:
            # Une image de contenu (avatar, banniere de serveur) n'est pas la
            # banniere d'intention : elle porte l'information demandee, donc elle
            # prend toute la largeur sous le texte plutot qu'une vignette d'angle.
            contenu = discord.ui.MediaGallery()
            contenu.add_item(media=str(image))
            conteneur.add_item(contenu)

        # Le pied n'est posé que s'il DIT quelque chose de plus que l'en-tête.
        # Sans texte métier ET sans état, _core_footer rend exactement la
        # signature déjà affichée en tête : le panneau portait alors deux fois
        # la même ligne, en haut et en bas. C'est du bruit, et ça se voit
        # immédiatement. Avec un état ou un texte métier, le pied dit quelque
        # chose de plus et reste posé — les deux améliorations se composent.
        pied_net = str(pied or "").strip()
        pied_net = _re.sub(
            r"^SentriX(?:\s*Core)?(?:\s*[•·:—–-]\s*)+",
            "",
            pied_net,
            flags=_re.IGNORECASE,
        ).strip()
        if pied_net.casefold() in {"sentrix", "sentrix core"}:
            pied_net = ""
        # Le fil SentriX : une action du staff porte sa référence, la même que
        # sur sa carte de log (utils/sentrix_trace.py).
        from utils.sentrix_trace import visible_ref

        reference = visible_ref()
        if reference:
            pied_net = f"{pied_net} · Réf. {reference}" if pied_net else f"Réf. {reference}"
        if pied_net:
            conteneur.add_item(discord.ui.TextDisplay(f"-# {_texte(pied_net, 240)}"))

        # 5 — navigation, DANS le conteneur pour rester sous l'accent de couleur.
        rangees = _rangees(boutons)
        if rangees:
            for rangee in rangees:
                conteneur.add_item(rangee)

        self.add_item(conteneur)

    def fichiers(self) -> list[discord.File]:
        """Pièces jointes à envoyer avec ce panneau.

        ``avec_banniere`` dit si le bandeau a RÉELLEMENT été posé, et la
        famille est celle figée à la construction : les deux côtés ne peuvent
        pas diverger.
        """
        # Les bandeaux décoratifs sont définitivement désactivés : aucune
        # pièce jointe de famille ne doit quitter le bot.
        return []


def _icone_de_famille(famille: str, titre: str) -> str:
    """Pose l'icône du domaine devant le titre, s'il n'en a pas déjà une.

    Deux icônes à la suite se liraient comme une erreur d'affichage, et le
    titre traduit porte déjà la sienne quand l'auteur en avait mis une.
    """
    from utils.sentrix_emojis import emoji as _emoji

    titre = str(titre or "")
    if titre.startswith("<:") or titre.startswith("<a:"):
        return titre
    nom = ICONES_FAMILLES.get(str(famille or ""))
    icone = _emoji(nom) if nom else ""
    # Seulement une VRAIE icône : le repli texte (« ✓ », « … ») devant un
    # titre de panneau serait du bruit, pas de l'identité.
    if not icone.startswith("<"):
        return titre
    return f"{icone} {titre}".strip()


def _icones(texte: str) -> str:
    """Remplace les emojis Unicode de l'HABILLAGE par les icônes SentriX.

    Import tardif : `sentrix_emojis` lit le disque au premier appel, et ce
    module est importé très tôt dans la chaîne de démarrage.
    """
    from utils.sentrix_emojis import traduire

    return traduire(texte)


def _rangees(boutons: Sequence[Bouton]) -> list[discord.ui.ActionRow]:
    """Cinq boutons par rangée, comme Discord l'impose."""
    rangees: list[discord.ui.ActionRow] = []
    lot: list[Bouton] = []
    for bouton in list(boutons)[:25]:
        lot.append(bouton)
        if len(lot) == 5:
            rangees.append(_rangee(lot))
            lot = []
    if lot:
        rangees.append(_rangee(lot))
    return [r for r in rangees if r is not None]


def _rangee(boutons: Sequence[Bouton]) -> discord.ui.ActionRow | None:
    rangee = discord.ui.ActionRow()
    pose = 0
    for bouton in boutons:
        try:
            if bouton.url:
                rangee.add_item(
                    discord.ui.Button(
                        label=_texte(bouton.libelle, 80),
                        url=bouton.url,
                        emoji=bouton.emoji,
                        disabled=bouton.desactive,
                    )
                )
            else:
                item = discord.ui.Button(
                    label=_texte(bouton.libelle, 80),
                    custom_id=bouton.custom_id or f"sentrix:panel:{pose}",
                    style=bouton.style,
                    emoji=bouton.emoji,
                    disabled=bouton.desactive,
                )
                if callable(bouton.callback):
                    item.callback = bouton.callback
                rangee.add_item(item)
            pose += 1
        except Exception:
            logger.exception("Bouton de panneau refusé : %s", bouton.libelle)
    return rangee if pose else None


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------
_MENTIONS_SURES = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)


def _message_envoye(resultat: Any):
    """Ramene toujours un Message, quelle que soit la surface d'envoi.

    ``interaction.response.send_message`` ne renvoie pas un Message mais un
    ``InteractionCallbackResponse``. Cinquante-neuf appels exploitent pourtant
    le retour d'``envoyer`` — ``message.id`` pour enregistrer un panneau de
    roles, ``message.edit`` pour une barre de progression, ``message.delete``
    pour un avertissement temporaire. Toutes ces lignes echouaient des que la
    commande etait lancee en slash plutot qu'en prefixe.

    La reponse porte deja le message dans ``resource`` : aucun appel
    supplementaire a l'API n'est necessaire.
    """
    if isinstance(resultat, discord.InteractionCallbackResponse):
        ressource = getattr(resultat, "resource", None)
        if isinstance(ressource, discord.Message):
            return ressource
        return None
    return resultat


_ERREUR_SIMPLE_RE = _re.compile(
    r"(?:erreur|invalide|introuvable|permission|cooldown|manque|manquant|"
    r"requis|impossible|interdit|refus|indisponible|échou|echou|"
    r"doit être|doit etre|maximum|minim(?:um|ale)|déjà|deja)",
    _re.IGNORECASE,
)


def _panneau_est_erreur_simple(panneau: Any) -> bool:
    if not isinstance(panneau, Panneau):
        return False
    if getattr(panneau, "boutons_source", ()):
        return False
    # Une carte qui fournit une procédure concrète n'est PAS une « erreur simple ».
    # La convertir en texte brut effaçait toute sa section de résolution, exactement
    # comme le refus de hiérarchie de la modération.
    if any(
        str(getattr(section, "titre", "")).casefold().strip() in {
            "comment corriger", "comment résoudre", "solution"
        }
        for section in getattr(panneau, "sections_source", ())
    ):
        return False
    if getattr(panneau, "kind", "") not in {"danger", "warning"}:
        return False
    nom, _ = _commande_en_cours()
    if not nom:
        return False
    texte = " ".join(
        part
        for part in (
            getattr(panneau, "titre", ""),
            getattr(panneau, "sous_titre", ""),
            texte_complet(panneau),
        )
        if part
    )
    return bool(_ERREUR_SIMPLE_RE.search(texte))


def _texte_erreur_depuis_panneau(panneau: Panneau) -> str:
    titre = str(getattr(panneau, "titre", "") or "").strip()
    sous_titre = str(getattr(panneau, "sous_titre", "") or "").strip()

    # Le sous-titre porte presque toujours le vrai message ("La valeur nombre…").
    # On évite les gros titres décoratifs et les sections "Commande / Vous avez tapé".
    texte = sous_titre or titre or "Une erreur est survenue. Merci de réessayer."
    texte = _sans_barre(texte)
    texte = _re.sub(r"\s{2,}", " ", texte).strip()
    return texte[:1900] or "Une erreur est survenue. Merci de réessayer."


async def _envoyer_texte_brut_depuis_panneau(
    destination: Any,
    texte: str,
    *,
    ephemere: bool,
    extra: dict[str, Any],
):
    # Le signal TEXTE_BRUT, comme texte_court : sans lui, la couche des cartes
    # (utils/command_visuals) reconvertissait ce texte en carte titrée du nom de
    # la commande ET perdait le corps — un membre sans assez d'argent recevait un
    # panneau « Pay » vide (mesuré le 09/10/2026).
    jeton = TEXTE_BRUT.set(True)
    try:
        return await _envoyer_texte_brut_sans_signal(destination, texte, ephemere=ephemere, extra=extra)
    finally:
        TEXTE_BRUT.reset(jeton)


async def _envoyer_texte_brut_sans_signal(
    destination: Any,
    texte: str,
    *,
    ephemere: bool,
    extra: dict[str, Any],
):
    kwargs = dict(extra)
    kwargs.pop("file", None)
    kwargs.pop("files", None)
    kwargs.pop("view", None)
    kwargs.pop("embed", None)
    kwargs.pop("embeds", None)
    kwargs["content"] = texte[:1900]
    # Un message d'erreur recopie souvent la saisie (un nom, une commande) : il
    # ne notifie personne. Sans cette ligne, le défaut du bot s'appliquait —
    # « Un modèle nommé « <@&rôle> » existe déjà » faisait sonner un rôle non
    # mentionnable (tools/mention_injection_sweep.py, 08/10/2026).
    kwargs.setdefault("allowed_mentions", _MENTIONS_AUCUNE)

    if isinstance(destination, discord.InteractionResponse):
        if ephemere:
            kwargs["ephemeral"] = True
        if not destination.is_done():
            return _message_envoye(await destination.send_message(**kwargs))
        parent = getattr(destination, "_parent", None)
        if parent is not None:
            return await parent.followup.send(**kwargs)

    interaction = getattr(destination, "interaction", None) or (
        destination if isinstance(destination, discord.Interaction) else None
    )
    if interaction is not None:
        if ephemere:
            kwargs["ephemeral"] = True
        if not interaction.response.is_done():
            return _message_envoye(await interaction.response.send_message(**kwargs))
        if reponse_differee_a_finaliser(interaction):
            try:
                result = await interaction.edit_original_response(
                    content=texte[:1900],
                    embeds=[],
                    view=None,
                    attachments=[],
                    allowed_mentions=kwargs["allowed_mentions"],
                )
                marquer_reponse_differee_finalisee(interaction)
                return result
            except (discord.NotFound, discord.HTTPException):
                logger.debug("Edition texte d'erreur différée impossible.", exc_info=True)
        return await interaction.followup.send(**kwargs)

    if ephemere and isinstance(destination, discord.Webhook):
        kwargs["ephemeral"] = True
    return await destination.send(**kwargs)


async def _completer_par_la_memoire(destination: Any, panneau: Any) -> None:
    """La mémoire SentriX sur un panneau : ajoutée à la ligne « Réf. », au moment de l'envoi.

    Le panneau se construit sans accès à la base ; l'envoi, lui, est asynchrone.
    Même format que texte_court : « -# solde 1 200 🪙 · 2 ajouts du staff en 30 j · Réf. SX-… ».
    """
    from utils import sentrix_trace

    reference = sentrix_trace.visible_ref()
    if not reference:
        return
    parent = getattr(destination, "_parent", None)
    guild = getattr(destination, "guild", None) or getattr(parent, "guild", None)
    bot = getattr(destination, "bot", None) or getattr(destination, "client", None) or getattr(parent, "client", None)
    try:
        ligne = await sentrix_trace.memory_line(bot, guild)
    except Exception:  # noqa: BLE001 — la mémoire ne doit jamais bloquer une réponse
        return
    if not ligne:
        return
    marque = f"Réf. {reference}"

    def parcourir(item: Any) -> bool:
        for enfant in list(getattr(item, "children", []) or []):
            if isinstance(enfant, discord.ui.TextDisplay) and marque in str(enfant.content):
                if ligne not in enfant.content:
                    enfant.content = enfant.content.replace(marque, f"{ligne} · {marque}", 1)
                return True
            if parcourir(enfant):
                return True
        return False

    parcourir(panneau)


async def envoyer(
    destination: Any,
    panneau: Panneau,
    *,
    ephemere: bool = False,
    mentionner: Any = None,
    **extra: Any,
):
    """Envoie un panneau, avec sa bannière, dans le MÊME message.

    ``destination`` peut être un Context, une Interaction ou un salon. Un panneau
    Components V2 ne peut pas cohabiter avec ``embed=`` : c'est la vue qui porte
    tout le contenu, donc rien ne peut se retrouver dans un second message.

    ``mentionner`` autorise nommément une personne à être notifiée. Discord refuse
    un ``content`` sur un message Components V2 — discord.py y pose le drapeau
    ``components_v2`` et l'API renvoie 400 —, donc la mention doit vivre DANS le
    texte du panneau. C'est ``allowed_mentions`` qui décide si elle notifie, et il
    reste fermé sur @everyone et sur les rôles : consulter une fiche ne doit jamais
    pouvoir alerter le serveur entier.
    """
    if _panneau_est_erreur_simple(panneau):
        return await _envoyer_texte_brut_depuis_panneau(
            destination,
            _texte_erreur_depuis_panneau(panneau),
            ephemere=ephemere,
            extra=extra,
        )

    await _completer_par_la_memoire(destination, panneau)

    # Toute vue exposant fichiers() est acceptee, pas seulement Panneau : les
    # panneaux interactifs (aide, setup) sont des LayoutView batis sur mesure.
    fabrique = getattr(panneau, "fichiers", None)
    fichiers = fabrique() if callable(fabrique) else []
    autorisees = _MENTIONS_SURES
    if mentionner is not None:
        autorisees = discord.AllowedMentions(
            users=[mentionner], roles=False, everyone=False, replied_user=False
        )
    kwargs: dict[str, Any] = {"view": panneau, "allowed_mentions": autorisees}
    kwargs.update(extra)

    # Les fichiers de l'appelant (transcription, carte, image generee) et la
    # banniere du panneau doivent COHABITER. Sans cette fusion, `files=` ecrasait
    # la banniere et laissait une galerie pointant vers une piece jointe absente.
    supplements = kwargs.pop("files", None) or []
    unique = kwargs.pop("file", None)
    if unique is not None:
        supplements = [*supplements, unique]
    tous = [*fichiers, *supplements]
    if tous:
        kwargs["files"] = tous

    # Garde-fou : un content glissé ici ferait échouer l'envoi côté Discord, et
    # l'erreur (400 Bad Request) ne dirait pas pourquoi.
    if kwargs.pop("content", None) is not None:
        logger.warning(
            "content ignoré : un message Components V2 n'en accepte pas. "
            "Placez le texte dans une section du panneau."
        )

    # ``interaction.response`` est la surface la plus utilisee dans les
    # callbacks de boutons, et c'est un InteractionResponse : il expose
    # send_message, PAS send. Sans ce cas, chaque appel levait une
    # AttributeError au clic — invisible pour un test d'import.
    if isinstance(destination, discord.InteractionResponse):
        if ephemere:
            kwargs["ephemeral"] = True
        if not destination.is_done():
            return _message_envoye(await destination.send_message(**kwargs))
        # Reponse deja consommee : seul le followup peut encore parler. On passe
        # par l'interaction parente, faute d'accesseur public.
        parent = getattr(destination, "_parent", None)
        if parent is not None:
            if reponse_differee_a_finaliser(parent):
                try:
                    result = await parent.edit_original_response(**kwargs_edition_reponse_differee(kwargs))
                    marquer_reponse_differee_finalisee(parent)
                    return result
                except (discord.NotFound, discord.HTTPException):
                    logger.debug("Edition du panneau différé impossible, repli follow-up.", exc_info=True)
            return await parent.followup.send(**kwargs)
        raise RuntimeError(
            "Reponse d'interaction deja envoyee et followup inaccessible."
        )

    interaction = getattr(destination, "interaction", None) or (
        destination if isinstance(destination, discord.Interaction) else None
    )
    if interaction is not None:
        if ephemere:
            kwargs["ephemeral"] = True
        if not interaction.response.is_done():
            return _message_envoye(await interaction.response.send_message(**kwargs))
        if reponse_differee_a_finaliser(interaction):
            try:
                result = await interaction.edit_original_response(**kwargs_edition_reponse_differee(kwargs))
                marquer_reponse_differee_finalisee(interaction)
                return result
            except (discord.NotFound, discord.HTTPException):
                logger.debug("Edition du panneau différé impossible, repli follow-up.", exc_info=True)
        return await interaction.followup.send(**kwargs)

    # Webhook (interaction.followup), Messageable (ctx, salon, membre).
    if ephemere and "ephemeral" not in kwargs:
        try:
            if isinstance(destination, discord.Webhook):
                kwargs["ephemeral"] = True
        except Exception:
            logger.warning("Étape non critique ignorée dans envoyer", exc_info=True)
    return await destination.send(**kwargs)


_BARRE_DESSINEE = _re.compile(r"[-━─—]{6,}")


def _sans_barre(texte: str) -> str:
    """Retire les barres dessinees : le panneau a de vrais filets."""
    return _BARRE_DESSINEE.sub("", str(texte or "")).strip()


_EMOJI_DE_TETE = _re.compile(
    r"^[\s\u200d\ufe0f]*(?:[\U0001F000-\U0001FAFF\u2190-\u2BFF\u2600-\u27BF]"
    r"[\s\u200d\ufe0f]*)+"
)


def _titre_propre(nom: object) -> str:
    """Titre de section sans emoji de tete.

    Les champs d'embed etaient prefixes d'un emoji pour se distinguer les uns des
    autres — « 👤 Membre », « 📝 Raison ». Dans un panneau, le chevron et le filet
    font deja ce travail : l'emoji ne fait plus qu'ajouter du bruit a un titre en
    capitales. On le retire ici, jamais a la source : l'embed continue d'alimenter
    les journaux, qui gardent leur propre mise en forme.

    Nuance ajoutée avec la bibliothèque d'icônes : un emoji qui a un
    ÉQUIVALENT SentriX est traduit au lieu d'être retiré. Un emoji Unicode
    coloré est du bruit, une icône SentriX monochrome est de l'identité — même
    distinction que sur les boutons. Ce qui n'a pas d'équivalent est toujours
    retiré, donc rien ne redevient bruyant.
    """
    brut = str(nom or "").strip()
    traduit = _icones(brut)
    if traduit != brut:
        return traduit.strip() or "Détail"
    return _EMOJI_DE_TETE.sub("", brut).strip() or "Détail"


_PAR_COULEUR: dict[int, str] = {
    int(_config.COLOR_SUCCESS): "success",
    int(_config.COLOR_ERROR): "danger",
    int(_config.COLOR_WARNING): "warning",
    int(_config.COLOR_INFO): "info",
    int(_config.COLOR_BRAND): "brand",
    int(_config.COLOR_NEUTRAL): "neutral",
}


def intention_de(embed: discord.Embed, defaut: str = "info") -> str:
    """Intention d'un embed deja construit, d'apres sa couleur.

    Les modules qui passent par un constructeur commun choisissent deja leur
    intention appel par appel — succes, avertissement, refus. Elle est encodee
    dans la couleur : la relire evite de la redemander au site d'envoi, et evite
    surtout qu'un « succes » reparte en banniere neutre.
    """
    valeur = getattr(getattr(embed, "colour", None), "value", None)
    return _PAR_COULEUR.get(valeur, defaut)


def _tient_sur_une_ligne(valeur: str) -> bool:
    """Un champ qui rentre dans le budget d'une ``Ligne`` sans jamais être tronqué.

    ``_texte()`` coupe a ``_LIMITE_LIGNE`` (240) caracteres : un champ plus long
    ou multi-lignes irait donc a la trappe si on le forcait quand meme dans le
    mode compact. Il garde alors sa propre section complete — jamais de perte,
    seuls les champs REELLEMENT courts sont regroupes.
    """
    texte = str(valeur or "").strip()
    return bool(texte) and "\n" not in texte and len(texte) <= _LIMITE_LIGNE


#: « <@123>\n`123` » : une mention suivie de son identifiant, telle que
#: ``embeds._who`` la compose. Le saut de ligne la faisait passer pour un champ
#: LONG, donc elle gagnait sa propre section numérotée — et un panneau de
#: sanction affichait le membre deux fois, dont une en identifiant brut sous un
#: titre « 02 · Membre ». L'identifiant reste copiable, sur la même ligne.
_IDENTITE = _re.compile(r"^(<[@#][!&]?\d{15,25}>)\s*\n\s*(`\d{15,25}`)$")


def _identite_compacte(valeur: str) -> str:
    """Remet une identité « mention + identifiant » sur une seule ligne."""
    correspondance = _IDENTITE.match(str(valeur or "").strip())
    if correspondance is None:
        return valeur
    return f"{correspondance.group(1)} {correspondance.group(2)}"


def depuis_embed(
    embed: discord.Embed,
    *,
    kind: str | None = None,
    titre: str | None = None,
    sous_titre: str | None = None,
    pied: str | None = None,
    # Transmis tel quel au Panneau : ``None`` suit le défaut du produit, et un
    # appelant peut demander ou refuser son bandeau explicitement.
    banniere: bool | None = None,
    boutons: Sequence[Bouton] = (),
    compact: bool = True,
) -> Panneau:
    """Convertit un embed deja construit en panneau compose.

    C'est le pont vers le code existant. Beaucoup de reponses SentriX sont
    produites par une CHAINE de modules qui enrichissent un embed — sanctions,
    centre de configuration, panneaux de securite. Porter chaque maillon vers un
    nouveau contrat serait autant d'occasions de casser ce qui marche ; convertir
    le resultat final n'en est aucune.

    Un champ d'embed devient une section : c'est exactement la meme intention,
    rendue avec un filet et un en-tete au lieu d'une colonne.

    ``compact`` (par defaut) regroupe les champs COURTS dans une seule section
    « Résumé », une ligne chacun, au lieu d'un en-tete de section complet par
    champ — un dossier de sanction a sept champs courts (membre, moderateur,
    duree...) qui n'ont pas besoin chacun de leur propre grand titre et de leur
    propre filet. Un champ trop long ou multi-lignes pour tenir sur une ligne
    garde sa section complete, jamais tronquee : le mode compact ne perd jamais
    d'information, il ne fait que grouper ce qui tient deja sur une ligne.
    Passer ``compact=False`` retrouve l'ancien rendu, une section par champ.
    """
    champs = [
        champ for champ in getattr(embed, "fields", ())
        if str(champ.value or "").strip()
    ]
    if compact:
        courtes: list[Ligne] = []
        sections: list[Section] = []
        for champ in champs:
            valeur = _identite_compacte(_sans_barre(champ.value))
            if _tient_sur_une_ligne(valeur):
                courtes.append(Ligne(_titre_propre(champ.name), valeur))
            else:
                sections.append(Section(_titre_propre(champ.name), texte=valeur))
        if courtes:
            sections.insert(0, Section("Résumé", courtes))
    else:
        sections = [Section(_titre_propre(champ.name), texte=_sans_barre(champ.value)) for champ in champs]
    if kind is None:
        kind = intention_de(embed)
    vignette = getattr(getattr(embed, "thumbnail", None), "url", None)
    image_url = getattr(getattr(embed, "image", None), "url", None)
    pied_embed = getattr(getattr(embed, "footer", None), "text", None)
    return Panneau(
        titre=titre_core(titre or str(getattr(embed, "title", "") or "SentriX")),
        sous_titre=sous_titre or _sans_barre(getattr(embed, "description", "")) or None,
        kind=kind,
        vignette=vignette,
        sections=sections,
        boutons=boutons,
        pied=pied or pied_embed or None,
        banniere=False,
        image=image_url if image_url else None,
    )


def texte_complet(panneau: Panneau) -> str:
    """Tout le texte d'un panneau, mis bout a bout.

    Un panneau repartit son contenu entre plusieurs TextDisplay ; verifier qu'il
    « dit » quelque chose demande donc de les recoller. Sert aux tests et aux
    controles de couverture, pas au rendu.
    """
    morceaux: list[str] = []

    def parcourir(items):
        for item in items or ():
            if item.get("type") == 10:
                morceaux.append(str(item.get("content", "")))
            for cle in ("components", "accessory"):
                valeur = item.get(cle)
                if isinstance(valeur, list):
                    parcourir(valeur)
                elif isinstance(valeur, dict):
                    parcourir([valeur])

    parcourir(panneau.to_components())
    return "\n".join(morceaux)


__all__ = [
    "Bouton",
    "CORE_NAME",
    "INTENTIONS",
    "Ligne",
    "Panneau",
    "Section",
    "depuis_embed",
    "intention_de",
    "envoyer",
    "TEXTE_BRUT",
    "texte_court",
    "texte_complet",
    "fichier_banniere",
    "fichier_de_famille",
    "famille_de_la_commande",
    "commande_en_texte_libre",
    "reponse_en_texte_libre",
    "vue_source",
    "vue_panneau",
    "terminer_vue",
    "REPONSE_LIBRE",
    "COMMANDES_TEXTE_LIBRE",
    "nom_banniere",
    "signature_core",
    "pied_core",
    "titre_core",
]


# Référence de secours si une classe discord.ui.Item refuse les attributs dynamiques.
# Le registre est nettoyé dès que la vue se termine ou expire.
_VUES_SOURCE_ITEMS: dict[int, discord.ui.View] = {}


def avec_composants(panneau: Panneau, vue: discord.ui.View) -> Panneau:
    """Reloge les composants d'une View existante DANS un panneau Components V2.

    discord.py ré-associe chaque Item à la LayoutView finale quand il est ajouté dans
    une ActionRow. Les callbacks historiques qui font ``self.view`` voient alors un
    :class:`Panneau` au lieu de leur vue métier et lèvent des AttributeError
    (`_lock`, `winner`, `selected`...). On conserve donc explicitement la vue
    d'origine sur chaque item avant le relogement.

    Le panneau reste la vraie vue Discord envoyée ; la vue source ne sert qu'à porter
    l'état métier et à débloquer les coroutines qui attendent ``view.wait()``.
    """
    enfants = list(getattr(vue, "children", ()) or ())
    if not enfants:
        return panneau

    conteneur = next((c for c in panneau.children if isinstance(c, discord.ui.Container)), None)
    if conteneur is None:
        return panneau

    for item in enfants:
        _VUES_SOURCE_ITEMS[id(item)] = vue
        try:
            item._sentrix_source_view = vue
        except Exception:
            pass

    rangees = _rangees_d_items(enfants)
    if rangees:
        for rangee in rangees:
            conteneur.add_item(rangee)

    panneau._vue_source = vue
    vue._sentrix_panel_view = panneau
    if getattr(vue, "timeout", None) is not None:
        panneau.timeout = vue.timeout

    interaction_check = getattr(vue, "interaction_check", None)
    if interaction_check is not None:
        panneau.interaction_check = interaction_check

    source_error = getattr(vue, "on_error", None)
    if source_error is not None:
        panneau.on_error = source_error

    source_timeout = getattr(vue, "on_timeout", None)

    async def _timeout_bridge():
        try:
            if source_timeout is not None:
                await source_timeout()
        except Exception:
            # Beaucoup d'anciennes View essayaient encore message.edit(view=self) dans
            # on_timeout. Sur un message Components V2 Discord refuse cette conversion ;
            # un timeout ne doit jamais devenir une erreur utilisateur.
            logger.warning("Timeout de la vue source ignoré proprement.", exc_info=True)
        finally:
            # La vue métier n'est pas enregistrée directement dans le ViewStore
            # (seul le Panneau l'est), donc son wait() ne se terminerait jamais
            # sans ce stop explicite.
            try:
                vue.stop()
            except Exception:
                logger.debug("Arrêt de la vue source impossible.", exc_info=True)
            for item in enfants:
                _VUES_SOURCE_ITEMS.pop(id(item), None)

    panneau.on_timeout = _timeout_bridge
    return panneau


def vue_source(item: discord.ui.Item):
    """Retourne la vue métier d'origine d'un composant relogé dans un Panneau."""
    return (
        getattr(item, "_sentrix_source_view", None)
        or _VUES_SOURCE_ITEMS.get(id(item))
        or getattr(item, "view", None)
    )


def vue_panneau(item: discord.ui.Item):
    """Retourne la LayoutView réellement attachée au message Discord."""
    current = getattr(item, "view", None)
    return current if isinstance(current, discord.ui.LayoutView) else getattr(
        vue_source(item), "_sentrix_panel_view", current
    )


def terminer_vue(item: discord.ui.Item) -> None:
    """Arrête à la fois la vue métier et la LayoutView envoyée."""
    source = vue_source(item)
    panel = vue_panneau(item)
    for candidate in (source, panel):
        stop = getattr(candidate, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.debug("Arrêt d'une vue interactive impossible.", exc_info=True)
    for child in list(getattr(source, "children", ()) or ()):
        _VUES_SOURCE_ITEMS.pop(id(child), None)


def _rangees_d_items(items: Sequence[discord.ui.Item]) -> list[discord.ui.ActionRow]:
    """Regroupe des items en rangees Discord valides.

    Discord impose cinq boutons par rangee, et un menu deroulant occupe une
    rangee entiere. Un item qui declare deja sa rangee (``row=``) la garde :
    l'auteur de la vue avait une raison de la fixer.
    """
    rangees: list[discord.ui.ActionRow] = []
    courante: discord.ui.ActionRow | None = None
    places = 0
    derniere_rangee_declaree = None

    for item in items[:25]:
        seul = not isinstance(item, discord.ui.Button)
        declaree = getattr(item, "row", None)
        rupture = (
            courante is None
            or seul
            or places >= 5
            or (declaree is not None and declaree != derniere_rangee_declaree)
        )
        if rupture:
            courante = discord.ui.ActionRow()
            rangees.append(courante)
            places = 0
        derniere_rangee_declaree = declaree
        try:
            # Un item pose dans une ActionRow ne doit plus porter de row= : la
            # rangee lui donne sa position.
            item.row = None
            courante.add_item(item)
            places += 1
        except Exception:
            continue
        if seul:
            places = 5
    return [r for r in rangees if len(r.children)][:5]


async def editer(cible: Any, panneau: Panneau, **extra: Any):
    """Remplace le contenu d'un message DÉJÀ composé.

    Discord pose le drapeau ``components_v2`` à la CRÉATION du message : un
    message né en embed ne deviendra jamais un panneau par édition, et un
    panneau ne redeviendra jamais un embed — l'API renvoie 400. Cette fonction
    ne vaut donc que pour un message né en panneau.

    Elle réattache systématiquement la bannière : un panneau d'une autre
    intention pointe vers un AUTRE nom de fichier, et Discord conserverait
    l'ancienne pièce jointe, laissant une image cassée dans le message.

    ``cible`` accepte les trois surfaces d'édition : ``interaction.response``,
    ``interaction`` et un ``Message``.
    """
    for interdit in ("embed", "embeds", "content"):
        if extra.pop(interdit, None) is not None:
            logger.warning(
                "sentrix_panels.editer : %r ignoré — un message Components V2 "
                "ne peut porter ni embed ni content.",
                interdit,
            )
    extra.pop("attachments", None)
    fichiers = panneau.fichiers() if hasattr(panneau, "fichiers") else []
    charge = {"view": panneau, "attachments": fichiers, **extra}

    for nom in ("edit_message", "edit_original_response", "edit"):
        methode = getattr(cible, nom, None)
        if callable(methode):
            return await methode(**charge)
    raise TypeError(f"{type(cible).__name__} n'expose aucune méthode d'édition.")


_MENTIONS_AUCUNE = discord.AllowedMentions.none()

# Signal lu par les transports qui promeuvent le texte en carte (final_interaction_policy,
# unified_command_panels) : pendant un envoi de texte_court, le texte reste du texte.
TEXTE_BRUT: contextvars.ContextVar[bool] = contextvars.ContextVar("sentrix_texte_brut", default=False)

# Une commande slash peut defer() avant son vrai résultat. Historiquement, le premier
# ctx.send()/panels.envoyer() partait ensuite en follow-up, ce qui laissait la réponse
# différée séparée du vrai résultat. Le préfixe +, lui, n'avait qu'UNE réponse finale.
# Ce registre permet à / d'utiliser le message différé comme réponse finale, une seule fois.
_REPONSES_DIFFEREES_FINALISEES: dict[str, float] = {}


def _cle_interaction(interaction: Any) -> str:
    token = str(getattr(interaction, "token", "") or "")
    if token:
        return token
    return str(getattr(interaction, "id", id(interaction)))


def reponse_differee_a_finaliser(interaction: Any) -> bool:
    if interaction is None:
        return False
    response = getattr(interaction, "response", None)
    if response is None or not bool(response.is_done()):
        return False
    response_type = getattr(response, "type", None)
    deferred_types = {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }
    if response_type not in deferred_types:
        return False
    return _cle_interaction(interaction) not in _REPONSES_DIFFEREES_FINALISEES


def marquer_reponse_differee_finalisee(interaction: Any) -> None:
    import time as _time

    _REPONSES_DIFFEREES_FINALISEES[_cle_interaction(interaction)] = _time.monotonic()
    if len(_REPONSES_DIFFEREES_FINALISEES) > 2048:
        cutoff = _time.monotonic() - 1800
        for key, stamp in list(_REPONSES_DIFFEREES_FINALISEES.items()):
            if stamp < cutoff:
                _REPONSES_DIFFEREES_FINALISEES.pop(key, None)


def kwargs_edition_reponse_differee(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Adapte un payload send()/followup vers edit_original_response()."""
    charge = dict(kwargs)
    charge.pop("ephemeral", None)  # fixé au moment du defer(), non modifiable ensuite
    charge.pop("delete_after", None)
    fichiers = charge.pop("files", None)
    fichier = charge.pop("file", None)
    if fichier is not None:
        fichiers = [*(fichiers or []), fichier]
    if fichiers:
        charge["attachments"] = list(fichiers)
    return charge


async def texte_court(
    destination: Any,
    message: str,
    *,
    ephemere: bool = False,
    supprimer_apres: float | None = None,
    **extra: Any,
):
    """Envoie une confirmation d'UNE ligne, en texte brut, sans bannière ni panneau.

    Une information complexe mérite un panneau ; une petite confirmation
    (« @membre a été banni. », « 15 messages supprimés. ») n'en mérite pas.
    Cette fonction est le pendant minimal de :func:`envoyer` : mêmes surfaces
    acceptées (Context, Interaction, InteractionResponse, salon, membre), même
    prise en charge d'une réponse d'interaction déjà consommée (followup), et
    aucune mention n'est jamais notifiée — la mention reste lisible sans réveiller
    personne.
    """
    texte = str(message)
    # Le fil SentriX : la confirmation d'une action du staff porte sa référence,
    # la même que sur la carte de log (utils/sentrix_trace.py).
    from utils import sentrix_trace

    reference = sentrix_trace.visible_ref()
    if reference and "Réf. SX-" not in texte:
        # La mémoire SentriX : une sanction rappelle ce que le serveur sait déjà
        # du membre visé (sanctions récentes, ancienneté, compte récent).
        contexte = ""
        cible = sentrix_trace.current_target() if sentrix_trace.current_is_moderation() else None
        guild = getattr(destination, "guild", None) or getattr(getattr(destination, "_parent", None), "guild", None)
        bot = getattr(destination, "bot", None) or getattr(destination, "client", None) or getattr(
            getattr(destination, "_parent", None), "client", None,
        )
        try:
            contexte = await sentrix_trace.memory_line(bot, guild)
        except Exception:  # noqa: BLE001 — le contexte ne doit jamais bloquer la réponse
            contexte = ""
        if cible and guild is not None and bot is not None:
            # Les suites : les gestes logiques d'après, en boutons (cogs/trace.py).
            if "view" not in extra:
                try:
                    from cogs import language_runtime

                    english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
                except Exception:  # noqa: BLE001
                    english = False
                suites = sentrix_trace.suites_view(sentrix_trace.current_command() or "", cible, reference,
                                                   english=english)
                if suites is not None:
                    extra = {**extra, "view": suites}
        texte = f"{texte}\n-# {contexte + ' · ' if contexte else ''}Réf. {reference}"
    kwargs: dict[str, Any] = {"content": texte, "allowed_mentions": _MENTIONS_AUCUNE}
    kwargs.update(extra)

    jeton = TEXTE_BRUT.set(True)
    try:
        return await _envoyer_texte(destination, kwargs, ephemere=ephemere, supprimer_apres=supprimer_apres)
    finally:
        TEXTE_BRUT.reset(jeton)


async def _envoyer_texte(destination: Any, kwargs: dict[str, Any], *, ephemere: bool, supprimer_apres: float | None):
    if isinstance(destination, discord.InteractionResponse):
        if ephemere:
            kwargs["ephemeral"] = True
        if not destination.is_done():
            return _message_envoye(await destination.send_message(**kwargs))
        parent = getattr(destination, "_parent", None)
        if parent is None:
            raise RuntimeError("Reponse d'interaction deja envoyee et followup inaccessible.")
        if reponse_differee_a_finaliser(parent):
            try:
                result = await parent.edit_original_response(**kwargs_edition_reponse_differee(kwargs))
                marquer_reponse_differee_finalisee(parent)
                return result
            except (discord.NotFound, discord.HTTPException):
                logger.debug("Edition de la réponse différée impossible, repli follow-up.", exc_info=True)
        return await parent.followup.send(**kwargs)

    interaction = getattr(destination, "interaction", None) or (
        destination if isinstance(destination, discord.Interaction) else None
    )
    if interaction is not None:
        if ephemere:
            kwargs["ephemeral"] = True
        if not interaction.response.is_done():
            return _message_envoye(await interaction.response.send_message(**kwargs))
        if reponse_differee_a_finaliser(interaction):
            try:
                result = await interaction.edit_original_response(**kwargs_edition_reponse_differee(kwargs))
                marquer_reponse_differee_finalisee(interaction)
                return result
            except (discord.NotFound, discord.HTTPException):
                logger.debug("Edition de la réponse différée impossible, repli follow-up.", exc_info=True)
        return await interaction.followup.send(**kwargs)

    # Webhook (followup) ou Messageable (ctx préfixe, salon, membre).
    if ephemere and isinstance(destination, discord.Webhook):
        kwargs["ephemeral"] = True
    if supprimer_apres is not None and not isinstance(destination, discord.Webhook):
        kwargs["delete_after"] = float(supprimer_apres)
    return await destination.send(**kwargs)
