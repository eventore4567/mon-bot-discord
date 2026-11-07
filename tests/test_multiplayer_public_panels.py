import json
import os
import subprocess
import sys
from pathlib import Path


def test_actual_public_duel_and_community_game():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tests/_boot_probe_multiplayer_panels.py")],
        cwd=root,
        env={**os.environ, "DISCORD_TOKEN": "ci.fake.token"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-5000:]
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "duel": "accepted_and_won",
        "group": "joined_started_and_won",
        "cleanup": True,
        "persistent_launcher": True,
    }
