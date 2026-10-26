"""/staff watch : tous les événements, choisis un par un, et qui remontent VRAIMENT.

Chaque clé du catalogue est déclenchée par son vrai écouteur Discord : le
test échoue si un événement s'affiche dans le menu sans jamais être
enregistré.
"""
import asyncio
import datetime as dt
import json
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import staff_suite as ss  # noqa: E402
from utils import watch_events as we  # noqa: E402

GUILD, MEMBRE, AUTRE = 1, 42, 77


class _Db:
    def __init__(self, lignes=()):
        self.insertions, self.majs = [], []
        self.lignes = list(lignes)

    async def execute(self, sql, params=()):
        if "INSERT INTO staff_watch_events_v1" in sql:
            self.insertions.append(params[1])
        elif sql.startswith("UPDATE staff_watches_v1"):
            self.majs.append(params)

    async def fetchall(self, sql, params=()):
        return self.lignes

    async def fetchone(self, sql, params=()):
        return None


def _suite(events=we.KEYS, *, presences=False, audit=True):
    intents = discord.Intents.default()
    intents.members = intents.message_content = True
    intents.presences = presences
    me = SimpleNamespace(guild_permissions=discord.Permissions(view_audit_log=audit, manage_guild=True))
    guild = SimpleNamespace(id=GUILD, me=me)
    bot = SimpleNamespace(db=_Db(), intents=intents, get_guild=lambda _i: guild)
    suite = ss.StaffSuite(bot)
    suite._watch_cache = {(GUILD, MEMBRE): [{"id": 9, "status": "actif", "end_at": None, "events": set(events)}]}
    return suite


def _salon(cid=5):
    return SimpleNamespace(id=cid, mention=f"<#{cid}>", name="général")


def _guild():
    return SimpleNamespace(id=GUILD)


def _membre(**extra):
    base = dict(
        id=MEMBRE, bot=False, guild=_guild(), roles=[], display_name="Jimmy",
        display_avatar=SimpleNamespace(url="a"), timed_out_until=None, status="online",
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _message(content="salut"):
    return SimpleNamespace(guild=_guild(), author=_membre(), channel=_salon(), content=content)


def _vocal(channel=None, **flags):
    defaults = dict(self_mute=False, self_deaf=False, self_video=False, self_stream=False, mute=False, deaf=False)
    defaults.update(flags)
    return SimpleNamespace(channel=channel, **defaults)


def _audit(action, **extra):
    return SimpleNamespace(
        action=getattr(discord.AuditLogAction, action), user_id=MEMBRE, guild=_guild(),
        target=SimpleNamespace(id=AUTRE, mention=f"<@{AUTRE}>"), reason="test",
        changes=SimpleNamespace(after=SimpleNamespace()), **extra,
    )


DECLENCHEURS = {
    "messages": lambda s: s.on_message(_message()),
    "deleted": lambda s: s.on_message_delete(_message()),
    "edited": lambda s: s.on_message_edit(_message("avant"), _message("après")),
    "threads": lambda s: s.on_thread_create(SimpleNamespace(
        guild=_guild(), owner_id=MEMBRE, mention="<#8>", parent=_salon(), id=8)),
    "reactions": lambda s: s.on_reaction_add(SimpleNamespace(message=_message(), emoji="👍"), _membre()),
    "reactions_removed": lambda s: s.on_reaction_remove(SimpleNamespace(message=_message(), emoji="👍"), _membre()),
    "voice": lambda s: s.on_voice_state_update(_membre(), _vocal(None), _vocal(_salon(6))),
    "voice_state": lambda s: s.on_voice_state_update(_membre(), _vocal(_salon(6)), _vocal(_salon(6), self_mute=True)),
    "presence": lambda s: s.on_presence_update(_membre(status="online"), _membre(status="idle")),
    "profile": lambda s: s.on_member_update(_membre(), _membre(display_name="Jim")),
    "username": lambda s: s.on_user_update(
        SimpleNamespace(id=MEMBRE, name="jimmy", global_name="J", avatar=None),
        SimpleNamespace(id=MEMBRE, name="jimmy2", global_name="J", avatar=None)),
    "roles": lambda s: s.on_member_update(
        _membre(), _membre(roles=[SimpleNamespace(id=3, mention="<@&3>")])),
    "timeout": lambda s: s.on_member_update(
        _membre(), _membre(timed_out_until=dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))),
    "bans": lambda s: s.on_audit_log_entry_create(SimpleNamespace(
        action=discord.AuditLogAction.ban, user_id=AUTRE, guild=_guild(),
        target=SimpleNamespace(id=MEMBRE), reason=None, changes=SimpleNamespace(after=SimpleNamespace()))),
    "join_leave": lambda s: s.on_member_join(_membre()),
    "invites": lambda s: s.on_invite_create(SimpleNamespace(
        guild=_guild(), inviter=SimpleNamespace(id=MEMBRE), code="abc", channel=_salon())),
    "mod_actions": lambda s: s.on_audit_log_entry_create(_audit("ban")),
    "channels": lambda s: s.on_audit_log_entry_create(_audit("channel_delete")),
    "permissions": lambda s: s.on_audit_log_entry_create(_audit("overwrite_update")),
    "role_admin": lambda s: s.on_audit_log_entry_create(_audit("member_role_update")),
    "message_admin": lambda s: s.on_audit_log_entry_create(_audit("message_delete")),
}


def test_le_catalogue_tient_dans_un_menu_discord():
    assert len(set(we.KEYS)) == len(we.KEYS)
    assert len(we.KEYS) <= 25  # limite d'options d'un menu Discord
    assert set(DECLENCHEURS) == set(we.KEYS), "chaque événement doit avoir un déclencheur testé"


@pytest.mark.parametrize("cle", we.KEYS)
def test_chaque_evenement_est_vraiment_enregistre(cle):
    suite = _suite(events={cle})
    asyncio.run(DECLENCHEURS[cle](suite))
    assert suite.bot.db.insertions == [cle]


@pytest.mark.parametrize("cle", we.KEYS)
def test_un_evenement_non_choisi_n_enregistre_rien(cle):
    autres = set(we.KEYS) - {cle}
    suite = _suite(events=autres)
    asyncio.run(DECLENCHEURS[cle](suite))
    assert cle not in suite.bot.db.insertions


def test_timeout_donne_par_le_membre_est_une_sanction_donnee():
    suite = _suite(events={"mod_actions"})
    entree = _audit("member_update")
    entree.changes = SimpleNamespace(after=SimpleNamespace(timed_out_until=dt.datetime(2030, 1, 1)))
    asyncio.run(suite.on_audit_log_entry_create(entree))
    assert suite.bot.db.insertions == ["mod_actions"]


def _vue(suite, **kwargs):
    async def creer():
        return ss.WatchSetupView(suite, 7, GUILD, MEMBRE, **kwargs)
    return asyncio.run(creer())


def _menus(vue):
    return [i for i in vue.children if isinstance(i, discord.ui.Select)]


def test_rien_n_est_coche_d_office_et_demarrer_est_grise():
    vue = _vue(_suite())
    assert vue.events == set()
    assert vue.start.disabled is True
    menus = _menus(vue)
    # Trois menus courts par famille, qui couvrent tout le catalogue.
    assert len(menus) == len(we.GROUPS)
    assert sorted(o.value for m in menus for o in m.options) == sorted(we.KEYS)
    assert all(m.min_values == 0 for m in menus)
    assert not any(o.default for m in menus for o in m.options)


def test_le_salon_de_publication_est_obligatoire():
    vue = _vue(_suite(), events=["messages"])
    assert vue.start.disabled is True  # événement choisi, mais pas de salon
    vue = _vue(_suite(), events=["messages"], channel_id=55)
    assert vue.start.disabled is False
    salon = next(i for i in vue.children if isinstance(i, discord.ui.ChannelSelect))
    assert [d.id for d in salon.default_values] == [55]


def test_chaque_evenement_est_decrit():
    vue = _vue(_suite(presences=True))
    for menu in _menus(vue):
        for option in menu.options:
            assert option.description and len(option.description) >= 15, option.label


def test_les_besoins_discord_sont_affiches_clairement():
    vue = _vue(_suite(presences=False, audit=False))
    descriptions = {o.value: o.description for m in _menus(vue) for o in m.options}
    assert "intent Présence" in descriptions["presence"]
    assert "Voir les logs du serveur" in descriptions["mod_actions"]
    texte = " ".join(
        str(getattr(i, "content", "")) for i in vue.panel().walk_children()
        if isinstance(i, discord.ui.TextDisplay)
    )
    assert "Ne remonteront rien" in texte and "Présence" in texte


def test_un_evenement_est_publie_dans_le_salon_sans_ping():
    envois = []

    class _Salon:
        async def send(self, **kwargs):
            envois.append(kwargs)

    suite = _suite(events={"messages"})
    guild = SimpleNamespace(id=GUILD, get_channel=lambda cid: _Salon() if cid == 55 else None)
    suite.bot.get_guild = lambda _i: guild
    suite._watch_cache[(GUILD, MEMBRE)][0]["channel_id"] = 55
    asyncio.run(DECLENCHEURS["messages"](suite))
    assert len(envois) == 1
    carte, mentions = envois[0]["embed"], envois[0]["allowed_mentions"]
    assert carte.title == "💬 Messages envoyés" and f"<@{MEMBRE}>" in carte.description
    assert mentions.users is False and mentions.roles is False and mentions.everyone is False


def test_tout_selectionner_puis_tout_deselectionner(monkeypatch):
    suite = _suite()
    editions = []

    async def editer(_cible, panneau, **_k):
        editions.append(panneau)

    monkeypatch.setattr(ss.panels, "editer", editer)

    async def scenario():
        vue = ss.WatchSetupView(suite, 7, GUILD, MEMBRE)
        inter = SimpleNamespace(response=object())
        await vue.select_all.callback(inter)
        tout = vue.events.copy()
        await vue.select_none.callback(inter)
        return tout, vue.events

    tout, rien = asyncio.run(scenario())
    assert tout == set(we.KEYS) and rien == set()
    assert len(editions) == 2


def test_modifier_une_surveillance_active_enregistre_en_base(monkeypatch):
    suite = _suite()
    rechargements = []

    async def recharger():
        rechargements.append(1)

    async def panneau(*_a):
        return "panneau"

    async def editer(*_a, **_k):
        return None

    monkeypatch.setattr(suite, "reload_watch_cache", recharger)
    monkeypatch.setattr(suite, "watch_panel", panneau)
    monkeypatch.setattr(ss.panels, "editer", editer)

    async def scenario():
        vue = ss.WatchSetupView(suite, 7, GUILD, MEMBRE, events=["roles", "bans"], watch_id=9, channel_id=55)
        assert vue.start.label == "Enregistrer" and vue.start.disabled is False
        await vue.start.callback(SimpleNamespace(response=object(), guild=_guild(), user=SimpleNamespace(id=7)))

    asyncio.run(scenario())
    events_json, channel_id, watch_id, _guild_id = suite.bot.db.majs[0]
    assert json.loads(events_json) == ["roles", "bans"] and watch_id == 9 and channel_id == 55
    assert rechargements


def test_les_choix_survivent_au_redemarrage():
    suite = _suite()
    suite.bot.db.lignes = [
        {"id": 1, "guild_id": GUILD, "member_id": MEMBRE, "status": "actif", "end_at": None,
         "events_json": json.dumps(["voice", "bans"])},
        {"id": 2, "guild_id": GUILD, "member_id": AUTRE, "status": "actif", "end_at": None,
         "events_json": "{illisible"},
    ]
    asyncio.run(suite.reload_watch_cache())
    assert suite._watch_cache[(GUILD, MEMBRE)][0]["events"] == {"voice", "bans"}
    # Un choix illisible n'active rien d'office.
    assert suite._watch_cache[(GUILD, AUTRE)][0]["events"] == set()
