"""Modeles de domaine (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BotCreate",
    "BotOut",
    "EnvironmentCreate",
    "EnvironmentOut",
    "OrganizationOut",
    "ProjectCreate",
    "ProjectOut",
    "UserOut",
]

Library = Literal["discordpy", "discordjs", "nextcord", "disnake"]
EnvKind = Literal["prod", "canary"]
RuntimeMode = Literal["managed", "generic"]
SecretProvider = Literal["tmpfs_file", "env"]


class _In(BaseModel):
    """Charge utile entrante : tout champ inconnu est REFUSE.

    Un client qui envoie org_id ou status doit recevoir une erreur, jamais voir
    son champ ignore silencieusement.
    """

    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    """Reponse sortante : construite depuis une ligne SQL complete.

    extra="ignore" est indispensable : les lignes portent des colonnes non
    exposees (updated_at, github_installation_id...). Avec extra="forbid",
    model_validate(dict(row)) leverait une ValidationError sur chaque reponse.
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class OrganizationOut(_Out):
    id: UUID
    name: str
    slug: str
    plan: str
    status: str
    created_at: datetime


class UserOut(_Out):
    id: UUID
    discord_user_id: str
    display_name: str
    email: str | None = None


class ProjectCreate(_In):
    name: str = Field(min_length=1, max_length=100)
    repo_full_name: str | None = Field(default=None, max_length=255)
    default_branch: str = Field(default="main", max_length=100)


class ProjectOut(_Out):
    id: UUID
    org_id: UUID
    name: str
    repo_full_name: str | None
    default_branch: str
    status: str
    created_at: datetime


class BotCreate(_In):
    project_id: UUID
    name: str = Field(min_length=1, max_length=100)
    library: Library = "discordpy"


class BotOut(_Out):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    library: str
    status: str
    created_at: datetime


class EnvironmentCreate(_In):
    bot_id: UUID
    kind: EnvKind
    discord_application_id: str | None = Field(default=None, max_length=32)
    runtime_mode: RuntimeMode = "generic"
    secret_provider: SecretProvider = "env"  # noqa: S105 - provider name, not a secret


class EnvironmentOut(_Out):
    id: UUID
    org_id: UUID
    bot_id: UUID
    kind: str
    discord_application_id: str | None
    discord_application_verified_at: datetime | None
    cell_id: UUID
    runtime_mode: str
    secret_provider: str
    status: str
    created_at: datetime
