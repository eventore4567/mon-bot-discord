"""Du panneau public à une vraie partie, avec le bootstrap de production."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import discord
import sentrix_e2e_harness as h
from setup_sweep import interaction

from cogs.community_game_panels import (
    CommunityLobby,
    DuelMemberPicker,
    open_community_lobby,
)
from cogs.economy_panel_builder import ACTIONS, ActivityPublicView
from utils import sentrix_panels as panels
from utils.game_duel_invites import DuelInvitation


def click(bot, guild, user_id=h.ADMIN_ID):
    value = interaction(bot)
    value.user = guild.get_member(user_id)
    return value


def valid(view):
    assert view.total_children_count <= 40
    assert all(c["type"] in {1, 9, 10, 12, 13, 14, 17} for c in view.to_components())


async def main():
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    # Le bootstrap recharge le cog des jeux ; utiliser la classe métier active.
    from cogs.games_economy import ConnectFourView

    config = {
        "title": "Le salon de jeux",
        "text": "Choisissez votre activité.",
        "actions": list(ACTIONS),
    }
    view = ActivityPublicView(bot, config)
    valid(view)
    assert len(ACTIONS) == 25 and view.is_persistent()
    pickers = [i for i in view.walk_children() if isinstance(i, discord.ui.Select)]
    assert len(pickers) == 4
    captured_private = []
    captured_public = []
    edited = []
    original_response = discord.InteractionResponse.send_message
    original_send = discord.abc.Messageable.send
    original_edit = discord.Message.edit

    async def response(self, *args, **kwargs):
        if kwargs.get("view") is not None:
            captured_private.append(kwargs["view"])
        return await original_response(self, *args, **kwargs)

    async def send(self, *args, **kwargs):
        if kwargs.get("view") is not None:
            captured_public.append(kwargs["view"])
        return await original_send(self, *args, **kwargs)

    async def edit(self, *args, **kwargs):
        if kwargs.get("view") is not None:
            edited.append(kwargs["view"])
        return await original_edit(self, *args, **kwargs)

    with (
        patch.object(discord.InteractionResponse, "send_message", response),
        patch.object(discord.abc.Messageable, "send", send),
        patch.object(discord.Message, "edit", edit),
    ):
        duel = next(p for p in pickers if p.custom_id == "sentrix:activity:Duels")
        duel._values = ["connect4"]
        await duel.callback(click(bot, guild))
        picker = next(v for v in captured_private if isinstance(v, DuelMemberPicker))
        peer = next(
            i for i in picker.walk_children() if isinstance(i, discord.ui.UserSelect)
        )
        peer._values = [guild.get_member(h.SECOND_ID)]
        await peer.callback(click(bot, guild))
        invitations = [
            panels.vue_source(i)
            for v in captured_public
            for i in v.walk_children()
            if isinstance(i, discord.ui.Button)
        ]
        invitation = next(v for v in invitations if isinstance(v, DuelInvitation))
        assert invitation.status == "pending"
        assert not any(
            isinstance(panels.vue_source(i), ConnectFourView)
            for v in edited
            for i in v.walk_children()
        )
        await invitation.resolve(click(bot, guild, h.TARGET_ID), "accept")
        assert invitation.status == "pending"
        await invitation.resolve(click(bot, guild, h.SECOND_ID), "accept")
        assert invitation.status == "accepted"
        assert any(
            isinstance(panels.vue_source(item), ConnectFourView)
            for view in edited
            for item in view.walk_children()
        ), [
            (
                type(v).__name__,
                [type(panels.vue_source(item)).__name__ for item in v.walk_children()],
            )
            for v in edited
        ]
        game = next(
            panels.vue_source(i)
            for v in edited
            for i in v.walk_children()
            if isinstance(panels.vue_source(i), ConnectFourView)
        )
        old = [list(row) for row in game.board]
        await game.play(click(bot, guild, h.SECOND_ID), 1)
        assert game.board == old
        for uid, col in [
            (h.ADMIN_ID, 0),
            (h.SECOND_ID, 1),
            (h.ADMIN_ID, 0),
            (h.SECOND_ID, 1),
            (h.ADMIN_ID, 0),
            (h.SECOND_ID, 1),
            (h.ADMIN_ID, 0),
        ]:
            await game.play(click(bot, guild, uid), col)
        assert game._settled
        history = await bot.db.get_game_history(guild.id, h.ADMIN_ID)
        assert any(r["game_name"] == "connect4" for r in history)
        # Une partie communautaire se prépare à plusieurs, puis utilise le vrai jeu.
        events = next(
            p for p in pickers if p.custom_id == "sentrix:activity:GamesCommunity"
        )
        events._values = ["guessrace"]
        await events.callback(click(bot, guild))
        lobby = bot._sentrix_public_game_lobbies[h.CID]
        assert isinstance(lobby, CommunityLobby) and len(lobby.players) == 1
        valid(lobby)
        await lobby.start(click(bot, guild))
        assert lobby.state == "waiting"
        await lobby.join(click(bot, guild, h.SECOND_ID))
        assert len(lobby.players) == 2
        await lobby.start(click(bot, guild, h.SECOND_ID))
        assert lobby.state == "waiting"
        before = len(captured_public)
        await open_community_lobby(
            bot, click(bot, guild, h.TARGET_ID), "wordrace", "Course aux mots"
        )
        assert (
            len(captured_public) == before
            and bot._sentrix_public_game_lobbies[h.CID] is lobby
        )
        answer = SimpleNamespace(
            channel=guild.get_channel(h.CID),
            author=guild.get_member(h.SECOND_ID),
            content="7",
            id=h.next_id(),
        )
        previous_wait = bot.wait_for

        async def wait(event, *, check=None, timeout=None):
            if event == "message":
                assert check(answer)
                return answer
            return await previous_wait(event, check=check, timeout=timeout)

        with (
            patch.object(bot, "wait_for", wait),
            patch("utils.game_rewards.secure_randint", return_value=7),
        ):
            await lobby.start(click(bot, guild))
            if lobby._watcher:
                await asyncio.wait_for(lobby._watcher, timeout=15)
        assert lobby.state == "finished"
        assert h.CID not in bot._sentrix_public_game_lobbies
        history = await bot.db.get_game_history(guild.id, h.SECOND_ID)
        assert any(r["game_name"] == "guessrace" for r in history)
        # Annulation et expiration libèrent la place sans démarrer un jeu.
        cancelled = await open_community_lobby(
            bot, click(bot, guild), "wordrace", "Course aux mots"
        )
        await cancelled.cancel(click(bot, guild, h.SECOND_ID))
        assert cancelled.state == "waiting"
        await cancelled.cancel(click(bot, guild))
        assert (
            cancelled.state == "closed"
            and h.CID not in bot._sentrix_public_game_lobbies
        )
        expired = await open_community_lobby(
            bot, click(bot, guild), "mathrace", "Course au calcul"
        )
        await expired.on_timeout()
        assert (
            expired.state == "closed" and h.CID not in bot._sentrix_public_game_lobbies
        )
    for label in ("Mes statistiques", "Classement des joueurs"):
        item = next(
            i
            for i in view.walk_children()
            if isinstance(i, discord.ui.Button) and i.label == label
        )
        before = len(h.CALLS)
        await item.callback(click(bot, guild))
        assert not any(
            m == "POST" and path.startswith("/channels/")
            for m, path, data in h.CALLS[before:]
        )
    print(
        json.dumps(
            {
                "duel": "accepted_and_won",
                "group": "joined_started_and_won",
                "cleanup": True,
                "persistent_launcher": True,
            }
        ),
        flush=True,
    )
    os._exit(0)


try:
    asyncio.run(main())
except Exception:
    logging.getLogger(__name__).exception("Échec des panneaux multijoueurs")
    sys.stderr.flush()
    os._exit(1)
