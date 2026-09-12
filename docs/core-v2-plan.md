# SentriX Core V2 — Audit Phase 0, Part D+E+F+G : Architecture cible, plan de migration, risques, tests

Prérequis de lecture : `docs/core-v2-audit-boot-and-patches.md` (architecture actuelle, carte des patchs) et `docs/core-v2-audit-technical-debt.md` (20 problèmes classés, dont deux bugs vivants confirmés).

**Rappel du mandat pour ce document** : diagnostic et plan uniquement. Aucune ligne de code Core V2 n'est écrite ici, aucun runtime n'est retiré, aucun merge ni déploiement. Ce document sert de base pour une autorisation explicite avant de commencer la Phase 1.

---

## D. Architecture cible Core V2

```
core/
    commands/       # Registre canonique : un handler métier par fonctionnalité,
                     # les deux transports (+/) appellent le même handler.
    permissions/     # access_matrix.py déplacé/étendu ici ; ajoute explain().
    errors/          # Pipeline d'erreur unique : codes SXR-xxxx, capture structurée,
                     # message utilisateur propre, trace serveur complète.
    observability/   # Compteurs/latences/percentiles par commande+transport.
    health/          # /health, /ready — process, event loop, DB, Discord, leader.
    ha/              # utils/failover.py promu ici, inchangé en Phase 0-1.

services/
    moderation.py    # validate -> permission -> hierarchy -> execute -> persist -> log -> DM
    tickets.py
    economy.py
    levels.py
    music/           # utils/music/ existe déjà et est déjà sain — relocalisation tardive, pas de réécriture
    ai.py            # enveloppe utils/ai_service.py existant
    guild_settings.py # settings.get(guild_id, "tickets.max_open") / .set(...), cache + invalidation

database/
    repositories/    # un repository par agrégat (tickets, économie, niveaux, sanctions...)
    migrations/      # 0001_initial.sql, runner de migration réel, dry-run, garde de compatibilité

cogs/
    moderation.py    # devient un adaptateur Discord fin : parse ctx/interaction, appelle le service, rend le résultat
    tickets.py
    music.py
    ...
```

### Principe non négociable

Core V2 se construit **à côté** du runtime existant, jamais à sa place, tant qu'un test ne prouve pas l'équivalence de comportement. Chaque module legacy listé dans la carte des patchs reste en place jusqu'à preuve du contraire — voir Phase 6.

### Pourquoi cette structure et pas une autre

- `core/` porte ce qui est transverse à TOUTES les fonctionnalités (comment une commande s'exécute, comment une permission se décide, comment une erreur se rapporte) — c'est la partie qui doit avoir une seule implémentation, un seul testeur.
- `services/` porte la logique métier pure, sans type discord.py dans les signatures (`ban_handler(guild_id: int, actor_id: int, target_id: int, reason: str) -> BanResult`, pas `ban_handler(ctx: commands.Context, ...)`) — ça permet de tester le métier sans jamais instancier Discord, et ça garantit qu'un même handler sert `+ban` et `/ban` sans lecture supplémentaire.
- `cogs/` redevient ce qu'un cog devrait être : un traducteur Discord ↔ service, pas un porteur de logique.
- `database/repositories/` isole les requêtes SQL du reste — aujourd'hui chaque cog interroge `database/db.py` ou ses propres tables directement ; un repository par agrégat rend chaque migration de schéma localisable.

---

## E. Plan de migration par phases

Chaque phase est additive, indépendamment testable, et ne retire rien. Une phase ne commence pas tant que la précédente n'est pas mergée et stable.

### Phase 0 — Cartographie (ce document, terminé)

Livré : architecture actuelle, carte des patchs, 20 problèmes classés. Aucune action de code.

**Décision à prendre par toi avant Phase 1** : les deux bugs vivants confirmés (permission `/sentrixpro`, absence de trace d'erreur) peuvent être corrigés isolément, hors du calendrier Core V2, si tu le souhaites — ce sont des correctifs d'une portée minuscule (quelques lignes chacun) qui ne dépendent d'aucune des phases suivantes. Ou ils peuvent attendre la Phase 1/3 respectivement, où ils seront de toute façon traités en premier. Les deux options sont raisonnables ; c'est un choix de séquencement, pas d'architecture.

### Phase 1 — Observabilité

- `core/observability/` : compteurs et latences par commande+transport, en **écoute passive** (listener additionnel, pas un remplacement de patch existant) — aucune commande existante ne change de comportement.
- `core/errors/` : génère un identifiant `SXR-CMD-xxxx`, journalise la trace complète côté serveur, et **un seul fichier existant** (`cogs/final_error_embed_v5.py`, l'autorité réelle confirmée) est modifié pour appeler ce nouveau module au lieu de gérer la mise en forme lui-même. Corrige au passage la lacune #2 (traces manquantes).
- `/diagnostic` (section 9 de la demande) : lecture seule, aucune mutation d'état.
- Logs structurés (`event=command_execute command=ban transport=slash guild=123 latency_ms=184 success=true`) : nouveau format utilisé par le nouveau code, migration opportuniste de l'existant, pas obligatoire.

### Phase 2 — Command Core (en parallèle, une famille à la fois)

- Construire `core/commands/` comme chemin **parallèle**. Commencer par UNE famille à faible risque et haute valeur de preuve — `ban` est un bon choix (déjà identifié cette session comme ayant divergé entre `+`/`/`, donc la preuve de correction sera visible).
- Extraire `moderation_service.ban(guild_id, actor_id, target_id, reason) -> BanResult` en fonction pure, sans type discord.py.
- `+ban` et `/ban` deviennent deux adaptateurs fins appelant la même fonction.
- Flag de fonctionnalité **par famille**, pas global : `COMMAND_CORE_V2_BAN=true`, pour qu'un rollback ne touche qu'une commande.
- Répéter, en priorisant les 12 commandes déjà connues comme ayant divergé (`ban, bot-status, clear, create-server, diagnostic, gamble, kick, mute, profile, rob, unban, warn`).

### Phase 3 — Permissions

- Corriger d'abord (si pas déjà fait en Phase 0) le motif structurel derrière le Bug #1 : soit balayer les décorateurs redondants après CHAQUE chargement d'extension plutôt qu'une seule fois, soit l'interdire par CI (`tools/permission_coverage_gate.py` est le bon candidat pour porter cette règle).
- Rendre explicite le branchement du check préfixe : `permission_guard.install()` doit appeler `bot.add_check()`/`remove_check()` lui-même, plutôt que de compter sur `main.py` pour ramasser un attribut d'instance déjà réaffecté (corrige le problème #6).
- Livrer `/permissions explain <commande> [@membre]` — enveloppe fine autour de `access_matrix.evaluate()` existant, aucune nouvelle logique de décision.
- Supprimer les copies locales de `PUBLIC_COMMANDS`/`OWNER_ONLY_COMMANDS`/`CATEGORY_COMMANDS` dans `main.py` et `cogs/setup_v2_core.py` ; tout consommateur lit `utils/access_matrix.py` directement (corrige la dérive #16).

### Phase 4 — Services métier

- Extraire `ModerationService` en premier (spécification déjà détaillée à la section 17 de la demande initiale : `validate -> permission -> hierarchy -> execute -> persist -> log -> DM`, avec la règle explicite qu'un échec du log ne doit jamais transformer une sanction Discord réussie en échec rapporté).
- Puis `TicketService`, `EconomyService`, `LevelsService`, `GuildSettingsService` — même patron : nouvelle fonction pure + flag + test parallèle + rodage + suppression de l'ancien chemin seulement après preuve.
- `AIService` : `utils/ai_service.py` a déjà l'essentiel de la logique ; le travail ici est surtout de garantir qu'aucun cog n'appelle directement l'API OpenAI en contournant le service.

### Phase 5 — Base de données

- `database/migrations/` : une vraie moteur de migration, versionné, avec dry-run et garde de compatibilité de schéma au démarrage.
- Migration `0001_initial` : no-op qui enregistre juste le schéma actuel comme référence — n'touche aucune donnée, sert de point de départ propre pour toute migration future.
- `database/repositories/` : un par agrégat, construits au fil de la Phase 4 (chaque service qui migre construit son repository en même temps).
- `/diagnostic database` (version attendue / version actuelle / migrations manquantes).

### Phase 6 — Suppression du legacy

Ne commence, module par module, que lorsque : (a) un test prouve que Core V2 couvre exactement le comportement utile du patch legacy correspondant, et (b) `tools/command_permission_group_consistency_audit.py`-style tooling confirme qu'aucune commande ne redevient fail-closed par accident. Non entamée dans ce plan — décision explicite à reprendre une fois les Phases 1-5 stables.

---

## F. Risques par sous-système

- **Slash** : la chaîne `CommandTree.sync` (V95→V97→V99→V100→V101→V102→V98, puis `hybrid_callback_resync` juste avant `tree.sync()`) est la dépendance la plus critique du dépôt. Tout changement Core V2 touchant la construction de commandes doit passer par le même point d'accroche final (`_add_grounded_surface`), jamais le contourner — et être vérifié par un diff de `bot.tree.get_commands()` avant/après (motif déjà utilisé par plusieurs `tools/*_gate.py` existants).
- **Préfixe** : le problème #6 (check de permission dépendant de l'ordre de chargement) rend tout refactor de `setup_hook()` risqué sans un test qui affirme explicitement QUEL objet fonction est réellement enregistré après le boot.
- **Tickets/IA** : risque plus faible, sous-systèmes relativement propres déjà. Vigilance principale : ne jamais laisser un service Core V2 et son cog legacy détenir chacun leur propre état pendant la transition (double source de vérité temporaire).
- **Musique** : le moteur (`utils/music/`) vient d'être entièrement réécrit cette session avec une architecture déjà proche de la cible Core V2 (fournisseurs indépendants, pas de couplage Discord dans la logique de résolution). Le travail Core V2 ici sera surtout un déplacement de dossier, pas une réécriture.
- **Permissions** : le Bug #1 signifie qu'il ne faut pas supposer le comportement actuel entièrement correct avant d'y bâtir dessus. Le premier test de la Phase 3 doit vérifier, pour CHAQUE commande à palier de catégorie, qu'un rôle autorisé via Setup obtient effectivement l'accès — pas seulement un échantillon.
- **Dashboard** : `web/` n'a pas été audité en détail dans cette passe (les agents se sont concentrés sur le runtime Discord). Recommandé : une passe dédiée avant que la Phase 4 ne touche la configuration exposée au dashboard.
- **HA** : toute modification du boot (`main.py`/`railway_boot.py`) doit être testée contre LES DEUX entrypoints réels (`railway_ha_product_boot.py` primary et `sentrix_v98_ha_product_boot.py` standby), qui ne sont pas des fichiers identiques (voir document boot-and-patches, §A.3) — un changement validé seulement côté primary pourrait casser silencieusement le standby.

---

## G. Tests requis par phase

- **Phase 1** : tests unitaires purs pour les compteurs d'observabilité (aucun Discord nécessaire) ; test de fumée "`/diagnostic` ne plante pas" ; test de régression sur les codes d'erreur (lever une exception connue, vérifier que LE MÊME code apparaît dans les logs serveur ET dans le message Discord rendu).
- **Phase 2** : par famille de commande migrée — test unitaire pur du handler extrait (sans type discord.py) ; test que `+commande` et `/commande` produisent un résultat identique pour la même entrée logique (cible directement la classe de bug `+`/`/` divergents) ; comparaison "ancienne décision vs nouvelle décision" pendant la période de rodage.
- **Phase 3** : test dédié à la classe de bug `/sentrixpro` — itérer chaque commande à palier de catégorie dans un scénario "autorisé via Setup mais pas admin", vérifier que la décision d'`access_matrix` est bien celle appliquée.
- **Phase 4** : tests de cycle de vie complet par service, à la manière de la section 24 de la demande initiale (ticket : ouverture → catégorie → permissions → accès rôle staff → logs → claim → fermeture → note), exécutés sur deux serveurs simultanément (section 25).
- **Phase 5** : tests du moteur de migration (applique sur base vierge, vérifie le schéma final ; démarrage avec un schéma plus récent que celui attendu par le code doit refuser de démarrer proprement, jamais corrompre).
- **Phase 6** : pour chaque patch legacy proposé à la suppression, un test prouvant que Core V2 couvre exactement son comportement observable — c'est la condition de suppression elle-même, pas une vérification a posteriori.

---

## Prochaine étape

Ce document clôt la Phase 0 telle que demandée. Aucune Phase 1 ne démarre sans ton accord explicite — et notamment ta décision sur les deux bugs vivants (correctif isolé immédiat, ou intégré à la Phase 1/3).
