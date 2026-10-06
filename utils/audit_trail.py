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
        if auteur is not None:
            fiche.add_field(
                name="👮 Auteur",
                value=f"{auteur.mention}\n`{auteur.id}`",
                inline=True,
            )
        salon = getattr(ctx, "channel", None)
        if salon is not None and getattr(salon, "id", None):
            fiche.add_field(name="📍 Salon", value=getattr(salon, "mention", "—"), inline=True)
        for nom, valeur in (champs or {}).items():
            texte = str(valeur) if valeur not in (None, "") else "—"
            fiche.add_field(name=nom, value=texte[:1024], inline=True)

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
