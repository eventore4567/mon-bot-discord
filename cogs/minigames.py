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

from utils import embeds, helpers, design_system, game_rewards

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

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed mini-jeux cohérent avec +designsetup (catégorie CATEGORY_STYLES["games"])."""
        style = design_system.CATEGORY_STYLES["games"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

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
        started, err, session_id = await self._start(ctx, "rps")
        if not started:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Pierre-feuille-ciseaux", description=err, kind="warning"))

        options = ["pierre", "feuille", "ciseaux"]
        bot_choice = random.choice(options)
        if choix == bot_choice:
            result, kind, game_result = "Égalité !", "primary", "draw"
        elif (choix, bot_choice) in [("pierre", "ciseaux"), ("feuille", "pierre"), ("ciseaux", "feuille")]:
            result, kind, game_result = "Vous avez gagné ! 🎉", "success", "win"
        else:
            result, kind, game_result = "Vous avez perdu !", "danger", "loss"

        reward = await self._finish(ctx, "rps", session_id, game_result, REWARD_RPS)
        description = f"Vous : **{choix}** | Bot : **{bot_choice}**\n{result}" + self._reward_line(reward)
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Pierre-feuille-ciseaux", description=description, kind=kind))

    @commands.hybrid_command(name="guess-number", description="Deviner un nombre entre 1 et 100.")
    async def guess_number(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "guess-number", cooldown=15)
        if not started:
            return await ctx.send(embed=await self._embed(guild_id, title="Devine le nombre", description=err, kind="warning"))

        target = random.randint(1, 100)
        await ctx.send(embed=await self._embed(guild_id, title="Devine le nombre", description="J'ai choisi un nombre entre 1 et 100. Vous avez 6 essais ! Écrivez votre réponse dans le chat."))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()

        for attempt in range(6):
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=20)
            except asyncio.TimeoutError:
                await self._finish(ctx, "guess-number", session_id, "loss", 0)
                return await ctx.send(embed=await self._embed(guild_id, title="Temps écoulé", description=f"⏱️ Le nombre était **{target}**.", kind="warning"))
            guess = int(msg.content)
            if guess == target:
                # Bonus si trouvé rapidement : jusqu'à +25 en plus du montant de base pour un coup au but.
                bonus = max(0, (6 - attempt - 1)) * 5
                reward = await self._finish(ctx, "guess-number", session_id, "win", REWARD_GUESS_BASE + bonus)
                description = f"🎉 Bravo ! Vous avez trouvé **{target}** en {attempt + 1} essai(s) !" + self._reward_line(reward)
                return await ctx.send(embed=await self._embed(guild_id, title="Trouvé !", description=description, kind="success"))
            elif guess < target:
                await ctx.send(embed=await self._embed(guild_id, title="Plus grand !", description="📈"))
            else:
                await ctx.send(embed=await self._embed(guild_id, title="Plus petit !", description="📉"))
        await self._finish(ctx, "guess-number", session_id, "loss", 0)
        await ctx.send(embed=await self._embed(guild_id, title="Essais épuisés", description=f"❌ Le nombre était **{target}**.", kind="warning"))

    @commands.hybrid_command(name="trivia", description="Répondre à une question de culture générale.")
    async def trivia(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "trivia", cooldown=12)
        if not started:
            return await ctx.send(embed=await self._embed(guild_id, title="Question de culture générale", description=err, kind="warning"))

        question, answer = random.choice(TRIVIA_QUESTIONS)
        await ctx.send(embed=await self._embed(guild_id, title="Question de culture générale", description=f"❓ {question}\nVous avez 15 secondes."))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
        except asyncio.TimeoutError:
            await self._finish(ctx, "trivia", session_id, "loss", 0)
            return await ctx.send(embed=await self._embed(guild_id, title="Temps écoulé", description=f"⏱️ La réponse était **{answer}**.", kind="warning"))
        if msg.content.strip().lower() == answer:
            reward = await self._finish(ctx, "trivia", session_id, "win", REWARD_TRIVIA)
            await ctx.send(embed=await self._embed(guild_id, title="Bonne réponse !", description="✅" + self._reward_line(reward), kind="success"))
        else:
            await self._finish(ctx, "trivia", session_id, "loss", 0)
            await ctx.send(embed=await self._embed(guild_id, title="Mauvaise réponse", description=f"❌ La bonne réponse était **{answer}**.", kind="danger"))

    @commands.hybrid_command(name="tictactoe", description="Jouer au morpion contre un autre membre.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre contre qui jouer")
    async def tictactoe(self, ctx: commands.Context, adversaire: discord.Member):
        guild_id = ctx.guild.id if ctx.guild else None
        invalid = game_rewards.validate_opponent(ctx.author, adversaire)
        if invalid:
            return await ctx.send(embed=await self._embed(guild_id, title="Adversaire invalide", description=invalid, kind="danger"))
        if ctx.guild is None:
            return await ctx.send(embed=await self._embed(guild_id, title="Morpion", description="🎮 Les mini-jeux ne sont disponibles que sur un serveur.", kind="warning"))
        ok, reason = await game_rewards.is_game_enabled(self.bot, ctx.guild.id, "tictactoe", ctx.channel.id)
        if not ok:
            return await ctx.send(embed=await self._embed(guild_id, title="Morpion", description=reason, kind="warning"))
        session_id = game_rewards.new_session_id("tictactoe")
        view = TicTacToeView(ctx.author, adversaire, cog=self, session_id=session_id)
        e = await self._embed(guild_id, title="Morpion", description=f"{ctx.author.mention} (❌) vs {adversaire.mention} (⭕)\nAu tour de {ctx.author.mention}")
        await ctx.send(embed=e, view=view)

    @commands.hybrid_command(name="hangman", description="Jouer au pendu.", with_app_command=False)
    async def hangman(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "hangman", cooldown=20)
        if not started:
            return await ctx.send(embed=await self._embed(guild_id, title="Pendu", description=err, kind="warning"))

        words = ["python", "discord", "ordinateur", "clavier", "programmation", "serveur"]
        word = random.choice(words)
        guessed = set()
        tries = 6
        display = "".join(c if c in guessed else "_" for c in word)
        await ctx.send(embed=await self._embed(guild_id, title="Pendu", description=f"🎯 `{display}`\nEssais restants : {tries}"))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and len(m.content) == 1

        while tries > 0 and "_" in display:
            try:
                m = await self.bot.wait_for("message", check=check, timeout=30)
            except asyncio.TimeoutError:
                await self._finish(ctx, "hangman", session_id, "loss", 0)
                return await ctx.send(embed=await self._embed(guild_id, title="Temps écoulé", description=f"⏱️ Le mot était **{word}**.", kind="warning"))
            letter = m.content.lower()
            if letter in word:
                guessed.add(letter)
                display = "".join(c if c in guessed else "_" for c in word)
            else:
                tries -= 1
            await ctx.send(embed=await self._embed(guild_id, title="Pendu", description=f"🎯 `{display}`\nEssais restants : {tries}"))

        if "_" not in display:
            reward = await self._finish(ctx, "hangman", session_id, "win", REWARD_HANGMAN)
            await ctx.send(embed=await self._embed(guild_id, title="Gagné !", description=f"🎉 Le mot était **{word}** !" + self._reward_line(reward), kind="success"))
        else:
            await self._finish(ctx, "hangman", session_id, "loss", 0)
            await ctx.send(embed=await self._embed(guild_id, title="Perdu", description=f"❌ Le mot était **{word}**.", kind="danger"))

    @commands.hybrid_command(name="math-quiz", description="Répondre à une opération mathématique rapide.", with_app_command=False)
    async def math_quiz(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "math-quiz")
        if not started:
            return await ctx.send(embed=await self._embed(guild_id, title="Quiz mathématique", description=err, kind="warning"))

        a, b = random.randint(2, 50), random.randint(2, 50)
        op = random.choice(list(MATH_OPS))
        answer = MATH_OPS[op](a, b)
        await ctx.send(embed=await self._embed(guild_id, title="Quiz mathématique", description=f"🧮 Combien font **{a} {op} {b}** ? (10 secondes)"))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=10)
        except asyncio.TimeoutError:
            await self._finish(ctx, "math-quiz", session_id, "loss", 0)
            return await ctx.send(embed=await self._embed(guild_id, title="Temps écoulé", description=f"⏱️ La réponse était **{answer}**.", kind="warning"))
        try:
            if int(msg.content.strip()) == answer:
                reward = await self._finish(ctx, "math-quiz", session_id, "win", REWARD_MATH_QUIZ)
                await ctx.send(embed=await self._embed(guild_id, title="Bonne réponse !", description="✅" + self._reward_line(reward), kind="success"))
            else:
                await self._finish(ctx, "math-quiz", session_id, "loss", 0)
                await ctx.send(embed=await self._embed(guild_id, title="Faux", description=f"❌ La réponse était **{answer}**.", kind="danger"))
        except ValueError:
            await self._finish(ctx, "math-quiz", session_id, "loss", 0)
            await ctx.send(embed=await self._embed(guild_id, title="Réponse invalide", description=f"❌ Ce n'est pas un nombre. La réponse était **{answer}**.", kind="danger"))

    @commands.hybrid_command(name="blackjack", description="Jouer au blackjack simplifié contre le bot.", with_app_command=False)
    async def blackjack(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "blackjack", cooldown=15)
        if not started:
            return await ctx.send(embed=await self._embed(guild_id, title="Blackjack", description=err, kind="warning"))

        def draw():
            return random.randint(1, 11)

        player = [draw(), draw()]
        bot_hand = [draw(), draw()]
        await ctx.send(embed=await self._embed(guild_id, title="Blackjack", description=f"🃏 Votre main : {player} (total {sum(player)})\nTapez `hit` pour tirer ou `stand` pour rester."))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ("hit", "stand")

        while sum(player) < 21:
            try:
                m = await self.bot.wait_for("message", check=check, timeout=20)
            except asyncio.TimeoutError:
                await self._finish(ctx, "blackjack", session_id, "loss", 0)
                return await ctx.send(embed=await self._embed(guild_id, title="Temps écoulé", kind="warning"))
            if m.content.lower() == "hit":
                player.append(draw())
                await ctx.send(embed=await self._embed(guild_id, title="Blackjack", description=f"🃏 Votre main : {player} (total {sum(player)})"))
            else:
                break

        if sum(player) > 21:
            await self._finish(ctx, "blackjack", session_id, "loss", 0)
            return await ctx.send(embed=await self._embed(guild_id, title="Perdu", description=f"💥 Vous avez dépassé 21 ({sum(player)}). Vous perdez !", kind="danger"))

        while sum(bot_hand) < 17:
            bot_hand.append(draw())

        if sum(bot_hand) > 21 or sum(player) > sum(bot_hand):
            issue, kind, game_result = "🎉 Vous gagnez !", "success", "win"
        elif sum(player) == sum(bot_hand):
            issue, kind, game_result = "🤝 Égalité !", "primary", "draw"
        else:
            issue, kind, game_result = "❌ Vous perdez !", "danger", "loss"
        reward = await self._finish(ctx, "blackjack", session_id, game_result, REWARD_BLACKJACK)
        e = await self._embed(guild_id, title="Résultat", description=f"Vous : {sum(player)} | Bot : {sum(bot_hand)}\n{issue}" + self._reward_line(reward), kind=kind)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="slots", description="Jouer à la machine à sous.", with_app_command=False)
    async def slots(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        started, err, session_id = await self._start(ctx, "slots", cooldown=10)
        if not started:
            return await ctx.send(embed=await self._embed(guild_id, title="Machine à sous", description=err, kind="warning"))

        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        result = [game_rewards.secure_pick(symbols) for _ in range(3)]
        text = " | ".join(result)
        if result[0] == result[1] == result[2]:
            reward = await self._finish(ctx, "slots", session_id, "win", REWARD_SLOTS_JACKPOT)
            await ctx.send(embed=await self._embed(guild_id, title="Machine à sous", description=f"🎰 {text}\n🎉 JACKPOT !" + self._reward_line(reward), kind="success"))
        elif len(set(result)) == 2:
            reward = await self._finish(ctx, "slots", session_id, "win", REWARD_SLOTS_PARTIAL)
            await ctx.send(embed=await self._embed(guild_id, title="Machine à sous", description=f"🎰 {text}\n👍 Presque !" + self._reward_line(reward)))
        else:
            await self._finish(ctx, "slots", session_id, "loss", 0)
            await ctx.send(embed=await self._embed(guild_id, title="Machine à sous", description=f"🎰 {text}\n❌ Perdu !", kind="danger"))


class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="​", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        view: "TicTacToeView" = self.view
        if interaction.user.id != view.current_player.id:
            return await interaction.response.send_message("Ce n'est pas votre tour !", ephemeral=True)
        symbol = "❌" if view.current_player == view.player_x else "⭕"
        self.label = symbol
        self.style = discord.ButtonStyle.danger if symbol == "❌" else discord.ButtonStyle.primary
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
        self._settled = False
        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

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
        """Crédite le gagnant du duel (récompense réelle, via game_rewards) — l'adversaire
        ne reçoit rien, aucune mise n'est prélevée à personne (pas de pari entre joueurs)."""
        if self._settled or self.cog is None or self.session_id is None:
            return
        self._settled = True
        guild_id = self.player_x.guild.id if hasattr(self.player_x, "guild") and self.player_x.guild else None
        if guild_id is None:
            return
        await game_rewards.reward_game_winner(
            self.cog.bot, guild_id, winner.id, "tictactoe", REWARD_TICTACTOE, self.session_id, result="win",
        )

    async def _finish_draw(self):
        if self._settled or self.cog is None or self.session_id is None:
            return
        self._settled = True
        guild_id = self.player_x.guild.id if hasattr(self.player_x, "guild") and self.player_x.guild else None
        if guild_id is None:
            return
        await game_rewards.reward_game_winner(
            self.cog.bot, guild_id, self.player_x.id, "tictactoe", 0, self.session_id, result="draw",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Minigames(bot))
