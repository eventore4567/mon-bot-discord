from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cogs" / "official_server_join_feed_v62.py"
INSTALLER = ROOT / "cogs" / "official_server_command_fix.py"


def test_v62_compiles_and_only_adds_join_listener() -> None:
    source = MODULE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(MODULE))
    assert 'bot.add_listener(announce_new_guild, "on_guild_join")' in source
    assert 'bot.add_listener' in source
    assert '"on_guild_remove"' not in source


def test_server_counter_is_not_refreshed_by_heartbeat() -> None:
    source = MODULE.read_text(encoding="utf-8")
    start = source.index("async def refresh_status_only")
    end = source.index("if not getattr(bot, \"_sentrix_join_feed_listener_v62\"", start)
    refresh = source[start:end]
    assert "statut-sentrix" in refresh
    assert "serveurs-sentrix" not in refresh
    assert "server_counter" not in refresh


def test_join_feed_is_installed_without_the_retired_create_server_command() -> None:
    """L'installateur dépendait de la commande ``create-server`` (retirée avec toutes les
    commandes de création de serveur) : le journal V62 doit rester installé sans elle."""
    source = INSTALLER.read_text(encoding="utf-8")
    assert "install_join_feed_v62(bot)" in source
    assert "install_binding_fix(bot)" in source
    assert 'get_command("create-server")' not in source
    assert "OFFICIAL_ALIASES" not in source


def test_old_static_counter_cleanup_is_narrow() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert '"sentrix sur discord" in title' in source
    assert "history(limit=50)" in source
    assert "message.author.id != runtime.bot.user.id" in source
