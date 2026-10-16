"""Usage réel des commandes, agrégé — la donnée qui manque pour simplifier.

Le brief interdit de supprimer une commande sans données d'usage. ``command_logs``
les contient (une ligne par commande préfixe ou hybride réussie), mais en
production la base n'est lisible que par le bot. Ce module en tire un résumé
SANS donnée personnelle : des comptes par commande et par nombre de serveurs,
jamais un identifiant de membre.

Limites, à garder en tête en lisant le résumé :
* seules les commandes RÉUSSIES sont journalisées (``on_command_completion``) ;
* les commandes purement natives (menus contextuels) n'y passent pas ;
* « jamais utilisée » ne vaut que sur la période réellement couverte —
  ``depuis`` dit depuis quand la table a des lignes.
"""
from __future__ import annotations

import time
from typing import Any

JOURS = 30
TOP = 40
LIGNE_MAX = 1500  # une ligne de journal Railway reste lisible et entière


async def resume(db: Any, catalogue: list[str], *, jours: int = JOURS,
                 maintenant: int | None = None) -> dict[str, Any]:
    maintenant = int(maintenant or time.time())
    depuis_ts = maintenant - jours * 86400
    lignes = await db.fetchall(
        "SELECT command_name, COUNT(*) AS n, COUNT(DISTINCT guild_id) AS g "
        "FROM command_logs WHERE timestamp >= ? GROUP BY command_name",
        (depuis_ts,),
    )
    premiere = await db.fetchone("SELECT MIN(timestamp) AS t FROM command_logs")
    par_commande = {str(r["command_name"]): (int(r["n"]), int(r["g"])) for r in lignes or ()}
    serveurs = await db.fetchone(
        "SELECT COUNT(DISTINCT guild_id) AS g FROM command_logs WHERE timestamp >= ?", (depuis_ts,)
    )
    connues = sorted(set(catalogue))
    utilisees = [nom for nom in connues if nom in par_commande]
    # Une commande parente (groupe) est « utilisée » si une sous-commande l'est.
    jamais = [nom for nom in connues if nom not in par_commande
              and not any(autre.startswith(nom + " ") for autre in par_commande)]
    t0 = premiere["t"] if premiere else None
    return {
        "jours": jours,
        "depuis": int(t0) if t0 is not None else None,
        "total": sum(n for n, _g in par_commande.values()),
        "serveurs": int(serveurs["g"]) if serveurs and serveurs["g"] is not None else 0,
        "catalogue": len(connues),
        "utilisees": len(utilisees),
        "top": sorted(par_commande.items(), key=lambda kv: (-kv[1][0], kv[0]))[:TOP],
        "jamais": jamais,
        "hors_catalogue": sorted(set(par_commande) - set(connues)),
    }


def _decouper(prefixe: str, elements: list[str]) -> list[str]:
    lignes, courante = [], prefixe
    for element in elements:
        if len(courante) + len(element) + 2 > LIGNE_MAX and courante != prefixe:
            lignes.append(courante.rstrip(", "))
            courante = prefixe + "(suite) "
        courante += element + ", "
    lignes.append(courante.rstrip(", ") if elements else prefixe + "aucune")
    return lignes


def lignes_de_journal(r: dict[str, Any]) -> list[str]:
    from datetime import datetime, timezone

    depuis = (datetime.fromtimestamp(r["depuis"], timezone.utc).date().isoformat()
              if r["depuis"] else "aucune donnée")
    lignes = [
        f"USAGE COMMANDES {r['jours']} j : {r['total']} exécutions, {r['serveurs']} serveurs, "
        f"{r['utilisees']}/{r['catalogue']} commandes utilisées, {len(r['jamais'])} jamais ; "
        f"journal depuis {depuis}"
    ]
    lignes += _decouper("USAGE TOP : ", [f"{nom}={n} ({g} srv)" for nom, (n, g) in r["top"]])
    lignes += _decouper(f"USAGE JAMAIS ({len(r['jamais'])}) : ", r["jamais"])
    if r["hors_catalogue"]:
        lignes += _decouper("USAGE HORS CATALOGUE : ", r["hors_catalogue"])
    return lignes


__all__ = ["resume", "lignes_de_journal", "JOURS"]
