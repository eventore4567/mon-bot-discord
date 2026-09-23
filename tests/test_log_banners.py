"""Contrat des bannières SentriX (1024x110, style issu de LOG_REGISTRY).

Style unique : fond entièrement transparent, deux traits lumineux colorés et logo
SentriX teinté au centre. Aucun rectangle, cadre ou fond coloré ne doit être visible."""
from io import BytesIO

import discord
from PIL import Image

from utils import log_banners
from utils.log_categories import LOG_REGISTRY


def test_chaque_famille_fait_1024x110_et_reste_distincte():
    """Cinq etats et neuf domaines. Toutes doivent differer.

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
    """Le trait est le dessin principal et doit ressortir sur un alpha transparent."""
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("info")) as image:
        alpha = image.convert("RGBA").getchannel("A")
        gauche = alpha.getpixel((300, 55))
        droite = alpha.getpixel((724, 55))
        au_dessus = alpha.getpixel((300, 25))
        bord = alpha.getpixel((1015, 55))
    assert gauche > 120, "trait gauche absent"
    assert droite > 120, "trait droit absent"
    assert au_dessus == 0, "le fond au-dessus du trait doit rester transparent"
    assert bord < gauche / 3, "le trait doit s'éteindre avant le bord"


def test_banner_background_is_really_transparent():
    """La couleur ne doit vivre que dans le trait, le logo et leur léger glow."""
    points = ((8, 8), (300, 15), (724, 15), (1015, 100))
    for style in ("error", "success", "warning", "music", "economy", "ai"):
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            rgba = image.convert("RGBA")
            for point in points:
                assert rgba.getpixel(point)[3] == 0, f"{style} : fond visible en {point}"


def test_the_centered_logo_is_tinted_with_the_family_colour():
    """Le logo conserve son alpha et prend la même famille de couleur que le trait."""
    def visible_average(style: str):
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            pixels = [
                pixel for pixel in image.convert("RGBA").crop((470, 20, 554, 90)).getdata()
                if pixel[3] > 40
            ]
        assert pixels, style
        return tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))

    rouge = visible_average("error")
    verte = visible_average("success")
    assert rouge[0] > rouge[2] * 1.35, "logo erreur non teinté en rouge"
    assert verte[1] > verte[0], "logo succès non teinté en vert"


def test_embed_banner_urls_use_the_runtime_generated_assets():
    """Les embeds classiques et les panneaux doivent partager la même source runtime."""
    import config
    from utils import command_visuals

    base = config.DASHBOARD_PUBLIC_URL.rstrip("/")
    for style in log_banners.STYLES:
        assert command_visuals._BANNER_URLS[style] == (
            f"{base}/assets/sentrix-banner/{style}.webp"
        )


def test_command_visuals_never_look_for_png_runtime_banners():
    from utils import command_visuals

    source = (log_banners.ROOT / "utils" / "command_visuals.py").read_text(encoding="utf-8")
    assert 'banner_{kind}.png' not in source
    assert 'sentrix_command_{kind}.png' not in source
    assert "nom_fichier(family)" in source
    assert ".webp" in source

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


def test_la_banniere_prend_la_couleur_de_la_commande_en_cours():
    """Une réponse neutre doit parler de SON domaine : +play en rose musique,
    +balance en or économie — pas le même bleu d'information pour tout le bot."""
    from types import SimpleNamespace

    from cogs import final_interaction_policy as policy
    from utils import sentrix_panels as panels

    def pour(commande: str, cog: str, kind: str = "info") -> str:
        jeton = policy._COMMAND_CONTEXT.set(
            SimpleNamespace(command=SimpleNamespace(qualified_name=commande, cog_name=cog))
        )
        try:
            return panels.nom_banniere(kind)
        finally:
            policy._COMMAND_CONTEXT.reset(jeton)

    assert pour("play", "Music") == log_banners.nom_fichier("music")
    assert pour("balance", "Economy") == log_banners.nom_fichier("economy")
    assert pour("level", "Levels") == log_banners.nom_fichier("levels")
    assert pour("ticket", "Tickets") == log_banners.nom_fichier("tickets")
    assert pour("blackjack", "Minigames") == log_banners.nom_fichier("games")
    assert pour("ai", "Ai") == log_banners.nom_fichier("ai")
    # Un état explicite garde sa couleur : une erreur reste rouge, même en musique.
    assert pour("play", "Music", "danger") == log_banners.nom_fichier("error")
    assert pour("play", "Music", "success") == log_banners.nom_fichier("success")
    # Hors commande (log automatique), l'intention demandée est respectée.
    assert panels.nom_banniere("info") == log_banners.nom_fichier("info")


def test_le_panneau_joint_exactement_la_banniere_qu_il_reference():
    """La galerie référence attachment://<fichier> : si fichiers() re-décidait la
    famille plus tard (contexte de commande retombé), l'image serait vide."""
    from types import SimpleNamespace

    from cogs import final_interaction_policy as policy
    from utils import sentrix_panels as panels

    jeton = policy._COMMAND_CONTEXT.set(
        SimpleNamespace(command=SimpleNamespace(qualified_name="play", cog_name="Music"))
    )
    try:
        panneau = panels.Panneau(titre="Lecture", kind="info")
    finally:
        policy._COMMAND_CONTEXT.reset(jeton)

    assert panneau.famille == "music"
    fichiers = panneau.fichiers()  # appelé hors contexte, comme à l'envoi réel
    assert [f.filename for f in fichiers] == [log_banners.nom_fichier("music")]


def test_le_liseré_du_conteneur_suit_la_banniere():
    """Le liseré Discord et la bannière doivent être de la même couleur."""
    from utils import sentrix_panels as panels

    for famille in log_banners.STYLES:
        assert famille in panels.ACCENTS_PAR_FAMILLE, famille


def test_chaque_famille_colore_uniquement_le_trait_et_le_logo():
    """Changer de famille ne doit jamais réintroduire un rectangle de fond."""
    for style in ("error", "success", "warning", "music", "economy"):
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            rgba = image.convert("RGBA")
            assert rgba.getpixel((300, 18))[3] == 0, style
            trait = rgba.getpixel((300, 55))
        assert trait[3] > 120, f"{style} : trait trop faible"
        assert max(trait[:3]) - min(trait[:3]) >= 20, f"{style} : trait trop neutre {trait}"


def test_les_deux_chemins_de_banniere_ont_les_memes_familles():
    """Pièce jointe et URL Railway doivent exposer les mêmes quatorze familles."""
    from utils import command_visuals

    assert set(command_visuals._BANNER_URLS) == set(log_banners.STYLES)
    assert set(command_visuals._ACCENTS) == set(log_banners.STYLES)


def test_les_commandes_en_texte_libre_n_ont_pas_de_banniere():
    """Un bandeau de 1024x110 au-dessus d'une réponse de l'IA n'ajoute rien."""
    from types import SimpleNamespace

    from cogs import final_interaction_policy as policy
    from utils import sentrix_panels as panels

    def panneau_pour(commande: str, cog: str) -> panels.Panneau:
        jeton = policy._COMMAND_CONTEXT.set(
            SimpleNamespace(command=SimpleNamespace(qualified_name=commande, cog_name=cog))
        )
        try:
            return panels.Panneau(titre="Réponse", sous_titre="texte", kind="info")
        finally:
            policy._COMMAND_CONTEXT.reset(jeton)

    for commande in ("sentrix", "ai", "translate", "summarize"):
        panneau = panneau_pour(commande, "Ai")
        assert panneau.avec_banniere is False, commande
        assert panneau.fichiers() == [], commande
    # Une commande structurée garde la sienne.
    structure = panneau_pour("balance", "Economy")
    assert structure.avec_banniere is True
    assert [f.filename for f in structure.fichiers()] == [log_banners.nom_fichier("economy")]
