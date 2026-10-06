#!/usr/bin/env python3
"""Quelle commande CHANGE quelque chose sans laisser de trace dans #logs ?

Une action importante dont la seule trace visible est la réponse dans le salon est
une action invisible : son auteur peut supprimer ce message, et il ne reste rien.

Le défaut ne se lit pas dans le source. Un cog peut journaliser via ``log_action``,
via un webhook, via une enveloppe réassignée au boot (voir
[[sentrix-tickets-six-methodes-reassignees]]) — ou pas du tout. Seul l'envoi réel
le dit. Ce balayage boote le bot comme en production, exécute chaque commande avec
des arguments générés depuis sa vraie signature, et croise trois signaux MESURÉS :

- ``mutation Discord`` : un appel PUT / PATCH / DELETE, ou un POST hors message,
  frappe l'API — un ban, un pseudo, une permission de salon, une suppression.
- ``écriture base``    : un INSERT / UPDATE / DELETE part vers SQLite — c'est le
  seul signal pour ``give-money``, qui ne fait AUCUN appel Discord.
- ``trace``            : un message atteint le salon de logs, ou un webhook.

Une commande qui mute sans tracer est signalée ``sans-trace``.

    python3 tools/log_trace_sweep.py                  # tout
    python3 tools/log_trace_sweep.py --only ban lock   # filtre
    python3 tools/log_trace_sweep.py --strict          # porte CI
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import sentrix_e2e_harness as harness  # noqa: E402
import command_sweep  # noqa: E402
from command_sweep import prefix_invocation, slash_invocation, _leaf_options, _skip_reason  # noqa: E402

#: Routes POST qui ne changent RIEN sur le serveur : une réponse, un indicateur de
#: saisie, l'ouverture d'un salon privé. Les confondre avec une mutation ferait
#: signaler toutes les commandes du bot.
_POST_INOFFENSIF = (
    re.compile(r"^/channels/\d+/messages$"),
    re.compile(r"^/channels/\d+/typing$"),
    re.compile(r"^/interactions/"),
    re.compile(r"^/users/@me/channels$"),
    re.compile(r"/callback"),
)
_ECRITURE_SQL = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
_TABLE_SQL = re.compile(
    r"^\s*(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+[\"`\[]?(\w+)",
    re.IGNORECASE,
)

#: Tables écrites par les couches de télémétrie à CHAQUE commande, y compris les
#: commandes purement lectrices. Mesuré : `+balance`, qui ne fait que lire, produit
#: six écritures, toutes ici. Sans cette liste, toute commande du bot serait
#: signalée comme mutante et le balayage ne dirait plus rien.
TABLES_AMBIANTES = frozenset({
    "production_command_events_v9",   # journal de télémétrie des commandes
    "v17_command_health",             # santé/latence par commande
    "member_daily_progress",          # compteur d'activité quotidienne
    "game_cooldowns",                 # anti-répétition des jeux : pas un changement d'état
})

#: Tables qui SONT un journal d'audit. Y écrire laisse une trace durable que
#: l'auteur de l'action ne peut pas effacer en supprimant un message — c'est une
#: meilleure preuve qu'une carte dans #logs, pas une absence de preuve.
#: ``sentrix_admin_actions`` enregistre auteur, action, cible, état avant/après et
#: réversibilité (sentrix_ops_v111.py:174). Sans cette liste, une centaine de
#: commandes de configuration ressortaient « sans trace » alors qu'elles tracent.
TABLES_AUDIT = frozenset({
    "sentrix_admin_actions",        # sentrix_ops_v111.py : auteur, action, avant/après
    "security_events",              # security_runtime_hardening.py : panic, protections
    "sanctions",                    # database/db.py : dossiers de modération numérotés
    "moderation_case_events",       # operations_center.py
    "platform_audit_log",           # platform_v4.py
    "antinuke_rollback_actions",    # antinuke_rollback.py
    "mastery_nuke_actions",         # bot_mastery_runtime.py
    "privacy_actions",              # production_readiness_runtime.py
    "v12_runtime_events",           # bot_v12_machine.py
})
#: Repérées par leur forme — une colonne qui nomme l'AUTEUR (actor_id, created_by,
#: moderator_id...) ET une qui nomme l'ACTION (action, event_type...). Deux tables
#: trouvées par ce critère sont volontairement EXCLUES, parce qu'elles décrivent une
#: configuration et non un geste : ``feature_suite_items`` et
#: ``sentrix_dashboard_automations``. ``staff_case_items_v1`` l'est aussi : elle
#: stocke le contenu d'un dossier, pas le fait qu'on y ait touché.


def _table(sql: str) -> str:
    m = _TABLE_SQL.match(sql)
    return m.group(1).casefold() if m else ""


def _reponse_interaction(path: str) -> bool:
    """La réponse d'une commande slash, quelle que soit sa méthode.

    Mesuré : une réponse d'interaction s'envoie par ``POST /webhooks/{app}/{token}``
    et se corrige par ``PATCH /webhooks/{app}/{token}/messages/@original``. Sans
    cette exception, répondre compte comme muter, et TOUTE commande slash — même
    ``/avatar`` — ressort comme changeant le serveur.
    """
    m = re.match(r"^/webhooks/(\d+)/", path)
    return bool(m) and int(m.group(1)) == harness.BOT_ID


def _est_mutation(method: str, path: str) -> bool:
    if _reponse_interaction(path) or path.startswith("/interactions/"):
        return False
    # Rééditer un message déjà posté par le bot rafraîchit un panneau ; ce n'est pas
    # un changement du serveur. SUPPRIMER le message d'autrui en est un, et garde sa
    # propre route (DELETE /channels/*/messages/*), traitée plus bas.
    if method == "PATCH" and re.match(r"^/channels/\d+/messages/\d+$", path):
        return False
    if method in ("PUT", "PATCH", "DELETE"):
        return True
    if method != "POST":
        return False
    return not any(m.search(path) for m in _POST_INOFFENSIF)


def _est_trace(method: str, path: str) -> bool:
    """Un message dans le salon de logs, ou un webhook qui n'est PAS la réponse slash.

    Piège mesuré : une réponse d'interaction est elle-même un appel webhook,
    ``POST /webhooks/{application_id}/{token}``. En comptant tout webhook comme une
    trace, 252 commandes slash ressortaient « tracées » contre 6 lectures — le
    détecteur ne mesurait plus rien sur ce transport. Seul un webhook dont
    l'identifiant n'est PAS celui de l'application est un vrai journal.
    """
    if method != "POST":
        return False
    m = re.match(r"^/channels/(\d+)/messages$", path)
    if m and int(m.group(1)) == harness.LOGCID:
        return True
    w = re.match(r"^/webhooks/(\d+)/", path)
    if w:
        return int(w.group(1)) != harness.BOT_ID
    return False


class _Ecritures:
    """Compte les écritures SQL d'une commande, en enveloppant db.execute."""

    def __init__(self, db):
        self.db = db
        self.sql: list[str] = []
        self.tables: set[str] = set()
        self._original = db.execute

    def __enter__(self):
        async def _execute(query: str, params: tuple = ()):
            if _ECRITURE_SQL.match(str(query)):
                plat = " ".join(str(query).split())
                table = _table(plat)
                if table and table not in TABLES_AMBIANTES:
                    self.tables.add(table)
                    self.sql.append(plat[:110])
            return await self._original(query, params)

        self.db.execute = _execute
        return self

    def __exit__(self, *_):
        self.db.execute = self._original
        return False

    def reset(self):
        self.sql.clear()
        self.tables.clear()


async def _mesurer(bot, guild, *, transport, name, invocation, runner, ecritures, timeout):
    depuis = len(harness.CALLS)
    ecritures.reset()
    erreur = ""
    try:
        await asyncio.wait_for(runner(), timeout)
    except asyncio.TimeoutError:
        erreur = "delai depasse"
    except Exception as exc:  # noqa: BLE001 — le balayage continue
        erreur = f"{type(exc).__name__}"
    try:
        await harness.settle(idle=0.15, maximum=1.0)
    except Exception:  # noqa: BLE001
        pass

    appels = harness.CALLS[depuis:]
    mutations = [f"{m} {p}" for m, p, _ in appels if _est_mutation(m, p)]
    traces = [f"{m} {p}" for m, p, _ in appels if _est_trace(m, p)]
    sql = list(ecritures.sql)
    tables = sorted(ecritures.tables)

    audit = sorted(set(tables) & TABLES_AUDIT)
    if mutations or sql:
        statut = "trace" if (traces or audit) else "sans-trace"
    else:
        statut = "lecture"

    return {
        "transport": transport,
        "command": name,
        "invocation": invocation,
        "statut": statut,
        "mutations": mutations[:6],
        "ecritures_sql": sql[:6],
        "tables": tables,
        "traces": traces[:3],
        "audit": audit,
        "erreur": erreur,
    }


async def sweep(*, only: list[str], transports: set[str], timeout: float, include_owner: bool) -> dict[str, Any]:
    from utils import access_matrix

    bot = await harness.boot()
    guild = await harness.setup_world(bot)
    command_sweep._SWEEP_BOT = bot

    def voulu(nom: str) -> bool:
        return not only or any(o.casefold() in nom.casefold() for o in only)

    lignes: list[dict[str, Any]] = []
    with _Ecritures(bot.db) as ecritures:
        if "prefix" in transports:
            vus: set[str] = set()
            for command in sorted(bot.walk_commands(), key=lambda c: c.qualified_name):
                nom = command.qualified_name
                if nom in vus or not voulu(nom) or command.hidden:
                    continue
                vus.add(nom)
                try:
                    invocation, manquants = prefix_invocation(command)
                except Exception as exc:  # noqa: BLE001
                    invocation, manquants = f"+{nom}", [f"generation impossible ({type(exc).__name__})"]
                saute = _skip_reason(nom, access_matrix.access_tier(nom), manquants, include_owner)
                if saute:
                    lignes.append({"transport": "prefix", "command": nom, "invocation": invocation,
                                   "statut": "ignoree", "mutations": [], "ecritures_sql": [],
                                   "tables": [], "traces": [], "erreur": saute})
                    continue
                ligne = await _mesurer(
                    bot, guild, transport="prefix", name=nom, invocation=invocation,
                    runner=lambda inv=invocation: harness.run_prefix(bot, guild, inv),
                    ecritures=ecritures, timeout=timeout,
                )
                lignes.append(ligne)
                print(f"[{ligne['statut']:11}] {invocation}", flush=True)

        if "slash" in transports:
            from discord import app_commands
            for command in sorted(bot.tree.walk_commands(), key=lambda c: c.qualified_name):
                if not isinstance(command, app_commands.Command):
                    continue
                nom = command.qualified_name
                if not voulu(nom):
                    continue
                try:
                    racine, options, manquants = slash_invocation(command)
                except Exception as exc:  # noqa: BLE001
                    racine, options, manquants = nom.split(" ")[0], [], [f"generation impossible ({type(exc).__name__})"]
                invocation = "/" + nom + "".join(f" {o['name']}={o['value']}" for o in _leaf_options(options))
                saute = _skip_reason(nom, access_matrix.access_tier(nom), manquants, include_owner)
                if saute:
                    lignes.append({"transport": "slash", "command": nom, "invocation": invocation,
                                   "statut": "ignoree", "mutations": [], "ecritures_sql": [],
                                   "tables": [], "traces": [], "erreur": saute})
                    continue
                ligne = await _mesurer(
                    bot, guild, transport="slash", name=nom, invocation=invocation,
                    runner=lambda r=racine, o=options: bot.tree._call(harness.build_interaction(bot, r, o)),
                    ecritures=ecritures, timeout=timeout,
                )
                lignes.append(ligne)
                print(f"[{ligne['statut']:11}] {invocation}", flush=True)

    comptes = {k: sum(1 for l in lignes if l["statut"] == k)
               for k in ("sans-trace", "trace", "lecture", "ignoree")}
    return {"generated_at": int(time.time()), "counts": comptes, "total": len(lignes), "results": lignes}


def render_markdown(rapport: dict[str, Any]) -> str:
    sans = [l for l in rapport["results"] if l["statut"] == "sans-trace"]
    out = ["# Actions sans trace dans #logs", "",
           f"{rapport['total']} invocations · " + " · ".join(f"{k}={v}" for k, v in rapport["counts"].items()), ""]
    if sans:
        out += ["| commande | transport | ce qu'elle change |", "|---|---|---|"]
        for l in sorted(sans, key=lambda r: r["command"]):
            quoi = ", ".join(l["mutations"] or l.get("tables") or l["ecritures_sql"])[:90]
            out.append(f"| `{l['invocation']}` | {l['transport']} | {quoi} |")
    else:
        out.append("Aucune : toute commande qui change quelque chose laisse une trace.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", default=[])
    p.add_argument("--transport", choices=("prefix", "slash", "both"), default="both")
    p.add_argument("--timeout", type=float, default=6.0)
    p.add_argument("--include-owner", action="store_true")
    p.add_argument("--out", default=str(ROOT / "reports" / "log_trace_audit"))
    p.add_argument("--strict", action="store_true")
    a = p.parse_args(argv)
    transports = {"prefix", "slash"} if a.transport == "both" else {a.transport}
    rapport = asyncio.run(sweep(only=a.only, transports=transports, timeout=a.timeout,
                                include_owner=a.include_owner))
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(rapport), encoding="utf-8")
    print(f"\nBalayage termine : {rapport['total']} invocations · {rapport['counts']}\nRapport : {out.with_suffix('.md')}", flush=True)
    import os
    sys.stdout.flush()
    os._exit(1 if (a.strict and rapport["counts"]["sans-trace"]) else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
