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

from utils import config_journal
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
    actor_token = trace.ACTOR.set((
        int(getattr(ctx.author, "id", 0) or 0),
        "prefix" if interaction is None
        else "bouton" if interaction.type is discord.InteractionType.component else "slash",
    ))
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
        origin=trace.ORIGIN.get() or "",
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
        trace.ACTOR.reset(actor_token)
        await _finish(ctx, current, error)


def _install_actor_on_components() -> None:
    """Un menu ou un formulaire (/setup) agit au nom de celui qui clique.

    Tous les clics de vues (classiques et Components V2) passent par
    ``_scheduled_task`` ; toutes les modales aussi. Le journal des réglages y lit
    l'auteur d'un changement fait depuis /setup.
    """
    from discord.ui import view as view_module

    targets = [(getattr(view_module, "BaseView", discord.ui.View), "menu"), (discord.ui.Modal, "formulaire")]
    for cls, source in targets:
        original = cls.__dict__.get("_scheduled_task")
        if original is None or getattr(original, "_sentrix_actor", False):
            continue

        async def scheduled(self, *args, _original=original, _source=source):
            interaction = next((a for a in args if isinstance(a, discord.Interaction)), None)
            user = getattr(interaction, "user", None)
            if user is None or trace.ACTOR.get() is not None:
                return await _original(self, *args)
            token = trace.ACTOR.set((int(user.id), _source))
            try:
                return await _original(self, *args)
            finally:
                trace.ACTOR.reset(token)

        scheduled._sentrix_actor = True
        scheduled._sentrix_original = original
        cls._scheduled_task = scheduled


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
    if current.origin:
        detail = f"{trace.SUITE_MARK}{current.origin}" + (f" · {detail}" if detail else "")
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
        custom_id = str(data.get("custom_id") or "")
        if custom_id.startswith(config_journal.UNDO_PREFIX) and not interaction.response.is_done():
            return await self._undo_click(interaction, custom_id)
        parsed = trace.parse_suite(custom_id)
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
        origin = trace.ORIGIN.set(trace.normalise_ref(ref) or None)
        try:
            await command.invoke(ctx)
        except commands.CommandError as exc:
            ctx.command_failed = True
            await command.dispatch_error(ctx, exc)
        else:
            if not ctx.command_failed:
                self.bot.dispatch("command_completion", ctx)
        finally:
            trace.ORIGIN.reset(origin)
            for target in forced:
                target.__dict__.pop("_parse_arguments", None)

    async def _undo_click(self, interaction: discord.Interaction, custom_id: str) -> None:
        from utils import access_matrix
        from utils.audit_trail import journaliser

        decision = await access_matrix.evaluate(
            self.bot, command_name="config-history", author=interaction.user, guild=interaction.guild,
        )
        if not decision.allowed:
            return await interaction.response.send_message(
                decision.message or "Vous n'avez pas accès à cette action.", ephemeral=True,
            )
        raw = custom_id[len(config_journal.UNDO_PREFIX):]
        if not raw.isdigit():
            return await interaction.response.send_message("Changement introuvable.", ephemeral=True)
        token = trace.ACTOR.set((int(interaction.user.id), "annulation"))
        try:
            done, reason, entry = await config_journal.undo(self.bot.db, interaction.guild.id, int(raw))
        finally:
            trace.ACTOR.reset(token)
        if not done:
            messages = {
                "missing": "Ce changement n'existe plus dans le journal.",
                "already": "Ce changement a déjà été annulé.",
                "changed": "Ce réglage a été modifié depuis : annulez d'abord le changement le plus récent.",
            }
            return await interaction.response.send_message(messages.get(reason, "Annulation impossible."), ephemeral=True)
        field = entry["field"]
        avant = config_journal.render(interaction.guild, field, entry["new_value"])
        apres = config_journal.render(interaction.guild, field, entry["old_value"])
        await journaliser(self.bot, interaction, "config_update", "↩️ Réglage annulé", {
            "⚙️ Réglage": config_journal.label(field), "Avant": avant, "Après": apres, "N° annulé": f"#{entry['id']}",
        })
        await interaction.response.send_message(
            f"↩️ **{config_journal.label(field)}** : {avant} → {apres} (changement n°{entry['id']} annulé).",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="config-history", help="Les derniers changements de réglages, avec annulation.")
    @commands.guild_only()
    async def config_history(self, ctx: commands.Context) -> None:
        entries = await config_journal.recent(self.bot.db, ctx.guild.id, limit=10)
        try:
            from cogs import language_runtime

            english = await language_runtime.get_language(self.bot, ctx.guild.id) == language_runtime.LANG_EN
        except Exception:
            english = False
        sources = config_journal.SOURCES_EN if english else config_journal.SOURCES
        if not entries:
            return await panels.envoyer(ctx, panels.Panneau(
                titre="Config history" if english else "Historique des réglages",
                sous_titre="No setting has changed yet." if english else "Aucun réglage n'a encore changé.",
                kind="info",
            ))
        lignes = []
        for entry in entries:
            par = f"<@{entry['actor_id']}>" if entry["actor_id"] else ("system" if english else "système")
            via = sources.get(str(entry["source"] or ""), str(entry["source"] or ""))
            etat = ("undone" if english else "annulé") if entry["undone_by"] else ""
            indice = " · ".join(x for x in (par, via, f"<t:{int(entry['created_at'])}:R>", etat) if x)
            lignes.append(panels.Ligne(
                f"n°{entry['id']} · {config_journal.label(entry['field'])}",
                f"{config_journal.render(ctx.guild, entry['field'], entry['old_value'])} → "
                f"{config_journal.render(ctx.guild, entry['field'], entry['new_value'])}",
                indice=indice,
            ))
        await panels.envoyer(ctx, panels.Panneau(
            titre="Config history" if english else "Historique des réglages",
            sous_titre=("Every change, wherever it came from. A change is only undone if nothing changed since."
                        if english else
                        "Chaque changement, d'où qu'il vienne. On n'annule que si rien n'a changé depuis."),
            sections=[panels.Section("Changes" if english else "Changements", lignes)],
            kind="info",
            boutons=config_journal.undo_buttons(list(entries), english=english),
        ))

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
        automatique = row["transport"] == trace.AUTOMATIC
        if automatique:
            commande = "AutoMod (action automatique de SentriX)"
        lignes = [
            panels.Ligne("Commande", commande),
            panels.Ligne("Par", "SentriX" if automatique else f"<@{row['actor_id']}>"),
            panels.Ligne("Quand", f"<t:{int(row['created_at'])}:F> · <t:{int(row['created_at'])}:R>"),
            panels.Ligne("Où", f"<#{row['channel_id']}>" if row["channel_id"] else "—"),
            panels.Ligne("Résultat", OUTCOME_LABELS.get(str(row["outcome"]), str(row["outcome"]))),
        ]
        if row["target_id"]:
            lignes.insert(2, panels.Ligne("Visait", f"<@{row['target_id']}>"))
        detail = str(row["detail"] or "")
        origine = trace.origin_of(detail)
        if origine:
            # Le fil vers l'amont : l'action dont celle-ci est la suite.
            lignes.append(panels.Ligne("Suite de", f"**{origine}**"))
            detail = detail[len(trace.SUITE_MARK) + len(origine):].lstrip(" ·")
        if detail:
            lignes.append(panels.Ligne("Détail", f"`{detail}`"))
        sections = [panels.Section("Action", lignes)]
        # Le fil vers l'aval : ce que le staff a fait depuis les boutons de suite.
        suites = await trace.follow_ups(self.bot.db, ctx.guild.id, row["ref"])
        if suites:
            prefixe = {"slash": "/", "prefix": "+"}
            sections.append(panels.Section("Suites données", [
                panels.Ligne(
                    f"`{prefixe.get(str(s['transport']), '')}{s['command']}`"
                    + (" (bouton)" if s["transport"] == "bouton" else ""),
                    f"par <@{s['actor_id']}> · **{s['ref']}** · <t:{int(s['created_at'])}:R>"
                    + ("" if s["outcome"] == "ok" else f" · {OUTCOME_LABELS.get(str(s['outcome']), s['outcome'])}"),
                )
                for s in suites
            ]))
        await panels.envoyer(ctx, panels.Panneau(
            titre=f"Trace {row['ref']}",
            sous_titre="La même référence figure sur la réponse et sur la carte de log.",
            sections=sections,
            kind="info",
        ))


async def setup(bot: commands.Bot) -> None:
    _install_invoke_wrapper()
    _install_actor_on_components()
    await bot.add_cog(Trace(bot))
