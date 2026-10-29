"""
Cog SÉCURITÉ ET AUTOMOD.
/blacklist-add /blacklist-remove /blacklist-list /blacklist-user /unblacklist-user
/blacklist-users /antispam /antilink /antiinvite /antimention /anticaps /antiemoji
/antiraid /antibot /antiaccount /antiscam /antinuke /automod-status /whitelist-domain
/unwhitelist-domain /security-level /antinuke-whitelist-add /antinuke-whitelist-remove
/antinuke-whitelist-list /lockdown-server /unlock-server /automod-escalation
/automod-exempt-role-add /automod-exempt-role-remove /automod-history

Un seul écouteur on_message applique tous les filtres actifs. Un salon ignoré via
/ignorechannel est désormais bien respecté par AutoMod (avant, ce n'était pas le cas).
Aucune adresse IP n'est collectée : seuls les identifiants Discord sont utilisés.

Escalade automatique des sanctions : chaque infraction (suppression de message par un
filtre) est comptabilisée sur une fenêtre glissante d'1h. Au-delà de certains seuils,
le membre est automatiquement mute (3), expulsé (5) puis banni (7) — sans intervention
manuelle. Désactivable via /automod-escalation. Historique consultable via /automod-history
et /automod-status (statistiques des dernières 24h par filtre).

Exemptions : propriétaire du serveur, propriétaire(s) du bot et tout rôle ajouté via
/automod-exempt-role-add ne sont jamais filtrés par AutoMod. La permission
« Administrateur » n'exempte de rien : Discord exempte toujours les administrateurs de
ses règles AutoMod natives, et le filtre Python de ce module est précisément le filet
qui les rattrape. Un membre dont le rôle dépasse celui de SentriX échappe en revanche
aux sanctions Discord — voir _repondre_abus_privilegie pour ce qui est fait alors.

Le filtre multilingue intégré analyse 2 663 termes, 1 200 phrases et 120 groupes de
mots dans 28 langues. Une détection supprime le message et applique immédiatement une
exclusion temporaire de 10 minutes, sans attendre l'escalade des autres filtres.

L'anti-nuke (/antinuke) protège contre un compte compromis (staff ou même le bot)
qui tenterait de détruire le serveur : suppression massive de salons/rôles ou
bannissements en rafale. Si le seuil est dépassé, le responsable est immédiatement
privé de ses rôles dangereux et expulsé, et le propriétaire du serveur est alerté.
"""

import asyncio
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field as _champ
from datetime import timedelta
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import audit_entries
from utils import embeds, checks, helpers, log_service, text_normalization, ai_service
from utils import lookalike_domains
from utils.sliding_window import FenetreGlissante
from utils.purge_queue import SuppressionsGroupees
from utils import spam_sensitivity
from utils.raid_join_deduplicator import RaidJoinDeduplicator
from utils.automod_message_claims import AutomodMessageClaims
from utils.raid_verification_recovery import RaidVerificationRecovery
from utils.security_member_bypass import can_bypass_message_filters
from utils import sentrix_panels as panels
from utils.moderation_dataset import MultilingualModerationDataset
from services import moderation as moderation_service

logger = logging.getLogger("bot")


def _as_member(user: discord.abc.User, guild: discord.Guild | None) -> discord.abc.User:
    """Le Member derrière un auteur. Discord transmet parfois un simple User
    (membre absent du cache) : sans ses permissions, un administrateur était
    traité comme un membre ordinaire et sanctionné."""
    if isinstance(user, discord.Member) or guild is None:
        return user
    return guild.get_member(getattr(user, "id", 0)) or user


def _is_discord_administrator(member: discord.abc.User) -> bool:
    """Compatibilité historique : admin Discord OU rôle de direction « all perms ».

    Un modérateur avec une seule permission de gestion n'est pas exempté.
    Ce garde vaut pour la modération des messages ; l'anti-nuke a sa propre
    règle (is_antinuke_exempt), réservée à la permission Administrateur.
    """
    member = _as_member(member, getattr(member, "guild", None))
    return isinstance(member, discord.Member) and can_bypass_message_filters(member)


# Redirecteurs d'invitation aussi courants que discord.gg lui-même : les
# ignorer laissait passer un lien d'invitation sur quatre.
# « discord . gg/abc » : un espace de part et d'autre du point suffisait à passer.
# On recolle UNIQUEMENT les couples hôte/TLD d'invitation connus — recoller tous
# les points transformerait « salut . com » en lien et ferait sanctionner une
# phrase banale.
_INVITE_ESPACEE = re.compile(
    r"\b(disc[o0]rd|disc[o0]rdapp|dsc|invite|disboard)\s*\.\s*(gg|me|io|com|org|net|link)\b",
    re.IGNORECASE,
)


def _recoller_hotes_invitation(contenu: str) -> str:
    return _INVITE_ESPACEE.sub(lambda m: f"{m.group(1)}.{m.group(2)}", str(contenu or ""))


INVITE_RE = re.compile(
    # « disc0rd.gg » passait : le zéro pour la lettre o est la substitution la
    # plus courante sur un nom d'hôte, et elle ne crée aucune ambiguïté ici.
    r"(?:disc[o0]rd\.gg|disc[o0]rd(?:app)?\.com/invite|dsc\.gg|invite\.gg|disc[o0]rd\.me"
    r"|disboard\.org/server/join|disc[o0]rd\.io|disc[o0]rdapp\.net/invite|disc[o0]rd\.link)"
    r"/\S+",
    re.IGNORECASE,
)
def _invitation_apres_recollage_total(contenu: str) -> bool:
    """« d i s c o r d . g g / abcd » : on recolle tout et on reteste.

    Supprimer tous les espaces est trop brutal pour servir de normalisation
    générale — mais comme simple TEST supplémentaire, c'est sûr : il faut déjà
    que le résultat ressemble à une invitation Discord complète, ce qu'aucune
    phrase ordinaire ne produit par accident.
    """
    compact = re.sub(r"\s+", "", str(contenu or ""))
    return bool(INVITE_RE.search(compact))


_COMMON_TLDS = (
    "com|net|org|gg|io|co|fr|ma|me|tv|ly|be|dev|app|ai|xyz|info|biz|online|"
    "site|shop|store|tech|pro|cc|ru|de|uk|us|ca|eu|ch|it|es|pt|nl|se|no|fi|"
    "pl|tr|in|jp|cn|kr|au|nz|br|mx|ar|za|tk|to|link|club|live|news|cloud|"
    "digital|world|vip|fun|games|social|xn--[a-z0-9]{2,}"
)
_VIRGULE_AVANT_TLD_RE = re.compile(rf"\s*,\s*({_COMMON_TLDS})\b", re.IGNORECASE)
_ESPACE_AVANT_TLD_RE = re.compile(rf"(?<=[a-z0-9])\s+\.\s*({_COMMON_TLDS})\b", re.IGNORECASE)
# « discord.gg /abcd » : l'espace avant le chemin casse INVITE_RE, qui exige
# « /quelquechose » collé à l'hôte.
_ESPACE_AVANT_CHEMIN_RE = re.compile(
    r"\b((?:discord|discordapp|dsc|invite|disboard)\.(?:gg|me|io|com|org|net|link))\s+/",
    re.IGNORECASE,
)

LINK_RE = re.compile(
    rf"""
    (?:
        \b(?:https?|hxxps?)://[^\s<]+
        | \bwww\.[^\s<]+
        | (?<![\w@])
          (?:[a-z0-9](?:[a-z0-9-]{{0,62}}[a-z0-9])?\.)+
          (?:{_COMMON_TLDS})\b
          (?::\d{{2,5}})?
          (?:/[^\s<]*)?
        | \b(?:\d{{1,3}}\.){{3}}\d{{1,3}}(?::\d{{2,5}})?(?:/[^\s<]*)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Séparateurs employés à la place du point dans une adresse. Mesuré le
# 2026-10-14 : « exemple[dot]com », « exemple{.}com » et « exemple·com »
# passaient tous les trois. La virgule n'est PAS dans la liste — « j'ai 3,5 de
# moyenne » deviendrait un lien, et un faux positif fait couper la protection.
_FAUX_POINTS_RE = re.compile(
    r"\s*(?:\[\s*(?:\.|dot|point)\s*\]|\(\s*(?:\.|dot|point)\s*\)"
    r"|\{\s*(?:\.|dot|point)\s*\}|<\s*(?:\.|dot|point)\s*>"
    r"|\bdot\b|[\u00b7\u2022\u2219\u30fb])\s*",
    re.IGNORECASE,
)
_MARQUEURS_DISCORD_RE = re.compile(r"\|\||\*\*|__|~~|`")


def _recoller_points_avant_tld(valeur: str) -> str:
    """« exemple ,com », « exemple . com », « discord.gg /abcd ».

    La virgule et l'espace ne sont PAS des faux points en général : « 3,5 » et
    « 14.30 » doivent rester des nombres. Ils ne le deviennent que juste avant
    un TLD connu, ce qu'aucune de ces phrases ne contient. Mesuré avant/après
    sur un corpus banal riche en nombres : zéro faux positif.
    """
    valeur = _VIRGULE_AVANT_TLD_RE.sub(r".\1", valeur)
    valeur = _ESPACE_AVANT_TLD_RE.sub(r".\1", valeur)
    return _ESPACE_AVANT_CHEMIN_RE.sub(r"\1/", valeur)


def _normaliser_confusables(valeur: str) -> str:
    """Pleine chasse, cyrillique et petites capitales ramenés en ASCII."""
    try:
        from utils.text_normalization import normaliser
    except Exception:  # pragma: no cover - la normalisation ne doit jamais casser le filtre
        return valeur
    try:
        return normaliser(valeur)
    except Exception:  # pragma: no cover
        logger.warning("Normalisation des confusables impossible.", exc_info=True)
        return valeur


def _normalize_link_text(content: str) -> str:
    """Normalise les séparateurs/obfuscations utilisés pour contourner l'anti-lien.

    Couvre notamment les schémas cassés ("https:/ /site"), les caractères zéro-largeur
    et plusieurs URLs collées sans espace.
    """
    value = str(content or "").casefold()
    value = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", value)
    # Pleine chasse et confusables : « ｅｘｅｍｐｌｅ.ｃｏｍ » doit redevenir
    # « exemple.com ». NFKD seul suffit pour la pleine chasse ; la table de
    # confusables couvre le cyrillique et les petites capitales.
    value = _normaliser_confusables(value)
    # Les marqueurs Discord collent au mot : « **discord.gg**/abcd » s'affiche
    # comme un lien entier pour le lecteur, il doit l'être pour le filtre aussi.
    value = _MARQUEURS_DISCORD_RE.sub("", value)
    # Substitution des faux points, appliquée jusqu'à stabilité : « exemple[dot]com »
    # demande deux passes (le mot « dot » devient « . », puis « [.] » devient « . »).
    for _ in range(3):
        suivant = _FAUX_POINTS_RE.sub(".", value)
        if suivant == value:
            break
        value = suivant
    value = _recoller_points_avant_tld(value)
    value = re.sub(
        r"\b(h(?:tt|xx)p?s?)\s*:\s*/\s*/\s*",
        lambda m: f"{m.group(1)}://",
        value,
        flags=re.IGNORECASE,
    )
    # Sépare les schémas concaténés : ".../codehttps://..." devient
    # ".../code https://..." pour que les matchers puissent traiter chaque URL.
    value = re.sub(r"(?<!\s)(?=(?:https?|hxxps?)://)", " ", value, flags=re.IGNORECASE)
    return value.strip()
SCAM_KEYWORDS = [
    "free nitro", "nitro gratuit", "discord nitro free", "free discord nitro",
    "gagnez des nitro", "claim your nitro", "gift nitro free", "nitro giveaway",
    "free robux", "robux gratuit", "claim robux", "robux giveaway",
    "free vbucks", "vbucks gratuit", "claim vbucks",
    "airdrop gratuit", "crypto giveaway", "double your crypto",
    "investissement garanti", "connect your wallet", "wallet verification",
    "steam gift free", "free steam gift", "steam gift gratuit", "cadeau steam gratuit",
]

SCAM_IMAGE_MAX_BYTES = 8 * 1024 * 1024
SCAM_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
SCAM_IMAGE_TIMEOUT_SECONDS = 4.5
SCAM_IMAGE_MIN_CONFIDENCE = 98
SCAM_IMAGE_MAX_PARALLEL = 4
_SCAM_IMAGE_CATEGORIES = frozenset({
    "fake_nitro", "fake_robux", "fake_vbucks", "fake_giveaway",
    "crypto_airdrop", "phishing_login", "qr_phishing",
})
_SCAM_IMAGE_SEMAPHORE = asyncio.Semaphore(SCAM_IMAGE_MAX_PARALLEL)
_SCAM_IMAGE_PROMPT = (
    "Tu es un classifieur anti-arnaque Discord très strict. Analyse uniquement l'image. "
    "Réponds EXACTEMENT sur une ligne: VERDICT|CONFIDENCE|CATEGORY|REASON. "
    "VERDICT = SCAM, SAFE ou UNCERTAIN. CONFIDENCE = entier 0-100. "
    "CATEGORY, si SCAM, doit être l'une de: fake_nitro, fake_robux, fake_vbucks, "
    "fake_giveaway, crypto_airdrop, phishing_login, qr_phishing. "
    "Ne mets SCAM que si des éléments VISIBLES prouvent clairement une promotion frauduleuse "
    "ou du phishing (faux gain/cadeau, faux login, QR/lien de récupération, crypto/airdrop). "
    "Une simple capture Discord, un meme, une discussion sur les scams, un logo Nitro/Roblox, "
    "une offre officielle ou un doute = SAFE/UNCERTAIN. N'invente aucun texte ou lien."
)


def _is_scam_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = str(getattr(attachment, "content_type", "") or "").casefold()
    filename = str(getattr(attachment, "filename", "") or "").casefold()
    size = int(getattr(attachment, "size", 0) or 0)
    if size <= 0 or size > SCAM_IMAGE_MAX_BYTES:
        return False
    return content_type.startswith("image/") or filename.endswith(SCAM_IMAGE_EXTENSIONS)


def _parse_scam_image_result(value: str) -> str | None:
    """Accepte uniquement un verdict SCAM explicite, très confiant et catégorisé."""
    parts = [part.strip() for part in str(value or "").split("|", 3)]
    if len(parts) != 4 or parts[0].upper() != "SCAM":
        return None
    try:
        confidence = int(parts[1])
    except (TypeError, ValueError):
        return None
    category = parts[2].casefold()
    if confidence < SCAM_IMAGE_MIN_CONFIDENCE or category not in _SCAM_IMAGE_CATEGORIES:
        return None
    reason = re.sub(r"\s+", " ", parts[3]).strip()
    if not reason:
        return None
    return f"{category}: {reason[:100]}"


async def _scan_scam_image(attachment: discord.Attachment) -> str | None:
    """Vision rapide et conservatrice : en cas de doute, timeout ou erreur => aucune sanction."""
    if not _is_scam_image_attachment(attachment):
        return None
    client = ai_service.get_client()
    if client is None:
        return None
    try:
        async with _SCAM_IMAGE_SEMAPHORE:
            response = await asyncio.wait_for(
                client.responses.create(
                    model=ai_service.MODEL_IDS.get(ai_service.MODEL_LUNA, config.OPENAI_MODEL),
                    instructions=_SCAM_IMAGE_PROMPT,
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Classe l'image avec le format imposé."},
                                {"type": "input_image", "image_url": attachment.url},
                            ],
                        }
                    ],
                    reasoning={"effort": "none"},
                    max_output_tokens=36,
                ),
                timeout=SCAM_IMAGE_TIMEOUT_SECONDS,
            )
        text = (getattr(response, "output_text", None) or ai_service._extract_text(response) or "").strip()
    except asyncio.TimeoutError:
        logger.debug("Analyse anti-scam image timeout attachment=%s", getattr(attachment, "id", None))
        return None
    except Exception as exc:
        logger.debug(
            "Analyse anti-scam image indisponible attachment=%s erreur=%s",
            getattr(attachment, "id", None), type(exc).__name__,
        )
        return None
    return _parse_scam_image_result(text)


# Détection locale plus robuste que la simple liste de mots-clés. Elle reste
# volontairement conservative : un domaine officiel n'est jamais déclaré frauduleux
# uniquement parce qu'il contient "discord", "roblox" ou "steam".
_SCAM_TRUSTED_DOMAINS = (
    "discord.com", "discord.gg", "discordapp.com", "discord.gift",
    "roblox.com",
    "steamcommunity.com", "steampowered.com",
    "epicgames.com",
)
# Liens frauduleux comme https://discord.com@site-piege.example :
# la partie avant @ est un NOM D'UTILISATEUR, pas le domaine réel.
# On ne bloque cette forme que lorsqu'elle usurpe une vraie marque connue.
_SCAM_SPOOFED_AUTHORITIES = frozenset({
    "discord.com", "discord.gift", "roblox.com", "steamcommunity.com",
    "steampowered.com", "epicgames.com", "paypal.com", "metamask.io",
})
_SCAM_URL_RE = re.compile(r"\b(?:https?|hxxps?)://[^\s<>()]+", re.IGNORECASE)
# Hôtes sans https:// et avec homoglyphes (ex. « discοrd.gg »). Le matcher
# ASCII LINK_RE ne reconnaissait pas ces imitations si aucun schéma n'était
# écrit ; ne sanctionner que les hôtes confirmés par l'analyse des sosies.
_SCAM_BARE_HOST_RE = re.compile(
    r"(?<![\w@])(?:[\w-]+\.)+(?:com|gg|net|org|io|gift|app|xyz|ru|info|co|site|online|dev)\b",
    re.IGNORECASE,
)
_SCAM_BRANDS = ("discord", "nitro", "roblox", "robux", "steam", "vbucks", "crypto", "wallet")
_SCAM_LURES = ("free", "gift", "claim", "bonus", "verify", "airdrop", "giveaway", "reward")
_SCAM_CTA = (
    "click", "clique", "claim", "reclame", "recupere", "récupère", "redeem",
    "get now", "maintenant", "dm me", "mp moi", "scan", "connect", "verify",
)
_SCAM_DISCUSSION_MARKERS = (
    "is this scam", "is it a scam", "est ce une arnaque", "est-ce une arnaque",
    "c est une arnaque", "c'est une arnaque", "scam ?", "fake ?", "c est fake",
    "c'est fake", "est ce fake", "est-ce fake", "attention arnaque", "warning scam",
)
_NATIVE_SCAM_KEYWORDS = (
    "claim your nitro", "claim robux", "claim vbucks",
    "double your crypto", "wallet verification",
)


def _iter_link_hosts(content: str):
    normalized = _normalize_link_text(content)
    for match in LINK_RE.finditer(normalized):
        raw = str(match.group(0) or "").strip("<>()[]{}.,;!?").casefold()
        raw = re.sub(r"^(?:https?|hxxps?)://", "", raw, flags=re.IGNORECASE)
        # Un hôte ne contient ni chemin, ni query, ni fragment. Avant,
        # https://google.com?lang=fr était considéré comme un hôte différent,
        # tandis que les paramètres pouvaient masquer un domaine dangereux.
        raw = re.split(r"[/?#]", raw, maxsplit=1)[0]
        raw = raw.rsplit("@", 1)[-1]
        raw = raw.split(":", 1)[0].strip(".")
        if raw.startswith("www."):
            raw = raw[4:]
        if raw:
            yield raw


def _trusted_scam_host(host: str) -> bool:
    host = str(host or "").casefold().strip(".")
    return any(host == domain or host.endswith("." + domain) for domain in _SCAM_TRUSTED_DOMAINS)


def _scam_hit(content: str) -> str | None:
    """Détection à haute précision : domaine suspect d'abord, texte ambigu ensuite."""
    # URL avec userinfo trompeur : l'interface montre souvent le nom de marque
    # au début, alors que seul le domaine APRES @ reçoit les identifiants.
    # N'interpréter que les URL explicites et les marques officielles connues.
    for found in _SCAM_URL_RE.finditer(_normalize_link_text(content)):
        try:
            url = urlsplit(found.group(0))
            username = (url.username or "").casefold().strip(".")
            actual_host = (url.hostname or "").casefold().strip(".")
        except ValueError:
            continue
        if (
            username
            and actual_host
            and any(
                username == brand or username.endswith("." + brand)
                for brand in _SCAM_SPOOFED_AUTHORITIES
            )
            and not lookalike_domains.est_de_confiance(actual_host)
        ):
            return f"domaine suspect: fausse adresse officielle avant @ ({actual_host[:90]})"

    hosts = list(_iter_link_hosts(content))
    suspicious_hosts: list[str] = []
    for host in hosts:
        if _trusted_scam_host(host):
            continue
        compact = re.sub(r"[^a-z0-9]", "", host)
        if any(brand in compact for brand in _SCAM_BRANDS) and any(
            lure in compact for lure in _SCAM_LURES
        ):
            suspicious_hosts.append(host)
            continue
        if re.search(r"steamcom(?:rn|nn|m)unity", compact):
            suspicious_hosts.append(host)
            continue
        # Domaines sosies. La règle « marque ET appât » juste au-dessus est
        # précise mais laisse passer tout le typosquatting, où la marque n'est
        # justement PAS écrite correctement : mesuré le 29/09/2026, un seul
        # lien d'hameçonnage sur dix était vu (discrod.com, disc0rd.gg,
        # dlscord.com, robiox.com, steamcommunnity.com, du punycode et un « а »
        # cyrillique passaient tous).
        #
        # utils/lookalike_domains décide, avec sa propre liste blanche — qui
        # contient les vrais domaines hérités de Discord, discordapp.com et
        # discordapp.net, parce qu'un détecteur qui les signale casse les CDN.
        sosie = lookalike_domains.examiner(host)
        if sosie is not None:
            marque, motif_sosie = sosie
            suspicious_hosts.append(f"{host} (imite {marque} — {motif_sosie})")

    if suspicious_hosts:
        return f"domaine suspect: {suspicious_hosts[0][:120]}"

    # Un lien sans préfixe https:// écrit avec une lettre grecque/cyrillique
    # ressemble visuellement à une marque officielle. On ne généralise PAS le
    # filtre de domaines Unicode à un bloqueur de mots ou d'URLs ordinaires :
    # seul un sosie de marque confirmé est sanctionné.
    for match in _SCAM_BARE_HOST_RE.finditer(str(content or "")):
        host = match.group(0)
        result = lookalike_domains.examiner(host)
        if result is not None:
            brand, _ = result
            return f"domaine suspect: {host[:85]} (imite {brand})"

    normalized = text_normalization.normaliser(content)
    if any(text_normalization.normaliser(marker) in normalized for marker in _SCAM_DISCUSSION_MARKERS):
        return None

    motif = text_normalization.contient(content, SCAM_KEYWORDS)
    if not motif:
        return None

    if hosts and all(_trusted_scam_host(host) for host in hosts):
        return None

    cta = any(text_normalization.normaliser(token) in normalized for token in _SCAM_CTA)
    if hosts or cta:
        return motif
    return None

# Noms des ANCIENNES règles natives auto-créées par SentriX. Depuis la
# migration vers le filtrage local, elles servent seulement au nettoyage sûr
# des règles dont creator_id correspond réellement au bot.
NATIVE_ANTILINK_RULE_NAME = "SentriX • Anti-liens"
NATIVE_ANTILINK_CUSTOM_MESSAGE = "Les liens sont interdits sur ce serveur."
NATIVE_BLACKLIST_RULE_NAME = "SentriX • Mots interdits"
NATIVE_BLACKLIST_CUSTOM_MESSAGE = "Ce contenu est bloqué par ce serveur."
NATIVE_TARGET_LINKS_RULE_NAME = "SentriX • Liens ciblés"
NATIVE_TARGET_LINKS_CUSTOM_MESSAGE = "Ce lien est interdit sur ce serveur."
NATIVE_ANTIINVITE_RULE_NAME = "SentriX • Anti-invitations"
NATIVE_ANTIINVITE_CUSTOM_MESSAGE = "Les invitations Discord sont interdites sur ce serveur."
NATIVE_ANTISCAM_RULE_NAME = "SentriX • Anti-arnaque"
NATIVE_ANTISCAM_CUSTOM_MESSAGE = "Ce message ressemble à une arnaque interdite par ce serveur."
NATIVE_ANTIMENTION_RULE_NAME = "SentriX • Anti-mentions"
NATIVE_ANTIMENTION_CUSTOM_MESSAGE = "Ce message contient trop de mentions."
NATIVE_HARMFUL_RULE_NAME = "SentriX • Contenu sensible"
NATIVE_HARMFUL_CUSTOM_MESSAGE = "Ce contenu est bloqué par la modération du serveur."
NATIVE_INVITE_REGEX_PATTERNS = (
    r"(?i)\bdiscord\.gg/[^\s<]+",
    r"(?i)\bdiscord(?:app)?\.com/invite/[^\s<]+",
    r"(?i)\b(?:dsc\.gg|invite\.gg|discord\.me|discord\.io|discord\.link)/[^\s<]+",
    r"(?i)\bdisboard\.org/server/join/[^\s<]+",
)
NATIVE_ANTILINK_REGEX_PATTERNS = (
    r"(?i)\b(?:https?|hxxps?)://[^\s<]+",
    r"(?i)\bwww\.[^\s<]+",
    r"(?i)(?:^|[^a-z0-9_@])(?:[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.)+[a-z]{2,24}(?::[0-9]{2,5})?(?:/[^\s<]*)?",
    r"(?i)\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{2,5})?(?:/[^\s<]*)?",
    r"(?i)\bdiscord\.gg/[^\s<]+",
    r"(?i)\bdiscord(?:app)?\.com/invite/[^\s<]+",
    r"(?i)\b[a-z0-9-]+(?:\s*(?:\[\.\]|\(\.\)|\s+dot\s+)\s*[a-z0-9-]+)+\b",
)

# ---------------------------------------------------------------- ESCALADE DES SANCTIONS
# Au-delà d'un simple "suppression + avertissement", AutoMod suit désormais le nombre
# d'infractions d'un même membre sur une fenêtre glissante et escalade automatiquement
# la sanction si ça continue — sans qu'un modérateur ait besoin d'intervenir à la main.
# Le compteur est remis à zéro dès qu'une sanction est appliquée (on ne cumule pas
# plusieurs sanctions pour la même série d'infractions).
ESCALATION_WINDOW = 3600  # fenêtre glissante d'une heure
ESCALATION_RULES = [  # (seuil d'infractions atteint, action) — évalué du plus haut au plus bas
    (7, "ban"),
    (5, "kick"),
    (3, "mute"),
]
MUTE_ESCALATION_SECONDS = 600  # 10 minutes
DATASET_TIMEOUT_SECONDS = 600  # sanction directe du filtre multilingue
ESCALATION_LABELS = {"mute": "🔇 Mute 10 minutes", "kick": "👢 Expulsion", "ban": "🔨 Bannissement",
                     "derank": "🛡️ Rôles à risque retirés"}

# Un membre dont le rôle le plus haut est au-dessus de celui de SentriX est hors
# de portée des sanctions Discord : ni timeout, ni kick, ni ban ne passeront.
# Jusqu'ici l'escalade abandonnait là, en silence — aucune sanction, aucune
# alerte, aucune trace. Un staff qui abusait ne produisait donc aucun signal.
#
# La réponse est volontairement graduée : une bêtise isolée ne déclenche rien,
# seul le seuil le plus haut d'ESCALATION_RULES compte comme abus avéré. À ce
# moment SentriX fait ce que Discord l'autorise à faire — retirer les rôles à
# risque qui sont sous le sien — et prévient le propriétaire dans tous les cas,
# y compris quand il n'a rien pu retirer, en disant exactement pourquoi.
ABUS_PRIVILEGIE_SEUIL = max(seuil for seuil, _ in ESCALATION_RULES)

# Une rafale de spam est traitée comme UN incident par membre : la première détection
# supprime, sanctionne, prévient et journalise ; les détections suivantes dans la
# fenêtre ne font que supprimer le message et incrémenter le compteur. Avant cela,
# une rafale de 30 messages produisait ~15 avertissements publics, 15 cartes de log
# et plusieurs escalades pour la même séquence.
INCIDENT_WINDOW_SECONDS = 30.0
INCIDENT_LOG_DELAY_SECONDS = 4.0
#: Applications installées par un utilisateur (badge « APP ») : un raid typique
#: poste plusieurs fois en quelques secondes depuis la même commande.
EXTERNAL_APP_BURST_WINDOW = 10.0
EXTERNAL_APP_BURST_COUNT = 3
EXTERNAL_APP_TIMEOUT_SECONDS = 3600
SPAM_FILTERS = frozenset({"antispam", "antispam_duplicate", "antiemoji", "antimention"})
# Le contenu contenant un lien interdit est SUPPRIMÉ, jamais republié sous
# le nom/avatar du membre via un webhook (même avec une URL censurée).
LINK_NOTICE_FILTERS = frozenset({
    "antilink", "antiinvite", "blacklist_link", "blacklist_word_link",
})
NO_REPOST_FILTERS = LINK_NOTICE_FILTERS | {"antiscam"}

# Progression dédiée au spam :
# 1) rappel public avec ping ; 2) vrai warn enregistré ; 3+) timeout croissant.
# Après 24 h sans nouvel incident de spam, la progression repart au premier rappel.
SPAM_INCIDENT_WINDOW_SECONDS = 8.0
NATIVE_CLEANUP_TASK = "automod-native-rules-cleanup"
# Vague de spam : quand plusieurs membres spamment le même salon, un seul
# avertissement public regroupé par seconde au lieu d'un par membre (mesuré :
# 20 spammeurs = 20 messages du bot ajoutés au flot). Le premier part tout de suite.
SPAM_NOTICE_GROUP_WINDOW_SECONDS = 6.0
SPAM_NOTICE_GROUP_DELAY_SECONDS = 1.0
SPAM_NOTICE_MAX_MENTIONS = 10
SPAM_ESCALATION_RESET_SECONDS = 86400
SPAM_MUTE_DURATIONS_SECONDS = (600, 1800, 3600, 10800, 21600, 43200, 86400)
SPAM_TIMEOUT_SECONDS = SPAM_MUTE_DURATIONS_SECONDS[0]
SPAM_ESCALATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_spam_escalation (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    stage INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
"""


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texte or "")) if not unicodedata.combining(c))


@dataclass
class _Incident:
    started: float
    filter_name: str
    reason: str
    channel_id: int
    message_preview: str = ""
    deleted: int = 1
    action: str | None = None
    action_label: str | None = None
    infractions: int = 0
    spam_stage: int = 0
    #: Référence SX- de l'incident (fil SentriX) : sur la carte, dans +trace, et
    #: citée par les suites du staff (« Suite de l'incident AutoMod SX-… »).
    ref: str = ""
    author_id: int = 0
    #: Carte de log complète (29/10/2026) : heure réelle, message, contenu brut
    #: (neutralisé à l'affichage), suppression réussie ou non, durée de sanction.
    created_at: float = _champ(default_factory=time.time)
    message_id: int = 0
    raw_content: str = ""
    deleted_ok: bool | None = None
    duration_s: int | None = None


def _normalize_blocked_link_rule(value: str) -> str:
    raw = _normalize_link_text(str(value or "")).strip().strip("<>()[]{}.,;!?")
    raw = re.sub(r"^(?:https?|hxxps?)://", "", raw, flags=re.IGNORECASE)
    raw = raw.rstrip("/")
    return raw.casefold()


def _blocked_link_hit(content: str, rules: list[str]) -> str | None:
    """Retourne la règle ciblée qui correspond au message, y compris URLs concaténées.

    Le schéma est retiré pour que http/https/hxxps désignent la même cible. Les URLs sont
    d'abord séparées par _normalize_link_text(), ce qui ferme le contournement
    "lienInterdithttps://autre-lien".
    """
    if not rules:
        return None
    normalized = _normalize_link_text(content)
    normalized = re.sub(r"\b(?:https?|hxxps?)://", "", normalized, flags=re.IGNORECASE)
    for stored in rules:
        rule = _normalize_blocked_link_rule(stored)
        if not rule:
            continue
        pattern = rf"(?<![\w.-]){re.escape(rule)}(?=$|[/?#\s<>()\[\]{{}},.;!?])"
        if re.search(pattern, normalized, re.IGNORECASE):
            return stored
    return None


def _censor_blacklist_word(content: str, word: str | None) -> str | None:
    """Masque un mot détecté sans republier le terme interdit.

    Retourne None si le texte détecté ne peut pas être retrouvé de façon sûre dans le
    contenu original (par exemple une variante Unicode trop éloignée) : dans ce cas on
    préfère ne pas cloner le message plutôt que de republier le terme interdit.
    """
    raw_word = str(word or "").strip()
    if not raw_word:
        return None
    prefix = raw_word.endswith("*")
    base = raw_word[:-1] if prefix else raw_word
    if not base:
        return None
    pattern = (
        rf"(?<![\w]){re.escape(base)}\w*"
        if prefix
        else rf"(?<![\w]){re.escape(base)}(?![\w])"
    )
    redacted, count = re.subn(
        pattern,
        "████ (mot censuré)",
        str(content or ""),
        flags=re.IGNORECASE,
    )
    return redacted if count else None


def _censor_links(content: str) -> str | None:
    """Masque les liens visibles d'un message destiné au repost webhook."""
    redacted, count = LINK_RE.subn("████ (lien censuré)", str(content or ""))
    return redacted if count else None


_CENSORED_INVITE_CODE = "æ@#/%E2%82%AC%C3%9F!%&"


def _censor_invites(content: str) -> str | None:
    """Conserve la forme du lien mais détruit définitivement le code d\'invitation.

    Exemple :
      https://discord.gg/vraicode
      -> https://discord.gg/æ@#/%E2%82%AC%C3%9F!%& (invitation censurée)

    Le schéma https:// n\'est pas inclus dans INVITE_RE : il reste donc naturellement
    devant le domaine, exactement comme dans le rendu demandé. Le vrai code ne doit
    jamais être recopié dans le message webhook.
    """
    def replacement(match: re.Match) -> str:
        raw = str(match.group(0) or "")
        slash = raw.rfind("/")
        base = raw[: slash + 1] if slash >= 0 else raw + "/"
        return f"{base}{_CENSORED_INVITE_CODE} (invitation censurée)"

    redacted, count = INVITE_RE.subn(replacement, str(content or ""))
    return redacted if count else None


def _censor_scam(content: str) -> str | None:
    redacted = str(content or "")
    count = 0
    for keyword in sorted(SCAM_KEYWORDS, key=len, reverse=True):
        redacted, hits = re.subn(
            re.escape(keyword),
            "████ (contenu censuré)",
            redacted,
            flags=re.IGNORECASE,
        )
        count += hits

    masked_links = _censor_links(redacted)
    if masked_links is not None:
        redacted = masked_links
        count += 1
    return redacted if count else None


def _compose_censored_content(
    content: str,
    *,
    blocked_word: str | None = None,
    links: bool = False,
    invites: bool = False,
    scam: bool = False,
) -> str | None:
    """Construit le texte cloné. None = impossible de censurer sans risque de fuite."""
    result = str(content or "")
    changed = False

    if blocked_word:
        masked = _censor_blacklist_word(result, blocked_word)
        if masked is None:
            return None
        result = masked
        changed = True

    if invites:
        masked = _censor_invites(result)
        if masked is None:
            return None
        result = masked
        changed = True

    if links:
        masked = _censor_links(result)
        if masked is None:
            # Un lien ciblé peut avoir été normalisé depuis une écriture obfusquée
            # ("site[.]com"). Ne jamais republier le texte original dans ce cas.
            return None
        result = masked
        changed = True

    if scam:
        masked = _censor_scam(result)
        if masked is None:
            return None
        result = masked
        changed = True

    if not changed:
        return None
    result = result.strip()
    if not result:
        return "(contenu censuré)"
    if len(result) > 1950:
        result = result[:1947].rstrip() + "..."
    return result


_WHITELIST_DOMAIN_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z",
    re.IGNORECASE,
)


def _canonical_whitelist_domain(value: str) -> str | None:
    """Accepte uniquement un nom d'hôte, jamais un motif ou une URL libre.

    Les anciennes entrées « . », « * », chemins et schémas sont rejetées à
    l'utilisation pour qu'une mauvaise valeur en base ne désactive pas la sécurité.
    """
    host = str(value or "").strip().casefold().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not _WHITELIST_DOMAIN_RE.fullmatch(host):
        return None
    return host


def _domain_allowed(content_lower: str, allowed_domains: list[str]) -> bool:
    """Autorise un message SEULEMENT si TOUS ses liens ont un hôte autorisé.

    L'ancien contrôle cherchait le texte « google.com » n'importe où, même
    dans le chemin d'un site frauduleux ou à côté d'un autre lien. Dorénavant
    on valide le véritable hôte de chaque URL, y compris après userinfo @.
    """
    whitelist = {
        host
        for item in allowed_domains
        if (host := _canonical_whitelist_domain(item)) is not None
    }
    if not whitelist:
        return False
    hosts = list(_iter_link_hosts(content_lower))
    return bool(hosts) and all(
        any(host == domain or host.endswith("." + domain) for domain in whitelist)
        for host in hosts
    )


TOGGLE_FIELDS = [
    "antispam", "antilink", "antilink_strict", "antiinvite", "antimention", "anticaps",
    "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke", "antiinsult",
    "security_vanity", "security_prune", "security_permissions", "join_gate", "risk_engine",
    "escalation",
]

# Protections qui inspectent un message et permettent le bypass par rôle
# OU par membre individuel. Un salon strict reprend toujours la priorité
# sur les deux types de bypass. Les protections serveur (anti-nuke, anti-raid, etc.)
# restent gérées par leurs garde-fous dédiés car elles ne possèdent pas de
# notion de salon de message.
SECURITY_FILTER_POLICY_KEYS = frozenset({
    "antispam",
    "antilink",
    "antiinvite",
    "antimention",
    "anticaps",
    "antiemoji",
    "antiscam",
    "antiinsult",
})
SECURITY_FILTER_POLICY_ALIASES = {
    "antispam_duplicate": "antispam",
    "spam": "antispam",
    "blacklist_link": "antilink",
    "blacklist_word_link": "antilink",
    "dangerous_attachment": "antiscam",
    "blacklist_word": "antiinsult",
    "multilingual_toxicity": "antiinsult",
}

# Libellés lisibles des filtres AutoMod — réutilisés par /automod-status ET par la page
# "Sécurité" de /setup, pour ne jamais avoir deux endroits à maintenir séparément.
AUTOMOD_TOGGLE_LABELS = {
    "antispam": "Flood & messages répétés",
    "antilink": "Liens externes",
    "antilink_strict": "Blocage total des liens",
    "antiinvite": "Invitations Discord",
    "antimention": "Mentions abusives",
    "anticaps": "Majuscules excessives",
    "antiemoji": "Flood d'émojis",
    "antiraid": "Protection anti-raid",
    "antibot": "Bots non autorisés",
    "antiaccount": "Comptes trop récents",
    "antiscam": "Arnaques & phishing",
    "antinuke": "Protection anti-destruction",
    "antiinsult": "Langage toxique",
    "security_vanity": "Lien personnalisé du serveur",
    "security_prune": "Suppressions massives de membres",
    "security_permissions": "Permissions à risque",
    "join_gate": "Filtre des nouvelles arrivées",
    "risk_engine": "Analyse comportementale",
    "escalation": "Sanctions progressives",
}

_AUTOMOD_LOG_EVENT_LABELS = {
    "automod_link": "Liens externes",
    "automod_invite": "Invitations Discord",
    "automod_scam": "Arnaques & phishing",
    "automod_word": "Contenu interdit",
    "automod_mention": "Mentions abusives",
    "automod_spam": "Flood & messages répétés",
    "spam": "Flood & messages répétés",
    "antiraid": "Protection anti-raid",
    "raid": "Protection anti-raid",
}

_AUTOMOD_LOG_TITLE_LABELS = (
    ("anti-nuke", "Anti-nuke"),
    ("antinuke", "Anti-nuke"),
    ("antibot", "Anti-bots non autorisés"),
    ("anti-bot", "Anti-bots non autorisés"),
    ("antiaccount", "Anti-comptes très récents"),
    ("anti-account", "Anti-comptes très récents"),
    ("anti-spam", "Anti-spam"),
    ("spam", "Anti-spam"),
    ("anti-lien", "Anti-liens"),
    ("antiinvite", "Anti-invitations Discord"),
    ("anti-invite", "Anti-invitations Discord"),
    ("anti-arnaque", "Anti-arnaques"),
    ("scam", "Anti-arnaques"),
    ("multilingue", "Anti-insultes / contenu offensant"),
    ("mention", "Anti-mentions massives"),
    ("raid", "Anti-raid"),
    ("risk score", "Score Risk comportemental"),
    ("vanity", "Protection vanity URL"),
    ("prune", "Détection des prunes membres"),
    ("permissions dangereuses", "Garde permissions dangereuses"),
    ("garde permissions", "Garde permissions dangereuses"),
    ("immunité", "Immunité AutoMod"),
)


def _contenu_brut(message) -> str:
    """Texte du message et noms des pièces jointes (jamais leurs URL signées)."""
    contenu = str(getattr(message, "content", "") or "").strip()
    noms = [str(getattr(a, "filename", "") or "") for a in list(getattr(message, "attachments", ()) or ())[:5]]
    noms = [n for n in noms if n]
    if noms:
        contenu = "\n".join(part for part in (contenu, "Pièces jointes : " + ", ".join(noms)) if part)
    return contenu


def _automod_message_preview(message_or_text, *, limit: int = 900) -> str:
    """Bloc Message lisible pour les logs AutoMod, sans jamais dépasser Discord."""
    if hasattr(message_or_text, "content"):
        content = str(getattr(message_or_text, "content", "") or "").strip()
        attachments = []
        for attachment in list(getattr(message_or_text, "attachments", ()) or ())[:3]:
            url = str(getattr(attachment, "url", "") or "").strip()
            if url:
                attachments.append(url)
        if attachments:
            content = "\n".join(part for part in (content, *attachments) if part)
    else:
        content = str(message_or_text or "").strip()

    if not content:
        return ""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if len(content) > limit:
        content = content[: max(1, limit - 1)].rstrip() + "…"
    # Citation Discord : garde les URLs cliquables et rend même un long texte lisible.
    return "> " + content.replace("\n", "\n> ")


def _automod_protection_label(log_type: str, title: str) -> str:
    key = str(log_type or "").strip().casefold().replace("-", "_")
    if key in _AUTOMOD_LOG_EVENT_LABELS:
        return _AUTOMOD_LOG_EVENT_LABELS[key]
    sample = str(title or "").casefold()
    for token, label in _AUTOMOD_LOG_TITLE_LABELS:
        if token in sample:
            return label
    return "Protection AutoMod"


def _automod_default_sanction(log_type: str, title: str, protection: str) -> str:
    key = str(log_type or "").strip().casefold().replace("-", "_")
    sample = f"{title} {protection}".casefold()
    if key in {"automod_link", "automod_invite", "automod_scam", "automod_word", "automod_mention", "automod_spam", "spam"}:
        return "Suppression du message"
    if "antibot" in sample or "anti-bot" in sample or "antiaccount" in sample or "anti-compte" in sample:
        return "Expulsion"
    if "risk" in sample:
        return "Surveillance renforcée"
    if "raid" in sample or "nuke" in sample or "permissions" in sample or "vanity" in sample or "prune" in sample:
        return "Protection automatique"
    return "Action AutoMod"


def _style_automod_log(embed: discord.Embed, log_type: str) -> discord.Embed:
    """Uniformise tous les logs AutoMod avant leur rendu SentriX Trace."""
    title = str(embed.title or "")
    fields = [
        (str(field.name or ""), str(field.value or ""), bool(field.inline))
        for field in embed.fields
        if str(field.value or "").strip()
    ]

    def take(*tokens: str, whole: bool = False):
        # Un libellé commence par le mot cherché ; en sous-chaîne, « action »
        # attrapait « Infr·actions (1h) » et « message » attrapait « Messages
        # supprimés » — la carte affichait « Sanction : 3 » et perdait le
        # message supprimé (mesuré le 09/10/2026 sur le bot booté).
        end = r"(?!\w)" if whole else ""
        for index, (name, value, inline) in enumerate(fields):
            low = name.casefold()
            if index not in used and any(re.search(rf"(?<!\w){re.escape(token)}{end}", low) for token in tokens):
                return index, name, value, inline
        return None

    used: set[int] = set()

    identity = take("membre", "bot expuls", "membre expuls", "auteur suspect", "auteur", "acteur", "cible", "utilisateur")
    if identity:
        used.add(identity[0])
    protection = take("protection")
    sanction = take("sanction", "action prise", "action")
    reason = take("raison", "reason")
    channel = take("salon", "channel")
    message = take("message", "contenu", "content", whole=True)

    ordered: list[tuple[str, str, bool]] = []

    if identity:
        used.add(identity[0])
        ordered.append(("Membre", identity[2][:1024], False))

    protection_value = protection[2] if protection else _automod_protection_label(log_type, title)
    if protection:
        used.add(protection[0])
    ordered.append(("Protection", protection_value[:1024], True))

    # Une carte au statut explicite (utils/automod_incident_card, Raid Protect)
    # dit elle-même ce qui a été fait : ne pas inventer une sanction par défaut.
    a_un_statut = any(name.casefold().strip() == "statut" for name, _v, _i in fields)
    sanction_value = sanction[2] if sanction else (
        "" if a_un_statut else _automod_default_sanction(log_type, title, protection_value)
    )
    if sanction:
        used.add(sanction[0])
    if sanction_value:
        ordered.append(("Sanction", sanction_value[:1024], True))

    if reason:
        used.add(reason[0])
        ordered.append(("Raison", reason[2][:1024], False))

    if channel:
        used.add(channel[0])
        ordered.append(("Salon", channel[2][:1024], False))

    if message:
        used.add(message[0])
        ordered.append(("Message", message[2][:1024], False))

    # Garde tous les détails spécifiques (score, nombre de messages, niveau,
    # rôle, permissions, etc.) APRÈS le bloc principal au lieu de les perdre.
    for index, (name, value, inline) in enumerate(fields):
        if index in used:
            continue
        if name.casefold().strip(" :") in {"protection", "sanction", "raison", "salon", "message"}:
            continue
        ordered.append((name[:256] or "Détail", value[:1024], inline))
        if len(ordered) >= 20:
            break

    styled = embeds.canonical_log_embed(
        "Protection SentriX",
        description=str(embed.description or "")[:3500],
        fields=ordered,
    )
    image_url = str(getattr(getattr(embed, "image", None), "url", "") or "")
    if image_url:
        styled.set_image(url=image_url)
    thumbnail_url = str(getattr(getattr(embed, "thumbnail", None), "url", "") or "")
    if thumbnail_url:
        styled.set_thumbnail(url=thumbnail_url)
    return styled


# Préréglages du niveau de sécurité global (/security-level et page "Sécurité" de /setup).
SECURITY_PRESETS = {
    "faible": {
        "antispam": 0, "antilink": 0, "antiinvite": 0, "antiraid": 0,
        "antiscam": 1, "antinuke": 1, "escalation": 0,
    },
    "moyen": {
        "antispam": 1, "antilink": 0, "antiinvite": 1, "antiraid": 1,
        "antiscam": 1, "antinuke": 1, "escalation": 1,
    },
    "eleve": {
        "antispam": 1, "antilink": 1, "antiinvite": 1, "antiraid": 1, "antiscam": 1,
        "antimention": 1, "antiaccount": 1, "antinuke": 1,
        "security_vanity": 1, "security_prune": 1, "security_permissions": 1,
        "join_gate": 1, "risk_engine": 1, "escalation": 1,
    },
}

TOGGLE_CHOICES = [
    app_commands.Choice(name="Activer", value="on"),
    app_commands.Choice(name="Désactiver", value="off"),
]

DANGEROUS_PERMS = [
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
    "ban_members", "kick_members", "moderate_members", "mention_everyone",
]
# Réactivité normale. Chaque serveur a désormais la sienne : utils/spam_sensitivity.py.
SPAM_WINDOW = 6  # secondes observées pour le comptage anti-spam
SPAM_THRESHOLD = 5  # messages dans la fenêtre avant sanction
# Flood lent réparti sur plusieurs salons : 14 messages SIGNIFICATIFS dans 60 s
# et au moins 4 salons distincts. Cette double condition évite de sanctionner
# une discussion active dans un seul salon ou des réponses brèves (« ok », « +1 »).
SPAM_CROSS_CHANNEL_WINDOW = 60
SPAM_CROSS_CHANNEL_THRESHOLD = 14
SPAM_CROSS_CHANNEL_MIN_CHANNELS = 4
SPAM_CROSS_CHANNEL_MIN_LENGTH = 12

# Le comptage par débit ne voit QUE la vitesse : quatre messages toutes les six
# secondes — quarante par minute, indéfiniment — restaient invisibles, et cent
# fois le même message espacé de dix secondes n'était pas du spam pour lui.
# C'est pourtant le schéma publicitaire le plus courant sur Discord.
REPEAT_WINDOW = 90  # secondes observées pour la répétition d'un même message
REPEAT_THRESHOLD = 4  # fois le même message avant sanction
REPEAT_CHANNEL_THRESHOLD = 3  # salons différents recevant le même message
# En dessous de cette longueur, on ne compte pas : « ok », « lol », « +1 » ou
# « merci » se répètent légitimement toute la journée dans une conversation, et
# les sanctionner ferait couper la protection par les admins — donc plus de
# protection du tout.
REPEAT_MIN_LENGTH = 12
# Raid coordonné : le même message posté par plusieurs comptes, chacun sous son
# propre seuil (mesuré : 15 comptes × 1 message identique = 0 suppression). Pour
# ne pas prendre une fête (« joyeux anniversaire ! » × 6) pour un raid, seul un
# message long ou portant un lien compte.
COORDINATED_WINDOW = 20
COORDINATED_AUTHORS = 5
COORDINATED_MIN_LENGTH = 40
RAID_JOIN_WINDOW = 10  # secondes observées pour l'afflux d'arrivées
RAID_JOIN_THRESHOLD = 8  # arrivées dans la fenêtre avant alerte de raid
# Même angle mort que l'anti-spam : une fenêtre courte ne voit que la vitesse.
# Sept arrivées toutes les dix secondes — quarante-deux comptes par minute,
# deux mille cinq cents par heure — n'atteignaient jamais le seuil. Une seconde
# fenêtre, large, attrape le raid patient sans gêner un serveur qui grandit.
RAID_SLOW_WINDOW = 600  # dix minutes
RAID_SLOW_THRESHOLD = 60  # arrivées sur dix minutes avant alerte

# Les deux seuils ci-dessus sont PLATS : huit arrivées en dix secondes
# déclenchent la même alerte sur un serveur de vingt membres et sur un serveur
# de vingt mille. Pour le petit, huit inconnus d'un coup EST le raid ; pour le
# gros, c'est une journée ordinaire. Un seuil unique est donc forcément trop
# laxiste d'un côté et trop nerveux de l'autre.
#
# Deux corrections, dans l'esprit des bots dédiés à l'anti-raid :
#
# 1. le seuil suit la taille du serveur, borné pour ne jamais devenir absurde ;
# 2. un compte créé il y a trois jours pèse plus qu'un compte de trois ans.
#    Vingt comptes neufs d'un coup, c'est un raid ; vingt vétérans après une
#    vidéo, non. C'est ce poids qui rend la détection réellement plus stricte
#    sans multiplier les fausses alertes.
RAID_SEUIL_MINIMAL = 4          # jamais plus laxiste que ça, même tout petit serveur
RAID_SEUIL_MAXIMAL = 25         # ni plus nerveux que ça sur un très gros serveur
RAID_PART_DES_MEMBRES = 0.012   # ~1,2 % des membres arrivant en dix secondes
RAID_COMPTE_NEUF_JOURS = 7      # en-deçà, le compte est « neuf »
RAID_POIDS_COMPTE_NEUF = 2.0    # un compte neuf compte double dans la vélocité


def seuil_raid_rapide(nombre_de_membres: int | None) -> int:
    """Seuil d'afflux adapté à la taille du serveur.

    Borné des deux côtés : en dessous de RAID_SEUIL_MINIMAL on sanctionnerait
    une arrivée d'amis, au-dessus de RAID_SEUIL_MAXIMAL on laisserait passer
    un vrai raid sur un gros serveur.
    """
    try:
        membres = int(nombre_de_membres or 0)
    except (TypeError, ValueError):
        membres = 0
    proportionnel = round(membres * RAID_PART_DES_MEMBRES)
    return max(RAID_SEUIL_MINIMAL, min(RAID_SEUIL_MAXIMAL, proportionnel))


def velocite_ponderee(arrivees: int, arrivees_neuves: int) -> float:
    """Vélocité où un compte fraîchement créé pèse double.

    Un afflux de comptes neufs est le signe le plus fiable d'un raid, et c'est
    précisément ce qu'un comptage brut ignore.
    """
    anciennes = max(0, int(arrivees) - int(arrivees_neuves))
    return anciennes + int(arrivees_neuves) * RAID_POIDS_COMPTE_NEUF
NUKE_ACTION_WINDOW = 30  # secondes
NUKE_ACTION_THRESHOLD = 3  # actions destructrices avant déclenchement
RISK_DECAY_SECONDS = 900
RISK_ALERT_THRESHOLD = 70
RISK_ACTION_THRESHOLD = 100
JOIN_GATE_DEFAULT_AVATAR_POINTS = 20
JOIN_GATE_RECENT_ACCOUNT_DAYS = 7
RISK_SIGNAL_POINTS = {
    "antispam": 18,
    "antispam_duplicate": 22,
    "antiemoji": 14,
    "antimention": 28,
    "antilink": 20,
    "antiinvite": 28,
    "antiscam": 45,
    "blacklist_word": 18,
    "blacklist_link": 25,
    "blacklist_word_link": 35,
    "multilingual_toxicity": 25,
}


def _member_has_default_avatar(member: discord.Member) -> bool:
    return getattr(member, "avatar", None) is None


def _dangerous_perm_names(perms: discord.Permissions) -> list[str]:
    return [name for name in DANGEROUS_PERMS if bool(getattr(perms, name, False))]


class _MessageDApplication:
    """Le message d'une application externe, vu comme celui du membre qui l'a lancée.

    Tout est délégué au vrai message (suppression, salon, pièces jointes…),
    sauf l'auteur — le membre qui a tapé la commande — et le contenu, qui
    inclut le texte des embeds : une application cache souvent son message
    dans un embed. Chaque filtre d'AutoMod s'applique donc tel quel, avec ses
    sanctions progressives, au vrai responsable.
    """

    _sentrix_external_app = True

    def __init__(self, message: discord.Message, invoker: discord.Member, content: str):
        object.__setattr__(self, "_message", message)
        object.__setattr__(self, "author", invoker)
        object.__setattr__(self, "content", content)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_message"), name)

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class _MessageModifie(_MessageDApplication):
    """Un message MODIFIÉ, filtré comme un nouveau message.

    Sans cela, poster « salut » puis le transformer en lien d'arnaque ou en
    invitation passait toutes les protections. Il n'est pas compté par
    l'anti-spam : ce n'est pas un message de plus.
    """

    _sentrix_external_app = False
    _sentrix_edit = True



def _reglages_par_defaut() -> dict:
    """Un serveur jamais configuré ne reçoit aucune protection sans accord."""
    from cogs.setup_control_center import AUTOMOD

    ligne = {champ: 0 for champ, _libelle in AUTOMOD}
    ligne.update(antilink_strict=0, escalation=0)
    return ligne


class AutoMod(commands.Cog, name="Automod"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Compteurs à fenêtre glissante. Ils étaient de simples dictionnaires dont
        # les horodatages étaient élagués mais dont les CLÉS ne l'étaient jamais :
        # une entrée par membre ayant parlé une fois, gardée à vie, même après son
        # départ. Mesuré à 12,4 Mo pour 50 000 membres sur le seul spam_tracker,
        # et rien ne redescendait. FenetreGlissante oublie les clés inactives.
        # Fenêtre la plus large permise : chaque serveur compte sur la sienne
        # (utils/spam_sensitivity.py).
        self.spam_tracker = FenetreGlissante(fenetre=spam_sensitivity.FENETRE_MAX)
        self.cross_channel_spam_tracker = FenetreGlissante(
            fenetre=SPAM_CROSS_CHANNEL_WINDOW,
        )
        self.join_tracker = FenetreGlissante(fenetre=RAID_JOIN_WINDOW, purge_toutes=100)
        self.slow_join_tracker = FenetreGlissante(fenetre=RAID_SLOW_WINDOW, purge_toutes=100)
        self.new_account_tracker = FenetreGlissante(fenetre=RAID_JOIN_WINDOW, purge_toutes=100)
        self._recent_raid_joins = RaidJoinDeduplicator(ttl_seconds=20, max_entries=8192)
        self._raid_alert_last: dict[int, float] = {}
        self._raid_recovery = RaidVerificationRecovery(bot)
        self._raid_recovery_task: asyncio.Task | None = None
        self.nuke_tracker = FenetreGlissante(fenetre=NUKE_ACTION_WINDOW, purge_toutes=100)
        self.infraction_tracker = FenetreGlissante(fenetre=ESCALATION_WINDOW)
        self.repeat_tracker = FenetreGlissante(fenetre=REPEAT_WINDOW)
        self.coordinated_tracker = FenetreGlissante(fenetre=COORDINATED_WINDOW, purge_toutes=200)
        self.risk_scores: dict[tuple[int, int], tuple[float, float]] = {}
        self.incidents: dict[tuple[int, int], _Incident] = {}
        # Plusieurs cogs traitent on_message en parallèle. La réservation est
        # synchrone, avant toute suppression/sanction, et commune aux filtres.
        self._sanctioned_messages = AutomodMessageClaims(
            ttl_seconds=120, max_entries=16384,
        )
        self.moderation_dataset = MultilingualModerationDataset()
        # Caches mémoire : évitent des allers-retours en base de données à CHAQUE
        # message (ce qui ralentissait le bot sur un salon actif). Invalidés dès
        # qu'une commande change un réglage.
        self.automod_cache: dict[int, dict] = {}
        self.blacklist_words_cache: dict[int, list[str]] = {}
        self.blacklist_links_cache: dict[int, list[str]] = {}
        self.blacklist_users_cache: dict[int, set[int]] = {}
        self.whitelist_domains_cache: dict[int, list[str]] = {}
        # Webhook utilisé pour recréer visuellement un message censuré avec le pseudo
        # et l'avatar du membre. Discord affiche toujours le badge APP/webhook.
        self._censor_webhooks: dict[int, discord.Webhook] = {}
        self.exempt_roles_cache: dict[int, set[int]] = {}
        self.ignored_channels_cache: dict[int, set[int]] = {}
        self.security_filter_policy_cache: dict[tuple[int, str], dict[str, set[int]]] = {}
        # Compatibilité avec les extensions V1 qui invalidaient encore ce cache.
        self.antispam_policy_cache: dict[int, dict[str, object]] = {}
        self.immunity_overrides_cache: dict[tuple[int, int], bool | None] = {}
        self._native_antilink_locks: dict[int, asyncio.Lock] = {}
        self._native_automod_bootstrap_task: asyncio.Task | None = None
        # Diagnostic des blocages Discord natifs, sans stocker le contenu privé.
        self._native_block_last_seen: dict[tuple[int, int, int], float] = {}
        self._local_block_last_seen: dict[tuple[int, int, str], float] = {}
        self._admin_link_last_seen: dict[tuple[int, int], float] = {}
        # Applications externes : rafales par (serveur, membre) et dernier
        # dernière exclusion posée, pour ne sanctionner qu'une fois par raid.
        self._external_app_bursts: dict[tuple[int, int], list[float]] = {}
        self._external_app_sanctioned: dict[tuple[int, int], float] = {}
        self._native_rule_details: dict[tuple[int, int], tuple[str, int | None]] = {}

        # Toute écriture AutoMod venant des commandes, du Dashboard ou de l'IA passe
        # par Database.set_automod et arrive ici pour invalider le cache + synchroniser
        # Discord AutoMod natif.
        db = getattr(self.bot, "db", None)
        if db is not None:
            db._sentrix_automod_change_hook = self._on_automod_setting_changed

    def _risk_value(self, guild_id: int, user_id: int) -> float:
        score, updated_at = self.risk_scores.get((guild_id, user_id), (0.0, time.monotonic()))
        age = max(0.0, time.monotonic() - updated_at)
        if age >= RISK_DECAY_SECONDS:
            return 0.0
        return max(0.0, score * (1.0 - (age / RISK_DECAY_SECONDS)))

    async def add_risk_signal(
        self,
        guild: discord.Guild,
        user_id: int | None,
        signal: str,
        points: int,
        *,
        reason: str,
        target: discord.abc.User | int | None = None,
    ) -> float:
        if user_id is None:
            return 0.0
        conf = await self.get_automod_cached(guild.id)
        if not conf.get("risk_engine"):
            return 0.0

        key = (guild.id, int(user_id))
        score = min(150.0, self._risk_value(*key) + max(0, int(points)))
        self.risk_scores[key] = (score, time.monotonic())
        await self.bot.db.log_automod_action(guild.id, int(user_id), f"risk:{signal}", "score", f"{reason} (+{points}, total {score:.0f})")

        if score >= RISK_ALERT_THRESHOLD:
            extra = {"Signal": signal, "Score": f"{score:.0f}/{RISK_ACTION_THRESHOLD}", "Décroissance": f"{RISK_DECAY_SECONDS // 60} min"}
            e = embeds.log_entry(
                "🔥 Risk score élevé" if score < RISK_ACTION_THRESHOLD else "🚨 Risk score critique",
                config.COLOR_WARNING if score < RISK_ACTION_THRESHOLD else config.COLOR_ERROR,
                cible=target or user_id,
                cible_label="Membre / acteur",
                raison=reason,
                extra=extra,
            )
            await self.log_action(guild, e)
        return score

    async def _bot_is_allowlisted(self, guild_id: int, bot_id: int) -> bool:
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM automod_bot_allowlist WHERE guild_id = ? AND bot_id = ?",
            (guild_id, bot_id),
        )
        return row is not None

    async def cog_load(self) -> None:
        await self._raid_recovery.ensure_schema()
        self._raid_recovery_task = asyncio.create_task(
            self._run_raid_recovery(),
            name="sentrix-raid-verification-recovery",
        )
        self._native_automod_bootstrap_task = asyncio.create_task(
            self._bootstrap_native_automod(),
            name="sentrix-native-automod-bootstrap",
        )

    def cog_unload(self) -> None:
        raid_task = self._raid_recovery_task
        if raid_task is not None:
            raid_task.cancel()
        task = self._native_automod_bootstrap_task
        if task is not None:
            task.cancel()
        db = getattr(self.bot, "db", None)
        hook = getattr(db, "_sentrix_automod_change_hook", None) if db is not None else None
        if getattr(hook, "__self__", None) is self:
            try:
                delattr(db, "_sentrix_automod_change_hook")
            except AttributeError:
                pass

    async def _run_raid_recovery(self) -> None:
        """Restauration des niveaux de vérification après un raid, même après reboot.

        En cas de logs d'audit indisponibles, la vérification maximale
        reste intacte pour ne jamais écraser un choix manuel d'administrateur.
        """
        try:
            await self.bot.wait_until_ready()
            while True:
                try:
                    result = await self._raid_recovery.restore_due()
                    if any(result.values()):
                        logger.info(
                            "Anti-raid restauration : restaurés=%s annulés=%s reportés=%s",
                            result["restored"], result["cancelled"], result["deferred"],
                        )
                except Exception:
                    logger.exception("Vérification des restaurations anti-raid impossible")
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    async def _bootstrap_native_automod(self) -> None:
        """Vérifie toutes les guilds et résume ce qui est réellement nettoyé."""
        try:
            await self.bot.wait_until_ready()
            from utils import once_per_guild

            totals = {"removed": 0, "protected": 0, "external": 0, "failed": 0}
            checked = 0
            # Migration ponctuelle : un serveur nettoyé ne l'est plus à chaque démarrage
            # (un appel Discord par serveur et par redémarrage, mesuré).
            by_id = {g.id: g for g in list(self.bot.guilds)}
            for guild_id in await once_per_guild.restants(self.bot, NATIVE_CLEANUP_TASK, by_id):
                result = await self._sync_native_suite(by_id[guild_id])
                if result is not None:
                    checked += 1
                    for name in totals:
                        totals[name] += result[name]
                    if not result["failed"]:
                        await once_per_guild.marquer(self.bot, NATIVE_CLEANUP_TASK, guild_id)
                await asyncio.sleep(0.15)
            logger.info(
                "AutoMod nettoyage terminé guilds=%s checked=%s removed=%s protected=%s external=%s failed=%s",
                len(self.bot.guilds), checked,
                totals["removed"], totals["protected"], totals["external"], totals["failed"],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Bootstrap de nettoyage AutoMod interrompu")

    @commands.Cog.listener()
    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        """Identifier les blocages exécutés par Discord AVANT le moteur Python.

        Ce signal est émis par l'intent auto_moderation_execution. Le contenu du
        message, les mots correspondants et les pièces jointes ne sont jamais
        journalisés. Une limitation réduit le bruit en cas de raid.
        """
        action = getattr(execution, "action", None)
        if getattr(action, "type", None) != discord.AutoModRuleActionType.block_message:
            return
        guild_id = int(getattr(execution, "guild_id", 0) or 0)
        rule_id = int(getattr(execution, "rule_id", 0) or 0)
        user_id = int(getattr(execution, "user_id", 0) or 0)
        if not guild_id or not rule_id or not user_id:
            return
        seen_key = (guild_id, rule_id, user_id)
        now = time.monotonic()
        if now - self._native_block_last_seen.get(seen_key, -9999.0) < 30:
            return
        if len(self._native_block_last_seen) > 2000:
            self._native_block_last_seen.clear()
        self._native_block_last_seen[seen_key] = now

        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild is not None else None
        privileged = (
            can_bypass_message_filters(member) if member is not None else None
        )
        details = self._native_rule_details.get((guild_id, rule_id))
        if details is None:
            details = ("inconnue", None)
            if guild is not None and getattr(
                getattr(getattr(guild, "me", None), "guild_permissions", None),
                "manage_guild", False,
            ):
                try:
                    rule = await guild.fetch_automod_rule(rule_id)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
                else:
                    details = (
                        str(getattr(rule, "name", "inconnue"))[:90],
                        getattr(rule, "creator_id", None),
                    )
            if len(self._native_rule_details) > 1000:
                self._native_rule_details.clear()
            self._native_rule_details[(guild_id, rule_id)] = details
        level = logging.WARNING if privileged else logging.INFO
        logger.log(
            level,
            "SENTRIX_BLOCK_SOURCE=discord_native guild=%s user=%s channel=%s rule=%s "
            "rule_name=%s creator=%s privileged=%s (aucun contenu enregistré)",
            guild_id, user_id, getattr(execution, "channel_id", None), rule_id,
            details[0], details[1], privileged,
        )

    async def _on_automod_setting_changed(self, guild_id: int, field: str, value: int) -> None:
        self.automod_cache.pop(int(guild_id), None)
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return

        if field in {"antilink", "antilink_strict"}:
            await self._sync_native_antilink_rule(guild)
        elif field == "antiinvite":
            await self._sync_native_antiinvite_rule(guild)
        elif field == "antiscam":
            await self._sync_native_antiscam_rule(guild)
        elif field == "antimention":
            await self._sync_native_antimention_rule(guild)
        elif field == "antiinsult":
            await self._sync_native_harmful_rule(guild)

    async def _native_policy_exemptions(
        self,
        guild: discord.Guild,
        filter_name: str,
    ) -> tuple[list[discord.Role], list[discord.abc.GuildChannel]] | None:
        """Traduit la politique SentriX vers les exemptions AutoMod Discord.

        Discord sait exempter un rôle OU un salon, mais ne sait pas exprimer
        « ce rôle est exempt partout SAUF dans ces salons stricts ». Si les deux
        sont configurés simultanément, la règle native SentriX est donc retirée et
        le moteur local (qui sait respecter cette priorité) devient l'autorité.
        """
        policy = await self.get_security_filter_policy_cached(guild.id, filter_name)
        bypass_role_ids = set(policy["role_ids"])
        bypass_role_ids.update(await self.get_exempt_roles_cached(guild.id))
        strict_channel_ids = set(policy["strict_channel_ids"])

        # Les règles natives Discord n'acceptent pas les exemptions par utilisateur.
        # Ne pas laisser une règle native sanctionner un membre exempté : dans ce
        # cas, SentriX applique lui-même ce filtre sur les messages.
        if policy.get("member_ids") or (strict_channel_ids and bypass_role_ids):
            return None

        roles = [
            role for role_id in bypass_role_ids
            if (role := guild.get_role(int(role_id))) is not None
        ]

        ignored = await self.get_ignored_channels_cached(guild.id)
        channels: list[discord.abc.GuildChannel] = []
        for channel_id in ignored:
            if int(channel_id) in strict_channel_ids:
                continue
            channel = guild.get_channel(int(channel_id))
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                channels.append(channel)
        return roles, channels

    async def _remove_owned_native_rules(
        self,
        guild: discord.Guild,
        names: frozenset[str] | set[str],
    ) -> dict[str, int] | None:
        """En une seule lecture, migrer les vieilles règles de SentriX.

        Les règles étrangères, homonymes ou appartenant à Discord sont
        conservées. Les protections « anti-mentions » imposées aux serveurs
        communautaires (erreur 200006) ne sont pas supprimables ; elles
        restent intactes et ne doivent pas empêcher le nettoyage des autres.
        """
        me = getattr(guild, "me", None)
        perms = getattr(me, "guild_permissions", None)
        if me is None or not getattr(perms, "manage_guild", False):
            logger.warning(
                "AutoMod nettoyage non vérifié guild=%s : Gérer le serveur manquant",
                guild.id,
            )
            return None
        own_id = getattr(getattr(self.bot, "user", None), "id", None) or getattr(me, "id", None)
        if own_id is None:
            logger.warning("AutoMod nettoyage impossible guild=%s : ID bot inconnu", guild.id)
            return None

        try:
            rules = await guild.fetch_automod_rules()
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("AutoMod règles inaccessibles guild=%s", guild.id, exc_info=True)
            return None

        results = {"removed": 0, "protected": 0, "external": 0, "failed": 0}
        for rule in rules:
            if getattr(rule, "name", None) not in names:
                continue
            creator_id = getattr(rule, "creator_id", None)
            if creator_id is None or int(creator_id) != int(own_id):
                results["external"] += 1
                continue
            try:
                await rule.delete(
                    reason="SentriX : migration vers filtres locaux avec exemptions staff",
                )
            except discord.Forbidden as exc:
                if getattr(exc, "code", None) == 200006:
                    # Règle anti-mentions requise par la communauté Discord.
                    results["protected"] += 1
                    continue
                results["failed"] += 1
                logger.warning(
                    "AutoMod suppression refusée guild=%s rule=%s status=403 code=%s",
                    guild.id, rule.id, getattr(exc, "code", None),
                )
            except discord.HTTPException as exc:
                results["failed"] += 1
                logger.warning(
                    "AutoMod suppression échouée guild=%s rule=%s error=%s",
                    guild.id, rule.id, type(exc).__name__,
                )
            else:
                results["removed"] += 1
                logger.info(
                    "AutoMod règle SentriX retirée guild=%s rule=%s name=%s",
                    guild.id, rule.id, rule.name,
                )
        logger.info(
            "AutoMod migration guild=%s removed=%s protected=%s external=%s failed=%s",
            guild.id, *(results[key] for key in ("removed", "protected", "external", "failed")),
        )
        return results

    async def _remove_owned_native_rule(
        self,
        guild: discord.Guild,
        name: str,
    ) -> bool:
        result = await self._remove_owned_native_rules(guild, frozenset({name}))
        return result is not None and not result["failed"]

    async def _sync_native_antilink_rule(self, guild: discord.Guild) -> bool:
        """Anti-liens LOCAL : plus de blocage natif avant le contrôle des admins."""
        return await self._remove_owned_native_rule(guild, NATIVE_ANTILINK_RULE_NAME)

    async def _upsert_native_rule(
        self,
        guild: discord.Guild,
        *,
        name: str,
        enabled: bool,
        trigger: discord.AutoModTrigger | None,
        custom_message: str,
        policy_filter: str | None = None,
    ) -> bool:
        """Compatibilité : retirer les anciennes règles SentriX, sans recréation.

        Discord AutoMod natif n'a pas toutes les exemptions par utilisateur ou
        par permissions de gestion. Tous les filtres actifs restent gérés
        localement par SentriX, selon leurs réglages de serveur.
        """
        return await self._remove_owned_native_rule(guild, name)

    async def _sync_native_target_links_rule(self, guild: discord.Guild) -> bool:
        rows = await self.bot.db.fetchall(
            "SELECT value FROM blacklist_links WHERE guild_id = ? ORDER BY value",
            (guild.id,),
        )
        keywords: list[str] = []
        seen: set[str] = set()
        for row in rows or ():
            value = _normalize_blocked_link_rule(str(row["value"] or ""))
            if not value or len(value) > 60 or value in seen:
                continue
            seen.add(value)
            keywords.append(value)
            if len(keywords) >= 1000:
                break
        trigger = discord.AutoModTrigger(keyword_filter=keywords) if keywords else None
        return await self._upsert_native_rule(
            guild,
            name=NATIVE_TARGET_LINKS_RULE_NAME,
            enabled=bool(keywords),
            trigger=trigger,
            custom_message=NATIVE_TARGET_LINKS_CUSTOM_MESSAGE,
            policy_filter="antilink",
        )

    async def _sync_native_antiinvite_rule(self, guild: discord.Guild) -> bool:
        conf = await self.bot.db.get_automod(guild.id)
        enabled = bool(conf and conf["antiinvite"] and not conf["antilink"])
        trigger = discord.AutoModTrigger(regex_patterns=list(NATIVE_INVITE_REGEX_PATTERNS))
        return await self._upsert_native_rule(
            guild,
            name=NATIVE_ANTIINVITE_RULE_NAME,
            enabled=enabled,
            trigger=trigger,
            custom_message=NATIVE_ANTIINVITE_CUSTOM_MESSAGE,
            policy_filter="antiinvite",
        )

    async def _sync_native_antiscam_rule(self, guild: discord.Guild) -> bool:
        conf = await self.bot.db.get_automod(guild.id)
        enabled = bool(conf and conf["antiscam"])
        # Discord AutoMod ne comprend pas le contexte : seulement les formulations les plus explicites.
        keywords = [k[:60] for k in _NATIVE_SCAM_KEYWORDS if k and len(k) <= 60]
        trigger = discord.AutoModTrigger(keyword_filter=keywords)
        return await self._upsert_native_rule(
            guild,
            name=NATIVE_ANTISCAM_RULE_NAME,
            enabled=enabled,
            trigger=trigger,
            custom_message=NATIVE_ANTISCAM_CUSTOM_MESSAGE,
            policy_filter="antiscam",
        )

    async def _sync_native_antimention_rule(self, guild: discord.Guild) -> bool:
        conf = await self.bot.db.get_automod(guild.id)
        enabled = bool(conf and conf["antimention"])
        trigger = discord.AutoModTrigger(
            mention_limit=5,
            mention_raid_protection=True,
        )
        return await self._upsert_native_rule(
            guild,
            name=NATIVE_ANTIMENTION_RULE_NAME,
            enabled=enabled,
            trigger=trigger,
            custom_message=NATIVE_ANTIMENTION_CUSTOM_MESSAGE,
            policy_filter="antimention",
        )

    async def _sync_native_harmful_rule(self, guild: discord.Guild) -> bool:
        # Le preset natif Discord mélange grossièretés, contenu sexuel et insultes.
        # Il peut donc bloquer des phrases neutres avant même que SentriX puisse
        # appliquer sa détection contextuelle. On le garde désactivé et on utilise
        # exclusivement le matcher multilingue local, plus précis et token-aware.
        presets = discord.AutoModPresets(
            profanity=True,
            sexual_content=True,
            slurs=True,
        )
        trigger = discord.AutoModTrigger(presets=presets)
        return await self._upsert_native_rule(
            guild,
            name=NATIVE_HARMFUL_RULE_NAME,
            enabled=False,
            trigger=trigger,
            custom_message=NATIVE_HARMFUL_CUSTOM_MESSAGE,
        )

    async def _sync_native_suite(self, guild: discord.Guild) -> dict[str, int] | None:
        """Nettoyage groupé : 1 appel HTTP par serveur au lieu de 7.

        Les vérifications Discord ne bloquent plus pendant plusieurs minutes
        une série de serveurs. Le moteur local continue de modérer les membres
        ordinaires ; seuls les filtres de messages sont concernés.
        """
        names = frozenset({
            NATIVE_ANTILINK_RULE_NAME,
            NATIVE_BLACKLIST_RULE_NAME,
            NATIVE_TARGET_LINKS_RULE_NAME,
            NATIVE_ANTIINVITE_RULE_NAME,
            NATIVE_ANTISCAM_RULE_NAME,
            NATIVE_ANTIMENTION_RULE_NAME,
            NATIVE_HARMFUL_RULE_NAME,
        })
        return await self._remove_owned_native_rules(guild, names)

    async def _sync_native_blacklist_rule(self, guild: discord.Guild) -> bool:
        """Les mots interdits restent filtrés localement avec bypass administrateur."""
        return await self._remove_owned_native_rule(guild, NATIVE_BLACKLIST_RULE_NAME)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        # Serveur neuf : réconcilie toutes les protections natives utiles.
        await self._sync_native_suite(guild)

    async def log_action(
        self,
        guild: discord.Guild,
        embed: discord.Embed,
        log_type: str = "automod",
        *,
        suites: discord.ui.View | None = None,
        file: discord.File | None = None,
    ):
        # Point unique : TOUS les événements AutoMod utilisent le même rendu
        # AutoMod Manage. helpers.send_log -> log_service -> send_wide_log ajoute
        # ensuite systématiquement la bannière de sécurité au-dessus de la carte.
        styled = _style_automod_log(embed, log_type)
        view = None
        if suites is not None:
            # Les boutons d'identifiants habituels d'abord, les suites ensuite.
            view = helpers._derive_log_view(styled) or discord.ui.View(timeout=None)
            for item in list(suites.children):
                view.add_item(item)
        await helpers.send_log(self.bot, guild, log_type, styled, view=view, file=file)

    # ---------------------------------------------------------------- CACHES

    async def get_automod_cached(self, guild_id: int) -> dict:
        if guild_id not in self.automod_cache:
            conf = await self.bot.db.get_automod(guild_id)
            self.automod_cache[guild_id] = dict(conf) if conf else _reglages_par_defaut()
        return self.automod_cache[guild_id]

    async def get_blacklist_words_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.blacklist_words_cache:
            rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (guild_id,))
            self.blacklist_words_cache[guild_id] = [r["word"] for r in rows]
        return self.blacklist_words_cache[guild_id]

    @staticmethod
    def _blacklist_hit(words: list[str], content: str) -> str | None:
        """Mot interdit présent comme MOT ENTIER (accents et casse ignorés).

        L'ancien test ``word in content_lower`` était un simple ``in`` : « con »
        supprimait « connexion », « pute » supprimait « réputé ». Un mot terminé par
        ``*`` garde volontairement la correspondance par préfixe (« merd* »).
        """
        if not words:
            return None
        # Même normalisation que les autres filtres : sans elle, « a r n a q u e »,
        # « 4rn4qu3 », « аrnaque » (а cyrillique) et « ᴀʀɴᴀǫᴜᴇ » passaient tous —
        # cinq contournements sur dix, sur le seul filtre que les admins
        # configurent eux-mêmes.
        texte = text_normalization.normaliser(content)
        for word in words:
            brut = text_normalization.normaliser(str(word or "")).strip()
            if not brut:
                continue
            # Le motif compilé est réutilisé (lru_cache) : passer par .pattern
            # puis re.search recompilait à chaque message, pour chaque mot de la
            # liste du serveur — 64 ms sur une liste de vingt mots.
            if brut.endswith("*"):
                motif = text_normalization.motif_prefixe(brut[:-1])
            else:
                motif = text_normalization.motif_tolerant(brut)
            if motif.search(texte):
                return word
        return None

    async def get_blacklist_links_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.blacklist_links_cache:
            rows = await self.bot.db.fetchall(
                "SELECT value FROM blacklist_links WHERE guild_id = ? ORDER BY value",
                (guild_id,),
            )
            self.blacklist_links_cache[guild_id] = [str(r["value"]) for r in rows if r["value"]]
        return self.blacklist_links_cache[guild_id]

    async def get_blacklist_users_cached(self, guild_id: int) -> set:
        if guild_id not in self.blacklist_users_cache:
            rows = await self.bot.db.fetchall("SELECT user_id FROM blacklist_users WHERE guild_id = ?", (guild_id,))
            self.blacklist_users_cache[guild_id] = {r["user_id"] for r in rows}
        return self.blacklist_users_cache[guild_id]

    async def get_whitelist_domains_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.whitelist_domains_cache:
            rows = await self.bot.db.fetchall("SELECT domain FROM whitelist_domains WHERE guild_id = ?", (guild_id,))
            self.whitelist_domains_cache[guild_id] = [r["domain"] for r in rows]
        return self.whitelist_domains_cache[guild_id]

    async def get_exempt_roles_cached(self, guild_id: int) -> set[int]:
        if guild_id not in self.exempt_roles_cache:
            reader = getattr(self.bot.db, "list_automod_exempt_roles", None)
            if callable(reader):
                rows = await reader(guild_id)
            else:
                fetchall = getattr(self.bot.db, "fetchall", None)
                rows = (
                    await fetchall(
                        "SELECT role_id FROM automod_exempt_roles WHERE guild_id = ?",
                        (guild_id,),
                    )
                    if callable(fetchall)
                    else []
                )
            self.exempt_roles_cache[guild_id] = {int(r["role_id"]) for r in rows}
        return self.exempt_roles_cache[guild_id]

    async def get_immunity_override_cached(self, guild_id: int, user_id: int) -> bool | None:
        key = (guild_id, user_id)
        if key not in self.immunity_overrides_cache:
            row = await self.bot.db.fetchone(
                "SELECT enabled FROM user_immunity_settings WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            self.immunity_overrides_cache[key] = (
                bool(int(row["enabled"])) if row is not None else None
            )
        return self.immunity_overrides_cache[key]

    async def get_ignored_channels_cached(self, guild_id: int) -> set[int]:
        if guild_id not in self.ignored_channels_cache:
            fetchall = getattr(self.bot.db, "fetchall", None)
            rows = (
                await fetchall(
                    "SELECT channel_id FROM ignored_channels WHERE guild_id = ?",
                    (guild_id,),
                )
                if callable(fetchall)
                else []
            )
            self.ignored_channels_cache[guild_id] = {int(r["channel_id"]) for r in rows}
        return self.ignored_channels_cache[guild_id]

    @staticmethod
    def _canonical_security_filter(filter_name: str) -> str:
        key = str(filter_name or "").strip().casefold().replace("-", "_")
        return SECURITY_FILTER_POLICY_ALIASES.get(key, key)

    @staticmethod
    def _message_scope_ids(message: discord.Message) -> set[int]:
        """IDs du salon courant + parent d'un thread, sans inventer de ressource."""
        def _id(value: object) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        ids: set[int] = set()
        channel_id = _id(getattr(message.channel, "id", 0))
        parent_id = _id(getattr(message.channel, "parent_id", 0))
        if channel_id:
            ids.add(channel_id)
        if parent_id:
            ids.add(parent_id)
        return ids

    def invalidate_security_filter_policy(self, guild_id: int, filter_name: str | None = None) -> None:
        guild_id = int(guild_id)
        if filter_name is None:
            for key in [key for key in self.security_filter_policy_cache if key[0] == guild_id]:
                self.security_filter_policy_cache.pop(key, None)
            self.antispam_policy_cache.pop(guild_id, None)
            return
        canonical = self._canonical_security_filter(filter_name)
        self.security_filter_policy_cache.pop((guild_id, canonical), None)
        if canonical == "antispam":
            self.antispam_policy_cache.pop(guild_id, None)

    async def get_security_filter_policy_cached(
        self,
        guild_id: int,
        filter_name: str,
    ) -> dict[str, set[int]]:
        canonical = self._canonical_security_filter(filter_name)
        if canonical not in SECURITY_FILTER_POLICY_KEYS:
            return {"role_ids": set(), "member_ids": set(), "strict_channel_ids": set()}

        key = (int(guild_id), canonical)
        cached = self.security_filter_policy_cache.get(key)
        if cached is not None:
            return cached

        reader = getattr(self.bot.db, "get_security_filter_policy", None)
        if callable(reader):
            raw = await reader(int(guild_id), canonical)
            role_ids = {int(value) for value in (raw.get("role_ids") or [])}
            member_ids = {int(value) for value in (raw.get("member_ids") or [])}
            strict_channel_ids = {
                int(value) for value in (raw.get("strict_channel_ids") or [])
            }
        else:
            # Compatibilité avec les doubles de test et un éventuel runtime ancien
            # pendant un rolling deploy : sans API générique disponible, la politique
            # est vide plutôt que de casser tout le moteur AutoMod.
            fetchall = getattr(self.bot.db, "fetchall", None)
            if callable(fetchall):
                role_rows = await fetchall(
                    "SELECT role_id FROM security_filter_bypass_roles "
                    "WHERE guild_id=? AND filter_name=?",
                    (int(guild_id), canonical),
                )
                member_rows = await fetchall(
                    "SELECT user_id FROM security_filter_bypass_members "
                    "WHERE guild_id=? AND filter_name=?",
                    (int(guild_id), canonical),
                )
                channel_rows = await fetchall(
                    "SELECT channel_id FROM security_filter_strict_channels "
                    "WHERE guild_id=? AND filter_name=?",
                    (int(guild_id), canonical),
                )
                role_ids = {int(row["role_id"]) for row in role_rows}
                member_ids = {int(row["user_id"]) for row in member_rows}
                strict_channel_ids = {int(row["channel_id"]) for row in channel_rows}
            else:
                role_ids = set()
                member_ids = set()
                strict_channel_ids = set()

        policy = {
            "role_ids": role_ids,
            "member_ids": member_ids,
            "strict_channel_ids": strict_channel_ids,
        }
        self.security_filter_policy_cache[key] = policy
        return policy

    async def security_filter_applies_to(
        self,
        message: discord.Message,
        filter_name: str,
    ) -> bool:
        """Décide si UN filtre doit s'appliquer à ce message.

        Priorité :
        1. Administrateur / Gérer le serveur => bypass de tous les filtres de messages ;
        2. immunité personnelle ON / propriétaire par défaut ;
        3. bypass explicite de ce filtre (membre ou rôle) ;
        4. rôle AutoMod global exempté (sauf immunité personnelle OFF) ;
        5. salon strict : protection appliquée à tous les autres membres ;
        6. salon ignoré : protection ignorée, hors salon strict ;
        7. comportement normal.

        Un salon strict renforce la modération des membres ordinaires, sans annuler
        les exceptions configurées par l'administrateur. Les threads héritent du
        salon parent. Un override personnel OFF neutralise l'immunité historique
        mais pas un bypass de filtre enregistré explicitement.
        """
        canonical = self._canonical_security_filter(filter_name)
        if canonical not in SECURITY_FILTER_POLICY_KEYS:
            return True

        # Exemption prioritaire pour les vrais administrateurs et les rôles
        # all-perms. Elle prime sur les salons stricts et les overrides, mais
        # ne désactive AUCUNE protection globale de sécurité du serveur.
        member = _as_member(message.author, message.guild)
        if _is_discord_administrator(member):
            return False

        policy = await self.get_security_filter_policy_cached(message.guild.id, canonical)
        scope_ids = self._message_scope_ids(message)
        strict = bool(scope_ids & policy["strict_channel_ids"])

        if not isinstance(member, discord.Member):
            return True

        override = await self.get_immunity_override_cached(member.guild.id, member.id)
        if override is True:
            return False
        if override is None and (
            member.id == member.guild.owner_id or member.id in config.OWNER_IDS
        ):
            return False

        # Les exemptions choisies dans le Dashboard priment TOUJOURS sur le
        # salon strict. Sinon « membre/rôle autorisé à contourner » était trompeur
        # et un modérateur pouvait encore être sanctionné dans #modo-chat.
        if member.id in policy.get("member_ids", set()):
            return False
        if policy["role_ids"] and any(
            role.id in policy["role_ids"] for role in member.roles
        ):
            return False

        # Les rôles AutoMod globalement exemptés sont aussi de vraies
        # exceptions, sauf si le membre a désactivé son immunité via override OFF.
        if override is None:
            exempt_ids = await self.get_exempt_roles_cached(member.guild.id)
            if exempt_ids and any(role.id in exempt_ids for role in member.roles):
                return False

        # Le mode strict conserve sa priorité sur « ignorer ce salon » pour
        # les membres NON exemptés, y compris dans les threads du salon parent.
        if strict:
            return True

        ignored = await self.get_ignored_channels_cached(member.guild.id)
        if scope_ids & ignored:
            return False
        return True

    async def get_antispam_policy_cached(self, guild_id: int) -> dict[str, object]:
        """Compatibilité V1 : l'anti-spam est désormais une politique générique."""
        policy = await self.get_security_filter_policy_cached(guild_id, "antispam")
        return {
            "scope_mode": "all",
            "role_ids": set(policy["role_ids"]),
            "channel_ids": set(policy["strict_channel_ids"]),
            "strict_channel_ids": set(policy["strict_channel_ids"]),
        }

    async def antispam_applies_to(self, message: discord.Message) -> bool:
        return await self.security_filter_applies_to(message, "antispam")

    async def is_automod_exempt(self, member: discord.abc.User) -> bool:
        """Détermine l'immunité AutoMod avec un override personnel explicite."""
        if not isinstance(member, discord.Member):
            return False
        if _is_discord_administrator(member):
            return True

        override = await self.get_immunity_override_cached(member.guild.id, member.id)
        if override is not None:
            return override

        if member.id == member.guild.owner_id or member.id in config.OWNER_IDS:
            return True
        exempt_ids = await self.get_exempt_roles_cached(member.guild.id)
        if exempt_ids and any(r.id in exempt_ids for r in member.roles):
            return True
        return False

    async def _next_spam_stage(self, guild_id: int, user_id: int) -> int:
        await self.bot.db.execute(SPAM_ESCALATION_SCHEMA)
        now = int(time.time())
        row = await self.bot.db.fetchone(
            "SELECT stage,updated_at FROM sentrix_spam_escalation WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(user_id)),
        )
        previous_stage = int(row["stage"] or 0) if row else 0
        updated_at = int(row["updated_at"] or 0) if row else 0
        if not updated_at or now - updated_at > SPAM_ESCALATION_RESET_SECONDS:
            previous_stage = 0
        stage = previous_stage + 1
        await self.bot.db.execute(
            "INSERT INTO sentrix_spam_escalation (guild_id,user_id,stage,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET stage=excluded.stage,updated_at=excluded.updated_at",
            (int(guild_id), int(user_id), int(stage), now),
        )
        return stage

    async def _spam_progressive_action(
        self,
        guild: discord.Guild,
        member: discord.Member,
        reason: str,
    ) -> tuple[str | None, int, int | None, str]:
        """Rappel -> warn -> timeout 10m, 30m, 1h, 3h, 6h, 12h, 24h."""
        stage = await self._next_spam_stage(guild.id, member.id)

        if stage == 1:
            return (
                "warning_ping",
                stage,
                None,
                "⚠️ merci d'arrêter le spam. En cas de récidive, vous recevrez un avertissement.",
            )

        if stage == 2:
            actor = guild.me
            if actor is None:
                return (
                    "warn",
                    stage,
                    None,
                    "⚠️ avertissement : spam répété. Prochaine récidive : mute 10 minutes.",
                )
            try:
                conf = await self.bot.db.get_guild_config(guild.id)
                warn_role_id = conf["warn_role"] if conf else None
                warn_role = guild.get_role(int(warn_role_id)) if warn_role_id else None
            except Exception:
                warn_role = None
            outcome = await moderation_service.warn(
                self.bot,
                guild=guild,
                actor=actor,
                target=member,
                reason=f"AutoMod : spam répété — {reason}",
                dm_text=(
                    f"Vous avez reçu un avertissement automatique sur {guild.name} pour spam répété. "
                    "Une nouvelle récidive entraînera un mute de 10 minutes."
                ),
                warn_role=warn_role,
                ban_threshold=0,
            )
            if outcome.executed:
                return (
                    "warn",
                    stage,
                    None,
                    "⚠️ avertissement enregistré pour spam répété. Prochaine récidive : mute 10 minutes.",
                )
            return (
                "warn",
                stage,
                None,
                "⚠️ spam répété détecté. SentriX n’a pas pu enregistrer le warn, mais la prochaine récidive entraînera un mute.",
            )

        duration = SPAM_MUTE_DURATIONS_SECONDS[
            min(stage - 3, len(SPAM_MUTE_DURATIONS_SECONDS) - 1)
        ]
        me = guild.me
        if (
            me is None
            or not me.guild_permissions.moderate_members
            or member.id == guild.owner_id
            or member.top_role >= me.top_role
        ):
            return (
                "mute_failed",
                stage,
                duration,
                f"⚠️ spam répété détecté. Timeout prévu : {helpers.format_duration(duration)}, "
                "mais SentriX n’a pas la permission ou la hiérarchie nécessaire.",
            )

        until = discord.utils.utcnow() + timedelta(seconds=duration)
        current_timeout = member.timed_out_until
        try:
            if not current_timeout or current_timeout < until:
                log_service.mark_sanction(guild.id, member.id, "timeout")
                await member.timeout(
                    until,
                    reason=f"AutoMod : récidive spam niveau {stage} — {reason}",
                )
        except (discord.Forbidden, discord.HTTPException):
            return (
                "mute_failed",
                stage,
                duration,
                f"⚠️ spam répété détecté. Timeout prévu : {helpers.format_duration(duration)}, "
                "mais Discord a refusé la sanction.",
            )

        return (
            "mute",
            stage,
            duration,
            f"🔇 spam répété : mute de {helpers.format_duration(duration)}.",
        )

    async def _maybe_escalate(self, guild: discord.Guild, member: discord.Member, reason: str) -> tuple[str | None, int]:
        """Enregistre une infraction pour ce membre et, si le nombre d'infractions récentes
        dépasse un des seuils d'ESCALATION_RULES, applique automatiquement une sanction plus
        sévère (mute → kick → ban). Retourne (action_prise_ou_None, nombre_d_infractions)."""
        key = (guild.id, member.id)
        count = self.infraction_tracker.ajouter(key)

        conf = await self.get_automod_cached(guild.id)
        if not conf.get("escalation", 0):
            return None, count

        action_to_take = None
        for threshold, action in ESCALATION_RULES:
            if count >= threshold:
                action_to_take = action
                break  # ESCALATION_RULES est trié du seuil le plus haut au plus bas

        if action_to_take is None:
            return None, count
        if member.id == guild.owner_id:
            return None, count  # le propriétaire du serveur n'est jamais sanctionné
        if member.top_role >= guild.me.top_role:
            # Hors de portée des sanctions Discord, mais plus hors de vue.
            return await self._repondre_abus_privilegie(guild, member, reason, count), count

        try:
            # La carte d'incident AutoMod est le seul log : pas de doublon « Timeout appliqué ».
            log_service.mark_sanction(guild.id, member.id, {"mute": "timeout", "kick": "kick", "ban": "ban"}[action_to_take])
            if action_to_take == "mute":
                until = discord.utils.utcnow() + timedelta(seconds=MUTE_ESCALATION_SECONDS)
                await member.timeout(until, reason=f"AutoMod : escalade ({count} infractions/1h) — {reason}")
            elif action_to_take == "kick":
                await member.kick(reason=f"AutoMod : escalade ({count} infractions/1h) — {reason}")
            elif action_to_take == "ban":
                await member.ban(reason=f"AutoMod : escalade ({count} infractions/1h) — {reason}", delete_message_seconds=0)
            self.infraction_tracker.reinitialiser(key)  # repart à zéro après une sanction
            return action_to_take, count
        except discord.Forbidden:
            return None, count

    async def _repondre_abus_privilegie(
        self, guild: discord.Guild, member: discord.Member, reason: str, count: int
    ) -> str | None:
        """Répond à un membre hors de portée des sanctions Discord.

        Discord refuse timeout, kick et ban sur un membre dont le rôle le plus
        haut dépasse celui du bot. Le retrait de rôle, lui, suit une autre
        règle : il suffit que le rôle visé soit sous celui du bot. SentriX peut
        donc désarmer un staff qui le dépasse, à condition que le rôle à retirer
        soit sous le sien.

        Une bêtise isolée ne déclenche rien : seul le seuil le plus haut compte
        comme abus avéré. Au-delà, le propriétaire est prévenu dans tous les
        cas — y compris quand rien n'a pu être retiré, ce qui est précisément
        l'information qui manquait.
        """
        if count < ABUS_PRIVILEGIE_SEUIL:
            return None

        moi = guild.me
        retires: list[discord.Role] = []
        bloques: list[discord.Role] = []
        if moi is not None and moi.guild_permissions.manage_roles:
            for role in member.roles:
                if role == guild.default_role or role.managed:
                    continue
                if not any(getattr(role.permissions, perm, False) for perm in DANGEROUS_PERMS):
                    continue
                (retires if role < moi.top_role else bloques).append(role)
            if retires:
                try:
                    await member.remove_roles(
                        *retires,
                        reason=f"AutoMod : abus confirmé ({count} infractions/1h) — {reason}",
                    )
                except discord.Forbidden:
                    bloques.extend(retires)
                    retires = []
                except discord.HTTPException:
                    logger.warning(
                        "Retrait des rôles à risque impossible sur guild=%s membre=%s.",
                        guild.id, member.id, exc_info=True,
                    )
                    bloques.extend(retires)
                    retires = []

        if retires:
            action = "rôles à risque retirés : " + ", ".join(r.name for r in retires)
        elif bloques:
            action = (
                "aucun rôle retiré — ses rôles à risque sont au-dessus de celui de SentriX "
                "(" + ", ".join(r.name for r in bloques) + "). "
                "Remontez le rôle de SentriX au-dessus pour qu'il puisse agir."
            )
        else:
            action = (
                "aucun rôle à risque trouvé sous celui de SentriX, et les sanctions Discord "
                "(exclusion, expulsion, bannissement) sont refusées sur un membre qui le dépasse."
            )

        carte = embeds.log_entry(
            "🚨 ABUS D'UN MEMBRE PRIVILÉGIÉ", config.COLOR_ERROR,
            cible=member, cible_label="👤 Membre concerné",
            raison=reason,
            extra={
                "⚔️ Action prise": action,
                "📊 Infractions": f"{count} en 1 h (seuil d'abus : {ABUS_PRIVILEGIE_SEUIL})",
                "🔗 ID": f"`{member.id}`",
            },
        )
        await self.log_action(guild, carte)
        try:
            proprietaire = guild.owner or await guild.fetch_member(guild.owner_id)
            if proprietaire:
                await panels.envoyer(proprietaire, panels.depuis_embed(carte))
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass

        if retires:
            self.infraction_tracker.reinitialiser((guild.id, member.id))
            return "derank"
        return None

    async def toggle(self, ctx: commands.Context, field: str, etat: str):
        value = 1 if etat == "on" else 0
        await self.bot.db.set_automod(ctx.guild.id, field, value)
        self.automod_cache.pop(ctx.guild.id, None)
        state_text = "ACTIF" if value else "INACTIF"
        label = "L'escalade automatique" if field == "escalation" else f"Le filtre **{AUTOMOD_TOGGLE_LABELS.get(field, field)}**"
        if field in {"antilink", "antilink_strict"} and value:
            label = "Le filtre **Anti-liens (blocage total + Discord AutoMod)**"
        message = f'{label} est maintenant {state_text}.'
        if field == "escalation":
            # Politique de cogs/content_filter_policy : les filtres de contenu ne
            # sanctionnent jamais seuls. Le réglage ne doit pas promettre l'inverse.
            # Vérifié dans les journaux de production le 2026-10-14 :
            # cogs/content_filter_policy est bien chargé (« Politique contenu
            # activée ») et remplace _maybe_escalate. Les filtres de contenu ne
            # sanctionnent donc réellement pas. Seule exception, ci-dessous.
            message += ("\nLes récidives sont comptées sur une heure glissante ; les filtres de "
                        "contenu suppriment le message sans exclure, expulser ni bannir. "
                        f"Une seule exception : au-delà de {ABUS_PRIVILEGIE_SEUIL} infractions en 1 h, "
                        "un membre dont le rôle dépasse celui de SentriX — donc intouchable par les "
                        "sanctions Discord — se voit retirer ses rôles à risque situés sous celui de "
                        "SentriX, et le propriétaire du serveur est prévenu dans tous les cas.")
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(message)))

    # ---------------------------------------------------------------- TOGGLES (10 commandes explicites)

    @commands.hybrid_command(name="antispam", description="Activer/désactiver la protection anti-spam.")
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antispam(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antispam", etat)

    @commands.hybrid_command(name="antilink", description="Bloquer tous les liens via SentriX + Discord AutoMod.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antilink(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antilink", etat)

    @commands.hybrid_command(
        name="antilink-strict",
        description="Alias de l'anti-liens total SentriX + Discord AutoMod.",
        with_app_command=False,
    )
    @app_commands.describe(etat="Activer ou désactiver le mode strict")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antilink_strict(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antilink_strict", etat)

    @commands.hybrid_command(name="antiinvite", description="Activer/désactiver le blocage des invitations Discord.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiinvite(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiinvite", etat)

    @commands.hybrid_command(name="antimention", description="Activer/désactiver la protection anti-mention massive.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antimention(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antimention", etat)

    @commands.hybrid_command(name="anticaps", description="Activer/désactiver le filtre anti-majuscules.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def anticaps(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "anticaps", etat)

    @commands.hybrid_command(name="antiemoji", description="Activer/désactiver le filtre anti-spam d'émojis.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiemoji(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiemoji", etat)

    @commands.hybrid_command(name="antiraid", description="Activer/désactiver la protection anti-raid.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiraid(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiraid", etat)

    @commands.hybrid_command(name="antibot", description="Activer/désactiver le blocage automatique des bots non autorisés.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antibot(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antibot", etat)

    @commands.hybrid_command(name="antiaccount", description="Activer/désactiver le filtre anti-comptes récents.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiaccount(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiaccount", etat)

    @commands.hybrid_command(name="antiscam", description="Activer/désactiver la détection de liens/messages d'arnaque.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antiscam(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiscam", etat)

    @commands.hybrid_command(name="antinuke", description="Activer/désactiver la protection anti-nuke (compte compromis).")
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def antinuke(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antinuke", etat)

    @commands.hybrid_command(name="vanity-guard", aliases=["protection-lien-perso"],
                             description="Empêcher le vol du lien personnalisé du serveur (discord.gg/votre-nom).",
                             with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def vanity_guard(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "security_vanity", etat)

    @commands.hybrid_command(name="prune-guard", aliases=["anti-purge-membres"],
                             description="Alerter quand quelqu'un expulse massivement des membres inactifs.",
                             with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def prune_guard(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "security_prune", etat)

    @commands.hybrid_command(name="permission-guard", aliases=["surveiller-permissions"],
                             description="Surveiller l'attribution de permissions dangereuses (Administrateur, Bannir…).",
                             with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def permission_guard(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "security_permissions", etat)

    @commands.hybrid_command(name="join-gate", aliases=["filtre-arrivees"],
                             description="Filtrer les arrivées suspectes : comptes récents, sans avatar, vagues d'inscriptions.",
                             with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def join_gate(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "join_gate", etat)

    @commands.hybrid_command(name="risk-engine", aliases=["score-de-risque"],
                             description="Noter chaque membre selon son comportement pour repérer les comptes à risque.",
                             with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def risk_engine(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "risk_engine", etat)

    # Le paramètre s'appelle `membre` et non `bot`, comme la commande voisine
    # +antinuke-whitelist-add. Ce n'est pas cosmétique : les gates V18
    # (tools/command_integrity_v18_gate, tools/audit_registre) refusent tout
    # paramètre dont le nom est dans {self, ctx, context, interaction, bot,
    # _bot}, parce qu'un paramètre ainsi nommé est normalement l'instance du
    # bot, jamais un argument d'utilisateur. Les deux commandes antibot
    # laissaient donc deux portes rouges en permanence.
    #
    # Mesuré avant de renommer, pour ne pas confondre faux positif et vraie
    # régression : après le boot complet, la signature restait
    # `(self, ctx, bot: discord.Member)` — aucune couche n'injectait l'instance
    # du bot dans ce paramètre, et la commande fonctionnait. C'était donc bien
    # un faux positif de nom, pas un bug. La preuve que les gates ne se
    # trompent pas toujours : +wipe-server, lui, avait de vrais paramètres
    # internes, et la couche de réparation les a bel et bien retirés
    # (clean_params vide après le boot).
    #
    # Le renommage est sans risque côté membres : les deux commandes sont en
    # with_app_command=False, donc aucune surface slash où le nom s'afficherait,
    # et en préfixé seul l'ordre des arguments compte.
    @commands.hybrid_command(name="antibot-allow", description="Autoriser un bot approuvé malgré l'anti-bot.", with_app_command=False)
    @app_commands.describe(membre="Le bot approuvé à autoriser")
    @checks.is_owner_or_admin_for("securite")
    async def antibot_allow(self, ctx: commands.Context, membre: discord.Member):
        if not membre.bot:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"{membre.mention} n'est pas un bot. Cette commande autorise un **bot** à rejoindre le serveur malgré l'anti-bot.")))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO automod_bot_allowlist (guild_id, bot_id, added_by, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id, membre.id, ctx.author.id, int(time.time())),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"{membre.mention} est autorisé par l'anti-bot SentriX.")))

    @commands.hybrid_command(name="antibot-deny", description="Retirer un bot de l'allowlist anti-bot.", with_app_command=False)
    @app_commands.describe(membre="Le bot à retirer de l'allowlist")
    @checks.is_owner_or_admin_for("securite")
    async def antibot_deny(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM automod_bot_allowlist WHERE guild_id = ? AND bot_id = ?",
            (ctx.guild.id, membre.id),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"{membre.mention} n'est plus dans l'allowlist anti-bot.")))

    @commands.hybrid_command(name="antinuke-whitelist-add", description="Exempter un membre de confiance de l'anti-nuke.", with_app_command=False)
    @app_commands.describe(membre="Le membre à exempter")
    @checks.is_owner_or_admin_for("securite")
    async def antinuke_whitelist_add(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, membre.id)
        )
        from cogs.setup_v2_core import invalidate_trusted_cache
        invalidate_trusted_cache(ctx.guild.id, membre.id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"{membre.mention} est maintenant exempté de l'anti-nuke.")))

    @commands.hybrid_command(name="antinuke-whitelist-remove", description="Retirer un membre de la liste blanche anti-nuke.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def antinuke_whitelist_remove(self, ctx: commands.Context, membre: discord.Member):
        # Les DEUX tables. `_antinuke_allowed` accorde l'accès si l'une OU
        # l'autre correspond : ne vider que `antinuke_whitelist` affichait
        # « a été retiré de la liste blanche » alors que la personne restait
        # autorisée par `v17_antinuke_whitelist`, posée par +nukewhitelist.
        # Une révocation qui annonce un succès sans révoquer est pire que pas
        # de révocation du tout : l'administrateur croit la trappe fermée.
        #
        # Retirer est le sens SÛR — ça resserre, jamais ça n'ouvre — donc
        # nettoyer les deux ne peut pas créer d'accès.
        await self.bot.db.execute(
            "DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await self.bot.db.execute(
            "DELETE FROM v17_antinuke_whitelist WHERE guild_id = ? AND subject_type = 'user' AND subject_id = ?",
            (ctx.guild.id, membre.id),
        )
        from cogs.setup_v2_core import invalidate_trusted_cache
        invalidate_trusted_cache(ctx.guild.id, membre.id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été retiré de la liste blanche anti-nuke.')))

    @commands.hybrid_command(name="antinuke-whitelist-list", description="Afficher les membres exemptés de l'anti-nuke.", with_app_command=False)
    @checks.is_owner_or_admin_for("securite")
    async def antinuke_whitelist_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM antinuke_whitelist WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun membre exempté (seul le propriétaire du serveur est protégé par défaut).')))
        lines = [f"<@{r['user_id']}>" for r in rows]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('🛡️ Liste blanche anti-nuke', '\n'.join(lines))))

    @commands.hybrid_command(name="lockdown-server", description="[Sécurité] Verrouiller tous les salons textuels du serveur.")
    @checks.is_owner_or_admin_for("securite")
    async def lockdown_server(self, ctx: commands.Context):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('🔒 Verrouillage de tous les salons en cours, merci de patienter...')))
        count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role, send_messages=False, reason=f"Verrouillage du serveur par {ctx.author}"
                )
                count += 1
            except discord.Forbidden:
                pass
        e = embeds.log_entry(
            "🔒 Verrouillage du serveur", config.COLOR_ERROR, acteur=ctx.author,
            acteur_label="🛠️ Verrouillé par", extra={"📊 Salons verrouillés": str(count)},
        )
        await self.log_action(ctx.guild, e)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🔒 {count} salon(s) verrouillé(s). Utilisez `/unlock-server` pour déverrouiller.')))

    @commands.hybrid_command(name="unlock-server", description="[Sécurité] Déverrouiller tous les salons textuels du serveur.")
    @checks.is_owner_or_admin_for("securite")
    async def unlock_server(self, ctx: commands.Context):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info('🔓 Déverrouillage en cours, merci de patienter...')))
        count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role, send_messages=None, reason=f"Déverrouillage du serveur par {ctx.author}"
                )
                count += 1
            except discord.Forbidden:
                pass
        e = embeds.log_entry(
            "🔓 Déverrouillage du serveur", config.COLOR_SUCCESS, acteur=ctx.author,
            acteur_label="🛠️ Déverrouillé par", extra={"📊 Salons déverrouillés": str(count)},
        )
        await self.log_action(ctx.guild, e)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🔓 {count} salon(s) déverrouillé(s).')))

    @commands.hybrid_command(name="automod-status", description="Afficher l'état de tous les filtres automod, avec les statistiques des dernières 24h.")
    @checks.is_owner_or_admin_for("securite")
    async def automod_status(self, ctx: commands.Context):
        conf = await self.bot.db.get_automod(ctx.guild.id)
        since_24h = int(time.time() - 86400)
        stats_rows = await self.bot.db.automod_stats_since(ctx.guild.id, since_24h)
        stats_by_filter = {r["filter_name"]: r["c"] for r in stats_rows}
        total_24h = sum(stats_by_filter.values())

        active = [
            label for field, label in AUTOMOD_TOGGLE_LABELS.items()
            if conf and conf[field]
        ]
        inactive = [
            label for field, label in AUTOMOD_TOGGLE_LABELS.items()
            if not conf or not conf[field]
        ]
        e = embeds.neutral(
            "État de l'AutoMod",
            f"{len(active)}/{len(AUTOMOD_TOGGLE_LABELS)} filtres configurés · "
            f"{total_24h} action(s) sur 24 h · "
            f"Escalade : {'active' if conf and conf['escalation'] else 'inactive'}",
        )
        e.add_field(
            name="Activés",
            value=", ".join(active)[:1024] or "Aucun filtre",
            inline=False,
        )
        e.add_field(
            name="Désactivés",
            value=", ".join(inactive)[:1024] or "Aucun",
            inline=False,
        )
        events = sorted(
            ((str(name), int(count)) for name, count in stats_by_filter.items() if count),
            key=lambda item: (-item[1], item[0]),
        )
        if events:
            labels = dict(AUTOMOD_TOGGLE_LABELS)
            e.add_field(
                name="Déclenchements (24 h)",
                value=" · ".join(
                    f"{labels.get(name, name)} : {count}" for name, count in events[:5]
                )[:1024],
                inline=False,
            )
        if not self.moderation_dataset.loaded:
            e.add_field(name="À vérifier", value="Le filtre multilingue n'a pas pu charger ses données.", inline=False)
        exempt_rows = await self.bot.db.list_automod_exempt_roles(ctx.guild.id)
        if exempt_rows:
            mentions = [f"<@&{r['role_id']}>" for r in exempt_rows]
            e.add_field(
                name="Rôles exemptés",
                value=", ".join(mentions[:5]) + (f" et {len(mentions) - 5} autre(s)" if len(mentions) > 5 else ""),
                inline=False,
            )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(
        name="automod-native-sync",
        description="Activer puis synchroniser les protections SentriX avec le vrai AutoMod Discord.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("securite")
    async def automod_native_sync(self, ctx: commands.Context):
        # Cette commande est volontairement opérationnelle, pas seulement diagnostique :
        # si aucune protection native n'est configurée sur ce serveur, elle active un
        # socle sûr et utile. L'utilisateur vient explicitement de demander la synchro.
        conf_before = await self.bot.db.get_automod(ctx.guild.id)
        word_rows = await self.bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id = ? LIMIT 1001",
            (ctx.guild.id,),
        )
        link_rows = await self.bot.db.fetchall(
            "SELECT value FROM blacklist_links WHERE guild_id = ? LIMIT 1001",
            (ctx.guild.id,),
        )

        had_native_config = bool(
            (conf_before and (
                conf_before["antilink"]
                or conf_before["antiinvite"]
                or conf_before["antiscam"]
                or conf_before["antimention"]
                or conf_before["antiinsult"]
            ))
            or word_rows
            or link_rows
        )

        auto_enabled: list[str] = []
        if not had_native_config:
            # Baseline recommandée : pas d'invention de blacklist personnalisée.
            # Anti-liens total absorbe déjà les invitations Discord.
            for field, label in (
                ("antilink", "Anti-liens total"),
                ("antiscam", "Anti-arnaque"),
                ("antimention", "Anti-mentions"),
                ("antiinsult", "Contenu sensible"),
            ):
                await self.bot.db.set_automod(ctx.guild.id, field, 1)
                auto_enabled.append(label)

        await self._sync_native_suite(ctx.guild)

        try:
            rules = await ctx.guild.fetch_automod_rules()
        except (discord.Forbidden, discord.HTTPException):
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.error(
                        "Discord refuse la lecture des règles AutoMod. Vérifiez que SentriX possède **Gérer le serveur**."
                    )
                ),
            )

        sentrix_rules = [r for r in rules if str(r.name).startswith("SentriX • ")]
        names = "\n".join(f"• {r.name}" for r in sentrix_rules) or "• Aucune règle native active sur ce serveur."

        conf = await self.bot.db.get_automod(ctx.guild.id)
        # Relire après activation automatique.
        word_rows = await self.bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id = ? LIMIT 1001",
            (ctx.guild.id,),
        )
        link_rows = await self.bot.db.fetchall(
            "SELECT value FROM blacklist_links WHERE guild_id = ? LIMIT 1001",
            (ctx.guild.id,),
        )

        enabled_labels: list[str] = []
        if conf:
            if conf["antilink"]:
                enabled_labels.append("Anti-liens total")
            elif conf["antiinvite"]:
                enabled_labels.append("Anti-invitations")
            if conf["antiscam"]:
                enabled_labels.append("Anti-arnaque")
            if conf["antimention"]:
                enabled_labels.append("Anti-mentions")
            if conf["antiinsult"]:
                enabled_labels.append("Contenu sensible")
        if word_rows:
            enabled_labels.append(f"Mots interdits ({len(word_rows)})")
        if link_rows:
            enabled_labels.append(f"Liens ciblés ({len(link_rows)})")

        local_state = ", ".join(enabled_labels) if enabled_labels else "Aucune protection native active."

        semaphore = asyncio.Semaphore(4)

        async def count_for_guild(guild: discord.Guild) -> int:
            async with semaphore:
                try:
                    guild_rules = await guild.fetch_automod_rules()
                except (discord.Forbidden, discord.HTTPException):
                    return 0
                return sum(
                    1 for rule in guild_rules
                    if str(getattr(rule, "name", "")).startswith("SentriX • ")
                )

        counts = await asyncio.gather(
            *(count_for_guild(guild) for guild in list(self.bot.guilds))
        )
        global_total = sum(counts)

        description_parts = [
            f"**Ce serveur : {len(sentrix_rules)} règle(s) native(s)**",
            names,
            "",
            f"**Protections actives :** {local_state}",
        ]
        if auto_enabled:
            description_parts.extend([
                "",
                "**Activées automatiquement par cette commande :** " + ", ".join(auto_enabled),
            ])
        description_parts.extend([
            "",
            f"**Total SentriX sur {len(self.bot.guilds)} serveur(s) : {global_total} règle(s) AutoMod native(s).**",
        ])

        if not sentrix_rules:
            me = ctx.guild.me
            manage_guild = bool(me and me.guild_permissions.manage_guild)
            description_parts.extend([
                "",
                "**Problème détecté :** les protections sont bien activées dans SentriX, "
                "mais Discord n'a créé aucune règle native.",
                "Le **0** n'est pas un échec de synchronisation en soi : il signifie "
                "qu'aucune règle native SentriX n'est actuellement visible sur ce serveur.",
                f"Permission **Gérer le serveur** pour SentriX : {'oui' if manage_guild else 'non'}.",
            ])

        logger.info(
            "AutoMod native sync command guild=%s local_rules=%s global_rules=%s auto_enabled=%s",
            ctx.guild.id,
            len(sentrix_rules),
            global_total,
            ",".join(auto_enabled) or "none",
        )

        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.success("\n".join(description_parts))),
        )

    @commands.hybrid_command(
        name="security-check",
        description="Diagnostiquer la configuration et les permissions du système de sécurité.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("securite")
    async def security_check(self, ctx: commands.Context):
        conf = await self.bot.db.get_automod(ctx.guild.id)
        me = ctx.guild.me
        perms = me.guild_permissions
        required = {
            "Gérer les messages": perms.manage_messages,
            "Voir les logs d'audit": perms.view_audit_log,
            "Exclure des membres": perms.kick_members,
            "Bannir des membres": perms.ban_members,
            "Modérer les membres": perms.moderate_members,
            "Gérer les rôles": perms.manage_roles,
            "Gérer les salons": perms.manage_channels,
        }
        configured = [
            label for field, label in AUTOMOD_TOGGLE_LABELS.items()
            if conf and conf[field]
        ]
        missing = [name for name, granted in required.items() if not granted]
        e = embeds.neutral(
            "Diagnostic de sécurité",
            f"{len(configured)} protection(s) configurée(s) · "
            f"{len(missing)} permission(s) manquante(s)",
        )
        e.add_field(
            name="Protections",
            value=", ".join(configured)[:1024] or "Aucune protection configurée",
            inline=False,
        )
        e.add_field(
            name="Permissions du bot",
            value=("Manquante : " + ", ".join(missing)) if missing else "Toutes accordées",
            inline=False,
        )

        # Jusqu'ici le diagnostic ne regardait que SentriX : ses protections et
        # ses permissions. Il disait si le bot peut travailler, jamais si le
        # serveur est exposé. Un serveur avec quatorze administrateurs et six
        # webhooks ouverts passait le diagnostic sans une remarque.
        try:
            from utils import security_advisory

            constats = [
                constat
                for constat in await security_advisory.analyser_complet(ctx.guild)
                # Déjà détaillé juste au-dessus, champ par champ.
                if constat.code != "permissions_bot"
            ]
            e.add_field(
                name="Exposition du serveur",
                value=security_advisory.resume(constats),
                inline=False,
            )
            for nom, valeur, inline in security_advisory.champs(constats, limite=2):
                e.add_field(name=nom, value=valeur, inline=inline)
        except Exception:
            logger.exception("Bulletin de sécurité indisponible guild=%s", ctx.guild.id)

        e.add_field(
            name="Test conseillé",
            value="Vérifiez les réglages dans +setup, puis testez avec un membre non staff.",
            inline=False,
        )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(
        name="immunity",
        aliases=["immunite"],
        description="Activer ou désactiver votre immunité personnelle SentriX.",
        with_app_command=False,
    )
    async def personal_immunity(self, ctx: commands.Context, etat: str = "status"):
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("Cette commande s’utilise dans un serveur.")),
            )

        allowed = ctx.author.id == ctx.guild.owner_id or await checks.is_verified_bot_owner(ctx)
        if not allowed:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.error("Seul le propriétaire du serveur ou le propriétaire vérifié de SentriX peut modifier sa propre immunité.")
                ),
            )

        normalized = _sans_accents(str(etat or "")).casefold().strip()
        key = (ctx.guild.id, ctx.author.id)
        if normalized in {"status", "statut", "etat"}:
            override = await self.get_immunity_override_cached(*key)
            enabled = True if override is None else override
            state = "active" if enabled else "désactivée"
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.info(f"Votre immunité SentriX est actuellement {state}.")),
            )

        if normalized in {"on", "active", "activer", "1", "oui"}:
            enabled = True
        elif normalized in {"off", "desactive", "desactiver", "0", "non"}:
            enabled = False
        else:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("Utilisez +immunity on ou +immunity off.")),
            )

        await self.bot.db.execute(
            """
            INSERT INTO user_immunity_settings (guild_id, user_id, enabled, updated_at)
            VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER))
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """,
            (ctx.guild.id, ctx.author.id, 1 if enabled else 0),
        )
        self.immunity_overrides_cache[key] = enabled

        if enabled:
            description = "Immunité SentriX activée. AutoMod vous ignore de nouveau selon les règles d’immunité habituelles."
        else:
            description = (
                "Immunité SentriX désactivée. AutoMod vous traite maintenant comme un membre normal : "
                "mots et liens interdits, spam et sanctions automatiques peuvent vous concerner. "
                "Les limites natives de Discord et la hiérarchie des rôles restent applicables."
            )

        await self.log_action(
            ctx.guild,
            embeds.log_entry(
                "Immunité personnelle SentriX modifiée",
                config.COLOR_WARNING if not enabled else config.COLOR_SUCCESS,
                cible=ctx.author,
                cible_label="Membre",
                raison="Immunité activée" if enabled else "Immunité désactivée",
            ),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(description)))
    @commands.hybrid_command(name="automod-escalation", description="Activer/désactiver l'escalade automatique des sanctions AutoMod.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver l'escalade")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin_for("securite")
    async def automod_escalation(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "escalation", etat)

    @commands.hybrid_command(name="automod-exempt-role-add", description="Exempter un rôle des filtres AutoMod (jamais sanctionné).", with_app_command=False)
    @app_commands.describe(role="Le rôle à exempter")
    @checks.is_owner_or_admin_for("securite")
    async def automod_exempt_role_add(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.add_automod_exempt_role(ctx.guild.id, role.id)
        self.exempt_roles_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Les membres avec le rôle {role.mention} ne seront plus jamais filtrés par AutoMod.')))

    @commands.hybrid_command(name="automod-exempt-role-remove", description="Retirer un rôle de la liste des rôles exemptés d'AutoMod.", with_app_command=False)
    @app_commands.describe(role="Le rôle à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def automod_exempt_role_remove(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.remove_automod_exempt_role(ctx.guild.id, role.id)
        self.exempt_roles_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Le rôle {role.mention} n'est plus exempté d'AutoMod.")))

    @commands.hybrid_command(name="automod-history", description="Afficher l'historique récent des actions AutoMod (globalement ou pour un membre).", with_app_command=False)
    @app_commands.describe(membre="Filtrer sur un membre précis (optionnel)")
    @checks.is_owner_or_admin_for("securite")
    async def automod_history(self, ctx: commands.Context, membre: discord.Member = None):
        if membre:
            rows = await self.bot.db.automod_history_for_user(ctx.guild.id, membre.id, limit=10)
            title = f"📜 Historique AutoMod — {membre.display_name}"
        else:
            rows = await self.bot.db.automod_recent(ctx.guild.id, limit=10)
            title = "📜 Historique AutoMod — Serveur"
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Aucune action AutoMod enregistrée pour l'instant.")))
        lines = []
        for r in rows:
            who = f"<@{r['user_id']}>" if r["user_id"] else "—"
            lines.append(f"<t:{r['timestamp']}:R> — {who} — `{r['filter_name']}` → **{r['action']}**\n╰ {r['reason']}")
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral(title, '\n\n'.join(lines))))

    @commands.hybrid_command(name="security-level", description="Définir le niveau de sécurité et la réactivité de l'anti-spam.")
    @app_commands.describe(
        niveau="Faible, Moyen, Élevé, ou Personnalisé pour choisir vos propres seuils anti-spam",
        messages=f"Personnalisé : messages avant intervention ({spam_sensitivity.MESSAGES_MIN} à {spam_sensitivity.MESSAGES_MAX})",
        secondes=f"Personnalisé : en combien de secondes ({spam_sensitivity.SECONDES_MIN} à {spam_sensitivity.SECONDES_MAX})",
    )
    @app_commands.choices(niveau=[
        app_commands.Choice(name="Faible", value="faible"),
        app_commands.Choice(name="Moyen", value="moyen"),
        app_commands.Choice(name="Élevé", value="eleve"),
        app_commands.Choice(name="Personnalisé", value="personnalise"),
    ])
    @checks.is_owner_or_admin_for("securite")
    async def security_level(
        self, ctx: commands.Context, niveau: str, messages: int | None = None, secondes: int | None = None,
    ):
        niveau = (niveau or "").strip().lower().replace("é", "e")
        if niveau in {"personnalise", "perso", "custom"}:
            # Les seuils choisis par le serveur ; les interrupteurs des filtres ne bougent pas.
            if messages is None or secondes is None:
                reglage = await spam_sensitivity.lire(self.bot, ctx.guild.id)
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(
                    f"Anti-spam actuel : **{reglage.seuils.phrase()}** (réactivité {reglage.niveau}). "
                    f"Pour choisir vos seuils : `+security-level personnalise <messages> <secondes>`, "
                    f"par exemple `+security-level personnalise 6 8`."
                )))
            seuils = await spam_sensitivity.personnaliser(
                self.bot, ctx.guild.id, messages, secondes, getattr(ctx.author, "id", None)
            )
            self._oublier_seuils(ctx.guild.id)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(
                f"Anti-spam personnalisé : SentriX intervient à partir de **{seuils.phrase()}**. "
                "Les filtres activés restent inchangés."
            )))
        if niveau not in SECURITY_PRESETS:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                "Niveau inconnu. Choisissez `faible`, `moyen`, `eleve` ou `personnalise`."
            )))
        await self.bot.db.set_guild_config(ctx.guild.id, "security_level", niveau)
        for field, value in SECURITY_PRESETS.get(niveau, {}).items():
            await self.bot.db.set_automod(ctx.guild.id, field, value)
        # Choisir un niveau remplace les seuils personnalisés éventuels.
        await spam_sensitivity.oublier_personnalisation(self.bot, ctx.guild.id)
        self._oublier_seuils(ctx.guild.id)
        self.automod_cache.pop(ctx.guild.id, None)
        reglage = await spam_sensitivity.lire(self.bot, ctx.guild.id)
        nom = {"faible": "Faible", "moyen": "Moyen", "eleve": "Élevé"}[niveau]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(
            f"Niveau de sécurité réglé sur **{nom}**. Les filtres associés ont été ajustés ; "
            f"l'anti-spam intervient à partir de **{reglage.seuils.phrase()}** (réactivité {reglage.niveau})."
        )))

    # ---------------------------------------------------------------- BLACKLIST MOTS

    @commands.hybrid_command(name="blacklist-add", description="Ajouter un mot à la liste noire.")
    @app_commands.describe(mot="Le mot ou l'expression à interdire")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_add(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)", (ctx.guild.id, mot.lower())
        )
        self.blacklist_words_cache.pop(ctx.guild.id, None)
        await self._sync_native_blacklist_rule(ctx.guild)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le mot `{mot}` a été ajouté à la liste noire.')))

    @commands.hybrid_command(name="blacklist-remove", description="Retirer un mot de la liste noire.", with_app_command=False)
    @app_commands.describe(mot="Le mot à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_remove(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, mot.lower())
        )
        self.blacklist_words_cache.pop(ctx.guild.id, None)
        await self._sync_native_blacklist_rule(ctx.guild)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le mot `{mot}` a été retiré de la liste noire.')))

    @commands.hybrid_command(name="blacklist-list", description="Afficher la liste des mots interdits.")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun mot interdit configuré.')))
        words = ", ".join(f"`{r['word']}`" for r in rows)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('🚫 Mots interdits', words)))

    # ---------------------------------------------------------------- BLACKLIST UTILISATEURS

    @commands.hybrid_command(name="blacklist-user", description="Ajouter un utilisateur à la liste noire du serveur.", with_app_command=False)
    @app_commands.describe(membre="Le membre à mettre en liste noire", raison="La raison")
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_user(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(err)))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist_users (guild_id, user_id, reason) VALUES (?, ?, ?)",
            (ctx.guild.id, membre.id, raison),
        )
        self.blacklist_users_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été ajouté à la liste noire.\nRaison : {raison}')))

    @commands.hybrid_command(name="unblacklist-user", description="Retirer un utilisateur de la liste noire.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer de la liste noire")
    @checks.is_owner_or_admin_for("securite")
    async def unblacklist_user(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM blacklist_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        self.blacklist_users_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été retiré de la liste noire.')))

    @commands.hybrid_command(name="blacklist-users", description="Afficher tous les utilisateurs en liste noire.", with_app_command=False)
    @checks.is_owner_or_admin_for("securite")
    async def blacklist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM blacklist_users WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun utilisateur en liste noire.')))
        e = embeds.neutral("🚫 Utilisateurs en liste noire")
        for row in rows[:20]:
            e.add_field(name=f"ID: {row['user_id']}", value=row["reason"] or "Aucune raison", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    # ---------------------------------------------------------------- WHITELIST DOMAINES

    @commands.hybrid_command(name="whitelist-domain", description="Autoriser un nom de domaine malgré l'antilink.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à autoriser (ex: youtube.com)")
    @checks.is_owner_or_admin_for("securite")
    async def whitelist_domain(self, ctx: commands.Context, domaine: str):
        domain = _canonical_whitelist_domain(domaine)
        if domain is None:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.warning("Domaine invalide. Entre uniquement un nom d'hôte, par exemple `youtube.com`, sans https://, chemin ni caractère *.")
                ),
            )
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO whitelist_domains (guild_id, domain) VALUES (?, ?)",
            (ctx.guild.id, domain),
        )
        self.whitelist_domains_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le domaine `{domain}` est maintenant autorisé.')))

    @commands.hybrid_command(name="unwhitelist-domain", description="Retirer un domaine de la liste blanche.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à retirer")
    @checks.is_owner_or_admin_for("securite")
    async def unwhitelist_domain(self, ctx: commands.Context, domaine: str):
        domain = _canonical_whitelist_domain(domaine)
        if domain is None:
            return await panels.envoyer(
                ctx, panels.depuis_embed(embeds.warning("Indiquez le nom du domaine à retirer (ex : `youtube.com`)."))
            )
        await self.bot.db.execute(
            "DELETE FROM whitelist_domains WHERE guild_id = ? AND domain = ?",
            (ctx.guild.id, domain),
        )
        self.whitelist_domains_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le domaine `{domain}` a été retiré de la liste blanche.')))

    # ---------------------------------------------------------------- ÉCOUTEURS

    # ---------------------------------------------------------- APPS EXTERNES
    #
    # Une application installée PAR UN UTILISATEUR (badge « APP ») publie la
    # réponse à sa commande au nom de l'application : message.author est un bot,
    # et le filtre « on ignore les bots » laissait passer les raids entiers
    # (@everyone/@here, invitations, liens) alors que toutes les protections
    # étaient actives. Le vrai responsable est le membre qui a lancé la commande
    # (interaction_metadata.user) : c'est lui que SentriX sanctionne.

    def _external_app_invoker(self, message: discord.Message):
        meta = getattr(message, "interaction_metadata", None)
        if meta is None or not message.guild:
            return None
        try:
            user_integration = bool(meta.is_user_integration())
        except Exception:
            user_integration = False
        if not user_integration:
            return None  # bot installé sur le serveur : sous le contrôle des admins
        user = getattr(meta, "user", None)
        if user is None:
            return None
        return message.guild.get_member(user.id) or user

    @staticmethod
    def _external_app_text(message: discord.Message) -> str:
        parts = [message.content or ""]
        for embed in getattr(message, "embeds", None) or ():
            parts.extend(str(x or "") for x in (embed.title, embed.description, embed.url))
            parts.extend(f"{f.name} {f.value}" for f in getattr(embed, "fields", None) or ())
        return "\n".join(parts)

    def _external_app_reason(self, message: discord.Message, conf: dict) -> str | None:
        text = self._external_app_text(message)
        lowered = text.casefold()
        link_text = _normalize_link_text(text)
        if (conf.get("antimention") or conf.get("antiraid") or conf.get("antispam")) and (
            message.mention_everyone or "@everyone" in lowered or "@here" in lowered
            or len(getattr(message, "role_mentions", ()) or ()) >= 3
        ):
            return "Mention @everyone/@here envoyée par une application externe."
        if (conf.get("antiinvite") or conf.get("antiraid") or conf.get("antilink")) and (
            INVITE_RE.search(link_text) or INVITE_RE.search(_recoller_hotes_invitation(text_normalization.normaliser(text)))
        ):
            return "Invitation Discord envoyée par une application externe."
        if conf.get("antilink") and LINK_RE.search(link_text):
            return "Lien envoyé par une application externe."
        key = (message.guild.id, message.interaction_metadata.user.id)
        bursts = self._external_app_bursts.setdefault(key, [])
        now = time.monotonic()
        bursts[:] = [t for t in bursts if now - t < EXTERNAL_APP_BURST_WINDOW]
        bursts.append(now)
        if (conf.get("antispam") or conf.get("antiraid")) and len(bursts) >= EXTERNAL_APP_BURST_COUNT:
            return "Rafale de messages d'application externe."
        return None

    async def _lock_external_apps(self, guild: discord.Guild, reason: str) -> bool:
        """Retire « Utiliser des applications externes » à @everyone : coupe le raid à la source."""
        everyone = guild.default_role
        me = guild.me
        if not getattr(everyone.permissions, "use_external_apps", False):
            return False
        if me is None or not me.guild_permissions.manage_roles:
            return False
        permissions = discord.Permissions(everyone.permissions.value)
        permissions.use_external_apps = False
        try:
            await everyone.edit(permissions=permissions, reason=f"SentriX anti-raid : {reason}")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Verrou des applications externes impossible guild=%s", guild.id, exc_info=True)
            return False
        return True

    async def _handle_external_app_message(self, message: discord.Message) -> bool:
        invoker = self._external_app_invoker(message)
        if invoker is None:
            return False
        conf = await self.get_automod_cached(message.guild.id)
        if not conf:
            return False
        if isinstance(invoker, discord.Member) and (
            _is_discord_administrator(invoker) or await self.is_automod_exempt(invoker)
        ):
            return False
        reason = self._external_app_reason(message, conf)
        if reason is None:
            return False
        self._mark_xp_skip(message.id)
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Message d'application externe non supprimé guild=%s", message.guild.id, exc_info=True)

        guild = message.guild
        key = (guild.id, invoker.id)
        now = time.monotonic()
        if now - self._external_app_sanctioned.get(key, -9999.0) < EXTERNAL_APP_BURST_WINDOW * 6:
            return True  # même raid : un seul timeout, une seule carte
        self._external_app_sanctioned[key] = now

        action = "message supprimé"
        if isinstance(invoker, discord.Member) and guild.me and guild.me.guild_permissions.moderate_members:
            try:
                await invoker.timeout(
                    discord.utils.utcnow() + timedelta(seconds=EXTERNAL_APP_TIMEOUT_SECONDS),
                    reason=f"SentriX anti-raid : {reason}",
                )
                action = f"exclu {helpers.format_duration(EXTERNAL_APP_TIMEOUT_SECONDS)}"
            except (discord.Forbidden, discord.HTTPException):
                action = "message supprimé (exclusion refusée par Discord : rôle trop haut)"
        locked = False
        if conf.get("antiraid"):
            locked = await self._lock_external_apps(guild, reason)

        app = message.author
        embed = embeds.log_entry(
            "🛡️ Raid par application externe bloqué",
            config.COLOR_WARNING,
            cible=invoker,
            cible_label="👤 Lancé par",
            extra={
                "🤖 Application": f"{getattr(app, 'name', 'Application')} (`{getattr(app, 'id', '?')}`)",
                "📍 Salon": message.channel.mention,
                "⚖️ Sanction": action,
                "🔒 Applications externes": (
                    "désactivées pour @everyone (réactivez-les dans Paramètres du serveur → Rôles → @everyone)"
                    if locked else "inchangées"
                ),
            },
            raison=reason,
        )
        try:
            await self.log_action(guild, embed)
        except Exception:
            logger.exception("Log anti-raid application externe impossible guild=%s", guild.id)
        try:
            await self.bot.db.log_automod_action(guild.id, invoker.id, "external_app", action, reason)
        except Exception:
            logger.debug("Historique AutoMod application externe non écrit", exc_info=True)
        return True

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # Discord émet aussi une modification quand il ajoute l'aperçu d'un lien :
        # seul un CHANGEMENT de texte est filtré.
        if not after.guild or getattr(after.author, "bot", False):
            return
        if (before.content or "") == (after.content or ""):
            return
        try:
            await self.on_message(_MessageModifie(after, after.author, after.content or ""))
        except Exception:
            logger.exception("Filtrage d'un message modifié impossible guild=%s", after.guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild and message.author.bot:
            if getattr(message, "webhook_id", None):
                # Raid Protect (opt-in) : un webhook qui inonde un salon.
                try:
                    from cogs import raid_protect

                    if await raid_protect.surveiller_webhook(self.bot, message):
                        return
                except Exception:
                    logger.exception("Garde des webhooks en échec guild=%s", message.guild.id)
            try:
                if await self._handle_external_app_message(message):
                    return
                invoker = self._external_app_invoker(message)
                if isinstance(invoker, discord.Member):
                    # Pas de raid évident : le message suit TOUS les filtres
                    # (arnaques, mots interdits, insultes, spam, majuscules…),
                    # sanctions progressives comprises, au nom du membre lanceur.
                    proxy = _MessageDApplication(message, invoker, self._external_app_text(message))
                    await self.on_message(proxy)
                    hardening = self.bot.get_cog("SecurityHardening")
                    if hardening is not None:
                        await hardening.on_message(proxy)
            except Exception:
                logger.exception("Contrôle d'application externe en échec guild=%s", message.guild.id)
            return
        if message.author.bot or not message.guild:
            return
        # Le bypass admin s'applique AVANT la blacklist, le spam, l'anti-arnaque,
        # les insultes et toute détection qui pourrait supprimer un message.
        if _is_discord_administrator(_as_member(message.author, message.guild)):
            # Prouve que le message de l'administrateur est bien arrivé au bot.
            # Si Discord l'intercepte auparavant, seul on_automod_action apparaît.
            if LINK_RE.search(_normalize_link_text(message.content)):
                key = (message.guild.id, message.author.id)
                now = time.monotonic()
                if now - self._admin_link_last_seen.get(key, -9999.0) >= 60:
                    if len(self._admin_link_last_seen) > 2000:
                        self._admin_link_last_seen.clear()
                    self._admin_link_last_seen[key] = now
                    logger.info(
                        "SENTRIX_LINK_BYPASS=staff guild=%s user=%s channel=%s",
                        message.guild.id, message.author.id, message.channel.id,
                    )
            return

        content_lower = message.content.lower()
        link_content = _normalize_link_text(message.content)
        conf = await self.get_automod_cached(message.guild.id)
        if conf.get("security_module_disabled"):
            return

        # Immunité personnelle explicite ON : aucun filtre AutoMod ne s'applique.
        # OFF ne court-circuite rien et l'utilisateur est traité comme un membre normal.
        personal_immunity = await self.get_immunity_override_cached(
            message.guild.id, message.author.id
        )
        if personal_immunity is True:
            return
        # Les exemptions de rôles ne sont plus court-circuitées globalement ici :
        # chaque filtre les évalue afin qu'un salon strict puisse reprendre priorité.

        # Les mentions globales doivent être traitées avant les filtres de contenu :
        # elles ne figurent pas dans message.mentions et une rafale peut sinon
        # traverser tous les salons avant le troisième incident anti-spam.
        if conf.get("antimention") and (
            getattr(message, "mention_everyone", False) is True
            or len({u.id for u in message.mentions} | {r.id for r in message.role_mentions}) >= 5
        ) and await self.security_filter_applies_to(message, "antimention"):
            return await self._delete_and_warn(message, "Mention massive détectée.", "antimention")

        # Un lien de phishing passe AVANT l'anti-liens générique. Sinon le
        # message est supprimé comme simple lien, la protection anti-arnaque
        # ne voit jamais l'URL et le modérateur perd la vraie cause.
        if conf and conf.get("antiscam") and await self.security_filter_applies_to(message, "antiscam"):
            early_scam_reason = _scam_hit(message.content)
            if early_scam_reason:
                return await self._delete_and_warn(
                    message,
                    f"Message d'arnaque potentiel détecté ({early_scam_reason}).",
                    "antiscam",
                    censored_content=_compose_censored_content(message.content, scam=True),
                )

        # Détections prioritaires pouvant être combinées dans un seul avertissement.
        # Chaque détection consulte sa propre politique de rôles bypass / salons stricts.
        words = await self.get_blacklist_words_cached(message.guild.id)
        blocked_word = self._blacklist_hit(words, message.content)

        blocked_links = await self.get_blacklist_links_cached(message.guild.id)
        blocked_hit = _blocked_link_hit(link_content, blocked_links)

        word_applies = bool(blocked_word) and await self.security_filter_applies_to(
            message, "antiinsult"
        )
        link_applies = bool(blocked_hit) and await self.security_filter_applies_to(
            message, "antilink"
        )

        if word_applies and link_applies:
            return await self._delete_and_warn(
                message,
                "Mot interdit et lien interdit détectés.",
                "blacklist_word_link",
                censored_content=_compose_censored_content(
                    message.content, blocked_word=blocked_word, links=True
                ),
            )
        if link_applies:
            return await self._delete_and_warn(
                message,
                "Lien ciblé interdit par la liste noire du serveur.",
                "blacklist_link",
                censored_content=_compose_censored_content(message.content, links=True),
            )

        # Le mode anti-liens strict bloque tous les domaines, mais respecte encore la
        # politique de ce filtre : rôle bypass hors salon strict, jamais dans un salon strict.
        if (
            conf
            and conf.get("antilink")
            and conf.get("antilink_strict")
            and LINK_RE.search(link_content)
            and await self.security_filter_applies_to(message, "antilink")
        ):
            return await self._delete_and_warn(
                message,
                "Lien interdit : mode anti-liens strict actif.",
                "antilink",
                censored_content=_compose_censored_content(message.content, links=True),
            )

        if word_applies:
            return await self._delete_and_warn(
                message,
                "Mot interdit détecté.",
                "blacklist_word",
                censored_content=_compose_censored_content(
                    message.content, blocked_word=blocked_word
                ),
            )

        if not conf:
            return

        # Filtre multilingue d'insultes : uniquement si le serveur l'a activé. Il tournait
        # avant pour tout le monde, sans interrupteur, et appliquait un timeout.
        if conf.get("antiinsult") and await self.security_filter_applies_to(message, "antiinsult"):
            dataset_match = self.moderation_dataset.match(message.content)
            if dataset_match and dataset_match.confidence >= 0.92:
                return await self._delete_and_timeout(
                    message,
                    f"Contenu offensant confirmé ({dataset_match.reason}, confiance {dataset_match.confidence:.0%}).",
                    detection_kind=dataset_match.kind,
                )
            if dataset_match and dataset_match.confidence >= 0.70:
                return await self._delete_and_warn(
                    message,
                    f"Contenu offensant probable ({dataset_match.reason}, confiance {dataset_match.confidence:.0%}).",
                    "multilingual_toxicity",
                    allow_escalation=False,
                )

        # Incident de spam : suppression silencieuse sur une courte fenêtre
        # de 8 secondes seulement. L'ancien code utilisait 30 secondes et
        # empêchait un membre de reparler longtemps après la rafale.
        incident = self.incidents.get((message.guild.id, message.author.id))
        if (
            incident is not None
            and incident.filter_name in SPAM_FILTERS
            and time.monotonic() - incident.started < SPAM_INCIDENT_WINDOW_SECONDS
            and await self.security_filter_applies_to(message, incident.filter_name)
        ):
            return await self._delete_and_warn(message, incident.reason, incident.filter_name)

        blacklisted_users = await self.get_blacklist_users_cached(message.guild.id)
        scope_ids = self._message_scope_ids(message)
        ignored_channels = await self.get_ignored_channels_cached(message.guild.id)
        if message.author.id in blacklisted_users and not (scope_ids & ignored_channels):
            self._mark_xp_skip(message.id)
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        antiscam_applies = bool(conf["antiscam"]) and await self.security_filter_applies_to(
            message, "antiscam"
        )
        if antiscam_applies and message.attachments:
            candidates = [
                attachment for attachment in message.attachments[:2]
                if _is_scam_image_attachment(attachment)
            ]
            if candidates:
                verdicts = await asyncio.gather(
                    *(_scan_scam_image(attachment) for attachment in candidates)
                )
                image_scam_reason = next((reason for reason in verdicts if reason), None)
                if image_scam_reason:
                    return await self._delete_and_warn(
                        message,
                        f"Image d'arnaque détectée avec haute confiance ({image_scam_reason}).",
                        "antiscam",
                    )

        contenu_invitation = _recoller_hotes_invitation(
            text_normalization.normaliser(message.content)
        )
        if (
            conf["antiinvite"]
            and await self.security_filter_applies_to(message, "antiinvite")
            and (INVITE_RE.search(link_content) or INVITE_RE.search(contenu_invitation))
        ):
            return await self._delete_and_warn(
                message,
                "Lien d'invitation Discord non autorisé.",
                "antiinvite",
                censored_content=_compose_censored_content(message.content, invites=True),
            )

        if (
            conf["antilink"]
            and await self.security_filter_applies_to(message, "antilink")
            and LINK_RE.search(link_content)
        ):
            allowed = await self.get_whitelist_domains_cached(message.guild.id)
            if not _domain_allowed(link_content, allowed):
                return await self._delete_and_warn(
                    message,
                    "Lien non autorisé.",
                    "antilink",
                    censored_content=_compose_censored_content(message.content, links=True),
                )


        if (
            conf["anticaps"]
            and await self.security_filter_applies_to(message, "anticaps")
            and len(message.content) >= 10
        ):
            letters = [char for char in message.content if char.isalpha()]
            if letters and sum(1 for char in letters if char.isupper()) / len(letters) > 0.7:
                return await self._delete_and_warn(message, "Trop de majuscules (SPAM CAPS).", "anticaps")

        if conf["antiemoji"] and await self.security_filter_applies_to(message, "antiemoji"):
            emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF]", message.content))
            if emoji_count > 10:
                return await self._delete_and_warn(message, "Spam d'émojis détecté.", "antiemoji")

        # Une modification n'est pas un nouveau message : la compter ferait passer
        # une simple correction de faute pour une rafale.
        if (
            conf["antispam"] and not getattr(message, "_sentrix_edit", False)
            and await self.security_filter_applies_to(message, "antispam")
        ):
            key = (message.guild.id, message.author.id)
            seuils = await self._spam_seuils(message.guild.id)
            group = self._coordinated_copies(message, link_content, seuils.comptes_coordonnes)
            if group:
                self._noter_spammeur(message.guild, message.author.id, raid=True)
                reason = "Même message publié par plusieurs comptes (raid coordonné)."
                results = await asyncio.gather(
                    *(self._delete_and_warn(m, reason, "antispam") for m in group),
                    return_exceptions=True,
                )
                for failure in results:
                    if isinstance(failure, Exception):
                        logger.error("Raid coordonné : traitement d'un message impossible", exc_info=failure)
                return
            # Revérifié ici, sans attente avant le comptage : un message qui a passé le
            # contrôle d'incident plus haut puis attendu la base pendant que l'incident
            # s'ouvrait arrivait au compteur juste remis à zéro, et restait affiché
            # (mesuré sur PostgreSQL, où chaque lecture est un aller-retour réseau).
            incident = self.incidents.get(key)
            if (
                incident is not None
                and incident.filter_name in SPAM_FILTERS
                and time.monotonic() - incident.started < SPAM_INCIDENT_WINDOW_SECONDS
            ):
                return await self._delete_and_warn(message, incident.reason, incident.filter_name)
            self.spam_tracker.ajouter(key, message)
            if self.spam_tracker.compter(key, fenetre=seuils.secondes) >= seuils.messages:
                # La rafale entière part, pas seulement le message qui franchit le seuil :
                # les premiers restaient affichés (4 par spammeur, mesuré).
                burst = [
                    m for m in self.spam_tracker.valeurs(key, fenetre=seuils.secondes)
                    if m is not None and m is not message
                ]
                self.spam_tracker.reinitialiser(key)
                earlier = self._delete_burst(message.guild.id, burst)
                result = await self._delete_and_warn(message, "Spam de messages détecté.", "antispam")
                incident = self.incidents.get(key)
                if incident is not None and earlier:
                    incident.deleted += len(earlier)
                await asyncio.gather(*earlier, return_exceptions=True)
                return result

            # Une promotion envoyée toutes les quelques secondes dans de
            # nombreux salons contourne le seuil de rafale courte. Suivi par
            # serveur+membre, jamais global à tout le serveur.
            if len(text_normalization.normaliser(message.content)) >= SPAM_CROSS_CHANNEL_MIN_LENGTH:
                self.cross_channel_spam_tracker.ajouter(key, message.channel.id)
                channel_history = self.cross_channel_spam_tracker.valeurs(key)
                if (
                    len(channel_history) >= SPAM_CROSS_CHANNEL_THRESHOLD
                    and len(set(channel_history)) >= SPAM_CROSS_CHANNEL_MIN_CHANNELS
                ):
                    self.cross_channel_spam_tracker.reinitialiser(key)
                    return await self._delete_and_warn(
                        message,
                        "Publications trop nombreuses dans plusieurs salons.",
                        "antispam",
                    )

            motif_repete = self._detecter_repetition(message, key, seuil=seuils.repetitions)
            if motif_repete:
                self.repeat_tracker.reinitialiser(key)
                return await self._delete_and_warn(message, motif_repete, "antispam")

    def _coordinated_copies(
        self, message: discord.Message, link_content: str, comptes: int = COORDINATED_AUTHORS
    ) -> list[discord.Message]:
        """Les messages identiques de plusieurs comptes, dès qu'ils sont assez nombreux.

        Retourne la liste à traiter (celui-ci compris, et ceux qui ont précédé et
        n'ont pas encore été traités), ou une liste vide.
        """
        contenu = text_normalization.normaliser(message.content)
        if len(contenu) < COORDINATED_MIN_LENGTH and not LINK_RE.search(link_content):
            return []
        if len(contenu) < REPEAT_MIN_LENGTH:
            return []
        empreinte = hash("".join(contenu.split()))
        cle = (message.guild.id, empreinte)
        tracker = getattr(self, "coordinated_tracker", None)
        if tracker is None:
            tracker = self.coordinated_tracker = FenetreGlissante(fenetre=COORDINATED_WINDOW, purge_toutes=200)
        tracker.ajouter(cle, message)
        copies = [m for m in tracker.valeurs(cle) if m is not None]
        if len({m.author.id for m in copies}) < comptes:
            return []
        return copies

    async def _spam_seuils(self, guild_id: int) -> spam_sensitivity.Seuils:
        """Seuils anti-spam du serveur (gardés une minute), renfort anti-raid compris."""
        cache = getattr(self, "_reglages_spam", None)
        if cache is None:
            cache = self._reglages_spam = {}
        now = time.monotonic()
        hit = cache.get(guild_id)
        if hit is None or hit[0] <= now:
            try:
                reglage = await spam_sensitivity.lire(self.bot, guild_id)
            except Exception:
                logger.exception("Seuils anti-spam illisibles guild=%s : réactivité normale.", guild_id)
                reglage = spam_sensitivity.Reglage(
                    spam_sensitivity.NIVEAU_PAR_DEFAUT,
                    spam_sensitivity.NIVEAUX[spam_sensitivity.NIVEAU_PAR_DEFAUT],
                )
            if len(cache) > 5000:
                cache.clear()
            cache[guild_id] = hit = (now + 60, reglage)
        seuils = hit[1].seuils
        if self._renfort_actif(guild_id):
            seuils = seuils.plus_strict(spam_sensitivity.NIVEAUX["stricte"])
        return seuils

    def _oublier_seuils(self, guild_id: int) -> None:
        getattr(self, "_reglages_spam", {}).pop(guild_id, None)

    def _renfort_actif(self, guild_id: int) -> bool:
        return getattr(self, "_renfort_jusqua", {}).get(guild_id, 0.0) > time.monotonic()

    def _noter_spammeur(self, guild: discord.Guild, member_id: int, *, raid: bool = False) -> None:
        """Plusieurs membres en incident anti-spam en même temps : renfort anti-raid."""
        tracker = getattr(self, "_spammeurs_recents", None)
        if tracker is None:
            tracker = self._spammeurs_recents = FenetreGlissante(
                fenetre=spam_sensitivity.RENFORT_FENETRE, purge_toutes=100
            )
        tracker.ajouter(guild.id, int(member_id))
        distincts = len(set(tracker.valeurs(guild.id)))
        if not raid and distincts < spam_sensitivity.RENFORT_SPAMMEURS:
            return
        jusqua = getattr(self, "_renfort_jusqua", None)
        if jusqua is None:
            jusqua = self._renfort_jusqua = {}
        deja = self._renfort_actif(guild.id)
        jusqua[guild.id] = time.monotonic() + spam_sensitivity.RENFORT_SECONDES
        if not deja:
            asyncio.create_task(self._annoncer_renfort(guild, distincts, raid))

    async def _annoncer_renfort(self, guild: discord.Guild, distincts: int, raid: bool) -> None:
        stricte = spam_sensitivity.NIVEAUX["stricte"]
        cause = (
            "le même message a été publié par plusieurs comptes"
            if raid else f"{distincts} membres ont déclenché l'anti-spam en moins de "
            f"{spam_sensitivity.RENFORT_FENETRE} s"
        )
        carte = embeds.log_entry(
            "Renfort anti-raid activé",
            config.COLOR_WARNING,
            extra={
                "Cause": cause[:1].upper() + cause[1:] + ".",
                "Réactivité": f"stricte ({stricte.phrase()}) pendant "
                              f"{spam_sensitivity.RENFORT_SECONDES // 60} min, puis retour au niveau du serveur",
                "Sanctions": "inchangées (rappel, puis avertissement, puis mute)",
            },
        )
        try:
            # Pas log_action : sa mise en forme AutoMod décrit un incident de membre
            # (« Spam bloqué », Protection, Sanction), pas un changement de réactivité.
            await helpers.send_log(self.bot, guild, "spam_boost", carte)
        except Exception:
            logger.exception("Annonce du renfort anti-raid impossible guild=%s", guild.id)

    def _purge_queue(self) -> SuppressionsGroupees:
        """Suppressions regroupées par salon : sous une rafale de plusieurs spammeurs,
        un appel groupé au lieu d'un appel par message. Créée à la demande, comme
        les autres états du cog que certains appelants construisent sans __init__."""
        queue = getattr(self, "_purge", None)
        if queue is None:
            queue = self._purge = SuppressionsGroupees()
        return queue

    def _delete_burst(self, guild_id: int, messages: list[discord.Message]) -> list[asyncio.Future]:
        """Met en file la suppression des messages d'une rafale déjà détectée, sans
        avertissement ni log de plus : l'incident en cours les compte."""
        futures = []
        for earlier in messages:
            if not self._sanctioned_messages.claim(guild_id, earlier.id):
                continue
            self._mark_xp_skip(earlier.id)
            log_service.mark_purged((earlier.id,))
            futures.append(asyncio.ensure_future(self._purge_queue().supprimer(earlier)))
        return futures

    def _detecter_repetition(
        self, message: discord.Message, key: tuple[int, int], seuil: int = REPEAT_THRESHOLD
    ) -> str | None:
        """Le même message répété, quelle que soit sa vitesse.

        L'empreinte passe par la normalisation de sécurité : « FREE NITRO » et
        « f r e e   n i t r o » comptent donc pour le même message, sinon il
        suffirait de changer la casse à chaque envoi.

        Deux signaux distincts, parce qu'ils décrivent deux abus différents :
        répéter dans un salon (flood) et recopier dans plusieurs salons
        (publicité). Le second se déclenche plus tôt — poster trois fois la
        même chose dans trois salons différents n'est jamais un accident.
        """
        contenu = text_normalization.normaliser(message.content)
        if len(contenu) < REPEAT_MIN_LENGTH:
            return None

        # L'empreinte ignore aussi les espaces : « promo » et « p r o m o » sont
        # le même message. Ici le dé-espacement est sans danger — l'empreinte
        # n'est comparée qu'à d'autres empreintes du MÊME membre, jamais à une
        # liste de mots interdits où « con » dans « connexion » poserait problème.
        empreinte = hash("".join(contenu.split()))
        salon_id = getattr(message.channel, "id", 0)
        self.repeat_tracker.ajouter(key, (empreinte, salon_id))
        precedents = [v for v in self.repeat_tracker.valeurs(key) if v and v[0] == empreinte]
        if len(precedents) >= seuil:
            return "Message identique répété plusieurs fois."
        if len({salon for _e, salon in precedents}) >= REPEAT_CHANNEL_THRESHOLD:
            return "Même message recopié dans plusieurs salons."
        return None

    def _mark_xp_skip(self, message_id: int):
        """Empêche cogs/levels.py d'accorder de l'XP pour ce message : AutoMod vient de
        décider de le supprimer (spam, lien interdit, mot blacklisté, arnaque...). Voir la
        vérification correspondante dans Levels._process_xp(). Le marqueur s'auto-nettoie
        après 10 secondes pour ne jamais laisser cet ensemble grossir indéfiniment.

        Best-effort : les deux écouteurs on_message (celui-ci et celui de Levels) sont
        indépendants et tournent en parallèle, donc cette protection couvre la grande
        majorité des cas réels mais n'offre pas une garantie absolue à la microseconde
        près sur un serveur extrêmement chargé."""
        skip_ids = getattr(self.bot, "_xp_skip_ids", None)
        if skip_ids is None:
            skip_ids = self.bot._xp_skip_ids = set()
        skip_ids.add(message_id)
        asyncio.get_event_loop().call_later(10, skip_ids.discard, message_id)

    async def _get_censor_webhook(self, channel) -> tuple[discord.Webhook | None, discord.Thread | None]:
        """Retourne un webhook réutilisable pour le salon, sans jamais contourner Discord."""
        thread = channel if isinstance(channel, discord.Thread) else None
        base = channel.parent if thread is not None else channel
        if not isinstance(base, discord.TextChannel):
            return None, thread

        me = base.guild.me
        if me is None:
            return None, thread
        perms = base.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.manage_webhooks):
            return None, thread

        cached = self._censor_webhooks.get(base.id)
        if cached is not None:
            return cached, thread

        try:
            hooks = await base.webhooks()
            bot_id = getattr(getattr(self.bot, "user", None), "id", None)
            hook = next(
                (
                    h for h in hooks
                    if h.name == "SentriX Censure"
                    and (bot_id is None or getattr(getattr(h, "user", None), "id", None) == bot_id)
                ),
                None,
            )
            if hook is None:
                hook = await base.create_webhook(
                    name="SentriX Censure",
                    reason="SentriX AutoMod : repost des messages censurés",
                )
            self._censor_webhooks[base.id] = hook
            return hook, thread
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Webhook censure indisponible guild=%s channel=%s",
                getattr(base.guild, "id", None),
                getattr(base, "id", None),
            )
            return None, thread

    async def _repost_censored(self, message: discord.Message, content: str | None) -> bool:
        """Recrée le message censuré avec pseudo/avatar d'origine + badge APP Discord."""
        if not content:
            return False
        webhook, thread = await self._get_censor_webhook(message.channel)
        if webhook is None:
            return False

        username = str(getattr(message.author, "display_name", None) or message.author.name or "Membre")
        username = username[:80] or "Membre"
        avatar = str(getattr(getattr(message.author, "display_avatar", None), "url", "") or "") or None
        kwargs = {
            "content": content,
            "username": username,
            "avatar_url": avatar,
            "allowed_mentions": discord.AllowedMentions.none(),
            "wait": False,
        }
        if thread is not None:
            kwargs["thread"] = thread

        try:
            await webhook.send(**kwargs)
            return True
        except discord.NotFound:
            # Webhook supprimé manuellement : invalide le cache, la prochaine détection
            # le recréera proprement.
            base = message.channel.parent if isinstance(message.channel, discord.Thread) else message.channel
            self._censor_webhooks.pop(getattr(base, "id", 0), None)
            return False
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Repost webhook censure impossible guild=%s channel=%s user=%s",
                message.guild.id,
                message.channel.id,
                message.author.id,
            )
            return False

    @staticmethod
    def _public_automod_message(filter_name: str, reason: str) -> str:
        """Message court visible dans le salon, proche du rendu demandé.

        Le détail technique reste dans les logs ; le salon reçoit seulement la raison
        utile. On ne republie jamais le contenu interdit ni l'URL supprimée.
        """
        labels = {
            "blacklist_word": "votre message contient un mot interdit sur le serveur.",
            "blacklist_link": "les liens sont interdits dans ce salon.",
            "blacklist_word_link": "votre message contient un mot interdit et un lien interdit sur le serveur.",
            "antilink": "les liens sont interdits dans ce salon.",
            "antiinvite": "votre message contient une invitation Discord interdite sur le serveur.",
            "antiscam": "votre message a été bloqué par la protection anti-arnaque.",
        }
        return labels.get(filter_name, f"votre message a été supprimé : {reason}")

    @staticmethod
    def _content_notice_view(member_mention: str, filter_name: str) -> discord.ui.LayoutView:
        """Avertissement AutoMod compact, sans bannière blanche ni embed générique.

        Components V2 est dessiné dans un seul conteneur, sans liseré coloré.
        Aucun lien suspect n'y est réaffiché ; le contenu a déjà été supprimé.
        """
        titles = {
            "antilink": ("🔗 Lien supprimé", "Les liens ne sont pas autorisés ici."),
            "blacklist_link": ("🔗 Lien bloqué", "Ce lien figure parmi les liens interdits."),
            "antiinvite": ("📨 Invitation bloquée", "Les invitations ne sont pas autorisées ici."),
            "blacklist_word": ("🛡️ Message modéré", "Un mot interdit a été détecté."),
            "blacklist_word_link": ("🛡️ Message modéré", "Un mot et un lien interdits ont été détectés."),
            "antiscam": ("🛡️ Arnaque suspectée", "Un lien ou un contenu suspect a été détecté."),
        }
        title, explanation = titles.get(filter_name, ("🛡️ Message modéré", "Un filtre de sécurité a été appliqué."))
        view = discord.ui.LayoutView(timeout=15)
        box = discord.ui.Container()
        box.add_item(
            discord.ui.TextDisplay(
                f"### {title}\n"
                f"{member_mention} · {explanation}\n"
                "-# **SentriX · Sécurité** · Avertissement temporaire (8 s)"
            )
        )
        view.add_item(box)
        return view

    async def _delete_and_warn(
        self,
        message: discord.Message,
        reason: str,
        filter_name: str = "automod",
        *,
        censored_content: str | None = None,
        allow_escalation: bool = True,
    ):
        """Supprime le message et traite la détection comme un incident par membre.

        Première détection dans la fenêtre : suppression, infraction + escalade
        éventuelle, exclusion temporaire directe pour les filtres de spam, UN avertissement
        court dans le salon et UNE carte de log compacte (envoyée après un court délai
        pour inclure le nombre réel de messages supprimés). Détections suivantes dans la
        fenêtre : suppression silencieuse, compteur incrémenté.
        """
        # Protection de dernier recours pour les autres listeners AutoMod qui
        # appelleraient cette méthode directement, sans passer par le filtre.
        if _is_discord_administrator(message.author):
            return
        if not self._sanctioned_messages.claim(message.guild.id, message.id):
            logger.debug(
                "AutoMod : détection concurrente ignorée guild=%s message=%s filtre=%s",
                message.guild.id, message.id, filter_name,
            )
            return
        if filter_name in {
            "antilink", "antiinvite", "antiscam", "blacklist_link", "blacklist_word_link",
        }:
            key = (message.guild.id, message.author.id, str(filter_name))
            now = time.monotonic()
            if now - self._local_block_last_seen.get(key, -9999.0) >= 30:
                if len(self._local_block_last_seen) > 2000:
                    self._local_block_last_seen.clear()
                self._local_block_last_seen[key] = now
                logger.info(
                    "SENTRIX_BLOCK_SOURCE=local guild=%s user=%s channel=%s filter=%s",
                    message.guild.id, message.author.id, message.channel.id, filter_name,
                )
        self._mark_xp_skip(message.id)
        # La suppression part tout de suite, mais l'incident est enregistré AVANT de
        # l'attendre. Avant, les messages suivants du même membre arrivaient pendant
        # l'appel à Discord, ne voyaient aucun incident et restaient visibles
        # (mesuré : jusqu'à 10 messages sur 12 par spammeur, tools/spam_burst_e2e.py).
        if filter_name in SPAM_FILTERS:
            # La carte AutoMod de l'incident résume la rafale (nombre, extrait) : pas
            # de carte « Message supprimé » par message en plus — mesuré : 242 cartes
            # pour une vague de 20 spammeurs. Même règle que +clear.
            log_service.mark_purged((message.id,))
        deletion = asyncio.ensure_future(self._purge_queue().supprimer(message))

        async def finish_deletion() -> None:
            # Republication contrôlée SentriX : seulement APRÈS suppression réussie, et
            # uniquement si le texte a pu être censuré de manière sûre. Sans Gérer les
            # webhooks, on garde automatiquement le comportement suppression + avertissement.
            if (
                await deletion and censored_content and filter_name not in NO_REPOST_FILTERS
                and not getattr(message, "_sentrix_external_app", False)
            ):
                await self._repost_censored(message, censored_content)

        key = (message.guild.id, message.author.id)
        now_ts = time.monotonic()
        incident = self.incidents.get(key)
        incident_window = (
            SPAM_INCIDENT_WINDOW_SECONDS
            if incident is not None and incident.filter_name in SPAM_FILTERS
            else INCIDENT_WINDOW_SECONDS
        )
        if (incident is not None and now_ts - incident.started < incident_window
                and not (filter_name == "antimention" and incident.filter_name != "antimention")):
            incident.deleted += 1
            await finish_deletion()
            return
        incident = _Incident(
            started=now_ts,
            filter_name=filter_name,
            reason=reason,
            channel_id=message.channel.id,
            message_preview=_automod_message_preview(message),
            message_id=int(getattr(message, "id", 0) or 0),
            raw_content=_contenu_brut(message),
        )
        self.incidents[key] = incident
        if filter_name in SPAM_FILTERS:
            self._noter_spammeur(message.guild, message.author.id)
        if len(self.incidents) > 5000:
            cutoff = now_ts - INCIDENT_WINDOW_SECONDS
            for candidate, item in list(self.incidents.items()):
                if item.started < cutoff:
                    self.incidents.pop(candidate, None)
        # Démarrer le timeout avant d'attendre suppression, SQL ou logs.
        # L'incident est déjà publié : les messages concurrents restent idempotents.
        mention_action = None
        if filter_name == "antimention":
            try:
                mention_action = await self._spam_timeout(message.guild, message.author, reason)
            except Exception:
                logger.exception("Timeout anti-mentions impossible guild=%s user=%s", message.guild.id, message.author.id)
        await finish_deletion()
        if deletion.done() and not deletion.cancelled() and deletion.exception() is None:
            incident.deleted_ok = bool(deletion.result())

        await self._record_incident_trace(message, incident)
        try:
            await self.bot.db.log_automod_action(
                message.guild.id,
                message.author.id,
                filter_name,
                "suppression",
                reason,
            )
        except Exception:
            logger.exception(
                "Historique AutoMod indisponible après suppression guild=%s user=%s filtre=%s.",
                message.guild.id,
                message.author.id,
                filter_name,
            )

        if allow_escalation:
            risk_points = RISK_SIGNAL_POINTS.get(filter_name, 10)
            try:
                await self.add_risk_signal(
                    message.guild,
                    message.author.id,
                    filter_name,
                    risk_points,
                    reason=reason,
                    target=message.author,
                )
            except Exception:
                logger.exception(
                    "Score de risque AutoMod indisponible guild=%s user=%s filtre=%s.",
                    message.guild.id,
                    message.author.id,
                    filter_name,
                )

        action = None
        infraction_count = 0
        spam_stage = 0
        spam_duration = None
        spam_public_text = None

        try:
            if filter_name == "antimention":
                action = mention_action or "mute_failed"
                spam_duration = SPAM_TIMEOUT_SECONDS
                incident.duration_s = SPAM_TIMEOUT_SECONDS
                incident.action_label = "🔇 Mute anti-mentions" if mention_action else "⚠️ Mute anti-mentions non appliqué"
            elif filter_name in SPAM_FILTERS:
                action, spam_stage, spam_duration, spam_public_text = await self._spam_progressive_action(
                    message.guild,
                    message.author,
                    reason,
                )
                incident.spam_stage = spam_stage
                incident.duration_s = spam_duration or SPAM_TIMEOUT_SECONDS
                if action == "warning_ping":
                    incident.action_label = "⚠️ Rappel anti-spam"
                elif action == "warn":
                    incident.action_label = "⚠️ Avertissement enregistré"
                elif action == "mute":
                    incident.action_label = f"🔇 Mute {helpers.format_duration(spam_duration or SPAM_TIMEOUT_SECONDS)}"
                elif action == "mute_failed":
                    incident.action_label = f"⚠️ Mute prévu {helpers.format_duration(spam_duration or SPAM_TIMEOUT_SECONDS)} — non appliqué"
            elif allow_escalation:
                action, infraction_count = await self._maybe_escalate(
                    message.guild,
                    message.author,
                    reason,
                )
        except Exception:
            # L'escalade est secondaire par rapport à la suppression déjà faite :
            # on garde l'avertissement public et le log d'incident au lieu de perdre
            # tout le traitement du message.
            logger.exception(
                "Escalade AutoMod indisponible guild=%s user=%s filtre=%s.",
                message.guild.id,
                message.author.id,
                filter_name,
            )

        incident.action = action
        incident.infractions = infraction_count
        if action == "mute" and incident.duration_s is None:
            incident.duration_s = MUTE_ESCALATION_SECONDS
        if action and action != "warning_ping":
            try:
                await self.bot.db.log_automod_action(
                    message.guild.id,
                    message.author.id,
                    filter_name,
                    action,
                    reason,
                )
            except Exception:
                logger.exception(
                    "Historique de sanction AutoMod indisponible guild=%s user=%s action=%s.",
                    message.guild.id,
                    message.author.id,
                    action,
                )

        public_text = (
            spam_public_text
            if filter_name in SPAM_FILTERS and spam_public_text
            else self._public_automod_message(filter_name, reason)
        )
        try:
            if filter_name in LINK_NOTICE_FILTERS:
                # Le membre voit un avertissement LISIBLE, sans embed, carte
                # blanche, webhook ou repost du lien interdit. La mention est
                # uniquement visuelle : aucun ping n'est envoyé.
                await message.channel.send(
                    f"🚫 {message.author.mention} Les liens sont interdits dans ce salon.",
                    allowed_mentions=discord.AllowedMentions.none(),
                    delete_after=8,
                )
            elif filter_name in {"blacklist_word", "antiscam"}:
                # Les autres infractions conservent leur interface existante.
                try:
                    await message.channel.send(
                        view=self._content_notice_view(message.author.mention, filter_name),
                        allowed_mentions=discord.AllowedMentions.none(),
                        delete_after=8,
                    )
                except (discord.Forbidden, discord.HTTPException):
                    # Composants indisponibles ou salon restreint : la
                    # suppression du message reste acquise, repli discret.
                    await panels.texte_court(
                        message.channel,
                        f"{message.author.mention}, {public_text}",
                        supprimer_apres=6,
                    )
            elif filter_name in SPAM_FILTERS and self._group_spam_notice(
                message.channel, message.author.mention, public_text
            ):
                pass
            else:
                await panels.texte_court(
                    message.channel,
                    f"{message.author.mention}, {public_text}",
                    supprimer_apres=6,
                )
        except discord.HTTPException:
            pass

        asyncio.create_task(self._flush_incident_log(message.guild, message.author, key, incident))

    def _group_spam_notice(self, channel, mention: str, text: str) -> bool:
        """True si l'avertissement rejoint un envoi groupé (l'appelant n'envoie rien).

        Le premier spammeur d'un salon est averti tout de suite ; ceux qui suivent
        dans les secondes d'après sont réunis dans un seul message.
        """
        now = time.monotonic()
        notices = getattr(self, "_spam_notices", None)
        if notices is None:
            notices = self._spam_notices = {}
        wave = notices.get(channel.id)
        if wave is None or now - wave["since"] > SPAM_NOTICE_GROUP_WINDOW_SECONDS:
            if len(notices) > 500:
                notices = self._spam_notices = {
                    cid: w for cid, w in notices.items()
                    if now - w["since"] <= SPAM_NOTICE_GROUP_WINDOW_SECONDS or w["task"] is not None
                }
            notices[channel.id] = {"since": now, "pending": {}, "task": None, "named": {mention}}
            return False
        if mention in wave["named"]:
            # Le même membre récidive : son nouvel avertissement (étape suivante)
            # part tout de suite, il ne se noie pas dans la vague.
            return False
        wave["named"].add(mention)
        mentions = wave["pending"].setdefault(text, [])
        if mention not in mentions:
            mentions.append(mention)
        if wave["task"] is None:
            wave["task"] = asyncio.create_task(self._send_grouped_spam_notice(channel, wave))
        return True

    async def _send_grouped_spam_notice(self, channel, wave: dict) -> None:
        try:
            await asyncio.sleep(SPAM_NOTICE_GROUP_DELAY_SECONDS)
        finally:
            pending, wave["pending"], wave["task"] = wave["pending"], {}, None
            wave["since"] = time.monotonic()
        lines = []
        for text, mentions in pending.items():
            shown = ", ".join(mentions[:SPAM_NOTICE_MAX_MENTIONS])
            hidden = len(mentions) - SPAM_NOTICE_MAX_MENTIONS
            if hidden > 0:
                shown += f" et {hidden} autre{'s' if hidden > 1 else ''}"
            lines.append(f"{shown}, {text}")
        if not lines:
            return
        try:
            await panels.texte_court(channel, "\n".join(lines), supprimer_apres=6)
        except discord.HTTPException:
            pass
        except Exception:
            logger.exception("Avertissement anti-spam groupé impossible salon=%s", getattr(channel, "id", None))

    async def _spam_timeout(self, guild: discord.Guild, member: discord.abc.User, reason: str) -> str | None:
        """Exclusion temporaire directe pour un incident de spam (une seule par incident)."""
        if not isinstance(member, discord.Member):
            return None
        me = guild.me
        if member.id == guild.owner_id or me is None or not me.guild_permissions.moderate_members or member.top_role >= me.top_role:
            return None
        until = discord.utils.utcnow() + timedelta(seconds=SPAM_TIMEOUT_SECONDS)
        current = member.timed_out_until
        if current and current > until:
            return "mute"
        try:
            log_service.mark_sanction(guild.id, member.id, "timeout")
            await member.timeout(until, reason=f"AutoMod : {reason}")
        except (discord.Forbidden, discord.HTTPException):
            return None
        return "mute"

    async def _record_incident_trace(self, message: discord.Message, incident: _Incident) -> None:
        """Une référence SX- par incident, écrite dans le fil comme une action du staff."""
        from utils import sentrix_trace

        try:
            ref = sentrix_trace.make_ref(message.guild.id, message.id)
            await sentrix_trace.record(self.bot.db, sentrix_trace.Trace(
                ref=ref, guild_id=message.guild.id, command="automod", transport=sentrix_trace.AUTOMATIC,
                actor_id=self._bot_user_id(), channel_id=message.channel.id,
                target_id=int(message.author.id), detail=f"{incident.filter_name} · {incident.reason}",
            ))
        except Exception:
            logger.exception("Référence d'incident AutoMod non enregistrée guild=%s", message.guild.id)
            return
        # Seulement une fois écrite : une référence affichée doit pouvoir se retrouver.
        incident.ref = ref
        incident.author_id = int(message.author.id)

    def _bot_user_id(self) -> int:
        return int(getattr(getattr(self.bot, "user", None), "id", 0) or 0)

    async def _flush_incident_log(self, guild: discord.Guild, member: discord.abc.User, key: tuple[int, int], incident: _Incident) -> None:
        """Une seule carte de log par incident, compacte, avec le nombre réel de messages."""
        # La mémoire est lue AVANT l'attente : l'incident vient d'être écrit en base,
        # son rang est exact ; lu après, un incident suivant pourrait le décaler.
        try:
            from utils import sentrix_trace

            memory = await sentrix_trace.automod_memory(self.bot, guild, member.id)
        except Exception:
            logger.exception("Mémoire AutoMod illisible guild=%s user=%s", guild.id, getattr(member, "id", None))
            memory = ""
        try:
            await asyncio.sleep(INCIDENT_LOG_DELAY_SECONDS)
            from utils import automod_incident_card as carte

            # Carte complète (29/10/2026) : statut, protection, règle, motif, salon,
            # date exacte, contenu neutralisé, action, durée et récidive ; le
            # contenu trop long part en fichier joint au lieu d'être tronqué.
            extra, fichier = carte.champs(
                filter_name=incident.filter_name, reason=incident.reason, guild_id=guild.id,
                channel_id=incident.channel_id, message_id=incident.message_id,
                created_at=incident.created_at, contenu=incident.raw_content,
                deleted=incident.deleted, deleted_ok=incident.deleted_ok, action=incident.action,
                duree_s=incident.duration_s, infractions=incident.infractions,
                spam_stage=incident.spam_stage, memoire=memory, ref=incident.ref,
            )
            etat = carte.statut(incident.deleted_ok, incident.action)
            title = {
                "reussie": "Action AutoMod — sanction appliquée",
                "bloque": "Action AutoMod — message bloqué",
                "detection": "Détection AutoMod",
                "erreur": "Action AutoMod — échec",
            }[etat]
            color = config.COLOR_ERROR if etat == "erreur" or incident.action in ("kick", "ban") else config.COLOR_WARNING
            e = embeds.log_entry(title, color, cible=member, cible_label="Membre", raison=None, extra=extra)
            event_type = {
                "antiscam": "automod_scam",
                "antiinvite": "automod_invite",
                "antilink": "automod_link",
                "blacklist_link": "automod_link",
                "blacklist_word_link": "automod_link",
                "blacklist_word": "automod_word",
                "antiinsult": "automod_word",
                "antimention": "automod_mention",
                "antispam": "automod_spam",
                "antispam_duplicate": "automod_spam",
                "antiemoji": "automod_spam",
            }.get(incident.filter_name, "automod")
            if not incident.ref:
                await self.log_action(guild, e, event_type, file=fichier)
                return
            from utils import sentrix_trace

            # La carte porte la référence de l'incident et les suites du staff ;
            # chaque bouton exécute la vraie commande au nom de celui qui clique.
            english = False
            try:
                from cogs import language_runtime

                english = await language_runtime.get_language(self.bot, guild.id) == language_runtime.LANG_EN
            except Exception:
                pass
            token = sentrix_trace.CURRENT.set(sentrix_trace.Trace(
                ref=incident.ref, guild_id=guild.id, command="automod", transport=sentrix_trace.AUTOMATIC,
                actor_id=self._bot_user_id(), channel_id=incident.channel_id,
                target_id=int(member.id),
            ))
            try:
                await self.log_action(
                    guild, e, event_type,
                    suites=sentrix_trace.suites_view("automod", member.id, incident.ref, english=english),
                    file=fichier,
                )
            finally:
                sentrix_trace.CURRENT.reset(token)
        except Exception:
            logger.exception(
                "Journal AutoMod impossible guild=%s user=%s filtre=%s",
                guild.id, getattr(member, "id", None), incident.filter_name,
            )

    async def _delete_and_timeout(
        self,
        message: discord.Message,
        reason: str,
        *,
        detection_kind: str,
    ):
        """Supprime le message et applique immédiatement un timeout de 10 minutes.

        Même verrou d'idempotence que _delete_and_warn : jamais deux sanctions
        sur un message détecté par plusieurs cogs simultanément.
        """
        if _is_discord_administrator(message.author):
            return
        if not self._sanctioned_messages.claim(message.guild.id, message.id):
            logger.debug(
                "AutoMod : timeout concurrent ignoré guild=%s message=%s",
                message.guild.id, message.id,
            )
            return
        self._mark_xp_skip(message.id)
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        member = message.author
        timeout_applied = False
        timeout_status = "Impossible à appliquer : permission ou hiérarchie insuffisante."
        if isinstance(member, discord.Member):
            me = message.guild.me
            until = discord.utils.utcnow() + timedelta(seconds=DATASET_TIMEOUT_SECONDS)
            current_timeout = member.timed_out_until
            if current_timeout and current_timeout > until:
                timeout_applied = True
                timeout_status = "Un timeout plus long était déjà actif; il a été conservé."
            elif (
                member.id != message.guild.owner_id
                and me is not None
                and me.guild_permissions.moderate_members
                and member.top_role < me.top_role
            ):
                try:
                    await member.timeout(
                        until,
                        reason="AutoMod : contenu offensant détecté par le filtre multilingue",
                    )
                    timeout_applied = True
                    timeout_status = "Exclusion temporaire appliquée pendant 10 minutes."
                except (discord.Forbidden, discord.HTTPException):
                    pass

        public_status = (
            "Sanction : exclusion temporaire de 10 minutes."
            if timeout_applied
            else "Le message a été bloqué, mais le bot n’a pas pu appliquer le mute. "
                 "Vérifiez la permission Modérer les membres et la hiérarchie des rôles."
        )
        try:
            note = await panels.envoyer(message.channel, panels.depuis_embed(embeds.warning(f'{message.author.mention}, votre message a été supprimé.\nRaison : contenu offensant détecté.\n{public_status}')))
            await note.delete(delay=8)
        except discord.HTTPException:
            pass

        action = "mute" if timeout_applied else "suppression"
        await self.bot.db.log_automod_action(
            message.guild.id,
            message.author.id,
            "multilingual_toxicity",
            action,
            reason,
        )
        e = embeds.log_entry(
            "Action AutoMod — filtre multilingue",
            config.COLOR_WARNING,
            cible=message.author,
            cible_label="Membre",
            raison=reason,
            extra={
                "Salon": f"{message.channel.mention}\n`ID: {message.channel.id}`",
                "Message": _automod_message_preview(message),
                "Type de détection": detection_kind.replace("_", " "),
                "Sanction": timeout_status,
            },
        )
        await self.log_action(message.guild, e, "automod_word")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        conf = await self.get_automod_cached(member.guild.id)
        if not conf or conf.get("security_module_disabled"):
            return

        # Un événement Discord JOIN dupliqué ne doit jamais être interprété
        # comme une nouvelle arrivée ni répéter un kick, un signal de risque
        # ou un comptage anti-raid. Le cache expire en 20 s.
        if not self._recent_raid_joins.first_join(member.guild.id, member.id):
            return

        if conf["antibot"] and member.bot:
            if await self._bot_is_allowlisted(member.guild.id, member.id):
                await self.add_risk_signal(member.guild, member.id, "bot_allowlisted_join", 5, reason="Bot allowlisté ajouté au serveur", target=member)
                return
            ajoute_par = await self.get_audit_actor(member.guild, discord.AuditLogAction.bot_add, member.id)
            erreur = ""
            try:
                await member.kick(reason="AutoMod : bot non autorisé")
                await self.add_risk_signal(member.guild, member.id, "bot_suspect", 60, reason="Bot non approuvé ajouté au serveur", target=member)
            except discord.HTTPException as exc:
                erreur = f"Discord a refusé l'expulsion ({exc.status}) : rôle de SentriX trop bas ou permission manquante."
            await self._journal_arrivee(
                member, titre="Bot non autorisé", protection="Anti-bots", regle="Bot absent de la liste autorisée",
                motif="Bot ajouté sans être autorisé (`/protection bot-allow` pour l'autoriser).",
                action="Bot expulsé", erreur=erreur,
                extra={"Ajouté par": f"{ajoute_par.mention} · `{ajoute_par.id}`" if ajoute_par else "inconnu"},
            )
            return

        # Le propriétaire et les vrais responsables « Gérer le serveur »
        # ne peuvent être expulsés pour ancienneté ni mutés sur leur arrivée.
        # Les bots gardent la politique antibot, sans passe-droit automatique.
        if not member.bot and (
            member.id == member.guild.owner_id
            or can_bypass_message_filters(member)
        ):
            return

        account_age = (discord.utils.utcnow() - member.created_at).days
        default_avatar = _member_has_default_avatar(member)
        track_joins = bool(conf.get("join_gate") or conf.get("antiraid"))
        fast_count = self.join_tracker.ajouter(member.guild.id) if track_joins else 0
        slow_count = self.slow_join_tracker.ajouter(member.guild.id) if track_joins else 0
        # Fenêtre parallèle réservée aux comptes récents : c'est leur
        # proportion, pas le nombre brut d'arrivées, qui distingue un raid
        # d'une vague de nouveaux membres après une vidéo.
        neufs_count = (
            self.new_account_tracker.ajouter(member.guild.id)
            if track_joins and account_age < RAID_COMPTE_NEUF_JOURS
            else 0
        )

        if conf.get("join_gate"):
            join_points = 0
            join_reasons: list[str] = []
            if account_age < JOIN_GATE_RECENT_ACCOUNT_DAYS:
                join_points += 45
                join_reasons.append(f"compte {account_age}j")
            if default_avatar:
                join_points += JOIN_GATE_DEFAULT_AVATAR_POINTS
                join_reasons.append("avatar par défaut")
            if fast_count >= max(3, RAID_JOIN_THRESHOLD // 2):
                join_points += 25
                join_reasons.append(f"arrivées rapides {fast_count}/{RAID_JOIN_WINDOW}s")
            if slow_count >= max(20, RAID_SLOW_THRESHOLD // 2):
                join_points += 20
                join_reasons.append(f"arrivées lentes {slow_count}/{RAID_SLOW_WINDOW // 60}min")
            if join_points:
                score = await self.add_risk_signal(
                    member.guild,
                    member.id,
                    "join_gate",
                    join_points,
                    reason=", ".join(join_reasons),
                    target=member,
                )
                # Les métadonnées passives d'un join (ancienneté, avatar,
                # afflux de membres) ne prouvent pas qu'un utilisateur spamme.
                # Enregistrer le score pour la surveillance, mais ne JAMAIS
                # timeout sur la seule base de ce score : les sanctions sont
                # réservées à des infractions de messages/actions confirmées.
                if score >= RISK_ACTION_THRESHOLD:
                    logger.info(
                        "Anti-raid Join Gate : score élevé non sanctionnant guild=%s user=%s score=%s",
                        member.guild.id, member.id, round(score, 1),
                    )

        if conf["antiaccount"]:
            if account_age < 7:
                erreur = ""
                try:
                    await member.kick(reason="AutoMod : compte créé il y a moins de 7 jours")
                    await self.add_risk_signal(member.guild, member.id, "recent_account", 50, reason="Compte très récent expulsé", target=member)
                except discord.HTTPException as exc:
                    erreur = f"Discord a refusé l'expulsion ({exc.status}) : rôle de SentriX trop bas ou permission manquante."
                await self._journal_arrivee(
                    member, titre="Compte trop récent", protection="Anti-comptes récents",
                    regle="Compte créé il y a moins de 7 jours",
                    motif=f"Compte créé <t:{int(member.created_at.timestamp())}:R> ({account_age} jour(s)).",
                    action="Membre expulsé (il pourra revenir quand son compte aura 7 jours)", erreur=erreur,
                )
                return

        if conf["antiraid"]:
            # Raid coordonné (comptes au nom presque identique) : alerte, jamais de sanction.
            try:
                from cogs import raid_protect

                await raid_protect.sur_arrivee(self.bot, member)
            except Exception:
                logger.exception("Détection de raid coordonné impossible guild=%s", member.guild.id)
            arrivees = fast_count
            arrivees_lentes = slow_count
            seuil = seuil_raid_rapide(getattr(member.guild, "member_count", None))
            velocite = velocite_ponderee(arrivees, neufs_count)
            # Le seuil historique reste un PLAFOND : on ne devient jamais plus
            # laxiste qu'avant, seulement plus strict quand le serveur est petit
            # ou quand les arrivants sont des comptes fraîchement créés.
            raid_rapide = velocite >= min(seuil, RAID_JOIN_THRESHOLD) or arrivees >= RAID_JOIN_THRESHOLD
            raid_lent = arrivees_lentes >= RAID_SLOW_THRESHOLD
            if raid_rapide or raid_lent:
                # On ne journalise pas 100 alertes identiques pendant un afflux
                # prolongé. En revanche la protection continue pour les
                # arrivées suivantes et le mode rapide peut toujours agir.
                tick = time.monotonic()
                last = self._raid_alert_last.get(member.guild.id, -9999.0)
                if len(self._raid_alert_last) > 4096:
                    self._raid_alert_last.clear()
                should_log = tick - last >= 60
                if should_log:
                    self._raid_alert_last[member.guild.id] = tick
                e = embeds.log_entry(
                    "🚨 Raid potentiel détecté", config.COLOR_WARNING,
                    raison=(
                        "Afflux massif de nouveaux membres observé"
                        if raid_rapide
                        else "Arrivées trop nombreuses sur une longue période "
                             "(raid lent, sous le seuil de l'afflux instantané)"
                    ),
                    extra={
                        "Statut": "Détection — réponse automatique selon vos réglages",
                        "Protection": "Anti-raid",
                        "Règle": "Afflux rapide d'arrivées" if raid_rapide else "Raid lent (arrivées sur 10 min)",
                        "Date": f"<t:{int(time.time())}:F> · <t:{int(time.time())}:R>",
                        f"Arrivées en {RAID_JOIN_WINDOW} s": str(arrivees),
                        f"Arrivées en {RAID_SLOW_WINDOW // 60} min": str(arrivees_lentes),
                        f"Comptes de moins de {RAID_COMPTE_NEUF_JOURS} j": f"{neufs_count} sur {arrivees}",
                        "Seuil du serveur": (
                            f"{min(seuil, RAID_JOIN_THRESHOLD)} "
                            f"(vélocité pondérée {velocite:.0f})"
                        ),
                        "Dernier arrivé": f"{member.mention} · `{member.id}`",
                        "Mesures possibles": "`/protection raid pause` · `/protection lockdown`",
                    },
                )
                if should_log:
                    await self.log_action(member.guild, e)
                await self.add_risk_signal(member.guild, member.id, "raid_join_velocity", 35, reason="Arrivée pendant un raid potentiel", target=member)
                # Une vague LENTE de 60 comptes/10 min peut aussi résulter
                # d'un événement légitime. On alerte, mais le changement
                # global de vérification nécessite un raid RAPIDE confirmé.
                # Réponse automatique : relever le niveau de vérification du serveur
                # freine immédiatement les faux comptes fraîchement créés, sans avoir
                # à verrouiller manuellement tous les salons.
                if raid_rapide:
                    # Raid Protect (opt-in) : pause native des invitations, levée
                    # automatiquement par Discord ; aucun membre n'est sanctionné.
                    try:
                        from cogs import raid_protect

                        await raid_protect.sur_raid_detecte(self.bot, member.guild)
                    except Exception:
                        logger.exception("Pause Raid Protect impossible guild=%s", member.guild.id)
                    # Sauvegarde du niveau précédent avant édition et expiration
                    # 15 minutes après le dernier afflux rapide. En cas de
                    # modification manuelle, le snapshot est invalidé.
                    try:
                        elevated = await self._raid_recovery.protect(member.guild)
                    except Exception:
                        elevated = False
                        logger.exception(
                            "Anti-raid : sauvegarde/hausse du niveau impossible guild=%s",
                            member.guild.id,
                        )
                    if elevated and should_log:
                        await self.log_action(
                            member.guild,
                            embeds.log_entry(
                                "🔒 Niveau de vérification provisoirement relevé",
                                config.COLOR_WARNING,
                                raison="Afflux rapide : niveau maximal pendant au moins 15 minutes. "
                                       "Restauration seulement si aucune modification manuelle n'est détectée.",
                            ),
                        )
                    elif should_log:
                        # `protect` rend False quand le serveur est DÉJÀ au niveau
                        # maximal — un choix de l'administrateur, que SentriX ne
                        # s'approprie pas. Mais alors la seule réponse automatique
                        # au raid ne fait rien, et jusqu'ici elle ne le disait pas :
                        # le propriétaire croyait SentriX en train d'agir pendant
                        # qu'il n'agissait pas. Le silence était le vrai défaut.
                        await self.log_action(
                            member.guild,
                            embeds.log_entry(
                                "⚠️ Raid détecté : aucune hausse possible",
                                config.COLOR_WARNING,
                                raison=(
                                    "La vérification du serveur est déjà au maximum, SentriX ne peut "
                                    "pas la relever davantage. Les arrivées continuent d'être notées "
                                    "comme suspectes, mais la protection automatique s'arrête là.\n"
                                    "À faire maintenant : `/protection lockdown` pour verrouiller les "
                                    "salons, puis `/protection unlock` une fois la vague passée."
                                ),
                            ),
                        )
                # Évite de redéclencher la même alerte à chaque nouvel arrivant tant que le raid dure.
                self.join_tracker.reinitialiser(member.guild.id)
                if raid_lent:
                    # Sinon l'alerte « raid lent » repartirait à chaque arrivée
                    # suivante tant que la fenêtre de dix minutes reste pleine.
                    self.slow_join_tracker.reinitialiser(member.guild.id)

    async def _journal_securite(self, guild: discord.Guild, *, titre: str, auteur, protection: str,
                                regle: str, motif: str, action: str, echec: bool = False,
                                extra: dict | None = None) -> discord.Embed:
        """Carte complète d'une modification dangereuse du serveur (anti-nuke, vanity,
        prune, permissions) : statut, auteur, règle, motif, date, action réelle."""
        maintenant = int(time.time())
        auteur_id = getattr(auteur, "id", auteur)
        champs = {
            "Statut": "Échec — l'action prévue n'a pas pu être appliquée" if echec else "Action réussie",
            "Compte": (f"<@{auteur_id}> · `{auteur_id}` (auteur suspecté)" if auteur_id
                       else "Auteur introuvable dans le journal d'audit"),
            "Protection": protection,
            "Règle": regle,
            "Motif": motif,
            "Date": f"<t:{maintenant}:F> · <t:{maintenant}:R>",
            "Action": action,
            **(extra or {}),
        }
        e = embeds.log_entry(titre, config.COLOR_ERROR, cible=auteur if hasattr(auteur, "id") else None,
                             cible_label="Membre", extra=champs)
        try:
            await self.log_action(guild, e)
        except Exception:
            logger.exception("Journal de sécurité impossible guild=%s", guild.id)
        return e

    async def _journal_arrivee(self, member: discord.Member, *, titre: str, protection: str, regle: str,
                               motif: str, action: str, erreur: str = "", extra: dict | None = None) -> None:
        """Carte complète d'une protection à l'arrivée : réussite ET échec sont journalisés
        (avant le 29/10/2026, une expulsion refusée par Discord ne laissait aucune trace)."""
        maintenant = int(time.time())
        champs = {
            "Statut": "Échec — l'action prévue n'a pas pu être appliquée" if erreur
                      else "Action réussie",
            # Le membre est souvent déjà expulsé : l'en-tête ne peut plus le résoudre.
            "Compte": f"{member.mention} · `{member.id}` · créé <t:{int(member.created_at.timestamp())}:R>",
            "Protection": protection,
            "Règle": regle,
            "Motif": motif,
            "Date": f"<t:{maintenant}:F> · <t:{maintenant}:R>",
            "Action": f"{action} — non appliquée" if erreur else action,
            **(extra or {}),
        }
        if erreur:
            champs["Erreur"] = erreur
        e = embeds.log_entry(titre, config.COLOR_ERROR, cible=member, cible_label="Membre", extra=champs)
        try:
            await self.log_action(member.guild, e)
        except Exception:
            logger.exception("Journal d'arrivée AutoMod impossible guild=%s", member.guild.id)

    # ---------------------------------------------------------------- ANTI-NUKE

    async def record_nuke_action(self, guild: discord.Guild, actor_id: int) -> bool:
        """Retourne True si le seuil d'actions destructrices est dépassé pour cet auteur."""
        return self.nuke_tracker.ajouter((guild.id, actor_id)) >= NUKE_ACTION_THRESHOLD

    async def get_audit_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None):
        """Retrouve l'auteur d'une action récente via les logs d'audit (nécessite la permission adéquate).

        BUG CORRIGÉ : cette fonction ne rattrapait avant que discord.Forbidden (permission
        manquante). Or elle est appelée par TOUS les écouteurs de logs (salon créé/supprimé,
        rôle créé/supprimé, membre expulsé, anti-nuke...) AVANT l'envoi du log lui-même. La
        moindre erreur réseau/API Discord (429, 5xx, timeout) pendant guild.audit_logs()
        faisait planter silencieusement l'écouteur entier : le log correspondant n'était
        alors JAMAIS envoyé, sans aucune trace nulle part. C'est une cause plausible des
        "logs qui ne marchent pas de temps en temps" signalés sans réussir à reproduire.
        On rattrape maintenant discord.HTTPException (qui couvre aussi Forbidden) et on
        trace l'échec dans les logs du process, comme le fait déjà helpers.send_log()."""
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > 15:
                    continue
                if target_id is None or (audit_entries.cible_id(entry) == target_id):
                    return entry.user
        except discord.HTTPException as exc:
            logger.warning(
                "get_audit_actor: échec de lecture de l'audit log ('%s') sur %s (%s) : %s. "
                "Le log correspondant sera envoyé sans auteur identifié plutôt que d'être perdu.",
                action, guild.name, guild.id, exc,
            )
            return None
        return None

    async def is_antinuke_exempt(self, guild: discord.Guild, actor: discord.abc.User) -> bool:
        # Sans auteur fiable dans l'audit log, ne sanctionne personne au hasard.
        if actor is None:
            return True
        # Le bot SentriX peut effectuer des actions légitimes. En revanche, les autres
        # bots ne sont plus exemptés automatiquement : un bot malveillant peut nuker.
        if self.bot.user and actor.id == self.bot.user.id:
            return True
        if actor.id == guild.owner_id:
            return True
        # Un administrateur du serveur gère salons et rôles en connaissance de
        # cause : le bannir pour trois suppressions coupait le serveur de son
        # propre staff. Un BOT administrateur reste surveillé — un bot piraté
        # est précisément le scénario de nuke le plus courant.
        member = _as_member(actor, guild)
        if (
            isinstance(member, discord.Member)
            and not member.bot
            and getattr(member.guild_permissions, "administrator", False) is True
        ):
            return True
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (guild.id, actor.id)
        )
        return row is not None

    async def punish_nuker(self, guild: discord.Guild, actor_id: int, reason: str):
        member = guild.get_member(actor_id)
        action_taken = "aucune action possible (permissions insuffisantes)"
        if member:
            dangerous_roles = [
                r for r in member.roles
                if r != guild.default_role and any(getattr(r.permissions, p, False) for p in DANGEROUS_PERMS)
            ]
            try:
                if dangerous_roles:
                    await member.remove_roles(*dangerous_roles, reason=f"AutoMod anti-nuke : {reason}")
            except discord.Forbidden:
                pass
            # Un nuke en cours justifie une réponse décisive : on bannit directement
            # (empêche de revenir avec une nouvelle invitation), avec repli sur un kick
            # si le bot n'a pas la permission de bannir.
            try:
                await guild.ban(discord.Object(id=actor_id), reason=f"AutoMod anti-nuke : {reason}", delete_message_seconds=3600)
                action_taken = "banni du serveur"
            except discord.Forbidden:
                try:
                    await member.kick(reason=f"AutoMod anti-nuke : {reason}")
                    action_taken = "expulsé du serveur (le bot n'a pas la permission de bannir)"
                except discord.Forbidden:
                    action_taken = "rôles à risque retirés, mais impossible de le sanctionner davantage (permissions insuffisantes)"
        e = await self._journal_securite(
            guild, titre="Anti-nuke déclenché", auteur=member or actor_id, protection="Anti-nuke",
            regle=f"Plus de {NUKE_ACTION_THRESHOLD - 1} actions destructrices en peu de temps", motif=reason,
            action=f"Auteur {action_taken}", echec="impossible de le sanctionner" in str(action_taken),
        )
        try:
            owner = guild.owner or await guild.fetch_member(guild.owner_id)
            if owner:
                await panels.envoyer(owner, panels.depuis_embed(e))
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass

    async def _handle_security_actor(
        self,
        guild: discord.Guild,
        *,
        actor: discord.abc.User | None,
        reason: str,
        signal: str,
        points: int,
        punish: bool = True,
    ) -> bool:
        if await self.is_antinuke_exempt(guild, actor):
            return False
        await self.add_risk_signal(guild, actor.id, signal, points, reason=reason, target=actor)
        if punish and await self.record_nuke_action(guild, actor.id):
            await self.punish_nuker(guild, actor.id, reason)
        return True

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        before_level = getattr(before, "verification_level", None)
        after_level = getattr(after, "verification_level", None)
        if before_level is not None and after_level is not None and before_level != after_level:
            await self._raid_recovery.on_guild_level_change(before, after)
        before_code = getattr(before, "vanity_url_code", None)
        after_code = getattr(after, "vanity_url_code", None)
        if before_code == after_code:
            return
        conf = await self.get_automod_cached(after.id)
        if not conf or not conf.get("security_vanity"):
            return
        actor = await self.get_audit_actor(after, discord.AuditLogAction.guild_update)
        suspicious = await self._handle_security_actor(
            after,
            actor=actor,
            reason="Modification suspecte du vanity URL",
            signal="vanity_update",
            points=80,
        )
        if not suspicious:
            return
        if before_code and before_code != after_code:
            try:
                await after.edit(vanity_code=before_code, reason="SentriX vanity guard : restauration du vanity URL")
                await self._journal_securite(
                    after, titre="Lien d'invitation personnalisé restauré", auteur=actor,
                    protection="Garde du lien personnalisé", regle="Modification du lien par un compte non autorisé",
                    motif=f"`{after_code or 'aucun'}` remis en `{before_code}`", action="Ancien lien restauré",
                )
            except (discord.Forbidden, discord.HTTPException, TypeError):
                await self._journal_securite(
                    after, titre="Lien d'invitation personnalisé modifié", auteur=actor,
                    protection="Garde du lien personnalisé", regle="Modification du lien par un compte non autorisé",
                    motif=f"`{before_code}` changé en `{after_code or 'aucun'}`",
                    action="Restauration refusée par Discord : remettez le lien à la main", echec=True,
                )

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = getattr(entry, "guild", None)
        if guild is None:
            return
        conf = await self.get_automod_cached(guild.id)
        if not conf:
            return
        action = getattr(entry, "action", None)
        if conf.get("security_prune") and action == getattr(discord.AuditLogAction, "member_prune", None):
            actor = getattr(entry, "user", None)
            await self._handle_security_actor(
                guild,
                actor=actor,
                reason="Prune de membres détecté",
                signal="member_prune",
                points=90,
            )
            nombre = getattr(getattr(entry, "extra", None), "members_removed", None)
            await self._journal_securite(
                guild, titre="Purge de membres détectée", auteur=actor, protection="Garde des purges",
                regle="Purge de membres inactifs (journal d'audit)",
                motif=f"{nombre} membres retirés." if nombre else "Purge vue dans le journal d'audit.",
                action="Auteur signalé au moteur de risque (sanction seulement si le seuil anti-nuke est atteint)",
            )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        conf = await self.get_automod_cached(role.guild.id)
        if not conf or not conf.get("security_permissions"):
            return
        dangerous = _dangerous_perm_names(role.permissions)
        if not dangerous:
            return
        actor = await self.get_audit_actor(role.guild, discord.AuditLogAction.role_create, role.id)
        suspicious = await self._handle_security_actor(
            role.guild,
            actor=actor,
            reason="Création d'un rôle avec permissions dangereuses",
            signal="dangerous_role_create",
            points=55,
        )
        if not suspicious:
            return
        try:
            await role.edit(permissions=discord.Permissions.none(), reason="SentriX permission guard : permissions dangereuses retirées")
            action = "Permissions retirées"
        except (discord.Forbidden, discord.HTTPException):
            action = "Retrait impossible"
        await self._journal_securite(
            role.guild, titre="Rôle à permissions dangereuses", auteur=actor, protection="Garde des permissions",
            regle="Création d'un rôle avec des permissions dangereuses", motif=", ".join(dangerous),
            action="Permissions dangereuses retirées du rôle" if action == "Permissions retirées"
                   else "Retrait refusé par Discord : vérifiez le rôle à la main",
            echec=action != "Permissions retirées",
            extra={"Rôle": f"{role.mention} · `{role.id}`"},
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        conf = await self.get_automod_cached(channel.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if await self.is_antinuke_exempt(channel.guild, actor):
            return
        if await self.record_nuke_action(channel.guild, actor.id):
            await self.punish_nuker(channel.guild, actor.id, "Suppression massive de salons")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        conf = await self.get_automod_cached(role.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        if await self.is_antinuke_exempt(role.guild, actor):
            return
        if await self.record_nuke_action(role.guild, actor.id):
            await self.punish_nuker(role.guild, actor.id, "Suppression massive de rôles")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        # Un "nuke" ne supprime pas forcément les salons : il arrive très souvent qu'il les
        # renomme en masse (ex: "NUKED-BY-...") sans rien supprimer, ce qui passait avant
        # complètement inaperçu par l'anti-nuke (qui ne regardait que les suppressions).
        overwrites_changed = before.overwrites != after.overwrites
        if before.name == after.name and not overwrites_changed:
            return
        conf = await self.get_automod_cached(after.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
        if await self.is_antinuke_exempt(after.guild, actor):
            return
        reason = "Modification massive de permissions de salons" if overwrites_changed else "Renommage massif de salons"
        if conf.get("security_permissions") and overwrites_changed:
            await self.add_risk_signal(after.guild, actor.id, "channel_permission_update", 45, reason=reason, target=actor)
            try:
                await after.edit(overwrites=before.overwrites, reason="SentriX permission guard : restauration permissions salon")
            except (discord.Forbidden, discord.HTTPException):
                pass
        if await self.record_nuke_action(after.guild, actor.id):
            await self.punish_nuker(after.guild, actor.id, reason)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        # Même logique que ci-dessus, pour les rôles : renommage massif ou octroi soudain
        # de permissions dangereuses (élévation de privilèges avant un nuke).
        name_changed = before.name != after.name
        perms_escalated = before.permissions != after.permissions and any(
            not getattr(before.permissions, p, False) and getattr(after.permissions, p, False) for p in DANGEROUS_PERMS
        )
        if not name_changed and not perms_escalated:
            return
        conf = await self.get_automod_cached(after.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(after.guild, discord.AuditLogAction.role_update, after.id)
        if await self.is_antinuke_exempt(after.guild, actor):
            return
        reason = "Élévation de permissions suspecte sur un rôle" if perms_escalated else "Renommage massif de rôles"
        if conf.get("security_permissions") and perms_escalated:
            gained = [
                p for p in DANGEROUS_PERMS
                if not getattr(before.permissions, p, False) and getattr(after.permissions, p, False)
            ]
            await self.add_risk_signal(after.guild, actor.id, "role_permission_escalation", 60, reason=reason, target=actor)
            try:
                await after.edit(permissions=before.permissions, reason="SentriX permission guard : restauration permissions rôle")
                restored = "oui"
            except (discord.Forbidden, discord.HTTPException):
                restored = "non"
            await self._journal_securite(
                after.guild, titre="Permissions dangereuses bloquées", auteur=actor,
                protection="Garde des permissions", regle="Ajout de permissions dangereuses à un rôle",
                motif=f"{reason} : {', '.join(gained)}",
                action="Anciennes permissions du rôle restaurées" if restored == "oui"
                       else "Restauration refusée par Discord : vérifiez le rôle à la main",
                echec=restored != "oui",
                extra={"Rôle": f"{after.mention} · `{after.id}`"},
            )
        if await self.record_nuke_action(after.guild, actor.id):
            await self.punish_nuker(after.guild, actor.id, reason)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        conf = await self.get_automod_cached(guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(guild, discord.AuditLogAction.ban, user.id)
        if await self.is_antinuke_exempt(guild, actor):
            return
        if await self.record_nuke_action(guild, actor.id):
            await self.punish_nuker(guild, actor.id, "Bannissements massifs")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
