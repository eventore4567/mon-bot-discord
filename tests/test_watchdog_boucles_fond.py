"""Le watchdog des boucles de fond annonçait des relances qui n'avaient jamais lieu.

En production, `Moderation.check_tempactions` était morte et le journal affichait
« Boucle de fond relancée : Moderation.check_tempactions » TOUTES LES 60 SECONDES
sans que la boucle ne reparte jamais — donc plus aucun bannissement temporaire
n'expirait, un `+tempban 2h` devenant un bannissement définitif de fait.

Cause exacte : le watchdog appelait ``Loop.restart()``, or discord.py le garde
derrière ``_can_be_cancelled()`` qui exige ``self._task and not self._task.done()``.
Une boucle morte a justement une tâche terminée : ``restart()`` y est un no-op
silencieux. La condition qui déclenchait la relance était donc exactement celle
qui la rendait impossible.

Ces tests exercent le VRAI code du watchdog (pas une reproduction) : ils tuent une
boucle pour de bon, vérifient que ``restart()`` seul ne la ressuscite pas — c'est
le bug d'origine, verrouillé ici pour qu'il ne revienne pas — puis vérifient que le
watchdog la relance et qu'elle exécute réellement de nouveaux tours.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402
from discord.ext import commands, tasks  # noqa: E402

from cogs import bot_mastery_runtime, moderation  # noqa: E402
from database.db import Database, now  # noqa: E402


async def _attendre(predicat, message: str, limite: float = 2.0) -> None:
    """Attend qu'une condition asynchrone se réalise, sans dormir inutilement."""
    debut = time.monotonic()
    while time.monotonic() - debut < limite:
        if predicat():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


async def _arreter(loop_obj) -> None:
    """Arrête la boucle ET attend sa tâche.

    Sans cette attente, la tâche est encore vivante quand asyncio.run() ferme
    l'event loop, et discord.py lève « Event loop is closed » au ramassage —
    du bruit de test que ce lot cherche justement à supprimer.
    """
    loop_obj.cancel()
    tache = getattr(loop_obj, "_task", None)
    if tache is not None:
        with contextlib.suppress(BaseException):
            await tache


def _cog_avec_boucle():
    class _CogDeTest(commands.Cog):
        def __init__(self):
            self.tours = 0
            self.doit_planter = True

        # Le nom doit commencer par « check_ » : c'est le filtre du watchdog.
        @tasks.loop(seconds=3600)
        async def check_demo(self):
            self.tours += 1
            if self.doit_planter:
                raise ValueError("panne simulée")

    return _CogDeTest()


async def _mort_puis_relance_par_le_watchdog():
    cog = _cog_avec_boucle()
    cog.check_demo.start()

    # 1. La boucle meurt pour de bon (ValueError n'est pas dans la liste de
    #    reconnexion de discord.py : la tâche se termine définitivement).
    await _attendre(lambda: not cog.check_demo.is_running(), "la boucle aurait dû mourir")
    assert cog.check_demo.failed(), "la boucle devrait être marquée en échec"
    assert cog.tours == 1

    # 2. Le bug d'origine : restart() seul ne ressuscite PAS une tâche terminée.
    cog.check_demo.restart()
    await asyncio.sleep(0.05)
    assert not cog.check_demo.is_running(), (
        "restart() ne peut pas relancer une tâche terminée — si ce test casse, "
        "discord.py a changé et le correctif du watchdog doit être revérifié"
    )

    # 3. Le watchdog réel, lui, doit la relancer.
    cog.doit_planter = False
    faux_runtime = SimpleNamespace(bot=SimpleNamespace(cogs={"demo": cog}))
    await bot_mastery_runtime.BotMasteryRuntime._restart_stalled_loops(faux_runtime)

    await _attendre(lambda: cog.check_demo.is_running(), "le watchdog aurait dû relancer la boucle")
    # 4. Et elle doit réellement retravailler, pas seulement « exister ».
    await _attendre(lambda: cog.tours >= 2, "la boucle relancée n'a exécuté aucun nouveau tour")
    assert not cog.check_demo.failed(), "le drapeau d'échec doit être réarmé après la relance"

    await _arreter(cog.check_demo)


def test_le_watchdog_relance_une_boucle_morte():
    asyncio.run(_mort_puis_relance_par_le_watchdog())


async def _boucle_vivante_mais_bloquee():
    """Une boucle vivante doit passer par restart(), pas par start() (qui lèverait)."""
    cog = _cog_avec_boucle()
    cog.doit_planter = False
    cog.check_demo.start()
    await _attendre(lambda: cog.tours >= 1, "la boucle aurait dû faire un tour")

    assert bot_mastery_runtime._relancer_boucle(cog.check_demo) is True
    await _attendre(lambda: cog.check_demo.is_running(), "la boucle vivante doit rester en marche")

    await _arreter(cog.check_demo)


def test_relancer_une_boucle_vivante_ne_leve_pas():
    asyncio.run(_boucle_vivante_mais_bloquee())


async def _tempban_expire_malgre_une_ligne_defectueuse():
    """Une ligne qui échoue ne doit plus empêcher les autres tempbans d'expirer."""
    db = Database(":memory:")
    await db.connect()
    for user_id in (111, 222):
        await db.execute(
            "INSERT INTO tempactions (guild_id,user_id,action,expires_at) VALUES (?,?,'ban',?)",
            (1, user_id, now() - 10),
        )

    debannis: list[int] = []

    async def unban(objet, reason=None):
        if objet.id == 111:
            # Panne NON-HTTP : c'est précisément ce que l'ancienne version
            # laissait remonter, ce qui terminait la tâche pour de bon.
            raise RuntimeError("panne non-HTTP au milieu du traitement")
        debannis.append(objet.id)

    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.unban = unban

    bot = Mock()
    bot.db = db
    bot.user = Mock(id=999)
    bot.get_guild = Mock(return_value=guild)

    cog = moderation.Moderation.__new__(moderation.Moderation)
    cog.bot = bot
    cog.log_action = AsyncMock()

    # Ne doit PAS lever : sinon discord.py arrêterait la boucle définitivement.
    await cog.check_tempactions()

    assert debannis == [222], "le second tempban devait expirer malgré l'échec du premier"
    restantes = await db.fetchall("SELECT * FROM tempactions")
    assert restantes == [], "les deux lignes échues doivent être consommées"

    await db.close()


def test_un_tempban_expire_meme_si_une_autre_ligne_echoue():
    asyncio.run(_tempban_expire_malgre_une_ligne_defectueuse())


async def _base_indisponible_ne_tue_pas_la_boucle():
    bot = Mock()
    bot.db = Mock()
    bot.db.fetchall = AsyncMock(side_effect=RuntimeError("base momentanément indisponible"))

    cog = moderation.Moderation.__new__(moderation.Moderation)
    cog.bot = bot

    await cog.check_tempactions()  # doit se contenter de journaliser et réessayer plus tard


def test_une_base_indisponible_ne_tue_pas_la_boucle():
    asyncio.run(_base_indisponible_ne_tue_pas_la_boucle())
