#!/bin/bash
# Double-cliquez sur ce fichier pour installer et lancer le bot sur Mac.
# Si macOS refuse de l'ouvrir : clic droit dessus > Ouvrir > Ouvrir.

cd "$(dirname "$0")"

echo "=========================================="
echo "  Installation et lancement du bot Discord"
echo "=========================================="
echo ""

# --- Vérifie/installe Homebrew ---
if ! command -v brew &> /dev/null; then
    echo "Installation de Homebrew (nécessaire pour ffmpeg)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# --- Vérifie/installe ffmpeg (nécessaire pour la musique) ---
if ! command -v ffmpeg &> /dev/null; then
    echo "Installation de ffmpeg..."
    brew install ffmpeg
fi

# --- Vérifie python3 ---
if ! command -v python3 &> /dev/null; then
    echo "Python 3 n'est pas installé. Installez-le depuis https://www.python.org/downloads/ puis relancez ce script."
    read -p "Appuyez sur Entrée pour fermer..."
    exit 1
fi

# --- Crée le fichier .env s'il n'existe pas déjà ---
if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
DISCORD_TOKEN=MTUzMjAxMDQxNTk1MTgzOTI1Mg.GKze67.IlNIA7txxXQSIwwvXfVHAxtUKo9dtVJiXeOQ6w
BOT_PREFIX=+
OPENAI_API_KEY=
WEATHER_API_KEY=
OWNER_IDS=
EOF
    echo "Fichier .env créé avec votre token."
fi

echo ""
echo "Installation des dépendances Python..."
pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt

echo ""
echo "Lancement du bot..."
echo "(Laissez cette fenêtre ouverte tant que vous voulez que le bot reste en ligne.)"
echo ""
python3 main.py

read -p "Appuyez sur Entrée pour fermer cette fenêtre..."
