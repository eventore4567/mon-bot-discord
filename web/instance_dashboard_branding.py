"""Marque visuelle du dashboard partagée entre les instances du bot."""
from __future__ import annotations

import logging
from utils.instance_identity import brand_label

logger = logging.getLogger("bot.dashboard.instance-branding")
_INSTALLED = False


def _apply(value: str) -> str:
    brand = brand_label()
    if brand.casefold() == "sentrix":
        return value
    return value.replace("SENTRIX", brand.upper()).replace("SentriX", brand)


def install(dashboard, *modules) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Le durcissement de rendu s'applique aux deux instances, avant le remplacement de marque.
    try:
        from web import community_growth_security
        for module in modules:
            if hasattr(module, "COMMUNITY_HTML"):
                community_growth_security.install(module)
    except Exception:
        logger.exception("Durcissement du dashboard communautaire impossible.")

    brand = brand_label()
    if brand.casefold() == "sentrix":
        return
    if isinstance(getattr(dashboard, "INDEX_HTML", None), str):
        dashboard.INDEX_HTML = _apply(dashboard.INDEX_HTML)
    for module in modules:
        for attr in ("ENTERPRISE_HTML", "APPEAL_HTML", "COMMUNITY_HTML", "APPLICATION_HTML", "OPERATIONS_HTML", "EMBED_CENTER_HTML"):
            value = getattr(module, attr, None)
            if isinstance(value, str):
                setattr(module, attr, _apply(value))
    logger.info("Dashboard partagé marqué pour %s.", brand)
