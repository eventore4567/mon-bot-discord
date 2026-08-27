import asyncio
import inspect
from pathlib import Path

from cogs import final_stability_guard


class DummyAi:
    def __init__(self):
        self._last_used = {(1, 2): 123.0}
        self._minute_bucket = {(1, 2): [1.0, 2.0]}

    def _check_cooldown(self, guild_id, user_id, cooldown_seconds):
        return 5.0

    def _check_minute_limit(self, guild_id, user_id, per_minute_limit):
        return True


class DummyBot:
    def __init__(self, ai=None):
        self.ai = ai

    def get_cog(self, name):
        return self.ai if name == "Ai" else None


class DummyFile:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_ai_local_throttle_is_disabled_without_touching_other_policy():
    ai = DummyAi()
    bot = DummyBot(ai)

    assert final_stability_guard._disable_ai_local_throttle(bot) is True
    assert ai._check_cooldown(1, 2, 999) is None
    assert ai._check_minute_limit(1, 2, 1) is False
    assert ai._last_used == {}
    assert ai._minute_bucket == {}


def test_ai_patch_is_safe_when_cog_is_absent():
    assert final_stability_guard._disable_ai_local_throttle(DummyBot()) is False


async def _exercise_partial_attachment_guard():
    from cogs import logs_unified_v6

    original = logs_unified_v6._best_effort_files
    one = DummyFile()

    async def partial(_attachments):
        return [one]

    try:
        logs_unified_v6._best_effort_files = partial
        assert final_stability_guard._install_safe_attachment_archive() is True
        wrapped = logs_unified_v6._best_effort_files
        assert inspect.iscoroutinefunction(wrapped)
        result = await wrapped([object(), object()])
        assert result == []
        assert one.closed is True
    finally:
        logs_unified_v6._best_effort_files = original


def test_partial_attachment_archive_never_misaligns_files():
    asyncio.run(_exercise_partial_attachment_guard())


def test_runtime_load_order_and_contracts():
    root = Path(__file__).resolve().parents[1]
    railway = (root / "railway_boot.py").read_text(encoding="utf-8")
    source = (root / "cogs" / "final_stability_guard.py").read_text(encoding="utf-8")

    assert railway.index('"cogs.slash_error_completion_guard"') < railway.index(
        '"cogs.final_stability_guard"'
    )
    assert "no_cooldown_final.install(bot)" in source
    assert "cog._check_cooldown" in source
    assert "cog._check_minute_limit" in source
    assert "len(files) == len(selected)" in source
    assert "daily_limit" not in source.split("def _disable_ai_local_throttle", 1)[1].split(
        "def _install_safe_attachment_archive", 1
    )[0]


if __name__ == "__main__":
    test_ai_local_throttle_is_disabled_without_touching_other_policy()
    test_ai_patch_is_safe_when_cog_is_absent()
    test_partial_attachment_archive_never_misaligns_files()
    test_runtime_load_order_and_contracts()
    print("final stability guard: ok")
