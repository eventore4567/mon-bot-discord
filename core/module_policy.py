"""Politique des modules SentriX.

Ce fichier ne contient aucune logique runtime : uniquement les règles déclaratives
du micro-kernel (criticité, verrouillage à chaud, dépendances connues).
"""

CRITICAL_EXTENSIONS = frozenset({
    "cogs.moderation",
    "cogs.automod",
    "cogs.security_runtime_hardening",
    "cogs.tickets",
    "cogs.configuration",
    "cogs.logs",
    "cogs.utility",
})

RUNTIME_LOCKED_EXTENSIONS = CRITICAL_EXTENSIONS | frozenset({
    "cogs.visual_experience_v5",
})

MODULE_DEPENDENCIES = {
    "cogs.security_runtime_hardening": ("cogs.automod",),
    "cogs.ticket_claim_security": ("cogs.tickets",),
    "cogs.ai_disable_guard": ("cogs.ai",),
    "cogs.giveaway_center": ("cogs.events",),
}


def validate_policy(extensions) -> list[str]:
    """Retourne les incohérences de politique sans lever d'exception."""
    extension_set = set(extensions)
    problems: list[str] = []

    for name in sorted(CRITICAL_EXTENSIONS | RUNTIME_LOCKED_EXTENSIONS):
        if name not in extension_set:
            problems.append(f"module déclaré dans la politique mais absent: {name}")

    for module, dependencies in MODULE_DEPENDENCIES.items():
        if module not in extension_set:
            problems.append(f"dépendance déclarée pour un module absent: {module}")
        for dependency in dependencies:
            if dependency not in extension_set:
                problems.append(
                    f"dépendance absente pour {module}: {dependency}"
                )

    return problems
