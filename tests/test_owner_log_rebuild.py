"""Contrats statiques du reset global des logs et de l'assistance d'installation."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "cogs" / "owner_log_rebuild.py"
ARRIVAL_PATH = ROOT / "cogs" / "guild_arrival.py"

source = SOURCE_PATH.read_text(encoding="utf-8")
arrival = ARRIVAL_PATH.read_text(encoding="utf-8")
module = ast.parse(source)
ast.parse(arrival)

# La commande demandée existe réellement, reste préfixée et propriétaire uniquement.
assert 'name="reset-logs-all"' in source
assert "@checks.is_bot_owner()" in source
assert "hidden=True" in source

# Toutes les routes réellement émises ont un nouveau salon dédié.
for log_type in (
    "messages",
    "members",
    "roles",
    "server",
    "voice",
    "moderation",
    "automod",
    "tickets",
):
    assert f'("{log_type}",' in source, log_type

# La reconstruction bascule à la fois la compatibilité historique et log_settings,
# active chaque route puis la teste avant suppression des anciens salons.
assert "set_guild_config" in source
assert "log_service.set_log_channel" in source
assert "log_service.set_log_enabled" in source
assert "log_service.send_test_log" in source
assert "_rollback_routes" in source
assert "Les anciens salons ne seront supprimés qu'après" in source

# Le bouton d'aide exige une décision explicite d'un responsable du serveur.
assert 'custom_id="sentrix:setup-help:request:v1"' in source
assert "perms.administrator or perms.manage_guild" in source
assert "HELP_INVITE_MAX_AGE = 24 * 60 * 60" in source
assert "HELP_INVITE_MAX_USES = 1" in source
assert "max_age=HELP_INVITE_MAX_AGE" in source
assert "max_uses=HELP_INVITE_MAX_USES" in source

# Aucun on_guild_join ne doit fabriquer une invitation secrètement : la création reste
# dans la fonction appelée uniquement après clic du bouton administrateur.
owner_cog = next(
    node for node in module.body
    if isinstance(node, ast.ClassDef) and node.name == "OwnerLogRebuild"
)
on_join = next(
    node for node in owner_cog.body
    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "on_guild_join"
)
join_source = ast.get_source_segment(source, on_join) or ""
assert "create_invite" not in join_source

# Le module est effectivement chargé par une extension déjà présente au démarrage.
assert 'from .owner_log_rebuild import OwnerLogRebuild' in arrival
assert 'bot.get_cog("OwnerLogRebuild")' in arrival
assert "await bot.add_cog(OwnerLogRebuild(bot))" in arrival

print("owner log rebuild contracts: OK")
