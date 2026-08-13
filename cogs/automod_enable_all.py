"""Administration du serveur: activer tous les filtres AutoMod configurables."""
from discord.ext import commands
from utils import checks, embeds

_INSTALLED = False

@checks.is_owner_or_admin_for("securite")
async def enable_all(ctx: commands.Context):
    if ctx.guild is None:
        return await ctx.send(embed=embeds.error("Commande disponible uniquement sur un serveur."))
    from .automod import TOGGLE_FIELDS, AUTOMOD_TOGGLE_LABELS
    for field in TOGGLE_FIELDS:
        await ctx.bot.db.set_automod(ctx.guild.id, field, 1)
    await ctx.bot.db.set_automod(ctx.guild.id, "escalation", 1)
    await ctx.bot.db.execute(
        "INSERT INTO guild_config (guild_id,security_level) VALUES (?,'eleve') "
        "ON CONFLICT(guild_id) DO UPDATE SET security_level='eleve'",
        (ctx.guild.id,),
    )
    automod = ctx.bot.get_cog("Automod")
    cache = getattr(automod, "automod_cache", None)
    if isinstance(cache, dict):
        cache.pop(ctx.guild.id, None)
    labels = [AUTOMOD_TOGGLE_LABELS.get(field, field) for field in TOGGLE_FIELDS]
    await ctx.send(embed=embeds.success(
        "Toutes les protections configurables sont maintenant **ACTIVES**.\n\n"
        + "\n".join(f"• {label}" for label in labels)
        + "\n• Escalade automatique des sanctions\n\nNiveau global : **ÉLEVÉ**."
    ))

def install(bot: commands.Bot):
    global _INSTALLED
    if _INSTALLED:
        return True
    root = bot.get_command("security")
    if not isinstance(root, commands.Group):
        return False
    if root.get_command("all") is None:
        root.add_command(commands.Command(enable_all, name="all", help="Activer tous les filtres AutoMod du serveur."))
    _INSTALLED = True
    return True

async def setup(bot: commands.Bot):
    install(bot)
