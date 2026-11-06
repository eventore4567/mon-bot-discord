"""Publication depuis setup dans le salon choisi, avec les icônes SentriX."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault('DISCORD_TOKEN', 'ci.fake.token')
import discord
import pytest
import sentrix_regression_runtime as runtime
import sentrix_setup_v116 as setup
from utils import sentrix_emojis


@pytest.mark.asyncio
async def test_setup_opens_the_builder_privately():
    guild = SimpleNamespace(me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True)), get_role=lambda _: None)
    interaction = SimpleNamespace(guild=guild, user=SimpleNamespace(id=42, guild_permissions=SimpleNamespace(administrator=True)), response=SimpleNamespace(send_message=AsyncMock()), original_response=AsyncMock())
    owner = SimpleNamespace(bot=SimpleNamespace(), _v116_module='staff', _v116_section='reaction')
    assert next(s for s in setup.MODULE_BY_KEY['staff'].sections if s.key == 'reaction').action == 'role-panel'
    await setup._run_action(owner, interaction)
    kwargs = interaction.response.send_message.call_args.kwargs
    assert kwargs['ephemeral'] is True
    assert isinstance(kwargs['view'], runtime.RolePanelBuilder)


@pytest.mark.asyncio
async def test_publication_uses_selected_channel_and_saves_it():
    channel = MagicMock(spec=discord.TextChannel)
    channel.id, channel.mention = 77, '<#77>'
    channel.send = AsyncMock()
    channel.permissions_for.return_value = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    guild = SimpleNamespace(get_channel=lambda ident: channel if ident == 77 else None, get_role=lambda _: None, get_member=lambda _: SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)), me=object())
    builder = runtime.RolePanelBuilder(SimpleNamespace(add_view=MagicMock()), guild, 42)
    builder.selected_role_ids, builder.channel_id = [99], 77
    source = SimpleNamespace(send=AsyncMock())
    interaction = SimpleNamespace(user=SimpleNamespace(id=42), channel=source, response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()), edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
    with patch.object(runtime, '_valid_roles', return_value=([SimpleNamespace(id=99)], [])), patch.object(runtime, 'ExistingDropdownPanel'), patch.object(runtime, '_dropdown_embed'), patch.object(runtime, '_save_panel', new_callable=AsyncMock) as save:
        await builder.create_panel(interaction)
    channel.send.assert_awaited_once()
    source.send.assert_not_awaited()
    save.assert_awaited_once()
    assert save.call_args.args[1] is channel.send.return_value
    assert '<#77>' in interaction.edit_original_response.call_args.kwargs['view'].children[0].children[0].content


@pytest.mark.asyncio
async def test_missing_channel_blocks_creation_and_models_are_absent():
    guild = SimpleNamespace(get_role=lambda _: None)
    builder = runtime.RolePanelBuilder(SimpleNamespace(), guild, 42)
    builder.selected_role_ids = [99]
    builder.rebuild()
    rows = [child for child in builder.children[0].children if isinstance(child, discord.ui.ActionRow)]
    assert rows[-1].children[0].disabled
    assert not any(isinstance(row.children[0], runtime.BuilderPresetSelect) for row in rows)
    interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))
    await builder.create_panel(interaction)
    assert 'salon' in interaction.response.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_builder_uses_custom_sentrix_icons():
    with patch.dict(sentrix_emojis._RESOLUS, {'sentrix_role': '<:sentrix_role:123456789012345678>', 'sentrix_success': '<:sentrix_success:123456789012345679>'}):
        builder = runtime.RolePanelBuilder(SimpleNamespace(), SimpleNamespace(get_role=lambda _: None), 42)
        assert '<:sentrix_role:' in builder.children[0].children[0].content
        rows = [child for child in builder.children[0].children if isinstance(child, discord.ui.ActionRow)]
        assert rows[-1].children[0].emoji.id == 123456789012345679


@pytest.mark.asyncio
async def test_selected_channel_permission_failure_does_not_publish():
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    channel.permissions_for.return_value = SimpleNamespace(view_channel=True, send_messages=False, embed_links=True)
    guild = SimpleNamespace(get_channel=lambda _: channel, get_role=lambda _: None, get_member=lambda _: SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)), me=object())
    builder = runtime.RolePanelBuilder(SimpleNamespace(), guild, 42)
    builder.selected_role_ids, builder.channel_id = [99], 77
    interaction = SimpleNamespace(user=SimpleNamespace(id=42), response=SimpleNamespace(send_message=AsyncMock()))
    await builder.create_panel(interaction)
    channel.send.assert_not_awaited()
    assert "envoyer des messages" in interaction.response.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_reactions_use_custom_emojis_in_selected_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.mention = '<#77>'
    channel.send = AsyncMock()
    channel.send.return_value.add_reaction = AsyncMock()
    channel.permissions_for.return_value = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True, add_reactions=True, read_message_history=True)
    guild = SimpleNamespace(get_channel=lambda _: channel, get_role=lambda _: None, get_member=lambda _: SimpleNamespace(guild_permissions=SimpleNamespace(administrator=True)), me=object())
    builder = runtime.RolePanelBuilder(SimpleNamespace(), guild, 42, mode='reaction')
    builder.selected_role_ids, builder.channel_id = [99], 77
    interaction = SimpleNamespace(user=SimpleNamespace(id=42), response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()), edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
    icon = discord.PartialEmoji(name='sentrix_role', id=123456789012345678)
    with patch.object(runtime, '_valid_roles', return_value=([SimpleNamespace(id=99)], [])), patch.object(runtime, '_reaction_embed'), patch.object(runtime, '_save_panel', new_callable=AsyncMock) as save, patch.object(sentrix_emojis, 'partiel', return_value=icon):
        await builder.create_panel(interaction)
    channel.send.return_value.add_reaction.assert_awaited_once_with(str(icon))
    assert save.call_args.kwargs['mappings'][0]['emoji'] == str(icon)
