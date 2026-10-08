#!/usr/bin/env python3
"""Une commande peut-elle faire sonner ce que son auteur n'a pas le droit de faire sonner ?

Le bot a « Mentionner @everyone » ; un membre ou un modérateur, souvent non.
Quand SentriX renvoie un texte saisi par quelqu'un (raison, message, titre…),
il ne doit pas lui prêter ce droit. Mesuré le 08/10/2026 : +schedule-send le
faisait, et un sticky l'aurait fait à chaque republication.

Le balayage reprend tools/command_sweep.py (mêmes arguments, préfixe ET slash)
avec deux différences :

- tout texte libre vaut « @everyone <@&Membre> » — Membre est un rôle NON
  mentionnable ;
- l'auteur est le modérateur du harnais, qui n'a pas « Mentionner @everyone ».

Pour chaque message sortant (salon, réponse d'interaction, suivi), on regarde le
texte et les composants — les embeds ne notifient jamais — et ce
qu'``allowed_mentions`` laisse sonner. Une absence d'``allowed_mentions`` fait
TOUT sonner : elle compte comme une fuite.

    python3 tools/mention_injection_sweep.py [--only mots…]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from discord import app_commands  # noqa: E402

import command_sweep as cs  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402

ROLE = h.MEMBER_ROLE_ID  # rôle NON mentionnable dans le monde du harnais
INJECTION = f"@everyone <@&{ROLE}>"
GENERIC = {"test", "test sweep", "question-test", "nom-test"}
MOD = dict(author_id=h.MOD_ID, author_roles=(h.MOD_ROLE_ID,))

_original_text_for = cs._text_for


def _text_for(name: str) -> str:
    value = _original_text_for(name)
    return INJECTION if value in GENERIC else value


cs._text_for = _text_for


def leaks(calls: list) -> list[str]:
    """Ce qui a réellement pu sonner dans ces appels HTTP."""
    found: list[str] = []
    for method, path, js in calls:
        if method not in ("POST", "PATCH") or not isinstance(js, dict):
            continue
        data = js.get("data") if isinstance(js.get("data"), dict) else js
        # Éphémère : seul l'auteur le voit, personne d'autre ne peut être notifié.
        if int(data.get("flags") or 0) & 64:
            continue
        texts = [str(data.get("content") or "")] + h._component_texts(data.get("components"))
        # Dans un bloc de code, Discord n'interprète aucune mention.
        text = re.sub(r"```.*?```|`[^`]*`", "", "\n".join(texts), flags=re.S)
        allowed = data.get("allowed_mentions")
        parse = (allowed or {}).get("parse", []) if allowed is not None else ["everyone", "roles", "users"]
        roles = [str(r) for r in (allowed or {}).get("roles", [])] if allowed is not None else []
        where = h.describe_call(method, path, None).strip()
        if ("@everyone" in text or "@here" in text) and "everyone" in parse:
            found.append(f"@everyone · {where} · allowed_mentions={allowed} · {text[:120]!r}")
        if f"<@&{ROLE}>" in text and ("roles" in parse or str(ROLE) in roles):
            found.append(f"rôle non mentionnable · {where} · allowed_mentions={allowed} · {text[:120]!r}")
    return found


async def main(only: list[str]) -> int:
    from utils import access_matrix

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    cs._SWEEP_BOT = bot
    results: list[tuple[str, list[str]]] = []
    tested = 0

    def wanted(name: str) -> bool:
        return not only or any(o.casefold() in name.casefold() for o in only)

    async def run(label: str, runner) -> None:
        nonlocal tested
        since = len(h.CALLS)
        try:
            await asyncio.wait_for(runner(), 10)
        except Exception:  # noqa: BLE001 — seul ce qui sort compte ici
            pass
        await h.settle()
        tested += 1
        found = leaks(h.CALLS[since:])
        if found:
            results.append((label, found))
            print(f"[FUITE] {label} -> {found[0]}", flush=True)

    for command in sorted(bot.walk_commands(), key=lambda c: c.qualified_name):
        name = command.qualified_name
        if not wanted(name) or command.hidden:
            continue
        try:
            invocation, missing = cs.prefix_invocation(command)
        except Exception:  # noqa: BLE001
            continue
        if INJECTION not in invocation or cs._skip_reason(name, access_matrix.access_tier(name), missing, False):
            continue
        await run(invocation, lambda inv=invocation: h.run_prefix(bot, guild, inv, **MOD))

    for command in sorted(bot.tree.walk_commands(), key=lambda c: c.qualified_name):
        if not isinstance(command, app_commands.Command) or not wanted(command.qualified_name):
            continue
        try:
            root, options, missing = cs.slash_invocation(command)
        except Exception:  # noqa: BLE001
            continue
        leaf = cs._leaf_options(options)
        if not any(INJECTION == str(o.get("value")) for o in leaf):
            continue
        if cs._skip_reason(command.qualified_name, access_matrix.access_tier(command.qualified_name), missing, False):
            continue
        label = "/" + command.qualified_name + "".join(f" {o['name']}=…" for o in leaf)
        await run(label, lambda r=root, o=options: bot.tree._call(h.build_interaction(bot, r, o, **MOD)))

    print(f"\n{tested} commande(s) avec texte libre testée(s) · {len(results)} fuite(s)")
    for label, found in results:
        print(f"- {label}\n    " + "\n    ".join(found[:4]))
    sys.stdout.flush()
    os._exit(1 if results else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    try:
        asyncio.run(main(args.only))
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(2)
