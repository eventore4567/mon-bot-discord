"""Verify moderation configuration now lives in the Setup control panel."""
import os
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import setup_control_center as ui


def test_moderation_setup_has_advanced_controls():
    class Bot:
        pass

    class Guild:
        id = 321

    view = ui.SetupView(Bot(), Guild(), author_id=1)
    view.category = "moderation"
    view.avance = True
    view.render()
    assert any(isinstance(c, ui.SetupIgnoredChannelSelect) for c in view._commandes)
    labels = [getattr(c, "label", None) for c in view._commandes]
    assert "Accès aux commandes" in labels
    assert "Seuil des warns" in labels


def test_setup_command_modals_limit_untrusted_input():
    parent = type("Parent", (), {})()
    modal = ui.SetupCommandAccessModal(parent)
    assert modal.command_name.max_length == 100
    assert modal.operation.required
    warn = ui.SetupWarnThresholdModal(parent)
    assert warn.limit.max_length == 4
