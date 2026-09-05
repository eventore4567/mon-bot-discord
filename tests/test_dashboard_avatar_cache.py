"""/api/me réencode la photo de profil Discord en base64 à chaque appel.

Sans cache, chaque appel retéléchargeait l'image depuis le CDN Discord (nouvelle
connexion HTTP à chaque fois) et la réencodait, gonflant chaque réponse à ~350 Ko.
Avec la boucle MutationObserver corrigée dans dashboard_no_decorative_icons.py,
/api/me pouvait être appelé des dizaines de fois par seconde — sans ce cache,
chacun de ces appels aurait aussi frappé le CDN Discord, au risque de se faire
bloquer/limiter côté Discord en plus de gaspiller de la bande passante.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard_user_avatar_v46 as avatar_v46  # noqa: E402


def _reinitialiser() -> None:
    avatar_v46._avatar_cache.clear()


def _session(user_id: str = "1", avatar_url: str = "") -> dict:
    return {"user": {"id": user_id, "username": "Jayden", "avatar_url": avatar_url}}


def _reponse_cdn(corps: bytes = b"\x89PNG-fake-bytes", content_type: str = "image/png"):
    upstream = MagicMock()
    upstream.status = 200
    upstream.read = AsyncMock(return_value=corps)
    upstream.headers = {"Content-Type": content_type}
    return upstream


class _FauxClientSession:
    """Simule aiohttp.ClientSession en comptant les vrais appels au CDN."""

    compteur_get = 0

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def get(self, _url):
        _FauxClientSession.compteur_get += 1
        return _reponse_cdn_ctx()


class _CdnCtx:
    async def __aenter__(self):
        return _reponse_cdn()

    async def __aexit__(self, *_exc):
        return False


def _reponse_cdn_ctx():
    return _CdnCtx()


async def _plusieurs_appels_ne_retelechargent_pas():
    _reinitialiser()
    _FauxClientSession.compteur_get = 0
    request = MagicMock()
    request.app = {"bot": None}
    session = _session()

    with patch.object(avatar_v46, "ClientSession", _FauxClientSession):
        premier = await avatar_v46._avatar_data_uri(request, session)
        for _ in range(20):
            suivant = await avatar_v46._avatar_data_uri(request, session)
            assert suivant == premier

    assert _FauxClientSession.compteur_get == 1, (
        f"20 appels rapprochés pour le même utilisateur doivent tenir sur un seul "
        f"téléchargement CDN, pas {_FauxClientSession.compteur_get}"
    )


def test_les_appels_rapproches_ne_retelechargent_pas_le_cdn():
    import asyncio

    asyncio.run(_plusieurs_appels_ne_retelechargent_pas())


async def _deux_utilisateurs_restent_independants():
    _reinitialiser()
    _FauxClientSession.compteur_get = 0
    request = MagicMock()
    request.app = {"bot": None}

    with patch.object(avatar_v46, "ClientSession", _FauxClientSession):
        await avatar_v46._avatar_data_uri(request, _session(user_id="1"))
        await avatar_v46._avatar_data_uri(request, _session(user_id="2"))
        await avatar_v46._avatar_data_uri(request, _session(user_id="1"))

    assert _FauxClientSession.compteur_get == 2, (
        "deux utilisateurs différents doivent chacun déclencher leur propre "
        f"téléchargement, pas se mélanger ({_FauxClientSession.compteur_get})"
    )


def test_deux_utilisateurs_ne_sont_pas_fusionnes():
    import asyncio

    asyncio.run(_deux_utilisateurs_restent_independants())


async def _changement_de_pp_invalide_le_cache():
    _reinitialiser()
    _FauxClientSession.compteur_get = 0
    request = MagicMock()
    request.app = {"bot": None}

    with patch.object(avatar_v46, "ClientSession", _FauxClientSession):
        await avatar_v46._avatar_data_uri(
            request, _session(avatar_url="https://cdn.discordapp.com/avatars/1/a.png")
        )
        await avatar_v46._avatar_data_uri(
            request, _session(avatar_url="https://cdn.discordapp.com/avatars/1/b.png")
        )

    assert _FauxClientSession.compteur_get == 2, (
        "une vraie nouvelle photo de profil (URL CDN différente) doit être "
        "retéléchargée, pas servie depuis l'ancien cache"
    )


def test_une_nouvelle_pp_invalide_le_cache():
    import asyncio

    asyncio.run(_changement_de_pp_invalide_le_cache())


if __name__ == "__main__":
    import unittest

    unittest.main()
