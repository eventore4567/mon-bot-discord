from types import SimpleNamespace

from web import dashboard_motion_audio_v27 as v27
import pytest


def _dashboard():
    return SimpleNamespace(
        INDEX_HTML='<!doctype html><html><head></head><body><main id="content"><h1>Dashboard</h1></main></body></html>'
    )


def test_v27_installs_once_and_preserves_real_content():
    dashboard = _dashboard()
    assert v27.install(dashboard) is True
    html = dashboard.INDEX_HTML
    assert html.count('id="sentrix-dashboard-motion-audio-v27"') == 1
    assert html.count('id="sentrix-dashboard-motion-audio-v27-js"') == 1
    assert "__sentrixDashboardMotionAudioV27" in html
    assert "<h1>Dashboard</h1>" in html

    first = dashboard.INDEX_HTML
    assert v27.install(dashboard) is True
    assert dashboard.INDEX_HTML == first


def test_v27_targets_real_v15_dom_with_web_animations_and_trusted_audio():
    style = v27.STYLE
    script = v27.SCRIPT

    assert "setInterval(" not in script
    assert "MutationObserver" in script
    assert ".animate([" in script
    assert "AudioContext" in script
    assert "webkitAudioContext" in script
    assert "event.isTrusted" in script
    assert "createOscillator" in script
    assert "createGain" in script
    assert "sentrix:ui-sound-v27" in script
    assert "window.__sentrixMotionV27" in script
    assert 'setSound(enabled)' in script
    assert '".nav button,button[data-tab]' in script
    assert '".card,.metric,.p18-card' in script
    assert '".row,.p18-table tbody tr' in script
    # Anti-clignotement : l'entrée d'une page ne part plus d'opacity 0 / flou / réduction,
    # et un rafraîchissement de données ne rejoue jamais les cartes.
    assert "scale(.925)" not in script
    assert "blur(5px)" not in script
    assert "opacity:0,transform:\"translateY(22px)" not in script
    assert "if (transitionPending) animateEnter();" in script
    assert "else animateSurfaceNodes()" not in script
    assert "scale(.90)" in script

    # Barre de progression en haut retirée (quatre couches en empilaient une chacune).
    assert "#sx27Progress" not in style
    assert "#sx27Flash" in style
    assert "sx27-ring" in style
    assert "@media(prefers-reduced-motion:reduce)" in style


def test_v27_is_built_for_the_browser_visible_v15_renderer():
    source = open("web/dashboard_live_response_v15.py", encoding="utf-8").read()
    assert "function renderAutoReactV15()" in source
    assert "Choisis toi-même les emojis ajoutés par SentriX." in source
    assert "Règles configurées" in source
    assert "class=\"card full\"" in source
    assert "class=\"row\"" in source


@pytest.mark.skip(reason="Couche historique retirée du programme /app (refonte 2026-09, lot 1) : le finalizer sert un programme unique ; suppression de la couche au lot 7.")
def test_v27_runs_after_v26_as_the_last_presentation_authority():
    source = open("sentrix_dashboard_finalizer_v7.py", encoding="utf-8").read()
    assert "from web import dashboard_motion_audio_v27" in source
    assert "dashboard_motion_audio_v27.install(dashboard)" in source
    assert source.index("dashboard_visible_motion_v26.install(dashboard)") < source.index(
        "dashboard_motion_audio_v27.install(dashboard)"
    )
    assert 'id="sentrix-dashboard-motion-audio-v27"' in source
    assert "motion_audio_v27" in source
