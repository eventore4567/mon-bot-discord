"""
Cog INTELLIGENCE ARTIFICIELLE.
/sentrix /ask /chat-reset /summarize /image-prompt /explain /rewrite /fact-check
"""

import re
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds


class Ai(commands.Cog, name="Ai"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.histories: dict[int, list] = {}

    def client(self):
        import config
        if not config.OPENAI_API_KEY:
            return None
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    async def ask_ai(self, prompt: str, history: list = None) -> str:
        client = self.client()
        if not client:
            return "__NO_KEY__"
        messages = [{"role": "system", "content": "Tu es un assistant utile, réponds toujours en français, de façon concise."}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        try:
            resp = await client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=600)
            return resp.choices[0].message.content
        except Exception as exc:
            return f"__ERROR__{exc}"

    async def ask_ai_with_confidence(self, prompt: str, history: list = None) -> tuple[str, int]:
        """Comme ask_ai, mais demande aussi à l'IA un indice de confiance (1-10) sur sa réponse."""
        client = self.client()
        if not client:
            return "__NO_KEY__", 0
        messages = [{
            "role": "system",
            "content": (
                "Tu es SentriX, l'assistant IA de ce serveur Discord. Réponds toujours en français, "
                "de façon claire et concise, à n'importe quelle question. "
                "Termine TOUJOURS ta réponse par une dernière ligne exactement au format "
                "'CONFIANCE: X/10' (X = ton indice de confiance dans l'exactitude de ta réponse, entre 1 et 10)."
            ),
        }]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        try:
            resp = await client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=600)
            content = resp.choices[0].message.content or ""
        except Exception as exc:
            return f"__ERROR__{exc}", 0

        confidence = 8
        match = re.search(r"CONFIANCE\s*:\s*(\d{1,2})\s*/\s*10", content, re.IGNORECASE)
        if match:
            confidence = max(1, min(10, int(match.group(1))))
            content = content[:match.start()].rstrip(" \n-")
        return content, confidence

    @commands.hybrid_command(
        name="sentrix",
        description="Demandez n'importe quoi à SentriX : l'IA du bot répond avec un indice de confiance.",
    )
    @app_commands.describe(question="Votre question, sur n'importe quel sujet")
    async def sentrix(self, ctx: commands.Context, *, question: str):
        if ctx.interaction:
            await ctx.defer()
        history = self.histories.get(ctx.author.id, [])
        answer, confidence = await self.ask_ai_with_confidence(question, history)
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot. Contactez un administrateur."))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=embeds.error("Une erreur est survenue avec l'IA. Réessayez plus tard."))
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self.histories[ctx.author.id] = history[-10:]

        e = embeds.brand("🧠 SentriX")
        e.add_field(name="❓ Question", value=question[:1024], inline=False)
        e.add_field(name="💬 Réponse", value=answer[:1000] or "…", inline=False)
        e.add_field(
            name="📡 Indice de confiance",
            value=f"{embeds.bar(confidence, 10)}  **{confidence}/10**",
            inline=False,
        )
        e.set_footer(text=f"SentriX AI • Demandé par {ctx.author}")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="ask", description="Poser une question à l'IA.")
    @app_commands.describe(question="Votre question pour l'IA")
    async def ask(self, ctx: commands.Context, *, question: str):
        if ctx.interaction:
            await ctx.defer()
        history = self.histories.get(ctx.author.id, [])
        answer = await self.ask_ai(question, history)
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot. Contactez un administrateur."))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=embeds.error("Une erreur est survenue avec l'IA. Réessayez plus tard."))
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self.histories[ctx.author.id] = history[-10:]
        e = embeds.neutral("🤖 Réponse de l'IA", answer[:4000])
        e.set_footer(text=f"Demandé par {ctx.author}")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="chat-reset", description="Réinitialiser votre historique de conversation avec l'IA.", with_app_command=False)
    async def chat_reset(self, ctx: commands.Context):
        self.histories.pop(ctx.author.id, None)
        await ctx.send(embed=embeds.success("🧹 Votre historique de conversation a été réinitialisé."))

    @commands.hybrid_command(name="summarize", description="Résumer un texte avec l'IA.")
    @app_commands.describe(texte="Le texte à résumer")
    async def summarize(self, ctx: commands.Context, *, texte: str):
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Résume ce texte en 3-4 phrases maximum :\n\n{texte}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot."))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=embeds.error("Une erreur est survenue avec l'IA."))
        await ctx.send(embed=embeds.neutral("📝 Résumé", answer[:4000]))

    @commands.hybrid_command(name="image-prompt", description="Générer une idée détaillée de prompt d'image avec l'IA.", with_app_command=False)
    @app_commands.describe(sujet="Le sujet de l'image souhaitée")
    async def image_prompt(self, ctx: commands.Context, *, sujet: str):
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Génère un prompt détaillé et créatif en anglais pour un générateur d'images IA, sur ce sujet : {sujet}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot."))
        await ctx.send(embed=embeds.neutral("🎨 Prompt généré", answer[:4000]))

    @commands.hybrid_command(name="explain", description="Demander à l'IA d'expliquer un concept simplement.", with_app_command=False)
    @app_commands.describe(sujet="Le concept à expliquer")
    async def explain(self, ctx: commands.Context, *, sujet: str):
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Explique ce concept simplement, comme à un débutant : {sujet}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot."))
        await ctx.send(embed=embeds.neutral("💡 Explication", answer[:4000]))

    @commands.hybrid_command(name="rewrite", description="Demander à l'IA de reformuler un texte.", with_app_command=False)
    @app_commands.describe(texte="Le texte à reformuler")
    async def rewrite(self, ctx: commands.Context, *, texte: str):
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Reformule ce texte de façon plus claire, en gardant le sens original :\n\n{texte}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot."))
        await ctx.send(embed=embeds.neutral("✏️ Reformulation", answer[:4000]))

    @commands.hybrid_command(name="fact-check", description="Demander à l'IA de vérifier une affirmation (à titre indicatif).", with_app_command=False)
    @app_commands.describe(affirmation="L'affirmation à vérifier")
    async def fact_check(self, ctx: commands.Context, *, affirmation: str):
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(
            f"Évalue la véracité probable de cette affirmation, avec prudence et nuance, en précisant que ce n'est pas une vérification garantie : {affirmation}"
        )
        if answer == "__NO_KEY__":
            return await ctx.send(embed=embeds.error("Aucune clé OpenAI n'est configurée sur ce bot."))
        e = embeds.neutral("🔍 Vérification (indicative)", answer[:4000])
        e.set_footer(text="⚠️ Réponse générée par IA, à vérifier par vous-même.")
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ai(bot))
