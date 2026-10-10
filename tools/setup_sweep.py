#!/usr/bin/env python3
"""Balayage de /setup sur le bot booté : chaque page, chaque bouton, chaque menu.

Pour chaque page servie (cogs/setup_experience_v74 — la couche qui gagne) :
construction, sérialisation, limite Discord de 40 composants ; puis chaque
contrôle est cliqué par un administrateur sur une page fraîchement construite.
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


async def main() -> int:
    from cogs import setup_experience_v74 as v74

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    pages = [None, "avancé", *v74.CATEGORY_ORDER, *EXTRA_PAGES]
    problems: list[str] = []
    clicked = 0
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
        for index in range(len(controls(view))):
            fresh = await build(bot, guild, page)
            items = controls(fresh)
            if index >= len(items):
                break
            item = items[index]
            if isinstance(item, discord.ui.Select):
                fill(item, guild)
            inter = interaction(bot)
            since = len(h.CALLS)
            try:
                await asyncio.wait_for(item.callback(inter), 10)
                await h.settle(idle=0.2, maximum=1.5)
            except Exception as exc:  # noqa: BLE001
                tb = traceback.extract_tb(exc.__traceback__)[-1]
                problems.append(f"[cassé    ] {name} · {label(item)} : {type(exc).__name__}: {str(exc)[:90]} "
                                f"({pathlib.Path(tb.filename).name}:{tb.lineno})")
                continue
            finally:
                clicked += 1
            answered = inter.response.is_done() or any(
                "/interactions/" in p or "/webhooks/" in p for _m, p, _js in h.CALLS[since:])
            if not answered:
                problems.append(f"[muet     ] {name} · {label(item)} : aucune réponse (« Échec de l'interaction »)")
                continue
            shown = h.visible_text(h.CALLS[since:])
            if "erreur technique" in shown.lower() or "SXR-" in shown:
                problems.append(f"[erreur   ] {name} · {label(item)} : {shown[:120]!r}")
        print(f"{name:14} {total:3} composants, {len(controls(view)):2} contrôles", flush=True)
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
