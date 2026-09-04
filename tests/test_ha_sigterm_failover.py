"""SIGTERM tuait SentriX sans libérer le lease ni sauvegarder.

Railway envoie SIGTERM à chaque redéploiement. Python termine alors le processus
SANS dérouler les ``finally`` : ni le snapshot d'arrêt de ``railway_boot.run()``
ni le ``coordinator.close(release=True)`` de ``railway_ha_boot.run()`` ne
s'exécutaient. Conséquences mesurées en production :

- le lease Redis survivait jusqu'à l'expiration du TTL, soit **jusqu'à 30 secondes
  de bot hors ligne** à chaque bascule ;
- le dernier snapshot manquait, donc une reprise restaurait un état plus ancien ;
- une instance encore passive (en attente du lease) ignorait complètement SIGTERM.

S'y ajoutait une restauration inutile : reprendre la main après SON PROPRE
redémarrage était traité comme un takeover, ce qui faisait REVENIR EN ARRIÈRE
toutes les écritures postérieures au dernier snapshot périodique.

Ces tests verrouillent les quatre garanties : arrêt gracieux, déblocage d'une
instance passive, non-restauration d'une reprise de soi, et surtout l'invariant
central — **une seule instance peut être active sur Discord**.
"""
from __future__ import annotations

import asyncio
import os
import signal

os.environ.setdefault("DISCORD_TOKEN", "x")

from utils.failover import SentriXFailoverCoordinator  # noqa: E402


class _FauxRedis:
    """Redis minimal : SET NX/EX, GET et le script Lua de libération."""

    def __init__(self):
        self.donnees: dict[str, str] = {}

    async def set(self, cle, valeur, nx=False, ex=None):
        if nx and cle in self.donnees:
            return None
        self.donnees[cle] = valeur
        return True

    async def get(self, cle):
        return self.donnees.get(cle)

    async def eval(self, script, _n, cle, proprietaire, *args):
        if self.donnees.get(cle) != proprietaire:
            return 0
        if "del" in script:
            self.donnees.pop(cle, None)
        return 1

    async def ping(self):
        return True

    async def aclose(self):
        return None


def _coordinateur(service: str, redis, role: str = "primary") -> SentriXFailoverCoordinator:
    coord = SentriXFailoverCoordinator()
    coord.enabled = True
    coord.redis_url = "redis://faux"
    coord.role = role
    coord.service_id = service
    coord.state = "starting"
    coord._redis = redis
    return coord


# --------------------------------------------------------------------------
# Invariant central : une seule instance active
# --------------------------------------------------------------------------
async def _une_seule_instance_gagne():
    redis = _FauxRedis()
    instances = [_coordinateur(f"service-{i}", redis) for i in range(5)]
    resultats = [await c._try_acquire() for c in instances]

    assert resultats.count(True) == 1, "exactement une instance doit obtenir le lease"
    gagnant = instances[resultats.index(True)]
    assert gagnant.is_leader is True
    for perdant in (c for c in instances if c is not gagnant):
        assert perdant.is_leader is False
        assert perdant.state == "standby"


def test_une_seule_instance_peut_devenir_active():
    asyncio.run(_une_seule_instance_gagne())


async def _le_lease_est_rendu_a_la_liberation():
    redis = _FauxRedis()
    premier = _coordinateur("primary", redis)
    assert await premier._try_acquire() is True

    second = _coordinateur("standby", redis, role="standby")
    assert await second._try_acquire() is False, "le lease est encore tenu"

    # Arrêt gracieux : le lease repart immédiatement, sans attendre les 30 s de TTL.
    assert await premier.release() is True
    assert await second._try_acquire() is True, "le lease libéré doit être repris aussitôt"


def test_la_liberation_gracieuse_evite_l_attente_du_ttl():
    asyncio.run(_le_lease_est_rendu_a_la_liberation())


async def _un_autre_proprietaire_ne_peut_pas_liberer():
    redis = _FauxRedis()
    proprietaire = _coordinateur("primary", redis)
    await proprietaire._try_acquire()

    intrus = _coordinateur("standby", redis, role="standby")
    intrus.state = "leader"  # prétend l'être
    assert await intrus.release() is False, "seul le vrai propriétaire peut libérer"
    assert redis.donnees.get(proprietaire.lock_key) == proprietaire.owner_id


def test_seul_le_proprietaire_libere_le_lease():
    asyncio.run(_un_autre_proprietaire_ne_peut_pas_liberer())


# --------------------------------------------------------------------------
# Restauration : ne jamais revenir en arrière pour rien
# --------------------------------------------------------------------------
async def _reprise_de_soi_apres_redemarrage():
    redis = _FauxRedis()

    depart = _coordinateur("mon-bot-discord", redis)
    await depart._try_acquire()
    assert depart.reprise_de_soi() is False, "premier démarrage : rien à reprendre"
    await depart.release()

    # Même service qui redémarre (redéploiement) : les données locales font foi.
    apres = _coordinateur("mon-bot-discord", redis)
    await apres._try_acquire()
    assert apres.reprise_de_soi() is True


def test_un_redemarrage_du_primary_ne_declenche_pas_de_restauration():
    asyncio.run(_reprise_de_soi_apres_redemarrage())


async def _bascule_vers_une_autre_instance():
    redis = _FauxRedis()
    primary = _coordinateur("mon-bot-discord", redis)
    await primary._try_acquire()
    await primary.release()

    standby = _coordinateur("sentrix-standby", redis, role="standby")
    await standby._try_acquire()
    # Une AUTRE instance a écrit : la restauration reste obligatoire.
    assert standby.reprise_de_soi() is False


def test_une_vraie_bascule_exige_toujours_la_restauration():
    asyncio.run(_bascule_vers_une_autre_instance())


# --------------------------------------------------------------------------
# SIGTERM
# --------------------------------------------------------------------------
async def _wait_for_leadership_se_debloque_sur_demande_d_arret():
    """Une instance passive doit sortir de l'attente au lieu d'être tuée."""
    redis = _FauxRedis()
    occupant = _coordinateur("occupant", redis)
    await occupant._try_acquire()

    passive = _coordinateur("passive", redis, role="standby")
    passive.poll_seconds = 1

    attente = asyncio.create_task(passive.wait_for_leadership())
    await asyncio.sleep(0.05)
    assert not attente.done(), "l'instance doit bien être en attente du lease"

    passive.demander_arret()
    try:
        await asyncio.wait_for(attente, timeout=2)
        raise AssertionError("wait_for_leadership devait s'interrompre")
    except asyncio.CancelledError:
        pass  # sortie attendue : le finally du launcher peut alors se dérouler


def test_une_instance_passive_sort_de_l_attente_sur_sigterm():
    asyncio.run(_wait_for_leadership_se_debloque_sur_demande_d_arret())


async def _sigterm_declenche_l_arret_gracieux():
    import railway_ha_boot

    ferme = asyncio.Event()

    class _FauxBot:
        async def close(self):
            ferme.set()

    bot = _FauxBot()
    boucle = asyncio.get_running_loop()
    try:
        assert railway_ha_boot._installer_arret_gracieux(bot) is True
        # Idempotent : un second appel ne réinstalle rien.
        assert railway_ha_boot._installer_arret_gracieux(bot) is True

        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(ferme.wait(), timeout=2)

        assert getattr(bot, "_sentrix_arret_demande", False) is True
        assert railway_ha_boot.coordinator._stop.is_set(), (
            "le coordinateur doit aussi être débloqué, sinon une instance passive "
            "resterait suspendue jusqu'au SIGKILL"
        )
    finally:
        for numero in (signal.SIGTERM, signal.SIGINT):
            try:
                boucle.remove_signal_handler(numero)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        railway_ha_boot.coordinator._stop = asyncio.Event()


def test_sigterm_ferme_discord_et_debloque_le_coordinateur():
    asyncio.run(_sigterm_declenche_l_arret_gracieux())
