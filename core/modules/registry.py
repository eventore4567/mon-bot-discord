"""Registre central des modules SentriX — Milestone 2 (Configuration Platform).

Avant ce module, chaque système (tickets, automod, vérification, niveaux...)
avait sa propre notion éparpillée d'"activé"/"configuré", jamais lue à un seul
endroit — /setup et le dashboard pouvaient donc en théorie afficher deux
histoires différentes pour le même serveur, puisque rien ne garantissait
qu'ils lisaient les mêmes calculs.

Ce registre ne remplace AUCUN stockage existant (guild_config, automod_
settings, ticket_types, etc. restent la source de données réelle) : c'est un
modèle de lecture, une couche de FAÇADE qui interroge ces sources existantes
et produit un statut normalisé. Toute nouvelle consommatrice (une future page
/setup, une future page dashboard, un futur diagnostic) doit passer par ici
plutôt que réinventer son propre calcul de statut par module.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

DescribeFunc = Callable[[object, int], Awaitable["ModuleStatus"]]


@dataclass(frozen=True, slots=True)
class ModuleStatus:
    """Statut d'un module pour UN serveur donné, au moment de l'appel."""

    enabled: bool
    configured: bool
    summary: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    key: str
    label: str
    describe: DescribeFunc
    commands: tuple[str, ...] = field(default_factory=tuple)
    dashboard_page: str | None = None


_REGISTRY: dict[str, ModuleDefinition] = {}


def register(definition: ModuleDefinition) -> None:
    """Idempotent par construction : ré-enregistrer la même clé remplace
    l'ancienne définition plutôt que d'échouer — utile pour les rechargements
    d'extension pendant le développement, sans jamais dupliquer une entrée."""
    _REGISTRY[definition.key] = definition


def unregister(key: str) -> None:
    _REGISTRY.pop(key, None)


def all_modules() -> tuple[ModuleDefinition, ...]:
    return tuple(_REGISTRY.values())


def get_definition(key: str) -> ModuleDefinition | None:
    return _REGISTRY.get(key)


_ERROR_STATUS = ModuleStatus(
    enabled=False,
    configured=False,
    summary="Diagnostic indisponible",
    issues=("une erreur est survenue pendant le diagnostic de ce module",),
)


async def status_for(bot, guild_id: int, key: str) -> ModuleStatus | None:
    definition = _REGISTRY.get(key)
    if definition is None:
        return None
    try:
        return await definition.describe(bot, guild_id)
    except Exception:
        return _ERROR_STATUS


async def all_statuses(bot, guild_id: int) -> dict[str, ModuleStatus]:
    """Ne lève jamais : un module dont le diagnostic échoue reçoit un statut
    d'erreur visible plutôt que de faire échouer l'affichage des autres —
    un /setup ou un dashboard qui plante entièrement à cause d'UN module cassé
    serait pire que d'en signaler un seul en erreur."""
    result: dict[str, ModuleStatus] = {}
    for key, definition in _REGISTRY.items():
        try:
            result[key] = await definition.describe(bot, guild_id)
        except Exception:
            result[key] = _ERROR_STATUS
    return result


def reset_for_tests() -> None:
    _REGISTRY.clear()
