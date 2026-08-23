#!/usr/bin/env python3
"""Gate de non-régression A→Z pour le registre de commandes SentriX V18."""
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

_RESERVED = {"self", "ctx", "context", "interaction", "bot", "_bot"}
_REQUIRED_CREATE = ("create", "create sentrix", "create server", "create-server")


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-v18-gate-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-v18.db")

        import main
        from cogs import command_integrity_v18, command_runtime_hardening_v18

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded: list[str] = []
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:
                errors.append(
                    f"extension {extension} non chargee: {type(exc).__name__}: {exc}"
                )

        if len(loaded) != len(main.EXTENSIONS):
            errors.append(f"extensions chargees: {len(loaded)}/{len(main.EXTENSIONS)}")

        # Reproduit le nettoyage de setup_hook avant l'audit final.
        bot._prune_redundant_commands()

        # Réapplique explicitement la couche finale afin que ce gate reste utile même si
        # l'ordre de bootstrap change plus tard.
        command_runtime_hardening_v18.install(bot, "ci-final")
        command_integrity_v18.install(bot, "ci-final")

        report = dict(
            getattr(bot, "_sentrix_command_integrity_v18", {}).get("last_report", {})
        )
        for item in report.get("critical", ()):
            errors.append(f"V18 critique: {item}")

        active = list(bot.walk_commands())
        if not active:
            errors.append("aucune commande texte/hybride active")

        # Aucune commande ne doit exposer des paramètres internes à l'utilisateur.
        for command in active:
            name = str(command.qualified_name)
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(f"callback non async: {name}")
            try:
                clean_params = dict(command.clean_params)
            except Exception as exc:
                errors.append(f"signature illisible {name}: {type(exc).__name__}: {exc}")
                continue
            leaked = sorted(param for param in clean_params if param.casefold() in _RESERVED)
            if leaked:
                errors.append(f"parametre interne expose {name}: {', '.join(leaked)}")

        # Les quatre routes create qui ont déjà régressé doivent être présentes ensemble.
        for qualified in _REQUIRED_CREATE:
            if bot.get_command(qualified) is None:
                errors.append(f"commande create essentielle absente: {qualified}")

        create_root = bot.get_command("create")
        if not isinstance(create_root, __import__("discord.ext.commands", fromlist=["Group"]).Group):
            errors.append("+create n'est plus un groupe discord.py")
        else:
            child_names = {child.name.casefold() for child in create_root.commands}
            if not {"sentrix", "server"} <= child_names:
                errors.append(
                    "+create incomplet: sous-commandes attendues sentrix/server absentes"
                )

        # Le verrou global de main décide sur la RACINE d'un groupe : create doit donc
        # appartenir à la catégorie configuration, sinon les gestionnaires configurateurs
        # sont refusés même si la sous-commande possède son propre check.
        configuration = set(main.CATEGORY_COMMANDS.get("configuration", ()))
        if "create" not in configuration:
            errors.append("racine create absente de CATEGORY_COMMANDS[configuration]")

        # Une vraie commande canonique ne doit jamais être masquée par l'alias d'une autre.
        root_canonical = {
            str(command.name).casefold(): command for command in bot.commands
        }
        for command in bot.commands:
            for alias in getattr(command, "aliases", ()):
                real = root_canonical.get(str(alias).casefold())
                if real is not None and real is not command:
                    errors.append(
                        f"alias racine {alias} de {command.qualified_name} masque {real.qualified_name}"
                    )

        for group in [item for item in active if hasattr(item, "all_commands") and hasattr(item, "commands")]:
            children = {
                str(child.name).casefold(): child
                for child in getattr(group, "commands", ())
            }
            for child in getattr(group, "commands", ()):
                for alias in getattr(child, "aliases", ()):
                    real = children.get(str(alias).casefold())
                    if real is not None and real is not child:
                        errors.append(
                            f"alias {alias} de {child.qualified_name} masque {real.qualified_name}"
                        )

        # Le générateur d'alias à chaud de V16 doit rester neutralisé.
        from cogs import bot_v16_commands
        dynamic_aliases = getattr(bot_v16_commands, "_register_compact_aliases", None)
        if dynamic_aliases is None or not getattr(dynamic_aliases, "_sentrix_v18_disabled", False):
            errors.append("generateur d'alias dynamiques V16 encore actif")

        # Slash : noms uniques et budget Discord global respecté.
        app_roots = list(bot.tree.get_commands())
        app_names = [str(item.name).casefold() for item in app_roots]
        if len(app_names) != len(set(app_names)):
            errors.append("racines slash dupliquees")
        if len(app_roots) > 100:
            errors.append(f"budget slash depasse: {len(app_roots)}/100")

        print(
            "SentriX V18 gate: "
            f"{len(active)} commandes texte/hybrides, "
            f"{len(app_roots)} racines slash, "
            f"{len(loaded)}/{len(main.EXTENSIONS)} extensions chargees"
        )
        if report:
            print(
                "V18 report: "
                f"groupes={report.get('groups', 0)}, "
                f"alias={report.get('aliases', 0)}, "
                f"collisions_reparees={report.get('repaired_alias_collisions', 0)}, "
                f"alias_v16_retires={report.get('removed_v16_aliases', 0)}"
            )

        for error in errors:
            print(f"[ERROR] {error}")

        current = asyncio.current_task()
        pending = [
            task for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        close_db = getattr(bot.db, "close", None)
        if callable(close_db):
            result = close_db()
            if inspect.isawaitable(result):
                await result

    if errors:
        print(f"ECHEC V18: {len(errors)} regression(s) de commande detectee(s)")
        return 1
    print("OK V18: registre, signatures, create, alias, permissions et slash coherents")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
