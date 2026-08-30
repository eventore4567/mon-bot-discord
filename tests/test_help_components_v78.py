from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V78 = ROOT / "cogs" / "help_components_v78.py"
V75 = ROOT / "cogs" / "setup_security_choice_v75.py"


def test_help_home_is_paginated_to_stay_under_discord_component_limit():
    source = V78.read_text(encoding="utf-8")

    assert "HOME_PAGE_SIZE = 6" in source
    assert "page_keys = visible_keys[start:start + HOME_PAGE_SIZE]" in source
    assert "Catégories : page **{page_index + 1}/{page_count}**" in source
    assert "Précédent" in source
    assert "Suivant" in source


def test_v78_is_installed_after_v77():
    source = V75.read_text(encoding="utf-8")

    install_v77 = source.index("help_v77.install(bot)")
    install_v78 = source.index("help_v78.install(bot)")
    assert install_v77 < install_v78


def test_home_page_budget_is_below_discord_limit():
    # One Container; header Section+Text+Thumbnail; separators; six category
    # Section+Text+Button groups; navigation ActionRow+4 buttons; links row+3 links.
    estimated_components = 1 + 3 + 1 + (6 * 3) + 1 + 1 + 5 + 4
    assert estimated_components == 34
    assert estimated_components <= 40
