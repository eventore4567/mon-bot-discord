#!/usr/bin/env python3
"""Audit runtime du registre de commandes SentriX sans se connecter à Discord.

Le test charge la vraie base temporaire et les vraies extensions comme en production, puis
inspecte toutes les commandes réellement enregistrées. Il ne lance volontairement aucune
sanction/ticket/écriture sur un vrai serveur Discord : ces actions nécessitent un contexte
Discord réel et ne doivent jamais être simulées sur la production depuis la CI.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile
from collections import Counter


# Lorsqu'un script est lancé avec `python tools/xxx.py`, Python met `tools/` en tête du
# sys.path et non la racine du dépôt. On ajoute explicitement la racine pour importer
# exactement le même `main.py`, `cogs/`, `database/` et `utils/` que la production.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CRITICAL_COMMANDS = {
    "help",
    "ping",
    "setup",
    "ticket",
    "ban",
    "mute",
    "warn",
    "bl",
    "giveaway-create",
    "guess-number",
    "ai",
    "play",
    "rolepanel",
}


async def run() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-command-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ci.db")

        import main
        from cogs import (
            command_catalog_cleanup,
            command_response_guard,
            help_category_rework,
            help_complete,
        )

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded: list[str] = []
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:  # CI doit afficher le module précis qui casse.
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        if len(loaded) != len(main.EXTENSIONS):
            errors.append(
                f"extensions chargées: {len(loaded)}/{len(main.EXTENSIONS)}"
            )

        if not command_catalog_cleanup._INSTALLED:
            errors.append("la politique de catalogue complet des commandes n'est pas installée")

        expected_pruned = command_catalog_cleanup.CONFIRMED_DUPLICATE_COMMANDS
        if main.PRUNED_COMMANDS != expected_pruned:
            errors.append(
                "politique de pruning inattendue: "
                + ", ".join(sorted(main.PRUNED_COMMANDS ^ expected_pruned))
            )

        # Reproduit le nettoyage effectué par setup_hook avant la synchro des slash.
        bot._prune_redundant_commands()

        active = list(bot.walk_commands())
        qualified = [command.qualified_name.casefold() for command in active]
        if not active:
            errors.append("aucune commande enregistrée")
        if len(qualified) != len(set(qualified)):
            duplicates = sorted({name for name in qualified if qualified.count(name) > 1})
            errors.append("commandes dupliquées: " + ", ".join(duplicates))

        for command in active:
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(
                    f"callback non asynchrone/invalide: {command.qualified_name}"
                )
            try:
                _ = command.signature
            except Exception as exc:
                errors.append(
                    f"signature impossible pour {command.qualified_name}: {type(exc).__name__}: {exc}"
                )

        missing_critical = sorted(
            name for name in CRITICAL_COMMANDS if bot.get_command(name) is None
        )
        if missing_critical:
            errors.append(
                "commandes critiques absentes: " + ", ".join(missing_critical)
            )

        restored_missing = sorted(
            name
            for name in command_catalog_cleanup.RESTORED_COMMANDS
            if bot.get_command(name) is None
        )
        if restored_missing:
            errors.append(
                "commandes utiles censées être restaurées mais absentes: "
                + ", ".join(restored_missing)
            )

        pruned_still_visible = sorted(
            name for name in main.PRUNED_COMMANDS if bot.get_command(name) is not None
        )
        if pruned_still_visible:
            errors.append(
                "commandes censées être retirées encore visibles: "
                + ", ".join(pruned_still_visible)
            )

        registered_roots = {command.name.casefold() for command in bot.commands}
        unknown_permissions = sorted(registered_roots - main.KNOWN_PERMISSION_COMMANDS)
        if unknown_permissions:
            # La production les bloque déjà en fail-closed. On les signale sans casser la
            # CI pour permettre une décision explicite sur leur niveau d'accès ensuite.
            warnings.append(
                "commandes protégées par fail-closed à classifier: "
                + ", ".join(unknown_permissions)
            )

        if not command_response_guard._INSTALLED:
            errors.append("le filet de sécurité de réponse des commandes n'est pas installé")

        # Le système qualité doit couvrir commandes préfixées ET slash : départ,
        # completion, erreurs et interactions. Une régression d'un listener casse la CI.
        required_listeners = {
            "on_command": "mesure de départ des commandes +",
            "on_command_completion": "réponse/mesure de fin des commandes +",
            "on_command_error": "suggestions et diagnostic d'erreur des commandes +",
            "on_interaction": "mesure de départ des commandes slash",
            "on_app_command_completion": "réponse/mesure de fin des commandes slash",
        }
        for event_name, label in required_listeners.items():
            if not bot.extra_events.get(event_name, []):
                errors.append(f"listener absent: {label} ({event_name})")

        # Garantie demandée : TOUTE commande visible, y compris les sous-commandes, doit
        # participer au correcteur de fautes. On simule une faute simple en ajoutant un
        # caractère : le nom canonique doit rester dans les 3 suggestions.
        suggestion_failures: list[str] = []
        suggestion_covered = 0
        for command in active:
            if getattr(command, "hidden", False):
                continue
            canonical = str(command.qualified_name).strip()
            if not canonical:
                continue
            suggestion_covered += 1
            typo = canonical + "x"
            suggestions = command_response_guard._command_suggestions(bot, typo)
            if canonical not in suggestions:
                suggestion_failures.append(
                    f"{canonical} -> {typo!r} => {suggestions!r}"
                )
        if suggestion_failures:
            errors.append(
                "correcteur de fautes incomplet pour certaines commandes: "
                + " ; ".join(suggestion_failures[:20])
            )

        typo_suggestions = command_response_guard._command_suggestions(bot, "hlep")
        if "help" not in typo_suggestions:
            errors.append(
                "la récupération de faute ne propose pas +help pour la saisie 'hlep'"
            )

        app_commands = list(bot.tree.walk_commands())
        app_names = [command.qualified_name.casefold() for command in app_commands]
        if len(app_names) != len(set(app_names)):
            duplicates = sorted({name for name in app_names if app_names.count(name) > 1})
            errors.append("commandes slash dupliquées: " + ", ".join(duplicates))

        # L'aide doit utiliser le rework canonique, et aucune commande active ne doit
        # retomber dans « Autres commandes ». Ainsi une future commande oubliée casse la
        # CI immédiatement au lieu d'apparaître dans une mauvaise rubrique sur Discord.
        if not help_category_rework._INSTALLED:
            errors.append("le rework des catégories +help n'est pas installé")

        category_counts: Counter[str] = Counter()
        uncategorized: list[str] = []
        for command in active:
            category = help_complete._category_for(command)
            category_counts[category.key] += 1
            if category.key == "other":
                cog = getattr(command, "cog", None)
                cog_name = getattr(cog, "qualified_name", "Sans cog") if cog else "Sans cog"
                uncategorized.append(f"{command.qualified_name} [{cog_name}]")
        if uncategorized:
            errors.append(
                "commandes sans catégorie logique: " + ", ".join(sorted(uncategorized))
            )

        print(f"SentriX command runtime audit: {len(active)} commande(s) texte/hybride")
        print(f"SentriX command runtime audit: {len(app_commands)} commande(s) slash enregistrée(s)")
        print(f"Extensions: {len(loaded)}/{len(main.EXTENSIONS)} chargées")
        print(
            "Catalogue: "
            f"{len(command_catalog_cleanup.RESTORED_COMMANDS)} commandes utiles garanties, "
            f"{len(command_catalog_cleanup.CONFIRMED_DUPLICATE_COMMANDS)} doublons retirés"
        )
        print(f"Correcteur de fautes: {suggestion_covered} commande(s) visible(s) couvertes")
        print("UX commandes: réponses garanties + diagnostic de latence préfixe/slash actifs")
        print("Catégories +help:")
        for category in help_complete.CATEGORIES:
            count = category_counts.get(category.key, 0)
            if count:
                print(f"  {category.key}: {count}")
        print("Commandes actives:")
        for name in sorted(command.qualified_name for command in active):
            print(f"  + {name}")
        for warning in warnings:
            print(f"[WARN] {warning}")
        for error in errors:
            print(f"[ERROR] {error}")

        # Plusieurs patches lancent des tâches de bootstrap qui attendent on_ready().
        # Elles sont annulées proprement puisque la CI ne se connecte jamais à Discord.
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
        print(f"ECHEC: {len(errors)} problème(s) détecté(s)")
        return 1
    print("OK: toutes les commandes actives sont chargées, classées, couvertes par le correcteur et protégées par les garde-fous UX")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
