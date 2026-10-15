"""Contrats des commandes Fun : résultats fictifs, GIFs pertinents et anti-spam."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs import fun_social as fun


def member(user_id: int, name: str = "Alex"):
    return SimpleNamespace(
        id=user_id, mention=f"<@{user_id}>", display_name=name,
        display_avatar=SimpleNamespace(url=f"https://cdn.discordapp.com/avatars/{user_id}/demo.png"),
    )


def fake_context(user_id: int = 1):
    ctx = SimpleNamespace(
        author=member(user_id), guild=SimpleNamespace(id=123),
        send=AsyncMock(),
    )
    return ctx


def test_catalog_has_over_sixty_distinct_actions_and_real_gif_categories():
    assert len(fun.ACTIONS) >= 60
    assert len(fun.ACTIONS) == len(fun.REACTIONS) + len(fun.SOLO) + len(fun.FUN_MODES)
    assert fun.REACTIONS["hug"][3] == "hug"
    assert fun.REACTIONS["slap"][3] == "slap"
    assert fun.REACTIONS["kiss"][3] == "kiss"
    assert fun.SOLO["dance"][3] == "dance"
    assert set(fun.SHORTCUTS).issubset(fun.ACTIONS)
    assert len(fun.SHORTCUTS) >= 16


def test_gif_urls_are_strictly_from_expected_action_and_host():
    assert fun.gif_url_is_safe("https://nekos.best/api/v2/hug/12345.gif", "hug")
    assert not fun.gif_url_is_safe("https://nekos.best/api/v2/slap/12345.gif", "hug")
    assert not fun.gif_url_is_safe("https://nekos.best.evil.example/api/v2/hug/a.gif", "hug")
    assert not fun.gif_url_is_safe("http://nekos.best/api/v2/hug/a.gif", "hug")
    assert not fun.gif_url_is_safe("https://nekos.best:bad/api/v2/hug/a.gif", "hug")
    assert not fun.gif_url_is_safe("https://guest:secret@nekos.best/api/v2/hug/a.gif", "hug")


def test_fake_scores_are_stable_per_day_and_not_based_on_discord_data():
    assert fun.fixed_score(1, 2, "aura", limit=9999) == fun.fixed_score(1, 2, "aura", limit=9999)
    assert 0 <= fun.fixed_score(1, 2, "scan") <= 100
    assert 0 <= fun.fixed_score(1, 2, "aura", limit=9999) <= 9999


def test_hack_and_scan_are_clearly_fictional_and_do_not_expose_real_credentials():
    fake_hack = fun._profile_embed("hack", member(8), 123)
    # Toujours une simulation annoncée, jamais d'identifiant ni de mention, et
    # de vraies variations d'un lancement à l'autre (plus de « croissant-magique »).
    hacks = {fun._profile_embed("hack", member(8), 123).description for _ in range(12)}
    for text in hacks:
        assert "Simulation pour rire" in text and "aucune donnée réelle" in text
        assert "@" not in text and "mot de passe" not in text.lower()
        assert "croissant" not in text and "imaginaire" not in text.lower()
    assert len(hacks) > 1
    fake_scan = fun._profile_embed("scan", member(8), 123)
    assert "scan fictif" in fake_scan.title.lower()
    assert "fictif" in fake_scan.footer.text.lower() or "inventé" in fake_scan.footer.text.lower()
    assert "Profil détecté" in fake_scan.description and "imaginaire" not in fake_scan.description.lower()


def test_fun_menu_has_three_pages_and_discord_length_budget():
    for page in ("social", "solo", "fun"):
        e = fun.menu_embed(page)
        assert "SentriX Fun" in e.title
        assert len(e.description) <= 4096
        assert "actions disponibles" in e.footer.text


@pytest.mark.asyncio
async def test_hug_embeds_matching_gif_and_counter(monkeypatch):
    seen = []

    async def gif(category):
        seen.append(category)
        return f"https://nekos.best/api/v2/{category}/demo.gif", "Anime de test"

    monkeypatch.setattr(fun, "fetch_gif", gif)
    db = SimpleNamespace(execute=AsyncMock(), fetchone=AsyncMock(return_value={"total": 3}))
    cog = fun.FunSocial(SimpleNamespace(db=db))
    ctx = fake_context()
    await cog.run_action(ctx, "hug", member(2, "Camille"))
    assert seen == ["hug"]
    db.execute.assert_awaited_once()
    ctx.send.assert_awaited_once()
    kwargs = ctx.send.await_args.kwargs
    embed = kwargs["embed"]
    assert embed.image.url.endswith("/hug/demo.gif")
    assert "3 câlins" in embed.description
    assert "Anime de test" in embed.fields[0].value
    assert kwargs["allowed_mentions"].everyone is False


@pytest.mark.asyncio
async def test_aura_contains_score_avatar_and_matching_visual(monkeypatch):
    called = []

    async def gif(category):
        called.append(category)
        return f"https://nekos.best/api/v2/{category}/demo.gif", None

    monkeypatch.setattr(fun, "fetch_gif", gif)
    cog = fun.FunSocial(SimpleNamespace(db=None))
    ctx = fake_context()
    await cog.run_action(ctx, "aura", member(9, "Camille"))
    e = ctx.send.await_args.kwargs["embed"]
    assert "Aura" in e.title
    assert "points d'aura" in e.description
    assert "Camille" in e.title
    assert e.image.url.endswith("/smug/demo.gif")
    assert called == ["smug"]


@pytest.mark.asyncio
async def test_social_cooldown_applies_between_different_shortcuts(monkeypatch):
    async def gif(category):
        return None, None

    monkeypatch.setattr(fun, "fetch_gif", gif)
    cog = fun.FunSocial(SimpleNamespace(db=None))
    ctx = fake_context()
    await cog.run_action(ctx, "dance")
    await cog.run_action(ctx, "cry")
    assert ctx.send.await_count == 2
    assert "Patientez 4 secondes" in ctx.send.await_args.args[0]


def test_cog_is_loaded_before_visual_finalizer_and_help_category():
    root = Path(__file__).resolve().parents[1]
    source = (root / "main.py").read_text(encoding="utf-8")
    assert '"cogs.fun_social"' in source
    assert source.index('"cogs.fun_social"') < source.index('"cogs.visual_experience_v5"')
    from cogs.help import CATEGORY_NAMES
    assert CATEGORY_NAMES["FunSocial"] == "Fun"
    names = {c.name for c in fun.FunSocial.__cog_commands__}
    assert {"fun", "hug", "hack", "scan", "aura", "ship", "slap"}.issubset(names)


def test_aura_dit_l_evolution_et_le_rang_avec_une_jauge():
    from cogs import fun_social

    texte, score = fun_social._aura_texte(1, 42)
    assert "depuis hier" in texte and "Rang :" in texte and ("▰" in texte or "▱" in texte)
    assert 0 <= score <= 9999
    # Le score du jour est stable : deux consultations donnent le même nombre.
    assert fun_social._aura_texte(1, 42)[1] == score


def test_ship_nom_de_couple_jauge_et_message_selon_le_score():
    from types import SimpleNamespace

    from cogs import fun_social

    assert fun_social._nom_de_couple("Jayden", "Alice") == "Jayice"
    a = SimpleNamespace(id=1, mention="<@1>", display_name="Jayden")
    b = SimpleNamespace(id=2, mention="<@2>", display_name="Alice")
    texte = fun_social._ship_texte(1, a, b)
    assert "Nom de couple : **Jayice**" in texte and "%" in texte and ("▰" in texte or "▱" in texte)
    assert texte.count("_") >= 2, "un message adapté au score accompagne le pourcentage"
    # Même couple, même jour : même score, quel que soit l'ordre.
    assert fun_social._ship_texte(1, b, a).split("**")[3] == texte.split("**")[3]
