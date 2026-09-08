#!/usr/bin/env python3
"""Audit d'intégrité du pipeline de commandes SentriX : détecte, sur le bot RÉELLEMENT
chargé (main.EXTENSIONS + les ~21 extensions supplémentaires ajoutées par
railway_boot.py, exactement comme en production), toute commande dont le chemin
d'exécution slash (`/`) et préfixe (`+`) ont divergé — la cause structurelle commune à
plusieurs bugs trouvés cette session (dont /unmute).

CAUSE RACINE CONFIRMÉE PAR LECTURE DU CODE SOURCE DE discord.py 2.7.1 :

  HybridAppCommand.__init__ (discord/ext/commands/hybrid.py) fait :
      super().__init__(..., callback=wrapped.callback, ...)
  ce qui COPIE la référence de fonction dans app_commands.Command._callback AU MOMENT
  de la construction. C'est un INSTANTANÉ, pas une liaison vivante :

      >>> demo.callback = wrapper
      >>> demo.callback is demo.app_command._callback
      False

  Le chemin préfixe (Command.invoke -> hooked_wrapped_callback(self, ctx, self.callback))
  relit `self.callback` à chaque appel, donc `command.callback = wrapper` (le motif
  utilisé par ~70 fichiers cogs/*.py pour ajouter dédoublonnage/sécurité/logs à une
  commande existante) le voit immédiatement. Le chemin slash
  (HybridAppCommand._do_call -> self._callback) ne le voit JAMAIS s'il a été appliqué
  APRÈS que l'app_command existait déjà (with_app_command=True dès la décoration, ou
  restauré plus tard par cogs/command_hybrid_slash_restore_v3.py) : la version slash
  continue silencieusement d'exécuter l'ANCIEN code, pour toujours.

  Concrètement : si un wrapper ajoute une protection anti-double-sanction, un check,
  ou une correction de comportement à une commande hybride déjà slash-active, `+la`
  commande est protégée mais `/la` commande ne l'est jamais. Aucune erreur, aucun log :
  silencieux des deux côtés.

Ce script compare, pour CHAQUE HybridCommand/HybridGroup (et récursivement ses
sous-commandes) déjà slash-active, `command.callback` à l'objet réellement invoqué côté
slash. Il vérifie aussi, plus généralement, la cohérence self/ctx/interaction et les
doublons de registre (déjà couverts partiellement par tools/command_runtime_audit.py,
repris ici pour un rapport unique).
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _app_callback_object(hybrid_command):
    """Le callback RÉELLEMENT exécuté côté slash pour une HybridCommand/HybridGroup,
    ou None si aucun app_command n'a jamais été construit pour elle (reste + only)."""
    app_command = getattr(hybrid_command, "app_command", None)
    if app_command is None:
        return None
    return getattr(app_command, "_callback", None)


async def _walk_all_hybrid(bot):
    """Toutes les HybridCommand/HybridGroup, y compris les sous-commandes de groupe,
    en excluant les groupes eux-mêmes qui n'ont pas de callback propre invocable."""
    from discord.ext import commands as dpy_commands

    for command in bot.walk_commands():
        if isinstance(command, (dpy_commands.HybridCommand, dpy_commands.HybridGroup)):
            yield command


async def run() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-callback-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ci.db")

        import main
        before = list(main.EXTENSIONS)

        # Réplique EXACTEMENT ce que fait railway_boot.py sur main.EXTENSIONS (les ~21
        # extensions supplémentaires actives en production), sans importer railway_boot.py
        # lui-même (qui patche commands.Bot en AutoShardedBot et importe web.dashboard —
        # non nécessaire pour un audit de registre, et plus fragile à charger hors serveur).
        railway_extra = [
            "cogs.drop", "cogs.interaction_transport_guard",
            "cogs.legacy_observability_conflict_guard", "cogs.slash_reliability_v7",
            "cogs.automod_enable_all", "cogs.setup_auto_fix", "cogs.setup_experience_v2",
            "cogs.emoji_name_lookup", "cogs.emoji_unicode_asset_fix", "cogs.create_sentrix",
            "cogs.create_sentrix_v3", "cogs.canonical_interactions", "cogs.sentrix_plus",
            "cogs.sentrix_ultimate", "cogs.plain_text_all_extension",
            "cogs.profile_oxyde_runtime", "cogs.deferred_context_response_guard",
            "cogs.slash_error_completion_guard", "cogs.final_stability_guard",
            "cogs.member_data_retention_v17", "cogs.sentrix_regression_fix",
        ]
        for ext in railway_extra:
            if ext not in main.EXTENSIONS:
                main.EXTENSIONS.append(ext)
        print(f"Extensions main.py: {len(before)} ; + railway_boot.py: {len(main.EXTENSIONS) - len(before)} ; total: {len(main.EXTENSIONS)}")

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded: list[str] = []
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")
        print(f"Extensions chargées: {len(loaded)}/{len(main.EXTENSIONS)}")

        # Reconstitue la surface finale exactement comme au vrai démarrage (voir
        # tools/command_runtime_audit.py) : c'est APRÈS ces étapes que
        # command_hybrid_slash_restore_v3 et slash_command_budget ont fini de jouer,
        # donc que la divergence éventuelle callback vs app_command._callback est figée
        # dans son état final de production.
        from cogs import command_catalog_cleanup, slash_command_budget
        from cogs.hybrid_callback_resync import resync as resync_hybrid_callbacks
        bot._prune_redundant_commands()
        command_catalog_cleanup.apply_surface(bot)
        slash_command_budget.finalize(bot)
        resynced = resync_hybrid_callbacks(bot)
        print(f"Callbacks slash resynchronisés par cogs/hybrid_callback_resync.py: {len(resynced)}")

        # ------------------------------------------------------------------
        # 1. Divergence callback prefixe vs callback slash (LA cause commune)
        # ------------------------------------------------------------------
        diverged: list[tuple[str, str, object, object]] = []
        no_app_command: list[str] = []
        async for command in _walk_all_hybrid(bot):
            app_callback = _app_callback_object(command)
            if app_callback is None:
                no_app_command.append(command.qualified_name)
                continue
            if command.callback is not app_callback:
                diverged.append((
                    command.qualified_name,
                    command.cog_name or "(sans cog)",
                    command.callback,
                    app_callback,
                ))

        if diverged:
            errors.append(
                f"{len(diverged)} commande(s) hybride(s) où / exécute un code DIFFÉRENT de + "
                "(callback réassigné après construction de l'app_command — voir le docstring "
                "de ce script) : " + ", ".join(name for name, *_ in diverged)
            )

        # ------------------------------------------------------------------
        # 2. self/ctx exposés à tort, signature vide suspecte
        # ------------------------------------------------------------------
        suspicious_signature: list[str] = []
        async for command in _walk_all_hybrid(bot):
            try:
                sig = inspect.signature(command.callback)
            except (TypeError, ValueError):
                continue
            names = list(sig.parameters.keys())
            has_only_var = names and all(
                sig.parameters[n].kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for n in names
            )
            if has_only_var:
                suspicious_signature.append(
                    f"{command.qualified_name} (callback={command.callback!r}, signature={sig})"
                )
        if suspicious_signature:
            warnings.append(
                f"{len(suspicious_signature)} commande(s) dont le callback ACTUEL n'a plus que "
                "*args/**kwargs (le paramétrage réel vient alors uniquement de command.params, "
                "figé à la construction — vérifier que ça reste synchronisé si la commande est "
                "un jour reconstruite en slash) : " + "; ".join(suspicious_signature)
            )

        # ------------------------------------------------------------------
        # 3. Doublons de registre (nom qualifié présent plus d'une fois)
        # ------------------------------------------------------------------
        from collections import Counter
        prefix_names = [c.qualified_name.casefold() for c in bot.walk_commands()]
        prefix_dupes = [name for name, count in Counter(prefix_names).items() if count > 1]
        if prefix_dupes:
            errors.append("Doublons dans le registre préfixe/hybride: " + ", ".join(sorted(prefix_dupes)))

        app_names = [c.qualified_name.casefold() for c in bot.tree.walk_commands()]
        app_dupes = [name for name, count in Counter(app_names).items() if count > 1]
        if app_dupes:
            errors.append("Doublons dans le CommandTree slash: " + ", ".join(sorted(app_dupes)))

        # ------------------------------------------------------------------
        # 4. Commande présente en + mais absente du CommandTree alors que
        #    with_app_command=True (devrait être slash mais ne l'est pas)
        # ------------------------------------------------------------------
        from discord.ext import commands as dpy_commands
        missing_slash_should_exist: list[str] = []
        async for command in _walk_all_hybrid(bot):
            if command.parent is not None:
                continue  # sous-commande : vérifiée via le groupe parent
            wants_slash = getattr(command, "with_app_command", True)
            if wants_slash and command.app_command is None:
                missing_slash_should_exist.append(command.qualified_name)
        if missing_slash_should_exist:
            warnings.append(
                "Commande(s) hybride(s) déclarées with_app_command=True mais sans "
                "app_command construit (probablement évincée par le budget slash, "
                "cogs/slash_command_budget.py — vérifier si c'est voulu) : "
                + ", ".join(sorted(missing_slash_should_exist))
            )

        print(f"Commandes hybrides restées + uniquement (with_app_command=False, jamais restaurées): {len(no_app_command)}")

        for warning in warnings:
            print(f"[WARN] {warning}")
        for error in errors:
            print(f"[ERROR] {error}")

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result

    if errors:
        print(f"ECHEC: {len(errors)} probleme(s) structurel(s) detecte(s)")
        return 1
    print("OK: aucune divergence callback slash/prefixe detectee sur les commandes hybrides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
