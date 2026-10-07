from sentrix_canonical_command_surface import (
    BUCKETS,
    LEAVES,
    MUSIC_LEAVES,
    PLAYLIST_LEAVES,
    ROOTS,
    SHORT_TARGETS,
    _english_public_name,
)


def test_canonical_roots_are_english_and_human_readable():
    assert ROOTS["music"] == "music"
    assert ROOTS["security"] == "security"
    assert ROOTS["config"] == "config"
    assert ROOTS["game"] == "games"
    assert ROOTS["level"] == "levels"
    assert ROOTS["giveaway"] == "giveaway"
    assert "musique" not in ROOTS.values()
    assert "securite" not in ROOTS.values()
    assert "outils" not in ROOTS.values()


def test_moderation_and_music_clear_stay_distinct_but_english():
    assert LEAVES.get("clear", "clear") == "clear"
    assert MUSIC_LEAVES["clear"] == "clear"
    assert MUSIC_LEAVES["queue"] == "queue"
    assert MUSIC_LEAVES["nowplaying"] == "now-playing"


def test_playlist_surface_is_english():
    assert PLAYLIST_LEAVES == {
        "create": "create",
        "import": "import",
        "add": "add",
        "list": "list",
        "show": "show",
        "play": "play",
        "remove": "remove",
        "clear": "clear",
        "rename": "rename",
        "delete": "delete",
    }


def test_legacy_short_french_surface_is_disabled():
    assert SHORT_TARGETS == {}


def test_music_direct_actions_have_expected_english_names():
    expected = {
        "play": "play",
        "pause": "pause",
        "resume": "resume",
        "skip": "skip",
        "previous": "previous",
        "stop": "stop",
        "nowplaying": "now-playing",
        "volume": "volume",
        "loop": "loop",
        "shuffle": "shuffle",
        "seek": "seek",
        "autoplay": "autoplay",
    }
    for source, public in expected.items():
        assert MUSIC_LEAVES[source] == public


def test_music_leaf_rebuild_prevents_cross_bucket_suffixes():
    import sentrix_canonical_command_surface as surface

    original = surface.v98.semantic_leaf

    class Target:
        def __init__(self, original_name, leaf_name):
            self.original_name = original_name
            self.leaf_name = leaf_name

    surface.install()
    leaf = surface.v98.semantic_leaf

    assert leaf("music", "queue", Target("music remove", "remove-2")) == "remove"
    assert leaf("music", "playlist", Target("music playlist clear", "clear-2")) == "clear"

    surface.v98.semantic_leaf = original


def test_generic_buckets_are_short_and_english():
    assert BUCKETS[("config", "general")] == "general"
    assert BUCKETS[("utility", "general")] == "general"
    assert BUCKETS[("moderation", "general")] == "general"


def test_legacy_french_tokens_are_normalized_before_publish():
    assert _english_public_name("profil") == "profile"
    assert _english_public_name("historique") == "history"
    assert _english_public_name("securite") == "security"
    assert _english_public_name("outils-pratiques") == "tools-utility"
