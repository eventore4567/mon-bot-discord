"""10/11/2026 : crash-test de sécurité — attaques simulées contre la config réelle."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import crash_test as ct  # noqa: E402

TOUTES = {"antispam", "antimention", "antiinvite", "antiscam", "antiinsult", "antiraid", "antibot", "antinuke"}
PERMS = {"manage_messages", "moderate_members", "kick_members", "ban_members", "manage_channels",
         "manage_roles", "view_audit_log"}


def _etats(ctx):
    return {r.cle: r.etat for r in ct.evaluer(ctx)}


def test_serveur_sans_protection_tout_passe_sauf_everyone():
    resultats = ct.evaluer(ct.Contexte(actives=set(), permissions=PERMS))
    etats = {r.cle: r.etat for r in resultats}
    assert all(etats[c] == ct.PASSE for c in TOUTES)
    assert etats["everyone"] == ct.BLOQUE
    assert ct.note(resultats) == 11 and "exposé" in ct.verdict(ct.note(resultats))


def test_serveur_bien_regle_est_blinde():
    resultats = ct.evaluer(ct.Contexte(actives=TOUTES, permissions=PERMS))
    assert all(r.etat == ct.BLOQUE for r in resultats)
    assert ct.note(resultats) == 100 and ct.verdict(100) == "Serveur blindé."


def test_une_permission_manquante_est_nommee():
    etats = ct.evaluer(ct.Contexte(actives=TOUTES, permissions=PERMS - {"manage_messages"}))
    spam = next(r for r in etats if r.cle == "antispam")
    assert spam.etat == ct.PASSE and "Gérer les messages" in spam.detail
    sans_mute = _etats(ct.Contexte(actives=TOUTES, permissions=PERMS - {"moderate_members"}))
    assert sans_mute["antispam"] == ct.PARTIEL
    sans_kick = _etats(ct.Contexte(actives=TOUTES, permissions=PERMS - {"kick_members"}))
    assert sans_kick["antiraid"] == ct.PARTIEL and sans_kick["antibot"] == ct.PASSE


def test_administrateur_vaut_toutes_les_permissions():
    assert all(e == ct.BLOQUE for e in _etats(ct.Contexte(actives=TOUTES, permissions={"administrator"})).values())


def test_nuke_un_role_au_dessus_de_sentrix_est_signale():
    resultats = ct.evaluer(ct.Contexte(actives=TOUTES, permissions=PERMS, roles_au_dessus=["Fondateur", "Co-fonda"]))
    nuke = next(r for r in resultats if r.cle == "antinuke")
    assert nuke.etat == ct.PARTIEL and "Fondateur" in nuke.detail and "tout en haut" in nuke.detail
    sans_audit = _etats(ct.Contexte(actives=TOUTES, permissions=PERMS - {"view_audit_log"}))
    assert sans_audit["antinuke"] == ct.PASSE


def test_everyone_avec_des_permissions_dangereuses():
    resultats = ct.evaluer(ct.Contexte(actives=TOUTES, permissions=PERMS, everyone_dangereux=["mention_everyone", "kick_members"]))
    everyone = next(r for r in resultats if r.cle == "everyone")
    assert everyone.etat == ct.PASSE and "Mentionner @everyone" in everyone.detail and "Expulser" in everyone.detail


def test_un_detecteur_qui_rate_son_echantillon_est_dit():
    aveugle = _etats(ct.Contexte(actives=TOUTES, permissions=PERMS, detecte_arnaque=lambda _t: False))
    assert aveugle["antiscam"] == ct.PASSE
    moitie = _etats(ct.Contexte(actives=TOUTES, permissions=PERMS, detecte_pub=lambda t: "discord.gg" in t))
    assert moitie["antiinvite"] == ct.PARTIEL


def test_les_vrais_detecteurs_attrapent_les_messages_d_essai():
    from cogs import automod
    from utils.moderation_dataset import MultilingualModerationDataset

    dataset = MultilingualModerationDataset()
    for texte in ct.ECHANTILLONS_PUB:
        assert automod.INVITE_RE.search(automod._recoller_hotes_invitation(texte)) or automod._invitation_apres_recollage_total(texte), texte
    for texte in ct.ECHANTILLONS_ARNAQUE:
        assert automod._scam_hit(texte), texte
    for texte in ct.ECHANTILLONS_INSULTE:
        assert dataset.match(texte) is not None, texte


def test_les_seuils_du_serveur_sont_dans_le_scenario():
    resultats = ct.evaluer(ct.Contexte(actives=TOUTES, permissions=PERMS, spam_messages=4, spam_secondes=5, seuil_raid=12))
    textes = {r.cle: f"{r.attaque} {r.detail}" for r in resultats}
    assert "7 messages en 5 s" in textes["antispam"] and "dès 4 messages" in textes["antispam"]
    assert "15 comptes" in textes["antiraid"] and "dès 12 arrivées" in textes["antiraid"]


def test_le_crash_test_est_dans_la_vraie_page_securite():
    racine = Path(__file__).resolve().parents[1] / "cogs"
    simple = (racine / "securite_simple.py").read_text(encoding="utf-8")
    centre = (racine / "complete_security_setup.py").read_text(encoding="utf-8")
    assert '_bouton("Tester ma sécurité", tester' in simple
    assert "crash_test.lancer(view.bot, view.guild" in simple
    # La page Sécurité de /setup (SecurityCenterView) s'ouvre sur l'écran simple.
    assert 'self.mode = "simple"' in centre
    assert "securite_simple.ecran_crash if self.mode == \"crash\" else securite_simple.ecran_simple" in centre
    assert 'button("Vue simple", simple)' in centre
