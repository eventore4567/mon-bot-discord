"""11/11/2026 : ce qui s'est passé pendant une coupure doit finir dans les logs.

« Fais un truc avec mémoire même quand il est off, pour tout. » Un bannissement
ou une expulsion pendant une coupure ne laissait aucune trace : le staff ne
pouvait même pas savoir qu'il lui manquait quelque chose. Discord, lui, garde
45 jours de journal d'audit — il suffit de le relire, et de savoir quelle
tranche relire, ce que mesure le battement de présence.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import rattrapage_logs  # noqa: E402
from cogs.rattrapage_logs import RattrapageLogs, carte_du_rattrapage, nom_de  # noqa: E402


class _Base:
    def __init__(self, presence: str | None = None):
        self._valeurs = {rattrapage_logs.PRESENCE_CLE: presence} if presence else {}

    async def get_setting(self, key, default=None):
        return self._valeurs.get(key, default)

    async def set_setting(self, key, value):
        self._valeurs[key] = value


def _cog(presence: str | None = None):
    cog = RattrapageLogs.__new__(RattrapageLogs)
    cog.bot = SimpleNamespace(db=_Base(presence), user=SimpleNamespace(id=1))
    cog._fait = False
    cog._tache = None
    return cog


def _entree(action, *, cible="Tomioka", auteur_id=50, raison="", minutes=5):
    return SimpleNamespace(
        id=12345, action=action,
        target=SimpleNamespace(display_name=cible, id=99), target_id=99,
        user=SimpleNamespace(display_name="Modo", id=auteur_id), reason=raison,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes),
    )


def _guild(entrees, *, audit=True):
    async def audit_logs(**_kwargs):
        for e in entrees:
            yield e

    return SimpleNamespace(
        id=1,
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=audit)),
        audit_logs=audit_logs,
    )


@pytest.mark.asyncio
async def test_sans_presence_enregistree_rien_n_est_rattrape():
    """Premier démarrage : aucune absence connue, donc aucun passé à inventer."""
    assert await _cog().duree_de_l_absence() == 0


@pytest.mark.asyncio
async def test_un_redemarrage_normal_ne_rattrape_rien():
    """La bascule HA dure ~6 s : rien n'a eu le temps d'être manqué."""
    cog = _cog(str(int(time.time()) - 10))
    assert await cog.duree_de_l_absence() == 0


@pytest.mark.asyncio
async def test_une_absence_trop_longue_ne_rattrape_rien():
    """Au-delà de la fenêtre, republier noierait les salons de logs."""
    cog = _cog(str(int(time.time()) - rattrapage_logs.FENETRE_MAX - 10))
    assert await cog.duree_de_l_absence() == 0


@pytest.mark.asyncio
async def test_une_vraie_coupure_est_mesuree():
    cog = _cog(str(int(time.time()) - 3600))
    absence = await cog.duree_de_l_absence()
    assert 3500 < absence < 3700


@pytest.mark.asyncio
async def test_les_actions_manquees_sont_republiees(monkeypatch):
    envoyes = []

    async def _faux_send(bot, guild, log_type, embed, **kwargs):
        envoyes.append((log_type, embed, kwargs.get("event_key")))
        return True

    monkeypatch.setattr(rattrapage_logs.log_service, "send_log", _faux_send)

    cog = _cog()
    guild = _guild([
        _entree(discord.AuditLogAction.ban, raison="raid"),
        _entree(discord.AuditLogAction.kick),
        # Un message supprimé n'est pas dans la table : Discord ne le conserve pas.
        _entree(discord.AuditLogAction.message_delete),
    ])
    envoyees = await cog.rattraper(guild, datetime.now(timezone.utc) - timedelta(hours=1))

    assert envoyees == 2
    assert [log_type for log_type, _e, _k in envoyes] == ["member_ban", "member_kick"]
    # La clé d'événement porte l'identifiant de l'entrée d'audit : deux démarrages
    # successifs ne peuvent pas publier deux fois la même action.
    assert all(cle and cle.endswith("12345") for _t, _e, cle in envoyes)


@pytest.mark.asyncio
async def test_les_actions_de_sentrix_ne_sont_pas_republiees(monkeypatch):
    """Un ban fait par SentriX est déjà journalisé par la commande qui l'a fait."""
    envoyes = []

    async def _faux_send(bot, guild, log_type, embed, **kwargs):
        envoyes.append(log_type)
        return True

    monkeypatch.setattr(rattrapage_logs.log_service, "send_log", _faux_send)
    cog = _cog()
    guild = _guild([_entree(discord.AuditLogAction.ban, auteur_id=1)])
    assert await cog.rattraper(guild, datetime.now(timezone.utc)) == 0
    assert envoyes == []


@pytest.mark.asyncio
async def test_sans_permission_audit_aucun_appel():
    cog = _cog()
    guild = _guild([_entree(discord.AuditLogAction.ban)], audit=False)
    assert await cog.rattraper(guild, datetime.now(timezone.utc)) == 0


def test_la_carte_dit_que_c_est_un_rattrapage():
    """Sans ça, le staff lit une action d'il y a deux heures comme si elle arrivait."""
    carte = carte_du_rattrapage(_entree(discord.AuditLogAction.ban, raison="raid"), "Membre banni")
    assert "hors ligne" in (carte.description or "")
    textes = [str(champ.value) for champ in carte.fields]
    assert any("Tomioka" in t for t in textes) and any("Modo" in t for t in textes)
    assert any("raid" in t for t in textes)


def test_une_cible_disparue_garde_son_identifiant():
    """Un rôle supprimé n'existe plus : on montre son ID plutôt que « Inconnu »."""
    assert nom_de(None, 4242) == "ID 4242"
    assert nom_de(None, None) == "Inconnu"
