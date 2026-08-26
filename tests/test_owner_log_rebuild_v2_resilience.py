from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "cogs" / "owner_log_rebuild_v2.py"
HEALTH = ROOT / "cogs" / "owner_log_rebuild_v2_health.py"
CONCURRENCY = ROOT / "cogs" / "owner_log_rebuild_v2_concurrency.py"
GUARD = ROOT / "cogs" / "slash_error_completion_guard.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sources_compile():
    for path in (V2, HEALTH, CONCURRENCY, GUARD):
        compile(read(path), str(path), "exec")


def test_reset_v2_is_installed_last():
    source = read(GUARD)
    assert "owner_log_rebuild_v2_health.install()" in source
    assert "await owner_log_rebuild_v2.install(bot)" in source


def test_disappearing_category_has_retry_and_root_fallback():
    source = read(V2)
    assert "getattr(exc, \"code\", None) == 50035" in source
    assert "category does not exist" in source
    assert "category = None" in source
    assert "fallback_root = True" in source


def test_missing_access_is_repaired_then_replaced():
    source = read(V2)
    assert '"403" in lowered' in source
    assert '"missing access" in lowered' in source
    assert "await _force_channel_access(guild, channel)" in source
    assert "Remplacement route {log_type} après Missing Access" in source
    assert "category=None" in source


def test_healthy_servers_are_not_rebuilt_from_legacy_routes():
    source = read(HEALTH)
    assert 'startswith("SentriX logs •")' in source
    assert "len(route_ids) == len(v1.LOG_ROUTES)" in source


def test_concurrency_never_deletes_after_lost_ownership():
    source = read(CONCURRENCY)
    assert "preserve_on_lost_ownership" in source
    assert ".delete(" not in source
    v2_source = read(V2)
    assert v2_source.count("await _routes_owned") >= 3
    assert "asyncio.Lock()" in v2_source


def test_command_name_is_preserved():
    source = read(V2)
    assert '@commands.command(name="reset-logs-all"' in source
    assert "@checks.is_bot_owner()" in source


if __name__ == "__main__":
    test_sources_compile()
    test_reset_v2_is_installed_last()
    test_disappearing_category_has_retry_and_root_fallback()
    test_missing_access_is_repaired_then_replaced()
    test_healthy_servers_are_not_rebuilt_from_legacy_routes()
    test_concurrency_never_deletes_after_lost_ownership()
    test_command_name_is_preserved()
    print("owner-log-rebuild-v2 resilience contracts: ok")
