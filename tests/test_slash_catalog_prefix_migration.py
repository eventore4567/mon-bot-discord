"""Test the usable, compact slash surface and keep configuration in Setup."""
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import slash_catalog as catalog
from utils import unused_commands as _unused


def test_prefix_only_actions_get_clear_category_paths():
    mapped = {entry.source: entry.path for entry in catalog.CATALOG}
    expected = {
        "hackban": "moderation hackban",
        "unwarn": "moderation unwarn",
        "hide": "moderation hide",
                "blacklist-list": "protection blacklist",
        "mots-interdits-ajouter": "protection word-add",
        "antibot-allow": "protection bot-allow",
        "automod-history": "security history",
        "ticket-reopen": "tickets reopen",
        "tickettranscript": "tickets transcript",
        "verify-repair": "verification restore",
        "rolepanel-refresh": "role refresh",
        "reactionrole-add": "role add-button",
        "event-create": "events create",
        "tournament-create": "events tournament-create",
        "invite-stats": "invites stats",
        "staff-reminder": "staff remind",
        "dm": "user dm",
    }
    # Masquées faute d'usage le 16/10/2026 (utils/unused_commands.py) : hors du
    # menu, mais leur chemin reste défini pour le jour où on les remet.
    masked = {entry.source: entry.path for entry in catalog._MASQUEES_DU_MENU}
    for source, path in expected.items():
        if source in masked:
            assert masked[source] == path and source in catalog.RETIRED, (source, path)
            continue
        assert mapped.get(source) == path, (source, path, mapped.get(source))


def test_no_owner_tools_or_redundant_setup_commands_published():
    sources = {entry.source for entry in catalog.CATALOG}
    owner = {
        "bl", "blinfo", "unbl", "editbl", "setstatus", "status-rotate",
        "set-bot", "bot-servers", "bot-leave", "sync", "syncguild", "health",
    }
    setup_only = {
        "disablecommand", "enablecommand", "ignorechannel",
        "unignorechannel", "setwarnbanthreshold", "setwelcomechannel",
        "setgoodbyechannel", "setautorole", "logsetup", "ticketsetup",
        "setlevelchannel",
    }
    assert not (sources & owner)
    assert not (sources & setup_only)


def test_new_menu_is_compact_and_within_discord_limits():
    paths = [entry.path for entry in catalog.CATALOG]
    assert len(paths) == len(set(paths))
    # Le nombre exact bougeait à chaque vague de nettoyage et le test restait
    # en arrière : le 2026-10-23 il exigeait encore 281 alors que le catalogue
    # en comptait 250, et son propre commentaire donnait déjà 382 − 132 = 250.
    # Une garde de build rouge bloque TOUT déploiement, donc elle ne doit pas
    # dépendre d'un chiffre recopié à la main.
    #
    # Ce qui compte vraiment, ce sont les limites de Discord et le fait que le
    # menu reste compact — pas une valeur précise.
    masquees = [e for e in catalog.CATALOG if _unused.masquee(e.source)]
    visibles = len(paths) - len(masquees)
    assert visibles > 0, "le menu « / » ne doit pas être entièrement masqué"
    assert len(paths) <= 400, f"catalogue hors de proportion : {len(paths)} routes"
    assert len(catalog.entries_by_root()) <= 100, "Discord plafonne à 100 racines"
    assert len({path.split()[0] for path in paths}) <= 100
    assert all(len(path.split()) <= 3 for path in paths)
    for name in ("moderation", "security", "staff", "invites", "events"):
        assert any(path.startswith(name + " ") for path in paths)
    roots = catalog.entries_by_root()
    assert len(roots["moderation"]) <= 25
    assert all(
        len(set(e.path.split()[1] for e in entries)) <= 25
        for root, entries in roots.items()
        if all(len(e.path.split()) > 1 for e in entries)
    )



def test_member_staff_details_have_one_slash_entry():
    """The interactive moderation view already opens the same member_panel.

    Keep +member for legacy users but avoid a second public slash route.
    """
    sources = {entry.source: entry.path for entry in catalog.CATALOG}
    assert sources["modview"] == "moderation view"
    assert "member" not in sources
    assert "staff member" not in {entry.path for entry in catalog.CATALOG}


def test_no_duplicate_slash_sources_or_paths():
    from collections import Counter

    assert not [name for name, count in Counter(e.source for e in catalog.CATALOG).items() if count > 1]
    assert not [name for name, count in Counter(e.path for e in catalog.CATALOG).items() if count > 1]
