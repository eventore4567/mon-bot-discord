from __future__ import annotations

from discord.ext import commands

import sentrix_grouped_slash_fix as fix
import sentrix_v95_runtime as v95


def test_hybrid_group_child_uses_native_binding():
    async def root_callback(ctx):
        return None

    async def child_callback(ctx):
        return None

    root = commands.HybridGroup(root_callback, name="music")
    child = commands.HybridCommand(child_callback, name="join")
    root.add_command(child)

    _signature, native, option_names = v95._build_signature(child)

    assert native is True
    assert child.root_parent is root
    assert isinstance(root, commands.HybridGroup)
    assert fix._supports_direct_binding(child, option_names) is True


def test_classic_prefix_group_child_still_uses_legacy_binding():
    async def root_callback(ctx):
        return None

    async def child_callback(ctx):
        return None

    root = commands.Group(root_callback, name="root")
    child = commands.Command(child_callback, name="child")
    root.add_command(child)

    _signature, native, option_names = v95._build_signature(child)

    assert native is True
    assert fix._supports_direct_binding(child, option_names) is False
