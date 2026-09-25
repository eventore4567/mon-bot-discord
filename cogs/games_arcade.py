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

import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.games_economy import _embed, _finish, _precheck
from services import game_stakes
from utils import game_rewards, stats_service
from utils import sentrix_panels as panels
from utils.game_ui import VueDeJeu, valider_composants

logger = logging.getLogger("bot.games-arcade")


# =============================================================================
# 💣 BOMB — cases sûres, multiplicateur progressif, encaissement
# =============================================================================

BOMB_CASES = 9          # grille 3x3 : tient sur un écran de téléphone
BOMB_BOMBES = 2         # deux bombes sur neuf cases
BOMB_COOLDOWN = 12
BOMB_MISE_MIN = 10
BOMB_MISE_MAX = 5_000


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
            # La mise est partie à l'OUVERTURE de la manche : il n'y a plus rien
            # à débiter ici, seulement à clore la réservation. C'est ce qui
            # empêche d'ouvrir trois grilles à 100 avec 100 en poche.
            await game_stakes.regler_perte(self.cog.bot.db, self.session_id)
            await _finish(self.cog.bot, self.ctx, "bomb", self.session_id, "loss", 0)
            self.terminer()
            return await self._rendre(interaction, kind="danger")

        self.ouvertes.append(index)
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


class GamesArcade(commands.Cog, name="GamesArcade"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.emoji_monnaie = "🪙"

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Rend les mises restées ouvertes après un redémarrage.

        Une manche interrompue — crash, déploiement, message supprimé — laisse
        sa mise réservée en base. Sans ce balayage, l'argent resterait bloqué
        dans une partie qui n'existe plus : le joueur l'aurait perdu sans avoir
        joué. Le balayage ne touche que les mises assez vieilles pour qu'aucune
        vue ne soit plus en face.
        """
        if getattr(self.bot, "_sentrix_mises_balayees", False):
            return
        self.bot._sentrix_mises_balayees = True
        try:
            rendues = await game_stakes.rembourser_mises_orphelines(self.bot.db)
            if rendues:
                logger.info("Mises orphelines remboursées au démarrage : %s.", rendues)
        except Exception:
            logger.warning("Balayage des mises orphelines impossible.", exc_info=True)

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
        except Exception:
            logger.exception("Grille non affichée : mise remboursée (%s).", session_id)
            await game_stakes.rembourser_mise(self.bot.db, session_id)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "bomb")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes",
                description="La partie n'a pas pu démarrer. Votre mise vous a été rendue.",
                kind="danger")))


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesArcade(bot))
