"""Utiliser le système natif de Discord EN ENTIER, pas à moitié.

Discord expose cinq déclencheurs d'AutoMod. SentriX en utilisait trois
(`keyword`, `keyword_preset`, `mention_spam`) et laissait les deux autres de
côté :

- `spam` tourne chez Discord AVANT que le message n'arrive au bot. Il attrape
  des rafales que SentriX ne voit qu'après coup, et il tient même si le bot est
  saturé ou déconnecté ;
- `member_profile` filtre le PSEUDO à l'arrivée. Un compte de raid nommé pour
  insulter ou usurper est arrêté avant d'avoir écrit une seule ligne — ce
  qu'aucune règle sur les messages ne peut faire.
"""
import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import automod as mod  # noqa: E402


class _Guild:
    id = 7


def _cog(conf, mots=("insulte", "arnaque")):
    cog = mod.AutoMod.__new__(mod.AutoMod)
    appels = []

    class _Db:
        async def get_automod(self, _gid):
            return conf

    cog.bot = type("Bot", (), {"db": _Db()})()

    async def _upsert(_guild, **kwargs):
        appels.append(kwargs)
        return True

    async def _mots(_gid):
        return list(mots)

    cog._upsert_native_rule = _upsert
    cog.get_blacklist_words_cached = _mots
    return cog, appels


def test_le_spam_natif_de_discord_est_utilise():
    cog, appels = _cog({"antispam": 1})
    assert asyncio.run(cog._sync_native_spam_rule(_Guild())) is True
    (appel,) = appels
    assert appel["enabled"] is True
    assert appel["trigger"].type is discord.AutoModRuleTriggerType.spam
    assert appel["policy_filter"] == "antispam"


def test_le_spam_natif_suit_le_reglage_du_serveur():
    cog, appels = _cog({"antispam": 0})
    asyncio.run(cog._sync_native_spam_rule(_Guild()))
    assert appels[0]["enabled"] is False


def test_les_pseudos_interdits_sont_filtres_a_l_arrivee():
    cog, appels = _cog({"antiscam": 1})
    assert asyncio.run(cog._sync_native_profile_rule(_Guild())) is True
    (appel,) = appels
    assert appel["enabled"] is True
    assert appel["trigger"].type is discord.AutoModRuleTriggerType.member_profile
    assert "insulte" in appel["trigger"].keyword_filter


def test_aucun_mot_interdit_laisse_la_regle_eteinte():
    # Une règle de filtrage sans mot à filtrer encombrerait les réglages du
    # serveur sans rien faire.
    cog, appels = _cog({"antiscam": 1}, mots=())
    asyncio.run(cog._sync_native_profile_rule(_Guild()))
    assert appels[0]["enabled"] is False


def test_la_regle_de_pseudo_ne_passe_pas_de_message_personnalise():
    # Discord refuse `custom_message` sur un déclencheur de profil et rejette
    # alors la règle ENTIÈRE.
    cog, appels = _cog({"antiscam": 1})
    asyncio.run(cog._sync_native_profile_rule(_Guild()))
    assert "custom_message" not in appels[0]


def test_les_mots_respectent_les_limites_de_discord():
    cog, appels = _cog({"antiscam": 1}, mots=["m" * 200] + [f"mot{i}" for i in range(1200)])
    asyncio.run(cog._sync_native_profile_rule(_Guild()))
    mots = appels[0]["trigger"].keyword_filter
    assert len(mots) <= 1000
    assert all(len(m) <= 60 for m in mots)


def test_les_deux_regles_sont_retirees_avec_les_autres():
    # Sans ça, elles survivraient à une désinstallation et resteraient dans les
    # réglages du serveur sans personne pour les gérer.
    source = __import__("inspect").getsource(mod.AutoMod._sync_native_suite)
    assert "NATIVE_SPAM_RULE_NAME" in source
    assert "NATIVE_PROFILE_RULE_NAME" in source


def test_les_cinq_declencheurs_de_discord_sont_desormais_couverts():
    source = __import__("inspect").getsource(mod)
    for declencheur in ("keyword_filter", "presets", "mention_limit", "spam", "member_profile"):
        assert declencheur in source, f"{declencheur} non utilisé"
