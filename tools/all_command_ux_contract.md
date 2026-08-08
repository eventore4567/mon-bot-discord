# SentriX — contrat UX global des commandes

Cette passe applique les mêmes garde-fous à tout le registre actif, sans liste manuelle par commande.

- `bot.walk_commands()` alimente le correcteur de fautes, y compris les sous-commandes.
- Les commandes préfixées sont chronométrées du début à la fin.
- Les commandes slash sont chronométrées via les interactions jusqu'à leur completion.
- Une commande valide qui finit sans réponse conserve le fallback de réponse existant.
- La CI vérifie chaque commande visible avec une faute synthétique et échoue si son nom canonique n'est plus proposé.

Ce fichier est volontairement court : le contrat exécutable est dans `tools/command_runtime_audit.py`.
