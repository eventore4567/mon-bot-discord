"""Le fond de la carte de niveau est généré, plus chargé depuis un fichier.

**Ce que la mesure a montré.** ``assets/sentrix/card-background-v5.png`` pèse
786 Ko et ne se décode pas :

    OSError: unrecognized data stream contents when reading image file

``_render_card_sync`` attrapait donc systématiquement l'exception et peignait
son repli de secours — cent bandes plates de douze pixels, quatre-vingts
couleurs en tout, marches visibles à l'œil. Ce n'est pas un fond « trop
chargé » que voyaient les membres : c'est un dégradé cassé, et rien ne le
signalait puisque le repli existait justement pour ne pas planter.

``banner-v70.png`` est corrompu de la même façon.
"""
from __future__ import annotations

import io
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils.visual_v5 import _font, fond_de_carte

ACCENT = (108, 92, 231)
SECONDAIRE = (76, 125, 255)


# =============================================================================
# Le dégradé est réellement lisse
# =============================================================================

def test_le_fond_na_pas_de_marches_visibles():
    """Le défaut mesuré sur le repli : entre deux pixels voisins, la somme des
    composantes sautait d'un coup tous les douze pixels. Un écart de 3 au
    maximum est invisible à l'œil."""
    image = fond_de_carte(1200, 400, ACCENT, SECONDAIRE).convert("RGB")
    ecart_max = max(
        abs(sum(image.getpixel((x, 200))) - sum(image.getpixel((x + 1, 200))))
        for x in range(image.width - 1)
    )
    assert ecart_max <= 4, f"marches visibles : écart de {ecart_max} entre deux pixels"


def test_le_fond_a_bien_plus_de_couleurs_que_lancien_repli():
    """L'ancien repli n'en avait que 80 pour 480 000 pixels, réparties en cent
    bandes plates. Un fond neutre en a forcément moins qu'un fond coloré — c'est
    l'ÉCART entre pixels voisins qui dit s'il est lisse, pas le décompte — mais
    il doit rester largement au-dessus du repli."""
    image = fond_de_carte(1200, 400, ACCENT, SECONDAIRE).convert("RGB")
    couleurs = len(set(image.getdata()))
    assert couleurs > 110, f"seulement {couleurs} couleurs : le dégradé est plat"


def test_le_fond_est_neutre_quelles_que_soient_les_couleurs_du_serveur():
    """Changement de parti pris, demandé par Jayden : « enlève le style bleu
    violet, je veux une couleur simple, pas IA ».

    Le fond était teinté par l'accent, ce qui donnait avec les couleurs par
    défaut de SentriX un dégradé violet vers bleu — le cliché visuel par
    excellence. Il est maintenant une ardoise neutre, identique partout, et
    l'accent ne sert plus qu'aux éléments qui doivent ressortir.
    """
    violet = fond_de_carte(300, 100, (108, 92, 231), (76, 125, 255)).convert("RGB")
    vert = fond_de_carte(300, 100, (33, 208, 122), (15, 163, 163)).convert("RGB")
    assert violet.getpixel((250, 20)) == vert.getpixel((250, 20)), (
        "le fond est encore teinté par l'accent du serveur"
    )
    # Neutre veut dire neutre : aucune composante ne domine.
    for x, y in ((280, 10), (30, 90), (150, 50)):
        r, v, b = violet.getpixel((x, y))
        assert max(r, v, b) - min(r, v, b) <= 8, f"teinte résiduelle en {(x, y)} : {(r, v, b)}"


def test_laccent_du_serveur_reste_visible_sur_la_carte():
    """Le fond devient neutre, mais la personnalisation ne disparaît pas : elle
    se déplace sur la barre de progression, l'anneau de l'avatar et le liseré.
    Sans ce test, « fond neutre » pourrait silencieusement devenir « plus aucune
    couleur nulle part », et le réglage du dashboard ne servirait plus à rien.
    """
    import io

    from PIL import Image, ImageDraw

    from utils.visual_v5 import _render_card_sync

    avatar = io.BytesIO()
    Image.new("RGB", (64, 64), (70, 72, 80)).save(avatar, "PNG")
    stats = {"current_level": 5, "current_level_xp": 10, "required_xp": 100,
             "rank": 1, "is_ranked": True, "message_count": 1, "total_money": 1}

    def couleurs(reglages):
        sortie = _render_card_sync(avatar.getvalue(), "A", "S", stats, reglages,
                                   5, True, True)
        return set(Image.open(sortie).convert("RGB").getdata())

    ambre = couleurs({"primary_color": 0xE8B04B, "secondary_color": 0xC08A2E})
    # Un orange franc doit apparaître quelque part sur la carte ambre.
    assert any(r > 180 and v > 130 and b < 120 for r, v, b in ambre), (
        "l'accent du serveur n'apparaît nulle part : la personnalisation est perdue"
    )


def test_le_fond_va_du_sombre_au_clair():
    """Un dégradé qui ne descend pas assez laisse le texte clair illisible
    au-dessus ; un qui ne monte pas du tout n'est plus un dégradé."""
    image = fond_de_carte(1200, 400, ACCENT, SECONDAIRE).convert("RGB")
    sombre = sum(image.getpixel((5, 395)))
    clair = sum(image.getpixel((1195, 5)))
    assert clair > sombre, "le dégradé est à l'envers ou inexistant"
    assert sombre < 200, "le coin sombre est trop clair pour du texte blanc"


@pytest.mark.parametrize("taille", [(1200, 400), (600, 200), (64, 64)])
def test_le_fond_accepte_nimporte_quelle_taille(taille):
    image = fond_de_carte(*taille, ACCENT, SECONDAIRE)
    assert image.size == taille
    assert image.mode == "RGBA"


def test_le_fond_reste_leger():
    """786 Ko pour un fond était déjà excessif ; un fond généré doit rester très
    en dessous, il part en pièce jointe à chaque montée de niveau."""
    image = fond_de_carte(1200, 400, ACCENT, SECONDAIRE).convert("RGB")
    tampon = io.BytesIO()
    image.save(tampon, format="PNG", optimize=True)
    assert len(tampon.getvalue()) < 120_000


# =============================================================================
# Plus aucune dépendance à un fichier qui peut se corrompre
# =============================================================================

def test_la_carte_ne_charge_plus_dimage_de_fond():
    import inspect

    from utils import visual_v5

    source = inspect.getsource(visual_v5._render_card_sync)
    assert "CARD_BACKGROUND" not in source, (
        "la carte recharge un fichier de fond : le jour où il se corrompt, le "
        "repli reprend la main sans que rien ne le signale"
    )
    assert "fond_de_carte" in source


def test_lasset_dorigine_est_bien_illisible():
    """Garde-fou de la mesure : si ce fichier redevenait lisible un jour, ce
    test échouerait et rappellerait de reconsidérer le choix. Tant qu'il est
    corrompu, générer est la seule option correcte."""
    from PIL import Image

    from utils.visual_v5 import CARD_BACKGROUND

    if not CARD_BACKGROUND.exists():
        pytest.skip("asset absent, rien à vérifier")
    with pytest.raises(Exception):
        Image.open(CARD_BACKGROUND).convert("RGB").getpixel((1, 1))


# =============================================================================
# La police de repli
# =============================================================================

def test_la_police_de_repli_respecte_la_taille_demandee():
    """``load_default()`` sans argument rend une police de taille FIXE : toute
    la carte s'affichait au même corps minuscule, quel que soit le 50, 28 ou 20
    demandé. Invisible sur Railway, où DejaVu existe — et immédiat le jour où
    l'image de base change."""
    petite = _font(14)
    grande = _font(50, bold=True)
    hauteur_petite = petite.getbbox("A")[3] - petite.getbbox("A")[1]
    hauteur_grande = grande.getbbox("A")[3] - grande.getbbox("A")[1]
    assert hauteur_grande > hauteur_petite * 2, (
        f"la taille n'est pas respectée : {hauteur_petite} contre {hauteur_grande}"
    )


def test_la_police_rend_les_accents_et_le_separateur():
    """« Économie » s'affichait « ⊠conomie » avec la police par défaut de
    Pillow, et le point médian sortait en carré. Sur un bot français, un É qui
    ne s'affiche pas se remarque tout de suite."""
    police = _font(30)
    for caractere in ("É", "è", "à", "•"):
        boite = police.getbbox(caractere)
        assert boite is not None and boite[2] > boite[0], f"{caractere!r} ne rend rien"
