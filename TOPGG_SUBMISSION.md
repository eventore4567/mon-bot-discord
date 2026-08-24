# SentriX — Soumission Top.gg prête à publier

## Application Discord

- Nom : **SentriX**
- Application ID : `1532010415951839252`
- Préfixes : `+` et `/`
- Langue principale : Français
- Site officiel : `https://mon-bot-discord-production-8944.up.railway.app/`
- Installation : `https://mon-bot-discord-production-8944.up.railway.app/start`
- Dashboard : `https://mon-bot-discord-production-8944.up.railway.app/app`
- Confidentialité : `https://mon-bot-discord-production-8944.up.railway.app/privacy`
- Conditions : `https://mon-bot-discord-production-8944.up.railway.app/terms`
- Media kit : `https://mon-bot-discord-production-8944.up.railway.app/media-kit`
- Avatar officiel : `https://mon-bot-discord-production-8944.up.railway.app/sentrix-avatar.png`

## Description courte

SentriX est un bot Discord tout-en-un avec dashboard, modération, sécurité, tickets, IA, logs, niveaux, économie et automatisations.

## Résumé alternatif

Gérez votre serveur Discord avec SentriX : modération, sécurité, tickets, IA, logs, automatisations et dashboard web complet.

## Description longue

# SentriX — Tout votre serveur Discord, au même endroit

SentriX centralise les outils essentiels d'une communauté Discord dans un seul bot avec un dashboard web complet.

### Modération et sécurité
- sanctions et historique de modération
- AutoMod
- anti-spam, anti-liens et anti-invitations
- anti-raid et anti-nuke
- surveillance configurable
- audits de permissions

### Tickets et support
- panels de tickets
- catégories et formulaires personnalisables
- claim staff
- transcripts
- historique et statistiques
- configuration depuis le dashboard

### IA et automatisations
- assistant IA SentriX
- génération et outils IA
- FAQ serveur
- automatisations configurables
- notifications sociales

### Communauté
- niveaux et XP
- économie et boutique de rôles
- mini-jeux
- événements et giveaways
- recrutements staff
- vocaux temporaires
- Sticky Roles
- vérification

### Dashboard web
Les administrateurs peuvent activer, désactiver et configurer les systèmes serveur par serveur depuis le dashboard SentriX.

**Site officiel :** https://mon-bot-discord-production-8944.up.railway.app/

## Catégories / tags à privilégier

1. Moderation
2. Utility
3. Dashboard / Web Dashboard
4. Security / Automod
5. Tickets
6. AI
7. Logging
8. Leveling
9. Multipurpose

Si Top.gg limite le nombre de catégories, garder en priorité : **Moderation, Utility, Security, Dashboard, Tickets**.

## Visuels

Ordre recommandé :

1. avatar officiel SentriX ;
2. screenshot dashboard ;
3. sécurité/modération ;
4. tickets ;
5. IA.

Les ressources sont disponibles via `/media-kit` et `assets/sentrix/`.

## Publication

Page officielle : `https://top.gg/bot/new`

Top.gg demande une connexion au compte du propriétaire avant la soumission. Utiliser exactement l'Application ID `1532010415951839252` et conserver le nom **SentriX**.

## État du problème Find Bot — 24 août 2026

Les vérifications côté Discord sont bonnes :

- l'Application ID affiche bien SentriX dans le flux d'installation Discord ;
- `Public Bot` est activé ;
- `Requires OAuth2 Code Grant` est désactivé ;
- le bot peut être ajouté à un serveur.

Malgré cela, Top.gg affiche actuellement `Your application was not found` sur `Find Bot`. Ne pas changer l'Application ID ni les permissions Discord pour tenter de contourner ce message.

### Message support prêt à envoyer

```text
Hello,

My Discord bot SentriX is public and can be installed normally through Discord.
Application ID: 1532010415951839252

However, the Top.gg submission page returns “Your application was not found” when I use Find Bot.
Public Bot is enabled and Requires OAuth2 Code Grant is disabled.
The Discord installation flow correctly displays SentriX and allows it to be added to a server.

Could you please check why the application is not being detected by the submission form?
Thank you.
```

## API Top.gg après approbation

Top.gg recommande désormais l'API v1 pour les nouvelles intégrations.

Une fois la fiche créée :

1. ouvrir les réglages **Integrations & API** du projet Top.gg ;
2. créer/copier le token API v1 ;
3. ajouter ce token uniquement dans Railway sous `TOPGG_TOKEN` ;
4. ne jamais mettre le token dans GitHub.

SentriX est déjà préparé pour publier automatiquement toutes les 30 minutes :

- `server_count` ;
- `shard_count`.

Endpoint préparé : `PATCH https://top.gg/api/v1/projects/@me/metrics` avec authentification Bearer.
