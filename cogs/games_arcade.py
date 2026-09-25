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
from utils import game_rewards, stats_service
from utils import sentrix_panels as panels
from utils.game_ui import (
    VueDeJeu,
    VueMisee,
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
