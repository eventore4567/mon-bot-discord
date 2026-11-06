"""07/11/2026 : mots-clés bloqués avant l'envoi, configurés dans /setup → Sécurité."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import mots_bloques as mb  # noqa: E402


def test_les_mots_sont_lus_proprement():
    assert mb.lire_mots("SAB, trade ; vente de compte\nsab") == ["sab", "trade", "vente de compte"]
    assert mb.lire_mots(" , ; ") == []
    assert len(mb.lire_mots("x" * 200)[0]) == 60


def _regle(numero, mots, message="", salons=(), createur=9):
    return SimpleNamespace(
        id=1000 + numero, name=f"{mb.PREFIXE} {numero}", creator_id=createur,
        trigger=SimpleNamespace(keyword_filter=list(mots)),
        actions=[SimpleNamespace(custom_message=message)], exempt_channel_ids=list(salons),
    )


def _guild(regles):
    return SimpleNamespace(
        id=1, me=SimpleNamespace(id=9),
        fetch_automod_rules=AsyncMock(return_value=regles),
        create_automod_rule=AsyncMock(side_effect=lambda **kw: SimpleNamespace(**kw)),
    )


def test_seules_les_regles_de_sentrix_sont_listees_dans_l_ordre():
    autre = SimpleNamespace(name="Règle d'un autre bot", creator_id=4)
    guild = _guild([_regle(2, ["b"]), autre, _regle(1, ["a"]), _regle(3, ["c"], createur=4)])
    noms = [r.name for r in asyncio.run(mb.lister(guild))]
    assert noms == [f"{mb.PREFIXE} 1", f"{mb.PREFIXE} 2"]


def test_creer_une_regle_qui_bloque_avant_l_envoi_avec_le_message():
    guild = _guild([_regle(1, ["a"])])
    asyncio.run(mb.creer(guild, ["sab", "trade"], "Pour parler de SAB, utilisez #sab."))
    kwargs = guild.create_automod_rule.await_args.kwargs
    assert kwargs["name"] == f"{mb.PREFIXE} 2"            # premier numéro libre
    assert kwargs["trigger"].keyword_filter == ["sab", "trade"]
    assert kwargs["actions"][0].custom_message == "Pour parler de SAB, utilisez #sab."
    assert kwargs["event_type"] == discord.AutoModRuleEventType.message_send


def test_la_limite_de_discord_est_expliquee():
    guild = _guild([_regle(n, ["x"]) for n in range(1, 7)])
    with pytest.raises(ValueError, match="6 règles"):
        asyncio.run(mb.creer(guild, ["y"], ""))


def test_le_panneau_resume_les_regles():
    vue = mb.MotsBloquesView(SimpleNamespace(id=1), 5, [_regle(1, ["sab"], "Salon #sab", salons=[42])])
    texte = str(vue.embed().to_dict())
    assert "sab" in texte and "Salon #sab" in texte and "<#42>" in texte


def test_le_bouton_est_dans_setup_securite():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "setup_security_choice_v75.py").read_text(encoding="utf-8")
    assert "mots_bloques.ouvrir(interaction, self.guild)" in source
    assert "discord.ui.ActionRow(exceptions, mots_bloques_bouton, admins_bouton)" in source


# --- 07/11/2026 : modifier / retirer des mots, bloquer les liens ---------------------

def test_modifier_remplace_les_mots_et_le_message():
    regle = _regle(1, ["sab", "trade"], "ancien")
    regle.edit = AsyncMock()
    asyncio.run(mb.modifier(regle, mots=["sab"], message="nouveau"))   # « trade » retiré
    kwargs = regle.edit.await_args.kwargs
    assert kwargs["trigger"].keyword_filter == ["sab"]
    assert kwargs["actions"][0].custom_message == "nouveau"


def test_regle_de_liens_bloque_les_adresses_sauf_les_sites_autorises():
    import re

    guild = _guild([])
    sites = mb.lire_sites("https://youtube.com/, tenor.com, tenor.com")
    assert sites == ["*youtube.com*", "*tenor.com*"]
    asyncio.run(mb.creer(guild, [], "Pas de liens ici.", liens=True, sites=sites))
    trigger = guild.create_automod_rule.await_args.kwargs["trigger"]
    assert trigger.allow_list == sites and not trigger.keyword_filter
    for texte in ("va sur https://exemple.com", "rejoins discord.gg/abc", "www.site.fr"):
        assert any(re.search(m, texte) for m in trigger.regex_patterns), texte
    assert not any(re.search(m, "salut ça va") for m in trigger.regex_patterns)
    regle = SimpleNamespace(trigger=trigger)
    assert mb.est_regle_liens(regle) and "youtube.com" in mb.resume(regle)


def test_le_panneau_propose_liens_et_modification():
    guild = SimpleNamespace(id=1)
    vue = mb.MotsBloquesView(guild, 5, [_regle(1, ["sab"])])
    libelles = [getattr(i, "label", None) for i in vue.children]
    assert "Bloquer les liens" in libelles
    vue.choisie = 1001
    vue._construire()
    assert "Modifier les mots" in [getattr(i, "label", None) for i in vue.children]
    modal = mb.ModifierModal(vue, vue._regle())
    assert modal.mots.default == "sab"
