"""Catalogues et données statiques des mini-jeux SentriX."""

GAME_CATALOG = {
    "rps": ("🎮 Pierre-feuille-ciseaux (vs bot)", "rapide"),
    "guess-number": ("🔢 Devine le nombre", "rapide"),
    "trivia": ("❓ Question de culture générale", "rapide"),
    "tictactoe": ("⭕ Morpion (duel)", "duel"),
    "hangman": ("🎯 Pendu", "rapide"),
    "math-quiz": ("🧮 Quiz mathématique", "rapide"),
    "blackjack": ("🃏 Blackjack (vs bot)", "rapide"),
    "slots": ("🎰 Machine à sous", "rapide"),
    "coinflip": ("🪙 Pile ou face", "rapide"),
    "dice": ("🎲 Pari sur un dé", "rapide"),
    "luckyroll": ("🎲🎲 Lancer de dés chanceux", "rapide"),
    "highlow": ("🃏 Plus haut ou plus bas", "rapide"),
    "memory": ("🧠 Mémoire", "rapide"),
    "reaction": ("⚡ Réaction rapide", "rapide"),
    "scramble": ("🔤 Mot mélangé", "rapide"),
    "wordgame": ("📖 Devine le mot (définition)", "rapide"),
    "emojiquiz": ("🧩 Quiz emoji", "rapide"),
    "colorquiz": ("🎨 Quiz couleur", "rapide"),
    "fasttype": ("⌨️ Retape vite", "rapide"),
    "duel": ("⚔️ Duel pierre-feuille-ciseaux", "duel"),
    "connect4": ("🔴 Puissance 4", "duel"),
    "numberduel": ("🔢 Duel du nombre secret", "duel"),
    "reactionduel": ("⚡ Duel de réaction", "duel"),
    "quizduel": ("❓ Duel de quiz", "duel"),
    "triviastart": ("❓ Trivia communautaire", "communautaire"),
    "wordrace": ("🔤 Course au mot", "communautaire"),
    "reactionevent": ("⚡ Évènement réaction", "communautaire"),
    "guessrace": ("🔢 Course au nombre", "communautaire"),
    "mathrace": ("🧮 Course mathématique", "communautaire"),
    "lastmessage": ("💬 Dernier message gagne", "communautaire"),
    "emoji-race": ("🍒 Course à l'emoji", "communautaire"),
    "adventure": ("🗺️ Aventure", "solo"),
    "dungeon": ("🏰 Donjon", "solo"),
    "mining": ("⛏️ Mine", "solo"),
    "fishing": ("🎣 Pêche", "solo"),
    "treasure": ("💎 Chasse au trésor", "solo"),
    "hunt": ("🏹 Chasse", "solo"),
    "explore": ("🧭 Exploration", "solo"),
}

WORDGAME_CLUES = [
    ("Petit animal domestique qui miaule", "chat"),
    ("Astre autour duquel tourne la Terre", "soleil"),
    ("Boisson chaude à base de grains torréfiés", "café"),
    ("Ce que l'on utilise pour écrire au tableau", "craie"),
    ("Saison la plus froide de l'année", "hiver"),
]

EMOJI_QUIZ = [
    ("🐱🐟", "chat"),
    ("🌙⭐", "nuit"),
    ("🔥🐉", "dragon"),
    ("🏴‍☠️⚓", "pirate"),
    ("🦁👑", "roi"),
]

COLOR_EMOJIS = {"rouge": "🟥", "vert": "🟩", "bleu": "🟦", "jaune": "🟨", "violet": "🟪", "orange": "🟧"}

FASTTYPE_PHRASES = [
    "SentriX protège ce serveur.",
    "Les mini-jeux rapportent des récompenses.",
    "La vitesse récompense les plus rapides.",
    "Discord est une plateforme de communication.",
]

RPS_BEATS = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}

COMMUNITY_TRIVIA = [
    ("Quel est le plus long fleuve du monde ?", "nil"),
    ("Combien y a-t-il de continents ?", "7"),
    ("Quelle est la monnaie du Japon ?", "yen"),
]
COMMUNITY_WORDS = ["communauté", "serveur", "discord", "récompense", "aventure"]
COMMUNITY_MATH_OPS = {"+": lambda a, b: a + b, "-": lambda a, b: a - b}

SOLO_FLAVORS = {
    "adventure": ("🗺️ Aventure", 900, [
        "Vous explorez une forêt mystérieuse et trouvez un coffre abandonné.",
        "Un vieux sage vous récompense pour votre courage.",
        "Vous traversez une rivière et découvrez des pièces anciennes.",
    ], "Vous vous perdez en chemin et rentrez bredouille."),
    "dungeon": ("🏰 Donjon", 1200, [
        "Vous vainquez le gardien du donjon et récupérez son butin.",
        "Un piège désamorcé à temps révèle une salle secrète pleine de trésors.",
    ], "Le donjon s'effondre partiellement, vous devez rebrousser chemin."),
    "mining": ("⛏️ Mine", 600, [
        "Votre pioche heurte un filon d'or !",
        "Vous ramenez un sac de minerai précieux.",
    ], "La mine est vide aujourd'hui, vous ne trouvez rien."),
    "fishing": ("🎣 Pêche", 600, [
        "Une prise magnifique mord à l'hameçon !",
        "Vous remontez un poisson rare, très recherché.",
    ], "Aucun poisson ne mord aujourd'hui."),
    "treasure": ("💎 Chasse au trésor", 1500, [
        "Votre carte au trésor était la bonne !",
        "Vous déterrez un coffre rempli de pièces anciennes.",
    ], "La carte au trésor était un faux, rien à l'horizon."),
    "hunt": ("🏹 Chasse", 900, [
        "Une chasse fructueuse vous rapporte un beau gibier.",
        "Vous rentrez avec un trophée de valeur.",
    ], "Le gibier s'échappe, vous rentrez les mains vides."),
    "explore": ("🧭 Exploration", 1000, [
        "Vous découvrez des ruines oubliées pleines de reliques.",
        "Une grotte inexplorée révèle des richesses insoupçonnées.",
    ], "La zone explorée était déjà pillée, rien à récupérer."),
}
