from sentrix_canonical_command_surface import LEAVES, MUSIC_LEAVES, PLAYLIST_LEAVES, ROOTS


def test_canonical_roots_are_human_readable():
    assert ROOTS["music"] == "musique"
    assert ROOTS["security"] == "securite"
    assert ROOTS["config"] == "configuration"
    assert ROOTS["game"] == "jeux"
    assert ROOTS["level"] == "niveaux"


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
