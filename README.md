# Bot Discord Tout-en-un

Bot Discord complet en Python (discord.py), avec commandes slash (`/`) **et** commandes textuelles avec préfixe (`+` par défaut). Base de données SQLite, embeds propres, boutons/menus, tout en français.

## Installation rapide (Mac)

1. Double-cliquez sur `installer.command` (clic droit > Ouvrir si macOS bloque).
2. Le script installe automatiquement Homebrew, ffmpeg, les dépendances Python, crée le fichier `.env` avec votre token, puis lance le bot.
3. Gardez la fenêtre de terminal ouverte : le bot reste en ligne tant qu'elle est ouverte.

## Installation manuelle

```bash
cd discord-bot
cp .env.example .env
# Ouvrez .env et remplissez DISCORD_TOKEN=votre_token
pip3 install -r requirements.txt
python3 main.py
```

## Configuration requise sur le Discord Developer Portal

Sur https://discord.com/developers/applications, sélectionnez votre application > **Bot** :
- Activez **SERVER MEMBERS INTENT**
- Activez **MESSAGE CONTENT INTENT**

Sans ces deux options, le bot plantera au démarrage.

## Inviter le bot sur votre serveur

Utilisez l'**OAuth2 URL Generator** (onglet OAuth2 > URL Generator) :
- Scopes : `bot`, `applications.commands`
- Permissions : `Administrator` (recommandé pour un fonctionnement complet)

## Commandes

- Toutes les commandes fonctionnent avec `/` (slash) **ou** avec le préfixe `+` (ex: `+ban @membre`).
- Discord limite les bots à 100 commandes slash globales. Ce bot en expose ~83 en slash ; **toutes** les commandes (y compris celles non exposées en `/`) fonctionnent avec `+`, sans exception.
- Utilisez `/help` ou `+help` pour voir la liste complète par catégorie.

Catégories : Modération, Sécurité/AutoMod, Tickets, Configuration, Utilitaires, Intelligence Artificielle, Économie, Niveaux/Communauté, Mini-jeux, Musique, Giveaways/Événements, Vérification/Rôles, Statistiques/Développement.

## Sécurité

- Le token et les clés API sont lus depuis `.env` (jamais écrits en dur dans le code, jamais commit).
- `.env` est dans `.gitignore`.
- Le bot ne collecte jamais d'adresses IP. Les listes noires utilisent uniquement les identifiants Discord (IDs).
- Toutes les commandes de modération vérifient la hiérarchie des rôles : impossible de sanctionner un membre de rang égal ou supérieur.
- Toutes les sanctions sont journalisées dans le salon de logs configuré (`/setlogchannel`).

## Hébergement

Pour que le bot reste en ligne 24h/24 sans garder votre Mac allumé, plusieurs options :

- **Railway** (https://railway.app) : connectez le dépôt, ajoutez la variable `DISCORD_TOKEN` dans les settings, déploiement automatique.
- **Render** (https://render.com) : créez un "Background Worker", même principe.
- **VPS + systemd** : hébergement le plus fiable pour un usage sérieux, nécessite des connaissances serveur.
- **Docker** : `docker build -t mon-bot .` puis `docker run -d --env-file .env mon-bot`.

## Structure du projet

```
discord-bot/
├── main.py                 # Point d'entrée
├── config.py                # Lecture des variables d'environnement
├── requirements.txt
├── .env                      # Vos secrets (ne pas partager)
├── database/
│   └── db.py                 # Base SQLite et schéma
├── utils/
│   ├── embeds.py             # Embeds réutilisables
│   ├── checks.py              # Permissions et hiérarchie
│   └── helpers.py             # Fonctions utilitaires, vues UI
└── cogs/                      # Un module par catégorie de commandes
    ├── moderation.py
    ├── automod.py
    ├── tickets.py
    ├── configuration.py
    ├── utility.py
    ├── ai.py
    ├── economy.py
    ├── levels.py
    ├── minigames.py
    ├── music.py
    ├── events.py
    ├── verification.py
    └── stats.py
```

## Dépannage

| Problème | Solution |
|---|---|
| `PrivilegedIntentsRequired` | Activez les deux intents dans le Developer Portal (voir ci-dessus). |
| Erreur de certificat SSL au démarrage | Sur Mac, lancez `/Applications/Python 3.x/Install Certificates.command`. |
| Une commande `/` n'apparaît pas | Attendez quelques minutes (synchronisation Discord) ou utilisez-la avec `+`. |
| Le bot ne répond à rien | Vérifiez que le terminal est toujours ouvert et qu'aucune erreur n'apparaît au démarrage. |
