"""Régressions pour la personnalité adaptative finale de SentriX AI."""
from __future__ import annotations

import asyncio

from cogs import ai_personality_final as personality
from utils import ai_service


def test_serious_requests_stay_expert():
    assert personality.classify_tone("Explique-moi précisément comment fonctionne un bot Discord") == "expert"
    assert personality.classify_tone("Sois intelligent et analyse ce problème de code Python") == "expert"
    assert personality.classify_tone("Pourquoi mon script plante quand la base redémarre ?") == "expert"


def test_low_effort_messages_get_dry_mode():
    for text in ("rien", "osef", "bof", "mdr", "ok", "pk ?", "...", "?"):
        assert personality.classify_tone(text) == "dry", text


def test_hostility_without_request_gets_dry_mode():
    assert personality.classify_tone("t'es nul") == "dry"
    assert personality.classify_tone("ta gueule") == "dry"
    assert personality.classify_tone("tg") == "dry"
    assert personality.classify_tone("you are stupid") == "dry"


def test_hostile_messages_force_calm_sarcasm_not_submission():
    for text in ("tg", "ta gueule", "ferme-la", "shut up", "t'es nul"):
        instruction = personality.personality_instruction(text)
        assert "SARCASME CALME" in instruction, text
        assert "Réponds OBLIGATOIREMENT" in instruction, text
        assert "UNE phrase courte" in instruction, text
        assert "mots très simples" in instruction, text
        assert "comparaison absurde" in instruction, text
        assert "NE réponds PAS" in instruction, text
        assert "NE t'excuse PAS" in instruction, text
        assert "NE dis PAS « d'accord »" in instruction, text


def test_real_request_wins_over_hostility():
    assert personality.classify_tone("t'es nul mais explique moi comment corriger ce bug python") == "expert_edge"
    instruction = personality.personality_instruction(
        "t'es nul mais explique moi comment corriger ce bug python"
    )
    assert "Réponds complètement" in instruction
    assert "Ne refuse jamais d'aider" in instruction


def test_normal_greetings_do_not_force_sarcasm():
    for text in ("salut", "yo", "bonjour", "ça va"):
        assert personality.classify_tone(text) == "normal", text


def test_more_than_300_unique_local_sarcasm_variations_exist():
    assert personality.SARCASM_VARIATION_COUNT > 300
    assert personality.SARCASM_VARIATION_COUNT == len(personality._SARCASM_VARIATIONS)
    assert len(set(personality._SARCASM_VARIATIONS)) == personality.SARCASM_VARIATION_COUNT


def test_dry_policy_uses_simple_absurd_comparisons_for_pointless_messages():
    instruction = personality.personality_instruction("pk ?")
    assert "SARCASME CALME" in instruction
    assert "UNE phrase courte" in instruction
    assert "comparaison absurde" in instruction
    assert "Pas de vocabulaire professionnel" in instruction
    assert "INSPIRATION DE STYLE" in instruction
    assert f"{personality.SARCASM_VARIATION_COUNT} combinaisons" in instruction


def test_dry_policy_has_safety_bounds():
    instruction = personality.personality_instruction("rien")
    assert "Aucune menace" in instruction
    assert "caractéristique personnelle sensible" in instruction
    assert "ne copie" in instruction

    hostile = personality.personality_instruction("tg")
    assert "Aucune menace" in hostile
    assert "aucun slur" in hostile
    assert "caractéristique personnelle sensible" in hostile
    assert "N'encourage pas le harcèlement" in hostile


def test_inspiration_is_small_even_with_360_plus_variations():
    inspiration = personality._sarcasm_inspiration(sample_size=6)
    bullets = [line for line in inspiration.splitlines() if line.startswith("- ")]
    assert len(bullets) == 6
    assert len(set(bullets)) == 6


def test_generate_wrapper_injects_tone_without_changing_prompt():
    original = ai_service.generate
    calls = []

    async def fake_generate(prompt, *args, **kwargs):
        calls.append((prompt, kwargs))
        return "ok"

    try:
        ai_service.generate = fake_generate
        assert personality.install() is True
        wrapped = ai_service.generate
        result = asyncio.run(wrapped("tg", instructions="BASE"))
        assert result == "ok"
        assert calls[0][0] == "tg"
        assert calls[0][1]["instructions"].startswith("BASE\n\n")
        assert "SARCASME CALME" in calls[0][1]["instructions"]
        assert "INSPIRATION DE STYLE" in calls[0][1]["instructions"]
    finally:
        ai_service.generate = original


if __name__ == "__main__":
    test_serious_requests_stay_expert()
    test_low_effort_messages_get_dry_mode()
    test_hostility_without_request_gets_dry_mode()
    test_hostile_messages_force_calm_sarcasm_not_submission()
    test_real_request_wins_over_hostility()
    test_normal_greetings_do_not_force_sarcasm()
    test_more_than_300_unique_local_sarcasm_variations_exist()
    test_dry_policy_uses_simple_absurd_comparisons_for_pointless_messages()
    test_dry_policy_has_safety_bounds()
    test_inspiration_is_small_even_with_360_plus_variations()
    test_generate_wrapper_injects_tone_without_changing_prompt()
    print("ai personality final: ok")
