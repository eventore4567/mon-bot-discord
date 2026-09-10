"""/clear a deux implémentations concurrentes : cogs/help_clear_fix_v80.py::_clear_v80
(logging de transcription + repli suppression unitaire pour les messages de plus
de 14 jours) et utils/sentrix_runtime.py::_patch_clear (plus simple, aucun
logging). En traçant __code__.co_filename/co_firstlineno sur un boot identique
à la production (51 extensions), le callback réellement exécutable est celui de
_patch_clear : plain_text_all_extension (une extension railway, chargée après
help_components_v78 qui installe _clear_v80) rappelle sentrix_runtime._patch_clear
en dernier, qui REMPLACE entièrement le callback (il capture l'ancien callback
dans functools.wraps() pour l'étiquette, mais ne l'appelle jamais) — la
transcription de _clear_v80 est donc du code mort en production.

discord.py's TextChannel.purge() gère déjà lui-même le repli message-par-message
pour les messages de plus de deux semaines (voir sa docstring : "will fall back
to single delete if messages are older than two weeks") : l'absence de logique
dédiée dans le gagnant n'est donc pas un bug de robustesse, seulement une
différence de fonctionnalité (pas de journal de purge) par rapport à
_clear_v80, dont le corps ne s'exécute jamais.

Ces tests verrouillent le comportement ACTUELLEMENT actif (celui de
_patch_clear), pas celui du code mort."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils import sentrix_runtime


class _FakeCommand:
    def __init__(self, callback):
        self.callback = callback
        self.params = {}


def _install(original_callback=None):
    async def default_original(cog, ctx, nombre):
        return None

    command = _FakeCommand(original_callback or default_original)
    bot = SimpleNamespace(get_command=lambda name: command if name == "clear" else None)
    sentrix_runtime._patch_clear(bot)
    return command, bot


class ClearActiveBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_defere_puis_purge_en_ephemere(self):
        command, _ = _install()
        deleted = [SimpleNamespace() for _ in range(7)]
        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: False, defer=AsyncMock())
        )
        channel = SimpleNamespace(purge=AsyncMock(return_value=deleted))
        ctx = SimpleNamespace(interaction=interaction, channel=channel, message=SimpleNamespace())

        with patch.object(sentrix_runtime.panels, "envoyer", AsyncMock()) as envoyer:
            await command.callback(SimpleNamespace(), ctx, 10)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        channel.purge.assert_awaited_once_with(limit=10)
        envoyer.assert_awaited_once()
        _dest, _panneau = envoyer.await_args.args
        self.assertTrue(envoyer.await_args.kwargs.get("ephemere"))

    async def test_slash_ne_redefere_pas_si_deja_repondu(self):
        command, _ = _install()
        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: True, defer=AsyncMock())
        )
        channel = SimpleNamespace(purge=AsyncMock(return_value=[]))
        ctx = SimpleNamespace(interaction=interaction, channel=channel, message=SimpleNamespace())

        with patch.object(sentrix_runtime.panels, "envoyer", AsyncMock()):
            await command.callback(SimpleNamespace(), ctx, 5)

        interaction.response.defer.assert_not_awaited()

    async def test_montant_est_borne_entre_1_et_100(self):
        command, _ = _install()
        channel = SimpleNamespace(purge=AsyncMock(return_value=[]))
        interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: True, defer=AsyncMock()))
        ctx = SimpleNamespace(interaction=interaction, channel=channel, message=SimpleNamespace())

        with patch.object(sentrix_runtime.panels, "envoyer", AsyncMock()):
            await command.callback(SimpleNamespace(), ctx, 9999)

        channel.purge.assert_awaited_once_with(limit=100)

    async def test_prefixe_supprime_le_message_invocateur_puis_purge(self):
        command, _ = _install()
        deleted = [SimpleNamespace() for _ in range(3)]
        message = SimpleNamespace(delete=AsyncMock())
        channel = SimpleNamespace(purge=AsyncMock(return_value=deleted))
        ctx = SimpleNamespace(interaction=None, channel=channel, message=message)

        with patch.object(sentrix_runtime.panels, "envoyer", AsyncMock()) as envoyer:
            await command.callback(SimpleNamespace(), ctx, 3)

        message.delete.assert_awaited_once()
        channel.purge.assert_awaited_once_with(limit=3)
        envoyer.assert_awaited_once()
        self.assertEqual(envoyer.await_args.args[0], channel)
        self.assertEqual(envoyer.await_args.kwargs.get("delete_after"), 4)

    async def test_prefixe_tolere_lechec_de_suppression_du_message_invocateur(self):
        import discord

        command, _ = _install()
        message = SimpleNamespace(delete=AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="x"), "x")))
        channel = SimpleNamespace(purge=AsyncMock(return_value=[]))
        ctx = SimpleNamespace(interaction=None, channel=channel, message=message)

        with patch.object(sentrix_runtime.panels, "envoyer", AsyncMock()):
            await command.callback(SimpleNamespace(), ctx, 3)

        channel.purge.assert_awaited_once()

    async def test_permission_manquante_produit_un_panneau_derreur_qui_sautodetruit(self):
        import discord

        command, _ = _install()
        message = SimpleNamespace(delete=AsyncMock())
        channel = SimpleNamespace(purge=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="x"), "x")))
        ctx = SimpleNamespace(interaction=None, channel=channel, message=message)

        with patch.object(sentrix_runtime.panels, "envoyer", AsyncMock()) as envoyer:
            await command.callback(SimpleNamespace(), ctx, 3)

        envoyer.assert_awaited_once()
        self.assertEqual(envoyer.await_args.kwargs.get("delete_after"), 6)
        panneau = envoyer.await_args.args[1]
        self.assertEqual(panneau.kind, "danger")

    async def test_est_idempotent_sur_reinstallation(self):
        command, bot = _install()
        self.assertTrue(command._sentrix_clear_fixed)
        callback_after_first = command.callback

        sentrix_runtime._patch_clear(bot)

        self.assertIs(command.callback, callback_after_first)

    async def test_absence_de_commande_clear_ne_leve_rien(self):
        bot = SimpleNamespace(get_command=lambda name: None)
        sentrix_runtime._patch_clear(bot)  # ne doit lever aucune exception


if __name__ == "__main__":
    unittest.main()
