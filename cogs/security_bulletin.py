"""Publie le bulletin de sécurité dans les journaux, tout seul.

La demande était explicite : pas une commande de plus, « que ça se configure
lui-même, genre pour les logs ». Ce module ne déclare donc **aucune commande**
et **aucun écouteur d'événement** — une seule boucle périodique, pour ne pas
peser sur le budget d'écouteurs.

Il ne republie que lorsque la situation a changé. Un bulletin identique renvoyé
à chaque redémarrage se ferait ignorer en trois jours, et c'est précisément le
jour où il change qu'il faut le lire. L'empreinte (code + gravité + mesure de
chaque constat) est gardée dans `bot_settings`, qui existe déjà : aucune
migration, aucune table nouvelle.

Le contenu vient de `utils/security_advisory` : rien n'est estimé, chaque ligne
porte un chiffre mesuré sur le serveur.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter

import discord
from discord.ext import commands, tasks

from utils import embeds, log_service, security_advisory

logger = logging.getLogger("bot.security-bulletin")

#: Un serveur ne change pas de surface d'exposition toutes les heures, et
#: chaque passage lit les webhooks de chaque serveur. Six heures suffisent à
#: voir arriver un nouvel administrateur le jour même.
INTERVALLE_HEURES = 6

#: Laisse le temps au cache des membres de se remplir. Analyser les rôles avant
#: que `role.members` soit peuplé ferait annoncer « aucun administrateur » sur
#: un serveur qui en compte quatorze — un faux négatif rassurant, le pire.
DELAI_AVANT_PREMIER_PASSAGE_SECONDES = 300

_CLE = "security_advisory"

#: Ce qu'un passage a fait sur un serveur. Nommé plutôt que booléen : « rien
#: publié » recouvrait quatre situations très différentes, dont « le serveur n'a
#: pas de salon de journaux » et « le module n'a jamais tourné » — et les
#: journaux de production ne permettaient pas de les distinguer.
#: Un bulletin de sécurité vaut mieux dans le journal de modération que nulle
#: part. Mesuré le 23/10/2026 au premier passage réel : 22 serveurs sur 36
#: avaient des constats à annoncer et AUCUN salon pour les recevoir, faute de
#: catégorie « Serveur » configurée. Ordre de préférence, du plus pertinent au
#: moins ; le premier journal réellement configuré gagne.
CATEGORIES_DE_REPLI = ("server", "moderation", "automod", "members")

ISSUE_PUBLIE = "publié"
ISSUE_INCHANGE = "inchangé"
ISSUE_PREMIER_PASSAGE_SAIN = "sain"
ISSUE_SANS_SALON = "sans journal"
ISSUE_HORS_CACHE = "hors cache"
ISSUE_ERREUR = "erreur"


def construire_le_bulletin(guild, constats) -> discord.Embed:
    """La carte envoyée dans les journaux.

    Le titre porte la pire gravité : c'est ce qu'on lit en diagonale dans une
    liste de journaux.
    """
    gravite = security_advisory.gravite_dominante(constats)
    titre = (
        "Bulletin de sécurité · rien à signaler"
        if not constats
        else f"Bulletin de sécurité · {security_advisory.LIBELLES_GRAVITE[gravite].lower()}"
    )
    champs: list[tuple[str, str, bool]] = [
        ("Serveur", f"`{guild.name}`", True),
        ("Relevé", security_advisory.resume(constats), False),
    ]
    champs += security_advisory.champs(constats)
    if constats:
        champs.append(
            (
                "Pourquoi maintenant",
                "SentriX republie ce bulletin uniquement quand la situation change.",
                False,
            )
        )
    return embeds.canonical_log_embed(titre, fields=champs)


class SecurityBulletin(commands.Cog, name="SecurityBulletin"):
    """Un passage périodique, zéro commande, zéro écouteur."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.passage.start()

    def cog_unload(self):
        self.passage.cancel()

    async def _empreinte_connue(self, guild_id: int) -> str | None:
        try:
            return await self.bot.db.get_setting(f"{_CLE}:{int(guild_id)}")
        except Exception:
            logger.exception("Lecture de l'empreinte impossible guild=%s", guild_id)
            return None

    async def _retenir(self, guild_id: int, empreinte: str) -> None:
        try:
            await self.bot.db.set_setting(f"{_CLE}:{int(guild_id)}", empreinte)
        except Exception:
            logger.exception("Écriture de l'empreinte impossible guild=%s", guild_id)

    async def examiner(self, guild: discord.Guild, *, forcer: bool = False) -> bool:
        """Analyse un serveur et publie si quelque chose a bougé.

        Renvoie True si un bulletin est parti. Ne jamais confondre « rien
        publié » et « rien trouvé » : le premier cas est le plus fréquent,
        puisqu'une situation stable ne mérite pas de carte.
        """
        if guild.me is None:
            return ISSUE_HORS_CACHE
        constats = await security_advisory.analyser_complet(guild)
        empreinte = security_advisory.empreinte(constats)
        connue = await self._empreinte_connue(guild.id)
        if not forcer and empreinte == connue:
            return ISSUE_INCHANGE

        # Le tout premier passage sur un serveur sain n'a rien à annoncer : on
        # mémorise l'état sans écrire une carte « rien à signaler » que
        # personne n'a demandée. Une dégradation future, elle, sera publiée.
        if connue is None and not constats:
            await self._retenir(guild.id, empreinte)
            return ISSUE_PREMIER_PASSAGE_SAIN

        carte = construire_le_bulletin(guild, constats)
        for categorie in CATEGORIES_DE_REPLI:
            envoye = await log_service.send_log(
                self.bot,
                guild,
                categorie,
                carte,
                event_key=log_service.make_event_key(
                    guild.id, categorie, target_id=guild.id, discriminator=empreinte
                ),
            )
            if envoye:
                if categorie != CATEGORIES_DE_REPLI[0]:
                    logger.info(
                        "Bulletin de sécurité guild=%s publié dans « %s » faute de "
                        "journal « %s » configuré.",
                        guild.id, categorie, CATEGORIES_DE_REPLI[0],
                    )
                # N'enregistrer qu'en cas d'envoi réussi : sinon un serveur sans
                # salon de journaux « consommerait » son bulletin et ne le verrait
                # jamais le jour où il en branche un.
                await self._retenir(guild.id, empreinte)
                return ISSUE_PUBLIE
        return ISSUE_SANS_SALON

    @tasks.loop(hours=INTERVALLE_HEURES)
    async def passage(self):
        """Un passage sur tous les serveurs, et UNE ligne de journal, toujours.

        La version précédente ne journalisait que si elle avait publié. Un
        passage muet était donc indistinguable d'une boucle qui n'a jamais
        démarré — exactement le doute qu'on ne peut pas lever après coup.
        """
        issues: Counter[str] = Counter()
        for guild in list(self.bot.guilds):
            try:
                issues[await self.examiner(guild)] += 1
            except Exception:
                issues[ISSUE_ERREUR] += 1
                logger.exception("Bulletin de sécurité impossible guild=%s", guild.id)
        logger.info(
            "Bulletin de sécurité : %s serveur(s) examiné(s) — %s",
            sum(issues.values()),
            ", ".join(f"{n} {issue}" for issue, n in issues.most_common()) or "aucun",
        )

    @passage.before_loop
    async def _attendre(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(DELAI_AVANT_PREMIER_PASSAGE_SECONDES)


async def setup(bot: commands.Bot):
    await bot.add_cog(SecurityBulletin(bot))
