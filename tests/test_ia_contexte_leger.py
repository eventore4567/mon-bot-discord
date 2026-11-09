"""10/11/2026 : la fiche du serveur ne part que si la question concerne le serveur."""
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import ai_context_v9 as ctx  # noqa: E402


def test_simple_discussion_sans_fiche_du_serveur():
    for question in ("salut ça va", "raconte moi une blague", "tu préfères les chats ou les chiens ?", "mdr"):
        assert not ctx.besoin_contexte_serveur(question), question


def test_question_sur_le_serveur_avec_fiche():
    for question in ("c'est quoi tes permissions", "combien de membres", "ban @toto", "crée un salon annonces",
                     "c'est quoi les règles", "quel est mon rôle", "comment configurer les tickets"):
        assert ctx.besoin_contexte_serveur(question), question
    assert ctx.besoin_contexte_serveur("x" * 300)  # longue question : contexte complet


def test_contexte_court_dit_qui_parle_a_qui():
    membre = SimpleNamespace(display_name="Jayden")
    guild = SimpleNamespace(name="Mon serveur", get_member=lambda uid: membre)
    bot = SimpleNamespace(get_guild=lambda gid: guild)
    texte = ctx.contexte_court(bot, 1, 2)
    assert "SentriX" in texte and "Mon serveur" in texte and "Jayden" in texte
    assert len(texte) < 200
