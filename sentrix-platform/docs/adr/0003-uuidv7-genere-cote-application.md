# ADR 0003 — Identifiants : UUIDv7 générés côté application

Statut : accepté (P0)

## Décision
UUIDv7 (RFC 9562) générés en Python, pas par PostgreSQL.

## Justification
- Triables temporellement : bon comportement des index B-tree, contrairement à
  UUIDv4 qui fragmente.
- Aucune fuite d'information séquentielle, contrairement à un entier
  auto-incrémenté (un client ne peut pas déduire le volume d'activité).
- `uuidv7()` natif n'existe qu'à partir de PostgreSQL 18. Générer côté
  application rend le projet portable dès PostgreSQL 16.
- L'identifiant est connu avant l'INSERT : utile pour l'audit et
  l'idempotence des opérations à venir (P4).

## Conséquence
`libs/ids` est la seule source d'identifiants. Conformité RFC vérifiée par
`tests/unit/test_ids.py` (bits de version et de variant, encodage 48 bits de
l'horodatage, ordre, unicité).
