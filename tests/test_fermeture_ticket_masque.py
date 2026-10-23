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
from cogs import ticket_claim_security


def _source_fermeture() -> str:
    """Lis le VRAI gestionnaire sécurisé, appelé par le pont V6."""
    src = inspect.getsource(ticket_claim_security)
    debut = src.index("async def secure_close_ticket")
    fin = src.index("\n    async def secure_claim", debut)
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
    assert "status='ferme'" in src
    assert "closed_at" in src


def test_un_refus_de_discord_annule_la_fermeture():
    """Ne jamais annoncer « fermé » si le membre lit encore le salon."""
    src = _source_fermeture()
    assert "status='ouvert'" in src, "il manque le retour arrière"
    assert "a refusé de masquer" in src


def test_le_message_dit_quoi_faire_ensuite():
    src = _source_fermeture()
    assert "vue_ticket_ferme(ticket_id)" in src
    assert "ticket_panels_v3.closed_card(" in src


def test_la_commande_de_reouverture_existe_toujours():
    assert 'name="ticket-reopen"' in inspect.getsource(tickets)


def test_c_est_bien_la_version_v6_qui_est_installee():
    """Le patch V6 sur l'instance doit maintenant DELEGUER au code sûr."""
    src = inspect.getsource(v6)
    assert "tickets_cog.close_ticket = types.MethodType(close_ticket_v6, tickets_cog)" in src
    assert "ticket_claim_security.close_ticket_via_security(" in src
    assert "embed=close_embed" not in src
    assert "view=_ticket_actions(" not in inspect.getsource(v6)[
        inspect.getsource(v6).index("async def close_ticket_v6"):
        inspect.getsource(v6).index("canonical_log_action._sentrix_unified_v6")
    ]
