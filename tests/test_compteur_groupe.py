"""09/11/2026 : compteurs regroupés (une écriture par membre toutes les 10 s)."""
import asyncio

from utils.compteur_groupe import CompteurGroupe


def test_les_increments_sont_additionnes_et_ecrits_une_fois():
    ecrits = []

    async def ecrire(cle, total):
        ecrits.append((cle, total))

    async def scenario():
        compteur = CompteurGroupe(ecrire, intervalle=0.05)
        for _ in range(5):
            compteur.ajouter(("g", 1))
        compteur.ajouter(("g", 2), 3)
        await asyncio.sleep(0.12)
        return compteur

    compteur = asyncio.run(scenario())
    assert sorted(ecrits) == [(("g", 1), 5), (("g", 2), 3)]
    assert compteur.en_attente() == {}


def test_une_ecriture_en_echec_n_empeche_pas_les_autres():
    ecrits = []

    async def ecrire(cle, total):
        if cle == "casse":
            raise RuntimeError("base indisponible")
        ecrits.append(cle)

    async def scenario():
        compteur = CompteurGroupe(ecrire, intervalle=60)
        compteur.ajouter("casse")
        compteur.ajouter("ok")
        await compteur.fermer()

    asyncio.run(scenario())
    assert ecrits == ["ok"]
