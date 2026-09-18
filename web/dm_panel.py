"""Panneau DM du Dashboard : message privé à UN membre, au nom du serveur.

Ce module n'implémente aucun moteur d'envoi : il appelle
``cogs.direct_message.envoyer_prive`` — exactement le chemin de ``+dm``. La diffusion à
tout le serveur (ancienne commande de diffusion et sa route) a été retirée.

Sécurité : l'autorisation est vérifiée **côté serveur** à chaque appel. Cacher le bouton
dans le navigateur ne protège rien — la route reste appelable directement. Seuls le
propriétaire du serveur et le propriétaire de SentriX peuvent écrire, comme pour ``+dm``.
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.dm-panel")

LONGUEUR_MAX = 3500


class _PorteurId:  # petit porteur d'ID, suffisant pour Bot.is_owner
    def __init__(self, identifiant: int) -> None:
        self.id = identifiant


async def _peut_ecrire(request: web.Request, guild) -> bool:
    """Propriétaire du serveur ou propriétaire de SentriX, comme +dm."""
    session = request.get("sentrix_session") or {}
    try:
        user_id = int(session.get("user", {}).get("id"))
    except (TypeError, ValueError):
        return False
    if guild.owner_id == user_id:
        return True
    bot = request.app["bot"]
    try:
        return await bot.is_owner(_PorteurId(user_id))
    except Exception:
        logger.exception("Vérification propriétaire SentriX impossible (guild %s).", getattr(guild, "id", "?"))
        return False


def installer(dashboard) -> None:
    """Branche les routes DM sur le dashboard existant."""

    async def _autoriser(request: web.Request):
        """Retourne (guild, erreur). Vérifie session, serveur, puis droit d'écriture."""
        try:
            guild_id = int(request.match_info["guild_id"])
        except (KeyError, ValueError):
            return None, dashboard._json_error("Identifiant de serveur invalide.", 400)

        session, guild, erreur = await dashboard._manageable_guild(request, guild_id)
        if erreur:
            return None, erreur
        request["sentrix_session"] = session

        if request.method != "GET":
            erreur_csrf = dashboard._require_csrf(request, session)
            if erreur_csrf:
                return None, erreur_csrf

        if not await _peut_ecrire(request, guild):
            return None, dashboard._json_error(
                "Seul le propriétaire du serveur peut écrire à ses membres en privé.", 403
            )
        return guild, None

    async def apercu(request: web.Request):
        """Confirme le droit d'écrire (l'onglet ne s'affiche qu'après cette réponse)."""
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        return web.json_response({"guild": {"id": str(guild.id), "name": guild.name}, "longueur_max": LONGUEUR_MAX})

    async def envoyer_un(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        try:
            charge = await request.json()
        except Exception:
            return dashboard._json_error("Requête invalide.", 400)
        contenu = str(charge.get("message") or "").strip()
        if not contenu:
            return dashboard._json_error("Le message est vide.", 400)
        if len(contenu) > LONGUEUR_MAX:
            return dashboard._json_error(
                f"Message trop long : {len(contenu)} caractères (maximum {LONGUEUR_MAX}).", 400
            )
        try:
            membre_id = int(str(charge.get("user_id") or "").strip())
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de membre invalide.", 400)

        membre = guild.get_member(membre_id)
        if membre is None:
            return dashboard._json_error("Ce membre est introuvable sur ce serveur.", 404)
        if membre.bot:
            return dashboard._json_error("Les bots ne reçoivent pas de message privé.", 400)

        from cogs.direct_message import envoyer_prive

        resultat = await envoyer_prive(guild, membre, contenu)
        if resultat == "envoye":
            message = f"{membre.display_name} a bien reçu le message."
        elif resultat == "dm_ferme":
            message = f"{membre.display_name} n'accepte pas les messages privés."
        else:
            message = "Discord a refusé l'envoi."
        return web.json_response({"resultat": resultat, "message": message})

    dashboard.DM_PANEL_ROUTES = [
        ("GET", "/api/guilds/{guild_id}/dm/apercu", apercu),
        ("POST", "/api/guilds/{guild_id}/dm/user", envoyer_un),
    ]

    original_build = dashboard.build_app

    def build_app_avec_dm(bot):
        app = original_build(bot)
        for methode, chemin, handler in dashboard.DM_PANEL_ROUTES:
            app.router.add_route(methode, chemin, handler)
        return app

    if not getattr(dashboard.build_app, "_sentrix_dm_panel", False):
        build_app_avec_dm._sentrix_dm_panel = True
        build_app_avec_dm._sentrix_original = original_build
        dashboard.build_app = build_app_avec_dm
        logger.info("Panneau DM du Dashboard installé (message privé à un membre).")


__all__ = ["installer", "LONGUEUR_MAX"]
