from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

import sentrix_grouped_slash_fix as fix
import sentrix_v95_runtime as v95


def test_keyword_only_text_is_forwarded_as_keyword_argument():
    async def callback(ctx, langue: str, *, texte: str):
        return None

    command = commands.Command(callback, name="ai-translate")
    _signature, native, option_names = v95._build_signature(command)

    assert native is True
    assert fix._supports_direct_binding(command, option_names) is True

    ctx = object()
    args, kwargs = asyncio.run(
        fix._bind_native_arguments(
            command,
            ctx,
            option_names,
            {"langue": "anglais", "texte": "bonjour tout le monde"},
        )
    )

    assert args == [ctx, "anglais"]
    assert kwargs == {"texte": "bonjour tout le monde"}


def test_ai_question_keeps_spaces_without_stringview_reparse():
    async def callback(ctx, *, question: str):
        return None

    command = commands.Command(callback, name="ai")
    _signature, native, option_names = v95._build_signature(command)
    question = "explique moi ce texte sans perdre les espaces"

    assert native is True
    args, kwargs = asyncio.run(
        fix._bind_native_arguments(command, object(), option_names, {"question": question})
    )

    assert len(args) == 1
    assert kwargs["question"] == question


def test_native_discord_object_is_not_serialized_back_to_text():
    async def callback(ctx, *, fichier: discord.Attachment):
        return None

    command = commands.Command(callback, name="upload")
    _signature, native, option_names = v95._build_signature(command)
    attachment_marker = object()

    assert native is True
    _args, kwargs = asyncio.run(
        fix._bind_native_arguments(
            command,
            object(),
            option_names,
            {"fichier": attachment_marker},
        )
    )

    assert kwargs["fichier"] is attachment_marker


def test_optional_gap_uses_original_default_instead_of_rejecting_next_option():
    async def callback(ctx, premier: str | None = None, second: str = "défaut"):
        return None

    command = commands.Command(callback, name="optional-gap")
    _signature, native, option_names = v95._build_signature(command)

    assert native is True
    args, kwargs = asyncio.run(
        fix._bind_native_arguments(
            command,
            object(),
            option_names,
            {"premier": None, "second": "fourni"},
        )
    )

    assert args[1:] == [None, "fourni"]
    assert kwargs == {}


def test_prefix_subcommand_with_early_parent_callback_keeps_legacy_path():
    async def root_callback(ctx):
        return None

    async def child_callback(ctx, *, texte: str):
        return None

    root = commands.Group(root_callback, name="root", invoke_without_command=False)
    child = commands.Command(child_callback, name="child")
    root.add_command(child)
    _signature, native, option_names = v95._build_signature(child)

    assert native is True
    assert fix._supports_direct_binding(child, option_names) is False


def test_compact_errors_are_plain_sentences():
    cooldown = commands.CommandOnCooldown(
        commands.Cooldown(1, 10.0),
        3.2,
        commands.BucketType.user,
    )

    assert fix._short_error(cooldown) == "Cette commande est en cooldown. Réessaie dans 3 s."
    assert "embed" not in fix._short_error(commands.BadArgument("bad")).casefold()


# Filet de sécurité anti-mélange de sanction (voir _sanction_callback_mismatch) : un
# rapport utilisateur a montré un dossier de sanction "Mute" journalisé pour un +unmute.
# Cause exacte non retrouvée malgré une simulation complète du boot de production ; ce
# garde-fou détecte, pour les 7 commandes de sanction, un command.callback qui ne pointe
# manifestement plus vers la fonction attendue, et bloque l'exécution plutôt que de
# risquer d'appliquer la mauvaise sanction à un membre réel.

def test_sanction_callback_mismatch_est_detecte():
    async def mute(self, ctx, membre, duree="10m", *, raison="..."):
        return None

    command = commands.Command(mute, name="unmute")  # nom de commande != nom de fonction
    message = fix._sanction_callback_mismatch(command)

    assert message is not None
    assert "unmute" in message
    assert "mute" in message


def test_sanction_callback_match_ne_declenche_rien():
    async def unmute(self, ctx, membre, *, raison="..."):
        return None

    command = commands.Command(unmute, name="unmute")

    assert fix._sanction_callback_mismatch(command) is None


def test_commandes_non_sanction_ne_sont_jamais_verifiees():
    """bot-status/system_status (et tout autre renommage légitime) ne doivent
    jamais déclencher ce garde-fou : il est volontairement limité aux 7
    commandes de sanction, où le nom de fonction est toujours fiable."""
    async def system_status(self, ctx):
        return None

    command = commands.Command(system_status, name="bot-status")

    assert fix._sanction_callback_mismatch(command) is None


def test_wrapper_avec_functools_wraps_est_vu_a_travers():
    """Les patches existants (v17_moderation_security, sentrix_v22, ...) enveloppent
    toujours le callback via functools.wraps — inspect.unwrap doit voir au travers
    jusqu'à la vraie fonction pour ne jamais déclencher de faux positif sur elles."""
    import functools

    async def unmute(self, ctx, membre, *, raison="..."):
        return None

    @functools.wraps(unmute)
    async def guarded_unmute(cog, ctx, membre, *, raison="..."):
        return await unmute(cog, ctx, membre, raison=raison)

    command = commands.Command(guarded_unmute, name="unmute")

    assert fix._sanction_callback_mismatch(command) is None


def test_invoke_native_refuse_d_executer_sur_mismatch():
    async def mute(self, ctx, membre, duree="10m", *, raison="..."):
        raise AssertionError("ne doit jamais être appelé : le garde-fou doit bloquer avant")

    command = commands.Command(mute, name="unmute")

    async def run():
        ctx = object()
        await fix._invoke_native(object(), command, ctx, ("membre", "raison"), {})

    try:
        asyncio.run(run())
    except commands.CommandError as exc:
        assert "unmute" in str(exc) and "mute" in str(exc)
    else:
        raise AssertionError("_invoke_native aurait dû lever CommandError")


# Diagnostic ajouté à CHAQUE invocation d'une commande de sanction (voir
# _sanction_diagnostic_snapshot), pas seulement quand _sanction_callback_mismatch()
# détecte un désaccord — pour qu'une reproduction réelle du mélange mute/unmute
# laisse une trace exploitable même si le nom déclaré concorde.

def test_diagnostic_snapshot_est_produit_pour_une_commande_de_sanction():
    async def unmute(self, ctx, membre, *, raison="..."):
        return None

    command = commands.Command(unmute, name="unmute")
    membre = object()
    snapshot = fix._sanction_diagnostic_snapshot(command, ("membre", "raison"), {"membre": membre, "raison": "x"})

    assert snapshot is not None
    assert "command=unmute" in snapshot
    assert "declared_name=unmute" in snapshot
    assert "a_duree=False" in snapshot


def test_diagnostic_snapshot_signale_la_presence_de_duree():
    async def mute(self, ctx, membre, duree="10m", *, raison="..."):
        return None

    command = commands.Command(mute, name="mute")
    snapshot = fix._sanction_diagnostic_snapshot(command, ("membre", "duree", "raison"), {"duree": "1h"})

    assert "a_duree=True" in snapshot


def test_diagnostic_snapshot_absent_pour_une_commande_non_sanction():
    async def system_status(self, ctx):
        return None

    command = commands.Command(system_status, name="bot-status")

    assert fix._sanction_diagnostic_snapshot(command, (), {}) is None


def test_diagnostic_snapshot_inclut_le_fichier_et_la_ligne_du_code_reel():
    async def unmute(self, ctx, membre, *, raison="..."):
        return None

    command = commands.Command(unmute, name="unmute")
    snapshot = fix._sanction_diagnostic_snapshot(command, ("membre", "raison"), {})

    assert "test_grouped_slash_arguments_v99.py" in snapshot


def test_invoke_native_journalise_le_diagnostic_meme_sans_desaccord(caplog):
    async def unmute(cog, ctx, membre, *, raison="..."):
        return None

    command = commands.Command(unmute, name="unmute")

    class FakeCtx:
        command_failed = False

    class FakeBot:
        def dispatch(self, *args, **kwargs):
            pass

    async def fake_can_run(ctx):
        return False  # s'arrête juste après le diagnostic, avant le vrai appel

    command.can_run = fake_can_run

    async def run():
        import logging
        caplog.set_level(logging.INFO, logger="bot.grouped-slash-fix")
        try:
            await fix._invoke_native(FakeBot(), command, FakeCtx(), ("membre", "raison"), {"membre": object()})
        except commands.CheckFailure:
            pass

    asyncio.run(run())
    assert any("Diagnostic sanction (native)" in record.message for record in caplog.records)
