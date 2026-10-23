"""Fermer un ticket le masque ; il n'est plus supprimé d'office.

Demandé par Jayden : « quand tu close / delete / rouvrir, quand on met
sur close ça garde tout en base, au moins ça close pas d'un coup, et ça
cache la visibilité du salon ».

Le ``close_ticket`` de cogs/tickets.py faisait déjà exactement cela — et
c'était du code mort : cogs/logs_unified_v6 remplace la méthode sur
l'instance du cog, et sa version faisait deux choses de travers :

- elle ne posait que ``send_messages = False``, donc le membre continuait
  de VOIR le salon et de lire les échanges entre staff ;
- elle programmait ``_auto_delete`` avec un délai de 30 secondes par
  défaut, et annonçait « Suppression automatique dans 30 seconde(s) ».

Le salon et la transcription disparaissaient donc d'un coup, sans retour
possible, alors que ``+ticket-reopen`` existe.
"""
from __future__ import annotations

import inspect
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs import logs_unified_v6 as v6
from cogs import tickets


def _source_fermeture() -> str:
    """La fermeture réellement installée, pas celle de tickets.py."""
    src = inspect.getsource(v6)
    debut = src.index("async def close_ticket_v6")
    fin = src.index("\ndef ", debut)
    return src[debut:fin]


def test_la_fermeture_retire_le_salon_de_la_vue_du_membre():
    src = _source_fermeture()
    assert "view_channel = False" in src, (
        "sans cela le membre voit encore le salon et lit la suite des échanges"
    )
    assert "read_message_history = False" in src


def test_la_fermeture_ne_programme_plus_de_suppression():
    src = _source_fermeture()
    assert "_auto_delete" not in src, "fermer n'est pas supprimer"
    assert "Suppression automatique" not in src


def test_le_ticket_reste_en_base_avec_son_statut():
    src = _source_fermeture()
    assert "status = 'ferme'" in src
    assert "closed_at" in src


def test_un_refus_de_discord_annule_la_fermeture():
    """Ne jamais annoncer « fermé » si le membre lit encore le salon."""
    src = _source_fermeture()
    assert "status='ouvert'" in src, "il manque le retour arrière"
    assert "a refusé de masquer" in src


def test_le_message_dit_quoi_faire_ensuite():
    src = _source_fermeture()
    assert "ticket-reopen" in src, "le staff doit savoir comment rendre le salon"


def test_la_commande_de_reouverture_existe_toujours():
    assert 'name="ticket-reopen"' in inspect.getsource(tickets)


def test_c_est_bien_la_version_v6_qui_est_installee():
    """Garde contre le piège : corriger tickets.py seul ne servirait à rien."""
    src = inspect.getsource(v6)
    assert "tickets_cog.close_ticket = types.MethodType(close_ticket_v6, tickets_cog)" in src
