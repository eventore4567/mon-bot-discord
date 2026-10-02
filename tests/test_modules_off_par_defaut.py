"""Modules configurables : absence de configuration = inactif, niveaux/économie indépendants,
bienvenue/départ séparés, migration des serveurs existants.

Base SQLite réelle (database.Database) : ces tests exercent le vrai schéma, la vraie
migration et la façade utils/system_features au-dessus de module_settings.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import setup_v2_core as core  # noqa: E402
import discord

from database.db import Database  # noqa: E402
from utils import system_features  # noqa: E402

NEW_GUILD = 111
OLD_LEVELS_GUILD = 222
OLD_WELCOME_GUILD = 333
OLD_EXPLICIT_OFF_GUILD = 444


class _Salon(discord.TextChannel):
    """Un salon que ``isinstance(..., discord.TextChannel)`` accepte.

    ``module_activation_issue`` ne se contente pas de lire l'identifiant en
    base : il vérifie que le salon EXISTE vraiment sur le serveur, sinon
    « configuré » voudrait dire « un identifiant est écrit quelque part ».
    """

    def __init__(self, channel_id: int):
        self.id = int(channel_id)


class _Serveur:
    """Serveur minimal : il résout n'importe quel salon demandé.

    Le test vérifie l'activation implicite, pas la résolution de salon.
    """

    def __init__(self, guild_id: int):
        self.id = int(guild_id)

    def get_channel(self, channel_id: int):
        return _Salon(channel_id)


class _Bot:
    """Double du bot.

    ``get_guild`` est indispensable : ``module_activation_issue`` l'appelle
    pour valider le salon choisi. Sans lui, ce double levait une
    AttributeError que ``note_guild_config_change`` avalait — le module
    n'était jamais activé et le test voyait « not_configured ». C'était aussi
    le cas EN PRODUCTION, où la base fabriquait un porteur tout aussi
    minimal ; le vrai bot s'y installe désormais au démarrage.
    """

    def __init__(self, db):
        self.db = db

    def get_guild(self, guild_id: int):
        return _Serveur(guild_id)


class ModulesOffParDefautTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _Bot(self.db)
        # Comme la production (main.py) : le vrai bot est le porteur des appels
        # modules déclenchés depuis la base. Sans lui, set_guild_config
        # fabriquait un porteur minimal, module_activation_issue n'avait pas de
        # serveur, et l'activation implicite échouait en silence. Le test
        # passait quand même pour « welcome » — la migration idempotente lui
        # créait une ligne depuis guild_config — puis échouait sur « goodbye »,
        # la migration ne se rejouant plus. Un vert pour la mauvaise raison.
        self.db._sentrix_module_holder = self.bot
        core.invalidate_module_cache()

    async def _configurer(self, module: str) -> None:
        """Pose la ressource qu'un module configurable exige avant activation.

        ``set_module_enabled`` refuse d'activer un module dont la ressource
        manque — « Choisis d'abord le salon de bienvenue ». C'est voulu : un
        module actif sans salon ne ferait rien tout en s'affichant comme actif.
        Ces tests activaient donc des modules par un chemin qu'un administrateur
        ne peut pas emprunter.
        """
        champ = {
            "welcome": "welcome_channel",
            "goodbye": "goodbye_channel",
            "levels": "level_channel",
        }.get(module)
        if champ:
            await self.db.set_guild_config(NEW_GUILD, champ, 500)

    async def asyncTearDown(self):
        await self.db.close()
        self._tmpdir.cleanup()
        core.invalidate_module_cache()

    # ------------------------------------------------------------ serveur neuf
    async def test_un_serveur_neuf_a_tout_de_configurable_inactif(self):
        for module in ("levels", "economy", "welcome", "goodbye", "tickets", "logs", "roles", "notifications"):
            with self.subTest(module=module):
                self.assertFalse(await core.module_enabled(self.bot, NEW_GUILD, module))
                self.assertEqual(await core.module_state(self.bot, NEW_GUILD, module), core.MODULE_STATE_NOT_CONFIGURED)
        # Les protections restent actives.
        for module in ("moderation", "security", "ai"):
            with self.subTest(module=module):
                self.assertTrue(await core.module_enabled(self.bot, NEW_GUILD, module))

    async def test_un_serveur_neuf_a_l_automod_inactif(self):
        conf = await self.db.get_automod(NEW_GUILD)
        for key in ("antispam", "antilink", "antiraid", "antiinvite", "antiscam"):
            self.assertFalse(bool(conf[key]), key)

    # ------------------------------------------------------------ trois états
    async def test_les_trois_etats_sont_distingues(self):
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "levels"), core.MODULE_STATE_NOT_CONFIGURED)
        await self._configurer("levels")
        await self._configurer("levels")
        await core.set_module_enabled(self.bot, NEW_GUILD, "levels", True)
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "levels"), core.MODULE_STATE_ENABLED)
        await core.set_module_enabled(self.bot, NEW_GUILD, "levels", False)
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "levels"), core.MODULE_STATE_DISABLED)
        await core.reset_module(self.bot, NEW_GUILD, "levels")
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "levels"), core.MODULE_STATE_NOT_CONFIGURED)

    # ------------------------------------------------------------ niveaux / économie
    async def test_niveaux_et_economie_sont_independants(self):
        cases = [(True, True), (True, False), (False, True), (False, False)]
        for levels_on, economy_on in cases:
            with self.subTest(levels=levels_on, economy=economy_on):
                await self._configurer("levels")
                await core.set_module_enabled(self.bot, NEW_GUILD, "levels", levels_on)
                await core.set_module_enabled(self.bot, NEW_GUILD, "economy", economy_on)
                self.assertEqual(await core.module_enabled(self.bot, NEW_GUILD, "levels"), levels_on)
                self.assertEqual(await core.module_enabled(self.bot, NEW_GUILD, "economy"), economy_on)
                # La façade historique lit la même vérité.
                features = await system_features.get_system_features(self.db, NEW_GUILD, fresh=True)
                self.assertEqual(features["levels_enabled"], levels_on)
                self.assertEqual(features["economy_enabled"], economy_on)

    async def test_la_facade_system_features_ecrit_dans_module_settings(self):
        await system_features.set_system_feature(self.db, NEW_GUILD, "economy", True)
        self.assertTrue(await core.module_enabled(self.bot, NEW_GUILD, "economy"))
        self.assertFalse(await core.module_enabled(self.bot, NEW_GUILD, "levels"))
        await self._configurer("levels")
        await system_features.set_system_feature(self.db, NEW_GUILD, "levels", True)
        await system_features.set_system_feature(self.db, NEW_GUILD, "economy", False)
        self.assertTrue(await system_features.is_system_enabled(self.db, NEW_GUILD, "levels"))
        self.assertFalse(await system_features.is_system_enabled(self.db, NEW_GUILD, "economy"))



    async def test_antilink_est_toujours_strict_et_notifie_le_hook_runtime(self):
        hook = AsyncMock()
        self.db._sentrix_automod_change_hook = hook

        await self.db.set_automod(NEW_GUILD, "antilink", 1)
        conf = await self.db.get_automod(NEW_GUILD)
        self.assertEqual(int(conf["antilink"]), 1)
        self.assertEqual(int(conf["antilink_strict"]), 1)
        hook.assert_awaited_with(NEW_GUILD, "antilink", 1)

        await self.db.set_automod(NEW_GUILD, "antilink_strict", 0)
        conf = await self.db.get_automod(NEW_GUILD)
        self.assertEqual(int(conf["antilink"]), 0)
        self.assertEqual(int(conf["antilink_strict"]), 0)
        hook.assert_awaited_with(NEW_GUILD, "antilink_strict", 0)

    # ------------------------------------------------------------ bienvenue / départ
    async def test_bienvenue_et_depart_sont_deux_modules(self):
        await self._configurer("welcome")
        await core.set_module_enabled(self.bot, NEW_GUILD, "welcome", True)
        self.assertTrue(await core.module_enabled(self.bot, NEW_GUILD, "welcome"))
        self.assertFalse(await core.module_enabled(self.bot, NEW_GUILD, "goodbye"))

    # ------------------------------------------------------------ configurer = activer
    async def test_poser_une_ressource_active_le_module_non_configure(self):
        await self.db.set_guild_config(NEW_GUILD, "welcome_channel", 555)
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "welcome"), core.MODULE_STATE_ENABLED)
        # Le départ reste non configuré : ce sont deux modules.
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "goodbye"), core.MODULE_STATE_NOT_CONFIGURED)
        await self.db.set_guild_config(NEW_GUILD, "goodbye_channel", 556)
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "goodbye"), core.MODULE_STATE_ENABLED)

    async def test_un_module_desactive_explicitement_n_est_pas_rallume_par_une_ressource(self):
        await core.set_module_enabled(self.bot, NEW_GUILD, "levels", False)
        await self.db.set_guild_config(NEW_GUILD, "level_channel", 777)
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "levels"), core.MODULE_STATE_DISABLED)

    # ------------------------------------------------------------ migration
    async def test_la_migration_materialise_les_modules_deja_utilises_une_seule_fois(self):
        # Données « historiques » écrites AVANT la première lecture de module.
        await self.db.execute("INSERT INTO levels (guild_id,user_id,xp,level) VALUES (?,?,?,?)", (OLD_LEVELS_GUILD, 1, 120, 2))
        await self.db.ensure_guild(OLD_WELCOME_GUILD)
        await self.db.execute("UPDATE guild_config SET welcome_channel=? WHERE guild_id=?", (555, OLD_WELCOME_GUILD))
        await self.db.execute(system_features.__doc__ and """
            CREATE TABLE IF NOT EXISTS system_features (
                guild_id INTEGER PRIMARY KEY, economy_enabled INTEGER NOT NULL DEFAULT 1,
                levels_enabled INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL DEFAULT 0)
        """)
        # Ligne explicite (updated_at > 0) : levels coupé volontairement, economy laissé actif.
        await self.db.execute(
            "INSERT INTO system_features (guild_id, economy_enabled, levels_enabled, updated_at) VALUES (?,?,?,?)",
            (OLD_EXPLICIT_OFF_GUILD, 1, 0, 1700000000),
        )
        # Ligne par défaut (updated_at = 0) : ne vaut pas configuration.
        await self.db.execute(
            "INSERT INTO system_features (guild_id, economy_enabled, levels_enabled, updated_at) VALUES (?,?,?,?)",
            (NEW_GUILD, 1, 1, 0),
        )

        # Première lecture : ensure_schema + migration.
        self.assertTrue(await core.module_enabled(self.bot, OLD_LEVELS_GUILD, "levels"))
        self.assertFalse(await core.module_enabled(self.bot, OLD_LEVELS_GUILD, "economy"))
        self.assertTrue(await core.module_enabled(self.bot, OLD_WELCOME_GUILD, "welcome"))
        self.assertFalse(await core.module_enabled(self.bot, OLD_WELCOME_GUILD, "goodbye"))
        self.assertFalse(await core.module_enabled(self.bot, OLD_EXPLICIT_OFF_GUILD, "levels"))
        self.assertTrue(await core.module_enabled(self.bot, OLD_EXPLICIT_OFF_GUILD, "economy"))
        self.assertFalse(await core.module_enabled(self.bot, NEW_GUILD, "levels"))
        self.assertEqual(await core.module_state(self.bot, NEW_GUILD, "economy"), core.MODULE_STATE_NOT_CONFIGURED)

        # Idempotente : une seconde exécution ne réécrit rien.
        self.assertEqual(await core.migrate_module_defaults(self.bot), {})
        rows = await self.db.fetchall("SELECT name FROM sentrix_migrations")
        self.assertEqual(sorted(r["name"] for r in rows), sorted([core._MODULE_DEFAULTS_MIGRATION, core._WARN_THRESHOLD_MIGRATION]))

    async def test_une_configuration_absente_ne_devient_jamais_vraie_apres_migration(self):
        await core.module_enabled(self.bot, NEW_GUILD, "levels")  # déclenche la migration
        for module in core.CONFIGURABLE_MODULES:
            self.assertFalse(await core.module_enabled(self.bot, 999, module), module)


class WelcomeSansSalonTests(unittest.IsolatedAsyncioTestCase):
    """Bienvenue activée mais aucun salon configuré : plus aucun repli sur le salon système."""

    async def test_pas_de_repli_sur_le_salon_systeme(self):
        from cogs import setup_v2_completion as completion

        guild = SimpleNamespace(id=1, get_channel=lambda cid: None, system_channel=SimpleNamespace(id=42), me=SimpleNamespace())
        bot = SimpleNamespace(db=SimpleNamespace(get_guild_config=_no_conf))
        channel, error = await completion._welcome_destination(bot, guild)
        self.assertIsNone(channel)
        self.assertIn("Aucun salon de bienvenue", error)

    async def test_salon_supprime_ne_plante_pas(self):
        from cogs import setup_v2_completion as completion

        conf = {"welcome_channel": 777}
        guild = SimpleNamespace(id=1, get_channel=lambda cid: None, system_channel=None, me=SimpleNamespace())
        bot = SimpleNamespace(db=SimpleNamespace(get_guild_config=_conf(conf)))
        channel, error = await completion._welcome_destination(bot, guild)
        self.assertIsNone(channel)
        self.assertTrue(error)


async def _no_conf(guild_id):
    return None


def _conf(values):
    async def _get(guild_id):
        return values
    return _get
