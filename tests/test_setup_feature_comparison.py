"""The feature comparer never claims to import a third-party bot's private code."""
import asyncio
from types import SimpleNamespace

from cogs.feature_comparison import compare_features, ComparisonView
import pytest


def test_feature_comparison_maps_public_claims_to_actual_setup_modules():
    recognized, unknown = compare_features(
        "Anti-Raid\nTickets\nBanque\nXP\nTikTok\nCustom map generator"
    )
    mapping = {name: modules for name, modules in recognized}
    assert "security" in mapping["Anti-Raid"]
    assert "tickets" in mapping["Tickets"]
    assert "economy" in mapping["Banque"]
    assert "xp" in mapping["XP"]
    assert "automations" in mapping["TikTok"]
    assert unknown == ["Custom map generator"]


def test_dedup_and_limits():
    matched, unknown = compare_features("ticket; Ticket\nrandom")
    assert len(matched) == 1 and unknown == ["random"]
    with pytest.raises(ValueError):
        compare_features("")
    with pytest.raises(ValueError):
        compare_features("\n".join(f"feature-{i}" for i in range(46)))


def test_comparison_only_advises_and_displays_unknowns():
    m, u = compare_features("anti-spam\nunknown-feature")
    view = ComparisonView(SimpleNamespace(), 1, 2, "OtherBot", m, u)
    embed = view.embed()
    assert "Sécurité" in embed.description
    assert "exactes ne sont pas automatiquement copiées" in embed.description
    assert "unknown-feature" in embed.fields[0].value


async def _test_save_only_after_explicit_action():
    class Db:
        def __init__(self):
            self.calls = []
        async def execute(self, sql, params=()):
            self.calls.append((sql, params))
    db=Db()
    bot=SimpleNamespace(db=db)
    matched, unknown = compare_features("ticket\nunknown-feature")
    view=ComparisonView(bot, 1, 2, "OtherBot", matched, unknown)
    view.embed()
    assert not db.calls
    assert not view.saved


def test_preview_does_not_mutate_configuration():
    asyncio.run(_test_save_only_after_explicit_action())
