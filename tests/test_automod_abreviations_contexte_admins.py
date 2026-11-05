"""06/11/2026 : abréviations d'insultes, contexte par l'IA, marge des admins."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import automod as am  # noqa: E402
from utils.moderation_dataset import MultilingualModerationDataset  # noqa: E402

DATASET = MultilingualModerationDataset()


@pytest.mark.parametrize("texte", [
    "ntm", "NTMMMM", "ntr", "fdp", "tg", "ftg", "vtff", "bztmr", "jtbz", "ntgm",
    "t'es un fdp", "bz ta mère", "nique tes morts",
])
def test_les_abreviations_courantes_sont_reconnues(texte):
    assert DATASET.match(texte) is not None, texte


@pytest.mark.parametrize("texte", [
    "explique à ta grand-mère", "j'ai vu ta mère au marché", "nsm ce jeu",
    "ptn j'ai perdu", "tqt", "salut tout le monde",
])
def test_les_phrases_anodines_passent(texte):
    assert DATASET.match(texte) is None, texte


def _cog_avec_ia(reponse):
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=1))
    return cog


def _message(texte="je te baise au foot mdr"):
    class Salon:
        id = 3

        def history(self, **_):
            async def gen():
                if False:
                    yield None
            return gen()

    return SimpleNamespace(
        id=9, content=texte, guild=SimpleNamespace(id=2), channel=Salon(),
        author=SimpleNamespace(id=5, display_name="tomioka"), reference=None,
    )


@pytest.mark.parametrize("verdict,attendu", [("ANODIN", False), ("OFFENSANT", True), ("???", None)])
def test_l_ia_juge_le_contexte(monkeypatch, verdict, attendu):
    from utils import ai_service

    generate = AsyncMock(return_value=SimpleNamespace(ok=True, text=verdict))
    monkeypatch.setattr(ai_service, "generate", generate)
    cog = _cog_avec_ia(verdict)
    assert asyncio.run(cog._insulte_selon_contexte(_message())) is attendu
    assert generate.await_args.kwargs["command"] == "sentrix-moderation-contexte"


def test_sans_ia_l_analyse_locale_reste_l_arbitre(monkeypatch):
    from utils import ai_service

    monkeypatch.setattr(ai_service, "generate", AsyncMock(side_effect=RuntimeError("quota")))
    assert asyncio.run(_cog_avec_ia("")._insulte_selon_contexte(_message())) is None


def _admin_cog():
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=1))
    cog._repondre_abus_privilegie = AsyncMock()
    cog._canonical_security_filter = am.AutoMod._canonical_security_filter
    return cog


def _admin_message(n, supprimes):
    async def delete():
        supprimes.append(n)
    return SimpleNamespace(
        id=n, guild=SimpleNamespace(id=2), author=SimpleNamespace(id=7, mention="<@7>"),
        channel=SimpleNamespace(id=3), delete=delete,
    )


def test_un_lien_d_arnaque_d_un_admin_est_sanctionne_tout_de_suite(monkeypatch):
    monkeypatch.setattr(am, "_as_member", lambda m, g: am.discord.Member.__new__(am.discord.Member))
    cog, supprimes = _admin_cog(), []
    asyncio.run(cog._incident_admin(_admin_message(1, supprimes), "arnaque", "antiscam"))
    assert supprimes == [1]
    cog._repondre_abus_privilegie.assert_awaited_once()


def test_pub_d_invitations_d_un_admin_toleree_puis_sanctionnee(monkeypatch):
    monkeypatch.setattr(am, "_as_member", lambda m, g: am.discord.Member.__new__(am.discord.Member))
    cog, supprimes = _admin_cog(), []

    async def scenario():
        for n in (1, 2):
            await cog._incident_admin(_admin_message(n, supprimes), "invitation", "antiinvite")
        assert supprimes == [] and cog._repondre_abus_privilegie.await_count == 0
        await cog._incident_admin(_admin_message(3, supprimes), "invitation", "antiinvite")

    asyncio.run(scenario())
    assert supprimes == [3]
    cog._repondre_abus_privilegie.assert_awaited_once()


def test_spam_d_un_admin_une_rafale_compte_une_fois(monkeypatch):
    monkeypatch.setattr(am, "_as_member", lambda m, g: am.discord.Member.__new__(am.discord.Member))
    monkeypatch.setattr(am.panels, "texte_court", AsyncMock())
    cog, supprimes = _admin_cog(), []

    async def scenario():
        for n in range(1, 11):   # 10 messages dans la même rafale
            await cog._incident_admin(_admin_message(n, supprimes), "spam", "antispam")

    asyncio.run(scenario())
    assert len(supprimes) == 10                       # tous supprimés
    cog._repondre_abus_privilegie.assert_not_awaited()  # mais 1 seul incident
    assert am.ADMIN_SEUILS == {"antiscam": 1, "spam": 3, "antiinvite": 3}
