#!/usr/bin/env python3
"""Vérifie qu'une commande inconnue ne peut recevoir qu'une seule réponse SentriX.

Le bug historique +hyelp envoyait deux embeds parce que deux couches différentes traitaient
CommandNotFound. Ce gate analyse toutes les branches Python qui testent CommandNotFound et
refuse qu'une deuxième branche envoie directement une réponse Discord.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_OWNER = pathlib.Path("sentrix_product_update.py")


def _is_command_not_found_test(node: ast.AST) -> bool:
    try:
        text = ast.unparse(node)
    except Exception:
        return False
    return "CommandNotFound" in text


def _call_name(call: ast.Call) -> str:
    try:
        return ast.unparse(call.func)
    except Exception:
        return ""


def _body_sends_reply(body: list[ast.stmt]) -> bool:
    wrapper = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(wrapper):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name.endswith(".send") or name.endswith(".send_message") or name.endswith(".followup.send"):
            return True
        if name in {"_safe_send", "safe_send"}:
            return True
    return False


def main() -> int:
    responders: list[tuple[pathlib.Path, int]] = []
    delegates: list[tuple[pathlib.Path, int]] = []
    parse_errors: list[str] = []

    for path in ROOT.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            parse_errors.append(f"{path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or not _is_command_not_found_test(node.test):
                continue
            relative = path.relative_to(ROOT)
            if _body_sends_reply(node.body):
                responders.append((relative, int(getattr(node, "lineno", 0))))
            else:
                delegates.append((relative, int(getattr(node, "lineno", 0))))

    errors = list(parse_errors)
    # L'autorité finale est sentrix_product_update : elle est volontairement
    # installée après les couches historiques, garde une seule réponse et réutilise
    # le filtre de suggestions de command_response_guard.
    canonical = ROOT / EXPECTED_OWNER
    canonical_text = canonical.read_text(encoding="utf-8") if canonical.exists() else ""
    # Politique actuelle : CommandNotFound ne répond plus dans le salon.
    # L'ancien test exigeait encore await _plain_send(...), abandonné pour
    # éviter le spam. Vérifier sur l'AST que la branche est un retour silencieux.
    canonical_tree = ast.parse(canonical_text)
    silent_guards = []
    for candidate in ast.walk(canonical_tree):
        if not isinstance(candidate, ast.AsyncFunctionDef) or candidate.name != "exact_error":
            continue
        for condition in candidate.body:
            if not isinstance(condition, ast.If) or not _is_command_not_found_test(condition.test):
                continue
            returns_none = (
                len(condition.body) == 1
                and isinstance(condition.body[0], ast.Return)
                and (
                    condition.body[0].value is None
                    or (
                        isinstance(condition.body[0].value, ast.Constant)
                        and condition.body[0].value.value is None
                    )
                )
            )
            silent_guards.append(returns_none)
    canonical_owns = (
        silent_guards == [True]
        and "bot.on_command_error = MethodType(exact_error, bot)" in canonical_text
    )
    foreign = [(path, line) for path, line in responders if path != EXPECTED_OWNER]
    if not canonical_owns:
        errors.append("sentrix_product_update ne garantit plus le silence de CommandNotFound")
    if foreign:
        rendered = ", ".join(f"{path}:{line}" for path, line in foreign)
        errors.append(f"répondant CommandNotFound concurrent détecté: {rendered}")

    guard = ROOT / "cogs/command_response_guard.py"
    if guard.exists():
        text = guard.read_text(encoding="utf-8")
        if "command_response_guard._command_suggestions(bot, ctx, typed)" not in canonical_text:
            errors.append("les suggestions de commandes inconnues ne passent plus par le filtre de permissions")
        if "_can_suggest_command" not in text:
            errors.append("le filtre de permissions des suggestions est absent")
    else:
        errors.append(f"fichier propriétaire absent: {EXPECTED_OWNER}")

    for path, line in delegates:
        print(f"[DELEGATE] {path}:{line}")
    for path, line in responders:
        print(f"[OWNER] {path}:{line}")
    for error in errors:
        print(f"[ERROR] {error}")

    if errors:
        print(f"ECHEC OWNERSHIP ERREURS: {len(errors)} problème(s)")
        return 1

    print("OK OWNERSHIP ERREURS: une seule réponse CommandNotFound, suggestions filtrées par permissions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
