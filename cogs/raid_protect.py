"""Raid Protect : réponses anti-raid proportionnées, toutes désactivées par défaut.

Demande de Jayden du 29/10/2026 : une vraie amélioration de la protection
anti-raid, sans qu'aucune protection ne s'active sans le choix explicite du
responsable du serveur, et sans sanctionner injustement les membres.

Ce que SentriX avait déjà (cogs/automod, security_runtime_hardening,
security_v2_runtime) : vélocité d'arrivée adaptative, comptes neufs, anti-bot,
anti-nuke avec retour en arrière (webhooks compris), +panic, quarantaine,
hausse provisoire du niveau de vérification. Ce qui manquait, ajouté ici :

- **pause native des invitations et des MP** (API Discord « incident
  actions », 24 h maximum, levée automatiquement par Discord) : en mode
  urgence manuel, et en réponse automatique à un raid rapide si le serveur
  l'a choisi ; personne n'est sanctionné, les arrivées sont seulement
  suspendues ;
- **garde des webhooks** : un webhook entrant qui inonde un salon voit ses
  messages retirés et est supprimé, sauf s'il a été créé par le propriétaire
  ou une personne de confiance (alerte seulement) ;
- **raid coordonné** : plusieurs comptes au nom presque identique qui
  arrivent ensemble produisent une alerte, sans sanction automatique.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
import unicodedata
from collections import defaultdict, deque

import discord
from discord.ext import commands

import config
from utils import checks, embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.raid-protect")

TABLE = """
CREATE TABLE IF NOT EXISTS raid_protect_settings (
    guild_id INTEGER PRIMARY KEY,
    auto_pause INTEGER NOT NULL DEFAULT 0,
    pause_minutes INTEGER NOT NULL DEFAULT 60,
    pause_dms INTEGER NOT NULL DEFAULT 0,
    webhook_guard INTEGER NOT NULL DEFAULT 0,
    webhook_limit INTEGER NOT NULL DEFAULT 10
)
"""

#: Discord plafonne la pause des invitations et des MP à 24 h.
PAUSE_MAX_MIN = 24 * 60
PAUSE_MIN_MIN = 5
WEBHOOK_FENETRE_S = 10.0
WEBHOOK_LIMITE_MIN = 5
WEBHOOK_LIMITE_MAX = 60
#: Raid coordonné : N comptes au nom presque identique en quelques minutes.
NOMS_FENETRE_S = 180.0
NOMS_SEUIL = 4

DEFAUTS = {"auto_pause": 0, "pause_minutes": 60, "pause_dms": 0, "webhook_guard": 0, "webhook_limit": 10}


async def reglages(db, guild_id: int) -> dict:
    row = await db.fetchone("SELECT * FROM raid_protect_settings WHERE guild_id=?", (int(guild_id),))
    out = dict(DEFAUTS)
    if row:
        out.update({k: row[k] for k in DEFAUTS})
    return out


async def enregistrer(db, guild_id: int, **valeurs) -> dict:
    actuel = await reglages(db, guild_id)
    actuel.update({k: v for k, v in valeurs.items() if k in DEFAUTS})
    await db.execute(
        "INSERT INTO raid_protect_settings(guild_id, auto_pause, pause_minutes, pause_dms, webhook_guard, webhook_limit) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET auto_pause=excluded.auto_pause, "
        "pause_minutes=excluded.pause_minutes, pause_dms=excluded.pause_dms, "
        "webhook_guard=excluded.webhook_guard, webhook_limit=excluded.webhook_limit",
        (int(guild_id), int(actuel["auto_pause"]), int(actuel["pause_minutes"]), int(actuel["pause_dms"]),
         int(actuel["webhook_guard"]), int(actuel["webhook_limit"])),
    )
    return actuel


def borne_minutes(minutes: int) -> int:
    return max(PAUSE_MIN_MIN, min(PAUSE_MAX_MIN, int(minutes)))


async def mettre_en_pause(guild: discord.Guild, minutes: int, *, invitations: bool = True, mp: bool = False,
                         raison: str) -> tuple[bool, dt.datetime | None, str]:
    """Pause native Discord, levée automatiquement à l'échéance. Rien n'est sanctionné."""
    me = guild.me
    if me is None or not me.guild_permissions.manage_guild:
        return False, None, "SentriX n'a pas la permission « Gérer le serveur »."
    fin = discord.utils.utcnow() + dt.timedelta(minutes=borne_minutes(minutes))
    champs = {}
    if invitations:
        champs["invites_disabled_until"] = fin
    if mp:
        champs["dms_disabled_until"] = fin
    if not champs:
        return False, None, "Rien à mettre en pause."
    try:
        await guild.edit(reason=f"SentriX Raid Protect : {raison}"[:500], **champs)
    except discord.HTTPException as exc:
        return False, None, f"Discord a refusé la pause ({exc.status})."
    return True, fin, ""


async def reprendre(guild: discord.Guild, *, raison: str) -> tuple[bool, str]:
    me = guild.me
    if me is None or not me.guild_permissions.manage_guild:
        return False, "SentriX n'a pas la permission « Gérer le serveur »."
    try:
        await guild.edit(reason=f"SentriX Raid Protect : {raison}"[:500],
                         invites_disabled_until=None, dms_disabled_until=None)
    except discord.HTTPException as exc:
        return False, f"Discord a refusé la reprise ({exc.status})."
    return True, ""


async def _journal(bot, guild: discord.Guild, titre: str, raison: str, extra: dict) -> None:
    automod = bot.get_cog("Automod")
    embed = embeds.log_entry(titre, config.COLOR_WARNING, raison=raison, extra=extra)
    try:
        if automod is not None:
            await automod.log_action(guild, embed, "antiraid")
        else:
            from utils import helpers

            await helpers.send_log(bot, guild, "antiraid", embed)
    except Exception:
        logger.exception("Journal Raid Protect impossible guild=%s", guild.id)


# --------------------------------------------------------------- RÉPONSE AU RAID

_derniere_pause: dict[int, float] = {}


async def sur_raid_detecte(bot, guild: discord.Guild) -> bool:
    """Appelé par l'anti-raid sur un afflux RAPIDE confirmé. N'agit que si le
    serveur a activé la pause automatique ; une seule pause par vague."""
    try:
        conf = await reglages(bot.db, guild.id)
    except Exception:
        logger.exception("Réglages Raid Protect illisibles guild=%s", guild.id)
        return False
    if not conf["auto_pause"]:
        return False
    if guild.invites_paused() and (not conf["pause_dms"] or guild.dms_paused()):
        return False
    maintenant = time.monotonic()
    if maintenant - _derniere_pause.get(guild.id, -1e9) < 120:
        return False
    _derniere_pause[guild.id] = maintenant
    ok, fin, erreur = await mettre_en_pause(
        guild, conf["pause_minutes"], invitations=True, mp=bool(conf["pause_dms"]), raison="raid détecté",
    )
    extra = {
        "Statut": "Action réussie" if ok else "Échec",
        "Mesure": "Invitations en pause" + (" et MP entre membres non amis en pause" if conf["pause_dms"] else ""),
        "Fin": f"<t:{int(fin.timestamp())}:F> · <t:{int(fin.timestamp())}:R>" if fin else "—",
        "Annuler": "`/protection raid resume`",
    }
    if erreur:
        extra["Erreur"] = erreur
    await _journal(bot, guild, "Raid Protect — arrivées suspendues" if ok else "Raid Protect — pause impossible",
                   "Afflux rapide confirmé : pause native Discord, aucun membre sanctionné.", extra)
    return ok


# --------------------------------------------------------------- RAID COORDONNÉ

_arrivees_noms: dict[int, deque] = defaultdict(lambda: deque(maxlen=200))
_alerte_noms: dict[int, float] = {}


def nom_de_base(nom: str) -> str:
    """« raider_0421 », « Raider-77 », « r a i d e r » -> « raider »."""
    texte = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().casefold()
    texte = re.sub(r"[^a-z]", "", texte)
    return texte[:12]


def noter_arrivee(guild_id: int, nom: str, maintenant: float | None = None) -> tuple[str, int] | None:
    """Retourne (base, nombre) quand NOMS_SEUIL comptes au même nom de base arrivent
    dans la fenêtre ; une alerte par base et par fenêtre."""
    maintenant = time.monotonic() if maintenant is None else maintenant
    base = nom_de_base(nom)
    if len(base) < 3:
        return None
    file = _arrivees_noms[int(guild_id)]
    file.append((maintenant, base))
    while file and maintenant - file[0][0] > NOMS_FENETRE_S:
        file.popleft()
    nombre = sum(1 for _, b in file if b == base)
    if nombre < NOMS_SEUIL:
        return None
    cle = hash((guild_id, base))
    if maintenant - _alerte_noms.get(cle, -1e9) < NOMS_FENETRE_S:
        return None
    _alerte_noms[cle] = maintenant
    if len(_arrivees_noms) > 5000:
        _arrivees_noms.clear()
    return base, nombre


async def sur_arrivee(bot, member: discord.Member) -> None:
    """Appelé par l'anti-raid (actif) à chaque arrivée : alerte, jamais de sanction."""
    trouve = noter_arrivee(member.guild.id, member.name)
    if trouve is None:
        return
    base, nombre = trouve
    await _journal(
        bot, member.guild, "Raid coordonné probable",
        f"{nombre} comptes au nom presque identique (« {base} ») sont arrivés en moins de "
        f"{int(NOMS_FENETRE_S // 60)} minutes. Aucune sanction automatique : vérifiez-les.",
        {"Statut": "Détection seule", "Dernier arrivé": f"{member.mention} · `{member.id}`",
         "Compte créé": f"<t:{int(member.created_at.timestamp())}:R>",
         "Mesures possibles": "`/protection raid pause` · `/moderation case`"},
    )


# --------------------------------------------------------------- GARDE WEBHOOKS

_rafales_webhook: dict[int, deque] = defaultdict(lambda: deque(maxlen=200))
_webhooks_traites: dict[int, float] = {}


async def _createur_de_confiance(bot, guild: discord.Guild, user) -> bool:
    if user is None:
        return False
    if user.id == guild.owner_id or (bot.user and user.id == bot.user.id):
        return True
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM antinuke_whitelist WHERE guild_id=? AND user_id=?", (guild.id, user.id)
        )
    except Exception:
        row = None
    return row is not None


async def surveiller_webhook(bot, message: discord.Message) -> bool:
    """True si le message appartient à une inondation de webhook traitée ici."""
    webhook_id = getattr(message, "webhook_id", None)
    guild = message.guild
    if not webhook_id or guild is None:
        return False
    try:
        conf = await reglages(bot.db, guild.id)
    except Exception:
        return False
    if not conf["webhook_guard"]:
        return False
    limite = max(WEBHOOK_LIMITE_MIN, min(WEBHOOK_LIMITE_MAX, int(conf["webhook_limit"])))
    maintenant = time.monotonic()
    file = _rafales_webhook[int(webhook_id)]
    file.append((maintenant, message.id, message.channel.id))
    while file and maintenant - file[0][0] > WEBHOOK_FENETRE_S:
        file.popleft()
    if len(file) <= limite:
        return False
    if maintenant - _webhooks_traites.get(int(webhook_id), -1e9) < 60:
        return True
    _webhooks_traites[int(webhook_id)] = maintenant
    ids = [mid for _, mid, cid in file if cid == message.channel.id]
    file.clear()

    statut, mesure, erreur = "Détection seule", "Alerte", ""
    webhook = None
    try:
        webhook = await bot.fetch_webhook(int(webhook_id))
    except discord.HTTPException:
        erreur = "Webhook introuvable ou permission « Gérer les webhooks » manquante."
    if webhook is not None and webhook.type != discord.WebhookType.incoming:
        return False  # salon suivi ou application : pas un webhook qu'on peut juger ici
    retires = 0
    if guild.me and message.channel.permissions_for(guild.me).manage_messages and ids:
        try:
            await message.channel.delete_messages([discord.Object(id=i) for i in ids[-100:]],
                                                  reason="SentriX Raid Protect : inondation par webhook")
            retires = len(ids[-100:])
        except discord.HTTPException:
            pass
    if webhook is not None:
        if await _createur_de_confiance(bot, guild, webhook.user):
            mesure = "Alerte seulement (webhook créé par une personne de confiance)"
        else:
            try:
                await webhook.delete(reason="SentriX Raid Protect : inondation par webhook")
                statut, mesure = "Action réussie", "Webhook supprimé"
            except discord.HTTPException:
                statut, erreur = "Échec", "Discord a refusé la suppression du webhook."
    createur = getattr(webhook, "user", None)
    extra = {
        "Statut": statut,
        "Webhook": f"{getattr(webhook, 'name', None) or 'inconnu'} · `{webhook_id}`",
        "Créé par": f"{createur.mention} · `{createur.id}`" if createur else "inconnu",
        "Salon": f"<#{message.channel.id}>",
        "Débit": f"plus de {limite} messages en {int(WEBHOOK_FENETRE_S)} s",
        "Messages retirés": str(retires),
        "Mesure": mesure,
    }
    if erreur:
        extra["Erreur"] = erreur
    await _journal(bot, guild, "Raid Protect — webhook abusif", "Inondation d'un salon par un webhook.", extra)
    return True


# --------------------------------------------------------------- COMMANDES

def _etat(valeur: int) -> str:
    return "activée" if valeur else "désactivée"


class RaidProtect(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        db = getattr(self.bot, "db", None)
        if db is not None:
            await db.execute(TABLE)

    @commands.group(name="raidprotect", invoke_without_command=True,
                    help="Raid Protect : réponses anti-raid, désactivées par défaut.")
    @commands.guild_only()
    @checks.is_owner_or_admin_for("securite")
    async def raidprotect(self, ctx: commands.Context):
        await self.raidprotect_status(ctx)

    @raidprotect.command(name="status", help="État de Raid Protect sur ce serveur.")
    async def raidprotect_status(self, ctx: commands.Context):
        conf = await reglages(self.bot.db, ctx.guild.id)
        automod = await self.bot.db.get_automod(ctx.guild.id) if hasattr(self.bot.db, "get_automod") else None
        antiraid = bool(automod and dict(automod).get("antiraid"))
        guild = ctx.guild
        pause = []
        if guild.invites_paused():
            pause.append(f"invitations jusqu'à <t:{int(guild.invites_paused_until.timestamp())}:t>")
        if guild.dms_paused():
            pause.append(f"MP jusqu'à <t:{int(guild.dms_paused_until.timestamp())}:t>")
        lignes = [
            panels.Ligne("Détection de raid", "active" if antiraid else "désactivée (`/security antiraid on`)"),
            panels.Ligne("Pause automatique", f"{_etat(conf['auto_pause'])} · {conf['pause_minutes']} min"
                         + (" · MP compris" if conf["pause_dms"] else "")),
            panels.Ligne("Garde des webhooks", f"{_etat(conf['webhook_guard'])} · {conf['webhook_limit']} messages / 10 s"),
            panels.Ligne("Pause en cours", " · ".join(pause) if pause else "aucune"),
        ]
        await panels.envoyer(ctx, panels.Panneau(
            titre="Raid Protect",
            sous_titre="Rien ne s'active sans votre choix. Les pauses sont levées automatiquement par Discord.",
            sections=[panels.Section("Réglages", lignes)],
            kind="info",
        ))

    @raidprotect.command(name="auto-pause", help="Pause automatique des arrivées pendant un raid rapide.")
    async def raidprotect_auto_pause(self, ctx: commands.Context, etat: str, minutes: int = 60, mp: str = "non"):
        actif = etat.strip().casefold() in {"on", "oui", "activer", "true", "1"}
        conf = await enregistrer(self.bot.db, ctx.guild.id, auto_pause=int(actif),
                                 pause_minutes=borne_minutes(minutes),
                                 pause_dms=int(mp.strip().casefold() in {"oui", "on", "true", "1"}))
        await panels.envoyer(ctx, panels.Panneau(
            titre="Pause automatique " + ("activée" if actif else "désactivée"),
            sous_titre=(f"Sur un raid rapide confirmé : invitations en pause {conf['pause_minutes']} min"
                        + (" et MP entre membres non amis aussi" if conf["pause_dms"] else "")
                        + ". Aucun membre n'est sanctionné." if actif else "Aucune pause ne sera faite automatiquement."),
            kind="success" if actif else "neutral",
        ))

    @raidprotect.command(name="pause", help="Mode urgence : met en pause les invitations (et les MP).")
    async def raidprotect_pause(self, ctx: commands.Context, minutes: int = 60, mp: str = "non"):
        ok, fin, erreur = await mettre_en_pause(
            ctx.guild, minutes, invitations=True, mp=mp.strip().casefold() in {"oui", "on", "true", "1"},
            raison=f"mode urgence lancé par {ctx.author}",
        )
        if not ok:
            return await panels.envoyer(ctx, panels.Panneau(titre="Pause impossible", sous_titre=erreur, kind="danger"))
        await panels.envoyer(ctx, panels.Panneau(
            titre="Arrivées en pause",
            sous_titre=f"Fin automatique <t:{int(fin.timestamp())}:R>. `/protection raid resume` pour lever avant.",
            kind="warning",
        ))
        await _journal(self.bot, ctx.guild, "Raid Protect — mode urgence", f"Lancé par {ctx.author.mention}.",
                       {"Statut": "Action réussie", "Fin": f"<t:{int(fin.timestamp())}:F>"})

    @raidprotect.command(name="resume", help="Lève la pause des invitations et des MP.")
    async def raidprotect_resume(self, ctx: commands.Context):
        ok, erreur = await reprendre(ctx.guild, raison=f"levée par {ctx.author}")
        await panels.envoyer(ctx, panels.Panneau(
            titre="Arrivées rétablies" if ok else "Reprise impossible",
            sous_titre="Invitations et MP fonctionnent de nouveau." if ok else erreur,
            kind="success" if ok else "danger",
        ))

    @raidprotect.command(name="webhook-guard", help="Supprime un webhook qui inonde un salon.")
    async def raidprotect_webhook_guard(self, ctx: commands.Context, etat: str, limite: int = 10):
        actif = etat.strip().casefold() in {"on", "oui", "activer", "true", "1"}
        limite = max(WEBHOOK_LIMITE_MIN, min(WEBHOOK_LIMITE_MAX, int(limite)))
        await enregistrer(self.bot.db, ctx.guild.id, webhook_guard=int(actif), webhook_limit=limite)
        await panels.envoyer(ctx, panels.Panneau(
            titre="Garde des webhooks " + ("activée" if actif else "désactivée"),
            sous_titre=(f"Au-delà de {limite} messages en 10 s, les messages sont retirés et le webhook supprimé "
                        "(alerte seulement s'il a été créé par le propriétaire ou une personne de confiance)."
                        if actif else "Aucun webhook ne sera supprimé automatiquement."),
            kind="success" if actif else "neutral",
        ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidProtect(bot))
