#!/usr/bin/env python3
"""Audit statique rapide du code actif SentriX.

Vérifie les erreurs qui peuvent casser un déploiement ou affaiblir sa sécurité avant
même de lancer Discord : syntaxe Python, extensions/imports cassés, limites Discord,
emojis de composants invalides, appels bloquants, secrets écrits en dur et primitives
d'exécution particulièrement dangereuses.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("cogs", "database", "utils", "web", "tools")
ROOT_FILES = ("main.py", "config.py")

errors: list[str] = []
warnings: list[str] = []
checked = 0

# Discord refuse certains glyphes décoratifs lorsqu'ils sont envoyés dans le champ
# `emoji` d'un composant, même s'ils sont parfaitement valides dans un label.
INVALID_COMPONENT_EMOJI_LITERALS = frozenset({"○"})

# Motifs suffisamment spécifiques pour bloquer une fuite évidente sans signaler les noms
# de variables comme OPENAI_API_KEY. Les placeholders volontairement courts ne matchent pas.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("clé OpenAI", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("token GitHub classique", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("token GitHub fin-grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("clé privée PEM", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

SENSITIVE_NAME_PARTS = ("token", "secret", "api_key", "apikey", "password", "passwd")
SAFE_LITERAL_VALUES = {
    "", "none", "null", "changeme", "change-me", "your-token", "your-secret",
    "example", "placeholder", "ci.fake.token",
}


def source_files() -> list[pathlib.Path]:
    files = [ROOT / name for name in ROOT_FILES]
    for folder in SOURCE_DIRS:
        base = ROOT / folder
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(set(files))


def literal_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def literal_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def call_name(node: ast.Call) -> str:
    parts: list[str] = []
    cur: ast.AST | None = node.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def check_decorator_limits(path: pathlib.Path, tree: ast.AST) -> None:
    command_suffixes = (
        "commands.command", "commands.hybrid_command", "commands.group",
        "commands.hybrid_group", "app_commands.command",
    )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorators = [dec for dec in node.decorator_list if isinstance(dec, ast.Call)]
        # Une hybrid command explicitement prefix-only n'est jamais envoyée à l'API slash.
        slash_disabled = False
        for dec in decorators:
            name = call_name(dec)
            if not any(name.endswith(suffix) for suffix in command_suffixes):
                continue
            for kw in dec.keywords:
                if kw.arg == "with_app_command" and literal_bool(kw.value) is False:
                    slash_disabled = True

        for dec in decorators:
            name = call_name(dec)
            if not slash_disabled and any(name.endswith(suffix) for suffix in command_suffixes):
                for kw in dec.keywords:
                    if kw.arg == "description":
                        value = literal_str(kw.value)
                        if value is not None and len(value) > 100:
                            errors.append(
                                f"{path.relative_to(ROOT)}:{node.lineno}: description slash >100 caractères ({len(value)})"
                            )
            if not slash_disabled and name.endswith("app_commands.describe"):
                for kw in dec.keywords:
                    value = literal_str(kw.value)
                    if value is not None and len(value) > 100:
                        errors.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: description du paramètre '{kw.arg}' >100 caractères ({len(value)})"
                        )


def check_component_emoji_literals(path: pathlib.Path, tree: ast.AST) -> None:
    """Bloque les glyphes déjà connus pour faire rejeter un composant par Discord."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if not (
            name.endswith("discord.ui.button")
            or name.endswith("ui.button")
            or name.endswith("discord.ui.Button")
            or name.endswith("ui.Button")
        ):
            continue
        for kw in node.keywords:
            if kw.arg != "emoji":
                continue
            value = literal_str(kw.value)
            if value in INVALID_COMPONENT_EMOJI_LITERALS:
                hits.append((node.lineno, value))

    relative = path.relative_to(ROOT).as_posix()
    # Compatibilité historique +embed : le runtime le remplace et un test construit la vue.
    if relative == "cogs/embed_builder.py" and len(hits) == 1 and hits[0][1] == "○":
        warnings.append(
            "cogs/embed_builder.py: ancien emoji ○ toléré uniquement car le correctif runtime + test UI le remplace par ❌"
        )
        return

    for lineno, value in hits:
        errors.append(
            f"{relative}:{lineno}: emoji de composant Discord invalide connu: {value!r}"
        )


def check_async_blocking_sleep(path: pathlib.Path, tree: ast.AST) -> None:
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and call_name(node) == "time.sleep":
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: time.sleep() bloque asyncio dans '{fn.name}'"
                )


def check_hardcoded_secrets(path: pathlib.Path, text: str, tree: ast.AST) -> None:
    """Refuse les secrets évidents dans le dépôt sans confondre variables d'environnement."""
    relative = path.relative_to(ROOT)
    for label, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            lineno = text[:match.start()].count("\n") + 1
            errors.append(f"{relative}:{lineno}: {label} potentiellement écrit(e) en dur")

    # Attrape aussi `DISCORD_TOKEN = "vraie valeur"` même si son format change un jour.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value_node = node.value
        value = literal_str(value_node)
        if value is None:
            continue
        normalized_value = value.strip().casefold()
        if normalized_value in SAFE_LITERAL_VALUES or len(value.strip()) < 12:
            continue

        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            variable = target.id.casefold()
            if any(part in variable for part in SENSITIVE_NAME_PARTS):
                errors.append(
                    f"{relative}:{node.lineno}: secret potentiel écrit en dur dans {target.id}; utilisez une variable d'environnement"
                )


def check_dangerous_execution(path: pathlib.Path, tree: ast.AST) -> None:
    """Bloque quelques primitives à haut risque qui n'ont aucune raison d'être dans SentriX."""
    relative = path.relative_to(ROOT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name in {"eval", "exec"}:
            errors.append(f"{relative}:{node.lineno}: appel dangereux interdit: {name}()")

        if name in {
            "subprocess.run", "subprocess.Popen", "subprocess.call",
            "subprocess.check_call", "subprocess.check_output",
        }:
            for keyword in node.keywords:
                if keyword.arg == "shell" and literal_bool(keyword.value) is True:
                    errors.append(f"{relative}:{node.lineno}: subprocess avec shell=True interdit")

        # Désactiver TLS transforme une requête HTTPS en cible MITM.
        if name.endswith("requests.get") or name.endswith("requests.post") or name.endswith("requests.request"):
            for keyword in node.keywords:
                if keyword.arg == "verify" and literal_bool(keyword.value) is False:
                    errors.append(f"{relative}:{node.lineno}: vérification TLS désactivée (verify=False)")


def parse_main_extensions() -> None:
    main_path = ROOT / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    extensions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXTENSIONS" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                extensions = [v.value for v in node.value.elts if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            break
    if not extensions:
        errors.append("main.py: impossible de lire EXTENSIONS")
        return
    for module in extensions:
        candidate = ROOT / (module.replace(".", "/") + ".py")
        package = ROOT / module.replace(".", "/") / "__init__.py"
        if not candidate.exists() and not package.exists():
            errors.append(f"main.py: extension introuvable: {module}")


def check_cogs_relative_imports() -> None:
    init_path = ROOT / "cogs" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            candidate = ROOT / "cogs" / (node.module.replace(".", "/") + ".py")
            package = ROOT / "cogs" / node.module.replace(".", "/") / "__init__.py"
            if not candidate.exists() and not package.exists():
                errors.append(f"cogs/__init__.py:{node.lineno}: import relatif introuvable: .{node.module}")


def check_obvious_conflict_markers(path: pathlib.Path, text: str) -> None:
    # Un vrai conflit Git occupe le début d'une ligne. Les séparateurs décoratifs
    # "# ======" utilisés dans le code ne doivent jamais être signalés.
    match = re.search(r"(?m)^(?:<<<<<<< .+|=======|>>>>>>> .+)$", text)
    if match:
        errors.append(
            f"{path.relative_to(ROOT)}:{text[:match.start()].count(chr(10)) + 1}: marqueur de conflit Git détecté"
        )


def check_forbidden_local_secret_files() -> None:
    """Empêche un futur commit accidentel de fichiers secrets locaux classiques."""
    for name in (".env", "secrets.json", "credentials.json", "id_rsa", "id_ed25519"):
        if (ROOT / name).is_file():
            errors.append(f"fichier secret local suivi/interdit: {name}")
    for suffix in ("*.pem", "*.p12", "*.pfx"):
        for path in ROOT.glob(suffix):
            if path.is_file():
                errors.append(f"fichier de clé/certificat privé interdit: {path.name}")


def main() -> int:
    global checked
    for path in source_files():
        if not path.exists():
            errors.append(f"fichier requis manquant: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        check_obvious_conflict_markers(path, text)
        try:
            tree = ast.parse(text, filename=str(path))
            compile(tree, str(path), "exec")
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: syntaxe invalide: {exc}")
            continue
        checked += 1
        check_decorator_limits(path, tree)
        check_component_emoji_literals(path, tree)
        check_async_blocking_sleep(path, tree)
        check_hardcoded_secrets(path, text, tree)
        check_dangerous_execution(path, tree)

    try:
        parse_main_extensions()
        check_cogs_relative_imports()
        check_forbidden_local_secret_files()
    except Exception as exc:
        errors.append(f"audit structurel impossible: {type(exc).__name__}: {exc}")

    print(f"SentriX audit: {checked} fichier(s) Python vérifié(s)")
    for warning in warnings:
        print(f"[WARN] {warning}")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} problème(s) bloquant(s)")
        return 1
    print("OK: syntaxe, structure et garde-fous de sécurité statique validés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
