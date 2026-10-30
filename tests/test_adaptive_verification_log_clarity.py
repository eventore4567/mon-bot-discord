"""Régression du 30/10/2026 : plus de panneau AutoMod vague et sans explication."""
from __future__ import annotations

import os
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
import discord
from utils import wide_logs


def _adaptive(decision: str = "Analyse réussie — vérification web encore requise", *, failed: str = "Aucun"):
    embed = discord.Embed(
        title="SentriX • Vérification adaptative",
        description="<@123456789012345678> — **18.50/20** • seuil **16/20** • **40 signaux**",
    )
    embed.add_field(name="Décision", value=decision, inline=False)
    embed.add_field(name="Signaux non validés", value=failed, inline=False)
    embed.add_field(name="Signaux neutres / non disponibles", value="2", inline=True)
    embed.add_field(name="Moteur", value="8 familles pondérées • score normalisé sur 20", inline=True)
    return embed


def test_adaptive_result_explains_the_outcome_without_claiming_enforcement():
    embed = _adaptive()
    body = wide_logs.narrative_body(
        embed, log_type="automod", identity_name="TL", identity_id=123456789012345678,
    )
    assert "Contrôle d'entrée du compte" in body
    assert "**Résultat :** Analyse réussie" in body
    assert "**Score de confiance :** 18.50/20" in body
    assert "**Seuil requis :** 16/20" in body
    assert "terminer le portail web et le CAPTCHA" in body
    assert "aucune sanction automatique" in body
    assert "Une protection SentriX s'est déclenchée" not in body
    assert "Moteur" not in body


def test_review_log_explains_failed_signals_and_staff_action():
    embed = _adaptive(
        "Reste Non vérifié — revue staff possible",
        failed="• Compte trop récent\n• Invitation suspecte",
    )
    embed.add_field(name="Blocage fort", value="Compte potentiellement automatisé", inline=False)
    body = wide_logs.narrative_body(embed, log_type="automod")
    assert "Compte trop récent" in body
    assert "Invitation suspecte" in body
    assert "Compte potentiellement automatisé" in body
    assert "revue staff" in body
    assert "aucune sanction automatique" in body
    assert body.count("Compte trop récent") == 1


def test_adaptive_fields_do_not_repeat_under_log():
    embed = _adaptive(failed="• Ancienneté du compte insuffisante")
    compact = wide_logs.compact_fields(embed)
    for word in ("Décision", "Signaux non validés", "Moteur"):
        assert word not in compact


def test_automod_subject_is_member_with_clickable_profile():
    ident = 123456789012345678
    assert wide_logs._trace_identity_label("automod") == "Membre"
    assert wide_logs._trace_identity_ref("automod", ident) == f"<@{ident}>"
    assert wide_logs.NO_PINGS.users is False
    assert wide_logs.NO_PINGS.roles is False


def test_other_automod_incident_logs_keep_existing_renderer():
    embed = discord.Embed(title="Protection SentriX")
    embed.add_field(name="Statut", value="Détection seule — aucun message retiré", inline=False)
    embed.add_field(name="Protection", value="Anti-liens", inline=False)
    embed.add_field(name="Règle", value="Invitation non autorisée", inline=False)
    embed.add_field(name="Action", value="Aucune action", inline=False)
    body = wide_logs.narrative_body(embed, log_type="automod")
    assert "Incident" in body
    assert "Anti-liens" in body
    assert "Contrôle d'entrée du compte" not in body
