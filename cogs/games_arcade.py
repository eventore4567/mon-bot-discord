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
from services import economy as economy_service
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
            # La mise est prélevée ICI, atomiquement, et pas avant : le joueur
            # ne paie que s'il perd. Économiquement identique à une mise
            # retenue d'avance, mais la limite quotidienne de récompenses ne
            # peut plus lui faire perdre son argent sans rien lui rendre.
            statut = await economy_service.atomic_gamble(
                self.cog.bot.db, self.ctx.guild.id, self.ctx.author.id, self.mise, win=False
            )
            if statut != "ok":
                logger.warning(
                    "Mise de %s non prélevée sur %s (statut=%s).",
                    self.mise, self.ctx.author.id, statut,
                )
                self.mise_non_prelevee = True
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
        # Le gain net passe par la même primitive atomique que la perte. Le
        # crédit de jeu (_finish) n'est appelé qu'avec 0 : il sert au cooldown,
        # à l'historique et aux statistiques, pas à payer une deuxième fois.
        self.credit_ok = True
        if gain > 0:
            statut = await economy_service.atomic_gamble(
                self.cog.bot.db, self.ctx.guild.id, self.ctx.author.id, gain, win=True
            )
            if statut != "ok":
                self.credit_ok = False
                logger.warning(
                    "Gain de %s non crédité sur %s (statut=%s).",
                    gain, self.ctx.author.id, statut,
                )
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

        # Sans cette vérification, une grille lancée sans le sou serait gratuite :
        # la perte ne prélèverait rien et l'encaissement paierait quand même.
        stats = await stats_service.get_member_statistics(self.bot, ctx.guild, ctx.author)
        liquide = int(stats.get("cash", stats.get("total_money", 0)) or 0)
        if liquide < mise:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes",
                description=(
                    f"Mise de **{stats_service.format_number(mise)}** {self.emoji_monnaie} impossible : "
                    f"vous avez **{stats_service.format_number(liquide)}** {self.emoji_monnaie} en liquide."
                ),
                kind="warning",
            )))

        demarre, erreur, session_id = await _precheck(self.bot, ctx, "bomb", BOMB_COOLDOWN)
        if not demarre:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title="Bombes", description=erreur, kind="warning")))

        vue = _VueBomb(self, ctx, mise, session_id)
        embed = await _embed(self.bot, guild_id, title="Bombes", description=vue.texte())
        valider_composants(vue)
        vue.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), vue))


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesArcade(bot))
