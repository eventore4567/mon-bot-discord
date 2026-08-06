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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")          # /ask, /ai, /sentrix, etc.
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")         # /weather (sinon fallback wttr.in gratuit)

# Modèle IA par défaut (questions courantes) et modèle avancé (programmation, analyse
# détaillée, résolution de problèmes, longs textes, explications difficiles) — voir
# utils/ai_service.py pour la logique de sélection automatique. Restent configurables via
# variables d'environnement sans toucher au code, au cas où OpenAI change encore les noms.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
OPENAI_MODEL_ADVANCED = os.getenv("OPENAI_MODEL_ADVANCED", "gpt-5.6-sol")
# Modèle séparé pour la génération d'images.
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")

# --- Général ---
DEFAULT_PREFIX = os.getenv("BOT_PREFIX", "+")
DEFAULT_LANGUAGE = "fr"
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/bot.db")

# --- Application dashboard (voir web/dashboard.py) ---
# Port d'écoute : Railway fournit automatiquement la variable PORT, sinon 8080 en local.
DASHBOARD_PORT = int(os.getenv("PORT", "8080"))
# OAuth Discord. Le client ID peut rester vide : le dashboard utilise alors l'ID du bot.
# Le secret doit uniquement être enregistré dans Railway, jamais dans GitHub.
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
# URL HTTPS publique de BASE, sans /app ni /oauth/callback. Les anciennes valeurs qui
# contiennent déjà l'un de ces suffixes sont corrigées automatiquement afin d'éviter les
# liens du type /oauth/callback/oauth/callback.
_DEFAULT_DASHBOARD_PUBLIC_URL = "https://mon-bot-discord-production-8944.up.railway.app"
_raw_dashboard_url = (
    os.getenv("DASHBOARD_PUBLIC_URL", "").strip().rstrip("/")
    or _DEFAULT_DASHBOARD_PUBLIC_URL
)
for _suffix in ("/oauth/callback", "/app"):
    if _raw_dashboard_url.endswith(_suffix):
        _raw_dashboard_url = _raw_dashboard_url[: -len(_suffix)].rstrip("/")
if not _raw_dashboard_url.startswith(("https://", "http://")):
    _raw_dashboard_url = _DEFAULT_DASHBOARD_PUBLIC_URL
DASHBOARD_PUBLIC_URL = _raw_dashboard_url
DASHBOARD_APP_URL = f"{DASHBOARD_PUBLIC_URL}/app"
DASHBOARD_CALLBACK_URL = f"{DASHBOARD_PUBLIC_URL}/oauth/callback"
# Ancien réglage conservé pour ne pas casser les installations existantes.
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

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
