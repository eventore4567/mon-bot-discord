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

    Ne lève jamais — et c'est une garantie, pas une intention. Elle est
    appelée APRÈS que l'action métier a réussi : le ticket est créé, fermé,
    rouvert, le membre ajouté. Une exception ici afficherait une erreur pour
    quelque chose qui a parfaitement fonctionné. C'est le défaut que Jayden a
    signalé nommément, et il s'est produit pendant ce lot même : un objet de
    contexte sans ``.author`` faisait remonter un AttributeError depuis un
    appel, sur une réouverture déjà écrite en base.

    Les deux écritures (audit, envoi) se protègent séparément plus bas ; cette
    enveloppe couvre tout le reste — construction des champs, lecture des
    attributs de l'acteur et de la cible, résolution du salon.
    """
    try:
        return await _journaliser(
            bot, guild, evenement,
            ticket_id=ticket_id, channel=channel, acteur=acteur, cible=cible,
            raison=raison, extra=extra, details=details,
            avec_bouton=avec_bouton, file=file,
        )
    except Exception:
        logger.exception(
            "Journalisation ticket impossible guild=%s événement=%s ; "
            "l'action métier reste acquise.",
            getattr(guild, "id", None), evenement,
        )
        # Une référence dégradée plutôt que rien : le staff peut toujours citer
        # le numéro de ticket, et une chaîne vide dans un message le
        # déconcerterait.
        return reference_incident(ticket_id, None)


async def _journaliser(
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
    """Corps de ``journaliser_evenement`` — voir sa docstring. Séparé pour que
    l'enveloppe qui garantit « ne lève jamais » n'ait rien d'autre à faire."""
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

    # Le champ « Membre concerné » n'est posé que si la phrase narrative ne
    # nomme PAS déjà le membre. Sinon le journal affichait la même personne
    # trois fois :
    #
    #     « X a fermé le ticket de Y. »
    #     **Membre concerné :** Y
    #     `123456789012345678`
    #
    # La règle se déduit du gabarit de phrase (wide_logs), donc ajouter un
    # événement ne peut pas réintroduire le doublon.
    # Les champs cible/acteur RESTENT : wide_logs.narrative_body compose sa
    # phrase en les lisant, et les retirer faisait dire au journal « Un membre
    # du staff a fermé le ticket » au lieu de nommer la personne — mesuré, et
    # c'est précisément ce qu'un audit ne doit jamais perdre.
    #
    # Le doublon qu'on voulait supprimer ne venait pas d'ici mais de
    # compact_fields, qui réaffiche tout champ contenant un saut de ligne — or
    # embeds._who() rend « <@id>\n`id` », donc deux lignes. Il est corrigé
    # là-bas, à sa source.
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
    # L'en-tête du panneau lisait son identité DANS le champ qu'on vient de
    # retirer (wide_logs.derive_identity balaie les libellés de cible). On la
    # passe donc explicitement, sans quoi retirer le doublon ferait aussi
    # disparaître le nom et l'avatar en tête de journal.
    identite = cible if cible is not None else acteur
    await safe_ticket_log(
        bot, guild, evenement, embed, file=file, view=vue, event_key=cle,
        identity_name=(getattr(identite, "display_name", None)
                       or getattr(identite, "name", None)),
        identity_id=getattr(identite, "id", None),
        identity_icon=(str(getattr(identite, "display_avatar", "") or "") or None),
    )
    return reference


# =============================================================================
# FERMER N'EST PAS SUPPRIMER
# =============================================================================
#
# Jusqu'ici, fermer un ticket programmait sa suppression automatique, et il
# n'existait aucun moyen de l'empêcher : ``ticket_delete_delay`` valait 30
# secondes par défaut, et les six endroits qui le lisaient écrivaient tous
#
#     delay = (conf["ticket_delete_delay"] if conf else 30) or 30
#
# où ``0 or 30`` rend 30. Mettre zéro pour dire « ne supprime pas » était donc
# impossible : la valeur était silencieusement ramenée à 30 secondes.
#
# Zéro veut maintenant dire ce qu'on attend : le salon reste, et un membre du
# staff décide. C'est aussi ce qui permet de relire un ticket le lendemain — 30
# secondes après la fermeture, personne n'a eu le temps de revenir dessus.

#: Valeur de ``ticket_delete_delay`` qui signifie « suppression manuelle ».
SUPPRESSION_MANUELLE = 0

#: Utilisé quand la configuration est absente. Inchangé, pour ne pas modifier le
#: comportement des serveurs qui n'ont jamais touché ce réglage.
DELAI_SUPPRESSION_DEFAUT = 30


def delai_de_suppression(config) -> int | None:
    """Secondes avant suppression automatique, ou None si c'est au staff.

    Le ``or`` des appelants historiques traitait 0 comme « non renseigné ».
    Ici on distingue vraiment les trois cas : absent (défaut), zéro (manuel),
    valeur (délai).
    """
    if config is None:
        return DELAI_SUPPRESSION_DEFAUT
    try:
        brut = config["ticket_delete_delay"]
    except (KeyError, TypeError, IndexError):
        return DELAI_SUPPRESSION_DEFAUT
    if brut is None:
        return DELAI_SUPPRESSION_DEFAUT
    try:
        valeur = int(brut)
    except (TypeError, ValueError):
        return DELAI_SUPPRESSION_DEFAUT
    if valeur <= SUPPRESSION_MANUELLE:
        return None
    return valeur


def duree_du_ticket(ticket, *, fin: int | None = None) -> str | None:
    """« 2 h 14 min » entre l'ouverture et la fermeture, ou None si incalculable.

    Demandé par Jayden : à la lecture d'un journal, savoir combien de temps un
    ticket est resté ouvert dit bien plus que deux horodatages qu'il faudrait
    soustraire de tête. C'est aussi le seul chiffre qui permet de voir qu'un
    ticket a traîné.
    """
    import time

    from utils import helpers

    try:
        debut = int(ticket["created_at"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if debut <= 0:
        return None
    arrivee = int(fin) if fin else int(time.time())
    ecoule = arrivee - debut
    if ecoule < 0:
        return None
    if ecoule < 60:
        # format_duration arrondit à la minute et rendrait « 0 min » pour un
        # ticket réglé en trente secondes — ce qui se lit comme une erreur.
        return f"{ecoule} s"
    return helpers.format_duration(ecoule)


class BoutonSupprimerTicket(discord.ui.DynamicItem[discord.ui.Button],
                            template=r"sx_ticket_del:(?P<ticket_id>[0-9]+)"):
    """« Supprimer le salon » — l'action explicite que Jayden a demandée.

    DynamicItem et non un bouton de vue ordinaire : son ``custom_id`` porte
    l'identifiant du ticket, donc Discord le fait fonctionner même après un
    redémarrage du bot. Un bouton de vue classique cesserait de répondre au
    premier redéploiement, et le salon resterait là sans que personne ne puisse
    le supprimer autrement qu'à la main — exactement le genre de bouton mort
    qu'on vient de retirer partout ailleurs.
    """

    def __init__(self, ticket_id: int):
        super().__init__(
            discord.ui.Button(
                label="Supprimer le salon",
                emoji="🗑️",
                style=discord.ButtonStyle.danger,
                custom_id=f"sx_ticket_del:{int(ticket_id)}",
            )
        )
        self.ticket_id = int(ticket_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["ticket_id"]))

    async def callback(self, interaction: discord.Interaction):
        from utils import embeds as _embeds
        from utils import sentrix_panels as _panels

        salon = interaction.channel
        guild = interaction.guild
        if guild is None or salon is None:
            return

        # Supprimer un salon est irréversible : réservé à qui peut gérer les
        # salons. Le créateur du ticket peut le FERMER, pas le supprimer — c'est
        # toute la séparation demandée.
        perms = getattr(interaction.user, "guild_permissions", None)
        autorise = bool(
            (perms and (perms.manage_channels or perms.administrator))
            or interaction.user.id == guild.owner_id
        )
        if not autorise:
            return await _panels.envoyer(
                interaction.response,
                _panels.depuis_embed(_embeds.error(
                    "Seul un membre pouvant **gérer les salons** peut supprimer ce ticket."
                )),
                ephemere=True,
            )

        ligne = await interaction.client.db.fetchone(
            "SELECT status FROM tickets WHERE id = ?", (self.ticket_id,)
        )
        if ligne is not None and str(ligne["status"]) == "ouvert":
            return await _panels.envoyer(
                interaction.response,
                _panels.depuis_embed(_embeds.warning(
                    "Ce ticket a été rouvert. Fermez-le d'abord."
                )),
                ephemere=True,
            )

        await interaction.client.db.execute(
            "UPDATE tickets SET status = 'supprime' WHERE id = ? AND status <> 'supprime'",
            (self.ticket_id,),
        )
        await journaliser_evenement(
            interaction.client, guild, "ticket_delete",
            ticket_id=self.ticket_id, channel=salon,
            acteur=interaction.user,
            raison="Suppression demandée par le staff.",
            avec_bouton=False,
        )
        try:
            await interaction.response.send_message(
                "🗑️ Suppression du salon…", ephemeral=True
            )
        except discord.HTTPException:
            pass
        try:
            await salon.delete(reason=f"Ticket supprimé par {interaction.user}.")
        except discord.HTTPException:
            logger.warning(
                "Suppression manuelle du ticket %s refusée par Discord (salon=%s).",
                self.ticket_id, getattr(salon, "id", None),
            )


def vue_supprimer_ticket(ticket_id: int) -> discord.ui.View:
    """La vue qui porte le bouton, à joindre au message de fermeture."""
    vue = discord.ui.View(timeout=None)
    vue.add_item(BoutonSupprimerTicket(int(ticket_id)))
    return vue
