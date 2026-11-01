"""Contrats réels : /setup privé, bannière embed, images multimodales Discord."""
from __future__ import annotations

import ast
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
ROOT = Path(__file__).resolve().parents[1]


def _attachment(*, mime="application/octet-stream"):
    out = io.BytesIO()
    Image.new("RGB", (96, 58), (18, 85, 125)).save(out, format="PNG")
    data = out.getvalue()
    return SimpleNamespace(
        filename="capture.png", content_type=mime, size=len(data),
        read=AsyncMock(return_value=data),
    )


@pytest.mark.asyncio
async def test_image_de_discord_reply_to_reaches_model_even_when_contextvar_empty():
    from cogs.ai import Ai, _PASSIVE_IMAGE_CONTEXT

    attachment = _attachment()
    author = SimpleNamespace(id=12, display_name="Tomioka")
    guild = SimpleNamespace(id=34)
    channel = SimpleNamespace(id=56, guild=guild, send=AsyncMock())
    source = SimpleNamespace(
        id=78, channel=channel, guild=guild,
        author=author, attachments=[attachment],
    )
    cog = SimpleNamespace(
        histories={}, ask_ai=AsyncMock(return_value="Je vois le message Ok."),
    )
    token = _PASSIVE_IMAGE_CONTEXT.set(())
    try:
        await Ai.send_sentrix_reply(cog, channel, author, "Décris cette image", reply_to=source)
    finally:
        _PASSIVE_IMAGE_CONTEXT.reset(token)
    image_urls = cog.ask_ai.await_args.kwargs["image_urls"]
    assert len(image_urls) == 1
    assert image_urls[0].startswith("data:image/jpeg;base64,")
    attachment.read.assert_awaited()
    channel.send.assert_awaited()


@pytest.mark.asyncio
async def test_image_capture_est_acceptee_meme_si_discord_donne_un_mime_generique():
    from cogs.ai import _images_from_discord_attachments
    attachment = _attachment()
    images = await _images_from_discord_attachments([attachment])
    assert len(images) == 1
    assert images[0].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_ai_recovery_uses_actual_multimodal_input_from_original_message():
    from cogs.ai_reply_recovery import _direct_reply

    attachment = _attachment(mime="image/png")
    author = SimpleNamespace(id=12, display_name="Tomioka")
    guild = SimpleNamespace(id=34)
    channel = SimpleNamespace(id=56, guild=guild)
    source = SimpleNamespace(
        id=78, channel=channel, guild=guild,
        author=author, attachments=[attachment],
    )
    bot = SimpleNamespace(get_cog=lambda _name: None)
    result = SimpleNamespace(ok=True, text="La capture montre un embed.")
    with patch("cogs.ai_reply_recovery.ai_service.generate", AsyncMock(return_value=result)) as generate:
        with patch("cogs.ai_reply_recovery._send_text", AsyncMock()) as send:
            await _direct_reply(bot, channel, author, "Décris cette image", reply_to=source)
    payload = generate.await_args.args[0]
    assert payload[0]["content"][1]["type"] == "input_image"
    assert payload[0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    send.assert_awaited()


def test_final_setup_private_from_first_interaction_ack():
    src = (ROOT / "cogs/setup_invitations.py").read_text(encoding="utf-8")
    start = src.index("    async def final_send_setup(self, target):")
    end = src.index("    current = setup_ui.OfficialSetup.send_setup", start)
    code = src[start:end]
    assert "await slash.response.defer(ephemeral=True, thinking=True)" in code
    assert code.index("await slash.response.defer(ephemeral=True, thinking=True)") < code.index(
        "await setup_ui._can_setup("
    )
    assert "if not is_private:" in code
    assert "Aucun panneau public n'a été envoyé" in code
    assert "return await panels.envoyer(target, view, ephemere=True)" in code
    assert "delete_after=15" in code
    for name in ("cogs/setup_invitations.py", "cogs/ai.py", "cogs/ai_api_hotfix.py",
                 "cogs/ai_reply_recovery.py", "cogs/platform_v4.py"):
        ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)


def test_custom_embed_has_real_thin_banner_above_not_extra_message():
    from utils.log_banners import BANNER_DIR, ensure_banners, nom_fichier
    ensure_banners()
    path = BANNER_DIR / nom_fichier("special")
    assert path.exists()
    with Image.open(path) as banner:
        assert banner.width >= 1000
        assert banner.height <= 80
    text = (ROOT / "cogs/platform_v4.py").read_text(encoding="utf-8")
    listener = text.split("    async def on_message(self, message:", 1)[1].split(
        "    # ----------------------------------------------------------- role menus", 1
    )[0]
    assert 'banner_name = nom_fichier("special")' in listener
    assert 'banner.set_image(url=f"attachment://{banner_name}")' in listener
    assert "embeds=[banner, embed]" in listener
    assert "file=banner_file" in listener
    assert "banner_file.close()" in listener
    assert "if row[\"embed_title\"]:" in listener
