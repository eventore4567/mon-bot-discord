"""04/11/2026 : spam compté à l'heure d'envoi, majuscules dès 5 lettres, pings
répétés sur plusieurs messages, protections de base sur un serveur neuf, langue
réservée au staff."""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as am  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_majuscules_des_cinq_lettres_titres_compris():
    assert am._trop_de_majuscules("WWWWW")
    assert am._trop_de_majuscules("# WWWWWW")
    assert am._trop_de_majuscules("ARRÊTEZ ÇA")
    assert not am._trop_de_majuscules("OK")  # moins de 5 lettres
    assert not am._trop_de_majuscules("Salut à tous, ça va ?")
    # Mentions, emojis et liens ne comptent pas comme des lettres.
    assert not am._trop_de_majuscules("<@123456789012345678> <:PEPE:123456789012345678> merci")


def test_le_spam_est_compte_a_l_heure_d_envoi_discord():
    il_y_a_8s = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=8)
    assert abs(am._instant_message(SimpleNamespace(created_at=il_y_a_8s)) - il_y_a_8s.timestamp()) < 0.01
    # Horloge aberrante ou absente : heure courante.
    tres_vieux = dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc)
    assert abs(am._instant_message(SimpleNamespace(created_at=tres_vieux)) - time.time()) < 2
    assert abs(am._instant_message(SimpleNamespace()) - time.time()) < 2


def _message(auteur, cibles, guild_id=1):
    return SimpleNamespace(
        author=SimpleNamespace(id=auteur),
        guild=SimpleNamespace(id=guild_id),
        mentions=[SimpleNamespace(id=c, bot=False) for c in cibles],
        role_mentions=[],
        reference=None,
        created_at=dt.datetime.now(dt.timezone.utc),
    )


def test_pings_repetes_sur_plusieurs_messages():
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=999))
    assert cog._pings_repetes(_message(7, [42])) is None
    assert cog._pings_repetes(_message(7, [42])) is None
    assert cog._pings_repetes(_message(7, [42])) == "Mentions répétées (ping spam)."
    # Un autre auteur a son propre compteur ; pinguer SentriX ou soi-même ne compte pas.
    assert cog._pings_repetes(_message(8, [42])) is None
    for _ in range(5):
        assert cog._pings_repetes(_message(9, [999, 9])) is None
    # Six mentions de personnes différentes en une minute.
    assert cog._pings_repetes(_message(10, [1, 2, 3])) is None
    assert cog._pings_repetes(_message(10, [4, 5, 6])) == "Mentions répétées (ping spam)."


class _Base:
    def __init__(self, deja=None):
        self.actives = []
        self.deja = dict(deja or {})

    async def get_automod(self, guild_id):
        return self.deja

    async def set_automod(self, guild_id, champ, valeur):
        self.actives.append(champ)


def test_aucun_filtre_n_est_active_d_office_a_l_arrivee():
    """04/11/2026 : « enlève les automod déjà activés » — chaque serveur choisit."""
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(db=_Base())
    synchro = []

    async def sync(guild):
        synchro.append(guild.id)

    cog._sync_native_suite = sync
    cog.automod_cache = {}
    asyncio.run(cog.on_guild_join(SimpleNamespace(id=1)))
    # Aucun filtre de messages ; seulement la sécurité qui ne touche à aucun message.
    assert sorted(cog.bot.db.actives) == ["antinuke", "antiraid", "escalation"]
    assert synchro == [1]
    assert not hasattr(am, "PROTECTIONS_DE_BASE")


def test_le_spam_est_sanctionne_des_la_premiere_rafale():
    # 05/11/2026 : avertissement à la première rafale, mute court à la récidive.
    assert am.SPAM_PREMIER_PALIER == 1  # 07/11 : rappel, warn, puis mute 5 min
    assert am.SPAM_ESCALATION_RESET_SECONDS <= 3600  # une heure calme remet à zéro
    assert am.SPAM_MUTE_DURATIONS_SECONDS[0] == 300
    assert max(am.SPAM_MUTE_DURATIONS_SECONDS) <= 7200
    assert {action for _seuil, action in am.ESCALATION_RULES} == {"mute"}


def test_la_langue_du_serveur_est_reservee_au_staff():
    for fichier in ("cogs/public_language_choice.py", "cogs/guild_arrival.py"):
        source = (ROOT / fichier).read_text(encoding="utf-8")
        assert "Seuls les administrateurs peuvent choisir la langue du serveur" in source, fichier


def test_un_serveur_deja_regle_garde_ses_choix_a_l_arrivee():
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(db=_Base(deja={"antispam": 1, "antinuke": 0}))
    cog.automod_cache = {}

    async def sync(guild):
        return None

    cog._sync_native_suite = sync
    asyncio.run(cog.on_guild_join(SimpleNamespace(id=1)))
    assert cog.bot.db.actives == []
