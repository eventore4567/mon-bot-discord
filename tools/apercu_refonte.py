#!/usr/bin/env python3
"""Rend un panneau SentriX en texte, tel que Discord l'afficherait.

Sert a deux choses : voir le resultat sans ouvrir Discord, et prouver qu'une
interface a REELLEMENT ete recomposee — banniere en tete, sections separees,
hierarchie — plutot que simplement recoloree.

    python3 tools/apercu_refonte.py            tous les apercus
    python3 tools/apercu_refonte.py erreur     un seul
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import discord  # noqa: E402

from utils import sentrix_panels as panels  # noqa: E402

LARGEUR = 74


def rendre(panneau: panels.Panneau) -> str:
    """Reconstitue l'affichage : cadre accentue, banniere, blocs, filets."""
    lignes: list[str] = []
    accent = None

    def parcourir(items, dans_rangee=False):
        nonlocal accent
        boutons: list[str] = []
        for item in items or ():
            t = item.get("type")
            if t == 17:
                accent = item.get("accent_color")
            elif t == 12:
                for media in item.get("items", []):
                    nom = str(media.get("media", {}).get("url", "")).split("/")[-1]
                    lignes.append(f"[ BANNIÈRE : {nom} ]".center(LARGEUR))
            elif t == 10:
                for ligne in str(item.get("content", "")).split("\n"):
                    lignes.append(ligne)
            elif t == 14:
                lignes.append("─" * LARGEUR)
            elif t == 11:
                lignes.append(f"   ⌐ vignette : {str(item.get('media', {}).get('url',''))[:46]}")
            elif t == 2:
                boutons.append(f"[ {item.get('label', '')} ]")
            elif t == 3:
                options = len(item.get("options", []))
                lignes.append(f"( ▾ {item.get('placeholder', 'Choisir')} — {options} options )")
            for cle in ("components", "accessory"):
                valeur = item.get(cle)
                if isinstance(valeur, list):
                    parcourir(valeur, dans_rangee=(t == 1))
                elif isinstance(valeur, dict):
                    parcourir([valeur])
        if boutons:
            lignes.append("  ".join(boutons))

    parcourir(panneau.to_components())
    entete = f"┌{'─' * LARGEUR}┐"
    if accent is not None:
        entete = f"┌── accent 0x{accent:06x} {'─' * (LARGEUR - 20)}┐"
    corps = "\n".join(f"│ {l[:LARGEUR - 2]:<{LARGEUR - 2}} │" for l in lignes)
    joints = ", ".join(f.filename for f in panneau.fichiers()) or "aucune"
    return f"{entete}\n{corps}\n└{'─' * LARGEUR}┘\n   pièces jointes : {joints}"


def mesurer(panneau: panels.Panneau) -> dict:
    """Criteres de RESTRUCTURATION, pas de couleur."""
    plat: list[tuple[str, str]] = []

    def parcourir(items):
        for item in items or ():
            t = item.get("type")
            if t == 10:
                plat.append(("texte", str(item.get("content", ""))))
            elif t == 12:
                plat.append(("banniere", ""))
            elif t == 14:
                plat.append(("filet", ""))
            elif t == 2:
                plat.append(("bouton", str(item.get("label", ""))))
            elif t == 3:
                plat.append(("menu", str(item.get("placeholder", ""))))
            elif t == 11:
                plat.append(("vignette", ""))
            for cle in ("components", "accessory"):
                valeur = item.get(cle)
                if isinstance(valeur, list):
                    parcourir(valeur)
                elif isinstance(valeur, dict):
                    parcourir([valeur])

    parcourir(panneau.to_components())
    textes = [v for k, v in plat if k == "texte"]
    return {
        "banniere": any(k == "banniere" for k, _ in plat),
        "sections": sum(1 for t in textes if t.startswith("### ")),
        "filets": sum(1 for k, _ in plat if k == "filet"),
        "boutons": [v for k, v in plat if k == "bouton"],
        "menus": [v for k, v in plat if k == "menu"],
        "vignette": any(k == "vignette" for k, _ in plat),
        "titre": next((t.split("\n")[0].replace("## ", "") for t in textes if t.startswith("## ")), ""),
    }


def apercus() -> dict[str, panels.Panneau]:
    """Panneaux construits avec des donnees representatives, jamais inventees
    au-dela de ce qu'un vrai appel produirait."""
    from cogs import final_error_embed_v5 as erreurs
    from discord.ext import commands as dcommands

    class Ctx:
        clean_prefix = prefix = "+"
        invoked_with = "bann"
        command = None
        guild = None

    resultat: dict[str, panels.Panneau] = {}
    resultat["erreur · commande introuvable"] = erreurs._prefix_error_panel(
        Ctx(), dcommands.CommandNotFound("bann")
    )
    resultat["erreur · permission refusée"] = erreurs._prefix_error_panel(
        Ctx(), dcommands.MissingPermissions(["manage_guild"])
    )
    resultat["erreur · permission de SentriX"] = erreurs._prefix_error_panel(
        Ctx(), dcommands.BotMissingPermissions(["manage_roles"])
    )
    resultat["erreur · cooldown"] = erreurs._prefix_error_panel(
        Ctx(), dcommands.CommandOnCooldown(dcommands.Cooldown(1, 5.0), 3.4, dcommands.BucketType.user)
    )
    resultat["erreur · interne"] = erreurs._prefix_error_panel(Ctx(), RuntimeError("boum"))
    resultat["erreur · bouton"] = erreurs._component_error_panel(
        type("B", (), {"label": "Confirmer"})()
    )

    # Fiche membre : meme composition que celle rendue par +userinfo.
    resultat["fiche · membre"] = panels.Panneau(
        titre="SentriX — Informations membre",
        sous_titre="<@1> · `123456789`\nMembre du serveur depuis <t:1700000000:R>, rôle le plus élevé <@&3>",
        kind="info",
        vignette="https://cdn.discordapp.com/avatars/1/a.png",
        sections=[
            panels.Section("Identité", [
                panels.Ligne("Utilisateur", "**jayden**"),
                panels.Ligne("Identifiant", "`123456789`"),
                panels.Ligne("Création du compte", "<t:1600000000:D> · <t:1600000000:R>"),
            ]),
            panels.Section("Sur ce serveur", [
                panels.Ligne("Arrivée", "<t:1700000000:D> · <t:1700000000:R>"),
                panels.Ligne("Rôle principal", "<@&3>"),
            ]),
            panels.Section("Activité SentriX", [
                panels.Ligne("Niveau", "42"),
                panels.Ligne("Messages", "3 284"),
                panels.Ligne("Argent", "12 450"),
                panels.Ligne("Classement", "#7"),
            ], aligne=True),
            panels.Section("Pouvoirs", [panels.Ligne("Modération", "Bannir · Expulser")]),
        ],
        pied="SentriX • Informations · demandé par jayden",
    )
    return resultat


def main() -> int:
    filtre = sys.argv[1].casefold() if len(sys.argv) > 1 else ""
    for nom, panneau in apercus().items():
        if filtre and filtre not in nom.casefold():
            continue
        mesure = mesurer(panneau)
        print(f"\n\n═══ {nom} ═══")
        print(f"    bannière={mesure['banniere']}  sections={mesure['sections']}  "
              f"filets={mesure['filets']}  boutons={len(mesure['boutons'])}  "
              f"vignette={mesure['vignette']}")
        print(rendre(panneau))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
