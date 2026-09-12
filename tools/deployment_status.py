#!/usr/bin/env python3
"""Compare le commit git local au commit RÉELLEMENT déployé (via /health).

Milestone 1 (SentriX Core Reliability), priorité P0 #2 : "Je ne veux plus de
situation où GitHub main = nouvelle version, Railway = vieux commit." Ce script
ne fait aucune supposition — il interroge le endpoint /health du service
réellement en ligne (qui expose déjà `release`, le SHA tronqué à 12 caractères
que Railway injecte via RAILWAY_GIT_COMMIT_SHA, voir
web/health_runtime_v45.py::_release_id) et le compare au HEAD git local.

Usage :
    python3 tools/deployment_status.py <url-de-base-ou-URL-/health>
    SENTRIX_HEALTH_URL=https://... python3 tools/deployment_status.py

Ne modifie rien, ne déploie rien, ne redémarre rien : lecture seule.
Sortie 0 si le commit déployé correspond au HEAD local, 1 sinon (y compris si
injoignable) — utilisable comme porte dans un script plus large sans avoir à
parser la sortie humaine.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 10


def _local_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=True
        )
        return result.stdout.strip()
    except Exception as exc:
        print(f"[ERREUR] impossible de lire le HEAD git local : {exc}")
        return None


def _health_url(argv: list[str]) -> str | None:
    if argv:
        url = argv[0].rstrip("/")
    else:
        url = (os.getenv("SENTRIX_HEALTH_URL", "") or "").rstrip("/")
    if not url:
        return None
    if not url.endswith("/health"):
        url = f"{url}/health"
    return url


def _fetch_health(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[ERREUR] /health injoignable ({url}) : {exc}")
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"[ERREUR] /health n'a pas renvoyé du JSON valide : {exc}")
        return None


def main() -> int:
    url = _health_url(sys.argv[1:])
    if url is None:
        print(__doc__)
        print("[ERREUR] aucune URL fournie (argument ou SENTRIX_HEALTH_URL).")
        return 1

    local_head = _local_head()
    if local_head is None:
        return 1
    local_short = local_head[:12]

    data = _fetch_health(url)
    if data is None:
        print("\nCODE CORRIGÉ    : oui (local)")
        print("DÉPLOYÉ         : INCONNU (endpoint injoignable)")
        print("BOOT OK         : INCONNU")
        return 1

    deployed = str(data.get("release") or "").strip()
    boot_ok = str(data.get("status") or "").strip().lower() in {"ok", "healthy", "ready"} or bool(
        data.get("ok")
    )

    print(f"HEAD local      : {local_head}")
    print(f"Déployé (/health): {deployed or 'non exposé'}")

    if not deployed or deployed == "inconnu":
        print("\nDÉPLOYÉ         : INCONNU (RAILWAY_GIT_COMMIT_SHA non injecté côté service)")
        return 1

    match = local_short.startswith(deployed) or deployed.startswith(local_short)
    print(f"\nCODE CORRIGÉ    : oui (local, {local_short})")
    print(f"DÉPLOYÉ         : {'OUI — identique au local' if match else 'NON — commit différent du local'} ({deployed})")
    print(f"BOOT OK         : {'oui' if boot_ok else 'inconnu ou non healthy'}")

    if not match:
        print(
            "\n[ATTENTION] Le commit déployé ne correspond pas au HEAD local. "
            "Ne pas annoncer un correctif comme \"en production\" tant que ceci n'est pas résolu."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
