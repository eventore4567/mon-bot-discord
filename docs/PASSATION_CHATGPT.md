# Passation SentriX — ce qui reste à faire et comment le faire

Document écrit le 30/10/2026 pour reprendre le travail sans rien casser.
Lis-le en entier avant de toucher au code.

## 1. Le projet en 30 secondes

- Bot Discord **SentriX** (Python 3.11, discord.py 2.7) + dashboard web (aiohttp).
- Dépôt : `eventore4567/mon-bot-discord`.
- **Branche de production : `dashboard-refonte-2026-09`.** Railway redéploie
  automatiquement chaque fusion sur cette branche (~3 min).
- Railway : projet `f5fcb248-073d-4801-bde3-d27e1f42cede`, deux services en haute
  disponibilité :
  - `mon-bot-discord` (principal, `d4fb0c3a-…`) — point d'entrée `railway_ha_product_boot_v8.py` ;
  - `sentrix-standby` (secours, `c8087708-…`).
  Un seul est « leader » à la fois (bail en base) ; l'autre en `standby`, c'est NORMAL.
- Base : PostgreSQL en production (SQLite en test), traduction SQL à la volée.
  Écris du SQL compatible SQLite ; `INSERT … ON CONFLICT(...) DO UPDATE` marche partout.

## 2. Règles à respecter (non négociables)

1. **Le préfixe `+` est retiré en production** (30/10/2026). Toute nouvelle commande
   se publie en `/`. Fonctionnement : on écrit une commande préfixe classique
   (`@commands.command` / `@commands.group`) qui sert de SOURCE, puis on déclare sa
   route `/` dans `utils/slash_catalog.py` (liste `CATALOG`, entrée
   `_e("racine sous-commande", "nom-source", "Description en anglais.")`).
   - 25 sous-commandes max par racine, 3 niveaux max, 100 racines max.
   - Interdit dans un chemin : test, debug, diag, tmp, temp, legacy, vN… (test
     `tests/test_slash_catalog.py`).
   - Un sous-groupe a besoin d'une ligne dans `GROUP_DESCRIPTIONS`.
   - Interrupteur du `+` : `cogs/prefix_deprecation.prefixe_actif()` (variable
     `SENTRIX_PREFIXE_ACTIF`, absente = coupé). Le harnais de test et
     `tests/conftest.py` le rallument pour les tests historiques.
   - Les **commandes personnalisées** du serveur gardent leur préfixe. Elles n'ont
     PLUS de commandes `/` (décision de Jayden : « trop de commandes pour SentriX ») :
     elles se gèrent dans `/setup` (à construire, voir §5.0) et dans le dashboard.
   - **Ne pas multiplier les commandes `/`** : toute nouvelle fonction de
     configuration va dans une page de `/setup`, pas dans une nouvelle commande.
2. **Permissions** : toute nouvelle commande doit être classée dans
   `utils/access_matrix.py` (`CATEGORY_COMMANDS`, ex. catégorie `configuration` ou
   `securite`). Non classée = réservée aux admins (fail-closed).
3. **Aucune protection ne s'active toute seule** : nouveau réglage = désactivé par
   défaut, activé par un admin.
4. **Pas de message automatique périodique dans les salons de logs.**
5. **Ne mentionne personne** : `allowed_mentions` toujours explicite
   (`discord.AllowedMentions.none()` ou `users=[la personne]`).
6. **Textes en français, vouvoiement** dans le bot (un test l'impose :
   `tests/test_registre_editorial.py`). Pas d'émoji Discord classique dans les
   interfaces : les icônes SentriX passent par `utils/sentrix_emojis`.
7. **Interfaces** : passer par `utils/sentrix_panels` (`panels.Panneau`,
   `panels.envoyer`, `panels.editer`, `panels.depuis_embed`, `panels.avec_composants`).
   - Un message Components V2 ne peut PAS recevoir `embed=` en édition : utiliser
     `panels.editer`.
   - Dans un bouton/menu d'une ancienne `View` relogée dans un panneau,
     `self.view` est le Panneau : utiliser `panels.vue_source(self)` pour retrouver
     la vue métier (bug `+modcenter` du 29/10).
8. **Ne modifie jamais un test pour cacher un échec.** Un test qui encode une
   ancienne décision se met à jour en écrivant la nouvelle décision et sa date.
9. **Le bot n'a pas de nouvel écouteur gratuit** : le nombre d'écouteurs par
   événement est plafonné (`tools/listener_budget_gate.py`). Brancher le nouveau
   code dans un écouteur existant si possible.

## 3. Comment tester AVANT de pousser (sinon la CI sera rouge)

Dans le dossier du dépôt :

```bash
# 1. Tests unitaires (≈ 4 min)
python3 -m pytest tests -q -p no:cacheprovider --deselect tests/test_product_e2e.py -k "not product_e2e"

# 2. Les ~56 contrôles des workflows CI (tous les `run: python tools/…` de .github/workflows)
#    avec DISCORD_TOKEN=ci.fake.token OPENAI_API_KEY= POSTGRES_URL= REDIS_URL=

# 3. Balayage strict de TOUTES les commandes, en « + » ET en « / » (≈ 10 min)
DISCORD_TOKEN=ci.fake.token python3 tools/command_sweep.py --strict --out /tmp/sweep

# 4. Les 48 scénarios de bout en bout (≈ 9 min)
python3 -m pytest tests/test_product_e2e.py -q -p no:cacheprovider

# 5. Audit des permissions (8 lots en CI)
DISCORD_TOKEN=ci.fake.token SENTRIX_SHORT_SLASH_NAMES=1 python3 tools/permission_audit_sweep.py --strict --only <nom>
```

- Le **harnais** `tools/sentrix_e2e_harness.py` démarre le vrai bot avec un faux
  Discord et capture chaque requête HTTP (`h.CALLS`). Modèles à copier :
  `tools/custom_commands_e2e.py`, `tools/prefix_deprecation_e2e.py`.
  - Commande `/` comme un membre : `h.slash_options_from_spec` + `h.build_interaction(bot, racine, options, author_id=…, author_roles=…)` + `await bot.tree._call(inter)`.
  - Le lecteur de spécification coupe sur les espaces : pas d'espace dans une valeur.
  - Message d'un membre : `bot.dispatch("message", h.build_message(...))`
    (`run_prefix` ne déclenche pas `on_message`).
- Un nouveau scénario e2e s'ajoute à la liste de `tests/test_product_e2e.py`.
- **Échecs déjà présents (pas les tiens)** : 3 tests liés au changement de `/ban`
  (voir §5.7) et l'outil `tools/v25_quality_gate.py`. Ne pas les confondre avec
  une régression que tu introduis.

## 4. Fusionner

- Ouvrir une PR vers `dashboard-refonte-2026-09`, attendre la CI (≈ 15 min, le job
  `sweep` est le dernier), puis :

```bash
bash tools/finir_prs.sh <numéro>
```

  Le script attend la CI et ne fusionne que si tout est vert et sans conflit.
- Après fusion, vérifier le déploiement Railway : les deux services sur le nouveau
  commit, `SUCCESS`, et dans les journaux du leader :
  « Connecté en tant que SentriX#8903 », « Catalogue slash publié »,
  « N commandes slash synchronisées », aucun `Traceback`.

## 5. Ce qui reste à faire, en détail

### 5.0 PRIORITÉ — Commandes personnalisées dans /setup (comme DraftBot)
Les commandes `/custom` ont été RETIRÉES le 30/10/2026. Le moteur reste et marche
(`cogs/custom_commands.py` : actions exécutées dans `PlatformV4.on_message`,
scénario `tools/custom_commands_e2e.py` 6/6). Il faut une page dans `/setup` :
1. Trouver le menu servi de `/setup` (catégories : Accueil, Sécurité, Modération,
   Bienvenue, Niveaux, Logs…) — chaîne `setup_components_v74 → v73` ; ajouter une
   catégorie « Commandes personnalisées ».
2. La page affiche : préfixe actuel, « Suppression du message : activée/désactivée »,
   la liste des commandes (`platform_custom_commands`), et des boutons :
   **Créer**, **Modifier**, **Supprimer**, **Voir**, **Préfixe**,
   **Suppression des commandes** (bascule), **Réinitialiser** (avec confirmation).
3. **Créer** = assistant en étapes (modals Discord) :
   nom (minuscules, sans espace) → description/message → première action dans un
   menu déroulant : Envoyer un message, Ajouter un ou plusieurs rôles, Ajouter un
   rôle temporaire (rôle + durée), Retirer un ou plusieurs rôles, Ajouter de
   l'argent, Ajouter de l'expérience → « Ajouter une autre action » ou « Terminer ».
   Griser « Ajouter de l'argent / de l'XP » si l'économie / les niveaux sont
   désactivés (comme DraftBot : « Système d'économie désactivé »).
4. Enregistrement : `PlatformV4.save_custom_command(guild, actor_id, {"name", "response"})`
   puis une ligne par action dans `custom_command_actions(guild_id, name, kind,
   value, duration_s)` avec `kind` ∈ role_add, role_remove, role_temp, money, xp.
   Préfixe : `bot.db.set_guild_config(guild_id, "prefix", "!")`.
   Suppression du message : table `custom_command_settings(guild_id, delete_trigger)`.
   Fonctions utiles déjà écrites dans `cogs/custom_commands.py` :
   `actions_de`, `decrire`, `supprimer_declencheur`, et les validations des
   anciennes commandes (durée 1 min–90 j, argent 1–1 000 000, XP 1–100 000,
   10 actions max, rôle au-dessous de SentriX).
5. Le dashboard (`web/platform_v4.py`, onglet commandes personnalisées) ne gère que
   le texte : y ajouter les actions ensuite.
6. Tester : réutiliser `tools/custom_commands_e2e.py` et ajouter les clics de la
   page `/setup` (modèle : `tools/setup_guide_e2e.py`).

### 5.1 PR #554 (fusionnée et déployée le 30/10/2026)
Logs de permissions complets, salons membres rouverts aux vérifiés, moteur des
commandes personnalisées, script `tools/finir_prs.sh`.
PR #557 : boutons « Dashboard » vers le lien court https://sentrixbot.up.railway.app/app
(fusion automatique si la CI est verte ; sinon `bash tools/finir_prs.sh 557`).

### 5.2 Snippets (absent de SentriX)
But (comme DraftBot) : des textes enregistrés que le staff réutilise d'un mot-clé.
1. Nouveau module `cogs/snippets.py` (modèle : `cogs/custom_commands.py`).
   Table `snippets(id, guild_id, name, content, created_by, created_at)`.
2. Groupe source `snippet` : `create <nom> <texte>`, `send <nom>` (poste le texte dans
   le salon, `allowed_mentions` none), `list`, `delete <nom>`.
3. Catalogue : `_e("snippet create", "snippet create", …)` etc. ; `GROUP_DESCRIPTIONS`.
4. Permission : `send` pour `moderation` (staff), le reste `configuration`.
5. Test unitaire + scénario e2e ; ajouter au dashboard ensuite (facultatif).

### 5.3 Messages récurrents (absent)
1. Module `cogs/recurring_messages.py` : table
   `recurring_messages(id, guild_id, channel_id, content, every_s, next_at, enabled)`.
2. Boucle `tasks.loop(minutes=1)` qui envoie les messages dus et calcule le
   prochain `next_at` (attention HA : n'envoyer que si l'instance est leader —
   regarder comment `cogs/sentrix_plus.py` (messages programmés `/schedule`) le fait,
   et RÉUTILISER ce mécanisme plutôt qu'en créer un second).
3. Commandes : `create <salon> <intervalle ex. 6h> <texte>`, `list`, `pause`,
   `resume`, `delete`. Intervalle minimal 10 min.
4. Désactivé par défaut, jamais dans un salon de logs.

### 5.4 Réactions de mots (absent)
1. Table `word_reactions(guild_id, word, emoji)`.
2. Brancher dans un `on_message` EXISTANT (budget d'écouteurs) : par ex. celui
   de `cogs/platform_v4.py`. Correspondance par **mot entier**, accents et casse
   ignorés (`utils/text_normalization`), jamais par sous-chaîne.
3. Limiter : 1 réaction par message, ignorer les bots.
4. Commandes `/wordreact add <mot> <emoji>`, `remove`, `list`.

### 5.5 Abonnement Premium (choix de Jayden : abonnement Discord officiel)
1. Sur le portail développeur : activer la monétisation, créer un SKU
   d'abonnement serveur (« SentriX Premium »).
2. Côté bot : `guild.entitlements` / `bot.entitlements()` (discord.py 2.7) pour
   savoir si un serveur est Premium. Créer `utils/premium.py` avec
   `async def est_premium(bot, guild_id) -> bool` (cache 5 min).
3. Décider avec Jayden la liste des fonctions payantes, puis les verrouiller
   avec un check commun ; message de refus avec bouton d'achat
   (`discord.ui.Button(style=premium, sku_id=...)`).
4. Dashboard : badge Premium et page d'offre.

### 5.6 Traduction anglaise complète
Quand le serveur est en anglais, tout n'est pas traduit.
1. Repérer le mécanisme existant : `cogs/language_runtime.py`
   (`get_language`, `LANG_EN`).
2. Lister les textes non traduits : lancer le balayage des commandes avec un
   serveur réglé en anglais et chercher les réponses en français.
3. Traduire par module, en commençant par l'aide, le setup et les erreurs.

### 5.7 Régressions de `/ban` (faites par une autre session, en production)
Commits `7d1c2dbc` et `130a319f`. Trois tests échouent :
- `tests/test_registre_editorial.py` : le texte « veux-tu supprimer » TUTOIE →
  passer au vouvoiement (« voulez-vous supprimer »).
- `tests/test_action_validation.py` : le contrôle de la cible a disparu du corps de
  `ban` (`cogs/moderation.py`) → remettre la validation de cible (hiérarchie,
  soi-même, propriétaire).
- `tools/v25_quality_gate.py` (contrat de signature) : `ban` attend
  `("membre", "raison", "supprimer_messages")`, il a maintenant `envoyer_mp` →
  mettre à jour le contrat SI le changement est voulu.

### 5.8 `/presentation` et l'audit des permissions
Commande `/` native (PR #555). L'audit ne sait pas neutraliser une commande native :
elle est exclue (`SKIP_COMMANDS` dans `tools/permission_audit_sweep.py`).
Vrai écart restant : le propriétaire de SentriX est refusé s'il n'a pas
« Gérer le serveur ». Mieux : faire neutraliser aussi les commandes natives par
l'audit, puis retirer l'exclusion.

### 5.9 Lien court du dashboard (FAIT : sentrixbot.up.railway.app)
Le domaine du service de secours a été renommé en `sentrixbot.up.railway.app`
(accueil : https://sentrixbot.up.railway.app/ ; dashboard : …/app, qui renvoie
vers l'adresse principale pour la connexion). Ce qui suit reste valable pour un
vrai domaine personnalisé :
Objectif : `sentrix.up.railway.app`. NE PAS renommer avant :
1. Jayden ajoute `https://sentrix.up.railway.app/oauth/callback` dans le portail
   développeur → OAuth2 → Redirects.
2. Jayden vérifie la variable Railway `DASHBOARD_PUBLIC_URL` du service principal
   (et la met à jour). Le code a une valeur par défaut dans `config.py`
   (`_DEFAULT_DASHBOARD_PUBLIC_URL`) à mettre à jour aussi.
3. Ensuite seulement : renommer le domaine Railway du service principal.
Alternative : le service de secours a déjà `sentrix.gg` et `sentrix.is-a.bot` —
il faut que le DNS de `sentrix.gg` pointe vers Railway.

### 5.10 Anciennes PR ouvertes
30 PR ouvertes, la plupart de septembre/octobre. Seule #479 est entièrement
contenue en production (à fermer). Les autres ont de 1 à 60 commits non intégrés et
sont probablement dépassées : les revoir UNE PAR UNE avec Jayden, ne pas fusionner
en bloc.

### 5.11 Demandes visuelles encore ouvertes
- Page d'accueil et AutoMod « moches » : demander à Jayden une capture de l'écran
  exact (l'accueil public du site est déjà soigné ; il parle sans doute du
  dashboard après connexion ou d'un panneau Discord).
- Bannière et photo de profil : fichiers prêts dans `assets/banniere/`
  (à envoyer sur le portail développeur → Bot).

## 6. Pièges déjà rencontrés (gagne du temps)

- `config.DATABASE_PATH` est figé au premier import : poser les variables
  d'environnement AVANT d'importer `config`.
- Un paramètre de commande nommé `name` casse le parseur (couches V18/V76) :
  l'appeler `nom`.
- `ImageDraw` sur une image RGBA REMPLACE les pixels (pas de transparence) :
  dessiner sur un calque et `alpha_composite`.
- `get_command("a b c")` renvoie `a` si `b` n'existe pas : comparer
  `qualified_name`.
- Sur macOS, `timeout` n'existe pas ; sous zsh, `$VAR` contenant plusieurs fichiers
  n'est pas découpé (utiliser `xargs`).
- La fusion par Claude Code peut être refusée par son classificateur : c'est Jayden
  qui fusionne alors (`gh pr merge N --repo eventore4567/mon-bot-discord --merge`).
