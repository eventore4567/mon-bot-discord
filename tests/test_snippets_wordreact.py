"""Nouveaux outils : mots complets et décisions de permission."""
from cogs.snippets import normal_name
from cogs.word_reactions import matches
from utils import access_matrix, slash_catalog
from cogs.recurring_messages import parse_interval, is_logs_channel
from types import SimpleNamespace


def test_snippet_names_are_strict():
    assert normal_name("Annonce-Staff") == "annonce-staff"
    assert normal_name("a") is None
    assert normal_name("@everyone") is None


def test_word_reactions_only_match_whole_words_and_ignore_accents():
    assert matches("HÉLLO, les amis", "hello")
    assert matches("Attention à la café !", "cafe")
    assert not matches("début de bonjourno", "bonjour")
    assert not matches("superbonjour", "bonjour")


def test_all_slash_entries_are_in_catalog():
    paths = {e.path: e.source for e in slash_catalog.CATALOG}
    for source in ("snippet create", "snippet send", "snippet list", "snippet delete",
                   "wordreact add", "wordreact remove", "wordreact list",
                   "recurring create", "recurring list", "recurring pause",
                   "recurring resume", "recurring delete"):
        assert paths[source] == source


def test_staff_can_send_but_only_admin_can_create():
    assert access_matrix.access_tier("snippet") == "discord:manage_messages"
    assert access_matrix.access_tier("snippet create") == "categorie:configuration"
    assert access_matrix.access_tier("snippet delete") == "categorie:configuration"
    assert access_matrix.access_tier("wordreact") == "categorie:configuration"



def test_recurring_is_paused_until_explicitly_enabled():
    assert parse_interval("9m") is None
    assert parse_interval("10m") == 600
    assert parse_interval("6h") == 21600
    assert parse_interval("31d") is None
    assert access_matrix.access_tier("recurring") == "categorie:configuration"


def test_recurring_rejects_log_channels():
    logs = SimpleNamespace(name="logs-modération", category=None)
    general = SimpleNamespace(name="général", category=SimpleNamespace(name="Discussion"))
    assert is_logs_channel(logs)
    assert not is_logs_channel(general)
