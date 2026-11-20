"""17/11/2026 : SentriX refusait d'inventer, mais ne savait pas répondre non plus.

Test de l'utilisateur : « SentriX, pourquoi tu as banni Natix hier à 14h ? »
Réponse : « je ne peux pas confirmer la raison sans l'inventer ». Refuser
d'inventer est le minimum, et c'était bien fait — mais l'information EXISTE en
base : numéro de dossier, action, motif, modérateur, date.

Ces tests verrouillent les deux règles qui encadrent cette mémoire : elle ne
s'ouvre qu'aux modérateurs, et elle n'est lue que quand on la demande.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import memoire_sanctions as memoire  # noqa: E402


def _membre(identifiant, nom, *, moderateur=False, bot=False):
    return SimpleNamespace(
        id=identifiant, name=nom, display_name=nom, bot=bot,
        guild_permissions=SimpleNamespace(
            administrator=False, ban_members=moderateur, kick_members=False,
            moderate_members=False, manage_guild=False,
        ),
    )


def _guild(membres):
    index = {m.id: m for m in membres}
    return SimpleNamespace(id=1, members=membres, get_member=index.get)


def _sanction(numero, action, motif, *, moderateur=50, duree=0, quand=None):
    return {
        "case_number": numero, "action": action, "reason": motif,
        "moderator_id": moderateur, "duration_seconds": duree,
        "created_at": quand or int(time.time()),
    }


class _Bot:
    def __init__(self, historique=None, casse=False, utilisateurs=()):
        self._historique = historique or []
        self._casse = casse
        self._utilisateurs = {u.id: u for u in utilisateurs}
        self.db = self

    def get_user(self, identifiant):
        return self._utilisateurs.get(identifiant)

    async def get_sanction_history(self, guild_id, user_id, limit=10):
        if self._casse:
            raise RuntimeError("base indisponible")
        return [s for s in self._historique if s.get("user") == user_id][:limit]


# ------------------------------------------------------- quand on la consulte
def test_une_question_de_moderation_est_reconnue():
    assert memoire.question_sur_une_sanction("pourquoi tu as banni Natix hier à 14h ?")
    assert memoire.question_sur_une_sanction("combien d'avertissements a Cookie ?")
    assert memoire.question_sur_une_sanction("quel est le motif du mute de Tomioka")


def test_une_phrase_ordinaire_ne_declenche_rien():
    """« ban » dans une phrase quelconque n'est pas une demande d'historique."""
    assert not memoire.question_sur_une_sanction("ce serveur est vraiment banger")
    assert not memoire.question_sur_une_sanction("salut ça va ?")
    # Le mot d'action sans question : on ne charge pas l'historique pour rien.
    assert not memoire.question_sur_une_sanction("j'ai banni quelqu'un")


# -------------------------------------------------------------- qui y a droit
@pytest.mark.asyncio
async def test_un_membre_ordinaire_n_obtient_rien():
    """Un motif de sanction parle d'un membre : ce n'est pas public."""
    natix = _membre(99, "Natix")
    curieux = _membre(7, "Curieux")
    guild = _guild([natix, curieux])
    bot = _Bot([{**_sanction(42, "ban", "raid"), "user": 99}])

    texte = "pourquoi tu as banni Natix hier à 14h ?"
    assert await memoire.memoire(bot, guild, curieux, texte) == ""


@pytest.mark.asyncio
async def test_un_moderateur_obtient_le_dossier_complet():
    natix = _membre(99, "Natix")
    modo = _membre(7, "Tomioka", moderateur=True)
    guild = _guild([natix, modo])
    bot = _Bot([{**_sanction(42, "ban", "raid sur le serveur", moderateur=7), "user": 99}])

    bloc = await memoire.memoire(bot, guild, modo, "pourquoi tu as banni Natix hier à 14h ?")
    assert "dossier #42" in bloc
    assert "bannissement" in bloc
    assert "raid sur le serveur" in bloc
    assert "Tomioka" in bloc, "le modérateur qui a agi doit être nommé"
    assert "SOURCE DE VÉRITÉ" in bloc and "n'invente jamais" in bloc


# ------------------------------------------------- ce qu'elle répond vraiment
@pytest.mark.asyncio
async def test_aucune_sanction_est_aussi_une_reponse():
    """« Natix n'a aucune sanction » vaut mieux qu'un silence : c'était le cas du test."""
    natix = _membre(99, "Natix")
    modo = _membre(7, "Tomioka", moderateur=True)
    bloc = await memoire.memoire(
        _Bot([]), _guild([natix, modo]), modo, "pourquoi tu as banni Natix hier à 14h ?"
    )
    assert "aucune sanction enregistrée" in bloc


@pytest.mark.asyncio
async def test_sans_membre_cite_on_ne_charge_rien():
    modo = _membre(7, "Tomioka", moderateur=True)
    bloc = await memoire.memoire(_Bot([]), _guild([modo]), modo, "pourquoi des bannissements ?")
    assert bloc == ""


@pytest.mark.asyncio
async def test_un_membre_est_reconnu_par_sa_mention():
    """Les identifiants Discord font 17 à 19 chiffres : le test doit en utiliser un vrai."""
    natix = _membre(1551256659668504746, "Natix")
    modo = _membre(7, "Tomioka", moderateur=True)
    bot = _Bot([{**_sanction(7, "warn", "pub sauvage", moderateur=7),
                 "user": 1551256659668504746}])
    bloc = await memoire.memoire(
        bot, _guild([natix, modo]), modo, "pourquoi tu as warn <@1551256659668504746> ?"
    )
    assert "dossier #7" in bloc and "pub sauvage" in bloc


@pytest.mark.asyncio
async def test_une_base_indisponible_ne_casse_pas_la_reponse():
    natix = _membre(99, "Natix")
    modo = _membre(7, "Tomioka", moderateur=True)
    bloc = await memoire.memoire(
        _Bot(casse=True), _guild([natix, modo]), modo, "pourquoi tu as banni Natix ?"
    )
    assert bloc == ""


def test_un_nom_trop_court_n_attrape_pas_toute_la_phrase():
    """Un membre nommé « a » ne doit pas correspondre à chaque question."""
    court = _membre(5, "a")
    natix = _membre(99, "Natix")
    cibles = memoire.cibles_citees("pourquoi tu as banni Natix ?", _guild([court, natix]))
    assert [c.identifiant for c in cibles] == [99]


def test_les_bots_ne_sont_pas_des_cibles():
    robot = _membre(3, "Natix", bot=True)
    assert memoire.cibles_citees("pourquoi tu as banni Natix ?", _guild([robot])) == []


# --------------------------------------------------- revue Codex du 17/11/2026
BANNI = 1551256659668504746


def test_un_membre_banni_reste_consultable():
    """Le cas qui a motivé la fonctionnalité : un banni n'est PLUS dans le serveur.

    La première version balayait guild.get_member puis guild.members. Un membre
    banni n'est dans ni l'un ni l'autre, donc « pourquoi tu as banni X ? » ne
    trouvait aucune cible et la mémoire ne lisait jamais rien.
    """
    modo = _membre(7, "Tomioka", moderateur=True)
    guild = _guild([modo])  # le banni n'y est pas, c'est tout le problème
    cibles = memoire.cibles_citees(f"pourquoi tu as banni <@{BANNI}> ?", guild)
    assert [c.identifiant for c in cibles] == [BANNI]
    assert str(BANNI) in cibles[0].nom, "sans profil connu, l'identifiant sert de nom"


def test_un_banni_connu_du_bot_est_nomme():
    modo = _membre(7, "Tomioka", moderateur=True)
    bot = _Bot(utilisateurs=[_membre(BANNI, "Natix")])
    cibles = memoire.cibles_citees(f"pourquoi <@{BANNI}> est banni ?", _guild([modo]), bot)
    assert cibles[0].nom == "Natix"


@pytest.mark.asyncio
async def test_le_dossier_d_un_banni_est_vraiment_lu():
    modo = _membre(7, "Tomioka", moderateur=True)
    bot = _Bot(
        [{**_sanction(42, "ban", "raid sur le serveur", moderateur=7), "user": BANNI}],
        utilisateurs=[_membre(BANNI, "Natix")],
    )
    bloc = await memoire.memoire(
        bot, _guild([modo]), modo, f"pourquoi tu as banni <@{BANNI}> hier ?"
    )
    assert "dossier #42" in bloc and "raid sur le serveur" in bloc
    assert "Natix" in bloc


@pytest.mark.asyncio
async def test_un_historique_tronque_n_autorise_aucun_dementi():
    """Avec plus de huit dossiers, nier une sanction serait un mensonge."""
    modo = _membre(7, "Tomioka", moderateur=True)
    natix = _membre(99, "Natix")
    historique = [
        {**_sanction(numero, "warn", f"motif {numero}", moderateur=7), "user": 99}
        for numero in range(1, 13)
    ]
    bloc = await memoire.memoire(
        _Bot(historique), _guild([natix, modo]), modo, "combien de warn a Natix ?"
    )
    assert "LES PLUS RÉCENTES" in bloc
    assert "ne dis JAMAIS qu'une sanction n'existe pas" in bloc
    assert "aucun total" in bloc
    assert bloc.count("dossier #") == memoire._SANCTIONS_MAX


@pytest.mark.asyncio
async def test_un_historique_complet_autorise_le_dementi():
    modo = _membre(7, "Tomioka", moderateur=True)
    natix = _membre(99, "Natix")
    historique = [{**_sanction(1, "warn", "pub", moderateur=7), "user": 99}]
    bloc = await memoire.memoire(
        _Bot(historique), _guild([natix, modo]), modo, "pourquoi Natix a un warn ?"
    )
    assert "Toutes les sanctions" in bloc
    assert "dis qu'elle n'est pas enregistrée" in bloc
    assert "LES PLUS RÉCENTES" not in bloc
