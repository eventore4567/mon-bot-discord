"""SentriX V33 — commande unique de test de tous les journaux.

Commande hybride administrateur : ``+testlogs`` / ``/testlogs``.
Elle envoie une carte de TEST dans chaque salon de log configuré, ancien comme nouveau,
sans provoquer de vraie sanction, suppression, raid, ticket ou modification serveur.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import log_service
from . import premium_logs_v2
from .premium_logs import style_log, _button_items

logger = logging.getLogger("bot.log-test-all-v33")


TEST_TITLES = {
    "messages": "Message supprimé — TEST",
    "members": "Membre arrivé — TEST",
    "roles": "Rôle créé — TEST",
    "server": "Serveur modifié — TEST",
    "voice": "Activité vocale — TEST",
    "moderation": "Membre banni — TEST",
    "tickets": "Ticket ouvert — TEST",
    "automod": "Protection déclenchée — TEST",
    "economy": "Transaction enregistrée — TEST",
    "levels": "Niveau gagné — TEST",
    "ai": "Requête IA — TEST",
    "games": "Partie terminée — TEST",
    "system": "Événement système — TEST",
    "channels": "Salon créé — TEST",
    "cases": "Avertissement ajouté — TEST",
    "spam": "Anti-spam déclenché — TEST",
    "raid": "Raid détecté — TEST",
    "staff": "Commande staff exécutée — TEST",
}


def _test_embed(ctx: commands.Context, log_type: str) -> discord.Embed:
    title = TEST_TITLES.get(log_type, f"Journal {log_type} — TEST")
    embed = discord.Embed(
        title=title,
        description=(
            "Test SentriX uniquement : aucun véritable événement n'a été exécuté. "
            "Cette carte sert à vérifier le salon, le routage et le style du journal."
        ),
        colour=0x7C5CFC,
        timestamp=discord.utils.utcnow(),
    )
    if ctx.author:
        embed.add_field(name="Auteur", value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=False)
    if ctx.channel:
        embed.add_field(name="Salon", value=f"{ctx.channel.mention}\n`ID : {ctx.channel.id}`", inline=False)

    if log_type == "messages":
        embed.add_field(name="Contenu", value="Ceci est un message de test SentriX.", inline=False)
        embed.add_field(name="ID du message", value=f"`{getattr(ctx.message, 'id', ctx.author.id)}`", inline=False)
    elif log_type == "roles":
        embed.add_field(name="Rôle", value="@Role-Test\n`Permissions : aucune modification réelle`", inline=False)
    elif log_type in {"moderation", "cases"}:
        embed.add_field(name="Effectué par", value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=False)
        embed.add_field(name="Raison", value="Test manuel de tous les journaux SentriX.", inline=False)
    elif log_type in {"automod", "spam", "raid"}:
        embed.add_field(name="Détection", value="Simulation de sécurité — aucune action réelle.", inline=False)
        embed.add_field(name="Action", value="TEST seulement", inline=False)
    elif log_type == "tickets":
        embed.add_field(name="Ticket", value="#test-ticket\n`Aucun ticket réel créé`", inline=False)
    elif log_type == "voice":
        embed.add_field(name="Avant", value="Hors vocal", inline=False)
        embed.add_field(name="Après", value="Salon vocal de test", inline=False)
    elif log_type == "channels":
        embed.add_field(name="Salon", value="#salon-test\n`Aucun salon réel créé`", inline=False)
    elif log_type == "staff":
        embed.add_field(name="Commande", value="`+testlogs`", inline=False)
        embed.add_field(name="Effectué par", value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=False)
    elif log_type == "economy":
        embed.add_field(name="Montant", value="+100 crédits (TEST)", inline=False)
    elif log_type == "levels":
        embed.add_field(name="Niveau", value="10 → 11 (TEST)", inline=False)
    elif log_type == "ai":
        embed.add_field(name="Requête", value="Test du journal IA SentriX.", inline=False)
    elif log_type == "games":
        embed.add_field(name="Résultat", value="Victoire de test — aucune récompense réelle.", inline=False)
    elif log_type == "system":
        embed.add_field(name="État", value="Système opérationnel — TEST", inline=False)
    elif log_type == "members":
        embed.add_field(name="Compte créé", value=discord.utils.format_dt(ctx.author.created_at, "F"), inline=False)
    elif log_type == "server":
        embed.add_field(name="Modification", value="Configuration de test — aucune modification réelle.", inline=False)

    embed.set_footer(text=f"Identifiant : {ctx.author.id}")
    return embed


async def _send_direct_test(bot: commands.Bot, guild: discord.Guild, channel, log_type: str, embed: discord.Embed) -> bool:
    """Utilise le renderer final même si la catégorie est désactivée, sans changer sa config."""
    try:
        styled = style_log(bot, guild, log_type, embed.copy())
        buttons = _button_items(styled, str(styled.title or ""))
        layout = premium_logs_v2.PremiumLogLayout(bot, guild, log_type, styled, buttons)
        await channel.send(view=layout, allowed_mentions=discord.AllowedMentions.none())
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
    except Exception:
        logger.exception("V33 : test de log impossible guild=%s type=%s", guild.id, log_type)
        return False


class LogTestAllV33(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="testlogs",
        aliases=["test-logs", "logs-test"],
        description="Tester tous les anciens et nouveaux salons de logs SentriX en une fois.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    async def testlogs(self, ctx: commands.Context):
        """Envoie un test visuel dans chaque catégorie ayant un salon configuré."""
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        sent: list[str] = []
        disabled_but_tested: list[str] = []
        missing: list[str] = []
        failed: list[str] = []

        # V32 a déjà enrichi LOG_TYPES avant l'installation de V33.
        for log_type, meta in list(log_service.LOG_TYPES.items()):
            try:
                setting = await log_service.get_log_setting(self.bot, ctx.guild.id, log_type)
            except Exception:
                failed.append(log_type)
                continue

            channel_id = setting.get("channel_id")
            channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
            if channel is None:
                missing.append(log_type)
                continue

            ok, _reason = log_service.validate_channel(ctx.guild, channel.id)
            if not ok:
                failed.append(log_type)
                continue

            embed = _test_embed(ctx, log_type)
            if await _send_direct_test(self.bot, ctx.guild, channel, log_type, embed):
                sent.append(log_type)
                if not setting.get("enabled"):
                    disabled_but_tested.append(log_type)
            else:
                failed.append(log_type)

            # Évite de pousser 18 messages dans la même seconde si plusieurs catégories
            # utilisent le même salon de repli.
            await asyncio.sleep(0.12)

        lines = [
            f"**{len(sent)}** catégorie(s) testée(s) sur **{len(log_service.LOG_TYPES)}**.",
        ]
        if missing:
            lines.append("**Sans salon :** " + ", ".join(f"`{x}`" for x in missing))
        if disabled_but_tested:
            lines.append("**Désactivées mais testées sans modifier la config :** " + ", ".join(f"`{x}`" for x in disabled_but_tested))
        if failed:
            lines.append("**Échec/permissions :** " + ", ".join(f"`{x}`" for x in failed))
        if not missing and not failed:
            lines.append("Tous les salons de logs configurés ont reçu leur carte de test.")

        await ctx.send(
            embed=discord.Embed(
                title="Test complet des logs SentriX",
                description="\n".join(lines)[:4000],
                colour=0x57F287 if sent and not failed else 0xFEE75C,
            ),
            ephemeral=bool(ctx.interaction),
        )


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    if bot.get_cog("LogTestAllV33") is None:
        await bot.add_cog(LogTestAllV33(bot))


__all__ = ["install", "LogTestAllV33"]
