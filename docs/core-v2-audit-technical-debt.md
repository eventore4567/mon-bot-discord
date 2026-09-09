# SentriX Core V2 — Audit Phase 0, Part C : Dette technique classée

Vingt problèmes, classés par sévérité réelle (bugs vivants confirmés d'abord, puis risques structurels). "Confirmé" signifie tracé jusqu'au comportement d'exécution réel (pas seulement lu dans un docstring) — voir `docs/core-v2-audit-boot-and-patches.md` pour la méthode.

Ces deux premiers points sont des **bugs vivants**, indépendants de la migration Core V2 elle-même. Ils sont documentés ici pour rester dans le rythme "audit d'abord", mais un correctif ciblé et isolé serait possible sans attendre la Phase 3 si tu le souhaites — c'est une décision séparée de l'autorisation de migration.

## 1. [BUG VIVANT CONFIRMÉ] Contournement de permission sur `/sentrixpro`

`cogs/sentrix_ultimate.py` décore encore `pro_security`, `pro_lockdown`, `pro_quarantine`, `pro_live`, `pro_notifications`, `pro_welcome` avec `@commands.has_guild_permissions(manage_guild=True)`. Le nettoyage censé retirer ces décorateurs redondants (`permission_guard.py::_strip_redundant_local_checks`) ne s'exécute **qu'une seule fois**, avant que `cogs.sentrix_ultimate` ne soit chargé (celui-ci arrive en position 41/48, ajouté par `railway_boot.py`, bien après `finalize_runtime()`). Discord exige que TOUS les checks (globaux + locaux) passent — donc un propriétaire de serveur qui autorise explicitement un rôle non-admin via Setup à utiliser `/sentrixpro security` (exactement la fonctionnalité que `access_matrix.py` existe pour permettre) se verra quand même refusé, à cause de ce décorateur jamais balayé. Mêmes résidus trouvés (non encore vérifiés un par un) dans `bot_tracker.py`, `security_runtime_hardening.py`, `rolepanel_notifications.py`, `sentrix_v21.py`, `utility.py`.

**Pourquoi c'est grave** : c'est une incohérence de sécurité dans les deux sens — trop restrictif ici, mais le motif général (décorateur local non balayé) pourrait tout aussi bien être trop permissif ailleurs sans qu'on le sache.

## 2. [LACUNE VIVANTE CONFIRMÉE] Aucune trace journalisée pour les erreurs génériques

Le gestionnaire d'erreur réellement actif aujourd'hui (`cogs/final_error_embed_v5.py`, voir #3) ne journalise le type d'exception ou la trace Python QUE si l'envoi du panneau d'erreur lui-même échoue. Une `ValueError` (ou n'importe quelle exception non explicitement prévue) levée dans une commande produit un message propre côté utilisateur — bien — mais **zéro trace exploitable côté serveur**, seulement un compteur anonyme dans `production_command_metrics`. Ceci contredit directement l'objectif de la section 7 de la mission (retrouver la stack trace exacte à partir d'une référence `SXR-xxxx`) : cette référence n'existe même pas aujourd'hui, et la trace qu'elle est censée pointer n'est jamais écrite.

## 3. Chaîne de gestionnaires d'erreur avec remplacements durs (non chaînés)

`main.py::on_command_error/on_app_command_error` (riche, détaillé) est du code mort — remplacé silencieusement par une chaîne qui traverse `bot_excellence_runtime` (chaîné correctement) → `error_experience_v3` (chaîné correctement) → `final_interaction_policy` (**remplacement dur**, chaîne cassée) → `command_error_release_v41` (chaîné) → `slash_error_completion_guard` (chaîné) → `final_error_embed_v5` (**remplacement dur final**, gagnant réel). Conséquence fonctionnelle confirmée, pas seulement théorique : le message d'accueil personnalisé pour `RuntimeRateLimitError` et l'auto-matchmake sur `+tictactoe` sans adversaire (tous deux dans `bot_excellence_runtime.py`) ne se déclenchent plus jamais.

## 4. Quatre déclarations différentes du point d'entrée Railway réel

Voir `docs/core-v2-audit-boot-and-patches.md` §0 : Procfile/Dockerfile, documentation interne, configuration réelle du service primary et configuration réelle du service standby pointent chacun vers un fichier différent. Aucune des trois sources ne se corrige elle-même.

## 5. Contrat "doit charger en dernier" violé en production

`cogs.visual_experience_v5` (qui déclenche `finalize_runtime()`) charge en position 27/48 ; 21 extensions supplémentaires chargent ensuite, hors de portée des protections que `finalize_runtime()` est censée garantir. Cause racine directe du Bug #1.

## 6. Le check de permission préfixe ne fonctionne que par accident d'ordre de chargement

`main.py:474` fait `self.add_check(self.global_permission_check)` **après** la boucle de chargement des extensions. Mais `cogs/permission_guard.py`, installé PENDANT cette boucle, a déjà réaffecté l'attribut d'instance `bot.global_permission_check`. Résultat : la méthode définie dans `main.py` (lignes 539-552) ne s'exécute jamais — mais rien ne le signale, et un futur refactor anodin (déplacer les trois lignes `add_check`) romprait silencieusement ce fonctionnement sans qu'aucun test actuel ne le détecte.

## 7. `help_command.callback` réécrit par au moins 3 modules distincts

`command_clarity.py`, `help_clean_style.py`, `language_runtime.py` — chacun se pense l'autorité finale sur `+help`. Risque réel de régression silencieuse au moindre changement d'ordre de chargement.

## 8. `Context.send` (~11 couches) et `InteractionResponse` (~8 couches) empilées

Chaîne de middleware légitime en principe, mais bien trop profonde pour être raisonnée. Contradiction directe trouvée : `cogs/reply_reference_fix.py` retire la référence de message que `main.py::SentriXContext.send` ajoute explicitement.

## 9. `bot.tree.on_error` réaffecté par au moins 5 modules actifs

Dont deux remplacements durs. Le vainqueur réel (`final_error_embed_v5.py`) correspond à son propre docstring ("autorité finale"), donc le comportement actuel est probablement voulu — mais rien dans les 4 autres modules ne signale qu'ils sont devenus inertes, et `cogs/command_response_guard.py` affirme même, à tort, dans son propre docstring, que `error_experience_v3 + main.py` sont "l'unique propriétaire" des messages d'erreur.

## 10. Un patch qui se réapplique lui-même pour survivre aux patchs futurs

`cogs/permission_setup_hardening_v65.py::guarded_init` réécrit `SetupView.__init__` puis se réinjecte à chaque nouvelle instance. Vérifié correct aujourd'hui, mais c'est le motif le plus fragile du dépôt — un futur mainteneur qui ignore ce mécanisme pourrait facilement croire qu'écraser `SetupView.__init__` une fois suffit.

## 11. Deux fichiers `remove_code_command` — l'un mort, activement modifié

`cogs/remove_code_command.py` (module plat) est en permanence masqué par `cogs/remove_code_command/__init__.py` (paquet) à cause de la résolution d'import de Python. Le fichier mort a pourtant une date de modification plus récente que le paquet vivant.

## 12. `sitecustomize.py` installe des patchs de manière invisible

V95, V96 et V102 s'installent avant que n'importe quel point d'entrée déclaré ne s'exécute, via l'auto-import implicite de `sitecustomize` par Python. Ce n'est documenté nulle part dans le code applicatif.

## 13. Famille `runtime_finish_v84` → `v94` (10 fichiers quasi redondants)

L'un d'eux réécrit `cogs.run_late_runtime_hooks` (la fonction du PAQUET lui-même) pour garantir son propre ordre d'exécution — motif méta, un niveau au-dessus de tous les autres patchs trouvés.

## 14. Convention du dépôt : neutraliser plutôt que supprimer

`cogs/production_observability_v9.py` est mort, neutralisé explicitement par un AUTRE module (`legacy_observability_conflict_guard.py`) plutôt que supprimé. C'est la stratégie de retrait par défaut du projet — elle garantit une accumulation monotone de dette, jamais sa réduction.

## 15. Duplication `+`/`/` — le problème fondateur, confirmé à grande échelle

~35 sites réécrivent `.callback`, nécessitant `repair_wrapped_signatures` après CHAQUE extension et `hybrid_callback_resync` une fois à la toute fin avant `tree.sync()`. Cette session elle-même a trouvé 12 commandes divergentes en une seule passe (`ban, bot-status, clear, create-server, diagnostic, gamble, kick, mute, profile, rob, unban, warn`) — preuve empirique, pas hypothèse, que ce motif casse des choses régulièrement.

## 16. Copies locales de `main.py` déjà en dérive par rapport à `access_matrix.py`

`main.py::OWNER_ONLY_COMMANDS` manque `logs-diag` et `reset-logs-all`, présents dans la copie de `access_matrix.py`. Conséquence aujourd'hui : fuite d'information cosmétique dans les suggestions "vouliez-vous dire" (pas un contournement d'exécution, `access_matrix.evaluate()` reste correct) — mais la dérive elle-même est la preuve vivante que deux copies du même ensemble de données divergent silencieusement dès qu'on ne force pas une source unique.

## 17. `/permissions explain` n'existe pas

Seuls des scripts CI hors-ligne existent (`tools/audit_permissions.py`, `tools/permission_matrix_gate.py`, etc.). Aucun outil interactif n'aurait permis de détecter le Bug #1 en production avant qu'un utilisateur ne le signale.

## 18. Aucun système de migrations de base de données

Pas de `database/migrations/`. Le schéma évolue via des `CREATE TABLE IF NOT EXISTS` dispersés dans chaque module au démarrage, sans version, sans dry-run, sans garde contre un schéma incompatible.

## 19. HA solide mais RPO non nul et documentation non synchronisée avec le déploiement réel

`utils/failover.py` est du bon travail (lease TTL, watchdog, anti-split-brain, anti-ping-pong, garde anti-écrasement). Mais : (a) PostgreSQL n'est qu'un instantané périodique (300s par défaut), SQLite reste la source transactionnelle réelle — une perte des toutes dernières écritures reste possible lors d'un crash brutal, limite déjà documentée par le projet lui-même ; (b) la documentation de la procédure de bascule référence une commande de démarrage qui ne correspond à aucun des deux services réels (voir #4) — donc en suivre les étapes littéralement, aujourd'hui, échouerait.

## 20. Changement de configuration Railway en attente, non résolu

39 variables modifiées en attente sur `mon-bot-discord`, 35 sur `sentrix-standby` (statut "STAGED"), découvert en consultant directement l'API Railway pendant cet audit. Ni accepté ni rejeté par cette session. À traiter consciemment — laisser une configuration "en attente" indéfiniment est une autre forme de dérive entre "ce qui est configuré" et "ce qui tourne réellement", exactement le type de flou que ce projet Core V2 vise à éliminer.

---

## Signaux structurels additionnels (non classés individuellement, mais pertinents pour la Phase 0)

- 260 fichiers dans `cogs/`, 174 fichiers de tests, 27 scripts à la racine.
- Au moins trois chaînes de méta-installation concurrentes au-delà de `cogs/__init__.py` : `bot_v17_major.py` (11 installs chaînés), `shop_default_prices.py` (11), `stability_runtime.py` (catch-all exécuté à CHAQUE chargement d'extension, lui-même chaînant 7 installs).
- `railway_canary_boot.py` est un troisième bot Discord entièrement indépendant, pas le standby — piège de nommage pour quiconque suppose qu'il n'existe que primary/standby.
- 64 scripts `tools/*_gate.py`/`*_audit.py` : autant de garde-fous statiques qu'il a fallu construire pour compenser l'absence d'une architecture qui empêcherait ces régressions à la source. Leur nombre est lui-même un indicateur de dette, pas seulement un filet de sécurité (positif).

Voir `docs/core-v2-plan.md` pour l'architecture cible, le plan de migration par phases, les risques par sous-système et les tests requis.
