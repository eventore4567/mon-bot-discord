# SentriX — failover Railway actif/passif

## Objectif

Garder **une seule** session Discord active tout en laissant une deuxième instance SentriX prête à prendre le relais si la première tombe.

Le système utilise :

- **Redis SentriX** : lease/heartbeat et élection du leader ;
- **Postgres SentriX** : snapshots durables de la base SQLite ;
- **railway_ha_boot.py** : launcher commun au principal et au secours ;
- **deux services SentriX** : un `primary`, un `standby`.

Le failover est désactivé par défaut. Tant que `SENTRIX_FAILOVER_ENABLED` n'est pas activé, le nouveau launcher garde le comportement historique.

## 1. Retirer Bot'Odboug sans toucher aux données SentriX

D'après l'architecture Railway actuelle, Bot'Odboug possède ses propres services et volumes. Procédure de retrait sûre :

1. **Stopper uniquement le service `[+] Bot'Odboug |`**.
2. Ne pas supprimer immédiatement `PostgresOdboug`, `RedisOdboug` ou `OdbougBackups`.
3. Vérifier que `mon-bot-discord` reste Online et tester plusieurs commandes SentriX.
4. Garder l'infrastructure Odboug 24–48 h comme possibilité de rollback/export.
5. Vérifier qu'aucune variable du service SentriX ne référence `PostgresOdboug` ou `RedisOdboug`.
6. Une fois les données Odboug confirmées inutiles/sauvegardées, supprimer ses ressources si souhaité.

Ne pas arrêter/supprimer : `mon-bot-discord`, `Postgres`, `Redis`, `sentrix-backups`.

Le volume visible `postgres-volume-vQ_h` ne doit pas être supprimé tant que son propriétaire exact n'est pas identifié.

## 2. Vérification avant activation HA

Les deux Redis visibles dans Railway affichent actuellement un avertissement. Ouvrir l'avertissement du service **Redis de SentriX** et le résoudre/identifier avant d'activer le failover : Redis arbitre quelle instance a le droit de se connecter à Discord.

Vérifier aussi que le service principal possède :

- une URL Redis SentriX valide via `REDIS_URL` (ou `SENTRIX_FAILOVER_REDIS_URL`) ;
- une URL Postgres SentriX valide via `POSTGRES_URL` ou `DATABASE_URL` ;
- le token Discord SentriX ;
- le même `BOT_INSTANCE_KEY=sentrix` sur toutes les instances HA.

## 3. Service principal

Start Command :

```text
python railway_ha_boot.py
```

Variables :

```text
SENTRIX_FAILOVER_ENABLED=1
SENTRIX_FAILOVER_ROLE=primary
BOT_INSTANCE_KEY=sentrix
SENTRIX_FAILOVER_TTL=30
SENTRIX_FAILOVER_RENEW_INTERVAL=7
SENTRIX_FAILOVER_POLL_INTERVAL=2
SENTRIX_FAILOVER_SNAPSHOT_INTERVAL=300
```

Les URLs Redis/Postgres doivent référencer les services **Redis** et **Postgres de SentriX**, jamais ceux d'Odboug.

Au premier démarrage HA, le principal prend le lease puis pousse un snapshot PostgreSQL de référence avant d'ouvrir Discord.

## 4. Service de secours

Créer un deuxième service depuis le même dépôt/commit, par exemple `sentrix-standby`.

Utiliser le même Start Command :

```text
python railway_ha_boot.py
```

Variables spécifiques :

```text
SENTRIX_FAILOVER_ENABLED=1
SENTRIX_FAILOVER_ROLE=standby
BOT_INSTANCE_KEY=sentrix
```

Il doit utiliser :

- **le même token Discord SentriX** ;
- **le même Redis SentriX** ;
- **le même Postgres SentriX** ;
- son propre stockage SQLite local/volume si un volume local est utilisé.

Le standby démarre son HTTP/dashboard, mais il ne se connecte pas à Discord tant qu'il ne possède pas le lease Redis.

## 5. Comportement attendu

État normal :

```text
mon-bot-discord   -> leader -> connecté à Discord
sentrix-standby   -> standby -> pas de connexion Discord
Redis             -> lease sentrix:sentrix:failover:discord-primary
Postgres          -> snapshots durables partagés
```

Si le principal crash brutalement :

1. son lease cesse d'être renouvelé ;
2. Redis laisse expirer le lease (30 s par défaut) ;
3. le standby acquiert le lease ;
4. le standby restaure le dernier snapshot PostgreSQL ;
5. seulement après la restauration, il ouvre la session Discord et reprend les commandes.

Si une instance active perd son lease ou l'accès Redis, elle ferme sa session Discord afin d'éviter deux SentriX actifs en même temps.

Quand l'ancien principal revient, il reste standby tant qu'une autre instance possède le lease. Il ne vole pas le leadership.

## 6. Test de bascule

Après déploiement :

1. vérifier dans les logs du principal `HA: leadership acquis` puis `ACTIVE sur Discord` ;
2. vérifier que le secours reste `standby` ;
3. lancer plusieurs commandes Discord ;
4. stopper volontairement le service principal ;
5. attendre l'expiration du lease + le temps de connexion Discord ;
6. vérifier dans les logs du secours qu'il a restauré un snapshot puis qu'il est devenu ACTIVE ;
7. relancer le principal : il doit rester standby ;
8. tester à nouveau les commandes et vérifier qu'aucune réponse n'est doublée.

## Limite actuelle importante

Le runtime historique de SentriX utilise encore SQLite. PostgreSQL stocke des snapshots, ce n'est pas encore la source de vérité transactionnelle de toutes les écritures. Avec un snapshot périodique de 300 secondes, un crash brutal peut donc perdre les toutes dernières modifications non encore répliquées, même si le bot reprend les commandes automatiquement.

Pour viser ensuite un failover avec RPO proche de zéro, la phase suivante consiste à migrer les états critiques (économie, niveaux, sanctions, tickets/configuration et autres écritures importantes) vers PostgreSQL partagé ou vers un journal d'événements durable.
