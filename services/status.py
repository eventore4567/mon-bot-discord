"""StatusService — Core V2, Phase 4 (docs/core-v2-plan.md).

/bot-status (le corps réellement exécuté vit dans cogs/visual_experience_v5.py
::build_status_embed — cogs/stats.py::system_status ne s'exécute jamais en
production, voir docs/core-v2-audit-technical-debt.md #15) mélangeait le calcul
de santé (latence, base de données joignable, cogs IA/Musique chargés, seuil
"nominal") avec la construction du discord.Embed. Cette fonction extrait le
calcul pur pour qu'il soit testable sans jamais instancier Discord ni sa base
de données réelle.

Contrairement à services/moderation.py, il n'y a ici aucune action Discord
mutante ni écriture en base à protéger après coup (section 17) — c'est une
sonde en LECTURE SEULE. Le seul garde-fou déjà présent dans le code existant
et conservé à l'identique : une base de données injoignable rend
``database_ok=False`` plutôt que de laisser l'exception remonter (SELECT 1
échoue silencieusement, comme avant).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils import helpers


@dataclass
class HealthSnapshot:
    latency_ms: int
    database_ok: bool
    ai_ok: bool
    music_ok: bool
    healthy_count: int
    is_nominal: bool
    command_count: int


async def compute_health_snapshot(bot: Any) -> HealthSnapshot:
    """Sonde de santé utilisée par /bot-status (et son bouton "Actualiser").

    Le ping base de données reste try/except ici exactement comme avant :
    une base injoignable donne database_ok=False, pas une exception."""
    latency_ms = helpers.latence_ms(bot)
    database_ok = False
    try:
        row = await bot.db.fetchone("SELECT 1 AS ok")
        database_ok = bool(row and row["ok"] == 1)
    except Exception:
        pass
    ai_ok = bot.get_cog("Ai") is not None
    music_ok = bot.get_cog("Music") is not None
    healthy_count = sum(1 for item in (database_ok, ai_ok, music_ok) if item)
    is_nominal = healthy_count == 3 and latency_ms < 300

    return HealthSnapshot(
        latency_ms=latency_ms,
        database_ok=database_ok,
        ai_ok=ai_ok,
        music_ok=music_ok,
        healthy_count=healthy_count,
        is_nominal=is_nominal,
        command_count=len(bot.commands),
    )
