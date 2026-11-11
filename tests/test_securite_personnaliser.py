"""11/11/2026 : l'écran « Personnaliser » de la Sécurité.

Capture de l'utilisateur : cinq compteurs par famille dont « Avancé · 0/0 actives »,
un paragraphe sur la vérification, six boutons sur trois rangées — et l'option
« Sanctionner les admins » introuvable, enterrée derrière « Exceptions générales ».
"""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

SOURCE = (Path(__file__).resolve().parents[1] / "cogs" / "complete_security_setup.py").read_text(encoding="utf-8")


def test_l_option_sanctionner_les_admins_est_sur_l_ecran():
    # Le bouton est construit avec les autres, pas dans global_exceptions.
    ecran = SOURCE.split("async def global_exceptions", 1)[0]
    assert 'f"Sanctionner les admins : {\'Oui\' if strict else \'Non\'}"' in ecran
    assert "boutons.append(button(" in ecran


def test_seul_le_proprietaire_peut_changer_cette_option():
    bloc = SOURCE.split("async def admins(i, actuel=strict):", 1)[1][:600]
    assert "i.user.id != self.guild.owner_id" in bloc
    assert "Seul le propriétaire du serveur" in bloc
    # L'état lu à la construction est figé dans le défaut : deux clics rapides ne
    # peuvent pas réappliquer la même valeur.
    assert "definir_admins_soumis(self.guild.id, not actuel" in bloc


def test_un_seul_compteur_au_lieu_de_cinq_familles():
    assert 'for group in ("Messages", "Arrivées", "Serveur", "Réponse", "Avancé")' not in SOURCE
    assert 'f"**{actives} protections actives sur {len(states)}.** "' in SOURCE


def test_l_ecran_porte_la_banniere_des_autres_pages():
    assert "securite_simple.conteneur(" in SOURCE


def test_les_boutons_tiennent_dans_les_rangees_de_discord():
    assert "for debut in range(0, len(boutons), 5):" in SOURCE
    assert "box.add_item(discord.ui.ActionRow(*boutons[debut:debut + 5]))" in SOURCE


def test_le_paragraphe_sur_la_verification_est_devenu_une_ligne():
    assert "choices.EXTRAS_NOT_INSTALLED" not in SOURCE
    assert "-# Salon piège et Vérification demandent d'installer la vérification." in SOURCE
