"""Non-network checks for SentriX presentation feedback and refresh UI."""
from types import SimpleNamespace

import discord

from cogs.presentation import _old_panel, presentation_panel
from cogs.presentation_feedback import (
    BUTTON_ID,
    COOLDOWN_SECONDS,
    FeedbackButton,
    FeedbackModal,
    FeedbackPersistentView,
)


def test_feedback_registration_survives_restart():
    view = FeedbackPersistentView(SimpleNamespace())
    assert view.timeout is None
    assert view.is_persistent()
    assert any(isinstance(item, FeedbackButton) and item.custom_id == BUTTON_ID
               for item in view.children)


def test_presentation_has_install_and_feedback_buttons():
    view = presentation_panel(
        "https://discord.com/oauth2/authorize?client_id=123",
        english=True,
        bot=SimpleNamespace(),
    )
    assert isinstance(view, discord.ui.LayoutView)
    buttons = [
        item
        for container in view.children
        for row in getattr(container, "children", ())
        for item in getattr(row, "children", ())
        if isinstance(item, discord.ui.Button)
    ]
    assert any(item.label == "Add SentriX" and item.url for item in buttons)
    assert any(item.label == "Give feedback" and item.custom_id == BUTTON_ID
               for item in buttons)


def test_feedback_modal_keeps_text_bounded():
    modal = FeedbackModal(SimpleNamespace(), english=False)
    assert modal.feedback.min_length == 10
    assert modal.feedback.max_length == 1200
    assert COOLDOWN_SECONDS >= 600


def test_legacy_presentation_detection_is_strict():
    class Component:
        def to_dict(self):
            return {"text": "SentriX /setup", "button": {"label": "Add SentriX"}}

    old = SimpleNamespace(author=SimpleNamespace(id=123), components=[Component()])
    assert _old_panel(old, 123)
    assert not _old_panel(old, 999)
    unrelated = SimpleNamespace(author=SimpleNamespace(id=123), components=[])
    assert not _old_panel(unrelated, 123)
