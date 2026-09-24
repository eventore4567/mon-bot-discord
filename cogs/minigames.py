"""
Cog MINI-JEUX.
+rps +guess-number +trivia +tictactoe +hangman +math-quiz +blackjack +slots

Récompenses économiques (Partie 1 de la demande de Jayden — Phase 4) : tous les jeux de ce
fichier créditent désormais une vraie récompense virtuelle via utils/game_rewards.py, qui
écrit dans la MÊME table `economy` que /balance, /daily, /pay... (aucune deuxième monnaie).
Chaque manche a un session_id unique généré au lancement de la manche (pas à la fin), pour
que la protection anti-double-récompense (contrainte UNIQUE en base) porte bien sur "cette
manche précise" et non sur un identifiant recalculé après coup. Les réglages +gamesetup
(jeu désactivé, salon/rôle bloqué, cooldown, limite journalière...) sont vérifiés avant que
la manche ne démarre — voir Minigames._start().
"""

import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from cogs.games_catalog import ROULEAU_SLOTS
from utils import embeds, helpers, design_system, game_rewards
from utils import sentrix_panels as panels

MATH_OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
}

TRIVIA_QUESTIONS = [
    ("Quelle est la capitale de la France ?", "paris"),
    ("Combien font 7 x 8 ?", "56"),
    ("Quel est le plus grand océan du monde ?", "pacifique"),
    ("En quelle année a eu lieu la Révolution française ?", "1789"),
    ("Quel est le symbole chimique de l'or ?", "au"),
]

# Récompenses de base (avant multiplicateur d'événement +gamesetup) — cohérentes avec
# celles d'economy.py (DAILY_AMOUNT=200, WORK_MIN/MAX=50-250) : des jeux rapides et courts
# rapportent nettement moins qu'une récompense journalière, pour ne pas déséquilibrer
# l'économie existante.
REWARD_RPS = 15
REWARD_GUESS_BASE = 15  # + bonus selon le nombre d'essais (voir guess_number)
REWARD_TRIVIA = 20
REWARD_TICTACTOE = 40
REWARD_HANGMAN = 25
REWARD_MATH_QUIZ = 12
REWARD_BLACKJACK = 25
REWARD_SLOTS_JACKPOT = 100
REWARD_SLOTS_PARTIAL = 20

# Cooldowns courts (secondes), persistés en base (game_cooldowns) — survivent à un
# redémarrage du bot, comme exigé par Jayden pour empêcher le farming en boucle.
COOLDOWN_RAPIDE = 8


class Minigames(commands.Cog, name="Minigames"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Une seule manche collective de Guess Number par salon. Le nombre de
        # participants, lui, n'est jamais limité.
        self._guess_number_channels: set[tuple[int, int]] = set()

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed mini-jeux cohérent avec +designsetup (catégorie CATEGORY_STYLES["games"])."""
        style = design_system.CATEGORY_STYLES["games"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        from utils.game_context import pictogramme_de_titre

        resolu = design_system.kind_title(title, kind=kind, category_emoji=style["emoji"])
        embed = design_system.create_embed(
            title=resolu,
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )
        # Le titre d'un mini-jeu porte le pictogramme de CE jeu, comme dans
        # cogs/games_economy : « Question de culture générale » arrivait nu.
        embed.title = f"{pictogramme_de_titre(title)} {resolu}"
        return embed

    @staticmethod
    def _reward_line(reward: "game_rewards.GameReward | None") -> str:
        """Ligne à ajouter à la description d'un embed de résultat quand une récompense a
        été accordée. Retourne une chaîne vide si aucune récompense (perdu, ou déjà
        récompensé, ou jeu désactivé) — jamais de fausse promesse de gain."""
        if reward and reward.success and reward.amount > 0:
            return f"\n\n🪙 **+{reward.amount}** crédités ! (réf. `{reward.display_id}`)"
        return ""

    async def _start(self, ctx: commands.Context, game_name: str, cooldown: int = COOLDOWN_RAPIDE) -> tuple[bool, str, str | None]:
        """Vérifications communes avant de lancer une manche : serveur requis, jeu activé
        (+gamesetup), cooldown, limite journalière, verrou anti-manches-parallèles. Retourne
        (autorisé, message_erreur, session_id). session_id est déjà généré si autorisé, pour
        être réutilisé tel quel jusqu'à la récompense finale."""
        if ctx.guild is None:
            return False, "🎮 Les mini-jeux ne sont disponibles que sur un serveur.", None
        guild_id = ctx.guild.id
        role_ids = {r.id for r in ctx.author.roles} if isinstance(ctx.author, discord.Member) else set()
        ok, reason = await game_rewards.is_game_enabled(self.bot, guild_id, game_name, ctx.channel.id, role_ids)
        if not ok:
            return False, reason, None
        allowed, remaining = await game_rewards.check_cooldown(self.bot, guild_id, ctx.author.id, game_name, cooldown)
        if not allowed:
            return False, f"⏱️ Encore **{remaining}s** avant de rejouer à ce jeu.", None
        if not game_rewards.acquire_play_lock(guild_id, ctx.author.id, game_name):
            return False, "🎮 Une manche de ce jeu est déjà en cours pour vous.", None
        return True, "", game_rewards.new_session_id(game_name)

    async def _finish(self, ctx: commands.Context, game_name: str, session_id: str, result: str, base_amount: int) -> "game_rewards.GameReward | None":
        """À appeler à la fin de CHAQUE manche démarrée via _start() (gagnée, perdue,
        expirée...), pour libérer le verrou et poser le cooldown — sinon un timeout laisse
        le joueur bloqué. Ne crédite réellement que si result == 'win'."""
        guild_id = ctx.guild.id
        game_rewards.release_play_lock(guild_id, ctx.author.id, game_name)
        await game_rewards.touch_cooldown(self.bot, guild_id, ctx.author.id, game_name)
        if result != "win":
            return None
        allowed, played, limit = await game_rewards.check_daily_limit(self.bot, guild_id, ctx.author.id)
        if not allowed:
            return None
        return await game_rewards.reward_game_winner(self.bot, guild_id, ctx.author.id, game_name, base_amount, session_id, result="win")

    @commands.hybrid_command(name="rps", description="Jouer à pierre-feuille-ciseaux contre le bot.")
    @app_commands.describe(choix="Votre choix")
    @app_commands.choices(choix=[
        app_commands.Choice(name="Pierre", value="pierre"),
        app_commands.Choice(name="Feuille", value="feuille"),
        app_commands.Choice(name="Ciseaux", value="ciseaux"),
    ])
    async def rps(self, ctx: commands.Context, choix: str):
        mains = {"pierre": "✊", "feuille": "✋", "ciseaux": "✌️"}
        options = list(mains)
        # En slash, app_commands.choices verrouille l'argument ; en préfixe, non.
        # `+rps banane` annonçait « vous avez perdu » — une défaite inventée pour
        # une faute de frappe. On le dit, et la manche n'est même pas démarrée.
        choix = str(choix or "").strip().casefold()
        if choix not in mains:
            gestes = " · ".join(f"{mains[o]} `{o}`" for o in options)
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                ctx.guild.id if ctx.guild else None,
                title='Pierre-feuille-ciseaux',
                description=f"Ce choix n'existe pas. Jouez l'un des trois :\n{gestes}",
                kind='warning',
            )))

        started, err, session_id = await self._start(ctx, "rps")
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Pierre-feuille-ciseaux', description=err, kind='warning')))

        bot_choice = random.choice(options)
        if choix == bot_choice:
            result, kind, game_result = "🤝 **Égalité !**", "primary", "draw"
        elif (choix, bot_choice) in [("pierre", "ciseaux"), ("feuille", "pierre"), ("ciseaux", "feuille")]:
            result, kind, game_result = "🎉 **Vous avez gagné !**", "success", "win"
        else:
            result, kind, game_result = "○ **Vous avez perdu.**", "danger", "loss"

        reward = await self._finish(ctx, "rps", session_id, game_result, REWARD_RPS)
        # Le geste se lit d'un coup d'œil : « pierre | feuille » demandait de relire.
        description = (
            f"{mains[choix]} **vous**  ⚔️  **le bot** {mains[bot_choice]}\n"
            f"{choix} contre {bot_choice}\n\n{result}"
        ) + self._reward_line(reward)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Pierre-feuille-ciseaux', description=description, kind=kind)))

    async def _finish_guess_number_round(
        self,
        ctx: commands.Context,
        session_id: str,
        winner: discord.Member | None,
        base_amount: int,
        *,
        participant_count: int,
        total_guesses: int,
    ) -> tuple["game_rewards.GameReward | None", str]:
        """Termine une manche collective et récompense le vrai gagnant, pas forcément
        la personne qui a lancé la commande. Les limites économiques restent appliquées."""
        guild_id = ctx.guild.id
        starter_id = ctx.author.id

        winner_cooldown_ok = True
        remaining = 0
        if winner is not None and winner.id != starter_id:
            winner_cooldown_ok, remaining = await game_rewards.check_cooldown(
                self.bot, guild_id, winner.id, "guess-number", 15
            )

        await game_rewards.touch_cooldown(self.bot, guild_id, starter_id, "guess-number")
        if winner is None:
            return None, ""
        if winner.id != starter_id and winner_cooldown_ok:
            await game_rewards.touch_cooldown(self.bot, guild_id, winner.id, "guess-number")
        if not winner_cooldown_ok:
            return None, f"\n\nLa partie est gagnée, mais la récompense est en cooldown pour encore {remaining}s."

        allowed, _played, limit = await game_rewards.check_daily_limit(self.bot, guild_id, winner.id)
        if not allowed:
            return None, f"\n\nLa partie est gagnée, mais la limite quotidienne de {limit} récompenses est atteinte."

        reward = await game_rewards.reward_game_winner(
            self.bot,
            guild_id,
            winner.id,
            "guess-number",
            base_amount,
            session_id,
            result="win",
            metadata={
                "multiplayer": True,
                "participant_count": participant_count,
                "total_guesses": total_guesses,
                "started_by": starter_id,
            },
        )
        return reward, ""

    @commands.hybrid_command(
        name="guess-number",
        description="Lancer une partie collective pour deviner un nombre entre 1 et 100.",
    )
    async def guess_number(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "guess-number", cooldown=15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Devine le nombre', description=err, kind='warning')))

        channel_key = (ctx.guild.id, ctx.channel.id)
        if channel_key in self._guess_number_channels:
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "guess-number")
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Partie déjà active', description='Une partie collective est déjà en cours dans ce salon. Rejoignez-la en envoyant un nombre.', kind='warning')))

        self._guess_number_channels.add(channel_key)
        target = random.randint(1, 100)
        attempts: dict[int, int] = {}
        participants: set[int] = set()
        denied_notified: set[int] = set()
        total_guesses = 0
        try:
            settings = await game_rewards.get_settings(self.bot, ctx.guild.id)
            allowed_roles = set(settings.get("allowed_role_ids", []))
            blocked_roles = set(settings.get("blocked_role_ids", []))

            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Devine le nombre — partie collective', description="J'ai choisi un nombre entre **1 et 100**.\nTout le monde peut participer : **essais illimités** et **aucune limite de temps**.\nLe premier qui trouve gagne. Une réaction vers le haut signifie « plus grand », et une réaction vers le bas signifie « plus petit ».")))
        except Exception:
            self._guess_number_channels.discard(channel_key)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "guess-number")
            raise

        def check(message: discord.Message) -> bool:
            if message.channel.id != ctx.channel.id or message.author.bot:
                return False
            content = message.content.strip()
            return content.isdigit() and 1 <= int(content) <= 100

        try:
            while True:
                msg = await self.bot.wait_for("message", check=check)

                role_ids = {role.id for role in getattr(msg.author, "roles", [])}
                role_allowed = (
                    (not allowed_roles or bool(role_ids & allowed_roles))
                    and not bool(role_ids & blocked_roles)
                )
                if not role_allowed:
                    if msg.author.id not in denied_notified:
                        denied_notified.add(msg.author.id)
                        await msg.reply(
                            "Vous n'avez pas le rôle requis pour participer à ce mini-jeu.",
                            mention_author=False,
                            delete_after=8,
                        )
                    continue

                attempts[msg.author.id] = attempts.get(msg.author.id, 0) + 1
                participants.add(msg.author.id)
                total_guesses += 1
                guess = int(msg.content.strip())

                if guess == target:
                    bonus = max(0, 6 - attempts[msg.author.id]) * 5
                    reward, reward_note = await self._finish_guess_number_round(
                        ctx,
                        session_id,
                        msg.author,
                        REWARD_GUESS_BASE + bonus,
                        participant_count=len(participants),
                        total_guesses=total_guesses,
                    )
                    description = (
                        f"{msg.author.mention} a trouvé **{target}** en "
                        f"{attempts[msg.author.id]} essai(s).\n"
                        f"Participants : **{len(participants)}** · Réponses : **{total_guesses}**"
                        + self._reward_line(reward)
                        + reward_note
                    )
                    return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Nombre trouvé', description=description, kind='success')))

                reaction = "⬆️" if guess < target else "⬇️"
                try:
                    await msg.add_reaction(reaction)
                except discord.HTTPException:
                    await msg.reply(
                        "Plus grand." if guess < target else "Plus petit.",
                        mention_author=False,
                        delete_after=8,
                    )
        finally:
            self._guess_number_channels.discard(channel_key)
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "guess-number")

    @commands.hybrid_command(name="trivia", description="Répondre à une question de culture générale.")
    async def trivia(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "trivia", cooldown=12)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Question de culture générale', description=err, kind='warning')))

        question, answer = random.choice(TRIVIA_QUESTIONS)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Question de culture générale', description=f'❓ {question}\nVous avez 15 secondes.')))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
        except asyncio.TimeoutError:
            await self._finish(ctx, "trivia", session_id, "loss", 0)
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Temps écoulé', description=f'⏱️ La réponse était **{answer}**.', kind='warning')))
        if game_rewards.answer_matches(msg.content, answer):
            reward = await self._finish(ctx, "trivia", session_id, "win", REWARD_TRIVIA)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Bonne réponse !', description='●' + self._reward_line(reward), kind='success')))
        else:
            await self._finish(ctx, "trivia", session_id, "loss", 0)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Mauvaise réponse', description=f'○ La bonne réponse était **{answer}**.', kind='danger')))

    @commands.hybrid_command(name="tictactoe", description="Jouer au morpion contre un autre membre.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre contre qui jouer")
    async def tictactoe(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Adversaire invalide', description=invalid, kind='danger')))

        started, err, session_id = await self._start(ctx, "tictactoe", cooldown=15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Morpion', description=err, kind='warning')))

        # Les restrictions de rôles +gamesetup valent aussi pour l'adversaire invité.
        opponent_roles = {r.id for r in getattr(adversaire, "roles", [])}
        opponent_ok, opponent_reason = await game_rewards.is_game_enabled(
            self.bot,
            ctx.guild.id,
            "tictactoe",
            ctx.channel.id,
            opponent_roles,
        )
        if not opponent_ok:
            game_rewards.release_play_lock(ctx.guild.id, ctx.author.id, "tictactoe")
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await self._embed(
                        guild_id,
                        title='Morpion',
                        description=f"Adversaire non autorisé : {opponent_reason}",
                        kind='warning',
                    )
                ),
            )

        view = TicTacToeView(ctx.author, adversaire, cog=self, session_id=session_id)
        e = await self._embed(guild_id, title="Morpion", description=f"{ctx.author.mention} (○) vs {adversaire.mention} (⭕)\nAu tour de {ctx.author.mention}")
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(e), view))
        view.message = msg

    @commands.hybrid_command(name="hangman", description="Jouer au pendu.", with_app_command=False)
    async def hangman(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "hangman", cooldown=20)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Pendu', description=err, kind='warning')))

        words = ["python", "discord", "ordinateur", "clavier", "programmation", "serveur", "aventure", "reaction"]
        word = random.choice(words)
        guessed = set()
        tries = 6
        display = "".join(c if c in guessed else "_" for c in word)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Pendu', description=f'🎯 `{display}`\nEssais restants : {tries}')))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and len(m.content) == 1

        while tries > 0 and "_" in display:
            try:
                m = await self.bot.wait_for("message", check=check, timeout=30)
            except asyncio.TimeoutError:
                await self._finish(ctx, "hangman", session_id, "loss", 0)
                return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Temps écoulé', description=f'⏱️ Le mot était **{word}**.', kind='warning')))
            letter = m.content.lower()
            if letter in guessed:
                await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Pendu', description=f'Lettre déjà proposée : **{letter}**\n🎯 `{display}`\nEssais restants : {tries}', kind='warning')))
                continue
            if letter in word:
                guessed.add(letter)
                display = "".join(c if c in guessed else "_" for c in word)
            else:
                guessed.add(letter)
                tries -= 1
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Pendu', description=f'🎯 `{display}`\nEssais restants : {tries}')))

        if "_" not in display:
            reward = await self._finish(ctx, "hangman", session_id, "win", REWARD_HANGMAN)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Gagné !', description=f'🎉 Le mot était **{word}** !' + self._reward_line(reward), kind='success')))
        else:
            await self._finish(ctx, "hangman", session_id, "loss", 0)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Perdu', description=f'○ Le mot était **{word}**.', kind='danger')))

    @commands.hybrid_command(name="math-quiz", description="Répondre à une opération mathématique rapide.", with_app_command=False)
    async def math_quiz(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "math-quiz")
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Quiz mathématique', description=err, kind='warning')))

        a, b = random.randint(2, 50), random.randint(2, 50)
        op = random.choice(list(MATH_OPS))
        answer = MATH_OPS[op](a, b)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Quiz mathématique', description=f"🧮 Combien font **{a} {('×' if op == '*' else op)} {b}** ? (10 secondes)")))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=10)
        except asyncio.TimeoutError:
            await self._finish(ctx, "math-quiz", session_id, "loss", 0)
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Temps écoulé', description=f'⏱️ La réponse était **{answer}**.', kind='warning')))
        try:
            if int(msg.content.strip()) == answer:
                reward = await self._finish(ctx, "math-quiz", session_id, "win", REWARD_MATH_QUIZ)
                await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Bonne réponse !', description='●' + self._reward_line(reward), kind='success')))
            else:
                await self._finish(ctx, "math-quiz", session_id, "loss", 0)
                await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Faux', description=f'○ La réponse était **{answer}**.', kind='danger')))
        except ValueError:
            await self._finish(ctx, "math-quiz", session_id, "loss", 0)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Réponse invalide', description=f"○ Ce n'est pas un nombre. La réponse était **{answer}**.", kind='danger')))

    # ---- Blackjack : un vrai paquet de 52 cartes -----------------------------
    # L'ancienne version tirait `random.randint(1, 11)` et affichait la liste
    # Python telle quelle : « Votre main : [1, 9] ». Illisible, et faux — un 1
    # est un as, qui vaut 11 tant que la main ne dépasse pas 21.
    ENSEIGNES = ("♠", "♥", "♦", "♣")
    VALEURS = (
        ("A", 11), ("2", 2), ("3", 3), ("4", 4), ("5", 5), ("6", 6), ("7", 7),
        ("8", 8), ("9", 9), ("10", 10), ("V", 10), ("D", 10), ("R", 10),
    )

    @classmethod
    def _paquet(cls) -> list[tuple[str, int]]:
        """52 cartes mélangées. Un paquet fini : on ne peut plus tirer cinq as."""
        paquet = [
            (f"{figure}{enseigne}", valeur)
            for enseigne in cls.ENSEIGNES
            for figure, valeur in cls.VALEURS
        ]
        random.shuffle(paquet)
        return paquet

    @staticmethod
    def _total(main: list[tuple[str, int]]) -> int:
        """Total de la main, les as retombant à 1 tant que ça dépasse 21."""
        total = sum(valeur for _carte, valeur in main)
        as_restants = sum(1 for carte, _valeur in main if carte.startswith("A"))
        while total > 21 and as_restants:
            total -= 10
            as_restants -= 1
        return total

    @classmethod
    def _main_lisible(cls, main: list[tuple[str, int]]) -> str:
        return " ".join(f"`{carte}`" for carte, _valeur in main)

    @commands.hybrid_command(name="blackjack", description="Jouer au blackjack simplifié contre le bot.", with_app_command=False)
    async def blackjack(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "blackjack", cooldown=15)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Blackjack', description=err, kind='warning')))

        paquet = self._paquet()
        player = [paquet.pop(), paquet.pop()]
        bot_hand = [paquet.pop(), paquet.pop()]

        def table(cache_le_bot: bool = True) -> str:
            if cache_le_bot:
                visible = f"{self._main_lisible(bot_hand[:1])} `??`"
                score_bot = "?"
            else:
                visible, score_bot = self._main_lisible(bot_hand), self._total(bot_hand)
            return (
                f"🃏 **Votre main** — {self._main_lisible(player)} · total **{self._total(player)}**\n"
                f"🤖 **Le bot** — {visible} · total **{score_bot}**"
            )

        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
            guild_id, title='Blackjack',
            description=(
                f"{table()}\n\n"
                "🎯 Objectif : s'approcher de **21** sans le dépasser.\n"
                "Tapez `hit` pour tirer une carte ou `stand` pour vous arrêter. "
                "Vous avez **20 secondes** par décision."
            ),
        )))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ("hit", "stand")

        while self._total(player) < 21:
            try:
                m = await self.bot.wait_for("message", check=check, timeout=20)
            except asyncio.TimeoutError:
                await self._finish(ctx, "blackjack", session_id, "loss", 0)
                return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                    guild_id, title='Temps écoulé',
                    description=f"⏱️ Plus de 20 secondes sans réponse.\n\n{table(cache_le_bot=False)}",
                    kind='warning',
                )))
            if m.content.lower() == "hit":
                tiree = paquet.pop()
                player.append(tiree)
                await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                    guild_id, title='Blackjack',
                    description=f"🂠 Vous tirez `{tiree[0]}`.\n\n{table()}",
                )))
            else:
                break

        if self._total(player) > 21:
            await self._finish(ctx, "blackjack", session_id, "loss", 0)
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                guild_id, title='Blackjack',
                description=(
                    f"💥 **Vous dépassez 21** avec {self._total(player)}.\n\n"
                    f"{table(cache_le_bot=False)}"
                ),
                kind='danger',
            )))

        while self._total(bot_hand) < 17:
            bot_hand.append(paquet.pop())

        total_joueur, total_bot = self._total(player), self._total(bot_hand)
        if total_bot > 21:
            issue, kind, game_result = f"🎉 **Le bot dépasse 21** ({total_bot}) — vous gagnez !", "success", "win"
        elif total_joueur > total_bot:
            issue, kind, game_result = f"🎉 **{total_joueur} contre {total_bot}** — vous gagnez !", "success", "win"
        elif total_joueur == total_bot:
            issue, kind, game_result = f"🤝 **Égalité à {total_joueur}.**", "primary", "draw"
        else:
            issue, kind, game_result = f"○ **{total_bot} contre {total_joueur}** — le bot l'emporte.", "danger", "loss"
        reward = await self._finish(ctx, "blackjack", session_id, game_result, REWARD_BLACKJACK)
        e = await self._embed(
            guild_id, title="Blackjack",
            description=f"{table(cache_le_bot=False)}\n\n{issue}" + self._reward_line(reward),
            kind=kind,
        )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    # ---- Machine à sous : rouleau pondéré ------------------------------------
    _MULTIPLICATEURS = tuple((symbole, mult) for symbole, _poids, mult in ROULEAU_SLOTS)

    @staticmethod
    def _tirer_rouleau() -> str:
        """Un symbole, tiré selon son poids. De l'argent réel en dépend : le
        tirage passe par game_rewards, pas par random."""
        tirage = game_rewards.secure_randint(1, sum(p for _s, p, _m in ROULEAU_SLOTS))
        for symbole, poids, _mult in ROULEAU_SLOTS:
            tirage -= poids
            if tirage <= 0:
                return symbole
        return ROULEAU_SLOTS[0][0]

    @staticmethod
    def _table_des_gains() -> str:
        """Ce que paie chaque symbole — un joueur ne devrait pas avoir à deviner."""
        return "Trois symboles identiques : " + " · ".join(
            f"{symbole} x{mult:g}" for symbole, _poids, mult in ROULEAU_SLOTS
        )

    @commands.hybrid_command(name="slots", description="Jouer à la machine à sous.", with_app_command=False)
    async def slots(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "slots", cooldown=10)
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Machine à sous', description=err, kind='warning')))

        result = [self._tirer_rouleau() for _ in range(3)]
        text = " | ".join(result)
        gains = dict(self._MULTIPLICATEURS)
        # Le gain suit le symbole : trois 7️⃣ ne peuvent pas payer comme trois 🍒,
        # sinon les symboles rares ne sont que du décor.
        if result[0] == result[1] == result[2]:
            multiplicateur = gains.get(result[0], 1.0)
            montant = max(1, round(REWARD_SLOTS_JACKPOT * multiplicateur))
            reward = await self._finish(ctx, "slots", session_id, "win", montant)
            titre = "🎉 **JACKPOT !**" if multiplicateur < 4 else "💥 **GROS JACKPOT !**"
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                guild_id, title='Machine à sous',
                description=(
                    f"🎰 {text}\n{titre}\n"
                    f"Trois {result[0]} — gains **x{multiplicateur:g}**"
                    + self._reward_line(reward)
                ),
                kind='success',
            )))
        elif len(set(result)) == 2:
            paire = next(sym for sym in result if result.count(sym) == 2)
            multiplicateur = max(1.0, gains.get(paire, 1.0) / 2)
            montant = max(1, round(REWARD_SLOTS_PARTIAL * multiplicateur))
            reward = await self._finish(ctx, "slots", session_id, "win", montant)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                guild_id, title='Machine à sous',
                description=(
                    f"🎰 {text}\n👍 **Une paire de {paire}**"
                    + (f" — gains **x{multiplicateur:g}**" if multiplicateur > 1 else "")
                    + self._reward_line(reward)
                ),
            )))
        else:
            await self._finish(ctx, "slots", session_id, "loss", 0)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                guild_id, title='Machine à sous',
                description=(
                    f"🎰 {text}\n○ **Perdu !** Trois symboles différents.\n"
                    f"-# {self._table_des_gains()}"
                ),
                kind='danger',
            )))


class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="​", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        view: "TicTacToeView" = self.view
        if interaction.user.id != view.current_player.id:
            return await interaction.response.send_message("Ce n'est pas votre tour !", ephemeral=True)
        symbol = "○" if view.current_player == view.player_x else "⭕"
        self.label = symbol
        self.style = discord.ButtonStyle.danger if symbol == "○" else discord.ButtonStyle.primary
        self.disabled = True
        view.board[self.y][self.x] = symbol

        winner = view.check_winner()
        if winner:
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(content=f"🎉 {view.current_player.mention} a gagné !", view=view)
            await view._reward_winner(view.current_player)
            return
        if view.is_full():
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(content="🤝 Match nul !", view=view)
            await view._finish_draw()
            return

        view.current_player = view.player_o if view.current_player == view.player_x else view.player_x
        await interaction.response.edit_message(content=f"Au tour de {view.current_player.mention}", view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player_x: discord.Member, player_o: discord.Member, *, cog: "Minigames | None" = None, session_id: str | None = None):
        super().__init__(timeout=120)
        self.player_x = player_x
        self.player_o = player_o
        self.current_player = player_x
        self.board = [[None] * 3 for _ in range(3)]
        self.cog = cog
        self.session_id = session_id
        self.message: discord.Message | None = None
        self._settled = False
        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    async def _close_session(self) -> int | None:
        """Ferme exactement une fois le verrou/cooldown de la manche."""
        if self._settled or self.cog is None:
            return None
        self._settled = True
        guild = getattr(self.player_x, "guild", None)
        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            return None

        game_rewards.release_play_lock(guild_id, self.player_x.id, "tictactoe")
        # Les deux joueurs ont participé : le cooldown empêche les invitations en boucle.
        await game_rewards.touch_cooldown(self.cog.bot, guild_id, self.player_x.id, "tictactoe")
        await game_rewards.touch_cooldown(self.cog.bot, guild_id, self.player_o.id, "tictactoe")
        return guild_id

    async def on_timeout(self):
        guild_id = await self._close_session()
        if guild_id is None:
            return
        if self.session_id is not None:
            await game_rewards.reward_game_winner(
                self.cog.bot,
                guild_id,
                self.player_x.id,
                "tictactoe",
                0,
                self.session_id,
                result="draw",
                metadata={"reason": "timeout"},
            )
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def check_winner(self):
        b = self.board
        lines = []
        lines.extend(b)
        lines.extend([[b[y][x] for y in range(3)] for x in range(3)])
        lines.append([b[i][i] for i in range(3)])
        lines.append([b[i][2 - i] for i in range(3)])
        for line in lines:
            if line[0] and line[0] == line[1] == line[2]:
                return line[0]
        return None

    def is_full(self):
        return all(cell is not None for row in self.board for cell in row)

    async def _reward_winner(self, winner: discord.Member):
        """Crédite le gagnant puis ferme verrou + cooldown pour les deux joueurs."""
        if self.cog is None or self.session_id is None:
            return
        guild_id = await self._close_session()
        if guild_id is None:
            return
        await game_rewards.reward_game_winner(
            self.cog.bot,
            guild_id,
            winner.id,
            "tictactoe",
            REWARD_TICTACTOE,
            self.session_id,
            result="win",
        )

    async def _finish_draw(self):
        if self.cog is None or self.session_id is None:
            return
        guild_id = await self._close_session()
        if guild_id is None:
            return
        await game_rewards.reward_game_winner(
            self.cog.bot,
            guild_id,
            self.player_x.id,
            "tictactoe",
            0,
            self.session_id,
            result="draw",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Minigames(bot))
