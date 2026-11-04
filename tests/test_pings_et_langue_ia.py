"""03/11/2026 : « enlève les pings inutiles » et « pas tout est en anglais »."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

ROOT = Path(__file__).resolve().parents[1]


def test_les_reponses_de_commande_ne_pinguent_plus_par_defaut():
    from cogs import final_interaction_policy as fip

    source = (ROOT / "cogs/final_interaction_policy.py").read_text(encoding="utf-8")
    assert 'kwargs.get("allowed_mentions") is None and root not in PING_ROOTS' in source
    assert "kwargs[\"allowed_mentions\"] = discord.AllowedMentions.none()" in source
    # Les commandes faites pour prévenir quelqu'un gardent leurs pings.
    for racine in ("say", "giveaway", "remind", "ticket"):
        assert racine in fip.PING_ROOTS
    for racine in ("balance", "leaderboard", "userinfo", "ban"):
        assert racine not in fip.PING_ROOTS


def test_repondre_a_un_message_ne_notifie_plus_son_auteur():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "replied_user=False" in main


def test_l_ia_repond_en_anglais_sur_un_serveur_anglais(monkeypatch):
    from cogs import ai as ai_cog
    from cogs import language_runtime

    async def faux_build(bot, *, user_id, author_name, creator_cache):
        return "BASE", creator_cache

    langues = {1: "en", 2: "fr"}

    async def fausse_langue(bot, guild_id):
        return langues[guild_id]

    monkeypatch.setattr(ai_cog, "build_system_instructions", faux_build)
    monkeypatch.setattr(language_runtime, "get_language", fausse_langue)
    cog = SimpleNamespace(bot=object(), _creator_cache=None)
    build = ai_cog.Ai._build_system_instructions
    en = asyncio.run(build(cog, 5, "tomioka", 1))
    fr = asyncio.run(build(cog, 5, "tomioka", 2))
    sans = asyncio.run(build(cog, 5, "tomioka"))
    assert "ANGLAIS" in en and en.startswith("BASE")
    assert fr == "BASE" and sans == "BASE"
