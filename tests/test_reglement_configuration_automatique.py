"""Publier le règlement configure les salons tout seul, avec 10 s pour annuler.

Demande de Jayden (26/10) : plus d'aperçu ni de bouton de verrouillage. Les
nouveaux ne voient que le règlement ; une fois le rôle reçu, les salons
membres s'ouvrent, jamais ceux du staff. Une IA aide au classement mais ne
peut que fermer un salon, jamais l'ouvrir.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import verify_setup_interactive_v78 as rules  # noqa: E402
from utils import channel_profiles as cp  # noqa: E402
from utils.verification_access_intelligence import AccessPlan  # noqa: E402
from tests.test_verrouillage_salons_membres import Salon, Serveur  # noqa: E402


def _prepare(monkeypatch, *, gate=1):
    plan = AccessPlan()
    plan.gate = [SimpleNamespace(id=i, name=f"salon-{i}", type="text") for i in range(gate)]
    prepared = {"lock": plan, "release": False, "context": {}, "forced": {}, "profiles": cp.ProfilePlan()}
    monkeypatch.setattr(rules, "prepare_auto_configuration", AsyncMock(return_value=prepared))
    monkeypatch.setattr(rules, "AUTO_CONFIG_DELAY_SECONDS", 0)
    monkeypatch.setattr(rules, "log_plan_decisions", lambda *_a: None)
    run = AsyncMock(return_value="🔒 1 salon(s) réservés aux membres vérifiés.")
    monkeypatch.setattr(rules, "run_auto_configuration", run)
    return prepared, run


class _Message:
    def __init__(self):
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


def _lancer(monkeypatch, *, annuler):
    _prepared, run = _prepare(monkeypatch)
    message = _Message()
    envois = []

    async def send(**kwargs):
        envois.append(kwargs)
        return message

    interaction = SimpleNamespace(user=SimpleNamespace(id=7), followup=SimpleNamespace(send=send))

    async def scenario():
        await rules.start_auto_configuration(SimpleNamespace(), SimpleNamespace(id=1), interaction)
        vue = envois[0]["view"]
        if annuler:
            vue.cancelled = True
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    return envois, message, run


def test_sans_annulation_les_salons_sont_configures(monkeypatch):
    envois, message, run = _lancer(monkeypatch, annuler=False)
    carte = envois[0]["embed"]
    assert carte.title == "Configuration des salons"
    assert "<t:" in carte.description and "Annulez" in carte.description
    run.assert_awaited_once()
    assert message.edits[-1]["embed"].title == "Salons configurés"


def test_annuler_dans_les_10_secondes_ne_modifie_rien(monkeypatch):
    _envois, message, run = _lancer(monkeypatch, annuler=True)
    run.assert_not_awaited()
    assert message.edits == []


def test_le_bouton_annuler_existe_et_se_desactive(monkeypatch):
    async def scenario():
        vue = rules.AutoConfigCountdownView(SimpleNamespace(id=1), 7)
        bouton = next(i for i in vue.children if getattr(i, "label", "") == "Annuler")
        edits = []

        async def edit_message(**kwargs):
            edits.append(kwargs)

        await bouton.callback(SimpleNamespace(response=SimpleNamespace(edit_message=edit_message)))
        return vue, edits

    vue, edits = asyncio.run(scenario())
    assert vue.cancelled is True
    assert edits[0]["embed"].title == "Configuration annulée"


def test_l_ia_ne_peut_que_fermer_un_salon(monkeypatch):
    s = Serveur()
    plan = cp.plan_profiles(s, verified_role=s.verifie)
    incertain = s.c["general"]
    assert plan.kinds[incertain] == (cp.DISCUSSION, "salon membre")

    from utils import ai_service

    reponse = (
        '{"%d": "staff", "%d": "discussion", "%d": "ouvert", "%d": "lecture"}'
        % (incertain.id, s.c["forum"].id, s.c["news"].id, s.c["staff"].id)
    )
    monkeypatch.setattr(ai_service, "get_client", lambda: object())
    monkeypatch.setattr(ai_service, "generate", AsyncMock(return_value=SimpleNamespace(text=reponse, error=None)))
    plus_strict = asyncio.run(cp.ai_reclassify(s, plan))
    # Seul un salon incertain peut être resserré ; « discussion »/inconnu ignorés,
    # et un salon déjà classé (staff) n'est jamais soumis ni modifié.
    assert plus_strict == {incertain.id: cp.STAFF}


def test_ia_indisponible_le_classement_par_nom_s_applique(monkeypatch):
    s = Serveur()
    plan = cp.plan_profiles(s, verified_role=s.verifie)
    from utils import ai_service

    monkeypatch.setattr(ai_service, "get_client", lambda: None)
    assert asyncio.run(cp.ai_reclassify(s, plan)) == {}
    monkeypatch.setattr(ai_service, "get_client", lambda: object())
    monkeypatch.setattr(ai_service, "generate", AsyncMock(side_effect=RuntimeError("panne")))
    assert asyncio.run(cp.ai_reclassify(s, plan)) == {}


def test_le_panneau_du_reglement_a_une_banniere_et_repart_sans_si_refuse(monkeypatch):
    envois = []

    class _Salon:
        id = 10

        async def send(self, **kwargs):
            envois.append({**kwargs, "image": kwargs["embed"].image.url})
            if "file" in kwargs:
                raise discord.HTTPException(SimpleNamespace(status=400, reason="Bad"), "image refusée")
            return SimpleNamespace(id=99)

    monkeypatch.setattr(rules, "_rules_banner_file", lambda: discord.File(__file__, filename=rules._RULES_BANNER_NAME))
    guild = SimpleNamespace(id=1, get_channel=lambda _i: None)
    bot = SimpleNamespace(get_cog=lambda _n: None)
    publie = asyncio.run(rules._publish_public_panel(
        bot, guild, _Salon(), rules="Respect", image_url="",
        previous_channel_id=None, message_id=None,
    ))
    assert publie.id == 99
    assert envois[0]["image"] == f"attachment://{rules._RULES_BANNER_NAME}"
    assert "file" not in envois[1] and not envois[1]["image"]
