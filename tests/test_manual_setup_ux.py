from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_essential_flow_is_ordered_and_advanced_is_collapsed():
    source = (ROOT / "web" / "dashboard.py").read_text(encoding="utf-8")
    essential = [
        'data-tab="general"',
        'data-tab="security"',
        'data-tab="logs"',
        'data-tab="tickets"',
        'data-tab="welcome"',
    ]
    positions = [source.index(item) for item in essential]
    assert positions == sorted(positions)
    assert 'id="advancedToggle"' in source
    assert 'data-advanced class="hidden"' in source
    assert "Bienvenue & Départ" in source


def test_setup_has_no_automatic_apply_ui():
    source = (ROOT / "sentrix_setup_compact_v113.py").read_text(encoding="utf-8")
    assert 'label="Smart Setup"' not in source
    assert 'label="Appliquer"' not in source
    assert 'placeholder="Choisir ce que Smart Setup peut modifier"' not in source
    assert "create_text_channel(" not in source
    assert "create_role(" not in source
    assert "configuration automatique est désactivée" in source


def test_guided_setup_matches_dashboard_essential_order():
    source = (ROOT / "sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    positions = [
        source.index('"security"'),
        source.index('"logs"'),
        source.index('"tickets"'),
        source.index('"members"'),
    ]
    assert positions == sorted(positions)


def test_guided_setup_hides_advanced_by_default_and_has_no_smart_setup():
    source = (ROOT / "sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert 'ESSENTIAL_MODULE_KEYS' in source
    assert 'ADVANCED_MODULE_KEYS' in source
    assert '"security",\n    "logs",\n    "tickets",\n    "members",' in source
    assert 'label="Afficher les réglages avancés"' in source
    assert 'label="Smart Setup"' not in source
    assert 'Setup manuel guidé' in source


def test_guided_setup_states_no_automatic_configuration():
    source = (ROOT / "sentrix_setup_guided_v117.py").read_text(encoding="utf-8")
    assert "Aucun salon, rôle ou réglage n’est choisi ou créé automatiquement." in source
