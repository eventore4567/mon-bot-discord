"""Journaux : le bon sujet en en-tête, et le vrai modérateur.

Mesuré le 08/10/2026 sur le bot booté :
- `role_add` était rendu comme un événement DE RÔLE : « Rôle · <@&identifiant du
  membre> » ;
- la fonction `journaliser` nommait le modérateur « Auteur », étiquette que le
  moteur prend pour le SUJET : « Salon · <#identifiant du modérateur> » ;
- une action passée par une commande SentriX est faite par le bot : le journal
  d'audit nomme SentriX, pas le modérateur.
"""
import time

from utils import audit_trail, wide_logs


def test_role_donne_a_un_membre_est_un_evenement_de_membre():
    for event in ("role_add", "role_remove"):
        assert wide_logs._trace_identity_label(event) == "Membre"
        assert wide_logs._trace_identity_ref(event, 77) == "<@77>"


def test_un_vrai_evenement_de_role_reste_un_role():
    assert wide_logs._trace_identity_label("role_create") == "Rôle"
    assert wide_logs._trace_identity_ref("role_create", 5) == "<@&5>"


def test_actions_staff_sur_un_membre():
    for event in ("warnings_cleared", "levels_xp_set", "economy_grant"):
        assert wide_logs._trace_identity_label(event) == "Membre", event
        assert wide_logs._trace_identity_ref(event, 77) == "<@77>", event


class _Bot:
    pass


def test_l_acteur_note_est_relu_une_seule_fois():
    bot = _Bot()
    audit_trail.noter_acteur(bot, 1, 77, "member_role_update", 79)
    assert audit_trail.acteur_local(bot, 1, 77, "member_role_update") == 79
    assert audit_trail.acteur_local(bot, 1, 77, "member_role_update") is None


def test_l_acteur_ne_se_trompe_pas_de_cible_ni_d_action():
    bot = _Bot()
    audit_trail.noter_acteur(bot, 1, 77, "member_role_update", 79)
    assert audit_trail.acteur_local(bot, 1, 78, "member_role_update") is None
    assert audit_trail.acteur_local(bot, 1, 77, "member_update") is None
    assert audit_trail.acteur_local(bot, 2, 77, "member_role_update") is None


def test_un_acteur_trop_ancien_est_ignore(monkeypatch):
    bot = _Bot()
    audit_trail.noter_acteur(bot, 1, 77, "member_update", 79)
    reel = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: reel() + audit_trail._LOCAL_ACTOR_TTL + 1)
    assert audit_trail.acteur_local(bot, 1, 77, "member_update") is None
