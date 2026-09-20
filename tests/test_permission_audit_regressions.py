"""Régressions trouvées par tools/permission_audit_sweep.py (20/09/2026)."""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView


def test_slash_text_values_are_quoted_for_string_view():
    """shlex.quote entourait les mentions d'apostrophes que StringView ignore :
    /shoprole ajouter recevait la mention dans « price »."""
    import sentrix_v95_runtime as v95

    for raw in ("<@&100000000000000103>", "hello world", 'dit "bonjour"', "l'ami", ""):
        quoted = v95._serialize_value(raw)
        assert StringView(quoted).get_quoted_word() == raw, raw
    assert v95._serialize_value("<@&1>") == "<@&1>"  # jamais d'apostrophe ASCII ajoutée


def test_default_valued_optional_slash_options_count_as_omitted():
    """/pro goal action:list échouait : reward_money=0 (défaut) était traité comme fourni
    après une option facultative vide."""
    import sentrix_v101_command_runtime as v101

    async def goal(ctx, action: str, metric: str | None = None, target: int | None = None, reward_money: int = 0):
        pass

    command = commands.Command(goal, name="goal")
    text = v101._argument_text(command, ("action", "metric", "target", "reward_money"),
                               {"action": "list", "metric": None, "target": None, "reward_money": 0})
    assert text == "list"


def test_commands_range_becomes_a_numeric_slash_option():
    """La couche bootstrap perdait commands.Range : /volume et /seek étaient des champs texte."""
    import sentrix_v95_bootstrap as bootstrap

    native = bootstrap._native_annotation_safe(commands.Range[int, 0, 100])
    assert isinstance(native, app_commands.transformers.RangeTransformer)
    assert native.min_value == 0 and native.max_value == 100
    assert bootstrap._native_annotation_safe(str) is str


def test_massrole_declares_its_cog_parameter_as_self():
    """/roles masse exposait une option obligatoire « verification_cog » : injouable."""
    from cogs import server_choice_roles

    params = list(inspect.signature(server_choice_roles._massrole_all_members.callback).parameters)
    assert params[0] == "self" and params[1] == "ctx"


def test_local_permission_checks_let_the_verified_bot_owner_through():
    """+modcenter / +systemstatus refusaient le propriétaire de SentriX alors que la
    matrice le laisse passer partout."""
    from utils import checks
    from database.db import PRIMARY_CREATOR_ID

    predicate = checks.has_permission("manage_guild").predicate
    owner_ctx = SimpleNamespace(author=SimpleNamespace(id=PRIMARY_CREATOR_ID), bot=SimpleNamespace(db=None))
    assert asyncio.run(predicate(owner_ctx)) is True

    from unittest import mock

    member = mock.Mock(spec=discord.Member)
    member.id = 1
    member.guild_permissions = discord.Permissions.none()
    member_ctx = SimpleNamespace(author=member, bot=SimpleNamespace(db=SimpleNamespace(is_bot_creator=_never)))
    try:
        asyncio.run(predicate(member_ctx))
    except checks.BotPermissionError as exc:
        assert "Gérer le serveur" in str(exc) and "Il te faut la permission" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("un membre sans permission doit être refusé")


async def _never(_user_id):
    return False


def test_late_added_known_commands_lose_redundant_authorization_checks():
    from cogs import permission_guard
    from utils import checks

    permission_guard._watch_late_commands()
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none(), help_command=None)

    @commands.command(name="ban")  # « ban » est classé par la matrice (discord:ban_members)
    @checks.has_permission("ban_members")
    async def ban(ctx, membre: discord.Member):
        pass

    bot.add_command(ban)
    assert ban.checks == [], "le check local redondant doit être retiré : la matrice décide"


def test_economy_off_message_is_kept_on_the_grouped_slash_path():
    import sentrix_grouped_slash_fix as fix
    from utils.checks import BotPermissionError

    error = commands.CommandInvokeError(BotPermissionError("Le **système d'argent est désactivé** sur ce serveur."))
    assert fix._short_error(error) == "Le **système d'argent est désactivé** sur ce serveur."
    assert "permission" not in fix._short_error(error).casefold()


def test_ai_search_wrappers_accept_force_web_search():
    """+ai search / /ia recherche : les remplaçants V3.2 (handler) et V3.4 (pipeline) ne
    connaissaient pas `force_web_search` → TypeError SXR-CMD à chaque appel."""
    import inspect
    from cogs import community_v32, community_v34

    src32 = inspect.getsource(community_v32._install_ai_recovery)
    src34 = inspect.getsource(community_v34._install_fast_ai)
    assert "force_web_search: bool = False" in src32 and "force_web_search=force_web_search" in src32
    assert "force_web_search: bool = False" in src34 and "force_web_search or ai_service.needs_web_search" in src34
