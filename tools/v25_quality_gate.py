#!/usr/bin/env python3
"""Quality gate V2.5 : stabilité, UX, sécurité et contrats de commandes SentriX.

Le but est de bloquer AVANT production les régressions déjà vues : paramètres ``ctx``
exposés, +gamble qui refuse un entier valide, slash absent/cassé, cooldowns sans retour,
perte des protections économie/tickets/IA et réintroduction de patchs obsolètes.
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

INTERNAL = {"ctx", "context", "interaction", "self", "cog", "_ctx"}
CRITICAL_CONTRACTS = {
    "gamble": ("montant",),
    "pay": ("membre", "montant"),
    "balance": ("membre",),
    "deposit": ("montant",),
    "withdraw": ("montant",),
    "rps": ("choix",),
    "ban": ("membre", "raison"),
    "kick": ("membre", "raison"),
    "mute": ("membre", "duree", "raison"),
    "tempban": ("membre", "duree", "raison"),
}


def _annotation_is_int(value) -> bool:
    return value is int or str(value).strip() in {"int", "<class 'int'>"}


def _static_checks(errors: list[str]) -> None:
    hygiene_path = ROOT / "cogs" / "user_facing_hygiene.py"
    integrity_path = ROOT / "cogs" / "integrity_hardening.py"
    ai_path = ROOT / "cogs" / "sentrix_intelligent_ux.py"
    response_path = ROOT / "cogs" / "command_response_guard.py"
    minigames_path = ROOT / "cogs" / "minigames.py"
    quality_path = ROOT / "cogs" / "runtime_quality_v25.py"

    for path in (hygiene_path, integrity_path, ai_path, response_path, minigames_path, quality_path):
        if not path.exists():
            errors.append(f"fichier requis absent: {path.relative_to(ROOT)}")

    if hygiene_path.exists():
        text = hygiene_path.read_text(encoding="utf-8")
        if "gamble_parser_fix" in text:
            errors.append("ancien module gamble_parser_fix encore référencé")
        if "_sanitize_registered_commands" in text:
            errors.append("ancienne mutation globale des signatures encore présente")
        for marker in (
            "_patch_prefix_error_ux",
            "_patch_slash_error_ux",
            "Cooldown actif",
            "_repair_gamble_parser",
            "runtime_quality_v25.install(bot)",
        ):
            if marker not in text:
                errors.append(f"garantie UX V2.5 absente: {marker}")

    obsolete = ROOT / "cogs" / "gamble_parser_fix.py"
    if obsolete.exists():
        errors.append("cogs/gamble_parser_fix.py doit rester supprimé (consolidé dans l'UX globale)")

    if integrity_path.exists():
        text = integrity_path.read_text(encoding="utf-8")
        for marker in (
            "_economy_lock",
            "AND quantity>=1",
            "AND cash>=?",
            "AND bank>=?",
            "_ticket_staff_allowed",
            "_ExpiringPlayLockRegistry",
        ):
            if marker not in text:
                errors.append(f"protection intégrité absente: {marker}")

    if ai_path.exists():
        text = ai_path.read_text(encoding="utf-8")
        for marker in (
            "_claim_natural_message",
            "_message_is_claimed",
            "_install_primary_ai_listener_guard",
        ):
            if marker not in text:
                errors.append(f"protection anti-double-réponse IA absente: {marker}")

    if response_path.exists():
        text = response_path.read_text(encoding="utf-8")
        for marker in ("_SLOW_COMMAND_SECONDS", "Commande lente", "on_app_command_completion"):
            if marker not in text:
                errors.append(f"observabilité commandes absente: {marker}")

    if minigames_path.exists():
        text = minigames_path.read_text(encoding="utf-8")
        if "check_cooldown" not in text or "avant de rejouer" not in text:
            errors.append("mini-jeux : cooldown explicite au joueur absent")

    if quality_path.exists():
        text = quality_path.read_text(encoding="utf-8")
        if "_NEGATIVE_CREATOR_TTL" not in text:
            errors.append("cache négatif de performance absent")
        if "if result:" not in text or "return True" not in text:
            errors.append("le cache propriétaire doit conserver les résultats positifs hors cache")
        if '"new_commands": 0' not in text:
            errors.append("runtime_quality_v25 doit déclarer 0 nouvelle commande")


async def _runtime_checks(errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="sentrix-v25-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-v25.db")

        import main
        from cogs import command_catalog_cleanup, slash_command_budget, user_facing_hygiene
        from utils.v22_rules import parse_friendly_amount, parse_friendly_duration

        bot = main.BotAllInOne()
        await bot.db.connect()

        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
            except Exception as exc:
                errors.append(f"chargement {extension}: {type(exc).__name__}: {exc}")

        try:
            bot._prune_redundant_commands()
            command_catalog_cleanup.apply_surface(bot)
            slash_command_budget.finalize(bot)
            user_facing_hygiene.apply(bot)
        except Exception as exc:
            errors.append(f"finalisation runtime: {type(exc).__name__}: {exc}")

        active = list(bot.walk_commands())
        if not active:
            errors.append("aucune commande active")

        for command in active:
            callback = getattr(command, "callback", None)
            if callback is None or not inspect.iscoroutinefunction(callback):
                errors.append(f"callback invalide: {command.qualified_name}")
                continue

            try:
                clean = tuple(str(name) for name in command.clean_params)
                signature = str(command.signature or "")
            except Exception as exc:
                errors.append(f"signature invalide {command.qualified_name}: {type(exc).__name__}: {exc}")
                continue

            leaked = sorted({name.casefold() for name in clean} & INTERNAL)
            if leaked:
                errors.append(f"paramètre interne dans {command.qualified_name}: {', '.join(leaked)}")
            lowered_signature = signature.casefold()
            for token in INTERNAL:
                if f"<{token}>" in lowered_signature or f"[{token}]" in lowered_signature:
                    errors.append(f"signature utilisateur polluée {command.qualified_name}: {signature}")

        for name, expected in CRITICAL_CONTRACTS.items():
            command = bot.get_command(name)
            if command is None:
                errors.append(f"commande critique absente: {name}")
                continue
            actual = tuple(str(item) for item in command.clean_params)
            if actual != expected:
                errors.append(f"contrat {name}: {actual!r} au lieu de {expected!r}")

        gamble = bot.get_command("gamble")
        if gamble is not None:
            parameter = gamble.clean_params.get("montant")
            if parameter is None:
                errors.append("+gamble n'a plus de paramètre montant")
            elif not _annotation_is_int(parameter.annotation):
                errors.append(f"+gamble montant doit rester int, obtenu {parameter.annotation!r}")
            if "ctx" in user_facing_hygiene.visible_usage(gamble, "+").casefold():
                errors.append("+gamble affiche encore ctx dans sa syntaxe")

        # Le bot conserve volontairement beaucoup plus de commandes + que de racines slash :
        # Discord limite les commandes chat-input globales à 100. On vérifie donc uniquement
        # la surface slash canonique, pas toutes les commandes historiques préfixées.
        roots = {str(command.name).casefold() for command in bot.tree.get_commands()}
        if len(roots) > slash_command_budget.GLOBAL_CHAT_INPUT_BUDGET:
            errors.append(f"budget slash dépassé: {len(roots)}/100")
        for name in ("help", "balance", "rps", "ban", "mute"):
            if name not in roots:
                errors.append(f"commande slash critique absente: /{name}")

        amount_cases = {
            "10": 10,
            "1 500": 1500,
            "1.5k": 1500,
            "2m": 2_000_000,
        }
        for raw, expected in amount_cases.items():
            if parse_friendly_amount(raw) != expected:
                errors.append(f"parse montant {raw!r} incorrect")
        if parse_friendly_amount("-10") is not None:
            errors.append("un montant négatif ne doit jamais être accepté")
        if parse_friendly_duration("1h30m") != 5400:
            errors.append("durée 1h30m non comprise")
        if user_facing_hygiene._cooldown_text(65) != "1 min 5 s":
            errors.append("format cooldown 65s incorrect")

        creator_lookup = getattr(bot.db, "is_bot_creator", None)
        if not getattr(creator_lookup, "_sentrix_v25_negative_cache", False):
            errors.append("cache négatif is_bot_creator V2.5 non installé")

        integrity_state = getattr(bot, "_sentrix_integrity_install_state", {})
        for key in ("economy", "tickets", "games"):
            if not integrity_state.get(key):
                errors.append(f"protection intégrité runtime absente: {key}")

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


def main_sync() -> int:
    errors: list[str] = []
    _static_checks(errors)
    asyncio.run(_runtime_checks(errors))

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC V2.5: {len(errors)} régression(s) détectée(s)")
        return 1
    print("OK V2.5: commandes +/slash, cooldowns, UX, économie, tickets, IA et cache performance conformes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_sync())
