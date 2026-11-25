"""25/11/2026 : « donne-moi une image de toi » finissait en prompt à copier.

Ni « donne-moi une image… », ni « dessine un chat », ni « image de toi »
n'étaient reconnus comme des demandes d'image, et « oui vas-y fais » après
un prompt proposé par SentriX ne générait rien.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.ai_image_intents import est_un_oui, is_image_creation_request, prompt_propose  # noqa: E402


def test_les_demandes_d_image_de_tous_les_jours_sont_reconnues():
    for phrase in ("nan donne moi une image de toi pls", "dessine un chat", "image de toi",
                   "une photo d'un chat", "envoie moi une image d'un toit"):
        assert is_image_creation_request(phrase), phrase
    for phrase in ("toit", "donne moi le rôle VIP", "envoie le message", "analyse cette image",
                   "pourquoi tu dessines mal"):
        assert not is_image_creation_request(phrase), phrase


def test_oui_apres_un_prompt_propose_retrouve_le_prompt():
    texte = ("Je peux pas générer l’image directement ici, mais utilise ce prompt : "
             "**SentriX, robot Discord futuriste noir et bleu, symbole « S » lumineux**.")
    assert prompt_propose(texte) == "SentriX, robot Discord futuriste noir et bleu, symbole « S » lumineux"
    assert prompt_propose("Le ban est fait. **Membre** : @x") is None
    assert all(est_un_oui(t) for t in ("oui vzi fait", "vas-y", "go", "ok fais le"))
    assert not any(est_un_oui(t) for t in ("non", "oui mais change complètement le style et la couleur stp"))


def test_revue_codex_pr_726():
    # Une acceptation nuancée reste une conversation (pas de génération à l'identique).
    for texte in ("oui mais en rouge", "ok ne génère rien", "oui attends avant de lancer"):
        assert not est_un_oui(texte), texte
    # « donne/envoie » ne compte que s'il porte sur l'image elle-même.
    for texte in ("donne-moi ton avis sur cette image", "donne une description de cette photo"):
        assert not is_image_creation_request(texte), texte
    assert is_image_creation_request("envoie moi une photo d'un chat")


def test_revue_codex_pr_726_suite():
    for texte in ("sais-tu dessiner ?", "je dessine un chat", "j'aime dessiner"):
        assert not is_image_creation_request(texte), texte
    for texte in ("dessine un chat", "dessine-moi un toit", "tu peux me dessiner un chien"):
        assert is_image_creation_request(texte), texte
    analyse = ("Sur cette image, **le texte est partiellement illisible**. "
               "Veux-tu que je retranscrive les passages lisibles ?")
    assert prompt_propose(analyse) is None
    offre = ("J'ai pas d'apparence officielle, mais je peux te faire une image de SentriX : "
             "**robot noir et bleu, symbole S lumineux**.")
    assert prompt_propose(offre) == "robot noir et bleu, symbole S lumineux"
