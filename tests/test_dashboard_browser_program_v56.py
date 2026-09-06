from __future__ import annotations

import html as html_lib
import re
import subprocess
from pathlib import Path


def _classic_inline_scripts(document: str) -> list[str]:
    scripts: list[str] = []
    pattern = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.I | re.S)
    for match in pattern.finditer(document):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        type_match = re.search(r"\btype\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.I)
        if type_match and type_match.group(1).lower() not in {"text/javascript", "application/javascript", "module"}:
            continue
        scripts.append(html_lib.unescape(body))
    return scripts


def _prestart_html() -> str:
    from web import dashboard
    import sentrix_product_update

    sentrix_product_update.install_dashboard_prestart(dashboard)
    return str(dashboard.INDEX_HTML)


def test_prestart_dashboard_contains_the_authenticated_boot_chain():
    document = _prestart_html()
    assert 'async function loadSession()' in document
    assert 'async function loadGuilds()' in document
    assert '"/api/me"' in document
    assert '"/api/guilds"' in document
    assert 'Promise.all([loadPublic(),loadSession()])' in document


def test_prestart_dashboard_javascript_parses_in_node(tmp_path: Path):
    document = _prestart_html()
    scripts = _classic_inline_scripts(document)
    assert scripts, "Aucun script inline classique trouvé dans /app"

    # Les balises <script> classiques partagent le même environnement global dans le
    # navigateur. Les concaténer détecte à la fois les erreurs de syntaxe et les
    # redéclarations lexicales globales introduites par les anciennes couches UI.
    bundle = "\n;/* --- script boundary --- */\n".join(scripts)
    target = tmp_path / "sentrix-dashboard-prestart.js"
    target.write_text(bundle, encoding="utf-8")

    result = subprocess.run(
        ["node", "--check", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        "Le JavaScript servi par /app est invalide avant même son exécution.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
        f"Bundle: {target}"
    )
