"""Parcours de configuration avec le véritable bootstrap, sans Discord réel."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import discord
import sentrix_e2e_harness as h
from setup_sweep import interaction

import sentrix_setup_v116 as routing
from cogs import setup_v2_completion as welcome_engine
from cogs.complete_backup_setup import (
    BackupNameModal,
    BackupSetupView,
    DeleteBackupView,
)
from cogs.complete_security_setup import SecurityCenterView, SecurityLimitsModal, specs
from cogs.complete_welcome_setup import WelcomeMessageModal, WelcomeSetupView
from cogs.setup_components_v73 import ACCENT
from cogs.setup_experience_v74 import SentriXSetupV74
from utils import spam_sensitivity


def valid(view):
    assert view.total_children_count <= 40, view.total_children_count
    assert all(c["type"] in {1, 9, 10, 12, 13, 14, 17} for c in view.to_components())
    assert not any(
        isinstance(i, discord.ui.MediaGallery)
        and any("sentrix-banniere-profil" in str(m.media.url) for m in i.items)
        for i in view.walk_children()
    )
    assert view.children[0].accent_colour is None or int(
        view.children[0].accent_colour
    ) in {int(ACCENT), 0x5865F2}


def find_button(view, label):
    return next(
        i
        for i in view.walk_children()
        if isinstance(i, discord.ui.Button) and i.label == label
    )


async def main():
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    before = dict(await bot.db.get_automod(guild.id))
    facade = SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await facade.prepare()
    for page in ("security", "welcome", "goodbye"):
        facade.clear_items()
        facade.page = page
        facade.backend = facade._new_backend(page)
        await facade._build_page(page)
        valid(facade)
        labels = [getattr(x, "label", "") for x in facade.walk_children()]
        if page in {"welcome", "goodbye"}:
            assert "Aperçu du texte en privé" in labels, (
                page,
                labels,
                type(facade)._build_page.__module__,
            )
        else:
            assert any(
                getattr(x, "placeholder", "") == "Configurer une protection"
                for x in facade.walk_children()
            ), (page, labels, type(facade)._build_security.__module__)
    for key, *_ in specs():
        view = await SecurityCenterView(bot, guild, h.ADMIN_ID, key).build()
        valid(view)
        if key == "antinuke":
            lines = [x for x in view.walk_children() if isinstance(x, discord.ui.Section)]
            assert len(lines) >= 4
            assert all(isinstance(x.accessory, discord.ui.Button) for x in lines)
        if key in {"antispam", "antiinvite", "antimention", "antiscam"}:
            for section in ("exceptions", "sanctions"):
                view.section = section
                await view.build()
                valid(view)
    assert dict(await bot.db.get_automod(guild.id)) == before
    # Une modification volontaire utilise le même réglage et invalide le cache du moteur.
    view = await SecurityCenterView(bot, guild, h.ADMIN_ID, "antispam").build()
    label = "Désactiver" if before["antispam"] else "Activer"
    await find_button(view, label).callback(interaction(bot))
    assert bool((await bot.db.get_automod(guild.id))["antispam"]) != bool(
        before["antispam"]
    )
    cog = bot.get_cog("Automod")
    await cog._spam_seuils(guild.id)
    modal = SecurityLimitsModal(
        view, (await spam_sensitivity.lire(bot, guild.id)).seuils
    )
    modal.fields["messages"]._value = "9"
    modal.fields["seconds"]._value = "12"
    await modal.on_submit(interaction(bot))
    thresholds = await cog._spam_seuils(guild.id)
    assert thresholds.messages == 9 and thresholds.secondes == 12
    # Rôles bypass et salons stricts écrits dans les tables déjà lues par AutoMod.
    view.section = "exceptions"
    await view.build()
    roles = next(
        i for i in view.walk_children() if isinstance(i, discord.ui.RoleSelect)
    )
    roles._values = [guild.get_role(h.PING_ROLE_ID)]
    await roles.callback(interaction(bot))
    channels = next(
        i for i in view.walk_children() if isinstance(i, discord.ui.ChannelSelect)
    )
    channels._values = [guild.get_channel(h.LOGCID)]
    await channels.callback(interaction(bot))
    policy = await bot.db.get_security_filter_policy(guild.id, "antispam")
    assert (
        h.PING_ROLE_ID in policy["role_ids"]
        and h.LOGCID in policy["strict_channel_ids"]
    )
    # Les entrées ciblées ne renvoient plus toutes au même écran général.
    for module, section, cls, feature in [
        ("security", "raid", SecurityCenterView, "antiraid"),
        ("security", "backups", BackupSetupView, None),
        ("members", "welcome", WelcomeSetupView, None),
    ]:
        owner = SimpleNamespace(bot=bot, _v116_module=module, _v116_section=section)
        i = SimpleNamespace(
            guild=guild,
            user=guild.get_member(h.ADMIN_ID),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        await routing._run_action(owner, i)
        opened = i.edit_original_response.call_args.kwargs["view"]
        assert isinstance(opened, cls)
        if feature:
            assert opened.feature == feature
        valid(opened)
    # Bienvenue et départ : sauvegarde du texte sans modifier l’autre message.
    welcome = await WelcomeSetupView(bot, guild, h.ADMIN_ID).build()
    conf = await bot.db.get_guild_config(guild.id)
    previous_goodbye = conf["goodbye_message"]
    p = await welcome_engine._welcome_presentation(bot, guild.id)
    modal = WelcomeMessageModal(welcome, conf, p)
    modal.heading._value = "Bienvenue chez nous"
    modal.text._value = "Salut {mention}, bienvenue sur {server} !"
    await modal.on_submit(interaction(bot))
    conf = await bot.db.get_guild_config(guild.id)
    assert conf["welcome_message"] == "Salut {mention}, bienvenue sur {server} !"
    assert conf["goodbye_message"] == previous_goodbye
    welcome.options = True
    await welcome.build()
    valid(welcome)
    old_p = await welcome_engine._welcome_presentation(bot, guild.id)
    label = "Message privé : " + ("Oui" if old_p["dm"] else "Non")
    await find_button(welcome, label).callback(interaction(bot))
    assert (await welcome_engine._welcome_presentation(bot, guild.id))["dm"] != old_p[
        "dm"
    ]
    before_calls = len(h.CALLS)
    await find_button(welcome, "Aperçu du texte en privé").callback(interaction(bot))
    assert not any(
        m == "POST" and path.startswith("/channels/")
        for m, path, data in h.CALLS[before_calls:]
    )
    # Créer une sauvegarde appelle la vraie logique existante et ne restaure rien.
    backups = await BackupSetupView(bot, guild, h.ADMIN_ID).build()
    valid(backups)
    modal = BackupNameModal(backups)
    modal.name._value = "Avant configuration"
    before_calls = len(h.CALLS)
    await modal.on_submit(interaction(bot))
    rows = await bot.db.fetchall(
        "SELECT * FROM server_backups WHERE guild_id=? AND label=?",
        (guild.id, "Avant configuration"),
    )
    assert len(rows) == 1
    assert not any(
        m == "POST" and (path.endswith(("/roles", "/channels")))
        for m, path, data in h.CALLS[before_calls:]
    )
    backups.selected = int(rows[0]["id"])
    await backups.build()
    valid(backups)
    cog = bot.get_cog("Security")
    callback = AsyncMock()
    with patch.object(cog.server_restore, "_callback", callback):
        await find_button(backups, "Préparer la restauration").callback(
            interaction(bot)
        )
    assert callback.await_count == 1 and callback.call_args.args[-1] == backups.selected
    confirmation = await DeleteBackupView(backups, rows[0]).build()
    assert await bot.db.fetchone(
        "SELECT id FROM server_backups WHERE guild_id=? AND id=?",
        (guild.id, backups.selected),
    )
    await find_button(confirmation, "Annuler").callback(interaction(bot))
    assert await bot.db.fetchone(
        "SELECT id FROM server_backups WHERE guild_id=? AND id=?",
        (guild.id, backups.selected),
    )
    confirmation = await DeleteBackupView(backups, rows[0]).build()
    await find_button(confirmation, "Supprimer cette sauvegarde").callback(
        interaction(bot)
    )
    assert not await bot.db.fetchone(
        "SELECT id FROM server_backups WHERE guild_id=? AND id=?",
        (guild.id, rows[0]["id"]),
    )
    # Un tiers ne peut pas modifier un panneau reçu par un autre membre.
    denied = interaction(bot)
    denied.user = guild.get_member(h.SECOND_ID)
    assert not await welcome.interaction_check(denied)
    print(
        json.dumps(
            {
                "protections": len(specs()),
                "welcome": True,
                "backups": True,
                "style": "SentriX",
                "runtime": "existing",
            }
        ),
        flush=True,
    )
    os._exit(0)


try:
    asyncio.run(main())
except Exception:
    logging.getLogger(__name__).exception("Échec du centre de configuration")
    sys.stderr.flush()
    os._exit(1)
