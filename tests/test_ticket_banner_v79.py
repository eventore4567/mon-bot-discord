from pathlib import Path


def test_ticket_public_panel_uses_sentrix_ticket_banner():
    source = Path("web/dashboard_v62_dense.py").read_text(encoding="utf-8")
    assert 'sx_panels.depuis_embed(cog.build_panel_embed(panel), kind="tickets")' in source
    assert "await sx_panels.envoyer(channel, panel_view)" in source
    assert "components_v2" in source


def test_ticket_persistent_view_restores_full_banner_layout():
    source = Path("cogs/tickets.py").read_text(encoding="utf-8")
    assert 'sx_panels.depuis_embed(self.build_panel_embed(panel), kind="tickets")' in source
    assert "self.bot.add_view(persistent, message_id=panel[\"message_id\"])" in source


def test_deferred_panel_fallback_never_reuses_closed_banner_file():
    source = Path("utils/sentrix_panels.py").read_text(encoding="utf-8")
    assert "def _rafraichir_fichiers_apres_echec_edit()" in source
    assert "I/O operation on closed file" in source
    assert source.count("_rafraichir_fichiers_apres_echec_edit()") >= 3
