from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_operational_ticket_controls_are_kept():
    source = (ROOT / "cogs" / "ticket_controls_minimal.py").read_text(encoding="utf-8")
    for key in (
        '"claim"',
        '"unclaim"',
        '"add"',
        '"remove"',
        '"rename"',
        '"transfer"',
        '"note"',
        '"bump"',
        '"close"',
    ):
        assert key in source
    assert 'Utilisez uniquement « Prendre en charge » ou « Fermer »' not in source
    assert "tickets_mod.DEFAULT_ENABLED_BUTTONS = set(_ALLOWED_KEYS)" in source


def test_embed_dashboard_finish_does_not_depend_on_old_exact_render_source():
    source = (ROOT / "sentrix_final_product_finish.py").read_text(encoding="utf-8")
    assert "embed_dashboard.EMBED_CSS" in source
    assert "embed_dashboard.EMBED_JS" in source
    assert 'data-tab="embeds"' in source
    assert "renderEmbedPage" in source
    assert "installRenderHook" in source
    assert "sendCurrentEmbed" in source
    assert 'id="sentrix-embed-runtime-finish"' in source


def test_final_finish_runs_after_product_runtime():
    source = (ROOT / "cogs" / "sentrix_regression_fix.py").read_text(encoding="utf-8")
    regression = source.index("await _regression_setup(bot)")
    product = source.index("await install_runtime(bot)")
    final = source.index("await install_final_product_finish(bot)")
    assert regression < product < final


def test_ticket_setup_remains_dashboard_only_while_runtime_reopen_survives():
    product = (ROOT / "sentrix_product_update.py").read_text(encoding="utf-8")
    tickets = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")
    assert '"ticketsetup"' in product
    assert '"ticketpanel"' in product
    assert '"ticketconfig"' in product
    assert "TICKET_CONFIG_COMMANDS" in product
    assert '@commands.hybrid_command(name="ticket-reopen"' in tickets
