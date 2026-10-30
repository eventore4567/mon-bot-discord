"""Le panneau /setup doit décrire le vrai parcours de vérification."""
from pathlib import Path


def test_adaptive_setup_describes_web_captcha_and_score():
    text = Path("cogs/automatic_verification_v5.py").read_text(encoding="utf-8")
    section = text.split("async def build_embed(self):", 1)[1].split("build_embed._sentrix_auto_verification_v5_display", 1)[0]
    assert "Aucun captcha ni calcul" not in section
    assert "**40 signaux**" in section
    assert "**8 familles pondérées**" in section
    assert "score sur **20**" in section
    assert "**portail web SentriX**" in section
    assert "CAPTCHA" in section
    assert "ne donne jamais directement le rôle final" in section
