"""Règlement : état publié persistant et verrouillage sans refaire le setup.

Exécute le vrai garde, sans Discord Gateway ni changement de permissions réelles.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import verify_setup_interactive_v78 as rules
import sentrix_setup_v116 as setup


def _bot(panel=None, conf=None):
    db = SimpleNamespace(
        execute=AsyncMock(),
        fetchone=AsyncMock(return_value=panel),
        get_guild_config=AsyncMock(return_value=conf or {}),
        set_guild_config=AsyncMock(),
    )
    return SimpleNamespace(db=db, get_cog=lambda _name: None)


@pytest.mark.asyncio
async def test_un_reglement_non_publie_ne_permet_pas_le_verrouillage():
    bot = _bot(
        {"message_id": None, "rules_text": "Brouillon"},
        {"verify_role": 40, "verification_channel": 60},
    )
    assert await rules.published_rules_state(bot, SimpleNamespace(id=10)) is None
    with pytest.raises(ValueError, match="Publiez d'abord"):
        await rules.lock_published_channels(bot, SimpleNamespace(id=10), SimpleNamespace(id=3))
    bot.db.set_guild_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_publication_enregistree_est_reconnue_sans_nouvelle_session():
    bot = _bot(
        {"message_id": 987, "rules_text": "Respect obligatoire"},
        {"verify_role": 40, "verification_channel": 60},
    )
    assert await rules.published_rules_state(bot, SimpleNamespace(id=10)) == {
        "message_id": 987, "role_id": 40, "channel_id": 60,
    }


@pytest.mark.asyncio
async def test_publier_le_texte_sans_message_public_ne_compte_pas():
    bot = _bot(
        {"message_id": 0, "rules_text": "Des règles écrites mais non publiées"},
        {"verify_role": 40, "verification_channel": 60},
    )
    assert await rules.published_rules_state(bot, SimpleNamespace(id=10)) is None


def test_bouton_de_verrouillage_active_apres_publication():
    bot = _bot()
    guild = SimpleNamespace(id=10, get_channel=lambda _id: None, get_role=lambda _id: None)
    def view(message_id):
        return rules.VerifySetupView(
            bot, guild, 3,
            channel_id=60, role_id=40, rules_text="Règlement",
            image_url="", captcha_enabled=True, captcha_max_attempts=3,
            message_id=message_id,
        )
    before = next(x for x in view(None).children if getattr(x, "label", "") == "Verrouiller les salons derrière le règlement")
    after = next(x for x in view(987).children if getattr(x, "label", "") == "Verrouiller les salons derrière le règlement")
    assert before.disabled is True
    assert after.disabled is False


@pytest.mark.asyncio
async def test_verrouillage_valide_panneau_sauvegarde_et_utilise_moteur_securise(monkeypatch):
    class Channel:
        def __init__(self):
            self.fetch_message = AsyncMock(return_value=SimpleNamespace(id=987))
    class Role:
        pass
    monkeypatch.setattr(rules.discord, "TextChannel", Channel)
    monkeypatch.setattr(rules.discord, "Role", Role)
    channel, role = Channel(), Role()
    guild = SimpleNamespace(
        id=10, get_channel=lambda _id: channel, get_role=lambda _id: role,
    )
    manager = SimpleNamespace(
        _preflight=AsyncMock(return_value=[]),
        _ensure_table=AsyncMock(),
        _apply_auto_access=AsyncMock(return_value=(5, 3)),
    )
    bot = _bot(
        {"message_id": 987, "rules_text": "Respect obligatoire"},
        {"verify_role": 40, "verification_channel": 60},
    )
    bot.get_cog = lambda _name: manager
    actor = SimpleNamespace(id=3)
    assert await rules.lock_published_channels(bot, guild, actor) == (5, 3)
    channel.fetch_message.assert_awaited_once_with(987)
    manager._preflight.assert_awaited_once_with(
        guild, channel=channel, role=role, auto_access=True,
    )
    manager._apply_auto_access.assert_awaited_once_with(
        guild, verification_channel=channel, verified_role=role, actor=actor,
    )
    bot.db.set_guild_config.assert_awaited_once_with(10, "verification_auto_access", 1)


@pytest.mark.asyncio
async def test_permissions_insuffisantes_ne_modifient_pas_les_salons(monkeypatch):
    class Channel:
        fetch_message = AsyncMock(return_value=SimpleNamespace(id=987))
    class Role:
        pass
    monkeypatch.setattr(rules.discord, "TextChannel", Channel)
    monkeypatch.setattr(rules.discord, "Role", Role)
    channel, role = Channel(), Role()
    guild = SimpleNamespace(id=10, get_channel=lambda _id: channel, get_role=lambda _id: role)
    manager = SimpleNamespace(
        _preflight=AsyncMock(return_value=["Gérer les salons manquant"]),
        _ensure_table=AsyncMock(),
        _apply_auto_access=AsyncMock(),
    )
    bot = _bot(
        {"message_id": 987, "rules_text": "Respect obligatoire"},
        {"verify_role": 40, "verification_channel": 60},
    )
    bot.get_cog = lambda _name: manager
    with pytest.raises(ValueError, match="Verrouillage impossible"):
        await rules.lock_published_channels(bot, guild, SimpleNamespace(id=3))
    manager._apply_auto_access.assert_not_awaited()
    bot.db.set_guild_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_refuse_config_sans_reglement_publie(monkeypatch):
    monkeypatch.setattr(rules, "published_rules_state", AsyncMock(return_value=None))
    response = SimpleNamespace(send_message=AsyncMock())
    bot = _bot()
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=10),
        user=SimpleNamespace(id=3),
        response=response,
    )
    await setup._open_captcha_channel_access(SimpleNamespace(bot=bot), interaction)
    response.send_message.assert_awaited_once()
    assert "Publiez d'abord" in response.send_message.await_args.args[0]
