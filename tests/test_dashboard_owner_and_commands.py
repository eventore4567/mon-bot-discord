"""03/11/2026 : page « Serveurs du bot » dans le dashboard et liste des commandes à jour."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from web import owner_server_manager as osm  # noqa: E402
from web import setup_dashboard  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class _Salon:
    def __init__(self, nom, position, peut, refuse=False):
        self.name, self.position, self._peut, self._refuse = nom, position, peut, refuse
        self.appels = []

    def permissions_for(self, _membre):
        return SimpleNamespace(create_instant_invite=self._peut)

    async def create_invite(self, **kwargs):
        self.appels.append(kwargs)
        if self._refuse:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "non")
        return SimpleNamespace(url=f"https://discord.gg/{self.name}")


def _guild(salons, *, systeme=None, gerer=False, invitations=()):
    async def invites():
        return list(invitations)

    return SimpleNamespace(
        id=1, name="Test", me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_guild=gerer)),
        system_channel=systeme, rules_channel=None, text_channels=salons, invites=invites,
    )


def test_invitation_unique_dans_le_premier_salon_autorise():
    interdit, ouvert = _Salon("a", 0, False), _Salon("b", 1, True)
    url = asyncio.run(osm.creer_invitation(_guild([interdit, ouvert])))
    assert url == "https://discord.gg/b"
    assert interdit.appels == []
    assert ouvert.appels[0]["max_uses"] == 1 and ouvert.appels[0]["max_age"] == 3600


def test_invitation_le_salon_systeme_passe_en_premier():
    systeme, autre = _Salon("sys", 5, True), _Salon("x", 0, True)
    assert asyncio.run(osm.creer_invitation(_guild([autre, systeme], systeme=systeme))) == "https://discord.gg/sys"


def test_invitation_repli_sur_une_invitation_existante_puis_none():
    refuse = _Salon("r", 0, True, refuse=True)
    existante = SimpleNamespace(url="https://discord.gg/old", max_uses=0, uses=4)
    assert asyncio.run(osm.creer_invitation(_guild([refuse], gerer=True, invitations=[existante]))) == "https://discord.gg/old"
    assert asyncio.run(osm.creer_invitation(_guild([_Salon("n", 0, False)]))) is None


def test_la_page_est_dans_le_dashboard_et_reservee_au_proprietaire():
    nav = (ROOT / "web/dashboard_ui/js/10_nav.js").read_text(encoding="utf-8")
    assert "['botservers', 'Serveurs du bot']" in nav
    assert "group !== 'Propriétaire' || state.developer" in nav
    page = (ROOT / "web/dashboard_ui/js/45_owner.js").read_text(encoding="utf-8")
    assert "/api/owner/guilds" in page and "/invite" in page and "/leave" in page
    boot = (ROOT / "web/dashboard_ui/js/90_boot.js").read_text(encoding="utf-8")
    assert "botservers: renderBotServers" in boot
    # L'API lit le cache Discord : elle suit le leader HA comme /api/guilds.
    from web.persistent_dashboard_sessions import _proxy_candidate_path

    assert _proxy_candidate_path("/api/owner/guilds")


def _bot(*noms):
    commandes = [
        SimpleNamespace(qualified_name=n, hidden=False, description=f"desc {n}", help=None) for n in noms
    ]
    return SimpleNamespace(walk_commands=lambda: iter(commandes))


def test_la_liste_suit_le_menu_slash_et_garde_les_desactivees(monkeypatch):
    from utils import slash_catalog

    monkeypatch.setattr(slash_catalog, "CATALOG", (
        slash_catalog.SlashEntry("ban", "ban", "Ban a member."),
        slash_catalog.SlashEntry("economy give", "give", "Give coins."),
    ))
    bot = _bot("ban", "give", "zombie", "wordreact")
    items = setup_dashboard._command_catalog(bot, ["wordreact"])
    par_nom = {i["name"]: i for i in items}
    assert par_nom["ban"]["label"] == "/ban"
    assert par_nom["give"]["label"] == "/economy give"
    assert "zombie" not in par_nom  # ancienne commande hors menu : plus affichée
    assert par_nom["wordreact"]["label"] == "+wordreact"  # désactivée : reste réactivable
    # La validation accepte toujours toute commande chargée.
    assert "zombie" in setup_dashboard._all_commands(bot)
