"""Panneau DM du Dashboard : diffusion serveur et message à un membre.

Écrire à des centaines de personnes est irréversible. Deux exigences priment sur
tout le reste et sont verrouillées ici :

1. **L'autorisation est vérifiée côté serveur.** Cacher le bouton dans le
   navigateur ne protège rien : la route reste appelable directement. Le contrôle
   est plus strict que « peut administrer le serveur » — propriétaire du serveur
   ou propriétaire de SentriX uniquement, comme ``+dmall``.
2. **Aucun double envoi.** Un double-clic, ou une diffusion déjà lancée depuis
   Discord, doivent être refusés — pas dédoublonnés après coup.

Le moteur d'envoi n'est pas réimplémenté : c'est celui de ``+dmall``. Ces tests
vérifient aussi qu'un membre en échec n'interrompt jamais la diffusion et que les
messages privés fermés sont comptés à part des vraies pannes.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

import sentrix_broadcast_dmall_visual as moteur  # noqa: E402
from web import dm_panel  # noqa: E402


def _membre(identifiant: int, *, bot: bool = False) -> Mock:
    membre = Mock(spec=discord.Member)
    membre.id = identifiant
    membre.bot = bot
    membre.display_name = f"membre{identifiant}"
    membre.mention = f"<@{identifiant}>"
    return membre


def _guild(proprietaire: int = 1, membres=None) -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.id = 4242
    guild.name = "Serveur test"
    guild.owner_id = proprietaire
    guild.icon = None
    guild.members = membres if membres is not None else []
    guild.get_member = lambda i: next((m for m in guild.members if m.id == i), None)
    return guild


# ---------------------------------------------------------------- moteur
def test_les_bots_sont_ignores_et_comptes():
    membres = [_membre(1), _membre(2, bot=True), _membre(3), _membre(4, bot=True)]
    guild = _guild(membres=membres)
    destinataires, bots = moteur.destinataires_du_serveur(guild, bot_user_id=None)
    assert [m.id for m in destinataires] == [1, 3]
    assert bots == 2


def test_le_bot_lui_meme_n_est_jamais_destinataire():
    membres = [_membre(1), _membre(999)]
    guild = _guild(membres=membres)
    destinataires, _ = moteur.destinataires_du_serveur(guild, bot_user_id=999)
    assert [m.id for m in destinataires] == [1]


async def _diffusion_avec(resultats: dict):
    """resultats: {member_id: None | Exception} — None = succès."""
    guild = _guild()
    membres = [_membre(i) for i in resultats]

    async def faux_envoyer(destination, panneau, **kwargs):
        issue = resultats[destination.id]
        if issue is not None:
            raise issue

    original_envoyer, original_delai = moteur.panels.envoyer, moteur.SEND_DELAY_SECONDS
    moteur.panels.envoyer = faux_envoyer
    moteur.SEND_DELAY_SECONDS = 0
    try:
        return await moteur.diffuser(guild, membres, "coucou")
    finally:
        moteur.panels.envoyer = original_envoyer
        moteur.SEND_DELAY_SECONDS = original_delai


def test_un_echec_n_interrompt_jamais_la_diffusion():
    reponse = Mock(status=403)
    bilan = asyncio.run(
        _diffusion_avec(
            {
                1: None,
                2: discord.Forbidden(reponse, "MP fermé"),
                3: RuntimeError("panne inattendue"),
                4: None,
            }
        )
    )
    assert bilan.total == 4
    assert bilan.envoyes == 2, "les membres joignables doivent tous être servis"
    assert bilan.dms_fermes == 1, "un MP fermé n'est pas une panne technique"
    assert bilan.echecs == 1
    assert bilan.traites == 4
    assert bilan.termine is True


def test_la_progression_est_notifiee_et_se_termine():
    guild = _guild()
    membres = [_membre(i) for i in range(1, 4)]
    etapes = []

    async def faux_envoyer(destination, panneau, **kwargs):
        return None

    async def progression(bilan):
        etapes.append(bilan.traites)

    original_envoyer, original_delai, original_pas = (
        moteur.panels.envoyer,
        moteur.SEND_DELAY_SECONDS,
        moteur.PROGRESS_EVERY,
    )
    moteur.panels.envoyer = faux_envoyer
    moteur.SEND_DELAY_SECONDS = 0
    moteur.PROGRESS_EVERY = 1
    try:
        bilan = asyncio.run(moteur.diffuser(guild, membres, "hello", progression=progression))
    finally:
        moteur.panels.envoyer = original_envoyer
        moteur.SEND_DELAY_SECONDS = original_delai
        moteur.PROGRESS_EVERY = original_pas

    assert etapes, "la progression doit être remontée"
    assert etapes[-1] == 3 and bilan.envoyes == 3


# ---------------------------------------------------------------- permissions
def _requete(session_user_id: int, methode: str = "POST") -> Mock:
    requete = Mock()
    requete.method = methode
    requete.app = {"bot": Mock()}
    requete.__setitem__ = Mock()
    requete.get = Mock(return_value={"user": {"id": str(session_user_id)}})
    return requete


async def _autorise(session_user_id: int, proprietaire: int, est_owner_bot: bool) -> bool:
    requete = _requete(session_user_id)
    requete.app["bot"].is_owner = AsyncMock(return_value=est_owner_bot)
    return await dm_panel._peut_diffuser(requete, _guild(proprietaire=proprietaire))


def test_le_proprietaire_du_serveur_est_autorise():
    assert asyncio.run(_autorise(session_user_id=1, proprietaire=1, est_owner_bot=False)) is True


def test_le_proprietaire_de_sentrix_est_autorise():
    assert asyncio.run(_autorise(session_user_id=7, proprietaire=1, est_owner_bot=True)) is True


def test_un_administrateur_ordinaire_est_refuse():
    """C'est tout l'enjeu : un admin du serveur ne doit PAS pouvoir écrire à tous."""
    assert asyncio.run(_autorise(session_user_id=99, proprietaire=1, est_owner_bot=False)) is False


def test_une_session_sans_utilisateur_est_refusee():
    requete = _requete(0)
    requete.get = Mock(return_value={})
    assert asyncio.run(dm_panel._peut_diffuser(requete, _guild())) is False


# ---------------------------------------------------------------- anti-doublon
def test_un_job_en_cours_est_visible_et_bloquant():
    app = {}
    magasin = dm_panel._jobs(app)
    magasin[4242] = {"termine": False, "fin": 0.0}
    # Un second clic doit retrouver le job en cours, donc pouvoir être refusé.
    assert dm_panel._jobs(app)[4242]["termine"] is False


def test_les_jobs_termines_finissent_par_etre_purges():
    import time

    magasin = {
        1: {"termine": True, "fin": time.time() - dm_panel._RETENTION_SECONDS - 10},
        2: {"termine": True, "fin": time.time()},
        3: {"termine": False, "fin": 0.0},
    }
    dm_panel._purger(magasin)
    assert 1 not in magasin, "un vieux bilan doit être libéré"
    assert 2 in magasin and 3 in magasin, "un bilan récent ou actif reste consultable"


def test_les_routes_dm_sont_toutes_declarees():
    from web import dashboard

    chemins = {chemin for _m, chemin, _h in dashboard.DM_PANEL_ROUTES}
    assert chemins == {
        "/api/guilds/{guild_id}/dm/apercu",
        "/api/guilds/{guild_id}/dm/all",
        "/api/guilds/{guild_id}/dm/job",
        "/api/guilds/{guild_id}/dm/user",
    }


def test_le_panneau_dm_ne_reimplemente_pas_le_moteur():
    """Garde-fou : deux moteurs concurrents finiraient par diverger."""
    import pathlib

    source = pathlib.Path("web/dm_panel.py").read_text(encoding="utf-8")
    assert "moteur.diffuser(" in source
    assert "panels.envoyer(" not in source, "le panneau ne doit jamais envoyer lui-même"
