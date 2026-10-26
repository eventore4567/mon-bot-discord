"""Le bouton 🔒 de /setup → Règlement & accès passe par l'aperçu sécurisé.

L'ancien formulaire « tapez VERROUILLER » parcourait TOUS les salons, les
cachait à @everyone et les ouvrait au rôle Vérifié — salons staff, logs et
privés compris : chaque membre vérifié aurait vu les espaces du staff. Le
bouton ouvre désormais le même aperçu que l'éditeur du règlement, et aucune
permission n'est écrite avant la confirmation explicite.
"""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import setup_experience_v74 as v74  # noqa: E402
from cogs import verify_setup_interactive_v78 as rules_setup  # noqa: E402


class _Salon:
    def __init__(self, sid, nom):
        self.id, self.name, self.mention = sid, nom, f"<#{sid}>"
        self.ecritures = []

    async def set_permissions(self, *args, **kwargs):
        self.ecritures.append((args, kwargs))


def _page(monkeypatch):
    reglement = _Salon(10, "règlement")
    staff = _Salon(11, "discussion-staff")
    role = SimpleNamespace(id=20, mention="@Vérifié", name="Vérifié")
    guild = SimpleNamespace(
        id=1, channels=[reglement, staff],
        get_channel=lambda cid: reglement if cid == 10 else None,
        get_role=lambda rid: role if rid == 20 else None,
    )

    async def execute(*_a):
        return None

    async def config(_gid):
        return {"verification_channel": 10, "verify_role": 20}

    async def fetchone(*_a):
        return {"rules_text": "Respect", "image_url": None, "message_id": 99}

    async def langue(*_a):
        return "fr"

    bot = SimpleNamespace(db=SimpleNamespace(
        execute=execute, get_guild_config=config, fetchone=fetchone,
    ))
    monkeypatch.setattr(v74.language_runtime, "get_language", langue)
    monkeypatch.setattr(v74.v73, "poser_banniere", lambda _c: None)
    monkeypatch.setattr(v74.v73, "_thumbnail", lambda _b: discord.ui.Thumbnail("https://example.com/a.png"))
    ajoutes = []
    vue = SimpleNamespace(
        bot=bot, guild=guild, add_item=ajoutes.append, _add_navigation=lambda _c: None,
    )
    asyncio.run(v74.SentriXSetupV74._build_rules_access(vue))
    return ajoutes, guild, [reglement, staff]


def test_le_formulaire_dangereux_n_existe_plus():
    assert not hasattr(v74, "VerrouillerSalonsModal")


def test_publier_suffit_plus_aucun_bouton_de_verrouillage(monkeypatch):
    # 26/10 : publier le règlement configure tout seul (10 s pour annuler).
    ajoutes, _guild, salons = _page(monkeypatch)
    items = [item for container in ajoutes for item in container.walk_children()]
    labels = [str(getattr(i, "label", "") or "") for i in items if isinstance(i, discord.ui.Button)]
    assert not any("Verrouiller" in label or "Configurer les salons" in label for label in labels)
    textes = " ".join(i.content for i in items if isinstance(i, discord.ui.TextDisplay))
    assert "10 secondes pour annuler" in textes
    assert all(not salon.ecritures for salon in salons)
