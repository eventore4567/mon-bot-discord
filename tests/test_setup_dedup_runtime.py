"""Les clics doivent produire des cartes valides après les personnalisations du boot."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_setup_and_role_picker_after_full_production_boot():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tests/_boot_probe_setup_dedup.py")],
        cwd=root,
        check=False,
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-5000:]
    data = json.loads(result.stdout.splitlines()[-1])
    assert data == {
        "picker_callbacks": 3,
        "custom_modal": True,
        "selected_channel_publish": True,
        "unique_setup": True,
    }
