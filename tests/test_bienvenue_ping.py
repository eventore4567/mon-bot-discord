"""Bienvenue et départ : un vrai @, et le ping se règle à part.

**Ce que Jayden a signalé.** « ça devrait @ la personne… mais genre un vrai @
sans ping. » Le message de bienvenue affichait ``Bienvenue **Jayden**`` — le
nom en gras — au lieu d'un vrai ``@``. La ligne fautive disait son intention :

    visual_body = body.replace(member.mention, f"**{member.display_name}**")

Elle remplaçait la mention pour éviter « deux mentions identiques », le ping
étant déjà au-dessus. Mais un nom en gras n'est plus cliquable : on perdait
l'accès au profil, et le message de bienvenue ne saluait plus vraiment la
personne.

**La correction, et la distinction qui la gouverne.** Une mention et une
notification sont deux choses. Un ``<@id>`` s'affiche toujours comme un @
cliquable ; c'est ``allowed_mentions`` qui décide seul s'il fait sonner le
téléphone. Le corps garde donc son vrai @, et un réglage par serveur dit si le
membre est notifié.

Deux tests étaient rouges EN PRODUCTION là-dessus avant ce lot.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from database.db import Database


class _Bot:
    def __init__(self, db):
        self.db = db


class ReglageDuPingTests(unittest.IsolatedAsyncioTestCase):
    """IsolatedAsyncioTestCase et non une fixture async : c'est le motif déjà
    utilisé partout dans ce dépôt, et pytest-asyncio n'est pas configuré pour
    les fixtures asynchrones ici."""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmp.name, "t.db"))
        await self.db.connect()
        self.bot = _Bot(self.db)

    async def asyncTearDown(self):
        await self.db._conn.close()
        self._tmp.cleanup()

    async def test_le_reglage_se_lit_apres_ecriture(self):
        """Le piège évité : les colonnes avaient été ajoutées au schéma mais pas
        au SELECT, donc la lecture retombait toujours sur le défaut et le
        réglage n'aurait jamais rien changé. Un aller-retour réel est le seul
        moyen de s'en apercevoir."""
        from cogs import setup_v2_completion as sv

        await sv._save_welcome_presentation(
            self.bot, 700, title="Salut !", show_avatar=True,
            show_member_count=True, actor_id=1, ping=False, goodbye_ping=True,
        )
        lu = await sv._welcome_presentation(self.bot, 700)
        assert lu["ping"] is False
        assert lu["goodbye_ping"] is True

    async def test_les_defauts_ne_changent_rien_aux_serveurs_existants(self):
        """Condition pour que ce lot soit sûr à déployer : un serveur qui n'a
        jamais touché ce réglage doit se comporter comme avant."""
        from cogs import setup_v2_completion as sv

        lu = await sv._welcome_presentation(self.bot, 999)
        assert lu["ping"] is True, "l'arrivant était notifié avant, il doit l'être encore"
        assert lu["goodbye_ping"] is False, (
            "un départ ne notifie personne : la personne est partie, et pinguer "
            "le salon à chaque départ est le meilleur moyen de faire couper le module"
        )

    async def test_changer_le_titre_ne_reinitialise_pas_le_ping(self):
        """Écraser un réglage parce qu'on en change un autre est une surprise
        désagréable — et c'est ce que fait un INSERT qui ne relit pas
        l'existant."""
        from cogs import setup_v2_completion as sv

        await sv._save_welcome_presentation(
            self.bot, 700, title="A", show_avatar=True, show_member_count=True,
            actor_id=1, ping=False,
        )
        # Appel « historique » : ni ping ni goodbye_ping passés.
        await sv._save_welcome_presentation(
            self.bot, 700, title="B", show_avatar=False,
            show_member_count=True, actor_id=1,
        )
        lu = await sv._welcome_presentation(self.bot, 700)
        assert lu["title"] == "B"
        assert lu["ping"] is False, "le ping a été réinitialisé par un changement de titre"


# =============================================================================
# Mention et notification sont deux choses distinctes
# =============================================================================

def test_une_mention_reste_affichee_meme_sans_notification():
    """Le cœur de la demande. allowed_mentions vide ne retire PAS le @ du
    message : il l'empêche seulement de notifier. C'est ce qui permet d'avoir
    « un vrai @ sans ping »."""
    import discord

    silencieux = discord.AllowedMentions.none()
    assert silencieux.users is False
    # Le texte, lui, contient toujours la mention — Discord l'affiche comme un
    # @ cliquable quoi qu'il arrive.
    corps = "Bienvenue <@111> sur **Le Repaire** !"
    assert "<@111>" in corps


def test_le_corps_du_message_nest_plus_transforme_en_gras():
    """Regarde le code réellement exécuté : le remplacement de la mention par
    le nom en gras ne doit pas revenir."""
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv._send_welcome)
    assert 'replace(member.mention' not in source, (
        "la mention est de nouveau remplacée par du texte : le @ n'est plus "
        "cliquable et le profil devient inaccessible depuis le message"
    )
    assert "display_name}**" not in source


def test_le_ping_decide_des_allowed_mentions():
    """La preuve que le réglage sert à quelque chose : il apparaît dans la
    construction des allowed_mentions, pas seulement dans la base."""
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv._send_welcome)
    assert 'presentation.get("ping"' in source
    assert "AllowedMentions" in source


def test_le_depart_a_son_propre_reglage():
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv._send_goodbye)
    assert 'presentation.get("goodbye_ping"' in source


# =============================================================================
# Le setup montre le DÉPART autant que la bienvenue
# =============================================================================
#
# Jayden : « pour le setup de bienvenue et départ on voit que bienvenue ».
#
# Le champ du message de départ existait pourtant, et il était bien enregistré.
# Ce qui manquait, c'était la RESTITUTION : la confirmation disait « Bienvenue
# enregistrée » alors que le départ venait d'être sauvegardé lui aussi, et le
# seul bouton de test ne testait que la bienvenue. On configurait donc son
# message de départ à l'aveugle et on le découvrait au premier vrai départ —
# trop tard pour corriger une faute de frappe.


def test_la_confirmation_nomme_les_deux():
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv.WelcomeSettingsModal.on_submit)
    assert "**Départ**" in source, "la confirmation ne parle toujours que de bienvenue"
    assert "**Bienvenue**" in source


def test_il_existe_un_bouton_de_test_du_depart():
    from cogs import setup_v2_completion as sv

    libelles = {
        str(getattr(enfant, "label", ""))
        for enfant in sv.WelcomeTestView(None, None, 1).children
    }
    assert "Tester la bienvenue" in libelles
    assert "Tester le départ" in libelles


def test_le_test_de_depart_ne_notifie_personne():
    """Un test qui pingue le salon à chaque essai de configuration est le
    meilleur moyen de faire couper le module."""
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv._send_goodbye)
    assert "and not test" in source, (
        "le mode test peut encore notifier le membre"
    )


def test_le_test_de_depart_ignore_le_module_coupe():
    """Sinon on ne peut pas prévisualiser son message avant d'activer le
    module, ce qui est précisément le moment où on en a besoin."""
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv._send_goodbye)
    assert 'if not test and not await core.module_enabled' in source


def test_le_champ_doptions_porte_les_deux_pings():
    """Discord limite une modale à cinq champs, et les cinq sont pris : les
    réglages suivants passent par le champ d'options, comme le font déjà
    l'avatar et le compteur de membres."""
    import inspect

    from cogs import setup_v2_completion as sv

    source = inspect.getsource(sv.WelcomeSettingsModal.__init__)
    assert "ping=" in source and "ping-depart=" in source
