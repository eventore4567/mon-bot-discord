"""Jeux d'arcade SentriX — manches à composants, mise et encaissement.

Ces jeux partagent tous le même socle :

  - ``utils.game_ui.VueDeJeu`` — propriétaire, anti-double-clic, fin propre,
    expiration visible ;
  - ``utils.game_rewards`` — aléa sécurisé, verrou de partie, cooldown persisté,
    crédit atomique avec référence de transaction et limite quotidienne ;
  - ``cogs.games_economy._precheck`` — serveur, +gamesetup, salon, rôle,
    cooldown, verrou. Une seule porte d'entrée, partagée avec les autres cogs.

Rien n'est recopié : l'économie reste la seule autorité pour créditer, et le
socle d'interface la seule autorité pour accepter un clic.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import secrets
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.games_economy import _embed, _finish, _precheck
from services import game_stakes
from services import crafting
from utils import game_rewards, ice_puzzle, stats_service
from utils import party_games as party
from utils import pve_engine as pve
from utils import sentrix_panels as panels
from utils.game_ui import (
    VueDeJeu,
    VueMisee,
    VuePvE,
    VueSalon,
    VueReflexe,
    positions_melangees,
    valider_composants,
)

logger = logging.getLogger("bot.games-arcade")


# =============================================================================
# 💣 BOMB — cases sûres, multiplicateur progressif, encaissement
# =============================================================================

BOMB_CASES = 9          # grille 3x3 : tient sur un écran de téléphone
BOMB_BOMBES = 2         # deux bombes sur neuf cases
BOMB_COOLDOWN = 12
BOMB_MISE_MIN = 10
BOMB_MISE_MAX = 1_500       # ×34,92 en grille parfaite → 52 380 au plus. Avec
                            # 5 000 le gain maximal atteignait 174 600, de quoi
                            # déséquilibrer l'économie d'un serveur en une manche.


def multiplicateur_bomb(ouvertes: int, bombes: int = BOMB_BOMBES, cases: int = BOMB_CASES) -> float:
    """Multiplicateur après ``ouvertes`` cases sûres, arrondi au centième.

    Il suit l'inverse de la probabilité de survie : plus il reste de bombes par
    case fermée, plus la case suivante vaut cher. Une maison prend une petite
    marge — sans elle, l'espérance serait neutre et le jeu ne coûterait jamais
    rien à la banque, ce qui n'est pas tenable pour une économie de serveur.
    """
    sures = cases - bombes
    if ouvertes <= 0:
        return 1.0
    if ouvertes > sures:
        ouvertes = sures
    probabilite = 1.0
    for index in range(ouvertes):
        probabilite *= (sures - index) / (cases - index)
    return round((1 / probabilite) * 0.97, 2)


class _VueBomb(VueDeJeu):
    """Grille de neuf cases. Le joueur ouvre, ou encaisse.

    La grille est tirée AVANT la première ouverture et ne bouge plus : une
    bombe déplacée après un clic rendrait le jeu truqué et invérifiable.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, mise: int, session_id: str):
        super().__init__(ctx.author.id, timeout=120.0,
                         message_intrus="Cette grille appartient à quelqu'un d'autre.")
        self.cog = cog
        self.ctx = ctx
        self.mise = int(mise)
        self.session_id = session_id
        self.ouvertes: list[int] = []
        self.perdu = False
        self.encaisse = False
        self.bombes = set(game_rewards.secure_sample(range(BOMB_CASES), BOMB_BOMBES))

        for index in range(BOMB_CASES):
            self.add_item(_CaseBomb(index, row=index // 3))
        self.add_item(_BoutonEncaisser(row=3))

    # -- état ---------------------------------------------------------------

    @property
    def multiplicateur(self) -> float:
        return multiplicateur_bomb(len(self.ouvertes))

    @property
    def gain(self) -> int:
        return max(0, round(self.mise * self.multiplicateur) - self.mise)

    def grille(self, devoilee: bool = False) -> str:
        cases = []
        for index in range(BOMB_CASES):
            if index in self.ouvertes:
                cases.append("💎")
            elif devoilee and index in self.bombes:
                cases.append("💣")
            elif devoilee:
                cases.append("🟩")
            else:
                cases.append("⬜")
        return "\n".join(" ".join(cases[ligne * 3:ligne * 3 + 3]) for ligne in range(3))

    def texte(self) -> str:
        emoji = self.cog.emoji_monnaie
        if self.perdu:
            return (
                f"{self.grille(devoilee=True)}\n\n"
                f"💥 **Bombe !** Vous perdez votre mise de **{stats_service.format_number(self.mise)}** {emoji}.\n"
                f"-# {len(self.ouvertes)} case(s) ouverte(s) avant l'explosion."
            )
        if self.encaisse:
            return (
                f"{self.grille(devoilee=True)}\n\n"
                f"💰 **Encaissé à ×{self.multiplicateur:g}** — gain de "
                f"**+{stats_service.format_number(self.gain)}** {emoji}."
            )
        prochain = multiplicateur_bomb(len(self.ouvertes) + 1)
        return (
            f"{self.grille()}\n\n"
            f"💣 Deux bombes cachées sur neuf cases. Ouvrez, ou encaissez.\n"
            f"**Mise** {stats_service.format_number(self.mise)} {emoji} · "
            f"**×{self.multiplicateur:g}** maintenant · **×{prochain:g}** à la prochaine case"
        )

    # -- coups --------------------------------------------------------------

    async def ouvrir(self, interaction: discord.Interaction, index: int) -> None:
        if index in self.ouvertes:
            return
        if index in self.bombes:
            self.perdu = True
            await game_stakes.marquer_engagee(self.cog.bot.db, self.session_id)
            # La mise est partie à l'OUVERTURE de la manche : il n'y a plus rien
            # à débiter ici, seulement à clore la réservation. C'est ce qui
            # empêche d'ouvrir trois grilles à 100 avec 100 en poche.
            await game_stakes.regler_perte(self.cog.bot.db, self.session_id)
            await _finish(self.cog.bot, self.ctx, "bomb", self.session_id, "loss", 0)
            self.terminer()
            return await self._rendre(interaction, kind="danger")

        self.ouvertes.append(index)
        # Première action significative : à partir d'ici un redémarrage ne rend
        # plus la mise, sinon un crash annulerait gratuitement une partie mal
        # engagée.
        await game_stakes.marquer_engagee(self.cog.bot.db, self.session_id)
        if len(self.ouvertes) >= BOMB_CASES - BOMB_BOMBES:
            # Grille entièrement nettoyée : encaissement d'office.
            return await self.encaisser(interaction)
        for enfant in self.children:
            if isinstance(enfant, _CaseBomb) and enfant.index == index:
                enfant.disabled = True
                enfant.emoji = "💎"
                enfant.style = discord.ButtonStyle.success
        await self._rendre(interaction)

    async def encaisser(self, interaction: discord.Interaction) -> None:
        if not self.ouvertes:
            return await self._refuser(interaction, "Ouvrez au moins une case avant d'encaisser.")
        self.encaisse = True
        gain = self.gain
        # On crédite le RETOUR COMPLET (mise + profit) : la mise a été débitée à
        # l'ouverture, ne rendre que le profit la confisquerait au gagnant.
        statut = await game_stakes.regler_gain(
            self.cog.bot.db, self.session_id, round(self.mise * self.multiplicateur)
        )
        self.credit_ok = statut == "ok"
        if not self.credit_ok:
            logger.warning(
                "Gain de %s non crédité sur %s (statut=%s).", gain, self.ctx.author.id, statut
            )
        # _finish n'est appelé qu'avec 0 : cooldown, historique et statistiques,
        # jamais un deuxième paiement.
        await _finish(
            self.cog.bot, self.ctx, "bomb", self.session_id, "win", 0,
            metadata={"mise": self.mise, "multiplicateur": self.multiplicateur,
                      "cases": len(self.ouvertes), "gain": gain},
        )
        self.terminer()
        await self._rendre(interaction, kind="success")

    async def _rendre(self, interaction: discord.Interaction, kind: str = "primary") -> None:
        texte = self.texte()
        if self.encaisse and not getattr(self, "credit_ok", True):
            texte += "\n⚠️ Gain non crédité — contactez le staff avec la référence ci-dessus."
        if self.perdu and getattr(self, "mise_non_prelevee", False):
            texte += "\n-# Mise non prélevée : votre solde avait changé entre-temps."
        embed = await _embed(self.cog.bot, self.ctx.guild.id, title="Bombes", description=texte, kind=kind)
        valider_composants(self)
        await panels.editer(self.message, panels.avec_composants(panels.depuis_embed(embed), self))


    async def on_timeout(self) -> None:
        """Comportement défini à l'expiration, jamais un silence.

        Aucune case ouverte : la manche n'a pas commencé, la mise est rendue.
        Des cases ouvertes : le joueur a choisi de ne pas encaisser, la mise
        est perdue — sinon attendre l'expiration serait une façon gratuite
        d'annuler une partie mal engagée.
        """
        if not self.terminee:
            if self.ouvertes:
                await game_stakes.regler_perte(self.cog.bot.db, self.session_id)
            else:
                await game_stakes.rembourser_mise(self.cog.bot.db, self.session_id)
            await _finish(self.cog.bot, self.ctx, "bomb", self.session_id, "loss", 0)
        await super().on_timeout()


class _CaseBomb(discord.ui.Button):
    def __init__(self, index: int, row: int):
        # Un pictogramme, jamais un libellé vide : c'est la case elle-même.
        super().__init__(emoji="⬜", style=discord.ButtonStyle.secondary,
                         row=row, custom_id=f"bomb:{index}")
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueBomb = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.ouvrir(interaction, self.index))


class _BoutonEncaisser(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(label="Encaisser", emoji="💰",
                         style=discord.ButtonStyle.success, row=row, custom_id="bomb:cashout")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueBomb = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.encaisser(interaction))


# --- Constantes du bloc risque/encaissement -------------------------------
# Déclarées avant la classe : Python évalue les valeurs par défaut des
# paramètres au moment où il lit la méthode, pas à l'appel.
LAVA_CASES = 3              # trois dalles par étage
LAVA_LAVE = 1               # une seule brûle
LAVA_ETAGES = 8             # au-delà, le gain deviendrait ingérable
LAVA_COOLDOWN = 12
LAVA_MISE_MIN, LAVA_MISE_MAX = 10, 1_000   # ×24,86 au 8ᵉ étage → 24 860 au plus,
                                           # du même ordre que le plafond de +rocket
RTP_CIBLE = 0.97
ROCKET_COOLDOWN = 15
ROCKET_MISE_MIN, ROCKET_MISE_MAX = 10, 1_000
ROCKET_PLAFOND = 50.0       # borne le gain maximal : 50 × la mise
ROCKET_CROISSANCE = 0.22    # e^(0,22·t) — ×2 vers 3,2 s, ×5 vers 7,3 s
ROCKET_DUREE_MAX = 30.0
SAFE_COOLDOWN = 20
SAFE_ESSAIS = 7
SAFE_DIFFICULTES = {
    "facile": (50, 30),
    "normal": (100, 55),
    "difficile": (200, 110),
}

class GamesArcade(commands.Cog, name="GamesArcade"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.emoji_monnaie = "🪙"

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        """Le symbole monétaire du serveur, lu une fois par manche."""
        if ctx.guild is None:
            return
        try:
            reglages = await self.bot.db.get_stats_settings(ctx.guild.id)
            self.emoji_monnaie = reglages.get("economy_emoji", "🪙")
        except Exception:
            logger.debug("Symbole monétaire illisible, repli sur 🪙.", exc_info=True)
            self.emoji_monnaie = "🪙"

    async def rendre(self, vue, interaction, titre: str, *, kind: str = "primary") -> None:
        """Édite le message de la manche. Partagé par les quatre jeux de réflexe.

        Les composants sont validés avant chaque envoi : une manche qui
        partirait avec un bouton vide serait injouable, et c'est précisément le
        défaut qui avait échappé à tout le monde sur « Course à l'emoji ».
        """
        texte = vue.texte()
        recompense = getattr(vue, "recompense", None)
        if recompense is not None:
            texte += self.ligne_recompense(recompense)
        embed = await _embed(self.bot, vue.ctx.guild.id, title=titre, description=texte, kind=kind)
        valider_composants(vue)
        await panels.editer(vue.message, panels.avec_composants(panels.depuis_embed(embed), vue))

    async def lancer_reflexe(self, ctx, vue, titre: str, jeu: str) -> None:
        """Affiche la manche, laisse un court suspense, puis donne le signal.

        Le signal n'est armé QU'APRÈS l'édition : tout clic avant est un faux
        départ, sinon le plus rapide serait celui qui clique au hasard avant
        même d'avoir vu la cible.
        """
        guild_id = ctx.guild.id
        embed = await _embed(self.bot, guild_id, title=titre, description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue)
        )
        # Délai court et variable : un délai fixe s'anticipe à la milliseconde.
        await asyncio.sleep(game_rewards.secure_randint(8, 18) / 10)
        if vue.terminee:   # faux départ déjà déclaré
            return
        vue.armer()
        embed = await _embed(self.bot, guild_id, title=titre, description=vue.texte())
        await panels.editer(vue.message, panels.avec_composants(panels.depuis_embed(embed), vue))

    def ligne_recompense(self, recompense) -> str:
        if recompense and recompense.success and recompense.amount > 0:
            return (
                f"\n{self.emoji_monnaie} **+{stats_service.format_number(recompense.amount)}** crédités"
                f" · réf. `{recompense.display_id}`"
            )
        if recompense and recompense.reason == "daily_limit":
            return "\n🪙 **0 crédit** — limite quotidienne atteinte. La partie reste jouable."
        return ""

    @commands.hybrid_command(
        name="bomb",
        description="Ouvrez des cases sûres et encaissez avant de tomber sur une bombe.",
        with_app_command=False,
    )
    @app_commands.describe(mise="Ce que vous misez sur cette grille")
    async def bomb(self, ctx: commands.Context, mise: int = BOMB_MISE_MIN):
        """Mines : neuf cases, deux bombes, multiplicateur qui monte."""
        guild_id = ctx.guild.id if ctx.guild else None
        mise = int(mise)
        if not BOMB_MISE_MIN <= mise <= BOMB_MISE_MAX:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes",
                description=(
                    f"La mise doit être comprise entre **{BOMB_MISE_MIN}** et "
                    f"**{stats_service.format_number(BOMB_MISE_MAX)}** {self.emoji_monnaie}."
                ),
                kind="warning",
            )))

        demarre, erreur, _session = await _precheck(self.bot, ctx, "bomb", BOMB_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes", description=erreur, kind="warning")))

        # La mise est RÉSERVÉE avant d'afficher la grille. Deux +bomb 100 lancés
        # à la même milliseconde avec 100 en poche : un seul démarre.
        session_id = game_stakes.nouvel_identifiant("bomb")
        statut = await game_stakes.ouvrir_mise(
            self.bot.db, ctx.guild.id, ctx.author.id, "bomb", mise, session_id
        )
        if statut != "ok":
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "bomb")
            texte = {
                "insufficient": (
                    f"Mise de **{stats_service.format_number(mise)}** {self.emoji_monnaie} impossible : "
                    "votre solde ne la couvre pas."
                ),
                "invalid": "Le montant de la mise est invalide.",
            }.get(statut, "Le casino est momentanément indisponible. Votre argent n'a pas bougé.")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes", description=texte, kind="warning")))

        # À partir d'ici l'argent est engagé : toute panne avant que le joueur
        # puisse cliquer doit le rendre, sinon il paierait une partie qu'il n'a
        # jamais vue.
        try:
            vue = _VueBomb(self, ctx, mise, session_id)
            embed = await _embed(self.bot, guild_id, title="Bombes", description=vue.texte())
            valider_composants(vue)
            vue.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), vue))
            # La grille est à l'écran : un crash ne la traitera plus comme
            # « jamais affichée », mais elle reste remboursable tant que le
            # joueur n'a ouvert aucune case.
            await game_stakes.marquer_active(
                self.bot.db, session_id, getattr(vue.message, "id", None)
            )
        except Exception:
            logger.exception("Grille non affichée : mise remboursée (%s).", session_id)
            await game_stakes.rembourser_mise(self.bot.db, session_id)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "bomb")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes",
                description="La partie n'a pas pu démarrer. Votre mise vous a été rendue.",
                kind="danger")))




    # ---- Commandes des jeux de réflexe et de mémoire ------------------------

    @commands.hybrid_command(
        name="target", description="Cliquez sur la bonne couleur le plus vite possible.",
        with_app_command=False,
    )
    async def target(self, ctx: commands.Context):
        demarre, erreur, session = await _precheck(self.bot, ctx, "target", TARGET_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Cible", description=erreur, kind="warning")))
        await self.lancer_reflexe(ctx, _VueTarget(self, ctx, session), "Cible", "target")

    @commands.hybrid_command(
        name="archery", description="Tirez quand la cible passe au centre.",
        with_app_command=False,
    )
    async def archery(self, ctx: commands.Context):
        demarre, erreur, session = await _precheck(self.bot, ctx, "archery", ARCHERY_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Tir à l'arc", description=erreur, kind="warning")))
        await self.lancer_reflexe(ctx, _VueArchery(self, ctx, session), "Tir à l'arc", "archery")

    @commands.hybrid_command(
        name="ghost", description="Trouvez derrière quelle porte se cache le fantôme.",
        with_app_command=False,
    )
    async def ghost(self, ctx: commands.Context):
        demarre, erreur, session = await _precheck(self.bot, ctx, "ghost", GHOST_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Fantôme", description=erreur, kind="warning")))
        await self.lancer_reflexe(ctx, _VueGhost(self, ctx, session), "Fantôme", "ghost")

    @commands.hybrid_command(
        name="sequence", description="Retrouvez le symbole manquant dans la suite.",
        with_app_command=False,
    )
    @app_commands.describe(longueur="Nombre de symboles (3 à 6) — plus long paie plus")
    async def sequence(self, ctx: commands.Context, longueur: int = 4):
        longueur = max(3, min(int(longueur), len(SEQUENCE_SYMBOLES)))
        demarre, erreur, session = await _precheck(self.bot, ctx, "sequence", SEQUENCE_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Suite", description=erreur, kind="warning")))
        vue = _VueSequence(self, ctx, session, longueur)
        embed = await _embed(self.bot, ctx.guild.id, title="Suite", description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue)
        )

    # ---- Bloc risque / encaissement ----------------------------------------

    async def _ouvrir_manche_misee(self, ctx, jeu: str, titre: str, mise: int,
                                   bornes: tuple[int, int], cooldown: int):
        """Précontrôle, réservation de la mise, identifiant de manche.

        Partagé par tous les jeux à mise : une deuxième implémentation
        économique en parallèle finirait par diverger de celle-ci.
        Retourne (game_id, None) ou (None, réponse déjà envoyée).
        """
        guild_id = ctx.guild.id if ctx.guild else None
        bas, haut = bornes
        if not bas <= mise <= haut:
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title=titre,
                description=(
                    f"La mise doit être comprise entre **{stats_service.format_number(bas)}** "
                    f"et **{stats_service.format_number(haut)}** {self.emoji_monnaie}."
                ),
                kind="warning")))
            return None, True

        demarre, erreur, _s = await _precheck(self.bot, ctx, jeu, cooldown)
        if not demarre:
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title=titre, description=erreur, kind="warning")))
            return None, True

        game_id = game_stakes.nouvel_identifiant(jeu)
        statut = await game_stakes.ouvrir_mise(
            self.bot.db, ctx.guild.id, ctx.author.id, jeu, mise, game_id
        )
        if statut != "ok":
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, jeu)
            texte = {
                "insufficient": "Votre solde ne couvre pas cette mise.",
                "invalid": "Le montant de la mise est invalide.",
            }.get(statut, "Jeu momentanément indisponible. Votre argent n'a pas bougé.")
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title=titre, description=texte, kind="warning")))
            return None, True
        return game_id, None

    @commands.hybrid_command(
        name="lava", description="Montez d'étage en étage et encaissez avant la lave.",
        with_app_command=False,
    )
    @app_commands.describe(mise="Ce que vous engagez sur cette ascension")
    async def lava(self, ctx: commands.Context, mise: int = LAVA_MISE_MIN):
        game_id, arrete = await self._ouvrir_manche_misee(
            ctx, "lava", "Tour de lave", int(mise),
            (LAVA_MISE_MIN, LAVA_MISE_MAX), LAVA_COOLDOWN,
        )
        if arrete:
            return
        try:
            vue = _VueLava(self, ctx, int(mise), game_id)
            embed = await _embed(self.bot, ctx.guild.id, title="Tour de lave", description=vue.texte())
            valider_composants(vue)
            vue.message = await panels.envoyer(
                ctx, panels.avec_composants(panels.depuis_embed(embed), vue))
            await vue.activer(getattr(vue.message, "id", None))
        except Exception:
            logger.exception("Tour de lave non affichée : mise remboursée (%s).", game_id)
            await game_stakes.rembourser_mise(self.bot.db, game_id)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "lava")

    @commands.hybrid_command(
        name="rocket", description="Encaissez avant que la fusée n'explose.",
        with_app_command=False,
    )
    @app_commands.describe(mise="Ce que vous engagez sur ce vol")
    async def rocket(self, ctx: commands.Context, mise: int = ROCKET_MISE_MIN):
        game_id, arrete = await self._ouvrir_manche_misee(
            ctx, "rocket", "Fusée", int(mise),
            (ROCKET_MISE_MIN, ROCKET_MISE_MAX), ROCKET_COOLDOWN,
        )
        if arrete:
            return
        try:
            vue = _VueRocket(self, ctx, int(mise), game_id)
            embed = await _embed(self.bot, ctx.guild.id, title="Fusée", description=vue.texte())
            valider_composants(vue)
            vue.message = await panels.envoyer(
                ctx, panels.avec_composants(panels.depuis_embed(embed), vue))
            await vue.activer(getattr(vue.message, "id", None))
        except Exception:
            logger.exception("Fusée non affichée : mise remboursée (%s).", game_id)
            await game_stakes.rembourser_mise(self.bot.db, game_id)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "rocket")
            return

        vue.demarrer()
        self.bot.loop.create_task(self._suivre_vol(vue))

    async def _suivre_vol(self, vue: "_VueRocket") -> None:
        """Rafraîchit le vol et déclenche l'explosion à l'heure dite.

        Le multiplicateur vient TOUJOURS de l'horloge monotone, jamais d'un
        compteur incrémenté ici : si cette boucle prend du retard — gros
        à-coup de l'event loop, rafraîchissement raté — le joueur n'est ni
        avantagé ni pénalisé, seul l'affichage retarde.
        """
        try:
            while not vue.terminee:
                await asyncio.sleep(0.9)
                if vue.terminee:
                    return
                if vue.multiplicateur_actuel() >= vue.crash:
                    return await vue.jouer_un_coup(lambda: vue.exploser(None))
                try:
                    await self.rendre(vue, None, "Fusée")
                except Exception:
                    logger.debug("Rafraîchissement du vol ignoré.", exc_info=True)
        except Exception:
            logger.warning("Suivi de vol interrompu (%s).", vue.game_id, exc_info=True)

    @commands.hybrid_command(
        name="safe", description="Trouvez le code du coffre avec des indices.",
        with_app_command=False,
    )
    @app_commands.describe(difficulte="facile, normal ou difficile")
    async def safe(self, ctx: commands.Context, difficulte: str = "normal"):
        difficulte = str(difficulte).strip().casefold()
        if difficulte not in SAFE_DIFFICULTES:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None, title="Coffre-fort",
                description="Difficultés disponibles : `facile`, `normal`, `difficile`.",
                kind="warning")))
        demarre, erreur, session = await _precheck(self.bot, ctx, "safe", SAFE_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Coffre-fort", description=erreur, kind="warning")))

        vue = _VueSafe(self, ctx, session, difficulte)
        embed = await _embed(self.bot, ctx.guild.id, title="Coffre-fort", description=vue.texte())
        vue.message = await panels.envoyer(ctx, panels.depuis_embed(embed))

        def du_joueur(message):
            return (
                message.author.id == ctx.author.id
                and message.channel.id == ctx.channel.id
                and message.content.strip().isdigit()
            )

        while not vue.terminee:
            try:
                message = await self.bot.wait_for("message", check=du_joueur, timeout=60)
            except asyncio.TimeoutError:
                await _finish(self.bot, ctx, "safe", session, "loss", 0)
                vue.terminer()
                break
            await vue.jouer_un_coup(
                lambda m=message: vue.proposer(int(m.content.strip()))
            )
            embed = await _embed(
                self.bot, ctx.guild.id, title="Coffre-fort", description=vue.texte(),
                kind="success" if vue.trouve else ("danger" if vue.terminee else "primary"),
            )
            texte = vue.texte()
            recompense = getattr(vue, "recompense", None)
            if recompense is not None:
                texte += self.ligne_recompense(recompense)
                embed = await _embed(self.bot, ctx.guild.id, title="Coffre-fort",
                                     description=texte, kind="success")
            await panels.envoyer(ctx, panels.depuis_embed(embed))

    # ------------------------------------------------------------- bloc PvE

    @commands.hybrid_command(
        name="dragon",
        description="Affrontez un dragon au tour par tour : attaque, parade, soin, déchaînement.",
        with_app_command=False,
    )
    @app_commands.describe(adversaire="dragonnet, feu, glace ou ombre — au hasard si omis")
    async def dragon(self, ctx: commands.Context, adversaire: str | None = None):
        choisi = (adversaire or "").strip().lower()
        if choisi and choisi not in pve.DRAGONS:
            connus = ", ".join(f"`{c}`" for c in pve.DRAGONS)
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None, title="Chasse au dragon",
                description=f"Dragon inconnu. Au choix : {connus}.", kind="warning")))
        demarre, erreur, session = await _precheck(self.bot, ctx, "dragon", DRAGON_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Chasse au dragon", description=erreur, kind="warning")))
        bete = pve.DRAGONS[choisi] if choisi else game_rewards.secure_pick(list(pve.DRAGONS.values()))
        vue = _VueDragon(self, ctx, bete, session)
        embed = await _embed(self.bot, ctx.guild.id, title="Chasse au dragon",
                             description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue))

    @commands.hybrid_command(
        name="zombie",
        description="Tenez six vagues de zombies : munitions comptées, retranchements limités.",
        with_app_command=False,
    )
    async def zombie(self, ctx: commands.Context):
        demarre, erreur, session = await _precheck(self.bot, ctx, "zombie", ZOMBIE_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Nuit des zombies", description=erreur, kind="warning")))
        vue = _VueZombie(self, ctx, session)
        embed = await _embed(self.bot, ctx.guild.id, title="Nuit des zombies",
                             description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue))

    @commands.hybrid_command(
        name="ice",
        description="Le pingouin glisse jusqu'au premier rocher : amenez-le sur le trou.",
        with_app_command=False,
    )
    async def ice(self, ctx: commands.Context):
        demarre, erreur, session = await _precheck(self.bot, ctx, "ice", ICE_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Lac gelé", description=erreur, kind="warning")))
        # Génération sous solveur : une grille sans solution n'est jamais envoyée.
        niveau = ice_puzzle.generer(pve.AleaSecurise())
        if niveau is None:
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "ice")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id, title="Lac gelé",
                description="La glace n'a pas pris ce soir. Réessayez dans un instant.",
                kind="warning")))
        vue = _VueIce(self, ctx, niveau, session)
        embed = await _embed(self.bot, ctx.guild.id, title="Lac gelé", description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue))

    @commands.hybrid_command(
        name="potion",
        description="Récoltez des ingrédients, fabriquez des potions, buvez-les pour un vrai bonus.",
        with_app_command=False,
    )
    async def potion(self, ctx: commands.Context):
        demarre, erreur, session = await _precheck(self.bot, ctx, "potion", POTION_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title="Atelier d'alchimie", description=erreur, kind="warning")))
        stocks = await crafting.stock(self.bot.db, ctx.guild.id, ctx.author.id)
        vue = _VuePotion(self, ctx, stocks, session)
        embed = await _embed(self.bot, ctx.guild.id, title="Atelier d'alchimie",
                             description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue))

    # --------------------------------------------------- bloc multijoueur

    async def _ouvrir_table(self, ctx, jeu: str, titre: str, cooldown: int, fabrique):
        """Précontrôle puis affichage d'un salon. Partagé par les trois tables."""
        demarre, erreur, session = await _precheck(self.bot, ctx, jeu, cooldown)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None,
                title=titre, description=erreur, kind="warning")))
        try:
            vue = fabrique(session)
        except Exception:
            logger.exception("Table %s non ouverte : verrou relâché.", jeu)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, jeu)
            raise
        embed = await _embed(self.bot, ctx.guild.id, title=titre, description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), vue))
        return vue

    @commands.hybrid_command(
        name="race",
        description="Course à plusieurs : avancer sûrement ou sprinter et risquer de caler.",
        with_app_command=False,
    )
    async def race(self, ctx: commands.Context):
        await self._ouvrir_table(
            ctx, "race", "Course d'obstacles", RACE_COOLDOWN,
            lambda session: _VueRace(self, ctx, session))

    @commands.hybrid_command(
        name="detective",
        description="Enquête à plusieurs : accusez tôt pour gagner plus, trompez-vous et sortez.",
        with_app_command=False,
    )
    async def detective(self, ctx: commands.Context):
        enquete = party.generer_enquete(pve.AleaSecurise())
        if enquete is None:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, ctx.guild.id if ctx.guild else None, title="Enquête",
                description="Aucun dossier exploitable ce soir. Réessayez dans un instant.",
                kind="warning")))
        await self._ouvrir_table(
            ctx, "detective", "Enquête", DETECTIVE_COOLDOWN,
            lambda session: _VueDetective(self, ctx, enquete, session))

    @commands.hybrid_command(
        name="crown",
        description="Roi de la colline : gardez la couronne jusqu'à un instant tenu secret.",
        with_app_command=False,
    )
    async def crown(self, ctx: commands.Context):
        await self._ouvrir_table(
            ctx, "crown", "Roi de la colline", CROWN_COOLDOWN,
            lambda session: _VueCrown(self, ctx, session))


# =============================================================================
# 🎯 TARGET — cliquer la bonne couleur, le plus vite possible
# =============================================================================

TARGET_COULEURS = ("🔴", "🟢", "🔵", "🟡", "🟣")
TARGET_COOLDOWN = 8
TARGET_BASE = 18


class _VueTarget(VueReflexe):
    """Cinq couleurs, une annoncée. La cible est présente EXACTEMENT une fois.

    Un doublon rendrait la manche ambiguë : deux boutons corrects, un seul
    accepté, et le joueur ne comprendrait pas pourquoi il a perdu.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, session_id: str):
        super().__init__(ctx.author.id, timeout=20.0,
                         message_intrus="Cette cible appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        # Les cinq couleurs sont distinctes et mélangées : la cible n'est donc
        # ni dupliquée, ni toujours à la même place.
        self.choix = positions_melangees(list(TARGET_COULEURS))
        self.cible = game_rewards.secure_pick(self.choix)
        self.gagne = False
        for position, couleur in enumerate(self.choix):
            self.add_item(_BoutonTarget(position, couleur))

    def texte(self) -> str:
        if self.faux_depart:
            return "🚫 **Faux départ !** Vous avez cliqué avant le signal."
        if not self.arme:
            return "🎯 Préparez-vous… la cible arrive."
        if self.gagne:
            return (
                f"🎯 **Touché en {self.reaction_ms} ms !**\n"
                f"La cible était {self.cible}."
            )
        if self.terminee:
            return f"○ Raté. La cible était {self.cible}."
        return f"🎯 Cliquez sur **{self.cible}** — le plus vite possible !"

    async def tirer(self, interaction: discord.Interaction, position: int) -> None:
        if not self.arme:
            self.declarer_faux_depart()
            await _finish(self.cog.bot, self.ctx, "target", self.session_id, "loss", 0)
            return await self.cog.rendre(self, interaction, "Cible", kind="danger")

        self.mesurer()
        self.gagne = self.choix[position] == self.cible
        if self.gagne:
            # Plus c'est rapide, plus ça paie — plafonné pour qu'un macro ne
            # rapporte pas dix fois un humain attentif.
            bonus = max(0, 12 - self.reaction_ms // 100)
            self.recompense = await _finish(
                self.cog.bot, self.ctx, "target", self.session_id, "win", TARGET_BASE + bonus,
                metadata={"reaction_ms": self.reaction_ms},
            )
        else:
            await _finish(self.cog.bot, self.ctx, "target", self.session_id, "loss", 0)
        self.terminer()
        await self.cog.rendre(self, interaction, "Cible", kind="success" if self.gagne else "danger")


class _BoutonTarget(discord.ui.Button):
    def __init__(self, position: int, couleur: str):
        # custom_id positionnel : il ne dit pas laquelle est la bonne.
        super().__init__(emoji=couleur, style=discord.ButtonStyle.secondary,
                         custom_id=f"target:{position}")
        self.position = position

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueTarget = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.tirer(interaction, self.position))


# =============================================================================
# 🏹 ARCHERY — fenêtre de précision, pas course à la latence
# =============================================================================

ARCHERY_COOLDOWN = 10
ARCHERY_PERIODE_MS = 2400          # un aller-retour complet de la cible
ARCHERY_ZONES = (
    (0.10, "🎯", "Parfait", 3.0),
    (0.25, "✨", "Excellent", 2.0),
    (0.45, "👍", "Bon", 1.0),
    (1.00, "○", "Raté", 0.0),
)
ARCHERY_BASE = 20


def zone_archery(ecart: float) -> tuple[str, str, float]:
    """Zone touchée pour un écart au centre entre 0 et 1."""
    for limite, emoji, libelle, facteur in ARCHERY_ZONES:
        if ecart <= limite:
            return emoji, libelle, facteur
    return ARCHERY_ZONES[-1][1], ARCHERY_ZONES[-1][2], ARCHERY_ZONES[-1][3]


class _VueArchery(VueReflexe):
    """La cible oscille selon une trajectoire fixée AVANT la manche.

    Le score ne dépend pas de la latence réseau mais de l'instant choisi : la
    période est lente (2,4 s pour un aller-retour) et les zones sont larges,
    si bien que ±100 ms de réseau décalent à peine le résultat. Un jeu où
    seule la connexion compte ne serait pas un jeu d'adresse.

    La phase est tirée au départ et stockée côté serveur : elle n'apparaît
    jamais dans un custom_id, donc la position gagnante n'est pas devinable.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, session_id: str):
        super().__init__(ctx.author.id, timeout=25.0,
                         message_intrus="Cet arc appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.phase_ms = game_rewards.secure_randint(0, ARCHERY_PERIODE_MS - 1)
        self.ecart: float | None = None
        self.add_item(_BoutonTirer())

    def position_cible(self, instant_ms: int) -> float:
        """Écart au centre (0 = plein centre, 1 = bord), déterministe."""
        avance = (instant_ms + self.phase_ms) % ARCHERY_PERIODE_MS
        demi = ARCHERY_PERIODE_MS / 2
        # Triangle : la cible va d'un bord à l'autre et revient.
        return abs(avance - demi) / demi

    def texte(self) -> str:
        if self.faux_depart:
            return "🚫 **Faux départ !** Vous avez tiré avant que la cible bouge."
        if not self.arme:
            return "🏹 Encochez… la cible se met en place."
        if self.ecart is None:
            return (
                "🏹 La cible oscille. Tirez quand vous la jugez au centre.\n"
                "-# 🎯 Parfait · ✨ Excellent · 👍 Bon · ○ Raté"
            )
        emoji, libelle, _facteur = zone_archery(self.ecart)
        return (
            f"{emoji} **{libelle}** — écart de {round(self.ecart * 100)} % au centre.\n"
            f"-# Tir à {self.reaction_ms} ms."
        )

    async def tirer(self, interaction: discord.Interaction) -> None:
        if not self.arme:
            self.declarer_faux_depart()
            await _finish(self.cog.bot, self.ctx, "archery", self.session_id, "loss", 0)
            return await self.cog.rendre(self, interaction, "Tir à l'arc", kind="danger")

        self.mesurer()
        self.ecart = self.position_cible(self.reaction_ms)
        _emoji, libelle, facteur = zone_archery(self.ecart)
        gagne = facteur > 0
        self.recompense = await _finish(
            self.cog.bot, self.ctx, "archery", self.session_id,
            "win" if gagne else "loss", round(ARCHERY_BASE * facteur),
            metadata={"zone": libelle, "ecart": round(self.ecart, 3)},
        )
        self.terminer()
        await self.cog.rendre(self, interaction, "Tir à l'arc",
                              kind="success" if gagne else "danger")


class _BoutonTirer(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Tirer", emoji="🏹",
                         style=discord.ButtonStyle.primary, custom_id="archery:shoot")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueArchery = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.tirer(interaction))


# =============================================================================
# 👻 GHOST — quatre portes, une seule cache le fantôme
# =============================================================================

GHOST_PORTES = 4
GHOST_COOLDOWN = 9
GHOST_BASE = 22


class _VueGhost(VueReflexe):
    """La bonne porte vit UNIQUEMENT côté serveur.

    Les custom_id sont positionnels (``ghost:0``…) : rien dans le payload ne
    dit où est le fantôme. Un identifiant du genre ``ghost:winning`` se lirait
    dans les outils de développement du client.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, session_id: str):
        super().__init__(ctx.author.id, timeout=20.0,
                         message_intrus="Ces portes appartiennent à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.bonne_porte = game_rewards.secure_randint(0, GHOST_PORTES - 1)
        self.choisie: int | None = None
        for index in range(GHOST_PORTES):
            self.add_item(_BoutonPorte(index))

    def texte(self) -> str:
        if self.faux_depart:
            return "🚫 **Faux départ !** Vous avez ouvert avant le signal."
        if not self.arme:
            return "👻 Le fantôme se cache…"
        if self.choisie is None:
            return "🚪 Derrière quelle porte se cache le fantôme 👻 ? Vite !"
        gagne = self.choisie == self.bonne_porte
        portes = " ".join(
            "👻" if i == self.bonne_porte else "🚪" for i in range(GHOST_PORTES)
        )
        return (
            f"{portes}\n\n"
            + (f"👻 **Trouvé en {self.reaction_ms} ms !**" if gagne
               else f"○ Raté — il était derrière la porte **{self.bonne_porte + 1}**.")
        )

    async def ouvrir(self, interaction: discord.Interaction, index: int) -> None:
        if not self.arme:
            self.declarer_faux_depart()
            await _finish(self.cog.bot, self.ctx, "ghost", self.session_id, "loss", 0)
            return await self.cog.rendre(self, interaction, "Fantôme", kind="danger")

        self.mesurer()
        self.choisie = index
        gagne = index == self.bonne_porte
        self.recompense = await _finish(
            self.cog.bot, self.ctx, "ghost", self.session_id,
            "win" if gagne else "loss", GHOST_BASE if gagne else 0,
            metadata={"reaction_ms": self.reaction_ms},
        )
        self.terminer()
        await self.cog.rendre(self, interaction, "Fantôme",
                              kind="success" if gagne else "danger")


class _BoutonPorte(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(label=str(index + 1), emoji="🚪",
                         style=discord.ButtonStyle.secondary, custom_id=f"ghost:{index}")
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueGhost = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.ouvrir(interaction, self.index))


# =============================================================================
# 🧩 SEQUENCE — retrouver l'élément manquant
# =============================================================================

SEQUENCE_SYMBOLES = ("🔴", "🔵", "🟢", "🟡", "🟠", "🟣")
SEQUENCE_COOLDOWN = 10
SEQUENCE_BASE = 16


class _VueSequence(VueDeJeu):
    """Une suite est montrée, un élément retiré : lequel manquait ?

    La séquence vit UNIQUEMENT côté serveur et n'apparaît dans aucun
    custom_id — ceux-ci sont positionnels. Les symboles d'une manche sont
    tous distincts : avec des répétitions, « l'élément manquant » deviendrait
    ambigu dès qu'il apparaît deux fois.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, session_id: str, longueur: int):
        super().__init__(ctx.author.id, timeout=30.0,
                         message_intrus="Cette suite appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.longueur = longueur
        self.suite = game_rewards.secure_sample(list(SEQUENCE_SYMBOLES), longueur)
        self.manquant = game_rewards.secure_pick(self.suite)
        self.affichee = [s for s in self.suite if s != self.manquant]
        self.reponse: str | None = None
        # Les propositions sont mélangées : la bonne n'est jamais à la même place.
        for position, symbole in enumerate(positions_melangees(list(self.suite))):
            self.add_item(_BoutonSequence(position, symbole))

    def texte(self) -> str:
        if self.reponse is None:
            return (
                f"🧩 La suite complète comptait **{self.longueur}** symboles :\n"
                f"## {' '.join(self.affichee)}\n\n"
                "Lequel manque ?"
            )
        gagne = self.reponse == self.manquant
        return (
            f"## {' '.join(self.suite)}\n\n"
            + (f"🧩 **Exact !** Il manquait {self.manquant}." if gagne
               else f"○ Non — il manquait {self.manquant}, pas {self.reponse}.")
        )

    async def repondre(self, interaction: discord.Interaction, symbole: str) -> None:
        self.reponse = symbole
        gagne = symbole == self.manquant
        self.recompense = await _finish(
            self.cog.bot, self.ctx, "sequence", self.session_id,
            "win" if gagne else "loss",
            SEQUENCE_BASE + (self.longueur - 3) * 6 if gagne else 0,
            metadata={"longueur": self.longueur},
        )
        self.terminer()
        await self.cog.rendre(self, interaction, "Suite",
                              kind="success" if gagne else "danger")


class _BoutonSequence(discord.ui.Button):
    def __init__(self, position: int, symbole: str):
        # Le symbole est affiché, mais le custom_id reste positionnel : la
        # réponse ne se lit pas dans le payload.
        super().__init__(emoji=symbole, style=discord.ButtonStyle.secondary,
                         custom_id=f"sequence:{position}")
        self.symbole = symbole

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueSequence = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.repondre(interaction, self.symbole))


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesArcade(bot))


# =============================================================================
# 🌋 LAVA — monter d'étage en étage, encaisser avant la coulée
# =============================================================================



def multiplicateur_lava(etages: int) -> float:
    """Multiplicateur après ``etages`` dalles franchies.

    Calculé — pas choisi au jugé : il vaut ``RTP / survie^étages``, si bien que
    l'espérance est la MÊME à tous les étages. Sans cette construction, un
    palier paierait mieux que les autres et tout le monde s'arrêterait là.
    """
    if etages <= 0:
        return 1.0
    survie = (LAVA_CASES - LAVA_LAVE) / LAVA_CASES
    return round(RTP_CIBLE / (survie ** min(etages, LAVA_ETAGES)), 2)


class _VueLava(VueMisee):
    """Une coulée par étage, tirée AVANT le premier pas.

    Toute la carte est décidée à la création : déplacer la lave après un choix
    rendrait le jeu truqué, et invérifiable. Les custom_id sont positionnels —
    rien dans le payload ne dit quelle dalle brûle.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, mise: int, game_id: str):
        super().__init__(ctx.author.id, game_id=game_id, db=cog.bot.db, timeout=150.0,
                         message_intrus="Cette tour appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.mise = cog, ctx, int(mise)
        # Une position de lave par étage, fixée d'avance.
        self.laves = [
            game_rewards.secure_randint(0, LAVA_CASES - 1) for _ in range(LAVA_ETAGES)
        ]
        self.etage = 0
        self.brule = False
        self.encaisse = False
        for position in range(LAVA_CASES):
            self.add_item(_DalleLava(position))
        self.add_item(_BoutonEncaisserLava())

    @property
    def multiplicateur(self) -> float:
        return multiplicateur_lava(self.etage)

    @property
    def retour(self) -> int:
        """Retour total, arrondi à l'entier — on ne paie pas des centièmes.

        L'arrondi est fait UNE fois, sur le produit final : arrondir le
        multiplicateur puis multiplier accumulerait l'erreur étage après étage.
        """
        return int(round(self.mise * self.multiplicateur))

    def texte(self) -> str:
        emoji = self.cog.emoji_monnaie
        if self.brule:
            return (
                f"🌋 **La dalle cède !** Vous tombez à l'étage {self.etage + 1}.\n"
                f"Mise perdue : **{stats_service.format_number(self.mise)}** {emoji}."
            )
        if self.encaisse:
            return (
                f"💰 **Encaissé au {self.etage}ᵉ étage, ×{self.multiplicateur:g}**\n"
                f"Retour : **{stats_service.format_number(self.retour)}** {emoji} "
                f"(profit **+{stats_service.format_number(self.retour - self.mise)}**)."
            )
        tour = "🟩" * self.etage
        prochain = multiplicateur_lava(self.etage + 1)
        return (
            f"{tour or '·'}\n\n"
            f"🌋 Étage **{self.etage + 1}/{LAVA_ETAGES}** — trois dalles, une brûle.\n"
            f"**Mise** {stats_service.format_number(self.mise)} {emoji} · "
            f"**×{self.multiplicateur:g}** acquis · **×{prochain:g}** à l'étage suivant"
        )

    async def avancer(self, interaction: discord.Interaction, position: int) -> None:
        await self.engager()
        if position == self.laves[self.etage]:
            self.brule = True
            await self.regler_perte()
            await _finish(self.cog.bot, self.ctx, "lava", self.game_id, "loss", 0)
            self.terminer()
            return await self.cog.rendre(self, interaction, "Tour de lave", kind="danger")

        self.etage += 1
        if self.etage >= LAVA_ETAGES:
            return await self.encaisser(interaction)
        await self.cog.rendre(self, interaction, "Tour de lave")

    async def encaisser(self, interaction: discord.Interaction) -> None:
        if self.etage <= 0:
            return await self._refuser(interaction, "Franchissez au moins une dalle avant d'encaisser.")
        self.encaisse = True
        await self.regler_gain(self.retour)
        await _finish(
            self.cog.bot, self.ctx, "lava", self.game_id, "win", 0,
            metadata={"mise": self.mise, "etages": self.etage,
                      "multiplicateur": self.multiplicateur, "retour": self.retour},
        )
        self.terminer()
        await self.cog.rendre(self, interaction, "Tour de lave", kind="success")

    async def on_timeout(self) -> None:
        if not self.terminee:
            await self.regler_expiration()
            await _finish(self.cog.bot, self.ctx, "lava", self.game_id, "loss", 0)
        await super().on_timeout()


class _DalleLava(discord.ui.Button):
    def __init__(self, position: int):
        super().__init__(emoji="🟫", label=str(position + 1),
                         style=discord.ButtonStyle.secondary, custom_id=f"lava:{position}")
        self.position = position

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueLava = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.avancer(interaction, self.position))


class _BoutonEncaisserLava(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Encaisser", emoji="💰",
                         style=discord.ButtonStyle.success, custom_id="lava:cashout")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueLava = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.encaisser(interaction))


# =============================================================================
# 🚀 ROCKET — le multiplicateur monte, encaissez avant l'explosion
# =============================================================================



def multiplicateur_rocket(secondes: float) -> float:
    """Multiplicateur après ``secondes`` de vol, arrondi au centième.

    Dérivé du temps écoulé mesuré à l'horloge monotone, jamais d'un compteur
    incrémenté dans une boucle : une boucle qui prend du retard fausserait le
    multiplicateur, et un gros à-coup de l'event loop ferait gagner ou perdre
    le joueur pour une raison qui n'est pas le jeu.
    """
    if secondes <= 0:
        return 1.0
    return min(ROCKET_PLAFOND, round(math.exp(ROCKET_CROISSANCE * secondes), 2))


def tirer_point_de_crash(seed: str) -> float:
    """Point d'explosion, dérivé du seed. Déterministe et vérifiable.

    ``crash = RTP / (1 − u)`` donne une espérance constante quelle que soit la
    cible visée : encaisser à ×1,2 ou à ×20 rapporte le même 97 % à long
    terme, donc aucune stratégie ne domine. Le plafond borne le gain sans rien
    changer en dessous de lui.

    Le seed est tiré AVANT la manche et conservé dans l'historique : le point
    de crash se recalcule après coup, ce qui permet de vérifier qu'il n'a pas
    bougé selon la mise, le solde ou le moment du clic.
    """
    brut = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:13], 16)
    u = brut / float(1 << 52)
    if u >= 1.0:  # borne théorique, jamais atteinte en pratique
        u = 0.999999
    return min(ROCKET_PLAFOND, max(1.00, math.floor((RTP_CIBLE / (1 - u)) * 100) / 100))


class _VueRocket(VueMisee):
    """Le point de crash est tiré à la création et n'est JAMAIS recalculé.

    Il ne dépend ni de la mise, ni du solde, ni de l'historique, ni du moment
    où le joueur clique : il est fixé par un seed tiré avant le décollage. Le
    seed n'est publié qu'après la manche, avec son empreinte, pour que le
    résultat soit auditable sans être devinable pendant le vol.

    **Règle du seuil, verrouillée par test** : l'encaissement est accepté si le
    multiplicateur atteint est STRICTEMENT inférieur au point de crash. À
    égalité exacte, la fusée explose — il faut une règle, et celle-ci est du
    côté de la maison de façon explicite plutôt qu'implicite.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, mise: int, game_id: str):
        super().__init__(ctx.author.id, game_id=game_id, db=cog.bot.db, timeout=ROCKET_DUREE_MAX + 10,
                         message_intrus="Cette fusée appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.mise = cog, ctx, int(mise)
        self.seed = secrets.token_hex(16)
        self.empreinte = hashlib.sha256(self.seed.encode("utf-8")).hexdigest()
        self.crash = tirer_point_de_crash(self.seed)
        self._decollage: float | None = None
        self.encaisse_a: float | None = None
        self.explose = False
        self.add_item(_BoutonEncaisserRocket())

    def demarrer(self) -> None:
        self._decollage = time.monotonic()

    def multiplicateur_actuel(self) -> float:
        if self._decollage is None:
            return 1.0
        return multiplicateur_rocket(time.monotonic() - self._decollage)

    @property
    def retour(self) -> int:
        if self.encaisse_a is None:
            return 0
        return int(round(self.mise * self.encaisse_a))

    def texte(self) -> str:
        emoji = self.cog.emoji_monnaie
        if self.explose:
            return (
                f"💥 **Explosion à ×{self.crash:g}**\n"
                f"Mise perdue : **{stats_service.format_number(self.mise)}** {emoji}.\n"
                f"-# Empreinte `{self.empreinte[:16]}…` · seed `{self.seed}`"
            )
        if self.encaisse_a is not None:
            return (
                f"🚀 **Encaissé à ×{self.encaisse_a:g}** (explosion à ×{self.crash:g})\n"
                f"Retour : **{stats_service.format_number(self.retour)}** {emoji} "
                f"(profit **+{stats_service.format_number(self.retour - self.mise)}**).\n"
                f"-# Empreinte `{self.empreinte[:16]}…` · seed `{self.seed}`"
            )
        return (
            f"🚀 La fusée décolle — **×{self.multiplicateur_actuel():g}**\n"
            f"**Mise** {stats_service.format_number(self.mise)} {emoji}\n"
            f"-# Empreinte du tirage `{self.empreinte[:16]}…` — publiée AVANT le résultat."
        )

    async def encaisser(self, interaction: discord.Interaction) -> None:
        await self.engager()
        atteint = self.multiplicateur_actuel()
        if atteint >= self.crash:
            # À égalité exacte, la fusée gagne : la règle est explicite.
            return await self.exploser(interaction)
        self.encaisse_a = atteint
        await self.regler_gain(self.retour)
        await _finish(
            self.cog.bot, self.ctx, "rocket", self.game_id, "win", 0,
            metadata={"mise": self.mise, "encaisse_a": atteint, "crash": self.crash,
                      "seed": self.seed, "empreinte": self.empreinte},
        )
        self.terminer()
        await self.cog.rendre(self, interaction, "Fusée", kind="success")

    async def exploser(self, interaction: discord.Interaction | None = None) -> None:
        if self.terminee:
            return
        self.explose = True
        await self.engager()
        await self.regler_perte()
        await _finish(
            self.cog.bot, self.ctx, "rocket", self.game_id, "loss", 0,
            metadata={"mise": self.mise, "crash": self.crash,
                      "seed": self.seed, "empreinte": self.empreinte},
        )
        self.terminer()
        await self.cog.rendre(self, interaction, "Fusée", kind="danger")

    async def on_timeout(self) -> None:
        if not self.terminee:
            await self.regler_expiration()
            await _finish(self.cog.bot, self.ctx, "rocket", self.game_id, "loss", 0)
        await super().on_timeout()


class _BoutonEncaisserRocket(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Encaisser", emoji="💰",
                         style=discord.ButtonStyle.success, custom_id="rocket:cashout")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueRocket = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.encaisser(interaction))


# =============================================================================
# 🔐 SAFE — trouver le code, plus haut ou plus bas
# =============================================================================



class _VueSafe(VueDeJeu):
    """Coffre gratuit : cooldown et récompense plafonnée, pas de mise.

    Un jeu de déduction pure n'a pas besoin d'argent engagé pour être
    intéressant, et le brancher sur une mise n'aurait ajouté qu'un risque de
    perte sur une manche qui se gagne à la réflexion. Le farm est contenu par
    le cooldown et par un gain borné, pas par une mise.

    Le code vit uniquement côté serveur : ni les custom_id, ni le texte envoyé
    ne le contiennent avant la fin.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, session_id: str, difficulte: str):
        super().__init__(ctx.author.id, timeout=120.0,
                         message_intrus="Ce coffre appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.difficulte = difficulte
        self.borne, self.gain_max = SAFE_DIFFICULTES[difficulte]
        self.code = game_rewards.secure_randint(1, self.borne)
        self.bas, self.haut = 1, self.borne
        self.restants = SAFE_ESSAIS
        self.trouve = False
        self.dernier: int | None = None

    def texte(self) -> str:
        if self.trouve:
            return (
                f"🔓 **Coffre ouvert !** Le code était **{self.code}**.\n"
                f"Trouvé avec **{self.restants}** essai(s) restant(s)."
            )
        if self.restants <= 0:
            return f"🔒 **Coffre bloqué.** Le code était **{self.code}**."
        indice = ""
        if self.dernier is not None:
            indice = (
                f"**{self.dernier}** — c'est plus "
                + ("**haut** ⬆️" if self.dernier < self.code else "**bas** ⬇️") + "\n"
            )
        return (
            f"🔐 Code entre **{self.bas}** et **{self.haut}**.\n"
            f"{indice}Essais restants : **{self.restants}**\n"
            "-# Écrivez un nombre dans le salon."
        )

    async def proposer(self, valeur: int) -> None:
        """Une proposition. Le compteur d'essais est protégé par le verrou de
        la vue : plusieurs envois simultanés ne consomment pas un seul essai
        pour deux, ni deux pour un."""
        if self.terminee or self.restants <= 0:
            return
        self.dernier = valeur
        self.restants -= 1
        if valeur == self.code:
            self.trouve = True
            gain = max(1, round(self.gain_max * (self.restants + 1) / SAFE_ESSAIS))
            self.recompense = await _finish(
                self.cog.bot, self.ctx, "safe", self.session_id, "win", gain,
                metadata={"difficulte": self.difficulte, "restants": self.restants},
            )
            self.terminer()
        else:
            if valeur < self.code:
                self.bas = max(self.bas, valeur + 1)
            else:
                self.haut = min(self.haut, valeur - 1)
            if self.restants <= 0:
                await _finish(self.cog.bot, self.ctx, "safe", self.session_id, "loss", 0)
                self.terminer()


# =============================================================================
# 🐉 DRAGON — duel au tour par tour contre un adversaire qui télégraphie
# =============================================================================

DRAGON_COOLDOWN = 45
DRAGON_BASE = 70            # récompense d'une victoire en difficulté normale
DRAGON_PRIMES = {"facile": 0.6, "normal": 1.0, "difficile": 1.8}

LIBELLES_ACTION = {
    "attaque": ("Attaquer", "⚔️"),
    "defense": ("Parer", "🛡️"),
    "soin": ("Soigner", "❤️"),
    "special": ("Déchaînement", "💥"),
}
LIBELLES_INTENTION = {
    pve.GRIFFE: ("🗡️", "prépare un coup de griffe"),
    pve.SOUFFLE: ("🔥", "inspire profondément — un souffle arrive"),
    pve.GARDE: ("🐚", "se replie derrière ses écailles"),
}


class _VueDragon(VuePvE):
    """Un duel entier, scellé à la création.

    Les intentions du dragon sont tirées d'avance : en décider après avoir lu
    le coup du joueur permettrait de souffler exactement quand il n'a pas paré,
    et le combat cesserait d'être un jeu de lecture.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, dragon, session_id: str):
        super().__init__(
            ctx.author.id,
            etat=pve.EtatDragon(dragon=dragon, alea=pve.AleaSecurise()),
            timeout=240.0,
            message_intrus="Ce dragon est déjà affronté par quelqu'un d'autre.",
        )
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.dragon = dragon
        self._reconstruire()

    # -- composants ---------------------------------------------------------

    def _reconstruire(self) -> None:
        """Reconstruit les boutons selon ce qui est réellement jouable.

        Un bouton « Déchaîner » affiché sans rage serait cliquable pour rien, et
        un bouton « Soigner » sans charge annoncerait un soin qui n'arrivera
        pas. Les actions impossibles disparaissent au lieu d'être grisées.
        """
        self.clear_items()
        if self.combat_fini:
            return
        possibles = self.actions_possibles()
        for action in pve.ACTIONS_DRAGON:
            if action in possibles:
                self.add_item(_BoutonDragon(action))
        self.add_item(_BoutonAbandon("dragon", "Fuir"))

    # -- rendu --------------------------------------------------------------

    def texte(self) -> str:
        e, d = self.etat, self.dragon
        emoji = self.cog.emoji_monnaie
        lignes = [
            f"{d.emoji} **{d.nom}** · {d.difficulte}",
            f"{self.barre(e.pv_dragon, d.pv)} `{e.pv_dragon}/{d.pv}` PV",
            f"🧝 **Vous** {self.barre(e.pv_joueur, pve.PV_JOUEUR)} `{e.pv_joueur}/{pve.PV_JOUEUR}` PV",
        ]
        if self.journal:
            lignes += ["", self.journal_texte()]
        if self.combat_fini:
            lignes += ["", self._conclusion()]
            if self.recompense is not None:
                lignes.append(self.cog.ligne_recompense(self.recompense).strip())
            elif self.abandonne:
                lignes.append(f"Aucun gain — vous avez quitté le combat. {emoji}")
            return "\n".join(lignes)

        picto, phrase = LIBELLES_INTENTION[e.intention]
        lignes += [
            "",
            f"{picto} Le dragon {phrase}.",
            f"🔥 Rage **{e.rage}/{pve.RAGE_MAX}** · ❤️ soins **{e.soins}** · "
            f"tour **{e.tour + 1}/{pve.TOURS_MAX_DRAGON}**",
        ]
        return "\n".join(lignes)

    def _conclusion(self) -> str:
        if self.abandonne:
            return "🏃 **Vous fuyez.** Le dragon vous laisse partir."
        issue = self.etat.issue()
        if issue == "victoire":
            return f"🏆 **{self.dragon.nom} s'effondre !** Victoire en {self.etat.tour} tours."
        if issue == "egalite":
            return "⚰️ **Vous tombez ensemble.** Personne ne ramène rien."
        if self.etat.pv_joueur <= 0:
            return f"💀 **Vous tombez.** {self.dragon.nom} garde son trésor."
        return f"🕊️ **{self.dragon.nom} s'envole.** Vous n'avez pas su le retenir à temps."

    def _resume_tour(self, r: dict) -> str:
        libelle, picto = LIBELLES_ACTION[r["action"]]
        bouts = [f"{picto} {libelle}"]
        if r["esquive"]:
            bouts.append("le dragon esquive")
        elif r["inflige"]:
            bouts.append(f"**{r['inflige']}** dégâts" + (" ✨ critique" if r["critique"] else ""))
        if r["soigne"]:
            bouts.append(f"**+{r['soigne']}** PV")
        if r["recu"]:
            bouts.append(f"vous encaissez **{r['recu']}**")
        return "· " + " · ".join(bouts)

    # -- jeu ----------------------------------------------------------------

    async def jouer(self, interaction: discord.Interaction, action: str) -> None:
        if self.combat_fini or action not in self.actions_possibles():
            return await self._refuser(interaction, "Cette action n'est plus disponible.")
        self.noter(self._resume_tour(self.etat.jouer(action)))
        if self.combat_fini:
            await self._conclure()
        self._reconstruire()
        await self.cog.rendre(self, interaction, "Chasse au dragon", kind=self._kind())

    def _kind(self) -> str:
        if not self.combat_fini:
            return "primary"
        return "success" if self.etat.issue() == "victoire" and not self.abandonne else "danger"

    async def _conclure(self) -> None:
        """Verse la récompense, une fois et une seule."""
        if not self.marquer_recompense_versee():
            return
        gagne = not self.abandonne and self.etat.issue() == "victoire"
        montant = round(DRAGON_BASE * DRAGON_PRIMES[self.dragon.difficulte]) if gagne else 0
        resultat = "win" if gagne else "loss"
        self.recompense = await _finish(
            self.cog.bot, self.ctx, "dragon", self.session_id, resultat, montant,
            metadata={"dragon": self.dragon.cle, "difficulte": self.dragon.difficulte,
                      "tours": self.etat.tour, "pv_restants": self.etat.pv_joueur,
                      "abandon": self.abandonne},
        )
        if not gagne:
            self.recompense = None
        self.terminer()

    async def abandonner_manche(self, interaction: discord.Interaction) -> None:
        self.abandonner()
        await self._conclure()
        self._reconstruire()
        await self.cog.rendre(self, interaction, "Chasse au dragon", kind="warning")

    async def on_timeout(self) -> None:
        if not self.terminee:
            self.abandonne = True
            await self._conclure()
        await super().on_timeout()


class _BoutonDragon(discord.ui.Button):
    def __init__(self, action: str):
        libelle, picto = LIBELLES_ACTION[action]
        style = {
            "attaque": discord.ButtonStyle.primary,
            "defense": discord.ButtonStyle.secondary,
            "soin": discord.ButtonStyle.success,
            "special": discord.ButtonStyle.danger,
        }[action]
        super().__init__(label=libelle, emoji=picto, style=style,
                         custom_id=f"dragon:{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueDragon = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.jouer(interaction, self.action))


class _BoutonAbandon(discord.ui.Button):
    """Sortie propre, partagée par les deux jeux PvE."""

    def __init__(self, jeu: str, libelle: str = "Abandonner"):
        super().__init__(label=libelle, emoji="🏳️", style=discord.ButtonStyle.secondary,
                         custom_id=f"{jeu}:abandon", row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        vue = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.abandonner_manche(interaction))


# =============================================================================
# 🧟 ZOMBIE — survie par vagues, la munition est la vraie ressource
# =============================================================================

ZOMBIE_COOLDOWN = 45
ZOMBIE_PAR_VAGUE = 26       # récompense par vague nettoyée
ZOMBIE_PRIME_INTEGRALE = 90  # bonus si les six vagues tombent

LIBELLES_ZOMBIE = {
    "tirer": ("Tirer", "🔫"),
    "melee": ("Corps à corps", "🔪"),
    "barricader": ("Se retrancher", "🧱"),
    "fouiller": ("Fouiller", "🎒"),
}


class _VueZombie(VuePvE):
    """Six vagues, connues d'avance et identiques pour tout le monde.

    Aucune vague n'est composée après avoir lu le choix du joueur : la
    composition ne dépend que du numéro de vague, si bien qu'un joueur peut
    apprendre le jeu au lieu de le subir.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, session_id: str):
        super().__init__(
            ctx.author.id,
            etat=pve.EtatZombie(alea=pve.AleaSecurise()),
            timeout=300.0,
            message_intrus="Cet abri est déjà défendu par quelqu'un d'autre.",
        )
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self._reconstruire()

    def _reconstruire(self) -> None:
        self.clear_items()
        if self.combat_fini:
            return
        possibles = self.actions_possibles()
        for action in pve.ACTIONS_ZOMBIE:
            if action in possibles:
                self.add_item(_BoutonZombie(action))
        self.add_item(_BoutonAbandon("zombie", "Se rendre"))

    def texte(self) -> str:
        e = self.etat
        if self.combat_fini:
            lignes = [self._conclusion(),
                      f"🧟 Vagues nettoyées : **{e.vagues_terminees}/{pve.VAGUES_MAX}** "
                      f"en {e.tour} tours."]
            if self.recompense is not None:
                lignes.append(self.cog.ligne_recompense(self.recompense).strip())
            return "\n".join(lignes)

        horde = "".join(z.emoji for z in pve.composer_vague(e.vague))
        total = pve.pv_vague(e.vague)
        lignes = [
            f"🧟 **Vague {e.vague}/{pve.VAGUES_MAX}** — {horde}",
            f"{self.barre(e.pv_vague_restants, total)} `{e.pv_vague_restants}/{total}` PV de horde",
            f"🧝 **Vous** {self.barre(e.pv, pve.PV_SURVIVANT)} `{e.pv}/{pve.PV_SURVIVANT}` PV",
        ]
        if self.journal:
            lignes += ["", self.journal_texte()]
        lignes += [
            "",
            f"🔫 Munitions **{e.munitions}** · 🧱 retranchements **{e.barricades_restantes}** · "
            f"tour **{e.tour + 1}/{pve.TOURS_MAX_ZOMBIE}**",
        ]
        return "\n".join(lignes)

    def _conclusion(self) -> str:
        e = self.etat
        if self.abandonne:
            return "🏳️ **Vous quittez l'abri.** Ce qui restait dehors y reste."
        if e.vagues_terminees >= pve.VAGUES_MAX:
            return "🏆 **L'aube se lève.** Vous avez tenu les six vagues."
        if e.pv <= 0:
            return "💀 **La horde vous submerge.**"
        return "⏳ **Vous n'avez plus la force de tenir un tour de plus.**"

    def _resume_tour(self, r: dict) -> str:
        libelle, picto = LIBELLES_ZOMBIE[r["action"]]
        bouts = [f"{picto} {libelle}"]
        if r["inflige"]:
            bouts.append(f"**{r['inflige']}** dégâts" + (" ✨ critique" if r["critique"] else ""))
        if r["trouve"]:
            bouts.append(f"**+{r['trouve']}** munitions")
        if r["soigne"]:
            bouts.append(f"**+{r['soigne']}** PV")
        if r["morsure"]:
            bouts.append("morsure")
        if r["recu"]:
            bouts.append(f"vous encaissez **{r['recu']}**")
        if r["vague_nettoyee"]:
            bouts.append("**vague nettoyée**")
        return "· " + " · ".join(bouts)

    async def jouer(self, interaction: discord.Interaction, action: str) -> None:
        if self.combat_fini or action not in self.actions_possibles():
            return await self._refuser(interaction, "Cette action n'est plus disponible.")
        self.noter(self._resume_tour(self.etat.jouer(action)))
        if self.combat_fini:
            await self._conclure()
        self._reconstruire()
        await self.cog.rendre(self, interaction, "Nuit des zombies", kind=self._kind())

    def _kind(self) -> str:
        if not self.combat_fini:
            return "primary"
        return "success" if self.etat.vagues_terminees >= pve.VAGUES_MAX else "danger"

    async def _conclure(self) -> None:
        if not self.marquer_recompense_versee():
            return
        vagues = self.etat.vagues_terminees
        montant = vagues * ZOMBIE_PAR_VAGUE
        if vagues >= pve.VAGUES_MAX and not self.abandonne:
            montant += ZOMBIE_PRIME_INTEGRALE
        self.recompense = await _finish(
            self.cog.bot, self.ctx, "zombie", self.session_id,
            "win" if vagues > 0 else "loss", montant,
            metadata={"vagues": vagues, "tours": self.etat.tour,
                      "munitions": self.etat.munitions, "abandon": self.abandonne},
        )
        if montant <= 0:
            self.recompense = None
        self.terminer()

    async def abandonner_manche(self, interaction: discord.Interaction) -> None:
        self.abandonner()
        await self._conclure()
        self._reconstruire()
        await self.cog.rendre(self, interaction, "Nuit des zombies", kind="warning")

    async def on_timeout(self) -> None:
        if not self.terminee:
            self.abandonne = True
            await self._conclure()
        await super().on_timeout()


class _BoutonZombie(discord.ui.Button):
    def __init__(self, action: str):
        libelle, picto = LIBELLES_ZOMBIE[action]
        style = {
            "tirer": discord.ButtonStyle.primary,
            "melee": discord.ButtonStyle.secondary,
            "barricader": discord.ButtonStyle.success,
            "fouiller": discord.ButtonStyle.secondary,
        }[action]
        super().__init__(label=libelle, emoji=picto, style=style,
                         custom_id=f"zombie:{action}")
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueZombie = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.jouer(interaction, self.action))


# =============================================================================
# 🧊 ICE — le pingouin glisse jusqu'au premier obstacle
# =============================================================================

ICE_COOLDOWN = 25
ICE_BASE = 40
ICE_PRIME_PARFAITE = 25     # résoudre au nombre de coups optimal


class _VueIce(VueDeJeu):
    """Puzzle glissant, validé par un solveur AVANT d'être envoyé.

    Près de six grilles sur dix tirées au hasard n'ont aucune solution : sans
    la vérification par parcours en largeur faite à la génération, la majorité
    des manches seraient injouables sans que personne ne le sache.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context,
                 niveau: ice_puzzle.Niveau, session_id: str):
        super().__init__(ctx.author.id, timeout=180.0,
                         message_intrus="Ce lac appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.niveau = niveau
        self.position = niveau.depart
        self.coups = 0
        self.reussi = False
        self.recompense = None
        for direction in ("haut", "gauche", "droite", "bas"):
            self.add_item(_BoutonGlisse(direction))
        self.add_item(_BoutonAbandon("ice", "Quitter le lac"))

    @property
    def coups_restants(self) -> int:
        return max(0, self.niveau.coups_max - self.coups)

    def texte(self) -> str:
        grille = ice_puzzle.dessiner(self.niveau, self.position)
        if self.reussi:
            parfait = self.coups == len(self.niveau.solution)
            tete = (f"🏆 **Dans le trou en {self.coups} coups !**"
                    + (" Le minimum possible. ✨" if parfait else ""))
            lignes = [grille, "", tete]
            if self.recompense is not None:
                lignes.append(self.cog.ligne_recompense(self.recompense).strip())
            return "\n".join(lignes)
        if self.terminee:
            chemin = " ".join(ice_puzzle.FLECHES[d] for d in self.niveau.solution)
            raison = ("🏳️ **Vous quittez le lac.**" if self.abandonne
                      else "❄️ **Plus de coups.** Le pingouin reste sur la glace.")
            return f"{grille}\n\n{raison}\nLa solution était : {chemin}"
        return (
            f"{grille}\n\n"
            f"🐧 Le pingouin glisse jusqu'au premier rocher — il ne s'arrête pas d'une case.\n"
            f"Amenez-le **exactement** sur le trou 🕳️.\n"
            f"Coups restants : **{self.coups_restants}/{self.niveau.coups_max}**"
        )

    @property
    def abandonne(self) -> bool:
        return getattr(self, "_abandonne", False)

    async def glisser(self, interaction: discord.Interaction, direction: str) -> None:
        arrivee = ice_puzzle.glisser(self.position, direction,
                                     self.niveau.rochers, self.niveau.taille)
        if arrivee == self.position:
            # Un mur juste devant : ne pas décompter un coup qui ne fait rien.
            return await self._refuser(
                interaction, "Un rocher bloque déjà ce côté — le pingouin ne bouge pas.")
        self.position = arrivee
        self.coups += 1
        if self.position == self.niveau.trou:
            self.reussi = True
            montant = ICE_BASE + len(self.niveau.solution) * 4
            if self.coups == len(self.niveau.solution):
                montant += ICE_PRIME_PARFAITE
            self.recompense = await _finish(
                self.cog.bot, self.ctx, "ice", self.session_id, "win", montant,
                metadata={"coups": self.coups, "optimal": len(self.niveau.solution)},
            )
            self.terminer()
            return await self.cog.rendre(self, interaction, "Lac gelé", kind="success")
        if self.coups_restants <= 0:
            await _finish(self.cog.bot, self.ctx, "ice", self.session_id, "loss", 0)
            self.terminer()
            return await self.cog.rendre(self, interaction, "Lac gelé", kind="danger")
        await self.cog.rendre(self, interaction, "Lac gelé")

    async def abandonner_manche(self, interaction: discord.Interaction) -> None:
        self._abandonne = True
        await _finish(self.cog.bot, self.ctx, "ice", self.session_id, "loss", 0)
        self.terminer()
        await self.cog.rendre(self, interaction, "Lac gelé", kind="warning")

    async def on_timeout(self) -> None:
        if not self.terminee:
            await _finish(self.cog.bot, self.ctx, "ice", self.session_id, "loss", 0)
        await super().on_timeout()


class _BoutonGlisse(discord.ui.Button):
    def __init__(self, direction: str):
        # Croix directionnelle : haut seul, puis gauche/droite, puis bas.
        rangee = {"haut": 0, "gauche": 1, "droite": 1, "bas": 2}[direction]
        super().__init__(emoji=ice_puzzle.FLECHES[direction],
                         style=discord.ButtonStyle.primary,
                         custom_id=f"ice:{direction}", row=rangee)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueIce = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.glisser(interaction, self.direction))


# =============================================================================
# ⚗️ POTION — récolte, fabrication atomique, effet réel
# =============================================================================

POTION_COOLDOWN = 30


class _VuePotion(VueDeJeu):
    """Atelier d'alchimie branché sur le vrai inventaire.

    Rien n'est simulé : les ingrédients et les potions sont des lignes de la
    table ``inventory``, celle qu'affichent ``+inv`` et la boutique. La
    fabrication passe par ``services.crafting``, qui consomme et crée dans une
    seule transaction — deux fabrications simultanées sur le dernier ingrédient
    ne peuvent pas aboutir toutes les deux.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context,
                 stocks: dict, session_id: str):
        super().__init__(ctx.author.id, timeout=180.0,
                         message_intrus="Cet atelier appartient à quelqu'un d'autre.")
        self.cog, self.ctx, self.session_id = cog, ctx, session_id
        self.stocks = dict(stocks)
        self.message_action = "Que préparez-vous ?"
        self.recolte_utilisee = False
        self._reconstruire()

    def _reconstruire(self) -> None:
        """Un bouton par recette réalisable, plus la récolte. Jamais de bouton mort."""
        self.clear_items()
        if self.terminee:
            return
        for recette in crafting.RECETTES.values():
            realisable = all(self.stocks.get(c, 0) >= q for c, q in recette.ingredients)
            if realisable:
                self.add_item(_BoutonFabriquer(recette))
        for recette in crafting.RECETTES.values():
            if self.stocks.get(recette.cle, 0) > 0:
                self.add_item(_BoutonBoire(recette))
        if not self.recolte_utilisee:
            self.add_item(_BoutonRecolter())
        self.add_item(_BoutonAbandon("potion", "Fermer l'atelier"))

    def texte(self) -> str:
        lignes = ["⚗️ **Atelier d'alchimie**", ""]
        possede = [f"{crafting.nom_objet(c)} ×**{n}**"
                   for c, n in self.stocks.items() if n > 0 and c in crafting.INGREDIENTS]
        fioles = [f"{crafting.nom_objet(c)} ×**{n}**"
                  for c, n in self.stocks.items() if n > 0 and c in crafting.RECETTES]
        lignes.append("🎒 " + (" · ".join(possede) if possede else "_Aucun ingrédient._"))
        if fioles:
            lignes.append("🧴 " + " · ".join(fioles))
        lignes.append("")
        for recette in crafting.RECETTES.values():
            besoin = " + ".join(
                f"{crafting.nom_objet(c)}×{q}" for c, q in recette.ingredients)
            manque = crafting.manquants(recette, self.stocks)
            etat = "✅" if not manque else "❌ manque " + ", ".join(
                f"{crafting.nom_objet(c)}×{n}" for c, n in manque)
            lignes.append(f"{recette.emoji} **{recette.nom}** — {besoin} {etat}")
            lignes.append(f"　_{recette.description}_")
        lignes += ["", self.message_action]
        return "\n".join(lignes)

    async def _rafraichir(self, interaction: discord.Interaction, kind: str = "primary") -> None:
        self.stocks = await crafting.stock(self.cog.bot.db, self.ctx.guild.id, self.ctx.author.id)
        self._reconstruire()
        await self.cog.rendre(self, interaction, "Atelier d'alchimie", kind=kind)

    async def recolter(self, interaction: discord.Interaction) -> None:
        if self.recolte_utilisee:
            return await self._refuser(interaction, "Vous avez déjà fouillé les environs.")
        self.recolte_utilisee = True
        # Les tirages sont figés ici puis passés à la base : tirer côté SQL
        # ferait diverger ce qui est affiché de ce qui est écrit.
        tirages: dict[str, int] = {}
        paires = [(i.cle, i.poids) for i in crafting.INGREDIENTS.values()]
        alea = pve.AleaSecurise()
        for _ in range(alea.entier(crafting.RECOLTE_MIN, crafting.RECOLTE_MAX)):
            cle = alea.pondere(paires)
            tirages[cle] = tirages.get(cle, 0) + 1
        statut, obtenus = await crafting.recolter(
            self.cog.bot.db, self.ctx.guild.id, self.ctx.author.id, list(tirages.items()))
        if statut != "ok":
            self.recolte_utilisee = False
            self.message_action = "🌾 La récolte a échoué — rien n'a été ajouté."
            return await self._rafraichir(interaction, "warning")
        butin = " · ".join(f"{crafting.nom_objet(c)} ×{n}" for c, n in obtenus)
        self.message_action = f"🌾 Vous ramenez {butin}."
        await _finish(self.cog.bot, self.ctx, "potion", self.session_id, "win", 0,
                      metadata={"action": "recolte", "butin": dict(obtenus)})
        await self._rafraichir(interaction, "success")

    async def fabriquer(self, interaction: discord.Interaction, recette) -> None:
        statut = await crafting.fabriquer(
            self.cog.bot.db, self.ctx.guild.id, self.ctx.author.id, recette.cle)
        if statut == "missing":
            self.message_action = (
                f"❌ Il vous manque des ingrédients pour {recette.emoji} **{recette.nom}**.")
            return await self._rafraichir(interaction, "warning")
        if statut != "ok":
            self.message_action = "⚠️ L'alambic refuse de coopérer. Rien n'a été consommé."
            return await self._rafraichir(interaction, "warning")
        self.message_action = f"{recette.emoji} **{recette.nom}** fabriquée et rangée dans votre sac."
        await _finish(self.cog.bot, self.ctx, "potion", self.session_id, "win", 0,
                      metadata={"action": "fabrication", "recette": recette.cle})
        await self._rafraichir(interaction, "success")

    async def boire(self, interaction: discord.Interaction, recette) -> None:
        statut, boost = await crafting.boire(
            self.cog.bot.db, self.ctx.guild.id, self.ctx.author.id, recette.cle)
        if statut == "missing":
            self.message_action = "❌ Vous n'avez plus cette potion."
            return await self._rafraichir(interaction, "warning")
        if statut != "ok":
            self.message_action = "⚠️ La potion n'a pas été consommée. Elle est toujours dans votre sac."
            return await self._rafraichir(interaction, "warning")
        from utils import temporary_boosts
        self.message_action = f"{recette.emoji} Vous buvez. {temporary_boosts.describe(boost)}"
        await _finish(self.cog.bot, self.ctx, "potion", self.session_id, "win", 0,
                      metadata={"action": "consommation", "recette": recette.cle})
        await self._rafraichir(interaction, "success")

    async def abandonner_manche(self, interaction: discord.Interaction) -> None:
        self.message_action = "🔒 Atelier fermé."
        self.terminer()
        self._reconstruire()
        await self.cog.rendre(self, interaction, "Atelier d'alchimie", kind="secondary")


class _BoutonFabriquer(discord.ui.Button):
    def __init__(self, recette):
        super().__init__(label=recette.nom, emoji=recette.emoji,
                         style=discord.ButtonStyle.success,
                         custom_id=f"potion:craft:{recette.cle}")
        self.recette = recette

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VuePotion = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.fabriquer(interaction, self.recette))


class _BoutonBoire(discord.ui.Button):
    def __init__(self, recette):
        super().__init__(label=f"Boire — {recette.nom}", emoji="🥤",
                         style=discord.ButtonStyle.primary, row=2,
                         custom_id=f"potion:drink:{recette.cle}")
        self.recette = recette

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VuePotion = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.boire(interaction, self.recette))


class _BoutonRecolter(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Récolter", emoji="🌾",
                         style=discord.ButtonStyle.secondary, row=3,
                         custom_id="potion:recolte")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VuePotion = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_un_coup(lambda: vue.recolter(interaction))


# =============================================================================
# SOCLE DES PARTIES À PLUSIEURS — salon, inscriptions, paiements multiples
# =============================================================================

class _VuePartie(VueSalon):
    """Ce que +race, +detective et +crown partagent côté Discord.

    Trois points seulement, mais ce sont les trois qui cassent :

      - **un identifiant de manche par joueur payé.** ``game_session_id`` est
        UNIQUE en base : réutiliser le même pour six gagnants n'en paierait
        qu'un, les cinq autres recevant « already_rewarded » en silence. Chacun
        a donc son propre identifiant, dérivé de celui de la manche, ce qui
        garde l'idempotence par joueur.
      - **un verrou de jeu par participant.** ``_precheck`` n'en pose un que
        pour l'organisateur ; sans celui-ci, un membre pourrait être inscrit à
        deux tables en même temps et encaisser deux fois.
      - **les départs.** Un joueur qui s'en va reste connu — son pseudo sert
        encore au tableau final — mais ne compte plus dans les vivants.
    """

    def __init__(self, cog: "GamesArcade", ctx: commands.Context, jeu: str,
                 session_id: str, **kwargs):
        super().__init__(ctx.author.id, **kwargs)
        self.cog, self.ctx, self.jeu, self.session_id = cog, ctx, jeu, session_id
        self.raison_de_fin = ""
        self.gains: dict[int, int] = {}
        self.recompenses: dict[int, object] = {}
        self.joindre(ctx.author.id, ctx.author.display_name)
        self._reconstruire()

    # -- verrous ------------------------------------------------------------

    def _prendre_verrou(self, user_id: int) -> bool:
        """L'organisateur a déjà le sien, posé par le précontrôle."""
        if user_id == self.ctx.author.id:
            return True
        return game_rewards.acquire_play_lock(self.ctx.guild.id, user_id, self.jeu)

    def liberer_verrous(self) -> None:
        for user_id in self.participants:
            game_rewards.release_play_lock(self.ctx.guild.id, user_id, self.jeu)

    # -- inscriptions -------------------------------------------------------

    async def rejoindre(self, interaction: discord.Interaction) -> None:
        membre = interaction.user
        if self.est_inscrit(membre.id):
            return await self._refuser(interaction, "Vous êtes déjà à cette table.")
        if not self._prendre_verrou(membre.id):
            return await self._refuser(
                interaction, "Vous avez déjà une manche de ce jeu en cours.")
        statut = self.joindre(membre.id, membre.display_name)
        if statut != "ok":
            game_rewards.release_play_lock(self.ctx.guild.id, membre.id, self.jeu)
            return await self._refuser(interaction, {
                "complet": f"La table est complète ({self.joueurs_max} joueurs).",
                "commencee": "La partie a déjà commencé.",
            }.get(statut, "Inscription impossible."))
        self._reconstruire()
        await self.cog.rendre(self, interaction, self.titre)

    async def partir(self, interaction: discord.Interaction) -> None:
        if self.quitter(interaction.user.id) != "ok":
            return await self._refuser(interaction, "Vous n'étiez pas à cette table.")
        game_rewards.release_play_lock(self.ctx.guild.id, interaction.user.id, self.jeu)
        if self.demarree and len(self.actifs) < self.joueurs_min:
            # Plus assez de monde en cours de route : on conclut avec ce qui a
            # été joué plutôt que de laisser une partie fantôme sur l'écran.
            return await self.conclure(interaction, "Il ne reste plus assez de joueurs.")
        self._reconstruire()
        await self.cog.rendre(self, interaction, self.titre)

    async def lancer(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.organisateur_id:
            return await self._refuser(
                interaction, "Seul l'organisateur de la table peut lancer la partie.")
        if self.demarree:
            return await self._refuser(interaction, "La partie a déjà commencé.")
        if not self.assez_de_joueurs:
            return await self._refuser(
                interaction, f"Il faut au moins {self.joueurs_min} joueurs.")
        self.demarree = True
        await self.demarrer()
        self._reconstruire()
        await self.cog.rendre(self, interaction, self.titre, kind="success")

    async def demarrer(self) -> None:
        """Préparation propre au jeu, une fois la table complète."""

    # -- composants ---------------------------------------------------------

    def _boutons_salon(self) -> None:
        self.add_item(_BoutonRejoindre(self.jeu))
        self.add_item(_BoutonQuitter(self.jeu))
        if not self.demarree:
            self.add_item(_BoutonLancer(self.jeu, self.assez_de_joueurs))

    def ligne_table(self) -> str:
        noms = []
        for user_id, nom in self.participants.items():
            noms.append(f"~~{nom}~~" if user_id in self.partis else nom)
        effectif = f"{len(self.actifs)}/{self.joueurs_max}"
        return f"👥 **Table ({effectif})** : " + (", ".join(noms) or "_personne_")

    # -- paiement -----------------------------------------------------------

    async def payer(self, gains: dict[int, int]) -> None:
        """Crédite chaque gagnant sous son propre identifiant de manche.

        Un seul identifiant pour toute la table ne paierait que le premier :
        l'insertion des suivants serait refusée pour cause de doublon, sans
        erreur visible nulle part.
        """
        if not self.marquer_recompense_versee():
            return
        self.gains = dict(gains)
        for user_id, montant in gains.items():
            if montant <= 0:
                continue
            try:
                self.recompenses[user_id] = await game_rewards.reward_game_winner(
                    self.cog.bot, self.ctx.guild.id, user_id, self.jeu, montant,
                    f"{self.session_id}-{user_id}", result="win",
                    metadata={"table": len(self.participants), "partis": len(self.partis)},
                )
            except Exception:
                logger.exception("Récompense non versée à %s (%s).", user_id, self.jeu)
        for user_id in self.participants:
            try:
                await game_rewards.touch_cooldown(
                    self.cog.bot, self.ctx.guild.id, user_id, self.jeu)
            except Exception:
                logger.debug("Cooldown non posé pour %s.", user_id, exc_info=True)
        self.liberer_verrous()

    def tableau_des_gains(self) -> str:
        if not self.gains:
            return ""
        lignes = []
        for user_id, montant in sorted(self.gains.items(), key=lambda p: -p[1]):
            if montant <= 0:
                continue
            recompense = self.recompenses.get(user_id)
            verse = getattr(recompense, "amount", montant) if recompense else montant
            reference = getattr(recompense, "display_id", None)
            suffixe = f" · réf. `{reference}`" if reference else ""
            lignes.append(f"{self.cog.emoji_monnaie} **{self.nom(user_id)}** "
                          f"+{stats_service.format_number(verse)}{suffixe}")
        return "\n".join(lignes)

    async def conclure(self, interaction, raison: str = "") -> None:
        """Fin commune : paiement, désactivation, dernier rendu."""
        await self.payer(self.calculer_gains())
        self.raison_de_fin = raison
        self.terminer()
        self._reconstruire()
        await self.cog.rendre(self, interaction, self.titre, kind="success")

    def calculer_gains(self) -> dict[int, int]:
        return {}

    async def on_timeout(self) -> None:
        if not self.terminee:
            if self.demarree:
                await self.payer(self.calculer_gains())
            self.liberer_verrous()
        await super().on_timeout()


class _BoutonRejoindre(discord.ui.Button):
    def __init__(self, jeu: str):
        super().__init__(label="Rejoindre", emoji="➕",
                         style=discord.ButtonStyle.success, row=4,
                         custom_id=f"{jeu}:rejoindre")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VuePartie = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id, lambda: vue.rejoindre(interaction))


class _BoutonQuitter(discord.ui.Button):
    def __init__(self, jeu: str):
        super().__init__(label="Quitter", emoji="🚪",
                         style=discord.ButtonStyle.secondary, row=4,
                         custom_id=f"{jeu}:quitter")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VuePartie = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id, lambda: vue.partir(interaction))


class _BoutonLancer(discord.ui.Button):
    def __init__(self, jeu: str, pret: bool):
        super().__init__(label="Lancer la partie", emoji="▶️", row=4,
                         style=discord.ButtonStyle.primary if pret
                         else discord.ButtonStyle.secondary,
                         disabled=not pret, custom_id=f"{jeu}:lancer")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VuePartie = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id, lambda: vue.lancer(interaction))


# =============================================================================
# 🏁 RACE — avancer sûrement ou sprinter, chacun sa ligne
# =============================================================================

RACE_COOLDOWN = 40


class _VueRace(_VuePartie):
    """Course où le choix compte autant que la vitesse de clic.

    Le pas garanti rapporte 2 cases en moyenne, le sprint 2,15 mais cale trois
    fois sur dix et coûte alors un tour. Mesuré sur 4 000 courses : ni l'un ni
    l'autre ne domine, et le jeu mixte — sprinter puis sécuriser à l'approche
    de la ligne — bat le pas garanti pur dans 58,5 % des duels.

    Un délai par joueur borne le clic : sans lui, la course se gagnerait à la
    macro et non à la décision.
    """

    titre = "Course d'obstacles"

    def __init__(self, cog, ctx, session_id: str):
        self.coureurs: dict[int, party.Coureur] = {}
        self.dernier_coup: dict[int, float] = {}
        self.vainqueur: int | None = None
        super().__init__(cog, ctx, "race", session_id,
                         joueurs_min=party.RACE_JOUEURS_MIN,
                         joueurs_max=party.RACE_JOUEURS_MAX,
                         timeout=300.0,
                         message_intrus="Rejoignez la course pour y courir.")

    async def demarrer(self) -> None:
        self.coureurs = {uid: party.Coureur(uid) for uid in self.actifs}

    def _reconstruire(self) -> None:
        self.clear_items()
        if self.terminee:
            return
        if self.demarree:
            self.add_item(_BoutonCourse("avancer", "Avancer", "👟",
                                        discord.ButtonStyle.primary))
            self.add_item(_BoutonCourse("sprinter", "Sprinter", "💨",
                                        discord.ButtonStyle.danger))
        self._boutons_salon()

    def piste(self, coureur: party.Coureur) -> str:
        avance = round(coureur.position / party.PISTE * 12)
        return "─" * avance + "🏃" + "·" * (12 - avance) + "🏁"

    def texte(self) -> str:
        if not self.demarree:
            return (f"🏁 **Course d'obstacles** — piste de {party.PISTE} cases.\n"
                    f"👟 Avancer : 1 à 3 cases, toujours.\n"
                    f"💨 Sprinter : jusqu'à {party.SPRINT[1]} cases, mais trois fois sur "
                    f"dix vous calez et perdez le tour suivant.\n\n"
                    f"{self.ligne_table()}\n\n"
                    f"Il faut **{self.joueurs_min}** joueurs pour lancer.")
        lignes = []
        for user_id, coureur in sorted(self.coureurs.items(),
                                       key=lambda p: -p[1].position):
            marque = "🏆 " if user_id == self.vainqueur else ""
            sortie = " _(parti)_" if user_id in self.partis else ""
            repos = " 😵" if coureur.repos > 0 else ""
            lignes.append(f"{marque}`{coureur.position:2}` {self.piste(coureur)} "
                          f"**{self.nom(user_id)}**{repos}{sortie}")
        corps = "\n".join(lignes)
        if self.terminee:
            tete = (f"🏆 **{self.nom(self.vainqueur)} franchit la ligne !**"
                    if self.vainqueur is not None
                    else f"🏁 **Course interrompue.** {self.raison_de_fin}")
            gains = self.tableau_des_gains()
            return f"{corps}\n\n{tete}" + (f"\n{gains}" if gains else "")
        return (f"{corps}\n\n👟 Avancer · 💨 Sprinter — "
                f"**{party.DELAI_ENTRE_COUPS:g} s** entre deux coups.")

    async def courir(self, interaction: discord.Interaction, sprinte: bool) -> None:
        user_id = interaction.user.id
        if not self.demarree:
            return await self._refuser(interaction, "La course n'a pas encore été lancée.")
        coureur = self.coureurs.get(user_id)
        if coureur is None or user_id in self.partis:
            return await self._refuser(interaction, "Vous ne courez pas cette manche.")
        # time.monotonic : une horloge qui ne recule pas. time.time() reculerait
        # à la synchronisation NTP et rendrait le délai négatif.
        maintenant = time.monotonic()
        attente = self.dernier_coup.get(user_id, 0.0) + party.DELAI_ENTRE_COUPS - maintenant
        if attente > 0:
            return await self._refuser(
                interaction, f"Reprenez votre souffle — encore {attente:.1f} s.")
        self.dernier_coup[user_id] = maintenant
        party.avancer(coureur, sprinte, pve.AleaSecurise())
        if coureur.arrive:
            self.vainqueur = user_id
            return await self.conclure(interaction)
        await self.cog.rendre(self, interaction, self.titre)

    def calculer_gains(self) -> dict[int, int]:
        gains: dict[int, int] = {}
        for user_id, coureur in self.coureurs.items():
            if user_id in self.partis:
                continue        # partir en route ne rapporte rien
            gains[user_id] = party.RACE_PARTICIPATION
        if self.vainqueur is not None:
            gains[self.vainqueur] = gains.get(self.vainqueur, 0) + party.RACE_BASE
        return gains


class _BoutonCourse(discord.ui.Button):
    def __init__(self, cle: str, libelle: str, picto: str, style):
        super().__init__(label=libelle, emoji=picto, style=style,
                         custom_id=f"race:{cle}")
        self.sprinte = cle == "sprinter"

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueRace = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id,
                             lambda: vue.courir(interaction, self.sprinte))


# =============================================================================
# 🕵️ DETECTIVE — accuser tôt paie plus, se tromper élimine
# =============================================================================

DETECTIVE_COOLDOWN = 50


class _VueDetective(_VuePartie):
    """Enquête dont les indices désignent toujours exactement un coupable.

    Vérifié à la génération par le même chemin que le jeu, exactement comme la
    grille de ``+ice`` : des indices tirés au hasard laissent souvent deux
    suspects compatibles, et le joueur qui accuse l'autre a raison sans pouvoir
    gagner. Le coupable et les indices restent côté serveur ; aucun custom_id
    ne dit lequel est le bon.
    """

    titre = "Enquête"

    def __init__(self, cog, ctx, enquete, session_id: str):
        self.enquete = enquete
        self.indices_lus = 1
        self.elimines: set[int] = set()
        self.vainqueur: int | None = None
        self.prime = 0
        super().__init__(cog, ctx, "detective", session_id,
                         joueurs_min=party.DETECTIVE_JOUEURS_MIN,
                         joueurs_max=party.DETECTIVE_JOUEURS_MAX,
                         timeout=300.0,
                         message_intrus="Rejoignez l'enquête pour accuser.")

    def _reconstruire(self) -> None:
        self.clear_items()
        if self.terminee:
            return
        if self.demarree:
            for position, suspect in enumerate(self.enquete.suspects):
                self.add_item(_BoutonSuspect(position, suspect.nom))
            if self.indices_lus < len(self.enquete.indices):
                self.add_item(_BoutonIndice())
        self._boutons_salon()

    def texte(self) -> str:
        if not self.demarree:
            return ("🕵️ **Enquête** — un coupable parmi "
                    f"{len(self.enquete.suspects)} suspects.\n"
                    "Chaque indice révélé rapproche de la vérité, mais réduit la prime : "
                    "accuser tôt paie davantage. Une accusation fausse vous élimine.\n\n"
                    f"{self.ligne_table()}\n\n"
                    f"Il faut **{self.joueurs_min}** joueurs pour lancer.")
        lignes = ["🕵️ **Suspects**"]
        lignes += [f"　{s.portrait()}" for s in self.enquete.suspects]
        lignes += ["", f"🔍 **Indices ({self.indices_lus}/{len(self.enquete.indices)})**"]
        lignes += [f"　• {i.texte()}" for i in self.enquete.indices[:self.indices_lus]]
        if self.terminee:
            if self.vainqueur is not None:
                lignes += ["", f"🏆 **{self.nom(self.vainqueur)} démasque "
                               f"{self.enquete.coupable.nom} !**"]
            else:
                lignes += ["", f"🕯️ **Personne n'a trouvé.** Le coupable était "
                               f"**{self.enquete.coupable.nom}**. {self.raison_de_fin}"]
            gains = self.tableau_des_gains()
            if gains:
                lignes.append(gains)
            return "\n".join(lignes)
        lignes += ["", f"💰 Accuser maintenant vaut "
                       f"**{party.prime_accusation(self.enquete, self.indices_lus)}** "
                       f"{self.cog.emoji_monnaie}."]
        if self.elimines:
            hors = ", ".join(self.nom(u) for u in self.elimines)
            lignes.append(f"❌ Éliminés : {hors}")
        return "\n".join(lignes)

    async def reveler(self, interaction: discord.Interaction) -> None:
        if self.indices_lus >= len(self.enquete.indices):
            return await self._refuser(interaction, "Tous les indices sont déjà là.")
        self.indices_lus += 1
        self._reconstruire()
        await self.cog.rendre(self, interaction, self.titre)

    async def accuser(self, interaction: discord.Interaction, position: int) -> None:
        user_id = interaction.user.id
        if not self.demarree:
            return await self._refuser(interaction, "L'enquête n'a pas encore commencé.")
        if user_id in self.elimines:
            return await self._refuser(interaction, "Vous vous êtes déjà trompé·e.")
        suspect = self.enquete.suspects[position]
        if suspect == self.enquete.coupable:
            self.vainqueur = user_id
            self.prime = party.prime_accusation(self.enquete, self.indices_lus)
            return await self.conclure(interaction)
        self.elimines.add(user_id)
        restants = [u for u in self.actifs if u not in self.elimines]
        if not restants:
            return await self.conclure(interaction, "Tout le monde s'est trompé.")
        await self._refuser(interaction, f"❌ Ce n'est pas {suspect.nom}. Vous êtes éliminé·e.")
        self._reconstruire()
        await self.cog.rendre(self, interaction, self.titre, kind="warning")

    def calculer_gains(self) -> dict[int, int]:
        return {self.vainqueur: self.prime} if self.vainqueur is not None else {}


class _BoutonSuspect(discord.ui.Button):
    #: Émoji d'accusation identique pour tous : un pictogramme par suspect
    #: laisserait deviner lequel est le coupable.
    def __init__(self, position: int, nom: str):
        super().__init__(label=nom, emoji="🔎", style=discord.ButtonStyle.secondary,
                         row=position // 3, custom_id=f"detective:accuser:{position}")
        self.position = position

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueDetective = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id,
                             lambda: vue.accuser(interaction, self.position))


class _BoutonIndice(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Nouvel indice", emoji="🔍", row=3,
                         style=discord.ButtonStyle.primary, custom_id="detective:indice")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueDetective = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id, lambda: vue.reveler(interaction))


# =============================================================================
# 👑 CROWN — tenir la couronne quand le temps s'arrête
# =============================================================================

CROWN_COOLDOWN = 50


class _VueCrown(_VuePartie):
    """Roi de la colline. L'instant de fin est scellé au départ.

    Le tirer en cours de manche permettrait de le faire tomber pile quand
    quelqu'un vient de prendre la couronne, et personne ne pourrait le prouver.
    Ici il est fixé au lancement et jamais relu depuis le client.

    Le temps de port compte autant que le dernier clic : payer uniquement le
    porteur final ferait de la manche une loterie où tenir la couronne une
    minute entière ne vaudrait rien.
    """

    titre = "Roi de la colline"

    def __init__(self, cog, ctx, session_id: str):
        self.couronne: party.Couronne | None = None
        self.duree = 0
        self._horloge: asyncio.Task | None = None
        super().__init__(cog, ctx, "crown", session_id,
                         joueurs_min=party.CROWN_JOUEURS_MIN,
                         joueurs_max=party.CROWN_JOUEURS_MAX,
                         timeout=240.0,
                         message_intrus="Rejoignez la colline pour prendre la couronne.")

    async def demarrer(self) -> None:
        """Scelle l'instant de fin. Rien d'autre.

        Le compte à rebours ne part pas d'ici : y créer une tâche rendrait la
        préparation de la manche impossible à vérifier sans bot vivant, et
        lierait l'état du jeu à une boucle d'événements. Il démarre au clic,
        là où la boucle et le message existent pour de bon.
        """
        self.duree = pve.AleaSecurise().entier(*party.CROWN_FENETRE)
        self.couronne = party.Couronne(fin=time.monotonic() + self.duree)

    async def lancer(self, interaction: discord.Interaction) -> None:
        await super().lancer(interaction)
        if self.demarree and self._horloge is None:
            self._horloge = asyncio.create_task(self._compte_a_rebours())

    def _reconstruire(self) -> None:
        self.clear_items()
        if self.terminee:
            return
        if self.demarree:
            self.add_item(_BoutonCouronne())
        self._boutons_salon()

    def _restant(self) -> float:
        if self.couronne is None:
            return 0.0
        return max(0.0, self.couronne.fin - time.monotonic())

    def texte(self) -> str:
        if not self.demarree:
            return ("👑 **Roi de la colline** — une couronne, plusieurs mains.\n"
                    f"La manche s'arrête à un instant tiré entre "
                    f"{party.CROWN_FENETRE[0]} et {party.CROWN_FENETRE[1]} secondes, "
                    "scellé au lancement et jamais annoncé.\n"
                    f"Reprendre la couronne demande {party.CROWN_VERROU:g} s d'attente "
                    "après l'avoir perdue.\n\n"
                    f"{self.ligne_table()}\n\n"
                    f"Il faut **{self.joueurs_min}** joueurs pour lancer.")
        porteur = (f"👑 **{self.nom(self.couronne.porteur)}** porte la couronne"
                   if self.couronne.porteur is not None
                   else "👑 La couronne est **à terre**")
        if self.terminee:
            lignes = [porteur, ""]
            classement = self.couronne.classement()
            for rang, (user_id, secondes) in enumerate(classement[:8], start=1):
                lignes.append(f"`{rang}.` **{self.nom(user_id)}** — "
                              f"{secondes:.0f} s de règne")
            if self.raison_de_fin:
                lignes.append(f"\n{self.raison_de_fin}")
            gains = self.tableau_des_gains()
            if gains:
                lignes += ["", gains]
            return "\n".join(lignes)
        restant = self._restant()
        barre = "▰" * max(0, round(restant / max(1, self.duree) * 12))
        return (f"{porteur}\n"
                f"{barre or '▱'} _le temps file…_\n\n"
                + "\n".join(f"　**{self.nom(u)}** {s:.0f} s"
                            for u, s in self.couronne.classement()[:6])
                + "\n\n👑 Prenez la couronne — et gardez-la.")

    async def prendre(self, interaction: discord.Interaction) -> None:
        if self.couronne is None:
            return await self._refuser(interaction, "La manche n'a pas encore commencé.")
        maintenant = time.monotonic()
        statut = self.couronne.prendre(interaction.user.id, maintenant)
        if statut == "deja":
            return await self._refuser(interaction, "Vous la portez déjà.")
        if statut == "verrou":
            attente = self.couronne.verrouille_jusqu_a(interaction.user.id) - maintenant
            return await self._refuser(
                interaction, f"Vous venez de la perdre — encore {attente:.1f} s.")
        if statut == "finie":
            return await self._refuser(interaction, "La manche est terminée.")
        await self.cog.rendre(self, interaction, self.titre)

    async def _compte_a_rebours(self) -> None:
        """Rafraîchit la manche, puis la conclut à l'instant scellé.

        La boucle ne décide de rien : elle lit ``couronne.fin``, fixé au
        lancement. Elle ne peut donc pas allonger la manche pour favoriser
        qui que ce soit.
        """
        try:
            while not self.terminee and self._restant() > 0:
                await asyncio.sleep(min(6.0, max(1.0, self._restant())))
                if self.terminee:
                    return
                try:
                    await self.cog.rendre(self, None, self.titre)
                except Exception:
                    logger.debug("Rafraîchissement de la couronne manqué.", exc_info=True)
            if not self.terminee:
                await self.jouer_pour(0, lambda: self.conclure(None))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Compte à rebours de la couronne interrompu.")

    def calculer_gains(self) -> dict[int, int]:
        if self.couronne is None:
            return {}
        self.couronne.cloturer(time.monotonic())
        gains = party.gains_couronne(self.couronne)
        # Partir en cours de manche ne fait pas perdre le temps déjà régné :
        # il a bien été tenu, et l'effacer punirait une déconnexion.
        return gains


class _BoutonCouronne(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Prendre la couronne", emoji="👑",
                         style=discord.ButtonStyle.primary, custom_id="crown:prendre")

    async def callback(self, interaction: discord.Interaction) -> None:
        vue: _VueCrown = panels.vue_source(self)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await vue.jouer_pour(interaction.user.id, lambda: vue.prendre(interaction))
