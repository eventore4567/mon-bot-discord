#!/usr/bin/env python3
"""Gate V95 : inventaire slash complet + journaux d'invitations canoniques."""
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

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")


async def run() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sentrix-v95-") as temp_dir:
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-v95.db")

        # Le gate est lance depuis tools/, donc sitecustomize n'est pas garanti d'avoir
        # vu la racine du repo au demarrage de Python. On installe explicitement V95 ici
        # afin de tester exactement le runtime que Railway reçoit avant son sync Discord.
        import sentrix_v95_bootstrap
        sentrix_v95_bootstrap.install()

        # railway_boot ajoute les extensions réellement chargées en production, sans
        # exécuter run() lors d'un simple import.
        import railway_boot
        import sentrix_v95_runtime as v95
        from cogs import invites as invites_mod
        from cogs import permission_guard
        from utils import log_categories, log_service

        bot_main = railway_boot.bot_main
        bot = bot_main.BotAllInOne()
        await bot.db.connect()

        loaded: list[str] = []
        for extension in bot_main.EXTENSIONS:
            try:
                await asyncio.wait_for(bot.load_extension(extension), timeout=30)
                loaded.append(extension)
            except Exception as exc:
                errors.append(
                    f"extension {extension}: {type(exc).__name__}: {exc}"
                )

        expected = {
            str(command.qualified_name)
            for command in bot.walk_commands()
            if v95._should_expose(command)
        }
        try:
            mapping = await v95.prepare_bot(bot)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            errors.append(f"prepare_bot: {type(exc).__name__}: {exc}")
            mapping = {}

        mapped = {str(info.get("original")) for info in mapping.values()}
        missing = sorted(expected - mapped)
        extra = sorted(mapped - expected)
        if missing:
            errors.append(
                f"{len(missing)} commande(s) historique(s) sans slash: "
                + ", ".join(missing[:30])
            )
        if extra:
            errors.append(
                f"{len(extra)} mapping(s) sans commande source: "
                + ", ".join(extra[:20])
            )
        if len(mapping) != len(set(mapping)):
            errors.append("chemins slash dupliqués")

        roots = list(bot.tree.get_commands())
        root_names = [str(item.name).casefold() for item in roots]
        if len(root_names) != len(set(root_names)):
            errors.append("racines slash dupliquées")
        if len(roots) > 100:
            errors.append(f"budget slash dépassé: {len(roots)}/100")
        for required in ("help", "setup", "ping", "sentrix", "moderation", "security", "ticket", "giveaway", "invites", "games"):
            if required not in root_names:
                errors.append(f"racine slash essentielle absente: /{required}")

        # Discord limite un groupe et un sous-groupe à 25 options/sous-commandes.
        for root in roots:
            children = list(getattr(root, "commands", ()) or ())
            if len(children) > 25:
                errors.append(f"/{root.name}: {len(children)} enfants > 25")
            for child in children:
                nested = list(getattr(child, "commands", ()) or ())
                if len(nested) > 25:
                    errors.append(
                        f"/{root.name} {child.name}: {len(nested)} enfants > 25"
                    )

        # Les paramètres Discord natifs doivent réellement exister sur des commandes de
        # modération courantes, pas être remplacés par un seul champ texte.
        def app_for_original(original: str):
            for app_command in bot.tree.walk_commands():
                callback = getattr(app_command, "callback", None)
                if getattr(callback, "_sentrix_original_command", None) == original:
                    return app_command
            return None

        ban_app = app_for_original("ban")
        if ban_app is None:
            errors.append("/moderation ... ban absent")
        else:
            params = list(getattr(ban_app, "parameters", ()) or ())
            if not any(str(getattr(param, "type", "")).casefold().endswith("user") for param in params):
                errors.append("ban n'expose pas de sélecteur utilisateur Discord natif")

        giverole_app = app_for_original("giverole")
        if giverole_app is None:
            errors.append("slash giverole absent")
        else:
            params = list(getattr(giverole_app, "parameters", ()) or ())
            if not any(str(getattr(param, "type", "")).casefold().endswith("role") for param in params):
                errors.append("giverole n'expose pas de sélecteur de rôle Discord natif")

        # Le verrou slash groupé doit continuer à évaluer la commande TEXTE d'origine,
        # sinon /owner ou /security deviendraient soit bloqués, soit trop permissifs.
        if not getattr(permission_guard.interaction_root_name, "_sentrix_v95", False):
            errors.append("pont permissions V95 non installé")

        # Le cog historique des invitations reste uniquement responsable du cache. Il ne
        # doit pas devenir un deuxième producteur de logs.
        source_create = inspect.getsource(invites_mod.Invites.on_invite_create)
        if "send_log" in source_create or "helpers.send_log" in source_create:
            errors.append("cogs.invites.on_invite_create émet encore un log concurrent")
        if bot.get_cog("InviteResourceLogsV95") is None:
            errors.append("producteur canonique InviteResourceLogsV95 absent")
        if log_categories.category_for("invite_create") != "resources":
            errors.append("invite_create n'est plus routé vers Ressources")
        if log_categories.category_for("invite_delete") != "resources":
            errors.append("invite_delete n'est plus routé vers Ressources")

        panel = discord.Embed(title="Invitation créée")
        panel.add_field(name="Invitation", value="`abc123`")
        key1 = log_service.semantic_event_key(123, "invite_create", panel)
        key2 = log_service.semantic_event_key(123, "invite_create", panel)
        if not key1 or key1 != key2 or "abc123" not in key1:
            errors.append(f"dédup sémantique invitation invalide: {key1!r} / {key2!r}")

        print(
            f"V95: extensions={len(loaded)}/{len(bot_main.EXTENSIONS)} "
            f"commandes_groupées={len(mapping)} racines_slash={len(roots)}"
        )
        print(f"V95: inventaire_attendu={len(expected)} manquantes={len(missing)} extras={len(extra)}")
        print("V95: invite_create/delete -> resources; producteur unique vérifié")

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await bot.db.close()

    if errors:
        for error in errors:
            print("[ERROR]", error)
        print(f"ECHEC V95: {len(errors)} problème(s)")
        return 1
    print("OK V95: slash complet groupé, paramètres natifs, permissions et invitations conformes")
    return 0


if __name__ == "__main__":
    import discord
    raise SystemExit(asyncio.run(run()))
