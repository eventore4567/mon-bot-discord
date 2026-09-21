"""Anti-spam : une rafale = UN incident (une sanction, un avertissement, une carte de log).

Avant : chaque cinquième message d'une rafale déclenchait _delete_and_warn (avertissement
public avec bannière + carte de log + infraction), et la couche
security_runtime_hardening en ajoutait autant pour les copiés-collés identiques. Une
rafale de 30 messages produisait donc une quinzaine d'avertissements, autant de logs et
plusieurs escalades pour la même séquence.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import automod as automod_module  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402


_ALL_OFF = {
    key: 0 for key in (
        "antispam", "antilink", "antilink_strict", "antiinvite", "antimention", "anticaps", "antiemoji",
        "antiscam", "antiraid", "antibot", "antiaccount", "antinuke", "escalation",
    )
}


def _cog(*, conf: dict) -> AutoMod:
    bot = SimpleNamespace(db=SimpleNamespace(log_automod_action=AsyncMock()))
    cog = AutoMod(bot)
    cog.automod_cache[1] = {**_ALL_OFF, **conf}
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = []
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.exempt_roles_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.log_action = AsyncMock()
    cog.moderation_dataset = SimpleNamespace(match=lambda content: None)
    return cog


def _member() -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = 999
    me = Mock()
    me.guild_permissions = Mock(moderate_members=True)
    me.top_role = 10
    guild.me = me
    member = Mock(spec=discord.Member)
    member.id = 7
    member.bot = False
    member.mention = "<@7>"
    member.guild = guild
    member.top_role = 1
    member.timed_out_until = None
    member.timeout = AsyncMock()
    member.roles = []
    member.guild_permissions = Mock(administrator=False, manage_guild=False)
    return member


def _message(member: Mock, index: int, content: str = "spam") -> Mock:
    message = Mock(spec=discord.Message)
    message.id = 1000 + index
    message.author = member
    message.guild = member.guild
    message.channel = Mock(id=55, mention="<#55>")
    message.content = f"{content} {index}"
    message.mentions = []
    message.role_mentions = []
    message.mention_everyone = False
    message.attachments = []
    message.delete = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_une_rafale_de_30_messages_produit_une_seule_sanction_un_avertissement_un_log():
    cog = _cog(conf={"antispam": 1, "escalation": 1})
    member = _member()
    messages = [_message(member, i) for i in range(30)]

    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        for message in messages:
            await cog.on_message(message)
        await asyncio.sleep(0.05)

    # Une seule exclusion temporaire, un seul avertissement public, une seule carte de log.
    assert member.timeout.await_count == 1
    assert court.await_count == 1
    assert cog.log_action.await_count == 1
    # Le 5e message déclenche l'incident ; TOUS les suivants sont supprimés sans bruit.
    deleted = sum(1 for m in messages if m.delete.await_count)
    assert deleted == 26
    # La carte de log est compacte et porte le compteur réel.
    embed = cog.log_action.await_args.args[1]
    fields = {f.name: f.value for f in embed.fields}
    assert any("26" in v for v in fields.values()), fields
    assert any("Mute" in v for v in fields.values()), fields
    note = court.await_args.args[1]
    assert "<@7>" in note and "Exclusion temporaire" in note


@pytest.mark.asyncio
async def test_le_flood_de_copies_identiques_rejoint_le_meme_incident():
    """security_runtime_hardening appelle _delete_and_warn pour les copiés-collés :
    pendant l'incident, il ne rajoute ni avertissement ni log."""
    cog = _cog(conf={"antispam": 1, "escalation": 1})
    member = _member()
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        for i in range(5):
            await cog.on_message(_message(member, i))
        await cog._delete_and_warn(_message(member, 50, "copie"), "Flood de messages identiques détecté.", "antispam_duplicate")
        await cog._delete_and_warn(_message(member, 51, "copie"), "Flood de messages identiques détecté.", "antispam_duplicate")
        await asyncio.sleep(0.05)
    assert court.await_count == 1
    assert cog.log_action.await_count == 1
    assert member.timeout.await_count == 1


@pytest.mark.asyncio
async def test_un_nouvel_incident_apres_la_fenetre_est_de_nouveau_traite():
    cog = _cog(conf={"antispam": 1, "escalation": 0})
    member = _member()
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        for i in range(5):
            await cog.on_message(_message(member, i))
        cog.incidents[(1, 7)].started -= automod_module.INCIDENT_WINDOW_SECONDS + 1
        for i in range(5, 10):
            await cog.on_message(_message(member, i))
        await asyncio.sleep(0.05)
    assert court.await_count == 2
    assert cog.log_action.await_count == 2


@pytest.mark.asyncio
async def test_avertissement_lien_est_un_embed_compact_temporaire():
    cog = _cog(conf={"antilink": 1, "escalation": 0})
    member = _member()
    message = _message(member, 1, "regarde https://exemple.com")
    cog._repost_censored = AsyncMock(return_value=True)
    fake_notice = SimpleNamespace(delete=AsyncMock())
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(panels, "envoyer", AsyncMock(return_value=fake_notice)) as envoyer, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        await cog.on_message(message)
        await asyncio.sleep(0.05)
    court.assert_not_awaited()
    assert envoyer.await_count == 1
    fake_notice.delete.assert_awaited_once_with(delay=8)
    cog._repost_censored.assert_awaited_once()
    censored = cog._repost_censored.await_args.args[1]
    assert "https://exemple.com" not in censored
    assert "lien censuré" in censored
    member.timeout.assert_not_awaited()  # un lien n'est pas du spam : pas de mute direct



@pytest.mark.asyncio
async def test_antilink_strict_ignore_whitelist_et_salon_ignore():
    cog = _cog(conf={"antilink": 1, "antilink_strict": 1, "escalation": 0})
    member = _member()
    message = _message(member, 1, "https://exemple.com")
    # Le mode strict doit passer AVANT ces exemptions.
    cog.ignored_channels_cache[1] = {55}
    cog.whitelist_domains_cache[1] = ["exemple.com"]

    with patch.object(panels, "texte_court", AsyncMock()),          patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        await cog.on_message(message)
        await asyncio.sleep(0.03)

    assert message.delete.await_count == 1


def test_automod_schema_persists_strict_link_mode():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "database" / "db.py").read_text(encoding="utf-8")
    assert "antilink_strict INTEGER DEFAULT 0" in source
    assert '"antilink_strict": "INTEGER DEFAULT 0"' in source

def test_censure_clone_masque_mot_interdit_sans_toucher_au_reste():
    result = automod_module._compose_censored_content(
        "salut idiot comment ça va",
        blocked_word="idiot",
    )
    assert result == "salut ████ (mot censuré) comment ça va"
    assert "idiot" not in result


def test_censure_clone_masque_lien_et_mot_dans_le_meme_message():
    result = automod_module._compose_censored_content(
        "idiot regarde https://evil.example/path maintenant",
        blocked_word="idiot",
        links=True,
    )
    assert result is not None
    assert "idiot" not in result
    assert "evil.example" not in result
    assert "mot censuré" in result
    assert "lien censuré" in result


def test_censure_clone_refuse_de_republier_si_le_terme_detecte_ne_peut_pas_etre_masque():
    # La détection de production ignore les accents ; si le texte brut ne peut pas être
    # masqué avec certitude, le clone doit être abandonné plutôt que fuiter le terme.
    assert automod_module._compose_censored_content(
        "contenu quelconque",
        blocked_word="terme-absent",
    ) is None


def test_censure_webhook_affiche_explicitement_un_nom_sentrix():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert 'name="SentriX Censure"' in source
    assert '"username": username' in source
    assert '"avatar_url": avatar' in source
    assert "AllowedMentions.none()" in source

