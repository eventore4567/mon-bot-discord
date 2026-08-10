"""Verification MECANIQUE de la regle "aucun SET persistant".

La discipline ne suffit pas : ce test scanne le depot et echoue si du code pose
le contexte tenant hors de libs/db, ou utilise un SET persistant. C'est ce qui
empeche un futur refactor de reintroduire silencieusement la faille de fuite de
contexte via PgBouncer en mode transaction.

Deux precautions de conception de ce test, apprises en le faisant echouer :

1. On analyse l'AST et on IGNORE LES DOCSTRINGS. Sans ca, la documentation qui
   explique la regle ("ne pas ecrire SET app.current_org") declenche elle-meme
   l'alerte - un test qui punit le fait de documenter sa propre regle.

2. Le troisieme argument de set_config est CAPTURE puis compare, au lieu d'un
   lookahead `,\\s*(?!true)`. Ce lookahead est piegeux : `\\s*` retrograde
   jusqu'a zero espace, le lookahead se retrouve devant une espace, ne voit pas
   "true", et signale une violation sur du code parfaitement correct.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_MODULE = ROOT / "libs" / "db" / "__init__.py"

SCANNED_DIRS = ("libs", "services", "agents")

PERSISTENT_SET = re.compile(r"\bSET\s+app\.current_org", re.IGNORECASE)
SET_CONFIG_CALL = re.compile(
    r"set_config\s*\(\s*['\"]app\.current_org['\"]\s*,(?P<value>[^,]+),(?P<local>[^)]+)\)",
    re.IGNORECASE,
)
ANY_TENANT_GUC = re.compile(r"app\.current_org", re.IGNORECASE)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCANNED_DIRS:
        base = ROOT / directory
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _executable_strings(path: Path) -> list[tuple[int, str]]:
    """Litteraux chaine du fichier, docstrings exclues."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))

    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]


def test_no_persistent_set_statement() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for lineno, text in _executable_strings(path):
            if PERSISTENT_SET.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert not offenders, (
        "SET persistant sur app.current_org detecte : avec PgBouncer en mode "
        f"transaction, le contexte fuit vers le tenant suivant. {offenders}"
    )


def test_set_config_is_always_transaction_local() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for lineno, text in _executable_strings(path):
            for match in SET_CONFIG_CALL.finditer(text):
                if match.group("local").strip().lower() != "true":
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{lineno} (is_local={match.group('local')!r})"
                    )

    assert not offenders, (
        f"set_config('app.current_org', ...) appele sans is_local=true : {offenders}"
    )


def test_tenant_context_is_centralised_in_libs_db() -> None:
    """Seul libs/db pose le contexte tenant."""
    offenders: list[str] = []
    for path in _python_files():
        if path == DB_MODULE:
            continue
        for lineno, text in _executable_strings(path):
            if ANY_TENANT_GUC.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}")

    assert not offenders, (
        f"app.current_org reference hors de libs/db : {offenders}"
    )


def test_libs_db_uses_set_config_not_set_local() -> None:
    """Controle positif : le module autorise fait bien ce qu'on attend de lui."""
    strings = [text for _, text in _executable_strings(DB_MODULE)]
    calls = [t for t in strings if SET_CONFIG_CALL.search(t)]
    assert calls, "libs/db doit poser le contexte via set_config(..., true)"
    for text in calls:
        match = SET_CONFIG_CALL.search(text)
        assert match is not None
        assert match.group("local").strip().lower() == "true"


def test_rls_context_helper_fails_closed_on_missing_or_empty_guc() -> None:
    """Le helper RLS normalise les deux formes de contexte absent en 42704.

    PostgreSQL peut conserver un placeholder de GUC custom vide apres un
    SET LOCAL termine. Le helper doit donc gerer NULL ET chaine vide, puis lever
    explicitement undefined_object au lieu de laisser une politique retourner
    silencieusement zero ligne.
    """
    rls = (ROOT / "migrations" / "0006_rls_policies.sql").read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.sentrix_current_org()" in rls
    assert "current_setting('app.current_org', true)" in rls
    assert "raw_org IS NULL OR raw_org = ''" in rls
    assert "ERRCODE = '42704'" in rls

    for table in ("organizations", "org_members", "projects", "bots", "environments", "audit_log"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in rls, table
        assert f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY" in rls, (
            f"FORCE manquant sur {table} : le proprietaire contournerait RLS"
        )

    policy_lines = [
        line.strip()
        for line in rls.splitlines()
        if line.strip().startswith(("USING      (", "WITH CHECK ("))
    ]
    assert policy_lines
    assert all("public.sentrix_current_org()" in line for line in policy_lines)


def test_discord_application_uniqueness_applies_only_after_verification() -> None:
    migration = (ROOT / "migrations" / "0004_bots_environments.sql").read_text(
        encoding="utf-8"
    )
    assert "environments_discord_app_verified_uniq" in migration
    assert "discord_application_verified_at IS NOT NULL" in migration
    assert "WHERE discord_application_id IS NOT NULL" in migration


def test_audit_log_has_no_update_or_delete_grant() -> None:
    grants = (ROOT / "migrations" / "0007_grants.sql").read_text(encoding="utf-8")
    for line in grants.splitlines():
        stripped = line.strip()
        if stripped.startswith("GRANT") and "audit_log" in stripped:
            assert "UPDATE" not in stripped.upper(), stripped
            assert "DELETE" not in stripped.upper(), stripped
