"""SentriX Core V2 — logique métier séparée de Discord (docs/core-v2-plan.md).

Une fonctionnalité = un handler métier ; les cogs deviennent des adaptateurs
fins qui parsent ctx/interaction, appellent le service, puis rendent le
résultat. Migration une famille de commandes à la fois (Phase 2) — voir
services/moderation.py pour le premier exemple concret (+ban / /ban).
"""
