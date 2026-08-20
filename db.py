"""Compatibilité historique.

La source unique de la base SentriX est désormais :mod:`database.db`.
Ce module racine reste volontairement disponible pour les anciens imports externes, mais
ne contient plus une seconde copie du schéma et de la classe Database.
"""

from database.db import *  # noqa: F401,F403
