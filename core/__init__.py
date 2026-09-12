"""SentriX Core V2 — modules transverses (une seule source de vérité par sujet).

Voir docs/core-v2-plan.md pour l'architecture cible complète et le plan de
migration par phases. Ce paquet se construit à côté du runtime existant
(cogs/, les dizaines de modules V18-V102) sans jamais le remplacer d'un coup :
chaque sous-module ici est additif, testable indépendamment de Discord, et
n'est branché au runtime existant que par un point d'intégration minimal et
documenté — jamais par un nouveau monkeypatch.
"""
