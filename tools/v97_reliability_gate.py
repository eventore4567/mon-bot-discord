#!/usr/bin/env python3
"""Gate V97 : vérifie les régressions que le gate V95 ne couvrait pas."""
from __future__ import annotations

import inspect
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

import sentrix_v95_bootstrap
sentrix_v95_bootstrap.install()
import sentrix_v95_runtime as v95
import sentrix_v97_reliability as v97


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def run() -> int:
    errors: list[str] = []
    v97.install_slash()

    @commands.command(name="native-ok")
    async def native_ok(ctx, member: discord.Member, reason: str = ""):
        pass

    @commands.command(name="gap")
    async def gap(ctx, member: discord.Member, duration: str = "10m", reason: str = ""):
        pass

    @commands.command(name="attachment")
    async def attachment(ctx, file: discord.Attachment, label: str = ""):
        pass

    sig_native, native_flag, native_names = v95._build_signature(native_ok)
    if native_names != ("member", "reason") or "member" not in sig_native.parameters:
        fail(f"signature native ban-like invalide: {sig_native}", errors)
    if not native_flag:
        fail("commande simple marquée non-native", errors)

    sig_gap, gap_native, gap_names = v95._build_signature(gap)
    if gap_names != ("arguments",) or gap_native:
        fail(f"optional gap non protégé: {sig_gap}", errors)
    if "ctx" in sig_gap.parameters:
        fail("ctx exposé dans une signature V97", errors)

    sig_attachment, _, attachment_names = v95._build_signature(attachment)
    if attachment_names != ("file", "label"):
        fail(f"attachment slash perdu: {sig_attachment}", errors)
    if sig_attachment.parameters["file"].annotation is not discord.Attachment:
        fail("sélecteur Attachment Discord non conservé", errors)

    # Le dashboard doit conserver le backend existant et n'ajouter qu'une couche UX tardive.
    from web import dashboard
    from sentrix_product_update import install_dashboard_prestart
    install_dashboard_prestart(dashboard)
    if not v97.install_dashboard(dashboard):
        fail("installation dashboard V97 a retourné False", errors)
    html = dashboard.INDEX_HTML
    # Les numéros sont assemblés dynamiquement dans JS (`${n}. ...`), on valide donc les
    # libellés et les marqueurs réellement présents dans la source injectée.
    for marker in (
        'id="sentrix-ticket-simple-v97-js"',
        'id="sentrix-ticket-simple-v97-css"',
        "Général",
        "Équipe",
        "Panel",
        "Publication",
        "Réglages avancés du serveur",
    ):
        if marker not in html:
            fail(f"dashboard Tickets V97 incomplet: {marker}", errors)

    # Garde statique : la couche runtime doit explicitement réinjecter les attachments et
    # remplacer le /setup historique plutôt que de laisser ctx dans Discord.
    source = inspect.getsource(v97)
    for fragment in ("ctx.message.attachments", "_replace_setup_slash", "_needs_text_fallback"):
        if fragment not in source:
            fail(f"garde runtime manquante: {fragment}", errors)

    if errors:
        for error in errors:
            print("[ERROR]", error)
        print(f"ECHEC V97: {len(errors)} problème(s)")
        return 1
    print("OK V97: slash fiables (gaps/attachments/setup) + dashboard Tickets guidé")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
