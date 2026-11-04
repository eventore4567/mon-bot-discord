"""04/11/2026 : un webhook refusé ne fait plus perdre le log (fichiers fermés).

Production : « Webhook mini-profil refusé … NotFound ; envoi par bot », puis
« ValueError: I/O operation on closed file » — le webhook avait fermé les pièces
jointes, et le repli par le bot les réutilisait.
"""
from __future__ import annotations

import asyncio
import io
import os
import time
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils import log_sender_profiles as profiles  # noqa: E402
from utils import wide_logs  # noqa: E402


def test_chaque_tentative_recoit_des_fichiers_neufs():
    original = discord.File(io.BytesIO(b"bande"), filename="bande.webp")
    copies = wide_logs._copier_fichiers([original])
    premier = wide_logs._fichiers_neufs(copies)
    premier[0].close()  # ce que fait un envoi raté
    second = wide_logs._fichiers_neufs(copies)
    assert second[0].fp.read() == b"bande"
    assert second[0].filename == "bande.webp"


def test_un_fichier_ouvert_depuis_un_chemin_survit_a_la_fermeture(tmp_path):
    # La bande des logs part d'un chemin : discord.py ouvre puis FERME ce fichier
    # après un envoi. C'est exactement celui qui cassait le repli.
    chemin = tmp_path / "bande.webp"
    chemin.write_bytes(b"bande")
    fichier = discord.File(str(chemin), filename="bande.webp")
    copies = wide_logs._copier_fichiers([fichier])
    fichier.close()
    assert fichier.fp.closed
    assert wide_logs._fichiers_neufs(copies)[0].fp.read() == b"bande"
    # Un fichier déjà fermé est écarté au lieu de faire échouer tout le log.
    assert wide_logs._copier_fichiers([fichier]) == []


def test_un_webhook_introuvable_est_mis_en_pause(monkeypatch):
    class FauxSalon:
        id = 99
        guild = SimpleNamespace(id=1)

    monkeypatch.setattr(profiles.discord, "TextChannel", FauxSalon)
    monkeypatch.setattr(profiles, "_webhook_en_pause", {})
    appels = []

    class Hook:
        async def send(self, **kwargs):
            appels.append(kwargs)
            for f in kwargs.get("files") or ():
                f.close()
            raise discord.NotFound(SimpleNamespace(status=404, reason="Unknown Webhook"), "Unknown Webhook")

    async def hook(_channel):
        return Hook()

    monkeypatch.setattr(profiles, "_webhook", hook)
    monkeypatch.setattr(profiles, "is_noninteractive", lambda _v: True)
    profil = {"enabled": True, "display_name": "Logs", "avatar_url": None}
    vue = discord.ui.LayoutView()

    async def scenario():
        premier = await profiles.send_with_profile(
            FauxSalon(), vue, [discord.File(io.BytesIO(b"a"), filename="a.png")], profil,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        second = await profiles.send_with_profile(
            FauxSalon(), vue, [], profil, allowed_mentions=discord.AllowedMentions.none(),
        )
        return premier, second

    assert asyncio.run(scenario()) == (None, None)
    assert len(appels) == 1  # le second log ne retente pas le webhook mort
    assert profiles._webhook_en_pause[99] > time.monotonic()
