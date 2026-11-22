"""``+emogi`` envoie aussi les liens directs des images des emojis.

Le propriétaire voulait les liens ``https://cdn.discordapp.com/emojis/<id>.gif|png``
en plus du markup. Une commande ``+emojis`` séparée avait été écrite pour ça,
puis supprimée parce qu'elle doublonnait ``+emogi`` : les liens vivent donc ici.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from cogs.utility import EMOJI_EXPORT_CHUNK_SIZE, EmojiExportView, emoji_export_chunks


def _emoji(name: str, emoji_id: int, animated: bool) -> SimpleNamespace:
    return SimpleNamespace(name=name, id=emoji_id, animated=animated)


PACK = [
    _emoji("flamme", 111, True),
    _emoji("bouclier", 222, False),
    _emoji("eclair", 333, True),
]


def test_liens_animes_en_gif_et_statiques_en_png():
    assert emoji_export_chunks(PACK, animated=True, links=True) == [
        "flamme  https://cdn.discordapp.com/emojis/111.gif\n"
        "eclair  https://cdn.discordapp.com/emojis/333.gif"
    ]
    assert emoji_export_chunks(PACK, animated=False, links=True) == [
        "bouclier  https://cdn.discordapp.com/emojis/222.png"
    ]


def test_le_markup_reste_inchange_sans_liens():
    # Les blocs de markup doivent rester collables tels quels dans Discord :
    # aucun lien ne doit s'y glisser.
    assert emoji_export_chunks(PACK, animated=True) == ["<a:flamme:111>\n<a:eclair:333>"]
    assert emoji_export_chunks(PACK, animated=False) == ["<:bouclier:222>"]


def test_un_gros_pack_de_liens_tient_dans_un_message_discord():
    pack = [_emoji("n" * 32, 10**18 + i, False) for i in range(300)]
    chunks = emoji_export_chunks(pack, animated=False, links=True)
    assert len(chunks) > 1
    assert all(len(chunk) <= EMOJI_EXPORT_CHUNK_SIZE for chunk in chunks)
    # Rien n'est perdu au découpage.
    assert sum(chunk.count("\n") + 1 for chunk in chunks) == 300


@pytest.mark.asyncio
async def test_le_mp_contient_le_markup_puis_les_liens():
    author = SimpleNamespace(id=1)
    view = EmojiExportView(author, list(PACK))
    member = Mock(spec=discord.Member)
    member.id = 2
    member.mention = "<@2>"
    member.send = AsyncMock()
    view.member = member

    interaction = Mock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.message.edit = AsyncMock()

    await view.send_export.callback(interaction)

    envoyes = [call.args[0] for call in member.send.await_args_list]
    titres = [message.split("\n", 1)[0] for message in envoyes[1:]]
    assert titres == [
        "**Emojis animés**",
        "**Emojis statiques**",
        "**Liens des emojis animés**",
        "**Liens des emojis statiques**",
    ]
    assert "https://cdn.discordapp.com/emojis/111.gif" in envoyes[3]
    assert "https://cdn.discordapp.com/emojis/222.png" in envoyes[4]
    # Hors bloc de code, Discord afficherait un aperçu d'image par lien.
    assert all(message.rstrip().endswith("```") for message in envoyes[1:])
    assert all(len(message) <= 2000 for message in envoyes)
