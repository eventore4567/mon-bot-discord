"""Gate CI des améliorations Production V9 du bot Discord."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cogs import game_seasons_v9, moderation_advisor_v9, production_observability_v9


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    # Les schémas ajoutés doivent rester valides indépendamment de la base de production.
    conn = sqlite3.connect(":memory:")
    for module in (production_observability_v9, game_seasons_v9, moderation_advisor_v9):
        conn.executescript(module.SCHEMA)
    conn.close()

    slash = text("cogs/slash_reliability_v7.py")
    for module_name in (
        "production_observability_v9",
        "ai_context_v9",
        "game_seasons_v9",
        "moderation_advisor_v9",
    ):
        assert module_name in slash, f"Production V9 non bootstrappé: {module_name}"
    assert slash.index("install(bot)") < slash.index("_install_production_v9(bot)")

    observability = text("cogs/production_observability_v9.py")
    assert "STUCK_COMMAND_SECONDS" in observability
    assert "production_command_metrics" in observability
    assert "_sentrix_production_v9_error_metrics" in observability
    assert "production_v9_health_snapshot" in observability
    assert "security_health" in observability

    ai_context = text("cogs/ai_context_v9.py")
    assert "_sentrix_ai_context_v9" in ai_context
    assert "build_server_context" in ai_context
    assert "OPENAI_API_KEY" not in ai_context
    assert "command_observability_v9.setup" in ai_context

    isolated = text("cogs/command_observability_v9.py")
    assert "production_command_events_v9" in isolated
    assert "production_v9_health_snapshot" in isolated
    assert "CREATE TABLE IF NOT EXISTS production_command_metrics" not in isolated

    games = text("cogs/game_seasons_v9.py")
    assert "game_season_scores_v2" in games
    assert "game_mission_progress_v2" in games
    assert "bonus_awarded=0" in games
    assert "rowcount" in games, "Le bonus de mission doit être protégé contre les doubles crédits"
    # La commande a ete renommee season -> gameseason (commit 0a9c254) pour ne pas
    # entrer en collision avec le groupe `season` de cogs/v17_ai_economy_games.py.
    # L'intention de la verification reste la meme : c'est bien une commande
    # prefixe simple, ce que confirment les deux assertions suivantes.
    assert '@commands.command(name="gameseason"' in games
    assert "@commands.hybrid_command" not in games
    assert "@app_commands.command" not in games

    moderation = text("cogs/moderation_advisor_v9.py")
    assert "moderation_risk_snapshots_v2" in moderation
    assert "Aucune sanction automatique" in moderation
    assert "security_risk" in moderation

    health = text("web/production_health.py")
    assert "production_v9_health_snapshot" in health
    assert 'payload["production_v9"]' in health

    # Les améliorations tickets déjà existantes ne doivent pas régresser : fermeture avec
    # raison, transcript unique, notation, priorité et IA ticket du centre Engagement.
    tickets = text("cogs/tickets.py")
    for marker in (
        "CloseReasonModal",
        "generate_transcript",
        "RatingView",
        "claimed_by",
        "priority",
        "ticket_delete_delay",
    ):
        assert marker in tickets, f"Régression ticket: {marker}"
    engagement_web = text("web/engagement_hub.py")
    engagement_cog = text("cogs/engagement_suite.py")
    assert "api_ticket_summary" in engagement_web
    assert "summarize_ticket" in engagement_cog

    # L'économie garde ses protections atomiques/anti-abus existantes pendant que V9 ajoute
    # les saisons et missions sans créer de seconde monnaie.
    excellence = text("cogs/bot_excellence_runtime.py")
    mastery = text("cogs/bot_mastery_runtime.py")
    rewards = text("utils/game_rewards.py")
    assert "_install_economy_atomicity" in excellence
    assert "economy_abuse" in mastery
    assert "reward_game_winner" in rewards
    assert "record_game_reward" in rewards

    print("OK: Production V9 — observabilité, diagnostic, IA, modération, tickets, jeux et économie vérifiés")


if __name__ == "__main__":
    main()
