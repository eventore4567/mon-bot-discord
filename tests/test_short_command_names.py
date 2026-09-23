"""Noms publics SentriX : + et / partagent la même surface sans renommer l'interne.

Les anciens raccourcis restent des alias de compatibilité ; +help affiche désormais
le chemin canonique publié en slash."""

from __future__ import annotations

from discord.ext import commands

from cogs import common_command_names as short


def _bot():
    return commands.Bot(command_prefix="+", intents=__import__("discord").Intents.none(), help_command=None)


def test_root_and_subcommand_short_names_resolve_to_the_same_object():
    bot = _bot()

    @bot.group(name="sentrixpro", invoke_without_command=True)
    async def sentrixpro(ctx):
        pass

    @sentrixpro.command(name="quarantine-setup")
    async def quarantine_setup(ctx):
        pass

    @bot.command(name="economyleaderboard", aliases=["classement-argent"])
    async def economyleaderboard(ctx):
        pass

    short._apply_short_names(bot, bot.get_command("sentrixpro"))
    short._apply_short_names(bot, bot.get_command("economyleaderboard"))

    assert bot.get_command("pro") is bot.get_command("sentrixpro")
    assert bot.get_command("pro quarantaine") is bot.get_command("sentrixpro quarantine-setup")
    assert bot.get_command("topeco") is bot.get_command("economyleaderboard")
    # Le nom interne — donc la clé de la matrice de permissions — n'a pas bougé.
    assert bot.get_command("topeco").qualified_name == "economyleaderboard"
    assert bot.get_command("pro quarantaine").qualified_name == "sentrixpro quarantine-setup"
    # Les vieux raccourcis restent tapables, mais le nom affiché suit le slash.
    assert short.display_name(bot.get_command("economyleaderboard")) == "economy leaderboard"


def test_canonical_prefix_routes_match_the_slash_surface():
    bot = _bot()

    @bot.command(name="economyleaderboard")
    async def economyleaderboard(ctx):
        pass

    @bot.command(name="set-bio")
    async def set_bio(ctx):
        pass

    @bot.command(name="guess-number")
    async def guess_number(ctx):
        pass

    @bot.command(name="setprefix")
    async def setprefix(ctx):
        pass

    @bot.command(name="welcome-config")
    async def welcome_config(ctx):
        pass

    routes = short._rebuild_canonical_prefix_routes(bot)
    assert routes["economy leaderboard"] == "economyleaderboard"
    assert short.rewrite_canonical_prefix_content(bot, "economy leaderboard") == "economyleaderboard"
    assert short.rewrite_canonical_prefix_content(bot, "economy leaderboard 5") == "economyleaderboard 5"

    # Exceptions explicitement conservées par le propriétaire.
    assert short.display_name(bot.get_command("set-bio")) == "set-bio"
    assert short.display_name(bot.get_command("guess-number")) == "guess-number"
    assert short.display_name(bot.get_command("setprefix")) == "setprefix"
    assert short.display_name(bot.get_command("welcome-config")) == "welcome-config"


def test_intermediate_group_short_name_propagates_to_children():
    bot = _bot()

    @bot.group(name="music")
    async def music(ctx):
        pass

    @music.group(name="playlist")
    async def playlist(ctx):
        pass

    @playlist.command(name="add")
    async def add(ctx):
        pass

    short._apply_short_names(bot, bot.get_command("music"))
    assert bot.get_command("music pl add") is bot.get_command("music playlist add")
    assert short.display_name(bot.get_command("music playlist add")) == "music pl add"


def test_short_name_never_steals_an_existing_command():
    bot = _bot()

    @bot.command(name="translate", aliases=["traduire"])
    async def translate(ctx):
        pass

    @bot.command(name="ai-translate")
    async def ai_translate(ctx):
        pass

    short._apply_short_names(bot, bot.get_command("translate"))
    short._apply_short_names(bot, bot.get_command("ai-translate"))
    assert bot.get_command("traduire") is bot.get_command("translate")
    assert bot.get_command("aitrad") is bot.get_command("ai-translate")


def test_late_added_commands_get_short_names_through_add_command():
    bot = _bot()
    short._watch_late_commands()

    @bot.group(name="manage")
    async def manage(ctx):
        pass

    async def permissions(ctx):
        pass

    manage.add_command(commands.Command(permissions, name="permissions"))
    assert bot.get_command("manage perms") is bot.get_command("manage permissions")


def test_legacy_preferred_names_stay_available():
    bot = _bot()

    @bot.command(name="reset-economy")
    async def reset_economy(ctx):
        pass

    short._apply_short_names(bot, bot.get_command("reset-economy"))
    assert bot.get_command("reseteco") is bot.get_command("reset-economy")
    assert bot.get_command("reseteconomy") is bot.get_command("reset-economy")


def test_every_short_name_is_shorter_than_the_internal_one():
    for internal, preferred in short.PREFERRED_COMMAND_NAMES.items():
        assert " " not in preferred and len(preferred) <= len(internal) + 1, (internal, preferred)
    for internal, leaf in short.PREFERRED_SUBCOMMAND_NAMES.items():
        assert " " not in leaf and len(leaf) <= len(internal.split(" ")[-1]), (internal, leaf)



def test_short_slash_names_are_gated_and_short(monkeypatch):
    import sentrix_canonical_command_surface as surface

    monkeypatch.delenv(surface.SHORT_SLASH_ENV, raising=False)
    assert surface.short_slash_enabled() is False, "désactivé par défaut : slash globaux partagés primaire/standby"
    monkeypatch.setenv(surface.SHORT_SLASH_ENV, "1")
    assert surface.short_slash_enabled() is True

    seen: set[tuple[str, str, str]] = set()
    for origin, (root, bucket, leaf) in surface.SHORT_TARGETS.items():
        assert " " not in root and " " not in leaf and " " not in bucket, origin
        assert len(root) <= 10 and len(leaf) <= 12, (origin, root, leaf)
        assert (root, bucket, leaf) not in seen, f"chemin slash en double : /{root} {bucket} {leaf}".replace("  ", " ")
        seen.add((root, bucket, leaf))
    for source, public in surface.SHORT_DIRECT.items():
        assert len(public) < len(source), (source, public)
