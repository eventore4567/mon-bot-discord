"""Rejoue le rendu et les clics avec toutes les couches de production chargées."""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import discord
import sentrix_e2e_harness as h
from setup_sweep import interaction

import sentrix_regression_runtime as runtime
from cogs.economy_setup import EconomyAdvancedView, EconomyFeatureView, EconomySetupView
from cogs.reaction_role_setup import RolePanelHubView
from cogs.setup_experience_v74 import SentriXSetupV74


def valid(view):
    allowed = {1, 9, 10, 12, 13, 14, 17}
    assert all(c["type"] in allowed for c in view.to_components()), view.to_components()
    assert view.total_children_count <= 40


async def main():
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    view = runtime.RolePanelBuilder(bot, guild, h.ADMIN_ID)
    await interaction(bot).response.send_message(view=view, ephemeral=True)
    for cls, value in (
        (runtime.BuilderRolePicker, guild.get_role(h.MEMBER_ROLE_ID)),
        (runtime.BuilderChannelPicker, guild.get_channel(h.LOGCID)),
        (runtime.BuilderModeSelect, "reaction"),
    ):
        item = next(i for i in view.walk_children() if isinstance(i, cls))
        item._values = [value]
        await item.callback(interaction(bot))
        valid(view)
    custom = next(
        i
        for i in view.walk_children()
        if isinstance(i, discord.ui.Button) and i.label == "Choisir les emojis"
    )
    captured = []
    previous = discord.InteractionResponse.send_modal

    async def capture(self, modal, *args, **kwargs):
        captured.append(modal)

    discord.InteractionResponse.send_modal = capture
    try:
        await custom.callback(interaction(bot))
    finally:
        discord.InteractionResponse.send_modal = previous
    modal = captured[0]
    modal.values_input._value = "🎁"
    await modal.on_submit(interaction(bot))
    valid(view)
    assert view.custom_emojis == ["🎁"]
    since = len(h.CALLS)
    await view.create_panel(interaction(bot))
    published = [
        (path, data)
        for method, path, data in h.CALLS[since:]
        if method == "POST" and path == f"/channels/{h.LOGCID}/messages"
    ]
    assert published, h.CALLS[since:]
    rows = await bot.db.fetchall(
        "SELECT channel_id FROM reaction_role_panels WHERE guild_id=?", (guild.id,)
    )
    assert any(row["channel_id"] == h.LOGCID for row in rows)

    setup = SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await setup.prepare()
    await setup._build_home()
    select = next(
        item for item in setup.walk_children() if isinstance(item, discord.ui.Select)
    )
    labels = [opt.label for opt in select.options]
    assert "Niveaux & économie" not in labels
    assert labels.count("Économie") == 1
    assert "Niveaux & réputation" in labels
    for page in ("levels", "roles"):
        setup.clear_items()
        setup.page = page
        setup.backend = setup._new_backend(page)
        await setup._build_page(page)
        valid(setup)
        names = [str(getattr(i, "label", "")) for i in setup.walk_children()]
        if page == "levels":
            assert not any("Économie" in name or "argent" in name for name in names)
            text = "\n".join(
                i.content
                for i in setup.walk_children()
                if isinstance(i, discord.ui.TextDisplay)
            )
            assert "Niveaux & économie" not in text
        else:
            placeholders = [
                str(getattr(i, "placeholder", "")) for i in setup.walk_children()
            ]
            assert not any(
                "Membre principal" in p or "Exclusion des giveaways" in p
                for p in placeholders
            )
            assert names.count("Panneaux de rôles") == 1
            assert "Rôles par réaction" not in names and "Panneau de rôles" not in names
    economy = await EconomyAdvancedView(bot, guild, h.ADMIN_ID).build()
    names = [
        i.label for i in economy.walk_children() if isinstance(i, discord.ui.Button)
    ]
    assert names.count("Jeux") == 1 and names.count("Vol (rob)") == 1
    assert not {
        "Gains des jeux",
        "Les jeux rapportent : oui / non",
        "Activer / Désactiver le vol",
    } & set(names)
    for kind in ("rob", "games"):
        feature = await EconomyFeatureView(bot, guild, h.ADMIN_ID, kind).build()
        valid(feature)
        assert any(
            i.label == "Activer / Désactiver"
            for i in feature.walk_children()
            if isinstance(i, discord.ui.Button)
        )
    hub = RolePanelHubView(bot, guild, h.ADMIN_ID)
    valid(hub)
    names = [i.label for i in hub.walk_children() if isinstance(i, discord.ui.Button)]
    assert not names
    assert any(isinstance(i, discord.ui.RoleSelect) for i in hub.walk_children())
    fixed = runtime.RolePanelBuilder(bot, guild, h.ADMIN_ID, allow_mode_switch=False)
    assert not any(
        isinstance(i, runtime.BuilderModeSelect) for i in fixed.walk_children()
    )
    from types import SimpleNamespace

    from cogs.economy_panel_builder import (
        ActivityPublicView,
        ActivityTextModal,
        EconomyPanelBuilder,
        restore_activity_panels,
    )
    from cogs.reaction_role_wizard import RoleEmojiModal, RoleTextModal
    from cogs.verification import Verification

    wizard = RolePanelHubView(bot, guild, h.ADMIN_ID)
    before = len(h.CALLS)
    for rid, emoji in ((h.MEMBER_ROLE_ID, "🎮"), (h.PING_ROLE_ID, "📣")):
        modal = RoleEmojiModal(wizard, guild.get_role(rid))
        modal.emoji._value = emoji
        await modal.on_submit(interaction(bot))
        valid(wizard)
    assert len(wizard.mappings) == 2
    assert not any(
        method == "POST" and path.startswith("/channels/")
        for method, path, data in h.CALLS[before:]
    )
    modal = RoleTextModal(wizard)
    modal.heading._value, modal.text._value = "Mes rôles", "Mon texte personnalisé"
    await modal.on_submit(interaction(bot))
    picker = next(
        i for i in wizard.walk_children() if isinstance(i, discord.ui.ChannelSelect)
    )
    picker._values = [guild.get_channel(h.LOGCID)]
    await picker.callback(interaction(bot))
    valid(wizard)
    assert wizard.stage == "preview" and not wizard.published
    before = len(h.CALLS)
    await wizard.publish(interaction(bot))
    assert wizard.published
    rows = await bot.db.fetchall(
        "SELECT * FROM reaction_role_panels WHERE title=?", ("Mes rôles",)
    )
    assert len(rows) == 1 and rows[0]["description"] == "Mon texte personnalisé"
    mid = rows[0]["message_id"]
    mappings = await bot.db.fetchall(
        "SELECT * FROM reaction_roles WHERE message_id=?", (mid,)
    )
    assert len(mappings) == 2
    assert (
        sum(
            method == "PUT" and "/reactions/" in path
            for method, path, data in h.CALLS[before:]
        )
        == 2
    )
    # Les vrais listeners relisent les associations, y compris après recréation du cog.
    payload = SimpleNamespace(
        guild_id=guild.id,
        channel_id=h.LOGCID,
        message_id=mid,
        user_id=h.SECOND_ID,
        member=guild.get_member(h.SECOND_ID),
        emoji=discord.PartialEmoji(name="📣"),
    )
    before = len(h.CALLS)
    await Verification(bot).on_raw_reaction_add(payload)
    await Verification(bot).on_raw_reaction_remove(payload)
    role_path = f"/guilds/{guild.id}/members/{h.SECOND_ID}/roles/{h.PING_ROLE_ID}"
    assert any(
        method == "PUT" and path == role_path for method, path, data in h.CALLS[before:]
    )
    assert any(
        method == "DELETE" and path == role_path
        for method, path, data in h.CALLS[before:]
    )
    before = len(h.CALLS)
    await wizard.publish(interaction(bot))
    assert not any(
        method == "POST" and path.startswith("/channels/")
        for method, path, data in h.CALLS[before:]
    )

    home = await EconomySetupView(bot, guild, h.ADMIN_ID).build()
    assert [
        i.label for i in home.walk_children() if isinstance(i, discord.ui.Button)
    ] == ["Créer un panneau", "Régler l'économie"]
    composer = EconomyPanelBuilder(bot, guild, h.ADMIN_ID)
    picker = next(
        i for i in composer.walk_children() if isinstance(i, discord.ui.Select)
    )
    picker._values = ["both"]
    await picker.callback(interaction(bot))
    picker = next(
        i for i in composer.walk_children() if isinstance(i, discord.ui.Select)
    )
    picker._values = ["balance", "doors"]
    await picker.callback(interaction(bot))
    modal = ActivityTextModal(composer)
    modal.heading._value, modal.text._value = "Mon espace", "Choisissez une activité"
    await modal.on_submit(interaction(bot))
    picker = next(
        i for i in composer.walk_children() if isinstance(i, discord.ui.ChannelSelect)
    )
    picker._values = [guild.get_channel(h.LOGCID)]
    await picker.callback(interaction(bot))
    valid(composer)
    await composer.publish(interaction(bot))
    assert composer.published
    stored = await bot.db.fetchall("SELECT * FROM sentrix_public_activity_panels")
    assert len(stored) == 1 and stored[0]["channel_id"] == h.LOGCID
    await restore_activity_panels(bot)
    public = ActivityPublicView(bot, composer.config)
    assert public.is_persistent()
    valid(public)
    for picker in [
        i for i in public.walk_children() if isinstance(i, discord.ui.Select)
    ]:
        picker._values = [picker.options[0].value]
        before = len(h.CALLS)
        click = interaction(bot)
        click.user = guild.get_member(h.SECOND_ID)
        await picker.callback(click)
        sent = [data for method, path, data in h.CALLS[before:] if method == "POST"]
        assert sent, h.CALLS[before:]
        assert any(int(data.get("data", data).get("flags", 0)) & 64 for data in sent), (
            sent
        )
        assert not any(
            method == "POST" and path.startswith("/channels/")
            for method, path, data in h.CALLS[before:]
        )
    for view in (home, wizard, composer, public):
        assert isinstance(view.children[0].children[0], discord.ui.MediaGallery)
    print(
        json.dumps(
            {
                "picker_callbacks": 3,
                "custom_modal": True,
                "selected_channel_publish": True,
                "unique_setup": True,
            }
        ),
        flush=True,
    )
    os._exit(0)


try:
    asyncio.run(main())
except Exception:
    import logging

    logging.getLogger(__name__).exception("Échec du parcours de configuration")
    sys.stderr.flush()
    os._exit(1)
