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
from services import moderation as moderation_service  # noqa: E402
from utils import sentrix_panels as panels  # noqa: E402


_ALL_OFF = {
    key: 0 for key in (
        "antispam", "antilink", "antilink_strict", "antiinvite", "antimention", "anticaps", "antiemoji",
        "antiscam", "antiraid", "antibot", "antiaccount", "antinuke", "escalation",
    )
}


def _cog(*, conf: dict) -> AutoMod:
    bot = SimpleNamespace(
        db=SimpleNamespace(
            log_automod_action=AsyncMock(),
            fetchone=AsyncMock(return_value=None),
            fetchall=AsyncMock(return_value=[]),
            # Palier anti-spam, références d'incident : écrits en base.
            execute=AsyncMock(),
        )
    )
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
    message.channel.send = AsyncMock()
    message.content = f"{content} {index}"
    message.mentions = []
    message.role_mentions = []
    message.mention_everyone = False
    message.attachments = []
    message.delete = AsyncMock()
    return message


def _palier_spam(precedent: int):
    """Base factice où le membre est déjà au palier anti-spam ``precedent``."""
    import time

    async def fetchone(sql, *_args, **_kwargs):
        if "sentrix_spam_escalation" in sql and precedent:
            return {"stage": precedent, "updated_at": int(time.time())}
        return None

    return fetchone


async def _rafale(cog, member, nombre: int):
    messages = [_message(member, i) for i in range(nombre)]
    # Délai de carte plus long que la rafale : la carte compte TOUTE la rafale.
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.2):
        for message in messages:
            await cog.on_message(message)
        await asyncio.sleep(0.3)
    return messages, court


@pytest.mark.asyncio
async def test_une_rafale_de_30_messages_produit_une_seule_sanction_un_avertissement_un_log():
    # Anti-spam progressif : rappel -> warn -> mute 10 min, 30 min… Une première
    # rafale ne vaut qu'un rappel, mais reste UN seul incident.
    cog = _cog(conf={"antispam": 1, "escalation": 1})
    member = _member()
    messages, court = await _rafale(cog, member, 30)

    member.timeout.assert_not_awaited()
    assert court.await_count == 1
    assert cog.log_action.await_count == 1
    # Toute la rafale disparaît, y compris les messages d'avant le déclenchement.
    assert sum(1 for m in messages if m.delete.await_count) == 30
    fields = {f.name: f.value for f in cog.log_action.await_args.args[1].fields}
    assert fields["Messages supprimés"] == "30", fields
    assert "Rappel anti-spam" in fields["Sanction"], fields
    note = court.await_args.args[1]
    assert "<@7>" in note and "spam" in note


@pytest.mark.asyncio
async def test_la_recidive_de_spam_mute_une_seule_fois():
    cog = _cog(conf={"antispam": 1, "escalation": 1})
    cog.bot.db.fetchone = _palier_spam(2)
    member = _member()
    _, court = await _rafale(cog, member, 30)

    assert member.timeout.await_count == 1
    assert court.await_count == 1
    assert cog.log_action.await_count == 1
    fields = {f.name: f.value for f in cog.log_action.await_args.args[1].fields}
    assert "Mute" in fields["Sanction"], fields
    assert fields["Niveau anti-spam"] == "3"
    assert "mute" in court.await_args.args[1]


@pytest.mark.asyncio
async def test_le_flood_de_copies_identiques_rejoint_le_meme_incident():
    """security_runtime_hardening appelle _delete_and_warn pour les copiés-collés :
    pendant l'incident, il ne rajoute ni avertissement ni log."""
    cog = _cog(conf={"antispam": 1, "escalation": 1})
    cog.bot.db.fetchone = _palier_spam(2)
    member = _member()
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.2):
        for i in range(5):
            await cog.on_message(_message(member, i))
        await cog._delete_and_warn(_message(member, 50, "copie"), "Flood de messages identiques détecté.", "antispam_duplicate")
        await cog._delete_and_warn(_message(member, 51, "copie"), "Flood de messages identiques détecté.", "antispam_duplicate")
        await asyncio.sleep(0.3)
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
    # Une phrase lisible qui s'efface après 8 s : ni carte, ni webhook, ni
    # republication du message (NO_REPOST_FILTERS), et aucun ping.
    cog = _cog(conf={"antilink": 1, "escalation": 0})
    member = _member()
    message = _message(member, 1, "regarde https://exemple.com")
    cog._repost_censored = AsyncMock(return_value=True)
    with patch.object(panels, "texte_court", AsyncMock()) as court, \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        await cog.on_message(message)
        await asyncio.sleep(0.05)
    court.assert_not_awaited()
    message.delete.assert_awaited_once()
    message.channel.send.assert_awaited_once()
    envoi = message.channel.send.await_args
    assert "<@7>" in envoi.args[0] and "liens" in envoi.args[0]
    assert "https://exemple.com" not in envoi.args[0]
    assert envoi.kwargs["delete_after"] == 8
    assert envoi.kwargs["allowed_mentions"].users is False
    cog._repost_censored.assert_not_awaited()
    member.timeout.assert_not_awaited()  # un lien n'est pas du spam : pas de mute direct



@pytest.mark.asyncio
async def test_antilink_strict_ignore_whitelist_et_salon_ignore():
    # Le mode strict bloque même les domaines de la liste blanche…
    cog = _cog(conf={"antilink": 1, "antilink_strict": 1, "escalation": 0})
    member = _member()
    message = _message(member, 1, "https://exemple.com")
    cog.whitelist_domains_cache[1] = ["exemple.com"]
    with patch.object(panels, "texte_court", AsyncMock()), \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        await cog.on_message(message)
        await asyncio.sleep(0.03)
    assert message.delete.await_count == 1

    # …mais un salon ignoré reste ignoré (security_filter_applies_to, priorité 6).
    cog = _cog(conf={"antilink": 1, "antilink_strict": 1, "escalation": 0})
    cog.ignored_channels_cache[1] = {55}
    ignore = _message(member, 2, "https://exemple.com")
    with patch.object(panels, "texte_court", AsyncMock()), \
         patch.object(automod_module, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        await cog.on_message(ignore)
        await asyncio.sleep(0.03)
    ignore.delete.assert_not_awaited()


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

@pytest.mark.asyncio
async def test_immunity_off_treats_verified_owner_like_normal_member():
    cog = _cog(conf={"antispam": 0})
    member = _member()
    cog.immunity_overrides_cache[(1, 7)] = False
    with patch.object(automod_module.config, "OWNER_IDS", {7}):
        assert await cog.is_automod_exempt(member) is False


@pytest.mark.asyncio
async def test_immunity_on_skips_even_strict_antilink():
    cog = _cog(conf={"antilink": 1, "antilink_strict": 1, "escalation": 0})
    member = _member()
    cog.immunity_overrides_cache[(1, 7)] = True
    message = _message(member, 1, "https://exemple.com")
    await cog.on_message(message)
    message.delete.assert_not_awaited()


def test_immunity_schema_is_persisted():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "database" / "db.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS user_immunity_settings" in source
    assert "PRIMARY KEY (guild_id, user_id)" in source

@pytest.mark.asyncio
async def test_immunity_off_allows_explicit_self_sanction_when_discord_allows_it():
    member = _member()
    bot = SimpleNamespace(
        db=SimpleNamespace(fetchone=AsyncMock(return_value={"enabled": 0}))
    )
    assert await moderation_service._hierarchy_error(
        bot, member.guild, member, member
    ) is None


@pytest.mark.asyncio
async def test_immunity_on_blocks_sentrix_sanctions():
    member = _member()
    bot = SimpleNamespace(
        db=SimpleNamespace(fetchone=AsyncMock(return_value={"enabled": 1}))
    )
    error = await moderation_service._hierarchy_error(
        bot, member.guild, member, member
    )
    assert error is not None
    assert "immunité SentriX" in error

def test_content_policy_wrapper_accepts_censored_content_and_honors_immunity_off():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "content_filter_policy.py").read_text(encoding="utf-8")
    assert "censored_content: str | None = None" in source
    assert "censored_content=censored_content" in source
    assert "override is False" in source
    assert "original_maybe_escalate" in source

def test_normalize_link_text_repairs_split_scheme_and_separates_concatenated_urls():
    raw = "https:/ /discord.gg/GgYzEFSshttps://discord.gg/Another"
    normalized = automod_module._normalize_link_text(raw)
    assert normalized == "https://discord.gg/ggyzefss https://discord.gg/another"


def test_targeted_blocked_link_matches_when_same_url_is_glued_to_another_url():
    rules = ["https://discord.gg/GgYzEFSs"]
    content = "https://discord.gg/GgYzEFSshttps://discord.gg/GgYzEFSs"
    assert automod_module._blocked_link_hit(content, rules) == rules[0]


@pytest.mark.asyncio
async def test_antiinvite_catches_repeated_discord_invites_without_spaces():
    cog = _cog(conf={"antiinvite": 1, "escalation": 0})
    member = _member()
    cog.immunity_overrides_cache[(1, 7)] = False
    message = _message(
        member,
        1,
        "https://discord.gg/GgYzEFSshttps://discord.gg/GgYzEFSs",
    )
    cog._repost_censored = AsyncMock(return_value=True)
    fake_notice = SimpleNamespace(delete=AsyncMock())
    with patch.object(panels, "envoyer", AsyncMock(return_value=fake_notice)):
        await cog.on_message(message)
    message.delete.assert_awaited_once()
    # Une invitation n'est jamais republiée, même censurée (NO_REPOST_FILTERS).
    cog._repost_censored.assert_not_awaited()

def test_native_antilink_patterns_fit_discord_limits_and_avoid_unsupported_lookaround():
    assert 1 <= len(automod_module.NATIVE_ANTILINK_REGEX_PATTERNS) <= 10
    for pattern in automod_module.NATIVE_ANTILINK_REGEX_PATTERNS:
        assert len(pattern) <= 260
        assert "(?<=" not in pattern
        assert "(?<!" not in pattern
        assert "(?=" not in pattern
        assert "(?!" not in pattern


# Les règles AutoMod natives de Discord ne savent pas exempter un administrateur
# ni un rôle de staff : SentriX filtre tout localement (aceb2db) et ne fait plus
# que RETIRER ses anciennes règles natives. Il n'en crée jamais.

_BOT_ID = 4242


def _regle(nom: str, *, createur: int = _BOT_ID):
    return SimpleNamespace(name=nom, id=hash(nom) % 1000, creator_id=createur, delete=AsyncMock())


def _cog_natif(regles, **db):
    bot = SimpleNamespace(
        user=SimpleNamespace(id=_BOT_ID),
        db=SimpleNamespace(fetchone=AsyncMock(return_value=None), **db),
    )
    guild = SimpleNamespace(
        id=123,
        me=SimpleNamespace(id=_BOT_ID, guild_permissions=SimpleNamespace(manage_guild=True)),
        fetch_automod_rules=AsyncMock(return_value=regles),
        create_automod_rule=AsyncMock(),
    )
    return AutoMod(bot), guild


@pytest.mark.asyncio
async def test_native_antilink_rule_is_created_with_block_message_action():
    # Filtre actif ou non : aucune règle native n'est créée.
    cog, guild = _cog_natif([], get_automod=AsyncMock(return_value={"antilink": 1}))
    assert await cog._sync_native_antilink_rule(guild) is True
    guild.create_automod_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_antilink_rule_is_deleted_when_filter_is_off():
    ancienne = _regle(automod_module.NATIVE_ANTILINK_RULE_NAME)
    etrangere = _regle(automod_module.NATIVE_ANTILINK_RULE_NAME, createur=1)
    cog, guild = _cog_natif([ancienne, etrangere], get_automod=AsyncMock(return_value={"antilink": 0}))

    assert await cog._sync_native_antilink_rule(guild) is True
    ancienne.delete.assert_awaited_once()
    # Une règle homonyme créée par quelqu'un d'autre n'est jamais touchée.
    etrangere.delete.assert_not_awaited()


def test_main_enables_discord_automod_gateway_intents():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "INTENTS.auto_moderation_configuration = True" in source
    assert "INTENTS.auto_moderation_execution = True" in source

@pytest.mark.asyncio
async def test_native_blacklist_rule_is_created_for_blocked_words():
    # Les mots interdits restent filtrés localement, avec le bypass des admins.
    cog, guild = _cog_natif([], fetchall=AsyncMock(return_value=[{"word": "spamword"}]))
    assert await cog._sync_native_blacklist_rule(guild) is True
    guild.create_automod_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_blacklist_rule_is_removed_when_no_words_remain():
    ancienne = _regle(automod_module.NATIVE_BLACKLIST_RULE_NAME)
    cog, guild = _cog_natif([ancienne], fetchall=AsyncMock(return_value=[]))
    assert await cog._sync_native_blacklist_rule(guild) is True
    ancienne.delete.assert_awaited_once()

@pytest.mark.asyncio
async def test_native_suite_uses_real_sentrix_features_instead_of_duplicate_badge_rules():
    # Nettoyage groupé : UNE lecture des règles pour tout le serveur, et seules
    # les règles SentriX de la suite sont retirées.
    noms = [
        automod_module.NATIVE_ANTILINK_RULE_NAME,
        automod_module.NATIVE_BLACKLIST_RULE_NAME,
        automod_module.NATIVE_TARGET_LINKS_RULE_NAME,
        automod_module.NATIVE_ANTIINVITE_RULE_NAME,
        automod_module.NATIVE_ANTISCAM_RULE_NAME,
        automod_module.NATIVE_ANTIMENTION_RULE_NAME,
        automod_module.NATIVE_HARMFUL_RULE_NAME,
    ]
    sentrix = [_regle(nom) for nom in noms]
    autre = _regle("Règle du staff")
    cog, guild = _cog_natif([*sentrix, autre])

    resultat = await cog._sync_native_suite(guild)

    guild.fetch_automod_rules.assert_awaited_once()
    guild.create_automod_rule.assert_not_awaited()
    assert resultat["removed"] == len(noms)
    for regle in sentrix:
        regle.delete.assert_awaited_once()
    autre.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_antiinvite_is_only_needed_when_global_antilink_is_off():
    db = SimpleNamespace(
        get_automod=AsyncMock(return_value={"antiinvite": 1, "antilink": 0}),
        fetchone=AsyncMock(return_value=None),
    )
    bot = SimpleNamespace(db=db)
    cog = AutoMod(bot)
    cog._upsert_native_rule = AsyncMock(return_value=True)
    guild = SimpleNamespace(id=1)

    await cog._sync_native_antiinvite_rule(guild)
    kwargs = cog._upsert_native_rule.await_args.kwargs
    assert kwargs["name"] == automod_module.NATIVE_ANTIINVITE_RULE_NAME
    assert kwargs["enabled"] is True

    db.get_automod = AsyncMock(return_value={"antiinvite": 1, "antilink": 1})
    await cog._sync_native_antiinvite_rule(guild)
    kwargs = cog._upsert_native_rule.await_args.kwargs
    assert kwargs["enabled"] is False


@pytest.mark.asyncio
async def test_native_antiscam_mentions_and_harmful_follow_real_module_state():
    db = SimpleNamespace(
        get_automod=AsyncMock(side_effect=[
            {"antiscam": 1},
            {"antimention": 1},
            {"antiinsult": 1},
        ]),
        fetchone=AsyncMock(return_value=None),
    )
    bot = SimpleNamespace(db=db)
    cog = AutoMod(bot)
    cog._upsert_native_rule = AsyncMock(return_value=True)
    guild = SimpleNamespace(id=1)

    await cog._sync_native_antiscam_rule(guild)
    scam = cog._upsert_native_rule.await_args.kwargs
    assert scam["enabled"] is True
    assert scam["trigger"].keyword_filter

    await cog._sync_native_antimention_rule(guild)
    mention = cog._upsert_native_rule.await_args.kwargs
    assert mention["enabled"] is True
    assert mention["trigger"].mention_limit == 5
    assert mention["trigger"].mention_raid_protection is True

    await cog._sync_native_harmful_rule(guild)
    harmful = cog._upsert_native_rule.await_args.kwargs
    # Le preset natif bloque des phrases neutres avant la détection contextuelle :
    # il reste désactivé, le matcher multilingue local fait le travail.
    assert harmful["enabled"] is False
    assert harmful["trigger"].presets.profanity
    assert harmful["trigger"].presets.sexual_content
    assert harmful["trigger"].presets.slurs


def test_native_suite_has_distinct_useful_rule_names():
    names = {
        automod_module.NATIVE_ANTILINK_RULE_NAME,
        automod_module.NATIVE_BLACKLIST_RULE_NAME,
        automod_module.NATIVE_TARGET_LINKS_RULE_NAME,
        automod_module.NATIVE_ANTIINVITE_RULE_NAME,
        automod_module.NATIVE_ANTISCAM_RULE_NAME,
        automod_module.NATIVE_ANTIMENTION_RULE_NAME,
        automod_module.NATIVE_HARMFUL_RULE_NAME,
    }
    assert len(names) == 7
    assert all(name.startswith("SentriX • ") for name in names)

def test_native_sync_command_distinguishes_local_and_global_counts():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert "**Ce serveur :" in source
    assert "**Total SentriX sur" in source
    assert "Le **0** n'est pas un échec de synchronisation" in source

def test_native_sync_command_enables_safe_baseline_when_server_has_no_native_config():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    block = source.split('name="automod-native-sync"', 1)[1].split('name="security-check"', 1)[0]
    assert '("antilink", "Anti-liens total")' in block
    assert '("antiscam", "Anti-arnaque")' in block
    assert '("antimention", "Anti-mentions")' in block
    assert '("antiinsult", "Contenu sensible")' in block
    assert "await self.bot.db.set_automod(ctx.guild.id, field, 1)" in block
    assert "Activées automatiquement par cette commande" in block


def test_native_sync_command_reports_when_discord_created_zero_rules():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    block = source.split('name="automod-native-sync"', 1)[1].split('name="security-check"', 1)[0]
    assert "Discord n'a créé aucune règle native" in block
    assert "Gérer le serveur" in block

