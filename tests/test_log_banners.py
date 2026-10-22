"""La bande neutre des logs est commune aux panneaux ; aucun ancien logo."""
import inspect
import discord
from PIL import Image
from utils import command_visuals
from utils import sentrix_panels as panels
from utils.premium_log_banners import BANNER_FILENAME, get_premium_log_banner

def test_common_strip_is_wide_and_almost_transparent():
    with Image.open(get_premium_log_banner()) as strip:
        assert strip.size == (1200, 24)
        assert strip.mode == "RGBA"
        assert strip.getchannel("A").getextrema()[1] <= 18

def test_panel_gallery_and_file_reference_same_neutral_strip():
    panel = panels.Panneau(titre="Test")
    files = panel.fichiers()
    try:
        assert len(files) == 1
        assert files[0].filename == BANNER_FILENAME
        rendered = repr(panel.to_components())
        assert "attachment://" + BANNER_FILENAME in rendered
        assert "banner_config.webp" not in rendered
    finally:
        for file in files:
            file.close()

def test_screen_can_explicitly_omit_the_strip():
    panel = panels.Panneau(titre="Test", banniere=False)
    assert not panel.avec_banniere
    assert panel.fichiers() == []

def test_legacy_banner_image_is_removed_but_semantic_image_is_preserved():
    old = command_visuals.banner_url("info")
    banner_embed = discord.Embed(title="Test")
    banner_embed.set_image(url=old)
    assert not getattr(command_visuals._decorate_embed(banner_embed, "info").image, "url", None)
    semantic = discord.Embed(title="Test")
    semantic.set_image(url="https://cdn.example.test/real-image.png")
    assert command_visuals._decorate_embed(semantic, "info").image.url == semantic.image.url

def test_embed_to_panel_keeps_real_content_image():
    embed = discord.Embed(title="Média")
    embed.set_image(url="https://cdn.example.test/photo.webp")
    assert embed.image.url in repr(panels.depuis_embed(embed).to_components())

def test_public_panel_does_not_add_trace_reference(monkeypatch):
    from utils import sentrix_trace
    monkeypatch.setattr(sentrix_trace, "visible_ref", lambda: "SX-TEST123")
    panel = panels.Panneau(titre="Action réussie", pied="Terminé")
    assert "SX-TEST123" not in repr(panel.to_components())
