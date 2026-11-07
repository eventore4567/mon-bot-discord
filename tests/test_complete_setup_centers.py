"""Configuration complète, moteurs inchangés, style SentriX et contrôles réels."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_complete_centers_with_actual_bootstrap():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tests/_boot_probe_complete_config.py")],
        cwd=root,
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-5000:]
    summary = json.loads(result.stdout.splitlines()[-1])
    assert summary["protections"] >= 19
    assert summary["welcome"] and summary["backups"]
    assert summary["style"] == "SentriX" and summary["runtime"] == "existing"
