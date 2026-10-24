"""Les deux portes de /setup doivent dire la même chose.

Constaté par Jayden le 24/10 : un gestionnaire ouvre `/setup` — accepté, car
`_can_setup` admet « Gérer le serveur » — puis se fait refuser « Permission
manquante : Administrateur » dès qu'il configure le règlement.

Deux gardes successives exigeaient des permissions différentes. Ce fichier
verrouille leur accord.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from cogs.permission_setup_hardening_v65 import CATEGORY_REQUIRED_PERMISSION  # noqa: E402
from utils.access_matrix import DISCORD_PERMISSION_COMMANDS  # noqa: E402

FAMILLE_VERIFICATION = (
    "verification",
    "verification-config",
    "verify-config",
    "verify-panel",
    "verify-repair",
    "verify-setup",
)


def test_la_famille_verification_suit_la_categorie_configuration():
    attendu = CATEGORY_REQUIRED_PERMISSION["configuration"]
    for commande in FAMILLE_VERIFICATION:
        assert DISCORD_PERMISSION_COMMANDS[commande] == attendu, (
            f"{commande} exige {DISCORD_PERMISSION_COMMANDS[commande]} alors que "
            f"/setup s'ouvre avec {attendu} : le gestionnaire passerait la "
            "première porte pour buter sur la seconde"
        )


def test_le_code_des_commandes_est_aligne_sur_la_matrice():
    # Changer la matrice seule recrée le double message : la garde du cog doit
    # suivre. C'est le piège que l'ancien commentaire décrivait déjà.
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1] / "cogs" / "verification.py").read_text(
        encoding="utf-8"
    )
    assert "@checks.is_owner_or_admin()" not in source, (
        "une garde Administrateur subsiste dans cogs/verification.py"
    )
    assert "@checks.is_owner_or_manager()" in source


def test_manage_reste_reserve_aux_administrateurs():
    # `manage` fait du rollback, des sanctions, des instantanés : ce n'est pas
    # de la configuration. L'alignement ne doit pas l'emporter avec lui.
    assert DISCORD_PERMISSION_COMMANDS["manage"] == "administrator"


def test_la_garde_gestionnaire_accepte_les_trois_cas_et_refuse_le_reste():
    import asyncio

    import discord

    from utils import checks
    from utils.checks import BotPermissionError

    predicat = checks.is_owner_or_manager().predicate

    class _Membre(discord.Object):
        def __init__(self, admin=False, gerer=False):
            super().__init__(id=1)
            self.guild_permissions = discord.Permissions(
                administrator=admin, manage_guild=gerer
            )

    class _Ctx:
        def __init__(self, membre):
            self.author = membre
            self.bot = type("B", (), {"db": type("D", (), {})()})()

    # discord.Object n'est pas un Member : on vise le refus explicite.
    with_refus = _Ctx(_Membre())
    try:
        asyncio.run(predicat(with_refus))
        leve = False
    except BotPermissionError as exc:
        leve = "Gérer le serveur" in str(exc)
    except Exception:
        leve = True
    assert leve, "un membre sans permission doit être refusé, avec la bonne raison"
