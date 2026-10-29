"""Le « + » est retiré le 30/11/2026 : un texte qui cite une commande montre sa
route « / » dès qu'elle est publiée (utils/sentrix_panels.commandes_en_code)."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import sentrix_panels as panels  # noqa: E402


def test_hors_du_code_la_commande_devient_sa_route_slash():
    assert panels.commandes_en_code("Tapez +help.") == "Tapez `/help`."
    assert panels.commandes_en_code("Utilisez +pay @x 10") == "Utilisez `/economy pay` @x 10"


def test_dans_le_code_les_arguments_suivent_la_route():
    texte = "`+shoprole add @VIP 500` — ajoute un rôle"
    assert panels.commandes_en_code(texte) == "`/shop role-add @VIP 500` — ajoute un rôle"


def test_sans_route_publiee_le_texte_reste_tel_quel():
    assert panels.commandes_en_code("Lancez `+infinit`.") == "Lancez `+infinit`."
    assert panels.commandes_en_code("`+alias add`") == "`+alias add`"


def test_ni_montant_ni_lien():
    assert panels.commandes_en_code("Gagnez +50 pièces") == "Gagnez +50 pièces"
    assert panels.commandes_en_code("https://x.y/+help") == "https://x.y/+help"


def test_un_historique_garde_la_commande_tapee():
    with panels.commandes_litterales():
        assert panels.commandes_en_code("Commande `+warn`") == "Commande `+warn`"
    assert panels.commandes_en_code("Commande `+warn`") == "Commande `/warn`"
