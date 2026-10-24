"""Régressions : /setup doit montrer les logs réels, sans les activer."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import sentrix_setup_v116 as v116


def _view(rows, *, known_channels=(101,)):
    db = SimpleNamespace(fetchall=AsyncMock(return_value=rows))
    guild = SimpleNamespace(get_channel=lambda channel_id: (
        SimpleNamespace(id=channel_id) if channel_id in known_channels else None
    ))
    return SimpleNamespace(bot=SimpleNamespace(db=db), guild_id=55, _guild=lambda: guild), db


@pytest.mark.asyncio
async def test_setup_signale_les_logs_non_configures_sans_mutation():
    view, db = _view([])
    status = await v116._log_routes_summary(view)
    assert "à configurer" in status
    assert "Rien n'est activé automatiquement" in status
    db.fetchall.assert_awaited_once_with(
        "SELECT channel_id, enabled FROM log_config WHERE guild_id = ?", (55,),
    )


@pytest.mark.asyncio
async def test_setup_ne_confond_pas_configure_et_actif():
    view, _ = _view([{"channel_id": 101, "enabled": 0}])
    status = await v116._log_routes_summary(view)
    assert "désactivées" in status
    assert "avec destination activée" not in status


@pytest.mark.asyncio
async def test_setup_affiche_salon_absent_sans_inventer_des_livraisons():
    view, _ = _view([
        {"channel_id": 101, "enabled": 1},
        {"channel_id": 999, "enabled": 1},
    ])
    status = await v116._log_routes_summary(view)
    assert "2 catégorie(s)" in status
    assert "1 destination(s) introuvable(s)" in status
    assert "La réception dépend" in status


@pytest.mark.asyncio
async def test_setup_n_annonce_pas_zero_log_en_cas_erreur_db():
    view, db = _view([])
    db.fetchall.side_effect = RuntimeError("DB temporary unavailable")
    status = await v116._log_routes_summary(view)
    assert "état indisponible" in status
    assert "Aucune destination" not in status


@pytest.mark.asyncio
async def test_home_embed_affiche_etat_logs(monkeypatch):
    view, _ = _view([])
    monkeypatch.setattr(v116.v4, "_health_snapshot", AsyncMock(return_value={
        "score": 60, "security_score": 70, "essential_done": 2,
    }))
    embed = await v116._home_embed(view)
    assert "Journaux : à configurer" in embed.description
    assert "Configurer les logs" in embed.description


@pytest.mark.asyncio
async def test_home_button_opens_logs_without_writing_configuration():
    view, db = _view([])
    view.message_id = 456
    view.page = v116.v4.PAGE_HOME
    view.items = []
    view.clear_items = lambda: view.items.clear()
    view.add_item = lambda item: view.items.append(item)
    view.render_page = lambda: None
    view.persist_session = AsyncMock()
    view._refresh_message = AsyncMock()
    v116._render_home(view)
    button = next(item for item in view.items if getattr(item, "label", None) == "Configurer les logs")
    interaction = SimpleNamespace()
    await button.callback(interaction)
    assert view.page == v116.v4.PAGE_LOGS
    view.persist_session.assert_awaited_once()
    view._refresh_message.assert_awaited_once_with(interaction)
    assert not hasattr(db, "execute")
