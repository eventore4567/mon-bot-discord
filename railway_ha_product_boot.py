"""Bootstrap HA SentriX avec interface dashboard finale installée avant aiohttp.

Le principal et le standby peuvent servir le dashboard avant de devenir leader Discord.
Cette entrée applique donc les routes/UI produit et la réparation finale de l'onglet Embeds
avant l'import du launcher HA historique. Un garde supplémentaire réapplique l'HTML final
au moment exact de ``dashboard.build_app`` : ainsi les couches visuelles importées entre le
bootstrap et la création aiohttp ne peuvent plus effacer la réparation.

Tous les autres comportements (lease Redis, PostgreSQL, healthcheck, snapshots et démarrage
du bot) restent gérés par railway_ha_boot.
"""
from __future__ import annotations

import asyncio
import logging

from discord import app_commands
from web import dashboard as dashboard_web
from sentrix_product_update import install_dashboard_prestart
from sentrix_final_product_finish import _install_embed_dashboard_finish

logger = logging.getLogger("bot.ha-product-boot")


def _install_dashboard_before_ha() -> None:
    product = bool(install_dashboard_prestart(dashboard_web))
    embeds = bool(_install_embed_dashboard_finish())
    if not product or not embeds:
        raise RuntimeError(
            f"Dashboard pré-start incomplet: product={product} embeds_final={embeds}"
        )
    logger.info(
        "Dashboard HA final installé avant aiohttp: product=%s embeds=%s.",
        product,
        embeds,
    )


_install_dashboard_before_ha()

# Import volontairement tardif : railway_ha_boot importe railway_boot, qui construit le
# bootstrap du bot. Aucune application aiohttp ne doit être construite avant la réparation.
import railway_ha_boot as ha_boot  # noqa: E402

# Une cession planifiée standby -> primary ne doit jamais couper une musique active.
# Le lease d'urgence reste strict : perte Redis/lease = fermeture immédiate comme avant.
from sentrix_ha_music_drain import install as _install_ha_music_drain  # noqa: E402

_install_ha_music_drain()
logger.warning("HA music drain : cession planifiée différée pendant une session musique active.")


# V95 doit être branchée explicitement dans le véritable entrypoint Railway. Le précédent
# branchement reposait uniquement sur l'import implicite de sitecustomize ; en production,
# on pouvait alors démarrer et synchroniser l'ancien catalogue (100 racines) sans jamais
# passer par la préparation V95. L'installation est idempotente : si sitecustomize l'a déjà
# faite, cet appel ne change rien ; sinon il garantit que CommandTree.sync prépare le
# catalogue groupé juste avant la synchronisation Discord.
from sentrix_v95_bootstrap import install as _install_v95_bootstrap  # noqa: E402

_install_v95_bootstrap()
if not getattr(app_commands.CommandTree.sync, "_sentrix_v95", False):
    raise RuntimeError("V95 slash non branchée sur CommandTree.sync avant le démarrage Railway.")
logger.warning("V95 bootstrap explicitement confirmé dans l'entrypoint Railway HA produit.")

# V97 corrige la couche d'exécution V95 elle-même : les signatures avec option facultative
# intermédiaire retombent sur un argument texte sûr, les pièces jointes sont réinjectées dans
# le Context legacy, /setup ne peut plus exposer ctx/*args et le dashboard Tickets reçoit une
# navigation guidée sans toucher à son schéma ni à ses API existantes.
from sentrix_v97_reliability import install as _install_v97_reliability  # noqa: E402

_install_v97_reliability(dashboard_web)
logger.warning("V97 fiabilité slash + dashboard Tickets simplifié branchés.")

# V99 corrige le transport des sous-commandes slash groupées dans le VERITABLE bootstrap
# Railway utilisé par la production. Les valeurs déjà transformées par Discord (texte,
# Member, Role, Channel, Attachment...) sont transmises directement au callback historique
# lorsque la signature est native ; les formes non natives gardent le parseur V95/V97.
# Cette installation doit arriver avant la construction V98, car les callbacks slash créés
# par V95 capturent v95._invoke_original au moment de leur exécution.
from sentrix_grouped_slash_fix import install as _install_v99_grouped_transport  # noqa: E402

_install_v99_grouped_transport()
logger.warning("V99 transport slash groupé natif + erreurs compactes branché dans l'entrypoint Railway HA produit.")

# V100 corrige les doubles acknowledgements/defer et les éditions d'anciens embeds sur
# Components V2. Il reste installé avant V101 : V101 ne remplace que la découverte des
# paramètres métier et la liaison des Commands de Cog.
from sentrix_v100_defer_fix import install as _install_v100_defer_fix  # noqa: E402
from sentrix_v100_runtime_fix import install as _install_v100_runtime_fix  # noqa: E402

_install_v100_defer_fix()
_install_v100_runtime_fix()
logger.warning("V100 interactions : defer idempotent, ack unique et compatibilité Components V2 branchés.")

# V101 est installé en dernier dans la pile runtime de commandes. Il assainit les
# signatures publiques à partir de la déclaration réelle du callback, restaure le Cog si
# une copie de Command l'a perdu et donne davantage de marge aux réponses IA de code.
from sentrix_v101_command_runtime import install as _install_v101_command_runtime  # noqa: E402

_install_v101_command_runtime()
logger.warning("V101 runtime commandes : signatures, liaison Cog et délai IA branchés.")

# V102 prépare la passerelle musique avant que cogs.music soit chargé. Elle ne crée aucune
# nouvelle commande : elle remplace uniquement la résolution de source du Cog Music afin
# que /music play et +play acceptent un titre, YouTube/YouTube Music, Spotify et Deezer.
# Spotify/Deezer sont résolus via leurs métadonnées publiques puis recherchés sur une source
# audio autorisée ; aucune lecture directe de flux DRM n'est tentée.
from sentrix_music_providers_v102 import install as _install_music_v102  # noqa: E402

_install_music_v102()
logger.warning("V102 musique : multi-provider branché avant le chargement des Cogs.")

# V98 doit être installé dans CE véritable bootstrap produit, pas uniquement dans un wrapper
# alternatif. Railway principal et standby utilisent historiquement ce module ; l'installation
# ici garantit donc que le constructeur V95 est remplacé par l'arborescence sémantique V98
# avant tout CommandTree.sync, quel que soit l'entrypoint externe utilisé.
from sentrix_v98_slash import install as _install_v98_grouped_slash  # noqa: E402

_install_v98_grouped_slash()
logger.warning("V98 slash sémantique explicitement branché dans l'entrypoint Railway HA produit.")

# Surface canonique : cette couche est maintenant installée dans le VRAI bootstrap partagé
# par primary et standby. Elle ne dépend donc plus d'un wrapper alternatif jamais exécuté.
# Elle garde les commandes + intactes, mais publie des racines/sous-commandes slash lisibles
# et françaises, notamment /musique playlist sauvegarder/importer/charger.
from sentrix_canonical_command_surface import install as _install_canonical_surface  # noqa: E402

_install_canonical_surface()
logger.warning("Surface slash canonique SentriX branchée sur le bootstrap HA réel.")

# V108 est installé par le wrapper Bot.add_cog de la passerelle musique V102. Ce second
# wrapper s'exécute juste après V108 afin de corriger la sémantique playlist sans dupliquer
# son stockage : create devient une vraie sauvegarde de la lecture/file et import devient
# une opération externe explicite.
from sentrix_music_playlist_semantics import install as _install_playlist_semantics  # noqa: E402

_install_playlist_semantics()
logger.warning("Sémantique playlist sauvegarder/importer/charger branchée après V108.")


# V96 doit être installée APRES l'import de railway_ha_boot : railway_boot remplace
# commands.Bot par la classe AutoSharded de production. On branche donc ici le hook de
# chargement sur la vraie classe utilisée en production, avant que run() charge
# cogs.verification. Le moteur CAPTCHA historique reste la seule source de vérité ; V96
# remplace seulement l'ancienne configuration par l'assistant guidé règlement/salon/rôle.
from sentrix_verification_v96 import install as _install_verification_v96  # noqa: E402
from sentrix_verification_v96_finalizer import install as _install_verification_v96_final  # noqa: E402

_install_verification_v96()
_install_verification_v96_final()
logger.warning(
    "V96 vérification guidée + finalizer explicitement branchés dans l'entrypoint Railway HA produit."
)


# Certaines couches dashboard historiques sont importées pendant le bootstrap HA. Elles
# peuvent encore modifier INDEX_HTML après la première réparation. On entoure donc la
# fonction build_app réellement utilisée : juste avant que les routes aiohttp soient figées,
# les réparations finales doivent obligatoirement être présentes.
_original_build_app = dashboard_web.build_app


def _build_app_with_final_dashboard(bot):
    if not _install_embed_dashboard_finish():
        raise RuntimeError("Réparation finale du dashboard Embeds absente avant build_app.")
    from sentrix_v97_reliability import install_dashboard as _install_v97_dashboard
    if not _install_v97_dashboard(dashboard_web):
        raise RuntimeError("Dashboard Tickets V97 absent avant build_app.")
    app = _original_build_app(bot)
    logger.info("Dashboard HA final confirmé au build_app aiohttp (Embeds + Tickets V97).")
    return app


_build_app_with_final_dashboard._sentrix_final_dashboard_build_guard = True
dashboard_web.build_app = _build_app_with_final_dashboard


if __name__ == "__main__":
    try:
        asyncio.run(ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX HA.")
