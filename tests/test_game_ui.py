"""Socle commun des vues de mini-jeux.

Chaque jeu réécrivait ces garde-fous à sa façon, parfois à moitié. Le pire cas
mesuré : « Course à l'emoji » demandait de cliquer sur 🍒 et envoyait cinq
boutons parfaitement vides — label='\\u200b', emoji=None dans le payload — parce
qu'une couche de style retirait l'emoji sans savoir qu'il était le jeu. Le jeu
était injouable, et rien ne le signalait.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from utils.game_ui import (
    BoutonInvisibleError,
    BoutonRejouer,
    VueDeJeu,
    composants_invisibles,
    valider_composants,
)


def _interaction(user_id: int):
    """Interaction minimale : ce qui compte est l'auteur et la réponse."""
    envoyes: list[dict] = []

    async def send_message(contenu, **kwargs):
        envoyes.append({"contenu": contenu, **kwargs})

    async def defer(*a, **k):
        envoyes.append({"defer": True})

    reponse = SimpleNamespace(
        is_done=lambda: False, send_message=send_message, defer=defer
    )
    return SimpleNamespace(user=SimpleNamespace(id=user_id), response=reponse, _envoyes=envoyes)


# --------------------------------------------------------------- boutons vides

def test_un_bouton_sans_libelle_ni_emoji_est_refuse():
    vue = discord.ui.View()
    vue.add_item(discord.ui.Button(label="​"))  # exactement le bug mesuré
    with pytest.raises(BoutonInvisibleError):
        valider_composants(vue)


def test_un_bouton_avec_emoji_seul_passe():
    """Le cas normal d'un jeu : l'emoji EST le libellé."""
    vue = discord.ui.View()
    vue.add_item(discord.ui.Button(label="​", emoji="🍒"))
    valider_composants(vue)


def test_un_bouton_avec_libelle_seul_passe():
    vue = discord.ui.View()
    vue.add_item(discord.ui.Button(label="Encaisser"))
    valider_composants(vue)


def test_un_bouton_lien_est_ignore():
    """Un bouton lien porte son URL ; Discord l'affiche même sans libellé."""
    vue = discord.ui.View()
    vue.add_item(discord.ui.Button(style=discord.ButtonStyle.link, url="https://exemple.test", label="Ouvrir"))
    valider_composants(vue)


def test_l_audit_liste_les_boutons_invisibles_sans_lever():
    vue = discord.ui.View()
    vue.add_item(discord.ui.Button(label="Jouer"))
    vue.add_item(discord.ui.Button(label="  ", custom_id="vide-1"))
    assert composants_invisibles(vue) == ["vide-1"]
    vue_saine = discord.ui.View()
    vue_saine.add_item(discord.ui.Button(label="Jouer"))
    assert composants_invisibles(vue_saine) == []


# ------------------------------------------------------------- propriétaire

def test_seul_le_joueur_peut_cliquer():
    vue = VueDeJeu(proprietaire_id=42)
    intrus = _interaction(99)
    assert asyncio.run(vue.interaction_check(intrus)) is False
    assert intrus._envoyes, "l'intrus doit recevoir une explication, pas un clic ignoré"
    assert intrus._envoyes[0]["ephemeral"] is True

    joueur = _interaction(42)
    assert asyncio.run(vue.interaction_check(joueur)) is True
    assert joueur._envoyes == []


def test_une_vue_sans_proprietaire_accepte_tout_le_monde():
    """Courses communautaires et drops : le premier qui clique gagne."""
    vue = VueDeJeu(proprietaire_id=None)
    assert asyncio.run(vue.interaction_check(_interaction(7))) is True
    assert asyncio.run(vue.interaction_check(_interaction(8))) is True


def test_une_partie_terminee_refuse_les_clics():
    vue = VueDeJeu(proprietaire_id=42)
    vue.terminer()
    interaction = _interaction(42)
    assert asyncio.run(vue.interaction_check(interaction)) is False
    assert "terminée" in interaction._envoyes[0]["contenu"]


# ------------------------------------------------------------- double clic

def test_deux_clics_simultanes_ne_jouent_qu_un_coup():
    """Le cœur de l'anti-double-crédit : deux clics quasi simultanés peuvent
    tous deux lire « pas encore terminé » avant que l'un n'ait écrit."""
    vue = VueDeJeu(proprietaire_id=1)
    coups: list[int] = []

    async def coup_lent():
        await asyncio.sleep(0.05)
        coups.append(1)

    async def scenario():
        return await asyncio.gather(
            vue.jouer_un_coup(coup_lent), vue.jouer_un_coup(coup_lent)
        )

    resultats = asyncio.run(scenario())
    assert coups == [1], "le coup a été joué deux fois"
    assert sorted(resultats) == [False, True]


def test_un_coup_apres_la_fin_est_refuse():
    vue = VueDeJeu(proprietaire_id=1)
    joue = []

    async def coup():
        joue.append(1)

    vue.terminer()
    assert asyncio.run(vue.jouer_un_coup(coup)) is False
    assert joue == []


# ------------------------------------------------------------- fin et timeout

def test_terminer_grise_tout_et_arrete_la_vue():
    """Exécuté DANS une boucle : discord.ui.View.stop() a besoin d'une boucle
    active pour marquer la vue finie, et c'est ce qui débloque un view.wait()."""

    async def scenario():
        vue = VueDeJeu(proprietaire_id=1)
        vue.add_item(discord.ui.Button(label="A"))
        vue.add_item(discord.ui.Button(label="B"))
        vue.terminer()
        assert all(enfant.disabled for enfant in vue.children)
        assert vue.terminee is True
        assert vue.is_finished(), "un view.wait() en attente resterait bloqué"

    asyncio.run(scenario())


def test_l_expiration_grise_les_boutons_et_edite_le_message():
    """Sans cette édition, le joueur garde des boutons actifs qui ne répondent
    plus — le pire état possible, parce que rien ne dit que c'est fini."""
    vue = VueDeJeu(proprietaire_id=1, timeout=0.01)
    vue.add_item(discord.ui.Button(label="A"))
    editions: list[dict] = []

    async def edit(**kwargs):
        editions.append(kwargs)

    vue.message = SimpleNamespace(edit=edit)
    asyncio.run(vue.on_timeout())
    assert vue.expiree is True and vue.terminee is True
    assert all(enfant.disabled for enfant in vue.children)
    assert editions and editions[0]["view"] is vue


def test_l_expiration_sans_message_ne_leve_pas():
    vue = VueDeJeu(proprietaire_id=1)
    asyncio.run(vue.on_timeout())  # ne doit pas lever
    assert vue.expiree is True


def test_un_message_disparu_n_empeche_pas_l_expiration():
    vue = VueDeJeu(proprietaire_id=1)

    async def edit(**kwargs):
        raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "disparu")

    vue.message = SimpleNamespace(edit=edit)
    asyncio.run(vue.on_timeout())  # avalé : la partie est finie de toute façon
    assert vue.terminee is True


# ------------------------------------------------------------- rejouer

def test_le_bouton_rejouer_est_visible_et_relance():
    bouton = BoutonRejouer(relancer=lambda interaction: asyncio.sleep(0))
    assert bouton.label == "Rejouer"
    assert str(bouton.emoji) == "🔁"

    vue = discord.ui.View()
    vue.add_item(bouton)
    valider_composants(vue)  # il doit passer la validation


def test_une_relance_qui_echoue_previent_le_joueur():
    appels: list[str] = []

    async def relance_cassee(interaction):
        appels.append("tentee")
        raise RuntimeError("commande indisponible")

    bouton = BoutonRejouer(relancer=relance_cassee)
    interaction = _interaction(1)
    asyncio.run(bouton.callback(interaction))
    assert appels == ["tentee"]
    assert any("Impossible de relancer" in str(e.get("contenu", "")) for e in interaction._envoyes)


# =============================================================================
# Refus : le joueur doit toujours savoir pourquoi son clic n'a rien fait
# =============================================================================

def _interaction_factice(deja_repondu: bool):
    """Deux moments, deux chemins.

    ``interaction_check`` s'exécute avant toute réponse ; un callback de bouton
    s'exécute APRÈS le ``defer()`` qui permet d'éditer le message. Dans le
    second cas ``send_message`` lèverait, et c'est le suivi qu'il faut prendre.
    """
    from types import SimpleNamespace

    envoyes: list[tuple[str, str]] = []

    async def par_reponse(texte, **kwargs):
        envoyes.append(("reponse", texte, kwargs.get("ephemeral")))

    async def par_suivi(texte, **kwargs):
        envoyes.append(("suivi", texte, kwargs.get("ephemeral")))

    return SimpleNamespace(
        envoyes=envoyes,
        followup=SimpleNamespace(send=par_suivi),
        response=SimpleNamespace(is_done=lambda: deja_repondu,
                                 send_message=par_reponse),
    )


def test_un_refus_avant_toute_reponse_passe_par_la_reponse():
    import asyncio

    from utils.game_ui import VueDeJeu

    interaction = _interaction_factice(deja_repondu=False)
    asyncio.run(VueDeJeu._refuser(interaction, "Pas votre partie."))
    assert interaction.envoyes == [("reponse", "Pas votre partie.", True)]


def test_un_refus_apres_le_defer_passe_par_le_suivi():
    """Le défaut mesuré sur le bot booté : tous les refus émis depuis un
    callback ne disaient rien du tout. Le joueur cliquait, et il ne se passait
    rien — encaisser sans avoir joué, cliquer pendant son délai, accuser après
    élimination, reprendre la couronne trop tôt."""
    import asyncio

    from utils.game_ui import VueDeJeu

    interaction = _interaction_factice(deja_repondu=True)
    asyncio.run(VueDeJeu._refuser(interaction, "Encore 2 s."))
    assert interaction.envoyes == [("suivi", "Encore 2 s.", True)]


def test_un_refus_sans_interaction_ne_leve_pas():
    """Le compte à rebours de +crown conclut la manche sans clic derrière."""
    import asyncio

    from utils.game_ui import VueDeJeu

    asyncio.run(VueDeJeu._refuser(None, "personne à prévenir"))


def test_un_refus_est_toujours_ephemere():
    """Un refus public exposerait la partie d'un joueur à tout le salon."""
    import ast
    import inspect
    import textwrap

    from utils.game_ui import VueDeJeu

    # dedent, pas lstrip : lstrip ne désindente que la première ligne et laisse
    # le corps décalé, ce qui fait échouer ast.parse sur une IndentationError.
    arbre = ast.parse(textwrap.dedent(inspect.getsource(VueDeJeu._refuser)))
    envois = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("send", "send_message")]
    assert envois, "aucun envoi trouvé : le test ne mesure plus rien"
    for envoi in envois:
        ephemere = [k for k in envoi.keywords if k.arg == "ephemeral"]
        assert ephemere and ephemere[0].value.value is True
