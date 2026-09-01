"""+wipe-server : la commande la plus destructive du bot.

Elle supprime TOUS les salons et TOUS les roles. Niveau 4 : proprietaire du serveur
uniquement — un administrateur Discord ne suffit pas.
"""
import asyncio
import inspect

import pytest

from utils import access_matrix as M

OWNER_ID, ADMIN_ID, MOD_ID, MEMBER_ID, CREATOR_ID = 1, 2, 3, 4, 5

PERMISSION_FIELDS = (
    "administrator", "ban_members", "kick_members", "moderate_members",
    "manage_messages", "manage_channels", "manage_roles", "manage_guild",
    "manage_nicknames", "move_members",
)


class Perms:
    def __init__(self, **kw):
        for field in PERMISSION_FIELDS:
            setattr(self, field, kw.get(field, False))


class Member:
    def __init__(self, uid, perms):
        self.id = uid
        self.guild_permissions = perms
        self.roles = []


class Guild:
    id = 1
    owner_id = OWNER_ID


class FakeDB:
    async def is_bot_creator(self, uid):
        return int(uid) == CREATOR_ID

    async def fetchone(self, *a, **k):
        return None

    async def fetchall(self, *a, **k):
        return []

    async def get_guild_config(self, *a, **k):
        return None


class Bot:
    def __init__(self):
        self.db = FakeDB()


MEMBRE = Member(MEMBER_ID, Perms())
MODERATEUR = Member(MOD_ID, Perms(ban_members=True, kick_members=True,
                                  manage_messages=True, manage_channels=True))
ADMIN = Member(ADMIN_ID, Perms(administrator=True))
PROPRIETAIRE = Member(OWNER_ID, Perms(administrator=True))
CREATEUR = Member(CREATOR_ID, Perms())


def decide(author):
    return asyncio.run(
        M.evaluate(Bot(), command_name="wipe-server", author=author, guild=Guild())
    )


def test_wipe_server_est_bien_au_niveau_4():
    assert "wipe-server" in M.GUILD_OWNER_COMMANDS
    assert M.access_tier("wipe-server") == "guild-owner"


def test_membre_refuse():
    assert not decide(MEMBRE).allowed


def test_moderateur_refuse():
    assert not decide(MODERATEUR).allowed


def test_administrateur_non_proprietaire_refuse():
    """Le coeur du niveau 4 : Administrateur ne suffit pas."""
    decision = decide(ADMIN)
    assert not decision.allowed
    assert decision.policy == "guild-owner-only"
    assert "propri" in decision.message.casefold()


def test_proprietaire_du_serveur_autorise():
    decision = decide(PROPRIETAIRE)
    assert decision.allowed
    assert decision.policy == "guild-owner-only"


def test_owner_sentrix_autorise():
    """Le createur passe partout : il intervient sur n'importe quel serveur."""
    assert decide(CREATEUR).allowed


# ------------------------------------------------- REVOCATION PENDANT LA FENETRE
def test_le_modal_reverifie_au_submit_et_pas_a_l_ouverture():
    from cogs.server_builder import WipeConfirmModal

    source = inspect.getsource(WipeConfirmModal.on_submit)
    assert "access_matrix.evaluate" in source, "aucune reverification au submit"
    assert '"wipe-server"' in source
    # La permission doit etre revue AVANT de comparer le nom saisi, sinon un refus
    # de permission serait annonce comme une faute de frappe.
    assert source.index("access_matrix.evaluate") < source.index("confirm_input.value")


def test_le_modal_resout_evaluate_au_moment_de_l_appel():
    """setup_simple_v68 remplace access_matrix.evaluate au demarrage.

    Un `from utils.access_matrix import evaluate` figerait la version d'origine et le
    modal deciderait avec une regle perimee.
    """
    source = (M.__file__.rsplit("/utils/", 1)[0] + "/cogs/server_builder.py")
    text = open(source, encoding="utf-8").read()
    assert "from utils import access_matrix" in text
    assert "from utils.access_matrix import evaluate" not in text


def test_permission_retiree_pendant_la_fenetre_refuse_le_wipe():
    """Simule le scenario reel : proprietaire a l'ouverture, plus proprietaire au submit."""
    ancien_proprietaire = Member(OWNER_ID, Perms(administrator=True))

    # A l'ouverture de la confirmation : autorise.
    assert decide(ancien_proprietaire).allowed

    # Le serveur a change de proprietaire entre-temps.
    class GuildTransferee(Guild):
        owner_id = 999

    apres = asyncio.run(
        M.evaluate(Bot(), command_name="wipe-server",
                   author=ancien_proprietaire, guild=GuildTransferee())
    )
    assert not apres.allowed, "le wipe passe alors que la personne n'est plus proprietaire"
    assert apres.policy == "guild-owner-only"


def test_le_bouton_de_confirmation_reste_limite_a_l_auteur():
    from cogs.server_builder import WipeConfirmView

    source = inspect.getsource(WipeConfirmView.interaction_check)
    assert "interaction.user.id != self.author_id" in source


# ------------------------------------------- TOUTES LES IMPLEMENTATIONS D'ACCORD
IMPLEMENTATIONS = [
    ("utils.access_matrix", "evaluate"),
    ("cogs.setup_simple_v68", "secure_evaluate_v68"),
    ("cogs.permission_setup_hardening_v65", "secure_evaluate"),
]


@pytest.mark.parametrize("module_name,function_name", IMPLEMENTATIONS)
def test_chaque_implementation_applique_le_niveau_4(module_name, function_name):
    """Trois copies du flux de decision coexistent ; elles doivent decider pareil.

    setup_simple_v68 remplace access_matrix.evaluate au demarrage, et
    permission_setup_hardening_v65 tente la meme chose. Laquelle gagne depend de
    l'ordre de chargement. Le niveau 4 avait ete pose dans deux d'entre elles
    seulement : V65 laissait donc passer un simple Administrateur sur wipe-server
    des qu'elle gagnait la course.
    """
    import importlib

    module = importlib.import_module(module_name)
    evaluate = getattr(module, function_name)

    refus = asyncio.run(
        evaluate(Bot(), command_name="wipe-server", author=ADMIN, guild=Guild())
    )
    assert not refus.allowed, f"{module_name} laisse un administrateur detruire le serveur"

    autorise = asyncio.run(
        evaluate(Bot(), command_name="wipe-server", author=PROPRIETAIRE, guild=Guild())
    )
    assert autorise.allowed, f"{module_name} refuse le proprietaire du serveur"


@pytest.mark.parametrize("module_name,function_name", IMPLEMENTATIONS)
def test_chaque_implementation_resout_les_sous_commandes(module_name, function_name):
    """"+season start" ne doit rester accessible a un membre dans AUCUNE des trois."""
    import importlib

    evaluate = getattr(importlib.import_module(module_name), function_name)
    decision = asyncio.run(
        evaluate(Bot(), command_name="season start", author=MEMBRE, guild=Guild())
    )
    assert not decision.allowed, f"{module_name} laisse un membre lancer une saison"
