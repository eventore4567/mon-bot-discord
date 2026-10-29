"""Réglages communs des tests.

30/10/2026 : les commandes « + » sont retirées en production
(cogs/prefix_deprecation.prefixe_actif). Les tests historiques vérifient le
comportement des commandes « + » : on les rallume ici, comme le fait le harnais
e2e. Le comportement « + » coupé est testé explicitement
(tests/test_prefix_retire.py, tools/prefix_deprecation_e2e.py).
"""
import os

os.environ.setdefault("SENTRIX_PREFIXE_ACTIF", "1")
