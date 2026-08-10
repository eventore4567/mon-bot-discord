# ADR 0004 — Migrations forward-only avec checksums

Statut : accepté (P0)

## Décision
Fichiers `.sql` numérotés `NNNN_nom.sql`, appliqués en ordre, chacun dans sa
propre transaction. Le SHA-256 de chaque migration appliquée est stocké et
revérifié à chaque démarrage.

## Justification
- Pas de SQLAlchemy introduit uniquement pour migrer (décision actée en amont).
- Le SQL reste lisible tel quel — décisif pour des politiques RLS, où toute
  couche d'abstraction masque ce qui compte.
- Le contrôle de checksum bloque la dérive : quelqu'un a édité une migration
  déjà passée en production.
- Une migration par transaction : jamais d'application partielle.

## Conséquence
Un fichier appliqué est immuable. Une correction = une nouvelle migration.

## Lien avec la suite
En P4, expand/contract et le refus de rollback sur migration destructive
s'appuieront sur cette base.
