"""
Configuration du bot.
Toutes les valeurs sensibles (token, clés API) sont lues depuis les variables
d'environnement / le fichier .env. NE JAMAIS écrire de token ou de clé en dur ici.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Obligatoire ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# --- Optionnel (fonctionnalités IA / utilitaires) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")          # /ask, /imagine, /rewrite, etc.
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")         # /weather (sinon fallback wttr.in gratuit)

# --- Général ---
DEFAULT_PREFIX = os.getenv("BOT_PREFIX", "+")
DEFAULT_LANGUAGE = "fr"
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/bot.db")

# Couleurs des embeds (identité visuelle SentriX : violet électrique / futuriste)
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_WARNING = 0xFEE75C
COLOR_INFO = 0x5865F2
COLOR_NEUTRAL = 0x5847EB
COLOR_BRAND = 0x5847EB

# Cooldown anti-spam global (par utilisateur, par commande) en secondes
GLOBAL_COOLDOWN_RATE = 3
GLOBAL_COOLDOWN_PER = 5.0

# ID du/des propriétaire(s) du bot pour les commandes développeur (/developer-panel, etc.)
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip().isdigit()]

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN manquant ! Copiez .env.example vers .env et renseignez votre token."
    )
