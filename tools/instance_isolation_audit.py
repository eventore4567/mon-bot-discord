#!/usr/bin/env python3
"""Gate CI : isolation SentriX/Bot'Odboug et optimisations IA V2."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Environnement propre : le comportement historique du service principal doit rester stable.
for name in ("BOT_INSTANCE_KEY", "BOT_BRAND_LABEL", "BOT_DISPLAY_NAME", "BOT_WAKE_WORDS", "RAILWAY_SERVICE_NAME"):
    os.environ.pop(name, None)

from utils import instance_identity

assert instance_identity.brand_label() == "SentriX"
assert instance_identity.instance_key() == "sentrix"
assert instance_identity.display_name() == ""
assert instance_identity.storage_key("counter:test") == "sentrix:sentrix:counter:test"

# Railway doit reconnaître Bot'Odboug sans configuration manuelle supplémentaire.
os.environ["RAILWAY_SERVICE_NAME"] = "[+] Bot'Odboug |"
assert instance_identity.brand_label() == "Odboug"
assert instance_identity.instance_key() == "odboug"
assert instance_identity.display_name() == "[+] Bot'Odboug |"
assert "Odboug" in instance_identity.wake_words()
assert instance_identity.storage_key("lease:test") == "sentrix:odboug:lease:test"
assert "Odboug" in instance_identity.brand_text("SentriX / UTILITAIRES")

# Une clé explicite est prioritaire et stable même si Railway renomme le service.
os.environ["BOT_INSTANCE_KEY"] = "odboug-production"
os.environ["RAILWAY_SERVICE_NAME"] = "service-renomme"
assert instance_identity.instance_key() == "odboug-production"
assert instance_identity.storage_key("x") == "sentrix:odboug-production:x"

# Pour les tests de schéma ci-dessous on revient à la clé recommandée Odboug.
os.environ["BOT_INSTANCE_KEY"] = "odboug"
os.environ["BOT_BRAND_LABEL"] = "Odboug"

from utils.durable_database import DurableDatabaseReplica, PG_SCHEMA
from utils.enterprise_infra import EnterpriseInfra

assert "instance_key TEXT NOT NULL DEFAULT 'sentrix'" in PG_SCHEMA
assert "idx_sentrix_main_db_snapshots_instance_time" in PG_SCHEMA
replica = DurableDatabaseReplica("/tmp/odboug-isolation-ci.db")
assert replica.instance_key == "odboug"

infra = EnterpriseInfra()
assert infra.instance_key == "odboug"

# L'identité injectée dans le moteur IA doit suivre l'instance sans modifier le code partagé.
from cogs import ai_reliability

prompt = ai_reliability._instance_system_prompt()
assert "Odboug AI" in prompt
assert "SentriX AI" not in prompt
assert 1 <= ai_reliability.AI_CONCURRENCY <= 32
assert 2 <= ai_reliability.SETTINGS_CACHE_TTL <= 300


async def check_health() -> None:
    health = await infra.health()
    assert health["instance_key"] == "odboug"
    assert health["postgres_online"] is False
    assert health["redis_online"] is False


asyncio.run(check_health())
print("OK: identités séparées, namespaces Redis/PostgreSQL, snapshots isolés et IA V2 multi-instance validés")
