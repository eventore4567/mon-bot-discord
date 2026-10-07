"""Service de traduction, testé avec un fournisseur simulé — aucun appel réseau."""
from __future__ import annotations

import asyncio
import time

import pytest

from services import translation as tr


def run(coro):
    return asyncio.run(coro)


def fake(text, source, target):
    return f"[{source}->{target}] {text}"


def test_traduction_simple():
    result = run(tr.translate("Bonjour", "en", provider=fake))
    assert result.text == "[auto->en] Bonjour" and result.target == "en" and result.source == "auto"


@pytest.mark.parametrize("saisie, code", [
    ("EN", "en"), ("français", "fr"), ("anglais", "en"), ("pt-BR", "pt"),
    ("zh", "zh-CN"), ("zh-TW", "zh-TW"), ("chinese", "zh-CN"), ("ko", "ko"),
])
def test_les_langues_se_saisissent_naturellement(saisie, code):
    assert tr.normalise_language(saisie) == code


def test_langue_discord_de_l_utilisateur():
    assert tr.locale_to_language("en-US") == "en"
    assert tr.locale_to_language("fr") == "fr"
    assert tr.locale_to_language("zh-CN") == "zh-CN"
    assert tr.locale_to_language("") == "en"


@pytest.mark.parametrize("texte, code", [("", "empty"), ("   ", "empty"), ("x" * (tr.MAX_LENGTH + 1), "too_long")])
def test_textes_refuses_avant_tout_appel(texte, code):
    appels = []
    with pytest.raises(tr.TranslationError) as err:
        run(tr.translate(texte, "en", provider=lambda *a: appels.append(a) or "x"))
    assert err.value.code == code and appels == []


def test_une_panne_du_fournisseur_n_accuse_pas_l_utilisateur():
    """Avant : toute erreur répondait « Vérifiez le code de langue »."""
    def panne(*_):
        raise ConnectionError("réseau coupé")

    with pytest.raises(tr.TranslationError) as err:
        run(tr.translate("Bonjour", "en", provider=panne))
    assert err.value.code == "unavailable"


def test_une_langue_inconnue_est_signalee_comme_telle():
    class LanguageNotSupportedException(Exception):
        pass

    def refuse(*_):
        raise LanguageNotSupportedException("xx")

    with pytest.raises(tr.TranslationError) as err:
        run(tr.translate("Bonjour", "xx", provider=refuse))
    assert err.value.code == "unsupported_language"


def test_la_traduction_ne_fige_pas_le_bot():
    """L'appel est SYNCHRONE côté bibliothèque ; il doit tourner hors de la boucle.

    Pendant une traduction lente, une autre tâche doit continuer à avancer — c'est
    ce qui manquait : tout le bot se figeait pendant chaque /translate.
    """
    def lent(text, source, target):
        time.sleep(0.4)
        return text

    async def scenario():
        battements = 0

        async def coeur():
            nonlocal battements
            for _ in range(8):
                await asyncio.sleep(0.03)
                battements += 1

        await asyncio.gather(tr.translate("Bonjour", "en", provider=lent), coeur())
        return battements

    assert run(scenario()) == 8


def test_autocompletion():
    assert ("English (en)", "en") in tr.suggestions("eng")
    assert all(code for _, code in tr.suggestions(""))
    assert len(tr.suggestions("")) <= 25
