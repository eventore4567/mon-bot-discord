from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
ROOT = Path(__file__).resolve().parents[1]


def test_departures_are_a_real_setup_category():
    from cogs import setup_components_v73 as v73
    from cogs import setup_experience_v74 as v74

    assert "goodbye" in v73.CATEGORY_ORDER
    assert "goodbye" in v74.CATEGORY_ORDER
    assert v73.CATEGORY_META["goodbye"][1] == "Départs"

    setup_source = (ROOT / "cogs" / "setup_control_center.py").read_text()
    assert 'elif self.category == "goodbye"' in setup_source
    assert 'if cle == "goodbye"' in setup_source


def test_command_channels_are_separate_from_automod_and_plain_text():
    from cogs.command_channel_gate import BLOCKED_MESSAGE

    assert BLOCKED_MESSAGE == "Les commandes sont désactivées dans ce salon."

    schema = (ROOT / "database" / "db.py").read_text()
    gate = (ROOT / "cogs" / "command_channel_gate.py").read_text()

    assert "CREATE TABLE IF NOT EXISTS command_blocked_channels" in schema
    assert "CREATE TABLE IF NOT EXISTS command_channel_blocks" in schema
    assert "SELECT 1 FROM command_blocked_channels" in gate
    assert "SELECT 1 FROM command_channel_blocks" in gate
    assert "panels.texte_court" in gate
    assert "class CommandChannelBlocked" in gate
    assert "_sentrix_channel_blocked" not in gate
    assert "ignored_channels" not in gate


def test_dashboard_can_choose_blocked_command_channels():
    backend = (ROOT / "web" / "setup_dashboard.py").read_text()
    frontend = (ROOT / "web" / "dashboard_ui" / "js" / "40_tools.js").read_text()

    assert '"command_blocked_channels"' in backend
    assert 'action == "command_channels"' in backend
    assert "commandBlockedChannels" in frontend
    assert "action: 'command_channels'" in frontend
    assert '"command_channel_rules"' in backend
    assert 'action == "command_channel_rule"' in backend
    assert "commandRuleChannels" in frontend
    assert "commandRuleCommands" in frontend
    assert "multiCommandPicker" in frontend
    assert frontend.index("Bloquer toutes les commandes") < frontend.index("card('Commandes'")
    assert frontend.index("Bloquer certaines commandes") < frontend.index("card('Commandes'")


def test_commands_access_page_is_visible_in_main_navigation():
    nav = (ROOT / "web" / "dashboard_ui" / "js" / "10_nav.js").read_text()
    boot = (ROOT / "web" / "dashboard_ui" / "js" / "90_boot.js").read_text()

    assert nav.count("['Administration'") == 1
    assert "['Administration', [['access', 'Commandes & accès'], ['settings', 'Paramètres'], ['backups', 'Sauvegardes & historique']]]" in nav
    assert "access: renderAccess" in boot



def test_dashboard_navigation_does_not_shift_layout():
    boot = (ROOT / "web" / "dashboard_ui" / "js" / "90_boot.js").read_text()
    css = (ROOT / "web" / "dashboard_ui" / "app.css").read_text()

    assert "navigation && !hadContent" in boot
    assert "navigation ? setTimeout" not in boot
    assert "scrollbar-gutter:stable" in css

    transition = css[css.index("#content.page-leave"):css.index(".grid{", css.index("#content.page-leave"))]
    assert "translateY" not in transition
    assert "scale(" not in transition


def test_dashboard_exposes_and_reuses_server_emojis():
    dashboard = (ROOT / "web" / "dashboard.py").read_text()
    hotfix = (ROOT / "web" / "dashboard_oxyde_hotfix.py").read_text()
    core = (ROOT / "web" / "dashboard_ui" / "js" / "00_core.js").read_text()
    roles = (ROOT / "web" / "dashboard_ui" / "js" / "35_community.js").read_text()
    modules = (ROOT / "web" / "dashboard_ui" / "js" / "30_modules.js").read_text()
    ticket_actions = (ROOT / "web" / "dashboard_ui" / "js" / "38_tickets.js").read_text()

    assert '"emojis": emojis' in dashboard
    assert '"emojis": emojis' in hotfix
    assert "function guildEmojis()" in core
    assert "function bindEmojiPickers" in core
    assert "pickDialog({" not in core[core.index("function emojiControl"):core.index("function resourceIssue")]
    assert "emoji-picker-inline" in core
    css = (ROOT / "web" / "dashboard_ui" / "app.css").read_text()
    assert ".emoji-picker-inline" in css
    assert "emojiControl('rrEmoji')" in roles
    assert "emojiControl('ttEmoji'" in modules
    assert "emojiControl('reactEmojiInput'" in modules
    assert "emojiControl('ticketActionEmoji'" in ticket_actions

def test_roles_offer_simple_no_emoji_and_reaction_modes():
    backend = (ROOT / "web" / "setup_dashboard.py").read_text()
    frontend = (ROOT / "web" / "dashboard_ui" / "js" / "35_community.js").read_text()
    runtime = (ROOT / "cogs" / "verification.py").read_text()

    assert "Créer sans emoji" in frontend
    assert "Créer avec emoji" in frontend
    assert "Texte affiché (optionnel)" in frontend
    assert "role_ids: roleIds" in frontend
    assert "label: $('rrLabel').value.trim()" in frontend

    assert 'payload.get("role_ids")' in backend
    assert "self_role_items" in backend
    assert "self_role_items" in runtime



def test_welcome_departure_backgrounds_and_level_card_are_simple():
    schema = (ROOT / "database" / "db.py").read_text()
    dashboard = (ROOT / "web" / "dashboard.py").read_text()
    welcome = (ROOT / "cogs" / "setup_v2_completion.py").read_text()
    cards = (ROOT / "utils" / "member_event_cards.py").read_text()
    visual = (ROOT / "utils" / "visual_v5.py").read_text()
    workflow = (ROOT / ".github" / "workflows" / "command-sweep.yml").read_text()

    assert "goodbye_image_url TEXT" in schema
    assert '"goodbye_image_url"' in dashboard
    assert "fetch_background_image(image_url)" not in welcome
    assert "_without_duplicate_member_mention" in welcome
    assert "background_preset=background_preset" in welcome
    assert "EVENT_BACKGROUND_PRESETS" in cards
    assert "Carte sobre façon Discord : avatar rond, gros titre, zéro couleur néon." in cards
    assert 'kind == "level"' in cards
    assert 'title = "Félicitations !"' in cards
    assert 'line2 = "vous avez atteint"' in cards
    assert 'line3 = f"le niveau {current_level}"' in cards
    assert 'title = "Bienvenue"' in cards
    assert 'title = "À bientôt"' in cards
    assert "_ACCENT" not in cards
    assert "if: github.event_name != 'push'" in workflow



def test_module_activation_requires_real_resources():
    core = (ROOT / "cogs" / "setup_v2_core.py").read_text()
    control = (ROOT / "cogs" / "control_center_v3.py").read_text()
    setup_v74 = (ROOT / "cogs" / "setup_experience_v74.py").read_text()

    assert "class ModuleSetupRequired(ValueError)" in core
    assert "async def module_activation_issue(" in core
    assert "Choisis d’abord le salon de bienvenue." in core
    assert "Choisis d’abord le salon de départ." in core
    assert "Choisis d’abord le salon des montées de niveau." in core
    assert '"welcome_message": "welcome"' not in core
    assert '"welcome_image_url": "welcome"' not in core
    assert '"goodbye_message": "goodbye"' not in core
    assert "except setup_v2_core.ModuleSetupRequired" in control
    assert "except core.ModuleSetupRequired" in setup_v74


def test_level_system_requires_or_reuses_a_level_channel_and_stays_synced():
    source = (ROOT / "cogs" / "feature_systems.py").read_text()
    assert "salon: discord.TextChannel = None" in source
    assert 'set_guild_config(ctx.guild.id, "level_channel", salon.id)' in source
    assert "module_state(self.bot, ctx.guild.id, module)" in source
    assert "setup_v2_core.set_module_enabled(" in source
    assert "choisis le salon des montées de niveau" in source


def test_test_events_command_previews_all_three_without_mutating_member_data():
    source = (ROOT / "cogs" / "levels.py").read_text()
    assert '@commands.command(' in source[source.index('name="test-events"') - 160:source.index('name="test-events"')]
    assert '@commands.hybrid_command(' not in source[source.index('name="test-events"') - 160:source.index('name="test-events"')]
    assert '@app_commands.describe(niveau=' not in source[source.index('name="test-events"') - 220:source.index('name="test-events"') + 220]
    assert 'await self.bot.db.set_guild_config(ctx.guild.id, field, fallback.id)' in source
    assert '"welcome_message"' in source
    assert '"goodbye_message"' in source
    assert 'for module in ("welcome", "goodbye", "levels")' in source
    assert "setup_v2_core.set_module_enabled(" in source
    assert 'set_system_feature(self.bot.db, ctx.guild.id, "levels", True)' not in source
    assert "presentation_row is None" in source
    assert "setup_v2_completion._send_welcome(" in source
    assert "setup_v2_completion._send_goodbye(" in source
    assert "self._send_level_announcement(" in source
    assert "ping=True" in source
    assert 'colour=discord.Colour(0x4E5058)' in source
    assert "content=member.mention if ping else None" in source
    assert "Aucune XP, aucun rôle et aucune donnée membre n’ont été modifiés." in source
    assert "Aucun salon n'est créé" in source



def test_welcome_and_goodbye_share_the_same_direct_embed_renderer():
    source = (ROOT / "cogs" / "setup_v2_completion.py").read_text()
    cards = (ROOT / "utils" / "member_event_cards.py").read_text()
    assert 'colour=discord.Colour(0x4E5058)' in source
    assert 'kind="welcome"' in source
    assert 'kind="goodbye"' in source
    goodbye = source[source.index("async def _send_goodbye"):source.index("def _replace_welcome_listeners")]
    assert "await channel.send(" in goodbye
    assert "panels.depuis_embed(panel)" not in goodbye
    assert "_paste_avatar(image, avatar_bytes, name)" in cards



def test_feature_system_commands_do_not_double_write_through_db_only_facade():
    source = (ROOT / "cogs" / "feature_systems.py").read_text()
    assert "set_system_feature(" not in source
    assert "setup_v2_core.set_module_enabled(" in source
    assert "get_system_features(self.bot.db, ctx.guild.id, fresh=True)" in source



def test_event_backgrounds_are_limited_to_three_presets_and_pings_are_forced():
    dashboard = (ROOT / "web" / "dashboard.py").read_text()
    frontend = (ROOT / "web" / "dashboard_ui" / "js" / "30_modules.js").read_text()
    setup = (ROOT / "cogs" / "setup_v2_completion.py").read_text()
    legacy_setup = (ROOT / "cogs" / "setup_v2_ui.py").read_text()

    for preset in ("preset:dark", "preset:gray", "preset:light"):
        assert preset in dashboard
        assert preset in frontend
    assert "URL bannière / image" not in setup
    assert "URL image de bienvenue" not in legacy_setup
    assert "URL image de départ" not in legacy_setup
    assert "Aucune image personnalisée" in frontend
    assert 'content=(None if test else member.mention)' in setup
    assert 'content = goodbye_body if test else f"{member.mention}\\n{goodbye_body}"' in setup
    assert '"ping": True' in setup
    assert '"goodbye_ping": True' in setup
