#!/usr/bin/env python3
"""Suggestions pendant la frappe (« / ») sur le bot booté, par de vraies interactions
d'autocomplétion (type 4) passées à l'arbre publié — exactement ce que Discord envoie.

    python3 tools/slash_suggestions_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db

    def param_of(path: str, name: str):
        parts = path.split()
        command = bot.tree.get_command(parts[0])
        for part in parts[1:]:
            command = command.get_command(part)
        return next(p for p in command.parameters if p.name == name), command

    async def suggest(path: str, name: str, typed: str) -> list[tuple[str, str]]:
        """Envoie l'interaction d'autocomplétion de Discord ; rend (nom, valeur) proposés."""
        param, command = param_of(path, name)
        shown = param.display_name
        parts = path.split()
        focused = {"name": shown, "type": 3, "value": typed, "focused": True}
        options = [focused]
        node = command
        for part in reversed(parts[1:]):
            kind = 2 if hasattr(node, "commands") else 1
            options = [{"name": part, "type": kind, "options": options}]
            node = node.parent
        inter = h.build_interaction(bot, parts[0], options)
        inter.type = discord.InteractionType.autocomplete
        since = len(h.CALLS)
        await asyncio.wait_for(bot.tree._call(inter), 10)
        await h.settle(idle=0.1, maximum=1)
        for method, p, js in h.CALLS[since:]:
            if "/callback" in p and (js or {}).get("type") == 8:
                return [(c["name"], c["value"]) for c in js["data"]["choices"]]
        return []

    def choices_of(path: str, name: str) -> list[str]:
        param, _ = param_of(path, name)
        return [c.name for c in param.choices]

    # Choix perdus par la surface « / » et repris de la commande d'origine.
    check(choices_of("security antispam", "etat") == ["Activer", "Désactiver"],
          "/security antispam propose de nouveau « Activer / Désactiver »", str(choices_of("security antispam", "etat")))
    check(choices_of("play rps", "choix") == ["Pierre", "Feuille", "Ciseaux"],
          "/play rps propose Pierre / Feuille / Ciseaux", str(choices_of("play rps", "choix")))

    shown = await suggest("weather", "ville", "mar")
    check(("Marseille", "Marseille") in shown and ("Marrakech", "Marrakech") in shown,
          "/weather : « mar » propose Marseille, Marrakech…", str(shown[:6]))
    shown = await suggest("weather", "ville", "saint et")
    check(not shown or shown[0][1] == "saint et", "une ville absente reste possible : la saisie est gardée",
          str(shown[:3]))
    shown = await suggest("weather", "ville", "quebec")
    check(("Québec", "Québec") in shown, "les accents ne gênent pas (« quebec » → Québec)", str(shown[:3]))

    shown = await suggest("ban", "raison", "")
    check(len(shown) >= 10 and ("Spam", "Spam") in shown, "/ban : raisons courantes proposées", str(shown[:4]))
    shown = await suggest("timeout", "duree", "1")
    check(("10 minutes", "10m") in shown and ("1 heure", "1h") in shown, "/timeout : durées lisibles proposées",
          str(shown[:6]))
    shown = await suggest("moderation slowmode", "duree", "")
    check(("Désactiver le mode lent", "off") in shown and not any(v.endswith("j") for _n, v in shown),
          "/moderation slowmode : jusqu'à 6 h seulement, et « off »", str(shown[:10]))
    shown = await suggest("help", "commande", "ba")
    check(any(v == "ban" for _n, v in shown), "/help : les noms de commandes sont proposés", str(shown[:5]))

    # Suggestions tirées du serveur.
    now = int(time.time())
    await db.execute(
        "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, status, end_at) VALUES (?,?,?,?,?,?)",
        (h.GID, h.CID, 555000111, "Nitro 1 mois", "actif", now + 3600),
    )
    shown = await suggest("giveaway end", "message_id", "nit")
    check(("Nitro 1 mois · 555000111", "555000111") in shown, "/giveaway end : le giveaway en cours est proposé",
          str(shown))
    try:
        await db.execute("INSERT INTO embed_templates (guild_id, name) VALUES (?, ?)", (h.GID, "annonce-rentree"))
        shown = await suggest("embeds send", "nom", "ann")
        check(("annonce-rentree", "annonce-rentree") in shown, "/embeds send : les embeds enregistrés sont proposés",
              str(shown))
    except Exception as exc:  # schéma différent : le dire plutôt que masquer
        check(False, "/embeds send : les embeds enregistrés sont proposés", repr(exc))

    # /security rules a quitté le menu « / » ; les mots interdits gardent leur
    # retrait avec suggestions.
    automod = bot.get_cog("Automod")
    await db.execute("INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)", (h.GID, "arnaque-test"))
    automod.blacklist_words_cache.pop(h.GID, None)
    shown = await suggest("security words remove", "mot", "arn")
    check(any(value == "arnaque-test" for _, value in shown),
          "/security words remove : les mots interdits enregistrés sont proposés", str(shown))

    # Un membre qui tape ne déclenche rien d'autre qu'une liste (aucun message, aucune action).
    since = len(h.CALLS)
    await suggest("ban", "raison", "sp")
    sent = [p for m, p, _ in h.CALLS[since:] if m == "POST" and "/callback" not in p]
    check(not sent, "une suggestion n'envoie aucun message et n'exécute rien", str(sent))

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
