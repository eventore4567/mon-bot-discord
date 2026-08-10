#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GAME_PUBLIC = (
    '    "coinflip", "dice", "luckyroll", "highlow", "memory", "reaction",\n'
    '    "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype", "duel",\n'
    '    "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",\n'
    '    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",\n'
    '    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure",\n'
    '    "hunt", "explore", "gamehistory", "gameprofile", "gamestats", "gametop",\n'
    '    "dailygames",\n'
)


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


main = ROOT / "main.py"
replace_exact(
    main,
    '    "cogs.minigames",\n    "cogs.music",',
    '    "cogs.minigames",\n    "cogs.games_economy",\n    "cogs.music",',
    "EXTENSIONS",
)
replace_exact(
    main,
    '    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",\n    "blackjack", "slots",\n',
    '    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",\n    "blackjack", "slots",\n' + GAME_PUBLIC,
    "PUBLIC_COMMANDS",
)
replace_exact(
    main,
    '        "shopsetup", "shoppanel", "shoprole", "give-money", "reset-economy",\n',
    '        "shopsetup", "shoppanel", "shoprole", "give-money", "reset-economy",\n        "gamesetup",\n',
    "CATEGORY_COMMANDS",
)

help_file = ROOT / "cogs" / "help_category_rework.py"
replace_exact(
    help_file,
    '    "Minigames": "games",\n',
    '    "Minigames": "games",\n'
    '    "GamesRapides": "games",\n'
    '    "GamesDuels": "games",\n'
    '    "GamesCommunity": "games",\n'
    '    "GamesSolo": "games",\n'
    '    "GamesPlayerCommands": "games",\n',
    "HELP_CATEGORIES",
)

print("Game recovery patch prepared cleanly")
