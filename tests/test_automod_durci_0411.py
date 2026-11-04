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
    def __init__(self, ligne):
        self.ligne, self.actives = ligne, []

    async def get_automod(self, guild_id):
        return self.ligne

    async def set_automod(self, guild_id, champ, valeur):
        self.actives.append(champ)


def test_protections_de_base_sur_un_serveur_neuf_seulement():
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.automod_cache = {}
    vierge = {champ: 0 for champ in am.TOGGLE_FIELDS}
    cog.bot = SimpleNamespace(db=_Base(vierge))
    assert asyncio.run(cog.activer_protections_de_base(1)) is True
    assert set(cog.bot.db.actives) == set(am.PROTECTIONS_DE_BASE)
    assert "antilink" not in cog.bot.db.actives  # liens et bots : au choix du serveur
    regle = dict(vierge, antilink=1)
    cog.bot = SimpleNamespace(db=_Base(regle))
    assert asyncio.run(cog.activer_protections_de_base(1)) is False
    assert cog.bot.db.actives == []


def test_le_spam_est_sanctionne_des_la_premiere_rafale():
    assert am.SPAM_PREMIER_PALIER == 3  # 1 = rappel, 2 = warn, 3 = mute 10 min


def test_la_langue_du_serveur_est_reservee_au_staff():
    for fichier in ("cogs/public_language_choice.py", "cogs/guild_arrival.py"):
        source = (ROOT / fichier).read_text(encoding="utf-8")
        assert "Seuls les administrateurs peuvent choisir la langue du serveur" in source, fichier
