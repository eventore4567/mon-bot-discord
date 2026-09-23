"""Contrat des bannières SentriX (1024xHEIGHT, style issu de LOG_REGISTRY).

Style unique : AUCUN fond. Un trait lumineux part de chaque bord, s'arrête avant le
logo SentriX centré et teinté, et tout le reste de l'image a un alpha de 0 — le
panneau Discord se voit directement derrière (voir utils/log_banners.py)."""
from io import BytesIO

import discord
from PIL import Image

from utils import log_banners
from utils.log_categories import LOG_REGISTRY


def test_chaque_famille_fait_1024x64_et_reste_distincte():
    """Seize familles : cinq états et onze domaines. Toutes doivent différer.

    WebP sans perte : la bannière part en pièce jointe à chaque message et sa
    couche alpha doit rester exacte (un WebP avec perte salit les bords du halo).
    """
    payloads = []
    for style in log_banners.STYLES:
        path = log_banners.BANNER_DIR / log_banners.nom_fichier(style)
        assert path.exists(), style
        payload = path.read_bytes()
        payloads.append(payload)
        assert payload[:4] == b"RIFF" and payload[8:12] == b"WEBP", style
        with Image.open(BytesIO(payload)) as image:
            assert image.size == (1024, log_banners.HEIGHT)
            assert image.mode == "RGBA", f"{style} : pas de couche alpha"
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
    """Le trait EST le dessin : il éclaire la mi-hauteur, il est plus intense près du
    logo et il s'éteint avant le bord (coupé net, il redessinerait un rectangle)."""
    milieu = log_banners.HEIGHT // 2
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("info")) as image:
        rgba = image.convert("RGBA")
        pres_du_logo = rgba.getpixel((460, milieu))[3]
        a_mi_chemin = rgba.getpixel((250, milieu))[3]
        vers_le_bord = rgba.getpixel((20, milieu))[3]
        cote_droit = rgba.getpixel((564, milieu))[3]
        au_dessus = rgba.getpixel((250, milieu - 6))[3]
    assert pres_du_logo > 200, "trait absent près du logo"
    assert cote_droit > 200, "trait droit absent"
    assert pres_du_logo > a_mi_chemin > vers_le_bord, "le trait doit s'éteindre vers le bord"
    assert vers_le_bord < 40, "le trait doit être éteint au bord"
    assert au_dessus < 40, "le trait doit rester fin"


def test_banner_has_no_background_at_all():
    """« aucun fond visible » : hors du trait, du logo et de leur halo, l'image est
    totalement transparente — sinon Discord affiche un rectangle coloré."""
    for style in log_banners.STYLES:
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            rgba = image.convert("RGBA")
            bas = log_banners.HEIGHT - 1
            # Loin du logo : rigoureusement transparent.
            for point in ((0, 0), (1023, 0), (0, bas), (1023, bas), (200, 6), (800, bas - 6)):
                assert rgba.getpixel(point)[3] == 0, f"{style} : fond peint en {point}"
            # Juste au-dessus et au-dessous du logo : le halo peut mourir ici, mais
            # il doit rester invisible (quelques unités d'alpha sur 255).
            for point in ((512, 0), (512, bas)):
                assert rgba.getpixel(point)[3] <= 12, f"{style} : halo trop marqué en {point}"
            opaques = sum(1 for valeur in rgba.getchannel("A").getdata() if valeur > 8)
        part = opaques / (log_banners.WIDTH * log_banners.HEIGHT)
        assert part < 0.25, f"{style} : {part:.0%} de l'image est peinte"


def test_the_centered_logo_is_tinted_with_the_family_colour():
    """Le logo du dépôt est bleu : non teinté, il jurait sur un trait rouge ou or."""
    def moyenne(style: str, canal: int) -> float:
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            centre = image.convert("RGBA").crop((492, 12, 532, 52))
        pixels = [p for p in centre.getdata() if p[3] > 60]
        return sum(p[canal] for p in pixels) / max(1, len(pixels))

    assert moyenne("error", 0) > moyenne("error", 2) * 1.5, "logo erreur non teinté en rouge"
    assert moyenne("success", 1) > moyenne("success", 0) * 1.5, "logo succès non teinté en vert"
    assert moyenne("music", 0) > moyenne("music", 1), "logo musique non teinté en rose"


def test_the_logo_is_exactly_centered():
    """« parfaitement centré » : le dessin doit être symétrique au pixel près."""
    with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier("info")) as image:
        alpha = image.convert("RGBA").getchannel("A")
    haut = log_banners.HEIGHT // 2 - log_banners.LOGO_BOX // 2
    colonnes = [x for x in range(log_banners.WIDTH)
                if any(alpha.getpixel((x, y)) > 40 for y in range(haut + 2, haut + 12))]
    lignes = [y for y in range(log_banners.HEIGHT)
              if any(alpha.getpixel((x, y)) > 40 for x in range(470, 554))]
    centre_x = (min(colonnes) + max(colonnes)) / 2
    centre_y = (min(lignes) + max(lignes)) / 2
    assert abs(centre_x - log_banners.WIDTH / 2) <= 1, f"logo décalé horizontalement ({centre_x})"
    assert abs(centre_y - log_banners.HEIGHT / 2) <= 1, f"logo décalé verticalement ({centre_y})"


def test_committed_source_banners_are_valid_and_match_the_generator():
    """Ces fichiers sont servis par URL GitHub raw aux réponses de commande :
    un fichier corrompu (cas réel de banner_source_warning.webp) casse l'embed
    sans aucune erreur côté bot."""
    for state in log_banners.STYLES:
        path = log_banners.BANNER_DIR / log_banners.nom_source(state)
        assert path.exists(), state
        payload = path.read_bytes()
        assert payload[:4] == b"RIFF" and payload[8:12] == b"WEBP", f"{state} : fichier illisible"
        with Image.open(BytesIO(payload)) as image:
            assert image.size == (1024, log_banners.HEIGHT), state
            assert image.mode == "RGBA", f"{state} : pas de couche alpha"
        assert path.stat().st_size < 12_000, f"{state} : {path.stat().st_size} octets"


def test_banner_uses_the_repository_logo():
    assert log_banners.LOGO_PATH.exists(), "aucun logo resolu"
    assert log_banners.LOGO_PATH.name in {"sentrix_logo.png", "brand.png"}


def test_generation_survives_a_missing_logo(tmp_path, monkeypatch):
    monkeypatch.setattr(log_banners, "LOGO_PATH", tmp_path / "absent.png")
    image = log_banners.build_banner("error")
    assert image.size == (1024, log_banners.HEIGHT)


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


def test_chaque_famille_porte_sa_couleur_sur_le_trait():
    """La couleur s'applique au trait et au logo, jamais à un fond."""
    milieu = log_banners.HEIGHT // 2
    for style, canal in (("error", 0), ("success", 1), ("info", 2), ("music", 0),
                         ("levels", 1), ("security", 2)):
        with Image.open(log_banners.BANNER_DIR / log_banners.nom_fichier(style)) as image:
            trait = image.convert("RGBA").getpixel((300, milieu))
        assert trait[3] > 120, f"{style} : trait trop pâle ({trait})"
        assert trait[canal] == max(trait[:3]), f"{style} : trait pas à la couleur ({trait})"


def test_une_famille_retiree_ne_reste_pas_sur_le_disque():
    """Le dossier survit aux déploiements : une bannière d'un ancien style pourrait
    encore être servie. ensure_banners() fait le ménage."""
    intruse = log_banners.BANNER_DIR / "banner_ancien_style.webp"
    intruse.write_bytes(b"pas une vraie image")
    try:
        log_banners.ensure_banners(force=True)
        assert not intruse.exists(), "l'ancienne bannière aurait dû être supprimée"
    finally:
        if intruse.exists():
            intruse.unlink()


def test_les_deux_chemins_de_banniere_ont_les_memes_familles():
    """Chemin panneau (pièce jointe) et chemin embed (URL GitHub raw) doivent donner
    la même couleur : sinon la même commande change d'allure selon la surface."""
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


def test_les_bannieres_servies_par_url_sont_versionnees():
    """Discord met en cache l'image d'un embed PAR URL, pendant des heures : changer
    le dessin sans changer le nom laissait l'ancienne bannière s'afficher (cas réel
    du 23/09/2026, capture de Jayden). Le nom porte donc la version du dessin."""
    from utils import command_visuals

    assert log_banners.BANNER_VERSION, "aucune version de bannière"
    for famille in log_banners.STYLES:
        nom = log_banners.nom_source(famille)
        assert log_banners.BANNER_VERSION in nom, nom
        assert command_visuals._BANNER_URLS[famille].endswith(nom), famille


def test_une_commande_en_texte_libre_n_a_pas_de_banniere_sur_les_deux_chemins():
    """+sentrix passe par le chemin embed (URL), pas par la pièce jointe : la règle
    « pas de bannière » doit valoir sur les DEUX, sinon le bandeau revient."""
    from types import SimpleNamespace

    from cogs import final_interaction_policy as policy
    from utils import command_visuals

    jeton = policy._COMMAND_CONTEXT.set(
        SimpleNamespace(command=SimpleNamespace(qualified_name="sentrix", cog_name="Ai"))
    )
    try:
        assert command_visuals.banniere_desactivee() is True
    finally:
        policy._COMMAND_CONTEXT.reset(jeton)
    assert command_visuals.banniere_desactivee() is False
