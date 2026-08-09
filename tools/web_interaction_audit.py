"""Audit CI des interactions web SentriX.

Vérifie deux régressions qui rendent visuellement les boutons « morts » :
- le verrou Administrateur ne doit jamais intercepter l'API publique /api/appeal/{token};
- chaque bloc JavaScript inline des pages avancées doit être syntaxiquement valide.

Node est déjà disponible sur les runners GitHub Actions (actions/* l'utilise) et sert ici
uniquement de parseur JavaScript, sans réseau ni exécution du code du dashboard.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import dashboard, operations_center, setup_center
from web import enterprise_suite

SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.I | re.S)
BUTTON_ID_RE = re.compile(r"<button\b[^>]*\bid=[\"']([^\"']+)[\"']", re.I)


def check_js(name: str, html: str) -> None:
    scripts = SCRIPT_RE.findall(html or "")
    if not scripts:
        return
    for index, source in enumerate(scripts, 1):
        if not source.strip():
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = Path(handle.name)
        try:
            result = subprocess.run(
                ["node", "--check", str(path)],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            assert result.returncode == 0, (
                f"JavaScript invalide dans {name}, script #{index}:\n"
                f"{result.stderr or result.stdout}"
            )
        finally:
            path.unlink(missing_ok=True)


def check_button_bindings(name: str, html: str) -> None:
    ids = BUTTON_ID_RE.findall(html or "")
    scripts = "\n".join(SCRIPT_RE.findall(html or ""))
    missing = [button_id for button_id in ids if button_id not in scripts]
    assert not missing, f"Boutons sans branchement JavaScript dans {name}: {missing}"


def main() -> None:
    admin_source = (ROOT / "web" / "admin_only_dashboard.py").read_text(encoding="utf-8")
    assert 'path.startswith("/api/appeal/")' in admin_source, (
        "Le middleware admin bloque de nouveau l'API publique des recours."
    )

    pages = {
        "dashboard.INDEX_HTML": dashboard.INDEX_HTML,
        "setup_center.SETUP_CENTER_HTML": setup_center.SETUP_CENTER_HTML,
        "operations_center.OPERATIONS_HTML": operations_center.OPERATIONS_HTML,
        "enterprise_suite.ENTERPRISE_HTML": enterprise_suite.ENTERPRISE_HTML,
        "enterprise_suite.APPEAL_HTML": enterprise_suite.APPEAL_HTML,
    }
    for name, html in pages.items():
        check_js(name, html)

    # Les deux pages nouvelles sont très interactives : chaque bouton statique doit avoir
    # une référence dans leur JavaScript. Les pages historiques ont des boutons servis par
    # plusieurs couches et sont couvertes par leurs audits dédiés.
    check_button_bindings("enterprise_suite.ENTERPRISE_HTML", enterprise_suite.ENTERPRISE_HTML)
    check_button_bindings("enterprise_suite.APPEAL_HTML", enterprise_suite.APPEAL_HTML)

    appeal_html = enterprise_suite.APPEAL_HTML
    assert "Envoyer le recours" in appeal_html
    assert "/api/appeal/" in appeal_html
    assert "method:'POST'" in appeal_html or 'method:"POST"' in appeal_html

    print("OK: API recours publique, scripts dashboard valides et boutons Enterprise/Recours branchés")


if __name__ == "__main__":
    main()
