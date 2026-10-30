"""Nouveaux outils : mots complets et décisions de permission."""
from cogs.snippets import normal_name
from cogs.word_reactions import matches
from utils import access_matrix, slash_catalog


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
                   "wordreact add", "wordreact remove", "wordreact list"):
        assert paths[source] == source


def test_staff_can_send_but_only_admin_can_create():
    assert access_matrix.access_tier("snippet") == "discord:manage_messages"
    assert access_matrix.access_tier("snippet create") == "categorie:configuration"
    assert access_matrix.access_tier("snippet delete") == "categorie:configuration"
    assert access_matrix.access_tier("wordreact") == "categorie:configuration"
