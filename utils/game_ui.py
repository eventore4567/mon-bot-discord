"""Socle commun des vues de mini-jeux : propriétaire, double-clic, fin de partie.

Ce module ne réinvente rien de ce qui existe déjà. Le côté économique est complet
depuis longtemps et reste la seule autorité :

  - ``game_rewards.reward_game_winner``  — crédit atomique, limite quotidienne,
    référence de transaction, écriture dans ``game_transactions`` (l'historique) ;
  - ``game_rewards.acquire_play_lock``   — une seule manche d'un jeu à la fois ;
  - ``game_rewards.secure_pick`` / ``secure_randint`` — l'aléa, quand de l'argent
    réel en dépend ;
  - ``game_rewards.check_cooldown``      — le délai entre deux parties.

Ce qui manquait était entièrement du côté des composants Discord, et chaque jeu
le réécrivait à sa façon — parfois à moitié :

  - vérifier que celui qui clique est bien le joueur ;
  - refuser le deuxième clic pendant que le premier est traité ;
  - désactiver les boutons à la fin, et à l'expiration ;
  - proposer de rejouer sans retaper la commande ;
  - refuser d'envoyer un bouton sans libellé NI pictogramme.

Ce dernier point n'est pas théorique : « Course à l'emoji » demandait de cliquer
sur 🍒 et envoyait cinq boutons parfaitement vides, parce qu'une couche de style
retirait l'emoji sans savoir qu'il était le jeu. Le jeu était injouable et rien
ne le signalait. ``valider_composants`` refuse désormais ce message avant qu'il
parte.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import discord

logger = logging.getLogger("bot.game-ui")

# Un bouton doit porter au moins l'un des deux. Discord accepte le contraire —
# il affiche un rectangle vide, et le joueur ne sait pas sur quoi il clique.
CHAMPS_VISIBLES = ("label", "emoji")


class BoutonInvisibleError(ValueError):
    """Un composant partirait sans rien d'affichable."""


def valider_composants(vue: discord.ui.View) -> None:
    """Refuse une vue dont un bouton n'a ni libellé ni pictogramme.

    Lève plutôt que de journaliser : un bouton vide rend la manche injouable, et
    un jeu injouable envoyé « en silence avec un avertissement dans les logs »
    est exactement ce qui a échappé à tout le monde pendant des semaines.
    """
    for item in vue.children:
        if not isinstance(item, discord.ui.Button):
            continue
        if item.style is discord.ButtonStyle.link:
            continue
        libelle = str(item.label or "").strip().strip("​").strip()
        if libelle or item.emoji is not None:
            continue
        raise BoutonInvisibleError(
            f"Bouton sans libellé ni pictogramme (custom_id={item.custom_id!r}) : "
            "le joueur verrait un rectangle vide."
        )


def composants_invisibles(vue: discord.ui.View) -> list[str]:
    """Les custom_id des boutons invisibles, sans lever. Pour les audits."""
    try:
        valider_composants(vue)
    except BoutonInvisibleError:
        return [
            str(item.custom_id)
            for item in vue.children
            if isinstance(item, discord.ui.Button)
            and item.style is not discord.ButtonStyle.link
            and not str(item.label or "").strip().strip("​").strip()
            and item.emoji is None
        ]
    return []


class VueDeJeu(discord.ui.View):
    """Vue de mini-jeu : un propriétaire, un clic à la fois, une fin propre.

    ``proprietaire_id`` est le seul membre autorisé à cliquer ; passer ``None``
    ouvre la vue à tout le monde (courses communautaires, drops). Les autres
    reçoivent un message éphémère plutôt qu'un clic ignoré sans explication.
    """

    def __init__(
        self,
        proprietaire_id: int | None,
        *,
        timeout: float | None = 60.0,
        message_intrus: str = "Cette partie appartient à quelqu'un d'autre.",
    ) -> None:
        super().__init__(timeout=timeout)
        self.proprietaire_id = int(proprietaire_id) if proprietaire_id is not None else None
        self.message_intrus = message_intrus
        self.message: discord.Message | None = None
        self.terminee = False
        self.expiree = False
        # Un verrou, pas un simple drapeau : deux clics quasi simultanés peuvent
        # tous deux lire « pas encore terminé » avant que l'un n'ait écrit.
        self._verrou = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.terminee:
            await self._refuser(interaction, "Cette partie est terminée.")
            return False
        if self.proprietaire_id is not None and interaction.user.id != self.proprietaire_id:
            await self._refuser(interaction, self.message_intrus)
            return False
        return True

    @staticmethod
    async def _refuser(interaction: discord.Interaction | None, texte: str) -> None:
        """Explique un refus au joueur, en éphémère, quoi qu'il arrive.

        Deux chemins, parce qu'il y a deux moments. Depuis
        ``interaction_check``, rien n'a encore répondu : on répond. Depuis un
        callback, le bouton a déjà fait ``defer()`` pour pouvoir éditer le
        message — ``is_done()`` est vrai et ``send_message`` lèverait. Il faut
        alors passer par un suivi.

        L'ancienne version ne testait que le premier cas et sortait en silence
        dans le second. Résultat mesuré sur le bot booté : tous les refus
        émis depuis un callback — encaisser sans avoir joué, cliquer pendant
        son délai, accuser après élimination, reprendre la couronne trop tôt —
        ne disaient rien du tout. Le joueur cliquait, et il ne se passait
        rien : exactement l'état que cette méthode existe pour éviter.
        """
        if interaction is None:
            return
        try:
            if interaction.response.is_done():
                await interaction.followup.send(texte, ephemeral=True)
            else:
                await interaction.response.send_message(texte, ephemeral=True)
        except discord.HTTPException:
            logger.debug("Refus d'interaction non délivré.", exc_info=True)

    async def jouer_un_coup(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Exécute un coup, au plus un à la fois. Faux si un coup est en cours.

        Le verrou est pris AVANT toute lecture d'état : c'est la seule façon
        d'empêcher deux clics simultanés de créditer deux fois la même manche.
        """
        if self._verrou.locked():
            return False
        async with self._verrou:
            if self.terminee:
                return False
            await action()
        return True

    def desactiver_tout(self) -> None:
        """Grise tous les composants. À appeler avant la dernière édition."""
        for enfant in self.children:
            if hasattr(enfant, "disabled"):
                enfant.disabled = True

    def terminer(self) -> None:
        """Fin de partie : plus aucun clic n'est accepté, les boutons sont gris."""
        self.terminee = True
        self.desactiver_tout()
        self.stop()

    async def on_timeout(self) -> None:
        """Expiration : la partie se ferme visiblement, jamais en silence.

        Sans cette édition, le joueur garde des boutons actifs qui ne répondent
        plus — le pire état possible, parce que rien ne dit que c'est fini.
        """
        self.expiree = True
        self.terminee = True
        self.desactiver_tout()
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("Vue expirée non mise à jour (message disparu).", exc_info=True)


class VueMisee(VueDeJeu):
    """Vue d'un jeu à mise. Sait dire où en est sa manche, pour n'importe quel jeu.

    Le système de reprise après redémarrage a besoin de savoir si une partie
    était non commencée, engagée ou déjà réglée. Coder cette réponse dans
    ``+bomb`` l'aurait rendue vraie pour lui seul ; chaque jeu suivant aurait
    refait la sienne, et la reprise aurait fini par se tromper sur l'un d'eux.

    Les trois transitions sont donc ici, et un jeu n'a qu'à appeler
    ``engager()`` à sa première action significative.
    """

    def __init__(self, proprietaire_id: int | None, *, game_id: str, db, **kwargs):
        super().__init__(proprietaire_id, **kwargs)
        self.game_id = game_id
        self._db = db
        self.engagee = False
        self.reglee = False

    async def activer(self, message_id: int | None = None) -> None:
        """La partie est à l'écran : un crash ne la dira plus « jamais affichée »."""
        from services import game_stakes

        await game_stakes.marquer_active(self._db, self.game_id, message_id)

    async def engager(self) -> None:
        """Première action significative : la mise n'est plus remboursable.

        Sans ce marqueur, un redémarrage rendrait la mise d'une partie déjà
        mal engagée — un crash, ou un simple déploiement, deviendrait une
        façon gratuite d'annuler une manche qu'on est en train de perdre.
        """
        from services import game_stakes

        if self.engagee:
            return
        self.engagee = True
        await game_stakes.marquer_engagee(self._db, self.game_id)

    async def regler_gain(self, retour_total: int) -> str:
        """Crédite le retour COMPLET : la mise a été débitée à l'ouverture."""
        from services import game_stakes

        statut = await game_stakes.regler_gain(self._db, self.game_id, retour_total)
        self.reglee = statut == "ok"
        return statut

    async def regler_perte(self) -> str:
        from services import game_stakes

        statut = await game_stakes.regler_perte(self._db, self.game_id)
        self.reglee = statut == "ok"
        return statut

    async def regler_expiration(self) -> str:
        """Politique de timeout, identique pour tous les jeux à mise.

        Aucune action jouée : la manche n'a pas commencé, la mise est rendue.
        Au moins une action : la mise est perdue — sinon attendre l'expiration
        serait une façon gratuite d'annuler une partie mal engagée.
        """
        from services import game_stakes

        if self.reglee:
            return "already_settled"
        if self.engagee:
            return await self.regler_perte()
        statut = await game_stakes.rembourser_mise(self._db, self.game_id)
        self.reglee = statut == "ok"
        return statut


class VueSalon(VueDeJeu):
    """Socle des jeux à plusieurs : +race, +detective, +crown.

    Une vue solo refuse tout clic qui n'est pas du propriétaire et laisse
    tomber le second clic simultané. Les deux règles sont fausses ici : la
    table appartient à plusieurs, et deux joueurs qui cliquent en même temps
    doivent être servis tous les deux. Ne rien changer aurait donné un jeu où
    le plus rapide fait perdre son tour au second — un bug invisible en test
    solo, et systématique dès qu'ils sont trois.

    Ce que le socle garantit :
      - inscription et départ volontaires, avec un effectif minimum et maximum ;
      - un seul coup en vol PAR JOUEUR (anti-double-clic), mais les coups de
        joueurs différents sont mis en file, jamais jetés ;
      - un non-inscrit reçoit une explication au lieu d'un clic ignoré ;
      - un départ en cours de partie ne casse pas la manche ;
      - récompense versée une fois, désactivation et expiration propres.
    """

    def __init__(
        self,
        organisateur_id: int,
        *,
        joueurs_min: int = 2,
        joueurs_max: int = 12,
        timeout: float | None = 180.0,
        message_intrus: str = "Rejoignez la partie pour y jouer.",
    ) -> None:
        # proprietaire_id=None : la vue est ouverte, le filtrage se fait sur
        # l'inscription et non sur un propriétaire unique.
        super().__init__(None, timeout=timeout, message_intrus=message_intrus)
        self.organisateur_id = int(organisateur_id)
        self.joueurs_min = max(2, int(joueurs_min))
        self.joueurs_max = max(self.joueurs_min, int(joueurs_max))
        self.participants: dict[int, str] = {}
        self.partis: set[int] = set()
        self.demarree = False
        self.recompense_versee = False
        self._coups_en_vol: set[int] = set()

    # -- inscription --------------------------------------------------------

    @property
    def complet(self) -> bool:
        """Les partis ne gardent pas leur chaise.

        Compter ``participants`` plutôt que ``actifs`` bloquerait une table de
        dix dont trois sont partis : elle refuserait de nouveaux joueurs tout
        en n'en ayant que sept.
        """
        return len(self.actifs) >= self.joueurs_max

    @property
    def assez_de_joueurs(self) -> bool:
        return len(self.actifs) >= self.joueurs_min

    @property
    def actifs(self) -> list[int]:
        """Les inscrits qui n'ont pas quitté, dans l'ordre d'arrivée."""
        return [uid for uid in self.participants if uid not in self.partis]

    def est_inscrit(self, user_id: int) -> bool:
        return int(user_id) in self.participants and int(user_id) not in self.partis

    def joindre(self, user_id: int, nom: str) -> str:
        """« ok », « deja », « complet » ou « commencee »."""
        user_id = int(user_id)
        if self.demarree:
            return "commencee"
        if user_id in self.participants and user_id not in self.partis:
            return "deja"
        if user_id not in self.participants and self.complet:
            return "complet"
        self.participants[user_id] = nom
        self.partis.discard(user_id)
        return "ok"

    def quitter(self, user_id: int) -> str:
        """« ok » ou « absent ». L'inscrit reste connu : son score garde un nom.

        Le supprimer effacerait son pseudo du tableau final, et une ligne
        « <@123> » sans nom est exactement ce qu'un joueur ne comprend pas.
        """
        user_id = int(user_id)
        if user_id not in self.participants or user_id in self.partis:
            return "absent"
        self.partis.add(user_id)
        return "ok"

    def nom(self, user_id: int) -> str:
        return self.participants.get(int(user_id), "Joueur")

    # -- contrôle d'accès ---------------------------------------------------

    #: Suffixes de ``custom_id`` que n'importe qui peut cliquer. Le contrôle se
    #: fait sur l'identifiant parce que discord.py appelle ``interaction_check``
    #: avant de savoir quel composant répondra : l'objet bouton n'est pas encore
    #: connu à cet instant.
    SUFFIXES_OUVERTS = (":rejoindre", ":quitter")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Tout le monde peut s'inscrire ; seuls les inscrits peuvent jouer."""
        if self.terminee:
            await self._refuser(interaction, "Cette partie est terminée.")
            return False
        identifiant = str((getattr(interaction, "data", None) or {}).get("custom_id") or "")
        if identifiant.endswith(self.SUFFIXES_OUVERTS):
            return True
        if not self.est_inscrit(interaction.user.id):
            await self._refuser(interaction, self.message_intrus)
            return False
        return True

    # -- coups --------------------------------------------------------------

    async def jouer_pour(self, user_id: int, action: Callable[[], Awaitable[None]]) -> bool:
        """Un coup par joueur à la fois ; les joueurs différents font la queue.

        ``jouer_un_coup`` jette le second clic simultané — la bonne règle en
        solo, où il s'agit du même doigt sur le même bouton. Ici elle ferait
        disparaître le coup d'un autre joueur, alors on attend le verrou au
        lieu d'abandonner.
        """
        user_id = int(user_id)
        if user_id in self._coups_en_vol:
            return False
        self._coups_en_vol.add(user_id)
        try:
            async with self._verrou:
                if self.terminee:
                    return False
                await action()
        finally:
            self._coups_en_vol.discard(user_id)
        return True

    def marquer_recompense_versee(self) -> bool:
        """Vrai la première fois seulement : une fin atteinte par deux chemins
        (dernier coup et expiration) ne doit pas payer deux fois."""
        if self.recompense_versee:
            return False
        self.recompense_versee = True
        return True


class VuePvE(VueDeJeu):
    """Socle des combats au tour par tour : ``+dragon`` et ``+zombie``.

    La vue ne tient AUCUN point de vie. Les règles vivent dans
    ``utils.pve_engine`` et l'état s'y trouve ; tout ici est délégué. Deux
    compteurs de PV, l'un dans la vue et l'autre dans le moteur, finiraient par
    se contredire au premier correctif appliqué d'un seul côté — et c'est
    l'affichage qui mentirait, donc le joueur qui aurait raison de se plaindre.

    Ce que le socle apporte vraiment : le propriétaire, le verrou d'interaction,
    l'expiration, l'abandon, la désactivation des composants, le rendu des
    barres de vie, le journal des derniers tours et — le seul garde-fou qui
    compte pour l'économie — la récompense versée une fois et une seule.
    """

    def __init__(self, proprietaire_id: int | None, *, etat, tours_journal: int = 3, **kwargs):
        super().__init__(proprietaire_id, **kwargs)
        self.etat = etat
        self.abandonne = False
        self.recompense_versee = False
        self.recompense = None
        self.journal: list[str] = []
        self._tours_journal = max(1, int(tours_journal))

    # -- délégation au moteur ----------------------------------------------

    @property
    def tour(self) -> int:
        return self.etat.tour

    @property
    def combat_fini(self) -> bool:
        """Vrai dès que le moteur conclut, ou que le joueur abandonne."""
        return self.abandonne or self.etat.fini

    def actions_possibles(self) -> list[str]:
        return self.etat.actions_possibles()

    # -- abandon -----------------------------------------------------------

    def abandonner(self) -> None:
        """Quitter proprement : la manche se conclut, sans récompense."""
        self.abandonne = True
        self.terminer()

    # -- récompense --------------------------------------------------------

    def marquer_recompense_versee(self) -> bool:
        """Vrai la PREMIÈRE fois seulement.

        Un combat peut se conclure par deux chemins au même instant — le
        dernier coup tue l'ennemi pendant qu'une expiration se déclenche. Celui
        qui obtient ``False`` ne doit rien payer.
        """
        if self.recompense_versee:
            return False
        self.recompense_versee = True
        return True

    # -- rendu partagé ------------------------------------------------------

    @staticmethod
    def barre(actuels: int, maximum: int, longueur: int = 10) -> str:
        """Barre de vie lisible sur téléphone, sans dépendre de la couleur.

        Un combattant encore debout garde toujours un bloc plein : arrondir un
        point de vie restant à zéro afficherait un mort qui joue encore.
        """
        maximum = max(1, int(maximum))
        actuels = max(0, min(int(actuels), maximum))
        pleins = round(actuels / maximum * longueur)
        if actuels > 0:
            pleins = max(1, pleins)
        pleins = max(0, min(longueur, pleins))
        return "█" * pleins + "░" * (longueur - pleins)

    def noter(self, ligne: str) -> None:
        """Ajoute une ligne au journal, qui ne garde que les derniers tours."""
        self.journal.append(ligne)
        del self.journal[:-self._tours_journal]

    def journal_texte(self) -> str:
        return "\n".join(self.journal)


class VueReflexe(VueDeJeu):
    """Socle des jeux de réflexe : signal, faux départ, mesure monotone.

    Trois jeux partagent exactement cette mécanique — ``+target``, ``+ghost``
    et ``+archery``. La recopier trois fois garantirait qu'un correctif n'en
    atteigne qu'un seul.

    **La mesure passe par ``time.monotonic``, jamais par l'heure système.**
    Un décalage NTP, un changement d'heure ou une horloge qui recule
    produiraient un « record » négatif ou absurde. L'horloge monotone ne
    recule pas, par définition.

    **Un clic avant le signal est un faux départ**, pas une victoire à zéro
    milliseconde : sans ce contrôle, le joueur le plus rapide serait celui qui
    clique au hasard avant même de voir la cible.
    """

    def __init__(self, proprietaire_id: int | None, *, timeout: float | None = 30.0, **kwargs):
        super().__init__(proprietaire_id, timeout=timeout, **kwargs)
        self._signal_a: float | None = None
        self.faux_depart = False
        self.reaction_ms: int | None = None

    def armer(self) -> None:
        """Le signal est donné : le chronomètre part maintenant."""
        self._signal_a = time.monotonic()

    @property
    def arme(self) -> bool:
        return self._signal_a is not None

    def mesurer(self) -> int | None:
        """Millisecondes depuis le signal, ou None si le signal n'a pas eu lieu."""
        if self._signal_a is None:
            return None
        self.reaction_ms = max(0, int((time.monotonic() - self._signal_a) * 1000))
        return self.reaction_ms

    def declarer_faux_depart(self) -> None:
        self.faux_depart = True
        self.terminer()


def positions_melangees(elements: list) -> list:
    """Mélange sûr, pour que la bonne réponse ne soit jamais à la même place.

    Le tirage passe par le RNG partagé des jeux : une position prévisible
    donnerait un avantage à qui l'a remarqué, et ces manches paient.
    """
    from utils.game_rewards import secure_sample

    return secure_sample(elements, len(elements))


class BoutonRejouer(discord.ui.Button):
    """Relance la même commande sans la retaper.

    Réservé au joueur de la manche : sinon n'importe qui relancerait une partie
    au nom de quelqu'un d'autre, en consommant son cooldown.
    """

    def __init__(self, relancer: Callable[[discord.Interaction], Awaitable[None]], *, row: int | None = None):
        super().__init__(label="Rejouer", emoji="🔁", style=discord.ButtonStyle.secondary, row=row)
        self._relancer = relancer

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            await self._relancer(interaction)
        except Exception:
            logger.warning("Impossible de relancer la partie.", exc_info=True)
            await VueDeJeu._refuser(interaction, "Impossible de relancer la partie pour le moment.")


__all__ = [
    "VueDeJeu",
    "VueSalon",
    "VuePvE",
    "VueMisee",
    "VueReflexe",
    "positions_melangees",
    "BoutonRejouer",
    "BoutonInvisibleError",
    "valider_composants",
    "composants_invisibles",
]
