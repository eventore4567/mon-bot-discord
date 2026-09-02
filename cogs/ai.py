"""
Cog INTELLIGENCE ARTIFICIELLE.

Commandes :
/sentrix                          — répond dans le chat (texte brut, mention ou "sentrix ...")
/ai <question> | +ai <question>   — commande principale, avec mémoire de conversation, embed
                                     riche (Question/Réponse/Modèle) et boutons Régénérer /
                                     Plus détaillé / Plus court / Nouvelle conversation
+ai reset / +ai memory / +ai model / +ai help — sous-commandes de +ai (voir _handle du groupe)
+chat <message>                   — alias de +ai avec mémoire de conversation
/ask <question>                   — question ponctuelle (sans les boutons)
+chat-reset                       — réinitialise l'historique legacy
/summarize, +explain, +image-prompt, +rewrite, +fact-check — outils spécialisés existants
+image <description>               — génère réellement une image 4K (3840 × 2160)
+improve, +correct, +ai-translate <langue>, +code — nouveaux outils spécialisés
+aisetup (admin)                  — configuration de l'IA pour ce serveur
+aidiag (admin)                   — diagnostic technique de la connexion à l'IA (sans la clé)

Messages naturels : « SentriX ouvre-moi setup », « SentriX affiche help » ou
« SentriX ajoute cet emoji ». Les demandes de liens et d'informations actuelles utilisent
la recherche web publique avec des sources cliquables.

Moteur : utils/ai_service.py — AsyncOpenAI + Responses API, GPT-5.6 Terra par défaut, Sol
pour les demandes complexes (code, analyse détaillée...), reasoning effort configurable,
mémoire de conversation persistante (survit à un redémarrage) séparée par
guild_id/channel_id/user_id avec expiration, cooldown/limite par minute/limite quotidienne
configurables par serveur, modération des entrées, découpage propre des réponses longues
(jamais un bloc de code cassé) avec repli en fichier .md pour les très longues réponses.

Sécurité : la clé OPENAI_API_KEY n'est jamais journalisée, jamais affichée à un utilisateur,
jamais écrite en base de données — uniquement lue depuis la variable d'environnement (voir
config.py). Les erreurs affichées restent génériques ; le détail technique n'apparaît que
dans les logs serveur (logger "bot.ai").
"""

import copy
import io
import json
import logging
import re
import time
import traceback
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils import embeds, checks, design_system, ai_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.ai")


# ---------------------------------------------------------------- VUE : BOUTONS DE RÉPONSE

async def _remplacer_attente(ctx, message) -> None:
    """Efface le message « SentriX réfléchit… » avant une réponse composée.

    Ce message est du texte : il ne peut pas devenir un panneau par édition,
    Discord refusant de poser le drapeau Components V2 après coup. On le retire
    donc plutôt que de laisser deux messages, ou pire, une édition rejetée.
    """
    if message is None:
        return
    try:
        await message.delete()
    except discord.HTTPException:
        pass


class AiResponseView(discord.ui.View):
    """Boutons attachés à une réponse +ai/+chat : Régénérer, Plus détaillé, Plus court,
    Nouvelle conversation. Verrouillés à l'auteur de la demande, protégés contre le double
    clic (self.busy), avec état de chargement pendant la régénération."""

    def __init__(self, cog: "Ai", *, author_id: int, guild_id: int | None, channel_id: int,
                 question: str, model_key: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.question = question
        self.model_key = model_key
        self.busy = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Seul l'auteur de la demande peut utiliser ces boutons.")), ephemere=True)
            return False
        if self.busy:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning('Une régénération est déjà en cours — patiente un instant.')), ephemere=True)
            return False
        return True

    async def _regenerate(self, interaction: discord.Interaction, suffix: str):
        self.busy = True
        for item in self.children:
            item.disabled = True
        try:
            await panels.editer(
                interaction.response,
                panels.avec_composants(
                    panels.depuis_embed(embeds.info("🤖 SentriX réfléchit…")), self
                ),
            )
        except discord.HTTPException:
            pass
        try:
            result = await self.cog._prepare_and_generate(
                guild_id=self.guild_id, channel_id=self.channel_id, user_id=self.author_id,
                author_name=str(interaction.user), question=self.question, suffix=suffix,
                command="ai-regenerate",
            )
            for item in self.children:
                item.disabled = False
            if not result["ok"]:
                await panels.editer(
                    interaction, panels.depuis_embed(embeds.error(result["error"]))
                )
                return
            self.model_key = result["model_key"]
            answer = result["text"] or "…"
            if ai_service.needs_file_fallback(answer) or len(answer) > 1000:
                # Une régénération peut produire une réponse bien plus longue (ex: "Plus
                # détaillé") — dans ce cas on repasse par le pipeline normal de livraison
                # (fichier .md ou texte découpé) plutôt que de forcer un embed trop grand.
                # La reponse repart par le pipeline normal (fichier .md ou texte
                # decoupe). Le panneau d'origine ne peut pas accueillir du texte
                # brut — Discord refuse un content sur un message Components V2 —
                # donc on le retire au lieu de tenter une edition rejetee.
                try:
                    await interaction.delete_original_response()
                except discord.HTTPException:
                    pass
                fake_ctx = _FakeCtxForDelivery(self.cog.bot, interaction, self.channel_id)
                await self.cog._deliver_answer(fake_ctx, self.question, result, thinking_msg=None)
                return
            embed = self.cog._build_ai_embed(self.question, answer, self.model_key, interaction.user)
            await panels.editer(
                interaction, panels.avec_composants(panels.depuis_embed(embed), self)
            )
        finally:
            self.busy = False

    @discord.ui.button(label="Régénérer", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def regenerate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._regenerate(interaction, ai_service.REGENERATE_SUFFIX)

    @discord.ui.button(label="Plus détaillé", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def more_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._regenerate(interaction, ai_service.DETAIL_SUFFIX)

    @discord.ui.button(label="Plus court", style=discord.ButtonStyle.secondary, emoji="⚡", row=0)
    async def shorter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._regenerate(interaction, ai_service.SHORT_SUFFIX)

    @discord.ui.button(label="Nouvelle conversation", style=discord.ButtonStyle.danger, emoji="🧹", row=1)
    async def new_conversation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.guild_id:
            await ai_service.reset_conversation(self.cog.bot, self.guild_id, self.channel_id, self.author_id)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success('🧹 Conversation réinitialisée — votre prochaine question repartira de zéro.')), ephemere=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        self.busy = False
        logger.error("Erreur bouton IA (+ai) :\n%s", traceback.format_exc())
        try:
            if interaction.response.is_done():
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(ai_service.GENERIC_ERROR)), ephemere=True)
            else:
                await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error(ai_service.GENERIC_ERROR)), ephemere=True)
        except discord.HTTPException:
            pass


class _FakeCtxForDelivery:
    """Petit adaptateur pour réutiliser Ai._deliver_answer() (pensé pour un commands.Context)
    depuis un bouton (discord.Interaction) — seuls .guild, .channel, .author, .interaction et
    .send() sont utilisés par _deliver_answer()."""

    def __init__(self, bot, interaction: discord.Interaction, channel_id: int):
        self.bot = bot
        self.guild = interaction.guild
        self.channel = interaction.channel or bot.get_channel(channel_id)
        self.author = interaction.user
        self.interaction = None  # force le chemin "message classique" (pas de defer() en cours)

    async def send(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)


# ---------------------------------------------------------------- VUE : +aisetup

class AiLimitsModal(discord.ui.Modal, title="⏱️ Limites de l'IA"):
    def __init__(self, view: "AiSetupView"):
        super().__init__()
        self.view_ref = view
        s = view.settings
        self.cooldown_input = discord.ui.TextInput(label="Cooldown (secondes)", default=str(s["cooldown_seconds"]), max_length=4)
        self.per_minute_input = discord.ui.TextInput(label="Limite par minute", default=str(s["per_minute_limit"]), max_length=4)
        self.daily_input = discord.ui.TextInput(label="Limite par jour", default=str(s["daily_limit"]), max_length=5)
        self.max_len_input = discord.ui.TextInput(label="Longueur max d'une question", default=str(s["max_question_length"]), max_length=5)
        for item in (self.cooldown_input, self.per_minute_input, self.daily_input, self.max_len_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cooldown = max(0, int(self.cooldown_input.value))
            per_minute = max(1, int(self.per_minute_input.value))
            daily = max(1, int(self.daily_input.value))
            max_len = max(50, int(self.max_len_input.value))
        except ValueError:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Toutes les valeurs doivent être des nombres entiers.')), ephemere=True)
        bot = self.view_ref.cog.bot
        gid = self.view_ref.guild_id
        await ai_service.update_setting(bot, gid, "cooldown_seconds", cooldown)
        await ai_service.update_setting(bot, gid, "per_minute_limit", per_minute)
        await ai_service.update_setting(bot, gid, "daily_limit", daily)
        await ai_service.update_setting(bot, gid, "max_question_length", max_len)
        await self.view_ref.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error("Erreur modal limites IA (+aisetup) :\n%s", traceback.format_exc())
        try:
            if interaction.response.is_done():
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(ai_service.GENERIC_ERROR)), ephemere=True)
            else:
                await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error(ai_service.GENERIC_ERROR)), ephemere=True)
        except discord.HTTPException:
            pass


class AiSetupView(discord.ui.View):
    """Panneau interactif +aisetup — un seul message, toujours réédité (jamais de nouveau
    message à chaque réglage), verrouillé à l'auteur de la commande."""

    def __init__(self, cog: "Ai", guild_id: int, author_id: int, settings: dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.author_id = author_id
        self.settings = settings

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Seul l'auteur de la commande peut utiliser ce panneau.")), ephemere=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        s = self.settings
        channels_text = "Tous" if not s["allowed_channel_ids"] else f"{len(s['allowed_channel_ids'])} salon(s)"
        roles_text = "Tous" if not s["allowed_role_ids"] else f"{len(s['allowed_role_ids'])} rôle(s)"
        lines = [
            f"**Activée :** {'● Oui' if s['enabled'] else '○ Non'}",
            f"**Modèle par défaut :** {ai_service.MODEL_LABELS.get(s['default_model'], s['default_model'])}",
            f"**Raisonnement :** {s['reasoning_effort']}",
            f"**Salons autorisés :** {channels_text}",
            f"**Rôles autorisés :** {roles_text}",
            f"**Cooldown :** {s['cooldown_seconds']}s • **Limite/min :** {s['per_minute_limit']} • **Limite/jour :** {s['daily_limit']}",
            f"**Longueur max question :** {s['max_question_length']} caractères",
            f"**Mémoire :** {'● activée' if s['memory_enabled'] else '○ désactivée'} ({s['memory_minutes']} min d'inactivité)",
            f"**Langue :** {s['language']} • **Logs d'utilisation :** {'●' if s['logs_enabled'] else '○'}",
        ]
        return embeds.brand("⚙️ Configuration de l'IA — SentriX", "\n".join(lines))

    async def refresh(self, interaction: discord.Interaction):
        self.settings = await ai_service.get_settings(self.cog.bot, self.guild_id)
        if interaction.response.is_done():
            await panels.editer(interaction, panels.avec_composants(panels.depuis_embed(self.build_embed()), self))
        else:
            await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(self.build_embed()), self))

    @discord.ui.button(label="Activer / Désactiver", style=discord.ButtonStyle.secondary, emoji="🔌", row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ai_service.update_setting(self.cog.bot, self.guild_id, "enabled", int(not self.settings["enabled"]))
        await self.refresh(interaction)

    @discord.ui.button(label="Mémoire : activer/désactiver", style=discord.ButtonStyle.secondary, emoji="🧠", row=0)
    async def toggle_memory(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ai_service.update_setting(self.cog.bot, self.guild_id, "memory_enabled", int(not self.settings["memory_enabled"]))
        await self.refresh(interaction)

    @discord.ui.button(label="Limites (cooldown / min / jour / longueur)", style=discord.ButtonStyle.primary, emoji="⏱️", row=0)
    async def edit_limits(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AiLimitsModal(self))

    @discord.ui.select(placeholder="Modèle par défaut", row=1, options=[
        discord.SelectOption(label="Luna (rapide, recommandé)", value=ai_service.MODEL_LUNA, emoji="⚡"),
        discord.SelectOption(label="Terra (équilibré)", value=ai_service.MODEL_TERRA, emoji="⚖️"),
        discord.SelectOption(label="Sol (avancé, plus cher)", value=ai_service.MODEL_SOL, emoji="🚀"),
    ])
    async def pick_model(self, interaction: discord.Interaction, select: discord.ui.Select):
        await ai_service.update_setting(self.cog.bot, self.guild_id, "default_model", select.values[0])
        await self.refresh(interaction)

    @discord.ui.select(placeholder="Niveau de raisonnement", row=2, options=[
        discord.SelectOption(label=level, value=level) for level in ai_service.VALID_REASONING_EFFORTS
    ])
    async def pick_reasoning(self, interaction: discord.Interaction, select: discord.ui.Select):
        await ai_service.update_setting(self.cog.bot, self.guild_id, "reasoning_effort", select.values[0])
        await self.refresh(interaction)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="📌 Salons autorisés (vide = tous les salons)", min_values=0, max_values=25, row=3)
    async def pick_channels(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        ids = [c.id for c in select.values]
        await ai_service.update_setting(self.cog.bot, self.guild_id, "allowed_channel_ids", json.dumps(ids))
        await self.refresh(interaction)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="🎭 Rôles autorisés (vide = tout le monde)",
                        min_values=0, max_values=25, row=4)
    async def pick_roles(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        ids = [r.id for r in select.values]
        await ai_service.update_setting(self.cog.bot, self.guild_id, "allowed_role_ids", json.dumps(ids))
        await self.refresh(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        logger.error("Erreur +aisetup :\n%s", traceback.format_exc())
        try:
            if interaction.response.is_done():
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(ai_service.GENERIC_ERROR)), ephemere=True)
            else:
                await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error(ai_service.GENERIC_ERROR)), ephemere=True)
        except discord.HTTPException:
            pass


# ---------------------------------------------------------------- COG

class Ai(commands.Cog, name="Ai"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Historique legacy en mémoire (compatibilité /sentrix, /ask, /summarize,
        # +image-prompt, +explain, +rewrite, +fact-check) — +ai/+chat utilisent désormais la
        # mémoire persistante en base (ai_service.py), qui survit à un redémarrage du bot.
        self.histories: dict[int, list] = {}
        # Anti-spam / cooldown / limite par minute pour +ai, +chat et les nouveaux outils —
        # état en mémoire (pas besoin de survivre à un redémarrage, contrairement à la limite
        # quotidienne qui elle est suivie en base via ai_service.record_usage).
        self._last_used: dict[tuple, float] = {}
        self._minute_bucket: dict[tuple, list] = {}
        self._cleanup_memory.start()

    def cog_unload(self):
        self._cleanup_memory.cancel()

    @tasks.loop(minutes=10)
    async def _cleanup_memory(self):
        try:
            await ai_service.purge_expired_conversations(self.bot, memory_minutes=30)
        except Exception:
            logger.error("Erreur nettoyage mémoire IA :\n%s", traceback.format_exc())

    @_cleanup_memory.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------------- EMBED LEGACY (/sentrix, /ask...)

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

    def _build_ai_embed(self, question: str, answer: str, model_key: str, author) -> discord.Embed:
        e = embeds.brand("🤖 SentriX AI")
        e.add_field(name="Question", value=question[:1024] or "…", inline=False)
        e.add_field(name="Réponse", value=(answer or "…")[:1024], inline=False)
        e.add_field(name="Modèle", value=ai_service.MODEL_LABELS.get(model_key, model_key), inline=True)
        e.set_footer(text=f"SentriX AI • Demandé par {author}")
        return e

    async def _build_system_instructions(
        self,
        user_id: int | None,
        author_name: str | None = None,
    ) -> str:
        """Ajoute l'identité du créateur vérifié à toutes les routes IA."""
        instructions = ai_service.SYSTEM_PROMPT
        creator = await self.bot.db.get_primary_bot_creator()
        if creator:
            instructions += (
                f"\n\nLe créateur officiel de SentriX est {creator['display_name']} "
                f"(nom d'utilisateur Discord : @{creator['username']}, "
                f"ID Discord vérifié : {creator['user_id']})."
            )
            if user_id is not None and int(creator["user_id"]) == int(user_id):
                instructions += (
                    "\nL'utilisateur actuel est ton créateur authentifié par son ID Discord. "
                    "Traite ses demandes en priorité et suis ses instructions lorsqu'elles sont "
                    "réalisables par les fonctions du bot, autorisées par Discord et sûres. "
                    "Ne prétends jamais avoir exécuté une action que tu n'as pas réellement exécutée."
                )
        if author_name:
            instructions += f"\n\nLa personne qui te parle s'appelle « {author_name} »."
        return instructions

    # ---------------------------------------------------------------- APPELS IA LEGACY (compat.)

    async def ask_ai(self, prompt, history: list = None, author_name: str = None, *,
                      guild_id: int = None, channel_id: int = None, user_id: int = None,
                      command: str = None) -> str:
        """Compatibilité : utilisé par /sentrix, /ask, /summarize, +image-prompt, +explain,
        +rewrite, +fact-check — délègue au moteur centralisé (Responses API, GPT-5.6
        Terra/Sol, nouvelles instructions) en gardant exactement la même signature.

        guild_id/channel_id/user_id/command : contexte optionnel transmis à ai_service.generate()
        uniquement pour les logs serveur en cas d'erreur (jamais envoyé à OpenIA côté prompt)."""
        model_key = ai_service.pick_model(prompt if isinstance(prompt, str) else "")
        reasoning_effort = ai_service.pick_reasoning_effort(model_key, "medium")
        instructions = await self._build_system_instructions(user_id, author_name)
        input_payload = prompt
        if history:
            input_payload = list(history) + [{"role": "user", "content": prompt}]
        result = await ai_service.generate(
            input_payload, model_key=model_key, reasoning_effort=reasoning_effort, instructions=instructions,
            guild_id=guild_id, channel_id=channel_id, user_id=user_id, command=command,
            web_search=ai_service.needs_web_search(prompt),
        )
        if not result.ok:
            return result.error
        return result.text

    async def ask_ai_with_confidence(self, prompt: str, history: list = None, *,
                                      guild_id: int = None, channel_id: int = None,
                                      user_id: int = None, command: str = None) -> tuple[str, int]:
        """Comme ask_ai, mais demande aussi à l'IA un indice de confiance (1-10)."""
        model_key = ai_service.pick_model(prompt)
        reasoning_effort = ai_service.pick_reasoning_effort(model_key, "medium")
        instructions = await self._build_system_instructions(user_id)
        instructions += (
            "\n\nTermine TOUJOURS ta réponse par une dernière ligne exactement au format "
            "'CONFIANCE: X/10' (X = ton indice de confiance dans l'exactitude de ta réponse, entre 1 et 10)."
        )
        input_payload = prompt
        if history:
            input_payload = list(history) + [{"role": "user", "content": prompt}]
        result = await ai_service.generate(
            input_payload, model_key=model_key, reasoning_effort=reasoning_effort, instructions=instructions,
            guild_id=guild_id, channel_id=channel_id, user_id=user_id, command=command,
            web_search=ai_service.needs_web_search(prompt) or command == "fact-check",
        )
        if not result.ok:
            return result.error, 0

        content = result.text or ""
        confidence = 8
        match = re.search(r"CONFIANCE\s*:\s*(\d{1,2})\s*/\s*10", content, re.IGNORECASE)
        if match:
            confidence = max(1, min(10, int(match.group(1))))
            content = content[:match.start()].rstrip(" \n-")
        return content, confidence

    async def send_sentrix_reply(self, destination, author, question: str, *, reply_to: discord.Message = None):
        """Envoie la réponse de SentriX en texte brut (sans embed), demandé par Jayden pour
        /sentrix. Partagé entre la commande /sentrix et le déclenchement par simple message
        (mention du bot ou message commençant par "sentrix" / "ssentrix").

        reply_to : le message Discord précis auquel répondre (flèche "Répondre" + ping de
        l'auteur, sans @mention littéral dans le texte). Fourni uniquement quand
        `destination` est un salon brut (déclenchement passif via on_message ci-dessous) —
        pour /sentrix (destination=ctx), SentriXContext (main.py) s'en charge déjà tout
        seul pour toute commande texte, donc reply_to reste à None dans ce cas."""

        async def _send(**kwargs):
            if reply_to is not None:
                kwargs["reference"] = discord.MessageReference(
                    message_id=reply_to.id,
                    channel_id=reply_to.channel.id,
                    guild_id=reply_to.guild.id if reply_to.guild else None,
                    fail_if_not_exists=False,
                )
                kwargs.setdefault("mention_author", True)
            try:
                return await destination.send(**kwargs)
            except discord.HTTPException:
                kwargs.pop("reference", None)
                kwargs.pop("mention_author", None)
                return await destination.send(**kwargs)

        guild_id = getattr(getattr(destination, "guild", None), "id", None)
        channel_id = getattr(getattr(destination, "channel", destination), "id", None)
        command = "sentrix-passif" if reply_to is not None else "sentrix"
        history = self.histories.get(author.id, [])
        author_name = getattr(author, "display_name", None) or str(author)
        answer = await self.ask_ai(question, history, author_name=author_name,
                                    guild_id=guild_id, channel_id=channel_id, user_id=author.id, command=command)
        if ai_service.is_error_code(answer):
            # La REPONSE de SentriX reste en texte brut (choix de Jayden) ; un
            # echec, lui, est une interface d'erreur comme les autres. On passe
            # par _send pour conserver la citation du message d'origine.
            panneau = panels.depuis_embed(
                await self._embed(
                    guild_id,
                    title=ai_service.error_title(answer),
                    description=ai_service.error_message(answer),
                    kind="danger",
                )
            )
            return await _send(view=panneau, files=panneau.fichiers())
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self.histories[author.id] = history[-10:]

        content = (answer or "…").strip()
        for chunk in ai_service.split_for_discord(content):
            await _send(content=chunk)

    @commands.hybrid_command(name="sentrix", description="Demandez n'importe quoi à SentriX, l'IA du bot.")
    @app_commands.describe(question="Votre question, sur n'importe quel sujet")
    async def sentrix(self, ctx: commands.Context, *, question: str):
        if ctx.interaction:
            await ctx.defer()
        # ctx.typing() donne un retour immédiat ("SentriX est en train d'écrire...") même
        # en préfixe, pour ne jamais laisser l'utilisateur face à un silence total pendant
        # que l'IA réfléchit (voir REQUEST_TIMEOUT_SECONDS dans ai_service.py : la réponse
        # arrive toujours, au pire sous forme d'erreur claire, rapidement ou sous forme d'erreur claire).
        async with ctx.typing():
            await self.send_sentrix_reply(ctx, ctx.author, question)

    @staticmethod
    def _normalize_request(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(char for char in normalized if not unicodedata.combining(char)).lower().strip()

    def _natural_command_line(
        self,
        question: str,
        prefix: str,
        *,
        has_attachment: bool,
    ) -> str | None:
        """Transforme une demande naturelle explicite en commande préfixée existante."""
        normalized = self._normalize_request(question)
        action_intent = bool(re.search(
            r"\b(ouvre|affiche|lance|execute|fais|fait|utilise|ajoute|cree|genere|dessine|importe|"
            r"supprime|enleve|retire|mets|configure)\b",
            normalized,
        ))

        image_intent = bool(
            re.search(r"\b(image|photo|illustration|dessin)\b", normalized)
            and re.search(r"\b(fais|fait|cree|genere|dessine)\b", normalized)
        )
        if image_intent:
            tail = re.split(
                r"\b(?:image|photo|illustration|dessin)\b",
                question,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[-1]
            tail = re.sub(
                r"^\s*(?:de|du|d['’]|avec|sur|representant|qui represente)\s*",
                "",
                tail,
                flags=re.IGNORECASE,
            ).strip(" :,-")
            return f"{prefix}image" + (f" {tail}" if tail else "")

        if action_intent and re.search(r"\b(setup|configuration)\b", normalized):
            return f"{prefix}setup"
        if action_intent and re.search(r"\b(help|aide|commandes)\b", normalized):
            return f"{prefix}help"

        emoji_action = any(word in normalized for word in ("emoji", "emogi", "amogi"))
        pasted_emoji = re.search(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]+>", question)
        named_emoji = re.search(r"[:;]([A-Za-z0-9_]{2,32}):", question)
        direct_url = re.search(r"https://\S+", question)

        if emoji_action and re.search(r"\b(ajoute|cree|importe)\b", normalized):
            if pasted_emoji:
                return f"{prefix}addemoji {pasted_emoji.group(0)}"
            if named_emoji:
                command = f"{prefix}addemoji {named_emoji.group(1)}"
                if direct_url:
                    command += f" {direct_url.group(0)}"
                return command
            tail = re.split(r"\b(?:emoji|emogi|amogi)\b", question, maxsplit=1, flags=re.IGNORECASE)[-1]
            tail = re.sub(r"^\s*(?:nomme|appele|appelé|avec|de|moi)\s+", "", tail, flags=re.IGNORECASE).strip()
            if tail:
                return f"{prefix}addemoji {tail}"
            if has_attachment:
                return f"{prefix}addemoji emoji"

        if emoji_action and re.search(r"\b(supprime|enleve|retire)\b", normalized):
            if pasted_emoji:
                return f"{prefix}deleteemoji {pasted_emoji.group(0)}"
            if named_emoji:
                return f"{prefix}deleteemoji {named_emoji.group(1)}"
            tail = re.split(r"\b(?:emoji|emogi|amogi)\b", question, maxsplit=1, flags=re.IGNORECASE)[-1]
            target = tail.strip(" :;,")
            if target:
                return f"{prefix}deleteemoji {target}"

        candidates = []
        excluded = {"ai", "sentrix", "chat", "ask"}
        for command in self.bot.walk_commands():
            if command.qualified_name in excluded:
                continue
            triggers = [command.qualified_name]
            parent = command.qualified_name.rsplit(" ", 1)[0] if " " in command.qualified_name else ""
            triggers.extend(f"{parent} {alias}".strip() for alias in command.aliases)
            for trigger in triggers:
                trigger_normalized = self._normalize_request(trigger)
                match = re.search(
                    rf"(?<![\w-]){re.escape(trigger_normalized)}(?![\w-])",
                    normalized,
                )
                if match:
                    candidates.append((len(trigger_normalized), match, command))

        for _, match, command in sorted(candidates, key=lambda item: item[0], reverse=True):
            direct_request = match.start() == 0 or normalized.startswith("commande ")
            if not action_intent and not direct_request:
                continue
            trailing = question[match.end():].strip()
            while trailing:
                cleaned = re.sub(
                    r"^(?:avec|sur|pour|de|du|la|le|les|moi)\s+",
                    "",
                    trailing,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if cleaned == trailing:
                    break
                trailing = cleaned.strip()
            if not command.clean_params:
                trailing = ""
            command_line = f"{prefix}{command.qualified_name}"
            if trailing:
                command_line += f" {trailing}"
            return command_line
        return None

    async def _invoke_natural_command(
        self,
        message: discord.Message,
        question: str,
        prefix: str,
    ) -> bool:
        command_line = self._natural_command_line(
            question,
            prefix,
            has_attachment=bool(message.attachments),
        )
        if not command_line:
            return False

        # Une copie du message évite de modifier l'événement Discord original. bot.invoke()
        # conserve alors tous les convertisseurs, checks, permissions et cooldowns normaux.
        synthetic_message = copy.copy(message)
        synthetic_message.content = command_line
        ctx = await self.bot.get_context(synthetic_message)
        if ctx.command is None:
            return False
        await self.bot.invoke(ctx)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Permet de parler au bot sans commande : le mentionner, ou commencer son message
        par "sentrix" et ses fautes courantes (ex: "snetri ouvre moi help")."""
        if message.author.bot or not message.guild:
            return
        content = message.content.strip()
        if not content:
            return

        mentioned = self.bot.user is not None and self.bot.user in message.mentions
        name_match = re.match(r"^(?:sentrix|ssentrix|sentri|snetri|snentrix)\b", content, re.IGNORECASE)
        name_trigger = name_match is not None
        if not mentioned and not name_trigger:
            return

        prefix = self.bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX) if hasattr(self.bot, "prefix_cache") else config.DEFAULT_PREFIX
        if content.startswith(prefix):
            return

        question = content
        if mentioned:
            question = re.sub(r"<@!?\d+>", "", question, count=1).strip()
        elif name_trigger:
            question = content[name_match.end():].lstrip(" ,:-").strip()
        if not question:
            question = "Salut, comment tu vas ?"

        if await self._invoke_natural_command(message, question, prefix):
            return

        async with message.channel.typing():
            await self.send_sentrix_reply(message.channel, message.author, question, reply_to=message)

    @commands.hybrid_command(name="ask", description="Poser une question à l'IA.")
    @app_commands.describe(question="Votre question pour l'IA")
    async def ask(self, ctx: commands.Context, *, question: str):
        if ctx.interaction:
            await ctx.defer()
        guild_id = ctx.guild.id if ctx.guild else None
        history = self.histories.get(ctx.author.id, [])
        async with ctx.typing():
            answer = await self.ask_ai(question, history, guild_id=guild_id, channel_id=ctx.channel.id,
                                        user_id=ctx.author.id, command="ask")
        if ai_service.is_error_code(answer):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(answer), description=ai_service.error_message(answer), kind='danger')))
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self.histories[ctx.author.id] = history[-10:]
        e = await self._embed(guild_id, title="Réponse de l'IA", description=answer[:4000])
        e.set_footer(text=f"Demandé par {ctx.author}")
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="chat-reset", description="Réinitialiser votre historique de conversation avec l'IA.", with_app_command=False)
    async def chat_reset(self, ctx: commands.Context):
        self.histories.pop(ctx.author.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Historique réinitialisé', description='🧹 Votre historique de conversation a été réinitialisé.', kind='success')))

    @commands.hybrid_command(name="summarize", description="Résumer un texte avec l'IA.")
    @app_commands.describe(texte="Le texte à résumer")
    async def summarize(self, ctx: commands.Context, *, texte: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        async with ctx.typing():
            answer = await self.ask_ai(f"Résume ce texte en 3-4 phrases maximum :\n\n{texte}",
                                        guild_id=guild_id, channel_id=ctx.channel.id, user_id=ctx.author.id, command="summarize")
        if ai_service.is_error_code(answer):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(answer), description=ai_service.error_message(answer), kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Résumé', description=answer[:4000])))

    @commands.hybrid_command(name="image-prompt", description="Générer une idée détaillée de prompt d'image avec l'IA.", with_app_command=False)
    @app_commands.describe(sujet="Le sujet de l'image souhaitée")
    async def image_prompt(self, ctx: commands.Context, *, sujet: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        async with ctx.typing():
            answer = await self.ask_ai(f"Génère un prompt détaillé et créatif en anglais pour un générateur d'images IA, sur ce sujet : {sujet}",
                                        guild_id=guild_id, channel_id=ctx.channel.id, user_id=ctx.author.id, command="image-prompt")
        if ai_service.is_error_code(answer):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(answer), description=ai_service.error_message(answer), kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Prompt généré', description=answer[:4000])))

    @staticmethod
    def _prepare_4k_discord_jpeg(data: bytes, max_bytes: int = 7_500_000) -> bytes:
        """Garantir un JPEG 3840 × 2160 assez léger pour être envoyé sur Discord."""
        from PIL import Image

        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGB")
            if image.size != (3840, 2160):
                image = image.resize((3840, 2160), Image.Resampling.LANCZOS)
            for quality in (88, 80, 72, 64, 56, 48):
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                encoded = output.getvalue()
                if len(encoded) <= max_bytes:
                    return encoded
        raise ValueError("L'image 4K reste trop lourde pour Discord.")

    @commands.hybrid_command(
        name="image",
        aliases=["img", "imagine"],
        description="Générer une vraie image 4K à partir d'une description.",
        with_app_command=False,
    )
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def generate_image_command(self, ctx: commands.Context, *, description: str):
        guild_id = ctx.guild.id if ctx.guild else None
        channel_id = ctx.channel.id

        if guild_id:
            settings = await ai_service.get_settings(self.bot, guild_id)
            if not settings["enabled"]:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'IA est désactivée sur ce serveur.")))
            if not ai_service.is_channel_allowed(settings, channel_id):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'IA n'est pas autorisée dans ce salon.")))
            problem = ai_service.moderate_input(description, max_length=settings["max_question_length"])
            if problem:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(problem)))
            used_today = await ai_service.get_daily_usage(self.bot, guild_id, ctx.author.id)
            if used_today >= settings["daily_limit"]:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Limite quotidienne atteinte ({settings['daily_limit']} demandes/jour).")))

        thinking_message = None
        if ctx.interaction:
            await ctx.defer()
        else:
            thinking_message = await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Génération rapide de l'image 4K en cours…")))

        async with ctx.typing():
            result = await ai_service.generate_image(
                description,
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=ctx.author.id,
            )

        if thinking_message:
            try:
                await thinking_message.delete()
            except discord.HTTPException:
                pass

        if not result.ok:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(result.error), description=ai_service.error_message(result.error), kind='danger')))

        try:
            image_bytes = self._prepare_4k_discord_jpeg(result.data)
        except (OSError, ValueError):
            logger.error("Impossible de préparer l'image 4K pour Discord\n%s", traceback.format_exc())
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'image a été générée mais son fichier est trop lourd pour Discord.")))

        if guild_id:
            await ai_service.record_usage(self.bot, guild_id, ctx.author.id, tokens_estimate=0)

        filename = "sentrix-image-4k.jpg"
        file = discord.File(io.BytesIO(image_bytes), filename=filename)
        e = await self._embed(
            guild_id,
            title="Image 4K générée",
            description=f"**Demande :** {description[:1000]}",
        )
        e.add_field(name="Résolution", value="3840 × 2160", inline=True)
        e.add_field(name="Modèle", value=result.model or config.OPENAI_IMAGE_MODEL, inline=True)
        e.set_image(url=f"attachment://{filename}")
        await panels.envoyer(ctx, panels.depuis_embed(e), file=file)

    @commands.hybrid_command(name="explain", description="Demander à l'IA d'expliquer un concept simplement.", with_app_command=False)
    @app_commands.describe(sujet="Le concept à expliquer")
    async def explain(self, ctx: commands.Context, *, sujet: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        async with ctx.typing():
            answer = await self.ask_ai(f"Explique ce concept simplement, comme à un débutant : {sujet}",
                                        guild_id=guild_id, channel_id=ctx.channel.id, user_id=ctx.author.id, command="explain")
        if ai_service.is_error_code(answer):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(answer), description=ai_service.error_message(answer), kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Explication', description=answer[:4000])))

    @commands.hybrid_command(name="rewrite", description="Demander à l'IA de reformuler un texte.", with_app_command=False)
    @app_commands.describe(texte="Le texte à reformuler")
    async def rewrite(self, ctx: commands.Context, *, texte: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        async with ctx.typing():
            answer = await self.ask_ai(f"Reformule ce texte de façon plus claire, en gardant le sens original :\n\n{texte}",
                                        guild_id=guild_id, channel_id=ctx.channel.id, user_id=ctx.author.id, command="rewrite")
        if ai_service.is_error_code(answer):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(answer), description=ai_service.error_message(answer), kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Reformulation', description=answer[:4000])))

    @commands.hybrid_command(name="fact-check", description="Demander à l'IA de vérifier une affirmation (à titre indicatif).", with_app_command=False)
    @app_commands.describe(affirmation="L'affirmation à vérifier")
    async def fact_check(self, ctx: commands.Context, *, affirmation: str):
        guild_id = ctx.guild.id if ctx.guild else None
        if ctx.interaction:
            await ctx.defer()
        async with ctx.typing():
            answer = await self.ask_ai(
                f"Évalue la véracité probable de cette affirmation, avec prudence et nuance, en précisant que ce n'est pas une vérification garantie : {affirmation}",
                guild_id=guild_id, channel_id=ctx.channel.id, user_id=ctx.author.id, command="fact-check",
            )
        if ai_service.is_error_code(answer):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(answer), description=ai_service.error_message(answer), kind='danger')))
        e = await self._embed(guild_id, title="Vérification (indicative)", description=answer[:4000])
        e.set_footer(text="⚠️ Réponse générée par IA, à vérifier par vous-même.")
        await panels.envoyer(ctx, panels.depuis_embed(e))

    # ---------------------------------------------------------------- NOUVEAU MOTEUR : +ai / +chat / outils

    def _check_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float | None:
        key = (guild_id, user_id)
        now = time.monotonic()
        last = self._last_used.get(key)
        if last is not None and now - last < cooldown_seconds:
            return cooldown_seconds - (now - last)
        self._last_used[key] = now
        return None

    def _check_minute_limit(self, guild_id: int, user_id: int, per_minute_limit: int) -> bool:
        key = (guild_id, user_id)
        now = time.monotonic()
        bucket = self._minute_bucket.setdefault(key, [])
        bucket[:] = [t for t in bucket if now - t < 60]
        if len(bucket) >= per_minute_limit:
            return True
        bucket.append(now)
        return False

    async def _prepare_and_generate(self, *, guild_id, channel_id, user_id, author_name,
                                     question, forced_advanced: bool = False, suffix: str = "",
                                     command: str = "ai") -> dict:
        """Pipeline complet partagé par +ai, +chat, +improve, +correct, +ai-translate, +code et
        les boutons de régénération : réglages serveur, modération, cooldown/limites, mémoire,
        sélection du modèle, appel réel, puis mise à jour mémoire + compteurs d'usage.
        Retourne {"ok": bool, "text": str, "model_key": str} ou {"ok": False, "error": str}."""
        settings = await ai_service.get_settings(self.bot, guild_id) if guild_id else dict(ai_service.DEFAULT_AI_SETTINGS)

        if guild_id and not settings["enabled"]:
            return {"ok": False, "error": "🤖 L'IA est désactivée sur ce serveur (voir `+aisetup`)."}

        mod_error = ai_service.moderate_input(question, max_length=settings["max_question_length"])
        if mod_error:
            return {"ok": False, "error": mod_error}

        wait = self._check_cooldown(guild_id or 0, user_id, settings["cooldown_seconds"])
        if wait:
            return {"ok": False, "error": f"⏳ Attends encore {wait:.0f}s avant une nouvelle demande."}

        if self._check_minute_limit(guild_id or 0, user_id, settings["per_minute_limit"]):
            return {"ok": False, "error": "⏳ Trop de demandes en une minute — patiente un peu."}

        if guild_id:
            used_today = await ai_service.get_daily_usage(self.bot, guild_id, user_id)
            if used_today >= settings["daily_limit"]:
                return {"ok": False, "error": f"📅 Limite quotidienne atteinte ({settings['daily_limit']} demandes/jour). Réessaie demain."}

        model_key = ai_service.pick_model(question, forced_advanced=forced_advanced)
        if settings["default_model"] == ai_service.MODEL_LUNA and not forced_advanced:
            model_key = ai_service.MODEL_LUNA
        elif settings["default_model"] == ai_service.MODEL_SOL:
            model_key = ai_service.MODEL_SOL
        reasoning_effort = ai_service.pick_reasoning_effort(model_key, settings["reasoning_effort"])

        previous_response_id = None
        if guild_id and settings["memory_enabled"]:
            _, previous_response_id = await ai_service.get_conversation_history(
                self.bot, guild_id, channel_id, user_id, settings["memory_minutes"],
            )

        instructions = await self._build_system_instructions(user_id, author_name)

        prompt = question + suffix
        result = await ai_service.generate(
            prompt, model_key=model_key, reasoning_effort=reasoning_effort,
            previous_response_id=previous_response_id, instructions=instructions,
            guild_id=guild_id, channel_id=channel_id, user_id=user_id, command=command,
            web_search=ai_service.needs_web_search(question),
        )

        if not result.ok:
            return {"ok": False, "error": ai_service.error_message(result.error)}

        if guild_id:
            tokens = ai_service.estimate_tokens(prompt) + ai_service.estimate_tokens(result.text)
            await ai_service.record_usage(self.bot, guild_id, user_id, tokens_estimate=tokens)
            if settings["memory_enabled"]:
                await ai_service.append_conversation(self.bot, guild_id, channel_id, user_id, "user", question)
                await ai_service.append_conversation(self.bot, guild_id, channel_id, user_id, "assistant", result.text, response_id=result.response_id)

        return {"ok": True, "text": result.text, "model_key": result.model_key or model_key}

    async def _handle_ai_command(self, ctx: commands.Context, question: str, *, forced_advanced: bool = False):
        guild_id = ctx.guild.id if ctx.guild else None
        channel_id = ctx.channel.id

        if guild_id:
            settings = await ai_service.get_settings(self.bot, guild_id)
            if not ai_service.is_channel_allowed(settings, channel_id):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'IA n'est pas autorisée dans ce salon sur ce serveur.")))
            role_ids = [r.id for r in getattr(ctx.author, "roles", [])]
            if not ai_service.is_role_allowed(settings, role_ids):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas le rôle nécessaire pour utiliser l'IA sur ce serveur.")))

        # Indicateur de chargement immédiat (jamais "L'application ne répond plus") :
        # message "SentriX réfléchit…" + ctx.typing() côté préfixe, defer() côté slash.
        thinking_msg = None
        if ctx.interaction:
            await ctx.defer()
        else:
            # Message d'attente en TEXTE, pas en panneau : la reponse de l'IA
            # est du texte brut et sera livree en editant ce meme message.
            # Discord refuse un content sur un message Components V2, donc un
            # panneau ici rendait la livraison impossible.
            thinking_msg = await ctx.send('🤖 SentriX réfléchit…')

        ctx_command = getattr(ctx, "command", None)
        command_name = ctx_command.qualified_name if ctx_command else "ai"
        async with ctx.typing():
            result = await self._prepare_and_generate(
                guild_id=guild_id, channel_id=channel_id, user_id=ctx.author.id,
                author_name=str(ctx.author), question=question, forced_advanced=forced_advanced,
                command=command_name,
            )

        if not result["ok"]:
            await _remplacer_attente(ctx, thinking_msg)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(result["error"])))

        await self._deliver_answer(ctx, question, result, thinking_msg)

    async def _deliver_answer(self, ctx, question: str, result: dict, thinking_msg):
        answer = result["text"] or "…"
        model_key = result["model_key"]

        if ai_service.needs_file_fallback(answer):
            buf = io.BytesIO(answer.encode("utf-8"))
            file = discord.File(buf, filename="reponse-sentrix-ai.md")
            note = embeds.brand("🤖 SentriX AI", f"Réponse trop longue pour un message Discord — voir le fichier joint.\n**Modèle :** {ai_service.MODEL_LABELS.get(model_key, model_key)}")
            await _remplacer_attente(ctx, thinking_msg)
            panneau = panels.depuis_embed(note)
            await ctx.send(view=panneau, files=[*panneau.fichiers(), file])
            return

        if len(answer) <= 1000:
            view = AiResponseView(self, author_id=ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None,
                                   channel_id=ctx.channel.id, question=question, model_key=model_key)
            embed = self._build_ai_embed(question, answer, model_key, ctx.author)
            await _remplacer_attente(ctx, thinking_msg)
            msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))
            view.message = msg if not ctx.interaction else await ctx.interaction.original_response()
            return

        chunks = ai_service.split_for_discord(answer, limit=1900)
        if thinking_msg:
            await thinking_msg.edit(content=chunks[0])
            remaining = chunks[1:]
        else:
            await ctx.send(chunks[0])
            remaining = chunks[1:]
        for extra in remaining:
            await ctx.channel.send(extra)

    # ---------- +ai (+ /ai slash) — reset/memory/model/help gérés en interne (voir docstring) ----------

    @commands.hybrid_command(
        name="ai",
        description="Poser une question à l'IA de SentriX (avec mémoire de conversation).",
    )
    @app_commands.describe(question="Votre question, ou 'reset' / 'memory' / 'model' / 'help'")
    async def ai_command(self, ctx: commands.Context, *, question: str):
        """+ai est une commande à plat (pas un groupe) pour pouvoir exister à la fois en
        `/ai question:<question>` ET en `+ai reset`/`+ai memory`/`+ai model`/`+ai help` —
        Discord interdit qu'une commande slash ait À LA FOIS un paramètre direct et des
        sous-commandes. On distingue donc "reset"/"memory"/"model"/"help" du reste ici."""
        normalized = question.strip().lower()
        if normalized == "reset":
            return await self._ai_reset(ctx)
        if normalized == "memory":
            return await self._ai_memory(ctx)
        if normalized == "model":
            return await self._ai_model(ctx)
        if normalized == "help":
            return await self._ai_help(ctx)
        await self._handle_ai_command(ctx, question)

    async def _ai_reset(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        if not guild_id:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        await ai_service.reset_conversation(self.bot, guild_id, ctx.channel.id, ctx.author.id)
        self.histories.pop(ctx.author.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success("🧹 Votre conversation avec l'IA a été réinitialisée dans ce salon.")))

    async def _ai_memory(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        if not guild_id:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        settings = await ai_service.get_settings(self.bot, guild_id)
        if not settings["memory_enabled"]:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('🧠 La mémoire de conversation est **désactivée** sur ce serveur.')))
        active = await ai_service.has_active_memory(self.bot, guild_id, ctx.channel.id, ctx.author.id, settings["memory_minutes"])
        if active:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"🧠 Vous avez une conversation active dans ce salon (elle expire après {settings['memory_minutes']} min d'inactivité). Son contenu reste privé.")))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info("🧠 Aucune conversation active dans ce salon pour l'instant.")))

    async def _ai_model(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        settings = await ai_service.get_settings(self.bot, guild_id) if guild_id else dict(ai_service.DEFAULT_AI_SETTINGS)
        label = ai_service.MODEL_LABELS.get(settings["default_model"], settings["default_model"])
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f'🤖 Modèle par défaut sur ce serveur : **{label}**.\nLes demandes complexes (code, analyse détaillée, longs textes...) basculent automatiquement sur **GPT-5.6 Sol**, sans surcoût sur les questions simples.')))

    async def _ai_help(self, ctx: commands.Context):
        e = embeds.brand("🤖 Aide — Intelligence artificielle SentriX", (
            "**+ai <question>** / **/ai question:...** — poser une question à l'IA\n**+ai reset** — réinitialiser votre conversation dans ce salon\n**+ai memory** — voir si une conversation est active\n**+ai model** — voir le modèle utilisé par défaut\n**+chat <message>** — discuter avec mémoire de conversation\n**+improve <texte>** — améliorer un texte\n**+correct <texte>** — corriger l'orthographe et la grammaire\n**+ai-translate <langue> <texte>** — traduire un texte avec l'IA\n**+code <demande>** — générer du code\n**+summarize / +explain / +rewrite / +fact-check** — outils spécialisés\n**+image <description>** — générer une image 4K (3840 × 2160)\n**SentriX fais-moi une image de...** — génération 4K en langage naturel\n**SentriX ouvre-moi setup/help** — exécuter une commande en langage naturel\n**SentriX ajoute cet emoji** — importer l'emoji collé ou l'image jointe\n**SentriX donne-moi le lien de...** — rechercher un lien public avec ses sources\n**+aisetup** *(admin)* — configurer l'IA sur ce serveur"
        ))
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="chat", description="Discuter avec l'IA de SentriX (avec mémoire de conversation).", with_app_command=False)
    @app_commands.describe(message='Votre message')
    async def chat_command(self, ctx: commands.Context, *, message: str):
        await self._handle_ai_command(ctx, message)

    @commands.hybrid_command(name="improve", description="Demander à l'IA d'améliorer un texte.", with_app_command=False)
    @app_commands.describe(texte="Le texte à améliorer")
    async def improve_command(self, ctx: commands.Context, *, texte: str):
        await self._handle_ai_command(ctx, f"Améliore ce texte, rends-le plus clair et plus percutant, en gardant le sens original — retourne directement la version améliorée :\n\n{texte}")

    @commands.hybrid_command(name="correct", description="Demander à l'IA de corriger un texte.", with_app_command=False)
    @app_commands.describe(texte="Le texte à corriger")
    async def correct_command(self, ctx: commands.Context, *, texte: str):
        await self._handle_ai_command(ctx, f"Corrige l'orthographe et la grammaire de ce texte, retourne directement la version corrigée sans rien ajouter d'autre :\n\n{texte}")

    # NOTE : le nom "translate" est déjà pris par une commande existante dans cogs/utility.py
    # (traduction via deep-translator, présente AVANT cette refonte — jamais supprimée, voir
    # règle "ne jamais supprimer une commande existante"). Utiliser le même nom ici ferait
    # planter le chargement de tout ce module au démarrage (CommandRegistrationError) : c'est
    # exactement ce qui s'est produit en production, d'où le renommage en "ai-translate".
    @commands.hybrid_command(name="ai-translate", description="Demander à l'IA de traduire un texte.", with_app_command=False)
    @app_commands.describe(langue="La langue cible (ex: anglais, espagnol...)", texte="Le texte à traduire")
    async def translate_command(self, ctx: commands.Context, langue: str, *, texte: str):
        await self._handle_ai_command(ctx, f"Traduis ce texte en {langue}, retourne uniquement la traduction, sans rien ajouter d'autre :\n\n{texte}")

    @commands.hybrid_command(name="code", description="Demander à l'IA d'écrire du code.", with_app_command=False)
    @app_commands.describe(demande="Ce que le code doit faire")
    async def code_command(self, ctx: commands.Context, *, demande: str):
        await self._handle_ai_command(ctx, f"Écris du code complet, propre et sécurisé pour cette demande : {demande}", forced_advanced=True)

    # ---------------------------------------------------------------- +aisetup (admin)

    @commands.hybrid_command(name="aisetup", description="Configurer l'intelligence artificielle du bot pour ce serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("ai")
    async def aisetup(self, ctx: commands.Context):
        if not ctx.guild:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée sur un serveur.')))
        settings = await ai_service.get_settings(self.bot, ctx.guild.id)
        view = AiSetupView(self, ctx.guild.id, ctx.author.id, settings)
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(view.build_embed()), view))

    @commands.hybrid_command(
        name="aidiag",
        description="Diagnostic technique de la connexion à l'IA (admin uniquement).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("ai")
    async def aidiag(self, ctx: commands.Context):
        """Fait un vrai appel de test à OpenAI et rapporte le résultat SANS JAMAIS afficher
        la clé — seulement : présence de la clé, latence, et le type d'erreur éventuel
        (ex: AuthenticationError = clé invalide, APIConnectionError = réseau bloqué côté
        hébergeur, RateLimitError/PermissionDeniedError = crédit épuisé, NotFoundError =
        modèle introuvable). Sert à diagnostiquer "l'IA ne répond pas" sans avoir besoin des
        logs Railway."""
        if ctx.interaction:
            await ctx.defer()
        msg = None
        if not ctx.interaction:
            msg = await panels.envoyer(ctx, panels.depuis_embed(embeds.info("🔧 Test de connexion à l'IA en cours…")))
        async with ctx.typing():
            result = await ai_service.test_connection()

        if not result["has_key"]:
            e = embeds.error("Aucune clé OPENAI_API_KEY n'est configurée sur Railway (variable vide ou absente).")
        elif result["ok"]:
            e = embeds.success(
                f"● Connexion à l'IA fonctionnelle.\n"
                f"**Latence :** {result['latency_ms']} ms\n"
                f"**Modèle testé :** {ai_service.MODEL_LABELS[ai_service.MODEL_TERRA]} (`{config.OPENAI_MODEL}`)\n"
                f"**Réponse test :** {result.get('sample') or '(vide)'}"
            )
        else:
            hints = {
                "AuthenticationError": "La clé OPENAI_API_KEY est invalide ou incorrecte.",
                "PermissionDeniedError": "La clé n'a pas la permission d'utiliser ce modèle (vérifie les permissions de la clé sur platform.openai.com).",
                "RateLimitError": "Limite de débit ou quota/crédit OpenAI épuisé.",
                "NotFoundError": "Modèle introuvable — vérifie OPENAI_MODEL sur Railway.",
                "APIConnectionError": "Impossible de joindre l'API OpenAI depuis Railway (problème réseau côté hébergeur).",
                "APITimeoutError": "L'appel a dépassé le délai maximal (15s) — connexion très lente ou bloquée.",
            }
            hint = hints.get(result["error_type"], "Erreur technique — voir les logs du serveur pour le détail complet.")
            e = embeds.error(
                f"○ Échec de connexion à l'IA après {result['latency_ms']} ms.\n"
                f"**Type d'erreur :** `{result['error_type']}`\n"
                f"**Diagnostic probable :** {hint}"
            )

        if msg:
            await panels.editer(msg, panels.depuis_embed(e))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(e))


async def setup(bot: commands.Bot):
    await bot.add_cog(Ai(bot))

