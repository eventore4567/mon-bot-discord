"""Le chargeur musique V102 doit suivre la classe Bot réellement utilisée.

sitecustomize l'installait avant que railway_boot remplace ``commands.Bot`` par
SentriXAutoShardedBot ; le second appel s'arrêtait sur un drapeau global et le
bot réel n'avait jamais ``+music playlist`` (vu au CI le 28/10/2026).
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from discord.ext import commands  # noqa: E402

import sentrix_music_providers_v102 as v102  # noqa: E402


def test_un_second_install_apres_remplacement_de_bot_patche_la_nouvelle_classe(monkeypatch):
    class Ancien(commands.Bot):
        pass

    class Nouveau(commands.AutoShardedBot):
        pass

    monkeypatch.setattr(v102, "_INSTALLED", False)
    monkeypatch.setattr(commands, "Bot", Ancien)
    monkeypatch.setattr(Ancien, "add_cog", Ancien.add_cog)
    v102.install()
    assert getattr(Ancien.add_cog, "_sentrix_music_v102_loader", False)

    monkeypatch.setattr(commands, "Bot", Nouveau)
    monkeypatch.setattr(Nouveau, "add_cog", Nouveau.add_cog)
    v102.install()
    assert getattr(Nouveau.add_cog, "_sentrix_music_v102_loader", False)

    # Idempotent sur une même classe : pas de double enveloppe.
    deja = Nouveau.add_cog
    v102.install()
    assert Nouveau.add_cog is deja
