"""Panneau DM du Dashboard : diffusion à tout le serveur et message à un membre.

Ce module n'implémente AUCUN moteur d'envoi : il appelle celui de
``sentrix_broadcast_dmall_visual`` — exactement celui de ``+dmall``. Écrire à des
centaines de personnes est une action irréversible ; en avoir deux implémentations
concurrentes garantirait qu'un jour l'une des deux oublie une protection.

Sécurité : l'autorisation est vérifiée **côté serveur** à chaque appel. Cacher le
bouton dans le navigateur ne protège rien — la route reste appelable directement.
Le contrôle est volontairement plus strict que « peut administrer le serveur » :
seuls le propriétaire du serveur et le propriétaire de SentriX peuvent diffuser,
comme pour ``+dmall``.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.dm-panel")

_JOBS_KEY = "sentrix_dm_jobs"
# Un job terminé reste consultable un moment pour que l'onglet affiche le bilan.
_RETENTION_SECONDS = 600
LONGUEUR_MAX = 3500


def _moteur():
    import sentrix_broadcast_dmall_visual as moteur

    return moteur


def _jobs(app: web.Application) -> dict:
    magasin = app.get(_JOBS_KEY)
    if magasin is None:
        magasin = {}
        app[_JOBS_KEY] = magasin
    return magasin


def _purger(magasin: dict) -> None:
    limite = time.time() - _RETENTION_SECONDS
    for cle in [k for k, v in magasin.items() if v.get("termine") and v.get("fin", 0) < limite]:
        magasin.pop(cle, None)


async def _peut_diffuser(request: web.Request, guild) -> bool:
    """Propriétaire du serveur ou propriétaire de SentriX, comme +dmall."""
    session = request.get("sentrix_session") or {}
    try:
        user_id = int(session.get("user", {}).get("id"))
    except (TypeError, ValueError):
        return False
    if guild.owner_id == user_id:
        return True
    bot = request.app["bot"]
    try:
        return await bot.is_owner(discord_user(user_id))
    except Exception:
        return False


class discord_user:  # petit porteur d'ID, suffisant pour Bot.is_owner
    def __init__(self, identifiant: int) -> None:
        self.id = identifiant


def installer(dashboard) -> None:
    """Branche les routes DM sur le dashboard existant."""

    async def _autoriser(request: web.Request):
        """Retourne (guild, erreur). Vérifie session, serveur, puis droit de diffusion."""
        try:
            guild_id = int(request.match_info["guild_id"])
        except (KeyError, ValueError):
            return None, dashboard._json_error("Identifiant de serveur invalide.", 400)

        session, guild, erreur = await dashboard._manageable_guild(request, guild_id)
        if erreur:
            return None, erreur
        request["sentrix_session"] = session

        # Le CSRF ne concerne que les requetes qui AGISSENT : l'imposer sur les
        # lectures casserait le suivi de progression sans rien proteger.
        if request.method != "GET":
            erreur_csrf = dashboard._require_csrf(request, session)
            if erreur_csrf:
                return None, erreur_csrf

        if not await _peut_diffuser(request, guild):
            # Volontairement le même message qu'un serveur inconnu : ne pas révéler
            # l'existence d'une capacité à quelqu'un qui n'y a pas droit.
            return None, dashboard._json_error(
                "Seul le propriétaire du serveur peut écrire à ses membres en privé.", 403
            )
        return guild, None

    async def _texte(request: web.Request):
        try:
            charge = await request.json()
        except Exception:
            return None, dashboard._json_error("Requête invalide.", 400)
        contenu = str(charge.get("message") or "").strip()
        if not contenu:
            return None, dashboard._json_error("Le message est vide.", 400)
        if len(contenu) > LONGUEUR_MAX:
            return None, dashboard._json_error(
                f"Message trop long : {len(contenu)} caractères (maximum {LONGUEUR_MAX}).", 400
            )
        return (contenu, charge), None

    # ---------------------------------------------------------------- aperçu
    async def apercu(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        moteur = _moteur()
        bot = request.app["bot"]
        membres, bots = moteur.destinataires_du_serveur(guild, getattr(bot.user, "id", None))
        return web.json_response(
            {
                "guild": {"id": str(guild.id), "name": guild.name},
                "destinataires": len(membres),
                "bots_ignores": bots,
                "duree_estimee_secondes": round(len(membres) * moteur.SEND_DELAY_SECONDS),
            }
        )

    # ------------------------------------------------------------- DM ALL
    async def diffuser_tout(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        donnees, erreur = await _texte(request)
        if erreur:
            return erreur
        contenu, charge = donnees

        if not bool(charge.get("confirme")):
            return dashboard._json_error("Confirmation obligatoire avant diffusion.", 400)

        magasin = _jobs(request.app)
        _purger(magasin)
        job = magasin.get(guild.id)
        if job is not None and not job.get("termine"):
            # Anti double-clic ET anti double-envoi : la même réponse sert aux deux.
            return web.json_response({"deja_en_cours": True, "etat": job}, status=409)

        moteur = _moteur()
        # La commande +dmall utilise le même verrou : les deux surfaces ne peuvent
        # pas lancer une diffusion simultanée sur le même serveur.
        cog = request.app["bot"].get_cog("Broadcast")
        if cog is not None:
            if guild.id in cog.active_guilds:
                return web.json_response({"deja_en_cours": True}, status=409)
            cog.active_guilds.add(guild.id)

        membres, bots = moteur.destinataires_du_serveur(guild, getattr(request.app["bot"].user, "id", None))
        etat = {
            "total": len(membres),
            "envoyes": 0,
            "dms_fermes": 0,
            "echecs": 0,
            "bots_ignores": bots,
            "traites": 0,
            "termine": False,
            "debut": time.time(),
            "fin": 0.0,
        }
        magasin[guild.id] = etat

        async def progression(bilan):
            etat.update(bilan.en_dict())

        async def executer():
            try:
                await moteur.diffuser(
                    guild,
                    membres,
                    contenu,
                    bots_ignores=bots,
                    fabrique_panneau=getattr(cog, "_panneau_prive", None) if cog else None,
                    progression=progression,
                )
            except Exception:
                logger.exception("Diffusion DM échouée (serveur %s).", guild.id)
            finally:
                etat["termine"] = True
                etat["fin"] = time.time()
                if cog is not None:
                    cog.active_guilds.discard(guild.id)

        asyncio.create_task(executer(), name=f"sentrix-dm-all-{guild.id}")
        return web.json_response({"demarre": True, "etat": etat})

    # ----------------------------------------------------------- progression
    async def etat_job(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        magasin = _jobs(request.app)
        _purger(magasin)
        etat = magasin.get(guild.id)
        return web.json_response({"actif": etat is not None and not etat["termine"], "etat": etat})

    # -------------------------------------------------------- DM utilisateur
    async def diffuser_un(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        donnees, erreur = await _texte(request)
        if erreur:
            return erreur
        contenu, charge = donnees

        try:
            membre_id = int(str(charge.get("user_id") or "").strip())
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de membre invalide.", 400)

        membre = guild.get_member(membre_id)
        if membre is None:
            return dashboard._json_error("Ce membre est introuvable sur ce serveur.", 404)
        if membre.bot:
            return dashboard._json_error("Les bots ne reçoivent pas de message privé.", 400)

        moteur = _moteur()
        cog = request.app["bot"].get_cog("Broadcast")
        bilan = await moteur.diffuser(
            guild,
            [membre],
            contenu,
            fabrique_panneau=getattr(cog, "_panneau_prive", None) if cog else None,
        )
        if bilan.envoyes:
            resultat, message = "envoye", f"{membre.display_name} a bien reçu le message."
        elif bilan.dms_fermes:
            resultat, message = "dm_ferme", f"{membre.display_name} n'accepte pas les messages privés."
        else:
            resultat, message = "echec", "Discord a refusé l'envoi."
        return web.json_response({"resultat": resultat, "message": message, "bilan": bilan.en_dict()})

    dashboard.DM_PANEL_ROUTES = [
        ("GET", "/api/guilds/{guild_id}/dm/apercu", apercu),
        ("POST", "/api/guilds/{guild_id}/dm/all", diffuser_tout),
        ("GET", "/api/guilds/{guild_id}/dm/job", etat_job),
        ("POST", "/api/guilds/{guild_id}/dm/user", diffuser_un),
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
        logger.info("Panneau DM du Dashboard installé (moteur +dmall partagé).")


__all__ = ["installer", "LONGUEUR_MAX"]
