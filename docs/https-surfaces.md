# Surfaces HTTPS SentriX

Les deux services HA existants servent les deux surfaces selon le domaine demandé.
Le lease Redis continue de choisir l'unique bot connecté à Discord. Les requêtes qui
nécessitent le bot actif utilisent le proxy privé existant ; ni les rôles HA, ni les
bases, ni les volumes ne sont modifiés.

| Surface | Domaine Railway | Comportement |
| --- | --- | --- |
| Dashboard | `https://mon-bot-discord-production-8944.up.railway.app` | Pages et OAuth existants, façade `/api` pour les sessions navigateur |
| API | `https://sentrix-standby-production.up.railway.app` | API uniquement, sans pages, connexion OAuth ou outils propriétaire |

Le dashboard conserve ses appels relatifs `/api`, ses cookies host-only `HttpOnly`,
`Secure`, `SameSite=Lax`, ses sessions Redis et ses jetons CSRF. Cette façade est
nécessaire avec les domaines Railway distincts : un navigateur ne peut pas partager
le cookie entre eux. Aucun jeton n'est ajouté au JavaScript, aucun style n'est modifié.
L'API publique est une surface réseau, pas une API anonyme : les routes privées
requièrent toujours la session et les permissions existantes. CORS n'accorde pas de
session ; seule l'origine exacte du dashboard est autorisée.

## Configuration

Définir les mêmes valeurs sur primary et standby :

```env
DASHBOARD_PUBLIC_URL=https://mon-bot-discord-production-8944.up.railway.app
API_PUBLIC_URL=https://sentrix-standby-production.up.railway.app
SENTRIX_HTTP_PROXY_SECRET=<secret aleatoire partage de 32 caracteres minimum>
```

`API_PUBLIC_URL` vide conserve le mode historique. Les origines doivent être deux
origines HTTPS distinctes, sans chemin. Le secret sert uniquement à authentifier
les échanges HTTP internes ; conserver sa valeur dans Railway, jamais dans Git.
Les URL privées HA existantes restent inchangées.

La garde est installée après la construction finale de l'application, y compris
dans le démarrage de secours. Elle précède le proxy HA, limite les appels API,
refuse les origines étrangères et les en-têtes de proxy falsifiés. Les contrôles de
session et CSRF s'exécutent après la restauration des sessions Redis.

Les limites sont locales à chaque processus : 120 appels API par minute, dont
30 écritures, par session validée ou adresse du pair TCP pour les appels anonymes.
`SENTRIX_API_RATE_LIMIT` et `SENTRIX_API_WRITE_RATE_LIMIT` règlent ces plafonds.
La réponse 429 fournit `Retry-After`. Les compteurs sont bornés en mémoire et
repartent à zéro au redémarrage ; les healthchecks restent hors quota.
Les en-têtes IP envoyés par le client ne permettent pas de changer de quota.
Sans proxy explicitement approuvé, les appels anonymes passant par le même ingress
partagent un quota. `SENTRIX_HTTP_TRUSTED_PROXY_CIDRS` ne doit être renseigné
qu'avec les réseaux vérifiés d'un proxy qui remplace lui-même `X-Real-IP`.

Les routes runtime du bot sont refusées sur les domaines publics. Les routes
propriétaire restent réservées au dashboard et à ses contrôles propriétaire.
Les routes non enregistrées n'acquièrent aucune autorisation par leur préfixe.
La télémétrie du bot HA est enregistrée directement dans son cache dashboard local.
Les anciens émetteurs externes anonymes ne peuvent plus alimenter le relais public.

`/health` reste local à chaque instance et conserve son code HTTP ainsi que les
champs HA nécessaires au companion. Les détails d'erreur sont remplacés par une
valeur générique. Une instance standby saine ne prétend pas être connectée à Discord.

## Déploiement progressif

1. Exécuter les tests critiques HTTP, auth, CSRF, proxy HA et démarrage de secours.
2. Configurer le secret partagé sans déclencher de déploiement. Déployer le code
   sur les deux instances avec `API_PUBLIC_URL` encore vide : elles signent alors
   déjà leurs échanges internes.
3. Attendre le statut Railway `SUCCESS` pour les deux déploiements et vérifier
   leurs healthchecks avant d'activer les origines.
4. Activer `API_PUBLIC_URL` sur une instance, vérifier son déploiement et ses routes,
   puis activer l'autre. Ne pas modifier Redis, Postgres, volumes ou rôles HA.
5. Vérifier dashboard, API publique, refus sans session, CORS, routes runtime et
   refus des pages sur le domaine API.

Les deux services suivent actuellement `main`. Un push sur cette branche peut
déclencher les deux déploiements ; les tests doivent donc passer avant ce push.
Le workflow historique `railway-ha-staggered-deploy.yml` actualise `standby-stable`,
mais ce n'est pas la branche suivie par le standby actuel.

## Domaines personnalisés

Quand les domaines sont disponibles, attacher `dashboard.sentrix…` au primary et
`api.sentrix…` au standby, puis remplacer les deux origines sur **les deux** services.
Mettre à jour la redirection Discord vers l'origine dashboard + `/oauth/callback`.
Les anciens domaines ne seront plus acceptés par la garde après ce changement.
Les cookies restent limités à leur hôte et la façade conserve la même sécurité.
