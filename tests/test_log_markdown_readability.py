"""Visual regression: all Trace cards remain readable Discord Markdown.

Regression captured on Oct 12: a malformed regex wrapped partial words in
backticks, e.g. "Positions" appeared as several grey inline-code tokens.
"""
import discord

from utils import wide_logs


def texts(view: discord.ui.LayoutView) -> str:
    lines = []

    def visit(items):
        for item in items:
            if isinstance(item, discord.ui.TextDisplay):
                lines.append(item.content)
            visit(getattr(item, "children", []) or [])
    visit(view.children)
    return "\n".join(lines)


def test_badge_formatter_never_splits_plain_words_or_headings():
    examples = (
        "-# Rôles\n## Rôles déplacés\n**Élément** · 17",
        "-# Membres\n## Rôle ajouté au membre\n**Membre** · <@123456789012345678>",
        "Positions modifiées : @Mineur : `4` → `17`",
        "**Créateur** · <@123456789012345678>",
    )
    for text in examples:
        assert wide_logs._bold_log_labels_as_badges(text) == text


def test_role_reorder_card_has_unbroken_labels_and_clean_positions():
    embed = discord.Embed(
        title="Rôles déplacés",
        description=(
            "**Rôles concernés :** 17\n\n"
            "**Positions modifiées :** <@&123456789012345678> : `4` → `17`\n"
            "<@&123456789012345679> : `3` → `16`"
        ),
    )
    view = wide_logs.WideLogView(
        embed, banner_filename="", log_type="roles_reordered",
        identity_name="17", identity_id=17,
    )
    text = texts(view)
    assert "## Rôles déplacés" in text
    assert "Élément · 17" not in text
    assert "**Positions modifiées :**" in text
    assert "<@&123456789012345678> : 4 → 17" in text
    assert "<@&123456789012345679> : 3 → 16" in text
    assert "`4`" not in text and "`17`" not in text
    assert "Rôles concernés :** 17" in text


def test_member_role_log_preserves_clickable_mentions_and_bold():
    embed = discord.Embed(title="Rôle ajouté au membre")
    embed.add_field(name="Membre", value="<@123456789012345678>")
    embed.add_field(name="Rôle", value="<@&123456789012345679>")
    view = wide_logs.WideLogView(
        embed, banner_filename="", log_type="role_add",
        identity_id=123456789012345678,
    )
    text = texts(view)
    assert "## Rôle ajouté au membre" in text
    assert "**Membre** · <@123456789012345678>" in text
    assert "`Membre`" not in text


def test_message_delete_content_is_not_rewritten_as_badges():
    embed = discord.Embed(title="Message supprimé", description="")
    embed.add_field(name="Auteur", value="<@123456789012345678>")
    embed.add_field(name="Salon", value="<#123456789012345679>")
    embed.add_field(name="Contenu", value="Salut **tout le monde** `test`")
    view = wide_logs.WideLogView(
        embed, banner_filename="", log_type="message_delete",
        identity_id=123456789012345678,
    )
    text = texts(view)
    assert "## Message supprimé" in text
    assert "**Auteur** · <@123456789012345678>" in text
    assert "tout le monde" in text
    assert "`tout le monde`" not in text


def test_numeric_log_cleanup_is_scoped_to_small_role_positions():
    text = "Pos: `4` → `17`, id: `123456789012345678`, nick: `hello`"
    assert wide_logs._clean_role_positions(text) == (
        "Pos: 4 → 17, id: `123456789012345678`, nick: `hello`"
    )
