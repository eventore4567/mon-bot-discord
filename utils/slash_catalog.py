"""Catalogue des commandes slash publiques de SentriX — LA source unique.

Ce fichier décide de ce que Discord affiche quand un membre tape « / » : le nom
anglais de chaque commande, sa place dans l'arborescence et sa description. Rien
d'autre n'est publié. Une commande absente d'ici reste utilisable en préfixe (+)
mais n'apparaît pas dans le menu slash.

Ce que ce fichier NE fait PAS : il ne contient aucune logique métier ni aucune
permission. Chaque entrée pointe vers la commande existante (`source`) qui porte
déjà la logique, les contrôles d'accès (`utils.access_matrix`) et les options.
Le slash et le préfixe exécutent donc exactement le même code et prennent
exactement la même décision de permission.

Pourquoi un catalogue, et pas les couches précédentes
----------------------------------------------------
Avant lui, sept couches (v95, v98, canonical, v102, v105, v110, grouped-fix)
réécrivaient chacune la surface de la précédente. Mesuré sur le payload réel
envoyé à Discord le 07/10/2026 :

- 64 racines et 309 commandes, dont des sous-groupes numérotés
  (« /utility tools-2 translate ») ;
- des descriptions vides de sens (« Use bot leave », « Use off », « Use explain ») ;
- les outils du propriétaire du bot (/owner bot-leave, /owner set-bot) visibles
  par tous les membres ;
- des doublons (/sentrix et /ai ai, /info info et /serverinfo, /economy wallet
  et /balance…) et une commande de test (/levels community test-events).

Ces couches construisent encore une surface intermédiaire ; `publish()` la
remplace intégralement juste avant la synchronisation (voir
`sentrix_v95_runtime.sync_v95`). L'audit bloquant du registre
(`utils.command_registry_audit`) valide ensuite CETTE surface.

Visibilité : pourquoi aucune commande n'est masquée aux membres
--------------------------------------------------------------
Discord sait masquer une commande via `default_member_permissions`, mais SentriX
accorde aussi l'accès par des rôles configurés dans Setup > Permissions et par
le rôle staff (voir `access_matrix.evaluate`). Masquer /ban derrière « Bannir
des membres » le cacherait à un modérateur légitime qui n'a que le rôle SentriX.
La lisibilité vient donc de la structure et des descriptions, et l'exécution
reste contrôlée par la même décision que le préfixe.

Règles vérifiées par tests/test_slash_catalog.py
------------------------------------------------
- noms anglais, en minuscules, 32 caractères au plus ;
- au plus 25 entrées par groupe et 100 racines ;
- une source n'est publiée qu'une fois (pas de synonymes) ;
- aucune description vide, générique (« Use … ») ou en français ;
- aucun mot de développement (test, debug, probe…) dans un chemin.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("bot.slash-catalog")


@dataclass(frozen=True)
class SlashEntry:
    path: str          # « ban », « economy give », « games quick trivia »
    source: str        # nom qualifié de la commande existante qui porte la logique
    description: str   # phrase anglaise courte, affichée par Discord


def _e(path: str, source: str, description: str) -> SlashEntry:
    return SlashEntry(path, source, description)


#: Description de chaque racine (et sous-groupe) — affichée sous le nom du groupe.
GROUP_DESCRIPTIONS: dict[str, str] = {
    "moderation": "Moderation tools for your staff.",
    "security": "Protect the server against spam, raids and scams.",
    "logs": "Choose what SentriX records.",
    "tickets": "Support tickets.",
    "suggestions": "Share ideas with the server team.",
    "remind": "Personal reminders.",
    "economy": "Coins, rewards and transfers.",
    "shop": "Buy and sell with server coins.",
    "market": "Trade items with other members.",
    "levels": "Levels, XP and level rewards.",
    "rep": "Member reputation.",
    "profile": "Your SentriX profile and progress.",
    "user": "Information about a member.",
    "server": "Information and tools for this server.",
    "role": "Manage and inspect roles.",
    "verification": "Member verification.",
    "config": "Core SentriX settings.",
    "embeds": "Build and send custom embeds.",
    "giveaway": "Run giveaways.",
    "events": "Community events and tournaments.",
    "notifications": "Social media alerts.",
    "counter": "The infinite counting game.",
    "sticky": "Messages that stay at the bottom of a channel.",
    "schedule": "Messages SentriX sends later.",
    "starboard": "Showcase the most popular messages.",
    "voice": "Temporary voice channels.",
    "ai": "Ask SentriX AI.",
    "bot": "About SentriX.",
    "permissions": "Understand who can run what.",
    "translate": "Translate text.",
    "music": "Play music in voice channels.",
    "games": "Mini-games for your community.",
    "games activities": "Solo and group activities.",
    "games quests": "Timed adventures with rewards.",
    "games casino": "Casino games.",
    "games duels": "Challenge another member.",
    "games quick": "Quick games.",
    "games races": "First to answer wins.",
    "games stats": "Your game statistics.",
}


CATALOG: tuple[SlashEntry, ...] = (
    # ------------------------------------------------------------------ Démarrer
    _e("setup", "setup", "Configure SentriX for this server."),
    _e("help", "help", "Browse SentriX commands and how to use them."),
    _e("ping", "ping", "Check SentriX latency."),

    # ---------------------------------------------------------------- Modération
    # Les gestes quotidiens restent à la racine, comme sur la plupart des bots :
    # un modérateur tape /ban, pas /moderation ban.
    _e("ban", "ban", "Ban a member from the server."),
    _e("unban", "unban", "Unban a user by their ID."),
    _e("kick", "kick", "Kick a member from the server."),
    _e("timeout", "mute", "Time out a member."),
    _e("untimeout", "unmute", "Remove a member's timeout."),
    _e("warn", "warn", "Warn a member."),
    _e("clear", "clear", "Delete recent messages in this channel."),

    _e("moderation tempban", "tempban", "Ban a member for a set duration."),
    _e("moderation warnings", "warnings", "Show a member's warnings."),
    _e("moderation warnings-clear", "clearwarnings", "Delete all of a member's warnings."),
    _e("moderation case", "case", "Open a moderation case."),
    _e("moderation view", "modview", "Open a member's full moderation view."),
    _e("moderation center", "modcenter", "Open the moderation center."),
    _e("moderation history", "sentrixpro history", "Show a member's SentriX history."),
    _e("moderation lock", "lock", "Lock this channel."),
    _e("moderation unlock", "unlock", "Unlock this channel."),
    _e("moderation slowmode", "slowmode", "Set this channel's slowmode."),
    _e("moderation nick", "nickname", "Change a member's nickname."),
    _e("moderation nick-reset", "resetnick", "Reset a member's nickname."),
    _e("moderation snipe", "snipe", "Show the last deleted message."),
    _e("moderation editsnipe", "editsnipe", "Show the last edited message."),
    _e("moderation dm-status", "sanctiondm status", "Show the sanction DM settings."),
    _e("moderation dm-disable", "sanctiondm off", "Disable the DM for a sanction type."),
    _e("moderation dm-reset", "sanctiondm reset", "Restore the default sanction DM."),

    # ------------------------------------------------------------------ Sécurité
    _e("security antispam", "antispam", "Enable or disable anti-spam."),
    _e("security antilink", "antilink", "Enable or disable link blocking."),
    _e("security antiinvite", "antiinvite", "Enable or disable invite blocking."),
    _e("security antimention", "antimention", "Enable or disable mass mention protection."),
    _e("security anticaps", "anticaps", "Enable or disable the capital letters filter."),
    _e("security antiemoji", "antiemoji", "Enable or disable the emoji spam filter."),
    _e("security antiscam", "antiscam", "Enable or disable scam detection."),
    _e("security antiraid", "antiraid", "Enable or disable raid protection."),
    _e("security antibot", "antibot", "Enable or disable unauthorised bot blocking."),
    _e("security antiaccount", "antiaccount", "Enable or disable the new account filter."),
    _e("security antinuke", "antinuke", "Enable or disable anti-nuke protection."),
    _e("security aimod", "sentrixpro aimod", "Set up AI moderation."),
    _e("security quarantine", "sentrixpro quarantine-setup", "Quarantine very new accounts."),
    _e("security lockdown", "sentrixpro lockdown", "Lock or unlock the whole server."),
    _e("security panic", "panic", "Emergency lockdown with a restorable snapshot."),
    _e("security panic-off", "panic off", "End the emergency lockdown."),
    _e("security panic-status", "panic status", "Show the emergency lockdown status."),
    _e("security score", "sentrixpro security", "Show the server security score."),
    _e("security blacklist-sync", "syncbl", "Ban every member on the SentriX blacklist."),

    # ---------------------------------------------------------------------- Logs
    _e("logs enable", "logevent on", "Enable a log event."),
    _e("logs disable", "logevent off", "Disable a log event."),
    _e("logs search", "logsearch", "Search a member's recorded history."),
    _e("logs digest", "sentrixpro digest", "Send a daily activity summary to staff."),

    # ------------------------------------------------------------------- Tickets
    _e("tickets open", "ticket", "Open a support ticket."),
    _e("tickets summary", "sentrixpro ticket-summary", "Summarise a ticket."),

    # ----------------------------------------------------------------- Communauté
    _e("suggestions submit", "suggest", "Submit a suggestion."),
    _e("suggestions setup", "suggestion-setup", "Choose the suggestion channel and settings."),
    _e("suggestions panel", "suggestion-panel", "Post the suggestion box in a channel."),
    _e("suggestions status", "suggestion-status", "Change a suggestion's status."),
    _e("poll", "poll", "Create a poll."),
    _e("translate text", "translate", "Translate a text into another language."),
    _e("afk", "afk", "Set yourself as away."),
    _e("weather", "weather", "Show the weather for a city."),
    _e("remind set", "remind", "Set a personal reminder."),
    _e("remind list", "reminder-list", "List your reminders."),
    _e("remind cancel", "reminder-cancel", "Cancel a reminder."),

    # ------------------------------------------------------------------- Économie
    _e("economy balance", "balance", "Show your balance or a member's."),
    _e("economy daily", "daily", "Claim your daily reward."),
    _e("economy weekly", "weekly", "Claim your weekly reward."),
    _e("economy checkin", "checkin", "Claim your daily check-in reward."),
    _e("economy work", "work", "Work to earn coins."),
    _e("economy rob", "rob", "Try to rob another member."),
    _e("economy pay", "pay", "Send coins to another member."),
    _e("economy deposit", "deposit", "Deposit coins in the bank."),
    _e("economy withdraw", "withdraw", "Withdraw coins from the bank."),
    _e("economy gamble", "gamble", "Bet coins: double or nothing."),
    _e("economy leaderboard", "economyleaderboard", "Show the richest members."),
    _e("economy inventory", "inventory", "Show your inventory."),
    _e("economy give", "give-money", "Give coins to a member."),
    _e("economy reset", "reset-economy", "Reset the whole server economy."),
    _e("economy toggle", "economy-system", "Enable or disable the economy."),

    _e("shop view", "shop", "Browse the server shop."),
    _e("shop buy", "buy", "Buy an item from the shop."),
    _e("shop sell", "sell", "Sell an item from your inventory."),
    _e("shop panel", "shoppanel", "Post the shop panel in a channel."),
    _e("shop roles", "shoprole", "Set up the roles for sale."),
    _e("shop role-add", "shoprole add", "Put a role up for sale."),
    _e("shop role-remove", "shoprole remove", "Take a role off sale."),
    _e("shop role-price", "shoprole price", "Change the price of a role."),
    _e("shop role-list", "shoprole list", "List the roles for sale."),

    _e("market view", "market", "Browse the member market."),
    _e("market buy", "market-buy", "Buy a market listing."),
    _e("market sell", "market-sell", "List an item for sale."),
    _e("market find", "market-find", "Search the market."),
    _e("market cancel", "market-cancel", "Cancel one of your listings."),
    _e("market mine", "market-my", "Show your active listings."),
    _e("market history", "market-history", "Show your market history."),

    # ------------------------------------------------------------------- Niveaux
    _e("levels rank", "level", "Show your level or a member's."),
    _e("levels leaderboard", "leaderboard-levels", "Show the level leaderboard."),
    _e("levels xp-set", "set-xp", "Set a member's XP."),
    _e("levels xp-add", "add-xp", "Give XP to a member."),
    _e("levels reset", "reset-levels", "Reset every level on the server."),
    _e("levels toggle", "level-system", "Enable or disable levels."),
    _e("levels role-add", "set-level-role", "Reward a level with a role."),
    _e("levels role-remove", "remove-level-role", "Remove a level reward."),
    _e("levels activity-role", "sentrixpro autorole", "Give a role from an activity threshold."),

    _e("rep give", "rep", "Give a reputation point to a member."),
    _e("rep view", "reputation", "Show a member's reputation."),
    _e("rep leaderboard", "repleaderboard", "Show the reputation leaderboard."),
    _e("rep history", "rephistory", "Show a member's reputation history."),

    _e("profile view", "stats", "Show a member's full profile."),
    _e("profile card", "profilecard", "Show your profile card."),
    _e("profile bio", "set-bio", "Set your profile bio."),
    _e("profile voice", "voice-time", "Show time spent in voice channels."),
    _e("profile badges", "sentrixpro badges", "Show unlocked badges."),
    _e("profile achievements", "achievements-v21", "Show your achievements."),
    _e("profile challenges", "challenges", "Show your active challenges."),
    _e("profile progress", "progress", "Show your overall progress."),
    _e("profile season", "sentrixpro season", "Show your season progress."),
    _e("profile trust", "sentrixpro trust", "Show a member's trust score."),

    # --------------------------------------------------------------- Informations
    _e("user info", "userinfo", "Show information about a member."),
    _e("user avatar", "avatar", "Show a member's avatar."),
    _e("user invites", "invites", "Show a member's invites."),
    _e("user invited-by", "invited-by", "Show who invited a member."),

    _e("server info", "serverinfo", "Show information about this server."),
    _e("server members", "membercount", "Show the member count."),
    _e("server channel", "channelinfo", "Show information about a channel."),
    _e("server emojis", "emoji-list", "List the server's emojis."),
    _e("server emoji-add", "addemoji", "Add an emoji to the server."),
    _e("server emoji-remove", "deleteemoji", "Delete a server emoji."),
    _e("server growth", "server-growth", "Show member growth."),
    _e("server invites", "invite-leaderboard", "Show the invite leaderboard."),
    _e("server live", "sentrixpro live", "Show live server activity."),
    _e("server goal", "sentrixpro goal", "Create, list or delete a server goal."),
    _e("server health", "server-health", "Check channels, roles and permissions."),
    _e("server audit", "server-audit", "Audit the server structure."),

    _e("role give", "giverole", "Give a role to a member."),
    _e("role remove", "removerole", "Remove a role from a member."),
    _e("role info", "info role", "Show information about a role."),
    _e("role mass", "massrole", "Add or remove a role for every member."),
    _e("role menu", "rolepanel dropdown", "Post a self-role dropdown menu."),
    _e("role reactions", "rolepanel reaction", "Post a self-role reaction panel."),

    # -------------------------------------------------------------- Vérification
    _e("verification captcha", "verification", "Set up rules, CAPTCHA and the verified role."),
    _e("verification setup", "proofsetup", "Set up proof verification."),
    _e("verification panel", "proofpanel", "Post the verification panel."),
    _e("verification instructions", "proof", "Show how to get verified."),
    _e("verification status", "proofstatus", "Show your latest verification."),
    _e("verification reset", "proofreset", "Reset a member's verification."),
    _e("verification example-add", "proofexample", "Add an example screenshot."),
    _e("verification example-remove", "proofexample-remove", "Remove an example screenshot."),
    _e("verification examples", "proofexamples", "List the example screenshots."),

    _e("config mod-role", "setmodrole", "Set the staff role."),
    _e("config prefix", "setprefix", "Change the text command prefix."),
    _e("config history", "config-history", "See recent setting changes and undo them."),

    # -------------------------------------------------------------------- Embeds
    _e("embeds create", "embed create", "Create a new embed template."),
    _e("embeds list", "embed list", "List saved embed templates."),
    _e("embeds edit", "embed edit", "Edit an embed template."),
    _e("embeds preview", "embed preview", "Preview an embed template privately."),
    _e("embeds send", "embed send", "Send an embed template to a channel."),
    _e("embeds delete", "embed delete", "Delete an embed template."),
    _e("embeds duplicate", "embed duplicate", "Duplicate an embed template."),
    _e("embeds rename", "embed rename", "Rename an embed template."),
    _e("embeds export", "embed export", "Export an embed template as JSON."),
    _e("embeds import", "embed import", "Import an embed template from JSON."),
    _e("embeds message", "embed message", "Edit a message already sent by SentriX."),
    _e("embeds allow-role", "embedconfig addrole", "Allow a role to build embeds."),
    _e("embeds deny-role", "embedconfig removerole", "Stop a role from building embeds."),
    _e("embeds allowed-roles", "embedconfig list", "List the roles allowed to build embeds."),

    # ---------------------------------------------------------------- Événements
    _e("giveaway create", "giveaway create", "Create a giveaway."),
    _e("giveaway end", "giveaway end", "End a giveaway now and draw winners."),
    _e("giveaway reroll", "giveaway reroll", "Draw new winners."),
    _e("giveaway cancel", "giveaway cancel", "Cancel a giveaway without winners."),
    _e("giveaway list", "giveaway list", "List the running giveaways."),
    _e("giveaway panel", "giveaway", "Open the giveaway center."),
    _e("giveaway blacklist", "giveaway blacklist", "Exclude a member from giveaways."),
    _e("giveaway unblacklist", "giveaway unblacklist", "Allow a member back into giveaways."),

    _e("events list", "event-list", "List upcoming events."),
    _e("events join", "event-join", "Join an event."),
    _e("events leave", "event-leave", "Leave an event."),
    _e("events tournaments", "tournament-list", "List running tournaments."),
    _e("events tournament-join", "tournament-join", "Join a tournament."),

    _e("notifications add", "notifs-ping", "Get alerts for a social media channel."),
    _e("notifications list", "notifs-list", "List the watched social media channels."),
    _e("notifications remove", "notifs-remove", "Stop watching a social media channel."),

    _e("counter status", "infinit status", "Show the counting game status."),
    _e("counter stop", "infinit stop", "Pause the counting game."),
    _e("counter resume", "infinit resume", "Resume the counting game."),

    _e("logs trace", "trace", "Find a staff action by its reference."),

    # Fonctions de cogs/sentrix_plus.py : elles existaient, mais seulement en +,
    # et masquées de l'aide par apply_surface faute de classement (08/10/2026).
    _e("sticky set", "sticky-set", "Keep a message at the bottom of a channel."),
    _e("sticky frequency", "sticky-every", "Repost the sticky message every N messages."),
    _e("sticky off", "sticky-off", "Remove the sticky message from a channel."),

    _e("schedule send", "schedule-send", "Send a message later in a channel."),
    _e("schedule list", "schedule-list", "List the scheduled messages."),
    _e("schedule cancel", "schedule-cancel", "Cancel a scheduled message."),

    _e("starboard setup", "starboard-setup", "Repost popular messages to a showcase channel."),
    _e("starboard off", "starboard-off", "Turn the starboard off."),

    _e("voice setup", "voicehub-setup", "Create the join-to-create voice channel."),
    _e("voice off", "voicehub-off", "Turn temporary voice channels off."),
    _e("voice rename", "voice-name", "Rename your temporary voice channel."),
    _e("voice limit", "voice-limit", "Set how many members can join your voice channel."),
    _e("voice lock", "voice-lock", "Stop new members from joining your voice channel."),
    _e("voice unlock", "voice-unlock", "Let members join your voice channel again."),
    _e("voice transfer", "voice-transfer", "Give your voice channel to another member."),

    # ------------------------------------------------------------------------ IA
    _e("ai ask", "ai", "Ask SentriX AI a question."),
    _e("ai search", "ai search", "Ask with a live web search."),
    _e("ai image", "image", "Generate an image from a description."),
    _e("ai image-prompt", "image-prompt", "Get a detailed image prompt idea."),
    _e("ai code", "code", "Ask AI to write code."),
    _e("ai explain", "explain", "Explain a concept simply."),
    _e("ai correct", "correct", "Fix spelling and grammar in a text."),
    _e("ai improve", "improve", "Improve a text."),
    _e("ai summarize", "summarize", "Summarize a text."),
    _e("ai fact-check", "fact-check", "Check a claim."),
    _e("ai memory", "ai memory", "Check the AI conversation in this channel."),
    _e("ai reset", "ai reset", "Reset your AI conversation in this channel."),
    _e("ai model", "ai model", "Show the AI model used on this server."),
    _e("ai enable", "ai enable", "Enable AI on this server."),
    _e("ai disable", "ai disable", "Disable AI on this server."),

    # ----------------------------------------------------------------- À propos
    _e("bot info", "botinfo", "About SentriX."),
    _e("bot changelog", "changelog", "Show the latest SentriX updates."),
    _e("bot feedback", "feedback", "Send feedback to the SentriX team."),
    _e("bot bug", "report-bug", "Report a bug to the SentriX team."),

    _e("permissions explain", "permissions explain", "Explain why a command is allowed or denied."),
    _e("permissions list", "permissions liste", "List every command and who can run it."),

    # -------------------------------------------------------------------- Musique
    _e("music play", "music play", "Play a song or a link."),
    _e("music pause", "music pause", "Pause the music."),
    _e("music resume", "music resume", "Resume the music."),
    _e("music skip", "music skip", "Skip to the next song."),
    _e("music previous", "music previous", "Go back to the previous song."),
    _e("music stop", "music stop", "Stop the music and clear the queue."),
    _e("music queue", "music queue", "Show the queue."),
    _e("music clear", "music clear", "Clear the queue without stopping the song."),
    _e("music remove", "music remove", "Remove a song from the queue."),
    _e("music shuffle", "music shuffle", "Shuffle the queue."),
    _e("music loop", "music loop", "Repeat the song, the queue, or nothing."),
    _e("music seek", "music seek", "Jump to a position in the song."),
    _e("music volume", "music volume", "Set the volume from 0 to 100."),
    _e("music autoplay", "music autoplay", "Keep playing when the queue ends."),
    _e("music now-playing", "music nowplaying", "Show the current song."),
    _e("music join", "music join", "Make SentriX join your voice channel."),
    _e("music leave", "music leave", "Make SentriX leave the voice channel."),

    # ------------------------------------------------------------------ Mini-jeux
    _e("games activities archery", "archery", "Shoot when the target is centred."),
    _e("games activities bomb", "bomb", "Open safe tiles and cash out before a bomb."),
    _e("games activities collection", "collec", "Show your collection from solo games."),
    _e("games activities crown", "crown", "King of the hill: keep the crown."),
    _e("games activities detective", "detective", "Group investigation: find the culprit."),
    _e("games activities dragon", "dragon", "Fight a dragon turn by turn."),
    _e("games activities ghost", "ghost", "Find the door hiding the ghost."),
    _e("games activities ice", "ice", "Slide the penguin onto the hole."),
    _e("games activities lava", "lava", "Climb floors and cash out before the lava."),
    _e("games activities minesweeper", "minesweeper", "Play minesweeper."),
    _e("games activities potion", "potion", "Gather ingredients and brew potions."),
    _e("games activities rocket", "rocket", "Cash out before the rocket explodes."),
    _e("games activities safe", "safe", "Crack the safe code with clues."),
    _e("games activities sequence", "sequence", "Find the missing symbol."),
    _e("games activities target", "target", "Click the right colour as fast as you can."),
    _e("games activities community-trivia", "triviastart", "Start a community trivia question."),
    _e("games activities zombie", "zombie", "Survive six zombie waves."),

    _e("games quests adventure", "adventure", "Go on an adventure for a reward."),
    _e("games quests dungeon", "dungeon", "Explore a dungeon for a reward."),
    _e("games quests explore", "explore", "Explore the area for a reward."),
    _e("games quests fishing", "fishing", "Go fishing for a reward."),
    _e("games quests hunt", "hunt", "Go hunting for a reward."),
    _e("games quests mining", "mining", "Go mining for a reward."),
    _e("games quests treasure", "treasure", "Search for treasure."),

    _e("games casino blackjack", "blackjack", "Play blackjack against the dealer."),
    _e("games casino coinflip", "coinflip", "Heads or tails, with or without a bet."),
    _e("games casino dice", "dice", "Bet on a six-sided die."),
    _e("games casino highlow", "highlow", "Guess if the next card is higher or lower."),
    _e("games casino luckyroll", "luckyroll", "Roll two dice: a double wins a bonus."),
    _e("games casino slots", "slots", "Play the slot machine."),

    _e("games duels connect4", "connect4", "Play Connect 4 against a member."),
    _e("games duels rps", "duel", "Challenge a member to rock paper scissors."),
    _e("games duels number", "numberduel", "Closest secret number wins."),
    _e("games duels quiz", "quizduel", "Fastest correct answer wins."),
    _e("games duels reaction", "reactionduel", "First to click wins."),
    _e("games duels tictactoe", "tictactoe", "Play tic-tac-toe against a member."),

    _e("games quick colorquiz", "colorquiz", "Click the right colour."),
    _e("games quick emojiquiz", "emojiquiz", "Guess the word behind the emojis."),
    _e("games quick guess", "guess-number", "Guess a number from 1 to 100 as a group."),
    _e("games quick hangman", "hangman", "Play hangman."),
    _e("games quick math", "math-quiz", "Solve a quick maths question."),
    _e("games quick memory", "memory", "Memorise a sequence of emojis."),
    _e("games quick reaction", "reaction", "Click the button as soon as it appears."),
    _e("games quick rps", "rps", "Play rock paper scissors against SentriX."),
    _e("games quick scramble", "scramble", "Unscramble a word."),
    _e("games quick trivia", "trivia", "Answer a general knowledge question."),
    _e("games quick wordgame", "wordgame", "Guess the word from its definition."),
    _e("games quick choose", "choose", "Let SentriX pick between options."),
    _e("games quick roll", "roll", "Roll a die."),

    _e("games races emoji", "emoji-race", "First to click the right emoji wins."),
    _e("games races typing", "fasttype", "Retype the sentence as fast as you can."),
    _e("games races guess", "guessrace", "First to guess the secret number wins."),
    _e("games races last-message", "lastmessage", "Last message in the channel wins."),
    _e("games races math", "mathrace", "Mental maths race."),
    _e("games races race", "race", "Multiplayer race: play it safe or sprint."),
    _e("games races reaction", "reactionevent", "First click wins."),
    _e("games races word", "wordrace", "First to unscramble the word wins."),

    _e("games stats today", "dailygames", "Your games today and active cooldowns."),
    _e("games stats history", "gamehistory", "Your latest game rounds."),
    _e("games stats leaderboard", "gametop", "Top players by game winnings."),
    _e("games stats profile", "gameprofile", "A member's full game profile."),
    _e("games stats details", "gamestats", "A member's detailed game statistics."),
)


#: Commandes qui existaient en slash et n'y sont plus publiées, avec la raison.
#: Elles restent utilisables en préfixe : seule la surface « / » change.
RETIRED: dict[str, str] = {
    # Outils du propriétaire de SentriX : rien à faire dans le menu des membres.
    "bot-leave": "owner tool",
    "bot-servers": "owner tool",
    "footer": "owner tool",
    "set-bot": "owner tool",
    "setstatus": "owner tool",
    "status-rotate": "owner tool",
    "theme": "owner tool",
    # Développement, test ou diagnostic interne.
    "test-events": "test command",
    "systemstatus": "internal diagnostic, same as /server health",
    "sentrixpro status": "internal diagnostic, same as /server health",
    "server-managed": "internal maintenance switch",
    # Doublons : une seule entrée par fonction.
    "sentrix": "duplicate of /ai ask",
    "ai help": "covered by /help",
    "ai-translate": "duplicate of /translate text",
    "antilink-strict": "alias of /security antilink",
    "info": "duplicate of /server info and /role info",
    "info serveur": "duplicate of /server info",
    "banque": "duplicate of /economy balance and /economy deposit",
    "economy": "duplicate of /economy balance",
    "roleall": "covered by /role mass",
    "permissions": "covered by /permissions explain",
    "logevent": "covered by /logs enable and /logs disable",
    "sentrixpro": "index of tools now published directly",
    "sentrixpro help": "covered by /help",
    "sentrixpro profile": "duplicate of /profile view",
    "sentrixpro module": "module switches live in /setup",
    "sentrixpro modules": "module switches live in /setup",
    "sentrixpro notifications": "status view covered by /setup",
    "sentrixpro welcome": "welcome lives in /setup",
}


# --------------------------------------------------------------------------
# Options : nom affiché et description en anglais
# --------------------------------------------------------------------------
# Les options héritent des paramètres Python des commandes préfixe, donc de noms
# français (« membre » ×43, « raison », « duree »…) et de descriptions souvent
# génériques (« Valeur à fournir pour « commande » »). Mesuré le 07/10/2026 :
# 207 descriptions françaises sur 214 options.
#
# Seul l'AFFICHAGE change : discord.py rattache la valeur reçue au paramètre
# Python d'origine, donc le code métier reçoit toujours `membre=`.
# Les VALEURS attendues ne changent pas non plus : quand une commande attend
# « pile » ou « face », la description le dit.

OPTION_NAMES: dict[str, str] = {
    "adversaire": "opponent",
    "affirmation": "claim",
    "ancien_nom": "current_name",
    "choix": "choice",
    "commande": "command",
    "cote": "side",
    "demande": "request",
    "difficulte": "difficulty",
    "duree": "duration",
    "etat": "state",
    "evenement": "event",
    "fichier": "file",
    "filtre": "filter",
    "identifiant": "id",
    "ident": "id",
    "langue": "language",
    "lien": "link",
    "longueur": "length",
    "membre": "member",
    "mise": "bet",
    "montant": "amount",
    "niveau": "level",
    "nom": "name",
    "nombre": "count",
    "nouveau_nom": "new_name",
    "numero": "number",
    "objet": "item",
    "pari": "guess",
    "prefixe": "prefix",
    "pseudo": "nickname",
    "raison": "reason",
    "recherche": "query",
    "retirer_role": "remove_role",
    "salon": "channel",
    "secondes": "seconds",
    "sujet": "subject",
    "texte": "text",
    "ville": "city",
}

#: Description par défaut, selon le nom anglais de l'option.
OPTION_DESCRIPTIONS: dict[str, str] = {
    "action": "What to do.",
    "anonymous": "Hide who posted each suggestion.",
    "delay": "When to send it, e.g. 10m, 2h, 1d.",
    "every": "Repost after this many messages.",
    "limit": "Maximum members, from 0 (no limit) to 99.",
    "message": "The message.",
    "cooldown": "Minutes to wait between two uses.",
    "response": "Public answer shown on the suggestion.",
    "source": "Source language, auto-detected if empty.",
    "status": "pending, planned, accepted, implemented or rejected.",
    "threads": "Open a discussion thread on each one.",
    "amount": "Amount of coins, or 'all'.",
    "bet": "Coins to bet.",
    "channel": "The channel.",
    "choice": "Your move.",
    "city": "City name.",
    "claim": "The claim to check.",
    "command": "A command to look up.",
    "configuration": "Panel configuration.",
    "count": "How many.",
    "current_name": "The template's current name.",
    "description": "Description.",
    "difficulty": "facile, normal or difficile.",
    "duration": "Duration, e.g. 10m, 1h, 2d.",
    "emoji": "The emoji.",
    "event": "The log event.",
    "file": "The JSON file exported by /embeds export.",
    "filter": "Only show commands containing this text.",
    "guess": "plus_haut or plus_bas (optional).",
    "id": "The ID.",
    "image": "Example screenshot.",
    "item": "The item.",
    "language": "Target language code, e.g. en, es, de.",
    "length": "Number of symbols, from 3 to 6.",
    "level": "The level.",
    "link": "Link to the message.",
    "listing_id": "Listing ID.",
    "max": "Highest value, 100 by default.",
    "member": "The member.",
    "message_id": "Message ID.",
    "metric": "Activity to measure.",
    "min_account_hours": "Minimum account age in hours.",
    "mode": "Mode.",
    "name": "Name.",
    "new_name": "New name.",
    "nickname": "The new nickname.",
    "number": "Case number (optional).",
    "opponent": "Opponent, random if empty.",
    "options": "Options separated by commas.",
    "position": "Position in the queue.",
    "prefix": "New prefix, e.g. !, ? or +.",
    "price": "Price in coins.",
    "quantity": "Quantity.",
    "query": "What to search for.",
    "question": "The question.",
    "reason": "The reason.",
    "reference_id": "Example ID.",
    "remove_role": "Also remove the role they received.",
    "request": "What the code should do.",
    "reward_money": "Coin reward.",
    "reward_role": "Role reward.",
    "role": "The role.",
    "roles": "The roles.",
    "seconds": "Position in seconds.",
    "side": "pile (heads) or face (tails).",
    "state": "Enable or disable.",
    "subject": "The subject.",
    "target": "Where to send it.",
    "text": "The text.",
    "threshold": "Threshold.",
    "ticket_id": "Ticket number.",
    "unit_price": "Price per item.",
    "url": "Full link starting with https://.",
    "user_id": "The user's Discord ID.",
    "xp": "Amount of XP.",
}

#: Description précise quand le contexte compte : un modérateur qui tape /ban doit
#: savoir exactement ce que chaque option fait.
OPTION_OVERRIDES: dict[tuple[str, str], str] = {
    ("ban", "member"): "The member to ban.",
    ("ban", "reason"): "Why they are banned. Shown in the logs.",
    ("unban", "reason"): "Why they are unbanned. Shown in the logs.",
    ("kick", "member"): "The member to kick.",
    ("kick", "reason"): "Why they are kicked. Shown in the logs.",
    ("timeout", "member"): "The member to time out.",
    ("timeout", "duration"): "How long, e.g. 10m, 1h, 1d.",
    ("timeout", "reason"): "Why they are timed out. Shown in the logs.",
    ("untimeout", "member"): "The member whose timeout ends.",
    ("warn", "member"): "The member to warn.",
    ("warn", "reason"): "Why they are warned. Shown in the logs.",
    ("clear", "count"): "Number of messages to delete, from 2 to 100.",
    ("moderation tempban", "member"): "The member to ban.",
    ("moderation tempban", "duration"): "How long, e.g. 1h, 2d.",
    ("moderation warnings", "member"): "Whose warnings to show.",
    ("moderation warnings-clear", "member"): "Whose warnings to delete.",
    ("moderation nick", "member"): "Whose nickname to change.",
    ("moderation dm-disable", "action"): "Sanction type: ban, kick, mute or warn.",
    ("moderation dm-reset", "action"): "Sanction type: ban, kick, mute or warn.",
    ("economy pay", "member"): "Who receives the coins.",
    ("economy give", "member"): "Who receives the coins.",
    ("economy rob", "member"): "Who to rob.",
    ("suggestions setup", "channel"): "Channel where suggestions are posted.",
    ("suggestions setup", "cooldown"): "Minutes between two suggestions from one member.",
    ("suggestions panel", "channel"): "Where to post the box. This channel if empty.",
    ("suggestions status", "number"): "Suggestion number, e.g. 12.",
    ("translate text", "text"): "The text to translate.",
    ("translate text", "language"): "Target language, e.g. en, es, de.",
    ("remind cancel", "id"): "Reminder ID, from /remind list.",
    ("logs trace", "reference"): "The reference shown on the response, e.g. SX-7K4QF2M.",
    ("schedule cancel", "id"): "Message ID, from /schedule list.",
    ("starboard setup", "threshold"): "Reactions needed, from 2 to 25.",
    ("starboard setup", "channel"): "Where popular messages are reposted.",
    ("voice transfer", "member"): "The new owner of your voice channel.",
    ("notifications remove", "id"): "Alert ID, from /notifications list.",
    ("help", "command"): "A command to look up, e.g. ban.",
    ("games activities dragon", "opponent"): "dragonnet, feu, glace or ombre. Random if empty.",
    ("games quick rps", "choice"): "pierre, feuille or ciseaux.",
}


def _english_options(command: Any, path: str) -> None:
    """Renomme l'affichage des options et leur donne une description anglaise.

    Les paramètres sont REMPLACÉS par des copies : la commande intermédiaire
    réutilisée partage ses objets paramètres, on ne la modifie jamais.
    """
    import dataclasses

    params = getattr(command, "_params", None)
    if not params:
        return
    renamed: dict[str, Any] = {}
    used: set[str] = set()
    for python_name, param in params.items():
        shown = param.display_name
        english = OPTION_NAMES.get(shown, shown)
        if english in used:
            # Deux options ne peuvent pas porter le même nom : on garde l'original
            # plutôt que de publier une commande que Discord refuserait.
            logger.warning("Option « %s » de /%s non renommée : collision.", shown, path)
            english = shown
        used.add(english)
        description = OPTION_OVERRIDES.get((path, english)) or OPTION_DESCRIPTIONS.get(english)
        changes: dict[str, Any] = {}
        if english != shown:
            changes["_rename"] = english
        if description:
            changes["description"] = description
        renamed[python_name] = dataclasses.replace(param, **changes) if changes else param
    command._params = renamed


# --------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------

def entries_by_root() -> dict[str, list[SlashEntry]]:
    roots: dict[str, list[SlashEntry]] = {}
    for entry in CATALOG:
        roots.setdefault(entry.path.split()[0], []).append(entry)
    return roots


def direct_roots() -> dict[str, str]:
    """Commande source -> racine directe. Vue compatible avec l'ancienne V110."""
    return {e.source: e.path for e in CATALOG if " " not in e.path}


#: Commandes dont la version slash doit répondre AVANT tout `defer` — un modal
#: ne peut s'ouvrir que sur une interaction encore vierge, or la couche v95
#: diffère systématiquement avant d'exécuter la commande préfixe. Le cog
#: concerné fournit ici une fabrique de commande slash native.
_NATIVE: dict[str, Any] = {}


def register_native(source: str, factory: Any) -> None:
    """Déclare qu'une source a une implémentation slash native.

    `factory(bot)` rend une `app_commands.Command` dont le callback porte
    `_sentrix_original_command = source` : l'aide, l'audit du registre et les
    outils de mesure la rattachent ainsi à la bonne commande. La décision de
    permission reste celle de `access_matrix.evaluate`, que le callback DOIT
    appeler avant d'agir.
    """
    _NATIVE[str(source)] = factory


def _source_index(tree: Any) -> dict[str, Any]:
    """Commande slash déjà construite par les couches précédentes, par source.

    On la réutilise plutôt que d'en fabriquer une : elle porte déjà sa signature
    native (v105), ses autocomplétions et ses gardes.
    """
    from discord import app_commands

    index: dict[str, Any] = {}
    for command in tree.walk_commands():
        if not isinstance(command, app_commands.Command):
            continue
        source = getattr(command.callback, "_sentrix_original_command", None)
        if source and source not in index:
            index[str(source)] = command
    return index


def _find_prefix(bot: Any, source: str) -> Any:
    command = bot.get_command(source)
    if command is not None:
        return command
    for candidate in bot.walk_commands():
        if str(getattr(candidate, "qualified_name", "")).casefold() == source.casefold():
            return candidate
    return None


def _build_leaf(bot: Any, entry: SlashEntry, existing: dict[str, Any]) -> Any | None:
    from discord import app_commands
    from discord.app_commands import locale_str

    name = entry.path.split()[-1]
    factory = _NATIVE.get(entry.source)
    if factory is not None:
        native = factory(bot)
        native.name = name
        native.description = entry.description
        native._locale_name = locale_str(name)
        native._locale_description = locale_str(entry.description)
        return native

    current = existing.get(entry.source)
    if current is not None:
        binding = getattr(current, "binding", None)
        # set_on_binding=False : ne jamais réécrire l'attribut du cog d'origine.
        copy = current._copy_with(
            parent=None,
            binding=binding,
            bindings={binding: binding} if binding is not None else {},
            set_on_binding=False,
        )
        copy.name = name
        copy.description = entry.description
        copy._locale_name = locale_str(name)
        copy._locale_description = locale_str(entry.description)
        return copy

    command = _find_prefix(bot, entry.source)
    if command is None:
        return None
    import sentrix_v95_runtime as v95

    callback, _native = v95._make_callback(bot, command)
    return app_commands.Command(name=name, description=entry.description, callback=callback)


def publish(bot: Any) -> dict[str, Any]:
    """Remplace toute la surface slash globale par le catalogue.

    Appelée par `sync_v95` juste avant l'audit bloquant et la synchronisation.
    Une source introuvable ou masquée est ignorée et journalisée — jamais
    publiée à moitié : l'audit refuserait de publier une commande cachée.
    """
    import discord
    from discord import app_commands

    tree = bot.tree
    existing = _source_index(tree)
    roots: dict[str, Any] = {}
    subgroups: dict[str, Any] = {}
    missing: list[str] = []
    hidden: list[str] = []

    def group(path: str) -> Any:
        parts = path.split()
        key = " ".join(parts)
        cache = roots if len(parts) == 1 else subgroups
        if key in cache:
            return cache[key]
        parent = None if len(parts) == 1 else group(" ".join(parts[:-1]))
        built = app_commands.Group(
            name=parts[-1],
            description=GROUP_DESCRIPTIONS.get(key, f"{parts[-1].title()} commands."),
            parent=parent,
        )
        # Group(parent=...) s'inscrit LUI-MÊME chez son parent : l'ajouter une
        # seconde fois lève CommandAlreadyRegistered (constaté au boot).
        cache[key] = built
        return built

    for entry in CATALOG:
        prefix = _find_prefix(bot, entry.source)
        if prefix is not None and getattr(prefix, "hidden", False):
            hidden.append(entry.source)
            continue
        leaf = _build_leaf(bot, entry, existing)
        if leaf is None:
            missing.append(entry.source)
            continue
        _english_options(leaf, entry.path)
        parts = entry.path.split()
        if len(parts) == 1:
            roots[parts[0]] = leaf
        else:
            group(" ".join(parts[:-1])).add_command(leaf)

    chat_input = discord.AppCommandType.chat_input
    for command in list(tree.get_commands(guild=None, type=chat_input)):
        tree.remove_command(command.name, type=chat_input)
    for name, command in roots.items():
        tree.add_command(command, override=True)

    leaves = sum(1 for c in tree.walk_commands() if isinstance(c, app_commands.Command))
    published = {c.name for c in tree.get_commands(guild=None, type=chat_input)}
    report = {
        "roots": len(published),
        "leaves": leaves,
        "missing": missing,
        "hidden": hidden,
        # Racine construite mais absente de l'arbre après ajout : ne doit jamais
        # arriver, et serait sinon invisible (cas /profile, 07/10/2026).
        "lost_roots": sorted(set(roots) - published),
    }
    bot._sentrix_slash_catalog_report = report
    if missing or hidden or report["lost_roots"]:
        logger.warning(
            "Catalogue slash : %s source(s) introuvable(s) %s, %s masquée(s) %s, racines perdues %s.",
            len(missing), missing[:10], len(hidden), hidden[:10], report["lost_roots"],
        )
    logger.info("Catalogue slash publié : %s racines, %s commandes.", len(roots), leaves)
    return report


__all__ = [
    "CATALOG", "GROUP_DESCRIPTIONS", "OPTION_DESCRIPTIONS", "OPTION_NAMES",
    "OPTION_OVERRIDES", "RETIRED", "SlashEntry",
    "direct_roots", "entries_by_root", "publish", "register_native",
]
