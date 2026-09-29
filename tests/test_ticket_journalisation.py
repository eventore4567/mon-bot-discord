"""La journalisation des tickets, mesurée sur une vraie base.

Ce que ces tests tiennent, et qu'aucun test ne tenait avant : chacune des
quatorze actions de ticket laisse une trace, dans le journal Tickets, avec
son propre type d'événement, une référence citable et un bouton vers le
salon. Avant ce lot, onze actions sur quatorze ne journalisaient rien du
tout, et les trois restantes partageaient deux types d'événement.

On mesure ce qui part réellement vers le transport — le type d'événement,
l'embed, la vue — en interceptant ``log_service.send_log``, le point unique
par lequel tout log passe.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from database.db import Database
from services import tickets as tickets_service


class _Bot:
    def __init__(self, db):
        self.db = db


def _membre(uid: int, nom: str):
    return SimpleNamespace(id=uid, mention=f"<@{uid}>", display_name=nom, name=nom, bot=False)


def _salon(cid: int, nom: str):
    return SimpleNamespace(id=cid, name=nom, mention=f"<#{cid}>")


class JournalisationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmp.name, "t.db"))
        await self.db.connect()
        self.bot = _Bot(self.db)
        self.guild = SimpleNamespace(id=700, name="Serveur")

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmp.cleanup()

    async def _journaliser(self, evenement, **kwargs):
        """Retourne (référence, appel capturé vers send_log)."""
        with patch("utils.log_service.send_log", new=AsyncMock(return_value=True)) as envoi:
            reference = await tickets_service.journaliser_evenement(
                self.bot, self.guild, evenement, **kwargs
            )
        return reference, envoi

    # ------------------------------------------------------- type d'événement

    async def test_chaque_evenement_part_avec_son_propre_type(self):
        """Le défaut central : onze actions n'émettaient rien, et les trois
        qui émettaient se partageaient « ticket_open » et « ticket_close »."""
        vus = []
        for evenement in tickets_service.EVENEMENTS_TICKET:
            _ref, envoi = await self._journaliser(
                evenement, ticket_id=1, channel=_salon(9, "ticket-1"),
                acteur=_membre(2, "mod"),
            )
            vus.append(envoi.await_args.args[2])
        assert sorted(vus) == sorted(tickets_service.EVENEMENTS_TICKET)
        assert len(set(vus)) == 14, "deux événements partagent un type"

    # ------------------------------------------------------- ligne d'audit

    async def test_la_ligne_daudit_est_ecrite_avec_tous_ses_champs(self):
        await self._journaliser(
            "ticket_member_add", ticket_id=42, channel=_salon(9, "ticket-42"),
            acteur=_membre(2, "mod"), cible=_membre(3, "ajoute"),
        )
        ligne = await self.db.fetchone("SELECT * FROM ticket_events")
        assert ligne["guild_id"] == 700
        assert ligne["ticket_id"] == 42
        assert ligne["channel_id"] == 9
        assert ligne["event"] == "ticket_member_add"
        assert ligne["actor_id"] == 2
        assert ligne["target_id"] == 3
        assert ligne["created_at"] > 0

    async def test_la_reference_correspond_a_la_ligne_ecrite(self):
        reference, _ = await self._journaliser(
            "ticket_claim", ticket_id=42, channel=_salon(9, "t"), acteur=_membre(2, "m"),
        )
        ligne = await self.db.fetchone("SELECT id FROM ticket_events")
        assert reference == f"TK-0042-{ligne['id']}"

    async def test_la_reference_est_dans_lembed_envoye(self):
        """Une référence que le staff ne voit pas ne sert à rien."""
        reference, envoi = await self._journaliser(
            "ticket_claim", ticket_id=42, channel=_salon(9, "t"), acteur=_membre(2, "m"),
        )
        embed = envoi.await_args.args[3]
        valeurs = " ".join(f.value or "" for f in embed.fields)
        assert reference in valeurs

    async def test_deux_actions_sur_le_meme_ticket_donnent_deux_references(self):
        a, _ = await self._journaliser("ticket_claim", ticket_id=42, channel=_salon(9, "t"))
        b, _ = await self._journaliser("ticket_unclaim", ticket_id=42, channel=_salon(9, "t"))
        assert a != b
        lignes = await self.db.fetchall("SELECT event FROM ticket_events ORDER BY id")
        assert [l["event"] for l in lignes] == ["ticket_claim", "ticket_unclaim"]

    async def test_laudit_survit_a_la_suppression_du_salon(self):
        """La raison d'être de la table : le salon d'un ticket est supprimé
        automatiquement quelques secondes après la fermeture. Si la seule trace
        vivait dans ce salon, elle disparaîtrait avec lui."""
        reference, _ = await self._journaliser(
            "ticket_close", ticket_id=42, channel=_salon(9, "ticket-42"), acteur=_membre(2, "m"),
        )
        ligne = await self.db.fetchone(
            "SELECT event, channel_id FROM ticket_events WHERE id = ?",
            (int(reference.rsplit("-", 1)[1]),),
        )
        assert ligne["event"] == "ticket_close"
        assert ligne["channel_id"] == 9

    # ------------------------------------------------------- bouton

    async def test_le_bouton_voir_le_ticket_accompagne_le_log(self):
        _ref, envoi = await self._journaliser(
            "ticket_claim", ticket_id=1, channel=_salon(9, "t"), acteur=_membre(2, "m"),
        )
        vue = envoi.await_args.kwargs["view"]
        assert vue is not None
        assert vue.children[0].url == "https://discord.com/channels/700/9"

    async def test_aucun_bouton_quand_le_salon_a_disparu(self):
        """ticket_delete journalise juste avant channel.delete() ; ticket_rating
        arrive en privé bien après. Dans les deux cas le lien mènerait nulle part."""
        _ref, envoi = await self._journaliser("ticket_rating", ticket_id=1, avec_bouton=False)
        assert envoi.await_args.kwargs["view"] is None

    # ------------------------------------------------------- champs de l'embed

    async def test_le_salon_est_donne_en_mention_ET_en_nom(self):
        """Après suppression, une mention s'affiche « #deleted-channel » : sans
        le nom en clair, on ne sait plus de quel ticket parlait la ligne."""
        _ref, envoi = await self._journaliser(
            "ticket_delete", ticket_id=1, channel=_salon(9, "ticket-jayden-3"),
            avec_bouton=False,
        )
        embed = envoi.await_args.args[3]
        salon = next(f.value for f in embed.fields if "Salon" in f.name)
        assert "<#9>" in salon and "ticket-jayden-3" in salon

    async def test_les_champs_supplementaires_de_lappelant_sont_conserves(self):
        _ref, envoi = await self._journaliser(
            "ticket_rename", ticket_id=1, channel=_salon(9, "apres"),
            acteur=_membre(2, "m"), extra={"📛 Avant": "`avant`", "🏷️ Après": "`apres`"},
        )
        embed = envoi.await_args.args[3]
        noms = [f.name for f in embed.fields]
        assert any("Avant" in n for n in noms) and any("Après" in n for n in noms)

    async def test_le_libelle_dacteur_depend_de_levenement(self):
        """« Modérateur » sur une ouverture de ticket serait faux : c'est le
        membre lui-même qui ouvre."""
        _ref, envoi = await self._journaliser(
            "ticket_open", ticket_id=1, channel=_salon(9, "t"), acteur=_membre(2, "jayden"),
        )
        noms = [f.name for f in envoi.await_args.args[3].fields]
        assert "Ouvert par" in noms
        assert "Modérateur" not in noms

    # ------------------------------------------------------- robustesse

    async def test_une_panne_de_log_ne_leve_jamais(self):
        """Le contrat que Jayden a posé : un ticket réellement créé ne doit
        jamais afficher « Action impossible » parce que son journal est en
        panne."""
        with patch("utils.log_service.send_log", new=AsyncMock(side_effect=RuntimeError("transport mort"))):
            reference = await tickets_service.journaliser_evenement(
                self.bot, self.guild, "ticket_open", ticket_id=1, channel=_salon(9, "t"),
            )
        assert reference.startswith("TK-0001-")
        # La ligne d'audit, elle, a bien été écrite : la trace survit même quand
        # le message ne part pas.
        assert await self.db.fetchone("SELECT id FROM ticket_events") is not None

    async def test_un_audit_en_panne_ne_leve_pas_et_degrade_la_reference(self):
        """Symétrique : base d'audit indisponible, l'action métier continue."""
        with patch.object(self.db, "execute", new=AsyncMock(side_effect=RuntimeError("base morte"))), \
             patch("utils.log_service.send_log", new=AsyncMock(return_value=True)) as envoi:
            reference = await tickets_service.journaliser_evenement(
                self.bot, self.guild, "ticket_close", ticket_id=7, channel=_salon(9, "t"),
            )
        assert reference == "TK-0007"
        # Et le log part quand même : mieux vaut une ligne sans numéro d'audit
        # que pas de ligne.
        envoi.assert_awaited_once()

    async def test_la_cle_devenement_porte_le_bon_type(self):
        """log_service._event_from_key relit parts[1] EN PRIORITÉ sur le
        log_type. Une clé mal formée ferait router l'événement au hasard."""
        from utils import log_service

        _ref, envoi = await self._journaliser(
            "ticket_transfer", ticket_id=1, channel=_salon(9, "t"), acteur=_membre(2, "m"),
        )
        cle = envoi.await_args.kwargs["event_key"]
        assert log_service._event_from_key(cle) == "ticket_transfer"

    async def test_un_evenement_inconnu_ne_casse_pas_la_journalisation(self):
        """Fail-open ici, volontairement : un événement non déclaré doit
        arriver quelque part avec un titre lisible, pas disparaître."""
        _ref, envoi = await self._journaliser("ticket_chose_nouvelle", ticket_id=1)
        assert envoi.await_args.args[3].title.endswith("ticket_chose_nouvelle")


if __name__ == "__main__":
    unittest.main()


class JamaisLeverTests(unittest.IsolatedAsyncioTestCase):
    """« Ne lève jamais » est une garantie, pas une intention.

    Ces appels arrivent APRÈS que l'action métier a réussi. Le ticket est
    créé, fermé, rouvert ; le membre est ajouté au salon. Une exception ici
    afficherait une erreur pour quelque chose qui a parfaitement fonctionné,
    et c'est exactement ce que Jayden a demandé de supprimer.

    Le cas du milieu n'est pas théorique : il s'est produit pendant le lot.
    ``ctx.author`` sur un objet de contexte qui n'en avait pas faisait
    remonter un AttributeError depuis ``ticket_reopen``, sur une réouverture
    déjà écrite en base.
    """

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmp.name, "t.db"))
        await self.db.connect()
        self.bot = _Bot(self.db)
        self.guild = SimpleNamespace(id=700, name="Serveur")

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmp.cleanup()

    async def _appeler(self, **kwargs):
        with patch("utils.log_service.send_log", new=AsyncMock(return_value=True)):
            return await tickets_service.journaliser_evenement(
                self.bot, self.guild, "ticket_reopen", **kwargs
            )

    async def test_un_acteur_absent_ne_leve_pas(self):
        reference = await self._appeler(ticket_id=7, acteur=None)
        assert reference.startswith("TK-0007-")

    async def test_un_acteur_sans_identifiant_ne_leve_pas(self):
        """Le cas réel : un objet de contexte minimal, sans .id exploitable."""
        reference = await self._appeler(ticket_id=7, acteur=object())
        assert reference.startswith("TK-0007-")

    async def test_un_salon_sans_nom_ni_mention_ne_leve_pas(self):
        reference = await self._appeler(ticket_id=7, channel=object())
        assert reference.startswith("TK-0007-")

    async def test_un_serveur_sans_identifiant_ne_leve_pas(self):
        with patch("utils.log_service.send_log", new=AsyncMock(return_value=True)):
            reference = await tickets_service.journaliser_evenement(
                self.bot, object(), "ticket_close", ticket_id=7,
            )
        assert reference.startswith("TK-0007")

    async def test_un_extra_non_iterable_ne_leve_pas(self):
        reference = await self._appeler(ticket_id=7, extra="pas un dictionnaire")
        assert reference.startswith("TK-0007")

    async def test_la_reference_reste_citable_meme_en_cas_de_panne_totale(self):
        """Pire cas : la construction de l'embed elle-même échoue. Le staff doit
        quand même recevoir quelque chose qu'il peut citer, pas une chaîne vide
        au milieu d'une phrase."""
        with patch("utils.embeds.log_entry", side_effect=RuntimeError("embeds morts")):
            reference = await tickets_service.journaliser_evenement(
                self.bot, self.guild, "ticket_reopen", ticket_id=7,
            )
        assert reference == "TK-0007"
        assert reference.strip(), "une référence vide dans un message est pire que rien"
