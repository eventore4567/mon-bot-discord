from types import SimpleNamespace

from services.usage_presence import usage_presence_text


def test_usage_presence_uses_members_and_servers():
    guilds = [SimpleNamespace(member_count=1250), SimpleNamespace(member_count=75)]

    assert usage_presence_text(guilds) == "🛡️ 1 325 membres protégés • 2 serveurs"


def test_usage_presence_handles_missing_counts_and_singulars():
    guilds = [SimpleNamespace(member_count=1), SimpleNamespace(member_count=None)]

    assert usage_presence_text(guilds) == "🛡️ 1 membre protégé • 2 serveurs"
    assert usage_presence_text([]) == "🛡️ 0 membres protégés • 0 serveurs"
