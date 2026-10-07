from __future__ import annotations

from types import SimpleNamespace

from utils.discord_command_publish_audit import audit_published_commands


class FakeTree:
    def __init__(self, roots):
        self.roots = list(roots)

    def get_commands(self):
        return list(self.roots)


def local(name, *children):
    return SimpleNamespace(name=name, commands=list(children))


def remote(name, *options, option_type=None):
    return SimpleNamespace(name=name, options=list(options), type=option_type)


def test_post_sync_audit_matches_real_english_tree():
    local_tree = FakeTree(
        [
            local(
                "music",
                local("play"),
                local(
                    "playlist",
                    local("create"),
                    local("import"),
                ),
            ),
            local("help"),
        ]
    )

    synced = [
        remote(
            "music",
            remote("play", option_type=1),
            remote(
                "playlist",
                remote("create", option_type=1),
                remote("import", option_type=1),
                option_type=2,
            ),
        ),
        remote("help"),
    ]

    audit = audit_published_commands(local_tree, synced)

    assert audit.matches is True
    assert audit.music_paths[0] == "music"
    assert "music playlist create" in audit.remote_paths
    assert "music playlist import" in audit.remote_paths
    assert audit.legacy_music_paths == ()
    assert audit.help_paths == ("help",)
    assert audit.legacy_help_paths == ()


def test_post_sync_audit_detects_legacy_french_music_and_remote_drift():
    tree = FakeTree([local("music"), local("help")])
    synced = [remote("musique"), remote("help")]

    audit = audit_published_commands(tree, synced)

    assert audit.matches is False
    assert audit.missing_paths == ("music",)
    assert audit.unexpected_paths == ("musique",)
    assert audit.legacy_music_paths == ("musique",)
    assert audit.music_paths == ()


def test_root_only_discord_response_compares_roots_without_fake_subcommand_gaps():
    tree = FakeTree(
        [
            local("music", local("play"), local("pause")),
            local("help"),
        ]
    )
    synced = [remote("music"), remote("help")]

    audit = audit_published_commands(tree, synced)

    assert audit.matches is True
    assert audit.missing_paths == ()
    assert audit.unexpected_paths == ()


def test_post_sync_audit_detects_legacy_french_help():
    tree = FakeTree([local("help")])
    synced = [remote("aide")]

    audit = audit_published_commands(tree, synced)

    assert audit.matches is False
    assert audit.help_paths == ()
    assert audit.legacy_help_paths == ("aide",)
    assert audit.missing_paths == ("help",)
    assert audit.unexpected_paths == ("aide",)
