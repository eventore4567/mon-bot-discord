"""SentriX V60 — identités fiables dans les cartes de logs.

Cette couche corrige le dernier renderer sans ajouter de listener métier ni de commande :
- un ID de rôle n'est plus rendu comme une mention utilisateur ;
- les rôles/salons supprimés gardent leur nom connu quand le log le contient ;
- les utilisateurs hors cache sont affichés avec leur nom connu ou, au minimum, leur ID ;
- les logs sans salon pertinent affichent une portée explicite au lieu de « Non disponible » ;
- les mentions devenues invalides dans les détails sont remplacées par un libellé stable.

Le correctif est volontairement idempotent car command_no_emoji_runtime.install() est rejoué
après plusieurs extensions et certaines couches historiques peuvent remplacer le renderer.
"""
from __future__ import annotations

import re
import unicodedata

import discord
from discord.ext import commands

from . import log_fixed_height_v50 as fixed_v50
from . import log_premium_v28 as v28
from .log_rectangle_v25 import _field_value, _target_id


_GENERIC = {
    "", "non disponible", "indisponible", "inconnu", "inconnue", "unknown",
    "utilisateur inconnu", "user inconnu", "role inconnu", "rôle inconnu",
    "salon inconnu", "channel unknown",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _first_id(value: object) -> int | None:
    return v28._first_id(str(value or ""))


def _safe_name(value: object, *, prefix: str = "") -> str:
    """Extrait un nom humain sans conserver une mention Discord cassée ou un ID."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    first = raw.splitlines()[0].strip()
    first = re.sub(r"<@!?\d{15,22}>", "", first)
    first = re.sub(r"<@&\d{15,22}>", "", first)
    first = re.sub(r"<#\d{15,22}>", "", first)
    first = re.sub(r"`(?:ID\s*:?\s*)?\d{15,22}`", "", first, flags=re.IGNORECASE)
    first = re.sub(r"(?<!\d)\d{15,22}(?!\d)", "", first)
    if " — " in first:
        first = first.split(" — ", 1)[0]
    first = first.strip(" `•·-—|@#")
    if prefix and first.casefold().startswith(prefix.casefold()):
        first = first[len(prefix):].lstrip(" :：-—")
    if _norm(first) in _GENERIC:
        return ""
    first = first.replace("@", "＠").replace("`", "'")
    return discord.utils.escape_markdown(first)[:90]


def _event_family(embed: discord.Embed) -> str:
    title = _norm(embed.title)
    names = " ".join(_norm(field.name) for field in embed.fields)
    sample = f"{title} {names}"

    # Ordre important : « rôles d'un membre modifiés » concerne d'abord un membre.
    if "roles d un membre" in sample or "role attribue" in sample or "role retire" in sample:
        return "member"
    if any(token in title for token in ("message supprime", "message modifie")):
        return "message"
    if any(token in title for token in ("role cree", "role supprime", "role modifie", "creation de roles", "suppression de roles", "modification de roles")):
        return "role"
    if any(token in title for token in ("salon cree", "salon supprime", "salon modifie", "channel create", "channel delete", "channel update")):
        return "channel"
    if any(token in title for token in ("serveur modifie", "guild update")):
        return "server"
    if any(token in title for token in (
        "membre", "bannissement", "debannissement", "ban", "kick", "mute", "timeout",
        "warn", "surnom", "activite vocale", "vocal",
    )):
        return "member"
    if "ticket" in sample:
        return "ticket"
    return "other"


def _client_user(guild: discord.Guild, user_id: int):
    member = guild.get_member(user_id)
    if member is not None:
        return member, True
    try:
        client = guild._state._get_client()  # discord.py state already owns this guild.
        user = client.get_user(user_id) if client is not None else None
    except Exception:
        user = None
    return user, False


def _display_user(guild: discord.Guild, raw: object, target_id: int | None = None) -> str:
    raw_text = str(raw or "")
    user_id = _first_id(raw_text) or target_id
    if user_id:
        user, is_member = _client_user(guild, int(user_id))
        if user is not None:
            name = getattr(user, "display_name", None) or getattr(user, "name", None) or str(user)
            safe = _safe_name(name)
            if is_member:
                return f"<@{user_id}> · **{safe or 'Utilisateur'}** · `{user_id}`"
            return f"**@{safe or 'Utilisateur'}** · `{user_id}`"

    saved = _safe_name(raw_text)
    if saved and user_id:
        return f"**@{saved}** · `{user_id}`"
    if saved:
        return f"**@{saved}**"
    if user_id:
        return f"**Utilisateur** · `{user_id}`"
    return "**Utilisateur** · identité non fournie par Discord"


def _display_role(guild: discord.Guild, raw: object, target_id: int | None = None) -> str:
    raw_text = str(raw or "")
    role_id = _first_id(raw_text) or target_id
    if role_id:
        role = guild.get_role(int(role_id))
        if role is not None:
            safe = _safe_name(role.name)
            return f"{role.mention} · **{safe or 'Rôle'}** · `{role.id}`"

    saved = _safe_name(raw_text)
    if saved and role_id:
        return f"**@{saved}** · `{role_id}`"
    if saved:
        return f"**@{saved}**"
    if role_id:
        return f"**Rôle supprimé** · `{role_id}`"
    return "**Rôle** · identité non fournie par Discord"


def _display_channel(guild: discord.Guild, raw: object, target_id: int | None = None) -> str:
    raw_text = str(raw or "")
    channel_id = _first_id(raw_text) or target_id
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            safe = _safe_name(channel.name)
            return f"{channel.mention} · **#{safe or 'salon'}** · `{channel.id}`"

    saved = _safe_name(raw_text)
    if saved and channel_id:
        return f"**#{saved}** · `{channel_id}`"
    if saved:
        return f"**#{saved}**"
    if channel_id:
        return f"**Salon supprimé** · `{channel_id}`"
    return "**Salon** · identité non fournie par Discord"


def _display_server(guild: discord.Guild) -> str:
    name = discord.utils.escape_markdown(str(guild.name).replace("`", "'").replace("@", "＠"))
    return f"**{name}** · `{guild.id}`"


def _target_raw(embed: discord.Embed, family: str) -> str:
    if family == "role":
        return _field_value(embed, "role", "rôle") or str(embed.description or "")
    if family == "channel":
        return _field_value(embed, "salon", "channel") or str(embed.description or "")
    if family in {"member", "message", "ticket"}:
        return (
            _field_value(embed, "auteur", "membre", "utilisateur", "cible")
            or str(embed.description or "")
        )
    return _field_value(embed, "cible") or str(embed.description or "")


def _target_value_compat(embed: discord.Embed) -> str:
    """Fallback à un argument conservé pour les wrappers V53 historiques."""
    family = _event_family(embed)
    raw = _target_raw(embed, family)
    target_id = _target_id(embed) or _first_id(raw)
    if family == "role":
        saved = _safe_name(raw)
        if saved and target_id:
            return f"**@{saved}** · `{target_id}`"
        if saved:
            return f"**@{saved}**"
        return f"**Rôle** · `{target_id}`" if target_id else "**Rôle**"
    if family == "channel":
        saved = _safe_name(raw)
        if saved and target_id:
            return f"**#{saved}** · `{target_id}`"
        if saved:
            return f"**#{saved}**"
        return f"**Salon** · `{target_id}`" if target_id else "**Salon**"
    if family == "server":
        return f"**Serveur** · `{target_id}`" if target_id else "**Serveur**"
    saved = _safe_name(raw)
    if saved and target_id:
        return f"**@{saved}** · `{target_id}`"
    if saved:
        return f"**@{saved}**"
    return f"**Utilisateur** · `{target_id}`" if target_id else "**Événement serveur**"


def _context_block(guild: discord.Guild, embed: discord.Embed) -> str:
    family = _event_family(embed)
    target_id = _target_id(embed)
    raw = _target_raw(embed, family)
    salon_raw = _field_value(embed, "salon", "channel")

    if family == "message":
        salon = _display_channel(guild, salon_raw, _first_id(salon_raw)) if salon_raw else "**Salon du message** · non fourni"
        cible = _display_user(guild, raw, target_id if not _first_id(raw) else None)
        text = f"**Salon**  {salon}\n**Cible**  {cible}"
    elif family == "role":
        cible = _display_role(guild, raw, target_id)
        text = f"**Portée**  Serveur entier\n**Rôle**  {cible}"
    elif family == "channel":
        cible = _display_channel(guild, raw, target_id)
        text = f"**Portée**  Serveur\n**Salon cible**  {cible}"
    elif family == "server":
        text = f"**Portée**  Serveur entier\n**Serveur**  {_display_server(guild)}"
    elif family == "member":
        cible = _display_user(guild, raw, target_id)
        text = f"**Portée**  Serveur\n**Membre**  {cible}"
    elif family == "ticket":
        if salon_raw:
            text = f"**Salon**  {_display_channel(guild, salon_raw, _first_id(salon_raw))}\n**Cible**  {_display_user(guild, raw, target_id)}"
        else:
            text = f"**Portée**  Support privé\n**Cible**  {_display_user(guild, raw, target_id)}"
    else:
        if salon_raw:
            first = f"**Salon**  {_display_channel(guild, salon_raw, _first_id(salon_raw))}"
        else:
            first = "**Portée**  Serveur"
        if raw or target_id:
            second = f"**Cible**  {_display_user(guild, raw, target_id)}"
        else:
            second = f"**Serveur**  {_display_server(guild)}"
        text = first + "\n" + second

    return fixed_v50._pad_rows(text, fixed_v50.CONTEXT_ROWS)


def _replace_dead_mentions(guild: discord.Guild, value: object) -> str:
    text = str(value or "")

    def role_repl(match: re.Match[str]) -> str:
        role_id = int(match.group(1))
        role = guild.get_role(role_id)
        if role is not None:
            return role.mention
        return f"**Rôle supprimé** · `{role_id}`"

    def user_repl(match: re.Match[str]) -> str:
        user_id = int(match.group(1))
        user, is_member = _client_user(guild, user_id)
        if user is not None and is_member:
            return f"<@{user_id}>"
        if user is not None:
            name = getattr(user, "display_name", None) or getattr(user, "name", None) or "Utilisateur"
            return f"**@{_safe_name(name) or 'Utilisateur'}** · `{user_id}`"
        return f"**Utilisateur** · `{user_id}`"

    def channel_repl(match: re.Match[str]) -> str:
        channel_id = int(match.group(1))
        channel = guild.get_channel(channel_id)
        if channel is not None:
            return channel.mention
        return f"**Salon supprimé** · `{channel_id}`"

    text = re.sub(r"<@&(\d{15,22})>", role_repl, text)
    text = re.sub(r"<@!?(\d{15,22})>", user_repl, text)
    text = re.sub(r"<#(\d{15,22})>", channel_repl, text)
    return text


def _detail_candidates(guild: discord.Guild, embed: discord.Embed):
    original = getattr(_detail_candidates, "_sentrix_original", None)
    if original is None:
        return [("Information", "Aucun détail supplémentaire.")]
    rows = original(guild, embed)
    return [(label, _replace_dead_mentions(guild, value)) for label, value in rows]


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    """Réapplique le correctif si une couche historique a remplacé nos fonctions."""
    del bot, extension_name

    if not getattr(fixed_v50._target_value, "_sentrix_identity_context_v60", False):
        _target_value_compat._sentrix_identity_context_v60 = True
        fixed_v50._target_value = _target_value_compat

    if not getattr(fixed_v50._context_block, "_sentrix_identity_context_v60", False):
        _context_block._sentrix_identity_context_v60 = True
        fixed_v50._context_block = _context_block

    current_details = fixed_v50._detail_candidates
    if not getattr(current_details, "_sentrix_identity_context_v60", False):
        _detail_candidates._sentrix_original = current_details
        _detail_candidates._sentrix_identity_context_v60 = True
        fixed_v50._detail_candidates = _detail_candidates


__all__ = ["install"]
