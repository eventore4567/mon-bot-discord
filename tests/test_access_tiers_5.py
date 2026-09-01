"""Les 5 niveaux d'acces SentriX, verifies par profil.

1 MEMBRE            2 MODERATEUR        3 ADMIN
4 PROPRIETAIRE DU SERVEUR               5 PROPRIETAIRE DE SENTRIX

Ces tests appellent la VRAIE fonction de decision, la meme que le prefixe et le slash.
"""
import asyncio

import pytest

from utils import access_matrix as M

OWNER_ID, ADMIN_ID, MOD_ID, MEMBER_ID, CREATOR_ID = 1, 2, 3, 4, 5

PERMISSION_FIELDS = (
    "administrator", "ban_members", "kick_members", "moderate_members",
    "manage_messages", "manage_channels", "manage_roles", "manage_guild",
    "manage_nicknames", "move_members", "manage_emojis", "manage_expressions",
    "view_audit_log", "mention_everyone", "manage_webhooks",
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
MODERATEUR = Member(MOD_ID, Perms(
    ban_members=True, kick_members=True, moderate_members=True,
    manage_messages=True, manage_channels=True, manage_nicknames=True,
    move_members=True,
))
ADMIN = Member(ADMIN_ID, Perms(administrator=True))
PROPRIETAIRE = Member(OWNER_ID, Perms(administrator=True))
CREATEUR = Member(CREATOR_ID, Perms())


def allowed(command, author):
    decision = asyncio.run(
        M.evaluate(Bot(), command_name=command, author=author, guild=Guild())
    )
    return decision.allowed, decision


# --------------------------------------------------------------- NIVEAU 1
MEMBRE_OK = ["help", "ping", "balance", "daily", "level", "leaderboard",
             "serverinfo", "gameseason", "season top", "sentrixpro profile",
             "ticket", "play", "rps"]


@pytest.mark.parametrize("command", MEMBRE_OK)
def test_niveau1_membre_peut_utiliser_les_commandes_publiques(command):
    ok, decision = allowed(command, MEMBRE)
    assert ok, f"{command} refuse a un membre : {decision.message}"


@pytest.mark.parametrize("command", ["ban", "kick", "clear", "setup", "antinuke",
                                     "wipe-server", "reset-economy", "sync", "bl",
                                     "season start", "sentrixpro lockdown"])
def test_niveau1_membre_ne_peut_rien_faire_de_sensible(command):
    ok, _ = allowed(command, MEMBRE)
    assert not ok, f"{command} accessible a un simple membre"


# --------------------------------------------------------------- NIVEAU 2
@pytest.mark.parametrize("command,permission", [
    ("ban", "ban_members"), ("kick", "kick_members"),
    ("mute", "moderate_members"), ("clear", "manage_messages"),
    ("lock", "manage_channels"), ("nickname", "manage_nicknames"),
])
def test_niveau2_moderateur_utilise_la_permission_discord_reelle(command, permission):
    assert M.DISCORD_PERMISSION_COMMANDS.get(command) == permission
    ok, _ = allowed(command, MODERATEUR)
    assert ok, f"{command} refuse a un moderateur qui possede {permission}"


def test_niveau2_une_permission_manquante_bloque_la_commande_correspondante():
    sans_ban = Member(MOD_ID, Perms(kick_members=True, manage_messages=True))
    assert not allowed("ban", sans_ban)[0], "ban passe sans ban_members"
    assert allowed("kick", sans_ban)[0], "kick refuse malgre kick_members"


@pytest.mark.parametrize("command", ["setup", "antinuke", "wipe-server", "sync"])
def test_niveau2_moderateur_ne_touche_pas_a_la_configuration(command):
    assert not allowed(command, MODERATEUR)[0], f"{command} accessible a un moderateur"


# --------------------------------------------------------------- NIVEAU 3
@pytest.mark.parametrize("command", ["setup", "antinuke", "panic", "create-logs",
                                     "season start", "sentrixpro lockdown", "ban"])
def test_niveau3_admin_configure_et_modere(command):
    ok, decision = allowed(command, ADMIN)
    assert ok, f"{command} refuse a un administrateur : {decision.message}"


@pytest.mark.parametrize("command", sorted(M.GUILD_OWNER_COMMANDS))
def test_niveau3_admin_ne_peut_pas_detruire_le_serveur(command):
    ok, decision = allowed(command, ADMIN)
    assert not ok, f"{command} accessible a un administrateur non proprietaire"
    assert "propri" in decision.message.casefold()


@pytest.mark.parametrize("command", sorted(M.OWNER_ONLY_COMMANDS))
def test_niveau3_admin_ne_peut_pas_utiliser_les_commandes_sentrix(command):
    assert not allowed(command, ADMIN)[0], f"{command} accessible a un administrateur"


# --------------------------------------------------------------- NIVEAU 4
@pytest.mark.parametrize("command", sorted(M.GUILD_OWNER_COMMANDS))
def test_niveau4_le_proprietaire_du_serveur_peut_tout_sur_son_serveur(command):
    ok, decision = allowed(command, PROPRIETAIRE)
    assert ok, f"{command} refuse au proprietaire : {decision.message}"


@pytest.mark.parametrize("command", sorted(M.OWNER_ONLY_COMMANDS))
def test_niveau4_le_proprietaire_du_serveur_reste_hors_des_commandes_sentrix(command):
    ok, decision = allowed(command, PROPRIETAIRE)
    assert not ok, f"{command} accessible au proprietaire du serveur"
    assert "sentrix" in decision.message.casefold()


# --------------------------------------------------------------- NIVEAU 5
@pytest.mark.parametrize("command", sorted(M.OWNER_ONLY_COMMANDS))
def test_niveau5_le_createur_utilise_les_commandes_globales(command):
    ok, decision = allowed(command, CREATEUR)
    assert ok, f"{command} refuse au createur : {decision.message}"


# --------------------------------------------------------------- MESSAGES
def test_les_refus_nomment_la_permission_requise():
    _, decision = allowed("ban", MEMBRE)
    assert "Bannir des membres" in decision.message

    _, decision = allowed("sync", MEMBRE)
    assert "SentriX" in decision.message

    _, decision = allowed("wipe-server", ADMIN)
    assert "proprietaire du serveur" in decision.message.casefold()


def test_aucun_refus_ne_divulgue_d_information_sensible():
    for command in ("ban", "sync", "wipe-server", "setup"):
        _, decision = allowed(command, MEMBRE)
        low = decision.message.casefold()
        for leak in ("token", "traceback", "sqlite", "postgres", "0x", "/users/"):
            assert leak not in low, f"{command} divulgue '{leak}'"


# --------------------------------------------------- PARITE ET HERITAGE
def test_les_cinq_niveaux_sont_disjoints():
    niveaux = {
        "membre": set(M.PUBLIC_COMMANDS),
        "proprietaire-serveur": set(M.GUILD_OWNER_COMMANDS),
        "proprietaire-sentrix": set(M.OWNER_ONLY_COMMANDS),
        "moderation": set(M.DISCORD_PERMISSION_COMMANDS),
    }
    for gauche in niveaux:
        for droite in niveaux:
            if gauche >= droite:
                continue
            partage = niveaux[gauche] & niveaux[droite]
            assert not partage, f"{gauche} / {droite} partagent {sorted(partage)}"


def test_une_sous_commande_herite_de_son_groupe_par_defaut():
    """C'est ce qui garantit la parite : le garde evalue la racine."""
    assert M.resolve_name("create manox", "create") == "create"
    assert M.resolve_name("logs reset", "logs") == "logs"
    assert M.access_tier("season top") == M.access_tier("season")


def test_une_sous_commande_declaree_est_plus_stricte_que_son_groupe():
    """Sans cette exception, "+season start" restait accessible a tout membre."""
    assert "season" in M.PUBLIC_COMMANDS
    assert M.resolve_name("season start", "season") == "season start"
    assert M.access_tier("season start") != "public"
    assert not allowed("season start", MEMBRE)[0]
    assert allowed("season top", MEMBRE)[0]


def test_un_alias_ne_contourne_aucune_permission():
    """discord.py resout l'alias en objet Command : c'est .name canonique qui est evalue."""
    assert M.resolve_name("", "ban") == "ban"
    assert not allowed("ban", MEMBRE)[0]


def test_le_niveau_est_identique_en_prefixe_et_en_slash():
    """Les deux transports appellent evaluate() avec le meme nom resolu."""
    from cogs import permission_guard

    class FauxCommande:
        def __init__(self, qualified, root_name):
            self.qualified_name = qualified
            self.name = qualified.split(" ")[-1]
            self.root_parent = None if " " not in qualified else FauxRacine(root_name)

    class FauxRacine:
        def __init__(self, name):
            self.name = name

    for qualified, racine in [("ban", "ban"), ("season start", "season"),
                              ("season top", "season"), ("wipe-server", "wipe-server")]:
        commande = FauxCommande(qualified, racine)
        nom = permission_guard.command_root_name(commande)
        assert M.access_tier(nom) == M.access_tier(M.resolve_name(qualified, racine))
