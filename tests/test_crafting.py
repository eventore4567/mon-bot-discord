"""Artisanat de +potion sur une vraie base SQLite.

Le seul défaut qui compte ici ne se voit pas en cliquant : deux fabrications
lancées au même instant sur le dernier ingrédient. Si les deux aboutissent, le
joueur a dupliqué un objet ; si les deux échouent à moitié, il a perdu ses
ingrédients sans rien recevoir. Les deux cas sont testés contre de vraies
transactions, pas contre une imitation.
"""
from __future__ import annotations

import asyncio
import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import aiosqlite

from services import crafting

SCHEMA = """
CREATE TABLE inventory (
    guild_id INTEGER, user_id INTEGER, item_name TEXT,
    quantity INTEGER DEFAULT 1, UNIQUE (guild_id, user_id, item_name));
CREATE TABLE temporary_boosts (
    guild_id INTEGER, user_id INTEGER, money_multiplier REAL, xp_multiplier REAL,
    expires_at INTEGER, source TEXT, updated_at INTEGER,
    PRIMARY KEY (guild_id, user_id));
CREATE TABLE shop_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER, name TEXT, price INTEGER, role_id INTEGER);
"""

GUILD, USER = 1, 2


class _FakeDB:
    """La surface réellement utilisée : une vraie connexion et le même verrou."""

    def __init__(self, conn):
        self._conn = conn
        self._economy_lock = asyncio.Lock()

    async def fetchall(self, requete, params=()):
        curseur = await self._conn.execute(requete, params)
        try:
            return await curseur.fetchall()
        finally:
            await curseur.close()

    async def fetchone(self, requete, params=()):
        curseur = await self._conn.execute(requete, params)
        try:
            return await curseur.fetchone()
        finally:
            await curseur.close()

    async def execute(self, requete, params=()):
        curseur = await self._conn.execute(requete, params)
        await self._conn.commit()
        return curseur


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await aiosqlite.connect(":memory:")
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        self.db = _FakeDB(self.conn)

    async def asyncTearDown(self):
        await self.conn.close()

    async def poser(self, cle, quantite, user=USER):
        await self.conn.execute(
            "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET "
            "quantity=inventory.quantity+excluded.quantity",
            (GUILD, user, crafting.nom_objet(cle), quantite))
        await self.conn.commit()

    async def equiper_pour(self, cle_recette, user=USER):
        for cle, quantite in crafting.RECETTES[cle_recette].ingredients:
            await self.poser(cle, quantite, user)

    async def lignes(self, user=USER):
        return await self.db.fetchall(
            "SELECT item_name, quantity FROM inventory WHERE guild_id=? AND user_id=?",
            (GUILD, user))


class RecettesTests(unittest.TestCase):
    def test_chaque_recette_consomme_plus_d_objets_qu_elle_n_en_produit(self):
        """Invariant indépendant des prix : aucune boucle ne peut créer d'objets."""
        for recette in crafting.RECETTES.values():
            self.assertGreater(recette.cout_total, 1, recette.cle)

    def test_aucune_boucle_fabriquer_puis_revendre_ne_cree_d_argent(self):
        """Mesuré avec le prix de repli de services.economy.atomic_sell.

        Un objet hors boutique se revend à prix fixe. Fabriquer trois
        ingrédients en une potion détruit donc les deux tiers de la valeur
        revendable : la boucle est un puits, jamais une source.
        """
        for recette in crafting.RECETTES.values():
            entree = recette.cout_total * crafting.VALEUR_REVENTE
            sortie = 1 * crafting.VALEUR_REVENTE
            self.assertLess(sortie, entree, f"{recette.cle} : {sortie} ≥ {entree}")

    def test_toutes_les_recettes_utilisent_des_ingredients_connus(self):
        for recette in crafting.RECETTES.values():
            for cle, quantite in recette.ingredients:
                self.assertIn(cle, crafting.INGREDIENTS)
                self.assertGreater(quantite, 0)

    def test_les_multiplicateurs_restent_dans_les_bornes_du_socle(self):
        """grant_quest_boost écrête à 2.0 : promettre plus serait mentir."""
        for recette in crafting.RECETTES.values():
            self.assertGreaterEqual(recette.multiplicateur_argent, 1.0)
            self.assertLessEqual(recette.multiplicateur_argent, 2.0)
            self.assertGreaterEqual(recette.multiplicateur_xp, 1.0)
            self.assertLessEqual(recette.multiplicateur_xp, 2.0)
            self.assertGreaterEqual(recette.duree, 60)

    def test_chaque_recette_a_un_effet_reel(self):
        for recette in crafting.RECETTES.values():
            self.assertGreater(
                max(recette.multiplicateur_argent, recette.multiplicateur_xp), 1.0,
                f"{recette.cle} ne fait rien")

    def test_les_noms_d_objets_sont_distincts_et_portent_leur_pictogramme(self):
        noms = [crafting.nom_objet(c)
                for c in list(crafting.INGREDIENTS) + list(crafting.RECETTES)]
        self.assertEqual(len(noms), len(set(noms)))
        for nom in noms:
            self.assertFalse(nom[0].isascii(), f"{nom} n'a pas de pictogramme")

    def test_la_recette_la_plus_forte_est_la_plus_chere(self):
        par_puissance = sorted(
            crafting.RECETTES.values(),
            key=lambda r: r.multiplicateur_argent + r.multiplicateur_xp)
        self.assertEqual(par_puissance[-1].cout_total,
                         max(r.cout_total for r in crafting.RECETTES.values()))


class FabricationTests(_Base):
    async def test_fabrique_consomme_les_ingredients_et_cree_la_potion(self):
        await self.equiper_pour("vigueur")
        self.assertEqual(await crafting.fabriquer(self.db, GUILD, USER, "vigueur"), "ok")
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {"vigueur": 1})

    async def test_deux_fabrications_simultanees_sur_le_dernier_ingredient(self):
        """Le test exigé par Jayden : exactement un succès, inventaire cohérent."""
        await self.equiper_pour("vigueur")
        resultats = await asyncio.gather(
            crafting.fabriquer(self.db, GUILD, USER, "vigueur"),
            crafting.fabriquer(self.db, GUILD, USER, "vigueur"),
        )
        self.assertEqual(sorted(resultats), ["missing", "ok"])
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {"vigueur": 1})
        for ligne in await self.lignes():
            self.assertGreater(ligne["quantity"], 0, "ligne à quantité nulle laissée en base")

    async def test_cinq_fabrications_simultanees_pour_deux_lots(self):
        for cle, quantite in crafting.RECETTES["vigueur"].ingredients:
            await self.poser(cle, quantite * 2)
        resultats = await asyncio.gather(*[
            crafting.fabriquer(self.db, GUILD, USER, "vigueur") for _ in range(5)])
        self.assertEqual(resultats.count("ok"), 2, resultats)
        self.assertEqual((await crafting.stock(self.db, GUILD, USER)).get("vigueur"), 2)

    async def test_un_echec_ne_consomme_rien(self):
        await self.poser("herbe", 2)
        avant = await crafting.stock(self.db, GUILD, USER)
        self.assertEqual(await crafting.fabriquer(self.db, GUILD, USER, "vigueur"), "missing")
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), avant)

    async def test_le_retrait_partiel_est_annule(self):
        """Le philtre prend trois ingrédients ; il en manque un seul.

        Les deux premiers retraits ont déjà eu lieu quand le troisième échoue :
        sans rollback, le joueur perdrait ses ingrédients pour rien.
        """
        await self.poser("herbe", 2)
        await self.poser("champignon", 1)
        avant = await crafting.stock(self.db, GUILD, USER)
        self.assertEqual(await crafting.fabriquer(self.db, GUILD, USER, "fortune"), "missing")
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), avant)

    async def test_une_recette_inconnue_est_refusee(self):
        self.assertEqual(await crafting.fabriquer(self.db, GUILD, USER, "amour"), "invalid")

    async def test_sans_connexion_rien_n_est_tente(self):
        class SansConnexion:
            _conn = None
            _economy_lock = asyncio.Lock()

        self.assertEqual(
            await crafting.fabriquer(SansConnexion(), GUILD, USER, "vigueur"), "unavailable")

    async def test_l_inventaire_d_un_autre_membre_n_est_pas_touche(self):
        await self.equiper_pour("vigueur", user=USER)
        await self.equiper_pour("vigueur", user=USER + 1)
        await crafting.fabriquer(self.db, GUILD, USER, "vigueur")
        voisin = await crafting.stock(self.db, GUILD, USER + 1)
        self.assertEqual(voisin, {"herbe": 2, "rosee": 1})


class RecolteTests(_Base):
    async def test_la_recolte_ajoute_ce_qui_est_annonce(self):
        statut, obtenus = await crafting.recolter(
            self.db, GUILD, USER, [("herbe", 2), ("eclat", 1)])
        self.assertEqual(statut, "ok")
        self.assertEqual(dict(obtenus), {"herbe": 2, "eclat": 1})
        self.assertEqual(await crafting.stock(self.db, GUILD, USER),
                         {"herbe": 2, "eclat": 1})

    async def test_une_recolte_vide_est_refusee(self):
        self.assertEqual((await crafting.recolter(self.db, GUILD, USER, []))[0], "invalid")

    async def test_un_ingredient_inconnu_annule_toute_la_recolte(self):
        statut, _ = await crafting.recolter(
            self.db, GUILD, USER, [("herbe", 2), ("dragon", 1)])
        self.assertEqual(statut, "invalid")
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {})

    async def test_une_quantite_negative_est_refusee(self):
        statut, _ = await crafting.recolter(self.db, GUILD, USER, [("herbe", -5)])
        self.assertEqual(statut, "invalid")
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {})

    async def test_les_recoltes_s_accumulent(self):
        await crafting.recolter(self.db, GUILD, USER, [("herbe", 2)])
        await crafting.recolter(self.db, GUILD, USER, [("herbe", 3)])
        self.assertEqual((await crafting.stock(self.db, GUILD, USER))["herbe"], 5)


class ConsommationTests(_Base):
    async def test_boire_consomme_la_potion_et_active_le_boost(self):
        await self.equiper_pour("vigueur")
        await crafting.fabriquer(self.db, GUILD, USER, "vigueur")
        statut, boost = await crafting.boire(self.db, GUILD, USER, "vigueur")
        self.assertEqual(statut, "ok")
        self.assertEqual(boost.source, "potion:vigueur")
        self.assertEqual(boost.money_multiplier,
                         crafting.RECETTES["vigueur"].multiplicateur_argent)
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {})

    async def test_boire_sans_potion_echoue_proprement(self):
        statut, boost = await crafting.boire(self.db, GUILD, USER, "vigueur")
        self.assertEqual(statut, "missing")
        self.assertIsNone(boost)

    async def test_deux_gorgees_simultanees_ne_consomment_qu_une_potion(self):
        await self.poser("vigueur", 1)
        resultats = await asyncio.gather(
            crafting.boire(self.db, GUILD, USER, "vigueur"),
            crafting.boire(self.db, GUILD, USER, "vigueur"),
        )
        self.assertEqual(sorted(s for s, _ in resultats), ["missing", "ok"])
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {})

    async def test_le_boost_survit_en_base(self):
        """Un effet perdu au redémarrage n'est pas un effet."""
        await self.poser("fortune", 1)
        await crafting.boire(self.db, GUILD, USER, "fortune")
        ligne = await self.db.fetchone(
            "SELECT source, money_multiplier, expires_at FROM temporary_boosts "
            "WHERE guild_id=? AND user_id=?", (GUILD, USER))
        self.assertEqual(ligne["source"], "potion:fortune")
        self.assertEqual(ligne["money_multiplier"],
                         crafting.RECETTES["fortune"].multiplicateur_argent)


class LectureTests(_Base):
    async def test_le_stock_ignore_les_objets_etrangers(self):
        await self.poser("herbe", 3)
        await self.conn.execute(
            "INSERT INTO inventory VALUES (?,?,?,?)", (GUILD, USER, "Épée rouillée", 4))
        await self.conn.commit()
        self.assertEqual(await crafting.stock(self.db, GUILD, USER), {"herbe": 3})

    async def test_recettes_realisables_suit_le_stock(self):
        self.assertEqual(crafting.recettes_realisables({}), [])
        await self.equiper_pour("vigueur")
        stocks = await crafting.stock(self.db, GUILD, USER)
        realisables = [r.cle for r in crafting.recettes_realisables(stocks)]
        self.assertEqual(realisables, ["vigueur"])

    async def test_manquants_dit_exactement_ce_qui_manque(self):
        manque = crafting.manquants(crafting.RECETTES["fortune"], {"herbe": 1})
        self.assertEqual(dict(manque), {"herbe": 1, "champignon": 1, "eclat": 1})

    async def test_un_inventaire_illisible_vaut_vide_et_ne_leve_pas(self):
        class Cassee(_FakeDB):
            async def fetchall(self, *a, **k):
                raise RuntimeError("base coupée")

        self.assertEqual(await crafting.stock(Cassee(self.conn), GUILD, USER), {})


if __name__ == "__main__":
    unittest.main()
