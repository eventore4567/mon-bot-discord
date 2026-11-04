"""04/11/2026 : logs précis — rôle réellement déplacé, membre parti nommé, plus d'« Historique »."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs.create_sentrix_v3 import resumer_deplacement_roles  # noqa: E402
from utils.wide_logs import WideLogView  # noqa: E402

USER_ID = 156756827600179209


def test_les_criteres_de_verification_manques_sont_clairs():
    from utils.wide_logs import criteres_non_remplis

    texte = criteres_non_remplis(
        "• Profil avec avatar\n• Compte âgé d'au moins 1 heure\n• Compte âgé d'au moins 1 jour\n"
        "• Compte âgé d'au moins 90 jours\n• État des rôles de vérification cohérent"
    )
    assert texte.splitlines() == [
        "❌ Compte créé il y a moins d'une heure",
        "❌ Profil avec avatar",
        "❌ État des rôles de vérification cohérent",
    ]
    assert criteres_non_remplis("• Compte âgé d'au moins 7 jours") == "❌ Compte créé il y a moins de 7 jours"


def test_le_role_deplace_est_celui_qui_a_le_plus_bouge():
    reels = {1: (11, 3), 2: (3, 4), 3: (4, 5), 4: (5, 6)}
    assert resumer_deplacement_roles(reels) == ("deplace", [1], 3)


def test_deux_roles_voisins_inverses_sont_un_echange():
    assert resumer_deplacement_roles({7: (4, 5), 8: (5, 4)}) == ("echange", 7, 8)


def test_un_decalage_global_d_un_cran_n_est_pas_un_deplacement():
    assert resumer_deplacement_roles({i: (i, i + 1) for i in range(6)}) is None
    assert resumer_deplacement_roles({}) is None


def _textes(vue):
    trouves = []

    def parcourir(item):
        contenu = getattr(item, "content", None)
        if isinstance(contenu, str):
            trouves.append(contenu)
        for enfant in list(getattr(item, "children", ()) or ()):
            parcourir(enfant)
        accessoire = getattr(item, "accessory", None)
        if accessoire is not None:
            parcourir(accessoire)

    parcourir(vue)
    return "\n".join(trouves)


def test_un_nouvel_arrivant_est_nomme_en_clair():
    # Capture du 04/11/2026 : « Membre · @utilisateur-inconnu » sur une arrivée.
    embed = discord.Embed(title="Membre arrivé")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    vue = WideLogView(
        embed, None, identity_name="hawks", identity_id=USER_ID,
        log_type="member_join", guild_id=1234567890123456789,
    )
    assert "**hawks** · <@" in _textes(vue)


def test_un_membre_parti_est_nomme_en_clair_et_sans_bouton_historique():
    embed = discord.Embed(title="Membre parti")
    embed.add_field(name="Membre", value=f"<@{USER_ID}>")
    vue = WideLogView(
        embed, None, identity_name="tomioka.13", identity_id=USER_ID,
        log_type="member_leave", guild_id=1234567890123456789,
    )
    texte = _textes(vue)
    assert "**tomioka.13** · <@" in texte
    boutons = [
        e for e in vue.walk_children()
        if "history" in str(getattr(getattr(e, "item", e), "custom_id", "") or "")
    ]
    assert boutons == []
