#!/usr/bin/env python3
"""`/classement` sur le bot démarré : les cinq classements, et le menu.

1. serveur vide : chaque catégorie le dit, sans planter ;
2. avec des données : le bon ordre, le bon format (heures en vocal, pièces en
   économie), et le rang de celui qui a lancé la commande ;
3. le menu passe d'une catégorie à l'autre sans relancer la commande ;
4. les bots ne sont pas classés.

    python3 tools/classements_e2e.py
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
from setup_sweep import interaction, walk  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "FAIL ") + label)


def texts(view) -> str:
    return "\n".join(str(getattr(i, "content", "")) for t in view.children for i in walk(t)
                     if isinstance(i, discord.ui.TextDisplay))


def menu_of(view) -> discord.ui.Select:
    for t in view.children:
        for i in walk(t):
            if isinstance(i, discord.ui.Select):
                return i
    raise AssertionError("menu des classements introuvable")


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import classements as cog
    from utils import classements as lb

    vide = await cog.construire(bot, guild, h.AUTHOR_ID, "vocal")
    check("aucune donnée" in texts(vide), "serveur vide : le classement le dit au lieu de planter")
    check(len(menu_of(vide).options) == len(lb.CATEGORIES) == 5,
          "le menu propose les cinq classements")

    autre, bot_id = h.TARGET_ID, 900000000000000001
    await bot.db.execute("INSERT OR REPLACE INTO voice_totals(guild_id,user_id,seconds) VALUES(?,?,?)",
                         (h.GID, autre, 7200))
    await bot.db.execute("INSERT OR REPLACE INTO voice_totals(guild_id,user_id,seconds) VALUES(?,?,?)",
                         (h.GID, h.AUTHOR_ID, 1800))
    await bot.db.execute("INSERT OR REPLACE INTO message_counts(guild_id,user_id,count) VALUES(?,?,?)",
                         (h.GID, h.AUTHOR_ID, 4200))
    await bot.db.ensure_guild(h.GID)
    await bot.db.execute("INSERT OR REPLACE INTO economy(guild_id,user_id,cash,bank) VALUES(?,?,?,?)",
                         (h.GID, h.AUTHOR_ID, 1500, 500))

    vocal = await cog.construire(bot, guild, h.AUTHOR_ID, "vocal")
    texte = texts(vocal)
    print(texte)
    check(f"<@{autre}>" in texte and "2h" in texte, "vocal : le temps est en heures, pas en secondes")
    check(texte.index(f"<@{autre}>") < texte.index(f"<@{h.AUTHOR_ID}>"), "vocal : le plus actif est premier")
    check("**#2** sur 2" in texte, "vocal : le rang de celui qui demande est affiché")

    messages = texts(await cog.construire(bot, guild, h.AUTHOR_ID, "messages"))
    check("4 200 messages" in messages or "4200 messages" in messages,
          f"messages : nombre lisible ({[l for l in messages.splitlines() if 'messages' in l][:1]})")
    economie = texts(await cog.construire(bot, guild, h.AUTHOR_ID, "economie"))
    check("2 000 pièces" in economie or "2000 pièces" in economie,
          "économie : cash + banque additionnés")

    # Un bot ne doit pas occuper le podium.
    await bot.db.execute("INSERT OR REPLACE INTO voice_totals(guild_id,user_id,seconds) VALUES(?,?,?)",
                         (h.GID, bot_id, 999999))
    lignes = lb.sans_les_bots(guild, await lb.lire(bot, h.GID, "vocal"))
    check(all(uid != bot_id for uid, _v in lignes) or guild.get_member(bot_id) is None,
          "les bots connus ne sont pas classés")

    # Le menu change de catégorie sans relancer la commande.
    # interaction() parle au nom de h.ADMIN_ID : c'est donc lui l'auteur ici.
    vue = await cog.construire(bot, guild, h.ADMIN_ID, "vocal")
    select = menu_of(vue)
    select._values = ["messages"]
    since = len(h.CALLS)
    await select.callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    edite = [p for m, p, _j in h.CALLS[since:] if m == "PATCH"]
    check(bool(edite), f"le menu modifie le message existant ({len(edite)} édition(s))")

    # Le menu d'un autre membre ne change pas SON classement : il est invité à
    # lancer la commande, sans toucher au message affiché.
    vue = await cog.construire(bot, guild, h.AUTHOR_ID, "vocal")
    select = menu_of(vue)
    select._values = ["messages"]
    since = len(h.CALLS)
    await select.callback(interaction(bot))
    await h.settle(idle=0.3, maximum=3)
    reponses = [j for m, p, j in h.CALLS[since:] if m == "POST"]
    check(not [p for m, p, _j in h.CALLS[since:] if m == "PATCH"] and bool(reponses),
          "le menu d'un autre membre ne modifie pas le classement affiché")

    echecs = [label for ok, label in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(echecs)}/{len(RESULTS)} étapes réussies.")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    code = asyncio.run(main())
    sys.stdout.flush()
    os._exit(code)
