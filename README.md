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

## Identité visuelle

Tous les embeds partagent désormais un style cohérent : violet électrique de marque, avatar du bot dans le footer, et des jauges visuelles (🟪) pour l'XP ou l'indice de confiance de l'IA.

- **`/sentrix <question>`** : posez n'importe quelle question à l'IA du bot ; elle répond en français avec un indice de confiance affiché sous forme de jauge (1 à 10).
- **Panneau de tickets amélioré** : cliquer sur "Créer un ticket" ouvre un formulaire (catégorie, priorité, description) au lieu d'un simple bouton, pour que le staff ait tout de suite le contexte.
- **Fermeture de ticket** : le bouton "Fermer" suffit, aucune commande requise ; le salon se supprime automatiquement 20 secondes après (annulable avec `+ticket-reopen`).
- **`/create-logs`** : crée et configure automatiquement un salon de logs privé en une seule commande, sans réglage manuel.

## Configuration en un clic

Plutôt que de taper une dizaine de commandes une par une, lancez simplement :

```
/setup
```

Un message avec des menus déroulants apparaît pour choisir votre rôle staff, votre salon de logs, votre salon de bienvenue et votre rôle automatique — tout en un seul endroit. C'est la façon la plus rapide de démarrer.

## Commandes

- Toutes les commandes fonctionnent avec `/` (slash) **ou** avec le préfixe `+` (ex: `+ban @membre`).
- Discord limite les bots à 100 commandes slash globales. Ce bot en expose 81 en slash ; **toutes** les commandes (y compris celles non exposées en `/`) fonctionnent avec `+`, sans exception.
- Utilisez `/help` ou `+help` pour voir la liste complète par catégorie.
- Les commandes gadgets peu utiles (QR code, calculatrice, boule magique, etc.) ont été retirées pour garder le bot simple et rapide ; les commandes de blacklist/whitelist ont toutes été conservées.

Catégories : Modération, Sécurité/AutoMod, Tickets, Configuration, Utilitaires, Intelligence Artificielle, Économie, Niveaux/Communauté, Mini-jeux, Musique, Giveaways/Événements, Vérification/Rôles, Statistiques/Développement.

## Sécurité renforcée

- **`/antinuke`** : protège contre un compte compromis (staff, ou même un rôle piraté) qui tenterait de détruire le serveur. Si quelqu'un supprime plusieurs salons/rôles ou bannit plusieurs membres en moins de 30 secondes, le bot lui retire immédiatement ses rôles à risque, l'expulse si possible, et alerte le propriétaire du serveur en message privé. Activé par défaut avec `/security-level`.
- **`/antinuke-whitelist-add`** : exempte un membre de confiance (vous-même, un co-admin) de cette protection.
- **`/antiraid`** : en plus de l'alerte, relève automatiquement le niveau de vérification du serveur dès qu'un afflux massif de nouveaux membres est détecté, ce qui bloque immédiatement les faux comptes.
- **`/lockdown-server`** et **`/unlock-server`** : verrouillent/déverrouillent tous les salons textuels en une commande, pour une réaction manuelle immédiate en cas d'urgence.

Pour un serveur sensible, activez `/security-level` sur **Élevé** et ajoutez tous vos administrateurs de confiance à la liste blanche anti-nuke avec `/antinuke-whitelist-add`.

## Tenir sur un gros serveur (20 000+ membres)

Le bot a été optimisé pour les grosses communautés :
- Base de données en mode **WAL** (lectures/écritures simultanées sans blocage).
- Index sur toutes les colonnes fréquemment interrogées (tickets, giveaways, avertissements...).
- Le préfixe de chaque serveur est mis en cache en mémoire pour ne pas interroger la base à chaque message.
- `/roleall` traite les membres progressivement (impossible d'attribuer un rôle à 20 000 personnes instantanément à cause des limites de débit de Discord — comptez quelques minutes).

Pour un serveur de cette taille, un hébergement 24/7 (voir section Hébergement) est fortement recommandé plutôt qu'un Mac personnel.

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
| Le bot semble lent (délai à l'envoi d'un message) | Si le dossier `discord-bot` se trouve dans **Documents** ou **Bureau** avec l'option "Synchronisation iCloud Drive du Bureau et Documents" activée sur le Mac, chaque écriture dans la base de données passe par iCloud et devient très lente. Déplacez le dossier ailleurs (par ex. `~/discord-bot`, en dehors de Documents/Bureau) pour un fonctionnement normal. |
