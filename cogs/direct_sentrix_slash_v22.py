"""SentriX V22 — /sentrix direct, sans commands.Context.

Le chemin hybride historique de /sentrix traversait plusieurs générations de wrappers
Context/defer/typing/send. La conversation naturelle fonctionnait, ce qui confirmait que
le moteur IA était sain, mais la commande slash pouvait encore échouer avant la livraison.

Cette couche remplace uniquement la commande slash locale ``/sentrix`` par un callback
app_commands direct :
- un seul defer Discord ;
- appel du même moteur Ai.ask_ai que le mode naturel ;
- édition/follow-up via les transports discord.py bruts capturés avant les runtimes ;
- aucune utilisation de Context.send, Context.typing ou du callback hybride.

La commande préfixée +sentrix et le listener naturel « SentriX ... » restent inchangés.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import ai_service

logger = logging.getLogger("bot.direct-sentrix-slash-v22")


def _raw_transports():
    try:
        from . import premium_style_runtime
        originals = premium_style_runtime._ORIGINALS
    except Exception:
        originals = {}
    return (
        originals.get("interaction_edit_original"),
        originals.get("webhook_send"),
    )


async def _edit_original(interaction: discord.Interaction, *, content: str) -> None:
    raw_edit, _ = _raw_transports()
    if raw_edit is not None:
        await raw_edit(interaction, content=content)
        return
    await interaction.edit_original_response(content=content)


async def _followup(interaction: discord.Interaction, *, content: str) -> None:
    _, raw_webhook = _raw_transports()
    if raw_webhook is not None:
        await raw_webhook(interaction.followup, content=content, ephemeral=True)
        return
    await interaction.followup.send(content=content, ephemeral=True)


async def _deliver_plain(interaction: discord.Interaction, text: str) -> None:
    chunks = ai_service.split_for_discord((text or "…").strip())
    if not chunks:
        chunks = ["…"]
    await _edit_original(interaction, content=chunks[0])
    for chunk in chunks[1:]:
        await _followup(interaction, content=chunk)


def _build_callback(bot: commands.Bot):
    @app_commands.describe(question="Votre question, sur n'importe quel sujet")
    async def direct_sentrix(interaction: discord.Interaction, question: str) -> None:
        # Un seul acquittement de l'interaction. Aucun Context.defer/typing n'intervient.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        ai_cog = bot.get_cog("Ai")
        if ai_cog is None or not hasattr(ai_cog, "ask_ai"):
            await _edit_original(
                interaction,
                content="Le moteur IA de SentriX n'est pas chargé. Réessayez dans quelques instants.",
            )
            return

        try:
            guild_id = interaction.guild_id
            channel_id = interaction.channel_id or 0
            user_id = interaction.user.id
            history = ai_cog.histories.get(user_id, [])
            author_name = getattr(interaction.user, "display_name", None) or str(interaction.user)

            answer = await ai_cog.ask_ai(
                question,
                history,
                author_name=author_name,
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=user_id,
                command="sentrix-slash-v22",
            )

            if ai_service.is_error_code(answer):
                await _deliver_plain(interaction, ai_service.error_message(answer))
                return

            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": answer})
            ai_cog.histories[user_id] = history[-10:]
            await _deliver_plain(interaction, answer)
        except Exception as exc:
            logger.exception("/sentrix V22 a échoué pour user=%s", interaction.user.id)
            # Le type est volontairement visible pendant la phase de réparation : aucun
            # prompt, token, clé, payload SQL ou contenu de réponse n'est exposé.
            await _edit_original(
                interaction,
                content=f"Erreur /sentrix : {type(exc).__name__}. Référence V22-SENTRIX.",
            )

    direct_sentrix._sentrix_direct_slash_v22 = True
    return direct_sentrix


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None:
        return

    existing = bot.tree.get_command("sentrix")
    callback = getattr(existing, "callback", None) if existing is not None else None
    if getattr(callback, "_sentrix_direct_slash_v22", False):
        return

    # Retirer uniquement la commande application. Le commands.Command hybride reste dans
    # bot.commands et continue donc de servir +sentrix normalement.
    try:
        bot.tree.remove_command("sentrix", type=discord.AppCommandType.chat_input)
    except Exception:
        logger.debug("Ancienne /sentrix déjà absente du tree.", exc_info=True)

    direct_callback = _build_callback(bot)
    command = app_commands.Command(
        name="sentrix",
        description="Demandez n'importe quoi à SentriX, l'IA du bot.",
        callback=direct_callback,
    )
    bot.tree.add_command(command, override=True)
    bot._sentrix_direct_slash_v22 = True
    logger.info("V22 : /sentrix remplacée par un callback Discord direct.")


__all__ = ["install"]
