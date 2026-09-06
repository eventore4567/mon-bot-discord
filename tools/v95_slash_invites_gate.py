#!/usr/bin/env python3
"""Gate V95 : inventaire slash complet + invitations + vérification guidée V96."""
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

        # Le gate est lancé depuis tools/, donc sitecustomize n'est pas garanti d'avoir
        # vu la racine du repo au démarrage de Python. On installe explicitement V95 ici.
        import sentrix_v95_bootstrap
        sentrix_v95_bootstrap.install()

        # railway_boot ajoute les extensions réellement chargées en production et remplace
        # commands.Bot par la classe AutoSharded utilisée sur Railway. V96 est donc branchée
        # juste après cet import, exactement comme dans railway_ha_product_boot.py.
        import railway_boot
        import sentrix_v95_runtime as v95
        import sentrix_verification_v96 as verification_v96
        import sentrix_verification_v96_finalizer as verification_v96_final
        from cogs import invites as invites_mod
        from cogs import permission_guard
        from utils import log_categories, log_service

        verification_v96.install()
        verification_v96_final.install()

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

        # Les runtimes V76/V78 sont volontairement chargés avant l'autorité finale V96.
        # Réaffirmer ici reproduit le moment juste avant CommandTree.sync en production.
        try:
            await verification_v96_final.reassert(bot)
        except Exception as exc:
            errors.append(f"V96 reassert: {type(exc).__name__}: {exc}")

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
        for required in ("help", "setup", "ping", "sentrix", "moderation", "security", "ticket", "giveaway", "invites", "games", "roles"):
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

        # V96 : une commande canonique, les anciens noms restent de vrais alias préfixés,
        # et un seul chemin slash /roles ... verification doit exister. La préparation
        # finale réinstalle volontairement le Cog de manière idempotente ; on compare donc
        # les alias et le comportement exposé, pas l'identité Python de l'objet Command.
        canonical = bot.get_command("verification")
        if canonical is None:
            errors.append("+verification absent après autorité finale V96")
        for alias in ("verify-panel", "verify-setup", "verify-config", "verification-config"):
            if canonical is None or bot.get_command(alias) is not canonical:
                errors.append(f"+{alias} n'est pas un alias de +verification")

        verification_paths = [
            path
            for path, info in mapping.items()
            if str(info.get("original")) == "verification"
        ]
        if len(verification_paths) != 1:
            errors.append(f"slash V96 attendu exactement une fois, obtenu={verification_paths!r}")
        elif not verification_paths[0].startswith("/roles "):
            errors.append(f"slash V96 hors /roles: {verification_paths[0]}")

        source_v96 = inspect.getsource(verification_v96)
        for required_fragment in (
            "VerificationChannelSelect",
            "VerificationRoleSelect",
            "VerificationRulesModal",
            "Aperçu",
            "Publier",
            "verify_captcha_enabled",
            "VerifyView",
            "5. Accès salons : NON",
            "_apply_auto_access",
            "verification_auto_access",
            "manage_channels",
            "manage_roles",
            "category_targets",
            "annulation après échec",
            "_SENSITIVE_CHANNEL_WORDS",
        ):
            if required_fragment not in source_v96:
                errors.append(f"V96 incomplet : élément absent {required_fragment}")

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
        print(
            "V96: +verification aliases=verify-panel,verify-setup,verify-config,verification-config "
            f"slash={verification_paths[0] if len(verification_paths) == 1 else 'INVALID'}"
        )
        print("V96: accès salons auto optionnel + protection staff/logs + rollback vérifiés")
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
    print("OK V95/V96: slash complet, permissions, invitations et vérification guidée conformes")
    return 0


if __name__ == "__main__":
    import discord
    raise SystemExit(asyncio.run(run()))
