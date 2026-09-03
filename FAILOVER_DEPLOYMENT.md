# SentriX — reprise automatique Railway

Ce mode garde deux services Railway disponibles avec le meme code et le meme token
Discord. Un seul service ouvre le Gateway Discord. Le second reste en attente avec un
healthcheck HTTP sain, puis prend le relais si le lease Redis de l'actif expire.

Le service Canary reste independant : il conserve son second token et
`python railway_canary_boot.py`. Il valide les versions, mais ne participe pas a la
reprise de production.

## Variables communes aux deux services

Les valeurs suivantes doivent etre strictement identiques :

```env
DISCORD_TOKEN=<token SentriX de production>
BOT_INSTANCE_KEY=sentrix
REDIS_URL=<reference du Redis Railway existant>
POSTGRES_URL=<reference du PostgreSQL Railway existant>
SENTRIX_FAILOVER_ENABLED=1
SENTRIX_FAILOVER_LEASE_TTL=20
SENTRIX_FAILOVER_RENEW_INTERVAL=5
SENTRIX_FAILOVER_POLL_INTERVAL=3
SENTRIX_FAILOVER_SNAPSHOT_INTERVAL=30
```

Les deux services utilisent la meme commande de demarrage :

```text
python railway_boot.py
```

## Service principal

```env
SENTRIX_FAILOVER_ROLE=primary
```

Le disque/volume SQLite actuel reste attache uniquement a ce service. Au premier
demarrage avec le failover active, le principal gagne normalement le lease et publie
immediatement un snapshot PostgreSQL.

## Service de secours

Creer un second service Railway depuis le meme depot et le nommer par exemple
`sentrix-failover`.

```env
SENTRIX_FAILOVER_ROLE=standby
SENTRIX_FAILOVER_STANDBY_DELAY=8
DATABASE_PATH=database/failover.db
```

Le secours ne doit pas partager le volume SQLite du principal. Lors d'une promotion, il
remplace sa copie locale par le dernier snapshot PostgreSQL avant de se connecter a
Discord.

## Ordre d'activation sans coupure

1. Deployer le code sur le service principal avec `SENTRIX_FAILOVER_ENABLED=0`.
2. Ajouter les variables de failover au principal, choisir le role `primary`, puis le
   redeployer.
3. Verifier `/health` : `failover.active=true` et `last_snapshot_id` non nul.
4. Creer seulement ensuite le service `sentrix-failover` avec le role `standby`.
5. Verifier son `/health` : `mode=standby`, `discord_ready=false` et
   `failover.status=standby`. Cet etat est normal et sain.

## Test de bascule

1. Arreter uniquement le service principal.
2. Attendre environ 20 a 35 secondes : expiration du lease, restauration du snapshot,
   chargement des commandes et connexion Discord.
3. Verifier que le service de secours expose `failover.active=true`, puis tester `+ping`
   et `/ping` dans le serveur Canary/test.
4. Redemarrer le principal. Il doit rester en standby tant que le secours est actif :
   aucune commande et aucun log ne doivent etre doubles.

## Garanties et limites

- Le compare-and-expire Redis empeche un processus de renouveler le lease d'un autre.
- Si l'actif perd Redis, il ferme Discord avant l'expiration du lease pour eviter deux
  instances actives.
- Une promotion sans snapshot PostgreSQL valide est refusee : une base vide ne remplace
  jamais silencieusement les donnees de production.
- Lors d'un crash brutal, les toutes dernieres ecritures SQLite peuvent manquer du
  snapshot. Avec la valeur par defaut, la fenetre habituelle est inferieure a 30 secondes.
- Une panne simultanee de Redis ou PostgreSQL bloque volontairement la promotion : mieux
  vaut une courte indisponibilite qu'un double bot ou une restauration vide.

## Retour arriere

Arreter d'abord le service de secours, verifier que le principal est actif, puis mettre
`SENTRIX_FAILOVER_ENABLED=0` sur le principal et le redeployer. Ne jamais desactiver le
mode sur les deux services tout en les laissant demarres avec le meme token.
