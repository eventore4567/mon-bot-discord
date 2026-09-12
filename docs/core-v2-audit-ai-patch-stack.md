# SentriX Core V2 — Audit Phase 4 : la pile de correctifs autour de l'IA

Périmètre : `utils/ai_service.py::generate()`/`generate_image()`, les modules qui les
enveloppent au démarrage, et `/image` (`cogs/v17_extras.py::image_v17`, l'implémentation
réellement vivante). Audit uniquement — aucun refactor n'a été fait sur cette pile.
Méthode : boot réel de `main.BotAllInOne()` avec les 51 extensions de production
(30 `main.EXTENSIONS` + 21 ajoutées par `railway_boot.py`), puis lecture directe de
`__code__.co_filename`/`co_firstlineno` de chaque couche — jamais `inspect.getsource()`
seul, qui ment ici exactement comme documenté pour `rob`/`gamble` (un `functools.wraps`
recopie le `__qualname__` de la couche précédente sur la nouvelle).

## Correction d'un audit précédent

Une recherche antérieure (menée dans cette même session) avait estimé la chaîne de
`generate()` à "6-7 couches". Un traçage direct sur un boot réel en trouve **11**.

**Correction ultérieure (audit de dette technique, lot Components V2/UI+DB) :**
une version précédente de ce document affirmait ici que `cogs/ai_api_hotfix.py`
n'était "en réalité jamais installé" (grep n'avait trouvé aucun appelant direct
de son `setup()`). C'était une erreur, corrigée après avoir fait tourner
`tools/ai_api_hotfix_gate.py` (orphelin, jamais exécuté en CI jusqu'à cet
audit) : ce gate affirme lui-même que `setup()` est bien appelé, et la lecture
directe du code confirme la chaîne complète —
`cogs/__init__.py:46` importe `install` de `cogs/remove_code_command/__init__.py`
(le PAQUET vivant, pas le fichier plat mort du même nom, voir
`docs/core-v2-audit-technical-debt.md` #11), `cogs/__init__.py:154` l'appelle
via `_run_installer(...)` dans la chaîne de démarrage réelle, et
`cogs/remove_code_command/__init__.py:7` fait
`from ..ai_api_hotfix import setup as install_ai_api_hotfix` puis l'appelle à
la ligne 39. Confirmé aussi de façon indépendante par un log de boot réel
(`bot_mastery_audit.py`) : `[ERROR] bot.ai-api-hotfix: SentriX AI: OPENAI_API_KEY
is missing`, émis par le logger propre de `ai_api_hotfix.py`. Ce fichier
s'exécute donc bel et bien à chaque boot — un nom de module ("remove_code_command")
totalement sans rapport avec ce qu'il installe réellement (l'exact piège que
`docs/core-v2-audit-technical-debt.md` documente déjà pour d'autres chaînes de
méta-installation). La couche 7 ci-dessous est donc active, pas morte.

## La chaîne réelle de `ai_service.generate()` (11 couches, extérieure en premier)

```
1.  cogs/ai_personality_final.py:305   guarded_generate      (marqueur _sentrix_ai_enabled_engine_guard —
                                                                installé via _install_service_guard, PARTAGÉ
                                                                avec ai_disable_guard, voir note ci-dessous)
2.  cogs/ai_disable_guard.py:83        guarded_generate       (2e application du même garde, voir "Pourquoi
                                                                4 fois" ci-dessous)
3.  cogs/ai_context_v9.py:70           generate_with_context  (injecte le contexte serveur dans "instructions")
4.  cogs/ai_disable_guard.py:83        guarded_generate       (3e application)
5.  cogs/community_v33.py:238          generate_v33           (retry sur réponse vide)
6.  cogs/ai_disable_guard.py:83        guarded_generate       (4e application)
7.  cogs/ai_api_hotfix.py:401          generate_compatible    active — installée via cogs/remove_code_command/
                                                                __init__.py (voir correction ci-dessus), pas du
                                                                code mort
8.  cogs/bot_v12_machine.py:242        generate_v12           (compat V12)
9.  cogs/bot_mastery_runtime.py:623    generate_safe          (coupe-circuit après erreurs répétées)
10. cogs/natural_music_intent_guard.py:285  guarded_generate  (encore le garde IA — 3e FICHIER différent qui
                                                                réutilise le même nom de fonction/le même motif)
11. cogs/bot_excellence_runtime.py:314 guarded_generate       (sémaphore de concurrence AI_CONCURRENCY, encore
                                                                nommé "guarded_generate" mais SANS rapport avec
                                                                le garde d'activation — collision de nom, pas de
                                                                collision de comportement)
    → utils/ai_service.py:689          generate               (l'original : filtre de contenu, appel OpenAI,
                                                                gestion d'erreurs typée)
```

**Pourquoi le garde d'activation apparaît 4 fois** : `cogs/ai_disable_guard.py::install()`
est appelé depuis DEUX sites (`cogs/afk_signature_fix.py:26` et
`cogs/stability_runtime.py:274`), et `stability_runtime.install()` est un catch-all
ré-exécuté après **chaque** chargement d'extension (confirmé dans
`docs/core-v2-audit-technical-debt.md` #13). Sa vérification d'idempotence
(`getattr(current_generate, "_sentrix_ai_enabled_engine_guard", False)`) ne détecte
"déjà installé" que si le garde est **directement** au sommet de la chaîne au moment de
l'appel. Entre deux exécutions de `stability_runtime`, d'autres cogs IA
(`ai_context_v9`, `community_v33`, `natural_music_intent_guard`, `bot_excellence_runtime`)
s'installent PAR-DESSUS le garde à leur propre point de chargement — donc au prochain
passage de `stability_runtime`, le garde n'est plus au sommet, le contrôle échoue, et il
se réinstalle par-dessus la nouvelle couche. Résultat : le garde protège bien la chaîne
(chaque enveloppe appelle correctement la suivante, confirmé), mais son propre
docstring ("autorité unique") est inexact — c'est une autorité appliquée plusieurs fois,
pas une seule fois comme conçu à l'origine.

Malgré ce motif inattendu, **la composition fonctionne correctement de bout en bout** :
chaque couche appelle bien la suivante via une fermeture (`current`/`current_generate`/
variantes), confirmé par lecture de chacune. Ce n'est PAS le motif "la dernière écriture
gagne, les autres sont mortes en silence" trouvé pour `clear`/`diagnostic`/`gamble`/`rob` —
c'est un motif différent : composition correcte, mais non maîtrisée/non documentée avant
cet audit.

## La chaîne de `ai_service.generate_image()` (2 couches)

```
1. cogs/ai_disable_guard.py:98   guarded_generate_image
2. cogs/bot_mastery_runtime.py:631  image_safe   (coupe-circuit dédié aux pannes OpenAI images)
   → utils/ai_service.py:587   generate_image
```

Chaîne bien plus courte et sans répétition — `generate_image()` est enveloppé par moins
de modules que `generate()`.

## `/image` : une réimplémentation complète, pas un contournement

Le décorateur `@commands.hybrid_command(name="image")` vit dans `cogs/ai.py:786`
(`generate_image_command`), mais ce corps **ne s'exécute jamais** : au chargement,
`cogs/v17_extras.py::install_image_role_quota()` remplace `command.callback` par
`image_v17` (confirmé sur boot réel : `command.callback.__code__` pointe vers
`cogs/v17_extras.py:70`). `image_v17` reste correct — il appelle bien
`ai_service.generate_image()` en interne (pas de contournement OpenAI) — mais ajoute
une couche de quota que `cogs/ai.py`'s propre corps n'a pas :

- Vérifie que l'IA est activée sur le serveur (`ai_service.get_settings`), que le
  salon est autorisé (`is_channel_allowed`) et que l'auteur a un rôle autorisé
  (`is_role_allowed`) — **avant** tout appel OpenAI.
- Résout un quota quotidien **par rôle** via `v17_ai_economy_games._role_ai_policy()` :
  si un rôle a une politique dédiée, `role_policy["daily_limit"]` **remplace**
  `settings["daily_limit"]` (le réglage par défaut du serveur) — un rôle premium peut
  ainsi avoir un quota plus large que le défaut du serveur, ou l'inverse.
  `role_policy["priority"]` détermine la position dans `PriorityGate` (file d'attente
  IA partagée, `cogs/v17_ai_economy_games.py::_ai_gate`).
- Bloque avec un message dédié si le quota du jour est atteint, sans jamais appeler
  `ai_service.generate_image()`.

Ce comportement (quota par rôle prioritaire sur le réglage serveur) est verrouillé par
`tests/test_ai_patch_stack_current_behavior.py::ImageRoleQuotaTests` et doit être
préservé tel quel dans toute migration future de `/image`.

## Le vrai contournement trouvé (corrigé séparément)

`utils/proof_service.py::_vision_json()` appelait `client.responses.create()`
directement plutôt que `ai_service.generate()` — contournant TOUTE cette pile,
disable-guard inclus. Corrigé dans un commit séparé
(`fix(ai): la vérification de preuves contournait le garde-fou IA activée/désactivée`),
avec 4 tests de régression qui installent le vrai garde et prouvent qu'aucun appel
OpenAI n'a lieu quand l'IA est désactivée. Ce fichier d'audit ne revient pas dessus.

## Recommandation

**Ne pas refondre maintenant** (conforme à la décision prise) : la pile compose
correctement, et le seul vrai bug (le contournement de `proof_service.py`) est déjà
corrigé indépendamment. Ce qui justifierait une consolidation future, le moment venu :

1. `cogs/ai_disable_guard.py`'s "autorité unique" devrait soit être installée une seule
   fois de façon réellement idempotente (vérifier une marque sur `ai_service` lui-même,
   pas sur la fonction actuellement au sommet de la chaîne), soit assumer et documenter
   qu'elle s'applique plusieurs fois par conception.
2. Trois fonctions différentes s'appellent toutes `guarded_generate` dans des fichiers
   différents avec des rôles différents (activation, concurrence dans
   `bot_excellence_runtime.py`, et encore l'activation dans
   `natural_music_intent_guard.py`) — un risque de confusion pour quiconque debug cette
   chaîne sans lire le code source complet, comme cet audit a dû le faire.
3. `cogs/ai_api_hotfix.py` est actif (voir correction en tête de document), mais
   installé via un nom de module ("remove_code_command") sans aucun rapport avec
   ce qu'il fait réellement — un futur mainteneur qui grep "ai_api_hotfix" pour
   trouver son point d'installation ne trouverait rien d'évident. Le renommage ou
   le déplacement de cet appel est hors périmètre de cet audit (refonte, pas
   documentation).
4. Si une consolidation dans `AIService` (Phase 4) a lieu un jour, ces 11 couches
   devraient devenir des étapes explicites d'un seul pipeline, testées individuellement
   — pas des monkeypatches empilés par des cogs qui s'ignorent mutuellement.

Rien de tout cela n'a été fait dans cet audit : recherche et documentation uniquement,
plus les tests de comportement actuel déjà cités.
