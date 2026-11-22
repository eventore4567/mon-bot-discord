"""L'IA crée les rôles, catégories et salons qu'on lui demande.

22/11/2026, capture d'un serveur : « non je veux que tu crées le rôle Ping
live, pas le give » → SentriX : « Je ne peux pas créer le rôle directement,
utilise +setup ». L'action role.create existait pourtant. Les motifs de
reconnaissance exigeaient la phrase exacte « crée un rôle X » : « crée LE
rôle », « crée LA catégorie », « crée-MOI un salon », « ajoute un salon » ou une
phrase qui ne commence pas par le verbe tombaient dans la conversation. Et le
nom était lu dans le texte normalisé : « Ping live » devenait « ping live ».
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import ai_actions  # noqa: E402


@pytest.mark.parametrize(("phrase", "intention", "slots"), [
    ("non je veux tu crée le role Ping live pas give", "role.create", {"name": "Ping live"}),
    ("crée le rôle Ping live", "role.create", {"name": "Ping live"}),
    ("cree un role Ping live", "role.create", {"name": "Ping live"}),
    ("fais un rôle VIP rouge", "role.create", {"name": "VIP", "color": "rouge"}),
    ("crée un rôle Modo #ff0000", "role.create", {"name": "Modo", "color": "#ff0000"}),
    ("stp fais un rôle VIP", "role.create", {"name": "VIP"}),
    ("crée la catégorie Events", "category.create", {"name": "Events"}),
    ("tu peux créer une catégorie Events", "category.create", {"name": "Events"}),
    ("crée moi un salon annonces", "channel.create_text", {"name": "annonces"}),
    ("ajoute un salon general", "channel.create_text", {"name": "general"}),
    ("crée-moi un salon textuel « Règles » stp", "channel.create_text", {"name": "Règles"}),
    ("crée un salon vocal Gaming dans la catégorie Events", "channel.create_voice",
     {"name": "Gaming", "category": "Events"}),
    ("crée une voc", "channel.create_voice", {}),
])
def test_une_demande_de_creation_est_comprise(phrase, intention, slots):
    action = ai_actions.local_parse(phrase)
    assert action is not None, phrase
    assert (action.intent, action.slots) == (intention, slots)


@pytest.mark.parametrize("phrase", [
    "tu as créé le rôle Ping live ?",       # une question sur le passé
    "on fait un salon pour quoi ?",         # « fait » dans une phrase courante
    "ca fait un salon de trop",
    "il fait un role play",
    "ajoute le rôle VIP à @bob",            # donner un rôle, pas le créer
])
def test_pas_de_creation_par_erreur(phrase):
    action = ai_actions.local_parse(phrase)
    assert action is None or action.intent not in {
        "role.create", "category.create", "channel.create_text", "channel.create_voice",
    }, (phrase, action)


def test_donner_un_role_a_tout_le_monde_n_est_pas_une_creation():
    action = ai_actions.local_parse("ajoute le role Membre à tout le monde")
    assert action is not None and action.intent != "role.create"


def _creer_role(slots, *, roles=(), actor_perms=True):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import discord

    from cogs.ai import Ai

    reponses = []
    cree = SimpleNamespace(name=slots.get("name"), mention="<@&1>")
    guild = SimpleNamespace(
        owner_id=7, roles=list(roles), create_role=AsyncMock(return_value=cree),
        me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True)),
    )
    message = SimpleNamespace(
        guild=guild,
        author=SimpleNamespace(id=5, guild_permissions=SimpleNamespace(manage_roles=actor_perms)),
        reply=AsyncMock(side_effect=lambda texte, **_: reponses.append(texte)),
    )
    cog = Ai.__new__(Ai)
    action = ai_actions.ParsedAction("role.create", dict(slots), 99, "local")
    asyncio.run(cog._execute_native_action(message, action))
    return guild, reponses, discord


def test_le_role_est_cree_avec_son_nom_exact_et_sa_couleur():
    guild, reponses, discord = _creer_role({"name": "Ping live", "color": "rouge"})
    kwargs = guild.create_role.await_args.kwargs
    assert kwargs["name"] == "Ping live"
    assert kwargs["colour"] != discord.Colour.default()
    assert "Rôle créé" in reponses[0]


def test_un_role_qui_existe_deja_n_est_pas_cree_en_double():
    from types import SimpleNamespace

    existant = SimpleNamespace(name="Ping Live", mention="<@&9>")
    guild, reponses, _ = _creer_role({"name": "ping live"}, roles=[existant])
    guild.create_role.assert_not_awaited()
    assert "existe déjà" in reponses[0]


def test_sans_gerer_les_roles_l_ia_refuse():
    guild, reponses, _ = _creer_role({"name": "VIP"}, actor_perms=False)
    guild.create_role.assert_not_awaited()
    assert "Gérer les rôles" in reponses[0]
