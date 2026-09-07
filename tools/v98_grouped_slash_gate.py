"""Gate V98 : arborescence slash sémantique et entrypoint Railway HA."""
from __future__ import annotations

import sys
from pathlib import Path

# Un script lancé via ``python tools/...`` reçoit ``tools/`` comme premier chemin Python.
# Réinjecter explicitement la racine du dépôt rend le gate identique en local et sur Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import discord
from discord import app_commands
from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v98_slash as v98


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def make_target(original: str, root: str, leaf: str | None = None) -> v95.SlashTarget:
    async def callback(ctx):
        return None

    command = commands.Command(
        callback,
        name=original.replace(" ", "-")[:32],
        description=f"Commande de gate {original}",
    )
    return v95.SlashTarget(
        command=command,
        root_name=root,
        leaf_name=leaf or original.replace(" ", "-"),
        original_name=original,
        native_options=True,
    )


def main() -> int:
    errors: list[str] = []

    v98.install()
    expected_roots = {
        "levels": "level",
        "games": "game",
        "roles": "role",
        "sanctions": "moderation",
    }
    for category, root in expected_roots.items():
        if v95.CATEGORY_ROOTS.get(category) != root:
            fail(f"racine {category!r} != {root!r}", errors)

    panel = make_target("ticketpanel", "ticket", "panel")
    if v98.semantic_bucket("ticket", panel) != "panel":
        fail("ticketpanel non classé dans /ticket panel", errors)
    if v98.semantic_leaf("ticket", "panel", panel) != "create":
        fail("ticketpanel non renommé en create", errors)

    raid = make_target("antiraid", "security")
    if v98.semantic_bucket("security", raid) != "automod":
        fail("antiraid non classé dans /security automod", errors)
    if v98.semantic_leaf("security", "automod", raid) != "raid":
        fail("antiraid non renommé en raid", errors)

    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
    targets = [make_target(f"guard-{index}", "security") for index in range(30)]
    original_builder = v95._build_targets
    try:
        v95._build_targets = lambda _bot: targets
        report = v98._add_grouped_surface_v98(bot)
    finally:
        v95._build_targets = original_builder

    security = bot.tree.get_command("security")
    if not isinstance(security, app_commands.Group):
        fail("/security absent ou non groupé", errors)
    else:
        if not security.commands:
            fail("/security ne contient aucun sous-groupe", errors)
        if any(not isinstance(child, app_commands.Group) for child in security.commands):
            fail("/security contient encore des commandes plates", errors)
        if any("page-" in child.name for child in security.commands):
            fail("un sous-groupe page-N subsiste", errors)
        if any(len(child.commands) > v95.MAX_CHILDREN for child in security.commands):
            fail("un sous-groupe dépasse 25 commandes", errors)

    if len(report) != 30:
        fail(f"30 actions attendues, {len(report)} générées", errors)
    if any(" page-" in path for path in report):
        fail("un chemin page-N subsiste dans le rapport", errors)

    ha_source = Path("sentrix_v98_ha_product_boot.py").read_text(encoding="utf-8")
    if "import railway_ha_product_boot as product_boot" not in ha_source:
        fail("entrypoint V98 HA ne délègue pas au bootstrap produit existant", errors)
    if "install_v98()" not in ha_source:
        fail("entrypoint V98 HA n'installe pas la surface V98", errors)
    if "product_boot.ha_boot.run()" not in ha_source:
        fail("entrypoint V98 HA ne relance pas le moteur HA historique", errors)

    if errors:
        for error in errors:
            print("[ERROR]", error)
        print(f"ECHEC V98: {len(errors)} problème(s)")
        return 1

    print(
        "OK V98: racines normalisées, sous-groupes sémantiques, "
        "aucun page-N, budget <=25, entrypoint Railway HA conservé"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
