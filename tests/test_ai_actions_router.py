from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_actions


def test_ban_natural_language_and_reason():
    parsed = ai_actions.local_parse("tu peux bannir Tomioka pour spam stp")
    assert parsed is not None
    assert parsed.intent == "moderation.ban"
    assert parsed.slots["target"].casefold() == "tomioka"
    assert parsed.slots["reason"] == "spam stp"


def test_mute_understands_words_and_normalizes_duration():
    parsed = ai_actions.local_parse("mets Tomioka en mute pendant dix heures pour insultes")
    assert parsed is not None
    assert parsed.intent == "moderation.mute"
    assert parsed.slots["target"].casefold() == "tomioka"
    assert parsed.slots["duration"] == "10h"
    assert parsed.slots["reason"] == "insultes"


def test_unmute_beats_mute_pattern():
    parsed = ai_actions.local_parse("enlève le mute de Tomioka")
    assert parsed is not None
    assert parsed.intent == "moderation.unmute"


def test_purge_extracts_count_and_caps_at_100():
    parsed = ai_actions.local_parse("supprime les 300 derniers messages")
    assert parsed is not None
    assert parsed.intent == "moderation.purge"
    assert parsed.slots["count"] == 100


def test_dashboard_typo_is_understood():
    parsed = ai_actions.local_parse("donne moi le lien du dashbord")
    assert parsed is not None
    assert parsed.intent == "navigation.dashboard"


def test_duration_formats_cover_requested_examples():
    assert ai_actions.normalize_duration("10 minutes") == "10m"
    assert ai_actions.normalize_duration("1 heure") == "1h"
    assert ai_actions.normalize_duration("2 heures") == "2h"
    assert ai_actions.normalize_duration("24h") == "24h"
    assert ai_actions.normalize_duration("une semaine") == "7j"
    assert ai_actions.normalize_duration("30 jours") == "30j"


def _member(uid: int, name: str, display: str | None = None):
    return SimpleNamespace(
        id=uid,
        name=name,
        display_name=display or name,
        global_name=None,
        mention=f"<@{uid}>",
    )


class _Guild:
    def __init__(self, members):
        self.members = list(members)

    def get_member(self, uid):
        return next((m for m in self.members if int(m.id) == int(uid)), None)


def test_member_resolution_never_guesses_ambiguous_name():
    a = _member(111111111111111, "tomioka", "Tomioka")
    b = _member(222222222222222, "tomioka2", "Tomioka")
    result = ai_actions.resolve_member(_Guild([a, b]), "Tomioka")
    assert result.member is None
    assert {m.id for m in result.ambiguous} == {a.id, b.id}


def test_member_resolution_accepts_unique_clear_match():
    a = _member(111111111111111, "tomioka", "Tomioka")
    b = _member(222222222222222, "someoneelse", "Someone Else")
    result = ai_actions.resolve_member(_Guild([a, b]), "Tomioka")
    assert result.member is a
    assert result.ambiguous == ()


def test_missing_duration_can_be_completed_by_followup():
    parsed = ai_actions.local_parse("mute Tomioka")
    assert parsed is not None
    assert ai_actions.missing_slots(parsed) == ("duration",)
    completed = ai_actions.merge_followup(parsed, "10 heures")
    assert completed.slots["duration"] == "10h"
    assert ai_actions.missing_slots(completed) == ()


def test_command_rendering_reuses_existing_commands():
    member = _member(111111111111111, "tomioka")
    action = ai_actions.ParsedAction(
        "moderation.mute",
        {"target": "Tomioka", "duration": "2h", "reason": "spam"},
    )
    assert ai_actions.build_command_line(action, prefix="+", member=member) == "+mute <@111111111111111> 2h spam"


def test_ai_payload_is_fail_closed():
    assert ai_actions._validate_ai_payload({"intent": "owner.eval", "confidence": 100}) is None
    assert ai_actions._validate_ai_payload({"intent": "moderation.ban", "confidence": 20}) is None



def test_security_toggle_maps_to_existing_command():
    parsed = ai_actions.local_parse("SentriX active l'anti-spam")
    assert parsed is not None
    assert parsed.intent == "security.antispam"
    assert parsed.slots["state"] == "on"
    assert ai_actions.build_command_line(parsed, prefix="+") == "+antispam on"

    parsed = ai_actions.local_parse("désactive les liens")
    assert parsed is not None
    assert parsed.intent == "security.antilink"
    assert parsed.slots["state"] == "off"
    assert ai_actions.build_command_line(parsed, prefix="+") == "+antilink off"


def test_desktop_open_app_never_becomes_a_discord_command():
    parsed = ai_actions.local_parse("SentriX ouvre Roblox")
    assert parsed is not None
    assert parsed.intent == "desktop.open_app"
    assert parsed.slots["app"].casefold() == "roblox"
    assert ai_actions.build_command_line(parsed, prefix="+") is None


def _channel(uid: int, name: str, *, topic: str = "", category: str = ""):
    cat = SimpleNamespace(name=category) if category else None
    return SimpleNamespace(id=uid, name=name, topic=topic, category=cat)


def test_log_autoconfig_scores_channel_name_topic_and_category_without_writing():
    guild = SimpleNamespace(text_channels=[
        _channel(1, "sanctions", topic="Logs de modération"),
        _channel(2, "logs-messages"),
        _channel(3, "voice-logs"),
        _channel(4, "ticket-logs"),
        _channel(5, "general"),
    ])
    proposals = ai_actions.propose_log_routes(guild)
    by_category = {p.category: p.channel_id for p in proposals}
    assert by_category["moderation"] == 1
    assert by_category["messages"] == 2
    assert by_category["voice"] == 3
    assert by_category["tickets"] == 4


def test_log_autoconfig_refuses_ambiguous_equal_matches():
    guild = SimpleNamespace(text_channels=[
        _channel(10, "logs-moderation-a"),
        _channel(11, "logs-moderation-b"),
    ])
    proposals = ai_actions.propose_log_routes(guild)
    assert not any(p.category == "moderation" for p in proposals)


def test_log_autoconfig_phrase_is_not_misread_as_generic_setup():
    parsed = ai_actions.local_parse("SentriX configure mes logs")
    assert parsed is not None
    assert parsed.intent == "config.logs.auto"



def test_setup_section_is_extracted_without_losing_navigation_intent():
    parsed = ai_actions.local_parse("SentriX ouvre les paramètres d'économie")
    assert parsed is not None
    assert parsed.intent == "navigation.setup"
    assert parsed.slots["section"] == "economy"


def test_sanction_history_uses_full_modhistory_command_not_warning_list():
    parsed = ai_actions.local_parse("montre-moi les sanctions de Tomioka")
    assert parsed is not None
    assert parsed.intent == "moderation.history"
    member = _member(111111111111111, "tomioka")
    assert ai_actions.build_command_line(parsed, prefix="+", member=member) == "+modhistory <@111111111111111>"



def test_direct_log_route_extracts_category_and_channel_name():
    parsed = ai_actions.local_parse("mets les logs vocaux dans #logs-vocal")
    assert parsed is not None
    assert parsed.intent == "config.logs.route"
    assert parsed.slots["log_category"] == "voice"
    assert parsed.slots["channel"] == "#logs-vocal"


def test_text_channel_resolution_does_not_guess_ambiguous_channel():
    guild = SimpleNamespace(text_channels=[
        _channel(20, "logs-vocal"),
        _channel(21, "logs-vocal"),
    ])
    result = ai_actions.resolve_text_channel(guild, "#logs-vocal")
    assert result.channel is None
    assert len(result.ambiguous) == 2


def test_text_channel_resolution_accepts_unique_exact_channel():
    target = _channel(20, "logs-vocal")
    guild = SimpleNamespace(text_channels=[target, _channel(21, "general")])
    result = ai_actions.resolve_text_channel(guild, "#logs-vocal")
    assert result.channel is target



def test_tempban_is_distinct_from_permanent_ban():
    parsed = ai_actions.local_parse("bannis temporairement Tomioka pendant 2 jours pour raid")
    assert parsed is not None
    assert parsed.intent == "moderation.tempban"
    assert parsed.slots["duration"] == "2j"
    member = _member(111111111111111, "tomioka")
    assert ai_actions.build_command_line(parsed, prefix="+", member=member) == "+tempban <@111111111111111> 2j raid"


def test_unban_requires_a_real_discord_id_and_keeps_context():
    parsed = ai_actions.local_parse("SentriX débannis 123456789012345678 pour erreur")
    assert parsed is not None
    assert parsed.intent == "moderation.unban"
    assert parsed.slots["user_id"] == "123456789012345678"
    assert ai_actions.build_command_line(parsed, prefix="+") == "+unban 123456789012345678 erreur"

    missing = ai_actions.local_parse("SentriX débannis cet utilisateur")
    assert missing is not None
    assert ai_actions.missing_slots(missing) == ("user_id",)
    completed = ai_actions.merge_followup(missing, "123456789012345678")
    assert ai_actions.build_command_line(completed, prefix="+") == "+unban 123456789012345678"



def test_pronoun_target_is_context_marker_not_a_guessed_member():
    parsed = ai_actions.local_parse("SentriX bannis-le")
    assert parsed is not None
    assert parsed.intent == "moderation.ban"
    assert parsed.slots["target"] == "__recent__"



def test_bare_action_gate_allows_commands_but_not_normal_chat():
    assert ai_actions.is_bare_action_candidate("ban Tomioka")
    assert ai_actions.is_bare_action_candidate("mute Tomioka 2h")
    assert ai_actions.is_bare_action_candidate("ouvre setup")
    assert ai_actions.is_bare_action_candidate("configure mes logs")
    assert not ai_actions.is_bare_action_candidate("tu penses quoi des bans sur Discord ?")
    assert not ai_actions.is_bare_action_candidate("comment fonctionne le mute ?")
