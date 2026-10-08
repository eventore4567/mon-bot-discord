"""Présentation encadrée du journal de +clear et /clear."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.moderation import Moderation


def _message(author: str, content: str):
    return SimpleNamespace(
        author=SimpleNamespace(display_name=author),
        content=content,
    )


def test_clear_preview_est_un_bloc_encadre_et_numerote():
    logs = [
        _message("Tomioka", "$clear 100"),
        _message("Tomioka", "wtf"),
        _message("Natix bot", "Erreur de conversion d'argument"),
    ]
    result = Moderation._clear_preview(logs)
    assert result.startswith("```text\n")
    assert result.endswith("\n```")
    assert "01 │ Tomioka\n   └ $clear 100" in result
    assert "02 │ Tomioka\n   └ wtf" in result
    assert "03 │ Natix bot" in result
    assert len(result) <= 1024


def test_clear_preview_ne_peut_pas_etre_brise_par_markdown_ou_backticks():
    logs = [_message("```**admin**", "```\n@everyone\n@here\\ttexte")]
    result = Moderation._clear_preview(logs)
    assert result.count("```") == 2
    assert "**admin**" in result  # affiché en texte brut, pas du Markdown
    assert "@\u200beveryone" in result
    assert "@\u200bhere" in result


def test_clear_preview_limite_le_nombre_et_signale_le_reste():
    logs = [_message("Membre", f"Message {i}") for i in range(23)]
    result = Moderation._clear_preview(logs)
    assert "01 │" in result
    assert "10 │" in result
    assert "11 │" not in result
    assert "13 autre(s) message(s)" in result
    assert len(result) <= 1024


def test_clear_preview_avec_contenu_tres_long_garde_un_champ_discord_valide():
    logs = [_message("X" * 80, "Texte " * 250) for _ in range(100)]
    result = Moderation._clear_preview(logs)
    assert len(result) <= 1000
    assert result.count("```") == 2
    assert "…" in result


def test_clear_preview_vide_et_emoji_anime_complet():
    assert "Aucun message à prévisualiser." in Moderation._clear_preview([])
    animated = "<a:sentrix_loading:410000000000000004>"
    logs = [_message("Auteur", "A" * 135 + animated)]
    result = Moderation._clear_preview(logs)
    assert "<a:sentrix_loading:" not in result  # pas de marqueur incomplet
    assert len(result) <= 1024
