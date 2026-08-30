from io import BytesIO

import discord
from PIL import Image

from utils import log_banners, log_service
from utils.log_wide_guard import SPACER_FIELD_NAME, SPACER_FIELD_VALUE


def _embed(title: str) -> discord.Embed:
    return discord.Embed(title=title)


def test_banner_png_dimensions_and_palette_variants():
    payloads = []
    for style in ("error", "success", "warning", "info", "special"):
        payload = log_banners._banner_png(style)
        payloads.append(payload)
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(payload)) as image:
            assert image.size == (1024, 14)
    assert len(set(payloads)) == 5


def test_semantic_styles_cover_the_five_sentrix_states():
    assert log_banners.resolve_log_style("messages", _embed("Message supprimé")) == "error"
    assert log_banners.resolve_log_style("moderation", _embed("Débannissement")) == "success"
    assert log_banners.resolve_log_style("moderation", _embed("Avertissement")) == "warning"
    assert log_banners.resolve_log_style("messages", _embed("Message modifié")) == "info"
    assert log_banners.resolve_log_style("members", _embed("Membre arrivé")) == "special"


def test_renderer_keeps_log_wide_while_banner_loads():
    rendered, _ = log_banners._render_embed("messages", _embed("Message modifié"))
    assert any(
        str(field.name) == SPACER_FIELD_NAME
        and str(field.value) == SPACER_FIELD_VALUE
        for field in rendered.fields
    )


def test_log_service_is_patched_once_from_utils_package():
    log_banners.install()
    first = log_service.send_log
    log_banners.install()
    assert log_service.send_log is first
    assert log_service.send_log is log_banners.send_log_v81
    assert log_service.send_test_log is log_banners.send_test_log_v81
