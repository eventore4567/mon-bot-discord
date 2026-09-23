"""Contrat des bannières SentriX (1024x110, style issu de LOG_REGISTRY).

Style unique depuis le 23/09/2026 : fond nuit, trait lumineux venant de chaque bord,
logo SentriX teinté au centre, liseré d'accent à gauche (voir utils/log_banners.py)."""
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


def test_banner_draws_a_glowing_line_from_each_edge():
    """Le trait est le dessin de la bannière : il doit éclairer la mi-hauteur et
    s'éteindre au bord, sinon il ne reste qu'un rectangle sombre."""
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("info")) as image:
        rgb = image.convert("RGB")
        gauche = sum(rgb.getpixel((300, 55)))
        droite = sum(rgb.getpixel((724, 55)))
        au_dessus = sum(rgb.getpixel((300, 40)))
        bord = sum(rgb.getpixel((1015, 55)))
        liseré_haut = sum(rgb.getpixel((300, 0)))
        fond = sum(rgb.getpixel((300, 15)))
    assert gauche > au_dessus * 2, "trait gauche absent"
    assert droite > au_dessus * 2, "trait droit absent"
    assert bord < gauche / 2, "le trait doit s'éteindre avant le bord"
    assert liseré_haut > fond, "liseré lumineux en haut absent"


def test_banner_keeps_a_night_background_and_an_accent_bar():
    """Fond nuit commun (c'est le trait et le logo qui portent la couleur) et
    liseré d'accent sur le bord gauche, comme les bannières validées."""
    for style, canal in (("error", 0), ("success", 1), ("info", 2)):
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            rgb = image.convert("RGB")
            fond = rgb.getpixel((300, 15))
            barre = rgb.getpixel((1, 55))
            trait = rgb.getpixel((300, 55))
        assert max(fond) < 60, f"{style} : le fond doit rester nuit ({fond})"
        assert barre[canal] == max(barre), f"{style} : liseré gauche pas à la couleur ({barre})"
        assert trait[canal] == max(trait), f"{style} : trait pas à la couleur ({trait})"


def test_the_centered_logo_is_tinted_with_the_family_colour():
    """Le logo du dépôt est bleu : non teinté, il jurait sur une bannière rouge ou or."""
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("error")) as image:
        rouge = image.convert("RGB").crop((470, 20, 554, 90))
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("success")) as image:
        verte = image.convert("RGB").crop((470, 20, 554, 90))
    r_rouge = sum(p[0] for p in rouge.getdata()) / rouge.width / rouge.height
    b_rouge = sum(p[2] for p in rouge.getdata()) / rouge.width / rouge.height
    v_verte = sum(p[1] for p in verte.getdata()) / verte.width / verte.height
    assert r_rouge > b_rouge * 1.5, "logo de la bannière erreur non teinté en rouge"
    assert v_verte > b_rouge, "logo de la bannière succès non teinté en vert"


def test_committed_source_banners_are_valid_and_match_the_generator():
    """Ces cinq fichiers sont servis par URL GitHub raw aux réponses de commande :
    un fichier corrompu (cas réel de banner_source_warning.webp) casse l'embed
    sans aucune erreur côté bot."""
    for state in ("error", "success", "warning", "info", "special"):
        path = log_banners.BANNER_DIR / f"banner_source_{state}.webp"
        assert path.exists(), state
        payload = path.read_bytes()
        assert payload[:4] == b"RIFF" and payload[8:12] == b"WEBP", f"{state} : fichier illisible"
        with Image.open(BytesIO(payload)) as image:
            assert image.size == (1024, 110), state
        assert path.stat().st_size < 12_000, f"{state} : {path.stat().st_size} octets"


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
