# ADR 0001 — Multi-tenancy : org_id partout et FK composites

Statut : accepté (P0) · Porte à sens unique n°1

## Contexte
Rétrofitter la multi-tenancy sur un schéma qui n'en a pas est une réécriture
complète, avec migration de données à risque. Le coût aujourd'hui est d'une
colonne par table.

## Décision
1. `org_id` sur chaque table tenant, même avec un seul client.
2. Chaque table parent porte `UNIQUE (id, org_id)` — redondant en apparence,
   mais c'est la cible obligatoire des FK composites.
3. Chaque table enfant référence `(parent_id, org_id)` conjointement.

## Conséquence
Une ligne d'une org ne *peut pas* pointer vers une ligne d'une autre org. Ce
n'est pas une vérification que le code pense à faire : même un bug applicatif,
une injection SQL ou une console d'admin ne peuvent pas produire la ligne
(erreur 23503).

## Alternative écartée
Filtrage par `WHERE org_id = ?` dans le code. Rejeté : un seul oubli, sur une
seule requête, suffit à provoquer une fuite, et rien ne le détecte.

## Règle de revue
Toute nouvelle table enfant DOIT utiliser une FK composite. Non négociable.
