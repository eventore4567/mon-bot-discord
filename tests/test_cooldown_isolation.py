from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "cogs" / "cooldown_isolation_fix.py"
GUARD = ROOT / "cogs" / "slash_error_completion_guard.py"
MAIN = ROOT / "main.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sources_compile():
    for path in (FIX, GUARD):
        compile(read(path), str(path), "exec")


def test_legacy_bug_is_documented_by_source_shape():
    source = read(MAIN)
    # L'ancien code possède bien un mapping unique et l'enregistre comme check global.
    assert "self._cooldown_bucket = commands.CooldownMapping.from_cooldown" in source
    assert "self.add_check(self.global_cooldown_check)" in source


def test_fix_removes_legacy_check_and_discards_shared_state():
    source = read(FIX)
    assert 'legacy_check = getattr(bot, "global_cooldown_check", None)' in source
    assert "bot.remove_check(legacy_check)" in source
    assert "mappings: dict[str, commands.CooldownMapping] = {}" in source
    assert 'state["mappings"] = mappings' in source
    assert "_cooldown_bucket.get_bucket" not in source


def test_each_command_gets_its_own_mapping():
    source = read(FIX)
    assert "command_key = _command_key(ctx)" in source
    assert "mapping = mappings.get(command_key)" in source
    assert "mappings[command_key] = mapping" in source
    assert "commands.BucketType.user" in source
    assert "mapping.get_bucket(_bucket_source(ctx))" in source


def test_qualified_command_name_is_the_isolation_key():
    source = read(FIX)
    assert 'qualified = getattr(command, "qualified_name", None)' in source
    assert "return str(qualified).casefold()" in source


def test_owner_bypass_is_preserved():
    source = read(FIX)
    assert "user_id == PRIMARY_CREATOR_ID" in source
    assert "user_id in config.OWNER_IDS" in source
    assert "await bot.db.is_bot_creator(user_id)" in source


def test_legacy_fix_is_not_installed_in_final_runtime():
    source = read(GUARD)
    v6 = source.index("await logs_unified_v6.install(bot)")
    no_cooldown = source.index("no_cooldown_final.install(bot)")
    assert no_cooldown > v6
    assert "cooldown_isolation_fix.install(bot)" not in source


if __name__ == "__main__":
    test_sources_compile()
    test_legacy_bug_is_documented_by_source_shape()
    test_fix_removes_legacy_check_and_discards_shared_state()
    test_each_command_gets_its_own_mapping()
    test_qualified_command_name_is_the_isolation_key()
    test_owner_bypass_is_preserved()
    test_legacy_fix_is_not_installed_in_final_runtime()
    print("cooldown isolation contracts: ok (legacy module retained, final runtime disabled)")
