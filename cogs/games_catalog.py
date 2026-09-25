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
    "minesweeper": ("💣 Démineur", "rapide"),
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
    ("Petit animal domestique qui miaule", ("chat",), "easy"),
    ("Astre autour duquel tourne la Terre", ("soleil",), "easy"),
    ("Boisson chaude à base de grains torréfiés", ("café", "cafe"), "normal"),
    ("Ce que l'on utilise pour écrire au tableau", ("craie",), "normal"),
    ("Saison la plus froide de l'année", ("hiver",), "easy"),
    ("Objet qui indique le nord sur une carte", ("boussole",), "normal"),
    ("Suite de choix où chaque décision change la suite", ("aventure",), "hard"),
]

EMOJI_QUIZ = [
    ("🐱🐟", ("chat",), "easy"),
    ("🌙⭐", ("nuit",), "easy"),
    ("🔥🐉", ("dragon",), "normal"),
    ("🏴‍☠️⚓", ("pirate",), "normal"),
    ("🦁👑", ("roi", "lion"), "normal"),
    ("🧊🏰", ("chateau de glace", "château de glace"), "hard"),
]

COLOR_EMOJIS = {"rouge": "🟥", "vert": "🟩", "bleu": "🟦", "jaune": "🟨", "violet": "🟪", "orange": "🟧"}

FASTTYPE_PHRASES = [
    "SentriX protège ce serveur.",
    "Les mini-jeux rapportent des récompenses.",
    "La vitesse récompense les plus rapides.",
    "Discord est une plateforme de communication.",
]

# Les défis de vitesse/mémoire mélangent volontairement texte, nombres et symboles
# afin qu'une manche ne ressemble jamais exactement à la précédente.
FASTTYPE_WORDS = [
    "NOVA", "VOLT", "PIXEL", "NEXUS", "ORBIT", "RAPID", "SENTRIX", "COMET",
]
FASTTYPE_EMOJIS = ["⚡", "🔥", "💎", "⭐", "🌙", "🎯", "🧊", "🪐"]
MEMORY_TOKENS = ["1", "2", "3", "4", "7", "8", "9", "⚡", "🔥", "💎", "⭐", "🌙", "🎯"]

# Tous les jeux solo proposent maintenant trois styles de partie. Les pourcentages ne
# changent pas l'économie globale : ils changent seulement la chance de succès et la
# récompense de base avant les limites/multiplicateurs existants.
SOLO_CHOICES = {
    "adventure": [
        ("🛡️", "Route sûre", 0.88, 0.75, "Suivre le chemin balisé"),
        ("🗺️", "Exploration", 0.70, 1.00, "Quitter le sentier pour chercher du butin"),
        ("🔥", "Zone interdite", 0.46, 1.65, "Prendre le raccourci le plus dangereux"),
    ],
    "dungeon": [
        ("🛡️", "Couloir calme", 0.86, 0.80, "Avancer prudemment"),
        ("🗝️", "Salle scellée", 0.67, 1.10, "Forcer une porte ancienne"),
        ("👑", "Boss", 0.42, 1.80, "Affronter directement le gardien"),
    ],
    "mining": [
        ("🪨", "Veine stable", 0.90, 0.70, "Miner près de l'entrée"),
        ("⛏️", "Galerie profonde", 0.72, 1.00, "Descendre chercher du minerai rare"),
        ("💥", "Faille instable", 0.45, 1.75, "Creuser dans une zone très riche mais fragile"),
    ],
    "fishing": [
        ("🎣", "Bord du lac", 0.90, 0.70, "Pêcher tranquillement"),
        ("🌊", "Eaux profondes", 0.70, 1.05, "Viser les grosses prises"),
        ("🦈", "Zone dangereuse", 0.43, 1.80, "Chercher une prise légendaire"),
    ],
    "treasure": [
        ("🧭", "Carte fiable", 0.86, 0.80, "Suivre les indices connus"),
        ("🏝️", "Île oubliée", 0.65, 1.15, "Explorer une piste secondaire"),
        ("💎", "Coffre maudit", 0.38, 2.00, "Tenter le trésor le plus rare"),
    ],
    "hunt": [
        ("🐾", "Piste facile", 0.88, 0.75, "Suivre des traces récentes"),
        ("🏹", "Grande chasse", 0.68, 1.05, "Chercher une cible plus rare"),
        ("🐉", "Créature légendaire", 0.40, 1.90, "Prendre tous les risques"),
    ],
    "explore": [
        ("🧭", "Zone connue", 0.90, 0.70, "Cartographier les alentours"),
        ("🏛️", "Ruines", 0.68, 1.10, "Entrer dans des ruines oubliées"),
        ("🌀", "Portail inconnu", 0.41, 1.90, "Traverser sans savoir ce qu'il y a derrière"),
    ],
}

RPS_BEATS = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}

COMMUNITY_TRIVIA = [
    ("Quel est le plus long fleuve du monde ?", ("nil", "le nil"), "normal"),
    ("Combien y a-t-il de continents ?", ("7", "sept"), "easy"),
    ("Quelle est la monnaie du Japon ?", ("yen",), "normal"),
    ("Quel langage est souvent utilisé pour les bots Discord Python ?", ("python",), "easy"),
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

# =============================================================================
# Butin des jeux solo : ce qu'on ramène vraiment
# =============================================================================
#
# Avant, une manche gagnante affichait une phrase au hasard et un montant : deux
# parties de pêche se ressemblaient, et rien ne donnait envie d'en relancer une.
# Chaque manche tire maintenant une PRISE, avec sa rareté et son multiplicateur —
# la légendaire est rare, visible, et vaut le coup.
#
# Le multiplicateur s'applique au montant de base ; les réglages du serveur
# (multiplicateur de gains, limite quotidienne) s'appliquent ensuite, comme avant.

RARETES = (
    # (clé, libellé, poids, multiplicateur)
    ("commun", "Commun", 58, 1.0),
    ("rare", "Rare", 26, 1.6),
    ("epique", "Épique", 13, 2.6),
    ("legendaire", "Légendaire", 3, 4.5),
)

SOLO_LOOT: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "fishing": {
        "commun": (("🐟", "Gardon"), ("🐠", "Poisson-clown"), ("🦐", "Crevette grise"), ("🥾", "Vieille botte")),
        "rare": (("🐡", "Poisson-globe"), ("🦑", "Calmar"), ("🦀", "Tourteau")),
        "epique": (("🦞", "Homard bleu"), ("🐙", "Pieuvre géante"), ("🐢", "Tortue centenaire")),
        "legendaire": (("🦈", "Requin blanc"), ("🐋", "Baleine bleue"), ("🧜", "Sirène (elle est repartie)")),
    },
    "mining": {
        "commun": (("🪨", "Caillou"), ("⚫", "Charbon"), ("🧱", "Argile")),
        "rare": (("🔩", "Fer"), ("🥉", "Cuivre"), ("🪙", "Filon d'argent")),
        "epique": (("🥇", "Pépite d'or"), ("💠", "Améthyste"), ("🔷", "Saphir brut")),
        "legendaire": (("💎", "Diamant pur"), ("☄️", "Fragment de météorite"), ("🟣", "Cristal de faille")),
    },
    "hunt": {
        "commun": (("🐇", "Lièvre"), ("🦆", "Canard"), ("🐿️", "Écureuil")),
        "rare": (("🦌", "Cerf"), ("🐗", "Sanglier"), ("🦃", "Dindon sauvage")),
        "epique": (("🐺", "Loup gris"), ("🦅", "Aigle royal"), ("🐻", "Ours brun")),
        "legendaire": (("🦁", "Lion évadé du zoo"), ("🦬", "Bison des plaines"), ("🐉", "Quelque chose d'inexplicable")),
    },
    "treasure": {
        "commun": (("🪙", "Poignée de pièces"), ("🗝️", "Clé rouillée"), ("🏺", "Vase ébréché")),
        "rare": (("💰", "Bourse pleine"), ("📜", "Parchemin scellé"), ("⚱️", "Urne gravée")),
        "epique": (("👑", "Couronne oubliée"), ("💍", "Anneau ancien"), ("🗿", "Idole de pierre")),
        "legendaire": (("🏆", "Trésor du capitaine"), ("💎", "Gemme des profondeurs"), ("🪬", "Amulette maudite")),
    },
    "adventure": {
        "commun": (("🍄", "Champignons rares"), ("🌿", "Herbes médicinales"), ("🪵", "Bois noble")),
        "rare": (("🗺️", "Carte annotée"), ("🧭", "Boussole ancienne"), ("🔮", "Éclat de cristal")),
        "epique": (("⚗️", "Fiole d'alchimiste"), ("📕", "Grimoire poussiéreux"), ("🎭", "Masque rituel")),
        "legendaire": (("🗡️", "Lame elfique"), ("🛡️", "Bouclier du gardien"), ("🪄", "Bâton runique")),
    },
    "dungeon": {
        "commun": (("🕯️", "Bougie du gardien"), ("🦴", "Ossements"), ("⛓️", "Chaîne brisée")),
        "rare": (("🗡️", "Dague ébréchée"), ("🛡️", "Écu cabossé"), ("💀", "Crâne gravé")),
        "epique": (("🏹", "Arc du veilleur"), ("🧿", "Œil de pierre"), ("🔱", "Trident rouillé")),
        "legendaire": (("👹", "Trophée du boss"), ("🔥", "Cœur de braise"), ("⚜️", "Sceau royal")),
    },
    "explore": {
        "commun": (("🌾", "Champ de blé"), ("🪺", "Nid abandonné"), ("🍃", "Sentier oublié")),
        "rare": (("⛰️", "Grotte cachée"), ("💧", "Source claire"), ("🏕️", "Campement désert")),
        "epique": (("🌋", "Cratère fumant"), ("🏛️", "Ruines antiques"), ("🌌", "Clairière étoilée")),
        "legendaire": (("🏝️", "Île non cartographiée"), ("🛸", "Objet non identifié"), ("🗿", "Monolithe silencieux")),
    },
}



# Machine à sous : le rouleau était uniforme et le gain plat — trois 7️⃣ payaient
# exactement comme trois 🍒, ce qui rendait les symboles rares purement décoratifs.
# Poids sur 100 (du plus commun au plus rare) puis multiplicateur de gain.
ROULEAU_SLOTS = (
    ("🍒", 30, 1.0),
    ("🍋", 24, 1.3),
    ("🍊", 19, 1.7),
    ("🍇", 14, 2.2),
    ("💎", 9, 4.0),
    ("7️⃣", 4, 9.0),
)


# Chaque expédition n'avait qu'UNE phrase d'échec : au troisième essai, on la
# connaît par cœur. SOLO_ECHECS en donne plusieurs par jeu (la phrase d'origine
# de SOLO_FLAVORS reste le secours si un jeu manque ici).
SOLO_ECHECS: dict[str, tuple[str, ...]] = {
    "adventure": (
        "Vous vous perdez en chemin et rentrez bredouille.",
        "Un orage vous force à faire demi-tour avant le col.",
        "La carte était fausse. Trois heures pour revenir au point de départ.",
        "Un pont effondré, et aucun gué à des lieues à la ronde.",
    ),
    "dungeon": (
        "Le donjon s'effondre partiellement, vous devez rebrousser chemin.",
        "La torche s'éteint dans le troisième couloir. On ne tente pas la suite à l'aveugle.",
        "La porte scellée résiste. Il faudra revenir avec la bonne clé.",
        "Quelque chose grogne derrière le mur. Vous décidez de ne pas vérifier quoi.",
    ),
    "mining": (
        "La mine est vide aujourd'hui, vous ne trouvez rien.",
        "Le filon s'arrête net après deux coups de pioche.",
        "Le manche de la pioche cède. Fin de la séance.",
        "Rien que de la roche stérile sur toute la galerie.",
    ),
    "fishing": (
        "Aucun poisson ne mord aujourd'hui.",
        "Une touche, une seule — et la ligne casse.",
        "Vous remontez une botte. Elle n'intéresse personne.",
        "Le poisson vous regarde, puis s'en va.",
    ),
    "treasure": (
        "La carte au trésor était un faux, rien à l'horizon.",
        "La croix sur la carte marquait un caillou.",
        "Le coffre était là. Quelqu'un est passé avant vous.",
        "Trois trous, trois déceptions.",
    ),
    "hunt": (
        "Le gibier s'échappe, vous rentrez les mains vides.",
        "Une piste fraîche, puis plus rien pendant des heures.",
        "Le vent tournait dans le mauvais sens tout l'après-midi.",
        "Vous rentrez avec le carquois plein. C'est bien le problème.",
    ),
    "explore": (
        "La zone explorée était déjà pillée, rien à récupérer.",
        "Le sentier se termine sur une falaise.",
        "Brouillard épais. Impossible de relever quoi que ce soit.",
        "Vous cartographiez une clairière déjà cartographiée.",
    ),
}


# Valeur en pièces d'un objet ramené. Vex affiche « a Salmon worth 45 Coins » :
# un objet sans prix n'est qu'un mot. La valeur se déduit de la rareté, avec un
# écart propre à chaque objet pour qu'un Requin blanc ne vaille pas exactement
# autant qu'une Baleine bleue — et elle est DÉTERMINISTE : le même objet vaut
# toujours le même prix, sinon le joueur ne peut rien comparer.
BANDES_DE_VALEUR: dict[str, tuple[int, int]] = {
    "commun": (5, 25),
    "rare": (30, 75),
    "epique": (95, 185),
    "legendaire": (260, 520),
}


def valeur_objet(rarete_cle: str, nom: str) -> int:
    """Prix en pièces d'un objet, stable d'une partie à l'autre."""
    bas, haut = BANDES_DE_VALEUR.get(rarete_cle, BANDES_DE_VALEUR["commun"])
    # Somme des codes du nom : déterministe entre deux exécutions, contrairement
    # à hash() que Python randomise à chaque démarrage du process.
    empreinte = sum(ord(c) for c in nom)
    return bas + empreinte % (haut - bas + 1)
