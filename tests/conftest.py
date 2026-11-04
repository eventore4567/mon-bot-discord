"""Réglages communs des tests.

30/10/2026 : les commandes « + » sont retirées en production
(cogs/prefix_deprecation.prefixe_actif). Les tests historiques vérifient le
comportement des commandes « + » : on les rallume ici, comme le fait le harnais
e2e. Le comportement « + » coupé est testé explicitement
(tests/test_prefix_retire.py, tools/prefix_deprecation_e2e.py).
"""
import os

os.environ.setdefault("SENTRIX_PREFIXE_ACTIF", "1")
# Traduction automatique des serveurs anglais (utils/english_fallback) : coupée en
# test, pour des sorties déterministes et sans réseau.
os.environ.setdefault("SENTRIX_TRADUCTION_AUTO", "0")
# Bande en tête des cartes : coupée en production (03/11/2026), mais la suite
# vérifie toujours sa mécanique (image et pièce jointe livrées ensemble).
os.environ.setdefault("SENTRIX_BANDEAUX", "1")
# Recherche musique : pas d'appel réseau aux API de catalogue pendant les tests.
os.environ.setdefault("SENTRIX_MUSIC_CATALOG", "0")
