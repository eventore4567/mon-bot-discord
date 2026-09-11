"""docs/core-v2-audit-technical-debt.md §5 : le second passage de
permission_guard (déjà testé dans test_global_checks_cannot_grant.py) ne
couvrait pas cogs/command_hardening_v41.py::_audit_registry — l'audit
"dangerous_public"/"unknown_policy" consommé par web/health_runtime_v45.py ne
tournait qu'une fois, via finalize_runtime() au chargement de
cogs.visual_experience_v5, donc AVANT les 21 extensions tardives de
railway_boot.py. Un bug de la forme du Bug #1 (§1, une commande destructive
déclarée publique) introduit par l'une de ces extensions restait invisible à
ce diagnostic. main.py::setup_hook() rappelle désormais _audit_registry après
le boot complet, exactement comme pour permission_guard.
"""
from __future__ import annotations

import pathlib

import discord
from discord.ext import commands

import main
from cogs import command_hardening_v41

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _make_fake_bot() -> commands.Bot:
    class FakeBot(commands.Bot):
        pass

    # Truque _runtime_main(bot) (sys.modules.get(bot.__class__.__module__)) pour
    # qu'il resolve vers le vrai module main deja importe, sans avoir a booter un
    # BotAllInOne complet (connexion DB, 51 extensions...).
    FakeBot.__module__ = "main"
    return FakeBot(command_prefix="+", intents=discord.Intents.none())


def test_main_py_fait_un_second_passage_de_laudit_v41_apres_boot_complet():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert (
        "from cogs.command_hardening_v41 import _audit_registry as _audit_command_registry_v41"
        in source
    )
    assert "_audit_command_registry_v41(self)" in source


def test_le_second_audit_detecte_une_commande_destructive_rendue_publique_tardivement():
    """dangerous_public = _DESTRUCTIVE_ROOTS & main.PUBLIC_COMMANDS : une simple
    intersection de listes de politique, independante de bot.walk_commands().
    Le risque reel (railway_boot.py et ~6 autres fichiers mutent
    main.PUBLIC_COMMANDS/OWNER_ONLY_COMMANDS en place, voir §16) est donc qu'une
    extension tardive elargisse PUBLIC_COMMANDS APRES le premier passage -- pas
    qu'elle enregistre une commande sur le bot."""
    bot = _make_fake_bot()
    destructive_root = next(iter(command_hardening_v41._DESTRUCTIVE_ROOTS))
    original_public = main.PUBLIC_COMMANDS
    try:
        assert destructive_root not in original_public

        # Premier passage (simule finalize_runtime(), avant les extensions
        # tardives de railway_boot.py) : la politique n'est pas encore alteree.
        command_hardening_v41._audit_registry(bot)
        assert destructive_root not in bot._sentrix_command_audit["dangerous_public"]

        # Une extension tardive mute main.PUBLIC_COMMANDS en place (motif reel
        # trouve dans cogs/sentrix_v2.py, cogs/v17_shared.py, etc.).
        main.PUBLIC_COMMANDS = original_public | {destructive_root}

        # Second passage (main.py::setup_hook, apres les 51 extensions) : doit
        # desormais la detecter.
        command_hardening_v41._audit_registry(bot)
        assert destructive_root in bot._sentrix_command_audit["dangerous_public"]
    finally:
        main.PUBLIC_COMMANDS = original_public


def test_le_second_audit_detecte_une_commande_enregistree_tardivement_et_non_classee():
    """unknown_policy depend, lui, reellement de bot.walk_commands() : une
    commande ajoutee par une extension tardive de railway_boot.py et absente de
    main.KNOWN_PERMISSION_COMMANDS n'etait detectee par aucun passage avant ce
    correctif, puisque le seul appel existant tournait avant son chargement."""
    bot = _make_fake_bot()
    late_root = "sentrix-audit-test-commande-inconnue"
    assert late_root not in main.KNOWN_PERMISSION_COMMANDS

    # Premier passage : la commande n'est pas encore enregistree sur le bot.
    command_hardening_v41._audit_registry(bot)
    assert late_root not in bot._sentrix_command_audit["unknown_policy"]

    # Une extension tardive (railway_boot.py) enregistre la commande.
    @bot.command(name=late_root)
    async def _late_unknown_command(ctx):
        raise AssertionError("jamais invoquee dans ce test")

    # Second passage : doit desormais la detecter comme non classee.
    command_hardening_v41._audit_registry(bot)
    assert late_root in bot._sentrix_command_audit["unknown_policy"]


def test_le_second_audit_ne_mute_aucune_commande():
    """_audit_registry ne fait que lire le registre et journaliser un rapport :
    contrairement a permission_guard, un second appel ne doit modifier aucun
    check ni aucune commande existante."""
    bot = _make_fake_bot()

    @bot.command(name="massrole")
    async def _massrole(ctx):
        raise AssertionError("jamais invoquee dans ce test")

    checks_before = list(_massrole.checks)
    command_hardening_v41._audit_registry(bot)
    command_hardening_v41._audit_registry(bot)
    assert list(_massrole.checks) == checks_before
