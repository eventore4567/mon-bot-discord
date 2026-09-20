from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_actions
from cogs.ai import Ai


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
    assert ai_actions.is_bare_action_candidate("ouvre-moi setup")
    assert ai_actions.is_bare_action_candidate("active l’anti-spam")
    assert ai_actions.is_bare_action_candidate("configure mes logs")
    assert not ai_actions.is_bare_action_candidate("tu penses quoi des bans sur Discord ?")
    assert not ai_actions.is_bare_action_candidate("comment fonctionne le mute ?")



def test_compact_duration_inside_full_sentence():
    parsed = ai_actions.local_parse("mut Tomioka 2h")
    assert parsed is not None
    assert parsed.intent == "moderation.mute"
    assert parsed.slots["target"].casefold() == "tomioka"
    assert parsed.slots["duration"] == "2h"


def test_natural_unmute_phrase_keeps_member_target():
    parsed = ai_actions.local_parse("SentriX enlève le mute de Tomioka")
    assert parsed is not None
    assert parsed.intent == "moderation.unmute"
    assert parsed.slots["target"].casefold() == "tomioka"



def test_dynamic_arguments_must_be_grounded_in_original_request():
    assert Ai._arguments_grounded_in_question(
        "donne le rôle VIP à Tomioka",
        "Tomioka VIP",
    )
    assert not Ai._arguments_grounded_in_question(
        "donne le rôle VIP à Tomioka",
        "Tomioka Administrateur",
    )
    assert not Ai._arguments_grounded_in_question(
        "ban cet utilisateur",
        "<@123456789012345678>",
    )


def test_voice_join_typos_become_real_native_action():
    for text in ("SentriX rejoint le vocal", "SentriX regoin une voc", "SentriX reg une voc"):
        parsed = ai_actions.local_parse(text)
        assert parsed is not None
        assert parsed.intent == "voice.join"
        assert ai_actions.missing_slots(parsed) == ()


def test_create_voice_channel_without_name_asks_followup():
    parsed = ai_actions.local_parse("SentriX crée une voc")
    assert parsed is not None
    assert parsed.intent == "channel.create_voice"
    assert ai_actions.missing_slots(parsed) == ("name",)
    completed = ai_actions.merge_followup(parsed, "Gaming")
    assert completed.slots["name"] == "Gaming"
    assert ai_actions.missing_slots(completed) == ()


def test_native_role_and_cross_channel_message_parsing():
    role = ai_actions.local_parse("SentriX donne le role VIP à Tomioka")
    assert role is not None
    assert role.intent == "role.give"
    assert role.slots["role"].casefold() == "vip"
    assert role.slots["target"].casefold() == "tomioka"

    msg = ai_actions.local_parse("SentriX envoie maintenance à 20h dans #annonces")
    assert msg is not None
    assert msg.intent == "message.send"
    assert msg.slots["channel"].casefold() == "#annonces"
    assert "maintenance" in msg.slots["text"].casefold()


def test_native_ai_payload_accepts_only_registered_fields():
    parsed = ai_actions._validate_ai_payload({
        "intent": "channel.create_text",
        "name": "annonces",
        "confidence": 95,
    })
    assert parsed is not None
    assert parsed.slots["name"] == "annonces"
    assert ai_actions._validate_ai_payload({
        "intent": "system.shell",
        "name": "rm -rf",
        "confidence": 100,
    }) is None


def test_category_and_role_colour_are_native_actions():
    category = ai_actions.local_parse("SentriX crée une catégorie STAFF")
    assert category is not None
    assert category.intent == "category.create"
    assert category.slots["name"].casefold() == "staff"

    colour = ai_actions.local_parse("SentriX mets le role Staff en rouge")
    assert colour is not None
    assert colour.intent == "role.color"
    assert colour.slots["role"].casefold() == "staff"
    assert colour.slots["color"].casefold() == "rouge"


def test_multi_action_detection_needs_multiple_actions():
    assert ai_actions.looks_multi_action(
        "crée une catégorie STAFF puis crée un salon staff-chat"
    )
    assert ai_actions.looks_multi_action(
        "crée un rôle Staff et mets le rôle Staff en rouge"
    )
    assert not ai_actions.looks_multi_action("ban Tomioka pour spam")


@pytest.mark.asyncio
async def test_multi_action_planner_is_closed_and_ordered(monkeypatch):
    class Result:
        ok = True
        text = (
            '{"actions":['
            '{"intent":"category.create","name":"STAFF","confidence":99},'
            '{"intent":"channel.create_text","name":"staff-chat","category":"STAFF","confidence":99},'
            '{"intent":"role.create","name":"Modérateur","confidence":99},'
            '{"intent":"category.restrict_role","category":"STAFF","role":"Modérateur","confidence":99}'
            ']}'
        )

    async def fake_generate(*args, **kwargs):
        return Result()

    monkeypatch.setattr(ai_actions.ai_service, "generate", fake_generate)
    plan = await ai_actions.parse_action_plan(
        "crée une catégorie STAFF puis un salon staff-chat, crée le rôle Modérateur et limite STAFF à ce rôle",
        guild_id=1,
        channel_id=2,
        user_id=3,
    )
    assert [action.intent for action in plan] == [
        "category.create",
        "channel.create_text",
        "role.create",
        "category.restrict_role",
    ]
    assert plan[1].slots["category"] == "STAFF"
    assert all(action.source == "plan" for action in plan)


@pytest.mark.asyncio
async def test_multi_action_planner_rejects_unknown_intent(monkeypatch):
    class Result:
        ok = True
        text = '{"actions":[{"intent":"system.shell","name":"x","confidence":100},{"intent":"role.create","name":"x","confidence":100}]}'

    async def fake_generate(*args, **kwargs):
        return Result()

    monkeypatch.setattr(ai_actions.ai_service, "generate", fake_generate)
    plan = await ai_actions.parse_action_plan(
        "fais deux actions dangereuses puis crée un rôle",
        guild_id=1,
        channel_id=2,
        user_id=3,
    )
    assert plan == ()
