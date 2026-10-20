"""Contracts: compact real moderation cards and no destructive slash pruning."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest
from discord import app_commands

from cogs import moderation as moderation_module
from cogs.moderation import Moderation
from utils import sentrix_panels as panels
from utils import slash_catalog
from utils.moderation_feedback import (
    build_sanction_confirmation, build_hierarchy_refusal,
)


def _target(id_=123456789012345678):
    return SimpleNamespace(
        id=id_, mention=f"<@{id_}>", name="aide_bot",
        display_name="Aide Bot",
        display_avatar=SimpleNamespace(
            url="https://cdn.discordapp.com/avatars/123456789012345678/demo.png"
        ),
    )


def _texts(root):
    text_nodes = []
    def collect(node):
        if isinstance(node, discord.ui.TextDisplay):
            text_nodes.append(node.content)
        for child in getattr(node, "children", []):
            collect(child)
    collect(root)
    return "\n".join(text_nodes)


def test_kick_card_displays_native_discord_mention_small_id_and_reason():
    view = build_sanction_confirmation(
        action="kick",
        target=_target(),
        actor=SimpleNamespace(id=987654321012345678),
        guild_id=111111111111111111,
        reason="Spam **répété**",
        case_number=23,
    )
    assert isinstance(view, discord.ui.LayoutView)
    assert len(view.children) == 1
    card = view.children[0]
    assert isinstance(card, discord.ui.Container)
    assert any(isinstance(x, discord.ui.Section) for x in card.children)
    body = _texts(view)
    assert "Expulsion effectuée" in body
    assert "<@123456789012345678>" in body
    assert "ID : " + chr(96) + "123456789012345678" + chr(96) in body
    assert "Dossier #23" in body
    assert "**répété**" not in body  # untrusted reason escaped
    assert "Spam" in body
    row = [x for x in card.children if isinstance(x, discord.ui.ActionRow)]
    assert len(row) == 1
    assert row[0].children[0].label == "Historique"


def test_kick_card_when_case_db_fails_never_claims_case_persisted():
    view = build_sanction_confirmation(
        action="kick", target=_target(), guild_id=111111111111111111,
        reason="Spam", case_number=None,
    )
    body = _texts(view)
    assert "Expulsion effectuée" in body
    assert "Dossier non enregistré" in body
    assert "Dossier #None" not in body


def test_hierarchy_refusal_is_compact_and_actionable_without_big_banner():
    view = build_hierarchy_refusal("SentriX ne peut pas sanctionner ce membre.")
    assert isinstance(view, discord.ui.LayoutView)
    assert len(view.children) == 1
    card = view.children[0]
    assert isinstance(card, discord.ui.Container)
    content = _texts(view)
    assert "Action refusée" in content
    assert "Paramètres du serveur" in content
    assert "Aucune sanction appliquée" in content
    assert len(card.children) <= 4
    assert build_hierarchy_refusal("Raison invalide") is None


@pytest.mark.asyncio
async def test_moderation_shared_confirmation_uses_one_native_panel_and_no_ping():
    cog = Moderation.__new__(Moderation)
    context = SimpleNamespace(
        guild=SimpleNamespace(id=111111111111111111),
        author=SimpleNamespace(id=987654321012345678),
    )
    with patch.object(panels, "envoyer", AsyncMock()) as send:
        await cog._confirm_sanction(
            context, "kick", _target(), "Spam", 48,
        )
    assert send.await_count == 1
    assert isinstance(send.await_args.args[1], discord.ui.LayoutView)
    # envoyer applies AllowedMentions.none when actually sending the view.


@pytest.mark.asyncio
async def test_moderation_refusal_uses_new_view_instead_of_legacy_full_panel():
    cog = Moderation.__new__(Moderation)
    ctx = SimpleNamespace()
    with patch.object(panels, "envoyer", AsyncMock()) as send, patch.object(
        panels, "texte_court", AsyncMock()
    ) as short:
        await cog._reply(ctx, "SentriX ne peut pas sanctionner ce membre.", ephemere=True)
    send.assert_awaited_once()
    assert send.await_args.kwargs["ephemere"] is True
    assert isinstance(send.await_args.args[1], discord.ui.LayoutView)
    short.assert_not_awaited()


class _Tree:
    def __init__(self):
        self.roots = []
    def get_commands(self, **kwargs):
        return list(self.roots)
    def remove_command(self, name, **kwargs):
        self.roots[:] = [x for x in self.roots if x.name != name]
    def add_command(self, command, **kwargs):
        self.roots.append(command)
    def walk_commands(self):
        for root in self.roots:
            yield root
            if isinstance(root, app_commands.Group):
                yield from root.walk_commands()


def test_catalog_deduplicates_only_true_aliases_same_command_object():
    original_command = object()
    other_command = object()
    entries = (
        slash_catalog.SlashEntry("ping", "ping", "Check connection"),
        slash_catalog.SlashEntry("latency", "latency", "Check connection again"),
        slash_catalog.SlashEntry("warn", "warn", "Warn a member"),
    )
    bot = SimpleNamespace(tree=_Tree())
    resolved = {"ping": original_command, "latency": original_command, "warn": other_command}

    async def callback(interaction: discord.Interaction):
        return None

    async def other_callback(interaction: discord.Interaction):
        return None

    def build(_bot, entry, _index):
        return app_commands.Command(
            name=entry.path, description=entry.description,
            callback=callback if entry.source != "warn" else other_callback,
        )

    with patch.object(slash_catalog, "CATALOG", entries), patch.object(
        slash_catalog, "_find_prefix", side_effect=lambda b, source: resolved[source]
    ), patch.object(slash_catalog, "_build_leaf", side_effect=build), patch.object(
        slash_catalog, "_english_options"
    ), patch("utils.slash_suggestions.enrichir"):
        report = slash_catalog.publish(bot)

    assert report["duplicate_aliases"] == [("latency", "ping")]
    assert {x.name for x in bot.tree.roots} == {"ping", "warn"}
    assert report["leaves"] == 2


def test_real_slash_catalog_does_not_duplicate_declared_source_or_path():
    source_names = [e.source for e in slash_catalog.CATALOG]
    paths = [e.path for e in slash_catalog.CATALOG]
    assert len(source_names) == len(set(source_names))
    assert len(paths) == len(set(paths))
    # Safety: these do different jobs and must never be treated as aliases.
    assert {"warn", "warnings"}.issubset(set(source_names))
    assert {"ban", "unban", "kick"}.issubset(set(source_names))
