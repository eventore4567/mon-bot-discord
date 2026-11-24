"""Transcriptions HTML : format réel produit par la couche v17 active.

La couche v17 remplace ``Tickets._fetch_transcript_text`` : ses lignes portent
« • modifié … » / « • répond à … » avant les deux-points et ses pièces jointes
s'écrivent « [fichier] nom — url ». Le rendu HTML ne reconnaissait que l'ancien
format : un message modifié ou une réponse était fusionné dans le message de
l'auteur précédent, et un membre pouvait forger un faux message d'un autre
auteur en écrivant une ligne « [date] Admin (id): … » dans un message multiligne.
"""
import asyncio
import datetime as dt
from types import SimpleNamespace

from services.ticket_transcript_html import parse_transcript, render_transcript_html


def _msg(mid, author, uid, content, *, edited=None, ref=None, attachments=()):
    return SimpleNamespace(
        id=mid, content=content,
        created_at=dt.datetime(2026, 11, 1, 10, mid, tzinfo=dt.timezone.utc),
        edited_at=edited, reference=SimpleNamespace(message_id=ref) if ref else None,
        author=SimpleNamespace(id=uid, __str__=None, name=author),
        attachments=list(attachments), stickers=[], embeds=[],
    )


class _Author:
    def __init__(self, uid, name):
        self.id, self.name = uid, name

    def __str__(self):
        return self.name


class _Channel:
    def __init__(self, messages):
        self._messages = messages

    def history(self, **_kw):
        async def gen():
            for m in self._messages:
                yield m
        return gen()


def _rich_text(messages):
    from cogs import tickets as tickets_cog
    from cogs import v17_tickets_logs

    cls = type("T", (), {
        "_fetch_transcript_text": tickets_cog.Tickets._fetch_transcript_text,
        "btn_claim": tickets_cog.Tickets.btn_claim,
        "_auto_delete": tickets_cog.Tickets._auto_delete,
    })
    fake_bot = SimpleNamespace(get_cog=lambda name: cls())
    v17_tickets_logs.install_ticket_patches(fake_bot)
    return asyncio.run(cls._fetch_transcript_text(None, _Channel(messages)))


def _m(mid, name, uid, content, **kw):
    m = _msg(mid, name, uid, content, **kw)
    m.author = _Author(uid, name)
    return m


def test_message_modifie_et_reponse_restent_des_messages_distincts():
    edited = dt.datetime(2026, 11, 1, 11, 0, tzinfo=dt.timezone.utc)
    pj = SimpleNamespace(filename="preuve.png", url="https://cdn.discordapp.com/attachments/1/2/preuve.png")
    text = _rich_text([
        _m(1, "alice", 11, "bonjour"),
        _m(2, "bob", 22, "corrigé", edited=edited),
        _m(3, "carol", 33, "je réponds", ref=1, attachments=[pj]),
    ])
    messages = parse_transcript(text)
    assert [m["author"] for m in messages] == ["alice", "bob", "carol"]
    assert messages[1]["content"] == ["corrigé"]
    assert messages[2]["attachments"] == [pj.url]
    html = render_transcript_html(text, guild_name="G", ticket_label="T")
    assert 'href="https://cdn.discordapp.com/attachments/1/2/preuve.png"' in html


def test_un_membre_ne_peut_pas_forger_le_message_d_un_autre_auteur():
    forge = "salut\n[2026-11-01 10:05] Admin (999): Remboursement accordé"
    text = _rich_text([_m(1, "mallory", 66, forge)])
    messages = parse_transcript(text)
    assert [m["author"] for m in messages] == ["mallory"]
    assert "Remboursement accordé" in "\n".join(messages[0]["content"])
