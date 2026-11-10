"""10/11/2026 : /classement — niveaux, messages, vocal, invitations, économie."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from types import SimpleNamespace  # noqa: E402

from utils import classements as lb  # noqa: E402


class _FauxDB:
    def __init__(self, lignes=None, invites=None):
        self.lignes, self.invites, self.requetes = lignes or [], invites or [], []

    async def fetchall(self, sql, params):
        self.requetes.append((" ".join(sql.split()), params))
        return self.lignes

    async def get_invite_leaderboard_credited(self, guild_id, limite):
        return self.invites


def _bot(db):
    return SimpleNamespace(db=db)


def test_les_cinq_classements_existent_et_sont_nommes():
    assert [c.cle for c in lb.CATEGORIES] == ["niveaux", "messages", "vocal", "invitations", "economie"]
    assert lb.DEFAUT in lb.PAR_CLE
    assert all(c.titre and c.description and c.icone for c in lb.CATEGORIES)


def test_le_niveau_prime_sur_l_xp_dans_le_tri():
    db = _FauxDB([
        {"user_id": 1, "level": 5, "xp": 10},
        {"user_id": 2, "level": 3, "xp": 999999},
    ])
    lignes = asyncio.run(lb.lire(_bot(db), 7, "niveaux"))
    assert lignes[0][0] == 1, "un niveau 5 passe devant un niveau 3, quelle que soit l'XP"
    assert lb.PAR_CLE["niveaux"].unite(lignes[0][1]) == "Niv. 5 · 10 XP"


def test_chaque_categorie_lit_sa_propre_table():
    for cle, table in (("messages", "message_counts"), ("vocal", "voice_totals"), ("economie", "economy")):
        db = _FauxDB([{"user_id": 1, "count": 3, "seconds": 3, "total": 3}])
        asyncio.run(lb.lire(_bot(db), 7, cle))
        assert table in db.requetes[0][0], (cle, db.requetes)


def test_les_invitations_ne_comptent_que_les_creditees():
    db = _FauxDB(invites=[(1, {"credited": 4}), (2, {"credited": 0})])
    lignes = asyncio.run(lb.lire(_bot(db), 7, "invitations"))
    assert lignes == [(1, 4)], "un invitant à zéro crédité n'entre pas au classement"


def test_une_categorie_inconnue_ne_plante_pas():
    assert asyncio.run(lb.lire(_bot(_FauxDB()), 7, "n_importe_quoi")) == []


def test_les_bots_sont_ecartes_mais_pas_les_absents():
    membres = {1: SimpleNamespace(bot=True), 2: SimpleNamespace(bot=False)}
    guild = SimpleNamespace(get_member=membres.get)
    # 3 n'est pas dans le cache : parti ou pas encore chargé — on le garde.
    assert lb.sans_les_bots(guild, [(1, 9), (2, 5), (3, 1)]) == [(2, 5), (3, 1)]
    assert lb.sans_les_bots(None, [(1, 9)]) == [(1, 9)]


def test_le_rang_et_le_podium():
    lignes = [(10, 100), (20, 50), (30, 10)]
    assert lb.rang_de(lignes, 20) == 2 and lb.rang_de(lignes, 99) is None
    assert lb.podium(1) == "🥇" and lb.podium(3) == "🥉" and lb.podium(4).strip() == "` 4.`".strip()
    categorie = lb.PAR_CLE["vocal"]
    assert "**#2** sur 3" in lb.ma_position(categorie, lignes, 20)
    assert lb.ma_position(categorie, lignes, 99) == "Vous n'êtes pas encore classé."


def test_le_top_mentionne_sans_pinger_et_formate_l_unite():
    lignes = lb.lignes_du_top(lb.PAR_CLE["vocal"], [(10, 7200), (20, 1800)])
    assert lignes[0] == "🥇 <@10> · **2h 0min**"
    assert lb.lignes_du_top(lb.PAR_CLE["invitations"], [(10, 1)])[0].endswith("**1 invitation**")
    assert lb.lignes_du_top(lb.PAR_CLE["invitations"], [(10, 3)])[0].endswith("**3 invitations**")


def test_la_commande_est_publiee_en_slash_et_visible():
    racine = Path(__file__).resolve().parents[1]
    catalogue = (racine / "utils" / "slash_catalog.py").read_text(encoding="utf-8")
    surface = (racine / "cogs" / "command_catalog_cleanup.py").read_text(encoding="utf-8")
    assert '_e("leaderboard", "classement"' in catalogue
    assert '"classement",' in surface
    assert '"cogs.classements",' in (racine / "main.py").read_text(encoding="utf-8")
