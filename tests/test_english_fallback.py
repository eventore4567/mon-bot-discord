"""Serveur en anglais : ce que le dictionnaire ne traduit pas est traduit quand même."""
import asyncio

import discord

from utils import english_fallback as ef


def test_detection_francais_prudente():
    assert ef.est_francais("Aucun salon de logs n'est configuré pour ce serveur.")
    assert ef.est_francais("Désactiver")
    assert not ef.est_francais("No log channel is configured for this server.")
    assert not ef.est_francais("<@123> · **500** 🪙")
    assert not ef.est_francais("")


def test_traduction_protege_mentions_code_et_liens(monkeypatch):
    from services import translation as tr

    vus = []

    async def faux(text, target, *, source="auto", provider=None):
        vus.append(text)
        return tr.Translation(text=text.replace("Bienvenue sur le serveur", "Welcome to the server")
                              .replace("utilisez", "use"), target=target, source=source)

    monkeypatch.setattr(tr, "translate", faux)
    ef._cache.clear()
    ef._coupe_jusqua = 0.0
    texte = "Bienvenue sur le serveur <@42>, utilisez `+help` ou https://x.y/fr"
    resultat = asyncio.run(ef.traduire_texte(texte))
    assert resultat == "Welcome to the server <@42>, use `+help` ou https://x.y/fr"
    assert "<@42>" not in vus[0] and "`+help`" not in vus[0]
    # Deuxième fois : depuis le cache, sans appel.
    asyncio.run(ef.traduire_texte(texte))
    assert len(vus) == 1


def test_panne_coupe_la_passe_et_garde_le_texte(monkeypatch):
    from services import translation as tr

    appels = []

    async def panne(text, target, *, source="auto", provider=None):
        appels.append(text)
        raise tr.TranslationError("unavailable")

    monkeypatch.setattr(tr, "translate", panne)
    ef._cache.clear()
    ef._coupe_jusqua = 0.0
    texte = "Aucun membre trouvé dans ce salon."
    assert asyncio.run(ef.traduire_texte(texte)) == texte
    assert asyncio.run(ef.traduire_texte("Choisissez un autre salon.")) == "Choisissez un autre salon."
    assert len(appels) == 1  # coupée après la panne
    ef._coupe_jusqua = 0.0


def test_vue_et_embed_traduits_sur_place(monkeypatch):
    from services import translation as tr

    async def faux(text, target, *, source="auto", provider=None):
        return tr.Translation(text="EN:" + text, target=target, source=source)

    monkeypatch.setattr(tr, "translate", faux)
    monkeypatch.setenv("SENTRIX_TRADUCTION_AUTO", "1")
    ef._cache.clear()
    ef._coupe_jusqua = 0.0

    async def scenario():
        vue = discord.ui.LayoutView()
        bloc = discord.ui.Container()
        bloc.add_item(discord.ui.TextDisplay("Aucun ticket ouvert pour le moment."))
        vue.add_item(bloc)
        embed = discord.Embed(title="Configuration du serveur", description="Already English text here.")
        contenu = await ef.traduire_charge("Votre demande est enregistrée.", [embed], vue)
        return contenu, embed, bloc.children[0].content

    contenu, embed, texte = asyncio.run(scenario())
    assert contenu == "EN:Votre demande est enregistrée."
    assert embed.title == "EN:Configuration du serveur"
    assert embed.description == "Already English text here."
    assert texte == "EN:Aucun ticket ouvert pour le moment."


def test_interrupteur_coupe_la_seconde_passe(monkeypatch):
    monkeypatch.setenv("SENTRIX_TRADUCTION_AUTO", "0")
    assert asyncio.run(ef.traduire_charge("Votre demande est enregistrée.", [], None)) == "Votre demande est enregistrée."
