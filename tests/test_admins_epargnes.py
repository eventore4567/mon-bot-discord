"""Le propriétaire n'est jamais sanctionné, et on choisit les admins épargnés.

21/11/2026 : « y a un admin, c'est le owner, donc si possible éviter de le
sanctionner — ou bien, quand on met sanctionner les admins, on a un choix des
admins à pas sanctionner. »

Les deux étaient absents. Pire : ``is_automod_exempt`` épargnait bien le
propriétaire, mais quatre chemins de sanction lisaient ``_admin_exempte``, qui
ne le faisait pas. Encore deux politiques pour une seule décision.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

import config  # noqa: E402
from cogs import automod as automod_mod  # noqa: E402
from cogs.automod import AutoMod  # noqa: E402


@pytest.fixture(autouse=True)
def _detection_admin(monkeypatch):
    """``_is_discord_administrator`` exige un vrai ``discord.Member``.

    Ce qu'on teste ici est la POLITIQUE d'exemption, pas la détection du statut
    d'administrateur — elle a ses propres tests. On la remplace donc par une
    lecture directe de la permission, ce qui garde les cas lisibles.
    """
    monkeypatch.setattr(
        automod_mod, "_is_discord_administrator",
        lambda membre: bool(getattr(getattr(membre, "guild_permissions", None),
                                    "administrator", False)),
    )


class _Perms:
    def __init__(self, administrator=True):
        self.administrator = administrator


def _membre(identifiant, *, admin=True, owner_id=999, roles=()):
    membre = SimpleNamespace(
        id=identifiant,
        guild_permissions=_Perms(admin),
        roles=list(roles),
        bot=False,
    )
    # ``_is_discord_administrator`` passe par ``_as_member``, qui interroge
    # ``guild.get_member`` : la doublure doit le fournir.
    membre.guild = SimpleNamespace(
        id=1, owner_id=owner_id, get_member=lambda _id, m=membre: m,
    )
    return membre


def _cog(*, strict=True, override=None, roles_exemptes=frozenset(), epargnes=frozenset()):
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2), db=SimpleNamespace())
    cog.admins_soumis = AsyncMock(return_value=strict)
    cog.get_immunity_override_cached = AsyncMock(return_value=override)
    cog.get_exempt_roles_cached = AsyncMock(return_value=set(roles_exemptes))
    cog.epargnes_du_mode_strict = AsyncMock(return_value=set(epargnes))
    return cog


@pytest.fixture(autouse=True)
def _owners(monkeypatch):
    monkeypatch.setattr(config, "OWNER_IDS", [4242], raising=False)


@pytest.mark.asyncio
async def test_le_proprietaire_du_serveur_n_est_jamais_sanctionne():
    """Le défaut signalé. Discord lui refuse de toute façon tout timeout.

    La seule sanction qui lui soit applicable est le retrait de ses rôles « à
    risque » — sur son propre serveur, ça n'a aucun sens.
    """
    cog = _cog(strict=True)
    assert await cog._admin_exempte(_membre(999, owner_id=999), 1) is True


@pytest.mark.asyncio
async def test_un_proprietaire_de_sentrix_non_plus():
    cog = _cog(strict=True)
    assert await cog._admin_exempte(_membre(4242, owner_id=999), 1) is True


@pytest.mark.asyncio
async def test_un_admin_quelconque_reste_sanctionne_en_mode_strict():
    """Sinon l'option « Sanctionner les admins » ne servirait à rien."""
    cog = _cog(strict=True)
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is False


@pytest.mark.asyncio
async def test_un_admin_designe_est_epargne():
    """« un choix des admins à pas sanctionner »."""
    cog = _cog(strict=True, epargnes={123})
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is True


@pytest.mark.asyncio
async def test_une_immunite_explicitement_coupee_gagne_sur_le_role_exempte():
    """``+immunity off`` veut dire « sanctionne-moi ». Il gagne sur le rôle.

    Trouvé en revue : la fonction retombait sur le test de rôle après un refus
    explicite et renvoyait ``True`` quand même. ``is_automod_exempt`` et
    ``security_filter_applies_to``, eux, laissent le refus l'emporter — donc la
    même question recevait deux réponses selon le chemin emprunté.
    """
    cog = _cog(strict=True, override=False, roles_exemptes={55})
    membre = _membre(123, owner_id=999, roles=[SimpleNamespace(id=55)])
    assert await cog._admin_exempte(membre, 1) is False


@pytest.mark.asyncio
async def test_une_immunite_accordee_epargne_encore():
    cog = _cog(strict=True, override=True)
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is True


@pytest.mark.asyncio
async def test_un_role_exempte_epargne_aussi_les_filtres_de_messages():
    """Ça marchait déjà pour l'anti-nuke, et pas ici. Une seule règle."""
    cog = _cog(strict=True, roles_exemptes={55})
    membre = _membre(123, owner_id=999, roles=[SimpleNamespace(id=55)])
    assert await cog._admin_exempte(membre, 1) is True


@pytest.mark.asyncio
async def test_hors_mode_strict_tout_admin_est_epargne():
    cog = _cog(strict=False)
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is True


@pytest.mark.asyncio
async def test_un_membre_sans_permission_admin_n_est_pas_concerne():
    """La fonction ne parle que des administrateurs ; un membre ordinaire passe
    par les filtres normaux, et ne doit pas se faire exempter par erreur."""
    cog = _cog(strict=False)
    assert await cog._admin_exempte(_membre(123, admin=False), 1) is False


@pytest.mark.asyncio
async def test_une_base_illisible_n_epargne_personne():
    """Un échec de lecture ne doit pas ouvrir une porte.

    L'inverse — exempter en cas de doute — ferait d'une panne de base une
    désactivation silencieuse du mode strict.
    """
    cog = _cog(strict=True)
    cog.get_immunity_override_cached = AsyncMock(side_effect=RuntimeError("pool fermé"))
    cog.get_exempt_roles_cached = AsyncMock(side_effect=RuntimeError("pool fermé"))
    cog.epargnes_du_mode_strict = AsyncMock(side_effect=RuntimeError("pool fermé"))
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is False


@pytest.mark.asyncio
async def test_l_anti_nuke_lit_la_meme_liste():
    """Trouvé en revue : la commande promettait, l'anti-nuke bannissait quand même.

    C'est le même interrupteur « Sanctionner les admins » qui gouverne les deux
    chemins ; un admin épargné ne doit pas se faire bannir par le second.
    """
    import discord

    cog = _cog(strict=True, epargnes={123})
    membre = _membre(123, owner_id=999)
    guild = membre.guild
    cog.admin_epargne_en_strict = AsyncMock(return_value=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(automod_mod, "_as_member", lambda u, g: u)
        mp.setattr(discord, "Member", type(membre))
        assert await cog._admin_exempte_antinuke(guild, membre) is True
    cog.admin_epargne_en_strict.assert_awaited_once()


@pytest.mark.asyncio
async def test_la_liste_a_sa_propre_table_pas_celle_de_immunity():
    """Trouvé en revue, et c'était le plus grave des quatre.

    ``user_immunity_settings`` est lue par services/moderation.py::_hierarchy_error
    pour REFUSER un +ban, +kick, +mute ou +warn manuel. Y écrire aurait empêché
    le propriétaire de modérer à la main l'admin qu'il venait seulement
    d'exempter de l'AutoMod — l'inverse de ce qu'il demandait.
    """
    ecrits: list[tuple] = []

    cog = AutoMod.__new__(AutoMod)
    cog._epargnes_schema_pret = True

    async def execute(requete, params=()):
        ecrits.append((requete, params))

    cog.bot = SimpleNamespace(db=SimpleNamespace(execute=execute))
    await cog.definir_admin_epargne(1, 123, True, 7)
    await cog.definir_admin_epargne(1, 123, False, 7)

    assert all("user_immunity_settings" not in r for r, _ in ecrits)
    assert "INSERT INTO sentrix_strict_epargnes" in ecrits[0][0]
    assert "DELETE FROM sentrix_strict_epargnes" in ecrits[1][0]


@pytest.mark.asyncio
async def test_la_liste_est_mise_en_cache_et_purgee_a_l_ecriture():
    """Elle est lue sur le chemin de chaque message d'administrateur.

    Sans purge à l'écriture, épargner quelqu'un n'aurait aucun effet pendant
    trente secondes — le genre de latence qui fait croire que ça ne marche pas.
    """
    lectures = {"n": 0}

    cog = AutoMod.__new__(AutoMod)
    cog._epargnes_schema_pret = True

    async def fetchall(requete, params=()):
        lectures["n"] += 1
        return [{"user_id": 123}]

    cog.bot = SimpleNamespace(db=SimpleNamespace(fetchall=fetchall, execute=AsyncMock()))
    assert await cog.epargnes_du_mode_strict(1) == {123}
    assert await cog.epargnes_du_mode_strict(1) == {123}
    assert lectures["n"] == 1, "la deuxième lecture n'a pas pris le cache"

    await cog.definir_admin_epargne(1, 456, True, 7)
    await cog.epargnes_du_mode_strict(1)
    assert lectures["n"] == 2, "le cache n'a pas été purgé à l'écriture"


def test_les_quatre_chemins_de_sanction_lisent_la_meme_regle():
    """Garde-fou : c'est leur divergence qui a créé le défaut.

    ``is_automod_exempt`` épargnait le propriétaire, ``_admin_exempte`` non, et
    quatre chemins de sanction ne lisaient que le second.
    """
    import io

    source = io.open("cogs/automod.py", encoding="utf-8").read()
    assert "async def admin_epargne_en_strict" in source
    # L'ancienne forme en une ligne ne doit pas revenir.
    assert ("return _is_discord_administrator(member) and not await "
            "self.admins_soumis(guild_id)") not in source
