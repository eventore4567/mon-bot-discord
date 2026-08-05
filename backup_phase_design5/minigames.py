"""
Cog MINI-JEUX.
/rps /guess-number /trivia /tictactoe /hangman /math-quiz /blackjack /slots
"""

import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, helpers

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


class Minigames(commands.Cog, name="Minigames"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="rps", description="Jouer à pierre-feuille-ciseaux contre le bot.")
    @app_commands.describe(choix="Votre choix")
    @app_commands.choices(choix=[
        app_commands.Choice(name="Pierre", value="pierre"),
        app_commands.Choice(name="Feuille", value="feuille"),
        app_commands.Choice(name="Ciseaux", value="ciseaux"),
    ])
    async def rps(self, ctx: commands.Context, choix: str):
        options = ["pierre", "feuille", "ciseaux"]
        bot_choice = random.choice(options)
        if choix == bot_choice:
            result = "Égalité !"
        elif (choix, bot_choice) in [("pierre", "ciseaux"), ("feuille", "pierre"), ("ciseaux", "feuille")]:
            result = "Vous avez gagné ! 🎉"
        else:
            result = "Vous avez perdu !"
        await ctx.send(embed=embeds.info(f"Vous : **{choix}** | Bot : **{bot_choice}**\n{result}"))

    @commands.hybrid_command(name="guess-number", description="Deviner un nombre entre 1 et 100.")
    async def guess_number(self, ctx: commands.Context):
        target = random.randint(1, 100)
        await ctx.send(embed=embeds.info("🔢 J'ai choisi un nombre entre 1 et 100. Vous avez 6 essais ! Écrivez votre réponse dans le chat."))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()

        for attempt in range(6):
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=20)
            except asyncio.TimeoutError:
                return await ctx.send(embed=embeds.warning(f"⏱️ Temps écoulé ! Le nombre était **{target}**."))
            guess = int(msg.content)
            if guess == target:
                return await ctx.send(embed=embeds.success(f"🎉 Bravo ! Vous avez trouvé **{target}** en {attempt + 1} essai(s) !"))
            elif guess < target:
                await ctx.send(embed=embeds.info("📈 Plus grand !"))
            else:
                await ctx.send(embed=embeds.info("📉 Plus petit !"))
        await ctx.send(embed=embeds.warning(f"❌ Vous avez épuisé vos essais. Le nombre était **{target}**."))

    @commands.hybrid_command(name="trivia", description="Répondre à une question de culture générale.")
    async def trivia(self, ctx: commands.Context):
        question, answer = random.choice(TRIVIA_QUESTIONS)
        await ctx.send(embed=embeds.info(f"❓ {question}\nVous avez 15 secondes."))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=15)
        except asyncio.TimeoutError:
            return await ctx.send(embed=embeds.warning(f"⏱️ Temps écoulé ! La réponse était **{answer}**."))
        if msg.content.strip().lower() == answer:
            await ctx.send(embed=embeds.success("✅ Bonne réponse !"))
        else:
            await ctx.send(embed=embeds.error(f"❌ Mauvaise réponse. La bonne réponse était **{answer}**."))

    @commands.hybrid_command(name="tictactoe", description="Jouer au morpion contre un autre membre.", with_app_command=False)
    @app_commands.describe(adversaire="Le membre contre qui jouer")
    async def tictactoe(self, ctx: commands.Context, adversaire: discord.Member):
        if adversaire.bot or adversaire.id == ctx.author.id:
            return await ctx.send(embed=embeds.error("Choisissez un adversaire valide."))
        view = TicTacToeView(ctx.author, adversaire)
        await ctx.send(embed=embeds.neutral("⭕ Morpion", f"{ctx.author.mention} (❌) vs {adversaire.mention} (⭕)\nAu tour de {ctx.author.mention}"), view=view)

    @commands.hybrid_command(name="hangman", description="Jouer au pendu.", with_app_command=False)
    async def hangman(self, ctx: commands.Context):
        words = ["python", "discord", "ordinateur", "clavier", "programmation", "serveur"]
        word = random.choice(words)
        guessed = set()
        tries = 6
        display = "".join(c if c in guessed else "_" for c in word)
        msg = await ctx.send(embed=embeds.info(f"🎯 Pendu : `{display}`\nEssais restants : {tries}"))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and len(m.content) == 1

        while tries > 0 and "_" in display:
            try:
                m = await self.bot.wait_for("message", check=check, timeout=30)
            except asyncio.TimeoutError:
                return await ctx.send(embed=embeds.warning(f"⏱️ Temps écoulé ! Le mot était **{word}**."))
            letter = m.content.lower()
            if letter in word:
                guessed.add(letter)
                display = "".join(c if c in guessed else "_" for c in word)
            else:
                tries -= 1
            await ctx.send(embed=embeds.info(f"🎯 Pendu : `{display}`\nEssais restants : {tries}"))

        if "_" not in display:
            await ctx.send(embed=embeds.success(f"🎉 Bravo ! Le mot était **{word}** !"))
        else:
            await ctx.send(embed=embeds.error(f"❌ Perdu ! Le mot était **{word}**."))

    @commands.hybrid_command(name="math-quiz", description="Répondre à une opération mathématique rapide.", with_app_command=False)
    async def math_quiz(self, ctx: commands.Context):
        a, b = random.randint(2, 50), random.randint(2, 50)
        op = random.choice(list(MATH_OPS))
        answer = MATH_OPS[op](a, b)
        await ctx.send(embed=embeds.info(f"🧮 Combien font **{a} {op} {b}** ? (10 secondes)"))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=10)
        except asyncio.TimeoutError:
            return await ctx.send(embed=embeds.warning(f"⏱️ Temps écoulé ! La réponse était **{answer}**."))
        try:
            if int(msg.content.strip()) == answer:
                await ctx.send(embed=embeds.success("✅ Bonne réponse !"))
            else:
                await ctx.send(embed=embeds.error(f"❌ Faux. La réponse était **{answer}**."))
        except ValueError:
            await ctx.send(embed=embeds.error(f"❌ Ce n'est pas un nombre. La réponse était **{answer}**."))

    @commands.hybrid_command(name="blackjack", description="Jouer au blackjack simplifié contre le bot.", with_app_command=False)
    async def blackjack(self, ctx: commands.Context):
        def draw():
            return random.randint(1, 11)

        player = [draw(), draw()]
        bot_hand = [draw(), draw()]
        await ctx.send(embed=embeds.info(f"🃏 Votre main : {player} (total {sum(player)})\nTapez `hit` pour tirer ou `stand` pour rester."))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() in ("hit", "stand")

        while sum(player) < 21:
            try:
                m = await self.bot.wait_for("message", check=check, timeout=20)
            except asyncio.TimeoutError:
                return await ctx.send(embed=embeds.warning("⏱️ Temps écoulé."))
            if m.content.lower() == "hit":
                player.append(draw())
                await ctx.send(embed=embeds.info(f"🃏 Votre main : {player} (total {sum(player)})"))
            else:
                break

        if sum(player) > 21:
            return await ctx.send(embed=embeds.error(f"💥 Vous avez dépassé 21 ({sum(player)}). Vous perdez !"))

        while sum(bot_hand) < 17:
            bot_hand.append(draw())

        e = embeds.neutral("🃏 Résultat", f"Vous : {sum(player)} | Bot : {sum(bot_hand)}")
        if sum(bot_hand) > 21 or sum(player) > sum(bot_hand):
            e.description += "\n🎉 Vous gagnez !"
        elif sum(player) == sum(bot_hand):
            e.description += "\n🤝 Égalité !"
        else:
            e.description += "\n❌ Vous perdez !"
        await ctx.send(embed=e)

    @commands.hybrid_command(name="slots", description="Jouer à la machine à sous.", with_app_command=False)
    async def slots(self, ctx: commands.Context):
        symbols = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        result = [random.choice(symbols) for _ in range(3)]
        text = " | ".join(result)
        if result[0] == result[1] == result[2]:
            await ctx.send(embed=embeds.success(f"🎰 {text}\n🎉 JACKPOT !"))
        elif len(set(result)) == 2:
            await ctx.send(embed=embeds.info(f"🎰 {text}\n👍 Presque !"))
        else:
            await ctx.send(embed=embeds.error(f"🎰 {text}\n❌ Perdu !"))

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
            return
        if view.is_full():
            for child in view.children:
                child.disabled = True
            await interaction.response.edit_message(content="🤝 Match nul !", view=view)
            return

        view.current_player = view.player_o if view.current_player == view.player_x else view.player_x
        await interaction.response.edit_message(content=f"Au tour de {view.current_player.mention}", view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player_x: discord.Member, player_o: discord.Member):
        super().__init__(timeout=120)
        self.player_x = player_x
        self.player_o = player_o
        self.current_player = player_x
        self.board = [[None] * 3 for _ in range(3)]
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Minigames(bot))
