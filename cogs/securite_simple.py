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


async def etats(view) -> dict[str, bool]:
    """État réel de chaque protection recommandée (même lecture que l'écran complet)."""
    from cogs import setup_v2_ui as policy

    return {
        cle: (await policy._security_center_state(view.bot, view.guild.id, cle))[0]
        for cle in RECOMMANDEES
    }


async def activer_recommandees(view) -> list[str]:
    """Active les protections recommandées encore coupées. Ne coupe jamais rien."""
    actuels = await etats(view)
    a_activer = [cle for cle in RECOMMANDEES if not actuels[cle]]
    if not a_activer:
        return []
    await view.bot.db.execute(
        "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (view.guild.id,),
    )
    for cle in a_activer:
        await view.bot.db.set_automod(view.guild.id, cle, 1)
        await config_journal.record(view.bot.db, view.guild.id, "automod." + cle, 0, 1)
    return a_activer


#: Couleur des centres de configuration. 10/11/2026 : la page changeait de couleur
#: selon l'état (vert / orange / rouge) ; elle jurait avec le reste de /setup.
COULEUR = 0x5865F2


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

    box.add_item(discord.ui.ActionRow(
        _bouton("Sécurité active" if not manquantes else "Activer la sécurité", activer,
                discord.ButtonStyle.success, icone="security", disabled=not manquantes),
        _bouton("Personnaliser", personnaliser, icone="settings"),
        _bouton("Mots bloqués", mots),
    ))
    return box


__all__ = ["PROTECTION_RECOMMANDEE", "RECOMMANDEES", "activer_recommandees", "conteneur", "ecran_simple", "etats"]
