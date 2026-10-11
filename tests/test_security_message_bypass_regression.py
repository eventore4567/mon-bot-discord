"""Régressions des exemptions des filtres de messages SentriX.

Les permissions Discord de gestion doivent rester exemptées de l'anti-lien,
anti-invitation, anti-spam et anti-scam locaux. Une simple permission
de modération ou un nom de rôle ne donne aucun passe-droit.
"""
import os
from types import SimpleNamespace

# L'import de config exige un token, sans utiliser de véritable secret en CI.
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.security_member_bypass import can_bypass_message_filters


def _member(**permissions):
    return SimpleNamespace(guild_permissions=SimpleNamespace(**permissions))


def test_administrator_bypasses_message_filters():
    assert can_bypass_message_filters(_member(administrator=True, manage_guild=False))


def test_manage_guild_bypasses_message_filters():
    assert can_bypass_message_filters(_member(administrator=False, manage_guild=True))


def test_partial_moderation_permissions_do_not_bypass():
    assert not can_bypass_message_filters(
        _member(administrator=False, manage_guild=False, manage_messages=True, ban_members=True)
    )


def test_role_name_does_not_grant_bypass():
    member = _member(administrator=False, manage_guild=False)
    member.roles = [SimpleNamespace(name="Admin")]
    assert not can_bypass_message_filters(member)


def test_unknown_member_permissions_fail_closed():
    assert not can_bypass_message_filters(None)
    assert not can_bypass_message_filters(SimpleNamespace(guild_permissions=None))
