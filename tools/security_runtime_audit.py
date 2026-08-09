#!/usr/bin/env python3
"""Audit runtime ciblé sur les protections de sécurité SentriX.

Ce test ne se connecte jamais à Discord et n'exécute aucune sanction réelle. Il vérifie
les invariants de sécurité qui doivent survivre aux refactors : compteur anti-nuke
persistant, commandes critiques verrouillées et groupe +panic disponible.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DummyGuild:
    def __init__(self, guild_id: int):
        self.id = guild_id


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-security-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "security.db")

        import main
        from cogs import security_runtime_hardening

        bot = main.BotAllInOne()
        await bot.db.connect()

        try:
            await bot.load_extension("cogs.automod")
        except Exception as exc:
            errors.append(f"chargement cogs.automod: {type(exc).__name__}: {exc}")

        automod = bot.get_cog("Automod")
        if automod is None:
            errors.append("Cog Automod absent")
        else:
            if not getattr(automod, "_sentrix_persistent_antinuke", False):
                errors.append("anti-nuke persistant non installé")

        hardening = bot.get_cog("SecurityHardening")
        if hardening is None:
            errors.append("Cog SecurityHardening absent")

        # Les tables sont la garantie que les événements anti-nuke et snapshots PANIC
        # ne disparaissent pas simplement parce que le processus redémarre.
        expected_tables = {"antinuke_events", "panic_snapshots", "security_events"}
        rows = await bot.db.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)",
            tuple(sorted(expected_tables)),
        )
        existing_tables = {row["name"] for row in rows}
        missing_tables = sorted(expected_tables - existing_tables)
        if missing_tables:
            errors.append("tables sécurité absentes: " + ", ".join(missing_tables))

        # Vérifie que le compteur utilise bien SQLite et non uniquement nuke_tracker :
        # on vide volontairement le compteur mémoire entre les appels 2 et 3. Le troisième
        # doit quand même atteindre le seuil grâce aux deux événements stockés en base.
        if automod is not None:
            guild = DummyGuild(987654321)
            actor_id = 123456789
            first = await automod.record_nuke_action(guild, actor_id)
            second = await automod.record_nuke_action(guild, actor_id)
            automod.nuke_tracker.clear()
            third = await automod.record_nuke_action(guild, actor_id)
            if (first, second, third) != (False, False, True):
                errors.append(
                    "anti-nuke persistant inattendu: "
                    f"{(first, second, third)!r} au lieu de (False, False, True)"
                )
            remaining = await bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM antinuke_events WHERE guild_id = ? AND actor_id = ?",
                (guild.id, actor_id),
            )
            if remaining and int(remaining["n"]) != 0:
                errors.append("les événements anti-nuke ne sont pas purgés après déclenchement")

        for command_name in security_runtime_hardening.CRITICAL_SECURITY_COMMANDS:
            command = bot.get_command(command_name)
            if command is None:
                errors.append(f"commande critique absente: {command_name}")
                continue
            if not getattr(command, "_sentrix_critical_security_guard", False):
                errors.append(f"verrou propriétaire absent: {command_name}")
            if not getattr(command, "checks", None):
                errors.append(f"aucun check préfixe sur: {command_name}")

        panic = bot.get_command("panic")
        if panic is None:
            errors.append("commande +panic absente")
        else:
            for subcommand in ("off", "status"):
                if panic.get_command(subcommand) is None:
                    errors.append(f"sous-commande +panic {subcommand} absente")
            if not getattr(panic, "checks", None):
                errors.append("+panic n'a aucun verrou d'accès")

        # Pas d'adresse IP dans le schéma des nouvelles protections défensives.
        schema_rows = await bot.db.fetchall(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)",
            tuple(sorted(expected_tables)),
        )
        joined_schema = "\n".join((row["sql"] or "") for row in schema_rows).casefold()
        forbidden = ("ip_address", "remote_addr", "client_ip")
        for marker in forbidden:
            if marker in joined_schema:
                errors.append(f"champ réseau privé inattendu dans le schéma: {marker}")

        # Les installateurs peuvent créer des tâches qui attendent on_ready ; la CI ne se
        # connecte pas à Discord, donc on les annule proprement avant de fermer la DB.
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} problème(s) de sécurité détecté(s)")
        return 1

    print("OK: anti-nuke persistant, verrous propriétaires et +panic validés")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
