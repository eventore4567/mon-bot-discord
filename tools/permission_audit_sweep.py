#!/usr/bin/env python3
"""Audit permissions × messages de refus de TOUTES les commandes SentriX (+ et /).

Le bot est booté comme en production (tools/sentrix_e2e_harness.py) et chaque commande
est réellement invoquée à travers TOUTE la chaîne : gardes globaux, matrice d'accès,
checks de cog/commande, cooldowns, transport slash, puis les couches qui rendent
l'erreur (final_error_embed_v5, sentrix_grouped_slash_fix, final_interaction_policy).
Seul le CORPS de la commande est court-circuité (``commands.Command.invoke`` s'arrête
après ``prepare``), ce qui rend l'audit rapide et sans effet de bord.

Pour chaque commande, on croise :
- personas : membre, modérateur, administrateur, propriétaire du serveur, propriétaire
  de SentriX ;
- module : activé / désactivé (si la commande dépend d'un module) ;
- bot : toutes permissions / permission nécessaire retirée (si la commande en déclare).

Puis on compare le résultat réel (autorisé, ou refusé avec TEL texte) à l'attendu
déduit de la matrice, et on classe les écarts :
- ``public-bloquee``  : commande publique refusée à un membre alors que le module est actif ;
- ``escalade``        : un membre passe une commande qui ne lui est pas ouverte ;
- ``message-trompeur``: le refus parle de permission alors que la vraie cause est un
                        module désactivé / un MP / un cooldown, ou masque le vrai message ;
- ``message-vague``   : refus de permission sans nommer la permission manquante ;
- ``erreur-technique``: un refus rendu comme une erreur technique (référence SXR) ;
- ``ecart``           : autorisé/refusé contraire à l'attendu.

    python3 tools/permission_audit_sweep.py [--only balance work] [--strict]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

import sentrix_e2e_harness as harness  # noqa: E402
import command_sweep  # noqa: E402

import discord  # noqa: E402
from discord import app_commands  # noqa: E402
from discord.ext import commands  # noqa: E402

PERSONAS = {
    "membre": dict(author_id=harness.TARGET_ID, author_roles=(harness.MEMBER_ROLE_ID,)),
    "moderateur": dict(author_id=harness.MOD_ID, author_roles=(harness.MOD_ROLE_ID,)),
    "administrateur": dict(author_id=harness.ADMIN_ID, author_roles=(harness.ADMIN_ROLE_ID,)),
    "proprietaire-serveur": dict(author_id=harness.AUTHOR_ID, author_roles=(harness.MEMBER_ROLE_ID,)),
    "proprietaire-sentrix": dict(author_id=None, author_roles=(harness.MEMBER_ROLE_ID,)),  # id résolu au boot
}
GENERIC_PERMISSION_PHRASES = (
    "pas la permission d’utiliser", "pas la permission d'utiliser", "permission insuffisante",
    "pas les permissions nécessaires", "pas accès à cette commande", "vous n'avez pas accès",
    "réservée aux administrateurs",
)
# Commandes dont la validation dépend d'une pièce jointe : non générable par l'audit.
SKIP_COMMANDS = frozenset({"embed import"})
# Commandes servies par leur propre transport slash (pas par Command.callback) : une
# réponse suffit à prouver l'accès.
NATIVE_TRANSPORT = frozenset({"setup"})
NON_PERMISSION_CAUSES = ("module", "désactivé", "desactive", "message privé", "en attente", "cooldown", "réessayez dans", "réessaie dans")


class _Audit:
    """État partagé entre le corps court-circuité et la boucle d'audit."""
    reached = False
    active = False
    last_error: str = ""


def _patch_error_capture() -> None:
    """Note l'exception réellement rendue (type + message) pour le rapport."""
    import sentrix_grouped_slash_fix as grouped
    from cogs import final_error_embed_v5 as v5

    def remember(error) -> None:
        base = getattr(error, "original", error)
        _Audit.last_error = f"{type(base).__name__}: {str(base)[:160]}"

    original_short = grouped._short_error_for

    async def short_error_for(bot, command, interaction, error):
        remember(error)
        return await original_short(bot, command, interaction, error)

    grouped._short_error_for = short_error_for
    original_prefix = v5._texte_erreur_prefix

    def texte_erreur_prefix(ctx, error):
        remember(error)
        return original_prefix(ctx, error)

    v5._texte_erreur_prefix = texte_erreur_prefix


def _patch_command_body() -> None:
    """Le corps de la commande ne s'exécute pas : prepare()/can_run()/arguments/cooldowns
    oui, le callback métier non — sur les DEUX chemins (Command.invoke pour le préfixe,
    appel direct de ``command.callback`` sur le transport slash natif)."""
    import functools

    original = commands.Command.callback
    stubs: dict[int, Any] = {}

    def getter(self):
        real = original.fget(self)
        if not _Audit.active:
            return real
        stub = stubs.get(id(self))
        if stub is None or getattr(stub, "__wrapped__", None) is not real:
            # functools.wraps garde __name__/__wrapped__ : les gardes d'identité des
            # commandes de sanction (inspect.unwrap) voient toujours la vraie fonction.
            @functools.wraps(real)
            async def stub(*_args, **_kwargs):
                _Audit.reached = True

            stubs[id(self)] = stub
        return stub

    commands.Command.callback = property(getter, original.fset)


def _reset_throttles(bot, command) -> None:
    """Cooldowns et anti-doublon ne doivent pas polluer l'audit d'une persona à l'autre."""
    state = getattr(bot, "_sentrix_command_hardening_state", None)
    if state is not None:
        for attr in ("slash_buckets", "same_command_last", "active_user", "active_guild",
                     "active_heavy_user", "active_heavy_guild", "prefix_tokens", "slash_tokens"):
            try:
                getattr(state, attr).clear()
            except Exception:
                pass
    bucket = getattr(bot, "_cooldown_bucket", None)
    if bucket is not None and hasattr(bucket, "_cache"):
        bucket._cache.clear()
    node = command
    while node is not None:
        buckets = getattr(node, "_buckets", None)
        if buckets is not None and hasattr(buckets, "_cache"):
            buckets._cache.clear()
        node = getattr(node, "parent", None)


def _bot_permissions_required(command) -> list[str]:
    required: list[str] = []
    node = command
    while node is not None:
        for check in getattr(node, "checks", ()) or ():
            required.extend(getattr(check, "_sentrix_bot_permissions", ()) or ())
            qualname = str(getattr(check, "__qualname__", ""))
            if "bot_has_permissions" in qualname or "bot_has_guild_permissions" in qualname:
                for cell in getattr(check, "__closure__", None) or ():
                    value = cell.cell_contents
                    if isinstance(value, dict):
                        required.extend(k for k, v in value.items() if v)
        node = getattr(node, "parent", None)
    seen: list[str] = []
    for name in required:
        if name not in seen:
            seen.append(name)
    return seen


def _set_bot_permissions(guild, *, without: str | None) -> None:
    role = guild.get_role(harness.BOT_ROLE_ID)
    perms = discord.Permissions.all()
    if without:
        perms = discord.Permissions(perms.value, administrator=False, **{without: False})
    role._permissions = perms.value


def _expected(name: str, tier: str, persona: str, module_off: bool, bot_missing: str | None,
              module: str | None = None) -> tuple[str, str]:
    """(autorisé|refusé, cause attendue), dans l'ordre réel des gardes : identité/owner,
    module, permission de la persona, puis permission du bot."""
    from cogs.permission_setup_hardening_v65 import CATEGORY_REQUIRED_PERMISSION
    if tier == "owner-global":
        if persona != "proprietaire-sentrix":
            return ("refuse", "owner-sentrix")
    elif module_off:
        # Le propriétaire de SentriX traverse les modules coupés (règle explicite de la
        # matrice) sauf là où un garde métier (économie/niveaux) bloque tout le monde :
        # les deux issues sont acceptées, seul le message d'un refus est contrôlé.
        if persona == "proprietaire-sentrix":
            return ("autorise-ou-module", "module-off")
        return ("refuse", "module-off")
    else:
        persona_ok = True
        if persona == "proprietaire-sentrix":
            persona_ok = True
        elif tier == "guild-owner":
            persona_ok = persona == "proprietaire-serveur"
        elif persona in ("proprietaire-serveur", "administrateur"):
            persona_ok = True
        elif tier == "public":
            persona_ok = True
        else:
            mod = harness.MOD_PERMISSIONS
            if tier == "embed-staff":
                persona_ok = persona == "moderateur"
            elif tier.startswith("discord:"):
                persona_ok = persona == "moderateur" and bool(getattr(mod, tier.split(":", 1)[1], False))
            elif tier.startswith("categorie:"):
                perm = CATEGORY_REQUIRED_PERMISSION.get(tier.split(":", 1)[1], "manage_guild")
                persona_ok = persona == "moderateur" and bool(getattr(mod, perm, False))
            else:
                persona_ok = False
        if not persona_ok:
            return ("refuse", "owner-serveur" if tier == "guild-owner" else "permission")
    if bot_missing:
        return ("refuse", "bot-permission")
    return ("autorise", "")


def _classify(row: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    text = (row.get("full_text") or row["text"] or "").casefold()
    expected, cause = row["expected"], row["expected_cause"]
    actual = row["actual"]
    if row.get("technical"):
        issues.append("erreur-technique")
    denial_markers = ("permission", "accès", "acces", "désactiv", "desactiv", "réservée", "reservee", "manque",
                      "invalide", "usage", "attente", "cooldown", "introuvable", "serveur", "autorisé", "bloqu")
    if actual == "refuse" and expected == "autorise" and text and not any(m in text for m in denial_markers):
        # Commande servie par son propre transport (ex. /setup) : la réponse est arrivée
        # sans passer par le corps court-circuité, ce n'est pas un refus.
        row["actual"] = actual = "autorise"
    if expected == "autorise-ou-module":
        expected = "refuse" if actual == "refuse" else "autorise"
    if actual == "autorise" and expected == "refuse":
        if row["persona"] == "membre" and cause == "permission":
            issues.append("escalade")
        else:
            issues.append("ecart")
    elif actual == "refuse" and expected == "autorise":
        if row["tier"] == "public" and row["persona"] == "membre":
            issues.append("public-bloquee")
        else:
            issues.append("ecart")
    if actual == "refuse":
        generic = any(p in text for p in GENERIC_PERMISSION_PHRASES)
        if cause in ("module-off", "bot-permission"):
            if generic:
                issues.append("message-trompeur")
            if cause == "module-off" and not any(k in text for k in ("désactivé", "desactive", "n'est pas activé")):
                issues.append("message-trompeur")
            if cause == "bot-permission" and "sentrix" not in text and "il me manque" not in text:
                issues.append("message-trompeur")
        if cause == "permission" and row.get("required_permission"):
            if row["required_permission"].casefold() not in text:
                issues.append("message-vague")
        if cause == "owner-sentrix" and "propriétaire" not in text and "proprietaire" not in text:
            issues.append("message-vague")
        if cause == "owner-serveur" and "serveur" not in text:
            issues.append("message-vague")
        if not text.strip():
            issues.append("refus-silencieux")
    return issues


async def _run_prefix(bot, guild, command, invocation: str, persona: dict) -> tuple[str, str, bool]:
    since = len(harness.CALLS)
    _Audit.reached = False
    _Audit.last_error = ""
    reports: list = []
    from core.errors import pipeline
    pipeline.subscribe(reports.append)
    try:
        await asyncio.wait_for(harness.run_prefix(bot, guild, invocation, **persona), 10)
    except Exception as exc:  # noqa: BLE001
        reports.append(exc)
    finally:
        pipeline.unsubscribe(reports.append)
    for _ in range(3):
        await asyncio.sleep(0)
    text = harness.visible_text(harness.CALLS[since:])
    if _Audit.reached:
        return "autorise", text, False
    return "refuse", text, bool(reports) or "SXR-CMD-" in text


async def _run_slash(bot, guild, root: str, options: list, persona: dict) -> tuple[str, str, bool]:
    since = len(harness.CALLS)
    _Audit.reached = False
    _Audit.last_error = ""
    reports: list = []
    from core.errors import pipeline
    pipeline.subscribe(reports.append)
    try:
        interaction = harness.build_interaction(bot, root, options, author_id=persona["author_id"], author_roles=persona["author_roles"])
        await asyncio.wait_for(bot.tree._call(interaction), 10)
    except Exception as exc:  # noqa: BLE001
        reports.append(exc)
    finally:
        pipeline.unsubscribe(reports.append)
    for _ in range(3):
        await asyncio.sleep(0)
    text = harness.visible_text(harness.CALLS[since:])
    if _Audit.reached:
        return "autorise", text, False
    return "refuse", text, bool(reports) or "SXR-CMD-" in text


async def audit(*, only: list[str], transports: set[str]) -> dict[str, Any]:
    from utils import access_matrix
    from cogs import setup_v2_core as core
    from database.db import PRIMARY_CREATOR_ID

    bot = await harness.boot()
    guild = await harness.setup_world(bot)
    command_sweep._SWEEP_BOT = bot
    PERSONAS["proprietaire-sentrix"]["author_id"] = PRIMARY_CREATOR_ID
    guild._add_member(discord.Member(data=harness.member_payload(PRIMARY_CREATOR_ID, "jayden-owner", [harness.MEMBER_ROLE_ID]), guild=guild, state=bot._connection))
    _patch_command_body()
    _patch_error_capture()
    _Audit.active = True

    rows: list[dict[str, Any]] = []

    def wanted(name: str) -> bool:
        return not only or any(o.casefold() in name.casefold() for o in only)

    async def with_states(command, root_name: str, runner, transport: str, invocation: str):
        tier = access_matrix.access_tier(root_name)
        module = access_matrix.module_for_command(root_name)
        bot_perms = _bot_permissions_required(command)
        required_permission = None
        if tier.startswith("discord:"):
            required_permission = access_matrix.permission_label(tier.split(":", 1)[1])
        elif tier.startswith("categorie:"):
            from cogs.permission_setup_hardening_v65 import CATEGORY_REQUIRED_PERMISSION
            required_permission = access_matrix.permission_label(CATEGORY_REQUIRED_PERMISSION.get(tier.split(":", 1)[1], "manage_guild"))
        states = [("module-on", None)]
        if module:
            states.append(("module-off", None))
        if bot_perms:
            states.append(("bot-sans-" + bot_perms[0], bot_perms[0]))
        for persona_name, persona in PERSONAS.items():
            for state_name, missing_bot_perm in states:
                module_off = state_name == "module-off"
                if module_off:
                    await core.set_module_enabled(bot, harness.GID, module, False)
                _set_bot_permissions(guild, without=missing_bot_perm)
                _reset_throttles(bot, command)
                try:
                    actual, text, technical = await runner(persona)
                finally:
                    _set_bot_permissions(guild, without=None)
                    if module_off:
                        await core.set_module_enabled(bot, harness.GID, module, True)
                expected, cause = _expected(root_name, tier, persona_name, module_off, missing_bot_perm, module)
                if root_name in NATIVE_TRANSPORT and text.strip() and not any(
                        m in text.casefold() for m in ("pas accès", "permission", "réservée")):
                    actual = "autorise"
                row = {
                    "transport": transport, "command": command.qualified_name, "invocation": invocation,
                    "root": root_name, "tier": tier, "module": module, "persona": persona_name, "state": state_name,
                    "expected": expected, "expected_cause": cause, "actual": actual,
                    "text": text.replace("\n", " ")[:300], "full_text": text.replace("\n", " "), "technical": technical,
                    "required_permission": required_permission, "error": _Audit.last_error,
                }
                if missing_bot_perm:
                    row["required_permission"] = access_matrix.permission_label(missing_bot_perm)
                row["issues"] = _classify(row)
                row.pop("full_text", None)
                rows.append(row)

    if "prefix" in transports:
        seen: set[str] = set()
        for command in sorted(bot.walk_commands(), key=lambda c: c.qualified_name):
            name = command.qualified_name
            if command.hidden or name in seen or not wanted(name):
                continue
            seen.add(name)
            invocation, missing = command_sweep.prefix_invocation(command)
            if missing or command_sweep._root_name(name) in command_sweep.NEVER_RUN or name in SKIP_COMMANDS:
                continue
            root_name = access_matrix.resolve_name(name, (command.root_parent or command).name)
            await with_states(command, root_name, lambda persona, inv=invocation, c=command: _run_prefix(bot, guild, c, inv, persona), "prefix", invocation)
            print(f"[{len(rows):5}] +{name}", flush=True)

    if "slash" in transports:
        for command in sorted(bot.tree.walk_commands(), key=lambda c: c.qualified_name):
            if not isinstance(command, app_commands.Command):
                continue
            name = command.qualified_name
            if not wanted(name):
                continue
            root, options, missing = command_sweep.slash_invocation(command)
            if missing:
                continue
            from cogs import permission_guard
            # Même résolution que le garde slash réel (V95 : callback._sentrix_original_command).
            probe = harness.build_interaction(bot, root, options)
            root_name = permission_guard.interaction_root_name(probe)
            original = getattr(getattr(command, "callback", None), "_sentrix_original_command", None)
            source = bot.get_command(str(original)) if original else None
            if source is None:
                source = command
            if command_sweep._root_name(name) in command_sweep.NEVER_RUN:
                continue
            invocation = "/" + name
            await with_states(source, root_name, lambda persona, r=root, o=options: _run_slash(bot, guild, r, o, persona), "slash", invocation)
            print(f"[{len(rows):5}] /{name}", flush=True)

    commands_checked = len({(r["transport"], r["command"]) for r in rows})
    issues = [r for r in rows if r["issues"]]
    counts: dict[str, int] = {}
    for r in issues:
        for issue in r["issues"]:
            counts[issue] = counts.get(issue, 0) + 1
    return {"generated_at": int(time.time()), "commands_checked": commands_checked, "rows": len(rows),
            "issue_counts": counts, "issues": issues, "all": rows}


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Audit permissions × messages de refus", "",
             f"{report['commands_checked']} commandes vérifiées · {report['rows']} combinaisons · "
             + " · ".join(f"{k} : {v}" for k, v in sorted(report["issue_counts"].items())) or "aucune anomalie", ""]
    by_kind: dict[str, list] = {}
    for row in report["issues"]:
        for issue in row["issues"]:
            by_kind.setdefault(issue, []).append(row)
    for kind, rows in sorted(by_kind.items()):
        lines += [f"## {kind} — {len(rows)}", "", "| Commande | Persona | État | Attendu | Réel | Message |", "|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| `{r['invocation']}` | {r['persona']} | {r['state']} | {r['expected']} ({r['expected_cause']}) | {r['actual']} | {(r['text'] or '').replace('|', '¦')[:160]} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--transport", choices=("prefix", "slash", "both"), default="both")
    parser.add_argument("--out", default=str(ROOT / "reports" / "permission_audit"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    transports = {"prefix", "slash"} if args.transport == "both" else {args.transport}
    report = asyncio.run(audit(only=args.only, transports=transports))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(f"\nAudit terminé : {report['commands_checked']} commandes, {report['rows']} combinaisons, anomalies={report['issue_counts']}\nRapport : {out.with_suffix('.md')}", flush=True)
    import os
    sys.stdout.flush()
    os._exit(1 if (args.strict and report["issue_counts"]) else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
