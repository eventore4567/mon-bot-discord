# ADR 0002 — Contexte tenant : transaction-local et fail-closed

Statut : accepté (P0)

## Contexte
PgBouncer en mode transaction recycle les connexions entre transactions. Un
`SET` persistant fuit donc vers la transaction suivante — donc vers un autre
tenant. Faille d'isolation totale, silencieuse, très difficile à diagnostiquer
après coup.

Un second piège PostgreSQL existe avec les paramètres personnalisés : après un
`SET LOCAL` terminé, le nom du GUC peut rester connu de la connexion avec une
**chaîne vide** comme valeur. Une politique qui suppose que « contexte absent =
`current_setting()` lève toujours 42704 » dépend alors de l'historique de la
connexion.

## Décision
1. `SELECT set_config('app.current_org', $1, true)` uniquement, dans une
   transaction explicite. `is_local=true` équivaut à `SET LOCAL`, mais accepte
   un paramètre — donc pas d'interpolation de chaîne sur un chemin critique.
2. Cette logique vit exclusivement dans `libs/db`.
3. Les politiques RLS n'appellent jamais `current_setting()` directement. Elles
   utilisent `public.sentrix_current_org()`. Ce helper lit le GUC avec
   `missing_ok=true`, traite **NULL et chaîne vide** comme « contexte absent »,
   puis lève explicitement SQLSTATE **42704**. Le résultat est déterministe sur
   une connexion neuve comme sur une connexion réutilisée.
4. `FORCE ROW LEVEL SECURITY` partout, sinon le propriétaire contourne RLS.
5. `WITH CHECK` autant que `USING`, sinon un tenant peut écrire chez son voisin
   sans jamais pouvoir le relire.

## Conséquence
Défaillance fermée : un bug qui oublie de poser le contexte produit une erreur
bruyante. Le test de pooling force la réutilisation du même backend et vérifie
que la valeur du tenant précédent a disparu, puis qu'une requête RLS sans
contexte lève 42704.

Les garde-fous statiques dans `tests/unit/test_no_persistent_set.py` interdisent
aussi toute pose du contexte hors de `libs/db` et tout `set_config(..., false)`.
