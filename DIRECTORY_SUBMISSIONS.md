# SentriX — Dossier de publication annuaires

Ce fichier centralise les informations prêtes à copier dans les principaux annuaires Discord.

## Identité commune

- Nom : **SentriX**
- Application ID : `1532010415951839252`
- Préfixes : `+` et `/`
- Langue : Français
- Site : `https://mon-bot-discord-production-8944.up.railway.app/`
- Installation : `https://mon-bot-discord-production-8944.up.railway.app/start`
- Dashboard : `https://mon-bot-discord-production-8944.up.railway.app/app`
- Stats : `https://mon-bot-discord-production-8944.up.railway.app/stats`
- Support : `https://mon-bot-discord-production-8944.up.railway.app/support`
- Confidentialité : `https://mon-bot-discord-production-8944.up.railway.app/privacy`
- Conditions : `https://mon-bot-discord-production-8944.up.railway.app/terms`
- Media kit : `https://mon-bot-discord-production-8944.up.railway.app/media-kit`
- Avatar : `https://mon-bot-discord-production-8944.up.railway.app/sentrix-avatar.png`

## Description courte

SentriX : bot Discord tout-en-un avec dashboard, modération, sécurité, tickets, IA, logs, niveaux, économie et automatisations.

## Description moyenne

SentriX centralise la gestion d'un serveur Discord : modération, AutoMod, anti-raid, tickets, logs, IA, automatisations, niveaux, économie et outils communautaires, avec un dashboard web complet.

## Tags prioritaires

`Moderation`, `Utility`, `Security`, `Automod`, `Ticket`, `Web Dashboard`, `AI`, `Logging`, `Multipurpose`, `Leveling`

## Liens de campagne SentriX

Ces URLs passent par le site officiel puis redirigent vers l'installation Discord. Elles servent à mesurer les clics par source sans enregistrer d'IP ni d'identifiant Discord.

- Top.gg : `/go/topgg`
- DiscordBotList : `/go/discordbotlist`
- Bots.gg : `/go/botsgg`
- DiscordList : `/go/discordlist`
- TikTok : `/go/tiktok`
- YouTube : `/go/youtube`
- Partenariats : `/go/partner`
- Diagnostic compteurs : `/marketing-stats`

---

## 1. Top.gg

- Soumission : `https://top.gg/bot/new`
- Connexion propriétaire requise.
- Fiche détaillée : voir `TOPGG_SUBMISSION.md`.
- Priorité : **très haute**.
- État au 24 août 2026 : Discord reconnaît et permet d'installer l'application `1532010415951839252`, `Public Bot` est activé et `Requires OAuth2 Code Grant` est désactivé, mais le formulaire Top.gg renvoie encore `Your application was not found`.
- Ne pas modifier l'Application ID : le souci observé est la détection Top.gg, pas l'installation Discord.
- Après approbation de la fiche, récupérer un token API v1 dans les intégrations Top.gg et l'ajouter uniquement dans Railway sous `TOPGG_TOKEN`.
- SentriX publiera alors automatiquement `server_count` et `shard_count` toutes les 30 minutes avec `PATCH /api/v1/projects/@me/metrics`.

## 2. DiscordBotList

- Site : `https://discordbotlist.com/`
- Utiliser l'identité commune ci-dessus.
- Catégories prioritaires : Moderation, Utility, Web Dashboard, Ticket, Automod.
- Ajouter le site officiel et le serveur support lorsqu'il sera configuré.
- Une connexion au service est nécessaire pour gérer une fiche de bot ; ne pas simuler une publication sans compte propriétaire.
- L'API officielle accepte les statistiques via `POST https://discordbotlist.com/api/v1/bots/:id/stats`.
- Après approbation, mettre le token uniquement dans Railway sous `DISCORDBOTLIST_TOKEN`.
- SentriX publiera automatiquement le nombre de serveurs et d'utilisateurs toutes les 30 minutes.

## 3. Discord Bots / Bots.gg

- Site : `https://discord.bots.gg/`
- Utiliser l'identité commune ci-dessus.
- Préfixe principal à afficher : `/` si un seul préfixe est accepté ; sinon `+ /`.
- Les conditions publiques interdisent l'automatisation de l'ajout, modification ou suppression de fiches de bots. La publication de la fiche reste donc manuelle depuis le compte propriétaire.
- Ne pas ajouter d'automatisation de gestion de fiche tant que la plateforme ne l'autorise pas explicitement.

## 4. DiscordList

- Site : `https://discordlist.gg/`
- Utiliser les mêmes descriptions, avatar et liens officiels.
- Priorité après Top.gg, DiscordBotList et Bots.gg.
- Publication manuelle jusqu'à confirmation d'une API officielle actuelle et de ses règles.

## 5. Discord App Directory

- Dossier complet : `DISCORD_APP_DIRECTORY.md`.
- Blocage actuel : la vérification d'identité Discord demandée au propriétaire n'a pas été terminée.
- Ne pas contourner cette vérification avec l'identité d'une autre personne.

---

## Publication automatique des statistiques

Fichier : `web/bot_directory_stats_v44.py`.

Le système est **désactivé par défaut**. Si aucun token n'est présent, aucune requête réseau vers un annuaire n'est effectuée.

Variables Railway :

```text
TOPGG_TOKEN=
DISCORDBOTLIST_TOKEN=
```

Les secrets ne doivent jamais être écrits dans GitHub. Le diagnostic sans secret est disponible sur `/api/directory-status`.

## Texte partenaire court

**SentriX — Tout votre serveur Discord, au même endroit.**

Modération, sécurité, tickets, IA, logs, automatisations et dashboard web dans un seul bot.

Site : https://mon-bot-discord-production-8944.up.railway.app/

## Ordre de publication recommandé

1. Top.gg — retenter la détection / support si le problème persiste
2. DiscordBotList
3. Bots.gg
4. DiscordList
5. Discord App Directory dès que la vérification Discord devient possible

## Règle

Ne jamais annoncer qu'une fiche externe est publiée tant que son URL publique n'a pas été vérifiée.
