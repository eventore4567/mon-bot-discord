"""Contrats du journal premium SentriX, indépendants de l'API Discord."""
import discord
from PIL import Image

from cogs.log_history_center import PremiumLogAction, MemberHistoryView
from utils.premium_log_banners import SIZE, build_premium_banner, get_premium_log_banner
from utils.wide_logs import WideLogView, narrative_body


GUILD_ID = 123456789012345678
USER_ID = 223456789012345678


def _walk(node):
    yield node
    for child in getattr(node, "children", []):
        yield from _walk(child)


def _embed(log_type="member_ban"):
    embed = discord.Embed(title="Dossier #42 — Membre banni")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Modérateur", value="<@323456789012345678>")
    embed.add_field(name="Raison", value="Spam répété")
    return embed


def test_premium_banner_is_full_width_and_themed():
    banner = build_premium_banner("member_ban")
    assert banner.size == SIZE
    assert SIZE[1] >= 180
    assert banner.mode == "RGB"
    assert get_premium_log_banner("member_ban").exists()


def test_unban_and_ban_get_different_colours():
    banned = build_premium_banner("member_ban").getpixel((29, 110))
    unbanned = build_premium_banner("member_unban").getpixel((29, 110))
    assert banned != unbanned


def test_premium_log_has_persistent_history_and_unban_buttons_without_reference():
    view = WideLogView(
        _embed(), "sentrix_premium_error.webp",
        identity_name="moussa", identity_id=USER_ID,
        log_type="member_ban", guild_id=GUILD_ID,
    )
    items = list(_walk(view))
    actions = [i for i in items if isinstance(i, PremiumLogAction)]
    assert {a.action for a in actions} == {"history", "unban"}
    assert all(str(GUILD_ID) in a.item.custom_id for a in actions)
    text = "\n".join(
        str(getattr(i, "content", "")) for i in items
    )
    assert "Dossier #42" not in text
    assert "BAN-0042" not in text


def test_departure_displays_old_roles_and_stay():
    embed = discord.Embed(title="Membre parti")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    embed.add_field(name="Présence", value="4 jours")
    embed.add_field(name="Rôles avant le départ", value="<@&423456789012345678>, <@&523456789012345678>")
    body = narrative_body(embed, log_type="member_leave", identity_id=USER_ID)
    assert "Rôles avant le départ" in body
    assert "<@&423456789012345678>" in body
    assert "4 jours" in body


def test_history_view_is_private_and_paginates():
    view = MemberHistoryView(author_id=USER_ID, guild_id=GUILD_ID, target_id=USER_ID)
    assert view.author_id == USER_ID
    assert view.page == 0
    assert view.records == []


def test_premium_buttons_keep_target_snowflake_not_public_case_reference():
    action = PremiumLogAction("unban", GUILD_ID, USER_ID)
    assert action.item.style is discord.ButtonStyle.success
    assert str(USER_ID) in action.item.custom_id
    assert "BAN-" not in action.item.custom_id
