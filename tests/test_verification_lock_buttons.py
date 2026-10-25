"""La disponibilité du raccourci suit le panneau persisté, non un wizard recommencé."""
from types import SimpleNamespace

from cogs.verify_setup_interactive_v78 import VerifySetupView
from sentrix_verification_v96 import VerificationSetupView


def _v78(message_id):
    return VerifySetupView(
        SimpleNamespace(),
        SimpleNamespace(id=123, get_channel=lambda _id: None, get_role=lambda _id: None),
        77, channel_id=12, role_id=5,
        rules_text="Règlement", image_url="",
        captcha_enabled=True, captcha_max_attempts=3,
        message_id=message_id,
    )


def test_v78_lock_button_disabled_if_rules_not_published():
    view = _v78(None)
    button = next(child for child in view.children if getattr(child, "label", None) == "Verrouiller les salons")
    assert button.disabled is True


def test_v78_lock_button_active_on_reopen_after_publication():
    view = _v78(54321)
    button = next(child for child in view.children if getattr(child, "label", None) == "Verrouiller les salons")
    assert button.disabled is False


def test_v96_exposes_lock_button_without_requiring_republish():
    bot = SimpleNamespace(get_guild=lambda _id: None)
    view = VerificationSetupView(
        SimpleNamespace(bot=bot), guild_id=123, author_id=77,
        has_existing_panel=True,
    )
    button = next(child for child in view.children if getattr(child, "label", None) == "Verrouiller les salons")
    assert button.disabled is False
