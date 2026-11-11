"""Les logs de ce qui s'est passé pendant que SentriX était éteint (11/11/2026).

« Fais un truc avec mémoire même quand il est off, pour tout. »

Un bot Discord n'apprend ce qui se passe que par les événements que Discord lui
pousse en direct. Éteint, il n'en reçoit aucun : un bannissement, une expulsion,
un salon supprimé pendant une coupure ne laissaient aucune trace dans les logs
SentriX. Le staff ne pouvait pas savoir qu'il lui manquait quelque chose.

Mais Discord, lui, garde tout ça : le JOURNAL D'AUDIT du serveur conserve 45
jours d'actions, avec leur auteur, leur cible et leur heure exacte. SentriX peut
donc, au démarrage, relire ce qu'il a manqué et le publier.

Encore faut-il savoir CE QU'IL A MANQUÉ. D'où un battement de cœur : tant qu'il
tourne, SentriX note l'heure en base toutes les minutes. Au démarrage, l'écart
entre ce dernier battement et maintenant est exactement sa durée d'absence. On
ne republie que les actions tombées dans cet intervalle — jamais celles déjà
journalisées en direct.

Ce qui ne peut PAS être rattrapé, et qu'on ne prétendra donc pas rattraper : les
messages supprimés ou modifiés, les réactions, les mouvements vocaux. Discord ne
les conserve nulle part. Un bot ne peut journaliser que ce qu'il a vu passer.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from utils import embeds, log_service

logger = logging.getLogger("bot.rattrapage-logs")

#: Clé du battement de cœur : l'heure du dernier instant où SentriX était vivant.
PRESENCE_CLE = "logs:derniere_presence"
#: Fréquence du battement. Plus il est court, plus l'absence est mesurée finement.
BATTEMENT_SECONDES = 60
#: Au-delà, l'absence est trop longue pour être rattrapée sans noyer les salons.
#: Discord ne garde de toute façon que 45 jours de journal d'audit.
FENETRE_MAX = 7 * 86400
#: Une absence plus courte que ça est un redémarrage normal (bascule HA ≈ 6 s) :
#: rien n'a eu le temps d'être manqué, et republier ferait des doublons.
ABSENCE_MINIMALE = 90
#: Plafond par serveur : un rattrapage ne doit jamais inonder un salon de logs.
MAX_PAR_SERVEUR = 25
#: Même précaution que le préchargement des invitations : la limite globale de
#: l'API Discord sert aussi à l'AutoMod, on ne la consomme pas d'un bloc.
PAUSE_ENTRE_SERVEURS = 0.5

#: action du journal d'audit -> (type de log SentriX, titre de la carte)
ACTIONS = {
    discord.AuditLogAction.ban: ("member_ban", "Membre banni"),
    discord.AuditLogAction.unban: ("member_unban", "Membre débanni"),
    discord.AuditLogAction.kick: ("member_kick", "Membre expulsé"),
    discord.AuditLogAction.channel_create: ("channel_create", "Salon créé"),
    discord.AuditLogAction.channel_delete: ("channel_delete", "Salon supprimé"),
    discord.AuditLogAction.role_create: ("role_create", "Rôle créé"),
    discord.AuditLogAction.role_delete: ("role_delete", "Rôle supprimé"),
}


def nom_de(cible, cible_id) -> str:
    """Le nom lisible d'une cible, ou son identifiant si l'objet n'existe plus."""
    nom = (
        getattr(cible, "display_name", None)
        or getattr(cible, "name", None)
        or (str(cible) if cible is not None else "")
    )
    if nom:
        return str(nom)
    return f"ID {cible_id}" if cible_id else "Inconnu"


def carte_du_rattrapage(entree, titre: str) -> discord.Embed:
    """La carte de log d'une action retrouvée, à son heure réelle, dite comme telle."""
    auteur = entree.user
    champs = [
        ("Cible", nom_de(entree.target, getattr(entree, "target_id", None)), True),
        ("Par", nom_de(auteur, getattr(auteur, "id", None)), True),
    ]
    if getattr(entree, "reason", None):
        champs.append(("Raison", str(entree.reason)[:1000], False))
    return embeds.canonical_log_embed(
        titre,
        fields=champs,
        # Dire que c'est un rattrapage n'est pas un détail : sans ça, le staff lit
        # une action d'il y a deux heures comme si elle venait d'arriver.
        description="-# Retrouvé dans le journal d'audit : SentriX était hors ligne.",
        event_time=entree.created_at,
    )


class RattrapageLogs(commands.Cog, name="RattrapageLogs"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._fait = False
        self._tache: asyncio.Task | None = None
        self.battement.start()

    def cog_unload(self):
        self.battement.cancel()
        if self._tache is not None:
            self._tache.cancel()

    @tasks.loop(seconds=BATTEMENT_SECONDES)
    async def battement(self):
        """« Je suis vivant, à cette heure-ci. » C'est ce qui mesurera l'absence."""
        if not log_service.is_primary_process():
            return
        try:
            await self.bot.db.set_setting(PRESENCE_CLE, str(int(time.time())))
        except Exception:  # noqa: BLE001 — un battement raté ne casse rien
            logger.debug("Battement de présence non enregistré", exc_info=True)

    @battement.before_loop
    async def avant_battement(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        # on_ready revient à chaque reconnexion : le rattrapage n'a lieu qu'une fois.
        if self._fait or (self._tache is not None and not self._tache.done()):
            return
        self._tache = asyncio.create_task(self._rattraper_partout())

    async def duree_de_l_absence(self) -> float:
        """Combien de temps SentriX a été absent, 0 s'il n'y a rien à rattraper."""
        try:
            dernier = int(await self.bot.db.get_setting(PRESENCE_CLE, "0") or 0)
        except Exception:  # noqa: BLE001
            return 0
        if not dernier:
            return 0  # Premier démarrage : aucune absence connue, donc rien à inventer.
        absence = time.time() - dernier
        if absence < ABSENCE_MINIMALE or absence > FENETRE_MAX:
            return 0
        return absence

    async def _rattraper_partout(self) -> int:
        absence = await self.duree_de_l_absence()
        if not absence:
            self._fait = True
            return 0
        depuis = datetime.fromtimestamp(time.time() - absence, tz=timezone.utc)
        logger.info("Logs : rattrapage des %.0f s d'absence", absence)
        total = 0
        for guild in list(self.bot.guilds):
            try:
                total += await self.rattraper(guild, depuis)
            except Exception:  # noqa: BLE001 — un serveur illisible n'arrête pas les autres
                logger.debug("Rattrapage impossible guild=%s", guild.id, exc_info=True)
            await asyncio.sleep(PAUSE_ENTRE_SERVEURS)
        self._fait = True
        if total:
            logger.info("Logs : %s action(s) retrouvée(s) pendant l'absence", total)
        return total

    async def rattraper(self, guild: discord.Guild, depuis: datetime) -> int:
        moi = getattr(guild, "me", None)
        if moi is None or not getattr(moi.guild_permissions, "view_audit_log", False):
            # Sans la permission, Discord refuse : inutile de dépenser l'appel.
            return 0
        retrouvees = []
        try:
            async for entree in guild.audit_logs(after=depuis, limit=MAX_PAR_SERVEUR, oldest_first=True):
                if entree.action not in ACTIONS:
                    continue
                auteur_id = getattr(entree.user, "id", None)
                if auteur_id and auteur_id == getattr(self.bot.user, "id", None):
                    # Une action de SentriX lui-même est déjà journalisée par la
                    # commande qui l'a faite : la republier ferait un doublon.
                    continue
                retrouvees.append(entree)
        except (discord.Forbidden, discord.HTTPException):
            return 0

        envoyees = 0
        for entree in retrouvees:
            type_log, titre = ACTIONS[entree.action]
            await log_service.send_log(
                self.bot, guild, type_log, carte_du_rattrapage(entree, titre),
                event_key=f"rattrapage:{type_log}:{entree.id}",
            )
            envoyees += 1
        return envoyees


async def setup(bot: commands.Bot):
    await bot.add_cog(RattrapageLogs(bot))
