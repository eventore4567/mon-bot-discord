from __future__ import annotations

import discord

from cogs import tickets
from services import tickets as ticket_service
from utils import wide_logs


def _all_enabled_settings():
    settings = tickets.default_button_settings()
    for key in tickets.STAFF_BUTTONS:
        settings[key]["enabled"] = True
    return settings


def test_ticket_controls_are_compact_even_when_all_actions_are_enabled():
    view = tickets.TicketControlView(_all_enabled_settings())

    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    selects = [item for item in view.children if isinstance(item, discord.ui.Select)]

    assert len(buttons) == 2
    assert {button.custom_id for button in buttons} == {
        "ticket_ctrl_claim",
        "ticket_ctrl_close",
    }
    assert len(selects) == 1
    assert selects[0].custom_id == "ticket_ctrl_actions"
    assert selects[0].placeholder == "Actions staff…"

    values = {option.value for option in selects[0].options}
    assert values == {
        "unclaim",
        "add",
        "remove",
        "rename",
        "transfer",
        "note",
        "bump",
    }


def test_ticket_control_select_keeps_secondary_actions_instead_of_dropping_features():
    select = tickets.TicketControlSelect(_all_enabled_settings())
    labels = {option.label for option in select.options}

    assert "Abandonner" in labels
    assert "Ajouter un membre" in labels
    assert "Retirer un membre" in labels
    assert "Renommer" in labels
    assert "Transférer" in labels
    assert "Ajouter une note" in labels
    assert "Relancer" in labels


def test_ticket_log_keeps_human_channel_name_even_if_discord_mention_is_unresolvable():
    embed = discord.Embed(title="Ticket ouvert")
    embed.add_field(name="📌 Salon", value="#ticket-tomioka · <#155500000000000001>")
    mapping = dict(wide_logs._field_map(embed))

    assert mapping["📌 Salon"] == "#ticket-tomioka · <#155500000000000001>"


def test_ticket_open_date_does_not_get_confused_with_opened_by_actor():
    embed = discord.Embed(title="Ticket ouvert")
    embed.add_field(name="Ouvert par", value="<@155500000000000002>\n`155500000000000002`")
    embed.add_field(name="🎟️ Ticket", value="#75")
    embed.add_field(name="📌 Salon", value="#ticket-tomioka · <#155500000000000001>")
    embed.add_field(name="🕒 Ouvert", value="<t:1791000000:F>")
    embed.add_field(name="🔖 Référence", value="`TK-0075-5`")

    body = wide_logs.narrative_body(
        embed,
        log_type="ticket_open",
        identity_name="tomioka",
        identity_id=155500000000000002,
    )

    assert "Ouvert : <t:1791000000:F>" in body
    assert "Ouvert : <@155500000000000002>" not in body
    assert "#ticket-tomioka" in body


def test_ticket_owner_events_recover_the_ticket_owner_from_durable_state():
    assert {
        "ticket_close",
        "ticket_autoclose",
        "ticket_claim",
        "ticket_unclaim",
        "ticket_reopen",
        "ticket_delete",
        "ticket_rating",
        "ticket_bump",
    } <= ticket_service._OWNER_TARGET_EVENTS
