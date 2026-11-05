"""Retours du 05/11/2026 au soir (captures) : logs de salon, alerte admin, /setup."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils import wide_logs  # noqa: E402


def test_le_log_salon_cree_donne_le_nom_du_salon():
    # « Le salon Un salon a été créé » : le nom du salon est maintenant dans le champ.
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "logs.py").read_text(encoding="utf-8")
    assert 'fields = [(nom, f"`{channel.name}`", True), ("Type", str(channel.type), True)]' in source
    embed = discord.Embed(title="Salon créé")
    embed.add_field(name="Salon", value="`général`")
    nom, ident, _icone = wide_logs.derive_identity(embed, log_type="channel_create")
    corps = wide_logs.narrative_body(embed, log_type="channel_create", identity_name=nom, identity_id=ident)
    assert corps == "Le salon **général** a été créé."


def test_l_alerte_admin_est_un_panneau_sentrix_jaune():
    from cogs import automod

    guild = SimpleNamespace(name="Mon serveur")
    admin = SimpleNamespace(id=57, mention="<@57>")
    vue = automod.carte_alerte_admin(guild, admin)
    assert vue.kind == "warning"
    assert "Sanctionner aussi les admins" in str([s.texte for s in vue.sections_source])
    assert "<@57>" in vue.sections_source[0].texte


def test_le_refus_slash_est_une_carte_et_plus_du_texte(monkeypatch):
    from cogs import final_interaction_policy as fip
    from utils import sentrix_panels as panels

    envois = []

    async def envoyer(destination, panneau, **kwargs):
        envois.append((panneau, kwargs))

    monkeypatch.setattr(panels, "envoyer", envoyer)
    decision = SimpleNamespace(message="Vous n'avez pas accès à cette commande.\n\n**Permission Discord requise :** Gérer le serveur.")
    asyncio.run(fip._permission_denial(SimpleNamespace(), decision))
    panneau, kwargs = envois[0]
    assert panneau.titre == "🔒 Accès refusé" and kwargs.get("ephemere") is True


def test_setup_s_ouvre_pour_tous_dans_les_deux_matrices_de_production():
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1] / "cogs"
    for fichier in ("permission_setup_hardening_v65.py", "setup_simple_v68.py"):
        assert 'policy="setup:lecture-seule"' in (racine / fichier).read_text(encoding="utf-8")
    # _can_setup reste « peut modifier » : la lecture seule n'y donne pas accès.
    assert '== "setup:lecture-seule":\n            return False' in (racine / "setup_v2_ui.py").read_text(encoding="utf-8")
