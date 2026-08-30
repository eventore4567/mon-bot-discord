"""Utilitaires partagés de SentriX.

Les modules de logs sont chargés explicitement par leurs consommateurs.

Important : ce package ne doit exécuter aucun ancien installateur de renderer à
l'import. Le système Components V2 actuel passe par ``utils.log_service`` puis
``utils.wide_logs`` ; ``utils.log_banners`` ne fournit volontairement plus de
fonction ``install()``.

Garder ``utils`` sans effet de bord évite aussi qu'un simple import de
``utils.durable_database`` fasse démarrer d'anciens patches de logs incompatibles
avec le renderer V83.
"""
