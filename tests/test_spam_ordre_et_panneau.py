"""Spam continu : sanctionner d'abord, afficher quand c'est calme (22/11/2026).

« Quand on spam en continu, SentriX supprime et met son truc pendant qu'il
spamme encore, et ça fait tout bugger : le panel se sup, les mess se sup
bizarrement. Il commence par le plus dangereux, et dès qu'il a le temps il fait
les autres, ou bien 2 actions en même temps, puis quand il est sûr d'avoir
empêché un spam il met son truc. »

Deux causes distinctes derrière ce désordre, et les deux sont ici.
"""
from __future__ import annotations

import asyncio
import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs.automod import AutoMod  # noqa: E402

SOURCE = io.open("cogs/automod.py", encoding="utf-8").read()


def test_la_sanction_est_calculee_avant_les_ecritures_en_base():
    """Le défaut : trois allers-retours en base avant que le mute tombe.

    ``_spam_progressive_action`` vivait tout en bas, après la trace d'incident,
    après ``log_automod_action`` et après ``add_risk_signal``. Pendant ces trois
    requêtes le spammeur continue, et chaque message relance une suppression.
    """
    corps = SOURCE.split("async def _delete_and_warn", 1)[1].split("\n    def ", 1)[0]
    sanction = corps.index("spam_sanction = await self._spam_progressive_action")
    for apres in ("await self._record_incident_trace",
                  "await self.bot.db.log_automod_action",
                  "await self.add_risk_signal"):
        assert sanction < corps.index(apres), f"la sanction passe après {apres}"


def test_la_sanction_n_est_appliquee_qu_une_fois():
    """Hisser l'appel sans retirer l'ancien aurait sanctionné deux fois."""
    corps = SOURCE.split("async def _delete_and_warn", 1)[1].split("\n    def ", 1)[0]
    assert corps.count("self._spam_progressive_action(") == 1


def test_la_suppression_tourne_en_parallele_de_la_sanction():
    """« Ou bien 2 actions en même temps. »

    La suppression est lancée en future plus haut et n'est attendue
    (``finish_deletion``) qu'APRÈS la sanction : les deux se recouvrent au lieu
    de s'enchaîner.
    """
    corps = SOURCE.split("async def _delete_and_warn", 1)[1].split("\n    def ", 1)[0]
    lancement = corps.index("deletion = asyncio.ensure_future(")
    sanction = corps.index("spam_sanction = await self._spam_progressive_action")
    attente = corps.index("await finish_deletion()\n        if deletion.done()")
    assert lancement < sanction < attente


def test_plus_d_echeance_fixe_sur_un_avertissement_de_spam():
    """Six secondes fixes tombaient au milieu de la rafale.

    C'est la cause du « panel se sup » : l'avertissement disparaissait sous les
    yeux du staff pendant que les suppressions continuaient.
    """
    corps = SOURCE.split("async def _delete_and_warn", 1)[1].split("\n    def ", 1)[0]
    # Le bloc des AVERTISSEMENTS, pas celui du calcul de la sanction : les deux
    # commencent par le même « elif filter_name in SPAM_FILTERS ».
    bloc_spam = corps.split("# Pas d'échéance fixe", 1)[1][:400]
    assert "supprimer_apres" not in bloc_spam
    assert "_programmer_retrait_calme(envoi)" in bloc_spam
    # Et l'avertissement groupé suit la même règle.
    groupe = SOURCE.split("async def _send_grouped_spam_notice", 1)[1][:1400]
    assert "supprimer_apres" not in groupe
    assert "_programmer_retrait_calme(envoi)" in groupe


def _cog():
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2))
    return cog


@pytest.mark.asyncio
async def test_l_avertissement_reste_tant_que_le_salon_spamme(monkeypatch):
    """Il ne part qu'après le silence, pas après un compte à rebours."""
    import cogs.automod as mod

    monkeypatch.setattr(mod, "SPAM_NOTICE_CALME_SECONDES", 0.20)
    monkeypatch.setattr(mod, "SPAM_NOTICE_VIE_MAX_SECONDES", 5.0)
    cog = _cog()
    envoi = SimpleNamespace(channel=SimpleNamespace(id=7), delete=AsyncMock())

    cog._noter_bruit_spam(7)
    tache = asyncio.ensure_future(cog._retirer_quand_calme(envoi))

    # Le spam continue : on repousse le silence trois fois de suite.
    for _ in range(3):
        await asyncio.sleep(0.12)
        cog._noter_bruit_spam(7)
        assert not tache.done(), "l'avertissement est parti pendant la rafale"

    await tache
    envoi.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_spam_qui_ne_s_arrete_jamais_ne_bloque_pas_l_avertissement(monkeypatch):
    """Sans plafond, un flux continu laisserait l'avertissement à vie."""
    import cogs.automod as mod

    monkeypatch.setattr(mod, "SPAM_NOTICE_CALME_SECONDES", 10.0)
    monkeypatch.setattr(mod, "SPAM_NOTICE_VIE_MAX_SECONDES", 0.25)
    cog = _cog()
    envoi = SimpleNamespace(channel=SimpleNamespace(id=7), delete=AsyncMock())

    async def bruit_sans_fin():
        for _ in range(20):
            cog._noter_bruit_spam(7)
            await asyncio.sleep(0.03)

    souffleur = asyncio.ensure_future(bruit_sans_fin())
    await asyncio.wait_for(cog._retirer_quand_calme(envoi), timeout=3)
    souffleur.cancel()
    envoi.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_avertissement_deja_supprime_ne_leve_pas(monkeypatch):
    """Le staff a pu le retirer à la main entre-temps."""
    import cogs.automod as mod

    monkeypatch.setattr(mod, "SPAM_NOTICE_CALME_SECONDES", 0.0)
    cog = _cog()
    envoi = SimpleNamespace(
        channel=SimpleNamespace(id=7),
        delete=AsyncMock(side_effect=RuntimeError("déjà supprimé")),
    )
    await cog._retirer_quand_calme(envoi)  # ne doit pas lever


@pytest.mark.asyncio
async def test_sans_envoi_il_n_y_a_rien_a_retirer():
    """``texte_court`` peut ne rien rendre (salon restreint, repli)."""
    await _cog()._retirer_quand_calme(None)


def test_chaque_suppression_de_spam_repousse_le_retrait():
    corps = SOURCE.split("async def _delete_and_warn", 1)[1].split("\n    def ", 1)[0]
    assert "self._noter_bruit_spam(message.channel.id)" in corps
