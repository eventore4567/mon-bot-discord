"""
Cog INTELLIGENCE ARTIFICIELLE.
/sentrix /ask /chat-reset /summarize /image-prompt /explain /rewrite /fact-check

En plus de la commande /sentrix, le bot répond aussi quand on lui parle directement dans
le chat : soit en le mentionnant (@SentriX ...), soit en commençant son message par
"sentrix" (ex: "sentrix comment tu vas ?"), sans avoir besoin d'une vraie commande.
"""

import logging
import re
import traceback

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, design_system

logger = logging.getLogger("bot.ai")


def _ai_error_detail(answer: str) -> str:
    """Extrait et tronque le détail technique d'une erreur IA (préfixe __ERROR__), pour
    l'afficher au staff au lieu d'un message générique sans information. BUG CORRIGÉ : avant,
    l'exception réelle (clé invalide, quota dépassé, accès au modèle refusé, etc.) était
    silencieusement jetée — impossible de savoir pourquoi "Erreur IA" s'affichait."""
    return answer[len("__ERROR__"):][:300]


class Ai(commands.Cog, name="Ai"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.histories: dict[int, list] = {}

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed IA cohérent avec +designsetup (catégorie CATEGORY_STYLES["ai"])."""
        style = design_system.CATEGORY_STYLES["ai"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

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
            logger.error("Erreur OpenAI (ask_ai) :\n%s", traceback.format_exc())
            return f"__ERROR__{type(exc).__name__}: {exc}"

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
            logger.error("Erreur OpenAI (ask_ai_with_confidence) :\n%s", traceback.format_exc())
            return f"__ERROR__{type(exc).__name__}: {exc}", 0

        confidence = 8
        match = re.search(r"CONFIANCE\s*:\s*(\d{1,2})\s*/\s*10", content, re.IGNORECASE)
        if match:
            confidence = max(1, min(10, int(match.group(1))))
            content = content[:match.start()].rstrip(" \n-")
        return content, confidence

    async def send_sentrix_reply(self, destination, author, question: str):
        """Construit et envoie la réponse "SentriX AI" (embed + jauge de confiance).
        Partagé entre la commande /sentrix et le déclenchement par simple message
        (mention du bot ou message commençant par "sentrix")."""
        guild_id = getattr(getattr(destination, "guild", None), "id", None)
        history = self.histories.get(author.id, [])
        answer, confidence = await self.ask_ai_with_confidence(question, history)
        if answer == "__NO_KEY__":
            return await destination.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot. Contactez un administrateur.", kind="danger"))
        if answer.startswith("__ERROR__"):
            return await destination.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA. Réessayez plus tard.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self.histories[author.id] = history[-10:]

        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        e = await self._embed(guild_id, title="SentriX")
        e.add_field(name="❓ Question", value=question[:1024], inline=False)
        e.add_field(name="💬 Réponse", value=answer[:1000] or "…", inline=False)
        bar = design_system.progress_bar(confidence, 10, length=design.get("progress_length", 10), filled=design.get("progress_filled", "🟪"), empty=design.get("progress_empty", "⬛"))
        e.add_field(name="📡 Indice de confiance", value=f"{bar}  **{confidence}/10**", inline=False)
        e.set_footer(text=f"SentriX AI • Demandé par {author}")
        await destination.send(embed=e)

    @commands.hybrid_command(
        name="sentrix",
        description="Demandez n'importe quoi à SentriX : l'IA du bot répond avec un indice de confiance.",
    )
    @app_commands.describe(question="Votre question, sur n'importe quel sujet")
    async def sentrix(self, ctx: commands.Context, *, question: str):
        if ctx.interaction:
            await ctx.defer()
        await self.send_sentrix_reply(ctx, ctx.author, question)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Permet de parler au bot sans commande : le mentionner, ou commencer son message
        par "sentrix" (ex: "sentrix comment tu vas ?"). Il répond alors comme avec /sentrix."""
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if not content:
            return

        mentioned = self.bot.user is not None and self.bot.user in message.mentions
        name_trigger = content.lower().startswith("sentrix")
        if not mentioned and not name_trigger:
            return

        # Ne pas répondre en double si c'est en fait une vraie commande préfixée
        # (ex: "+sentrix ..." est déjà géré par le système de commandes classique).
        prefix = self.bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX) if hasattr(self.bot, "prefix_cache") else config.DEFAULT_PREFIX
        if content.startswith(prefix):
            return

        question = content
        if mentioned:
            question = re.sub(r"<@!?\d+>", "", question, count=1).strip()
        elif name_trigger:
            question = content[len("sentrix"):].lstrip(" ,:-").strip()
        if not question:
            question = "Salut, comment tu vas ?"

        async with message.channel.typing():
            await self.send_sentrix_reply(message.channel, message.author, question)

    @commands.hybrid_command(name="ask", description="Poser une question à l'IA.")
    @app_commands.describe(question="Votre question pour l'IA")
    async def ask(self, ctx: commands.Context, *, question: str):
        if ctx.interaction:
            await ctx.defer()
        guild_id = ctx.guild.id if ctx.guild else None
        history = self.histories.get(ctx.author.id, [])
        answer = await self.ask_ai(question, history)
        if answer == "__NO_KEY__":
            return await ctx.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot. Contactez un administrateur.", kind="danger"))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA. Réessayez plus tard.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self.histories[ctx.author.id] = history[-10:]
        e = await self._embed(guild_id, title="Réponse de l'IA", description=answer[:4000])
        e.set_footer(text=f"Demandé par {ctx.author}")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="chat-reset", description="Réinitialiser votre historique de conversation avec l'IA.", with_app_command=False)
    async def chat_reset(self, ctx: commands.Context):
        self.histories.pop(ctx.author.id, None)
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Historique réinitialisé", description="🧹 Votre historique de conversation a été réinitialisé.", kind="success"))

    @commands.hybrid_command(name="summarize", description="Résumer un texte avec l'IA.")
    @app_commands.describe(texte="Le texte à résumer")
    async def summarize(self, ctx: commands.Context, *, texte: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Résume ce texte en 3-4 phrases maximum :\n\n{texte}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot.", kind="danger"))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        await ctx.send(embed=await self._embed(guild_id, title="Résumé", description=answer[:4000]))

    @commands.hybrid_command(name="image-prompt", description="Générer une idée détaillée de prompt d'image avec l'IA.", with_app_command=False)
    @app_commands.describe(sujet="Le sujet de l'image souhaitée")
    async def image_prompt(self, ctx: commands.Context, *, sujet: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Génère un prompt détaillé et créatif en anglais pour un générateur d'images IA, sur ce sujet : {sujet}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot.", kind="danger"))
        # BUG CORRIGÉ : le cas __ERROR__ n'était pas vérifié ici — en cas d'erreur OpenAI, le
        # message brut "__ERROR__..." s'affichait tel quel comme si c'était la réponse de l'IA.
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        await ctx.send(embed=await self._embed(guild_id, title="Prompt généré", description=answer[:4000]))

    @commands.hybrid_command(name="explain", description="Demander à l'IA d'expliquer un concept simplement.", with_app_command=False)
    @app_commands.describe(sujet="Le concept à expliquer")
    async def explain(self, ctx: commands.Context, *, sujet: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Explique ce concept simplement, comme à un débutant : {sujet}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot.", kind="danger"))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        await ctx.send(embed=await self._embed(guild_id, title="Explication", description=answer[:4000]))

    @commands.hybrid_command(name="rewrite", description="Demander à l'IA de reformuler un texte.", with_app_command=False)
    @app_commands.describe(texte="Le texte à reformuler")
    async def rewrite(self, ctx: commands.Context, *, texte: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(f"Reformule ce texte de façon plus claire, en gardant le sens original :\n\n{texte}")
        if answer == "__NO_KEY__":
            return await ctx.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot.", kind="danger"))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        await ctx.send(embed=await self._embed(guild_id, title="Reformulation", description=answer[:4000]))

    @commands.hybrid_command(name="fact-check", description="Demander à l'IA de vérifier une affirmation (à titre indicatif).", with_app_command=False)
    @app_commands.describe(affirmation="L'affirmation à vérifier")
    async def fact_check(self, ctx: commands.Context, *, affirmation: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        answer = await self.ask_ai(
            f"Évalue la véracité probable de cette affirmation, avec prudence et nuance, en précisant que ce n'est pas une vérification garantie : {affirmation}"
        )
        if answer == "__NO_KEY__":
            return await ctx.send(embed=await self._embed(guild_id, title="Clé IA manquante", description="Aucune clé OpenAI n'est configurée sur ce bot.", kind="danger"))
        if answer.startswith("__ERROR__"):
            return await ctx.send(embed=await self._embed(guild_id, title="Erreur IA", description=f"Une erreur est survenue avec l'IA.\nDétail technique : `{_ai_error_detail(answer)}`", kind="danger"))
        e = await self._embed(guild_id, title="Vérification (indicative)", description=answer[:4000])
        e.set_footer(text="⚠️ Réponse générée par IA, à vérifier par vous-même.")
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ai(bot))
