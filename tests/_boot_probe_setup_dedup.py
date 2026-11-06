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
from cogs.economy_setup import EconomyFeatureView, EconomySetupView
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
            assert names.count("Panneaux de rôles") == 1
            assert "Rôles par réaction" not in names and "Panneau de rôles" not in names
    economy = await EconomySetupView(bot, guild, h.ADMIN_ID).build()
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
    assert names == ["Menu déroulant", "Réactions emoji"]
    fixed = runtime.RolePanelBuilder(bot, guild, h.ADMIN_ID, allow_mode_switch=False)
    assert not any(
        isinstance(i, runtime.BuilderModeSelect) for i in fixed.walk_children()
    )
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


asyncio.run(main())
