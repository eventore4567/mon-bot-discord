#!/usr/bin/env python3
"""Parcours complet des suggestions sur le bot booté comme en production.

Chaque étape simule ce que Discord envoie réellement — commande slash, clic de
bouton (interaction de type 3), envoi de formulaire (type 5) — et vérifie ce que
SentriX renvoie à Discord ET ce qu'il écrit en base.

    python3 tools/suggestions_e2e.py

Code de sortie 1 si une étape échoue.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, step: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), step, detail))
    print(f"[{'OK ' if ok else 'ÉCHEC'}] {step}" + (f" — {detail}" if detail and not ok else ""), flush=True)
    return bool(ok)


def persona(name: str) -> dict:
    return {
        "membre": dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,)),
        "moderateur": dict(author_id=h.MOD_ID, author_roles=(h.MOD_ROLE_ID,)),
        "admin": dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,)),
    }[name]


def _base(author_id: int, roles, *, kind: int, data: dict, message: dict | None = None) -> dict:
    everything = str(discord.Permissions.all().value)
    payload = {
        "id": str(h.next_id()), "application_id": str(h.BOT_ID), "type": kind, "token": "tok",
        "version": 1, "guild_id": str(h.GID), "channel_id": str(h.CID),
        "channel": {"id": str(h.CID), "type": 0}, "locale": "fr", "guild_locale": "fr",
        "app_permissions": everything, "entitlements": [], "attachment_size_limit": 26214400,
        "authorizing_integration_owners": {}, "context": 0,
        "member": dict(h.member_payload(author_id, "testeur", list(roles)), permissions=everything),
        "data": data,
    }
    if message is not None:
        payload["message"] = message
    return payload


def callbacks(since: int) -> list[dict]:
    """Réponses d'interaction envoyées par SentriX depuis l'index donné."""
    out = []
    for method, path, body in h.CALLS[since:]:
        if method == "POST" and path.endswith("/callback") and isinstance(body, dict):
            out.append(body)
    return out


async def slash(bot, root: str, sub: str, who: str, options=None) -> int:
    since = len(h.CALLS)
    p = persona(who)
    inter = h.build_interaction(
        bot, root, [{"name": sub, "type": 1, "options": options or []}], **p,
    )
    await asyncio.wait_for(bot.tree._call(inter), 15)
    await h.settle(idle=0.2, maximum=1.5)
    return since


async def click(bot, custom_id: str, message_id: int, who: str) -> int:
    since = len(h.CALLS)
    p = persona(who)
    message = h.message_payload(message_id, h.CID, "")
    data = _base(p["author_id"], p["author_roles"], kind=3,
                 data={"custom_id": custom_id, "component_type": 2}, message=message)
    inter = discord.Interaction(data=data, state=bot._connection)
    bot._connection._view_store  # noqa: B018 — garanti initialisé
    bot.dispatch("interaction", inter)
    await h.settle(idle=0.3, maximum=2.0)
    return since


async def submit_modal(bot, modal_custom_id: str, components: list, who: str, message_id: int | None = None) -> int:
    since = len(h.CALLS)
    p = persona(who)
    message = h.message_payload(message_id, h.CID, "") if message_id else None
    data = _base(p["author_id"], p["author_roles"], kind=5,
                 data={"custom_id": modal_custom_id, "components": components}, message=message)
    inter = discord.Interaction(data=data, state=bot._connection)
    bot._connection._view_store.dispatch_modal(modal_custom_id, inter, components, {})
    await h.settle(idle=0.4, maximum=3.0)
    return since


def _buttons(node) -> list[dict]:
    """Tous les boutons d'un arbre de composants Components V2."""
    if isinstance(node, dict):
        found = [node] if node.get("type") == 2 else []
        for key in ("components", "accessory"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    found.extend(_buttons(item))
            elif isinstance(child, dict):
                found.extend(_buttons(child))
        return found
    return []


def text_field(custom_id: str, value: str) -> dict:
    return {"type": 18, "id": 0, "component": {"type": 4, "custom_id": custom_id, "value": value}}


def file_field(custom_id: str) -> dict:
    return {"type": 18, "id": 0, "component": {"type": 19, "custom_id": custom_id, "values": []}}


def select_field(custom_id: str, value: str) -> dict:
    return {"type": 18, "id": 0, "component": {"type": 3, "custom_id": custom_id, "values": [value]}}


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from services import suggestions as svc
    from utils import slash_catalog as sc

    # 1 — Chargement et publication.
    check(bot.get_cog("Suggestions") is not None, "le cog Suggestions est chargé")
    group = bot.tree.get_command("suggestions")
    leaves = {c.name: c for c in getattr(group, "commands", [])}
    check(set(leaves) >= {"submit", "setup", "panel", "status"}, "/suggestions publie submit, setup, panel, status",
          str(sorted(leaves)))
    submit = leaves.get("submit")
    check(submit is not None and submit.callback.__module__ == "cogs.suggestions",
          "/suggestions submit est la commande native (formulaire sans defer)")
    check(not (getattr(bot, "_sentrix_slash_catalog_report", {}) or {}).get("missing"),
          "le catalogue ne signale aucune source manquante")

    # 2 — Avant configuration : refus clair, aucun salon créé.
    since = await slash(bot, "suggestions", "submit", "membre")
    texte = h.visible_text(h.CALLS[since:])
    check("pas encore configurées" in texte, "avant configuration, /suggestions submit explique quoi faire", texte[:160])
    created_channels = [c for c in h.CALLS[since:] if c[0] == "POST" and c[1].endswith("/channels")]
    check(not created_channels, "aucun salon n'est créé automatiquement")

    # 3 — Un membre ne peut pas configurer.
    since = await slash(bot, "suggestions", "setup", "membre",
                        [{"name": "channel", "type": 7, "value": str(h.CID)}])
    settings = await svc.get_settings(bot.db, h.GID)
    check(not settings.configured, "un membre ne peut pas configurer les suggestions")

    # 4 — L'administrateur configure.
    since = await slash(bot, "suggestions", "setup", "admin",
                        [{"name": "channel", "type": 7, "value": str(h.CID)},
                         {"name": "cooldown", "type": 4, "value": 0}])
    settings = await svc.get_settings(bot.db, h.GID)
    check(settings.channel_id == h.CID, "l'administrateur configure le salon", h.visible_text(h.CALLS[since:])[:200])

    # 5 — Le membre ouvre le formulaire.
    since = await slash(bot, "suggestions", "submit", "membre")
    modals = [c for c in callbacks(since) if c.get("type") == 9]
    check(len(modals) == 1, "/suggestions submit ouvre un formulaire", json.dumps(callbacks(since))[:200])
    modal_id = modals[0]["data"]["custom_id"] if modals else ""

    # 6 — Il l'envoie, avec un @everyone piégé.
    since = await submit_modal(bot, modal_id, [
        text_field("sentrix:suggestions:title", "Salon d'entraide"),
        text_field("sentrix:suggestions:body", "Créer un salon d'entraide. @everyone venez voir"),
        file_field("sentrix:suggestions:file"),
    ], "membre")
    posts = [c for c in h.CALLS[since:] if c[0] == "POST" and c[1] == f"/channels/{h.CID}/messages"]
    check(len(posts) == 1, "la suggestion est publiée dans le salon configuré", str([c[:2] for c in h.CALLS[since:]])[:300])
    card = h.visible_text(posts) if posts else ""
    check("Suggestion #0001" in card and "Salon d'entraide" in card, "la carte affiche le numéro et le titre", card[:200])
    mentions = (posts[0][2] or {}).get("allowed_mentions", {}) if posts else {}
    check("everyone" not in (mentions.get("parse") or []), "un @everyone dans une suggestion ne ping personne", str(mentions))
    s = await svc.by_number(bot.db, h.GID, 1)
    check(s is not None and s.message_id is not None, "la suggestion est en base, reliée à son message")
    message_id = s.message_id if s else 0

    # 7 — Votes : pour, retrait, bascule.
    since = await click(bot, "sentrix:suggestions:up", message_id, "membre")
    check(await svc.counts(bot.db, s.id) == (1, 0), "un clic sur Pour compte un vote")
    check(any(c.get("type") == 7 for c in callbacks(since)), "la carte se met à jour sur place")
    await click(bot, "sentrix:suggestions:up", message_id, "membre")
    check(await svc.counts(bot.db, s.id) == (0, 0), "recliquer sur Pour retire le vote")
    await click(bot, "sentrix:suggestions:up", message_id, "membre")
    await click(bot, "sentrix:suggestions:down", message_id, "membre")
    check(await svc.counts(bot.db, s.id) == (0, 1), "cliquer sur Contre bascule le vote")
    await click(bot, "sentrix:suggestions:up", message_id, "moderateur")
    check(await svc.counts(bot.db, s.id) == (1, 1), "chaque membre a son propre vote")

    # 8 — Gérer : refusé à un membre, formulaire pour le staff.
    since = await click(bot, "sentrix:suggestions:manage", message_id, "membre")
    check(not any(c.get("type") == 9 for c in callbacks(since)), "« Gérer » est refusé à un membre")
    since = await click(bot, "sentrix:suggestions:manage", message_id, "moderateur")
    modals = [c for c in callbacks(since) if c.get("type") == 9]
    check(len(modals) == 1, "« Gérer » ouvre le formulaire du staff")
    manage_id = modals[0]["data"]["custom_id"] if modals else ""

    # 9 — Décision du staff.
    since = await submit_modal(bot, manage_id, [
        select_field("sentrix:suggestions:status", "accepted"),
        text_field("sentrix:suggestions:response", "On l'ajoute la semaine prochaine."),
    ], "moderateur", message_id=message_id)
    s = await svc.by_number(bot.db, h.GID, 1)
    check(s.status == "accepted" and s.staff_id == h.MOD_ID, "le staff accepte la suggestion")
    updated = [c for c in callbacks(since) if c.get("type") == 7]
    shown = h.visible_text(h.CALLS[since:])
    check(updated and "Acceptée" in shown and "semaine prochaine" in shown,
          "la carte affiche le statut et la réponse du staff", shown[:200])
    logs = [c for c in h.CALLS[since:] if c[0] == "POST" and c[1] == f"/channels/{h.LOGCID}/messages"]
    check(bool(logs), "la décision part dans les journaux")

    # 10 — Plus de vote sur une suggestion tranchée.
    before = await svc.counts(bot.db, s.id)
    since = await click(bot, "sentrix:suggestions:up", message_id, "admin")
    check(await svc.counts(bot.db, s.id) == before, "on ne vote plus sur une suggestion acceptée")

    # 11 — Préfixe : +suggest avec texte, et la commande de statut.
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+suggest Un salon pour les memes", **persona("membre")), 15)
    await h.settle(idle=0.3, maximum=2)
    deux = await svc.by_number(bot.db, h.GID, 2)
    check(deux is not None, "+suggest publie la suggestion #0002")
    await click(bot, "sentrix:suggestions:up", deux.message_id, "admin")
    check(await svc.counts(bot.db, deux.id) == (1, 0), "on vote aussi sur une suggestion publiée en préfixe")
    await asyncio.wait_for(h.run_prefix(bot, guild, "+suggestion-status 2 rejected Hors sujet", **persona("membre")), 15)
    await h.settle(idle=0.3, maximum=2)
    check((await svc.by_number(bot.db, h.GID, 2)).status == "pending", "+suggestion-status est refusé à un membre")
    await asyncio.wait_for(h.run_prefix(bot, guild, "+suggestion-status 2 rejected Hors sujet", **persona("moderateur")), 15)
    await h.settle(idle=0.3, maximum=2)
    check((await svc.by_number(bot.db, h.GID, 2)).status == "rejected", "+suggestion-status fonctionne pour le staff")

    # 12 — Serveur anglophone : la carte suit la langue du serveur, même publiée
    #      depuis un formulaire (hors du contexte de commande qui traduit d'habitude).
    from cogs import language_runtime
    await language_runtime.set_language(bot, h.GID, language_runtime.LANG_EN)
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+suggest A channel for memes", **persona("admin")), 15)
    await h.settle(idle=0.3, maximum=2)
    posts = [c for c in h.CALLS[since:] if c[0] == "POST" and c[1] == f"/channels/{h.CID}/messages"]
    card = h.visible_text(posts)
    check("Proposal" in card and "Pending" in card and "Proposition" not in card,
          "sur un serveur anglais, la carte est en anglais", card[:200])
    labels = [b.get("label") for c in posts for row in (c[2] or {}).get("components", [])
              for b in _buttons(row)]
    check("Create a suggestion" in labels and any(str(l).startswith("For ") for l in labels),
          "les boutons sont en anglais", str(labels))

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
