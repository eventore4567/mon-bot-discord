from __future__ import annotations

import inspect

from cogs import guild_arrival


EXPECTED_HOME = "https://sentrix-standby-production.up.railway.app/home"


def test_owner_onboarding_uses_exact_public_home_url():
    assert guild_arrival.PUBLIC_HOME_URL == EXPECTED_HOME


def test_owner_onboarding_has_professional_sentrix_intro_and_home_button():
    source = inspect.getsource(guild_arrival.GuildArrival.on_guild_join)
    assert 'title="Bienvenue sur SentriX"' in source
    assert "Votre centre de contrôle Discord" in source
    assert "modération, la sécurité" in source
    assert "l'AutoMod, les tickets, les logs" in source
    assert 'label="Découvrir SentriX"' in source
    assert "PUBLIC_HOME_URL" in source
    assert "`+setup`" in source
    assert "`+help`" in source


def test_owner_onboarding_keeps_dashboard_and_support_buttons():
    source = inspect.getsource(guild_arrival.GuildArrival.on_guild_join)
    assert 'label="Ouvrir le Dashboard"' in source
    assert 'label="Serveur officiel"' in source
