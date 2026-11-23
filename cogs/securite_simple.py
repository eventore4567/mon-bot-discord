"""Écran simple de la page Sécurité (10/11/2026).

« Trop compliqué, garde les bannières, juste un bouton pour activer la sécurité à la
place de tout configurer. » La page Sécurité de /setup s'ouvre sur cet écran : l'état
en une phrase, les huit protections recommandées et un bouton « Activer la sécurité ».
L'écran complet d'avant (une protection à la fois, seuils, exceptions) reste derrière
« Personnaliser ».

Ces écrans vivent dans SecurityCenterView (cogs/complete_security_setup.py), la vue
réellement affichée par /setup → Sécurité.
"""
from __future__ import annotations

import discord

from utils import config_journal
from utils import sentrix_emojis as icons

PROTECTION_RECOMMANDEE = (
    ("antispam", "Spam et flood"),
    ("antimention", "@everyone et pings en masse"),
    ("antiinvite", "Pub pour d'autres serveurs"),
    ("antiscam", "Liens d'arnaque (faux Nitro…)"),
    ("antiinsult", "Insultes (avec analyse du contexte)"),
    ("antiraid", "Raids (afflux de comptes)"),
    ("antibot", "Bots ajoutés sans autorisation"),
    ("antinuke", "Destruction du serveur (nuke)"),
)
RECOMMANDEES = tuple(cle for cle, _ in PROTECTION_RECOMMANDEE)
#: Nom court, pour tenir sur une ligne dans le résumé.
PROTECTION_COURTE = (
    ("antispam", "spam"),
    ("antimention", "@everyone"),
    ("antiinvite", "pub"),
    ("antiscam", "arnaques"),
    ("antiinsult", "insultes"),
    ("antiraid", "raids"),
    ("antibot", "bots"),
    ("antinuke", "nuke"),
)


async def _module_securite_actif(view) -> bool:
    from cogs import setup_v2_core as core

    try:
        return bool(await core.module_enabled(view.bot, view.guild.id, "security"))
    except Exception:  # noqa: BLE001 — illisible : on ne prétend pas protéger
        return False


async def etats(view) -> dict[str, bool]:
    """État EFFECTIF de chaque protection recommandée.

    Revue Codex (PR #714) : module Sécurité coupé, setup_v2_core neutralise toutes
    les protections (get_automod_cached les met à 0), mais cette lecture ne
    regardait que leurs interrupteurs : l'accueil affichait « 8/8, serveur
    protégé » sur un serveur sans aucune protection.
    """
    from cogs import setup_v2_ui as policy

    module = await _module_securite_actif(view)
    return {
        cle: module and (await policy._security_center_state(view.bot, view.guild.id, cle))[0]
        for cle in RECOMMANDEES
    }


def toutes_les_protections() -> tuple[str, ...]:
    """Tout ce que « Activer la sécurité » allume.

    22/11/2026 : « arrête de faire des commandes, tu dois améliorer, c'est dans
    Sécurité que tu mets ça. » Le bouton n'allumait que les huit protections
    affichées ; les dix autres (majuscules, flood d'émojis, comptes récents,
    lien personnalisé, purges, permissions à risque, filtre des arrivées,
    analyse comportementale, sanctions progressives) demandaient une commande
    chacune. Elles passent par le bouton maintenant.

    Le blocage des liens reste dehors : il coupe aussi les liens légitimes
    (YouTube, GitHub, le lien d'aide d'un modérateur), donc c'est un choix
    éditorial et pas une protection. Les DEUX noms sont exclus parce que
    ``Database.set_automod`` les écrit ensemble.
    """
    from cogs.automod import TOGGLE_FIELDS

    return tuple(cle for cle in TOGGLE_FIELDS
                 if cle not in {"antilink", "antilink_strict"})


async def activer_recommandees(view) -> list[str]:
    """Active toutes les protections encore coupées. Ne coupe jamais rien."""
    from cogs import setup_v2_ui as policy

    cibles = toutes_les_protections()
    actuels = {}
    for cle in cibles:
        try:
            actuels[cle] = (await policy._security_center_state(view.bot, view.guild.id, cle))[0]
        except Exception:  # noqa: BLE001 — une protection illisible est traitée comme coupée
            actuels[cle] = False
    a_activer = [cle for cle in cibles if not actuels[cle]]
    if not await _module_securite_actif(view):
        # Module coupé : sans lui, aucun interrupteur n'a d'effet.
        from cogs import setup_v2_core as core

        auteur = getattr(view, "author_id", None) or getattr(view, "owner_id", None)
        await core.set_module_enabled(view.bot, view.guild.id, "security", True, actor_id=auteur)
    if not a_activer:
        return []
    await view.bot.db.execute(
        "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (view.guild.id,),
    )
    for cle in a_activer:
        await view.bot.db.set_automod(view.guild.id, cle, 1)
        await config_journal.record(view.bot.db, view.guild.id, "automod." + cle, 0, 1)
    # Le cache du cog sert chaque message : sans purge, les protections
    # fraîchement allumées resteraient inertes une trentaine de secondes.
    cog = view.bot.get_cog("Automod")
    if cog is not None and hasattr(cog, "automod_cache"):
        cog.automod_cache.pop(view.guild.id, None)
    return a_activer


#: Couleur des centres de configuration. 10/11/2026 : la page changeait de couleur
#: selon l'état (vert / orange / rouge) ; elle jurait avec le reste de /setup.
COULEUR = 0x5865F2


async def basculer_protection(view, cle: str, actif: bool, *, actor_id: int | None = None) -> None:
    """Allume ou coupe UNE protection (section Sécurité de /setup, 22/11/2026).

    Même écriture que l'écran « Personnaliser », plus la purge du cache d'AutoMod,
    qu'il oubliait : sans elle, le changement n'agissait qu'après une trentaine
    de secondes.
    """
    if cle not in toutes_les_protections():
        raise ValueError(f"protection inconnue : {cle}")
    await view.bot.db.execute(
        "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (view.guild.id,),
    )
    await view.bot.db.set_automod(view.guild.id, cle, 1 if actif else 0)
    await config_journal.record(view.bot.db, view.guild.id, "automod." + cle, int(not actif), int(actif))
    if actif and not await _module_securite_actif(view):
        # Allumer une protection n'a de sens que module allumé.
        from cogs import setup_v2_core as core

        await core.set_module_enabled(view.bot, view.guild.id, "security", True, actor_id=actor_id)
    cog = view.bot.get_cog("Automod")
    if cog is not None and hasattr(cog, "automod_cache"):
        cog.automod_cache.pop(view.guild.id, None)


def conteneur(view, titre: str, texte: str) -> discord.ui.Container:
    from cogs import setup_components_v73 as v73

    box = discord.ui.Container(accent_colour=discord.Colour(COULEUR))
    v73.poser_banniere(box)
    box.add_item(discord.ui.Section(
        discord.ui.TextDisplay(f"## {titre}\n{texte}"),
        accessory=v73._thumbnail(view.bot),
    ))
    box.add_item(discord.ui.Separator())
    return box


def _bouton(label: str, callback, style=discord.ButtonStyle.secondary, *, icone=None, disabled=False):
    """``icone`` est un nom d'icône SentriX, jamais un emoji Unicode.

    Discord n'accepte pas de marquage texte dans un libellé, et la traduction
    des icônes ne touche pas le paramètre ``emoji`` : il faut donc l'y poser
    nous-mêmes. Icône absente : bouton sans emoji, ce qui reste valide.
    """
    item = discord.ui.Button(
        label=label, style=style, disabled=disabled,
        emoji=icons.partiel(icone) if icone else None,
    )
    item.callback = callback
    return item


def _raid_arme(view) -> bool:
    try:
        from cogs import raid_mode

        return raid_mode.est_manuel(view.guild.id)
    except Exception:  # noqa: BLE001 — un panneau ne doit jamais planter
        return False


async def _basculer_mode_raid(view, interaction: discord.Interaction) -> None:
    """Ferme ou rouvre la porte du serveur, en un clic.

    Armé, le mode raid expulse CHAQUE nouvel arrivant — pas seulement les
    comptes suspects. C'est tout l'intérêt de l'armer soi-même : un raideur
    prépare ses comptes à l'avance, et ceux-là passent les filtres d'âge et
    d'avatar.
    """
    from cogs import raid_mode

    if not interaction.response.is_done():
        await interaction.response.defer()
    arme = raid_mode.est_manuel(view.guild.id)
    if arme:
        await raid_mode.desarmer_manuel(view.bot, view.guild)
        message = "**Mode raid désarmé.** Les arrivées redeviennent normales."
    else:
        await raid_mode.armer_manuel(view.bot, view.guild, interaction.user.id)
        message = (
            "**Mode raid ARMÉ.** Chaque nouvel arrivant est expulsé, y compris les "
            "comptes anciens. L'anti-nuke se durcit aussi.\n"
            "-# Il reste armé tant que vous ne le désarmez pas, redémarrages compris."
        )
    await view.refresh(interaction)
    try:
        await interaction.followup.send(message, ephemeral=True)
    except Exception:  # noqa: BLE001 — le réglage est pris, le message est un plus
        pass


async def _activer(view, interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    await activer_recommandees(view)
    await view.refresh(interaction)


async def ecran_simple(view) -> discord.ui.Container:
    """Deux lignes : combien de protections tournent, et ce qui manque.

    La liste des huit protections, une par ligne avec sa coche, faisait dix lignes
    pour dire « tout va bien ». Les noms tiennent sur une ligne.
    """
    from utils.protection_requirements import diagnostic

    actuels = await etats(view)
    actives = [cle for cle in RECOMMANDEES if actuels[cle]]
    manquantes = [cle for cle in RECOMMANDEES if not actuels[cle]]
    courts = dict(PROTECTION_COURTE)
    if not manquantes:
        etat = (f"**Le serveur est protégé.** {len(actives)} protections actives.\n"
                "-# " + ", ".join(courts[cle] for cle in actives) + ".")
    elif actives:
        etat = (f"**{len(actives)} protections sur {len(RECOMMANDEES)}.** "
                "« Activer la sécurité » met le reste en place.\n"
                "-# Manquantes : " + ", ".join(courts[cle] for cle in manquantes) + ".")
    else:
        etat = ("**Aucune protection active.** « Activer la sécurité » protège le serveur en un clic.\n"
                "-# " + ", ".join(courts[cle] for cle in RECOMMANDEES) + ".")
    box = conteneur(view, icons.titre("security", "Sécurité"), etat)
    permissions = view.guild.me.guild_permissions if view.guild.me else discord.Permissions.none()
    inertes, degradees = diagnostic(permissions, set(actives))
    if inertes or degradees:
        box.add_item(discord.ui.TextDisplay(
            f"⚠️ **{len(inertes) + len(degradees)} protection(s) bridée(s)** par des permissions "
            "manquantes du rôle SentriX. « Personnaliser » dit lesquelles."
        ))

    async def activer(interaction):
        await _activer(view, interaction)

    async def personnaliser(interaction):
        view.mode = "detail"
        await view.refresh(interaction)

    async def mots(interaction):
        from cogs import mots_bloques

        await mots_bloques.ouvrir(interaction, view.guild)

    async def basculer_raid(interaction):
        await _basculer_mode_raid(view, interaction)

    box.add_item(discord.ui.ActionRow(
        _bouton("Sécurité active" if not manquantes else "Activer la sécurité", activer,
                discord.ButtonStyle.success, icone="security", disabled=not manquantes),
        # 21/11/2026 : « un raid mode dans sécurité qui kick les nouveaux », sans
        # passer par une commande. Rouge quand il est armé : on doit voir d'un
        # coup d'œil que la porte est fermée, et pouvoir la rouvrir du même clic.
        _bouton(
            "Mode raid : ARMÉ" if _raid_arme(view) else "Mode raid",
            basculer_raid,
            discord.ButtonStyle.danger if _raid_arme(view) else discord.ButtonStyle.secondary,
            icone="shield",
        ),
        _bouton("Personnaliser", personnaliser, icone="settings"),
        _bouton("Mots bloqués", mots),
    ))
    return box


__all__ = ["PROTECTION_RECOMMANDEE", "RECOMMANDEES", "activer_recommandees", "basculer_protection", "conteneur",
           "ecran_simple", "etats", "toutes_les_protections"]
