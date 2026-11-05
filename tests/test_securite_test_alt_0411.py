"""04/11/2026 (soir) : test avec un compte secondaire non admin.

- Le honeypot ignorait un membre ordinaire qui écrivait dans le salon piège
  (« n'a pas le rôle non vérifié ») : il est désormais pris.
- Un lien d'arnaque était seulement supprimé : sanction immédiate.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import security_verification_v71 as v71  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _membre(*, admin=False, gerer=False, roles=(), owner=False, bot=False):
    guild = SimpleNamespace(owner_id=1 if owner else 999)
    return SimpleNamespace(
        id=1, bot=bot, guild=guild,
        guild_permissions=SimpleNamespace(administrator=admin, manage_guild=gerer),
        roles=[SimpleNamespace(id=r) for r in roles],
    )


def _runtime():
    classe = next(
        obj for obj in vars(v71).values()
        if isinstance(obj, type) and hasattr(obj, "_staff_bypass")
    )
    return classe.__new__(classe)


CONF = {"verified_role_id": 50, "unverified_role_id": 60, "trap_channel_id": 70}


def test_un_membre_ordinaire_dans_le_salon_piege_est_pris():
    runtime = _runtime()
    assert runtime._staff_bypass(_membre(), CONF) is False
    assert runtime._raison_bypass(_membre(), CONF) == "aucune exemption"


def test_staff_et_proprietaire_restent_exemptes():
    runtime = _runtime()
    assert runtime._staff_bypass(_membre(admin=True), CONF) is True
    assert runtime._staff_bypass(_membre(gerer=True), CONF) is True
    assert runtime._staff_bypass(_membre(owner=True), CONF) is True
    assert runtime._staff_bypass(_membre(bot=True), CONF) is True


def test_un_membre_verifie_est_pris_lui_aussi():
    # 05/11/2026 : un compte vérifié peut être piraté ; le piège le prend aussi.
    runtime = _runtime()
    assert runtime._staff_bypass(_membre(roles=(50,)), CONF) is False


def test_un_lien_d_arnaque_est_sanctionne_tout_de_suite():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert 'if filter_name in ("antimention", "antiscam"):' in source
    assert '"🔇 Mute anti-arnaque"' in source


def test_plus_de_bouton_historique_sous_les_sanctions():
    from utils import sentrix_trace

    vue = sentrix_trace.suites_view("mute", 42, "SX-1")
    libelles = [getattr(b, "label", "") for b in vue.children]
    assert "Historique" not in libelles
    assert "Lever l'exclusion" in libelles
    assert sentrix_trace.suites_view("kick", 42, "SX-1") is None
    # Les anciens boutons publiés restent utilisables.
    assert sentrix_trace.suite_command("mute", "history", 42, "SX-1") == ("modhistory", "<@42>")


def test_un_refus_de_permission_est_une_carte_rouge():
    from utils import sentrix_panels as panels
    from utils.access_matrix import DENIAL_HEADER

    carte = panels.carte_refus(f"{DENIAL_HEADER}\n\n**Permission Discord requise :** Bannir des membres.")
    assert carte.titre == "🔒 Accès refusé"
    assert carte.kind == "danger"
    assert DENIAL_HEADER not in str(carte.sous_titre)
    assert "Bannir des membres" in str(carte.sous_titre)
