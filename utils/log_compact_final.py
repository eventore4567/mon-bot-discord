"""Rendu final compact des logs SentriX.

Cette couche ne touche qu'aux journaux :
- une seule grande ligne sous le titre ;
- aucune ligne qui déborde ou se répète ;
- métadonnées compactes, une information par ligne ;
- champs longs (Avant / Après / Raison / Contenu) conservés tels quels.
"""
from __future__ import annotations

import re
from datetime import datetime

import discord

from . import embeds as sx
from . import sentrix_runtime as runtime
from . import sentrix_visual_cleanup as visual

_INSTALLED = False
PANEL_BAR = visual.PANEL_BAR
_SEPARATOR_LINE = re.compile(r"^[\s━─═—–_\-•·┄┈┉┅┇]+$")

_ORIGINAL_LOG_EMBED = sx.log_embed
_ORIGINAL_NORMALIZE_LOG = sx.normalize_log


def _clean_description(value: object) -> str:
    """Garde le contenu mais retire les anciens séparateurs et les grands espaces."""
    lines: list[str] = []
    for raw_line in str(value or "").replace("\r", "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped and len(stripped) >= 3 and _SEPARATOR_LINE.fullmatch(stripped):
            continue
        lines.append(line)

    # Dans les logs, une ligne par information suffit : pas de double saut entre
    # Membre / Rôle / Modérateur / Salon. Les champs Discord Avant/Après restent séparés.
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        if not line.strip():
            if compact and not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False

    while compact and not compact[-1].strip():
        compact.pop()

    body = "\n".join(compact).strip()
    # Les métadonnées stylées **Nom :** sont regroupées sans ligne vide entre elles.
    body = re.sub(r"(?m)(\*\*[^\n:]{1,60}\s*:\*\*[^\n]*)\n\n(?=\*\*[^\n:]{1,60}\s*:\*\*)", r"\1\n", body)
    return body


def _finalize_log(embed: discord.Embed | None) -> discord.Embed | None:
    if not isinstance(embed, discord.Embed):
        return embed
    body = _clean_description(embed.description)
    embed.description = f"{PANEL_BAR}\n{body}" if body else PANEL_BAR
    return embed


def log_embed(
    title: str,
    *,
    fields=(),
    description: str = "",
    event_time: datetime | None = None,
    banner: bool = True,
) -> discord.Embed:
    panel = _ORIGINAL_LOG_EMBED(
        title,
        fields=fields,
        description=description,
        event_time=event_time,
        banner=banner,
    )
    return _finalize_log(panel)


def normalize_log(
    source: discord.Embed,
    *,
    event_time: datetime | None = None,
) -> discord.Embed:
    panel = _ORIGINAL_NORMALIZE_LOG(source, event_time=event_time)
    return _finalize_log(panel)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    sx.log_embed = log_embed
    sx.normalize_log = normalize_log
    runtime._log_embed = log_embed
    runtime._normalize_log = normalize_log
    _INSTALLED = True


install()
