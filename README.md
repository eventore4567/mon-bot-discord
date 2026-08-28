# SentriX — Bot Discord tout-en-un

SentriX est un bot Discord en Python (`discord.py`) avec commandes slash (`/`) et commandes préfixées (`+` par défaut). Il regroupe modération, sécurité, logs, tickets, rôles, niveaux, économie, notifications sociales, IA et outils de gestion de serveur.

## Installation

```bash
cd discord-bot
cp .env.example .env
pip3 install -r requirements.txt
python3 main.py
```

Les secrets (`DISCORD_TOKEN`, clés API, secret OAuth) restent dans `.env` ou dans les variables Railway et ne doivent jamais être commit sur GitHub.

Dans le Discord Developer Portal, activez au minimum **SERVER MEMBERS INTENT** et **MESSAGE CONTENT INTENT**. Pour toutes les fonctions de gestion, invitez le bot avec les scopes `bot` et `applications.commands` et accordez-lui les permissions réellement nécessaires aux modules utilisés.

## `+setup` / `/setup` — centre de configuration V2

`+setup` est le centre principal de configuration. Il affiche l’état réel des modules et sépare clairement deux choses différentes :

- **Permissions du bot** : permissions Discord possédées par SentriX lui-même ;
- **Accès aux commandes** : permissions des membres, modérateurs, administrateurs et rôles personnalisés.

Les catégories principales sont : Modération, Permissions, Sécurité, Logs, Tickets, Bienvenue & départ, Rôles, Niveaux/économie, Notifications et IA.

Chaque module peut être **ACTIF** ou **INACTIF**. Désactiver un module ne supprime pas sa configuration ni ses données. Lors d’une réactivation depuis le setup, SentriX vérifie les salons/rôles et les permissions du bot nécessaires ; s’il manque quelque chose, l’activation est refusée avec la correction à effectuer.

Le bouton **Réinitialiser configuration** est volontairement séparé de la désactivation et exige de taper `RESET`. Une réinitialisation de configuration conserve les données utilisateur comme les XP, niveaux, soldes, banques et historiques.

## Accès aux commandes

La même règle d’accès est appliquée aux commandes `+` et `/`.

- les commandes publiques restent utilisables par les membres ;
- les rôles de modération peuvent recevoir l’accès aux commandes de modération nécessaires ;
- les administrateurs et le propriétaire du serveur conservent les fonctions de gestion du serveur ;
- un rôle personnalisé peut recevoir une autorisation ou un refus sur une commande précise ;
- les commandes réservées au propriétaire global de SentriX restent réservées au propriétaire global ;
- les règles SentriX ne contournent pas la hiérarchie Discord ni les limites du rôle du bot.

La whitelist globale de sécurité accepte des membres, modérateurs, administrateurs ou bots de confiance. Elle est utilisée par les protections automatiques concernées, notamment AutoMod/anti-raid/anti-nuke. Elle peut être gérée dans le setup ou avec `+whitelist` / `/whitelist` et `+unwhitelist` / `/unwhitelist` lorsque le rôle possède l’accès requis.

## Logs V2

Les routes de logs sont indépendantes. Le module Logs possède un interrupteur global, puis chaque type possède son propre état, son salon et un bouton de test.

- **Messages** : messages supprimés/modifiés et pièces jointes. Les images récemment supprimées peuvent être jointes au log grâce au cache binaire temporaire.
- **Membres** : arrivées, départs, pseudonymes et rôles ajoutés/retirés à un membre.
- **Modération** : warns, mutes/timeouts, kicks, bans, unbans et actions de modération.
- **Rôles** : création, suppression et modification des objets rôle/permissions.
- **Salons** : création, suppression et modification des salons.
- **Vocal** : connexions, déconnexions et changements vocaux.
- **Tickets** : cycle de vie des tickets.
- **Sécurité** : AutoMod, anti-spam, anti-raid et anti-nuke.
- **Ressources serveur** : emojis, stickers, invitations et modifications de webhooks.

Un type de log explicitement désactivé dans `+setup` reste désactivé après redémarrage. La récupération automatique des anciens salons `logs-*` n’a plus le droit de réactiver une route configurée puis coupée.

## Bienvenue & départ

Quand le module Bienvenue est actif et qu’aucun texte personnalisé n’est défini, SentriX utilise un modèle propre par défaut avec la mention, le pseudo et le nom du serveur. Le setup permet de régler :

- le salon de bienvenue et le salon de départ ;
- le titre et le texte ;
- une image/bannière par URL ;
- l’affichage de l’avatar ;
- l’affichage du nombre de membres ;
- l’autorôle ;
- un test de bienvenue sans ping.

Si aucun salon de bienvenue n’est choisi, SentriX utilise le salon système uniquement s’il existe et s’il est accessible. **SentriX ne crée jamais automatiquement un salon de bienvenue.**

## Notifications sociales

Les notifications sont stockées comme des sources indépendantes. Ajouter une nouvelle chaîne TikTok, YouTube, Twitch ou autre source prise en charge ne remplace pas les autres sources du serveur.

Le setup permet de sélectionner une source par son identifiant, modifier son lien/texte/image, choisir son salon et son rôle, l’activer/désactiver, la tester ou la supprimer. La liste est paginée : les serveurs ayant plus de 25 sources peuvent accéder à toutes leurs entrées.

Le moniteur vérifie les sources actives périodiquement. Chaque notification utilise le salon et le rôle enregistrés pour cette source précise.

## IA

Le module IA possède un interrupteur principal et des sous-fonctions indépendantes : conversation naturelle, commandes IA, analyse d’images et génération d’images. Couper l’une de ces sous-fonctions ne réinitialise pas les autres réglages IA.

## Niveaux & économie

Les niveaux et l’économie peuvent être coupés sans effacer les données des membres. Les récompenses de niveaux peuvent être ajoutées/modifiées dans le setup. La monnaie de l’économie peut avoir un nom singulier, un nom pluriel et un symbole personnalisés.

## `+create-server` / `/create-server`

`create-server` configure **le serveur Discord actuel** ; un bot Discord ne peut pas créer un nouveau serveur à la place de l’utilisateur.

La commande affiche toujours un aperçu puis demande une confirmation avant de créer/modifier des éléments. Le profil **Essentiel / Minimal** est proposé en premier : il crée une structure courte avec seulement les rôles et salons utiles. Les anciens profils Communauté, Professionnel et Support restent disponibles lorsqu’une structure plus grande est réellement souhaitée.

Une création explicite peut configurer les éléments du modèle sélectionné, mais un simple redémarrage de SentriX ne doit pas modifier un serveur. La maintenance automatique est donc **INACTIVE par défaut** et ne peut être activée qu’explicitement avec :

```text
+server-managed on
+server-managed off
+server-managed status
```

La présence de salons nommés `choix-des-rôles`, `boutique`, `annonces`, etc. n’est plus considérée comme une autorisation de modifier automatiquement le serveur.

## Tickets

Les tickets conservent leurs panels, types, rôles support, catégories, logs et historiques. Couper le module empêche les nouvelles ouvertures sans supprimer les tickets/configurations existants. Pour les réglages avancés des formulaires et panels, utilisez `+ticketsetup` ou `/ticketsetup` lorsqu’il est disponible dans la synchronisation slash.

## Dashboard

Le dashboard web intégré peut utiliser :

```env
DISCORD_CLIENT_SECRET=secret_oauth_de_l_application
DASHBOARD_PUBLIC_URL=https://votre-domaine.up.railway.app
DISCORD_CLIENT_ID=
```

La redirection OAuth configurée dans Discord doit correspondre exactement à :

```text
https://votre-domaine.up.railway.app/oauth/callback
```

## Données et persistance

SentriX utilise SQLite avec WAL. Les niveaux, nombres de messages, économie, banques, achats et historiques sont stockés par serveur/membre et ne doivent pas être supprimés simplement parce qu’un module est désactivé ou qu’un membre est sanctionné/banni.

## Aide et dépannage

Utilisez `+help` ou `/help` pour consulter les commandes disponibles. Si une commande est refusée, vérifiez dans cet ordre : état du module dans `+setup`, **Accès aux commandes**, permissions Discord du membre, permissions Discord du bot, puis hiérarchie des rôles.

Pour Railway, le dépôt peut être déployé automatiquement après merge. Vérifiez toujours les GitHub Actions et l’état du déploiement avant de considérer une version comme publiée.