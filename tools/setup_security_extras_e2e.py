#!/usr/bin/env python3
"""Page Sécurité du /setup : le salon piège et la vérification ne s'activent plus
« pour rien » (signalé le 15/10/2026).

Sans système de vérification installé (salons + rôle Non vérifié), ces deux
protections s'affichaient cochées et ne faisaient rien. On vérifie, sur le bot
booté : elles ne sont ni proposées ni cochées, « Activer toutes les protections »
et « Activer la sécurité » ne les activent pas, un ancien réglage resté à 1 n'est
pas affiché comme actif, et le bouton « Installer la vérification » est présent.

    python3 tools/setup_security_extras_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from setup_sweep import build, interaction, walk  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import security_verification_v71 as v71

    async def flags() -> tuple[bool, bool]:
        cfg = await v71.settings(bot, h.GID)
        return cfg["honeypot_enabled"], cfg["verification_enabled"]

    def items(view):
        return [i for top in view.children for i in walk(top)]

    def select_of(view):
        return next(i for i in items(view) if isinstance(i, discord.ui.Select)
                    and "protections" in str(i.placeholder or ""))

    def button(view, text: str):
        return next((i for i in items(view) if isinstance(i, discord.ui.Button) and text in str(i.label or "")), None)

    def texts(view) -> str:
        return "\n".join(str(getattr(i, "content", "")) for i in items(view) if isinstance(i, discord.ui.TextDisplay))

    view = await build(bot, guild, "security")
    values = [o.value for o in select_of(view).options]
    check("honeypot" not in values and "verification" not in values,
          "sans système de vérification, le menu ne propose ni Salon piège ni Vérification", str(values))
    check("ne feraient rien" in texts(view) and button(view, "Installer la vérification") is not None,
          "la page explique pourquoi et propose « Installer la vérification »")
    check(sum(1 for _ in items(view)) <= 40, f"la page tient dans la limite Discord ({len(items(view))} composants)")

    await button(view, "Activer toutes les protections").callback(interaction(bot))
    await h.settle(idle=0.2, maximum=2)
    check(await flags() == (False, False), "« Activer toutes les protections » ne les active pas pour rien",
          str(await flags()))

    v74_view = await build(bot, guild, "security")
    await v74_view._set_security_profile(True, h.ADMIN_ID)
    check(await flags() == (False, False), "« Activer la sécurité » ne les active pas pour rien", str(await flags()))

    # Un ancien réglage resté à 1 (avant ce correctif) n'est plus affiché coché.
    await v71.update_setting(bot, h.GID, "honeypot_enabled", 1, h.ADMIN_ID)
    await v71.update_setting(bot, h.GID, "verification_enabled", 1, h.ADMIN_ID)
    view = await build(bot, guild, "security")
    defaults = [o.value for o in select_of(view).options if o.default]
    check("honeypot" not in defaults and "verification" not in defaults
          and "Salon piège" not in texts(view).split("**Actuellement :**")[-1],
          "un ancien réglage à 1 n'apparaît pas comme actif", str(defaults))

    # Système installé (ressources existantes) : les deux redeviennent proposées.
    from cogs import setup_security_choice_v75 as v75

    original = v75._honeypot_resources_ready

    async def ready(_view):
        return True

    v75._honeypot_resources_ready = ready
    try:
        view = await build(bot, guild, "security")
        values = [o.value for o in select_of(view).options]
        defaults = [o.value for o in select_of(view).options if o.default]
        check("honeypot" in values and "verification" in values and button(view, "Installer") is None,
              "système installé : les deux sont proposées, sans bouton d'installation", str(values))
        check({"honeypot", "verification"} <= set(defaults), "et leur état réel est affiché", str(defaults))
    finally:
        v75._honeypot_resources_ready = original

    # L'administrateur installe le système depuis la page : salons créés, panneaux
    # publiés, et les deux protections démarrent actives.
    await v71.update_setting(bot, h.GID, "honeypot_enabled", 0, h.ADMIN_ID)
    await v71.update_setting(bot, h.GID, "verification_enabled", 0, h.ADMIN_ID)
    view = await build(bot, guild, "security")
    since = len(h.CALLS)
    await button(view, "Installer la vérification").callback(interaction(bot))
    await h.settle(idle=0.2, maximum=3)
    shown = h.visible_text(h.CALLS[since:])
    check("Vérification installée" in shown and "Salon piège" in shown and await flags() == (True, True),
          "« Installer la vérification » crée les salons, publie les panneaux et active les deux", shown[-200:])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
