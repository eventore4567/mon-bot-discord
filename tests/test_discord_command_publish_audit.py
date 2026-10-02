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
    return SimpleNamespace(
        name=name,
        options=list(options),
        type=option_type,
    )


def test_post_sync_audit_matches_real_musique_tree():
    local_tree = FakeTree(
        [
            local(
                "musique",
                local("jouer"),
                local(
                    "playlist",
                    local("sauvegarder"),
                    local("importer"),
                ),
            ),
            local("aide"),
        ]
    )

    synced = [
        remote(
            "musique",
            remote("jouer", option_type=1),
            remote(
                "playlist",
                remote("sauvegarder", option_type=1),
                remote("importer", option_type=1),
                option_type=2,
            ),
        ),
        remote("aide"),
    ]

    audit = audit_published_commands(local_tree, synced)

    assert audit.matches is True
    assert "/musique" == f"/{audit.musique_paths[0]}"
    assert "musique playlist sauvegarder" in audit.remote_paths
    assert "musique playlist importer" in audit.remote_paths
    assert audit.legacy_music_paths == ()
    assert audit.aide_paths == ("aide",)
    assert audit.legacy_help_paths == ()


def test_post_sync_audit_detects_legacy_music_and_remote_drift():
    tree = FakeTree([local("musique"), local("aide")])
    synced = [remote("music"), remote("aide")]

    audit = audit_published_commands(tree, synced)

    assert audit.matches is False
    assert audit.missing_paths == ("musique",)
    assert audit.unexpected_paths == ("music",)
    assert audit.legacy_music_paths == ("music",)
    assert audit.musique_paths == ()


def test_root_only_discord_response_compares_roots_without_fake_subcommand_gaps():
    tree = FakeTree(
        [
            local("musique", local("jouer"), local("pause")),
            local("aide"),
        ]
    )
    # Certaines versions de discord.py ne développent pas les options dans les
    # AppCommand renvoyées par sync().
    synced = [remote("musique"), remote("aide")]

    audit = audit_published_commands(tree, synced)

    assert audit.matches is True
    assert audit.missing_paths == ()
    assert audit.unexpected_paths == ()



def test_post_sync_audit_detects_legacy_help_instead_of_aide():
    tree = FakeTree([local("aide")])
    synced = [remote("help")]

    audit = audit_published_commands(tree, synced)

    assert audit.matches is False
    assert audit.aide_paths == ()
    assert audit.legacy_help_paths == ("help",)
    assert audit.missing_paths == ("aide",)
    assert audit.unexpected_paths == ("help",)
