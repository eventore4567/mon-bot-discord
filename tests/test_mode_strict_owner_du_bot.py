"""« Sanctionner aussi les admins » : le propriétaire du bot y a droit (21/11/2026).

« fait que je puisse activer sanctionner les admins même si je suis pas owner,
car je suis le owner du bot. »

La commande ``+automod-strict`` acceptait déjà le propriétaire de SentriX. Le
bouton de /setup → Sécurité, lui, ne comparait qu'à ``guild.owner_id`` : le
propriétaire du bot se faisait refuser l'option dans l'interface alors que la
commande équivalente la lui donnait. Deux règles pour une seule décision, c'est
une de trop.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

import config  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402

PEUT = AutoMod.peut_changer_mode_strict


@pytest.fixture
def owners_du_bot(monkeypatch):
    monkeypatch.setattr(config, "OWNER_IDS", [4242], raising=False)
    return [4242]


def _guild(owner_id=999):
    return SimpleNamespace(id=1, owner_id=owner_id)


def test_le_proprietaire_du_serveur_peut(owners_du_bot):
    assert PEUT(999, _guild()) is True


def test_le_proprietaire_du_bot_peut_sur_un_serveur_qui_n_est_pas_le_sien(owners_du_bot):
    assert PEUT(4242, _guild(owner_id=999)) is True


def test_un_administrateur_quelconque_ne_peut_pas(owners_du_bot):
    """Sinon n'importe quel admin se retirerait lui-même de la surveillance.

    C'est tout l'objet de l'option : la demander à quelqu'un qui en est la
    cible la viderait de son sens.
    """
    assert PEUT(123, _guild()) is False


def test_un_identifiant_illisible_ne_passe_pas(owners_du_bot):
    """Un refus vaut mieux qu'une exception dans un callback de bouton.

    Une exception dans un callback Discord laisse l'interaction sans réponse :
    l'utilisateur voit « L'application ne répond pas » sans savoir pourquoi.
    """
    assert PEUT(None, _guild()) is False
    assert PEUT("pas un id", _guild()) is False


def test_sans_liste_de_proprietaires_seul_le_proprietaire_du_serveur_passe(monkeypatch):
    monkeypatch.setattr(config, "OWNER_IDS", None, raising=False)
    assert PEUT(999, _guild()) is True
    assert PEUT(4242, _guild()) is False


def test_la_commande_et_le_bouton_lisent_la_meme_regle():
    """Garde-fou contre la divergence qui a créé le bug.

    Si quelqu'un remet un ``i.user.id != guild.owner_id`` en dur dans l'écran
    Sécurité, ce test le voit.
    """
    import io

    ui = io.open("cogs/complete_security_setup.py", encoding="utf-8").read()
    assert "peut_changer_mode_strict" in ui
    assert "i.user.id != self.guild.owner_id" not in ui

    cog = io.open("cogs/automod.py", encoding="utf-8").read()
    assert "if not self.peut_changer_mode_strict(ctx.author.id, ctx.guild):" in cog
