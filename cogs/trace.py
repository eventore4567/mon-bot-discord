"""Le fil SentriX : une référence par action du staff, et ``+trace`` / ``/logs trace``.

Voir utils/sentrix_trace.py pour le principe. Ce cog :

- enveloppe ``Command.invoke`` et ``Group.invoke``, le passage commun du préfixe
  et du slash du catalogue (sentrix_v95_runtime._invoke_original appelle
  ``root.invoke(ctx)``, ``Bot.invoke`` appelle ``ctx.command.invoke(ctx)``) ;
- enregistre chaque invocation tracée avec son résultat réel ;
- répond à ``+trace <référence>`` ;
- purge les traces de plus de 90 jours.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from utils import sentrix_panels as panels
from utils import sentrix_trace as trace

logger = logging.getLogger("bot.trace")

OUTCOME_LABELS = {
    "ok": "Exécutée",
    "échec": "Échec signalé à l'auteur",
    "refusé": "Refusée (permission)",
    "saisie invalide": "Refusée (saisie invalide)",
    "erreur": "Erreur technique",
}


async def _traced(ctx, name: str, run):
    """Ouvre la trace de l'invocation la plus externe ; les appels imbriqués en héritent."""
    guild = getattr(ctx, "guild", None)
    interaction = getattr(ctx, "interaction", None)
    message = getattr(ctx, "message", None)
    invocation = getattr(interaction, "id", None) or getattr(message, "id", None)
    if trace.CURRENT.get() is not None or guild is None or invocation is None:
        return await run()
    current = trace.Trace(
        ref=trace.make_ref(guild.id, invocation),
        guild_id=guild.id,
        command=name,
        transport=(
            "prefix" if interaction is None
            else "bouton" if interaction.type is discord.InteractionType.component
            else "slash"
        ),
        actor_id=int(getattr(ctx.author, "id", 0) or 0),
        channel_id=getattr(getattr(ctx, "channel", None), "id", None),
        ctx=ctx,
    )
    token = trace.CURRENT.set(current)
    error: BaseException | None = None
    try:
        return await run()
    except BaseException as exc:
        error = exc
        raise
    finally:
        trace.CURRENT.reset(token)
        await _finish(ctx, current, error)


def _install_invoke_wrapper() -> None:
    for cls in (commands.Command, commands.Group):
        original = cls.__dict__.get("invoke")
        if original is None or getattr(original, "_sentrix_trace", False):
            continue

        async def invoke(self, ctx, _original=original):
            return await _traced(ctx, self.qualified_name, lambda: _original(self, ctx))

        invoke._sentrix_trace = True
        invoke._sentrix_original = original
        cls.invoke = invoke

    # Le slash « natif » (sentrix_grouped_slash_fix) lie les options sans parser
    # et appelle command.callback directement : il ne passe jamais par
    # Command.invoke. Mesuré : /warn s'exécutait sans trace.
    try:
        import sentrix_grouped_slash_fix as grouped
    except Exception:
        logger.exception("Slash natif introuvable : /commandes non tracées.")
        return
    native = grouped._invoke_native
    if getattr(native, "_sentrix_trace", False):
        return

    async def invoke_native(bot, command, ctx, option_names, values, _native=native):
        return await _traced(
            ctx, command.qualified_name, lambda: _native(bot, command, ctx, option_names, values),
        )

    invoke_native._sentrix_trace = True
    invoke_native._sentrix_original = native
    grouped._invoke_native = invoke_native


async def _finish(ctx, current: trace.Trace, error: BaseException | None) -> None:
    resolved = getattr(getattr(ctx, "command", None), "qualified_name", None) or current.command
    current.command = resolved
    if not trace.is_traced(resolved):
        return
    outcome, detail = trace.classify(error if isinstance(error, Exception) else None)
    if outcome == "ok" and getattr(ctx, "command_failed", False):
        outcome = "échec"
    current.outcome, current.detail = outcome, detail
    current.target_id = trace.target_of(ctx)
    db = getattr(getattr(ctx, "bot", None), "db", None)
    if db is None:
        return
    try:
        await trace.record(db, current)
    except Exception:
        logger.exception("Trace %s impossible à enregistrer.", current.ref)


async def _context_from_click(bot: commands.Bot, interaction: discord.Interaction, command: commands.Command):
    """Un Context au nom de la personne qui clique, comme Context.from_interaction.

    discord.py refuse une interaction de bouton (elle ne porte pas de commande) ;
    on reproduit donc son message synthétique — auteur = celui qui clique, jamais
    le bot qui a posté le bouton.
    """
    from discord.ext.commands.view import StringView

    payload = {
        "id": interaction.id, "reactions": [], "embeds": [], "mention_everyone": False, "tts": False,
        "pinned": False, "edited_timestamp": None, "type": discord.MessageType.chat_input_command.value,
        "flags": 64, "content": "", "mentions": [], "mention_roles": [], "attachments": [],
        "channel_id": interaction.channel_id,
    }
    channel = interaction.channel or discord.PartialMessageable(
        state=interaction._state, guild_id=interaction.guild_id, id=interaction.channel_id,
    )
    message = discord.Message(state=interaction._state, channel=channel, data=payload)
    message.author = interaction.user
    ctx = commands.Context(
        message=message, bot=bot, view=StringView(""), args=[], kwargs={}, prefix="/",
        interaction=interaction, invoked_with=command.name, command=command,
    )
    try:
        sentrix_context = getattr(__import__("main"), "SentriXContext", None)
        if sentrix_context is not None and not isinstance(ctx, sentrix_context):
            ctx.__class__ = sentrix_context
    except Exception:
        pass
    # Une commande hybride relit son contexte ici (HybridAppCommand._check_can_run) :
    # Context.from_interaction le range, sans lui les contrôles lisent MISSING.guild.
    interaction._baton = ctx
    return ctx


class Trace(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        if not self.purge_old.is_running():
            self.purge_old.start()

    async def cog_unload(self) -> None:
        self.purge_old.cancel()

    @tasks.loop(hours=6)
    async def purge_old(self) -> None:
        try:
            await trace.purge(self.bot.db)
        except Exception:
            logger.exception("Purge des traces impossible.")

    @purge_old.before_loop
    async def _before_purge(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Un bouton de suite = la commande correspondante, exécutée par celui qui clique."""
        if interaction.type is not discord.InteractionType.component or interaction.guild is None:
            return
        data = interaction.data if isinstance(interaction.data, dict) else {}
        parsed = trace.parse_suite(str(data.get("custom_id") or ""))
        if parsed is None or interaction.response.is_done():
            return
        sanction, action, target_id, ref = parsed
        resolved = trace.suite_command(sanction, action, target_id, ref)
        command = self.bot.get_command(resolved[0]) if resolved else None
        if command is None:
            return await interaction.response.send_message("Cette action n'est plus disponible.", ephemeral=True)
        # Accusé immédiat (3 s), privé : la suite est un geste du staff, pas une annonce.
        await interaction.response.defer(ephemeral=True, thinking=True)
        from discord.ext.commands.view import StringView

        ctx = await _context_from_click(self.bot, interaction, command)
        ctx.view = StringView(resolved[1])
        self.bot.dispatch("command", ctx)
        # ctx.interaction est renseigné : discord.py croirait les arguments déjà
        # fournis par Discord et appellerait la commande sans membre. Les
        # arguments arrivent ici en texte, comme sur le chemin slash « legacy ».
        import sentrix_grouped_slash_fix as grouped

        forced = grouped._force_text_parser((command,))
        try:
            await command.invoke(ctx)
        except commands.CommandError as exc:
            ctx.command_failed = True
            await command.dispatch_error(ctx, exc)
        else:
            if not ctx.command_failed:
                self.bot.dispatch("command_completion", ctx)
        finally:
            for target in forced:
                target.__dict__.pop("_parse_arguments", None)

    @commands.command(name="trace", help="Retrouver une action du staff par sa référence (SX-…).")
    @commands.guild_only()
    async def trace_command(self, ctx: commands.Context, reference: str) -> None:
        row = await trace.lookup(self.bot.db, ctx.guild.id, reference)
        if row is None:
            return await panels.envoyer(ctx, panels.Panneau(
                titre="Référence introuvable",
                sous_titre=f"Aucune action **{trace.normalise_ref(reference) or reference}** sur ce serveur "
                           "(les références sont gardées 90 jours).",
                kind="warning",
            ))
        transport = {"slash": "/", "prefix": "+"}.get(str(row["transport"]), "")
        commande = f"`{transport}{row['command']}`" + (" (bouton)" if row["transport"] == "bouton" else "")
        lignes = [
            panels.Ligne("Commande", commande),
            panels.Ligne("Par", f"<@{row['actor_id']}>"),
            panels.Ligne("Quand", f"<t:{int(row['created_at'])}:F> · <t:{int(row['created_at'])}:R>"),
            panels.Ligne("Où", f"<#{row['channel_id']}>" if row["channel_id"] else "—"),
            panels.Ligne("Résultat", OUTCOME_LABELS.get(str(row["outcome"]), str(row["outcome"]))),
        ]
        if row["target_id"]:
            lignes.insert(2, panels.Ligne("Visait", f"<@{row['target_id']}>"))
        if row["detail"]:
            lignes.append(panels.Ligne("Détail", f"`{row['detail']}`"))
        await panels.envoyer(ctx, panels.Panneau(
            titre=f"Trace {row['ref']}",
            sous_titre="La même référence figure sur la réponse et sur la carte de log.",
            sections=[panels.Section("Action", lignes)],
            kind="info",
        ))


async def setup(bot: commands.Bot) -> None:
    _install_invoke_wrapper()
    await bot.add_cog(Trace(bot))
