"""Contrat des bannières de logs SentriX (1024x110, style issu de LOG_REGISTRY)."""
from io import BytesIO

import discord
from PIL import Image

from utils import log_banners
from utils.log_categories import LOG_REGISTRY


def test_chaque_famille_fait_1024x110_et_reste_distincte():
    """Neuf familles : cinq etats, quatre domaines. Toutes doivent differer.

    Le format est WebP depuis que la banniere part en piece jointe a chaque
    reponse de commande et plus seulement dans les journaux : le meme visuel pese
    5 Ko au lieu de 45.
    """
    payloads = []
    for style in log_banners.STYLES:
        path = log_banners.BANNER_DIR / log_banners.nom_fichier(style)
        assert path.exists(), style
        payload = path.read_bytes()
        payloads.append(payload)
        assert payload[:4] == b"RIFF" and payload[8:12] == b"WEBP", style
        with Image.open(BytesIO(payload)) as image:
            assert image.size == (1024, 110)
    assert len(set(payloads)) == len(log_banners.STYLES)


def test_une_banniere_reste_legere():
    """Elle est jointe a CHAQUE message : son poids est un cout par commande."""
    for style in log_banners.STYLES:
        path = log_banners.BANNER_DIR / log_banners.nom_fichier(style)
        assert path.stat().st_size < 12_000, f"{style} : {path.stat().st_size} octets"


def test_les_domaines_ont_leur_propre_teinte():
    """Une sanction affichee en vert de reussite serait un contresens."""
    from utils import sentrix_panels as panels

    assert panels.nom_banniere("moderation") == log_banners.nom_fichier("moderation")
    assert panels.nom_banniere("securite") == log_banners.nom_fichier("security")
    assert panels.nom_banniere("economie") == log_banners.nom_fichier("economy")
    assert panels.nom_banniere("configuration") == log_banners.nom_fichier("config")


def test_style_comes_from_the_registry_not_from_the_title():
    """« unban » contient « ban » : deviner depuis le titre sortait un déban en rouge."""
    assert log_banners.banner_kind("member_unban") == "success"
    assert log_banners.banner_kind("member_ban") == "error"
    # Même avec un titre trompeur, le registre gagne.
    assert log_banners.banner_kind("member_unban", "Bannissement définitif") == "success"
    assert log_banners.banner_kind("message_delete", "") == "error"
    assert log_banners.banner_kind("ticket_close", "") == "special"


def test_every_registry_entry_maps_to_a_generated_banner():
    for log_type, (_category, _emoji, kind) in LOG_REGISTRY.items():
        assert kind in log_banners.COLORS, f"{log_type} -> {kind}"
        assert log_banners.get_banner(log_type).exists()


def test_banner_has_a_top_light_edge_and_a_right_vignette():
    # x=200 : hors du logo centre et de son halo, qui eclaircissent le milieu.
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("info")) as image:
        rgb = image.convert("RGB")
        top = sum(rgb.getpixel((200, 0)))
        middle = sum(rgb.getpixel((200, 55)))
        right = sum(rgb.getpixel((1015, 55)))
    assert top > middle, "liseré lumineux en haut absent"
    assert right < middle, "vignettage à droite absent"


def test_banner_uses_the_repository_logo():
    assert log_banners.LOGO_PATH.exists(), "aucun logo resolu"
    assert log_banners.LOGO_PATH.name in {"sentrix_logo.png", "brand.png"}


def test_generation_survives_a_missing_logo(tmp_path, monkeypatch):
    monkeypatch.setattr(log_banners, "LOGO_PATH", tmp_path / "absent.png")
    image = log_banners.build_banner("error")
    assert image.size == (1024, 110)


def test_no_invisible_padding_and_no_hard_rules_in_the_renderer():
    source = (log_banners.ROOT / "utils" / "wide_logs.py").read_text(encoding="utf-8")
    for forbidden in ("⠀", "　" * 3, "─────"):
        assert forbidden not in source
    # WideLogView doit utiliser Separator(), pas des lignes de tirets en dur.
    assert "discord.ui.Separator" in source
