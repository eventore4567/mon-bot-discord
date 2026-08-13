import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for path in (
    "cogs/bot_v10.py",
    "web/platform_v10.py",
    "cogs/slash_reliability_v7.py",
    "cogs/setup_auto_fix.py",
):
    source = (ROOT / path).read_text(encoding="utf-8")
    compile(source, path, "exec")

core = (ROOT / "cogs/bot_v10.py").read_text(encoding="utf-8")
boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
assert "@commands.hybrid_command" not in core
assert "@app_commands.command" not in core
assert '"cogs.setup_auto_fix"' in boot

from cogs.setup_auto_fix import parse_setup_auto_profile

assert parse_setup_auto_profile("+setup auto community") == "community"
assert parse_setup_auto_profile("+setup auto gaming") == "gaming"
assert parse_setup_auto_profile("+setup auto support") == "support"
assert parse_setup_auto_profile("+setup auto creator") == "creator"
assert parse_setup_auto_profile("+setup auto") == "community"
assert parse_setup_auto_profile("!SeTuP AUTO GAMING", "!", "setup") == "gaming"
assert parse_setup_auto_profile("+setup") is None
assert parse_setup_auto_profile("+setupfoo auto community") is None

print("OK: V10 sources compile, setup auto routes all profiles, slash catalog unchanged")
