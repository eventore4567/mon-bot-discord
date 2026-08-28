from pathlib import Path

import pytest

from cogs.automatic_verification_v4 import (
    DEFAULT_THRESHOLD,
    FACTOR_COUNT,
    MIN_THRESHOLD,
    Factor,
    clamp_threshold,
    score_factors,
)


def factors(passed: int):
    return [
        Factor(key=f"factor_{index}", label=f"Facteur {index}", passed=index < passed)
        for index in range(FACTOR_COUNT)
    ]


def test_contract_is_exactly_twenty_factors():
    assert FACTOR_COUNT == 20
    score, accepted = score_factors(factors(20))
    assert score == 20
    assert accepted is True


def test_sixteen_passes_and_fifteen_fails():
    assert DEFAULT_THRESHOLD == 16
    assert score_factors(factors(16)) == (16, True)
    assert score_factors(factors(15)) == (15, False)


def test_threshold_can_never_be_lower_than_sixteen():
    assert MIN_THRESHOLD == 16
    assert clamp_threshold(0) == 16
    assert clamp_threshold(15) == 16
    assert clamp_threshold(16) == 16
    assert clamp_threshold(19) == 19
    assert clamp_threshold(999) == 20


def test_wrong_factor_count_fails_closed():
    with pytest.raises(ValueError):
        score_factors(factors(19))
    with pytest.raises(ValueError):
        score_factors(factors(20) + [Factor("extra", "Extra", True)])


def test_low_score_never_contains_automatic_ban_path():
    source = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
    evaluate = source.split("async def evaluate_member", 1)[1].split("def schedule_evaluation", 1)[0]
    low_score_branch = evaluate.split("if not passed:", 1)[1].split("unverified =", 1)[0]
    assert ".ban(" not in low_score_branch
    assert ".kick(" not in low_score_branch
    assert '"low_score"' in low_score_branch


def test_membership_screening_is_deferred_then_retried():
    source = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
    assert 'getattr(member, "pending", False)' in source
    assert 'reason="screening-complete"' in source
    assert "on_member_update" in source


def test_honeypot_is_separate_from_score_decision():
    source = Path("cogs/automatic_verification_v4.py").read_text(encoding="utf-8")
    assert 'kind="honeypot"' in source
    assert "SentriX Honeypot anti-bot" in source
    assert "Un score insuffisant ne bannit jamais" in source


def test_natural_sentrix_trigger_still_exists():
    source = Path("cogs/ai.py").read_text(encoding="utf-8")
    assert "async def on_message" in source
    assert "sentrix|ssentrix|sentri|snetri|snentrix" in source
    assert "send_sentrix_reply" in source


def test_setup_v4_exposes_real_ticket_hub():
    source = Path("cogs/control_center_v4.py").read_text(encoding="utf-8")
    assert "TicketSetupHubView" in source
    assert "ticket_panels_v2" in source
    assert "ticket_types" in source
    assert "Claim • unclaim" in source or "claim / unclaim" in source
