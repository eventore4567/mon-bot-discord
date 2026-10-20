"""Régression Discord : 2 panneaux « Invitation créée », fausse identité et champs collés.

Deux anciens producteurs :
- gateway : « Ressources » + event_key invite_create, Code SmeMEFNH ;
- audit : « Ressources » + titre « Invitation créée », Lien discord.gg/SmeMEFNH.
Ils doivent aboutir au MÊME événement, identifié par le code, sans supprimer
une AUTRE invitation légitime créée dans la même fenêtre de 8 secondes.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import setup_v2_resource_events as resource_events
from utils import log_service, wide_logs


def _gateway_embed(code: str = "SmeMEFNH", *, inviter_id: int | None = None):
    embed = discord.Embed(title="Invitation créée")
    embed.add_field(name="Code", value=f"`{code}`")
    embed.add_field(name="Salon", value="<#123456789012345678>")
    if inviter_id:
        embed.add_field(name="Créateur", value=f"<@{inviter_id}>")
    embed.add_field(name="Utilisations max", value="Illimité")
    embed.add_field(name="Expiration", value="Dans 7 jours")
    return embed


def _audit_embed(code: str = "SmeMEFNH"):
    embed = discord.Embed(title="Invitation créée")
    embed.add_field(name="Responsable", value="<@111111111111111111>")
    embed.add_field(name="Créateur", value="<@111111111111111111>")
    embed.add_field(name="Salon", value="<#123456789012345678>")
    embed.add_field(name="Lien", value=f"https://discord.gg/{code}")
    embed.add_field(name="Expire", value="dans 7 jours")
    embed.add_field(name="Utilisations max", value="Illimité")
    return embed


def test_same_invite_code_matches_gateway_and_audit_even_with_different_actors():
    a = log_service.semantic_event_key(42, "invite_create", _gateway_embed())
    b = log_service.semantic_event_key(42, "invite_create", _audit_embed())
    assert a == b == "semantic:42:invite_create:code:smemefnh"


def test_independent_invites_do_not_collide_even_if_same_creator():
    key_a = log_service.semantic_event_key(42, "invite_create", _audit_embed("AAA111"))
    key_b = log_service.semantic_event_key(42, "invite_create", _audit_embed("BBB222"))
    assert key_a != key_b
    assert log_service.semantic_event_key(42, "invite_delete", _audit_embed("AAA111")) != key_a


def test_missing_code_does_not_suppress_other_uncertain_invites():
    embed = discord.Embed(title="Invitation créée")
    embed.add_field(name="Créateur", value="<@111111111111111111>")
    assert log_service.semantic_event_key(42, "invite_create", embed) is None


def test_dedup_memory_is_shared_by_both_formats_and_keeps_other_code():
    log_service._recent_event_keys.clear()
    try:
        a = log_service.semantic_event_key(42, "invite_create", _gateway_embed())
        b = log_service.semantic_event_key(42, "invite_create", _audit_embed())
        other = log_service.semantic_event_key(42, "invite_create", _gateway_embed("OTHER99"))
        assert not log_service._is_duplicate(a)
        assert log_service._is_duplicate(b)
        assert not log_service._is_duplicate(other)
    finally:
        log_service._recent_event_keys.clear()


def test_invite_code_extracted_from_embedded_link_or_plain_field():
    assert log_service._invite_code_from_embed(_gateway_embed()) == "SmeMEFNH"
    assert log_service._invite_code_from_embed(_audit_embed()) == "SmeMEFNH"
    embed = discord.Embed(description="Une invitation : https://discord.gg/AbC123")
    assert log_service._invite_code_from_embed(embed) == "AbC123"


@pytest.mark.asyncio
async def test_real_send_log_routes_generic_resources_as_invite_and_suppresses_echo():
    log_service._recent_event_keys.clear()
    guild = SimpleNamespace(
        id=42,
        get_channel=lambda cid: SimpleNamespace(id=cid),
        get_member=lambda uid: None,
    )
    bot = SimpleNamespace(get_user=lambda uid: None, fetch_user=AsyncMock(return_value=None))
    sender = AsyncMock(return_value=True)
    config = {"channel_id": 99, "enabled": True, "updated_at": 0}
    try:
        with (
            patch.object(log_service, "get_log_config", AsyncMock(return_value=config)),
            patch.object(log_service, "validate_channel", return_value=(True, "ok")),
            patch.object(log_service.wide_logs, "salon_inaccessible", return_value=False),
            patch.object(log_service, "send_wide_log", sender),
        ):
            # La passerelle précise le type dans sa clé.
            first = await log_service.send_log(
                bot, guild, "resources", _gateway_embed(),
                event_key=log_service.make_event_key(42, "invite_create", discriminator="SmeMEFNH"),
            )
            # L'ancien audit indique seulement « resources » et un lien.
            duplicate = await log_service.send_log(
                bot, guild, "resources", _audit_embed(),
                event_key=log_service.make_event_key(42, "resources", discriminator="audit987"),
            )
            other = await log_service.send_log(
                bot, guild, "resources", _audit_embed("OTHER99"),
                event_key=log_service.make_event_key(42, "resources", discriminator="audit988"),
            )
        assert first is True
        assert duplicate is False
        assert other is True
        assert sender.await_count == 2
        assert sender.await_args_list[0].kwargs["log_type"] == "invite_create"
        assert sender.await_args_list[1].kwargs["log_type"] == "invite_create"
    finally:
        log_service._recent_event_keys.clear()


def test_creator_identity_is_never_channel_id_when_actor_missing():
    guild = SimpleNamespace(get_member=lambda uid: None, get_channel=lambda cid: None)
    name, uid, icon = wide_logs.derive_identity(
        _gateway_embed(), log_type="invite_create", guild=guild
    )
    assert uid is None
    assert name is None or "123456789012345678" not in name
    assert icon is None


def test_creator_identity_preserved_when_provided_by_discord():
    identity = wide_logs.derive_identity(
        _audit_embed(), log_type="invite_create", guild=None
    )
    assert identity[1] == 111111111111111111
    assert wide_logs._trace_identity_label("invite_create") == "Créateur"


def test_formatted_log_is_a_readable_card_without_quoted_bar_or_repeated_identity():
    embed = _audit_embed()
    body = wide_logs.narrative_body(embed, log_type="invite_create", identity_id=111111111111111111)
    assert "**Salon**\\n" in body.replace("\n", "\\n")
    assert "**Lien**" in body
    assert "**Expiration**" in body
    assert "Responsable" not in body
    assert "Créateur" not in body
    assert "SmeMEFNH" in body
    view = wide_logs.WideLogView(
        embed, banner_filename="", log_type="invite_create",
        identity_name="Toxic", identity_id=111111111111111111,
        identity_icon=None,
    )
    container = view.children[0]
    displays = [item.content for item in container.children if isinstance(item, discord.ui.TextDisplay)]
    combined = "\n".join(displays)
    assert "🔗 Ressources" in combined
    assert "**Créateur** · <@111111111111111111>" in combined
    assert "## Invitation créée" in combined
    assert "Item" not in combined
    assert "> " not in combined
    assert combined.count("https://discord.gg/SmeMEFNH") == 1


@pytest.mark.asyncio
async def test_gateway_producer_sends_known_inviter_and_readable_expiry():
    user = SimpleNamespace(
        id=111111111111111111, name="Toxic", display_name="Toxic",
        mention="<@111111111111111111>",
        display_avatar=SimpleNamespace(url="https://example.org/avatar.png"),
    )
    invite = SimpleNamespace(
        code="SmeMEFNH", inviter=user, max_uses=0, max_age=604800,
        expires_at=None,
    )
    guild = SimpleNamespace(id=42)
    with patch.object(resource_events.log_service, "send_log", AsyncMock(return_value=True)) as send:
        await resource_events._send(
            SimpleNamespace(), guild, "Invitation créée",
            [
                ("Code", "`SmeMEFNH`", False),
                ("Créateur", user.mention, False),
                ("Expiration", resource_events._expiration(invite), False),
            ],
            "invite_create", invite=invite,
        )
    send.assert_awaited_once()
    assert send.await_args.kwargs["identity_id"] == user.id
    assert send.await_args.kwargs["identity_name"] == "Toxic"
    assert "SmeMEFNH" in send.await_args.kwargs["event_key"]
    assert resource_events._expiration(invite) == "Dans 7 jours"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_first", [False, True])
async def test_real_1955_duplicate_dossiers_and_invite_create_single_card(legacy_first):
    """Reproduit les DEUX lignes Railway du 10/10 19:55:54, pas « resources ».

    L'ordre peut changer selon la cadence des listeners. Les deux ordres doivent
    émettre une seule carte, avec le renderer canonique invite_create.
    """
    guild = SimpleNamespace(
        id=42,
        get_channel=lambda cid: SimpleNamespace(id=cid),
        get_member=lambda uid: None,
    )
    bot = SimpleNamespace(get_user=lambda uid: None, fetch_user=AsyncMock(return_value=None))
    config = {"enabled": True, "channel_id": 99, "updated_at": 0}
    sender = AsyncMock(return_value=True)
    gateway = (
        "resources", _gateway_embed("UExgvBgF", inviter_id=111111111111111111),
        log_service.make_event_key(42, "invite_create", discriminator="UExgvBgF"),
    )
    legacy = (
        "dossiers", _audit_embed("UExgvBgF"),
        log_service.make_event_key(42, "dossiers", discriminator="audit-legacy-777"),
    )
    first, second = (legacy, gateway) if legacy_first else (gateway, legacy)
    log_service._recent_event_keys.clear()
    try:
        with (
            patch.object(log_service, "get_log_config", AsyncMock(return_value=config)),
            patch.object(log_service, "validate_channel", return_value=(True, "ok")),
            patch.object(log_service.wide_logs, "salon_inaccessible", return_value=False),
            patch.object(log_service, "send_wide_log", sender),
        ):
            r1 = await log_service.send_log(bot, guild, first[0], first[1], event_key=first[2])
            r2 = await log_service.send_log(bot, guild, second[0], second[1], event_key=second[2])
            # Deux VRAIES invitations différentes ne doivent pas disparaître.
            r3 = await log_service.send_log(
                bot, guild, "dossiers", _audit_embed("DIFFERENT"),
                event_key=log_service.make_event_key(42, "dossiers", discriminator="audit-legacy-778"),
            )
        assert (r1, r2, r3) == (True, False, True)
        assert sender.await_count == 2
        assert all(call.kwargs["log_type"] == "invite_create" for call in sender.await_args_list)
    finally:
        log_service._recent_event_keys.clear()


@pytest.mark.asyncio
async def test_dossiers_member_arrival_remains_untouched():
    """Les journaux d'arrivée routés via dossiers doivent continuer à partir."""
    guild = SimpleNamespace(
        id=42, get_channel=lambda cid: SimpleNamespace(id=cid),
        get_member=lambda uid: None,
    )
    bot = SimpleNamespace(get_user=lambda uid: None, fetch_user=AsyncMock(return_value=None))
    embed = discord.Embed(title="Nouvelle arrivée")
    embed.add_field(name="Membre", value="<@111111111111111111>")
    sender = AsyncMock(return_value=True)
    log_service._recent_event_keys.clear()
    try:
        with (
            patch.object(log_service, "get_log_config", AsyncMock(return_value={
                "enabled": True, "channel_id": 99, "updated_at": 0
            })),
            patch.object(log_service, "validate_channel", return_value=(True, "ok")),
            patch.object(log_service.wide_logs, "salon_inaccessible", return_value=False),
            patch.object(log_service, "send_wide_log", sender),
        ):
            result = await log_service.send_log(
                bot, guild, "dossiers", embed, event_key="invite-join:42:111111111111111111"
            )
        assert result is True
        sender.assert_awaited_once()
        assert sender.await_args.kwargs["log_type"] != "invite_create"
    finally:
        log_service._recent_event_keys.clear()


@pytest.mark.asyncio
async def test_dossiers_invite_delete_keeps_correct_event_type():
    guild = SimpleNamespace(
        id=42, get_channel=lambda cid: SimpleNamespace(id=cid),
        get_member=lambda uid: None,
    )
    bot = SimpleNamespace(get_user=lambda uid: None, fetch_user=AsyncMock(return_value=None))
    embed = _audit_embed("ANOTHER")
    embed.title = "Invitation supprimée"
    sender = AsyncMock(return_value=True)
    log_service._recent_event_keys.clear()
    try:
        with (
            patch.object(log_service, "get_log_config", AsyncMock(return_value={
                "enabled": True, "channel_id": 99, "updated_at": 0
            })),
            patch.object(log_service, "validate_channel", return_value=(True, "ok")),
            patch.object(log_service.wide_logs, "salon_inaccessible", return_value=False),
            patch.object(log_service, "send_wide_log", sender),
        ):
            await log_service.send_log(
                bot, guild, "dossiers", embed,
                event_key=log_service.make_event_key(42, "dossiers", discriminator="legacy-del"),
            )
        assert sender.await_args.kwargs["log_type"] == "invite_delete"
    finally:
        log_service._recent_event_keys.clear()
