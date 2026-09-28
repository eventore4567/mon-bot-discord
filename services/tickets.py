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

safe_ticket_log() vient de cogs/ticket_claim_security.py::_safe_ticket_log()
(déplacée à l'identique, seul son premier paramètre passe de ``cog`` à
``bot`` puisque c'est la seule chose qu'elle lisait dessus). C'est la garantie
« une panne de log ne transforme jamais une action de ticket déjà réussie en
erreur utilisateur » — partagée par ``Tickets.close_ticket`` (remplacée par
``secure_close_ticket``, confirmée seule implémentation active :
``tickets.Tickets.close_ticket = secure_close_ticket`` est une réassignation
de classe, sans aucun autre appelant qui la reprendrait ensuite) et par
``Tickets.log_action`` (elle-même re-remplacée plus tard par
cogs/runtime_finish_v90.py::safe_ticket_log, une garantie équivalente mais
indépendante — hors périmètre de ce lot).

claim_decision()/unclaim_decision() extraient la logique de décision pure de
cogs/ticket_claim_security.py::secure_claim()/secure_unclaim() (les seules
implémentations de +claim/+unclaim, `Tickets.btn_claim`/`btn_unclaim` étant
réassignées vers elles à l'installation) : qui peut prendre en charge ou
abandonner un ticket, séparément des effets Discord (permissions de salon,
écriture en base, message de réponse) qui restent dans le cog. Ce sont déjà
des fonctions pures — aucun type discord.py, seulement des identifiants et
des booléens — jamais testées directement avant ce lot.
"""
from __future__ import annotations

import io
import logging

import discord

from utils import log_service

logger = logging.getLogger("bot.tickets")


async def fetch_transcript_text(channel: discord.TextChannel) -> str:
    """Build the plain-text transcript used by close/manual transcript flows."""
    lines: list[str] = []
    async for msg in channel.history(limit=2000, oldest_first=True):
        lines.append(
            f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author} ({msg.author.id}): {msg.content}"
        )
        for attachment in msg.attachments:
            lines.append(f"  [Pièce jointe] {attachment.url}")
    return "\n".join(lines)


def transcript_file(channel: discord.TextChannel, text: str) -> discord.File:
    """Create a fresh Discord file object from already-fetched transcript text."""
    return discord.File(
        io.BytesIO(text.encode("utf-8")),
        filename=f"transcript-{channel.name}.txt",
    )


async def generate_transcript(channel: discord.TextChannel) -> discord.File:
    """Fetch channel history once and return a sendable transcript file."""
    text = await fetch_transcript_text(channel)
    return transcript_file(channel, text)


async def safe_ticket_log(bot, guild: discord.Guild, log_type: str, embed: discord.Embed, **kwargs) -> bool:
    """Journalise sans jamais casser l'action métier qui vient de réussir."""
    try:
        sent = await log_service.send_log(bot, guild, log_type, embed, **kwargs)
        if not sent:
            logger.warning(
                "Log ticket non envoyé guild=%s type=%s : route désactivée/invalide ou transport indisponible.",
                guild.id,
                log_type,
            )
        return bool(sent)
    except Exception:
        logger.exception("Échec du log ticket guild=%s type=%s ; action métier conservée.", guild.id, log_type)
        return False


def claim_decision(*, current_claimant_id: int | None, member_id: int, is_admin: bool, is_owner: bool) -> str:
    """Décide si `member_id` peut prendre en charge un ticket déjà à l'état
    `current_claimant_id` (None si pas encore pris en charge). Retourne
    "self_already" (déjà pris en charge par ce même membre), "taken" (pris
    en charge par quelqu'un d'autre, et ce membre n'est ni admin ni
    propriétaire du serveur — les deux seuls rôles pouvant reprendre la
    charge d'un autre), ou "ok"."""
    if current_claimant_id is not None:
        if int(current_claimant_id) == member_id:
            return "self_already"
        if not is_admin and not is_owner:
            return "taken"
    return "ok"


def unclaim_decision(*, current_claimant_id: int | None, member_id: int, is_admin: bool, is_owner: bool) -> str:
    """Décide si `member_id` peut abandonner la prise en charge d'un ticket à
    l'état `current_claimant_id`. Retourne "not_claimed" (personne ne l'a
    pris en charge), "forbidden" (pris en charge par quelqu'un d'autre, et ce
    membre n'est ni le titulaire, ni admin, ni propriétaire du serveur), ou
    "ok"."""
    if current_claimant_id is None:
        return "not_claimed"
    if int(current_claimant_id) != member_id and not is_admin and not is_owner:
        return "forbidden"
    return "ok"


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


# =============================================================================
# JOURNALISATION DES ÉVÉNEMENTS DE TICKET
# =============================================================================
#
# Avant ce lot, la journalisation des tickets tenait à une seule ligne, dans
# cogs/ticket_claim_security.secure_log_action :
#
#     log_type = "ticket_close" if "ferm" in title else "ticket_open"
#
# Tout ce qui n'était pas une fermeture arrivait donc dans le journal étiqueté
# « ouverture de ticket » — et, comme la bannière et la catégorie découlent du
# type, avec la bannière d'ouverture. Mesuré sur le code : seules trois actions
# journalisaient quoi que ce soit (ouverture, fermeture, fermeture
# automatique). Prise en charge, abandon, ajout/retrait de membre, renommage,
# transfert, note, rappel, réouverture, suppression et notation ne laissaient
# aucune trace.
#
# La fermeture, elle, est un cas à part et il faut être exact : le
# ``Tickets.close_ticket`` qu'on lit dans cogs/tickets.py refait le routage à la
# main et retombe sur ``helpers.send_log(bot, guild, "moderation", embed)`` — le
# journal Modération pour un événement de ticket. Mais ce code est MORT :
# ``cogs/ticket_claim_security`` réassigne ``Tickets.close_ticket`` au
# démarrage, et sa version passe bien par ``"ticket_close"``. Ce qui lui
# manquait n'était donc pas le routage mais la traçabilité — aucune ligne
# d'audit, aucune référence citable, aucun bouton vers le salon.
#
# Le piège vaut d'être retenu : quatre méthodes de Tickets sont réassignées au
# boot (log_action, handle_control_button, create_ticket, close_ticket,
# btn_claim, btn_unclaim). Lire le corps de l'une d'elles dans cogs/tickets.py
# ne dit RIEN de ce qui tourne en production.

#: Un titre et un libellé d'acteur par événement. Le type d'événement — et non
#: le texte du titre — décide seul de la catégorie et de la bannière
#: (utils/log_categories.LOG_REGISTRY).
EVENEMENTS_TICKET: dict[str, tuple[str, str]] = {
    "ticket_open": ("📬 Ticket ouvert", "Ouvert par"),
    "ticket_close": ("🔒 Ticket fermé", "Fermé par"),
    "ticket_autoclose": ("⏱️ Ticket fermé automatiquement", "Déclencheur"),
    "ticket_claim": ("🙋 Ticket pris en charge", "Pris en charge par"),
    "ticket_unclaim": ("↩️ Prise en charge abandonnée", "Abandonnée par"),
    "ticket_member_add": ("➕ Membre ajouté au ticket", "Ajouté par"),
    "ticket_member_remove": ("➖ Membre retiré du ticket", "Retiré par"),
    "ticket_rename": ("✏️ Ticket renommé", "Renommé par"),
    "ticket_transfer": ("🔀 Ticket transféré", "Transféré par"),
    "ticket_reopen": ("🔓 Ticket rouvert", "Rouvert par"),
    "ticket_delete": ("🗑️ Ticket supprimé", "Supprimé par"),
    "ticket_rating": ("⭐ Ticket noté", "Noté par"),
    "ticket_note": ("📝 Note interne ajoutée", "Auteur"),
    "ticket_bump": ("🔔 Rappel envoyé au membre", "Envoyé par"),
}


def reference_incident(ticket_id: object, ligne_id: object) -> str:
    """``TK-0042-317`` — ticket 42, 317ᵉ événement enregistré sur ce serveur.

    Les deux nombres sont nécessaires : la ligne seule est unique mais ne dit
    pas de quel ticket il s'agit, le ticket seul ne distingue pas ses propres
    événements. Un ticket inconnu donne ``TK-????-317`` plutôt que rien : la
    référence reste retrouvable en base, c'est son seul rôle.
    """
    try:
        ticket = f"{int(ticket_id):04d}"
    except (TypeError, ValueError):
        ticket = "????"
    try:
        ligne = str(int(ligne_id))
    except (TypeError, ValueError):
        return f"TK-{ticket}"
    return f"TK-{ticket}-{ligne}"


async def enregistrer_evenement(
    bot,
    guild_id: int,
    evenement: str,
    *,
    ticket_id: int | None = None,
    channel_id: int | None = None,
    actor_id: int | None = None,
    target_id: int | None = None,
    details: str | None = None,
) -> int | None:
    """Écrit la ligne d'audit et retourne son ``id``, source de la référence.

    Ne lève jamais : un journal d'audit indisponible ne doit pas annuler
    l'action métier qui vient de réussir. Retourne None si l'écriture échoue,
    et l'appelant produit alors une référence dégradée plutôt qu'aucune.
    """
    import time

    try:
        curseur = await bot.db.execute(
            "INSERT INTO ticket_events "
            "(guild_id, ticket_id, channel_id, event, actor_id, target_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(guild_id),
                int(ticket_id) if ticket_id else None,
                int(channel_id) if channel_id else None,
                str(evenement),
                int(actor_id) if actor_id else None,
                int(target_id) if target_id else None,
                (str(details)[:500] if details else None),
                int(time.time()),
            ),
        )
        return int(getattr(curseur, "lastrowid", 0)) or None
    except Exception:
        logger.exception(
            "Audit ticket non écrit guild=%s événement=%s ; action métier conservée.",
            guild_id,
            evenement,
        )
        return None


def vue_voir_le_ticket(guild_id: int | None, channel_id: int | None) -> discord.ui.View | None:
    """Bouton lien vers le salon du ticket, ou None s'il n'y a rien à ouvrir.

    Un bouton lien ne porte aucun ``custom_id`` et n'a pas besoin d'être
    réenregistré au démarrage — contrairement à un bouton d'action, il survit
    donc indéfiniment au redémarrage du bot.

    Retourne None sans salon : un bouton « Voir le ticket » qui mène à un salon
    supprimé est pire que pas de bouton. C'est le cas normal de
    ``ticket_delete``, où le salon vient justement de disparaître.
    """
    if not guild_id or not channel_id:
        return None
    vue = discord.ui.View(timeout=None)
    vue.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.link,
            label="Voir le ticket",
            emoji="🎫",
            url=f"https://discord.com/channels/{int(guild_id)}/{int(channel_id)}",
        )
    )
    return vue


async def journaliser_evenement(
    bot,
    guild: discord.Guild,
    evenement: str,
    *,
    ticket_id: int | None = None,
    channel=None,
    acteur=None,
    cible=None,
    raison: str | None = None,
    extra: dict | None = None,
    details: str | None = None,
    avec_bouton: bool = True,
    file: discord.File | None = None,
) -> str:
    """Enregistre l'événement, l'envoie au journal Tickets, rend la référence.

    Un seul chemin pour les quatorze événements : le type décide de la
    catégorie, de l'emoji et de la bannière, et rien ne se déduit du texte du
    titre.

    Ne lève jamais. La valeur de retour est la référence d'incident, à afficher
    dans la réponse au staff pour qu'un membre puisse la citer.
    """
    from utils import embeds as _embeds

    titre, libelle_acteur = EVENEMENTS_TICKET.get(
        evenement, (f"🎫 {evenement}", "Acteur")
    )
    guild_id = getattr(guild, "id", None)
    channel_id = getattr(channel, "id", None)

    ligne_id = await enregistrer_evenement(
        bot,
        guild_id,
        evenement,
        ticket_id=ticket_id,
        channel_id=channel_id,
        actor_id=getattr(acteur, "id", None),
        target_id=getattr(cible, "id", None),
        details=details or raison,
    )
    reference = reference_incident(ticket_id, ligne_id)

    champs: dict = {}
    if ticket_id:
        champs["🎟️ Ticket"] = f"#{int(ticket_id)}"
    if channel is not None:
        # Le nom EN PLUS de la mention : après suppression du salon, une mention
        # s'affiche « #deleted-channel » et l'information est perdue.
        nom = getattr(channel, "name", None)
        mention = getattr(channel, "mention", None)
        champs["📌 Salon"] = f"{mention} (`{nom}`)" if mention and nom else (mention or f"`{nom}`")
    if extra:
        champs.update(extra)
    champs["🔖 Référence"] = f"`{reference}`"

    embed = _embeds.log_entry(
        titre,
        cible=cible,
        cible_label="Membre concerné",
        acteur=acteur,
        acteur_label=libelle_acteur,
        raison=raison,
        extra=champs,
    )
    vue = vue_voir_le_ticket(guild_id, channel_id) if avec_bouton else None
    # event_key a un format imposé — « guild:event:cible:acteur:audit:message:
    # discriminant » — et log_service._event_from_key relit parts[1] comme type
    # d'événement, en PRIORITÉ sur le log_type passé juste à côté. Une chaîne
    # libre (la référence brute, par exemple) n'a pas de parts[1] : elle passe,
    # mais seulement parce que le repli se déclenche. On le construit donc
    # correctement, ce qui rend en plus la déduplication opérante contre un
    # double envoi du même événement. La référence sert de discriminant : elle
    # est unique par événement, donc jamais deux événements distincts ne se
    # dédupliquent l'un l'autre.
    cle = log_service.make_event_key(
        guild_id or 0,
        evenement,
        target_id=getattr(cible, "id", None),
        executor_id=getattr(acteur, "id", None),
        discriminator=reference,
    )
    await safe_ticket_log(
        bot, guild, evenement, embed, file=file, view=vue, event_key=cle
    )
    return reference
