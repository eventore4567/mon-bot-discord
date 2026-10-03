from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_boot_uses_native_sentrix_setup_core_not_legacy_external_layer():
    source = _source("cogs/__init__.py")
    assert "setup_core_v119" in source
    assert "install_setup_core_v119" in source
    assert "setup_oxyde_v69" not in source
    assert "Control Center" not in source


def test_active_setup_layers_have_no_external_bot_style_names():
    paths = (
        "cogs/setup_core_v119.py",
        "cogs/setup_polish_v70.py",
        "cogs/setup_components_v73.py",
        "cogs/setup_experience_v74.py",
        "cogs/setup_security_choice_v75.py",
    )
    forbidden = (
        "oxyde",
        "control center",
        "draftbot",
        "carl-bot",
        "ticket tool",
    )
    for path in paths:
        source = _source(path).casefold()
        for name in forbidden:
            assert name not in source, f"{path}: legacy identity {name}"


def test_final_security_setup_never_bootstraps_honeypot_resources():
    source = _source("cogs/setup_security_choice_v75.py")
    assert "create_or_refresh_system" not in source
    assert "def _honeypot_resources_ready" in source
    assert "SentriX ne crée rien automatiquement" in source
    assert "v74.v73.poser_banniere(container)" in source
    assert "SENTRIX CORE · Configuration · setup" in source


def test_ticket_setup_activation_does_not_create_default_configuration():
    source = _source("cogs/setup_experience_v74.py")
    start = source.index("    async def _build_tickets")
    end = source.index("\n    async def _build_moderation", start)
    block = source[start:end]

    assert "Configuration rapide / réparer" not in block
    assert "Activer avec les réglages par défaut" not in block
    assert "ensure_ticket_configuration(" not in block
    assert 'label="Activer"' in block
    assert "core.set_module_enabled(" in block
    assert "Tout personnaliser" in block


def test_rolepanel_uses_only_existing_roles():
    source = _source("cogs/rolepanel_notifications.py")
    start = source.index("    async def _existing_roles")
    end = source.index("\n    async def _save_panel", start)
    block = source[start:end]

    assert "guild.create_role(" not in block
    assert "discord.utils.get(guild.roles" in block

    command_start = source.index("    async def rolepanel(self, ctx")
    command_end = source.index("\n    @commands.command(", command_start)
    command_block = source[command_start:command_end]
    assert "SentriX ne crée aucun rôle automatiquement." in command_block


def test_setup_core_keeps_current_clean_components_layout():
    v73 = _source("cogs/setup_components_v73.py")
    v75 = _source("cogs/setup_security_choice_v75.py")

    assert "SENTRIX CORE · Configuration · setup" in v73
    assert "discord.ui.Container" in v73
    assert "poser_banniere(" in v73
    assert "SENTRIX CORE · Configuration · setup" in v75
    assert "poser_banniere(" in v75


def test_ticket_and_role_panels_do_not_duplicate_sentrix_brand():
    tickets = _source("cogs/tickets.py")
    roles = _source("cogs/rolepanel_notifications.py")

    assert 'titre="SentriX — Ticket ouvert"' not in tickets
    assert 'titre="SentriX — Tickets"' not in tickets
    assert 'titre="Ticket ouvert"' in tickets
    assert 'titre="Tickets"' in tickets
    assert 'f"SentriX — {titre}"' not in roles



def test_infinite_counter_error_assistant_is_native_sentrix_and_self_cleaning():
    source = _source("cogs/infinite_counter.py")

    assert "class InfiniteMistakeView(discord.ui.LayoutView)" in source
    assert "sentrix_emojis.emoji(\"error\")" in source
    assert "sentrix_emojis.partiel(\"message_edit\")" in source
    assert "sentrix_emojis.partiel(\"trash\")" in source
    assert 'label="Je me suis trompé"' in source
    assert 'label="Supprimer ce message"' in source
    assert "await self._delete_notice()" in source
    assert "await self._delete_original()" in source
    assert "async def on_timeout(self)" in source


def test_infinite_counter_staff_override_is_guarded_and_stale_safe():
    source = _source("cogs/infinite_counter.py")

    assert "perms.manage_messages" in source
    assert "perms.manage_guild" in source
    assert "perms.administrator" in source
    assert 'int(row["next_number"]) != self.expected' in source
    assert "SET next_number=?,last_user_id=?,updated_at=?" in source
    assert "self.accepted_override = True" in source


def test_infinite_counter_invalid_message_pings_only_the_author():
    source = _source("cogs/infinite_counter.py")

    assert 'content=f"<@{message.author.id}>"' in source
    assert "users=[message.author]" in source
    assert "everyone=False" in source
    assert "roles=False" in source



def test_infinite_counter_assistant_pings_only_author_and_waits_one_minute():
    source = _source("cogs/infinite_counter.py")

    assert "super().__init__(timeout=60)" in source
    assert 'content=f"<@{message.author.id}>"' in source
    assert "users=[message.author]" in source
    assert "everyone=False" in source
    assert "roles=False" in source
    assert "Sans réponse, ton message sera supprimé automatiquement dans 1 minute." in source



def test_infinite_counter_timeout_deletes_only_when_member_did_not_answer():
    source = _source("cogs/infinite_counter.py")

    assert "self.responded = False" in source
    assert "self.responded = True" in source
    assert "if not self.responded and not self.accepted_override:" in source
    mistake = source[source.index("async def _mistake"):source.index("async def _correct_counter")]
    assert "self.stop()" in mistake



def test_security_setup_has_per_filter_bypass_and_strict_channel_controls():
    source = _source("cogs/setup_v2_ui.py")

    assert "SECURITY_POLICY_FILTERS" in source
    assert "class SecurityPolicyView(discord.ui.View)" in source
    assert "Rôles bypass ·" in source
    assert "Salons stricts ·" in source
    assert 'label="Retirer rôles bypass"' in source
    assert 'label="Aucun salon strict"' in source
    assert "set_security_filter_policy" in source
    block = source[
        source.index("class SecurityPolicyView"):
        source.index("class PermissionRoleSelect")
    ]
    assert "guild.create_text_channel" not in block


def test_dashboard_security_policy_has_clean_per_filter_multi_select_ui_and_api():
    api = _source("web/dashboard_api_security.py")
    ui = _source("web/dashboard_ui/js/30_modules.js")

    assert '/security/filter-policies' in api
    assert "security_filter_bypass_roles" in api
    assert "security_filter_strict_channels" in api
    assert "Exceptions par protection" in ui
    assert 'id="securityPolicyBypassRoles"' in ui
    assert 'id="securityPolicyStrictChannels"' in ui
    assert "Salons stricts — aucun bypass" in ui
    assert "Retirer les rôles bypass" in ui
