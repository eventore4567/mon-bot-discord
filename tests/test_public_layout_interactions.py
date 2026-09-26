from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import marketing_growth_v40


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"


def _html() -> str:
    request = SimpleNamespace(path="/start", app={"dashboard_module": _Dashboard})
    return marketing_growth_v40._layout(
        request,
        title="Test SentriX",
        description="Test",
        heading="Test",
        body='<section class="grid"><div class="card">Carte</div></section>',
    )


def test_shared_public_layout_is_responsive_and_interactive():
    page = _html()
    for marker in (
        # « id="publicPointer" » a quitté cette liste le 2026-09-26 : l'élément
        # était display:none dans les trois media queries, donc jamais visible.
        # C'était de la décoration morte, pas une interaction à garder.
        'querySelectorAll(".card,.media-grid img")',
        'requestAnimationFrame(()=>frame(el))',
        'e.pointerType!=="touch"',
        'e.pointerType==="touch"',
        "@media(max-width:1024px)",
        "@media(max-width:760px)",
        "@media(max-width:430px)",
        "@media(max-width:360px)",
        "@media(pointer:coarse)",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert marker in page


def test_shared_public_layout_javascript_syntax(tmp_path: Path):
    node = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node.returncode != 0:
        pytest.skip("node indisponible")
    scripts = re.findall(r"<script>(.*?)</script>", _html(), re.S)
    # Deux scripts depuis le 2026-09-26 : le moteur de fond partagé
    # (web/sentrix_fx_v1) et l'inclinaison des cartes propre à cette coquille.
    assert len(scripts) == 2
    for index, source in enumerate(scripts):
        target = tmp_path / f"shared-public-layout-{index}.js"
        target.write_text(source, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(target)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
