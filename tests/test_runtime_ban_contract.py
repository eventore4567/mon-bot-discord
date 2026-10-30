"""La surface runtime du bot ne doit pas garder un ancien paramètre /ban."""
from cogs.runtime_quality_v25 import _CRITICAL_CONTRACTS
from tools.v25_quality_gate import CRITICAL_CONTRACTS


def test_runtime_contract_matches_live_ban_signature():
    expected = ("membre", "raison", "envoyer_mp")
    assert _CRITICAL_CONTRACTS["ban"] == expected
    assert CRITICAL_CONTRACTS["ban"] == expected
