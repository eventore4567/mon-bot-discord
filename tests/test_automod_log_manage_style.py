from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import _automod_message_preview, _style_automod_log
from utils import embeds
from utils.log_banners import get_banner


def _fields(embed):
    return [(field.name, field.value) for field in embed.fields]


def test_all_automod_logs_use_manage_title_and_main_fields():
    member = SimpleNamespace(id=123456789, mention="<@123456789>")
    source = embeds.log_entry(
        "Action AutoMod — sanction appliquée",
        cible=member,
        cible_label="Membre",
        raison="Lien non autorisé (example.com)",
        extra={
            "Salon": "<#987654321>",
            "Message": "> https://example.com/test",
            "Sanction": "Suppression du message",
            "Messages supprimés": "1",
        },
    )

    styled = _style_automod_log(source, "automod_link")
    fields = _fields(styled)
    names = [name for name, _ in fields]

    assert styled.title == "Protection SentriX"
    assert names[:6] == [
        "Membre",
        "Protection",
        "Sanction",
        "Raison",
        "Salon",
        "Message",
    ]
    assert dict(fields)["Protection"] == "Anti-liens"
    assert dict(fields)["Sanction"] == "Suppression du message"
    assert "https://example.com/test" in dict(fields)["Message"]


def test_long_automod_message_is_quoted_and_truncated_cleanly():
    preview = _automod_message_preview("x" * 5000)
    assert preview.startswith("> ")
    assert preview.endswith("…")
    assert len(preview) <= 902


def test_attachment_only_automod_message_keeps_useful_context():
    attachment = SimpleNamespace(url="https://cdn.discordapp.com/file.png")
    message = SimpleNamespace(content="", attachments=[attachment])
    preview = _automod_message_preview(message)

    assert "https://cdn.discordapp.com/file.png" in preview


def test_automod_banner_is_available_for_manage_logs():
    assert get_banner("automod").exists()
    assert get_banner("automod_link").exists()
    assert get_banner("automod_spam").exists()
