"""Une erreur en texte brut ne notifie personne, même quand elle recopie la saisie.

Trouvé par tools/mention_injection_sweep.py le 08/10/2026 : « Un modèle nommé
« <@&rôle> » existe déjà » partait sans allowed_mentions, donc avec le défaut
du bot, et faisait sonner un rôle non mentionnable.
"""
from __future__ import annotations

import asyncio

from utils import embeds
from utils import sentrix_panels as panels


class Salon:
    def __init__(self) -> None:
        self.envois: list[dict] = []

    async def send(self, **kwargs):
        self.envois.append(kwargs)
        return None


def test_une_erreur_en_texte_brut_ne_notifie_personne():
    salon = Salon()
    asyncio.run(panels._envoyer_texte_brut_depuis_panneau(
        salon, "Un modèle nommé « @everyone <@&42> <@7> » existe déjà.", ephemere=False, extra={},
    ))
    assert salon.envois[0]["allowed_mentions"].to_dict() == {"parse": []}


def test_la_carte_ferme_aussi_everyone_et_les_roles():
    salon = Salon()
    asyncio.run(panels.envoyer(salon, panels.depuis_embed(embeds.error("« @everyone <@&42> » existe déjà."))))
    mentions = salon.envois[0]["allowed_mentions"].to_dict()
    assert "everyone" not in mentions.get("parse", []) and "roles" not in mentions.get("parse", [])


def test_un_appelant_peut_toujours_choisir_ses_mentions():
    salon = Salon()
    choisi = panels.discord.AllowedMentions(users=True)
    asyncio.run(panels._envoyer_texte_brut_depuis_panneau(
        salon, "texte", ephemere=False, extra={"allowed_mentions": choisi},
    ))
    assert salon.envois[0]["allowed_mentions"] is choisi
