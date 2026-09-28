from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as automod_module


def test_discussion_about_free_nitro_is_not_sanctioned():
    assert automod_module._scam_hit("est-ce une arnaque le free nitro ?") is None


def test_official_discord_gift_domain_is_not_scam():
    assert (
        automod_module._scam_hit(
            "free nitro https://discord.gift/AbCdEf123"
        )
        is None
    )


def test_suspicious_nitro_domain_is_detected():
    hit = automod_module._scam_hit(
        "claim your nitro https://discord-nitro-free.example.com"
    )
    assert hit is not None
    assert "domaine suspect" in hit


def test_text_only_bait_without_call_to_action_is_not_enough():
    assert automod_module._scam_hit("free nitro") is None


def test_text_only_bait_with_call_to_action_is_detected():
    assert automod_module._scam_hit("free nitro claim maintenant") is not None


def test_image_result_requires_very_high_confidence():
    assert (
        automod_module._parse_scam_image_result(
            "SCAM|97|fake_nitro|Faux cadeau Nitro"
        )
        is None
    )
    assert (
        automod_module._parse_scam_image_result(
            "SCAM|98|fake_nitro|Faux cadeau Nitro avec lien de récupération"
        )
        == "fake_nitro: Faux cadeau Nitro avec lien de récupération"
    )


def test_image_result_rejects_unknown_category_and_uncertain():
    assert (
        automod_module._parse_scam_image_result(
            "SCAM|100|other|Quelque chose de suspect"
        )
        is None
    )
    assert (
        automod_module._parse_scam_image_result(
            "UNCERTAIN|100|fake_nitro|Pas certain"
        )
        is None
    )
