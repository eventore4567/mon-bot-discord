"""Composition des panneaux SentriX : bannière, sections, hiérarchie, boutons.

Ce module ne change pas une couleur, il change la MISE EN PAGE. Un embed classique
ne peut pas afficher de bannière en tête — ``set_image`` la place sous les champs.
Seuls les Components V2 (``LayoutView`` + ``Container`` + ``MediaGallery``)
permettent la composition demandée :

    ┌──────────────────────────────────────────┐
    │  [ BANNIÈRE SENTRIX pleine largeur ]     │
    │  ## Titre du panneau                     │
    │  Sous-titre court                        │
    │  ─────────────────────────────────────   │
    │  ### IDENTITÉ                            │
    │  **Utilisateur** · @User                 │
    │  ─────────────────────────────────────   │
    │  ### ACTIVITÉ                            │
    │  ```  Niveau      42  ```                │
    │  -# SentriX • Informations               │
    │  [ Bouton ] [ Bouton ]                   │
    └──────────────────────────────────────────┘

La structure reprend celle de ``utils/wide_logs.WideLogView``, éprouvée en
production pour les journaux, et en applique deux règles déjà apprises ici :
un ``MediaGallery`` ou un ``Thumbnail`` construit avec ``description=`` fait
afficher un badge « ALT » par-dessus l'image.

Les bannières sont générées au démarrage par ``utils/log_banners`` et jointes au
message (``attachment://``). Elles ne dépendent donc pas du dépôt distant.
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import discord

import config as _config
from utils.log_banners import ensure_banners, nom_fichier, BANNER_DIR

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
    # Etats
    "success": (int(_config.COLOR_SUCCESS), "success"),
    "danger": (int(_config.COLOR_ERROR), "error"),
    "warning": (int(_config.COLOR_WARNING), "warning"),
    "info": (int(_config.COLOR_INFO), "info"),
    "brand": (int(_config.COLOR_BRAND), "special"),
    "neutral": (int(_config.COLOR_NEUTRAL), "info"),
    # Domaines
    "moderation": (0xE8546A, "moderation"),
    "securite": (0x8B7AFF, "security"),
    "economie": (0xF0BE4E, "economy"),
    "configuration": (0x40D0D6, "config"),
}

# Marqueur de section. Discord ne sait pas tracer de filet horizontal dans un
# TextDisplay : le Separator du conteneur s'en charge, et ce chevron donne au
# titre de section une accroche visuelle constante.
CHEVRON = "◢"

_LIMITE_LIGNE = 240
_LIMITE_BLOC = 3800


def _texte(valeur: Any, limite: int = _LIMITE_LIGNE) -> str:
    brut = str(valeur if valeur is not None else "").strip()
    return brut[: limite - 1] + "…" if len(brut) > limite else brut


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

    def rendu(self) -> str:
        entete = f"### {CHEVRON} {_texte(self.titre, 80).upper()}"
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
    """Un bouton de navigation du panneau."""

    libelle: str
    custom_id: str | None = None
    url: str | None = None
    style: discord.ButtonStyle = discord.ButtonStyle.secondary
    emoji: str | None = None
    desactive: bool = False


def nom_banniere(kind: str) -> str:
    """Fichier de bannière correspondant à l'intention."""
    _, style = INTENTIONS.get(kind, INTENTIONS["info"])
    return nom_fichier(style)


def fichier_banniere(kind: str) -> discord.File | None:
    """Bannière prête à joindre. ``None`` si la génération a échoué."""
    nom = nom_banniere(kind)
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
        banniere: bool = True,
        image: str | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.kind = kind if kind in INTENTIONS else "info"
        self.avec_banniere = banniere
        accent, _ = INTENTIONS[self.kind]

        conteneur = discord.ui.Container(accent_colour=discord.Colour(accent))

        # 1 — bannière pleine largeur, en TÊTE. C'est ce qu'un embed ne sait pas faire.
        #     Pas de description= : elle ferait apparaître un badge « ALT » par-dessus.
        if banniere:
            galerie = discord.ui.MediaGallery()
            galerie.add_item(media=f"attachment://{nom_banniere(self.kind)}")
            conteneur.add_item(galerie)

        # 2 — titre et sous-titre. La vignette, quand il y en a une, se place à
        #     droite du titre plutôt qu'en médaillon perdu dans un coin.
        entete = f"## {_texte(titre, 200)}"
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
        for section in sections:
            rendu = section.rendu()
            if not rendu:
                continue
            conteneur.add_item(discord.ui.Separator())
            conteneur.add_item(discord.ui.TextDisplay(rendu[:_LIMITE_BLOC]))

        # 4 — pied de page en petit, comme la signature d'un document.
        if image:
            # Une image de contenu (avatar, banniere de serveur) n'est pas la
            # banniere d'intention : elle porte l'information demandee, donc elle
            # prend toute la largeur sous le texte plutot qu'une vignette d'angle.
            contenu = discord.ui.MediaGallery()
            contenu.add_item(media=str(image))
            conteneur.add_item(discord.ui.Separator())
            conteneur.add_item(contenu)

        if pied:
            conteneur.add_item(discord.ui.TextDisplay(f"-# {_texte(pied, 200)}"))

        # 5 — navigation, DANS le conteneur pour rester sous l'accent de couleur.
        rangees = _rangees(boutons)
        if rangees:
            conteneur.add_item(discord.ui.Separator())
            for rangee in rangees:
                conteneur.add_item(rangee)

        self.add_item(conteneur)

    def fichiers(self) -> list[discord.File]:
        """Pièces jointes à envoyer avec ce panneau."""
        if not self.avec_banniere:
            return []
        fichier = fichier_banniere(self.kind)
        return [fichier] if fichier is not None else []


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
                rangee.add_item(
                    discord.ui.Button(
                        label=_texte(bouton.libelle, 80),
                        custom_id=bouton.custom_id or f"sentrix:panel:{pose}",
                        style=bouton.style,
                        emoji=bouton.emoji,
                        disabled=bouton.desactive,
                    )
                )
            pose += 1
        except Exception:
            logger.exception("Bouton de panneau refusé : %s", bouton.libelle)
    return rangee if pose else None


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------
_MENTIONS_SURES = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)


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
    if fichiers:
        kwargs["files"] = fichiers
    kwargs.update(extra)

    # Garde-fou : un content glissé ici ferait échouer l'envoi côté Discord, et
    # l'erreur (400 Bad Request) ne dirait pas pourquoi.
    if kwargs.pop("content", None) is not None:
        logger.warning(
            "content ignoré : un message Components V2 n'en accepte pas. "
            "Placez le texte dans une section du panneau."
        )

    interaction = getattr(destination, "interaction", None) or (
        destination if isinstance(destination, discord.Interaction) else None
    )
    if interaction is not None:
        if ephemere:
            kwargs["ephemeral"] = True
        if not interaction.response.is_done():
            return await interaction.response.send_message(**kwargs)
        return await interaction.followup.send(**kwargs)

    return await destination.send(**kwargs)


_BARRE_DESSINEE = _re.compile(r"[━─—]{6,}")


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
    """
    return _EMOJI_DE_TETE.sub("", str(nom or "").strip()).strip() or "Détail"


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


def depuis_embed(
    embed: discord.Embed,
    *,
    kind: str | None = None,
    titre: str | None = None,
    sous_titre: str | None = None,
    pied: str | None = None,
    boutons: Sequence[Bouton] = (),
) -> Panneau:
    """Convertit un embed deja construit en panneau compose.

    C'est le pont vers le code existant. Beaucoup de reponses SentriX sont
    produites par une CHAINE de modules qui enrichissent un embed — sanctions,
    centre de configuration, panneaux de securite. Porter chaque maillon vers un
    nouveau contrat serait autant d'occasions de casser ce qui marche ; convertir
    le resultat final n'en est aucune.

    Un champ d'embed devient une section : c'est exactement la meme intention,
    rendue avec un filet et un en-tete au lieu d'une colonne.
    """
    sections = [
        Section(_titre_propre(champ.name), texte=_sans_barre(champ.value))
        for champ in getattr(embed, "fields", ())
        if str(champ.value or "").strip()
    ]
    if kind is None:
        kind = intention_de(embed)
    vignette = getattr(getattr(embed, "thumbnail", None), "url", None)
    pied_embed = getattr(getattr(embed, "footer", None), "text", None)
    return Panneau(
        titre=titre or str(getattr(embed, "title", "") or "SentriX"),
        sous_titre=sous_titre or _sans_barre(getattr(embed, "description", "")) or None,
        kind=kind,
        vignette=vignette,
        sections=sections,
        boutons=boutons,
        pied=pied or pied_embed or "SentriX",
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
    "CHEVRON",
    "INTENTIONS",
    "Ligne",
    "Panneau",
    "Section",
    "depuis_embed",
    "intention_de",
    "envoyer",
    "texte_complet",
    "fichier_banniere",
    "nom_banniere",
]


def avec_composants(panneau: Panneau, vue: discord.ui.View) -> Panneau:
    """Reloge les composants d'une View existante DANS un panneau.

    Une interface interactive (aide, setup, confirmation, panneau de tickets)
    envoyait jusqu'ici un embed et, a cote, une View classique portant ses
    boutons. Un message Components V2 n'accepte pas cette cohabitation : la vue
    EST le message. Reconstruire ces boutons a l'identique reviendrait a
    dupliquer des dizaines de callbacks metier, donc on deplace les items
    existants au lieu de les recreer.

    C'est sur : un item decore par ``@discord.ui.button`` garde une reference a
    la vue qui l'a cree (discord.py lie son callback a cette instance), donc son
    comportement ne change pas en changeant de conteneur. On redirige en plus le
    controle d'interaction et l'expiration vers la vue d'origine, sinon ses
    gardes (« ce bouton n'est pas pour vous », desactivation a l'expiration)
    seraient perdues.
    """
    enfants = list(getattr(vue, "children", ()) or ())
    if not enfants:
        return panneau

    conteneur = next((c for c in panneau.children if isinstance(c, discord.ui.Container)), None)
    if conteneur is None:
        return panneau

    rangees = _rangees_d_items(enfants)
    if rangees:
        conteneur.add_item(discord.ui.Separator())
        for rangee in rangees:
            conteneur.add_item(rangee)

    # La vue d'origine reste responsable de son comportement ; le panneau n'est
    # que le contenant. Sans ces trois renvois, un bouton continuerait de
    # fonctionner mais les gardes de la vue seraient muettes.
    panneau._vue_source = vue
    if getattr(vue, "timeout", None) is not None:
        panneau.timeout = vue.timeout
    for nom in ("interaction_check", "on_timeout", "on_error"):
        methode = getattr(vue, nom, None)
        if methode is not None:
            setattr(panneau, nom, methode)
    return panneau


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
