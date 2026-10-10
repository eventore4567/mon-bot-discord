"""Le texte sobre garde les unités ; une erreur simple reste du texte, avec son corps.

Mesuré le 09/10/2026 : « **0 ** au total » et « 500  ajoutés » dans toute
l'économie (la pièce 🪙 effacée comme une décoration), et un panneau « Pay »
VIDE pour un membre sans assez d'argent — la couche des cartes reconvertissait
le texte d'erreur et perdait le corps.
"""
from __future__ import annotations

import asyncio

from utils import embeds
from utils import sentrix_panels as panels


def test_une_unite_apres_un_nombre_est_gardee():
    assert embeds.strip_emojis("500 🪙 ajoutés") == "500 🪙 ajoutés"
    assert embeds.strip_emojis("**+200** 🪙") == "**+200** 🪙"
    assert embeds.strip_emojis("**0 🪙** au total") == "**0 🪙** au total"
    assert embeds.strip_emojis("3 <:coin:123456789012345678> gagnés") == "3 <:coin:123456789012345678> gagnés"


def test_une_decoration_reste_retiree():
    assert embeds.strip_emojis("🎉 Bravo") == " Bravo"
    assert embeds.strip_emojis("Niveau 5 ✅") == "Niveau 5 "
    assert embeds.strip_emojis("Il a 20 ans 😀 ok") == "Il a 20 ans  ok"


def test_le_symbole_configure_par_un_serveur_devient_une_unite():
    embeds.UNIT_EMOJIS.add("🍪")
    try:
        assert embeds.strip_emojis("12 🍪 gagnés") == "12 🍪 gagnés"
    finally:
        embeds.UNIT_EMOJIS.discard("🍪")


def test_une_erreur_en_texte_brut_porte_le_signal_pendant_l_envoi():
    vus = []

    class Salon:
        async def send(self, **kwargs):
            vus.append((kwargs.get("content"), panels.TEXTE_BRUT.get()))

    asyncio.run(panels._envoyer_texte_brut_depuis_panneau(
        Salon(), "Vous n'avez pas assez d'argent liquide.", ephemere=False, extra={},
    ))
    assert vus == [("Vous n'avez pas assez d'argent liquide.", True)]
    assert panels.TEXTE_BRUT.get() is False


def test_un_emoji_personnalise_comme_monnaie_n_est_plus_tronque():
    """« <:piece:123…> » fait plus de 16 caractères : tronqué, il s'affichait cassé."""
    from cogs.setup_v2_core import clean_currency_symbol

    marquage = "<:piece:123456789012345678>"
    assert clean_currency_symbol(marquage) == marquage
    assert clean_currency_symbol("<a:piece:123456789012345678>") == "<a:piece:123456789012345678>"
    assert clean_currency_symbol("x" * 40) == "x" * 16
    assert clean_currency_symbol("") == "🪙"


def test_un_emoji_supprime_du_serveur_redevient_la_piece_a_l_affichage():
    from cogs.setup_v2_core import displayable_currency_symbol

    class Bot:
        def __init__(self, connus):
            self.connus = connus

        def get_emoji(self, emoji_id):
            return object() if emoji_id in self.connus else None

    marquage = "<:piece:123456789012345678>"
    assert displayable_currency_symbol(Bot(set()), marquage) == "🪙"
    assert displayable_currency_symbol(Bot({123456789012345678}), marquage) == marquage
    assert displayable_currency_symbol(Bot(set()), "💎") == "💎"
