# Les 28 handlers `on_ready` — analyse, sans consolidation

Mesure faite le 2026-09-02 sur le bot réellement chargé (44 extensions, plus celles
que `railway_boot` ajoute à l'exécution), en lisant `bot.extra_events["on_ready"]`.

**Conclusion : aucun défaut prouvé. Rien n'a été fusionné.**

## Ce que la mesure donne

28 handlers enregistrés. Répartition par risque potentiel :

| Critère | Nombre | Verdict |
|---|---|---|
| Sans `try/except` interne | 18 | **Non pertinent** — voir ci-dessous |
| Sans garde d'idempotence explicite | 7 | Tous idempotents autrement |
| Parcourent tous les serveurs | 5 | Coût négligeable, mesuré |
| Appellent `tree.sync` | 0 | — |

## Hypothèse écartée : « une exception coupe la chaîne »

C'était ma première lecture des 18 handlers sans `try/except`, et elle est fausse.
`discord.Client._run_event` enveloppe **chaque** listener :

```python
try:
    await coro(*args, **kwargs)
except asyncio.CancelledError:
    pass
except Exception:
    await self.on_error(event_name, *args, **kwargs)
```

Chaque listener est par ailleurs planifié dans sa propre tâche. Un handler qui lève
n'empêche donc pas les 27 autres de s'exécuter. Ajouter 18 `try/except` n'aurait rien
corrigé et aurait masqué les erreurs que `on_error` remonte aujourd'hui.

## Le vrai risque : `on_ready` refire à chaque reconnexion

Ce n'est pas un événement de démarrage. Discord le renvoie après chaque IDENTIFY,
donc à chaque reconnexion qui ne peut pas être reprise (RESUME échoué). Un handler
non idempotent republie, recrée ou réempile à chaque incident réseau.

Les 7 handlers sans marqueur `_installed` ont été lus un par un :

- **`release_announcer`** — le seul qui publie un message. Il est protégé par un
  anti-doublon **persistant** (`_reserve_release`) qui est *fail-closed* : si la
  table anti-doublon est indisponible, l'annonce est annulée plutôt que risquée.
  Une reconnexion ne réannonce rien.
- **`community_v3`, `v31`, `v32`, `v33`, `v34`** — appellent des `_install_*` qui
  posent chacun leur propre marqueur (`_replace_callback` sort si le marqueur est
  déjà là, `_install_global_visual_style` teste `_sentrix_v32_clean`, etc.).
  Réexécuter est un aller-retour sans effet.
- **`language_runtime`** — recharge le cache des langues. `_ensure_table` est gardé,
  et `get_language` lit le cache : après le premier READY, la boucle ne fait que des
  accès mémoire.

## Les 5 boucles sur tous les serveurs

`language_runtime`, `language_setup_finalizer`, `invites`, `setup_auto_fix`,
`runtime_fix_v1`. Aucune ne fait d'appel réseau par serveur, et les lectures passent
par un cache. Le coût par reconnexion croît linéairement avec le nombre de serveurs,
mais reste en mémoire. À surveiller si le bot dépasse quelques centaines de serveurs ;
rien à corriger aujourd'hui.

## Pourquoi ne pas consolider

Fusionner 28 handlers en un seul point d'entrée créerait exactement ce que ce dépôt a
déjà en trop : une couche supplémentaire qui doit connaître l'ordre d'exécution de 28
modules. La dispersion actuelle a un avantage réel — chaque module possède son propre
démarrage et échoue seul. La consolidation ne se justifierait que sur un défaut prouvé
d'ordonnancement, et il n'y en a pas.
