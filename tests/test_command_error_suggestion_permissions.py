from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

from discord.ext import commands

from cogs import command_response_guard, error_experience_v3


def run(coro):
    return asyncio.run(coro)


def _texte_du_panneau(panneau) -> str:
    """Tout le texte affiché par un Panneau, composants compris."""
    morceaux: list[str] = []

    def parcourir(noeud):
        contenu = getattr(noeud, "content", None)
        if isinstance(contenu, str) and contenu.strip():
            morceaux.append(contenu)
        enfants = list(getattr(noeud, "children", []) or [])
        enfants += list(getattr(noeud, "items", []) or [])
        for enfant in enfants:
            parcourir(enfant)

    for enfant in getattr(panneau, "children", []) or []:
        parcourir(enfant)
    return "\n".join(morceaux)


def test_unknown_command_handler_uses_permission_filtered_suggestions(monkeypatch):
    """Ce que ce test protège vraiment : les suggestions sont filtrées par les
    permissions du membre, et le nom suggéré arrive bien dans le message.

    Il épinglait auparavant le TRANSPORT — un appel exact à ``_send_plain``
    avec ``delete_after=8``. Deux problèmes : il était rouge depuis longtemps
    (le code passait 5, pas 8), et il interdisait de changer l'apparence du
    message sans le casser. Or c'est exactement ce qui a changé le 29/09/2026 :
    une commande introuvable rend maintenant un panneau avec sa bannière,
    comme la branche « argument manquant » juste à côté, au lieu d'une ligne de
    texte nu. Le filtrage par permissions, lui, n'a pas bougé — et c'est lui
    qui compte, parce qu'il évite de suggérer à un membre une commande qu'il
    n'a pas le droit d'utiliser.
    """
    bot = object()
    ctx = SimpleNamespace(
        command=None,
        invoked_with="kik",
        clean_prefix="+",
        author=SimpleNamespace(id=123),
    )
    filtered = Mock(return_value=["kick"])
    envoye = AsyncMock()

    monkeypatch.setattr(error_experience_v3, "_can_reply_unknown", lambda *_args: True)
    monkeypatch.setattr(error_experience_v3, "_command_suggestions", filtered)
    monkeypatch.setattr(error_experience_v3.panels, "envoyer", envoye)

    handled = run(
        error_experience_v3._handle_user_error(
            bot,
            ctx,
            commands.CommandNotFound("kik"),
        )
    )

    assert handled is True
    filtered.assert_called_once_with(bot, ctx, "kik")
    envoye.assert_awaited_once()

    # La suggestion filtrée doit apparaître dans ce qui part RÉELLEMENT. Un
    # Panneau est une vue : son texte vit dans ses composants, pas dans un
    # attribut. On le lit donc là où il est, ce qui vérifie du même coup que le
    # message n'est pas parti vide.
    panneau = envoye.await_args.args[1]
    assert "+kick" in _texte_du_panneau(panneau)

    # Et la faute de frappe s'efface toute seule : elle n'a pas à encombrer le
    # salon comme une vraie erreur.
    assert envoye.await_args.kwargs.get("delete_after") == 5


def test_command_suggestions_hide_commands_without_required_permission(monkeypatch):
    fake_main = ModuleType("main")
    fake_main.PUBLIC_COMMANDS = {"help"}
    fake_main.OWNER_ONLY_COMMANDS = {"eval"}
    fake_main.DISCORD_PERMISSION_COMMANDS = {"kick": "kick_members"}
    fake_main.CATEGORY_COMMANDS = {}
    monkeypatch.setitem(sys.modules, "main", fake_main)

    def command(name: str):
        return SimpleNamespace(
            name=name,
            qualified_name=name,
            aliases=(),
            parent=None,
            root_parent=None,
            hidden=False,
            enabled=True,
        )

    bot = SimpleNamespace(walk_commands=lambda: [command("help"), command("kick"), command("eval")])

    no_staff_perms = SimpleNamespace(
        administrator=False,
        manage_guild=False,
        kick_members=False,
    )
    ctx = SimpleNamespace(author=SimpleNamespace(guild_permissions=no_staff_perms))
    assert "kick" not in command_response_guard._command_suggestions(bot, ctx, "kik")
    assert "eval" not in command_response_guard._command_suggestions(bot, ctx, "evl")

    kick_perms = SimpleNamespace(
        administrator=False,
        manage_guild=False,
        kick_members=True,
    )
    ctx = SimpleNamespace(author=SimpleNamespace(guild_permissions=kick_perms))
    assert command_response_guard._command_suggestions(bot, ctx, "kik") == ["kick"]
