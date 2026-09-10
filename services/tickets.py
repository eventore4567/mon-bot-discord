"""TicketService — Core V2, Phase 4 (docs/core-v2-plan.md).

count_genuinely_open_tickets() vivait dans cogs/tickets.py mais est déjà
partagée par deux points d'entrée bien distincts (Tickets.start_ticket_flow
et cogs/ticket_claim_security.py::secure_create_ticket) — déjà
"service-shaped" (aucune écriture, aucun état de cog), mais jamais testée
directement en dehors du cycle complet d'ouverture de ticket.

Extraction volontairement limitée à cette seule fonction pour ce lot :
get_button_settings()/save_button_settings()/default_button_settings()
restent dans cogs/tickets.py car ticket_controls_minimal.py réassigne
directement cogs.tickets.DEFAULT_ENABLED_BUTTONS (pas une mutation en place,
une réassignation d'attribut de module) — les déplacer ferait lire
default_button_settings() une valeur figée au lieu de la valeur réassignée,
un changement de comportement, pas une extraction neutre. La création
complète d'un ticket (salon, permissions, rôle staff) reste elle aussi dans
le cog : elle construit des objets discord.py (Role, CategoryChannel,
PermissionOverwrite) du début à la fin, ce qui n'a pas sa place dans une
fonction de service au sens de ce plan (aucun type discord.py dans la
signature).

cogs/tickets.py importe cette fonction et la ré-expose sous le même nom, afin
que cogs/ticket_claim_security.py (``from . import tickets; tickets.count_
genuinely_open_tickets(...)``) et cogs/sentrix_v22.py continuent de
fonctionner sans aucun changement — le comportement observable est
strictement identique à avant cette extraction.
"""
from __future__ import annotations

import discord


async def count_genuinely_open_tickets(bot, guild: discord.Guild, user_id: int, type_id: int) -> int:
    """Compte les tickets réellement ouverts : ``status='ouvert'`` ET salon existant.

    Avant ce correctif, la vérification "l'utilisateur a-t-il déjà un ticket ouvert"
    ne regardait que la colonne ``status`` en base, jamais si le salon Discord existait
    encore. Une suppression manuelle du salon (staff, anti-nuke, purge de catégorie...)
    laissait donc la ligne à ``status='ouvert'`` pour toujours, bloquant indéfiniment
    toute nouvelle ouverture du même type pour cet utilisateur — c'est le bug rapporté
    ("impossible de rouvrir un ticket après fermeture/suppression"). Une ligne dont le
    salon n'existe plus est donc auto-réparée ici en ``status='supprime'`` et n'est
    jamais comptée. Utilisé par ``Tickets.start_ticket_flow`` et
    ``ticket_claim_security.secure_create_ticket`` : les deux points où ce blocage se
    manifestait.
    """
    rows = await bot.db.fetchall(
        "SELECT id, channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND type_id = ? AND status = 'ouvert'",
        (guild.id, user_id, type_id),
    )
    count = 0
    for row in rows:
        channel = guild.get_channel(int(row["channel_id"]))
        if channel is None:
            await bot.db.execute("UPDATE tickets SET status = 'supprime' WHERE id = ?", (row["id"],))
            continue
        count += 1
    return count
