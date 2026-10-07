#!/usr/bin/env python3
"""Parcours complet de la traduction sur le bot booté comme en production.

Le fournisseur est simulé (le harnais coupe le réseau) : ce scénario vérifie ce
que SentriX contrôle — les trois portes d'entrée, la langue choisie, les
messages d'erreur, les mentions, l'autocomplétion.

    python3 tools/translation_e2e.py
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
from suggestions_e2e import RESULTS, _base, callbacks, check, persona  # noqa: E402

CALLS_PROVIDER: list[tuple[str, str, str]] = []


def fake_provider(text: str, source: str, target: str) -> str:
    CALLS_PROVIDER.append((text, source, target))
    return f"<{target}> {text}"


def down_provider(text: str, source: str, target: str) -> str:
    raise ConnectionError("network down")


async def main() -> int:
    from services import translation as tr

    tr._google = fake_provider
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    # 1 — Chargement : une seule commande, un menu contextuel.
    check(bot.get_cog("Translation") is not None, "le cog Translation est chargé")
    check(bot.get_cog("Utility") is not None, "Utility est toujours chargé (aucune collision de nom)")
    group = bot.tree.get_command("translate")
    leaf = group.get_command("text") if group is not None else None
    check(leaf is not None and leaf.callback.__module__ == "cogs.translation", "/translate text est la commande native")
    names = [p.display_name for p in leaf.parameters] if leaf else []
    check(names == ["language", "text", "source"], "options anglaises : language, text, source", str(names))
    menu = bot.tree.get_command("Translate Message", type=discord.AppCommandType.message)
    check(menu is not None, "le menu contextuel « Translate Message » est enregistré")

    # 2 — /translate text.
    since = len(h.CALLS)
    inter = h.build_interaction(bot, "translate", [{"name": "text", "type": 1, "options": [
        {"name": "language", "type": 3, "value": "es"},
        {"name": "text", "type": 3, "value": "Bonjour à tous"},
    ]}], **persona("membre"))
    await asyncio.wait_for(bot.tree._call(inter), 15)
    await h.settle(idle=0.3, maximum=2)
    shown = h.visible_text(h.CALLS[since:])
    check("<es> Bonjour à tous" in shown, "/translate text traduit vers la langue choisie", shown[:200])

    # 3 — Menu contextuel : dans la langue DE L'UTILISATEUR, en privé.
    mid = h.next_id()
    message = h.message_payload(mid, h.CID, "Salut @everyone, réunion à 20h", author_id=h.SECOND_ID, name="ami")
    p = persona("membre")
    data = _base(p["author_id"], p["author_roles"], kind=2, data={
        "id": "1", "name": "Translate Message", "type": 3, "target_id": str(mid),
        "resolved": {"messages": {str(mid): message}},
    })
    data["locale"] = "en-US"
    since = len(h.CALLS)
    await asyncio.wait_for(bot.tree._call(discord.Interaction(data=data, state=bot._connection)), 15)
    await h.settle(idle=0.3, maximum=2)
    shown = h.visible_text(h.CALLS[since:])
    check("<en> Salut @everyone" in shown, "le menu traduit dans la langue Discord de l'utilisateur (en-US)", shown[:200])
    flags = [c.get("data", {}).get("flags") for c in callbacks(since) if c.get("type") in (4, 5)]
    check(any((f or 0) & 64 for f in flags), "la traduction du menu est privée (éphémère)", str(flags))
    payloads = [c[2] for c in h.CALLS[since:] if isinstance(c[2], dict)]
    everyone = [pl for pl in payloads if "everyone" in str((pl.get("allowed_mentions") or {}).get("parse", []))]
    check(not everyone, "un @everyone traduit ne ping personne")

    # 4 — Préfixe.
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+translate de Bonne nuit", **persona("membre")), 15)
    await h.settle(idle=0.3, maximum=2)
    check("<de> Bonne nuit" in h.visible_text(h.CALLS[since:]), "+translate fonctionne en préfixe")

    # 5 — Panne du fournisseur : on le dit, sans accuser l'utilisateur.
    tr._google = down_provider
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+translate en Bonjour", **persona("membre")), 15)
    await h.settle(idle=0.3, maximum=2)
    shown = h.visible_text(h.CALLS[since:])
    check("ne répond pas" in shown and "code de langue" not in shown,
          "une panne du service est annoncée comme telle", shown[:200])
    tr._google = fake_provider

    # 6 — Autocomplétion des langues.
    p = persona("membre")
    data = _base(p["author_id"], p["author_roles"], kind=4, data={
        "id": "1", "name": "translate", "type": 1, "options": [{"name": "text", "type": 1, "options": [
            {"name": "language", "type": 3, "value": "esp", "focused": True},
        ]}],
    })
    since = len(h.CALLS)
    await asyncio.wait_for(bot.tree._call(discord.Interaction(data=data, state=bot._connection)), 15)
    await h.settle(idle=0.2, maximum=1.5)
    choices = [c for c in callbacks(since) if c.get("type") == 8]
    values = [ch["value"] for ch in (choices[0]["data"]["choices"] if choices else [])]
    check("es" in values, "l'autocomplétion propose Español pour « esp »", str(values))

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
