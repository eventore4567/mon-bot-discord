# P1 — Execution Plane et isolation

P1 est considere vert uniquement si les deux gates hote passent :

1. **Chaos** : le node-agent tire l'etat desire, lance un sandbox `runsc`, le
   Control Plane est coupe, puis le conteneur est tue en `SIGKILL`. Le bot doit
   etre relance depuis le cache local sans dependance au Control Plane.
2. **Isolation** : un sandbox peut faire un HTTPS public mais ne peut joindre ni
   `169.254.169.254`, ni RFC1918/CGNAT, ni le sandbox d'un autre tenant. Les
   limites CPU/RAM/PID et le rootfs read-only sont verifiees par Docker inspect.

## Node-agent

Enregistrer le noeud avec `ops/execution/register_node.py`, puis renseigner :

```env
SENTRIX_CONTROL_PLANE_URL=https://control.example.com
SENTRIX_NODE_ID=...
SENTRIX_NODE_TOKEN=...
SENTRIX_CONTROL_PLANE_CIDRS=203.0.113.10/32
SENTRIX_AGENT_CACHE=/var/lib/sentrix-agent/desired.json
```

Le node-agent est **pull-only** : aucun SSH et aucune commande poussee depuis le
Control Plane. Le cache est ecrit atomiquement en mode `0600`.

## Isolation fail-closed

- runtime obligatoire : gVisor `runsc` ;
- cgroups v2 obligatoire ;
- rootfs read-only + `/tmp` tmpfs ;
- `cap-drop=ALL`, `no-new-privileges`, aucun bind mount, aucun socket Docker ;
- un bridge Docker distinct par instance, ICC desactive ;
- `DOCKER-USER` bloque metadata, RFC1918 et CGNAT pour tous les reseaux SentriX ;
- les CIDR du Control Plane public doivent etre ajoutes a
  `SENTRIX_CONTROL_PLANE_CIDRS`.

Le script refuse de demarrer si la chaine `DOCKER-USER` n'existe pas. C'est
volontaire : le backend nftables Docker necessite une politique equivalente
specifique et P1 ne pretend pas etre isole sans filtre effectivement applique.

## Heartbeats

Le rapport de sante courant est stocke dans Redis avec TTL. PostgreSQL ne recoit
que les transitions d'etat (UPSERT conditionnel), afin de ne pas transformer la
base transactionnelle en base time-series.
