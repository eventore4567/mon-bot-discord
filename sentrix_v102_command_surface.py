"""SentriX V102 — surface slash lisible et playlists fiables.

V102 est une couche d'interface : elle garde les callbacks métier existants, retire de
la surface slash les commandes cachées/doublons, francise les noms visibles et répare
la sauvegarde/lecture des playlists sans toucher aux données des autres modules.
"""
from __future__ import annotations

import asyncio
import json
import logging

from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_v98_slash as v98

logger = logging.getLogger("bot.v102-command-surface")
_INSTALLED = False

ROOTS = {
    "ai": "ia", "info": "infos", "utility": "outils", "economy": "economie",
    "level": "niveaux", "levels": "niveaux", "game": "jeux", "games": "jeux",
    "music": "musique", "events": "evenements", "ticket": "tickets",
    "sanctions": "moderation", "moderation": "moderation", "security": "securite",
    "config": "configuration", "server": "serveur", "role": "roles", "roles": "roles",
    "embeds": "messages", "owner": "proprietaire", "more": "autres",
    "giveaway": "concours", "invites": "invitations",
}
ROOT_BACK = {
    "tickets": "ticket", "moderation": "moderation", "securite": "security",
    "configuration": "config", "economie": "economy", "niveaux": "level",
    "jeux": "game", "roles": "role", "serveur": "server",
}
ROOT_DESC = {
    "ia": "Assistant IA, images et outils intelligents.",
    "infos": "Informations sur les membres, salons, serveur et bot.",
    "outils": "Outils pratiques et commandes du quotidien.",
    "economie": "Solde, banque, boutique et récompenses.",
    "niveaux": "Niveaux, XP, réputation et classements.",
    "jeux": "Mini-jeux et activités communautaires.",
    "musique": "Musique, file d'attente, lecture et playlists.",
    "evenements": "Événements, tournois et activités.",
    "tickets": "Tickets, support et réglages des tickets.",
    "moderation": "Sanctions et outils de modération.",
    "securite": "AutoMod, anti-raid, anti-nuke et sécurité.",
    "configuration": "Configuration générale de SentriX.",
    "serveur": "Structure et administration du serveur.",
    "roles": "Rôles, panels et vérification.",
    "messages": "Embeds, annonces et design des messages.",
    "proprietaire": "Commandes réservées au propriétaire de SentriX.",
    "autres": "Autres fonctions utiles de SentriX.",
    "concours": "Concours et tirages au sort.",
    "invitations": "Invitations, classements et bonus.",
}

# Noms réellement montrés dans Discord. Les inconnus gardent leur nom historique :
# mieux vaut un nom exact qu'une traduction automatique ambiguë.
LEAVES = {
    "userinfo": "utilisateur", "membercount": "membres", "emoji-list": "emojis",
    "reminder-list": "rappels", "reminder-cancel": "annuler-rappel", "report-bug": "signaler-bug",
    "fact-check": "verifier-info", "image-prompt": "prompt-image", "ai-translate": "traduire",
    "bot-status": "statut", "server-growth": "croissance", "command-stats": "stats-commandes",
    "unban": "debannir", "kick": "expulser", "warn": "avertir", "warnings": "avertissements",
    "unwarn": "retirer-avertissement", "clearwarnings": "vider-avertissements", "clear": "nettoyer",
    "slowmode": "mode-lent", "lock": "verrouiller", "unlock": "deverrouiller", "nickname": "pseudo",
    "resetnick": "reset-pseudo", "giverole": "donner-role", "removerole": "retirer-role",
    "modhistory": "historique", "ticket-reopen": "rouvrir", "tickettranscript": "transcription",
    "sanctiondm": "message-sanction", "security-check": "verification", "security-level": "niveau",
    "permission-audit": "audit-permissions", "server-backup": "sauvegarder", "server-restore": "restaurer",
    "lockdown-server": "verrouillage-total", "unlock-server": "deverrouillage-total",
    "blacklist-users": "utilisateurs-bloques", "blacklist-list": "liste-noire", "blacklist-add": "bloquer",
    "blacklist-remove": "debloquer", "whitelist-domain": "autoriser-domaine",
    "unwhitelist-domain": "retirer-domaine", "syncbl": "sync-liste-noire", "unsyncbl": "desync-liste-noire",
    "setprefix": "prefixe", "setmodrole": "role-modo", "config-view": "voir",
    "config-reset": "reinitialiser", "create-server": "creer-structure", "delete-channel": "supprimer-salon",
    "disablecommand": "desactiver-commande", "enablecommand": "activer-commande",
    "ignorechannel": "ignorer-salon", "unignorechannel": "reactiver-salon", "setwarnrole": "role-avertissement",
    "setwarnbanthreshold": "limite-avertissements", "set-xp": "definir-xp", "add-xp": "ajouter-xp",
    "reset-levels": "reset-niveaux", "levelcheck": "verifier-niveau", "levelrepair": "reparer-niveau",
    "designsetup": "design", "embedconfig": "reglages-embed", "reactionrole-add": "ajouter-reaction",
    "reactionrole-remove": "retirer-reaction", "reactionrole-list": "liste-reactions",
    "balance": "solde", "daily": "quotidien", "weekly": "hebdo", "work": "travailler",
    "pay": "payer", "inventory": "inventaire", "economyleaderboard": "classement",
    "leaderboard-levels": "classement", "set-level-role": "role-niveau",
    "remove-level-role": "retirer-role-niveau", "voice-time": "temps-vocal", "set-bio": "bio",
    "ticket": "ouvrir", "ticketsetup": "configuration", "ticketpanel": "creer-panel",
    "ticketpanel-toggle": "activer-panel", "tickettype": "type", "ticketform": "formulaire",
    "ticketconfig": "reglages", "ticketlogs": "logs", "ticketlimit": "limite",
    "ticketautoclose": "fermeture-auto", "giveaway-list": "liste", "giveaway-create": "creer",
    "giveaway-end": "terminer", "giveaway-reroll": "relancer", "giveaway-cancel": "annuler",
    "event-join": "rejoindre", "event-leave": "quitter", "event-list": "liste", "event-create": "creer",
    "event-cancel": "annuler", "tournament-join": "rejoindre-tournoi", "tournament-list": "tournois",
    "tournament-create": "creer-tournoi", "tournament-start": "lancer-tournoi",
    "invite-leaderboard": "classement", "invited-by": "invite-par", "addbonusinvites": "ajouter-bonus",
    "removebonusinvites": "retirer-bonus", "invitebonushistory": "historique-bonus",
    "notifs-ping": "ajouter", "notifs-list": "liste", "notifs-remove": "supprimer",
    "welcome-config": "bienvenue", "join": "rejoindre", "leave": "quitter", "play": "jouer",
    "resume": "reprendre", "skip": "suivant", "queue": "file", "nowplaying": "en-cours",
    "loop": "boucle", "shuffle": "melanger", "remove-from-queue": "retirer-file",
    "clear-queue": "vider-file", "playlist-save": "playlist-sauvegarder",
    "playlist-load": "playlist-charger", "rps": "pierre-feuille-ciseaux", "guess-number": "devine-nombre",
    "trivia": "quiz", "tictactoe": "morpion", "hangman": "pendu", "math-quiz": "calcul",
    "slots": "machine-a-sous", "coinflip": "pile-ou-face", "dice": "des", "highlow": "plus-ou-moins",
    "memory": "memoire", "scramble": "mot-melange", "wordgame": "jeu-mots", "emojiquiz": "quiz-emoji",
    "colorquiz": "quiz-couleur", "fasttype": "vitesse", "connect4": "puissance4",
    "numberduel": "duel-nombres", "reactionduel": "duel-reaction", "quizduel": "duel-quiz",
    "wordrace": "course-mots", "reactionevent": "course-reaction", "guessrace": "course-devinette",
    "mathrace": "course-calcul", "emoji-race": "course-emoji", "dungeon": "donjon",
    "mining": "minage", "fishing": "peche", "treasure": "tresor", "hunt": "chasse",
    "explore": "explorer", "gamehistory": "historique", "gameprofile": "profil",
    "gamestats": "stats", "gametop": "classement", "dailygames": "jeux-du-jour",
}

DUPLICATES = frozenset({
    "leaderboard-money", "me", "rank", "buyrole", "ask", "chat", "chat-reset", "embed-create", "latency", "levelroles",
})
MUSIC = frozenset({
    "join", "leave", "play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "volume", "loop",
    "shuffle", "remove-from-queue", "clear-queue", "playlist-save", "playlist-load",
})
BUCKETS = {
    ("ticket", "panel"): "panneaux", ("ticket", "config"): "configuration",
    ("ticket", "manage"): "gestion", ("ticket", "stats"): "historique",
    ("moderation", "members"): "membres", ("moderation", "cases"): "dossiers",
    ("moderation", "emoji"): "emojis", ("moderation", "general"): "outils",
    ("security", "lists"): "listes", ("security", "backup"): "sauvegarde",
    ("security", "general"): "outils", ("config", "commands"): "commandes",
    ("config", "channels"): "salons", ("config", "levels"): "niveaux",
    ("economy", "wallet"): "portefeuille", ("economy", "rewards"): "recompenses",
    ("economy", "shop"): "boutique", ("economy", "ranking"): "classement",
    ("economy", "admin"): "administration", ("economy", "general"): "outils",
    ("level", "profile"): "profil", ("level", "ranking"): "classement",
    ("level", "general"): "outils", ("game", "quick"): "rapides",
    ("game", "races"): "courses", ("game", "adventure"): "aventure", ("game", "general"): "autres",
    ("role", "manage"): "gestion", ("role", "panels"): "panneaux", ("role", "reactions"): "reactions",
    ("role", "general"): "autres", ("server", "build"): "creation", ("server", "channels"): "salons",
    ("server", "backup"): "sauvegarde", ("server", "manage"): "gestion", ("server", "general"): "autres",
}


def _name(command: commands.Command) -> str:
    return str(getattr(command, "qualified_name", "") or getattr(command, "name", "")).casefold().strip()


def _stable(track: dict) -> dict:
    return {
        "title": str(track.get("title") or "Titre inconnu")[:300],
        "webpage_url": str(track.get("webpage_url") or "")[:2000],
        "thumbnail": str(track.get("thumbnail") or "")[:2000],
        "duration": int(track.get("duration") or 0),
    }


async def _reply(cog, ctx, title: str, text: str, kind: str):
    from utils import sentrix_panels as panels
    embed = await cog._embed(ctx.guild.id, title=title, description=text, kind=kind)
    return await panels.envoyer(ctx, panels.depuis_embed(embed))


def _patch_playlists(bot: commands.Bot) -> None:
    save = bot.get_command("playlist-save")
    load = bot.get_command("playlist-load")
    if save is None or load is None or getattr(save, "_sentrix_v102", False):
        return

    async def save_fixed(self, ctx: commands.Context, *, nom: str):
        name = " ".join(str(nom or "").split()).strip()[:60]
        if not name:
            return await _reply(self, ctx, "Nom requis", "Choisissez un nom pour la playlist.", "danger")
        state = self.get_state(ctx.guild.id)
        source = ([state.current] if state.current else []) + list(state.queue)
        tracks = [_stable(t) for t in source if isinstance(t, dict)]
        tracks = [t for t in tracks if t["webpage_url"] or t["title"] != "Titre inconnu"]
        if not tracks:
            return await _reply(self, ctx, "Aucune musique", "Lancez au moins une musique avant de sauvegarder.", "danger")
        await bot.db.execute(
            "DELETE FROM playlists WHERE guild_id=? AND user_id=? AND LOWER(name)=LOWER(?)",
            (ctx.guild.id, ctx.author.id, name),
        )
        await bot.db.execute(
            "INSERT INTO playlists (guild_id,user_id,name,tracks) VALUES (?,?,?,?)",
            (ctx.guild.id, ctx.author.id, name, json.dumps(tracks, ensure_ascii=False)),
        )
        return await _reply(
            self, ctx, "Playlist sauvegardée",
            f"**{name}** contient **{len(tracks)} titre(s)**. Utilisez **playlist charger** pour la relancer.", "success",
        )

    async def load_fixed(self, ctx: commands.Context, *, nom: str):
        voice = getattr(ctx.author, "voice", None)
        if voice is None or getattr(voice, "channel", None) is None:
            return await _reply(self, ctx, "Salon vocal requis", "Rejoignez un salon vocal puis réessayez.", "danger")
        name = " ".join(str(nom or "").split()).strip()[:60]
        row = await bot.db.fetchone(
            "SELECT * FROM playlists WHERE guild_id=? AND user_id=? AND LOWER(name)=LOWER(?) ORDER BY id DESC LIMIT 1",
            (ctx.guild.id, ctx.author.id, name),
        )
        if not row:
            return await _reply(self, ctx, "Playlist introuvable", f"Aucune playlist **{name or 'sans nom'}** sur votre compte.", "danger")
        try:
            saved = json.loads(row["tracks"] or "[]")
        except (TypeError, ValueError):
            saved = []
        if not isinstance(saved, list) or not saved:
            return await _reply(self, ctx, "Playlist vide", "Cette playlist ne contient aucun titre exploitable.", "danger")

        sem = asyncio.Semaphore(3)
        async def resolve(item):
            if not isinstance(item, dict):
                return None
            query = str(item.get("webpage_url") or item.get("query") or item.get("title") or "").strip()
            if not query:
                return None
            async with sem:
                try:
                    return await self.ytdl_extract(query)
                except Exception:
                    return None

        resolved = await asyncio.gather(*(resolve(item) for item in saved[:40]))
        tracks = [t for t in resolved if isinstance(t, dict)]
        if not tracks:
            return await _reply(self, ctx, "Lecture impossible", "Aucun titre de la playlist n'a pu être retrouvé.", "danger")
        state = self.get_state(ctx.guild.id)
        channel = voice.channel
        if state.voice_client is None or not state.voice_client.is_connected():
            state.voice_client = await channel.connect()
        elif getattr(state.voice_client, "channel", None) != channel:
            await state.voice_client.move_to(channel)
        state.queue.extend(tracks)
        started = False
        if not state.current and not state.voice_client.is_playing() and not state.voice_client.is_paused():
            self.play_next(ctx.guild)
            started = True
        skipped = min(len(saved), 40) - len(tracks)
        text = f"**{len(tracks)} titre(s)** ajouté(s) depuis **{name}**."
        if started:
            text += "\nLa lecture a démarré automatiquement."
        if skipped:
            text += f"\n{skipped} titre(s) introuvable(s) ignoré(s)."
        return await _reply(self, ctx, "Playlist chargée", text, "success")

    save.callback = save_fixed
    load.callback = load_fixed
    save.description = "Sauvegarder la musique en cours et la file dans une playlist personnelle."
    load.description = "Charger votre playlist et démarrer la lecture dans votre salon vocal."
    save.help, load.help = save.description, load.description
    save._sentrix_v102 = load._sentrix_v102 = True


def _prepare(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_v102_prepared", False):
        return
    bot._sentrix_v102_prepared = True
    for name in MUSIC:
        command = bot.get_command(name)
        if command is not None:
            command.hidden = False
    for name in DUPLICATES:
        command = bot.get_command(name)
        if command is not None:
            command.hidden = True
    _patch_playlists(bot)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    old_should_expose = v95._should_expose
    old_group_for = v95._group_for
    old_bucket = v98.semantic_bucket
    old_surface = v95._add_grouped_surface  # V98 a déjà remplacé cette fonction.

    def should_expose(command: commands.Command) -> bool:
        simple = str(getattr(command, "name", "") or "").casefold()
        if getattr(command, "hidden", False) or _name(command) in DUPLICATES or simple in DUPLICATES:
            return False
        return bool(old_should_expose(command))

    def group_for(command: commands.Command):
        root, leaf = old_group_for(command)
        simple = str(getattr(command, "name", "") or "").casefold()
        if simple.startswith("playlist-"):
            root = "music"
        root = ROOTS.get(str(root).casefold(), str(root).casefold())
        leaf = LEAVES.get(_name(command), LEAVES.get(simple, leaf))
        return root, leaf

    def bucket(root_name: str, target: v95.SlashTarget) -> str:
        original_root = ROOT_BACK.get(str(root_name).casefold(), str(root_name).casefold())
        original_bucket = old_bucket(original_root, target)
        return BUCKETS.get((original_root, original_bucket), original_bucket)

    def leaf(_root: str, _bucket: str, target: v95.SlashTarget) -> str:
        return v95._safe_name(target.leaf_name)

    def chunks(bucket_name: str, count: int) -> list[str]:
        base = v95._safe_name(bucket_name)
        return [base] + [v95._safe_name(f"{base}-suite" if i == 2 else f"{base}-suite-{i}") for i in range(2, count + 1)]

    def surface(bot: commands.Bot):
        _prepare(bot)
        return old_surface(bot)

    v95._should_expose = should_expose
    v95._group_for = group_for
    v95._add_grouped_surface = surface
    v98.semantic_bucket = bucket
    v98.semantic_leaf = leaf
    v98._chunk_group_names = chunks
    v98.FORCED_SEMANTIC_ROOTS = frozenset({
        "tickets", "moderation", "securite", "configuration", "economie", "niveaux", "jeux", "roles", "serveur",
    })
    v95.GROUP_DESCRIPTIONS.update(ROOT_DESC)
    logger.warning("V102 actif : slash nettoyé/francisé, doublons masqués et playlists réparées.")


__all__ = ["install"]
