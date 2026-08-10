#!/usr/bin/env python3
"""Gate d'acceptation utilisateur SentriX.

Cette suite complète les audits techniques : elle vérifie les parcours que voient réellement
les membres/staff sans exécuter d'actions dangereuses sur un vrai serveur Discord. Elle charge
le bot complet avec une base temporaire, contrôle les commandes et permissions visibles,
la navigation +help, les jeux, le dashboard, la persistance après redémarrage et les garde-fous
qui doivent rester actifs en production.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database


MEMBER_JOURNEYS = {
    "demarrage": ("help", "ping", "avatar", "userinfo", "membercount"),
    "outils": ("poll", "remind", "translate", "weather", "suggest", "afk"),
    "ia": ("sentrix", "image", "explain", "rewrite", "code"),
    "economie": ("balance", "daily", "weekly", "work", "pay", "shop", "buy", "inventory", "deposit", "withdraw"),
    "profil": ("level", "profile", "rep", "reputation", "voice-time"),
    "tickets": ("ticket",),
    "evenements": ("giveaway-list", "event-join", "event-list", "tournament-join", "tournament-list"),
    "invites": ("invites", "invite-leaderboard", "invited-by"),
    "musique": ("join", "play", "queue", "nowplaying"),
    "jeux_classiques": ("rps", "guess-number", "trivia", "blackjack", "slots"),
    "jeux_recuperes": ("coinflip", "dice", "luckyroll", "connect4", "adventure", "gameprofile", "gametop", "dailygames"),
}

STAFF_JOURNEYS = {
    "moderation": ("ban", "unban", "mute", "warn"),
    "configuration": ("setup", "create-server", "rolepanel", "logs"),
    "securite": ("security", "health"),
    "evenements": ("giveaway-create", "notifs-ping"),
    "jeux": ("gamesetup",),
}

OWNER_JOURNEYS = ("bl", "sync", "setstatus")

RECOVERED_GAMES = {
    "coinflip", "dice", "luckyroll", "highlow", "memory", "reaction",
    "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype", "duel",
    "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",
    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",
    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure",
    "hunt", "explore", "gamehistory", "gameprofile", "gamestats", "gametop",
    "dailygames", "gamesetup",
}


async def persistence_journey(path: str) -> None:
    """Simule un membre/staff avant puis après un redémarrage du conteneur."""
    guild_id = 8844001
    user_id = 8844002
    moderator_id = 8844003
    channel_id = 8844004

    db = Database(path)
    await db.connect()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO guild_config (guild_id,prefix) VALUES (?,?)",
            (guild_id, "+"),
        )
        await db.execute(
            "INSERT INTO warnings (guild_id,user_id,moderator_id,reason,timestamp) VALUES (?,?,?,?,?)",
            (guild_id, user_id, moderator_id, "acceptance-warning", 1786332000),
        )
        await db.execute(
            "INSERT OR REPLACE INTO economy (guild_id,user_id,cash,bank) VALUES (?,?,?,?)",
            (guild_id, user_id, 2500, 7500),
        )
        await db.execute(
            "INSERT INTO tickets (guild_id,channel_id,user_id,status,created_at) VALUES (?,?,?,?,?)",
            (guild_id, channel_id, user_id, "ouvert", 1786332000),
        )
    finally:
        await db.close()

    reopened = Database(path)
    await reopened.connect()
    try:
        prefix = await reopened.fetchone(
            "SELECT prefix FROM guild_config WHERE guild_id=?", (guild_id,)
        )
        warning = await reopened.fetchone(
            "SELECT reason FROM warnings WHERE guild_id=? AND user_id=? ORDER BY rowid DESC LIMIT 1",
            (guild_id, user_id),
        )
        economy = await reopened.fetchone(
            "SELECT cash,bank FROM economy WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        ticket = await reopened.fetchone(
            "SELECT status FROM tickets WHERE guild_id=? AND channel_id=?", (guild_id, channel_id)
        )
        quick = await reopened.fetchone("PRAGMA quick_check")

        assert prefix and prefix["prefix"] == "+", "préfixe perdu après redémarrage"
        assert warning and warning["reason"] == "acceptance-warning", "warning perdu après redémarrage"
        assert economy and int(economy["cash"]) == 2500 and int(economy["bank"]) == 7500, "solde économie perdu après redémarrage"
        assert ticket and ticket["status"] == "ouvert", "ticket perdu après redémarrage"
        assert quick and str(quick[0]).casefold() == "ok", "SQLite quick_check en échec"
    finally:
        await reopened.close()


async def runtime_journey(path: str) -> dict[str, int | float]:
    os.environ["DATABASE_PATH"] = path

    import main
    from cogs import command_catalog_cleanup, command_no_emoji_runtime, command_response_guard, help_complete
    import web
    from web import dashboard, enterprise_suite, operations_center

    bot = main.BotAllInOne()
    await bot.db.connect()
    started = time.perf_counter()
    loaded = 0
    try:
        for extension in main.EXTENSIONS:
            await bot.load_extension(extension)
            loaded += 1
        bot._prune_redundant_commands()
        boot_seconds = time.perf_counter() - started

        assert loaded == len(main.EXTENSIONS), f"extensions chargées: {loaded}/{len(main.EXTENSIONS)}"
        assert boot_seconds < 25.0, f"chargement des cogs anormalement lent: {boot_seconds:.2f}s"

        active = list(bot.walk_commands())
        names = [cmd.qualified_name.casefold() for cmd in active]
        assert len(names) == len(set(names)), "commandes texte/hybrides dupliquées"

        member_checked = 0
        for journey, commands in MEMBER_JOURNEYS.items():
            for name in commands:
                command = bot.get_command(name)
                assert command is not None, f"parcours membre {journey}: +{name} absent"
                assert name in main.PUBLIC_COMMANDS, f"parcours membre {journey}: +{name} bloqué par la politique d'accès"
                category = help_complete._category_for(command)
                assert category.key != "other", f"parcours membre {journey}: +{name} mal classé dans +help"
                member_checked += 1

        staff_checked = 0
        for journey, commands in STAFF_JOURNEYS.items():
            for name in commands:
                command = bot.get_command(name)
                assert command is not None, f"parcours staff {journey}: +{name} absent"
                assert name in main.KNOWN_PERMISSION_COMMANDS, f"parcours staff {journey}: +{name} sans politique explicite"
                assert name not in main.PUBLIC_COMMANDS, f"parcours staff {journey}: +{name} rendu public par erreur"
                category = help_complete._category_for(command)
                assert category.key != "other", f"parcours staff {journey}: +{name} mal classé dans +help"
                staff_checked += 1

        for name in OWNER_JOURNEYS:
            command = bot.get_command(name)
            assert command is not None, f"commande propriétaire +{name} absente"
            assert name in main.OWNER_ONLY_COMMANDS, f"commande propriétaire +{name} n'est plus owner-only"

        # Les anciennes commandes fusionnées ne doivent pas réapparaître. Leur destination
        # canonique (+setup ou +security) doit en revanche rester accessible.
        merged_checked = 0
        for old_name, target in command_catalog_cleanup.MERGED_COMMAND_TARGETS.items():
            assert bot.get_command(old_name) is None, f"ancienne commande fusionnée +{old_name} réapparue"
            target_root = target.split()[0]
            assert bot.get_command(target_root) is not None, f"destination +{target_root} absente pour +{old_name}"
            merged_checked += 1

        missing_games = sorted(name for name in RECOVERED_GAMES if bot.get_command(name) is None)
        assert not missing_games, "jeux récupérés absents: " + ", ".join(missing_games)
        for name in sorted(RECOVERED_GAMES - {"gamesetup"}):
            command = bot.get_command(name)
            assert name in main.PUBLIC_COMMANDS, f"jeu +{name} non public"
            assert help_complete._category_for(command).key == "games", f"jeu +{name} hors catégorie Jeux"
        assert help_complete._category_for(bot.get_command("gamesetup")).key == "configuration"

        slash_roots = list(bot.tree.get_commands())
        assert len(slash_roots) <= 95, f"budget slash dépassé: {len(slash_roots)} racines"

        assert command_response_guard._INSTALLED, "filet de réponse des commandes absent"
        assert command_no_emoji_runtime._INSTALLED, "politique sans emoji non installée"
        assert getattr(bot, "_sentrix_no_emoji_commands", False), "politique sans emoji non appliquée au bot"
        cleaned = command_no_emoji_runtime.clean_text("Test ✅ 🎮")
        assert cleaned == "Test", f"nettoyage emoji inattendu: {cleaned!r}"

        for event in ("on_command", "on_command_completion", "on_command_error", "on_interaction", "on_app_command_completion"):
            assert bot.extra_events.get(event, []), f"listener UX manquant: {event}"

        html = dashboard.INDEX_HTML
        assert 'id="sentrix-simple-dashboard-js"' in html, "mode simple dashboard absent"
        assert 'id="sentrix-core-recovery"' in html, "récupération dashboard au boot absente"
        assert "Mode simple" in html and "Mode avancé" in html, "bascule simple/avancé absente"
        assert "Que voulez-vous faire ?" in html, "accueil guidé dashboard absent"
        assert "loginButton" in html, "bouton de connexion Discord absent"
        assert "Envoyer le recours" in enterprise_suite.APPEAL_HTML, "parcours recours de ban absent"
        assert "OPERATIONS_HTML" in dir(operations_center), "page Operations absente"
        assert web is not None

        return {
            "extensions": loaded,
            "commands": len(active),
            "slash_roots": len(slash_roots),
            "member_checks": member_checked,
            "staff_checks": staff_checked,
            "merged_checks": merged_checked,
            "boot_seconds": round(boot_seconds, 3),
        }
    finally:
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result


async def main_audit() -> None:
    with tempfile.TemporaryDirectory(prefix="sentrix-user-acceptance-") as folder:
        root = pathlib.Path(folder)
        await persistence_journey(str(root / "persistence.db"))
        metrics = await runtime_journey(str(root / "runtime.db"))

    print(
        "User acceptance: "
        f"{metrics['extensions']} extensions, {metrics['commands']} commandes, "
        f"{metrics['slash_roots']} racines slash, "
        f"{metrics['member_checks']} contrôles membre, {metrics['staff_checks']} contrôles staff, "
        f"{metrics['merged_checks']} routes fusionnées, boot={metrics['boot_seconds']}s"
    )
    print("OK: parcours membre/staff, routes fusionnées, jeux, permissions, dashboard, no-emoji et persistance après redémarrage validés")


if __name__ == "__main__":
    asyncio.run(main_audit())
