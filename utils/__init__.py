"""Utilitaires partagés de SentriX.

Les modules de logs sont chargés explicitement par leurs consommateurs.

Pendant le diagnostic Components V2, aucun monkey-patch global de
``discord.TextChannel.send`` n'est installé ici : il masquait l'origine exacte des
échecs en pouvant retomber sur un ancien embed. Le pipeline officiel reste
``utils.log_service`` -> ``utils.wide_logs``.
"""
