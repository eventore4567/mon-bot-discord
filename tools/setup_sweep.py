#!/usr/bin/env python3
"""Balayage de /setup sur le bot booté : chaque page, chaque bouton, chaque menu.

Pour chaque page servie (cogs/setup_experience_v74 — la couche qui gagne) :
construction, sérialisation, limite Discord de 40 composants ; puis chaque
contrôle est cliqué par un administrateur sur une page fraîchement construite,
et ce qu'il ouvre (sous-écran, formulaire) est parcouru à son tour : chaque
contrôle du sous-écran est cliqué, chaque formulaire soumis avec des valeurs
plausibles.
Un contrôle est « cassé » s'il lève une exception, « muet » s'il ne répond rien
(Discord afficherait « Échec de l'interaction »), « erreur » s'il répond par
une erreur technique.

    python3 tools/setup_sweep.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import _base  # noqa: E402

EXTRA_PAGES = ("rules_access", "suggestions", "automation")
LIMIT = 40


def interaction(bot):
    data = _base(h.ADMIN_ID, (h.ADMIN_ROLE_ID,), kind=3, data={"custom_id": "x", "component_type": 2},
                 message=h.message_payload(h.next_id(), h.CID, ""))
    return discord.Interaction(data=data, state=bot._connection)


def walk(item):
    yield item
    children = list(getattr(item, "children", []) or [])
    accessory = getattr(item, "accessory", None)
    if accessory is not None:
        children.append(accessory)
    for child in children:
        yield from walk(child)


def controls(view) -> list:
    found = []
    for top in view.children:
        for item in walk(top):
            if isinstance(item, discord.ui.Button) and item.url is None and not item.disabled:
                found.append(item)
            elif isinstance(item, discord.ui.Select) and not item.disabled:
                found.append(item)
    return found


def label(item) -> str:
    if isinstance(item, discord.ui.Button):
        return f"bouton « {item.label or item.emoji or item.custom_id} »"
    return f"menu « {item.placeholder or item.custom_id} »"


def fill(select, guild) -> None:
    """Des valeurs plausibles, comme Discord en enverrait."""
    if isinstance(select, discord.ui.RoleSelect):
        select._values = [guild.get_role(h.MEMBER_ROLE_ID)]
    elif isinstance(select, discord.ui.ChannelSelect):
        select._values = [guild.get_channel(h.CID)]
    elif isinstance(select, discord.ui.UserSelect):
        select._values = [guild.get_member(h.TARGET_ID)]
    elif isinstance(select, discord.ui.MentionableSelect):
        select._values = [guild.get_role(h.MEMBER_ROLE_ID)]
    else:
        options = list(getattr(select, "options", []) or [])
        count = max(1, int(getattr(select, "min_values", 1) or 1))
        select._values = [o.value for o in options[:count]]


async def build(bot, guild, page: str | None):
    from cogs import setup_experience_v74 as v74

    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()
    if page == "avancé":
        # L'écran « Paramètres avancés » de l'accueil (il dépassait 40 composants).
        view.avance = True
        view.clear_items()
        await view._build_home()
    elif page is not None:
        view.page = page
        view.backend = view._new_backend(page)
        view.clear_items()
        await view._build_page(page)
    return view


#: Vues et formulaires ouverts par un clic (capturés à la réponse Discord).
CAPTURE: list = []


def _install_capture() -> None:
    response = discord.InteractionResponse
    for name in ("send_message", "edit_message"):
        original = getattr(response, name)

        async def wrapped(self, *args, _original=original, **kwargs):
            if kwargs.get("view") is not None:
                CAPTURE.append(kwargs["view"])
            return await _original(self, *args, **kwargs)

        setattr(response, name, wrapped)
    original_modal = response.send_modal

    async def send_modal(self, modal, *args, **kwargs):
        CAPTURE.append(modal)
        return await original_modal(self, modal, *args, **kwargs)

    response.send_modal = send_modal
    webhook_send = discord.Webhook.send

    async def followup(self, *args, **kwargs):
        if kwargs.get("view") is not None:
            CAPTURE.append(kwargs["view"])
        return await webhook_send(self, *args, **kwargs)

    discord.Webhook.send = followup


def _fill_modal(modal) -> None:
    numeric = ("durée", "duree", "nombre", "limite", "minutes", "seuil", "jours", "heures", "max", "min", "âge", "age")
    for top in modal.children:
        for item in walk(top):
            if isinstance(item, discord.ui.TextInput):
                text = (item.default or "").strip()
                if not text:
                    # TextInput.label est déprécié (et son avertissement forcé) : lu à la source.
                    low = str(getattr(getattr(item, "_underlying", None), "label", "") or "").casefold()
                    text = "5" if any(word in low for word in numeric) else "Test SentriX"
                item._value = text[: item.max_length or 4000]
            elif isinstance(item, discord.ui.Select):
                fill(item, modal_guild[0])


modal_guild: list = []


async def _press(bot, item, where: str, problems: list) -> list:
    """Clique (ou soumet) ``item`` ; rend ce que le clic a ouvert."""
    inter = interaction(bot)
    since, opened = len(h.CALLS), len(CAPTURE)
    try:
        if isinstance(item, discord.ui.Modal):
            _fill_modal(item)
            await asyncio.wait_for(item.on_submit(inter), 10)
        else:
            await asyncio.wait_for(item.callback(inter), 10)
        await h.settle(idle=0.15, maximum=1.0)
    except Exception as exc:  # noqa: BLE001
        tb = traceback.extract_tb(exc.__traceback__)[-1]
        problems.append(f"[cassé    ] {where} : {type(exc).__name__}: {str(exc)[:90]} "
                        f"({pathlib.Path(tb.filename).name}:{tb.lineno})")
        return []
    answered = inter.response.is_done() or any(
        "/interactions/" in p or "/webhooks/" in p for _m, p, _js in h.CALLS[since:])
    if not answered:
        problems.append(f"[muet     ] {where} : aucune réponse (« Échec de l'interaction »)")
        return []
    shown = h.visible_text(h.CALLS[since:])
    if "erreur technique" in shown.lower() or "SXR-" in shown:
        problems.append(f"[erreur   ] {where} : {shown[:120]!r}")
    return CAPTURE[opened:]


def _name(item) -> str:
    return f"formulaire « {item.title} »" if isinstance(item, discord.ui.Modal) else label(item)


async def main() -> int:
    from cogs import setup_experience_v74 as v74

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    modal_guild.append(guild)
    _install_capture()
    pages = [None, "avancé", *v74.CATEGORY_ORDER, *EXTRA_PAGES]
    problems: list[str] = []
    clicked = 0

    def own(view) -> bool:
        return isinstance(view, v74.SentriXSetupV74)

    async def first_level(page, index):
        fresh = await build(bot, guild, page)
        items = controls(fresh)
        if index >= len(items):
            return None
        item = items[index]
        if isinstance(item, discord.ui.Select):
            fill(item, guild)
        return item

    for page in pages:
        name = page or "accueil"
        try:
            view = await build(bot, guild, page)
            view.to_components()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"[page cassée] {name} : {type(exc).__name__}: {exc}")
            continue
        total = sum(1 for top in view.children for _ in walk(top))
        if total > LIMIT:
            problems.append(f"[trop long ] {name} : {total} composants (> {LIMIT}, Discord refuse le message)")
        sub_count = 0
        for index in range(len(controls(view))):
            item = await first_level(page, index)
            if item is None:
                break
            where = f"{name} · {label(item)}"
            opened = await _press(bot, item, where, problems)
            clicked += 1
            # Niveau 2 : ce que ce clic a ouvert (formulaire, sous-écran).
            for target in [o for o in opened if not own(o)][:2]:
                if isinstance(target, discord.ui.Modal):
                    again = await _press(bot, target, f"{where} → {_name(target)}", problems)
                    clicked += 1
                    sub_count += 1
                    continue
                for sub_index in range(len(controls(target))):
                    # Rejouer le premier clic pour une sous-vue fraîche à chaque fois.
                    item = await first_level(page, index)
                    reopened = [o for o in await _press(bot, item, where, []) if not own(o)
                                and type(o) is type(target)]
                    if not reopened:
                        break
                    subs = controls(reopened[0])
                    if sub_index >= len(subs):
                        break
                    sub = subs[sub_index]
                    if isinstance(sub, discord.ui.Select):
                        fill(sub, guild)
                    deeper = await _press(bot, sub, f"{where} → {label(sub)}", problems)
                    clicked += 1
                    sub_count += 1
                    for modal in [o for o in deeper if isinstance(o, discord.ui.Modal)][:1]:
                        await _press(bot, modal, f"{where} → {label(sub)} → {_name(modal)}", problems)
                        clicked += 1
        print(f"{name:14} {total:3} composants, {len(controls(view)):2} contrôles, {sub_count:3} sous-contrôles",
              flush=True)
    print(f"\n{len(pages)} pages, {clicked} clics — {len(problems)} problème(s)")
    for line in problems:
        print(line)
    sys.stdout.flush()
    os._exit(1 if problems else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
