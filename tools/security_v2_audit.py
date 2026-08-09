"""Audit CI minimal de la couche SentriX Security V2.

Le but est d'empêcher une régression silencieuse des branchements critiques : compteur
anti-nuke, rollback rôles, incidents, sauvegardes auto, règles propriétaire et dashboard.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    ast.parse(text, filename=path)
    return text


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"Security V2: branchement manquant: {label}")


def main() -> None:
    runtime = read("cogs/security_v2_runtime.py")
    require(runtime, "CREATE TABLE IF NOT EXISTS antinuke_policy", "politique anti-nuke persistante")
    require(runtime, "CREATE TABLE IF NOT EXISTS security_incidents", "journal d'incidents")
    require(runtime, "on_guild_role_delete", "snapshot suppression rôle")
    require(runtime, "on_guild_role_create", "snapshot création rôle")
    require(runtime, "on_guild_role_update", "snapshot modification rôle")
    require(runtime, "on_guild_update", "rollback serveur")
    require(runtime, "on_webhooks_update", "surveillance webhooks")
    require(runtime, "auto_backup_watch", "sauvegarde automatique")
    require(runtime, "_patch_dynamic_counter", "seuil dynamique")
    require(runtime, "_patch_incidents", "incident après déclenchement")
    require(runtime, 'name="health"', "+health")
    require(runtime, 'name="incidents"', "+security incidents")
    require(runtime, 'name="antinuke-config"', "+security antinuke-config")

    backup_fix = read("cogs/security_v2_backup_schema_fix.py")
    require(backup_fix, '"overwrites": _snapshot_overwrites(category)', "overwrites catégories backup auto")
    require(backup_fix, '"overwrites": _snapshot_overwrites(channel)', "overwrites salons backup auto")

    owner = read("cogs/security_owner_immunity_final.py")
    require(owner, "security whitelist domain-add", "whitelist domaine owner-only")
    require(owner, "security whitelist role-add", "whitelist rôle owner-only")
    require(owner, "message.author.id == message.guild.owner_id", "immunité Anti-GIF propriétaire")
    require(owner, "_late_reapply", "repatch propriétaire après chargement tardif")

    common = read("cogs/shop_default_prices.py")
    require(common, "install_security_v2_runtime", "chargement runtime commun")
    require(common, "await install_security_v2_runtime(bot)", "exécution runtime commun")
    require(common, "install_security_owner_immunity_final", "règles propriétaire finales")
    require(common, "install_security_v2_backup_schema_fix", "compatibilité backup auto")

    dashboard = read("web/setup_center_security_v2.py")
    require(dashboard, 'data-tab="security"', "onglet Sécurité V2")
    require(dashboard, "/api/guilds/{guild_id}/security-v2", "API sécurité dashboard")
    require(dashboard, "Seul le propriétaire réel du serveur", "verrou propriétaire dashboard")

    web_init = read("web/__init__.py")
    require(web_init, "setup_center_security_v2", "import dashboard sécurité")
    require(web_init, "_setup_center_security_v2.install", "installation dashboard sécurité")

    print("OK: Security V2 — compteur, rollback, incidents, backups, propriétaire, commandes et dashboard branchés")


if __name__ == "__main__":
    main()
