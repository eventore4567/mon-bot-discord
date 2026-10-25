"""Aperçu du verrouillage : toute décision modifiée exige une nouvelle validation."""
from types import SimpleNamespace

from cogs.verify_setup_interactive_v78 import plan_signature


class Role:
    def __init__(self, role_id, name="Vérifié"):
        self.id = role_id
        self.name = name


class Channel:
    def __init__(self, *, name="general", public=True):
        self.id = 10
        self.name = name
        self.category_id = 50
        self.permissions_synced = False
        self.public = public
        self.overwrites = {}

    def permissions_for(self, _role):
        return SimpleNamespace(view_channel=self.public)


def _args():
    everyone = Role(1, "@everyone")
    role = Role(2)
    channel = Channel()
    guild = SimpleNamespace(default_role=everyone, channels=[channel])
    plan = SimpleNamespace(
        gate=[channel], secure_sensitive=[], protected={50: "catégorie protégée"},
        untouched={}, log_destinations=[], staff_channels=[],
    )
    state = {"channel_id": 99, "role_id": 2, "message_id": 123}
    return plan, guild, role, state, channel


def _sig(plan, guild, role, state):
    return plan_signature(plan, role=role, state=state, guild=guild)


def test_same_published_rules_and_permissions_keep_same_signature():
    plan, guild, role, state, _ = _args()
    assert _sig(plan, guild, role, state) == _sig(plan, guild, role, dict(state))


def test_changing_published_role_invalidates_approval():
    plan, guild, role, state, _ = _args()
    previous = _sig(plan, guild, role, state)
    state["role_id"] = 3
    assert _sig(plan, guild, Role(3), state) != previous


def test_changing_rules_panel_invalidates_approval():
    plan, guild, role, state, _ = _args()
    previous = _sig(plan, guild, role, state)
    state["message_id"] = 124
    assert _sig(plan, guild, role, state) != previous


def test_changing_effective_public_access_invalidates_approval():
    plan, guild, role, state, channel = _args()
    previous = _sig(plan, guild, role, state)
    channel.public = False
    assert _sig(plan, guild, role, state) != previous


def test_changing_any_explicit_staff_overwrite_invalidates_approval():
    plan, guild, role, state, channel = _args()
    previous = _sig(plan, guild, role, state)
    staff = Role(43, "Staff")
    channel.overwrites[staff] = SimpleNamespace(view_channel=True)
    assert _sig(plan, guild, role, state) != previous


def test_channel_rename_invalidates_approval_even_if_bucket_is_same():
    plan, guild, role, state, channel = _args()
    previous = _sig(plan, guild, role, state)
    channel.name = "discussions"
    assert _sig(plan, guild, role, state) != previous


def test_saved_log_destination_change_invalidates_approval():
    plan, guild, role, state, channel = _args()
    previous = _sig(plan, guild, role, state)
    plan.log_destinations.append(channel)
    assert _sig(plan, guild, role, state) != previous
