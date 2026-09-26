"""La page publique /commands partage l'identité du reste du site.

Avant le 2026-09-26 elle avait sa propre palette (``--bg:#080a11``,
``--brand:#7566ff``), différente à la fois du moteur partagé (``#070b14``)
et de la landing : le sol changeait de couleur en naviguant. Elle n'avait
pas non plus la navigation du site, seulement un lien « Retour au hub ».
"""
from __future__ import annotations

import os
import re
from unittest.mock import MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from web import public_commands_v46 as pages


def _commande(nom, aide, cog, signature=""):
    c = MagicMock()
    c.qualified_name, c.name, c.help, c.brief = nom, nom, aide, aide
    c.description, c.signature, c.cog_name = aide, signature, cog
    c.hidden, c.enabled = False, True
    return c


def _bot():
    bot = MagicMock()
    bot.commands = [
        _commande("ban", "Bannit un membre.", "Moderation", "<membre>"),
        _commande("ticket", "Ouvre un ticket.", "Tickets"),
        _commande("dragon", "Affronte un dragon.", "Jeux"),
    ]
    slash = []
    for nom, desc in (("ban", "Bannit un membre."), ("config", "Configure SentriX.")):
        c = MagicMock()
        c.qualified_name, c.name, c.description = nom, nom, desc
        slash.append(c)
    bot.tree.get_commands.return_value = slash
    return bot


def _requete() -> MagicMock:
    requete = MagicMock()
    requete.path = "/commands"
    requete.headers = {"Host": "exemple.test", "X-Forwarded-Proto": "https"}
    requete.scheme, requete.host = "https", "exemple.test"
    # La coquille calcule l'URL canonique via dashboard._public_url ; sans le
    # configurer, c'est la repr du mock qui finirait dans la balise.
    requete.app.__getitem__.return_value._public_url.return_value = "https://exemple.test"
    return requete


def _rendre() -> str:
    return pages._page(_bot(), MagicMock(), _requete())


def test_la_page_porte_le_moteur_visuel_partage():
    corps = _rendre()
    assert 'id="sxfx"' in corps
    assert "requestAnimationFrame" in corps


def test_la_page_abandonne_son_ancienne_palette():
    """Le sol ne doit plus changer de couleur en naviguant."""
    corps = _rendre()
    assert "#080a11" not in corps, "l'ancien fond isolé est toujours là"
    assert "#7566ff" not in corps, "l'ancien violet isolé est toujours là"
    assert "--fond:#070b14" in corps, "la page n'est pas sur la palette partagée"


def test_la_page_recupere_la_navigation_du_site():
    """Elle n'offrait qu'un « Retour au hub » et laissait le visiteur coincé."""
    corps = _rendre()
    for lien in ('href="/start"', 'href="/docs"', 'href="/stats"', 'href="/support"', 'href="/app"'):
        assert lien in corps, f"{lien} absent de la navigation"


def test_les_chiffres_affiches_sont_les_vrais():
    """Jayden : chiffres réels uniquement. 2 slash + 3 préfixe = 5."""
    assert "5 commandes affichées · 2 slash / · 3 préfixe +" in _rendre()


def test_la_recherche_est_utilisable_au_clavier_et_annoncee():
    corps = _rendre()
    assert 'class="sx-sr"' in corps, "le champ de recherche n'a pas de label"
    assert 'aria-live="polite"' in corps, "le nombre de résultats n'est pas annoncé"
    boutons = re.findall(r"<button[^>]*>", corps)
    assert len(boutons) == 3, "les trois filtres ne sont pas rendus"
    assert all("aria-pressed" in b for b in boutons), "les filtres n'exposent pas leur état"
    assert ":focus-visible" in corps


def test_les_cartes_de_commandes_ne_portent_pas_l_inclinaison():
    """Garde de performance.

    La coquille attache un écouteur de pointeur et une animation d'entrée à
    chaque ``.card``. Sur une page qui liste plusieurs centaines de commandes
    cela ferait autant d'écouteurs et autant d'animations au chargement, donc
    la grille utilise ``.cmd``.
    """
    corps = _rendre()
    grille = corps[corps.index('class="cmd-grille"') :]
    assert 'class="card"' not in grille
    assert grille.count('class="cmd"') == 5


def test_la_page_reste_indexable():
    corps = _rendre()
    assert '<link rel="canonical" href="https://exemple.test/commands">' in corps
    assert "index,follow" in corps


@pytest.mark.parametrize("valeur", ['" onmouseover="alert(1)', "<script>alert(1)</script>"])
def test_une_description_hostile_est_echappee(valeur):
    bot = _bot()
    bot.commands = [_commande("piege", valeur, "Autres")]
    corps = pages._page(bot, MagicMock(), _requete())
    assert "<script>alert(1)</script>" not in corps
    assert 'onmouseover="alert(1)"' not in corps


def test_le_script_de_la_page_est_syntaxiquement_valide():
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("node"):
        pytest.skip("node absent")
    scripts = re.findall(r"<script>(.*?)</script>", _rendre(), re.S)
    assert len(scripts) == 3, "moteur + inclinaison + recherche"
    for index, source in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fichier:
            fichier.write(source)
            chemin = fichier.name
        resultat = subprocess.run(["node", "--check", chemin], capture_output=True, text=True)
        assert resultat.returncode == 0, f"script {index} : {resultat.stderr}"


def _bot_vide():
    """Une instance qui ne détient pas le bail HA.

    Mesuré en production le 2026-09-26 : l'instance non-leader répond
    ``discord_ready: false`` et ``extensions_loaded: 0/58``, donc
    ``bot.commands`` est vide et ``tree.get_commands()`` ne renvoie rien.
    """
    bot = MagicMock()
    bot.commands = []
    bot.tree.get_commands.return_value = []
    return bot


def test_une_instance_sans_commandes_ne_annonce_pas_zero():
    """Un « 0 commandes » a l'air d'un vrai chiffre. Il est faux.

    Jayden : « chiffres réels uniquement, jamais inventés ». Dire qu'on ne
    sait pas est exact ; annoncer zéro ne l'est pas. /stats fait déjà ça
    correctement avec ses tirets et son « Chargement… ».
    """
    corps = pages._page(_bot_vide(), MagicMock(), _requete())
    assert "0 commandes affichées" not in corps
    assert "0 slash" not in corps
    assert "Liste momentanément indisponible" in corps


def test_la_page_d_attente_garde_l_identite_et_une_sortie():
    corps = pages._page(_bot_vide(), MagicMock(), _requete())
    assert 'id="sxfx"' in corps, "la page d'attente perd l'identité du site"
    assert 'href="/support"' in corps, "aucune sortie proposée au visiteur"
    assert 'href="/commands"' in corps, "impossible de réessayer"


def test_la_page_d_attente_n_est_ni_mise_en_cache_ni_indexee():
    """Sinon un accident de démarrage survit bien après qu'il soit passé."""
    import asyncio

    requete = _requete()
    requete.app.get.side_effect = lambda cle, defaut=None: {
        "dashboard_module": MagicMock(),
        "bot": _bot_vide(),
    }.get(cle, defaut)
    reponse = asyncio.run(pages.commands_page(requete))
    assert reponse.status == 503
    assert reponse.headers["Cache-Control"] == "no-store"
    assert reponse.headers["X-Robots-Tag"] == "noindex"


def test_une_instance_qui_a_les_commandes_reste_indexable():
    import asyncio

    requete = _requete()
    requete.app.get.side_effect = lambda cle, defaut=None: {
        "dashboard_module": MagicMock(),
        "bot": _bot(),
    }.get(cle, defaut)
    reponse = asyncio.run(pages.commands_page(requete))
    assert reponse.status == 200
    assert "max-age=60" in reponse.headers["Cache-Control"]
    assert reponse.headers["X-Robots-Tag"] == "index, follow"


def test_les_descriptions_longues_ne_debordent_pas_sur_telephone():
    """Mesuré en production le 2026-09-26 à 360px de large.

    La description de ``+statut`` contient
    « (playing/streaming/listening/watching/competing). », 48 caractères sans
    espace. Avec le ``overflow-wrap: normal`` par défaut, elle sortait de sa
    carte : 362 px de contenu pour 302 px disponibles.
    """
    corps = _rendre()
    debut = corps.index(".cmd p{")
    assert "overflow-wrap:anywhere" in corps[debut : corps.index("}", debut)]
