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
    assert "SENTRIX CORE · Configuration · setup" not in source


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

    assert "SENTRIX CORE · Configuration · setup" not in v73
    assert "discord.ui.Container" in v73
    assert "poser_banniere(" in v73
    assert "SENTRIX CORE · Configuration · setup" not in v75
    assert "poser_banniere(" in v75


def test_ticket_and_role_panels_do_not_duplicate_sentrix_brand():
    tickets = _source("cogs/tickets.py")
    roles = _source("cogs/rolepanel_notifications.py")

    assert 'titre="SentriX — Ticket ouvert"' not in tickets
    assert 'titre="SentriX — Tickets"' not in tickets
    # Ce test interrogeait le TEXTE SOURCE de cogs/tickets.py et cherchait
    # `titre="Ticket ouvert"`. La confirmation d'ouverture a déménagé dans
    # services/ticket_panels_v3.ticket_created_confirmation : la chaîne a
    # disparu, le test est devenu rouge, et une garde de build rouge bloque
    # TOUT déploiement — alors que le comportement visé n'avait pas changé.
    #
    # Ce qui compte vraiment : le titre ne répète pas la marque. On le vérifie
    # donc sur le panneau RÉELLEMENT construit.
    from services import ticket_panels_v3

    panneau = ticket_panels_v3.ticket_created_confirmation(
        ticket_number=42, ticket_type="Support",
        guild_id=1, channel_id=2, channel_name="ticket-42",
    )
    # TicketCardV3 est une LayoutView : son titre vit dans un TextDisplay.
    morceaux = []

    def _lire(item):
        contenu = getattr(item, "content", None)
        if isinstance(contenu, str):
            morceaux.append(contenu)
        for enfant in list(getattr(item, "children", ()) or ()):
            _lire(enfant)

    _lire(panneau)
    # Le TITRE seul : la ligne « ## … ». La marque a sa place dans le
    # surtitre et le pied (« SENTRIX / CENTRE DE SUPPORT »), pas dans le titre.
    titre = next(
        (ligne[3:].strip() for bloc in morceaux for ligne in bloc.split("\n")
         if ligne.startswith("## ")),
        "",
    )
    assert titre and "SentriX" not in titre, f"marque répétée : {titre!r}"
    assert 'titre="Tickets"' in tickets
    assert 'f"SentriX — {titre}"' not in roles



def test_infinite_counter_invalid_messages_are_deleted_silently():
    source = _source("cogs/infinite_counter.py")
    invalid = source[
        source.index("    async def _invalid("):
        source.index('    @commands.group(name="infinit"', source.index("    async def _invalid("))
    ]

    assert "await message.delete()" in invalid
    assert ".channel.send(" not in invalid
    assert "send_message(" not in invalid
    assert "panels." not in invalid
    assert "InfiniteMistakeView" not in source
    assert 'content=f"<@{message.author.id}>"' not in source


def test_infinite_counter_keeps_progression_and_same_member_guard():
    source = _source("cogs/infinite_counter.py")

    assert 'int(row["last_user_id"]) == message.author.id' in source
    assert 'reason="consecutive"' in source
    assert "SET next_number=?,last_user_id=?,updated_at=?" in source
    assert "next_number=1" not in source


def test_infinite_counter_no_longer_has_public_correction_assistant():
    source = _source("cogs/infinite_counter.py")

    for obsolete in (
        "class InfiniteMistakeView",
        'label="Je me suis trompé"',
        'label="Supprimer ce message"',
        "super().__init__(timeout=60)",
        "Sans réponse, ton message sera supprimé automatiquement dans 1 minute.",
        "self.accepted_override",
        "self.responded",
    ):
        assert obsolete not in source


def test_security_setup_has_full_premium_center_and_per_filter_exceptions():
    source = _source("cogs/setup_v2_ui.py")

    assert "SECURITY_POLICY_FILTERS" in source
    assert "SECURITY_CENTER_PROTECTIONS" in source
    assert "class SecurityPolicyView(discord.ui.View)" in source
    for marker in (
        '"antispam"',
        '"antiraid"',
        '"antinuke"',
        '"security_permissions"',
        '"honeypot"',
        '"verification"',
        "Rôles bypass ·",
        "Salons stricts ·",
        "set_security_filter_policy",
        "raid_intensity",
        "honeypot_action",
        "verification_threshold",
    ):
        assert marker in source
    block = source[
        source.index("class SecurityPolicyView"):
        source.index("class PermissionRoleSelect")
    ]
    assert "guild.create_text_channel" not in block


def test_dashboard_security_has_full_control_center_and_per_filter_policy():
    api = _source("web/dashboard_api_security.py")
    ui = _source("web/dashboard_ui/js/30_modules.js")

    assert '/security/filter-policies' in api
    assert "_PROTECTION_CATALOG" in api
    assert "security_filter_bypass_roles" in api
    assert "security_filter_strict_channels" in api
    assert "Centre de sécurité" in ui
    assert "Messages" in ui
    assert "Arrivées" in ui
    assert "Serveur" in ui
    assert 'data-security-config=' in ui
    assert 'id="securityPolicyBypassRoles"' in ui
    assert 'id="securityPolicyStrictChannels"' in ui
    assert "membre ou rôle exempté → salon strict → protection normale" in ui
    assert "security_filter_bypass_members" in api
    assert 'id="securityPolicyMemberSearch"' in ui
    assert "Retirer les membres exemptés" in ui
    assert "Retirer les rôles bypass" in ui
