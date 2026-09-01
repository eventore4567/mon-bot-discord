"""La vignette d'un log porte l'entite concernee, jamais le bot.

L'ancienne regle forcait l'icone SentriX sur chaque journal. Elle a ete abandonnee :
le bloc 1 du panneau doit identifier le membre banni, le salon supprime ou le role
modifie. Ces tests verifient la regle actuelle sur le rendu reel.
"""
import discord

from utils.wide_logs import WideLogView, _accent_for_kind, derive_identity

MEMBER_ID = 1355855757991481475
AVATAR = "https://cdn.discordapp.com/avatars/1355855757991481475/abc.png"


def _thumbnail_of(view: discord.ui.LayoutView):
    for container in view.children:
        for item in getattr(container, "children", []):
            if isinstance(item, discord.ui.Section):
                return item.accessory
    return None


def _panel(identity_icon):
    embed = discord.Embed(title="Membre banni")
    embed.add_field(name="Membre", value=f"<@{MEMBER_ID}>", inline=True)
    return WideLogView(
        embed, "sentrix_log_error.png", None, _accent_for_kind("error"),
        identity_name="Tomioka", identity_id=MEMBER_ID,
        identity_icon=identity_icon, emoji="", log_type="member_ban",
    )


def test_thumbnail_shows_the_concerned_entity():
    thumb = _thumbnail_of(_panel(AVATAR))
    assert isinstance(thumb, discord.ui.Thumbnail)
    assert MEMBER_ID == 1355855757991481475
    assert "1355855757991481475" in str(thumb.media.url)


def test_thumbnail_has_no_alt_description():
    """description= sur un Thumbnail affiche un badge « ALT » par-dessus l'image."""
    thumb = _thumbnail_of(_panel(AVATAR))
    assert getattr(thumb, "description", None) in (None, "")


def test_panel_still_renders_without_any_icon():
    """Perdre la vignette est acceptable ; perdre le panneau ne l'est pas."""
    view = _panel(None)
    assert view.children, "le Container doit exister meme sans icone"


def test_identity_is_derived_from_the_event_not_from_the_bot():
    embed = discord.Embed(title="Membre banni")
    embed.add_field(name="Membre", value=f"<@{MEMBER_ID}>", inline=True)
    name, ident, _icon = derive_identity(embed, log_type="member_ban")
    assert ident == MEMBER_ID
    assert (name or "").casefold() not in {"sentrix", "journal sentrix"}


def test_legacy_bot_icon_forcing_is_gone():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "log_transport_v52.py").read_text(
        encoding="utf-8"
    )
    assert "_force_sentrix_log_icon" not in source
    assert "set_thumbnail(url=_sentrix_log_icon_url())" not in source
