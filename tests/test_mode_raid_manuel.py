"""Un mode raid qu'on arme soi-même, depuis Setup → Sécurité (21/11/2026).

« fait un raid mode stp pour éviter de faire des commandes, un raid mode dans
sécurité qui kick les nouveaux. »

Jusqu'ici le mode ne s'armait QUE sur un afflux détecté : jamais à l'avance,
alors que « ça peut raid à tout moment ». Et son état vivait en mémoire, donc
chaque déploiement rouvrait silencieusement la porte — onze fois dans la seule
journée d'hier.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import raid_mode  # noqa: E402


class _Db:
    def __init__(self):
        self.lignes: dict[int, int] = {}

    async def execute(self, requete, params=()):
        if "INSERT OR REPLACE INTO sentrix_raid_manuel" in requete:
            self.lignes[int(params[0])] = int(params[1])
        elif "DELETE FROM sentrix_raid_manuel" in requete:
            self.lignes.pop(int(params[0]), None)

    async def fetchall(self, requete, params=()):
        if "FROM sentrix_raid_manuel" in requete:
            return [{"guild_id": g} for g in self.lignes]
        return []


def _bot(db):
    return SimpleNamespace(db=db)


def _guild(identifiant=1):
    return SimpleNamespace(id=identifiant)


@pytest.fixture(autouse=True)
def _etat_propre():
    raid_mode._etats.clear()
    yield
    raid_mode._etats.clear()


@pytest.mark.asyncio
async def test_armer_ferme_la_porte_a_tout_le_monde():
    """Armé à la main, PERSONNE de nouveau n'entre.

    Un raideur prépare ses comptes à l'avance : ils passent les filtres d'âge
    et d'avatar. Exiger qu'un compte soit « suspect » laisserait donc entrer
    précisément ceux qu'on veut bloquer.
    """
    db = _Db()
    await raid_mode.armer_manuel(_bot(db), _guild(), auteur_id=7)

    assert raid_mode.est_manuel(1) is True
    etat = raid_mode._etats[1]

    # Un compte parfaitement banal : ancien, avec avatar, pas un bot.
    banal = SimpleNamespace(bot=False, created_at=None, avatar=object())
    assert raid_mode.motif_suspect(banal, manuel=etat.manuel) is not None
    # Le même, hors mode manuel, reste épargné.
    assert raid_mode.motif_suspect(banal, manuel=False) is None


@pytest.mark.asyncio
async def test_desarmer_rouvre():
    db = _Db()
    bot, guild = _bot(db), _guild()
    await raid_mode.armer_manuel(bot, guild, auteur_id=7)
    await raid_mode.desarmer_manuel(bot, guild)

    assert raid_mode.est_manuel(1) is False
    assert db.lignes == {}, "la ligne doit disparaître, sinon le redémarrage réarme"


@pytest.mark.asyncio
async def test_le_mode_survit_a_un_redemarrage():
    """Onze déploiements hier : sans persistance, chacun rouvrait la porte."""
    db = _Db()
    await raid_mode.armer_manuel(_bot(db), _guild(), auteur_id=7)

    raid_mode._etats.clear()               # le bot redémarre
    assert raid_mode.est_manuel(1) is False

    restaures = await raid_mode.restaurer_manuels(_bot(db))
    assert restaures == 1
    assert raid_mode.est_manuel(1) is True


@pytest.mark.asyncio
async def test_un_serveur_desarme_n_est_pas_restaure():
    db = _Db()
    bot = _bot(db)
    await raid_mode.armer_manuel(bot, _guild(1), auteur_id=7)
    await raid_mode.armer_manuel(bot, _guild(2), auteur_id=7)
    await raid_mode.desarmer_manuel(bot, _guild(2))

    raid_mode._etats.clear()
    await raid_mode.restaurer_manuels(bot)
    assert raid_mode.est_manuel(1) is True
    assert raid_mode.est_manuel(2) is False


@pytest.mark.asyncio
async def test_une_base_indisponible_n_empeche_pas_d_armer():
    """La protection prime sur sa trace : on ferme d'abord, on note ensuite."""
    class _DbCassee:
        async def execute(self, *a, **k):
            raise RuntimeError("base indisponible")

    await raid_mode.armer_manuel(_bot(_DbCassee()), _guild(), auteur_id=7)
    assert raid_mode.est_manuel(1) is True


def test_le_bouton_est_dans_l_ecran_securite():
    """Il devait être dans Setup → Sécurité, pas dans une commande."""
    import inspect

    from cogs import securite_simple

    source = inspect.getsource(securite_simple.ecran_simple)
    assert "Mode raid" in source
    assert "_basculer_mode_raid" in inspect.getsource(securite_simple)
    # Rouge quand il est armé : l'état doit se voir sans cliquer.
    assert "ButtonStyle.danger" in source


def test_le_demarrage_restaure_bien_les_modes():
    """Sans cet appel, la persistance ne servirait à rien."""
    import inspect

    from cogs import automod

    assert "restaurer_manuels" in inspect.getsource(automod.AutoMod.cog_load)
