#!/usr/bin/env python3
"""Audit runtime ciblé sur les protections et commandes Sécurité V3 de SentriX.

Ce test ne se connecte jamais à Discord et n'exécute aucune sanction réelle. Il vérifie
les invariants de sécurité qui doivent survivre aux refactors : anti-nuke persistant,
verrous critiques, PANIC et arborescence canonique `+security` complète.
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
        from cogs import security_command_center, security_runtime_hardening

        bot = main.BotAllInOne()
        await bot.db.connect()

        for extension in ("cogs.automod", "cogs.security_tools"):
            try:
                await bot.load_extension(extension)
            except Exception as exc:
                errors.append(
                    f"chargement {extension}: {type(exc).__name__}: {exc}"
                )

        automod = bot.get_cog("Automod")
        if automod is None:
            errors.append("Cog Automod absent")
        elif not getattr(automod, "_sentrix_persistent_antinuke", False):
            errors.append("anti-nuke persistant non installé")

        hardening = bot.get_cog("SecurityHardening")
        if hardening is None:
            errors.append("Cog SecurityHardening absent")

        command_center = bot.get_cog("SecurityCommandCenter")
        if command_center is None:
            errors.append("Cog SecurityCommandCenter absent")
        if not getattr(bot, "_sentrix_security_command_center_v3", False):
            errors.append("marqueur Security V3 absent")

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
                "SELECT COUNT(*) AS n FROM antinuke_events "
                "WHERE guild_id = ? AND actor_id = ?",
                (guild.id, actor_id),
            )
            if remaining and int(remaining["n"]) != 0:
                errors.append(
                    "les événements anti-nuke ne sont pas purgés après déclenchement"
                )

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
            errors.append("commande legacy +panic absente")
        else:
            for subcommand in ("off", "status"):
                if panic.get_command(subcommand) is None:
                    errors.append(f"sous-commande legacy +panic {subcommand} absente")
            if not getattr(panic, "checks", None):
                errors.append("+panic legacy n'a aucun verrou d'accès")

        # Surface V3 : chaque famille demandée doit exister sous une seule racine.
        expected_v3 = {
            "security",
            "security status",
            "security filter",
            "security level",
            "security scan",
            "security repair",
            "security history",
            "security panic",
            "security whitelist",
            "security whitelist user-add",
            "security whitelist user-remove",
            "security whitelist users",
            "security whitelist role-add",
            "security whitelist role-remove",
            "security whitelist roles",
            "security whitelist domain-add",
            "security whitelist domain-remove",
            "security whitelist domains",
            "security blacklist",
            "security blacklist word-add",
            "security blacklist word-remove",
            "security blacklist words",
            "security blacklist user-add",
            "security blacklist user-remove",
            "security blacklist users",
            "security quarantine",
            "security unquarantine",
            "security role-snapshot",
            "security role-restore",
            "security permissions",
            "security backup",
            "security restore",
        }
        for qualified_name in sorted(expected_v3):
            if bot.get_command(qualified_name) is None:
                errors.append(f"commande Security V3 absente: +{qualified_name}")

        root = bot.get_command("security")
        if root is not None:
            if bot.get_command("securite") is not root:
                errors.append("alias +securite absent ou incorrect")
            if getattr(root, "cog", None) is not command_center:
                errors.append("+security n'appartient pas au SecurityCommandCenter")

        # Les anciens noms restent exécutables pour compatibilité, mais ne doivent plus
        # polluer +help. On vérifie tous ceux qui sont chargés dans cet audit.
        for legacy_name in sorted(security_command_center.LEGACY_SECURITY_ROOTS):
            command = bot.get_command(legacy_name)
            if command is not None and not command.hidden:
                errors.append(f"ancienne commande non masquée: +{legacy_name}")

        # Pas d'adresse IP dans le schéma des nouvelles protections défensives.
        schema_rows = await bot.db.fetchall(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)",
            tuple(sorted(expected_tables)),
        )
        joined_schema = "\n".join(
            (row["sql"] or "") for row in schema_rows
        ).casefold()
        for marker in ("ip_address", "remote_addr", "client_ip"):
            if marker in joined_schema:
                errors.append(
                    f"champ réseau privé inattendu dans le schéma: {marker}"
                )

        # Les cogs avancés créent une boucle qui attend on_ready ; l'audit ne se connecte
        # pas à Discord, donc on l'annule proprement avant de fermer SQLite.
        current = asyncio.current_task()
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
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

    print(
        "OK: anti-nuke persistant, verrous critiques, PANIC et "
        "arborescence +security V3 complète validés"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
