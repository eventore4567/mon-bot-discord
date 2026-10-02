# SentriX — Phase 10 + Phase 11

Date: 2026-10-02

## Phase 10 — applications connectées

Cette phase utilise uniquement les intégrations qui apportent une vérification ou une
trace utile au produit.

- **GitHub** : travail isolé sur `sentrix-phase-10-11`, PR dédiée et GitHub Actions.
- **Railway** : reste l'autorité pour le build Docker, le healthcheck, les logs HA et le
  déploiement final après fusion vers `dashboard-refonte-2026-09`.
- **Linear** : le suivi P1 de la publication slash reste rattaché à SEN-5 et sera mis à
  jour avec le résultat réel de la phase.
- **Airtable** : `SentriX Command Inventory` reçoit l'inventaire vérifié des commandes
  après l'audit final.
- **Notion** : la page d'architecture SentriX reçoit le compte rendu final de la phase.
- **Figma** : aucune écriture pendant cette phase, car aucune modification visuelle ou de
  design system n'est nécessaire.
- **Trello** : aucune duplication de suivi ; Linear reste la source de vérité technique.
- **Supabase** : aucune migration. La phase ne requiert aucun changement de schéma ou de
  stockage, donc ajouter une migration augmenterait le risque sans bénéfice produit.

Aucun secret, token, domaine ou donnée de production n'est modifié.

## Phase 11 — matrice de régression

Le workflow `.github/workflows/phase-11-regression.yml` vérifie six domaines en
parallèle :

1. commandes, arbre slash, permissions et compatibilité des commandes `+`;
2. musique, fournisseurs, playlists et persistance vocale;
3. tickets et modération;
4. économie, niveaux et jeux;
5. dashboard et UX produit;
6. contrats de release et compatibilité historique.

La PR exécute également le workflow **SentriX Command Sweep**, qui conserve les audits
stricts des commandes et permissions.

## Critères de fusion

La fusion n'est autorisée qu'après validation des points suivants :

- matrice Phase 11 verte;
- Command Sweep sans erreur technique bloquante;
- aucune divergence critique dans le registre slash;
- après fusion, build Railway primary et standby en succès;
- audit runtime final : zéro critique et zéro avertissement;
- comparaison locale/distante Discord sans chemin manquant ou inattendu;
- `/aide` publié et ancien `/help` absent;
- aucune régression sur `/musique`, playlists ou persistance vocale.
