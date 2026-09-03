"""Le rôle de vérification (+verify-setup / configurable dans /setup) était donné
IMMÉDIATEMENT au clic sur "J'ai lu les règles", sans aucun filtre anti-bot. Un CAPTCHA
image (code à recopier) s'intercale désormais entre le clic et l'attribution réelle du
rôle : cogs/verification.py reste l'unique système de règles/vérification de SentriX,
rien n'a été dupliqué à côté.

Couverture :
- génération de code/image (utils PIL déjà présents ailleurs dans SentriX) ;
- cycle de vie complet d'une session (tentatives, régénération de code à chaque échec,
  verrouillage après le nombre configuré de tentatives, expiration, nettoyage) ;
- role_grant_problem() (permission Discord manquante, hiérarchie, rôle managé/@everyone) ;
- anti-spam du bouton ;
- le flux complet do_verify -> CAPTCHA -> handle_captcha_submission -> rôle attribué,
  avec un faux bot/DB réels (pas seulement des assertions sur le texte source).
"""
from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import verification as v  # noqa: E402
from database.db import Database  # noqa: E402


def test_generate_captcha_code_uses_unambiguous_alphabet():
    for _ in range(200):
        code = v._generate_captcha_code()
        assert len(code) == v._CAPTCHA_CODE_LENGTH
        assert all(character in v._CAPTCHA_ALPHABET for character in code)
    # 0/O et 1/I sont volontairement exclus : trop ambigus à l'oeil sur une petite image.
    # L reste (visuellement distinct d'un 1/I en police grasse).
    assert not set("01IO") & set(v._CAPTCHA_ALPHABET)


def test_render_captcha_image_is_a_valid_png_at_expected_size():
    from PIL import Image
    import io

    image_bytes = v._render_captcha_image("7K3PL")
    assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    image = Image.open(io.BytesIO(image_bytes))
    assert image.size == (260, 100)


def test_click_is_spam_only_blocks_rapid_repeats():
    guild_id, user_id = 111, 222
    assert v._click_is_spam(guild_id, user_id) is False
    assert v._click_is_spam(guild_id, user_id) is True
    # Un autre utilisateur n'est jamais bloqué par le clic de quelqu'un d'autre.
    assert v._click_is_spam(guild_id, user_id + 1) is False


class _FakeRole:
    def __init__(self, rid=1, position=1, managed=False, default=False):
        self.id, self.position, self.managed = rid, position, managed
        self._default = default

    def is_default(self):
        return self._default

    def __ge__(self, other):
        return self.position >= getattr(other, "position", 0)

    def __lt__(self, other):
        return self.position < getattr(other, "position", 0)


class _FakeMe:
    def __init__(self, top_position=10, manage_roles=True):
        self.top_role = _FakeRole(position=top_position)
        self.guild_permissions = discord.Permissions(manage_roles=manage_roles)


class _FakeGuild:
    def __init__(self, me):
        self.me = me


def test_role_grant_problem_covers_every_failure_mode():
    ok_guild = _FakeGuild(_FakeMe(top_position=10, manage_roles=True))
    assert v.role_grant_problem(ok_guild, None) is not None
    assert v.role_grant_problem(ok_guild, _FakeRole(default=True)) is not None
    assert v.role_grant_problem(ok_guild, _FakeRole(managed=True)) is not None
    assert v.role_grant_problem(_FakeGuild(_FakeMe(manage_roles=False)), _FakeRole(position=1)) is not None
    assert v.role_grant_problem(_FakeGuild(_FakeMe(top_position=2)), _FakeRole(position=5)) is not None
    assert v.role_grant_problem(ok_guild, _FakeRole(position=2)) is None


class _FakeBot:
    def __init__(self, db):
        self.db = db


async def _session_lifecycle():
    db = Database(":memory:")
    await db.connect()
    bot = _FakeBot(db)
    guild_id, user_id = 900, 111

    code1 = await v._start_captcha_session(bot, guild_id, user_id)
    session = await v._get_captcha_session(bot, guild_id, user_id)
    assert session["code"] == code1 and session["attempts"] == 0 and session["locked_until"] is None

    locked, code2, attempts = await v._fail_captcha_attempt(bot, guild_id, user_id, 3)
    assert not locked and attempts == 1 and code2 != code1

    locked, code3, attempts = await v._fail_captcha_attempt(bot, guild_id, user_id, 3)
    assert not locked and attempts == 2 and code3 != code2

    locked, code4, attempts = await v._fail_captcha_attempt(bot, guild_id, user_id, 3)
    assert locked and attempts == 3 and code4 is None
    session = await v._get_captcha_session(bot, guild_id, user_id)
    assert session["locked_until"] is not None and session["locked_until"] > int(time.time())

    await v._clear_captcha_session(bot, guild_id, user_id)
    assert await v._get_captcha_session(bot, guild_id, user_id) is None

    await db.close()


def test_captcha_session_lifecycle_attempts_and_lockout():
    asyncio.run(_session_lifecycle())


def _make_interaction(guild, member):
    interaction = Mock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = member
    interaction.response = Mock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = Mock(return_value=False)
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    return interaction


async def _full_flow_grants_role_only_after_correct_captcha():
    db = Database(":memory:")
    await db.connect()
    bot = _FakeBot(db)
    cog = v.Verification.__new__(v.Verification)
    cog.bot = bot

    guild = Mock(spec=discord.Guild)
    guild.id = 900
    me = Mock()
    me.top_role = _FakeRole(position=50)
    me.guild_permissions = discord.Permissions(manage_roles=True)
    guild.me = me
    role = _FakeRole(rid=42, position=5)
    guild.get_role = Mock(return_value=role)

    member = Mock(spec=discord.Member)
    member.id = 111
    member.roles = []

    await db.set_guild_config(guild.id, "verify_role", role.id)
    await db.set_guild_config(guild.id, "verify_captcha_enabled", 1)
    await db.set_guild_config(guild.id, "verify_captcha_max_attempts", 3)

    # 1) Premier clic : CAPTCHA envoyé, PAS de rôle attribué.
    interaction = _make_interaction(guild, member)
    await cog.do_verify(interaction)
    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "view" in kwargs and isinstance(kwargs["view"], v.CaptchaOpenModalView)
    member.add_roles.assert_not_called()

    session = await v._get_captcha_session(bot, guild.id, member.id)
    real_code = session["code"]

    # 2) Mauvais code : toujours pas de rôle, nouveau code renvoyé.
    interaction2 = _make_interaction(guild, member)
    await cog.handle_captcha_submission(interaction2, "WRONG")
    member.add_roles.assert_not_called()
    session_after_wrong = await v._get_captcha_session(bot, guild.id, member.id)
    assert session_after_wrong["code"] != real_code
    assert session_after_wrong["attempts"] == 1

    # 3) Bon code (avec espaces/minuscules, doit quand même passer) : rôle attribué,
    # session nettoyée.
    correct_code = session_after_wrong["code"]
    interaction3 = _make_interaction(guild, member)
    await cog.handle_captcha_submission(interaction3, f"  {correct_code.lower()}  ")
    member.add_roles.assert_awaited_once()
    assert await v._get_captcha_session(bot, guild.id, member.id) is None
    interaction3.response.send_message.assert_awaited_with("● Vous avez été vérifié avec succès !", ephemeral=True)

    await db.close()


def test_full_flow_only_grants_role_after_correct_captcha():
    asyncio.run(_full_flow_grants_role_only_after_correct_captcha())


async def _captcha_disabled_grants_immediately():
    db = Database(":memory:")
    await db.connect()
    bot = _FakeBot(db)
    cog = v.Verification.__new__(v.Verification)
    cog.bot = bot

    guild = Mock(spec=discord.Guild)
    guild.id = 901
    me = Mock()
    me.top_role = _FakeRole(position=50)
    me.guild_permissions = discord.Permissions(manage_roles=True)
    guild.me = me
    role = _FakeRole(rid=43, position=5)
    guild.get_role = Mock(return_value=role)

    member = Mock(spec=discord.Member)
    member.id = 222
    member.roles = []

    await db.set_guild_config(guild.id, "verify_role", role.id)
    await db.set_guild_config(guild.id, "verify_captcha_enabled", 0)

    interaction = _make_interaction(guild, member)
    await cog.do_verify(interaction)
    member.add_roles.assert_awaited_once()
    interaction.response.send_message.assert_awaited_with("● Vous avez été vérifié avec succès !", ephemeral=True)

    await db.close()


def test_captcha_disabled_keeps_old_immediate_behaviour():
    asyncio.run(_captcha_disabled_grants_immediately())


async def _role_hierarchy_problem_blocks_before_captcha():
    db = Database(":memory:")
    await db.connect()
    bot = _FakeBot(db)
    cog = v.Verification.__new__(v.Verification)
    cog.bot = bot

    guild = Mock(spec=discord.Guild)
    guild.id = 902
    me = Mock()
    me.top_role = _FakeRole(position=1)  # sous le role vise -> jamais assignable
    me.guild_permissions = discord.Permissions(manage_roles=True)
    guild.me = me
    role = _FakeRole(rid=44, position=50)
    guild.get_role = Mock(return_value=role)

    member = Mock(spec=discord.Member)
    member.id = 333
    member.roles = []

    await db.set_guild_config(guild.id, "verify_role", role.id)

    interaction = _make_interaction(guild, member)
    await cog.do_verify(interaction)
    # Jamais de CAPTCHA envoye pour un role qui ne pourra de toute facon jamais etre donne.
    member.add_roles.assert_not_called()
    assert await v._get_captcha_session(bot, guild.id, member.id) is None
    message = interaction.response.send_message.call_args.args[0]
    assert "au-dessus" in message

    await db.close()


def test_unfeasible_role_never_starts_a_captcha_session():
    asyncio.run(_role_hierarchy_problem_blocks_before_captcha())
