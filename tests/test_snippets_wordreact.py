"""Nouveaux outils : mots complets et décisions de permission."""
from cogs.snippets import normal_name
from cogs.word_reactions import matches
from utils import access_matrix, slash_catalog
from cogs.recurring_messages import parse_interval, is_logs_channel
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from cogs.recurring_messages import is_reserved_channel


def test_snippet_names_are_strict():
    assert normal_name("Annonce-Staff") == "annonce-staff"
    assert normal_name("a") is None
    assert normal_name("@everyone") is None


def test_word_reactions_only_match_whole_words_and_ignore_accents():
    assert matches("HÉLLO, les amis", "hello")
    assert matches("Attention à la café !", "cafe")
    assert not matches("début de bonjourno", "bonjour")
    assert not matches("superbonjour", "bonjour")


def test_30_oct_decision_only_operational_snippet_is_slash():
    """Configuration dans /setup ; seul l'envoi opérationnel reste en /."""
    paths = {e.path: e.source for e in slash_catalog.CATALOG}
    assert paths["snippet send"] == "snippet send"
    assert not any(p.startswith("wordreact ") or p.startswith("recurring ") for p in paths)
    assert not any(p in paths for p in ("snippet create","snippet delete","snippet list"))
    from pathlib import Path
    view = (Path(__file__).resolve().parents[1] / "cogs/setup_experience_v74.py").read_text(encoding="utf-8")
    for page in ("snippets", "word_reactions", "recurring_messages"):
        assert ('"' + page + '"') in view


def test_staff_can_send_but_only_admin_can_create():
    assert access_matrix.access_tier("snippet") == "discord:manage_messages"
    assert access_matrix.access_tier("snippet create") == "categorie:configuration"
    assert access_matrix.access_tier("snippet delete") == "categorie:configuration"
    assert access_matrix.access_tier("wordreact") == "categorie:configuration"  # legacy internal source, no slash route



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


@pytest.mark.asyncio
async def test_recurring_rejects_configured_logs_even_with_generic_name():
    channel = SimpleNamespace(
        name="informations", id=123, category=None,
        guild=SimpleNamespace(id=777),
    )
    db = SimpleNamespace(fetchone=AsyncMock(return_value={"configured": 1}))
    bot = SimpleNamespace(db=db)
    assert await is_reserved_channel(bot, channel)
    db.fetchone.assert_awaited_once_with(
        "SELECT 1 AS configured FROM log_config "
        "WHERE guild_id=? AND channel_id=? AND enabled=1 LIMIT 1",
        (777, 123),
    )
