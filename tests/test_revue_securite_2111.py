"""Six défauts trouvés en revue sur le lot sécurité du 21/11/2026.

Tous partagent une racine : du code neuf greffé sur des mécanismes existants
dont j'avais mal lu le contrat. Chacun est reproduit ici avant d'être corrigé,
pour qu'une prochaine greffe ne les ramène pas.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import raid_mode  # noqa: E402
from cogs.antinuke_emergency_v55 import AntiNukeEmergencyV55  # noqa: E402
from utils import empreinte_serveur as emp  # noqa: E402


# ------------------------------------------------------------------ MODE RAID MANUEL

class _DbRaid:
    def __init__(self):
        self.lignes: dict[int, int] = {}

    async def execute(self, requete, params=()):
        if "INSERT OR REPLACE INTO sentrix_raid_manuel" in requete:
            self.lignes[int(params[0])] = int(params[1])
        elif "DELETE FROM sentrix_raid_manuel" in requete:
            self.lignes.pop(int(params[0]), None)

    async def fetchall(self, requete, params=()):
        return [{"guild_id": g} for g in self.lignes]


@pytest.fixture(autouse=True)
def _etat_propre():
    raid_mode._etats.clear()
    yield
    raid_mode._etats.clear()


@pytest.mark.asyncio
async def test_une_expulsion_ne_raccourcit_pas_un_armement_manuel():
    """Le défaut : la première expulsion ramenait 24 h à dix minutes.

    ``declencher()`` et ``sur_arrivee()`` écrasent ``jusqua`` par
    ``maintenant + RAID_MODE_DUREE``. Comme ``est_manuel()`` passait par
    ``actif()``, donc par ``jusqua``, le mode armé à la main se désarmait tout
    seul après dix minutes de calme — alors que le bouton promet le contraire.
    """
    await raid_mode.armer_manuel(_DbRaid(), SimpleNamespace(id=1), auteur_id=7)
    etat = raid_mode._etats[1]

    # Ce que fait la détection automatique à chaque arrivée suspecte.
    etat.jusqua = time.monotonic() + raid_mode.RAID_MODE_DUREE
    assert raid_mode.est_manuel(1) is True

    # Puis dix minutes de calme : l'échéance automatique est passée.
    etat.jusqua = time.monotonic() - 1
    assert raid_mode.est_manuel(1) is True, "le mode manuel a expiré tout seul"
    assert raid_mode.actif(1) is True, "la porte s'est rouverte sans décision"


@pytest.mark.asyncio
async def test_le_desarmement_explicite_reste_le_seul_moyen_de_rouvrir():
    db = _DbRaid()
    guild = SimpleNamespace(id=1)
    await raid_mode.armer_manuel(db, guild, auteur_id=7)
    await raid_mode.desarmer_manuel(db, guild)
    assert raid_mode.est_manuel(1) is False
    assert raid_mode.actif(1) is False


def test_aucune_echeance_n_est_posee_a_l_armement():
    """Garde-fou : reposer une durée ici ramènerait le défaut ci-dessus."""
    import io

    source = io.open("cogs/raid_mode.py", encoding="utf-8").read()
    assert "DUREE_MANUELLE" not in source
    # ``actif`` doit lire ``manuel`` AVANT l'échéance.
    corps = source.split("def actif(", 1)[1].split("def ", 1)[0]
    assert "etat.manuel" in corps


def test_le_mode_manuel_est_traite_meme_si_l_anti_raid_est_coupe():
    """Le défaut le plus grave : le bouton annonçait une porte fermée, ouverte.

    ``antiraid`` vaut 0 par défaut dans database/db.py, et tout le traitement
    des arrivées vivait derrière ``if conf.get("antiraid")``. Sur un serveur qui
    n'avait jamais activé l'anti-raid — le cas de celui qui vient de se faire
    harceler — armer le mode raid ne kickait donc personne.
    """
    import io

    source = io.open("cogs/automod.py", encoding="utf-8").read()
    bloc = source.split("async def on_member_join", 1)[1][:3000]
    assert "manuel = raid_mode.est_manuel(member.guild.id)" in bloc
    assert 'if conf.get("antiraid") or manuel:' in bloc


# ------------------------------------------------------------------ AUTEUR D'AUDIT

def test_l_auteur_d_une_attribution_de_role_n_est_jamais_mis_en_cache():
    """Le défaut : deux attributions au même membre en moins de 18 s.

    Le resolver mettait en cache l'auteur sous (serveur, action, cible) pour
    TOUTE action. Un autorôle du bot, puis une attribution malveillante juste
    après : la seconde héritait du bot, donc exemptée. Et l'inverse — un rôle
    donné par le bot retiré au nom d'un auteur non exempté.

    Un salon n'est supprimé qu'une fois ; les rôles d'un membre changent
    légitimement plusieurs fois de suite. Le cache est donc faux pour cette
    action, indépendamment de mon écouteur.
    """
    import io

    import discord

    source = io.open("cogs/antinuke_emergency_v55.py", encoding="utf-8").read()
    assert "actions_sans_cache = {discord.AuditLogAction.member_role_update}" in source
    assert "jamais_en_cache = action in actions_sans_cache" in source
    # Les deux lectures et l'écriture doivent toutes respecter le drapeau.
    assert source.count("None if jamais_en_cache else cache.get(lookup_key)") == 2
    assert "if not jamais_en_cache:\n                            cache[lookup_key]" in source
    assert discord.AuditLogAction.member_role_update not in {
        discord.AuditLogAction.channel_delete, discord.AuditLogAction.ban,
    }


# ------------------------------------------------------------------ FILET EMPREINTE

class _DbEmp:
    def __init__(self, contenu, pris_le=None):
        self.contenu = contenu
        self.pris_le = int(time.time()) if pris_le is None else pris_le
        self.ecritures = 0

    async def execute(self, requete, params=()):
        if f"INSERT INTO {emp.TABLE}" in requete:
            import json

            self.ecritures += 1
            self.pris_le = int(params[1])
            self.contenu = json.loads(params[2])

    async def fetchone(self, requete, params=()):
        import json

        if f"FROM {emp.TABLE}" in requete and self.contenu is not None:
            return {"pris_le": self.pris_le,
                    "contenu_json": json.dumps(self.contenu, ensure_ascii=False)}
        return None


def _empreinte(roles=(), salons=()):
    return {
        "roles": [{"id": i, "name": f"r{i}", "position": i, "managed": False} for i in roles],
        "salons": [{"id": i, "name": f"s{i}", "kind": k, "position": i, "category_id": None}
                   for i, k in salons],
    }


def _guild(roles=(), salons=()):
    r = {int(i): SimpleNamespace(id=i) for i in roles}
    s = {int(i): SimpleNamespace(id=i) for i in salons}
    return SimpleNamespace(id=1, get_role=r.get, get_channel=s.get)


def _cog(db):
    cog = AntiNukeEmergencyV55.__new__(AntiNukeEmergencyV55)
    cog.bot = SimpleNamespace(db=db)
    cog._restore_role = AsyncMock(side_effect=lambda g, s, m: SimpleNamespace(id=s["id"]))
    cog._restore_deleted_channel = AsyncMock(
        side_effect=lambda g, s, cm, rm: SimpleNamespace(id=s["id"])
    )
    cog._reconcile_restored_channels = AsyncMock()
    return cog


@pytest.mark.asyncio
async def test_un_role_deja_recree_n_est_pas_recree_une_seconde_fois():
    """Le défaut : deux rôles pour un seul, avec des permissions divergentes.

    Une passe événementielle recrée le rôle supprimé sous un NOUVEAU ID et pose
    ``role_map[ancien] = nouveau``. L'ancien ID n'existe plus dans Discord, donc
    ``disparus()`` le croit toujours manquant — et ``_restore_role`` ne consulte
    pas la correspondance avant de créer. Résultat : un deuxième rôle, et les
    salons restaurés avant visent le premier, ceux d'après le second.
    """
    cog = _cog(_DbEmp(_empreinte(roles=[10, 11])))
    deja = SimpleNamespace(id=777)
    bilan = await cog._restaurer_depuis_empreinte(_guild(), {}, {10: deja}, {})

    assert bilan["roles_restored"] == 1
    assert [a.args[1]["id"] for a in cog._restore_role.await_args_list] == [11]


@pytest.mark.asyncio
async def test_un_salon_deja_recree_n_est_pas_recree_une_seconde_fois():
    cog = _cog(_DbEmp(_empreinte(salons=[(20, "text"), (21, "text")])))
    bilan = await cog._restaurer_depuis_empreinte(
        _guild(), {20: SimpleNamespace(id=888)}, {}, {}
    )
    assert bilan["channels_restored"] == 1
    assert [a.args[1]["id"] for a in cog._restore_deleted_channel.await_args_list] == [21]


@pytest.mark.asyncio
async def test_les_salons_sont_reconcilies_apres_le_filet():
    """Le défaut : un salon recréé sans sa catégorie restait à la racine.

    La réconciliation tournait AVANT le filet. Si la suppression d'un salon
    avait été vue mais pas celle de sa catégorie, la passe événementielle
    recréait le salon sans parent ; le filet recréait ensuite la catégorie, trop
    tard. Le salon restait à la racine, et potentiellement sans ses
    restrictions d'accès — donc visible par qui ne devait pas le voir.
    """
    cog = _cog(_DbEmp(_empreinte(salons=[(20, "category")])))
    instantanes: dict = {}
    await cog._restaurer_depuis_empreinte(_guild(), {}, {}, instantanes)

    cog._reconcile_restored_channels.assert_awaited_once()
    # Le salon recréé par le filet doit figurer dans les instantanés, sinon la
    # réconciliation n'a rien à réappliquer pour lui.
    assert 20 in instantanes


@pytest.mark.asyncio
async def test_rien_a_restaurer_ne_declenche_pas_de_reconciliation():
    cog = _cog(_DbEmp(_empreinte(roles=[10])))
    bilan = await cog._restaurer_depuis_empreinte(_guild(roles=[10]), {}, {}, {})
    assert bilan["roles_restored"] == 0
    cog._reconcile_restored_channels.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_seconde_restauration_ne_duplique_pas():
    """Le défaut : deux auteurs sanctionnés pendant le même nuke.

    Chaque ``restore_burst`` recrée ses dictionnaires de correspondance et
    relit la même empreinte, où les anciens IDs sont toujours cités. Sans les
    oublier, le second passage recréait tout une deuxième fois.
    """
    db = _DbEmp(_empreinte(roles=[10], salons=[(20, "text")]))
    cog = _cog(db)
    premier = await cog._restaurer_depuis_empreinte(_guild(), {}, {}, {})
    assert premier["roles_restored"] == 1 and premier["channels_restored"] == 1

    second = await cog._restaurer_depuis_empreinte(_guild(), {}, {}, {})
    assert second == {"roles_restored": 0, "channels_restored": 0, "failed": 0}


@pytest.mark.asyncio
async def test_ce_qui_a_echoue_reste_dans_l_empreinte():
    """Un échec n'est pas un oubli : il faudra réessayer au prochain incident."""
    db = _DbEmp(_empreinte(roles=[10]))
    cog = _cog(db)
    cog._restore_role = AsyncMock(return_value=None)
    await cog._restaurer_depuis_empreinte(_guild(), {}, {}, {})

    restant = await emp.lire(db, 1)
    assert [r["id"] for r in restant["roles"]] == [10]


@pytest.mark.asyncio
async def test_oublier_garde_la_date_de_capture():
    """Sinon l'empreinte rajeunirait à chaque restauration.

    Elle paraîtrait fraîche alors que son contenu date : le plafond de sept
    jours ne protégerait plus rien.
    """
    db = _DbEmp(_empreinte(roles=[10, 11]), pris_le=1_700_000_000)
    retires = await emp.oublier(db, 1, roles=[10])
    assert retires == 1
    assert db.pris_le == 1_700_000_000
    assert [r["id"] for r in (await emp.lire(db, 1))["roles"]] == [11]


@pytest.mark.asyncio
async def test_oublier_sans_rien_a_oublier_n_ecrit_pas():
    db = _DbEmp(_empreinte(roles=[10]))
    assert await emp.oublier(db, 1) == 0
    assert await emp.oublier(db, 1, roles=[999]) == 0
    assert db.ecritures == 0


@pytest.mark.asyncio
async def test_un_vrai_raid_ne_desarme_pas_le_mode_manuel():
    """Défaut vu en résolvant un conflit, créé par la correction n°2.

    Depuis que ``manuel`` ne dépend plus de ``jusqua``, un état armé à la main a
    son échéance dépassée en permanence. ``declencher()`` calculait
    ``nouveau = etat is None or maintenant >= etat.jusqua`` : il passait donc à
    vrai et REMPLAÇAIT l'état entier par un neuf, dont ``manuel`` vaut False.

    Autrement dit : un vrai raid détecté pendant un armement manuel désarmait le
    mode manuel, en silence, au pire moment possible.
    """
    await raid_mode.armer_manuel(_DbRaid(), SimpleNamespace(id=1), auteur_id=7)
    etat_arme = raid_mode._etats[1]
    etat_arme.jusqua = time.monotonic() - 1  # l'échéance automatique est passée

    automod = SimpleNamespace(bot=SimpleNamespace(user=SimpleNamespace(id=2)))
    guild = SimpleNamespace(id=1, name="S")
    rendu = await raid_mode.declencher(automod, guild, mesures=["vague détectée"])

    assert rendu is etat_arme, "l'état armé à la main a été remplacé"
    assert raid_mode.est_manuel(1) is True
    assert raid_mode._etats[1].manuel is True
