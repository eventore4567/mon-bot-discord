#!/usr/bin/env python3
"""Audit de cohérence des permissions par groupe + relevé des commandes fail-closed.

Cherche systématiquement, sur les 500+ commandes réellement chargées en production
(main.EXTENSIONS + les extensions ajoutées par railway_boot.py), le même type de bug
que celui trouvé sur +giveaway/+giveaway list : un groupe public dont une sous-commande
dangereuse hérite silencieusement du niveau public (aucune entrée SUBCOMMAND_TIERS), ou
une sous-commande manifestement bénigne qui hérite à tort d'un niveau restrictif. Liste
aussi toute commande "fail-closed" (non classée nulle part, donc Administrateur par
défaut) pour revue manuelle — une commande censée être publique qui y tombe par erreur
produit exactement ce type de blocage silencieux.

Les heuristiques de mots-clés ci-dessous donnent des FAUX POSITIFS attendus (ex: "logs
list"/"security whitelist" sont légitimement admin malgré leur nom "en lecture seule" —
ils révèlent une configuration serveur sensible, pas une information publique comme
"giveaway list"). Ce script sert de point de départ pour une revue humaine, pas un
verdict automatique.
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

READ_ONLY_HINTS = ("list", "liste", "view", "show", "status", "info", "stats", "history", "search")
DANGEROUS_HINTS = (
    "create", "end", "reroll", "cancel", "delete", "remove", "ban", "clear", "reset",
    "set", "add", "edit", "disable", "enable", "kick", "mute", "warn", "wipe", "purge",
    "blacklist", "unblacklist", "give", "grant", "revoke", "transfer",
)


async def run() -> int:
    with tempfile.TemporaryDirectory(prefix="sentrix-perm-group-audit-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ci.db")

        import main
        railway_extra = [
            "cogs.drop", "cogs.interaction_transport_guard",
            "cogs.legacy_observability_conflict_guard", "cogs.slash_reliability_v7",
            "cogs.automod_enable_all", "cogs.setup_auto_fix", "cogs.setup_experience_v2",
            "cogs.emoji_name_lookup", "cogs.emoji_unicode_asset_fix", "cogs.create_sentrix",
            "cogs.create_sentrix_v3", "cogs.canonical_interactions", "cogs.sentrix_plus",
            "cogs.sentrix_ultimate", "cogs.plain_text_all_extension",
            "cogs.profile_oxyde_runtime", "cogs.deferred_context_response_guard",
            "cogs.slash_error_completion_guard", "cogs.final_stability_guard",
            "cogs.member_data_retention_v17", "cogs.sentrix_regression_fix",
        ]
        for ext in railway_extra:
            if ext not in main.EXTENSIONS:
                main.EXTENSIONS.append(ext)

        bot = main.BotAllInOne()
        await bot.db.connect()
        loaded = 0
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded += 1
            except Exception:
                pass

        from cogs import command_catalog_cleanup, slash_command_budget
        from cogs.hybrid_callback_resync import resync
        bot._prune_redundant_commands()
        command_catalog_cleanup.apply_surface(bot)
        slash_command_budget.finalize(bot)
        resync(bot)

        from discord.ext import commands as dpy_commands
        from utils import access_matrix as am

        print(f"Extensions chargées : {loaded}/{len(main.EXTENSIONS)}")

        all_commands = list(bot.walk_commands())
        print(f"Commandes totales (racines + sous-commandes) : {len(all_commands)}")

        # 1) Cohérence groupe / sous-commande (heuristique par mots-clés)
        anomalies: list[str] = []
        groups_checked = 0
        for command in all_commands:
            if not isinstance(command, dpy_commands.GroupMixin) or not command.commands or command.parent is not None:
                continue
            groups_checked += 1
            root_name = command.name.casefold()
            root_tier = am.access_tier(root_name)

            def all_subcommands(cmd, prefix=""):
                for sub in cmd.commands:
                    qualified = f"{prefix}{sub.name}".casefold()
                    yield qualified, sub
                    if isinstance(sub, dpy_commands.GroupMixin) and sub.commands:
                        yield from all_subcommands(sub, prefix=f"{qualified} ")

            for qualified, sub in all_subcommands(command, prefix=f"{root_name} "):
                has_override = qualified in am.SUBCOMMAND_TIERS or qualified in am.GUILD_OWNER_COMMANDS
                leaf = sub.name.casefold()
                is_dangerous = any(h in leaf for h in DANGEROUS_HINTS)
                is_readonly = any(h in leaf for h in READ_ONLY_HINTS)
                if root_tier == "public" and is_dangerous and not has_override:
                    anomalies.append(f"[PUBLIC->DANGEREUX sans override] {qualified!r} (racine {root_name!r} publique)")
                if root_tier != "public" and is_readonly and not is_dangerous and not has_override:
                    anomalies.append(f"[lecture-seule héritant de {root_tier}] {qualified!r} (racine {root_name!r})")

        print(f"\nGroupes racines vérifiés : {groups_checked}")
        print(f"Anomalies heuristiques (à revoir manuellement, faux positifs attendus) : {len(anomalies)}")
        for a in sorted(anomalies):
            print(" -", a)

        # 2) Commandes fail-closed (non classées nulle part -> Administrateur par défaut)
        fail_closed = []
        seen = set()
        for command in all_commands:
            name = command.qualified_name.casefold()
            if name in seen:
                continue
            seen.add(name)
            resolved = am.resolve_name(name, (command.root_parent or command).name)
            tier = am.access_tier(resolved)
            if tier == "fail-closed":
                fail_closed.append(name)

        print(f"\nCommandes fail-closed (non classées, Admin par défaut) : {len(fail_closed)}")
        for name in sorted(fail_closed):
            print(" -", name)

        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result

        # Les anomalies heuristiques du §1 sont imprimées pour revue humaine mais ne
        # bloquent jamais la CI (faux positifs attendus et déjà revus un par un :
        # "lecture seule" ne veut pas dire "public" quand la donnée elle-même est
        # sensible — logs/security/staffnote/embed restent légitimement admin malgré
        # leur nom). Seul un VRAI trou de classification (fail-closed) est bloquant :
        # c'est exactement la classe de bug déjà trouvée sur +giveaway/+giveaway list.
        if fail_closed:
            print(f"\nECHEC: {len(fail_closed)} commande(s) sans classification explicite (fail-closed).")
            return 1
    print("\nOK: aucune commande sans classification explicite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
