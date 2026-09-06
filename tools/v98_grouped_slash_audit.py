#!/usr/bin/env python3
"""Audit structurel complet de la surface slash groupée SentriX V98.

Ce gate charge le même registre de commandes que Railway, construit la surface V95/V97/V98
sans contacter Discord puis vérifie TOUTES les familles, pas uniquement quelques exemples.
Il ne déclenche aucune action métier destructive.
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


REQUIRED_ROOTS = {
    "ai", "economy", "levels", "games", "music", "ticket", "moderation",
    "security", "config", "server", "roles", "sentrix",
}
# Racines spéciales qui ne sont créées que si les commandes correspondantes existent dans le
# registre historique de cette release. Elles sont auditées si présentes, mais leur absence
# n'est pas artificiellement transformée en fonctionnalité.
OPTIONAL_SPECIAL_ROOTS = {"giveaway", "invites", "notifications", "events", "social", "info", "utility", "embeds", "stats", "owner", "more"}
FORBIDDEN_USER_PARAMS = {"ctx", "context", "self", "args", "kwargs"}


def _walk_app(command, prefix: str = ""):
    name = getattr(command, "name", "")
    path = f"{prefix} {name}".strip()
    children = list(getattr(command, "commands", ()) or ())
    if children:
        for child in children:
            yield from _walk_app(child, path)
    else:
        yield path, command


async def run() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-v98-slash-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-v98.db")

        import main
        import sentrix_v95_runtime as v95
        import sentrix_v98_runtime as v98

        bot = main.BotAllInOne()
        await bot.db.connect()

        loaded = []
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        if len(loaded) != len(main.EXTENSIONS):
            errors.append(f"extensions chargées: {len(loaded)}/{len(main.EXTENSIONS)}")

        # Reproduit l'ordre produit : V97 est installé dans V98, puis V98 entoure prepare_bot.
        v98.install()
        try:
            mapping = await v95.prepare_bot(bot)
        except Exception as exc:
            errors.append(f"construction V98 impossible: {type(exc).__name__}: {exc}")
            mapping = {}

        roots = list(bot.tree.get_commands(guild=None))
        root_names = {str(item.name).casefold() for item in roots}
        if len(roots) > v95.MAX_ROOT_COMMANDS:
            errors.append(f"budget racines dépassé: {len(roots)}/{v95.MAX_ROOT_COMMANDS}")
        missing_roots = sorted(REQUIRED_ROOTS - root_names)
        if missing_roots:
            errors.append("familles slash essentielles absentes: " + ", ".join(missing_roots))

        leaves: dict[str, object] = {}
        for root in roots:
            for raw_path, leaf in _walk_app(root):
                path = "/" + raw_path
                if path in leaves:
                    errors.append(f"chemin slash dupliqué: {path}")
                leaves[path] = leaf

                callback = getattr(leaf, "callback", None)
                if callback is None or not inspect.iscoroutinefunction(callback):
                    errors.append(f"callback slash invalide: {path}")
                    continue
                try:
                    sig = inspect.signature(callback)
                except Exception as exc:
                    errors.append(f"signature slash illisible {path}: {type(exc).__name__}: {exc}")
                    continue
                exposed = {name.casefold() for name in sig.parameters if name.casefold() != "interaction"}
                leaked = sorted(exposed & FORBIDDEN_USER_PARAMS)
                if leaked:
                    errors.append(f"paramètre interne exposé {path}: {', '.join(leaked)}")

        # La mapping V95 est la preuve que chaque leaf dynamique pointe vers une vraie commande
        # historique. Les callbacks synthétiques explicites (ex. /ai enable) sont volontairement
        # en plus de ce mapping et sont contrôlés séparément ci-dessous.
        if len(mapping) < 300:
            errors.append(f"inventaire slash anormalement petit: {len(mapping)} (<300)")
        missing_mapped_paths = sorted(path for path in mapping if path not in leaves)
        if missing_mapped_paths:
            errors.append(
                f"{len(missing_mapped_paths)} chemin(s) mappé(s) absent(s) de l'arbre: "
                + ", ".join(missing_mapped_paths[:20])
            )

        historical_by_name = {str(cmd.qualified_name).casefold(): cmd for cmd in bot.walk_commands()}
        unresolved = []
        for path, meta in mapping.items():
            original = str(meta.get("original") or "").casefold()
            if original not in historical_by_name:
                unresolved.append(f"{path}->{original}")
        if unresolved:
            errors.append(
                f"{len(unresolved)} slash sans commande historique résoluble: "
                + ", ".join(unresolved[:20])
            )

        # Toutes les commandes historiques destinées à être exposées doivent apparaître une
        # fois dans le mapping. Cela audite automatiquement logs/automod/roles/levels/economy/
        # giveaway/games/notifications/server/emoji/image/music/sentrix et les autres familles.
        targets = v95._build_targets(bot)
        expected_originals = {target.original_name.casefold() for target in targets}
        mapped_originals = {str(meta.get("original") or "").casefold() for meta in mapping.values()}
        missing_originals = sorted(expected_originals - mapped_originals)
        extra_originals = sorted(mapped_originals - expected_originals)
        if missing_originals:
            errors.append(
                f"{len(missing_originals)} commande(s) historiques non exposée(s): "
                + ", ".join(missing_originals[:30])
            )
        if extra_originals:
            errors.append(
                f"{len(extra_originals)} mapping(s) sans cible attendue: "
                + ", ".join(extra_originals[:30])
            )

        # Le bridge commun est le cœur de toutes les familles : il doit passer par Bot.invoke.
        source = inspect.getsource(v98._invoke_original)
        if "await bot.invoke(ctx)" not in source or "await root.invoke(ctx)" in source:
            errors.append("bridge V98: les slash ne passent pas exclusivement par Bot.invoke")

        # Contrats utilisateur observés dans les captures.
        ai_group = bot.tree.get_command("ai")
        ai_names = {child.name for child in getattr(ai_group, "commands", ())} if ai_group else set()
        required_ai = {"ask", "translate", "enable", "disable", "search", "reset", "memory", "model", "help"}
        missing_ai = sorted(required_ai - ai_names)
        if missing_ai:
            errors.append("sous-commandes /ai absentes: " + ", ".join(missing_ai))
        if "ai" in ai_names:
            errors.append("ancienne sous-commande ambiguë /ai ai encore visible")

        setup = bot.tree.get_command("setup")
        if setup is None:
            errors.append("/setup absent après préparation V98")
        else:
            try:
                setup_params = set(inspect.signature(setup.callback).parameters)
            except Exception:
                setup_params = set()
            if setup_params & FORBIDDEN_USER_PARAMS:
                errors.append("/setup expose encore ctx/args/kwargs")

        # Les wrappers V17 peuvent garder *args/**kwargs en interne uniquement si leur
        # commande expose finalement une signature utilisateur propre.
        polluted = []
        for command in bot.walk_commands():
            try:
                params = list(command.clean_params)
            except Exception:
                continue
            leaked = [name for name in params if name.casefold() in FORBIDDEN_USER_PARAMS]
            if leaked:
                polluted.append(f"{command.qualified_name}:{','.join(leaked)}")
        if polluted:
            errors.append(
                f"{len(polluted)} commande(s) historiques avec paramètre interne visible: "
                + ", ".join(polluted[:30])
            )

        present_optional = sorted(root_names & OPTIONAL_SPECIAL_ROOTS)
        print(f"V98 audit: {len(loaded)}/{len(main.EXTENSIONS)} extensions chargées")
        print(f"V98 audit: {len(mapping)} actions historiques mappées")
        print(f"V98 audit: {len(roots)} racines /, {len(leaves)} feuilles slash")
        print("V98 audit: familles spéciales présentes=" + ",".join(present_optional))
        for warning in warnings:
            print("[WARN]", warning)
        for error in errors:
            print("[ERROR]", error)

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close = getattr(bot.db, "close", None)
        if close:
            result = close()
            if inspect.isawaitable(result):
                await result

    if errors:
        print(f"ECHEC V98: {len(errors)} problème(s)")
        return 1
    print("OK V98: toutes les familles slash sont structurellement reliées au runtime commun")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
