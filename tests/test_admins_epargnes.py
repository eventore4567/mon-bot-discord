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


def _cog(*, strict=True, override=None, roles_exemptes=frozenset()):
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2), db=SimpleNamespace())
    cog.admins_soumis = AsyncMock(return_value=strict)
    cog.get_immunity_override_cached = AsyncMock(return_value=override)
    cog.get_exempt_roles_cached = AsyncMock(return_value=set(roles_exemptes))
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
    cog = _cog(strict=True, override=True)
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is True


@pytest.mark.asyncio
async def test_une_immunite_explicitement_coupee_n_epargne_pas():
    """``+immunity off`` veut dire « sanctionne-moi ». On ne l'inverse pas.

    L'absence de ligne vaut None, et seul un True explicite épargne : lire la
    valeur comme un booléen aurait transformé un refus d'immunité en immunité.
    """
    cog = _cog(strict=True, override=False)
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is False


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
    assert await cog._admin_exempte(_membre(123, owner_id=999), 1) is False


@pytest.mark.asyncio
async def test_la_liste_s_ecrit_dans_la_meme_table_que_immunity():
    """Une deuxième liste finirait par contredire la première."""
    ecrits: list[tuple] = []

    cog = AutoMod.__new__(AutoMod)
    cog.immunity_overrides_cache = {}

    async def execute(requete, params=()):
        ecrits.append((requete, params))

    cog.bot = SimpleNamespace(db=SimpleNamespace(execute=execute))
    await cog.definir_admin_epargne(1, 123, True)

    assert "user_immunity_settings" in ecrits[0][0]
    assert ecrits[0][1] == (1, 123, 1)
    assert cog.immunity_overrides_cache[(1, 123)] is True

    await cog.definir_admin_epargne(1, 123, False)
    assert ecrits[1][1] == (1, 123, 0)
    assert cog.immunity_overrides_cache[(1, 123)] is False


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
