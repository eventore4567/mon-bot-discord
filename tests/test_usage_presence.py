from types import SimpleNamespace

from services.usage_presence import rotating_presence_text, usage_presence_text


def test_usage_presence_uses_members_and_servers():
    guilds = [SimpleNamespace(member_count=1250), SimpleNamespace(member_count=75)]

    assert usage_presence_text(guilds) == "🛡️ 1 325 membres protégés • 2 serveurs"


def test_usage_presence_handles_missing_counts_and_singulars():
    guilds = [SimpleNamespace(member_count=1), SimpleNamespace(member_count=None)]

    assert usage_presence_text(guilds) == "🛡️ 1 membre protégé • 2 serveurs"
    assert usage_presence_text([]) == "🛡️ 0 membres protégés • 0 serveurs"


def test_rotating_presence_alternates_french_and_english():
    guilds = [SimpleNamespace(member_count=1250), SimpleNamespace(member_count=75)]
    assert rotating_presence_text(guilds, 0) == "Protège 1 325 membres"
    assert rotating_presence_text(guilds, 1) == "Protecting 1 325 members"
    assert rotating_presence_text(guilds, 2) == "Actif sur 2 serveurs"
    assert rotating_presence_text(guilds, 3) == "Active on 2 servers"
    assert rotating_presence_text(guilds, 4) == "Protège 1 325 membres"


def test_rotating_presence_handles_singular_and_missing_counts():
    guilds = [SimpleNamespace(member_count=1)]
    assert rotating_presence_text(guilds, 0) == "Protège 1 membre"
    assert rotating_presence_text(guilds, 1) == "Protecting 1 member"
    assert rotating_presence_text(guilds, 2) == "Actif sur 1 serveur"
    assert rotating_presence_text(guilds, 3) == "Active on 1 server"
    assert rotating_presence_text([]) == "Protège 0 membres"
    assert rotating_presence_text([SimpleNamespace(member_count=None)], 1) == "Protecting 0 members"
