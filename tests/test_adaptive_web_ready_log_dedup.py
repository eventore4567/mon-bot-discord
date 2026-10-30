"""Éviter le spam des contrôles ordinaires sans masquer les vraies alertes."""
import time

from cogs.automatic_verification_v5 import (
    WEB_READY_LOG_DEDUP_SECONDS,
    should_log_web_ready,
)


def test_first_success_always_logged():
    assert should_log_web_ready(None, now=2000)


def test_repeated_web_ready_in_ten_minutes_is_not_logged_twice():
    assert not should_log_web_ready(
        {"status": "web_ready", "evaluated_at": 1500}, now=2000,
    )


def test_status_transition_after_review_is_logged():
    assert should_log_web_ready(
        {"status": "review", "evaluated_at": 1999}, now=2000,
    )
    assert should_log_web_ready(
        {"status": "pending_recheck", "evaluated_at": 1999}, now=2000,
    )


def test_success_is_logged_again_after_dedup_window():
    assert should_log_web_ready(
        {"status": "web_ready", "evaluated_at": 2000 - WEB_READY_LOG_DEDUP_SECONDS},
        now=2000,
    )


def test_missing_or_future_database_timestamp_does_not_hide_logs():
    assert should_log_web_ready({"status": "web_ready"}, now=2000)
    assert should_log_web_ready({"status": "web_ready", "evaluated_at": 3000}, now=2000)
    assert should_log_web_ready({"status": None, "evaluated_at": 1999}, now=2000)


def test_only_web_ready_branch_applies_deduplication():
    from pathlib import Path
    source = Path("cogs/automatic_verification_v5.py").read_text(encoding="utf-8")
    review_branch = source.split('await self._save_result(member, score, threshold, "review"', 1)[1].split(
        'await self._save_result(member, score, threshold, "web_ready"', 1
    )[0]
    assert 'await self._log_result(member, score, threshold, "review", factors)' in review_branch
    assert "should_log_web_ready" not in review_branch
