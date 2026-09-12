# SentriX Core V2 — Suivi des Milestones (transformation produit)

Suite à `docs/core-v2-audit-technical-debt.md` (audit de dette technique) et à
l'audit de maturité produit (comparaison Dyno/Carl-bot/ProBot/MEE6/Ticket
Tool), ce document suit l'avancement des 5 milestones de la roadmap produit.
Chaque entrée renvoie au commit réel — ce fichier documente ce qui EXISTE,
pas une intention.

## Milestone 1 — SentriX Core Reliability : **complet**

- **Migrations DB réelles** (`database/migrations.py`, commit `6b7e271`) :
  réconciliation additive générique sur les ~79 tables (compare le schéma
  cible — les mêmes chaînes `SCHEMA`/`GAME_TRANSACTIONS_SCHEMA`/
  `LOG_CONFIG_SCHEMA` déjà exécutées à chaque boot — au schéma réel, ajoute
  les colonnes manquantes) + infrastructure de migrations numérotées
  (`schema_migrations`, vide pour l'instant). Tourne à chaque
  `Database.connect()`, boot normal ET reprise HA après restauration.
- **`PRAGMA busy_timeout=5000`** sur la connexion principale (`63d9282`).
- **Test de smoke-boot** (`tests/test_boot_smoke.py`, `63d9282`) : charge
  réellement les 51 extensions et échoue si une seule casse.
- **`tools/deployment_status.py`** (`dea6d4b`) : compare le HEAD git local au
  commit réellement déployé, lu depuis `/health`.

## Milestone 2 — Configuration Platform : **complet**

- **Registre central des modules** (`core/modules/registry.py` +
  `core/modules/definitions.py`, `5c613b7`) : façade de lecture sur 8 modules
  (moderation, automod, tickets, verification, logs, welcome, levels, ai),
  lue depuis les tables déjà existantes — ne remplace aucun stockage.
- **`/setupdiag`** (`cogs/setup_diagnostics.py`, `d2dd3f7`) : rend ce registre
  visible sans toucher au rendu fragile de `/setup` (12 couches de
  monkeypatch sur `SetupView`). Même garde de permission que `/setup`
  (`_can_setup`, importé verbatim).
- **Audit trail dashboard réparé** (`51efa14`) : le mécanisme générique
  existait déjà (`web/operations_center.py::_wrap_existing_writes`) mais sa
  table n'était jamais créée en production (cog propriétaire jamais chargé)
  et son contenu était vide de tout détail. `dashboard_audit_log` déplacée
  dans le schéma canonique ; `handle_update_guild` dépose désormais le détail
  champ par champ (ancien → nouveau) que le wrapper inclut dans son audit.
- **Fondation Permission Center** (`c48458d`) : `command_channel_permissions`
  (exceptions salon/catégorie par commande, même précédence "deny gagne" que
  `command_role_permissions` déjà existant) + `Backend.channel_rule()`.
  **Pas branché dans `evaluate()`** — voir "Décisions en attente" ci-dessous.

## Milestone 3 — Modules avancés : **fondations posées, wiring en attente**

- **Fondation moteur de règles AutoMod** (`automod_rules`,
  `cogs/automod.py::get_automod_rule/set_automod_rule`, `702c4fa`) :
  configuration fine par filtre (seuil, fenêtre, action, exclusions),
  coexiste avec `automod_settings` (l'interrupteur global, inchangé).
  **Pas branché dans `_maybe_escalate`** — voir "Décisions en attente".
- **`+ticket-priority`** (`5850eb4`) : la colonne `tickets.priority` existait
  depuis toujours mais aucune commande ne l'avait jamais modifiée après
  création (toujours `'normale'`) — premier réel usage de ce champ.
- **Correction d'un audit précédent** : `cogs/automatic_verification_v4.py`
  et `_v5.py` avaient été classés à tort comme "morts" dans une session
  antérieure. Une recherche dédiée (boot réel + `tools/dead_module_gate.py`
  + historique git) a confirmé qu'ils sont **vivants**, atteints par une
  chaîne d'installation indirecte à 3 niveaux (`cogs/__init__.py::
  finalize_runtime` → `control_center_v3_language.py` → `control_center_v4.py`/
  `automatic_verification_v5.py`). Aucune suppression faite.

## Milestone 4 — Observabilité : **avancé**

- **`/health` enrichi** (`d8c8e86`) : expose `migration_version`,
  `migrations_available`, `ha_enabled`, `ha_role`, `ha_leader`, `ha_state`.
- **Chaînage santé réparé** (`33de714`) — trouvaille la plus significative de
  ce lot : `railway_ha_boot.py::_install_ha_healthcheck` remplaçait purement
  `dashboard.handle_health` (le diagnostic riche : DB, extensions,
  migrations, politique de commandes) par un payload HA minimal, **sans
  jamais l'appeler**. Dès que le failover HA est actif (le cas réel sur
  Railway), tout ce diagnostic devenait invisible. Corrigé en chaînant :
  bénéfice supplémentaire, un leader réellement connecté à Discord doit
  désormais AUSSI avoir un diagnostic riche sain pour être rapporté "ok" (un
  leader avec une base de données cassée n'est plus rapporté sain à tort).
- Analytics commandes (exécutions, erreurs, latence) : déjà couvert par
  `core/observability/metrics.py` + `/corediag`, existant avant cette session.
- Reste ouvert : analytics serveur consolidées (membres actifs, sanctions,
  tickets, vérifications dans une seule vue) — pas commencé, plus gros
  chantier produit que les correctifs ci-dessus.

## Milestone 5 — Scale : **2 correctifs sûrs appliqués, reste flaggé**

- **Index `economy_transactions`** déplacé dans le schéma canonique
  (`bfaa29b`) : n'était garanti que si `cogs/sentrix_v22.py` chargeait avec
  succès, alors que la table est filtrée par sender/receiver à plusieurs
  endroits.
- **Purge de caches au départ d'un serveur** (`bfaa29b`) :
  `Database._guild_config_cache` et `bot._rank_cache` (utils/stats_service.py)
  ne l'étaient jamais — les deux avaient déjà leur méthode d'invalidation
  publique, appelée depuis `cogs/bot_v14_core.py::guild_remove` (qui purgeait
  déjà 3 autres caches). `Levels._xp_locks` délibérément PAS touché : son
  propre commentaire documente ce choix comme voulu, pas un oubli.
- **Délibérément pas touché** : les ~5 `tasks.loop` qui font "for guild in
  bot.guilds: requêtes séquentielles" (réel mais pas cassé aujourd'hui) ; le
  seed vocal complet au reconnect (`cogs/voice_logs_v2.py` — son rappel
  répété n'est PAS redondant, il rattrape les changements survenus pendant
  une déconnexion Discord, une "correction" naïve aurait cassé ce rattrapage).

## Décisions produit en attente (flaggées, pas tranchées)

Ces deux points touchent des fonctions parmi les plus critiques du bot
(la décision de sécurité centrale et l'escalade de sanctions automatique).
Une fondation sûre a été posée pour chacun ; le branchement final est un
choix produit délibérément laissé à Jayden plutôt que deviné :

1. **Point d'intégration des exceptions salon/catégorie dans
   `utils/access_matrix.py::evaluate()`** — voir tâche de suivi créée
   (conflit entre "restreint uniquement" vs "peut aussi accorder", et
   priorité par rapport au bypass Administrateur/propriétaire).
2. **Conflit à trois cogs sur l'escalade AutoMod** (`owner_sanction_immunity.py`
   chaîne correctement ; `content_filter_policy.py` désactive les sanctions
   pour les filtres de contenu ; `bot_excellence_runtime.py` remplace tout
   par un système concurrent à score, déjà persistant en DB) — voir tâche de
   suivi créée. Le comportement réellement actif en production aujourd'hui
   dépend de l'ordre d'installation, jamais confirmé par un boot réel dédié.

## Discipline suivie

Chaque changement ci-dessus : recherche avant implémentation (jamais de
supposition non vérifiée sur ce qui est "mort" ou "déjà fait"), test avant
commit, `git diff --stat` revu, boot réel des 51-52 extensions vérifié quand
le changement touche le runtime, commit séparé et réversible par changement,
push uniquement sur demande explicite. Aucun merge vers `main`, aucun
déploiement Railway, aucune donnée de production touchée.
