# SentriX — DiscordBotList prêt à publier

## Identité

- Nom : **SentriX**
- Application ID : `1532010415951839252`
- Préfixe principal : `/`
- Préfixe secondaire : `+`
- Langue : Français
- Site : `https://mon-bot-discord-production-8944.up.railway.app/`
- Dashboard : `https://mon-bot-discord-production-8944.up.railway.app/app`
- Support : `https://mon-bot-discord-production-8944.up.railway.app/support`
- Privacy : `https://mon-bot-discord-production-8944.up.railway.app/privacy`
- Terms : `https://mon-bot-discord-production-8944.up.railway.app/terms`
- Avatar : `https://mon-bot-discord-production-8944.up.railway.app/sentrix-avatar.png`

## Description courte

SentriX : bot Discord tout-en-un avec dashboard, modération, sécurité, tickets, IA, logs, niveaux, économie et automatisations.

## Description longue

# SentriX — Tout votre serveur Discord, au même endroit

SentriX regroupe dans une seule application les outils essentiels d'un serveur Discord : modération, sécurité, tickets, IA, logs, automatisations, niveaux, économie et gestion communautaire.

### Modération & sécurité
- sanctions et historique
- AutoMod
- anti-spam, anti-liens et anti-invitations
- anti-raid et anti-nuke
- audits de permissions

### Tickets
- panels configurables
- formulaires
- claim staff
- transcripts
- statistiques et historique

### IA & automatisations
- assistant SentriX
- outils IA
- FAQ serveur
- automatisations
- notifications sociales

### Communauté
- niveaux / XP
- économie
- boutique de rôles
- événements et giveaways
- recrutements
- vocaux temporaires
- Sticky Roles

### Dashboard
Les administrateurs peuvent activer et configurer les systèmes serveur par serveur depuis le dashboard web SentriX.

## Tags prioritaires

À choisir parmi ceux réellement proposés par DiscordBotList :

1. Moderation
2. Utility
3. Web Dashboard
4. Ticket
5. Automod
6. Logging
7. Multipurpose
8. AI si disponible

## Visuels

Ordre recommandé :

1. avatar officiel ;
2. dashboard ;
3. tickets ;
4. modération/sécurité ;
5. IA.

## Après approbation

DiscordBotList fournit une API officielle pour les statistiques du bot.

Endpoint :

`POST https://discordbotlist.com/api/v1/bots/1532010415951839252/stats`

SentriX est déjà préparé pour envoyer automatiquement :

- le nombre de serveurs ;
- le nombre d'utilisateurs.

Une fois le token DiscordBotList obtenu, l'ajouter uniquement dans les variables Railway :

```text
DISCORDBOTLIST_TOKEN=VOTRE_TOKEN
```

Ne jamais écrire la vraie clé dans GitHub.

Le diagnostic de l'intégration est disponible sans exposer les secrets sur :

`/api/directory-status`

## Votes

DiscordBotList classe les bots notamment grâce aux votes. Leur documentation indique qu'un utilisateur peut voter toutes les 12 heures. Une fois la fiche approuvée, il sera possible d'ajouter un webhook de vote vérifié si l'on souhaite récompenser les votants dans SentriX.
