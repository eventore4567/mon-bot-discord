"""tools/command_sweep.py : génération d'arguments depuis les signatures réelles.
Le cas historique : commands.Range[int, 1, 100] doit produire la borne haute (100),
c'est elle qui a révélé SXR-CMD-0001 sur +clear."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import discord
from discord import app_commands
from discord.ext import commands

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("command_sweep", ROOT / "tools" / "command_sweep.py")
command_sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(command_sweep)
harness = command_sweep.harness


def test_prefix_arguments_use_range_upper_bound_and_mentions():
    @commands.command(name="clear")
    async def clear(ctx, nombre: commands.Range[int, 1, 100]):
        pass

    @commands.command(name="ban")
    async def ban(ctx, membre: discord.Member, duree: str, *, raison: str = "x"):
        pass

    assert command_sweep.prefix_invocation(clear) == ("+clear 100", [])
    invocation, missing = command_sweep.prefix_invocation(ban)
    assert invocation == f"+ban <@{harness.TARGET_ID}> 10m" and missing == []


def test_prefix_attachment_is_reported_as_not_generable():
    @commands.command(name="upload")
    async def upload(ctx, fichier: discord.Attachment):
        pass

    assert command_sweep.prefix_invocation(upload) == ("+upload", ["fichier"])


def test_slash_options_follow_nesting_and_bounds():
    group = app_commands.Group(name="moderation", description="d")
    sub = app_commands.Group(name="membres", description="d", parent=group)

    @sub.command(name="mute", description="d")
    @app_commands.describe(membre="m", duree="d", nombre="n")
    async def mute(interaction, membre: discord.Member, duree: str, nombre: app_commands.Range[int, 1, 50]):
        pass

    root, options, missing = command_sweep.slash_invocation(mute)
    assert root == "moderation" and missing == []
    assert options[0]["name"] == "membres" and options[0]["type"] == 2
    leaf = options[0]["options"][0]
    assert leaf["name"] == "mute" and leaf["type"] == 1
    values = {o["name"]: o["value"] for o in leaf["options"]}
    assert values == {"membre": str(harness.TARGET_ID), "duree": "10m", "nombre": 50}


def test_skip_rules_protect_process_and_owner_commands():
    assert command_sweep._skip_reason("sync", "owner-global", [], False)
    assert command_sweep._skip_reason("sync", "owner-global", [], True)  # NEVER_RUN gagne toujours
    assert command_sweep._skip_reason("health", "owner-global", [], False)
    assert command_sweep._skip_reason("health", "owner-global", [], True) is None
    assert command_sweep._skip_reason("ban", "discord:ban_members", [], False) is None
    assert "fichier" in command_sweep._skip_reason("upload", "public", ["fichier"], False)


def test_markdown_report_lists_broken_first():
    report = {"generated_at": 0, "total": 2, "counts": {"cassee": 1, "fragile": 0, "ok": 1, "ignoree": 0},
              "results": [
                  {"transport": "prefix", "command": "clear", "invocation": "+clear 100", "status": "cassee",
                   "detail": "SXR-CMD-0001 ClientException", "response": "Erreur"},
                  {"transport": "prefix", "command": "ping", "invocation": "+ping", "status": "ok", "detail": "", "response": "ok"},
              ]}
    text = command_sweep.render_markdown(report)
    assert text.index("## Cassées") < text.index("## OK")
    assert "SXR-CMD-0001" in text and "**1 cassée(s)**" in text
