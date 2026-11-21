"""« Donne les emojis de SentriX » et de quoi les récupérer (21/11/2026).

Rien ne permettait de les voir : ils sont posés par le code, nom par nom, et
aucune commande ne les listait. ``noms_disponibles()`` ne convenait pas — elle
lit le dossier d'images, donc elle annonce aussi celles qui n'ont pas encore
été téléversées et dont le marquage n'existe pas.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import sentrix_emoji_sync as cog_emojis  # noqa: E402
from utils import sentrix_emojis  # noqa: E402

FIXE = "<:sentrix_bouclier:111>"
ANIME = "<a:sentrix_c_loading:222>"


@pytest.fixture(autouse=True)
def _pack(monkeypatch):
    monkeypatch.setattr(sentrix_emojis, "_RESOLUS", {
        "sentrix_bouclier": FIXE,
        "sentrix_c_loading": ANIME,
        "sentrix_admin": "<:sentrix_admin:333>",
        # Une entrée sans marquage : la synchronisation a échoué pour celle-là.
        "sentrix_casse": "",
    }, raising=False)


# ------------------------------------------------------------------- catalogue

def test_le_catalogue_ignore_les_icones_sans_marquage():
    """Les annoncer ferait promettre des icônes qui ne s'afficheront pas."""
    assert "sentrix_casse" not in sentrix_emojis.catalogue()
    assert len(sentrix_emojis.catalogue()) == 3


def test_animes_et_fixes_se_distinguent_par_le_marquage_pas_par_le_nom():
    """``sentrix_c_*`` est la convention des variantes colorées, et toutes ne
    sont pas animées. Seul le ``<a:`` du marquage dit la vérité."""
    assert set(sentrix_emojis.catalogue(animes=True)) == {"sentrix_c_loading"}
    assert set(sentrix_emojis.catalogue(animes=False)) == {"sentrix_bouclier", "sentrix_admin"}


def test_le_catalogue_est_trie():
    assert list(sentrix_emojis.catalogue()) == sorted(sentrix_emojis.catalogue())


# ----------------------------------------------------------------- découpage

def test_une_page_ne_coupe_jamais_une_ligne():
    """Un marquage coupé en deux s'afficherait en texte brut des deux côtés."""
    lignes = [f"{ANIME} `nom_{i}` → `{ANIME}`" for i in range(200)]
    pages = cog_emojis._pages(lignes)
    assert len(pages) > 1
    assert all(len(p) <= cog_emojis.LIMITE_MESSAGE for p in pages)
    # Aucune ligne perdue ni scindée.
    assert sum(len(p.split("\n")) for p in pages) == len(lignes)
    for page in pages:
        assert all(l.endswith("`") for l in page.split("\n"))


def test_chaque_ligne_donne_le_lien_direct_de_l_image():
    """C'est ce qui sert vraiment : un lien s'ouvre et se réutilise ailleurs."""
    ligne = cog_emojis._lignes({"sentrix_bouclier": FIXE})[0]
    assert ligne.startswith(FIXE)
    assert "`sentrix_bouclier`" in ligne
    assert "https://cdn.discordapp.com/emojis/111.png" in ligne


def test_une_icone_animee_donne_un_lien_gif():
    """L'extension vient du ``a`` du marquage, pas du nom.

    Un ``.png`` sur une icône animée donnerait la première image seulement.
    """
    ligne = cog_emojis._lignes({"sentrix_c_loading": ANIME})[0]
    assert "https://cdn.discordapp.com/emojis/222.gif" in ligne


def test_le_mode_codes_rend_le_marquage():
    ligne = cog_emojis._lignes({"sentrix_bouclier": FIXE}, codes=True)[0]
    assert f"`{FIXE}`" in ligne
    assert "cdn.discordapp.com" not in ligne


def test_un_marquage_illisible_retombe_sur_le_code():
    """Mieux vaut le code que rien : la ligne reste utilisable."""
    assert cog_emojis.lien("pas un marquage") == ""
    ligne = cog_emojis._lignes({"sentrix_x": "pas un marquage"})[0]
    assert "`pas un marquage`" in ligne


# ------------------------------------------------------------------- commande

def _ctx(guild=True, envoyes=None, prives=None):
    # `prives or []` rendrait une NOUVELLE liste tant que la mienne est vide —
    # c'est-à-dire exactement au moment qui compte : les envois partaient dans
    # le vide et le test voyait une liste vide. On lie les listes telles quelles.
    envoyes = [] if envoyes is None else envoyes
    prives = [] if prives is None else prives
    auteur = SimpleNamespace(
        id=7, send=AsyncMock(side_effect=lambda t, **k: prives.append(t)),
    )
    return SimpleNamespace(
        guild=SimpleNamespace(id=1) if guild else None,
        author=auteur,
        clean_prefix="+",
        send=AsyncMock(side_effect=lambda t, **k: envoyes.append(t)),
    )


@pytest.mark.asyncio
async def test_un_filtre_repond_dans_le_salon(monkeypatch):
    envoyes: list[str] = []
    ctx = _ctx(envoyes=envoyes)
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(cog, ctx, recherche="bouclier")

    tout = "\n".join(envoyes)
    assert "sentrix_bouclier" in tout
    assert "sentrix_admin" not in tout
    ctx.author.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_terme_sans_resultat_le_dit(monkeypatch):
    envoie = AsyncMock()
    monkeypatch.setattr(cog_emojis.panels, "envoyer", envoie)
    monkeypatch.setattr(cog_emojis.panels, "depuis_embed", lambda e: e)
    monkeypatch.setattr(cog_emojis.embeds, "error", lambda t: t)
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(
        cog, _ctx(), recherche="rienquicorrespond"
    )
    assert "Aucune icône" in envoie.await_args.args[1]


@pytest.mark.asyncio
async def test_un_gros_catalogue_part_en_prive(monkeypatch):
    """Quatre cents lignes dans un salon, personne ne les a demandées."""
    monkeypatch.setattr(
        sentrix_emojis, "_RESOLUS",
        {f"sentrix_n{i}": f"<:sentrix_n{i}:{i}>" for i in range(80)},
        raising=False,
    )
    monkeypatch.setattr(cog_emojis.panels, "envoyer", AsyncMock())
    monkeypatch.setattr(cog_emojis.embeds, "success", lambda t: t)
    prives: list[str] = []
    envoyes: list[str] = []
    ctx = _ctx(envoyes=envoyes, prives=prives)
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(cog, ctx)

    assert prives, "rien n'est parti en privé"
    assert not envoyes, "le salon a reçu le catalogue complet"


@pytest.mark.asyncio
async def test_messages_prives_fermes_explique_quoi_faire(monkeypatch):
    """Un refus muet laisserait croire que la commande est cassée."""
    import discord

    monkeypatch.setattr(
        sentrix_emojis, "_RESOLUS",
        {f"sentrix_n{i}": f"<:sentrix_n{i}:{i}>" for i in range(80)},
        raising=False,
    )
    envoie = AsyncMock()
    monkeypatch.setattr(cog_emojis.panels, "envoyer", envoie)
    monkeypatch.setattr(cog_emojis.panels, "depuis_embed", lambda e: e)
    monkeypatch.setattr(cog_emojis.embeds, "error", lambda t: t)
    ctx = _ctx()
    ctx.author.send = AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "cannot send"
    ))
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(cog, ctx)

    message = envoie.await_args.args[1]
    assert "messages privés sont fermés" in message
    assert "+emojis animes" in message


@pytest.mark.asyncio
async def test_l_entete_annonce_les_liens_et_la_facon_d_avoir_les_codes():
    envoyes: list[str] = []
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(
        cog, _ctx(envoyes=envoyes), recherche="bouclier"
    )
    assert "lien direct" in envoyes[0]
    assert "+emojis codes" in envoyes[0]


@pytest.mark.asyncio
async def test_le_mode_codes_dit_ou_le_code_fonctionne_vraiment():
    """Les emojis d'application n'appartiennent qu'au bot qui les possède.

    Donner le code sans le dire ferait croire à un bug quand le coller dans un
    message personnel laisse du texte brut. C'est une règle de Discord, pas une
    limite de SentriX, et ça doit être écrit.
    """
    envoyes: list[str] = []
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(
        cog, _ctx(envoyes=envoyes), recherche="bouclier codes"
    )
    assert "emoji d'application" in envoyes[0]
    assert f"`{FIXE}`" in "\n".join(envoyes)


@pytest.mark.asyncio
async def test_le_mot_codes_ne_fait_pas_partie_de_la_recherche():
    """Sinon « bouclier codes » chercherait une icône nommée « bouclier codes »."""
    envoyes: list[str] = []
    cog = cog_emojis.SentriXEmojiCatalogue(SimpleNamespace())
    await cog_emojis.SentriXEmojiCatalogue.emojis.callback(
        cog, _ctx(envoyes=envoyes), recherche="bouclier codes"
    )
    assert "sentrix_bouclier" in "\n".join(envoyes)


def test_l_alias_emoji_list_n_est_pas_repris():
    """cogs/utility.py le porte déjà, pour les emojis DU SERVEUR.

    Un alias en doublon fait refuser le cog entier au chargement : toutes les
    icônes auraient disparu avec lui.
    """
    commande = cog_emojis.SentriXEmojiCatalogue.emojis
    assert "emoji-list" not in commande.aliases
    assert commande.name == "emojis"
