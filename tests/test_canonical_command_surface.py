from sentrix_canonical_command_surface import (
    LEAVES,
    MUSIC_LEAVES,
    PLAYLIST_LEAVES,
    ROOTS,
    SHORT_TARGETS,
)


def test_canonical_roots_are_human_readable():
    assert ROOTS["music"] == "musique"
    assert ROOTS["security"] == "securite"
    assert ROOTS["config"] == "configuration"
    assert ROOTS["game"] == "jeux"
    assert ROOTS["level"] == "niveaux"
    assert ROOTS["giveaway"] == "giveaway"
    assert "concours" not in ROOTS.values()


def test_music_names_do_not_leak_into_moderation_names():
    # Regression: a duplicate dict key used to turn moderation clear into "vider".
    assert LEAVES["clear"] == "nettoyer"
    assert MUSIC_LEAVES["clear"] == "vider"
    assert MUSIC_LEAVES["queue"] == "voir"
    assert MUSIC_LEAVES["nowplaying"] == "en-cours"


def test_playlist_surface_has_explicit_semantics():
    assert PLAYLIST_LEAVES == {
        "create": "sauvegarder",
        "import": "importer",
        "add": "ajouter",
        "list": "liste",
        "show": "infos",
        "play": "charger",
        "remove": "retirer",
        "clear": "vider",
        "rename": "renommer",
        "delete": "supprimer",
    }



def test_music_short_mode_keeps_the_same_canonical_vocabulary():
    assert SHORT_TARGETS["music remove"] == ("musique", "file", "retirer")
    assert SHORT_TARGETS["music autoplay"] == ("musique", "", "lecture-auto")
    assert SHORT_TARGETS["music playlist create"] == (
        "musique",
        "playlist",
        "sauvegarder",
    )


def test_music_direct_actions_have_expected_french_names():
    expected = {
        "play": "jouer",
        "pause": "pause",
        "resume": "reprendre",
        "skip": "suivant",
        "previous": "precedent",
        "stop": "arreter",
        "nowplaying": "en-cours",
        "volume": "volume",
        "loop": "boucle",
        "shuffle": "melanger",
        "seek": "position",
        "autoplay": "lecture-auto",
    }
    for source, public in expected.items():
        assert MUSIC_LEAVES[source] == public



def test_music_leaf_rebuild_prevents_cross_bucket_suffixes(monkeypatch):
    import sentrix_canonical_command_surface as surface

    captured = {}
    original = surface.v98.semantic_leaf

    class Target:
        def __init__(self, original_name, leaf_name):
            self.original_name = original_name
            self.leaf_name = leaf_name

    # install() remplace semantic_leaf ; on capture la fonction active sans
    # dépendre d'un bot réel.
    surface.install()
    leaf = surface.v98.semantic_leaf

    assert leaf("musique", "file", Target("music remove", "retirer-2")) == "retirer"
    assert leaf("musique", "playlist", Target("music playlist clear", "vider-2")) == "vider"

    surface.v98.semantic_leaf = original



def test_generic_general_buckets_are_renamed_in_public_surface():
    import sentrix_canonical_command_surface as surface

    assert surface.BUCKETS[("config", "general")] == "reglages"
    assert surface.BUCKETS[("utility", "general")] == "pratiques"
    assert "general" not in {
        surface.BUCKETS[("config", "general")],
        surface.BUCKETS[("utility", "general")],
    }
