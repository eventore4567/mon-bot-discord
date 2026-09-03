"""
Configuration du bot.
Toutes les valeurs sensibles (token, clés API) sont lues depuis les variables
d'environnement / le fichier .env. NE JAMAIS écrire de token ou de clé en dur ici.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Obligatoire ---
# Railway peut conserver un retour à la ligne final lorsqu'un secret est collé/importé.
# Discord envoie le token dans l'en-tête Authorization : un CR/LF résiduel est donc rejeté
# par aiohttp comme tentative d'injection d'en-tête. On retire uniquement l'espace externe,
# puis on refuse explicitement tout caractère de contrôle restant à l'intérieur du token.
DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
if any(ord(ch) < 32 or ord(ch) == 127 for ch in DISCORD_TOKEN):
    raise RuntimeError(
        "DISCORD_TOKEN invalide : caractère de contrôle détecté. "
        "Recréez la variable Railway ou utilisez une référence vers le token du service principal."
    )

# --- Optionnel (fonctionnalités IA / utilitaires) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")          # /ask, /ai, /sentrix, etc.
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")         # /weather (sinon fallback wttr.in gratuit)

# Modèles API OpenAI actuels. Les noms internes Luna/Terra/Sol restent gérés dans
# utils/ai_service.py. Railway peut toujours fournir un override explicite si nécessaire.
OPENAI_MODEL_FAST = os.getenv("OPENAI_MODEL_FAST", "gpt-5.6-luna")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
OPENAI_MODEL_ADVANCED = os.getenv("OPENAI_MODEL_ADVANCED", "gpt-5.6-sol")
# Modèle séparé pour la génération d'images.
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")

# --- Général ---
DEFAULT_PREFIX = os.getenv("BOT_PREFIX", "+")
DEFAULT_LANGUAGE = "fr"
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/bot.db")

# --- Scalabilité Enterprise ---
# AutoShardedBot calcule automatiquement le nombre recommandé par Discord si SHARD_COUNT
# vaut 0. Une valeur explicite permet de figer le nombre de shards sur un gros déploiement.
try:
    SHARD_COUNT = max(0, int(os.getenv("SHARD_COUNT", "0") or 0))
except ValueError:
    SHARD_COUNT = 0
# PostgreSQL et Redis sont optionnels : EnterpriseInfra les active automatiquement si les
# URLs sont présentes, sinon SQLite/caches locaux restent le fallback sans casser le bot.
POSTGRES_URL = (os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or "").strip()
REDIS_URL = os.getenv("REDIS_URL", "").strip()
# Mode canary pour un service de test séparé. Ne jamais l'activer sur le service principal.
CANARY_MODE = os.getenv("SENTRIX_CANARY_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
try:
    CANARY_GUILD_ID = int(os.getenv("CANARY_GUILD_ID", "0") or 0)
except ValueError:
    CANARY_GUILD_ID = 0

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

# ---------------------------------------------------------------------------
# PALETTE SEMANTIQUE — SOURCE UNIQUE
#
# Ces valeurs sont celles REELLEMENT affichees par le bot. Mesure faite apres un
# boot complet : utils/sentrix_runtime.py ecrase les constantes de utils/embeds.py
# au demarrage, donc les valeurs codees dans embeds.py etaient mortes. Trois
# fichiers definissaient la meme semantique avec des valeurs differentes — un
# membre voyait deux verts distincts selon la commande utilisee.
#
# utils/design_system.py et utils/sentrix_runtime.py referencent desormais ces
# constantes. Changer une couleur ici la change PARTOUT.
#
# Les couleurs par CATEGORIE (economie, moderation, tickets...) restent definies
# dans design_system : ce sont des teintes d'identite, pas des etats.
# ---------------------------------------------------------------------------
# Palette semantique UNIQUE du bot. Elle vivait a deux endroits : ici, et une copie
# locale dans utils/embeds.py. Les deux avaient diverge, donc un succes n'avait pas le
# meme vert selon la commande (0x57F287 contre 0x22C55E). C'est la version de
# utils/embeds.py qui est retenue : plus lisible sur fond sombre, et deja servie a la
# majorite des commandes. utils/embeds.py, utils/design_system.py, utils/sentrix_runtime.py
# et utils/sentrix_visual_cleanup.py lisent tous ces constantes desormais.
COLOR_SUCCESS = 0x22C55E
COLOR_ERROR = 0xEF4444
COLOR_WARNING = 0xF59E0B
COLOR_INFO = 0x3B82F6
COLOR_NEUTRAL = 0x64748B
COLOR_BRAND = 0x7C3AED

# Valeurs historiques conservées pour compatibilité avec les anciens modules.
GLOBAL_COOLDOWN_RATE = 3
GLOBAL_COOLDOWN_PER = 5.0

# Zéro limite de débit pour les commandes IA/lourdes. L'autorité runtime finale neutralise
# également les anciens cooldowns, anti-doublons et compteurs de concurrence V41.
HEAVY_COMMAND_RATE_LIMIT = False

# ID du/des propriétaire(s) du bot pour les commandes développeur (/developer-panel, etc.)
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip().isdigit()]

if not DISCORD_TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN manquant ! Copiez .env.example vers .env et renseignez votre token."
    )
