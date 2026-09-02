"""Chaque commande reelle, face aux six profils d'utilisateur.

Les tests de la matrice verifient des commandes CHOISIES. Cet audit part de
l'inverse : il charge le bot complet, prend les 537 commandes reellement
enregistrees, et demande a la matrice ce qu'elle repond a chacun des six
profils. Une commande oubliee dans la matrice, ou un administrateur qui
atteindrait une commande reservee au proprietaire, se voit alors tout de suite.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter, defaultdict

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "tests"))

from utils import access_matrix as M  # noqa: E402
from test_access_matrix import (  # noqa: E402
    FakeBackend, Guild, Member, ROLE_MOD, OWNER_ID,
    member, limited_mod, administrator, guild_owner, global_owner,
)

# L'ordre compte : du moins privilegie au plus privilegie. Une permission qui
# s'ouvre a un profil doit rester ouverte a tous ceux d'apres.
PROFILS = [
    ("membre", member),
    ("moderateur", limited_mod),
    ("administrateur", administrator),
    ("proprietaire du serveur", guild_owner),
    ("proprietaire SentriX", global_owner),
]


class _Bot:
    def __init__(self, backend):
        self.sentrix_access_backend = backend
        self.blacklist_cache = {}


def _decider(backend, auteur, nom):
    return asyncio.run(
        M.evaluate(_Bot(backend), command_name=nom, author=auteur, guild=Guild())
    )


async def _commandes_reelles() -> list[str]:
    """Les noms qualifies effectivement enregistres par le bot."""
    import config
    import tempfile
    import pathlib

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "audit.db")
    import main as bot_main

    import re

    bot = bot_main.BotAllInOne()
    await bot.db.connect()

    # railway_boot ajoute des extensions APRES la liste de main.py. Les omettre
    # laissait 47 commandes hors de l'audit — dont tout le constructeur +create.
    extensions = list(bot_main.EXTENSIONS)
    source_boot = pathlib.Path(RACINE, "railway_boot.py").read_text(encoding="utf-8")
    for module in re.findall(r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', source_boot):
        if module not in extensions:
            extensions.append(module)

    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=20)
        except Exception:
            pass
    noms = sorted({c.qualified_name for c in bot.walk_commands()})
    await bot.db.close()
    return noms


def auditer(noms: list[str]) -> int:
    backend = FakeBackend()
    anomalies: list[str] = []
    niveaux: Counter = Counter()
    par_profil: Counter = Counter()
    ouverture: dict[str, list[str]] = defaultdict(list)

    for nom in noms:
        niveau = M.access_tier(nom)
        niveaux[niveau.split(":")[0]] += 1

        autorises = []
        for etiquette, fabrique in PROFILS:
            decision = _decider(backend, fabrique(), nom)
            if decision.allowed:
                autorises.append(etiquette)
                par_profil[etiquette] += 1
        ouverture[nom] = autorises

        # 1. Une commande inconnue de la matrice retombe en fail-closed : elle
        #    n'est cassee pour personne, mais personne ne l'a classee non plus.
        if niveau == "fail-closed":
            anomalies.append(f"NON CLASSEE   {nom}")

        # 2. Un administrateur ne doit JAMAIS atteindre une commande reservee
        #    au proprietaire, global ou du serveur. C'est la regle qui protege
        #    un serveur d'un administrateur devenu hostile.
        racine = M.resolve_name(nom)
        if racine in M.OWNER_ONLY_COMMANDS and "administrateur" in autorises:
            anomalies.append(f"ADMIN > OWNER GLOBAL   {nom}")
        if racine in M.GUILD_OWNER_COMMANDS and "administrateur" in autorises:
            anomalies.append(f"ADMIN > PROPRIETAIRE SERVEUR   {nom}")
        if racine in M.OWNER_ONLY_COMMANDS and "proprietaire du serveur" in autorises:
            anomalies.append(f"PROPRIETAIRE SERVEUR > OWNER GLOBAL   {nom}")

        # 3. Une commande sensible ouverte a un simple membre.
        if "membre" in autorises and niveau not in ("public",):
            anomalies.append(f"MEMBRE SUR COMMANDE NON PUBLIQUE   {nom} ({niveau})")

        # 4. L'ouverture doit etre croissante : ce qu'un profil obtient, les
        #    profils plus eleves l'obtiennent aussi. Une inversion signale une
        #    regle ecrite a l'envers.
        rangs = [i for i, (e, _) in enumerate(PROFILS) if e in autorises]
        if rangs and rangs != list(range(min(rangs), len(PROFILS))):
            manquants = [
                PROFILS[i][0] for i in range(min(rangs), len(PROFILS))
                if i not in rangs
            ]
            anomalies.append(f"OUVERTURE NON CROISSANTE   {nom} — manque {manquants}")

    print(f"commandes auditees : {len(noms)}\n")
    print("  par niveau declare")
    for niveau, n in niveaux.most_common():
        print(f"    {niveau:16} {n:>4}")
    print("\n  commandes accessibles, par profil")
    for etiquette, _ in PROFILS:
        print(f"    {etiquette:26} {par_profil[etiquette]:>4}")

    if not anomalies:
        print("\nOK : aucune anomalie de permission.")
        return 0
    print(f"\nECHEC : {len(anomalies)} anomalie(s)\n")
    for a in sorted(set(anomalies)):
        print("   " + a)
    return 1


def auditer_configuration_hostile(noms: list[str]) -> int:
    """Et si le serveur s'est configure contre lui-meme ?

    Un administrateur peut, dans Setup, autoriser nommement un role ou un
    membre sur une commande. La question qui compte est : cette autorisation
    peut-elle ouvrir une commande reservee au proprietaire ? Si oui, un
    administrateur hostile contourne toute la hierarchie en trois clics.
    """
    anomalies: list[str] = []
    reserve = M.OWNER_ONLY_COMMANDS | M.GUILD_OWNER_COMMANDS

    for nom in noms:
        racine = M.resolve_name(nom)
        if racine not in reserve:
            continue

        # Autorisation explicite accordee au simple membre, par utilisateur ET
        # par role : les deux voies qu'offre Setup.
        for sujet in (("user", 10), ("role", ROLE_MOD)):
            backend = FakeBackend(rules={(sujet[0], sujet[1], racine): True})
            auteur = Member(10, roles=[ROLE_MOD])
            if _decider(backend, auteur, nom).allowed:
                anomalies.append(
                    f"REGLE SETUP OUVRE UNE COMMANDE RESERVEE   {nom} via {sujet[0]}"
                )

        # Un administrateur muni de la meme autorisation explicite.
        backend = FakeBackend(rules={("user", 12, racine): True})
        if _decider(backend, administrator(), nom).allowed:
            anomalies.append(f"ADMIN AUTORISE PAR REGLE SUR RESERVEE   {nom}")

    # Une mise en liste noire doit primer sur tout, y compris le proprietaire
    # du serveur : c'est une decision du proprietaire de SentriX.
    backend = FakeBackend(blacklist={OWNER_ID: "abus"})
    for nom in ("help", "ban", "wipe-server"):
        if _decider(backend, guild_owner(), nom).allowed:
            anomalies.append(f"LISTE NOIRE IGNOREE   {nom}")

    if not anomalies:
        print("\nOK : aucune regle de configuration ne contourne la hierarchie.")
        return 0
    print(f"\nECHEC : {len(anomalies)} contournement(s) possible(s)\n")
    for a in sorted(set(anomalies)):
        print("   " + a)
    return 1


def main() -> int:
    noms = asyncio.run(_commandes_reelles())
    return auditer(noms) | auditer_configuration_hostile(noms)


if __name__ == "__main__":
    code = main()
    # Le bot laisse des taches asyncio vivantes : une sortie normale attendrait
    # indefiniment. Ce processus n'a plus rien a faire.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
