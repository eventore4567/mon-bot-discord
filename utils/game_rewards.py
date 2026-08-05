"""
Service central des RÉCOMPENSES DE MINI-JEUX (Partie 1 de la demande de Jayden).

Règle absolue : ce fichier ne crée AUCUNE deuxième monnaie. Toute récompense de jeu passe
par la même table `economy` (via Database.record_game_reward -> UPDATE economy SET cash =
cash + ?) que /daily, /work, /pay... Un +balance après une victoire de mini-jeu montre donc
exactement le même solde, à jour.

Anti-triche / anti-double-récompense :
- Chaque manche de jeu doit avoir un `session_id` UNIQUE (voir new_session_id()) transmis à
  reward_game_winner(). La table game_transactions a une contrainte UNIQUE sur ce champ : si
  la même manche est récompensée deux fois (double-clic, redémarrage en plein milieu, bug),
  la deuxième tentative est automatiquement refusée par la base — jamais par une simple
  vérification en mémoire qui pourrait être contournée par un redémarrage.
- acquire_play_lock() empêche un même joueur de faire tourner deux manches du même jeu en
  parallèle (ex: lancer +dice deux fois d'un coup pour tenter de doubler un gain).
- validate_opponent() interdit tout duel contre soi-même ou contre un bot.

Cooldowns : check_cooldown()/touch_cooldown() sont persistés dans game_cooldowns (table SQL),
donc ils survivent à un redémarrage du bot (contrainte explicite de Jayden pour les jeux à
grosse récompense). Pour les jeux rapides (cooldown de quelques secondes), le même mécanisme
est utilisé — un cooldown en mémoire serait perdu à chaque redéploiement Railway.

Réglages par serveur (table game_settings, +gamesetup) : voir get_settings()/is_game_enabled().
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass, field

DEFAULT_GAME_SETTINGS = {
    "enabled": True,
    "disabled_games": [],
    "allowed_channel_ids": [],
    "blocked_channel_ids": [],
    "allowed_role_ids": [],
    "blocked_role_ids": [],
    "min_reward_multiplier": 1.0,
    "max_reward_multiplier": 1.0,
    "daily_limit": 50,
    "event_multiplier": 1.0,
    "logs_enabled": True,
    "leaderboard_enabled": True,
    "dm_results": False,
    "compact_mode": False,
    "default_difficulty": "normal",
}

_JSON_FIELDS = ("disabled_games", "allowed_channel_ids", "blocked_channel_ids", "allowed_role_ids", "blocked_role_ids")
_BOOL_FIELDS = ("enabled", "logs_enabled", "leaderboard_enabled", "dm_results", "compact_mode")


@dataclass
class GameReward:
    """Résultat d'une tentative de récompense de mini-jeu."""

    success: bool
    game_name: str
    session_id: str
    guild_id: int
    user_id: int
    amount: int = 0
    result: str = "win"
    reason: str = "ok"
    display_id: str | None = None
    metadata: dict = field(default_factory=dict)


def new_session_id(game_name: str) -> str:
    """Identifiant UNIQUE d'une manche de jeu (à créer UNE FOIS au début de la manche, puis
    réutiliser pour la récompense éventuelle à la fin — jamais régénéré en cours de route,
    sinon la protection anti-double-récompense ne sert plus à rien)."""
    return f"{game_name}:{uuid.uuid4().hex}"


async def get_settings(bot, guild_id: int) -> dict:
    """Réglages +gamesetup fusionnés avec les valeurs par défaut, colonnes JSON/bool
    décodées pour être directement utilisables par le code appelant."""
    raw = await bot.db.get_game_settings(guild_id)
    settings = dict(DEFAULT_GAME_SETTINGS)
    for key, value in raw.items():
        if key in _JSON_FIELDS:
            try:
                settings[key] = json.loads(value) if value else []
            except (TypeError, ValueError):
                settings[key] = []
        elif key in _BOOL_FIELDS:
            settings[key] = bool(value)
        elif key in settings:
            settings[key] = value
    return settings


async def set_settings(bot, guild_id: int, updates: dict) -> dict:
    """Encode `updates` (dict Python) vers les colonnes SQL attendues par game_settings,
    puis enregistre. `updates` peut mélanger des clés JSON, bool ou simples — seules les
    clés reconnues sont transmises à la base."""
    encoded = {}
    for key, value in updates.items():
        if key not in DEFAULT_GAME_SETTINGS:
            continue
        if key in _JSON_FIELDS:
            encoded[key] = json.dumps(value)
        elif key in _BOOL_FIELDS:
            encoded[key] = 1 if value else 0
        else:
            encoded[key] = value
    if not encoded:
        return await get_settings(bot, guild_id)
    await bot.db.set_game_settings(guild_id, encoded)
    return await get_settings(bot, guild_id)


async def is_game_enabled(bot, guild_id: int, game_name: str, channel_id: int | None = None, role_ids: set[int] | None = None) -> tuple[bool, str]:
    """Vérifie, dans l'ordre : interrupteur général -> jeu désactivé -> salon autorisé/bloqué
    -> rôle autorisé/bloqué. Retourne (True, "") si la manche peut démarrer, ou
    (False, raison_lisible) sinon."""
    settings = await get_settings(bot, guild_id)
    if not settings["enabled"]:
        return False, "🎮 Les mini-jeux sont désactivés sur ce serveur."
    if game_name in settings["disabled_games"]:
        return False, f"🎮 Le jeu **{game_name}** est désactivé sur ce serveur."
    if channel_id is not None:
        if settings["allowed_channel_ids"] and channel_id not in settings["allowed_channel_ids"]:
            return False, "🎮 Les mini-jeux ne sont pas autorisés dans ce salon."
        if channel_id in settings["blocked_channel_ids"]:
            return False, "🎮 Les mini-jeux sont bloqués dans ce salon."
    if role_ids is not None:
        if settings["allowed_role_ids"] and not (role_ids & set(settings["allowed_role_ids"])):
            return False, "🎮 Vous n'avez pas le rôle requis pour jouer aux mini-jeux ici."
        if role_ids & set(settings["blocked_role_ids"]):
            return False, "🎮 Un de vos rôles vous empêche de jouer aux mini-jeux ici."
    return True, ""


async def check_cooldown(bot, guild_id: int, user_id: int, game_name: str, cooldown_seconds: int) -> tuple[bool, int]:
    """(True, 0) si le joueur peut jouer, (False, secondes_restantes) sinon. Le cooldown est
    persisté en base (game_cooldowns) : il survit à un redémarrage du bot."""
    if cooldown_seconds <= 0:
        return True, 0
    remaining = await bot.db.get_game_cooldown_remaining(guild_id, user_id, game_name, cooldown_seconds)
    return (remaining <= 0), remaining


async def touch_cooldown(bot, guild_id: int, user_id: int, game_name: str):
    await bot.db.touch_game_cooldown(guild_id, user_id, game_name)


async def check_daily_limit(bot, guild_id: int, user_id: int) -> tuple[bool, int, int]:
    """Vérifie la limite journalière de manches RÉCOMPENSÉES (+gamesetup, daily_limit).
    Retourne (autorisé, jouées_aujourd'hui, limite)."""
    settings = await get_settings(bot, guild_id)
    limit = settings["daily_limit"]
    if limit <= 0:
        return True, 0, 0  # 0 = illimité
    played = await bot.db.count_game_rewards_today(guild_id, user_id)
    return played < limit, played, limit


def validate_opponent(author, opponent) -> str | None:
    """Anti-triche pour les duels : retourne un message d'erreur en français si l'adversaire
    n'est pas valide, sinon None. Aucun duel contre soi-même, aucun duel contre un bot."""
    if opponent is None:
        return "○ Adversaire introuvable."
    if getattr(opponent, "bot", False):
        return "○ Vous ne pouvez pas défier un bot."
    if opponent.id == author.id:
        return "○ Vous ne pouvez pas vous défier vous-même."
    return None


class PlayLockRegistry:
    """Empêche un même joueur de faire tourner deux manches du MÊME jeu en même temps (ex:
    lancer +dice deux fois d'un coup avant que la première réponse n'arrive). Un verrou par
    (guild_id, user_id, game_name), en mémoire — c'est une protection anti-spam de manches
    simultanées, pas une source de vérité (celle-ci reste toujours la contrainte UNIQUE de
    game_session_id en base pour l'anti-double-récompense)."""

    def __init__(self):
        self._locked: set[tuple[int, int, str]] = set()

    def try_acquire(self, guild_id: int, user_id: int, game_name: str) -> bool:
        key = (guild_id, user_id, game_name)
        if key in self._locked:
            return False
        self._locked.add(key)
        return True

    def release(self, guild_id: int, user_id: int, game_name: str):
        self._locked.discard((guild_id, user_id, game_name))


_registry = PlayLockRegistry()


def acquire_play_lock(guild_id: int, user_id: int, game_name: str) -> bool:
    return _registry.try_acquire(guild_id, user_id, game_name)


def release_play_lock(guild_id: int, user_id: int, game_name: str):
    _registry.release(guild_id, user_id, game_name)


def compute_reward(settings: dict, base_amount: int) -> int:
    """Applique le multiplicateur d'événement (+gamesetup) puis borne le résultat entre
    min_reward_multiplier et max_reward_multiplier du montant de base, jamais négatif."""
    amount = base_amount * settings.get("event_multiplier", 1.0)
    lo = base_amount * settings.get("min_reward_multiplier", 1.0)
    hi = base_amount * settings.get("max_reward_multiplier", 1.0)
    if hi < lo:
        lo, hi = hi, lo
    amount = max(lo, min(amount, hi))
    return max(0, round(amount))


async def reward_game_winner(
    bot, guild_id: int, user_id: int, game_name: str, base_amount: int, session_id: str,
    result: str = "win", metadata: dict | None = None,
) -> GameReward:
    """Point d'entrée UNIQUE pour créditer une récompense de mini-jeu. Applique les réglages
    du serveur (+gamesetup), puis délègue à Database.record_game_reward() pour l'écriture
    atomique + la protection anti-double-récompense (contrainte UNIQUE sur session_id)."""
    metadata = metadata or {}
    settings = await get_settings(bot, guild_id)
    final_amount = compute_reward(settings, base_amount) if result == "win" else 0
    ok, display_id_or_reason, credited = await bot.db.record_game_reward(
        guild_id, user_id, game_name, session_id, result, final_amount, json.dumps(metadata),
    )
    if not ok:
        return GameReward(
            success=False, game_name=game_name, session_id=session_id, guild_id=guild_id,
            user_id=user_id, amount=0, result=result, reason=display_id_or_reason, metadata=metadata,
        )
    reward = GameReward(
        success=True, game_name=game_name, session_id=session_id, guild_id=guild_id, user_id=user_id,
        amount=credited or 0, result=result, reason="ok", display_id=display_id_or_reason, metadata=metadata,
    )
    if settings.get("logs_enabled", True):
        await _emit_game_log(bot, guild_id, reward)
    return reward


async def _emit_game_log(bot, guild_id: int, reward: GameReward):
    """Émet dans la catégorie de log 'games' (+logsetup) si un salon est configuré et
    activé — n'échoue jamais silencieusement de façon bruyante (send_log gère déjà tout ça)."""
    try:
        import discord
        from utils import log_service, design_system

        guild = bot.get_guild(guild_id)
        if guild is None:
            return
        member = guild.get_member(reward.user_id)
        who = member.mention if member else f"<@{reward.user_id}>"
        title = design_system.kind_title("Récompense de mini-jeu", kind="success", category_emoji="🎮")
        embed = discord.Embed(
            title=title,
            description=(
                f"**Jeu :** {reward.game_name}\n"
                f"**Joueur :** {who}\n"
                f"**Résultat :** {reward.result}\n"
                f"**Récompense :** {reward.amount} 🪙\n"
                f"**Référence :** `{reward.display_id}`"
            ),
            colour=design_system.COLORS.games,
        )
        await log_service.send_log(bot, guild, "games", embed)
    except Exception:
        # Le jeu doit toujours fonctionner même si le log échoue (salon supprimé,
        # permissions manquantes, guilde introuvable en cache...).
        pass


def random_reward(rng, lo: int, hi: int) -> int:
    """Petit utilitaire commun : montant aléatoire entre lo et hi inclus, via le module
    `random` fourni par l'appelant (pour rester testable/déterministe si besoin)."""
    return rng.randint(lo, hi)


# Cooldowns (secondes) de chaque mini-jeu — à titre INFORMATIF pour +dailygames (affiche à
# un joueur ses cooldowns en cours sans avoir à retenter chaque commande). La valeur qui
# fait réellement foi reste toujours celle passée à check_cooldown()/touch_cooldown() par
# la commande elle-même (cogs/minigames.py, cogs/games_economy.py) : si les deux venaient à
# diverger, seul l'appel réel dans la commande a un effet, ce dictionnaire ne sert qu'à
# l'affichage informatif de +dailygames.
GAME_COOLDOWNS = {
    "rps": 8, "guess-number": 15, "trivia": 12, "hangman": 20, "math-quiz": 8,
    "blackjack": 15, "slots": 10,
    "coinflip": 10, "dice": 10, "luckyroll": 8, "highlow": 12, "memory": 20, "reaction": 15,
    "scramble": 15, "wordgame": 15, "emojiquiz": 15, "colorquiz": 10, "fasttype": 15,
    "duel": 15, "numberduel": 15, "quizduel": 15, "reactionduel": 15, "connect4": 15,
    "triviastart": 60, "wordrace": 60, "mathrace": 60, "guessrace": 60,
    "reactionevent": 60, "emoji-race": 60, "lastmessage": 90,
    "adventure": 900, "dungeon": 1200, "mining": 600, "fishing": 600,
    "treasure": 1500, "hunt": 900, "explore": 1000,
}


def secure_pick(options: list):
    """Choix aléatoire cryptographiquement sûr (secrets), utilisé pour tout ce qui touche à
    une récompense — évite un random.choice() prévisible/manipulable."""
    return options[secrets.randbelow(len(options))]
