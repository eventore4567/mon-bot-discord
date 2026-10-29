#!/usr/bin/env python3
"""« Sécurité — ON » sur un serveur où aucune protection ne tourne.

27/10/2026 : ``security`` est actif par défaut (module_settings absent), mais
toutes les colonnes d'automod_settings valent 0 tant que personne n'a cliqué
« Activer la sécurité ». L'accueil du Setup affichait « Sécurité — ON » alors
qu'un spammeur n'était pas touché. On vérifie sur le bot booté :

1. serveur neuf : l'accueil dit « aucune protection active » et le spam passe ;
2. un clic sur « Sécurité » dans le menu des interrupteurs active le profil ;
3. l'accueil dit alors « Sécurité — ON » et le même spam est supprimé ;
4. couper puis rallumer garde les choix (pas de remise à zéro du profil).

    python3 tools/setup_security_honest_e2e.py
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

RESULTS: list[tuple[bool, str]] = []
SPAMMER = 990000000000000001


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "FAIL ") + label)


def switch_select(view) -> discord.ui.Select:
    for top in view.children:
        for item in walk(top):
            if isinstance(item, discord.ui.Select) and item.placeholder == "Activer / désactiver un module":
                return item
    raise AssertionError("menu des interrupteurs introuvable")


def option_label(view, key: str) -> str:
    return next(o.label for o in switch_select(view).options if o.value == key)


def texts(view) -> str:
    return "\n".join(item.content for top in view.children for item in walk(top)
                     if isinstance(item, discord.ui.TextDisplay))


async def press(bot, guild, key: str) -> None:
    view = await build(bot, guild, None)
    select = switch_select(view)
    select._values = [key]
    await select.callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)


async def spam_deleted(bot, guild, offset: int) -> int:
    """Huit messages identiques en rafale : combien sont supprimés ?"""
    since = len(h.CALLS)
    ids = []
    for n in range(8):
        message = h.build_message(bot, guild, "ACHETEZ MAINTENANT promo gratuite", author_id=SPAMMER + offset,
                                  author_name="spam", author_roles=(h.MEMBER_ROLE_ID,))
        ids.append(str(message.id))
        bot.dispatch("message", message)
        await asyncio.sleep(0.05)
    await h.settle(idle=1.0, maximum=20)
    gone = set()
    for method, path, payload in h.CALLS[since:]:
        if method == "DELETE" and "/messages/" in path:
            gone.add(path.rstrip("/").rsplit("/", 1)[-1])
        if method == "POST" and path.endswith("/bulk-delete") and isinstance(payload, dict):
            gone.update(str(m) for m in payload.get("messages", ()))
    return sum(1 for i in ids if i in gone)


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import setup_v2_core as core

    # Serveur vierge : aucune protection sans activation par un administrateur.
    await bot.db.execute("DELETE FROM module_settings WHERE guild_id=?", (h.GID,))
    await bot.db.execute("DELETE FROM automod_settings WHERE guild_id=?", (h.GID,))
    core.invalidate_module_cache(h.GID)
    bot.get_cog("Automod").automod_cache.clear()
    view = await build(bot, guild, None)
    check("aucune protection" in option_label(view, "security"),
          f"serveur neuf : « {option_label(view, 'security')} » (aucune activation implicite)")
    # Pas de ligne du tout (création paresseuse, cache V14) = aucune protection.
    row = dict(await bot.db.get_automod(h.GID) or {})
    check(not row.get("antispam") and not row.get("antiraid") and not row.get("antinuke"),
          "serveur neuf : anti-spam, anti-raid et anti-nuke à zéro en base")
    neuf = await spam_deleted(bot, guild, 5)
    check(neuf == 0, f"serveur neuf : aucun message supprimé sans choix admin ({neuf}/8)")

    zeros = ", ".join(
        f"{champ}=0"
        for champ, _label in __import__(
            "cogs.setup_control_center", fromlist=["AUTOMOD"]
        ).AUTOMOD
    )

    # Un admin qui a tout coupé à la main : l'écran le dit et le spam passe.
    await bot.db.execute(f"UPDATE automod_settings SET {zeros} WHERE guild_id=?", (h.GID,))
    bot.get_cog("Automod").automod_cache.clear()
    view = await build(bot, guild, None)
    check("aucune protection" in option_label(view, "security"),
          f"tout coupé : l'interrupteur dit « {option_label(view, 'security')} »")
    check("Aucune protection ne tourne" in texts(view), "tout coupé : l'accueil prévient qu'aucune protection ne tourne")
    avant = await spam_deleted(bot, guild, 0)
    check(avant == 0, f"tout coupé : le spam n'est effectivement pas traité ({avant}/8 supprimés) — l'écran dit vrai")

    await press(bot, guild, "security")
    bot.get_cog("Automod").automod_cache.clear()
    row = await bot.db.fetchone("SELECT antispam, antiraid, antinuke FROM automod_settings WHERE guild_id=?", (h.GID,))
    check(row is not None and row["antispam"] and row["antiraid"] and row["antinuke"],
          "un clic sur « Sécurité » active anti-spam, anti-raid et anti-nuke")
    view = await build(bot, guild, None)
    check(option_label(view, "security") == "Sécurité — Actif", f"après le clic : « {option_label(view, 'security')} »")
    check("Aucune protection ne tourne" not in texts(view), "après le clic : plus d'avertissement")
    apres = await spam_deleted(bot, guild, 1)
    check(apres >= 6, f"après le clic : le spam est supprimé ({apres}/8)")

    # Un admin qui a retiré l'anti-liens puis coupe et rallume la sécurité.
    await bot.db.set_automod(h.GID, "antilink", 0)
    await press(bot, guild, "security")
    check(not await core.module_enabled(bot, h.GID, "security"), "second clic : la sécurité est coupée")
    await press(bot, guild, "security")
    row = await bot.db.fetchone("SELECT antispam, antilink FROM automod_settings WHERE guild_id=?", (h.GID,))
    check(await core.module_enabled(bot, h.GID, "security") and row["antispam"] and not row["antilink"],
          "rallumer garde les choix de l'admin (anti-liens reste coupé)")

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} vérifications passées.")
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        import traceback

        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
