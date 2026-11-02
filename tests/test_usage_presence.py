from types import SimpleNamespace

from services.usage_presence import rotating_presence_text, usage_presence_text


def test_usage_presence_uses_members_and_servers():
    guilds = [SimpleNamespace(member_count=1250), SimpleNamespace(member_count=75)]

    assert usage_presence_text(guilds) == "🛡️ 1 325 membres protégés • 2 serveurs"


def test_usage_presence_handles_missing_counts_and_singulars():
    guilds = [SimpleNamespace(member_count=1), SimpleNamespace(member_count=None)]

    assert usage_presence_text(guilds) == "🛡️ 1 membre protégé • 2 serveurs"
    assert usage_presence_text([]) == "🛡️ 0 membres protégés • 0 serveurs"


def test_rotating_presence_keeps_original_format_and_alternates_language():
    guilds = [SimpleNamespace(member_count=1250), SimpleNamespace(member_count=75)]
    assert rotating_presence_text(guilds, 0) == "🛡️ 1 325 membres protégés • 2 serveurs"
    assert rotating_presence_text(guilds, 1) == "🛡️ 1,325 members protected • 2 servers"
    assert rotating_presence_text(guilds, 2) == "🛡️ 1 325 membres protégés • 2 serveurs"
    assert rotating_presence_text(guilds, 3) == "🛡️ 1,325 members protected • 2 servers"


def test_rotating_presence_handles_singular_empty_and_missing_counts():
    guilds = [SimpleNamespace(member_count=1)]
    assert rotating_presence_text(guilds, 0) == "🛡️ 1 membre protégé • 1 serveur"
    assert rotating_presence_text(guilds, 1) == "🛡️ 1 member protected • 1 server"
    assert rotating_presence_text([], 0) == "🛡️ 0 membres protégés • 0 serveurs"
    assert rotating_presence_text([], 1) == "🛡️ 0 members protected • 0 servers"
    assert rotating_presence_text([SimpleNamespace(member_count=None)], 1) == "🛡️ 0 members protected • 1 server"
