#!/usr/bin/env python3
"""Quel français reste visible quand un serveur choisit English ?

Le mode anglais de SentriX traduit au TRANSPORT : les cogs construisent du
français, et la dernière couche le remplace avant l'envoi à Discord. On ne peut
donc pas mesurer la couverture en lisant le code — seul le payload rendu le dit.

Ce balayage boote le bot comme en production, bascule le serveur en anglais,
exécute chaque commande avec des arguments générés depuis sa vraie signature
(tools/command_sweep.py), puis relève le français qui SUBSISTE dans la réponse.

Deux relevés complémentaires, parce qu'aucun des deux ne suffit :

- par MOT, classé par fréquence : donne les priorités ;
- par LIGNE entière : donne la phrase à traduire, car un mot de liaison ne se
  traduit jamais isolément — ("encore", "still") rendait « n'est pas still
  disponible » (mesuré le 07/10/2026).

Ce qui est volontairement EXCLU du relevé : le contenu des blocs ``` et des
segments `code`, les mentions et les horodatages Discord, et les littéraux
protégés (nom du serveur, du bot, de l'auteur) — ceux-là ne doivent jamais être
traduits, les compter comme des manques fausserait la mesure.

    python3 tools/i18n_coverage_sweep.py                 # tout
    python3 tools/i18n_coverage_sweep.py --only solde niveau
    python3 tools/i18n_coverage_sweep.py --lignes         # phrases à traduire
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import sentrix_e2e_harness as harness  # noqa: E402
import command_sweep  # noqa: E402
from command_sweep import prefix_invocation, _skip_reason  # noqa: E402

#: Hors mesure : ce qui ne doit pas être traduit.
HORS_MESURE = re.compile(
    r"```.*?```|`[^`\n]*`|<@!?&?\d+>|<#\d+>|<t:\d+(?::[A-Za-z])?>|<a?:\w+:\d+>|https?://\S+",
    re.DOTALL,
)
#: Un mot français : soit il porte un accent, soit c'est un mot-outil ou une
#: étiquette courante qui n'a pas la même forme en anglais.
MOT_FRANCAIS = re.compile(
    r"\b([A-Za-zÀ-ÿ]*[àâäéèêëîïôöùûüç][A-Za-zÀ-ÿ]*"
    r"|(?:Aucun|Aucune|Serveur|Serveurs|Membre|Membres|Salon|Salons|Niveau|Niveaux"
    r"|Avertissement|Avertissements|Sanction|Sanctions|Raison|Auteur|Statut|Actif"
    r"|Inactif|Oui|Non|Jamais|Toujours|Utilisateur|Utilisateurs|Fichier|Fichiers"
    r"|et|ou|le|la|les|des|une|dans|pour|avec|sur|par|est|sont|pas|vous|votre)\b)"
)


def _francais(texte: str) -> list[str]:
    return [m.group(1) for m in MOT_FRANCAIS.finditer(HORS_MESURE.sub(" ", texte))
            if len(m.group(1)) >= 3]


async def sweep(*, only: list[str], lignes: bool, timeout: float) -> dict:
    from utils import access_matrix
    from cogs import language_runtime

    bot = await harness.boot()
    guild = await harness.setup_world(bot)
    command_sweep._SWEEP_BOT = bot
    await language_runtime.set_language(bot, harness.GID, language_runtime.LANG_EN)

    persona = dict(author_id=harness.ADMIN_ID, author_roles=(harness.ADMIN_ROLE_ID,))
    mots: collections.Counter[str] = collections.Counter()
    ou: dict[str, set[str]] = collections.defaultdict(set)
    phrases: dict[str, list[str]] = collections.defaultdict(list)
    rendues = 0

    def voulu(nom: str) -> bool:
        return not only or any(o.casefold() in nom.casefold() for o in only)

    vus: set[str] = set()
    for command in sorted(bot.walk_commands(), key=lambda c: c.qualified_name):
        nom = command.qualified_name
        if nom in vus or not voulu(nom) or command.hidden:
            continue
        vus.add(nom)
        try:
            invocation, manquants = prefix_invocation(command)
        except Exception:  # noqa: BLE001
            continue
        if _skip_reason(nom, access_matrix.access_tier(nom), manquants, False):
            continue
        depuis = len(harness.CALLS)
        try:
            await asyncio.wait_for(harness.run_prefix(bot, guild, invocation, **persona), timeout)
        except Exception:  # noqa: BLE001 — une commande qui échoue n'intéresse pas la mesure
            continue
        try:
            await harness.settle(idle=0.15, maximum=1.0)
        except Exception:  # noqa: BLE001
            pass
        texte = harness.visible_text(harness.CALLS[depuis:])
        if not texte.strip():
            continue
        rendues += 1
        restants = _francais(texte)
        for mot in restants:
            mots[mot] += 1
            ou[mot].add(nom)
        if lignes and restants:
            for ligne in (l.strip() for l in texte.splitlines()):
                if ligne and _francais(ligne):
                    phrases[nom].append(ligne[:200])
        print(f"[{len(restants):>3} fr] {invocation[:70]}", flush=True)

    return {
        "commandes_rendues": rendues,
        "mots": [(m, n, sorted(ou[m])[:6]) for m, n in mots.most_common()],
        "phrases": {k: v[:8] for k, v in phrases.items()},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--lignes", action="store_true", help="relève aussi les phrases entières")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--out", default=str(ROOT / "reports" / "i18n_coverage"))
    a = ap.parse_args(argv)
    rapport = asyncio.run(sweep(only=a.only, lignes=a.lignes, timeout=a.timeout))
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{rapport['commandes_rendues']} commandes ont rendu du texte")
    print(f"{len(rapport['mots'])} mots français restants\n")
    for mot, n, cmds in rapport["mots"][:40]:
        print(f"  {n:>3}x  {mot:<26} {', '.join(cmds[:4])}")
    print(f"\nRapport : {out.with_suffix('.json')}")
    import os
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
