"""La bienvenue avait TROIS émetteurs vivants à la fois, pas deux :

- cogs/control_center_v3.py assignait bot.on_member_join/on_member_remove (un ATTRIBUT) ;
- cogs/setup_v2_completion.py pose un LISTENER (add_listener) — discord.py déclenche les
  deux mécanismes séparément (Bot.dispatch appelle self.on_member_join ET chaque listener
  de extra_events), donc chaque arrivée réelle envoyait deux messages différents (titre,
  ping et respect du module "welcome" tous divergents) ;
- cogs/bot_tracker.py assignait LUI AUSSI bot.on_member_join/on_member_remove (un TROISIÈME
  système, avec son propre anti-doublon _claim_member_event/_cleanup_presence_duplicates).
  Il restait invisible en production uniquement parce que control_center_v3 s'installait
  après lui dans la chaîne de boot et écrasait l'attribut à son tour : en corrigeant
  seulement le premier doublon (control_center_v3 vs setup_v2_completion) sans toucher
  bot_tracker, celui-ci serait redevenu actif et aurait simplement DÉPLACÉ le doublon au
  lieu de le résoudre — confirmé par un boot complet pendant ce correctif, qui montrait
  bot.on_member_join à nouveau assigné après le premier retrait.

Le nettoyage heuristique de control_center_v3 (inspection du code source pour repérer et
retirer un autre listener) ne pouvait de toute façon pas détecter celui de
setup_v2_completion, dont le corps n'appelle qu'un helper (_send_welcome) sans jamais
contenir littéralement ".send(" ni "welcome_channel".

cogs/setup_v2_completion.py::_send_welcome est maintenant l'unique émetteur, et c'est
exactement la fonction appelée par le bouton "Tester la bienvenue" du setup — l'aperçu et
le message réel passent donc forcément par le même code. Le filet de sécurité après-coup de
bot_tracker.py (_cleanup_presence_duplicates, utile aussi contre un doublon inter-processus
pendant une bascule HA PRIMARY/standby) est conservé et rebranché sur ce seul émetteur.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import control_center_v3, setup_v2_completion  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_control_center_v3_no_longer_sends_welcome_or_goodbye():
    source = _source("cogs/control_center_v3.py")
    assert "bot.on_member_join = on_member_join" not in source
    assert "bot.on_member_remove = on_member_remove" not in source
    assert "_install_presence_renderer(bot)" not in source
    # Les utilitaires partagés restent : setup_v2_completion.py les réutilise.
    assert "def render_member_template(" in source
    assert "def _is_primary_sentrix_service(" in source


def test_setup_v2_completion_is_the_single_listener():
    source = _source("cogs/setup_v2_completion.py")
    assert 'bot.add_listener(on_member_join, "on_member_join")' in source
    assert 'bot.add_listener(on_member_remove, "on_member_remove")' in source
    assert "control_center_v3.render_member_template" in source
    assert "control_center_v3._is_primary_sentrix_service()" in source
    assert "bot_tracker._cleanup_presence_duplicates" in source


def test_bot_tracker_no_longer_sends_welcome_or_goodbye():
    source = _source("cogs/bot_tracker.py")
    assert "bot.on_member_join = on_member_join" not in source
    assert "bot.on_member_remove = on_member_remove" not in source
    assert "_install_member_presence_mentions(bot)" not in source
    # Le filet de sécurité après-coup reste défini et exporté : setup_v2_completion.py
    # l'appelle après chaque envoi réel (pas les tests).
    assert "def _cleanup_presence_duplicates(" in source
    assert "def _claim_member_event(" in source


def test_bot_tracker_and_control_center_v3_are_valid_python():
    ast.parse(_source("cogs/bot_tracker.py"))
    ast.parse(_source("cogs/control_center_v3.py"))
    ast.parse(_source("cogs/setup_v2_completion.py"))


def test_control_center_v3_is_valid_python_and_installs_without_presence():
    source = _source("cogs/control_center_v3.py")
    ast.parse(source)
    assert "async def install(bot: commands.Bot)" in source
    assert "_install_setup_v3(bot)" in source
    assert "_install_honeypot_runtime(bot)" in source
    assert "_install_self_role_backend(bot)" in source


class _Guild:
    def __init__(self, member_count=42):
        self.id = 900
        self.name = "Le Repaire"
        self.member_count = member_count


class _Member:
    def __init__(self, guild):
        self.id = 111
        self.name = "jayden"
        self.display_name = "Jayden"
        self.mention = "<@111>"
        self.guild = guild
        self.display_avatar = Mock(url="https://cdn.discordapp.com/embed/avatars/0.png")


def test_render_member_template_supports_french_and_english_variables():
    guild = _Guild(member_count=57)
    member = _Member(guild)
    for placeholder in ("{member}", "{membre}", "{mention}", "{user}"):
        assert control_center_v3.render_member_template(f"Salut {placeholder} !", member) == "Salut <@111> !"
    assert control_center_v3.render_member_template("Sur {server}", member) == "Sur Le Repaire"
    assert control_center_v3.render_member_template("Sur {serveur}", member) == "Sur Le Repaire"
    assert control_center_v3.render_member_template("{member_count} membres", member) == "57 membres"
    # Pas de substitution litterale residuelle : la variable ne doit JAMAIS ressortir telle quelle.
    assert "{membre}" not in control_center_v3.render_member_template("Bienvenue {membre}", member)


class _FakeDB:
    def __init__(self, conf, presentation=None):
        self._conf = conf
        self._presentation = presentation

    async def get_guild_config(self, guild_id):
        return self._conf

    async def fetchone(self, query, params=()):
        if "welcome_presentation_v2" in query:
            return self._presentation
        return None

    async def execute(self, *a, **k):
        return None


class _FakeBot:
    def __init__(self, conf, presentation=None):
        self.db = _FakeDB(conf, presentation)


def _fake_channel():
    channel = Mock(spec=discord.TextChannel)
    channel.mention = "#bienvenue"
    channel.send = AsyncMock(return_value=Mock())
    channel.permissions_for = Mock(return_value=discord.Permissions.all())
    return channel


async def _run_send_welcome_pair():
    guild = Mock(spec=discord.Guild)
    guild.id = 900
    guild.name = "Le Repaire"
    guild.member_count = 57
    channel = _fake_channel()
    guild.get_channel = Mock(return_value=channel)
    guild.me = Mock()

    member = Mock(spec=discord.Member)
    member.id = 111
    member.mention = "<@111>"
    member.display_name = "Jayden"
    member.name = "jayden"
    member.guild = guild
    member.display_avatar = Mock(url="https://cdn.discordapp.com/embed/avatars/0.png")

    conf = {
        "welcome_channel": 42,
        "welcome_message": "Bienvenue {membre} sur **{serveur}** !",
        "welcome_image_url": "https://example.com/banner.png",
    }
    presentation = {"title": "Salut {membre} !", "show_avatar": 1, "show_member_count": 1}
    bot = _FakeBot(conf, presentation)

    ok_test, _ = await setup_v2_completion._send_welcome(bot, member, test=True)
    embed_test = channel.send.call_args.kwargs["embed"]
    content_test = channel.send.call_args.kwargs["content"]

    channel.send.reset_mock()
    ok_real, _ = await setup_v2_completion._send_welcome(bot, member, test=False)
    embed_real = channel.send.call_args.kwargs["embed"]
    content_real = channel.send.call_args.kwargs["content"]

    return ok_test, ok_real, embed_test, embed_real, content_test, content_real


def test_preview_and_real_send_produce_the_identical_embed():
    import asyncio

    ok_test, ok_real, embed_test, embed_real, content_test, content_real = asyncio.run(_run_send_welcome_pair())

    assert ok_test and ok_real
    # Meme titre, meme description, meme couleur, meme banniere, meme miniature : c'est
    # exactement l'exigence "l'apercu = le message reel envoye sur Discord". embeds.brand()
    # prefixe une barre decorative a la description (mise en forme commune a tout SentriX,
    # sans rapport avec la bienvenue) : on verifie donc le contenu utile avec un "endswith"
    # plutot qu'une egalite exacte a une chaine tapee a la main.
    assert embed_test.title == embed_real.title == "Salut <@111> !"
    assert embed_test.description == embed_real.description
    assert embed_real.description.endswith("Bienvenue <@111> sur **Le Repaire** !")
    assert embed_test.colour == embed_real.colour
    assert embed_test.image.url == embed_real.image.url == "https://example.com/banner.png"
    assert embed_test.thumbnail.url == embed_real.thumbnail.url
    # Variable francaise remplacee, jamais laissee telle quelle dans le message envoye.
    assert "{membre}" not in embed_real.description
    assert "{serveur}" not in embed_real.description
    # Seule difference attendue entre test et reel : le ping (content) au-dessus du panneau.
    assert content_test is None
    assert content_real == "<@111>"
