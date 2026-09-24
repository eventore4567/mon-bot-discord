"""
Cog JEUX ÉCONOMIQUES (Partie 1 de la demande de Jayden — Phase 4).

Étend cogs/minigames.py (rps, guess-number, trivia, tictactoe, hangman, math-quiz,
blackjack, slots — déjà retrofités avec des récompenses réelles) avec le reste des mini-jeux
demandés : jeux rapides supplémentaires, duels 1v1, jeux communautaires (premier arrivé /
premier correct gagne) et jeux solo à cooldown long. TOUS créditent une récompense virtuelle
réelle via utils/game_rewards.py, qui écrit dans la même table `economy` que /balance —
jamais de deuxième monnaie, jamais d'argent réel, jamais d'achat.

Honnêteté de périmètre (documentée ici comme pour la refonte des logs) : la liste envoyée
par Jayden citait ~37 noms de mini-jeux répartis en 4 catégories. Plutôt que d'écrire 37
mécaniques totalement indépendantes (risque élevé de bugs et de code impossible à maintenir
dans le temps imparti), ce fichier utilise quelques moteurs génériques réutilisables
(course textuelle, course au clic, duel à choix privé, aventure solo à cooldown) déclinés
en autant de commandes distinctes que possible, avec un habillage (texte, emoji, valeurs)
différent à chaque fois. `duel` couvre à la fois "duel" et "rps" (duel) de la liste — un
duel façon pierre-feuille-ciseaux entre deux joueurs est la même mécanique. Toute commande
manquante peut être ajoutée plus tard sur le même moteur, sans nouvelle table ni nouvelle
architecture.

Commandes ajoutées ici :
  Rapides    : +coinflip +dice +roll +highlow +memory +reaction +scramble +wordgame
               +emojiquiz +colorquiz +fasttype
  Duels      : +duel +connect4 +numberduel +reactionduel +quizduel
  Communauté : +triviastart +wordrace +reactionevent +guessrace +mathrace +lastmessage
               +emoji-race
  Solo       : +adventure +dungeon +mining +fishing +treasure +hunt +explore
  Joueur     : +gamehistory +gameprofile +gamestats +gametop +dailygames
  Staff      : +gamesetup (panneau interactif, voir GamesSetupView)
"""

from __future__ import annotations
import json
import logging

import asyncio
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs.games_catalog import (
    COLOR_EMOJIS,
    COMMUNITY_MATH_OPS,
    COMMUNITY_TRIVIA,
    COMMUNITY_WORDS,
    EMOJI_QUIZ,
    FASTTYPE_EMOJIS,
    FASTTYPE_PHRASES,
    FASTTYPE_WORDS,
    GAME_CATALOG,
    MEMORY_TOKENS,
    RARETES,
    RPS_BEATS,
    SOLO_CHOICES,
    SOLO_ECHECS,
    SOLO_FLAVORS,
    SOLO_LOOT,
    WORDGAME_CLUES,
)
from utils import checks, design_system, game_rewards, stats_service, temporary_boosts
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.games-economy")

TICTACTOE_QUESTIONS = None  # (placeholder retiré — voir cogs/minigames.py pour tictactoe)


def _game_icon(title: str) -> str:
    """Pictogramme du titre — règle unique dans utils/game_context."""
    from utils.game_context import pictogramme_de_titre

    return pictogramme_de_titre(title)


async def _embed(bot, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
    style = design_system.CATEGORY_STYLES["games"]
    colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
    default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
    design = await bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
    resolved_title = design_system.kind_title(title, kind=kind, category_emoji=style["emoji"])
    embed = design_system.create_embed(
        title=resolved_title,
        description=description,
        colour=design.get(colour_key, default_colour),
        footer=design.get("footer"),
    )
    embed.title = f"{_game_icon(title)} {resolved_title}"
    if description:
        embed.description = str(description)
    return embed


# Plus haut ou plus bas : la valeur reste un nombre de 1 a 13 pour la comparaison,
# mais le joueur voit une vraie carte. « Première carte : 1 » ne veut rien dire a
# une table de jeu ; « A♠ » si.
_ENSEIGNES = ("♠", "♥", "♦", "♣")
_FIGURES = {1: "A", 11: "V", 12: "D", 13: "R"}


_FACES_DE = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


def _carte_lisible(valeur: int, enseigne: str) -> str:
    return f"`{_FIGURES.get(int(valeur), str(valeur))}{enseigne}`"


def _reward_line(reward: "game_rewards.GameReward | None") -> str:
    if reward and reward.success and reward.amount > 0:
        boost = float((reward.metadata or {}).get("money_boost", 1.0) or 1.0)
        suffix = f" · 🚀 boost x{boost:g}" if boost > 1.0 else ""
        return f"\n\n🪙 **+{reward.amount}** crédités !{suffix} (réf. `{reward.display_id}`)"
    if reward and reward.reason == "daily_limit":
        return (
            "\n\n🪙 **Récompense quotidienne maximale atteinte.** "
            "La partie reste jouable : seule la monnaie est limitée."
        )
    return ""


def _primary_answer(answer) -> str:
    if isinstance(answer, (list, tuple, set)):
        return str(next(iter(answer)))
    return str(answer)


def _difficulty_profile(value: str) -> tuple[int, float, int]:
    """Retourne longueur du défi, temps d'affichage et multiplicateur de récompense."""
    value = str(value or "normal").casefold()
    return {
        "facile": (3, 0.8, 0),
        "easy": (3, 0.8, 0),
        "normal": (4, 1.2, 4),
        "difficile": (6, 1.5, 9),
        "hard": (6, 1.5, 9),
    }.get(value, (4, 1.2, 4))


async def _game_difficulty(bot, guild_id: int | None) -> str:
    if guild_id is None:
        return "normal"
    try:
        settings = await game_rewards.get_settings(bot, guild_id)
        return str(settings.get("default_difficulty") or "normal")
    except Exception:
        return "normal"


def _make_fasttype_challenge(difficulty: str) -> str:
    length, _preview, _bonus = _difficulty_profile(difficulty)
    tokens: list[str] = []
    # Toujours au moins un mot, un nombre et un emoji.
    tokens.append(game_rewards.secure_pick(FASTTYPE_WORDS))
    tokens.append(str(10 + game_rewards.secure_pick(list(range(90)))))
    tokens.append(game_rewards.secure_pick(FASTTYPE_EMOJIS))
    while len(tokens) < length:
        pool_kind = game_rewards.secure_pick(["word", "number", "emoji"])
        if pool_kind == "word":
            tokens.append(game_rewards.secure_pick(FASTTYPE_WORDS))
        elif pool_kind == "number":
            tokens.append(str(game_rewards.secure_pick(list(range(10)))))
        else:
            tokens.append(game_rewards.secure_pick(FASTTYPE_EMOJIS))
    # Pas de phrase statique : chaque manche est unique.
    return " ".join(tokens)


def _make_memory_sequence(difficulty: str) -> list[str]:
    length, _preview, _bonus = _difficulty_profile(difficulty)
    return [game_rewards.secure_pick(MEMORY_TOKENS) for _ in range(length)]


def _reaction_round() -> tuple[list[str], str]:
    """Construit 4 cibles visuelles uniques, dont une seule est correcte."""
    emojis = ["⚡", "🔥", "💎", "⭐", "🌙", "🎯", "🧊", "🪐"]
    numbers = ["2", "3", "4", "5", "7", "8", "9"]
    options: list[str] = []
    while len(options) < 4:
        token = f"{game_rewards.secure_pick(emojis)} {game_rewards.secure_pick(numbers)}"
        if token not in options:
            options.append(token)
    target = game_rewards.secure_pick(options)
    random.shuffle(options)
    return options, target


async def _precheck(bot, ctx: commands.Context, game_name: str, cooldown: int) -> tuple[bool, str, str | None]:
    """Identique à Minigames._start() (cogs/minigames.py) — dupliqué ici en fonction libre
    pour ne pas faire dépendre ce cog du cog Minigames. Vérifie serveur, +gamesetup, salon,
    rôle, cooldown persisté, puis pose le verrou anti-manches-parallèles."""
    if ctx.guild is None:
        return False, "🎮 Les mini-jeux ne sont disponibles que sur un serveur.", None
    guild_id = ctx.guild.id
    role_ids = {r.id for r in ctx.author.roles} if isinstance(ctx.author, discord.Member) else set()
    ok, reason = await game_rewards.is_game_enabled(bot, guild_id, game_name, ctx.channel.id, role_ids)
    if not ok:
        return False, reason, None
    allowed, remaining = await game_rewards.check_cooldown(bot, guild_id, ctx.author.id, game_name, cooldown)
    if not allowed:
        return False, f"⏱️ Encore **{remaining}s** avant de rejouer à ce jeu.", None
    if not game_rewards.acquire_play_lock(guild_id, ctx.author.id, game_name):
        return False, "🎮 Une manche de ce jeu est déjà en cours pour vous.", None
    return True, "", game_rewards.new_session_id(game_name)


def tirer_butin(game_name: str) -> tuple[str, str, str, float] | None:
    """Tire une prise : (emoji, nom, libellé de rareté, multiplicateur).

    Le tirage passe par game_rewards.secure_pick/secure_below : les gains sont
    réels, donc l'aléa doit l'être aussi — pas un random prévisible.
    """
    table = SOLO_LOOT.get(game_name)
    if not table:
        return None
    total = sum(poids for _cle, _libelle, poids, _mult in RARETES)
    tirage = game_rewards.secure_randint(1, total)
    for cle, libelle, poids, multiplicateur in RARETES:
        tirage -= poids
        if tirage <= 0:
            objets = table.get(cle) or table.get("commun") or ()
            if not objets:
                return None
            emoji, nom = game_rewards.secure_pick(list(objets))
            return emoji, nom, libelle, multiplicateur
    return None


async def _finish(
    bot, ctx: commands.Context, game_name: str, session_id: str, result: str, base_amount: int,
    metadata: dict | None = None,
) -> "game_rewards.GameReward | None":
    guild_id = ctx.guild.id
    game_rewards.release_play_lock(guild_id, ctx.author.id, game_name)
    await game_rewards.touch_cooldown(bot, guild_id, ctx.author.id, game_name)
    if result != "win":
        return None
    # reward_game_winner est l'unique autorité sur la limite quotidienne. Il retourne
    # un GameReward(reason="daily_limit") au lieu de faire disparaître l'information :
    # l'UI peut donc dire clairement que seul l'argent est plafonné, jamais le gameplay.
    return await game_rewards.reward_game_winner(
        bot, guild_id, ctx.author.id, game_name, base_amount, session_id, result="win",
        metadata=metadata,
    )


async def _precheck_duel(
    bot,
    ctx: commands.Context,
    game_name: str,
    opponent: discord.Member,
    cooldown: int,
) -> tuple[bool, str, str | None]:
    """Prépare les DEUX participants d'un duel.

    Avant ce helper, seul l'initiateur passait les rôles/salons/cooldowns et le verrou
    était relâché immédiatement : un adversaire interdit pouvait jouer et les duels
    pouvaient être spammés sans cooldown réel.
    """
    started, reason, session_id = await _precheck(bot, ctx, game_name, cooldown)
    if not started:
        return False, reason, None

    guild_id = ctx.guild.id
    opponent_roles = {r.id for r in getattr(opponent, "roles", [])}
    ok, reason = await game_rewards.is_game_enabled(
        bot,
        guild_id,
        game_name,
        ctx.channel.id,
        opponent_roles,
    )
    if not ok:
        game_rewards.release_play_lock(guild_id, ctx.author.id, game_name)
        return False, f"Adversaire non autorisé : {reason}", None

    allowed, remaining = await game_rewards.check_cooldown(
        bot,
        guild_id,
        opponent.id,
        game_name,
        cooldown,
    )
    if not allowed:
        game_rewards.release_play_lock(guild_id, ctx.author.id, game_name)
        return False, f"L'adversaire doit encore attendre **{remaining}s** pour ce jeu.", None

    if not game_rewards.acquire_play_lock(guild_id, opponent.id, game_name):
        game_rewards.release_play_lock(guild_id, ctx.author.id, game_name)
        return False, "L'adversaire a déjà une manche de ce jeu en cours.", None

    return True, "", session_id


async def _finish_duel(
    bot,
    guild_id: int,
    game_name: str,
    p1: discord.Member,
    p2: discord.Member,
) -> None:
    """Libère les deux verrous et démarre le cooldown des deux participants."""
    game_rewards.release_play_lock(guild_id, p1.id, game_name)
    game_rewards.release_play_lock(guild_id, p2.id, game_name)
    await asyncio.gather(
        game_rewards.touch_cooldown(bot, guild_id, p1.id, game_name),
        game_rewards.touch_cooldown(bot, guild_id, p2.id, game_name),
    )


# =============================================================================
# JEUX RAPIDES
# =============================================================================

class GamesRapides(commands.Cog, name="GamesRapides"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="coinflip", description="Pile ou face — devinez le résultat.", with_app_command=False)
    @app_commands.describe(cote="pile ou face")
    async def coinflip(self, ctx: commands.Context, cote: str):
        guild_id = ctx.guild.id if ctx.guild else None
        cote = cote.strip().lower()
        if cote not in ("pile", "face"):
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Pile ou face', description='Précisez `pile` ou `face`.', kind='warning')))
        started, err, sid = await _precheck(self.bot, ctx, "coinflip", 10)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Pile ou face', description=err, kind='warning')))
        # Le résultat est tiré AVANT l'animation : ce qui tourne à l'écran ne
        # décide de rien, et une édition perdue ne peut pas changer la manche.
        result = game_rewards.secure_pick(["pile", "face"])
        faces = {"pile": "🪙", "face": "🌝"}
        message = await panels.envoyer(ctx, panels.depuis_embed(await _embed(
            self.bot, guild_id, title='Pile ou face',
            description=f"🪙 La pièce monte…\nVous avez dit **{cote}**.",
        )))
        for apercu in ("pile", "face"):
            await asyncio.sleep(0.7)
            try:
                await panels.editer(message, panels.depuis_embed(await _embed(
                    self.bot, guild_id, title='Pile ou face',
                    description=f"{faces[apercu]} Elle tourne…\nVous avez dit **{cote}**.",
                )))
            except Exception:
                logger.debug("Animation de pile ou face interrompue.", exc_info=True)
                break
        await asyncio.sleep(0.7)

        if result == cote:
            reward = await _finish(self.bot, ctx, "coinflip", sid, "win", 12)
            desc = f"{faces[result]} **{result.upper()}** — vous aviez vu juste !" + _reward_line(reward)
            kind = "success"
        else:
            await _finish(self.bot, ctx, "coinflip", sid, "loss", 0)
            desc = f"{faces[result]} **{result.upper()}** — raté, vous aviez dit {cote}."
            kind = "danger"
        await panels.editer(message, panels.depuis_embed(await _embed(
            self.bot, guild_id, title='Pile ou face', description=desc, kind=kind,
        )))

    @commands.hybrid_command(name="dice", description="Pariez sur le résultat d'un dé à 6 faces.", with_app_command=False)
    @app_commands.describe(nombre="Votre pari, entre 1 et 6")
    async def dice(self, ctx: commands.Context, nombre: int):
        guild_id = ctx.guild.id if ctx.guild else None
        if not 1 <= nombre <= 6:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Pari sur un dé', description='Choisissez un nombre entre 1 et 6.', kind='warning')))
        started, err, sid = await _precheck(self.bot, ctx, "dice", 10)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Pari sur un dé', description=err, kind='warning')))
        result = game_rewards.secure_pick([1, 2, 3, 4, 5, 6])
        message = await panels.envoyer(ctx, panels.depuis_embed(await _embed(
            self.bot, guild_id, title='Pari sur un dé',
            description=f"🎲 Le dé roule…\nVous avez parié sur {_FACES_DE[nombre]} **{nombre}**.",
        )))
        for _tour in range(2):
            await asyncio.sleep(0.7)
            try:
                await panels.editer(message, panels.depuis_embed(await _embed(
                    self.bot, guild_id, title='Pari sur un dé',
                    description=(
                        f"{_FACES_DE[game_rewards.secure_pick([1, 2, 3, 4, 5, 6])]} Il rebondit…\n"
                        f"Vous avez parié sur {_FACES_DE[nombre]} **{nombre}**."
                    ),
                )))
            except Exception:
                logger.debug("Animation du dé interrompue.", exc_info=True)
                break
        await asyncio.sleep(0.7)

        face = _FACES_DE[result]
        if result == nombre:
            reward = await _finish(self.bot, ctx, "dice", sid, "win", 35)
            desc = f"{face} Le dé s'arrête sur **{result}** — pari gagné !" + _reward_line(reward)
            kind = "success"
        else:
            await _finish(self.bot, ctx, "dice", sid, "loss", 0)
            desc = (
                f"{face} Le dé s'arrête sur **{result}** — vous aviez parié {nombre}.\n"
                "-# Une chance sur six : ça se retente vite."
            )
            kind = "danger"
        await panels.editer(message, panels.depuis_embed(await _embed(
            self.bot, guild_id, title='Pari sur un dé', description=desc, kind=kind,
        )))

    @commands.hybrid_command(name="luckyroll", description="Lancez deux dés — un double rapporte un petit bonus. (+roll existant reste inchangé)", with_app_command=False)
    async def luckyroll(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "luckyroll", 8)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Lancer de dés chanceux', description=err, kind='warning')))
        d1, d2 = game_rewards.secure_pick(range(1, 7)), game_rewards.secure_pick(range(1, 7))
        faces = f"{_FACES_DE[d1]} {_FACES_DE[d2]}"
        if d1 == d2:
            # Le double six est le meilleur des doubles : il mérite d'être signalé.
            montant = 32 if d1 == 6 else 20
            reward = await _finish(self.bot, ctx, "luckyroll", sid, "win", montant)
            titre = "🏆 **DOUBLE SIX !**" if d1 == 6 else f"🎉 **DOUBLE {d1} !**"
            desc = f"## {faces}\n{titre}" + _reward_line(reward)
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Lancer de dés chanceux', description=desc, kind='success')))
        await _finish(self.bot, ctx, "luckyroll", sid, "loss", 0)
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(
            self.bot, guild_id, title='Lancer de dés chanceux',
            description=(
                f"## {faces}\n**{d1} et {d2}** — pas de double cette fois.\n"
                "-# Un double paie 20, un double six en paie 32."
            ),
        )))

    @commands.hybrid_command(name="highlow", description="Le bot tire une carte (1-13). Devinez si la suivante sera plus haute ou plus basse.", with_app_command=False)
    @app_commands.describe(pari="Optionnel : plus_haut ou plus_bas ; sinon utilisez les boutons")
    @app_commands.choices(pari=[app_commands.Choice(name="Plus haut", value="plus_haut"), app_commands.Choice(name="Plus bas", value="plus_bas")])
    async def highlow(self, ctx: commands.Context, pari: str = None):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "highlow", 12)
        if not started:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await _embed(self.bot, guild_id, title="Plus haut ou plus bas", description=err, kind="warning")
                ),
            )

        first = game_rewards.secure_pick(range(1, 14))
        enseigne_1 = game_rewards.secure_pick(_ENSEIGNES)
        carte_1 = _carte_lisible(first, enseigne_1)
        selected = (pari or "").strip().casefold()
        msg = None

        if selected not in {"plus_haut", "plus_bas"}:
            view = _HighLowView(ctx.author.id)
            msg = await panels.envoyer(
                ctx,
                panels.avec_composants(
                    panels.depuis_embed(
                        await _embed(
                            self.bot,
                            guild_id,
                            title="Plus haut ou plus bas",
                            description=(
                                f"🃏 Première carte : {carte_1}\n"
                                "La prochaine sera-t-elle plus haute ou plus basse ?"
                            ),
                        )
                    ),
                    view,
                ),
            )
            await view.wait()
            if view.choice is None:
                await _finish(self.bot, ctx, "highlow", sid, "loss", 0)
                return await panels.editer(
                    msg,
                    panels.depuis_embed(
                        await _embed(
                            self.bot,
                            guild_id,
                            title="Plus haut ou plus bas",
                            description="⏱️ Aucun choix reçu.",
                            kind="warning",
                        )
                    ),
                )
            selected = view.choice

        second = game_rewards.secure_pick(range(1, 14))
        carte_2 = _carte_lisible(second, game_rewards.secure_pick(_ENSEIGNES))
        if second == first:
            await _finish(self.bot, ctx, "highlow", sid, "draw", 0)
            desc = f"🃏 {carte_1} → {carte_2} · égalité, manche nulle."
            kind = "primary"
        else:
            won = (
                (selected == "plus_haut" and second > first)
                or (selected == "plus_bas" and second < first)
            )
            if won:
                # Les cartes proches sont plus difficiles à prédire : petit bonus.
                distance = abs(second - first)
                skill_bonus = 6 if distance <= 2 else 3 if distance <= 4 else 0
                reward = await _finish(self.bot, ctx, "highlow", sid, "win", 18 + skill_bonus)
                desc = (
                    f"🃏 {carte_1} → {carte_2} · bon choix : "
                    f"**{'plus haut' if selected == 'plus_haut' else 'plus bas'}**."
                    + (f"\n🎯 Bonus risque : **+{skill_bonus}**" if skill_bonus else "")
                    + _reward_line(reward)
                )
                kind = "success"
            else:
                await _finish(self.bot, ctx, "highlow", sid, "loss", 0)
                desc = (
                    f"🃏 {carte_1} → {carte_2} · perdu. Vous aviez choisi "
                    f"**{'plus haut' if selected == 'plus_haut' else 'plus bas'}**."
                )
                kind = "danger"

        panel = panels.depuis_embed(
            await _embed(
                self.bot,
                guild_id,
                title="Plus haut ou plus bas — résultat",
                description=desc,
                kind=kind,
            )
        )
        if msg is not None:
            return await panels.editer(msg, panel)
        return await panels.envoyer(ctx, panel)

    @commands.hybrid_command(name="memory", description="Mémorisez une séquence d'emojis puis retapez-la dans l'ordre.", with_app_command=False)
    async def memory(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "memory", 20)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Mémoire', description=err, kind='warning')))

        difficulty = await _game_difficulty(self.bot, guild_id)
        sequence = _make_memory_sequence(difficulty)
        _length, preview_seconds, bonus = _difficulty_profile(difficulty)
        prompt = await panels.envoyer(
            ctx,
            panels.avec_composants(
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Mémoire — observez",
                        description=(
                            f"🧠 Niveau **{difficulty}** · {len(sequence)} symboles\n"
                            "Mémorisez les boutons ci-dessous : ils ne sont pas sélectionnables "
                            "et disparaissent avant la phase de réponse."
                        ),
                    )
                ),
                _PreviewTokensView(sequence),
            ),
        )
        await asyncio.sleep(preview_seconds)
        await panels.editer(
            prompt,
            panels.depuis_embed(
                await _embed(
                    self.bot,
                    guild_id,
                    title="Mémoire — à vous",
                    description=(
                        "🎯 Retapez maintenant la séquence **dans le même ordre**, "
                        "avec des espaces. Vous avez **20 secondes**."
                    ),
                )
            ),
        )

        started_at = time.monotonic()

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            await _finish(self.bot, ctx, "memory", sid, "loss", 0)
            return await panels.editer(
                prompt,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Mémoire — temps écoulé",
                        description=f"⏱️ La séquence était : **{'  '.join(sequence)}**",
                        kind="warning",
                    )
                ),
            )

        elapsed = time.monotonic() - started_at
        if msg.content.split() == sequence:
            speed_bonus = max(0, 8 - int(elapsed))
            reward = await _finish(self.bot, ctx, "memory", sid, "win", 25 + bonus + speed_bonus)
            return await panels.editer(
                prompt,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Mémoire — parfait",
                        description=(
                            f"🧠 **{len(sequence)}/{len(sequence)}** corrects en **{elapsed:.1f}s**.\n"
                            f"⚡ Bonus vitesse : **+{speed_bonus}**"
                        ) + _reward_line(reward),
                        kind="success",
                    )
                ),
            )

        await _finish(self.bot, ctx, "memory", sid, "loss", 0)
        await panels.editer(
            prompt,
            panels.depuis_embed(
                await _embed(
                    self.bot,
                    guild_id,
                    title="Mémoire — raté",
                    description=f"❌ Bonne séquence : **{'  '.join(sequence)}**",
                    kind="danger",
                )
            ),
        )

    @commands.hybrid_command(name="reaction", description="Cliquez sur le bouton dès qu'il apparaît, le plus vite possible.", with_app_command=False)
    async def reaction(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "reaction", 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Réaction rapide', description=err, kind='warning')))

        options, target = _reaction_round()
        msg = await panels.envoyer(
            ctx,
            panels.depuis_embed(
                await _embed(
                    self.bot,
                    guild_id,
                    title="Réaction — préparez-vous",
                    description=(
                        f"🎯 Quand les boutons apparaissent, cliquez sur **{target}**.\n"
                        "Attention : les autres boutons sont des leurres."
                    ),
                )
            ),
        )
        await asyncio.sleep(random.uniform(1.8, 4.2))

        view = _ReactionSoloView(author_id=ctx.author.id, options=options, target=target)
        await panels.editer(
            msg,
            panels.avec_composants(
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Réaction — GO",
                        description=f"⚡ **CIBLE : {target}** · trouvez-la parmi les 4 boutons.",
                    )
                ),
                view,
            ),
        )
        await view.wait()

        if view.correct is None:
            await _finish(self.bot, ctx, "reaction", sid, "loss", 0)
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(self.bot, guild_id, title="Réaction — temps écoulé", description="⏱️ Trop lent.", kind="warning")
                ),
            )
        if not view.correct:
            await _finish(self.bot, ctx, "reaction", sid, "loss", 0)
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Réaction — mauvais bouton",
                        description=f"❌ La cible était **{target}**.",
                        kind="danger",
                    )
                ),
            )

        elapsed = view.elapsed or 0.0
        amount = 36 if elapsed < 0.55 else 28 if elapsed < 1.0 else 20
        reward = await _finish(self.bot, ctx, "reaction", sid, "win", amount)
        await panels.editer(
            msg,
            panels.depuis_embed(
                await _embed(
                    self.bot,
                    guild_id,
                    title="Réaction — réussi",
                    description=f"⚡ Bonne cible en **{elapsed:.2f}s** !" + _reward_line(reward),
                    kind="success",
                )
            ),
        )

    @commands.hybrid_command(name="scramble", description="Remettez les lettres d'un mot mélangé dans le bon ordre.", with_app_command=False)
    async def scramble(self, ctx: commands.Context):
        await _run_word_guess(self.bot, ctx, "scramble", pool=["discord", "python", "serveur", "modération", "aventure", "chevalier"], cooldown=15, mode="scramble")

    @commands.hybrid_command(name="wordgame", description="Devinez le mot correspondant à sa définition.", with_app_command=False)
    async def wordgame(self, ctx: commands.Context):
        await _run_word_guess(self.bot, ctx, "wordgame", pool=WORDGAME_CLUES, cooldown=15, mode="clue")

    @commands.hybrid_command(name="emojiquiz", description="Devinez le mot ou l'expression représentée par des emojis.", with_app_command=False)
    async def emojiquiz(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "emojiquiz", 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Quiz emoji', description=err, kind='warning')))
        emojis, answer, difficulty = game_rewards.secure_pick(EMOJI_QUIZ)
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Quiz emoji', description=f'🧩 {emojis}\nVous avez 20 secondes.')))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            await _finish(self.bot, ctx, "emojiquiz", sid, "loss", 0)
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Temps écoulé', description=f'⏱️ La réponse était **{_primary_answer(answer)}**.', kind='warning')))
        if game_rewards.answer_matches(msg.content, answer):
            amount = game_rewards.skill_reward(20, difficulty=difficulty)
            reward = await _finish(self.bot, ctx, "emojiquiz", sid, "win", amount)
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Bonne réponse !', description=f'✅ Difficulté **{difficulty}**.' + _reward_line(reward), kind='success')))
        else:
            await _finish(self.bot, ctx, "emojiquiz", sid, "loss", 0)
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Mauvaise réponse', description=f'❌ La réponse était **{_primary_answer(answer)}**.', kind='danger')))

    @commands.hybrid_command(name="colorquiz", description="Cliquez sur la bonne couleur.", with_app_command=False)
    async def colorquiz(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "colorquiz", 10)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Quiz couleur', description=err, kind='warning')))
        options = list(COLOR_EMOJIS.items())
        random.shuffle(options)
        options = options[:4]
        target_name, target_emoji = game_rewards.secure_pick(options)
        view = _ColorQuizView(author_id=ctx.author.id, options=options, target=target_name)
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title='Quiz couleur', description=f'🎨 Cliquez sur **{target_name.upper()}**')), view))
        await view.wait()
        if view.correct is None:
            await _finish(self.bot, ctx, "colorquiz", sid, "loss", 0)
        elif view.correct:
            reward = await _finish(self.bot, ctx, "colorquiz", sid, "win", 15)
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Quiz couleur', description='✅ Bonne couleur !' + _reward_line(reward), kind='success')))
        else:
            await _finish(self.bot, ctx, "colorquiz", sid, "loss", 0)
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Quiz couleur', description='❌ Mauvaise couleur.', kind='danger')))

    @commands.hybrid_command(
        name="minesweeper",
        description="Démineur interactif : ouvrez toutes les cases sûres sans toucher une bombe.",
        with_app_command=False,
    )
    async def minesweeper(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "minesweeper", 10)
        if not started:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Démineur",
                        description=err,
                        kind="warning",
                    )
                ),
            )

        difficulty = await _game_difficulty(self.bot, guild_id)
        bomb_count = {
            "facile": 4,
            "easy": 4,
            "normal": 6,
            "difficile": 8,
            "hard": 8,
        }.get(difficulty.casefold(), 6)
        view = _MinesweeperView(
            bot=self.bot,
            ctx=ctx,
            session_id=sid,
            bomb_count=bomb_count,
            difficulty=difficulty,
        )
        embed = await view.make_embed(
            "💣 Ouvrez les cases. Le chiffre indique combien de bombes touchent cette case."
        )
        msg = await panels.envoyer(
            ctx,
            panels.avec_composants(panels.depuis_embed(embed), view),
        )
        view.message = msg

    @commands.hybrid_command(name="fasttype", description="Retapez la phrase affichée le plus vite et le plus précisément possible.", with_app_command=False)
    async def fasttype(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, "fasttype", 15)
        if not started:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await _embed(self.bot, guild_id, title="Course de vitesse", description=err, kind="warning")
                ),
            )

        difficulty = await _game_difficulty(self.bot, guild_id)
        challenge = _make_fasttype_challenge(difficulty)
        _length, ready_delay, bonus = _difficulty_profile(difficulty)
        challenge_tokens = challenge.split()

        msg = await panels.envoyer(
            ctx,
            panels.depuis_embed(
                await _embed(
                    self.bot,
                    guild_id,
                    title="Course de vitesse — préparez-vous",
                    description=(
                        "⌨️ **But du jeu**\n"
                        "Dans un instant, un petit code apparaît sous forme de cases.\n"
                        "Recopiez-le **dans le chat**, dans le même ordre, avec un espace entre chaque case.\n\n"
                        "🧪 Exemple : NOVA 7 🔥 2\n"
                        f"🎚️ Difficulté : **{difficulty}** · {len(challenge_tokens)} cases\n"
                        "⏳ Préparez-vous..."
                    ),
                )
            ),
        )
        await asyncio.sleep(ready_delay)

        token_view = _PreviewTokensView(challenge_tokens)
        await panels.editer(
            msg,
            panels.avec_composants(
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Course de vitesse — GO",
                        description=(
                            "⚡ **GO ! Recopiez les cases ci-dessous dans le chat.**\n"
                            "Les cases restent visibles : pas besoin de mémoriser.\n"
                            "Elles ne sont pas sélectionnables, donc pas de simple copier-coller.\n"
                            "⏱️ Vous avez **20 secondes**."
                        ),
                    )
                ),
                token_view,
            ),
        )
        start_time = time.monotonic()

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            answer = await self.bot.wait_for("message", check=check, timeout=20)
        except asyncio.TimeoutError:
            await _finish(self.bot, ctx, "fasttype", sid, "loss", 0)
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Course de vitesse — temps écoulé",
                        description=f"⏱️ Le code était : **{challenge}**\n🔁 Réessayez dans quelques secondes.",
                        kind="warning",
                    )
                ),
            )

        elapsed = time.monotonic() - start_time
        if game_rewards.normalize_answer(answer.content) != game_rewards.normalize_answer(challenge):
            await _finish(self.bot, ctx, "fasttype", sid, "loss", 0)
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Course de vitesse — presque",
                        description=(
                            f"❌ Votre réponse : **{answer.content.strip() or 'vide'}**\n"
                            f"✅ Il fallait écrire : **{challenge}**\n"
                            "Astuce : gardez bien un espace entre chaque case."
                        ),
                        kind="danger",
                    )
                ),
            )

        speed_bonus = 12 if elapsed < 5 else 7 if elapsed < 9 else 3
        reward = await _finish(self.bot, ctx, "fasttype", sid, "win", 18 + bonus + speed_bonus)
        await panels.editer(
            msg,
            panels.depuis_embed(
                await _embed(
                    self.bot,
                    guild_id,
                    title="Course de vitesse — réussi",
                    description=(
                        f"🏁 Code exact en **{elapsed:.1f}s**.\n"
                        f"⚡ Bonus vitesse : **+{speed_bonus}**"
                    ) + _reward_line(reward),
                    kind="success",
                )
            ),
        )

async def _run_word_guess(bot, ctx: commands.Context, game_name: str, pool, cooldown: int, mode: str):
    guild_id = ctx.guild.id if ctx.guild else None
    started, err, sid = await _precheck(bot, ctx, game_name, cooldown)
    if not started:
        return await panels.envoyer(ctx, panels.depuis_embed(await _embed(bot, guild_id, title='Devine le mot', description=err, kind='warning')))
    if mode == "scramble":
        word = game_rewards.secure_pick(pool)
        letters = list(word)
        random.shuffle(letters)
        scrambled = "".join(letters)
        prompt = f"🔤 Remettez les lettres dans l'ordre : **{scrambled.upper()}**"
        answer = word
    else:
        clue, answer, difficulty = game_rewards.secure_pick(pool)
        prompt = f"📖 {clue}"
    await panels.envoyer(ctx, panels.depuis_embed(await _embed(bot, guild_id, title='Devine le mot', description=f'{prompt}\nVous avez 20 secondes.')))

    def check(m):
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

    try:
        msg = await bot.wait_for("message", check=check, timeout=20)
    except asyncio.TimeoutError:
        await _finish(bot, ctx, game_name, sid, "loss", 0)
        return await panels.envoyer(ctx, panels.depuis_embed(await _embed(bot, guild_id, title='Temps écoulé', description=f'⏱️ La réponse était **{_primary_answer(answer)}**.', kind='warning')))
    if game_rewards.answer_matches(msg.content, answer):
        amount = 20 if mode == "scramble" else game_rewards.skill_reward(20, difficulty=difficulty, attempts=1, max_attempts=1)
        reward = await _finish(bot, ctx, game_name, sid, "win", amount)
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(bot, guild_id, title='Bonne réponse !', description='✅' + _reward_line(reward), kind='success')))
    else:
        await _finish(bot, ctx, game_name, sid, "loss", 0)
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(bot, guild_id, title='Mauvaise réponse', description=f'❌ La réponse était **{_primary_answer(answer)}**.', kind='danger')))


class _PreviewTokensView(discord.ui.View):
    """Affiche un code en boutons désactivés : visible, mais pas sélectionnable/copier-coller."""

    def __init__(self, tokens: list[str]):
        super().__init__(timeout=None)
        visual_emojis = set(FASTTYPE_EMOJIS) | {
            item for item in MEMORY_TOKENS if not str(item).isdigit()
        }
        for index, token in enumerate(tokens[:20]):
            value = str(token)
            is_emoji = value in visual_emojis
            self.add_item(
                discord.ui.Button(
                    label=" " if is_emoji else value[:80],
                    emoji=value if is_emoji else None,
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    row=index // 5,
                )
            )


class _ReactionSoloView(discord.ui.View):
    def __init__(self, author_id: int, options: list[str], target: str):
        super().__init__(timeout=6)
        self.author_id = author_id
        self.target = target
        self.correct: bool | None = None
        self.elapsed: float | None = None
        self._start = time.monotonic()
        self._lock = asyncio.Lock()
        for token in options:
            self.add_item(_ReactionButton(token, is_target=(token == target)))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            if not interaction.response.is_done():
                await interaction.response.send_message("Cette manche appartient à un autre joueur.", ephemeral=True)
            return False
        return True


class _ReactionButton(discord.ui.Button):
    def __init__(self, token: str, *, is_target: bool):
        parts = str(token).split(maxsplit=1)
        emoji = parts[0] if len(parts) == 2 else None
        label = parts[1] if len(parts) == 2 else str(token)
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)
        self.is_target = is_target

    async def callback(self, interaction: discord.Interaction):
        view: _ReactionSoloView = panels.vue_source(self)
        async with view._lock:
            if view.correct is not None:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Cette manche est déjà terminée.", ephemeral=True)
                return
            view.correct = self.is_target
            view.elapsed = time.monotonic() - view._start
            for child in view.children:
                child.disabled = True
            self.style = discord.ButtonStyle.success if self.is_target else discord.ButtonStyle.danger
            await interaction.response.edit_message(view=panels.vue_panneau(self))
            panels.terminer_vue(self)


class _MinesweeperView(discord.ui.View):
    SIZE = 5

    def __init__(
        self,
        *,
        bot,
        ctx: commands.Context,
        session_id: str,
        bomb_count: int,
        difficulty: str,
    ):
        super().__init__(timeout=90)
        self.bot = bot
        self.ctx = ctx
        self.session_id = session_id
        self.guild_id = ctx.guild.id
        self.author_id = ctx.author.id
        self.bomb_count = max(2, min(int(bomb_count), 10))
        self.difficulty = difficulty
        self.bombs = set(random.SystemRandom().sample(range(self.SIZE * self.SIZE), self.bomb_count))
        self.revealed: set[int] = set()
        self.message: discord.Message | None = None
        self._settled = False
        self._lock = asyncio.Lock()

        for index in range(self.SIZE * self.SIZE):
            self.add_item(_MinesweeperButton(index))

    @property
    def safe_target(self) -> int:
        return self.SIZE * self.SIZE - self.bomb_count

    def adjacent_bombs(self, index: int) -> int:
        row, col = divmod(index, self.SIZE)
        total = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if 0 <= nr < self.SIZE and 0 <= nc < self.SIZE:
                    total += (nr * self.SIZE + nc) in self.bombs
        return int(total)

    async def make_embed(self, status: str, *, kind: str = "primary") -> discord.Embed:
        return await _embed(
            self.bot,
            self.guild_id,
            title=f"Démineur — {self.difficulty}",
            description=(
                f"{status}\n\n"
                f"💣 Bombes : **{self.bomb_count}** · "
                f"✅ Cases sûres ouvertes : **{len(self.revealed)}/{self.safe_target}**\n"
                "🔢 0–8 = bombes autour de la case · touchez une bombe et la manche est perdue."
            ),
            kind=kind,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ce démineur appartient à un autre joueur.",
                    ephemeral=True,
                )
            return False
        return True

    async def settle_loss(self, interaction: discord.Interaction, hit_index: int) -> None:
        if self._settled:
            return
        self._settled = True
        for child in self.children:
            child.disabled = True
            if isinstance(child, _MinesweeperButton) and child.index in self.bombs:
                child.label = "💣"
                child.style = discord.ButtonStyle.danger
        await _finish(self.bot, self.ctx, "minesweeper", self.session_id, "loss", 0)
        embed = await self.make_embed(
            f"💥 Bombe touchée sur la case **{hit_index + 1}**. Manche perdue.",
            kind="danger",
        )
        await panels.editer(interaction.response, panels.depuis_embed(embed))
        self.stop()
        panel = getattr(self, "_sentrix_panel_view", None)
        if panel is not None:
            panel.stop()

    async def settle_win(self, interaction: discord.Interaction) -> None:
        if self._settled:
            return
        self._settled = True
        for child in self.children:
            child.disabled = True
        _length, _preview, difficulty_bonus = _difficulty_profile(self.difficulty)
        reward = await _finish(
            self.bot,
            self.ctx,
            "minesweeper",
            self.session_id,
            "win",
            40 + difficulty_bonus,
        )
        embed = await self.make_embed(
            "🏆 Grille nettoyée : toutes les cases sûres ont été ouvertes."
            + _reward_line(reward),
            kind="success",
        )
        await panels.editer(interaction.response, panels.depuis_embed(embed))
        self.stop()
        panel = getattr(self, "_sentrix_panel_view", None)
        if panel is not None:
            panel.stop()

    async def on_timeout(self):
        if self._settled:
            return
        self._settled = True
        for child in self.children:
            child.disabled = True
        await _finish(self.bot, self.ctx, "minesweeper", self.session_id, "loss", 0)
        if self.message is not None:
            try:
                embed = await self.make_embed("⏱️ Partie expirée.", kind="warning")
                await panels.editer(self.message, panels.depuis_embed(embed))
            except discord.HTTPException:
                pass


class _MinesweeperButton(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(
            label="·",
            style=discord.ButtonStyle.secondary,
            row=index // _MinesweeperView.SIZE,
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: _MinesweeperView = panels.vue_source(self)
        async with view._lock:
            if view._settled or self.index in view.revealed:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Cette case est déjà ouverte.",
                        ephemeral=True,
                    )
                return

            if self.index in view.bombs:
                return await view.settle_loss(interaction, self.index)

            view.revealed.add(self.index)
            around = view.adjacent_bombs(self.index)
            self.label = str(around) if around else "0"
            self.disabled = True
            self.style = (
                discord.ButtonStyle.primary if around else discord.ButtonStyle.success
            )

            if len(view.revealed) >= view.safe_target:
                return await view.settle_win(interaction)

            # Les boutons vivent dans le Panneau Components V2 : leurs labels/styles
            # changent directement dans cette LayoutView. On accuse réception sans
            # tenter de réinjecter un embed classique (interdit par Discord).
            await interaction.response.edit_message(view=panels.vue_panneau(self))


class _HighLowView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=20)
        self.author_id = author_id
        self.choice: str | None = None
        self._lock = asyncio.Lock()
        self.add_item(_HighLowButton("⬆️ Plus haut", "plus_haut", discord.ButtonStyle.success))
        self.add_item(_HighLowButton("⬇️ Plus bas", "plus_bas", discord.ButtonStyle.primary))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            if not interaction.response.is_done():
                await interaction.response.send_message("Cette manche appartient à un autre joueur.", ephemeral=True)
            return False
        return True


class _HighLowButton(discord.ui.Button):
    def __init__(self, label: str, choice: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        view: _HighLowView = panels.vue_source(self)
        async with view._lock:
            if view.choice is not None:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Choix déjà enregistré.", ephemeral=True)
                return
            view.choice = self.choice
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(view=panels.vue_panneau(self))
            panels.terminer_vue(self)


class _ColorQuizView(discord.ui.View):
    def __init__(self, author_id: int, options: list, target: str):
        super().__init__(timeout=15)
        self.author_id = author_id
        self.correct = None
        for name, emoji in options:
            self.add_item(_ColorButton(name, emoji, is_target=(name == target)))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce n'est pas votre partie.", ephemeral=True)
            return False
        return True


class _ColorButton(discord.ui.Button):
    def __init__(self, name: str, emoji: str, is_target: bool):
        super().__init__(label=name.capitalize(), emoji=emoji, style=discord.ButtonStyle.secondary)
        self.is_target = is_target

    async def callback(self, interaction: discord.Interaction):
        view: _ColorQuizView = panels.vue_source(self)
        view.correct = self.is_target
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=panels.vue_panneau(self))
        panels.terminer_vue(self)


# =============================================================================
# DUELS (1 contre 1) — choix privés jusqu'à ce que les DEUX joueurs aient répondu, comme
# demandé par Jayden. Aucune mise n'est prélevée au perdant : seul le gagnant reçoit une
# récompense (pas de pari entre joueurs, uniquement contre la "banque" virtuelle du bot).
# =============================================================================

class GamesDuels(commands.Cog, name="GamesDuels"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="duel", description="Défier un membre en pierre-feuille-ciseaux (récompense au gagnant).", with_app_command=False)
    @app_commands.describe(adversaire="Le membre à défier")
    async def duel(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel', description=invalid, kind='danger')))
        started, err, sid = await _precheck_duel(self.bot, ctx, "duel", adversaire, 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel', description=err, kind='warning')))
  # le verrou individuel ne s'applique pas aux duels à 2
        view = _RPSDuelView(cog=self, guild_id=guild_id, p1=ctx.author, p2=adversaire, session_id=sid)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel — Pierre-feuille-ciseaux', description=f'⚔️ {ctx.author.mention} défie {adversaire.mention} !\nCliquez sur le bouton pour faire votre choix EN PRIVÉ.')), view))
        view.message = msg

    @commands.hybrid_command(name="numberduel", description="Duel : chacun choisit un nombre secret entre 1 et 100, le plus proche gagne.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre à défier")
    async def numberduel(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel du nombre secret', description=invalid, kind='danger')))
        started, err, sid = await _precheck_duel(self.bot, ctx, "numberduel", adversaire, 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel du nombre secret', description=err, kind='warning')))

        view = _NumberDuelView(cog=self, guild_id=guild_id, p1=ctx.author, p2=adversaire, session_id=sid)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel du nombre secret', description=f'🔢 {ctx.author.mention} vs {adversaire.mention}\nLe bot a choisi un nombre secret entre 1 et 100. Cliquez pour proposer le vôtre EN PRIVÉ.')), view))
        view.message = msg

    @commands.hybrid_command(name="quizduel", description="Duel de quiz : répondez en privé, le plus rapide des bonnes réponses gagne.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre à défier")
    async def quizduel(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de quiz', description=invalid, kind='danger')))
        started, err, sid = await _precheck_duel(self.bot, ctx, "quizduel", adversaire, 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de quiz', description=err, kind='warning')))

        question, answer, difficulty = game_rewards.secure_pick(WORDGAME_CLUES)
        view = _QuizDuelView(cog=self, guild_id=guild_id, p1=ctx.author, p2=adversaire, session_id=sid, answer=answer)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de quiz', description=f'❓ {ctx.author.mention} vs {adversaire.mention}\n**{question}**\nDifficulté : **{difficulty}**\nCliquez pour répondre EN PRIVÉ.')), view))
        view.message = msg

    @commands.hybrid_command(name="reactionduel", description="Duel de réaction : soyez le premier à cliquer quand le bouton apparaît.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre à défier")
    async def reactionduel(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de réaction', description=invalid, kind='danger')))
        started, err, sid = await _precheck_duel(self.bot, ctx, "reactionduel", adversaire, 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de réaction', description=err, kind='warning')))

        msg = await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de réaction', description=f'⚡ {ctx.author.mention} vs {adversaire.mention}\n⏳ Préparez-vous...')))
        await asyncio.sleep(random.uniform(2.0, 6.0))
        view = _ReactionDuelView(p1=ctx.author, p2=adversaire)
        await panels.editer(msg, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de réaction', description='🔴 **MAINTENANT !**')), view))
        await view.wait()
        await _finish_duel(self.bot, guild_id, "reactionduel", ctx.author, adversaire)
        if view.winner is None:
            await game_rewards.reward_game_winner(self.bot, guild_id, ctx.author.id, "reactionduel", 0, sid, result="draw")
            return await panels.editer(msg, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de réaction', description="⏱️ Personne n'a cliqué à temps.")))
        reward = await game_rewards.reward_game_winner(self.bot, guild_id, view.winner.id, "reactionduel", 35, sid, result="win")
        await panels.editer(msg, panels.depuis_embed(await _embed(self.bot, guild_id, title='Duel de réaction', description=f'⚡ {view.winner.mention} a été le plus rapide !' + _reward_line(reward), kind='success')))

    @commands.hybrid_command(name="connect4", description="Jouer au Puissance 4 contre un autre membre.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre à défier")
    async def connect4(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Puissance 4', description=invalid, kind='danger')))
        started, err, sid = await _precheck_duel(self.bot, ctx, "connect4", adversaire, 15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Puissance 4', description=err, kind='warning')))

        view = ConnectFourView(cog=self, guild_id=guild_id, p1=ctx.author, p2=adversaire, session_id=sid)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title='Puissance 4', description=view.render(f'Au tour de {ctx.author.mention} (🔴)'))), view))
        view.message = msg


class _RPSPickView(discord.ui.View):
    def __init__(self, outer: "_RPSDuelView", picker: discord.Member):
        super().__init__(timeout=60)
        self.outer = outer
        self.picker = picker
        for label, value in (("🪨 Pierre", "pierre"), ("📄 Feuille", "feuille"), ("✂️ Ciseaux", "ciseaux")):
            self.add_item(_RPSPickButton(label, value))


class _RPSPickButton(discord.ui.Button):
    def __init__(self, label: str, value: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.value = value

    async def callback(self, interaction: discord.Interaction):
        view: _RPSPickView = panels.vue_source(self)
        view.outer.choices[view.picker.id] = self.value
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"✅ Choix enregistré : **{self.value}**", view=view)
        await view.outer.maybe_resolve()


class _RPSDuelView(discord.ui.View):
    def __init__(self, cog: "GamesDuels", guild_id: int, p1: discord.Member, p2: discord.Member, session_id: str):
        super().__init__(timeout=90)
        self.cog = cog
        self.guild_id = guild_id
        self.p1, self.p2 = p1, p2
        self.session_id = session_id
        self.choices: dict[int, str] = {}
        self.message: discord.Message | None = None
        self._settled = False
        self.add_item(_RPSDuelButton())

    async def on_timeout(self):
        if self._settled or self.message is None:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "duel", self.p1, self.p2)
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="⏱️ Duel expiré (l'un des deux joueurs n'a pas répondu).", view=self)
        except Exception:
            logger.warning("Étape non critique ignorée dans on_timeout", exc_info=True)

    async def maybe_resolve(self):
        if self._settled or len(self.choices) < 2:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "duel", self.p1, self.p2)
        c1, c2 = self.choices[self.p1.id], self.choices[self.p2.id]
        if c1 == c2:
            winner = None
        elif RPS_BEATS[c1] == c2:
            winner = self.p1
        else:
            winner = self.p2
        for child in self.children:
            child.disabled = True
        if winner is None:
            await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, self.p1.id, "duel", 0, self.session_id, result="draw")
            desc = f"⚔️ {self.p1.mention} : **{c1}** | {self.p2.mention} : **{c2}**\n🤝 Égalité !"
        else:
            reward = await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, winner.id, "duel", 35, self.session_id, result="win")
            desc = f"⚔️ {self.p1.mention} : **{c1}** | {self.p2.mention} : **{c2}**\n🏆 {winner.mention} gagne !" + _reward_line(reward)
        if self.message:
            await self.message.edit(embed=await _embed(self.cog.bot, self.guild_id, title="Duel — Pierre-feuille-ciseaux", description=desc, kind="success" if winner else "primary"), view=self)


class _RPSDuelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🎯 Faire mon choix", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        view: _RPSDuelView = panels.vue_source(self)
        if interaction.user.id not in (view.p1.id, view.p2.id):
            return await interaction.response.send_message("❌ Ce duel ne vous concerne pas.", ephemeral=True)
        if interaction.user.id in view.choices:
            return await interaction.response.send_message("✅ Vous avez déjà fait votre choix.", ephemeral=True)
        await interaction.response.send_message("Faites votre choix :", view=_RPSPickView(view, interaction.user), ephemeral=True)


class _NumberDuelModal(discord.ui.Modal, title="Duel du nombre secret"):
    nombre = discord.ui.TextInput(label="Votre nombre (1-100)", placeholder="ex: 42", max_length=3)

    def __init__(self, outer: "_NumberDuelView", picker: discord.Member):
        super().__init__()
        self.outer = outer
        self.picker = picker

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.nombre.value).strip())
            assert 1 <= value <= 100
        except (ValueError, AssertionError):
            return await interaction.response.send_message("❌ Entrez un nombre entier entre 1 et 100.", ephemeral=True)
        self.outer.choices[self.picker.id] = value
        await interaction.response.send_message(f"✅ Nombre enregistré : **{value}**", ephemeral=True)
        await self.outer.maybe_resolve()


class _NumberDuelView(discord.ui.View):
    def __init__(self, cog: "GamesDuels", guild_id: int, p1: discord.Member, p2: discord.Member, session_id: str):
        super().__init__(timeout=90)
        self.cog = cog
        self.guild_id = guild_id
        self.p1, self.p2 = p1, p2
        self.session_id = session_id
        self.target = game_rewards.secure_pick(range(1, 101))
        self.choices: dict[int, int] = {}
        self.message: discord.Message | None = None
        self._settled = False
        self.add_item(_DuelModalButton("🎯 Proposer mon nombre"))

    async def on_timeout(self):
        if self._settled or self.message is None:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "numberduel", self.p1, self.p2)
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="⏱️ Duel expiré.", view=self)
        except Exception:
            logger.warning("Étape non critique ignorée dans on_timeout", exc_info=True)

    async def open_modal(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            return await interaction.response.send_message("❌ Ce duel ne vous concerne pas.", ephemeral=True)
        if interaction.user.id in self.choices:
            return await interaction.response.send_message("✅ Vous avez déjà proposé un nombre.", ephemeral=True)
        await interaction.response.send_modal(_NumberDuelModal(self, interaction.user))

    async def maybe_resolve(self):
        if self._settled or len(self.choices) < 2:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "numberduel", self.p1, self.p2)
        n1, n2 = self.choices[self.p1.id], self.choices[self.p2.id]
        d1, d2 = abs(n1 - self.target), abs(n2 - self.target)
        for child in self.children:
            child.disabled = True
        if d1 == d2:
            await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, self.p1.id, "numberduel", 0, self.session_id, result="draw")
            desc = f"🔢 Nombre secret : **{self.target}**\n{self.p1.mention} : {n1} | {self.p2.mention} : {n2}\n🤝 Égalité !"
            kind = "primary"
        else:
            winner = self.p1 if d1 < d2 else self.p2
            reward = await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, winner.id, "numberduel", 35, self.session_id, result="win")
            desc = f"🔢 Nombre secret : **{self.target}**\n{self.p1.mention} : {n1} | {self.p2.mention} : {n2}\n🏆 {winner.mention} était le plus proche !" + _reward_line(reward)
            kind = "success"
        if self.message:
            await self.message.edit(embed=await _embed(self.cog.bot, self.guild_id, title="Duel du nombre secret", description=desc, kind=kind), view=self)


class _QuizDuelModal(discord.ui.Modal, title="Duel de quiz"):
    reponse = discord.ui.TextInput(label="Votre réponse", max_length=100)

    def __init__(self, outer: "_QuizDuelView", picker: discord.Member):
        super().__init__()
        self.outer = outer
        self.picker = picker

    async def on_submit(self, interaction: discord.Interaction):
        self.outer.choices[self.picker.id] = (str(self.reponse.value).strip().lower(), time.monotonic())
        await interaction.response.send_message("✅ Réponse enregistrée.", ephemeral=True)
        await self.outer.maybe_resolve()


class _QuizDuelView(discord.ui.View):
    def __init__(self, cog: "GamesDuels", guild_id: int, p1: discord.Member, p2: discord.Member, session_id: str, answer: str):
        super().__init__(timeout=90)
        self.cog = cog
        self.guild_id = guild_id
        self.p1, self.p2 = p1, p2
        self.session_id = session_id
        self.answer = answer
        self.choices: dict[int, tuple] = {}
        self.message: discord.Message | None = None
        self._settled = False
        self.add_item(_DuelModalButton("✏️ Répondre"))

    async def on_timeout(self):
        if self._settled or self.message is None:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "quizduel", self.p1, self.p2)
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="⏱️ Duel expiré.", view=self)
        except Exception:
            logger.warning("Étape non critique ignorée dans on_timeout", exc_info=True)

    async def open_modal(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            return await interaction.response.send_message("❌ Ce duel ne vous concerne pas.", ephemeral=True)
        if interaction.user.id in self.choices:
            return await interaction.response.send_message("✅ Vous avez déjà répondu.", ephemeral=True)
        await interaction.response.send_modal(_QuizDuelModal(self, interaction.user))

    async def maybe_resolve(self):
        if self._settled or len(self.choices) < 2:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "quizduel", self.p1, self.p2)
        (a1, t1), (a2, t2) = self.choices[self.p1.id], self.choices[self.p2.id]
        c1, c2 = game_rewards.answer_matches(a1, self.answer), game_rewards.answer_matches(a2, self.answer)
        for child in self.children:
            child.disabled = True
        if c1 and c2:
            winner = self.p1 if t1 <= t2 else self.p2
        elif c1:
            winner = self.p1
        elif c2:
            winner = self.p2
        else:
            winner = None
        if winner is None:
            await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, self.p1.id, "quizduel", 0, self.session_id, result="loss")
            desc = f"❓ Bonne réponse : **{_primary_answer(self.answer)}**\nPersonne n'a trouvé — pas de gagnant."
            kind = "danger"
        else:
            reward = await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, winner.id, "quizduel", 30, self.session_id, result="win")
            desc = f"❓ Bonne réponse : **{_primary_answer(self.answer)}**\n🏆 {winner.mention} gagne !" + _reward_line(reward)
            kind = "success"
        if self.message:
            await self.message.edit(embed=await _embed(self.cog.bot, self.guild_id, title="Duel de quiz", description=desc, kind=kind), view=self)


class _DuelModalButton(discord.ui.Button):
    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await panels.vue_source(self).open_modal(interaction)


class _ReactionDuelView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=10)
        self.p1, self.p2 = p1, p2
        self.winner: discord.Member | None = None
        self.add_item(_ReactionDuelButton())


class _ReactionDuelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔴 CLIQUEZ !", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        view: _ReactionDuelView = panels.vue_source(self)
        if interaction.user.id not in (view.p1.id, view.p2.id):
            return await interaction.response.send_message("❌ Ce duel ne vous concerne pas.", ephemeral=True)
        if view.winner is not None:
            return await interaction.response.send_message("❌ Trop tard, quelqu'un a déjà cliqué.", ephemeral=True)
        view.winner = interaction.user
        self.disabled = True
        await interaction.response.defer()
        panels.terminer_vue(self)


class ConnectFourView(discord.ui.View):
    ROWS, COLS = 6, 7
    SYMBOLS = {"p1": "🔴", "p2": "🟡", "empty": "⚪"}

    def __init__(self, cog: "GamesDuels", guild_id: int, p1: discord.Member, p2: discord.Member, session_id: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.p1, self.p2 = p1, p2
        self.session_id = session_id
        self.board = [[None] * self.COLS for _ in range(self.ROWS)]
        self.current = p1
        self.message: discord.Message | None = None
        self._settled = False
        for col in range(self.COLS):
            self.add_item(_ConnectFourButton(col))

    def render(self, status: str) -> str:
        rows_text = "\n".join(
            "".join(self.SYMBOLS["p1"] if cell == "p1" else self.SYMBOLS["p2"] if cell == "p2" else self.SYMBOLS["empty"] for cell in row)
            for row in self.board
        )
        return f"{rows_text}\n\n{status}"

    def panneau(self, status: str) -> "panels.Panneau":
        """Le plateau, en panneau.

        Le plateau EST du texte (une grille d'emojis), mais il vit dans un
        message Components V2 depuis que la partie est servie en panneau :
        l'editer avec un content serait refuse par Discord.
        """
        rows_text = "\n".join(
            "".join(
                self.SYMBOLS["p1"] if cell == "p1"
                else self.SYMBOLS["p2"] if cell == "p2"
                else self.SYMBOLS["empty"]
                for cell in row
            )
            for row in self.board
        )
        return panels.Panneau(
            titre="Puissance 4",
            sous_titre=status,
            kind="brand",
            sections=[panels.Section("Plateau", texte=rows_text)],
            pied=f"{self.p1.display_name} {self.SYMBOLS['p1']}  ·  "
            f"{self.p2.display_name} {self.SYMBOLS['p2']}",
        )

    def _lowest_row(self, col: int) -> int | None:
        for row in range(self.ROWS - 1, -1, -1):
            if self.board[row][col] is None:
                return row
        return None

    def _check_win(self, symbol: str) -> bool:
        b = self.board
        for r in range(self.ROWS):
            for c in range(self.COLS - 3):
                if all(b[r][c + i] == symbol for i in range(4)):
                    return True
        for c in range(self.COLS):
            for r in range(self.ROWS - 3):
                if all(b[r + i][c] == symbol for i in range(4)):
                    return True
        for r in range(self.ROWS - 3):
            for c in range(self.COLS - 3):
                if all(b[r + i][c + i] == symbol for i in range(4)):
                    return True
        for r in range(3, self.ROWS):
            for c in range(self.COLS - 3):
                if all(b[r - i][c + i] == symbol for i in range(4)):
                    return True
        return False

    def _is_full(self) -> bool:
        return all(self.board[0][c] is not None for c in range(self.COLS))

    async def play(self, interaction: discord.Interaction, col: int):
        if interaction.user.id != self.current.id:
            return await interaction.response.send_message("Ce n'est pas votre tour !", ephemeral=True)
        if interaction.user.id not in (self.p1.id, self.p2.id):
            return await interaction.response.send_message("❌ Cette partie ne vous concerne pas.", ephemeral=True)
        row = self._lowest_row(col)
        if row is None:
            return await interaction.response.send_message("❌ Colonne pleine.", ephemeral=True)
        symbol = "p1" if self.current.id == self.p1.id else "p2"
        self.board[row][col] = symbol
        if all(self._lowest_row(c) is None for c in range(self.COLS)):
            for child in self.children:
                child.disabled = True

        if self._check_win(symbol):
            for child in self.children:
                child.disabled = True
            self._settled = True
            await _finish_duel(self.cog.bot, self.guild_id, "connect4", self.p1, self.p2)
            winner = self.current
            reward = await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, winner.id, "connect4", 40, self.session_id, result="win")
            await panels.editer(
                interaction.response,
                panels.avec_composants(
                    self.panneau(f"🏆 {winner.mention} gagne la partie !" + _reward_line(reward)),
                    self,
                ),
            )
            return
        if self._is_full():
            self._settled = True
            await _finish_duel(self.cog.bot, self.guild_id, "connect4", self.p1, self.p2)
            await game_rewards.reward_game_winner(self.cog.bot, self.guild_id, self.p1.id, "connect4", 0, self.session_id, result="draw")
            await panels.editer(interaction.response, panels.avec_composants(self.panneau("🤝 Match nul, plateau plein !"), self))
            return

        self.current = self.p2 if self.current.id == self.p1.id else self.p1
        symbole = self.SYMBOLS["p1"] if self.current.id == self.p1.id else self.SYMBOLS["p2"]
        await panels.editer(
            interaction.response,
            panels.avec_composants(
                self.panneau(f"Au tour de {self.current.mention} ({symbole})"), self
            ),
        )

    async def on_timeout(self):
        if self._settled or self.message is None:
            return
        self._settled = True
        await _finish_duel(self.cog.bot, self.guild_id, "connect4", self.p1, self.p2)
        for child in self.children:
            child.disabled = True
        try:
            await panels.editer(self.message, panels.avec_composants(self.panneau("⏱️ Partie expirée (inactivité)."), self))
        except Exception:
            logger.warning("Étape non critique ignorée dans on_timeout", exc_info=True)


class _ConnectFourButton(discord.ui.Button):
    def __init__(self, col: int):
        super().__init__(label=str(col + 1), style=discord.ButtonStyle.secondary, row=col // 4)
        self.col = col

    async def callback(self, interaction: discord.Interaction):
        await panels.vue_source(self).play(interaction, self.col)


# =============================================================================
# JEUX COMMUNAUTAIRES — n'importe qui peut lancer une manche (avec un cooldown sur le
# lanceur pour éviter le spam) ; le PREMIER membre à répondre correctement (ou à cliquer)
# remporte la récompense. Un cooldown par lanceur empêche qu'une seule personne relance en
# boucle un évènement pour cumuler les récompenses de ses alts.
# =============================================================================

class GamesCommunity(commands.Cog, name="GamesCommunity"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Parties "dernier message gagne" actives, par salon — voir on_message ci-dessous.
        self._lastmessage_state: dict[int, dict] = {}

    async def _start_community(self, ctx: commands.Context, game_name: str, cooldown: int = 60) -> tuple[bool, str, str | None]:
        return await _precheck(self.bot, ctx, game_name, cooldown)

    async def _finish_community(self, guild_id: int, user_id: int, game_name: str) -> None:
        """Toujours libérer le verrou de manche puis démarrer le cooldown du lanceur."""
        game_rewards.release_play_lock(guild_id, user_id, game_name)
        await game_rewards.touch_cooldown(self.bot, guild_id, user_id, game_name)

    async def _run_text_race(self, ctx: commands.Context, game_name: str, title: str, prompt: str, answer, window: int, reward: int, *, difficulty: str = "normal"):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await self._start_community(ctx, game_name)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title=title, description=err, kind='warning')))

        try:
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title=title, description=f'{prompt}\n🏁 Premier(e) à répondre correctement dans ce salon gagne ! ({window}s)')))

            def check(m):
                return m.channel.id == ctx.channel.id and not m.author.bot and game_rewards.answer_matches(m.content, answer)

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=window)
            except asyncio.TimeoutError:
                return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title=title, description=f"⏱️ Personne n'a trouvé. La réponse était **{_primary_answer(answer)}**.", kind='warning')))

            reward_amount = game_rewards.skill_reward(reward, difficulty=difficulty)
            game_reward = await game_rewards.reward_game_winner(
                self.bot, guild_id, msg.author.id, game_name, reward_amount, sid, result="win"
            )
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title=title, description=f'🏆 {msg.author.mention} a trouvé en premier !\nDifficulté : **{difficulty}**' + _reward_line(game_reward), kind='success')))
        finally:
            await self._finish_community(guild_id, ctx.author.id, game_name)
    @commands.hybrid_command(name="triviastart", description="Lancer une question de culture générale communautaire.", with_app_command=False)
    async def triviastart(self, ctx: commands.Context):
        question, answer, difficulty = game_rewards.secure_pick(COMMUNITY_TRIVIA)
        await self._run_text_race(ctx, "triviastart", "Trivia communautaire", f"❓ {question}", answer, 20, 20, difficulty=difficulty)

    @commands.hybrid_command(name="wordrace", description="Lancer une course pour deviner un mot mélangé.", with_app_command=False)
    async def wordrace(self, ctx: commands.Context):
        word = game_rewards.secure_pick(COMMUNITY_WORDS)
        letters = list(word)
        random.shuffle(letters)
        await self._run_text_race(ctx, "wordrace", "Course au mot", f"🔤 Remettez les lettres dans l'ordre : **{''.join(letters).upper()}**", word, 25, 20)

    @commands.hybrid_command(name="mathrace", description="Lancer une course de calcul mental.", with_app_command=False)
    async def mathrace(self, ctx: commands.Context):
        a, b = random.randint(5, 80), random.randint(5, 80)
        op = random.choice(list(COMMUNITY_MATH_OPS))
        answer = str(COMMUNITY_MATH_OPS[op](a, b))
        await self._run_text_race(ctx, "mathrace", "Course mathématique", f"🧮 Combien font **{a} {op} {b}** ?", answer, 15, 18)

    @commands.hybrid_command(name="guessrace", description="Lancer une course pour deviner un nombre secret.", with_app_command=False)
    async def guessrace(self, ctx: commands.Context):
        target = random.randint(1, 50)
        await self._run_text_race(ctx, "guessrace", "Course au nombre", "🔢 Le bot a choisi un nombre secret entre 1 et 50.", str(target), 25, 20)

    @commands.hybrid_command(name="reactionevent", description="Lancer un évènement réaction : premier clic gagne.", with_app_command=False)
    async def reactionevent(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await self._start_community(ctx, "reactionevent")
        if not started:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Évènement réaction",
                        description=err,
                        kind="warning",
                    )
                ),
            )

        try:
            options, target = _reaction_round()
            msg = await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Évènement réaction — préparez-vous",
                        description=(
                            f"🎯 **CIBLE : {target}**\n"
                            "Mémorisez-la. Quatre boutons apparaîtront après un délai aléatoire.\n"
                            "Le premier membre qui clique sur la bonne cible gagne."
                        ),
                    )
                ),
            )
            await asyncio.sleep(random.uniform(2.0, 5.0))

            view = _CommunityRaceButtonView(options, target)
            await panels.editer(
                msg,
                panels.avec_composants(
                    panels.depuis_embed(
                        await _embed(
                            self.bot,
                            guild_id,
                            title="Évènement réaction — GO",
                            description=(
                                f"⚡ Trouvez **{target}** parmi les quatre boutons.\n"
                                "Les mauvaises cibles ne terminent pas la manche."
                            ),
                        )
                    ),
                    view,
                ),
            )
            await view.wait()

            if view.winner is None:
                return await panels.editer(
                    msg,
                    panels.depuis_embed(
                        await _embed(
                            self.bot,
                            guild_id,
                            title="Évènement réaction — terminé",
                            description=f"⏱️ Personne n'a trouvé **{target}** à temps.",
                            kind="warning",
                        )
                    ),
                )

            elapsed = view.elapsed or 0.0
            speed_bonus = 10 if elapsed < 0.7 else 6 if elapsed < 1.3 else 2
            reward = await game_rewards.reward_game_winner(
                self.bot,
                guild_id,
                view.winner.id,
                "reactionevent",
                25 + speed_bonus,
                sid,
                result="win",
                metadata={"elapsed": round(elapsed, 3), "target": target},
            )
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(
                        self.bot,
                        guild_id,
                        title="Évènement réaction — gagné",
                        description=(
                            f"🏆 {view.winner.mention} a trouvé **{target}** en **{elapsed:.2f}s**.\n"
                            f"⚡ Bonus vitesse : **+{speed_bonus}**"
                        )
                        + _reward_line(reward),
                        kind="success",
                    )
                ),
            )
        finally:
            await self._finish_community(guild_id, ctx.author.id, "reactionevent")

    @commands.hybrid_command(name="emoji-race", description="Lancer une course à l'emoji : cliquez sur le bon emoji en premier.", with_app_command=False)
    async def emoji_race(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await self._start_community(ctx, "emoji-race")
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title="Course à l'emoji", description=err, kind='warning')))
        try:
            pool = ["🍒", "🍋", "🍊", "🍇", "💎"]
            target = game_rewards.secure_pick(pool)
            view = _EmojiRaceView(pool, target)
            await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(await _embed(self.bot, guild_id, title="Course à l'emoji", description=f'🎯 Cliquez sur **{target}** — premier(e) à cliquer sur le bon emoji gagne ! (15s)')), view))
            await view.wait()
            if view.winner is None:
                return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title="Course à l'emoji", description="⏱️ Personne n'a trouvé à temps.")))
            reward = await game_rewards.reward_game_winner(self.bot, guild_id, view.winner.id, "emoji-race", 20, sid, result="win")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title="Course à l'emoji", description=f'🏆 {view.winner.mention} a trouvé le bon emoji en premier !' + _reward_line(reward), kind='success')))
        finally:
            await self._finish_community(guild_id, ctx.author.id, "emoji-race")
    @commands.hybrid_command(name="lastmessage", description="Lancer un défi 'dernier message gagne' dans ce salon.", with_app_command=False)
    @app_commands.describe(duree="Durée en secondes (30 à 120, défaut 45)")
    async def lastmessage(self, ctx: commands.Context, duree: int = 45):
        guild_id = ctx.guild.id if ctx.guild else None
        duree = max(30, min(duree, 120))
        started, err, sid = await self._start_community(ctx, "lastmessage", cooldown=90)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Dernier message gagne', description=err, kind='warning')))
        if ctx.channel.id in self._lastmessage_state:
            await self._finish_community(guild_id, ctx.author.id, "lastmessage")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Dernier message gagne', description='⚠️ Un défi est déjà en cours dans ce salon.', kind='warning')))

        self._lastmessage_state[ctx.channel.id] = {"last_author": None}
        try:
            await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Dernier message gagne', description=f"💬 Le dernier membre à écrire dans ce salon d'ici **{duree}s** remporte la récompense !")))
            await asyncio.sleep(duree)
            state = self._lastmessage_state.pop(ctx.channel.id, {})
            winner = state.get("last_author")
            if winner is None:
                return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Dernier message gagne', description="⏱️ Personne n'a écrit — pas de gagnant.")))
            reward = await game_rewards.reward_game_winner(self.bot, guild_id, winner.id, "lastmessage", 25, sid, result="win")
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Dernier message gagne', description=f'🏆 {winner.mention} a écrit le dernier message !' + _reward_line(reward), kind='success')))
        finally:
            self._lastmessage_state.pop(ctx.channel.id, None)
            await self._finish_community(guild_id, ctx.author.id, "lastmessage")
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        state = self._lastmessage_state.get(message.channel.id)
        if state is not None:
            state["last_author"] = message.author


class _CommunityRaceButtonView(discord.ui.View):
    def __init__(self, options: list[str], target: str):
        super().__init__(timeout=10)
        self.target = target
        self.winner: discord.Member | discord.User | None = None
        self.elapsed: float | None = None
        self._start = time.monotonic()
        self._lock = asyncio.Lock()
        for token in options:
            self.add_item(_CommunityRaceButton(token, is_target=(token == target)))


class _CommunityRaceButton(discord.ui.Button):
    def __init__(self, token: str, *, is_target: bool):
        parts = str(token).split(maxsplit=1)
        emoji = parts[0] if len(parts) == 2 else None
        label = parts[1] if len(parts) == 2 else str(token)
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)
        self.is_target = is_target

    async def callback(self, interaction: discord.Interaction):
        view: _CommunityRaceButtonView = panels.vue_source(self)
        async with view._lock:
            if view.winner is not None:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Trop tard, la manche est déjà terminée.", ephemeral=True)
                return
            if not self.is_target:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Mauvaise cible. Cherchez le bon symbole + nombre.", ephemeral=True)
                return

            view.winner = interaction.user
            view.elapsed = time.monotonic() - view._start
            for child in view.children:
                child.disabled = True
            self.style = discord.ButtonStyle.success
            # edit_message accuse réception immédiatement : le callback ne reste jamais
            # sans ACK et évite l'ancien panneau « Action interrompue ».
            await interaction.response.edit_message(view=panels.vue_panneau(self))
            panels.terminer_vue(self)


class _EmojiRaceView(discord.ui.View):
    def __init__(self, pool: list[str], target: str):
        super().__init__(timeout=15)
        self.winner: discord.Member | None = None
        for emoji in pool:
            self.add_item(_EmojiRaceButton(emoji, is_target=(emoji == target)))


class _EmojiRaceButton(discord.ui.Button):
    def __init__(self, emoji: str, is_target: bool):
        super().__init__(label="​", emoji=emoji, style=discord.ButtonStyle.secondary)
        self.is_target = is_target

    async def callback(self, interaction: discord.Interaction):
        view: _EmojiRaceView = panels.vue_source(self)
        if view.winner is not None:
            return await interaction.response.send_message("❌ Trop tard.", ephemeral=True)
        if not self.is_target:
            return await interaction.response.send_message("❌ Mauvais emoji.", ephemeral=True)
        view.winner = interaction.user
        for child in view.children:
            child.disabled = True
        await interaction.response.defer()
        panels.terminer_vue(self)


# =============================================================================
# JEUX SOLO À COOLDOWN LONG (aventure/donjon/mine/pêche/trésor/chasse/exploration) — même
# moteur générique, habillage différent par jeu. Cooldown 10-30 min (persisté en base, donc
# conservé après redémarrage), petite chance d'échec (aucune récompense, cooldown quand
# même posé) pour rester crédible plutôt que 100% de réussite garantie.
# =============================================================================

class _SoloChoiceView(discord.ui.View):
    def __init__(self, author_id: int, choices: list[tuple]):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.selected: tuple | None = None
        self._lock = asyncio.Lock()
        for index, choice in enumerate(choices[:3]):
            emoji, label, chance, multiplier, description = choice
            self.add_item(
                _SoloChoiceButton(
                    index=index, emoji=emoji, label=label, chance=chance,
                    multiplier=multiplier, description=description,
                )
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Cette aventure appartient à un autre joueur.", ephemeral=True
                )
            return False
        return True


class _SoloChoiceButton(discord.ui.Button):
    def __init__(self, *, index: int, emoji: str, label: str, chance: float, multiplier: float, description: str):
        super().__init__(
            label=label, emoji=emoji,
            style=(
                discord.ButtonStyle.success if index == 0
                else discord.ButtonStyle.primary if index == 1
                else discord.ButtonStyle.danger
            ),
        )
        self.choice = (emoji, label, chance, multiplier, description)

    async def callback(self, interaction: discord.Interaction):
        view: _SoloChoiceView = panels.vue_source(self)
        async with view._lock:
            if view.selected is not None:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Un choix a déjà été enregistré.", ephemeral=True)
                return
            view.selected = self.choice
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(view=panels.vue_panneau(self))
            panels.terminer_vue(self)

class GamesSolo(commands.Cog, name="GamesSolo"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _run_solo(self, ctx: commands.Context, game_name: str):
        """Jeu solo interactif : trois chemins, trois niveaux de risque et aucun long verrou."""
        titre, cooldown, succes, texte_echec = SOLO_FLAVORS[game_name]
        # Le libellé du catalogue porte déjà son pictogramme, et _embed le repose
        # devant : « 🎣 SentriX — 🎣 Pêche ». On garde le nom du jeu, rien d'autre.
        titre = titre.split(" ", 1)[1] if " " in titre and not titre[0].isalnum() else titre
        # Une seule phrase d'échec par jeu se reconnaissait dès la troisième
        # partie. SOLO_ECHECS en propose plusieurs ; l'ancienne reste le secours.
        echecs = list(SOLO_ECHECS.get(game_name) or (texte_echec,))
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, sid = await _precheck(self.bot, ctx, game_name, cooldown)
        if not started:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(await _embed(self.bot, guild_id, title=titre, description=err, kind="warning")),
            )

        difficulty = await _game_difficulty(self.bot, guild_id)
        choices = list(SOLO_CHOICES[game_name])
        view = _SoloChoiceView(ctx.author.id, choices)
        choice_lines = []
        for emoji, label, chance, multiplier, description in choices:
            choice_lines.append(
                f"{emoji} **{label}** · réussite ~{round(chance * 100)}% · butin x{multiplier:g}\n"
                f"└ {description}"
            )

        msg = await panels.envoyer(
            ctx,
            panels.avec_composants(
                panels.depuis_embed(
                    await _embed(
                        self.bot, guild_id, title=titre,
                        description=(
                            f"🎮 Difficulté serveur : **{difficulty}**\n"
                            "Choisissez votre approche : plus le risque monte, plus le butin potentiel augmente.\n\n"
                            + "\n\n".join(choice_lines)
                        ),
                    )
                ),
                view,
            ),
        )
        await view.wait()

        if view.selected is None:
            game_rewards.release_play_lock(guild_id, ctx.author.id, game_name)
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(
                        self.bot, guild_id, title=titre,
                        description="⏱️ Aucun choix effectué. La manche est annulée, vous pouvez relancer le jeu.",
                        kind="warning",
                    )
                ),
            )

        emoji, label, base_chance, multiplier, description = view.selected
        difficulty_key = difficulty.casefold()
        chance_shift = (
            0.08 if difficulty_key in {"facile", "easy"}
            else -0.07 if difficulty_key in {"difficile", "hard"}
            else 0.0
        )
        chance = max(0.15, min(0.95, float(base_chance) + chance_shift))
        won = random.random() < chance

        if not won:
            await _finish(self.bot, ctx, game_name, sid, "loss", 0)
            return await panels.editer(
                msg,
                panels.depuis_embed(
                    await _embed(
                        self.bot, guild_id, title=f"{titre} — échec",
                        description=(
                            f"{emoji} **{label}**\n{game_rewards.secure_pick(echecs)}\n\n"
                            f"🎲 Chance de réussite : **{round(chance * 100)}%**\n"
                            "🔁 Vous pouvez rejouer dans quelques secondes."
                        ),
                        kind="danger",
                    )
                ),
            )

        base = random.randint(30, 70)
        text = game_rewards.secure_pick(succes)
        # La prise est le deuxieme axe de variete : le chemin choisi dit le risque,
        # la rarete de l'objet dit la chance. Les deux se cumulent sur le gain.
        butin = tirer_butin(game_name)
        butin_text = ""
        if butin is not None:
            emoji_butin, nom_butin, rarete, mult_butin = butin
            base = max(1, round(base * float(mult_butin)))
            butin_text = f"{emoji_butin} Prise : **{nom_butin}** · {rarete} · gains x{mult_butin:g}\n"
            if rarete == "Légendaire":
                butin_text += "✨ **Prise légendaire !** Ça n'arrive presque jamais.\n"
        amount = max(1, round(base * float(multiplier)))
        # La prise part avec la manche dans metadata_json : c'est elle que relit
        # +collec, sans table supplémentaire.
        reward = await _finish(
            self.bot, ctx, game_name, sid, "win", amount,
            metadata=(
                {"butin": {"emoji": emoji_butin, "nom": nom_butin, "rarete": rarete}}
                if butin is not None
                else None
            ),
        )

        boost_text = ""
        if game_name == "adventure":
            try:
                money_boost, xp_boost, duration, rarity = temporary_boosts.quest_boost_for_risk(multiplier)
                active_boost, granted = await temporary_boosts.grant_quest_boost(
                    self.bot.db,
                    guild_id,
                    ctx.author.id,
                    money_multiplier=money_boost,
                    xp_multiplier=xp_boost,
                    duration_seconds=duration,
                    source=f"quest:{rarity}",
                )
                if granted:
                    boost_text = (
                        f"\n\n🚀 **Boost de quête {rarity} activé !**\n"
                        f"🪙 Argent **x{active_boost.money_multiplier:g}** · "
                        f"⭐ XP **x{active_boost.xp_multiplier:g}** · "
                        f"⏱️ **{max(1, (active_boost.remaining() + 59) // 60)} min**"
                    )
                else:
                    boost_text = (
                        f"\n\n🚀 Votre boost actuel est déjà aussi fort ou meilleur : "
                        f"argent x{active_boost.money_multiplier:g} · XP x{active_boost.xp_multiplier:g}."
                    )
            except Exception:
                logger.warning("Boost de quête indisponible, résultat du jeu conservé.", exc_info=True)

        if reward and reward.success and reward.amount > 0:
            reward_text = (
                f"🪙 **+{stats_service.format_number(reward.amount)}** crédités\n"
                f"Référence `{reward.display_id}`"
            )
        else:
            reward_text = (
                "🪙 **0 crédit** — limite quotidienne de récompenses atteinte.\n"
                "La partie reste jouable normalement."
            )

        await panels.editer(
            msg,
            panels.depuis_embed(
                await _embed(
                    self.bot, guild_id, title=f"{titre} — réussite",
                    description=(
                        f"{emoji} **{label}** · butin x{multiplier:g}\n{text}\n\n"
                        f"{butin_text}"
                        f"🎲 Chance jouée : **{round(chance * 100)}%**\n"
                        f"{reward_text}{boost_text}\n\n"
                        "🔁 Vous pouvez rejouer dans quelques secondes."
                    ),
                    kind="success",
                )
            ),
        )
    @commands.hybrid_command(name="adventure", description="Partir à l'aventure pour une récompense (cooldown long).", with_app_command=False)
    async def adventure(self, ctx: commands.Context):
        await self._run_solo(ctx, "adventure")

    @commands.hybrid_command(name="dungeon", description="Explorer un donjon pour une récompense (cooldown long).", with_app_command=False)
    async def dungeon(self, ctx: commands.Context):
        await self._run_solo(ctx, "dungeon")

    @commands.hybrid_command(name="mining", description="Miner pour une récompense (cooldown moyen).", with_app_command=False)
    async def mining(self, ctx: commands.Context):
        await self._run_solo(ctx, "mining")

    @commands.hybrid_command(name="fishing", description="Pêcher pour une récompense (cooldown moyen).", with_app_command=False)
    async def fishing(self, ctx: commands.Context):
        await self._run_solo(ctx, "fishing")

    @commands.hybrid_command(name="treasure", description="Chercher un trésor pour une récompense (cooldown long).", with_app_command=False)
    async def treasure(self, ctx: commands.Context):
        await self._run_solo(ctx, "treasure")

    @commands.hybrid_command(name="hunt", description="Chasser pour une récompense (cooldown long).", with_app_command=False)
    async def hunt(self, ctx: commands.Context):
        await self._run_solo(ctx, "hunt")

    @commands.hybrid_command(name="explore", description="Explorer les environs pour une récompense (cooldown long).", with_app_command=False)
    async def explore(self, ctx: commands.Context):
        await self._run_solo(ctx, "explore")


# =============================================================================
# COMMANDES JOUEUR — +gamehistory, +gameprofile, +gamestats, +gametop, +dailygames
# (lecture seule, toutes les données viennent de game_transactions via database/db.py).
# =============================================================================

class GamesPlayerCommands(commands.Cog, name="GamesPlayerCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _resolve_target(self, ctx: commands.Context, membre: discord.Member | None) -> discord.Member:
        if membre is None:
            return ctx.author
        if membre.id == ctx.author.id:
            return membre
        # Voir les stats de jeu d'un AUTRE membre est réservé au staff (comme +stats), pour
        # ne pas transformer +gamehistory en outil de surveillance ouvert à tous.
        return membre

    @commands.hybrid_command(name="gamehistory", description="Historique de vos dernières manches de mini-jeux.", with_app_command=False)
    @app_commands.describe(membre="Voir l'historique d'un autre membre (staff uniquement)")
    async def gamehistory(self, ctx: commands.Context, membre: discord.Member = None):
        guild_id = ctx.guild.id if ctx.guild else None
        if membre and membre.id != ctx.author.id:
            allowed = ctx.author.guild_permissions.administrator if isinstance(ctx.author, discord.Member) else False
            if not allowed:
                return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Historique', description="❌ Seul le staff peut consulter l'historique d'un autre membre.", kind='danger')))
        target = membre or ctx.author
        rows = await self.bot.db.get_game_history(guild_id, target.id, limit=10)
        if not rows:
            prefixe = ctx.clean_prefix if isinstance(getattr(ctx, "clean_prefix", None), str) else "+"
            qui = "Vous n'avez" if target.id == ctx.author.id else f"{target.mention} n'a"
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title='Historique des jeux',
                description=(
                    f"📜 {qui} pas encore joué ici.\n"
                    f"`{prefixe}jeuxjour` montre les 39 jeux disponibles sur ce serveur."
                ),
            )))
        lines = []
        for row in rows:
            label = GAME_CATALOG.get(row["game_name"], (row["game_name"], ""))[0]
            amount = f"+{row['reward_amount']} 🪙" if row["reward_amount"] > 0 else "0"
            lines.append(f"`{row['game_session_id'][:8]}…` **{label}** — {row['result']} — {amount} — <t:{row['created_at']}:R>")
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title=f'Historique des jeux — {target.display_name}', description='\n'.join(lines))))

    @commands.hybrid_command(name="collec", description="Votre collection de prises rapportées des jeux solo.", with_app_command=False)
    @app_commands.describe(membre="Voir la collection d'un autre membre (staff uniquement)")
    async def collec(self, ctx: commands.Context, membre: discord.Member = None):
        guild_id = ctx.guild.id if ctx.guild else None
        if membre and membre.id != ctx.author.id:
            allowed = ctx.author.guild_permissions.administrator if isinstance(ctx.author, discord.Member) else False
            if not allowed:
                return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                    self.bot, guild_id, title="Collection",
                    description="❌ Seul le staff peut consulter la collection d'un autre membre.",
                    kind="danger",
                )))
        target = membre or ctx.author

        trouves: dict[str, dict[tuple[str, str], int]] = {}
        try:
            rows = await self.bot.db.get_game_loot(guild_id, target.id)
        except Exception:
            logger.warning("Collection indisponible pour %s", target.id, exc_info=True)
            rows = []
        for row in rows:
            try:
                butin = (json.loads(row["metadata_json"] or "{}") or {}).get("butin") or {}
            except Exception:
                continue
            emoji, nom = butin.get("emoji"), butin.get("nom")
            if not emoji or not nom:
                continue
            seau = trouves.setdefault(row["game_name"], {})
            seau[(emoji, nom)] = seau.get((emoji, nom), 0) + 1

        total_possible = sum(
            len(objets) for table in SOLO_LOOT.values() for objets in table.values()
        )
        total_trouve = sum(len(seau) for seau in trouves.values())

        if not total_trouve:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title=f"Collection — {target.display_name}",
                description=(
                    f"🎒 **0 / {total_possible}** objet trouvé.\n\n"
                    "Gagnez une manche de `+fishing`, `+mining`, `+hunt`, `+treasure`, "
                    "`+adventure`, `+dungeon` ou `+explore` pour rapporter votre première prise."
                ),
            )))

        # Une rareté par objet : la table du catalogue est l'autorité, pas ce que
        # la manche avait affiché ce jour-là.
        rarete_de: dict[tuple[str, str], str] = {}
        for table in SOLO_LOOT.values():
            for cle, libelle, _poids, _mult in RARETES:
                for objet in table.get(cle, ()):
                    rarete_de[tuple(objet)] = libelle

        sections = []
        for jeu in sorted(trouves, key=lambda j: -len(trouves[j])):
            seau = trouves[jeu]
            possible = sum(len(o) for o in SOLO_LOOT.get(jeu, {}).values())
            lignes = []
            for (emoji, nom), combien in sorted(
                seau.items(), key=lambda kv: (-kv[1], kv[0][1])
            )[:12]:
                rarete = rarete_de.get((emoji, nom), "Commun")
                lignes.append(panels.Ligne(
                    f"{emoji} {nom}",
                    f"×{combien}",
                    indice=rarete,
                ))
            titre_jeu = GAME_CATALOG.get(jeu, (jeu, ""))[0]
            sections.append(panels.Section(
                f"{titre_jeu} — {len(seau)}/{possible}", lignes
            ))

        pourcent = round(total_trouve * 100 / total_possible) if total_possible else 0
        entete = panels.Section("Avancement", [
            panels.Ligne("Objets distincts", f"**{total_trouve} / {total_possible}**", indice=f"{pourcent} % de la collection"),
            panels.Ligne("Prises rapportées", f"**{sum(sum(s.values()) for s in trouves.values())}**"),
        ])
        await panels.envoyer(ctx, panels.Panneau(
            titre=f"{_game_icon('Collection')} Collection — {target.display_name}",
            sous_titre=f"{pourcent} % de la collection SentriX",
            sections=[entete, *sections],
            kind="jeux",
        ))

    @commands.hybrid_command(name="gameprofile", description="Profil de jeu complet d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à afficher")
    async def gameprofile(self, ctx: commands.Context, membre: discord.Member = None):
        guild_id = ctx.guild.id if ctx.guild else None
        target = membre or ctx.author
        prefixe = ctx.clean_prefix if isinstance(getattr(ctx, "clean_prefix", None), str) else "+"
        stats = await self.bot.db.get_game_stats(guild_id, target.id)
        recent = await self.bot.db.get_game_history(guild_id, target.id, limit=5)
        joues = stats["games_played"]
        win_rate = round((stats["wins"] / joues) * 100) if joues else 0

        if not joues:
            return await panels.envoyer(ctx, panels.Panneau(
                titre=f"{_game_icon('Profil de jeu')} Profil de jeu — {target.display_name}",
                vignette=target.display_avatar.url,
                sections=[panels.Section(
                    "Aucune manche jouée",
                    texte=(
                        f"{target.mention} n'a pas encore joué ici.\n"
                        f"`{prefixe}jeuxjour` montre les 39 jeux disponibles sur ce serveur."
                        if target.id != ctx.author.id else
                        "Vous n'avez pas encore joué ici.\n"
                        f"`{prefixe}jeuxjour` montre les 39 jeux disponibles sur ce serveur."
                    ),
                )],
                kind="jeux",
            ))

        # Le jeu préféré se compte sur TOUT l'historique, pas sur les cinq
        # dernières manches — sinon « votre jeu » changerait à chaque partie.
        favori = await self.bot.db.get_favourite_game(guild_id, target.id)

        issues = {"win": "🏆 gagnée", "loss": "○ perdue", "draw": "🤝 nulle"}
        dernieres = [
            panels.Ligne(
                GAME_CATALOG.get(r["game_name"], (r["game_name"], ""))[0],
                issues.get(r["result"], r["result"]),
                indice=(
                    f"+{stats_service.format_number(r['reward_amount'])} 🪙"
                    if r["reward_amount"] else None
                ),
            )
            for r in recent
        ]

        bilan = [
            panels.Ligne("Manches jouées", f"**{stats_service.format_number(joues)}**"),
            panels.Ligne(
                "Victoires",
                f"**{stats_service.format_number(stats['wins'])}** · {win_rate} %",
                indice=design_system.progress_bar(stats["wins"], joues),
            ),
            panels.Ligne(
                "Défaites / égalités",
                f"{stats_service.format_number(stats['losses'])} · {stats_service.format_number(stats['draws'])}",
            ),
            panels.Ligne("Total gagné", f"**{stats_service.format_number(stats['total_earned'])}** 🪙"),
        ]
        if favori:
            nom_favori, manches_favori = favori
            libelle = GAME_CATALOG.get(nom_favori, (nom_favori, ""))[0]
            bilan.append(panels.Ligne(
                "Jeu préféré", f"**{libelle}**",
                indice=f"{stats_service.format_number(manches_favori)} manche(s) jouée(s)",
            ))

        sections = [
            panels.Section("Bilan", bilan),
            panels.Section("Dernières manches", dernieres),
        ]
        await panels.envoyer(ctx, panels.Panneau(
            titre=f"{_game_icon('Profil de jeu')} Profil de jeu — {target.display_name}",
            sous_titre=f"{win_rate} % de victoires sur {stats_service.format_number(joues)} manches",
            vignette=target.display_avatar.url,
            sections=sections,
            kind="jeux",
        ))

    @commands.hybrid_command(name="gamestats", description="Statistiques détaillées de mini-jeux d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à afficher")
    async def gamestats(self, ctx: commands.Context, membre: discord.Member = None):
        guild_id = ctx.guild.id if ctx.guild else None
        target = membre or ctx.author
        stats = await self.bot.db.get_game_stats(guild_id, target.id)
        win_rate = round((stats["wins"] / stats["games_played"]) * 100) if stats["games_played"] else 0
        description = (
            f"**Manches jouées :** {stats['games_played']}\n"
            f"**Victoires :** {stats['wins']}\n"
            f"**Défaites :** {stats['losses']}\n"
            f"**Égalités :** {stats['draws']}\n"
            f"**Taux de victoire :** {win_rate}%\n"
            f"**Total gagné :** {stats['total_earned']} 🪙"
        )
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title=f'Statistiques de jeu — {target.display_name}', description=description)))

    @commands.hybrid_command(name="gametop", description="Classement des joueurs par gains de mini-jeux.", with_app_command=False)
    async def gametop(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        settings = await game_rewards.get_settings(self.bot, guild_id)
        if not settings.get("leaderboard_enabled", True):
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Classement des jeux', description='🎮 Le classement des mini-jeux est désactivé sur ce serveur.', kind='warning')))
        rows = await self.bot.db.get_game_leaderboard(guild_id, limit=10)
        if not rows:
            # Un écran vide qui ne dit pas quoi faire ensuite est un cul-de-sac.
            prefixe = ctx.clean_prefix if isinstance(getattr(ctx, "clean_prefix", None), str) else "+"
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(
                self.bot, guild_id, title='Classement des jeux',
                description=(
                    "🏆 Personne n'a encore joué sur ce serveur.\n"
                    f"`{prefixe}jeuxjour` montre les 39 jeux disponibles — "
                    "la première manche jouée ouvre le classement."
                ),
            )))
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            rank = medals[i] if i < 3 else f"**#{i + 1}**"
            lines.append(f"{rank} <@{row['user_id']}> — {row['total_earned']} 🪙 ({row['games_played']} manches)")
        await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='🏆 Classement des mini-jeux', description='\n'.join(lines))))

    @commands.hybrid_command(name="dailygames", description="Votre activité de mini-jeux aujourd'hui et vos cooldowns en cours.", with_app_command=False)
    async def dailygames(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        if guild_id is None:
            return await panels.envoyer(ctx, panels.depuis_embed(await _embed(self.bot, guild_id, title='Mini-jeux du jour', description='🎮 Disponible uniquement sur un serveur.', kind='warning')))
        _allowed, played, limit = await game_rewards.check_daily_limit(self.bot, guild_id, ctx.author.id)
        limit_text = f"**{played} / {limit}**" if limit > 0 else f"**{played}** (illimité)"
        prefixe = ctx.clean_prefix if isinstance(getattr(ctx, "clean_prefix", None), str) else "+"

        # Cet écran ne disait que le quota et les cooldowns : rien n'indiquait
        # quels jeux existent. C'est pourtant le seul endroit où un membre
        # vient chercher « à quoi je peux jouer maintenant ». Il liste donc le
        # catalogue, avec pour chaque jeu son état réel sur CE serveur.
        familles = {
            "rapide": ("⚡ Jeux rapides", "seul, une manche courte"),
            "duel": ("⚔️ Duels", "contre un autre membre"),
            "communautaire": ("🎪 Jeux communautaires", "tout le salon participe"),
            "solo": ("🗺️ Expéditions", "trois chemins de risque, une prise à rapporter"),
        }
        # Les gardes de serveur (interrupteur, salon, rôle) sont les mêmes pour les
        # 39 jeux : is_game_enabled tranche UNE fois et reste l'autorité. Seule la
        # liste des jeux coupés varie ensuite, et elle sort des mêmes réglages.
        ouvert, _raison = await game_rewards.is_game_enabled(
            self.bot, guild_id, "", channel_id=getattr(ctx.channel, "id", None),
            role_ids={r.id for r in getattr(ctx.author, "roles", [])} or None,
        )
        reglages = await game_rewards.get_settings(self.bot, guild_id)
        coupes = set(reglages.get("disabled_games") or ())
        # Un seul aller-retour pour tous les cooldowns, au lieu d'un par ligne.
        derniers = await self.bot.db.get_game_cooldowns(guild_id, ctx.author.id)
        maintenant = int(time.time())

        rangs: dict[str, list[str]] = {cle: [] for cle in familles}
        cooldowns_actifs = 0
        for game_name, (libelle, famille) in GAME_CATALOG.items():
            if famille not in rangs or not ouvert or game_name in coupes:
                continue
            duree = min(
                int(game_rewards.GAME_COOLDOWNS.get(game_name, 0)),
                game_rewards.MAX_PLAY_COOLDOWN_SECONDS,
            )
            reste = 0
            if duree > 0 and derniers.get(game_name):
                reste = max(0, duree - (maintenant - derniers[game_name]))
            if reste:
                cooldowns_actifs += 1
                etat, marque = f"encore {reste}s", "⏳"
            else:
                etat, marque = "prêt", "·"
            rangs[famille].append(f"{marque} {libelle} — `{prefixe}{game_name}` · {etat}")

        sections = [panels.Section("Aujourd'hui", [
            panels.Ligne("Manches récompensées", limit_text,
                         indice="Au-delà, les parties restent jouables : seule la monnaie est plafonnée."),
            panels.Ligne("Jeux en attente", f"**{cooldowns_actifs}**" if cooldowns_actifs else "**Aucun**",
                         indice="⏳ = il faut patienter un peu avant de rejouer."),
        ])]
        for cle, (titre_famille, quoi) in familles.items():
            lignes = rangs[cle]
            if not lignes:
                continue
            sections.append(panels.Section(f"{titre_famille} — {len(lignes)}", texte=f"*{quoi}*\n" + "\n".join(lignes)))

        if len(sections) == 1:
            sections.append(panels.Section(
                "Aucun jeu disponible",
                texte="Les mini-jeux sont désactivés ici, ou bloqués dans ce salon. "
                      "Un membre du staff peut les rouvrir avec `+gamesetup`.",
            ))

        await panels.envoyer(ctx, panels.Panneau(
            titre=f"{_game_icon('Mini-jeux du jour')} Mini-jeux du jour",
            sous_titre="Ce à quoi vous pouvez jouer, maintenant, sur ce serveur",
            sections=sections,
            kind="jeux",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesRapides(bot))
    await bot.add_cog(GamesDuels(bot))
    await bot.add_cog(GamesCommunity(bot))
    await bot.add_cog(GamesSolo(bot))
    await bot.add_cog(GamesPlayerCommands(bot))
    from cogs.games_setup import GamesSetup
    await bot.add_cog(GamesSetup(bot))
