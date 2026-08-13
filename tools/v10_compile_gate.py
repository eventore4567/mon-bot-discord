from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in ("cogs/bot_v10.py","web/platform_v10.py","cogs/slash_reliability_v7.py"):
    source=(ROOT/path).read_text(encoding="utf-8")
    compile(source,path,"exec")
core=(ROOT/"cogs/bot_v10.py").read_text(encoding="utf-8")
assert "@commands.hybrid_command" not in core
assert "@app_commands.command" not in core
print("OK: V10 sources compile and keep the slash catalog unchanged")
