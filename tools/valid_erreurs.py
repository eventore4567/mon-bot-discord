"""Les onze chemins d'erreur, rendus pour de vrai.

Une erreur est une interface comme une autre : elle a une banniere, un titre,
des sections et un pied. Ces chemins sont les plus vus par les utilisateurs et
les moins testes, parce qu'il faut provoquer la panne pour les voir.

On construit donc chaque erreur et on demande au module canonique le panneau
qu'il rendrait, puis on verifie ce que l'utilisateur verrait : banniere
presente, couleur semantique correcte, sections reelles, pied d'identite.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

from utils import sentrix_panels as panels  # noqa: E402


class _Salon:
    id = 7
    name = "general"


class _Membre:
    id = 42
    name = "Jayden"
    display_name = "Jayden"
    mention = "<@42>"
    bot = False


class _Ctx:
    def __init__(self, commande="ban"):
        self.author = _Membre()
        self.channel = _Salon()
        self.guild = None
        self.prefix = "+"
        self.interaction = None
        self.invoked_with = commande
        self.command = None
        self.message = None
        self.bot = None


def _erreur_slash():
    """CommandInvokeError lit command.name a la construction."""
    faux = type("Commande", (), {"name": "ban", "qualified_name": "ban"})()
    return discord.app_commands.CommandInvokeError(faux, RuntimeError("panne slash"))


def _cas() -> list[tuple[str, str, object]]:
    """(libelle, surface, erreur) — surface dit quel constructeur repond."""
    param = commands.Parameter(
        name="membre", kind=commands.Parameter.POSITIONAL_OR_KEYWORD
    )
    return [
        ("commande inconnue", "prefixe", commands.CommandNotFound("bam")),
        ("argument manquant", "prefixe", commands.MissingRequiredArgument(param)),
        ("argument invalide", "prefixe", commands.BadArgument("Membre introuvable.")),
        ("permission refusee (membre)", "prefixe",
         commands.MissingPermissions(["ban_members"])),
        ("permission refusee (bot)", "prefixe",
         commands.BotMissingPermissions(["manage_roles"])),
        ("recharge", "prefixe",
         commands.CommandOnCooldown(
             commands.Cooldown(1, 5.0), 3.2, commands.BucketType.user)),
        ("hors serveur", "prefixe", commands.NoPrivateMessage()),
        ("erreur interne", "prefixe",
         commands.CommandInvokeError(RuntimeError("panne interne"))),
        ("erreur slash", "slash", _erreur_slash()),
        ("echec de bouton", "composant", discord.ui.Button(label="Confirmer")),
        ("echec de modal", "composant", None),
    ]


def _controler(libelle: str, panneau) -> list[str]:
    problemes = []
    if not isinstance(panneau, panels.Panneau):
        return [f"{libelle} : ce n'est pas un Panneau ({type(panneau).__name__})"]

    if not panneau.fichiers():
        problemes.append(f"{libelle} : aucune banniere jointe")
    if panneau.kind not in ("danger", "warning", "info", "neutral"):
        problemes.append(f"{libelle} : intention inattendue « {panneau.kind} »")

    rendu = panels.texte_complet(panneau)
    if not rendu.startswith("## "):
        problemes.append(f"{libelle} : pas de titre de panneau")
    if "### ◢ " not in rendu:
        problemes.append(f"{libelle} : aucune section — l'erreur n'explique rien")
    if "\n-# " not in rendu:
        problemes.append(f"{libelle} : pas de pied d'identite")
    return problemes


def main() -> int:
    from cogs.final_error_embed_v5 import (
        _component_error_panel,
        _prefix_error_panel,
        _slash_error_panel,
    )

    problemes: list[str] = []
    for libelle, surface, erreur in _cas():
        try:
            if surface == "prefixe":
                panneau = _prefix_error_panel(_Ctx(), erreur)
            elif surface == "slash":
                panneau = _slash_error_panel(erreur)
            else:
                panneau = _component_error_panel(erreur)
        except Exception as exc:
            problemes.append(f"{libelle} : {type(exc).__name__}: {exc}")
            continue
        problemes += _controler(libelle, panneau)

    total = len(_cas())
    if not problemes:
        print(f"BILAN : {total}/{total} chemins d'erreur conformes")
        return 0
    print(f"BILAN : {total - len({p.split(' : ')[0] for p in problemes})}/{total} conformes\n")
    for p in problemes:
        print("   " + p)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
