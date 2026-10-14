"""Un membre privilégié qui abuse ne doit plus passer sous les radars.

Mesuré avant ce travail : ``_maybe_escalate`` se terminait par

    if member.id == guild.owner_id or member.top_role >= guild.me.top_role:
        return None, count  # hors de portée du bot, inutile d'essayer

Un staff dont le rôle dépasse celui de SentriX ne produisait donc aucun
signal : ni sanction, ni retrait de rôle, ni alerte, ni trace. Discord
refuse effectivement l'exclusion, l'expulsion et le bannissement dans ce
cas — mais le retrait de rôle suit une autre règle, il suffit que le rôle
visé soit sous celui du bot.

La réponse est graduée : une bêtise isolée ne déclenche rien, seul le
seuil le plus haut compte comme abus avéré.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import automod


def _role(nom: str, position: int, *, dangereux: bool, managed: bool = False):
    r = MagicMock(spec=discord.Role)
    r.name, r.position, r.managed = nom, position, managed
    r.permissions = MagicMock()
    for perm in automod.DANGEROUS_PERMS:
        setattr(r.permissions, perm, dangereux)
    r.__lt__ = lambda self, autre: self.position < autre.position
    r.__ge__ = lambda self, autre: self.position >= autre.position
    return r


def _monde(roles_membre, position_bot=50, *, manage_roles=True):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1000
    guild.owner_id = 7
    guild.default_role = _role("@everyone", 0, dangereux=False)

    bot_role = _role("SentriX", position_bot, dangereux=True)
    guild.me = MagicMock(spec=discord.Member)
    guild.me.top_role = bot_role
    guild.me.guild_permissions = MagicMock(manage_roles=manage_roles)

    membre = MagicMock(spec=discord.Member)
    membre.id = 42
    membre.roles = [guild.default_role, *roles_membre]
    membre.top_role = max(roles_membre, key=lambda r: r.position)
    membre.remove_roles = AsyncMock()

    guild.owner = MagicMock()
    guild.fetch_member = AsyncMock(return_value=guild.owner)
    return guild, membre


def _cog(guild):
    cog = MagicMock(spec=automod.AutoMod)
    cog.infraction_tracker = MagicMock()
    cog.infraction_tracker.reinitialiser = MagicMock()
    cog.log_action = AsyncMock()
    cog._repondre_abus_privilegie = automod.AutoMod._repondre_abus_privilegie.__get__(cog)
    return cog


@pytest.fixture(autouse=True)
def _pas_de_mp(monkeypatch):
    monkeypatch.setattr(automod.panels, "envoyer", AsyncMock())
    monkeypatch.setattr(automod.panels, "depuis_embed", MagicMock())


async def _repondre(cog, guild, membre, count):
    return await cog._repondre_abus_privilegie(guild, membre, "spam répété", count)


@pytest.mark.parametrize("count", [1, 2, automod.ABUS_PRIVILEGIE_SEUIL - 1])
@pytest.mark.asyncio
async def test_une_betise_isolee_ne_declenche_rien(count):
    """« Un admin c'est pas sanctionné s'il fait une bêtise. »"""
    guild, membre = _monde([_role("Admin", 90, dangereux=True)])
    cog = _cog(guild)
    assert await _repondre(cog, guild, membre, count) is None
    membre.remove_roles.assert_not_awaited()
    cog.log_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_abus_avere_retire_les_roles_a_risque_accessibles():
    """Le rôle à risque est sous SentriX : il tombe, même si le membre le dépasse."""
    staff = _role("Staff", 20, dangereux=True)      # sous SentriX (50)
    au_dessus = _role("Direction", 90, dangereux=False)  # au-dessus, sans permission à risque
    guild, membre = _monde([staff, au_dessus])
    assert membre.top_role.position > guild.me.top_role.position, "le membre doit dépasser le bot"

    cog = _cog(guild)
    resultat = await _repondre(cog, guild, membre, automod.ABUS_PRIVILEGIE_SEUIL)

    assert resultat == "derank"
    membre.remove_roles.assert_awaited_once()
    assert list(membre.remove_roles.await_args.args) == [staff]
    cog.log_action.assert_awaited_once()
    cog.infraction_tracker.reinitialiser.assert_called_once()


@pytest.mark.asyncio
async def test_un_abus_hors_de_portee_alerte_quand_meme():
    """Le point essentiel : ne plus jamais abandonner en silence."""
    au_dessus = _role("Direction", 90, dangereux=True)  # à risque ET au-dessus de SentriX
    guild, membre = _monde([au_dessus])
    cog = _cog(guild)

    resultat = await _repondre(cog, guild, membre, automod.ABUS_PRIVILEGIE_SEUIL)

    assert resultat is None, "rien n'a pu être retiré"
    membre.remove_roles.assert_not_awaited()
    cog.log_action.assert_awaited_once(), "le propriétaire doit être prévenu malgré tout"
    carte = cog.log_action.await_args.args[1]
    texte = str(carte.to_dict() if hasattr(carte, "to_dict") else carte)
    assert "Direction" in texte, "l'alerte doit nommer le rôle bloquant"


@pytest.mark.asyncio
async def test_un_role_gere_par_discord_est_laisse_tranquille():
    """Retirer un rôle d'intégration (bot, boost) échouerait et n'a aucun sens."""
    integre = _role("Bot Admin", 10, dangereux=True, managed=True)
    guild, membre = _monde([integre, _role("Direction", 90, dangereux=False)])
    cog = _cog(guild)
    await _repondre(cog, guild, membre, automod.ABUS_PRIVILEGIE_SEUIL)
    membre.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_sans_la_permission_de_gerer_les_roles_on_alerte_sans_echouer():
    staff = _role("Staff", 20, dangereux=True)
    guild, membre = _monde([staff, _role("Direction", 90, dangereux=False)], manage_roles=False)
    cog = _cog(guild)
    assert await _repondre(cog, guild, membre, automod.ABUS_PRIVILEGIE_SEUIL) is None
    membre.remove_roles.assert_not_awaited()
    cog.log_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_refus_de_discord_est_rapporte_et_non_avale():
    staff = _role("Staff", 20, dangereux=True)
    guild, membre = _monde([staff, _role("Direction", 90, dangereux=False)])
    membre.remove_roles = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "non"))
    cog = _cog(guild)
    assert await _repondre(cog, guild, membre, automod.ABUS_PRIVILEGIE_SEUIL) is None
    cog.log_action.assert_awaited_once()


def test_le_seuil_d_abus_suit_les_regles_d_escalade():
    """Il ne doit pas diverger si quelqu'un modifie ESCALATION_RULES."""
    assert automod.ABUS_PRIVILEGIE_SEUIL == max(s for s, _ in automod.ESCALATION_RULES)
    assert automod.ABUS_PRIVILEGIE_SEUIL > min(s for s, _ in automod.ESCALATION_RULES)


def test_le_resultat_derank_a_une_etiquette_lisible():
    """Sans cela, la carte d'incident afficherait le mot brut « derank »."""
    assert automod.ESCALATION_LABELS.get("derank")


def test_la_doc_du_module_n_affirme_plus_que_les_admins_sont_exemptes():
    """is_automod_exempt ne regarde aucune permission : la doc le disait à tort."""
    doc = automod.__doc__ or ""
    assert "Exemptions : administrateurs" not in doc
    assert "n'exempte de rien" in doc


# --------------------------------------------------------------------------
# La politique de contenu vivante
#
# Erreur que ces tests existent pour ne plus refaire : j'avais conclu que
# cogs/content_filter_policy ne tournait pas en production, au motif qu'il
# n'est pas dans les 48 entrées d'EXTENSIONS de main.py. Les journaux Railway
# du 2026-10-14 20:00:58 disent le contraire — « Politique contenu activée ».
# Il remplace _maybe_escalate sur l'instance du cog, donc TOUS les appelants
# passent par lui et jamais par l'original : sans branchement explicite,
# _repondre_abus_privilegie était du code mort.
#
# L'absence d'EXTENSIONS ne prouve pas qu'un module est mort. Seuls les
# journaux de production le prouvent.
# --------------------------------------------------------------------------


def test_la_politique_de_contenu_atteint_la_reponse_a_l_abus():
    """Garde de source : le branchement doit exister dans la politique vivante."""
    import inspect

    from cogs import content_filter_policy

    source = inspect.getsource(content_filter_policy)
    assert "_repondre_abus_privilegie" in source, (
        "delete_only_escalation n'appelle pas la réponse : elle serait du code mort"
    )
    assert "_automod_module.ABUS_PRIVILEGIE_SEUIL" in source, (
        "le seuil doit venir du module, pas de l'instance du cog"
    )


@pytest.mark.asyncio
async def test_la_politique_de_contenu_ne_sanctionne_toujours_pas_un_membre_normal():
    """La règle « suppression seule » reste entière pour qui est à portée."""
    import inspect

    from cogs import content_filter_policy

    source = inspect.getsource(content_filter_policy)
    # La condition doit exiger que le membre DÉPASSE le bot ; sinon la politique
    # se mettrait à agir sur des membres ordinaires, ce qu'elle interdit.
    assert "member.top_role >= moi.top_role" in source
    assert "member.id != guild.owner_id" in source
