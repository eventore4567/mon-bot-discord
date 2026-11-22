"""Escalade des filtres de contenu : un avertissement, puis le mute.

Décision du propriétaire, 22/11/2026 : « 1 avertissement puis mute », et une
heure sans infraction remet tout à zéro. Avant ce jour :

* l'escalade réellement exécutée en production était « suppression seule »
  (cogs/content_filter_policy la remplaçait sur l'instance du cog) : personne
  n'était jamais muté par un filtre de contenu ;
* la version de cogs/automod.py, morte, avait quatre fuites : deux seuils
  identiques ``(6, "mute")`` et ``(3, "mute")``, un compteur remis à zéro après
  chaque sanction, une fenêtre glissante d'une heure, et un compteur en mémoire
  perdu à chaque redémarrage.

Ces tests utilisent une VRAIE base SQLite (database.db.Database) : une doublure
de base qui ne reproduisait pas le comportement réel a déjà validé un bug.
"""
from __future__ import annotations

import os
import time as vrai_time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest
import pytest_asyncio

from cogs import automod
from database.db import Database

GUILD_ID = 1000
OWNER_ID = 7
MEMBRE_ID = 42


@pytest.fixture
def horloge(monkeypatch):
    """Horloge murale contrôlée, utilisée par le compteur en base."""
    instant = [1_800_000_000.0]
    monkeypatch.setattr(
        automod, "time",
        SimpleNamespace(time=lambda: instant[0], monotonic=vrai_time.monotonic),
    )
    monkeypatch.setattr(automod.log_service, "mark_sanction", MagicMock())
    return instant


@pytest_asyncio.fixture
async def base(tmp_path):
    db = Database(str(tmp_path / "escalade.db"))
    await db.connect()
    yield db
    await db.close()


def _cog(db, *, escalade=True, override=None):
    """Un cog AutoMod neuf : en créer un second simule un redémarrage."""
    cog = automod.AutoMod.__new__(automod.AutoMod)
    cog.bot = SimpleNamespace(db=db, user=SimpleNamespace(id=999))
    cog.get_automod_cached = AsyncMock(return_value={"escalation": 1 if escalade else 0})
    cog.get_immunity_override_cached = AsyncMock(return_value=override)
    cog._repondre_abus_privilegie = AsyncMock(return_value="derank")
    cog._alerter_permission_manquante = AsyncMock()
    return cog


def _guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.owner_id = OWNER_ID
    guild.me = SimpleNamespace(
        top_role=50,
        guild_permissions=SimpleNamespace(moderate_members=True, manage_messages=True),
    )
    return guild


def _membre(membre_id=MEMBRE_ID, *, role=10, admin=False):
    membre = MagicMock(spec=discord.Member)
    membre.id = membre_id
    membre.top_role = role
    membre.guild_permissions = SimpleNamespace(administrator=admin)
    membre.timeout = AsyncMock()
    membre.timed_out_until = None
    return membre


def _duree(membre) -> int:
    """Durée en secondes du dernier timeout demandé à Discord."""
    fin = membre.timeout.await_args.args[0]
    return round((fin - discord.utils.utcnow()).total_seconds() / 60) * 60


async def _infraction(cog, membre):
    return await cog._maybe_escalate(_guild(), membre, "lien interdit")


@pytest.mark.asyncio
async def test_un_avertissement_puis_le_mute(base, horloge):
    cog, membre = _cog(base), _membre()

    assert await _infraction(cog, membre) == ("avertissement", 1)
    membre.timeout.assert_not_awaited()

    horloge[0] += 60
    assert await _infraction(cog, membre) == ("mute", 2)
    membre.timeout.assert_awaited_once()
    assert _duree(membre) == 300
    assert cog.duree_mute_escalade(GUILD_ID, MEMBRE_ID) == 300


@pytest.mark.asyncio
async def test_un_mute_ne_remet_pas_le_compteur_a_zero(base, horloge):
    """Fuite n°2 : le membre qui recommence juste après son mute montait de
    nouveau par l'avertissement. Il passe maintenant au palier suivant."""
    cog, membre = _cog(base), _membre()
    for _ in range(2):
        await _infraction(cog, membre)
        horloge[0] += 60

    assert await _infraction(cog, membre) == ("mute", 3)
    assert _duree(membre) == 600
    horloge[0] += 60
    await _infraction(cog, membre)
    assert _duree(membre) == 1800


@pytest.mark.asyncio
async def test_le_mute_plafonne_a_deux_heures(base, horloge):
    cog, membre = _cog(base), _membre()
    for _ in range(10):
        await _infraction(cog, membre)
        horloge[0] += 60
    assert _duree(membre) == 7200


@pytest.mark.asyncio
async def test_une_heure_de_calme_efface_tout(base, horloge):
    cog, membre = _cog(base), _membre()
    await _infraction(cog, membre)
    horloge[0] += 60
    assert (await _infraction(cog, membre))[0] == "mute"

    horloge[0] += automod.ESCALATION_WINDOW + 1
    assert await _infraction(cog, membre) == ("avertissement", 1)
    horloge[0] += 60
    await _infraction(cog, membre)
    assert _duree(membre) == 300, "les paliers de mute repartent aussi de zéro"


@pytest.mark.asyncio
async def test_moins_d_une_heure_entre_deux_infractions_ne_compte_pas_comme_du_calme(base, horloge):
    """L'heure se compte depuis la DERNIÈRE infraction, pas depuis la première."""
    cog, membre = _cog(base), _membre()
    await _infraction(cog, membre)
    horloge[0] += automod.ESCALATION_WINDOW - 1
    assert (await _infraction(cog, membre))[0] == "mute"


@pytest.mark.asyncio
async def test_le_compteur_survit_au_redemarrage(base, horloge):
    """Fuite n°4 : le compteur vivait en mémoire."""
    membre = _membre()
    await _infraction(_cog(base), membre)
    horloge[0] += 60

    apres_redemarrage = _cog(base)
    assert await _infraction(apres_redemarrage, membre) == ("mute", 2)


@pytest.mark.asyncio
async def test_chaque_membre_a_son_compteur(base, horloge):
    cog = _cog(base)
    await _infraction(cog, _membre(42))
    assert (await _infraction(cog, _membre(43)))[0] == "avertissement"


@pytest.mark.asyncio
async def test_escalade_desactivee_compte_sans_sanctionner(base, horloge):
    cog, membre = _cog(base, escalade=False), _membre()
    assert await _infraction(cog, membre) == (None, 1)
    assert await _infraction(cog, membre) == (None, 2)
    membre.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_proprietaire_du_serveur_n_est_pas_sanctionne(base, horloge):
    cog, proprio = _cog(base), _membre(OWNER_ID, role=99)
    for _ in range(3):
        assert await _infraction(cog, proprio) == (None, 0)
    proprio.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_proprietaire_qui_coupe_son_immunite_est_compte(base, horloge):
    cog, proprio = _cog(base, override=False), _membre(OWNER_ID, role=10)
    assert await _infraction(cog, proprio) == ("avertissement", 1)


@pytest.mark.asyncio
async def test_le_proprietaire_du_bot_n_est_jamais_sanctionne(base, horloge, monkeypatch):
    from utils import owner_access

    monkeypatch.setattr(owner_access, "is_bot_owner_id", lambda uid: int(uid or 0) == MEMBRE_ID)
    cog, membre = _cog(base), _membre()
    for _ in range(3):
        assert await _infraction(cog, membre) == (None, 0)
    membre.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_membre_hors_de_portee_passe_par_la_reponse_a_l_abus(base, horloge):
    """Discord refuse tout timeout sur lui : seule la réponse à l'abus agit."""
    cog, staff = _cog(base), _membre(role=90)
    assert await _infraction(cog, staff) == ("derank", 1)
    cog._repondre_abus_privilegie.assert_awaited_once()
    assert cog._repondre_abus_privilegie.await_args.args[3] == 1
    staff.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_administrateur_sous_le_bot_passe_aussi_par_la_reponse_a_l_abus(base, horloge):
    """Discord refuse le timeout d'un administrateur, même sous le rôle du bot."""
    cog, admin = _cog(base), _membre(role=10, admin=True)
    assert (await _infraction(cog, admin))[0] == "derank"
    cog._repondre_abus_privilegie.assert_awaited_once()
    admin.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_timeout_refuse_bascule_sur_le_mute_sentrix(base, horloge):
    """Revue Codex (PR #710) : Discord refuse le timeout → on n'abandonne pas.
    SentriX supprime lui-même les messages du membre et prévient le propriétaire,
    comme pour le spam (_muter)."""
    cog, membre = _cog(base), _membre()
    await _infraction(cog, membre)
    horloge[0] += 60
    membre.timeout.side_effect = discord.Forbidden(MagicMock(status=403), "non")
    assert (await _infraction(cog, membre))[0] == "mute"
    assert cog._est_mute_sentrix(GUILD_ID, MEMBRE_ID)
    cog._alerter_permission_manquante.assert_awaited_once()


@pytest.mark.asyncio
async def test_sans_aucune_permission_le_palier_ne_monte_pas(base, horloge):
    cog, membre, guild = _cog(base), _membre(), _guild()
    guild.me.guild_permissions = SimpleNamespace(moderate_members=False, manage_messages=False)
    await cog._maybe_escalate(guild, membre, "lien")
    horloge[0] += 60
    assert (await cog._maybe_escalate(guild, membre, "lien"))[0] == "mute_failed"

    horloge[0] += 60
    assert (await _infraction(cog, membre))[0] == "mute"
    assert _duree(membre) == 300, "un mute raté ne compte pas comme un palier"


@pytest.mark.asyncio
async def test_un_timeout_plus_long_deja_en_place_est_garde(base, horloge):
    """Revue Codex (PR #710) : un mute d'un jour posé par un modérateur ne doit
    pas être raccourci à cinq minutes par l'escalade."""
    from datetime import timedelta

    cog, membre = _cog(base), _membre()
    await _infraction(cog, membre)
    horloge[0] += 60
    membre.timed_out_until = discord.utils.utcnow() + timedelta(days=1)
    assert (await _infraction(cog, membre))[0] == "mute"
    membre.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_recidive_dans_la_meme_rafale_mute_quand_meme(base, horloge, monkeypatch):
    """Revue Codex (PR #710) : une rafale est UN incident (une carte, un
    avertissement), et seul son premier message atteignait l'escalade. Une
    deuxième insulte envoyée dans les 30 s n'était donc jamais comptée."""
    monkeypatch.setattr(automod.panels, "texte_court", AsyncMock())
    cog, membre = _cog(base), _membre()
    message = SimpleNamespace(guild=_guild(), author=membre, channel=MagicMock())
    incident = automod._Incident(
        started=0.0, filter_name="multilingual_toxicity", reason="insulte",
        channel_id=1, message_id=1, raw_content="", deleted_ok=True,
    )
    incident.action, incident.infractions = await cog._maybe_escalate(message.guild, membre, "insulte")
    assert incident.action == "avertissement"

    await cog._escalader_dans_incident(message, incident, "multilingual_toxicity", "insulte")
    assert incident.action == "mute" and incident.duration_s == 300
    automod.panels.texte_court.assert_awaited_once()

    # Les messages suivants de la même rafale ne font pas grimper le palier.
    await cog._escalader_dans_incident(message, incident, "multilingual_toxicity", "insulte")
    membre.timeout.assert_awaited_once()


@pytest.mark.asyncio
async def test_la_politique_de_contenu_ne_remplace_plus_l_escalade(base, horloge):
    """Le chemin RÉELLEMENT emprunté en production : après installation de la
    politique de contenu, l'instance doit encore appeler la vraie méthode."""
    from cogs import content_filter_policy

    cog = _cog(base)
    bot = SimpleNamespace(get_cog=lambda name: cog if name == "Automod" else None)
    content_filter_policy._patch_automod(bot)

    assert cog._sentrix_delete_only_content_policy is True
    assert "_maybe_escalate" not in vars(cog)
    membre = _membre()
    await cog._maybe_escalate(_guild(), membre, "lien")
    horloge[0] += 60
    assert (await cog._maybe_escalate(_guild(), membre, "lien"))[0] == "mute"


def test_le_salon_annonce_le_mute_a_venir():
    vue = automod.AutoMod._content_notice_view(
        "<@42>", "blacklist_word", suite="Prochaine infraction dans l'heure : mute."
    )
    texte = vue.children[0].children[0].content
    assert "Prochaine infraction dans l'heure : mute." in texte


@pytest.mark.asyncio
async def test_des_messages_simultanes_ne_font_qu_une_sanction(base, horloge, monkeypatch):
    """Revue Codex (PR #710, 2e passage) : cinq détections simultanées dans un
    même incident passaient toutes la garde « déjà sanctionné ? » avant que le
    premier mute n'aboutisse, et appliquaient 5 min, 10 min, 30 min, 1 h, 2 h."""
    import asyncio

    monkeypatch.setattr(automod.panels, "texte_court", AsyncMock())
    cog, membre = _cog(base), _membre()

    async def timeout_lent(*_args, **_kwargs):
        await asyncio.sleep(0.05)

    membre.timeout = AsyncMock(side_effect=timeout_lent)
    message = SimpleNamespace(guild=_guild(), author=membre, channel=MagicMock())
    incident = automod._Incident(
        started=0.0, filter_name="antilink", reason="lien",
        channel_id=1, message_id=1, raw_content="", deleted_ok=True,
    )
    incident.action, incident.infractions = await cog._maybe_escalate(message.guild, membre, "lien")

    await asyncio.gather(*(
        cog._escalader_dans_incident(message, incident, "antilink", "lien") for _ in range(5)
    ))
    membre.timeout.assert_awaited_once()
    assert incident.action == "mute" and incident.duration_s == 300
