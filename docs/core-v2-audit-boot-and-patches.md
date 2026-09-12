# SentriX Core V2 — Audit Phase 0, Part A+B : Architecture actuelle et carte des patchs

Document de cartographie uniquement. Aucun code n'a été modifié, aucun runtime retiré. Produit sur la branche `architecture/sentrix-core-v2`, à partir de l'état de `integration/music-multiprovider-v327` (PR #328, verte).

Méthode : exploration directe du code (main.py, railway_boot.py, cogs/__init__.py, utils/failover.py, utils/access_matrix.py), plus interrogation directe de l'API Railway (services réels, commandes de démarrage réelles, variables réellement configurées) pour ne pas se fier uniquement à la documentation interne — qui s'est révélée elle-même obsolète sur plusieurs points (voir §0).

---

## 0. Constat préalable : la documentation et la réalité déployée divergent déjà

Avant même de lister les patchs, un fait vérifié en interrogeant directement Railway (pas seulement le dépôt) :

| Source | Ce qu'elle affirme comme point d'entrée |
|---|---|
| `Procfile` / `Dockerfile` (`CMD`) | `python3 sentrix_v98_boot.py` |
| `docs/SENTRIX_FAILOVER_RAILWAY.md` (Start Command documenté, primary ET standby) | `python railway_ha_boot.py` |
| **Config Railway réelle du service `mon-bot-discord` (primary)** — vérifiée via l'API Railway | `python railway_ha_product_boot.py` |
| **Config Railway réelle du service `sentrix-standby`** — vérifiée via l'API Railway | `python sentrix_v98_ha_product_boot.py` |

Quatre affirmations différentes, trois sources différentes, aucune ne corrige les autres. C'est exactement le symptôme que ce projet Core V2 doit faire disparaître : il n'existe aujourd'hui aucun endroit unique où lire "voici ce qui démarre réellement en production."

Autres faits vérifiés directement via l'API Railway au moment de l'audit (2026-09-09), sans action prise :
- Le service `mon-bot-discord` tourne sur la branche `fix/v98-grouped-slash`.
- Un changement de configuration Railway est **actuellement en attente ("staged"), non appliqué** sur `mon-bot-discord` (39 variables) et `sentrix-standby` (35 variables) — ni accepté ni annulé par cette session, à traiter consciemment plutôt que laissé indéfiniment en suspens.
- Le projet contient aussi deux services non documentés dans `SENTRIX_FAILOVER_RAILWAY.md` : `sentrix-hosting-control-plane` et `sentrix-companion`.
- `deploy/standby/` contient des fichiers marqueurs texte (`v102-music-providers.txt`, `pr326-command-audit.txt`, etc.) qui semblent servir de suivi manuel de ce qui a été "synchronisé" vers le standby — un mécanisme de suivi non déclaratif, donc fragile.

---

## A. Architecture actuelle — du process Railway à `bot.start()`

### A.1 — Ce qui s'exécute AVANT même le script déclaré (`sitecustomize.py`)

Python importe automatiquement `sitecustomize.py` au démarrage de l'interpréteur, avant n'importe quel script. Ce fichier :
1. `_configure_railway_logging()` — filtre anti-inondation de logs (seulement si des variables `RAILWAY_*` sont présentes).
2. `_install_railway_dashboard_ha_proxy()` — si `SENTRIX_FAILOVER_ENABLED` est vrai, installe `web/dashboard_ha_proxy_v1.py` pour qu'un standby passif puisse proxyfier le dashboard vers le leader.
3. `_install_railway_dashboard_focus_ui()` — `web/dashboard_focus_loading_v1.py`.
4. `_install_sentrix_v95()` — `sentrix_v95_bootstrap.install()`.
5. `_install_sentrix_verification_v96()` — `sentrix_verification_v96.install()`.
6. `_install_sentrix_music_v102()` — `sentrix_music_providers_v102.install()`.

**Conséquence pour Core V2** : n'importe qui lisant `main.py` ou `railway_boot.py` de haut en bas ne découvrira jamais cette étape. C'est la couche la plus invisible de tout le boot.

### A.2 — Chaîne d'entrypoint réelle (primary, `railway_ha_product_boot.py`)

```
sitecustomize.py (implicite)
  → V95 bootstrap, V96 vérification, V102 musique
railway_ha_product_boot.py (déclaré côté Railway pour mon-bot-discord)
  → dashboard pré-start (sentrix_product_update + sentrix_final_product_finish)
  → import railway_ha_boot (patch commands.Bot.start pour attendre le lease HA)
      → import railway_boot
          → commands.Bot = SentriXAutoShardedBot   (AVANT `import main`)
          → import main as bot_main                 (définit EXTENSIONS, BotAllInOne, permissions)
          → bot_main.EXTENSIONS.append(...) × 21     (ordre exact, voir §A.4)
          → fusion CATEGORY_COMMANDS / PUBLIC_COMMANDS / KNOWN_PERMISSION_COMMANDS
  → V95 bootstrap re-confirmé explicitement (assert CommandTree.sync._sentrix_v95)
  → V97 fiabilité slash
  → V99 (grouped-slash-fix) — doit précéder V98 (capture v95._invoke_original)
  → V100 defer-fix puis V100 runtime-fix
  → V101 command runtime
  → V102 musique (re-confirmé)
  → V98 (reconstruit l'arbre slash groupé)
  → V96 vérification + finalizer dashboard
```

`railway_ha_boot.py` patch `BotAllInOne.start` pour appeler `coordinator.wait_for_leadership()` (lease Redis) AVANT le vrai `bot.start()` — sur le standby, tout le chargement de cogs ci-dessous ne se déclenche donc jamais tant que le lease n'est pas acquis. Le serveur HTTP `/health` démarre lui quand même plus tôt, donc le healthcheck Railway répond même standby.

### A.3 — Le service standby exécute un AUTRE fichier

`sentrix-standby` déclare `python sentrix_v98_ha_product_boot.py`, PAS le même fichier que le primary. Ce fichier fait `import railway_ha_product_boot as product_boot` (il enveloppe donc le primary) puis ajoute une couche `sentrix_v98_slash.install()`. Le standby n'exécute donc pas un code strictement identique au primary — il exécute primary + une couche en plus, sous un nom qui suggère (à tort) l'inverse ("V98" sonne plus récent, alors que c'est la variante SECONDAIRE réservée au standby).

`railway_canary_boot.py` n'est PAS le standby — c'est un troisième bot Discord entièrement séparé (exige `CANARY_BOT_TOKEN` distinct, base `database/canary.db` séparée, quitte toute guilde qui n'est pas `CANARY_GUILD_ID`). Aucune logique de lease/élection. Piège de nommage à connaître avant toute intervention HA.

### A.4 — Liste ordonnée complète des 48 extensions (primary)

```
 1 cogs.moderation                        15 cogs.minigames                  29 cogs.interaction_transport_guard
 2 cogs.automod                           16 cogs.games_economy              30 cogs.legacy_observability_conflict_guard
 3 cogs.security_tools                    17 cogs.music                      31 cogs.slash_reliability_v7
 4 cogs.tickets                           18 cogs.events                     32 cogs.automod_enable_all
 5 cogs.configuration                     19 cogs.giveaway_center            33 cogs.setup_auto_fix
 6 cogs.server_builder                    20 cogs.verification               34 cogs.setup_experience_v2
 7 cogs.logs                              21 cogs.stats                      35 cogs.emoji_name_lookup
 8 cogs.soundboard_logs                   22 cogs.owner                      36 cogs.emoji_unicode_asset_fix
 9 cogs.utility                           23 cogs.invites                    37 cogs.create_sentrix
10 cogs.guild_arrival                     24 cogs.design                     38 cogs.create_sentrix_v3
11 cogs.notifications                     25 cogs.embed_builder              39 cogs.canonical_interactions
12 cogs.ai                                26 sentrix_broadcast_dmall_visual  40 cogs.sentrix_plus
13 cogs.economy                           27 cogs.visual_experience_v5      41 cogs.sentrix_ultimate
14 cogs.levels                                                               42 cogs.plain_text_all_extension
                                                                              43 cogs.profile_oxyde_runtime
                                                                              44 cogs.deferred_context_response_guard
                                                                              45 cogs.slash_error_completion_guard
                                                                              46 cogs.final_stability_guard
                                                                              47 cogs.member_data_retention_v17
                                                                              48 cogs.sentrix_regression_fix
```
(1-27 : `main.py`. 28-48 : ajoutés par `railway_boot.py`, dans cet ordre exact.)

### A.5 — `cogs/__init__.py` : le vrai hub central

Dès le premier `bot.load_extension("cogs.moderation")`, Python doit d'abord exécuter `cogs/__init__.py`, qui :
1. Capture `_ORIGINAL_LOAD_EXTENSION = commands.Bot.load_extension`.
2. Remplace **la classe** `commands.Bot.load_extension` par une version qui, après CHAQUE extension : installe le budget de commandes slash, appelle `_install_extension_specific(bot, name)` (dispatch ~25 installs conditionnels selon le nom de l'extension), répare les signatures (`repair_wrapped_signatures`), et si `name == "cogs.visual_experience_v5"`, déclenche `finalize_runtime(bot)`.

**Constat critique confirmé** : le commentaire de `main.py` ("`cogs.visual_experience_v5` doit rester DERNIÈRE") vise en réalité `finalize_runtime()`. Or celle-ci se déclenche à la position 27 sur 48 — **21 extensions supplémentaires chargent ensuite**, en dehors de toute protection posée par `finalize_runtime()`. C'est la cause racine directe du Bug confirmé n°1 (voir le document technical-debt).

`finalize_runtime()` elle-même enchaîne, dans cet ordre exact : garde-fous communs → patchs de configuration critiques → annonces/serveur officiel → pile d'erreurs → vérification de preuve → `command_hardening_v41` → `production_ops` → `permission_guard` → `final_interaction_policy` → `command_error_release_v41` → aide officielle → `control_center_v3` (+langue) → V65 → V68 → V69 → V70 → V71 → V72 → V73 → V74 → V75 → hooks tardifs → `ban_command_whitelist` (explicitement "doit être installé en dernier").

### A.6 — La cascade `cogs.ai` (extension #12)

`cogs.ai` déclenche, via `cogs/__init__.py`, l'installation de `cogs/remove_code_command/__init__.py::install()` :

```
install_catalog → install_operations → install_mastery("cogs.ai") → install_readiness("cogs.ai")
  → install_resilience → install_custom_command_failsafe → install_v12_machine → install_v13_production
  → install_ai_api_hotfix → install_ai_reply_recovery
```
Puis une seconde passe différée, une seconde après `on_ready` : re-exécute uniquement `install_mastery("ready")` et `install_readiness("ready")` — pour couvrir les cogs chargés APRÈS `cogs.ai` (notamment `cogs.music`, #17).

**Constat** : il existe DEUX fichiers `cogs/remove_code_command.py` (module plat) et `cogs/remove_code_command/__init__.py` (paquet). Python préfère silencieusement le paquet — le module plat est du code **mort**, jamais exécuté, et pourtant modifié plus récemment que le paquet (quelqu'un édite du code qui ne s'exécute jamais).

### A.7 — Mécanisme HA réel (`utils/failover.py`)

Solide dans l'ensemble : lease Redis `SET NX EX ttl` (TTL 30s par défaut), renouvellement via un watchdog (`_watch_leadership`), fermeture immédiate de Discord si le lease est perdu (anti split-brain), restauration automatique du dernier snapshot PostgreSQL à la prise de leadership, garde anti-écrasement pour une ancienne instance "fencée" (`_guard_durable_snapshots`), et un mécanisme anti-ping-pong (un standby devenu leader cède la place au primary après un délai minimum plutôt que de se battre). Ce sont exactement les qualités demandées à la section 11 de la mission — la fondation existe déjà, elle a juste besoin d'être democumentée correctement (voir §0) et son admission de limite (RPO non nul, SQLite reste la source transactionnelle réelle) mérite d'être résolue, pas seulement documentée.

---

## B. Carte des patchs runtime

### B.1 — `commands.Bot` / instance Bot

| Fichier:ligne | Cible | Rôle | Ordre | Statut |
|---|---|---|---|---|
| `railway_boot.py:34` | `commands.Bot = SentriXAutoShardedBot` | Sharding avant `import main` | Avant tout | Actif (prod) |
| `railway_canary_boot.py:42` | `commands.Bot = CanaryBotBase` | Variante canary | Boot canary uniquement | Actif (canary) |
| `railway_ha_boot.py:337` | `BotAllInOne.start` | Attend le lease HA avant le vrai `start()` | Après import de `railway_boot` | Actif (HA) |
| `cogs/__init__.py:305-307` | `commands.Bot.load_extension` | **Le hub central** — dispatch tous les installs par extension | Avant la boucle `EXTENSIONS` de `main.py` | Actif, central |
| `sentrix_verification_v96.py:629-644` | `commands.Bot.load_extension` | Re-wrap (idempotent), s'enchaîne avec celui de `cogs/__init__.py` | Installé par `sitecustomize.py`, donc avant | Actif |
| `sentrix_music_providers_v102.py:283-305` | `commands.Bot.add_cog` | Injecte le résolveur multi-provider quand le cog "Music" est ajouté | Installé par `sitecustomize.py` | Actif |
| `utils/sentrix_runtime.py:395-409` | `commands.Bot.add_cog` | Corrige la signature de `+clear` après ajout de n'importe quel cog | Lazy, via `utils/__init__.py` | Actif |
| `cogs/final_interaction_policy.py:407` | `commands.Bot.invoke` | Normalise `ctx.command` vers sa racine | Dans `finalize_runtime()` | Actif — à vérifier isolément (pas de préservation de chaîne visible) |

Environ 10 `bot.add_check(...)` distincts empilés à travers `main.py` et plusieurs cogs (`bot_excellence_runtime`, `bot_mastery_runtime` ×2, `enterprise_suite`, `cooldown_isolation_fix`, `operations_center`, `v17_ai_economy_games`, `command_hardening_v41`) — usage légitime de l'API publique, mais la pile combinée mérite d'être auditée comme un tout avant Core V2.

### B.2 — `Command.callback` / `HybridCommand.callback`

Environ 35 sites de réaffectation de `.callback` confirmés (motif dominant du dépôt). Cas notables :
- `help_command.callback` réécrit par au moins **3 modules distincts** (`command_clarity.py`, `help_clean_style.py`, `language_runtime.py`), chacun se croyant l'autorité finale.
- `cogs/command_runtime_hardening_v18.py` (`repair_wrapped_signatures`) existe spécifiquement pour **réparer les dégâts collatéraux** causés par tous les autres réécrivains de `.callback` — appelé après CHAQUE chargement d'extension.
- Économie (`rob`, `gamble`, `withdraw`, `sell`) réécrite par `bot_excellence_runtime.py`.
- `+me`/`+profile` séparés par `profile_oxyde_runtime.py` (fonctionnellement voulu, mais montre le motif).
- Boutons UI (`discord.ui.Button.callback`) réécrits par `permission_setup_hardening_v65.py` pour les contrôles de Setup.

### B.3 — `app_commands.Command` / `CommandTree`

Chaîne `CommandTree.sync` : `sentrix_v95_runtime.py` (patch initial) ← `sentrix_v95_bootstrap.py` (variantes "safe") ← `sentrix_grouped_slash_fix.py` (V99, doit précéder V98) ← `sentrix_v100_runtime_fix.py` ← `sentrix_v101_command_runtime.py` ← `sentrix_v98_slash.py` (reconstruit l'arbre final groupé, dernier de la chaîne).

`cogs/hybrid_callback_resync.py` — réaligne `_callback` sur le `.callback` réel courant pour chaque `HybridCommand`/`HybridGroup`. Appelé une seule fois, **après** toute la boucle `EXTENSIONS` et **avant** `tree.sync()` — la dépendance d'ordre la plus critique du dépôt. Cette session a elle-même trouvé et corrigé 12 commandes divergentes juste avant (`ban, bot-status, clear, create-server, diagnostic, gamble, kick, mute, profile, rob, unban, warn`), preuve que ce motif produit des bugs réels, récurrents.

**`bot.tree.on_error` — au moins 5 réaffectations actives**, dont au moins deux remplacements durs (sans chaînage) : `cogs/final_interaction_policy.py` puis `cogs/final_error_embed_v5.py`. Voir le document technical-debt pour la trace complète — c'est aujourd'hui `final_error_embed_v5.py` qui gagne, mais rien ne le documente.

### B.4 — `commands.Context` (`.send`/`.reply`)

Chaîne légitimement conçue mais très profonde (~11 couches actives) : `reply_reference_fix` → `control_center_v3` → `community_v32/v33/v34` (trois passes successives de simplification) → `plain_response_policy` (dernier mot revendiqué) → `premium_style_runtime` → `setup_v2_core` → `v17_user_facing_hotfix` → `command_response_guard` → `deferred_context_response_guard` → panneaux visuels (`command_visuals`, `me_single_panel`, `profile_embed_guard`, `unified_command_panels`) → `final_interaction_policy`.

Contradiction directe trouvée : `cogs/reply_reference_fix.py` retire la référence de réponse Discord que `main.py::SentriXContext.send` a explicitement pour but d'ajouter.

### B.5 — `discord.Interaction` / `InteractionResponse`

~8 réaffectations actives (`defer`, `send_message`, `edit_message`, `edit_original_response`). Les patchs V100 (installés très tôt, à l'import) rendent `defer()` idempotent et gèrent la double-réponse ; les cogs installés plus tard (`community_v34`, `final_interaction_policy`, `plain_response_policy`, `premium_style_runtime`, `setup_v2_core`, panneaux visuels) enveloppent correctement ces gardes V100 — chaîne globalement saine, mais à re-vérifier ligne par ligne pour `final_interaction_policy.py` spécifiquement (module déjà pris en flagrant délit de remplacement dur ailleurs, §B.3).

### B.6 — Gestion d'erreur (au-delà de `tree.on_error`)

Voir le document technical-debt pour la trace complète et vérifiée (quel handler gagne réellement, quel code est mort). Résumé : `main.py::on_command_error` (riche, français, détaillé) est du code mort en production, silencieusement remplacé par une chaîne qui finit par `cogs/final_error_embed_v5.py`, lequel ne journalise **aucune trace** pour les erreurs génériques non prévues.

### B.7 — Mutations globales de `main.py` (données, pas méthodes)

`railway_boot.py` étend `EXTENSIONS`, `CATEGORY_COMMANDS`, `PUBLIC_COMMANDS`, `KNOWN_PERMISSION_COMMANDS` après l'import de `main`. `railway_boot.py` et `railway_canary_boot.py` remplacent aussi `bot_main.start_dashboard` par un no-op (le dashboard démarre plus tôt, avant `bot.start()`, pour que `/health` réponde avant que Discord soit prêt).

### B.8 — Réécriture croisée de méthodes d'autres modules

Cas le plus agressif trouvé : `cogs/permission_setup_hardening_v65.py` réécrit CINQ fonctions/méthodes dans quatre modules différents (`access_matrix.evaluate`, `access_matrix.help_requirement`, `permission_guard.evaluate` + sa propre référence à `access_matrix.evaluate`, `setup_v2_core.set_role_command_decision`, et le constructeur de `SetupView`), puis installe un `guarded_init` qui **se réapplique lui-même** à chaque nouvelle instance de `SetupView` pour survivre à toute réécriture future de la classe. Vérifié correctement chaîné (pas de bug trouvé), mais c'est le patch le plus difficile à raisonner du dépôt.

Famille `cogs/runtime_finish_v84.py` → `v94.py` (10 fichiers) : quasi certainement 90% redondants entre eux ; l'un d'eux réécrit `cogs.run_late_runtime_hooks` (la fonction du PAQUET `cogs` lui-même) pour garantir sa propre exécution en dernier — motif méta, un niveau au-dessus de tout le reste.

---

## Ce que ce document ne couvre PAS encore

- Le dossier `web/` (dashboard) n'a pas été audité en profondeur dans cette passe — recommandé avant la Phase 4 (services) si elle touche la configuration exposée au dashboard.
- Les 64 scripts `tools/*_gate.py`/`*_audit.py` sont des vérificateurs CI statiques, jamais importés par le runtime — hors sujet pour ce document, mais leur existence (et leur nombre) est elle-même un signal de dette : autant de gardes qu'il a fallu construire pour compenser l'absence d'architecture unifiée.

Voir `docs/core-v2-audit-technical-debt.md` pour le classement des 20 problèmes les plus importants, et `docs/core-v2-plan.md` pour l'architecture cible et le plan de migration.
