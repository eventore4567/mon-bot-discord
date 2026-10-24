"""Raid par application externe (badge « APP ») : le membre qui l'a lancée répond.

Scénario réel du 24/10/2026 : « Kln r » (application installée par un
utilisateur) publiait « RAIDED BY KLN » avec @everyone/@here et une invitation.
Le message a pour auteur l'APPLICATION (un bot) : AutoMod l'ignorait en entier
alors que toutes les protections étaient activées.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import automod as automod_module  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402

RAID = "RAIDED BY KLN ||<@everyone|@here>|| Want to raid other servers? Join Kln. https://discord.gg/7Meyya3vuN"


def _member(user_id: int, *, admin: bool = False) -> Mock:
    member = Mock(spec=discord.Member)
    member.id = user_id
    member.bot = False
    member.mention = f"<@{user_id}>"
    member.roles = []
    member.timeout = AsyncMock()
    member.guild_permissions = SimpleNamespace(administrator=admin, manage_guild=admin)
    member.display_avatar = None
    return member


def _setup(*, conf=None, admin=False, everyone_external=True):
    raider = _member(77, admin=admin)
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = 999
    guild.get_member = lambda uid: raider if uid == raider.id else None
    me = Mock()
    me.guild_permissions = SimpleNamespace(moderate_members=True, manage_roles=True)
    guild.me = me
    everyone = Mock()
    everyone.permissions = discord.Permissions(use_external_apps=everyone_external, send_messages=True)
    everyone.edit = AsyncMock()
    guild.default_role = everyone
    raider.guild = guild

    bot = SimpleNamespace(db=SimpleNamespace(
        fetchone=AsyncMock(return_value=None), fetchall=AsyncMock(return_value=[]),
        execute=AsyncMock(), log_automod_action=AsyncMock(),
    ), user=SimpleNamespace(id=5))
    cog = AutoMod(bot)
    cog.automod_cache[1] = conf if conf is not None else {
        "antispam": 1, "antilink": 1, "antiinvite": 1, "antimention": 1, "antiraid": 1, "antiscam": 1,
    }
    cog.exempt_roles_cache[1] = set()
    cog.immunity_overrides_cache[(1, 77)] = None
    cog.log_action = AsyncMock()
    return cog, guild, raider, everyone


def _app_message(guild, raider, content=RAID, *, user_install=True):
    meta = SimpleNamespace(user=SimpleNamespace(id=raider.id), is_user_integration=lambda: user_install)
    message = Mock(spec=discord.Message)
    message.id = 4242
    message.guild = guild
    message.author = SimpleNamespace(id=900, bot=True, name="Kln r")
    message.interaction_metadata = meta
    message.content = content
    message.embeds = []
    message.mention_everyone = False
    message.role_mentions = []
    message.channel = SimpleNamespace(id=55, mention="<#55>")
    message.delete = AsyncMock()
    return message


def test_le_raid_kln_est_supprime_et_son_lanceur_exclu():
    cog, guild, raider, everyone = _setup()
    message = _app_message(guild, raider)
    asyncio.run(cog.on_message(message))

    message.delete.assert_awaited_once()
    raider.timeout.assert_awaited_once()
    # Coupé à la source : @everyone ne peut plus lancer d'applications externes.
    everyone.edit.assert_awaited_once()
    assert everyone.edit.await_args.kwargs["permissions"].use_external_apps is False
    cog.log_action.assert_awaited_once()


def test_une_rafale_du_meme_raid_ne_sanctionne_qu_une_fois():
    cog, guild, raider, _ = _setup()
    messages = [_app_message(guild, raider) for _ in range(5)]
    for m in messages:
        asyncio.run(cog.on_message(m))
    assert all(m.delete.await_count == 1 for m in messages), "chaque message du raid disparaît"
    assert raider.timeout.await_count == 1
    assert cog.log_action.await_count == 1


def test_le_contenu_dans_un_embed_est_aussi_lu():
    cog, guild, raider, _ = _setup()
    message = _app_message(guild, raider, content="")
    message.embeds = [discord.Embed(title="RAIDED", description="Join https://discord.gg/7Meyya3vuN")]
    asyncio.run(cog.on_message(message))
    message.delete.assert_awaited_once()


def test_un_administrateur_qui_lance_une_app_n_est_pas_sanctionne():
    cog, guild, raider, everyone = _setup(admin=True)
    message = _app_message(guild, raider)
    asyncio.run(cog.on_message(message))
    message.delete.assert_not_awaited()
    raider.timeout.assert_not_awaited()
    everyone.edit.assert_not_awaited()


def test_un_bot_installe_sur_le_serveur_reste_sous_controle_des_admins():
    cog, guild, raider, _ = _setup()
    message = _app_message(guild, raider, user_install=False)
    asyncio.run(cog.on_message(message))
    message.delete.assert_not_awaited()


def test_un_message_d_app_banal_passe():
    cog, guild, raider, _ = _setup()
    message = _app_message(guild, raider, content="Voici la météo : 18 °C à Paris.")
    asyncio.run(cog.on_message(message))
    message.delete.assert_not_awaited()


def test_securite_coupee_rien_n_est_fait():
    cog, guild, raider, _ = _setup(conf={})
    message = _app_message(guild, raider)
    asyncio.run(cog.on_message(message))
    message.delete.assert_not_awaited()


def test_sans_anti_raid_le_verrou_des_apps_n_est_pas_pose():
    cog, guild, raider, everyone = _setup(conf={"antiinvite": 1, "antimention": 1})
    asyncio.run(cog.on_message(_app_message(guild, raider)))
    raider.timeout.assert_awaited_once()
    everyone.edit.assert_not_awaited()


# --------------------------------------------- tous les filtres, pas seulement le raid

def _cog_complet(conf):
    cog, guild, raider, everyone = _setup(conf=conf)
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = ["arnaqueur"]
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.moderation_dataset = SimpleNamespace(match=lambda content: None)
    raider.top_role = 1
    raider.timed_out_until = None
    return cog, guild, raider


def test_un_mot_interdit_poste_par_une_app_suit_le_filtre_normal():
    from unittest.mock import patch
    from utils import sentrix_panels as panels

    cog, guild, raider = _cog_complet({"antiinsult": 0})
    message = _app_message(guild, raider, content="Ce serveur est tenu par un arnaqueur, fuyez")
    message.channel = Mock(id=55, mention="<#55>")
    message.channel.send = AsyncMock()
    message.attachments = []
    message.mentions = []
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        asyncio.run(cog.on_message(message))
    message.delete.assert_awaited_once()
    # L'avertissement vise le membre qui a lancé l'application, pas l'application.
    def textes(appel):
        morceaux = [str(a) for a in appel.args]
        pile = [appel.kwargs.get("view")]
        while pile:
            element = pile.pop()
            if element is None:
                continue
            if isinstance(element, discord.ui.TextDisplay):
                morceaux.append(element.content)
            pile.extend(getattr(element, "children", []) or [])
        return " ".join(morceaux)

    notices = [textes(c) for c in [*message.channel.send.await_args_list, *court.await_args_list]]
    assert any("<@77>" in n for n in notices), notices


def test_le_texte_d_un_embed_est_filtre_comme_un_message():
    from unittest.mock import patch
    from utils import sentrix_panels as panels

    cog, guild, raider = _cog_complet({})
    message = _app_message(guild, raider, content="")
    message.embeds = [discord.Embed(description="Contactez cet arnaqueur pour gagner")]
    message.channel = Mock(id=55, mention="<#55>")
    message.channel.send = AsyncMock()
    message.attachments = []
    message.mentions = []
    with patch.object(panels, "texte_court", AsyncMock()), \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        asyncio.run(cog.on_message(message))
    message.delete.assert_awaited_once()


def test_le_mandataire_ne_change_que_l_auteur_et_le_contenu():
    cog, guild, raider, _ = _setup()
    message = _app_message(guild, raider)
    proxy = automod_module._MessageDApplication(message, raider, "texte")
    assert proxy.author is raider and proxy.content == "texte"
    assert proxy.id == message.id and proxy.channel is message.channel
    assert proxy._sentrix_external_app is True
