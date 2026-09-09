"""Entrée Railway HA SentriX V98.

Le bootstrap produit historique est importé d'abord afin qu'il installe V95/V97/V96 et
les gardes dashboard. V98 remplace ensuite uniquement le constructeur de l'arbre slash,
puis lance exactement le même moteur HA.
"""
from __future__ import annotations

import asyncio
import logging

import railway_ha_product_boot as product_boot
from sentrix_v98_slash import install as install_v98


logger = logging.getLogger("bot.v98-ha-boot")
install_v98()
logger.warning("V98 confirmé dans l'entrypoint Railway HA produit.")


if __name__ == "__main__":
    try:
        asyncio.run(product_boot.ha_boot.run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX V98 HA.")
