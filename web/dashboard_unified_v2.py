"""Frontend unique du dashboard SentriX.

Le document servi sur ``/app`` est assemblé ici à partir de ``web/dashboard_ui/`` :
``index.html`` (squelette), ``app.css`` (une seule feuille de style) et ``js/*.js``
(un seul programme, concaténé dans l'ordre des noms de fichiers). Aucune couche ne
réécrit ce document après coup : les APIs restent la source de vérité, le navigateur ne
reçoit qu'un ``<style>`` et un ``<script>``.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("bot.dashboard-unified-v2")

UI_DIR = Path(__file__).resolve().parent / "dashboard_ui"
SCRIPT_ID = "sentrix-dashboard-unified-v2"
_CSS_SLOT = "/*__CSS__*/"
_JS_SLOT = "/*__JS__*/"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_index_html() -> str:
    """Assemble le document à partir des sources du dossier ``dashboard_ui``."""
    shell = _read(UI_DIR / "index.html")
    css = _read(UI_DIR / "app.css").strip()
    scripts = sorted((UI_DIR / "js").glob("*.js"))
    program = "\n\n".join(f"/* ==== {p.name} ==== */\n{_read(p).strip()}" for p in scripts)
    # Une seule fermeture lexicale : les fichiers partagent leurs déclarations sans exposer
    # quoi que ce soit sur ``window``.
    program = '(() => {\n"use strict";\n' + program + "\n})();"
    if _CSS_SLOT not in shell or _JS_SLOT not in shell:
        raise RuntimeError("dashboard_ui/index.html : emplacements CSS/JS introuvables")
    return shell.replace(_CSS_SLOT, css, 1).replace(_JS_SLOT, program, 1)


INDEX_HTML = build_index_html()

__all__ = ["INDEX_HTML", "SCRIPT_ID", "UI_DIR", "build_index_html"]
