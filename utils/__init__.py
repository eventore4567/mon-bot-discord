"""Utilitaires partagés de SentriX.

Les modules de logs sont chargés explicitement par leurs consommateurs.
Aucun monkey-patch ou installer de logs n'est exécuté à l'import du package ``utils``.
Le transport officiel reste ``utils.log_service`` -> ``utils.wide_logs``.
"""
