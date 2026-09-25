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
import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.games_economy import _embed, _finish, _precheck
from services import game_stakes
from utils import game_rewards, stats_service
from utils import sentrix_panels as panels
from utils.game_ui import (
    VueDeJeu,
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
