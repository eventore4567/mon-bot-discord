"""Un audit permissions ne doit jamais ignorer une extension absente."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tools import audit_permissions as audit


@pytest.mark.asyncio
async def test_chargement_ok_ne_produit_pas_d_anomalie(capsys):
    bot = SimpleNamespace(load_extension=AsyncMock(return_value=None))
    failures = await audit._charger_extensions(bot, ["cogs.a", "cogs.b"])
    bot._sentrix_audit_load_failures = failures
    assert not failures
    assert audit.auditer_chargement(bot) == 0
    assert bot.load_extension.await_count == 2


@pytest.mark.asyncio
async def test_module_absent_fait_echouer_audit_sans_masquer_son_nom(capsys):
    async def load(ext):
        if ext == "cogs.broken":
            raise ModuleNotFoundError("secret shouldn't be printed")
        return None

    bot = SimpleNamespace(load_extension=load)
    failures = await audit._charger_extensions(bot, ["cogs.ok", "cogs.broken"])
    bot._sentrix_audit_load_failures = failures
    assert failures == {"cogs.broken": "ModuleNotFoundError"}
    assert audit.auditer_chargement(bot) == 1
    message = capsys.readouterr().out
    assert "cogs.broken" in message
    assert "secret shouldn't be printed" not in message


@pytest.mark.asyncio
async def test_timeout_de_chargement_est_signale(capsys):
    async def slow(_ext):
        import asyncio
        await asyncio.sleep(10)

    bot = SimpleNamespace(load_extension=slow)
    failures = await audit._charger_extensions(bot, ["cogs.slow"], timeout=0.001)
    bot._sentrix_audit_load_failures = failures
    assert failures == {"cogs.slow": "TimeoutError"}
    assert audit.auditer_chargement(bot) == 1


def test_aucun_etat_chargement_ne_peut_etre_interprete_comme_succes(capsys):
    assert audit.auditer_chargement(SimpleNamespace()) == 1


@pytest.mark.asyncio
async def test_chargement_dedoublonne_extensions():
    bot = SimpleNamespace(load_extension=AsyncMock())
    assert not await audit._charger_extensions(bot, ["cogs.a", "cogs.a"])
    bot.load_extension.assert_awaited_once_with("cogs.a")


def test_critical_commands_present_independent_of_total_count(capsys):
    commands = ["help", "ban", "kick", "clear", "wipe-server", "one_more_command"]
    assert audit.auditer_commandes_critiques(commands) == 0
    assert "critiques présentes" in capsys.readouterr().out


def test_critical_missing_command_must_fail_without_hardcoded_registry_size(capsys):
    commands = ["help", "ban", "kick", "clear", "harmless", "another_one"]
    assert audit.auditer_commandes_critiques(commands) == 1
    assert "COMMANDE CRITIQUE ABSENTE   wipe-server" in capsys.readouterr().out
