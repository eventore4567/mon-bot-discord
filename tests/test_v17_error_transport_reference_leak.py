"""docs/core-v2-audit-technical-debt.md §8 (suivi) : cogs/v17_user_facing_hotfix.py::
_apply_error_context_transport() réinjectait reference=message/mention_author=False
pour les erreurs de commandes préfixées, en CONTOURNANT cogs/reply_reference_fix.py.

Cause : son wrapper (error_send) capture `current_send = commands.Context.send` à SON
propre moment d'installation (au chargement de la toute première extension, via
cogs.stability_runtime -> cogs.bot_v17_major -> cogs.v17_user_facing_hotfix), soit bien
AVANT que reply_reference_fix.install() ne s'exécute (dans finalize_runtime(), déclenché
par la DERNIÈRE extension, cogs.visual_experience_v5). Sur le chemin d'erreur, error_send
appelait ensuite ce current_send figé (l'envoi Discord original, non filtré) avec un
reference= qu'il venait de rajouter lui-même — contournant donc entièrement le filtrage
"sans référence" de reply_reference_fix, alors que le chemin normal (succès) restait,
lui, bien protégé.

Confirmé par une exécution réelle à travers toute la chaîne (v17 installé en premier
comme en production, reply_reference_fix installé ensuite) avant correctif : le
reference= parvenait jusqu'au send() final. Après correctif, ces tests verrouillent
qu'aucune reference/mention_author ne fuite plus, sur aucun des deux chemins.
"""
from __future__ import annotations

import asyncio
import inspect

import discord
import pytest
from discord.ext import commands

import cogs.reply_reference_fix as rrf
import cogs.v17_user_facing_hotfix as v17
import main as botmain


@pytest.fixture
def clean_context_send(monkeypatch):
    """Isole chaque test de l'état global mutable que ces deux modules réaffectent
    (commands.Context.send/.reply, discord.abc.Messageable.send, discord.Message.reply,
    cogs.reply_reference_fix._INSTALLED) pour un résultat déterministe indépendant de
    l'ordre d'exécution du reste de la suite."""
    captured: dict = {}

    async def pristine_send(self, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "SENT"

    async def pristine_reply(self, *args, **kwargs):
        return await pristine_send(self, *args, **kwargs)

    monkeypatch.setattr(commands.Context, "send", pristine_send, raising=True)
    monkeypatch.setattr(commands.Context, "reply", pristine_reply, raising=True)
    monkeypatch.setattr(discord.abc.Messageable, "send", pristine_send, raising=True)
    monkeypatch.setattr(discord.Message, "reply", pristine_reply, raising=True)
    monkeypatch.setattr(rrf, "_INSTALLED", False)
    # D'autres modules de test (production_embed_log_repair*) réaffectent directement
    # main.SentriXContext.send SANS passer par monkeypatch, donc ça survit à leur test
    # pour le reste de la session pytest. On neutralise cette pollution ici, le temps du
    # test, pour un résultat indépendant de l'ordre d'exécution de la suite.
    monkeypatch.delattr(botmain.SentriXContext, "send", raising=False)
    yield captured


def _install_v17_then_reply_reference_fix() -> None:
    """Reproduit l'ordre réel de production : v17 (extension #1) avant
    reply_reference_fix (finalize_runtime, dernière extension)."""
    v17._apply_error_context_transport()
    rrf.install()


class _FakeMessage:
    id = 999

    def __init__(self):
        self.channel = None


def _make_ctx(*, private_error: bool, interaction=None, message=None):
    ctx = botmain.SentriXContext.__new__(botmain.SentriXContext)
    ctx.interaction = interaction
    ctx.message = message
    ctx.channel = getattr(message, "channel", None)
    ctx.guild = None
    ctx.command = None
    ctx._sentrix_private_error = private_error
    return ctx


def test_reponse_normale_prefixee_reste_sans_reference(clean_context_send):
    _install_v17_then_reply_reference_fix()
    ctx = _make_ctx(private_error=False, message=_FakeMessage())

    asyncio.run(ctx.send(content="ok"))

    assert "reference" not in clean_context_send["kwargs"]
    assert "mention_author" not in clean_context_send["kwargs"]


def test_erreur_prefixee_ne_fait_plus_fuiter_de_reference(clean_context_send):
    """Avant le correctif, cette assertion échouait : reference=<message> et
    mention_author=False parvenaient jusqu'à l'envoi Discord réel."""
    _install_v17_then_reply_reference_fix()
    ctx = _make_ctx(private_error=True, message=_FakeMessage())

    asyncio.run(ctx.send(content="Erreur"))

    kwargs = clean_context_send["kwargs"]
    assert "reference" not in kwargs
    assert "mention_author" not in kwargs
    assert kwargs.get("delete_after") == v17.PREFIX_ERROR_LIFETIME
    assert kwargs.get("allowed_mentions").to_dict() == discord.AllowedMentions.none().to_dict()


def test_erreur_slash_reste_ephemere_et_sans_reference(clean_context_send):
    """Garde-fou : le correctif ne doit pas toucher le chemin slash (ephemeral=True),
    qui n'a jamais utilisé reference= de toute façon."""
    _install_v17_then_reply_reference_fix()
    ctx = _make_ctx(private_error=True, interaction=object(), message=None)

    asyncio.run(ctx.send(content="Erreur"))

    kwargs = clean_context_send["kwargs"]
    assert kwargs.get("ephemeral") is True
    assert "reference" not in kwargs


def test_sentrix_context_ne_surcharge_plus_send():
    """main.py::SentriXContext ne doit plus définir son propre send() : la construction
    de reference=/mention_author=True qu'il faisait était retirée avant le vrai send()
    par reply_reference_fix.py depuis 5 semaines (voir §8) — code mort, supprimé.

    Lit le SOURCE de la classe (inspect.getsource, insensible aux monkey-patches
    d'exécution) plutôt que vars(SentriXContext) : d'autres modules de production
    (cogs/production_embed_log_repair.py) réaffectent légitimement SentriXContext.send
    au runtime, et cette réaffectation peut survivre dans le process pytest partagé
    bien après le test qui l'a déclenchée."""
    source = inspect.getsource(botmain.SentriXContext)
    assert "def send(" not in source
