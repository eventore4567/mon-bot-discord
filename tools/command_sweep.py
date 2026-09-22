#!/usr/bin/env python3
"""Balayage E2E de TOUTES les commandes SentriX (préfixe ET slash) sur le bot booté
comme en production, avec des arguments générés depuis les signatures réelles.

Pour chaque commande : exécution réelle via ``bot.process_commands`` / ``tree._call``,
HTTP Discord capturé (tools/sentrix_e2e_harness.py), puis classement :

- ``cassee``   : erreur technique (référence SXR émise par core.errors, trace ERROR
                 dans les logs, exception échappée) — c'est le cas ``+clear 100``.
- ``fragile``  : pas de réponse visible, délai dépassé, ou réponse contenant une
                 erreur d'arguments alors que les arguments viennent de la signature
                 (la commande annonce une chose et en attend une autre).
- ``ok``       : réponse visible, aucune trace technique.
- ``ignoree``  : commande volontairement non exécutée (propriétaire du bot,
                 arrêt/redémarrage, pièce jointe obligatoire).

Sortie : rapport Markdown + JSON (``--out``), et code retour 1 avec ``--strict`` si
au moins une commande est cassée. Aucune connexion réseau, base temporaire.

    python3 tools/command_sweep.py                      # tout
    python3 tools/command_sweep.py --only clear ban     # filtre par nom
    python3 tools/command_sweep.py --strict             # porte CI
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import pathlib
import sys
import time
import typing
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import sentrix_e2e_harness as harness  # noqa: E402  (fixe l'environnement avant discord/config)

import discord  # noqa: E402
from discord import app_commands  # noqa: E402
from discord.ext import commands  # noqa: E402

# Commandes jamais exécutées par le balayage : elles arrêtent le processus, touchent le
# compte du bot ou dépendent d'un état impossible à simuler proprement.
NEVER_RUN = frozenset({
    "shutdown", "restart", "reboot", "logout", "reload", "sync", "syncguild", "bot-leave",
    "set-bot", "setstatus", "status-rotate", "leave", "exit", "quit",
})
TECHNICAL_IGNORE = frozenset({
    "CommandNotFound", "CommandOnCooldown", "MissingPermissions", "BotMissingPermissions",
    "NoPrivateMessage", "CheckFailure", "DisabledCommand",
})
ARGUMENT_ERRORS = frozenset({
    "MissingRequiredArgument", "BadArgument", "TooManyArguments", "MemberNotFound",
    "UserNotFound", "RoleNotFound", "ChannelNotFound", "BadUnionArgument", "BadLiteralArgument",
    "RangeError", "TransformerError", "CommandInvokeError",
})

# ----------------------------------------------------------------- génération d'arguments
_SWEEP_BOT = None  # bot booté, pour résoudre les commandes d'origine (option « arguments »)


def _text_for(name: str) -> str:
    key = name.casefold()
    # Option texte libre qui attend en réalité une mention (Greedy[Role], Greedy[Member]…).
    if key in ("role", "roles", "rôle") or key.startswith("role"):
        return f"<@&{harness.PING_ROLE_ID}>"
    if any(k in key for k in ("membre", "member", "user", "utilisateur", "cible", "target", "adversaire")):
        return f"<@{harness.TARGET_ID}>"
    if any(k in key for k in ("salon", "channel")):
        return f"<#{harness.CID}>"
    if any(k in key for k in ("duree", "durée", "duration", "temps", "delai", "délai", "time")):
        return "10m"
    if any(k in key for k in ("raison", "reason", "motif")):
        return "test sweep"
    if any(k in key for k in ("montant", "amount", "mise", "somme", "prix", "price", "quantite", "nombre", "count")):
        return "10"
    if any(k in key for k in ("url", "lien", "link", "image", "avatar", "banner")):
        return "https://example.com/image.png"
    if any(k in key for k in ("couleur", "color", "colour")):
        return "#5865F2"
    if any(k in key for k in ("langue", "language", "lang")):
        return "fr"
    if any(k in key for k in ("emoji", "reaction")):
        return "✅"
    if any(k in key for k in ("choix", "options", "choices")):
        return "oui|non"
    if any(k in key for k in ("question", "titre", "title", "sujet")):
        return "question-test"
    if any(k in key for k in ("prefix", "préfixe")):
        return "+"
    if any(k in key for k in ("code", "id", "identifiant")):
        return "1"
    if any(k in key for k in ("nom", "name", "pseudo", "nick", "surnom")):
        return "nom-test"
    if any(k in key for k in ("ville", "city", "lieu")):
        return "Paris"
    if any(k in key for k in ("mot", "word", "terme", "keyword")):
        return "test"
    return "test"


def _unwrap(annotation: Any) -> tuple[Any, bool]:
    """Retire Optional/Union/Greedy ; renvoie (type principal, optionnel?)."""
    optional = False
    origin = typing.get_origin(annotation)
    if origin is typing.Union or (hasattr(__import__("types"), "UnionType") and isinstance(annotation, __import__("types").UnionType)):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        optional = len(args) != len(typing.get_args(annotation))
        annotation = args[0] if args else str
    if isinstance(annotation, commands.Greedy):
        annotation = annotation.converter
    return annotation, optional


def prefix_argument(param: commands.Parameter) -> str | None:
    """Valeur texte pour un paramètre de commande préfixée, ou None si non générable."""
    annotation, _optional = _unwrap(param.converter)
    name = param.name
    if isinstance(annotation, commands.Range):
        if annotation.annotation is int:
            return str(int(annotation.max if annotation.max is not None else (annotation.min or 1)))
        if annotation.annotation is float:
            return str(float(annotation.max if annotation.max is not None else 1.0))
        return "t" * int(annotation.max or 4) if annotation.max and annotation.max <= 12 else _text_for(name)
    if typing.get_origin(annotation) is typing.Literal:
        return str(typing.get_args(annotation)[0])
    if annotation is int:
        return "10" if "nombre" not in name.casefold() else "100"
    if annotation is float:
        return "1.5"
    if annotation is bool:
        return "oui"
    if annotation in (discord.Member, discord.User):
        return f"<@{harness.TARGET_ID}>"
    if annotation is discord.Role:
        return f"<@&{harness.PING_ROLE_ID}>"
    if annotation in (discord.VoiceChannel, discord.StageChannel):
        return f"<#{harness.VOICE_CID}>"
    if annotation in (discord.CategoryChannel,):
        return f"<#{harness.CATEGORY_ID}>"
    if inspect.isclass(annotation) and issubclass(annotation, discord.abc.GuildChannel):
        return f"<#{harness.CID}>"
    if annotation is discord.Message or annotation is discord.PartialMessage:
        return str(harness.STATE.get("last_cmd_id") or harness.next_id())
    if annotation in (discord.Emoji, discord.PartialEmoji):
        return "✅"
    if annotation is discord.Colour or annotation is discord.Color:
        return "#5865F2"
    if annotation is discord.Attachment:
        return None
    if annotation is str or annotation is inspect.Parameter.empty or annotation is None:
        return _text_for(name)
    if inspect.isclass(annotation) and issubclass(annotation, commands.Converter):
        return _text_for(name)
    if isinstance(annotation, commands.Converter):
        return _text_for(name)
    if inspect.isclass(annotation) and issubclass(annotation, commands.FlagConverter):
        return ""
    return _text_for(name)


def prefix_invocation(command: commands.Command) -> tuple[str, list[str]]:
    """"+ban <@cible> test sweep" + liste des paramètres non générables."""
    # Nom court conseillé (cogs/common_command_names.py) : le balayage prouve ainsi que
    # chaque alias court résout bien vers la même commande, avec les mêmes permissions.
    try:
        from cogs.common_command_names import display_name
        shown = display_name(command)
    except Exception:  # noqa: BLE001
        shown = command.qualified_name
    parts = [f"+{shown}"]
    missing: list[str] = []
    for name, param in command.clean_params.items():
        if not param.required:
            continue
        value = prefix_argument(param)
        if value is None:
            missing.append(name)
            continue
        if value:
            parts.append(value)
    return " ".join(parts), missing


def slash_option(param: app_commands.Parameter) -> dict | None:
    kind = param.type
    name = param.name
    if param.choices:
        return {"name": name, "type": kind.value, "value": param.choices[0].value}
    if kind is discord.AppCommandOptionType.string:
        if getattr(param, "max_length", None) is not None and param.max_length < 6:
            return {"name": name, "type": 3, "value": "t" * param.max_length}
        return {"name": name, "type": 3, "value": _text_for(name)}
    if kind is discord.AppCommandOptionType.integer:
        value = param.max_value if param.max_value is not None else (param.min_value if param.min_value is not None else 10)
        return {"name": name, "type": 4, "value": int(value)}
    if kind is discord.AppCommandOptionType.number:
        value = param.max_value if param.max_value is not None else 1.5
        return {"name": name, "type": 10, "value": float(value)}
    if kind is discord.AppCommandOptionType.boolean:
        return {"name": name, "type": 5, "value": True}
    if kind is discord.AppCommandOptionType.user:
        return {"name": name, "type": 6, "value": str(harness.TARGET_ID)}
    if kind is discord.AppCommandOptionType.channel:
        types = list(param.channel_types or [])
        if types and all(t in (discord.ChannelType.voice, discord.ChannelType.stage_voice) for t in types):
            return {"name": name, "type": 7, "value": str(harness.VOICE_CID)}
        if types and all(t is discord.ChannelType.category for t in types):
            return {"name": name, "type": 7, "value": str(harness.CATEGORY_ID)}
        return {"name": name, "type": 7, "value": str(harness.CID)}
    if kind is discord.AppCommandOptionType.role:
        return {"name": name, "type": 8, "value": str(harness.PING_ROLE_ID)}
    if kind is discord.AppCommandOptionType.mentionable:
        return {"name": name, "type": 9, "value": str(harness.TARGET_ID)}
    if kind is discord.AppCommandOptionType.attachment:
        return None
    return {"name": name, "type": kind.value, "value": _text_for(name)}


def slash_invocation(command: app_commands.Command) -> tuple[str, list, list[str]]:
    """(racine, options imbriquées, paramètres non générables) pour une commande slash feuille."""
    leaf_options: list[dict] = []
    missing: list[str] = []
    params = list(command.parameters)
    if len(params) == 1 and params[0].name == "arguments":
        # Surface V95 « texte libre » : on rejoue les mêmes arguments que le préfixe.
        source = getattr(getattr(command, "callback", None), "_sentrix_original_command", None)
        from discord.ext import commands as _commands
        bot_command = None
        try:
            import sentrix_v95_runtime as _v95  # noqa: F401
        except Exception:
            pass
        text = ""
        if source and _SWEEP_BOT is not None:
            bot_command = _SWEEP_BOT.get_command(str(source))
        if isinstance(bot_command, _commands.Command):
            invocation, missing_prefix = prefix_invocation(bot_command)
            text = " ".join(invocation.split(" ")[bot_command.qualified_name.count(" ") + 1:])
            missing.extend(missing_prefix)
        if text:
            leaf_options.append({"name": "arguments", "type": 3, "value": text})
        params = []
    for param in params:
        if not param.required:
            continue
        option = slash_option(param)
        if option is None:
            missing.append(param.name)
            continue
        leaf_options.append(option)
    chain = []
    node: Any = command
    while node is not None:
        chain.append(node)
        node = getattr(node, "parent", None)
    chain.reverse()  # racine → feuille
    options = leaf_options
    for depth in range(len(chain) - 1, 0, -1):
        sub = chain[depth]
        kind = 2 if isinstance(sub, app_commands.Group) else 1
        options = [{"name": sub.name, "type": kind, "options": options}]
    return chain[0].name, options, missing


# ----------------------------------------------------------------- capture des erreurs


class _ErrorCapture(logging.Handler):
    """Toute trace ERROR avec exception pendant la fenêtre d'une commande = commande cassée."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []
        self.active = False

    def emit(self, record: logging.LogRecord) -> None:
        if self.active and record.exc_info:
            self.records.append(record)


def _root_name(name: str) -> str:
    return name.split(" ", 1)[0]


def _skip_reason(name: str, tier: str, missing: list[str], include_owner: bool) -> str | None:
    root = _root_name(name)
    if root in NEVER_RUN or name in NEVER_RUN:
        return "arrêt/redémarrage ou compte du bot : jamais exécutée par le balayage"
    if tier == "owner-global" and not include_owner:
        return "réservée au propriétaire du bot (--include-owner pour l'inclure)"
    if missing:
        return "paramètre obligatoire non générable : " + ", ".join(missing)
    return None


async def _run_one(bot, guild, *, transport: str, name: str, invocation: str, runner, capture: _ErrorCapture,
                   reports: list, timeout: float, generated_args: int = 0) -> dict[str, Any]:
    since = len(harness.CALLS)
    reports.clear()
    capture.records.clear()
    capture.active = True
    escaped: str | None = None
    timed_out = False
    started = time.perf_counter()
    try:
        await asyncio.wait_for(runner(), timeout)
    except asyncio.TimeoutError:
        timed_out = True
    except Exception as exc:  # noqa: BLE001 - on veut tout voir
        escaped = f"{type(exc).__name__}: {str(exc)[:200]}"
    await harness.settle()
    capture.active = False
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    calls = harness.CALLS[since:]
    replies = [c for c in calls if harness.is_reply(c[0], c[1])]
    text = harness.visible_text(calls)
    technical = [r for r in reports if r.exc_type not in TECHNICAL_IGNORE]
    argument_errors = [r for r in reports if r.exc_type in ARGUMENT_ERRORS]
    log_errors = [f"{r.name}: {str(r.getMessage())[:160]}" for r in capture.records]

    if technical or escaped or log_errors:
        status = "cassee"
    elif timed_out and not replies:
        status = "fragile"
    elif not replies:
        status = "fragile"
    elif "SXR-CMD-" in text or "Une erreur technique" in text:
        status = "cassee"
    elif generated_args and (argument_errors or any(
            k in text for k in ("Argument manquant", "Il manque", "Argument invalide", "Usage :", "Utilisation :"))):
        # Nos arguments viennent de la signature : s'ils sont refusés, la commande
        # annonce une chose et en attend une autre (ex. app_commands.Range en préfixe).
        status = "fragile"
    else:
        status = "ok"

    detail_parts: list[str] = []
    for r in technical:
        detail_parts.append(f"{r.code} {r.exc_type}: {r.exc_message[:160]}")
    if escaped:
        detail_parts.append("exception échappée : " + escaped)
    detail_parts.extend(log_errors[:3])
    if timed_out and not replies:
        detail_parts.append(f"délai dépassé ({int(timeout)} s) sans réponse")
    elif timed_out:
        # Jeu ou menu qui attend une interaction : la réponse est partie, la commande
        # reste volontairement ouverte — le balayage l'interrompt sans la compter.
        detail_parts.append(f"interactive (attend une action du membre), interrompue après {int(timeout)} s")
    if status == "fragile" and not replies and not timed_out:
        detail_parts.append("aucune réponse visible envoyée au membre")
    if status == "fragile" and argument_errors:
        detail_parts.append("arguments générés depuis la signature refusés : " + ", ".join(sorted({r.exc_type for r in argument_errors})))

    return {
        "transport": transport, "command": name, "invocation": invocation, "status": status,
        "elapsed_ms": elapsed_ms, "replies": len(replies), "http_calls": len(calls),
        "detail": " | ".join(detail_parts), "response": text.replace("\n", " ")[:220],
    }


async def sweep(*, only: list[str], include_owner: bool, timeout: float, transports: set[str]) -> dict[str, Any]:
    from core.errors import pipeline as error_pipeline
    from utils import access_matrix

    bot = await harness.boot()
    guild = await harness.setup_world(bot)
    global _SWEEP_BOT
    _SWEEP_BOT = bot

    capture = _ErrorCapture()
    logging.getLogger().addHandler(capture)
    logging.disable(logging.NOTSET)
    reports: list = []
    error_pipeline.subscribe(reports.append)

    results: list[dict[str, Any]] = []

    def wanted(name: str) -> bool:
        if not only:
            return True
        return any(o.casefold() in name.casefold() for o in only)

    if "prefix" in transports:
        seen: set[str] = set()
        for command in sorted(bot.walk_commands(), key=lambda c: c.qualified_name):
            name = command.qualified_name
            if name in seen or not wanted(name) or command.hidden:
                continue
            seen.add(name)
            try:
                invocation, missing = prefix_invocation(command)
            except Exception as exc:  # noqa: BLE001 - le balayage continue
                invocation, missing = f"+{name}", [f"génération impossible ({type(exc).__name__})"]
            skip = _skip_reason(name, access_matrix.access_tier(name), missing, include_owner)
            if skip:
                results.append({"transport": "prefix", "command": name, "invocation": invocation, "status": "ignoree",
                                "elapsed_ms": 0, "replies": 0, "http_calls": 0, "detail": skip, "response": ""})
                continue
            results.append(await _run_one(
                bot, guild, transport="prefix", name=name, invocation=invocation,
                runner=lambda inv=invocation: harness.run_prefix(bot, guild, inv),
                capture=capture, reports=reports, timeout=timeout,
                generated_args=len(invocation.split()) - 1 - invocation.split(" ")[0].count(" ") - (len(_prefix_words(invocation, command)) - 1),
            ))
            print(f"[{results[-1]['status']:8}] {invocation}", flush=True)

    if "slash" in transports:
        for command in sorted(bot.tree.walk_commands(), key=lambda c: c.qualified_name):
            if not isinstance(command, app_commands.Command):
                continue
            name = command.qualified_name
            if not wanted(name):
                continue
            try:
                root, options, missing = slash_invocation(command)
            except Exception as exc:  # noqa: BLE001 - le balayage continue
                root, options, missing = name.split(" ")[0], [], [f"génération impossible ({type(exc).__name__})"]
            invocation = "/" + name + "".join(
                f" {o['name']}={o['value']}" for o in _leaf_options(options)
            )
            skip = _skip_reason(name, access_matrix.access_tier(name), missing, include_owner)
            if skip:
                results.append({"transport": "slash", "command": name, "invocation": invocation, "status": "ignoree",
                                "elapsed_ms": 0, "replies": 0, "http_calls": 0, "detail": skip, "response": ""})
                continue
            results.append(await _run_one(
                bot, guild, transport="slash", name=name, invocation=invocation,
                runner=lambda r=root, o=options: bot.tree._call(harness.build_interaction(bot, r, o)),
                capture=capture, reports=reports, timeout=timeout,
                generated_args=len(_leaf_options(options)),
            ))
            print(f"[{results[-1]['status']:8}] {invocation}", flush=True)

    counts = {key: sum(1 for r in results if r["status"] == key) for key in ("cassee", "fragile", "ok", "ignoree")}
    return {"generated_at": int(time.time()), "counts": counts, "total": len(results), "results": results}


def _prefix_words(invocation: str, command: commands.Command) -> list[str]:
    """Mots du nom affiché (« +music pl add » → 3) pour ne pas les compter comme arguments."""
    depth = command.qualified_name.count(" ") + 1
    return invocation.split(" ")[:depth]


def _leaf_options(options: list) -> list:
    node = options
    while node and isinstance(node, list) and node[0].get("type") in (1, 2) and "options" in node[0]:
        node = node[0]["options"]
    return node or []


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# Balayage des commandes SentriX",
        "",
        f"Généré le {time.strftime('%d/%m/%Y %H:%M', time.localtime(report['generated_at']))} — "
        f"{report['total']} exécutions · **{counts['cassee']} cassée(s)** · {counts['fragile']} fragile(s) · "
        f"{counts['ok']} ok · {counts['ignoree']} ignorée(s)",
        "",
    ]
    for status, title in (("cassee", "Cassées (erreur technique)"), ("fragile", "Fragiles (à vérifier)"),
                          ("ignoree", "Ignorées"), ("ok", "OK")):
        rows = [r for r in report["results"] if r["status"] == status]
        lines.append(f"## {title} — {len(rows)}")
        lines.append("")
        if not rows:
            lines.append("_Aucune._")
            lines.append("")
            continue
        lines.append("| Commande | Invocation testée | Détail | Réponse vue par le membre |")
        lines.append("|---|---|---|---|")
        for r in rows:
            detail = (r["detail"] or "").replace("|", "\\|")
            response = (r["response"] or "").replace("|", "\\|")
            if status == "ok":
                response = response[:80]
            lines.append(f"| `{r['invocation'].split(' ')[0]}` ({r['transport']}) | `{r['invocation'].replace('`', '')}` | {detail} | {response} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=[], help="ne tester que les commandes contenant ces mots")
    parser.add_argument("--include-owner", action="store_true", help="exécuter aussi les commandes propriétaire du bot")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--transport", choices=("prefix", "slash", "both"), default="both")
    parser.add_argument("--out", default=str(ROOT / "reports" / "command_sweep"), help="préfixe des fichiers .md/.json")
    parser.add_argument("--strict", action="store_true", help="code retour 1 si une commande est cassée")
    args = parser.parse_args(argv)
    transports = {"prefix", "slash"} if args.transport == "both" else {args.transport}

    report = asyncio.run(sweep(only=args.only, include_owner=args.include_owner, timeout=args.timeout, transports=transports))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    counts = report["counts"]
    print(f"\nBalayage terminé : {report['total']} exécutions — cassées={counts['cassee']} fragiles={counts['fragile']} "
          f"ok={counts['ok']} ignorées={counts['ignoree']}\nRapport : {out.with_suffix('.md')}", flush=True)
    code = 1 if (args.strict and counts["cassee"]) else 0
    sys.stdout.flush()
    os._exit(code)  # aiosqlite garde des threads vivants : sortie franche.


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
