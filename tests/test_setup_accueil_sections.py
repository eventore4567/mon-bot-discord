"""/setup : accueil en six sections (22/11/2026).

« Refais tout le setup, plus simple, plus beau. » L'accueil alignait un menu de
22 entrées sans ordre. Les mêmes réglages sont rangés en six sections ; aucun
réglage n'a changé de place, seul le chemin pour y arriver.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import setup_experience_v74 as v74  # noqa: E402

#: Les 22 réglages de l'ancien menu (13 modules + 9 fonctions).
ANCIEN_MENU = {
    "security", "moderation", "tickets", "welcome", "goodbye", "roles", "logs", "invitations",
    "levels", "economy", "notifications", "music", "ai",
    "rules_access", "suggestions", "embeds", "custom_commands", "prefixes", "snippets",
    "recurring_messages", "automation", "language",
}


def test_aucun_reglage_de_l_ancien_menu_n_est_perdu():
    ranges = [page for section in v74.SECTIONS for page in section[6]]
    assert set(ranges) == ANCIEN_MENU
    assert len(ranges) == len(set(ranges)), "un réglage rangé dans deux sections"


def test_six_sections_tiennent_sur_deux_rangees_de_boutons():
    assert len(v74.SECTIONS) == 6  # 2 rangées de 3 : Discord en accepte 5 par rangée


def test_chaque_section_a_ses_textes_dans_les_deux_langues():
    for cle, nom_fr, nom_en, icone, desc_fr, desc_en, pages in v74.SECTIONS:
        assert nom_fr and nom_en and desc_fr and desc_en and icone, cle
        assert pages, cle


def test_chaque_fonction_hors_module_a_ses_textes():
    for cle, (nom, desc, nom_en, desc_en) in v74.EXTRAS.items():
        assert nom and desc and nom_en and desc_en, cle


def test_les_fiches_prennent_l_emoji_anime_du_pack(monkeypatch):
    """23/11/2026 : « mets les émojis animés ». Pack synchronisé : l'émoji animé
    SentriX ; pas encore synchronisé : l'Unicode, jamais un marqueur cassé."""
    from utils import sentrix_emojis

    monkeypatch.setattr(sentrix_emojis, "emoji", lambda nom: f"<a:{nom}:123>")
    assert v74.icone_section("securite") == "<a:sentrix_live_security:123>"
    monkeypatch.setattr(sentrix_emojis, "emoji", lambda nom: "")
    assert v74.icone_section("securite") == "🛡️"
    monkeypatch.setattr(sentrix_emojis, "emoji", lambda nom: "◆")  # repli typographique
    assert v74.icone_section("moderation") == "⚖️"


def test_chaque_icone_animee_existe_dans_le_pack():
    from pathlib import Path

    dossier = Path(v74.__file__).resolve().parents[1] / "assets" / "sentrix_emojis"
    for cle, (nom, _repli) in v74.ICONES_SECTIONS.items():
        assert (dossier / f"{nom}.gif").exists(), (cle, nom)
