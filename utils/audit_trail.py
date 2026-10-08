"""Trace unique pour les actions d'administration qui n'ouvrent pas de dossier.

**Le défaut, mesuré le 06/10/2026** (``tools/log_trace_sweep.py``, bot booté comme
en production) : 36 commandes staff changeaient réellement le serveur — rôles
donnés ou retirés, salon ralenti, monnaie créée, XP accordée, AutoMod reconfiguré,
avertissements effacés — sans laisser AUCUNE trace. Leur seule preuve était le
message de confirmation dans le salon, que son auteur peut supprimer. Après quoi
il ne reste rien, nulle part.

``Moderation.log_sanction`` ne convenait pas : il ouvre un dossier numéroté CONTRE
un membre, ce qui n'a pas de sens pour un verrouillage de salon ou un changement de
prix en boutique. D'où ce point de passage, volontairement plus simple.

**Deux règles tenues ici.**

1. L'action Discord a déjà eu lieu quand on journalise. Une panne de journal ne doit
   donc jamais transformer un succès en échec : tout est enveloppé, et l'échec part
   dans les logs du bot, pas à l'utilisateur. C'est la même discipline que
   ``log_sanction`` applique déjà aux sanctions.
2. Le type d'événement doit exister dans ``utils/log_categories.LOG_REGISTRY``,
   sinon la fiche retombe sur une catégorie générique et perd son icône. Les
   événements manquants y ont été ajoutés avec leur icône.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

import discord

logger = logging.getLogger("bot.audit-trail")

__all__ = ["journaliser"]


async def journaliser(
    bot: Any,
    ctx: Any,
    event_type: str,
    titre: str,
    champs: Mapping[str, str] | None = None,
) -> bool:
    """Envoie une fiche d'audit dans le salon de logs. Rend True si elle est partie.

    ``ctx`` peut être un Context préfixe comme une Interaction : seuls ``guild`` et
    ``author``/``user`` sont lus, ce qui couvre les deux transports sans que
    l'appelant ait à s'en soucier.
    """
    try:
        from utils import embeds, helpers

        guild = getattr(ctx, "guild", None)
        if guild is None:
            return False
        auteur = getattr(ctx, "author", None) or getattr(ctx, "user", None)

        fiche = embeds.info("", title=titre)
        # Les champs du SUJET d'abord, le modérateur ensuite, et nommé comme tel.
        # Le moteur de rendu des journaux (utils/wide_logs.py) prend pour sujet
        # le premier champ « auteur / membre / salon » : l'ancien « 👮 Auteur »
        # faisait du modérateur le sujet de chaque carte — « Salon ·
        # <#identifiant du modérateur> », « l'administrateur a reçu le rôle »
        # (constaté le 08/10/2026). « Modérateur » est une étiquette qu'il
        # reconnaît comme l'acteur. Le salon où la commande a été tapée n'est
        # plus ajouté d'office : il n'apprenait rien et doublait le salon visé.
        for nom, valeur in (champs or {}).items():
            texte = str(valeur) if valeur not in (None, "") else "—"
            fiche.add_field(name=nom, value=texte[:1024], inline=True)
        if auteur is not None:
            fiche.add_field(
                name="👮 Modérateur",
                value=f"{auteur.mention}\n`{auteur.id}`",
                inline=True,
            )

        await helpers.send_log(bot, guild, event_type, fiche)
        return True
    except Exception:
        # Volontairement silencieux pour l'utilisateur : l'action est déjà appliquée.
        logger.exception(
            "Fiche d'audit non envoyée guild=%s auteur=%s event=%s.",
            getattr(getattr(ctx, "guild", None), "id", None),
            getattr(getattr(ctx, "author", None) or getattr(ctx, "user", None), "id", None),
            event_type,
        )
        return False


# --------------------------------------------------------------------------
# Acteur réel d'une action faite PAR SentriX
# --------------------------------------------------------------------------
# Quand +giverole ou +nickname modifie un membre, c'est le BOT qui appelle
# Discord : le journal d'audit nomme donc SentriX, et la carte de l'événement
# disait « Modérateur · @SentriX ». La commande note le vrai modérateur juste
# avant l'appel ; cogs/logs.py le relit. Même principe que
# `_sentrix_local_message_deleters` pour les suppressions de messages.

_LOCAL_ACTORS_ATTR = "_sentrix_local_member_actors"
_LOCAL_ACTOR_TTL = 15.0


def noter_acteur(bot, guild_id: int, target_id: int, action: str, actor_id: int) -> None:
    """À appeler juste AVANT l'appel Discord qui modifie `target_id`."""
    import time

    store = getattr(bot, _LOCAL_ACTORS_ATTR, None)
    if not isinstance(store, dict):
        store = {}
        setattr(bot, _LOCAL_ACTORS_ATTR, store)
    maintenant = time.monotonic()
    if len(store) > 256:
        for cle in [c for c, (t0, _a) in store.items() if maintenant - t0 > _LOCAL_ACTOR_TTL]:
            store.pop(cle, None)
    store[(int(guild_id), int(target_id), str(action))] = (maintenant, int(actor_id))


def acteur_local(bot, guild_id: int, target_id: int, action: str) -> int | None:
    """Le modérateur noté pour cette action, s'il est récent. Consommé à la lecture."""
    import time

    store = getattr(bot, _LOCAL_ACTORS_ATTR, None)
    if not isinstance(store, dict):
        return None
    entree = store.pop((int(guild_id), int(target_id), str(action)), None)
    if entree is None or time.monotonic() - entree[0] > _LOCAL_ACTOR_TTL:
        return None
    return entree[1]
