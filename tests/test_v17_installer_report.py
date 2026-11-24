"""Les échecs d'installateurs ne doivent plus se perdre dans des logs isolés."""
from types import SimpleNamespace

import pytest

from cogs import bot_v17_major as v17


@pytest.mark.asyncio
async def test_report_collecte_succes_sync_et_async():
    bot = SimpleNamespace()

    def sync_installer(_bot, _extension):
        return None

    async def async_installer(_bot, _extension):
        return None

    await v17._install_one("sync", sync_installer, bot, "cogs.test")
    await v17._install_one("async", async_installer, bot, "cogs.test")
    assert bot._sentrix_v17_install_report == {
        "sync": {"status": "ok"},
        "async": {"status": "ok"},
    }


@pytest.mark.asyncio
async def test_report_enregistre_echec_sans_exposer_les_secrets(caplog):
    bot = SimpleNamespace()
    secret = "SENSITIVE_DO_NOT_SAVE"

    async def fails(_bot, _extension):
        raise ValueError(secret)

    await v17._install_one("module test", fails, bot, "cogs.test")
    assert bot._sentrix_v17_install_report == {
        "module test": {"status": "failed", "error_type": "ValueError"},
    }
    # Le rapport consultable par les composants du bot ne révèle aucun détail d'erreur.
    assert secret not in repr(bot._sentrix_v17_install_report)


@pytest.mark.asyncio
async def test_un_installeur_en_echec_ne_masque_pas_ses_successeurs():
    bot = SimpleNamespace()

    def fails(_bot, _extension):
        raise RuntimeError("boot")

    await v17._install_one("A", fails, bot, "cogs.test")
    await v17._install_one("B", lambda *_args: None, bot, "cogs.test")
    assert bot._sentrix_v17_install_report["A"]["status"] == "failed"
    assert bot._sentrix_v17_install_report["B"]["status"] == "ok"
