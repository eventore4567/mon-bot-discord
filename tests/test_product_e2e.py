"""Parcours complets sur le bot booté comme en production (lents : ~1 min chacun).

Suggestions : formulaire, votes, décision du staff, langue, permissions.
Sondages : formulaire, éditeur, sondage natif publié, forme rapide en préfixe.
Traduction : commande native, menu contextuel, langue de l'utilisateur, pannes, mentions.
Chaque scénario s'exécute dans son propre processus, avec sa base jetable.
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["suggestions_e2e.py", "poll_e2e.py", "translation_e2e.py", "log_echo_e2e.py", "welcome_e2e.py", "setup_suggestions_e2e.py", "afk_e2e.py", "security_policy_e2e.py", "mentions_e2e.py", "sentrix_plus_slash_e2e.py", "reminders_e2e.py", "trace_e2e.py", "suites_e2e.py", "config_journal_e2e.py", "ticket_memory_e2e.py", "economy_memory_e2e.py", "join_memory_e2e.py", "automod_memory_e2e.py", "levels_memory_e2e.py", "last_seen_e2e.py", "hackban_e2e.py", "setup_sweep.py", "ticket_panel_dashboard_e2e.py", "dashboard_guilds_e2e.py", "member_names_e2e.py", "slash_defer_e2e.py", "auto_roles_e2e.py", "fight_e2e.py", "spam_burst_e2e.py", "spam_levels_e2e.py", "setup_security_extras_e2e.py", "slash_suggestions_e2e.py", "fun_gif_e2e.py", "unused_commands_e2e.py", "rich_responses_e2e.py", "automod_default_on_e2e.py", "ticket_category_pick_e2e.py", "member_commands_default_e2e.py", "honeypot_e2e.py", "setup_security_honest_e2e.py", "ticket_open_reply_e2e.py", "ticket_close_reopen_e2e.py", "prefix_mirrors_e2e.py", "logs_setup_test_e2e.py", "setup_guide_e2e.py"])
def test_parcours_complet(scenario):
    env = dict(os.environ, DISCORD_TOKEN="ci.fake.token", PYTHONPATH=str(ROOT))
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / scenario)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    echecs = [line for line in result.stdout.splitlines() if "ÉCHEC" in line]
    assert result.returncode == 0 and not echecs, "\n".join(echecs) or result.stdout[-2000:] + result.stderr[-2000:]
