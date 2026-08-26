"""Utilitaires partagés de SentriX.

Les modules historiques restent importables pour compatibilité, mais aucun renderer n'est
installé implicitement à l'import du package. ``utils.embeds`` et ``utils.log_service``
sont les deux sources canoniques ; le bootstrap Discord installe explicitement le transport.
"""
