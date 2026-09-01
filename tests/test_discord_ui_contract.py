from __future__ import annotations

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import discord

from utils import embeds, helpers, log_service

ROOT = Path(__file__).resolve().parents[1]


class DiscordUiContractTests(unittest.TestCase):
    def test_authoritative_files_compile(self):
        for rel in (
            "utils/embeds.py",
            "utils/log_service.py",
            "utils/helpers.py",
            "cogs/help.py",
            "cogs/logs.py",
            "cogs/final_interaction_policy.py",
            "cogs/final_runtime_polish.py",
            "cogs/error_experience_v3.py",
            "cogs/command_error_release_v41.py",
            "cogs/__init__.py",
        ):
            path = ROOT / rel
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_exact_banner_asset_exists_and_is_used(self):
        asset = ROOT / "assets" / "sentrix-log-header.png"
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 1000)
        self.assertTrue(embeds.SENTRIX_BANNER_URL.endswith("/assets/sentrix-log-header.png"))
        panel = embeds.log_embed("Rôle retiré", fields=(("Membre", "<@123456789012345678>", True),))
        self.assertEqual(panel.image.url, embeds.SENTRIX_BANNER_URL)

    def test_small_boxes_do_not_use_log_banner(self):
        for panel in (
            embeds.error("x", title="Commande introuvable"),
            embeds.success("ok"),
            embeds.warning("attention"),
            embeds.help_embed("SentriX — Centre d’aide", "Sélectionnez une catégorie."),
        ):
            self.assertFalse(panel.image.url)
            self.assertEqual(panel.colour.value, embeds.SENTRIX_COLOR)

    def test_log_mentions_are_native_markup_and_transport_blocks_pings(self):
        member = "<@1355855757991481475>"
        role = "<@&1355855757991481476>"
        channel = "<#1355855757991481477>"
        panel = embeds.log_embed(
            "Rôle retiré",
            fields=(("Membre", member, True), ("Rôle", role, True), ("Salon", channel, True)),
        )
        values = [field.value for field in panel.fields]
        self.assertIn(member, values)
        self.assertIn(role, values)
        self.assertIn(channel, values)
        payload = log_service.LOG_ALLOWED_MENTIONS.to_dict()
        self.assertEqual(payload.get("parse", []), [])
        self.assertNotIn("users", payload)
        self.assertNotIn("roles", payload)
        self.assertFalse(payload.get("replied_user", False))

    def test_log_producer_is_not_tied_to_a_railway_uuid(self):
        source = (ROOT / "utils" / "log_service.py").read_text(encoding="utf-8")
        self.assertNotIn("PRIMARY_RAILWAY_SERVICE_ID", source)
        self.assertNotIn("d4fb0c3a-d62b-4817-aae1-3cfc859d32c0", source)
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(log_service.is_primary_process())
        with patch.dict(os.environ, {"RAILWAY_SERVICE_ID": "un-nouvel-id"}, clear=True):
            self.assertTrue(log_service.is_primary_process())
        with patch.dict(os.environ, {"SENTRIX_LOG_PRODUCER": "false"}, clear=True):
            self.assertFalse(log_service.is_primary_process())

    def test_log_config_is_the_only_source_of_truth(self):
        """log_settings est migrée puis archivée une fois ; le runtime ne la touche plus."""
        source = (ROOT / "utils" / "log_service.py").read_text(encoding="utf-8")
        # Aucun accès SQL à log_settings, aucun trigger, aucun miroir legacy.
        for forbidden in ("FROM log_settings", "INTO log_settings", "UPDATE log_settings",
                          "CREATE TRIGGER", "_mirror_legacy_setting"):
            self.assertNotIn(forbidden, source, forbidden)

        db_source = (ROOT / "database" / "db.py").read_text(encoding="utf-8")
        # La table log_settings ne doit plus être recréée à chaque connect().
        self.assertNotIn("LOG_SETTINGS_SCHEMA", db_source)
        # La migration existe, est unique, et archive la table.
        self.assertIn("async def _migrate_logs", db_source)
        self.assertIn("ALTER TABLE log_settings RENAME TO", db_source)
        self.assertIn("LOG_CONFIG_SCHEMA", db_source)

    def test_set_log_config_rereads_after_write(self):
        """Le panneau ne doit jamais afficher ACTIF sur une écriture non confirmée."""
        source = (ROOT / "utils" / "log_service.py").read_text(encoding="utf-8")
        body = source[source.index("async def set_log_config("):]
        body = body[: body.index("\nasync def ")]
        self.assertIn("saved = await get_log_config(", body)
        self.assertIn("log_config_write_failed", body)

    def test_kick_command_and_discord_event_share_semantic_dedup_key(self):
        target = 1355855757991481475
        command_log = embeds.log_embed(
            "Dossier 12 — Expulsion",
            fields=(("Membre", f"<@{target}>\n`ID: {target}`", True),),
        )
        event_log = embeds.log_embed(
            "Membre expulsé",
            fields=(("Membre", f"<@{target}>", True),),
        )
        self.assertEqual(
            log_service.semantic_event_key(1, "moderation", command_log),
            log_service.semantic_event_key(1, "moderation", event_log),
        )
        self.assertEqual(
            log_service.semantic_event_key(1, "moderation", event_log),
            f"semantic:1:kick:{target}",
        )

    def test_legacy_ticket_fallback_is_never_sent_to_moderation_logger(self):
        ticket_log = embeds.log_entry(
            "Ticket fermé",
            cible=discord.Object(id=1355855757991481475),
            raison="Terminé",
        )
        self.assertEqual(helpers._normalize_log_kind("moderation", ticket_log), "tickets")
        moderation_log = embeds.log_embed(
            "Membre banni",
            fields=(("Membre", "<@1355855757991481475>", True),),
        )
        self.assertEqual(helpers._normalize_log_kind("moderation", moderation_log), "moderation")

    def test_log_layout_skips_empty_filler_and_uses_inline_width(self):
        panel = embeds.log_embed(
            "Rôle retiré",
            fields=(
                ("Membre", "<@1355855757991481475>", True),
                ("Rôle", "<@&1355855757991481476>", True),
                ("Modérateur", "<@1355855757991481477>", True),
                ("Raison", None, False),
            ),
        )
        self.assertEqual([field.name for field in panel.fields], ["Membre", "Rôle", "Modérateur"])
        self.assertTrue(all(field.inline for field in panel.fields))
        self.assertTrue(panel.footer.text.startswith("SentriX • "))

    def test_legacy_log_normalization_removes_filler(self):
        old = discord.Embed(title="Sanction")
        old.add_field(name="Historique", value="7 sanctions", inline=True)
        old.add_field(name="Raison", value="Aucune raison fournie", inline=False)
        old.add_field(name="Membre", value="<@1355855757991481475>", inline=True)
        rendered = embeds.normalize_log(old)
        self.assertEqual([field.name for field in rendered.fields], ["Membre"])

    def test_message_buttons_have_real_behavior(self):
        view = log_service.log_actions(
            jump_url="https://discord.com/channels/1/2/3",
            ids=[("Copier l'ID de l'auteur", 1355855757991481475), ("Copier l'ID du message", 1355855757991481476)],
        )
        self.assertIsNotNone(view)
        self.assertEqual(view.children[0].url, "https://discord.com/channels/1/2/3")
        self.assertEqual(view.children[1].custom_id, "sxid:1355855757991481475")
        self.assertEqual(view.children[2].custom_id, "sxid:1355855757991481476")
        self.assertTrue(all(item.row == 0 for item in view.children))

    def test_help_is_registry_backed_compact_and_preserves_member_state(self):
        source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")
        self.assertIn("bot.walk_commands()", source)
        self.assertIn("bot.tree.get_commands", source)
        self.assertIn("PAGE_SIZE = 7", source)
        self.assertIn("member=interaction.user", source)
        self.assertIn("SentriX — Centre d’aide", source)
        self.assertIn("Rechercher", source)
        self.assertIn("Précédent", source)
        self.assertIn("Accueil", source)
        self.assertIn("Suivant", source)

    def test_official_help_is_really_loaded_before_tree_sync(self):
        source = (ROOT / "cogs" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('_OFFICIAL_HELP_EXTENSION = "cogs.help"', source)
        self.assertIn("await _load_official_help(bot)", source)
        self.assertIn("_ORIGINAL_LOAD_EXTENSION(bot, _OFFICIAL_HELP_EXTENSION)", source)

    def test_official_prefix_help_cannot_be_repatched_with_ctx_callback(self):
        bootstrap = (ROOT / "cogs" / "plain_text_all_extension.py").read_text(encoding="utf-8")
        polish = (ROOT / "cogs" / "final_runtime_polish.py").read_text(encoding="utf-8")
        self.assertIn("prefix_command._sentrix_official_help_owner = True", bootstrap)
        self.assertIn("prefix_command._sentrix_context_is_internal = True", bootstrap)
        self.assertIn('getattr(command, "_sentrix_official_help_owner", False)', polish)
        self.assertIn('getattr(command, "_sentrix_context_is_internal", False)', polish)
        marker_index = polish.index('getattr(command, "_sentrix_official_help_owner", False)')
        callback_index = polish.index("command.callback = root_only_callback")
        self.assertLess(marker_index, callback_index)
        self.assertIn("if is_official_help:", polish)
        self.assertIn("return\n\n    from . import help_clean_style", polish)

    def test_final_command_transport_uses_only_official_embed_renderer(self):
        source = (ROOT / "cogs" / "final_interaction_policy.py").read_text(encoding="utf-8")
        self.assertIn("from utils import embeds as sentrix_embeds", source)
        self.assertIn("sentrix_embeds.standard", source)
        self.assertIn("sentrix_embeds.error", source)
        self.assertNotIn("from utils import premium_style", source)
        self.assertNotIn("premium_style.style_kwargs", source)

    def test_real_listener_logger_uses_native_refs_and_audit_correlation(self):
        source = (ROOT / "cogs" / "logs.py").read_text(encoding="utf-8")
        self.assertIn('return f"<@{int(user_id)}>"', source)
        self.assertIn('return f"<@&{int(role_id)}>"', source)
        self.assertIn('return f"<#{int(channel_id)}>"', source)
        self.assertIn("entry.target", source)
        self.assertIn("max_age_seconds", source)
        self.assertIn("after.jump_url", source)
        self.assertIn("AuditLogAction.kick", source)
        self.assertIn("log_service.send_log", source)

    def test_old_v_layers_are_gone(self):
        for rel in (
            "cogs/sentrix_visual_refactor_v70.py",
            "cogs/sentrix_profile_refactor_v70.py",
            "cogs/sentrix_log_safety_v71.py",
            "cogs/help_catalog_v72.py",
            "tests/test_visual_v70.py",
        ):
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_runtime_no_longer_installs_competing_log_help_layers(self):
        source = (ROOT / "cogs" / "__init__.py").read_text(encoding="utf-8")
        forbidden = (
            "premium_logs_v2", "log_rectangle_v25", "log_reference_layout_v26",
            "sentrix_visual_refactor_v70", "sentrix_log_safety_v71", "help_catalog_v72",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
