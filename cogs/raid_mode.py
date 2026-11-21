"""Mode raid : détecter, expulser en quelques secondes, puis faire le rapport (07/11/2026).

Demande : « que le raid mode détecte vraiment le flux de gens qui rejoignent,
puis kick tous les bots en quelques secondes, puis fasse son rapport ; le raid
mode englobe tout ce qui touche aux raids, pareil pour le nuke ».

Avant, un raid confirmé ne faisait que prévenir et relever le niveau de
vérification : les comptes du raid restaient sur le serveur. Désormais, quand
l'AutoMod confirme un afflux RAPIDE (cogs/automod.on_member_join) :

1. le mode raid s'active pour le serveur (RAID_MODE_DUREE, prolongé à chaque
   arrivée suspecte) ;
2. tous les comptes SUSPECTS arrivés pendant la vague (bots, comptes de moins de
   COMPTE_SUSPECT_JOURS jours, avatar par défaut) sont expulsés en parallèle ;
3. tant que le mode est actif, chaque nouvel arrivant suspect est expulsé dès
   son arrivée, et tout bot non autorisé aussi, même si l'anti-bot est coupé ;
4. l'anti-nuke se durcit : 2 actions destructrices suffisent au lieu de 3 ;
5. quand la vague retombe (CALME_SECONDES sans arrivée), UN rapport complet part
   dans les logs et en MP au propriétaire, avec la liste des comptes en fichier.

Jamais expulsés : le propriétaire, les comptes avec des permissions qui
contournent l'AutoMod, les bots autorisés, et les comptes anciens avec un avatar
(une vague légitime après une vidéo n'est pas vidée).
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import deque
from dataclasses import dataclass, field

import discord

logger = logging.getLogger("bot.raid-mode")

RAID_MODE_DUREE = 600          # le mode reste actif 10 min après la dernière arrivée suspecte
CALME_SECONDES = 45            # rapport quand plus personne n'arrive pendant 45 s
FENETRE_VAGUE = 60             # les arrivées des 60 dernières secondes forment la vague
COMPTE_SUSPECT_JOURS = 30
#: 21/11/2026 : 5 en parallèle, c'étaient dix vagues successives pour cinquante
#: comptes. Monté à 12 : discord.py gère lui-même les 429 avec un délai, donc
#: viser plus haut ne gagnerait rien et ferait surtout attendre le bucket.
EXPULSIONS_EN_PARALLELE = 12
NUKE_SEUIL_EN_RAID = 2
RAISON = "SentriX mode raid : compte arrivé pendant un raid"


@dataclass
class EtatRaid:
    debut: float
    jusqua: float
    derniere_arrivee: float
    arrivees: int = 0
    expulses: list = field(default_factory=list)      # (id, nom, motif)
    echecs: list = field(default_factory=list)        # (id, nom, erreur)
    neutralises: list = field(default_factory=list)   # expulsion refusée, mute appliqué
    epargnes: int = 0
    mesures: list = field(default_factory=list)
    rapport_tache: asyncio.Task | None = None
    #: 21/11/2026 : armé À LA MAIN par le staff, pas par un afflux détecté.
    #: « ça peut raid à tout moment » — on ne veut pas attendre que la vague
    #: soit là. En manuel, PERSONNE de nouveau n'entre : on n'exige plus qu'un
    #: compte soit suspect, puisque c'est un humain qui a décidé de fermer.
    manuel: bool = False


_arrivees: dict[int, deque] = {}
_etats: dict[int, EtatRaid] = {}


def actif(guild_id: int) -> bool:
    """Le mode raid tourne-t-il sur ce serveur.

    ``manuel`` passe AVANT l'échéance, et pas seulement pour faire joli. Une
    première version donnait au mode manuel une échéance de 24 h ; or
    ``declencher()`` et ``sur_arrivee()`` écrasent ``jusqua`` par
    ``maintenant + RAID_MODE_DUREE``. La toute première expulsion ramenait donc
    les 24 h à dix minutes, et après dix minutes de calme la porte se
    rouvrait — sans que personne ne l'ait décidé, et alors que le bouton
    promettait le contraire. Un mode armé à la main n'a pas d'échéance : il se
    désarme à la main.
    """
    etat = _etats.get(int(guild_id))
    if etat is None:
        return False
    return bool(etat.manuel) or time.monotonic() < etat.jusqua


#: 21/11/2026 : « un raid mode dans sécurité qui kick les nouveaux ».
#: Jusqu'ici le mode ne s'armait QUE sur un afflux détecté — donc jamais à
#: l'avance, alors que « ça peut raid à tout moment ». Armé à la main, il tient
#: jusqu'à ce qu'on le désarme, et il SURVIT AUX REDÉMARRAGES : l'état vivait en
#: mémoire, et il y a eu onze déploiements dans la seule journée d'hier.
RAID_MANUEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_raid_manuel (
    guild_id INTEGER PRIMARY KEY,
    arme_par INTEGER,
    arme_a INTEGER
)
"""


def est_manuel(guild_id: int) -> bool:
    """Armé à la main, donc sans échéance (voir ``actif``)."""
    etat = _etats.get(int(guild_id))
    return bool(etat is not None and etat.manuel)


async def armer_manuel(bot, guild, auteur_id: int) -> None:
    """Ferme la porte jusqu'à nouvel ordre. Personne de nouveau n'entre."""
    maintenant = time.monotonic()
    etat = _etats.get(guild.id)
    if etat is None:
        etat = _etats[guild.id] = EtatRaid(
            debut=maintenant, jusqua=maintenant, derniere_arrivee=maintenant,
        )
    # Pas de minuterie, et surtout pas d'échéance posée ici : ``actif()`` lit
    # ``manuel`` en premier, donc les écrasements de ``jusqua`` par la détection
    # automatique ne peuvent plus raccourcir un armement décidé par un humain.
    etat.manuel = True
    if "mode armé manuellement" not in etat.mesures:
        etat.mesures.append("mode armé manuellement")
    try:
        await bot.db.execute(RAID_MANUEL_SCHEMA)
        await bot.db.execute(
            "INSERT OR REPLACE INTO sentrix_raid_manuel (guild_id, arme_par, arme_a) "
            "VALUES (?, ?, ?)",
            (guild.id, int(auteur_id), int(time.time())),
        )
    except Exception:  # noqa: BLE001 — la protection prime sur sa trace
        logger.warning("Mode raid manuel non persisté guild=%s", guild.id, exc_info=True)


async def desarmer_manuel(bot, guild) -> None:
    etat = _etats.get(guild.id)
    if etat is not None:
        etat.manuel = False
        etat.jusqua = time.monotonic()  # plus actif
    try:
        await bot.db.execute(RAID_MANUEL_SCHEMA)
        await bot.db.execute(
            "DELETE FROM sentrix_raid_manuel WHERE guild_id = ?", (guild.id,),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Désarmement non persisté guild=%s", guild.id, exc_info=True)


async def restaurer_manuels(bot) -> int:
    """Au démarrage : rouvrir les modes armés avant le redémarrage.

    Sans cela, un déploiement désarmait silencieusement tous les serveurs qui
    s'étaient fermés — exactement au moment où ils en avaient besoin.
    """
    try:
        await bot.db.execute(RAID_MANUEL_SCHEMA)
        lignes = await bot.db.fetchall("SELECT guild_id FROM sentrix_raid_manuel")
    except Exception:  # noqa: BLE001
        logger.warning("Modes raid manuels illisibles au démarrage.", exc_info=True)
        return 0
    maintenant = time.monotonic()
    restaures = 0
    for ligne in lignes or ():
        guild_id = int(ligne["guild_id"])
        etat = _etats.get(guild_id)
        if etat is None:
            etat = _etats[guild_id] = EtatRaid(
                debut=maintenant, jusqua=maintenant, derniere_arrivee=maintenant,
            )
        etat.manuel = True
        restaures += 1
    if restaures:
        logger.info("Mode raid manuel restauré sur %s serveur(s).", restaures)
    return restaures


def seuil_nuke(guild_id: int, normal: int) -> int:
    """Pendant un raid, l'anti-nuke se déclenche plus tôt."""
    return min(normal, NUKE_SEUIL_EN_RAID) if actif(guild_id) else normal


def noter_arrivee(member) -> None:
    file_ = _arrivees.setdefault(int(member.guild.id), deque(maxlen=500))
    maintenant = time.monotonic()
    file_.append((maintenant, member))
    while file_ and maintenant - file_[0][0] > FENETRE_VAGUE:
        file_.popleft()
    if len(_arrivees) > 2000:
        _arrivees.clear()


def motif_suspect(member, *, manuel: bool = False) -> str | None:
    """Pourquoi ce compte est suspect pendant un raid, ou None s'il est épargné.

    En mode MANUEL, plus personne n'est épargné : le staff a fermé la porte, et
    laisser entrer « les comptes anciens avec un avatar » reviendrait à laisser
    passer précisément les comptes qu'un raideur prépare à l'avance.
    """
    if manuel:
        return "mode raid armé manuellement"
    if getattr(member, "bot", False):
        return "bot ajouté pendant le raid"
    cree = getattr(member, "created_at", None)
    if cree is not None:
        jours = (discord.utils.utcnow() - cree).days
        if jours < COMPTE_SUSPECT_JOURS:
            return f"compte créé il y a {jours} jour(s)"
    avatar = getattr(member, "avatar", None)
    if avatar is None:
        return "avatar par défaut"
    return None


async def _intouchable(automod, member) -> bool:
    guild = member.guild
    if member.id == getattr(guild, "owner_id", None):
        return True
    try:
        from cogs.automod import can_bypass_message_filters

        if can_bypass_message_filters(member):
            return True
    except Exception:  # noqa: BLE001
        pass
    if getattr(member, "bot", False):
        try:
            return bool(await automod._bot_is_allowlisted(guild.id, member.id))
        except Exception:  # noqa: BLE001
            return False
    return False


async def _expulser(automod, etat: EtatRaid, member, motif: str, verrou: asyncio.Semaphore) -> None:
    if any(i == member.id for i, _, _ in etat.expulses):
        return
    async with verrou:
        try:
            from utils import log_service

            log_service.mark_sanction(member.guild.id, member.id, "kick")
        except Exception:  # noqa: BLE001
            pass
        try:
            await member.kick(reason=f"{RAISON} ({motif})")
            etat.expulses.append((member.id, str(member), motif))
        except discord.NotFound:
            pass  # déjà parti
        except discord.HTTPException as exc:
            # Solution de repli : mute (Discord ou SentriX) pendant le raid, et UN
            # MP au propriétaire avec la permission à donner.
            repli = "mute_failed"
            muter = getattr(automod, "_muter", None)
            if callable(muter):
                try:
                    repli = await muter(member.guild, member, RAID_MODE_DUREE, f"{RAISON} ({motif})")
                except Exception:  # noqa: BLE001
                    repli = "mute_failed"
            alerter = getattr(automod, "_alerter_permission_manquante", None)
            if callable(alerter):
                try:
                    await alerter(member.guild, "kick")
                except Exception:  # noqa: BLE001
                    pass
            if repli != "mute_failed":
                etat.neutralises.append((member.id, str(member), motif))
            else:
                etat.echecs.append((member.id, str(member), f"refus Discord ({exc.status})"))


def _verrou(automod) -> asyncio.Semaphore:
    verrou = getattr(automod, "_raid_mode_verrou", None)
    if verrou is None:
        verrou = automod._raid_mode_verrou = asyncio.Semaphore(EXPULSIONS_EN_PARALLELE)
    return verrou


async def _examiner_et_expulser(automod, etat: EtatRaid, member, verrou: asyncio.Semaphore) -> None:
    """Vérifie PUIS expulse, en une seule tâche pour que tout aille en parallèle."""
    if await _intouchable(automod, member):
        etat.epargnes += 1
        return
    motif = motif_suspect(member, manuel=etat.manuel)
    if motif is None:
        etat.epargnes += 1
        return
    await _expulser(automod, etat, member, motif, verrou)


async def declencher(automod, guild, *, mesures: list[str] | None = None) -> EtatRaid:
    """Raid rapide confirmé : active le mode et vide la vague en quelques secondes."""
    maintenant = time.monotonic()
    etat = _etats.get(guild.id)
    nouveau = etat is None or maintenant >= etat.jusqua
    if nouveau:
        etat = _etats[guild.id] = EtatRaid(debut=maintenant, jusqua=maintenant + RAID_MODE_DUREE,
                                           derniere_arrivee=maintenant)
    etat.jusqua = maintenant + RAID_MODE_DUREE
    for mesure in mesures or ():
        if mesure not in etat.mesures:
            etat.mesures.append(mesure)
    vague = [m for t, m in _arrivees.get(guild.id, ()) if maintenant - t <= FENETRE_VAGUE]
    if nouveau:
        etat.arrivees = len(vague)
    # 21/11/2026 : « il met du temps à mute ou ban et kick dans un raid ».
    # Cette boucle vérifiait CHAQUE compte en série — et _intouchable fait une
    # requête en base pour un bot — AVANT de lancer le moindre kick. Sur une
    # vague de cinquante bots, le premier compte ne partait donc qu'après
    # cinquante allers-retours Postgres.
    #
    # La vérification entre maintenant DANS la tâche : chaque compte est examiné
    # et expulsé indépendamment, et le premier kick part dès que SA vérification
    # est finie, sans attendre les quarante-neuf autres.
    verrou = _verrou(automod)
    taches = [_examiner_et_expulser(automod, etat, member, verrou) for member in vague]
    if taches:
        await asyncio.gather(*taches, return_exceptions=True)
    _planifier_rapport(automod, guild, etat)
    return etat


async def sur_arrivee(automod, member) -> bool:
    """Arrivée pendant un raid actif. Vrai si le compte a été expulsé (traitement fini)."""
    etat = _etats.get(member.guild.id)
    if etat is None or not actif(member.guild.id):
        return False
    etat.arrivees += 1
    etat.derniere_arrivee = time.monotonic()
    if await _intouchable(automod, member):
        etat.epargnes += 1
        return False
    motif = motif_suspect(member, manuel=etat.manuel)
    if motif is None:
        etat.epargnes += 1
        return False
    etat.jusqua = time.monotonic() + RAID_MODE_DUREE
    await _expulser(automod, etat, member, motif, _verrou(automod))
    _planifier_rapport(automod, member.guild, etat)
    return True


def _planifier_rapport(automod, guild, etat: EtatRaid) -> None:
    if etat.rapport_tache is not None and not etat.rapport_tache.done():
        return
    etat.rapport_tache = asyncio.ensure_future(_rapport_quand_calme(automod, guild, etat))


async def _rapport_quand_calme(automod, guild, etat: EtatRaid) -> None:
    while time.monotonic() - etat.derniere_arrivee < CALME_SECONDES:
        await asyncio.sleep(max(1.0, CALME_SECONDES - (time.monotonic() - etat.derniere_arrivee)))
    try:
        await envoyer_rapport(automod, guild, etat)
    except Exception:  # noqa: BLE001
        logger.exception("Rapport de raid impossible guild=%s", getattr(guild, "id", None))


def champs_rapport(etat: EtatRaid) -> dict:
    duree = max(1, int(etat.derniere_arrivee - etat.debut))
    liste = "\n".join(f"<@{i}> · `{i}` · {motif}" for i, _, motif in etat.expulses[:15])
    if len(etat.expulses) > 15:
        liste += f"\n… et {len(etat.expulses) - 15} autre(s) (fichier joint)"
    champs = {
        "Statut": (
            f"Raid repoussé — {len(etat.expulses)} compte(s) expulsé(s)"
            if not etat.echecs else f"Raid freiné — {len(etat.echecs)} expulsion(s) refusée(s) par Discord"
        ),
        "Protection": "Mode raid",
        "Règle": "Afflux rapide d'arrivées confirmé",
        "Durée": f"{duree} s",
        "Arrivées pendant le raid": str(etat.arrivees),
        "Expulsés": str(len(etat.expulses)),
        "Épargnés (comptes anciens, staff, bots autorisés)": str(etat.epargnes),
    }
    if etat.neutralises:
        champs["Rendus muets (expulsion refusée)"] = (
            f"{len(etat.neutralises)} — leurs messages sont bloqués ; donne-moi **Expulser des membres**"
        )
    if etat.echecs:
        champs["Échecs"] = f"{len(etat.echecs)} — rôle de SentriX trop bas ou permission Expulser manquante"
    champs["Mesures"] = " · ".join(
        etat.mesures + [f"anti-nuke durci ({NUKE_SEUIL_EN_RAID} actions) pendant le raid"]
    )
    if liste:
        champs["Comptes expulsés"] = liste[:1000]
    return champs


def fichier_rapport(etat: EtatRaid) -> discord.File | None:
    if not etat.expulses and not etat.echecs and not etat.neutralises:
        return None
    lignes = ["Rapport du mode raid SentriX", "", "Expulsés :"]
    lignes += [f"{i}\t{nom}\t{motif}" for i, nom, motif in etat.expulses]
    if etat.neutralises:
        lignes += ["", "Rendus muets (expulsion refusée) :"] + [f"{i}\t{nom}\t{m}" for i, nom, m in etat.neutralises]
    if etat.echecs:
        lignes += ["", "Non expulsés :"] + [f"{i}\t{nom}\t{err}" for i, nom, err in etat.echecs]
    return discord.File(io.BytesIO("\n".join(lignes).encode("utf-8")), filename="rapport-raid.txt")


async def envoyer_rapport(automod, guild, etat: EtatRaid) -> None:
    from utils import embeds

    import config
    from cogs.automod import _mp_vue, carte_securite_mp

    champs = champs_rapport(etat)
    e = embeds.log_entry("🚨 Rapport du mode raid", config.COLOR_ERROR, extra=champs)
    try:
        await automod.log_action(guild, e, "automod", file=fichier_rapport(etat))
    except TypeError:
        await automod.log_action(guild, e)
    proprietaire = getattr(guild, "owner", None)
    if proprietaire is not None:
        try:
            await _mp_vue(proprietaire, carte_securite_mp(
                "Raid repoussé" if not etat.echecs else "Raid freiné",
                {k: v for k, v in champs.items() if k != "Comptes expulsés"},
                serveur=getattr(guild, "name", ""), echec=bool(etat.echecs),
            ))
        except (discord.Forbidden, discord.HTTPException):
            pass


def oublier(guild_id: int) -> None:
    _etats.pop(int(guild_id), None)
    _arrivees.pop(int(guild_id), None)


__all__ = [
    "RAID_MODE_DUREE", "actif", "seuil_nuke", "noter_arrivee", "motif_suspect", "declencher",
    "sur_arrivee", "champs_rapport", "envoyer_rapport", "oublier",
]
