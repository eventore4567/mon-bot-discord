#!/usr/bin/env python3
"""/setup en six sections, sur le bot booté (22/11/2026).

Accueil → section → réglage → « Retour » revient à la SECTION ; « Activer toutes
les protections » allume réellement les protections recommandées.

    python3 tools/setup_sections_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402
from welcome_e2e import admin_interaction, control  # noqa: E402


def bouton(view, libelle):
    return control(view, lambda i: isinstance(i, discord.ui.Button) and i.label == libelle)


def fiche(view, cle):
    """Le bouton « Ouvrir » de la fiche d'une section, sur l'accueil (23/11/2026)."""
    from cogs import setup_experience_v74 as v74

    ouvrir = [i for i in view.walk_children() if isinstance(i, discord.ui.Button) and i.label == "Ouvrir"]
    return ouvrir[[s[0] for s in v74.SECTIONS].index(cle)]


async def cliquer(bot, item):
    await item.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=3)


async def main() -> int:
    from cogs import securite_simple, setup_experience_v74 as v74

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()
    view.clear_items()
    await view._build_home()

    texte_accueil = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    noms = [s[1] for s in v74.SECTIONS]
    ouvrir = [i for i in view.walk_children() if isinstance(i, discord.ui.Button) and i.label == "Ouvrir"]
    check(all(f"**{nom}**" in texte_accueil for nom in noms) and len(ouvrir) == 6,
          "l'accueil présente les six sections en fiches, chacune avec « Ouvrir »", str(noms))
    check("⬜" not in texte_accueil and "🟩" not in texte_accueil, "plus de barre de carrés sur l'accueil")
    check(control(view, lambda i: isinstance(i, discord.ui.Select)) is None,
          "l'accueil n'a plus le menu de 22 entrées")

    # Communauté garde la présentation « une ligne + Ouvrir » ; Sécurité et
    # Modération sont des panneaux tout-en-un (étapes 2 et 3).
    await cliquer(bot, fiche(view, "communaute"))
    check(view.page == "section:communaute" and bouton(view, "Ouvrir") is not None,
          "une section s'ouvre et liste ses réglages", str(view.page))

    ouvrir = [b for b in view.walk_children() if isinstance(b, discord.ui.Button) and b.label == "Ouvrir"]
    await cliquer(bot, ouvrir[2])
    check(view.page == "roles", "« Ouvrir » mène au réglage", str(view.page))

    await cliquer(bot, bouton(view, "Retour"))
    check(view.page == "section:communaute", "« Retour » revient à la section, pas à l'accueil", str(view.page))

    await cliquer(bot, bouton(view, "Retour"))
    check(view.page is None and bouton(view, "Activer toutes les protections") is not None,
          "« Retour » de la section revient à l'accueil")

    avant = await securite_simple.etats(view)
    await cliquer(bot, bouton(view, "Activer toutes les protections"))
    apres = await securite_simple.etats(view)
    check(not all(avant.values()) and all(apres.values()),
          "« Activer toutes les protections » les allume toutes", f"{sum(avant.values())} → {sum(apres.values())}")
    check(bouton(view, "Toutes les protections sont actives") is not None,
          "l'accueil indique ensuite que tout est actif")

    # Section Communauté (étape 4) : fiches réelles + interrupteurs rapides.
    from cogs import setup_v2_core as core_communaute

    view.page = "section:communaute"
    view.clear_items()
    await view._build_page(view.page)
    texte_communaute = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check(f"<#{h.CID}>" in texte_communaute and "Arrivée" in texte_communaute,
          "la section Communauté affiche les vrais salons et rôles", texte_communaute[:160])
    await cliquer(bot, bouton(view, "Bienvenue : activé"))
    check(not await core_communaute.module_enabled(bot, guild.id, "welcome") and view.page == "section:communaute",
          "l'interrupteur coupe l'accueil, en base, sans quitter la section")
    await cliquer(bot, bouton(view, "Bienvenue : désactivé"))
    check(await core_communaute.module_enabled(bot, guild.id, "welcome"), "un second clic le rallume")
    await bot.db.set_guild_config(guild.id, "goodbye_channel", None)
    await core_communaute.set_module_enabled(bot, guild.id, "goodbye", False, actor_id=h.ADMIN_ID)
    view.clear_items()
    await view._build_page(view.page)
    await cliquer(bot, bouton(view, "Départs : désactivé"))
    check(view.page == "goodbye" and not await core_communaute.module_enabled(bot, guild.id, "goodbye"),
          "sans salon, l'interrupteur ouvre la page pour le choisir au lieu d'activer à vide", str(view.page))

    # Revue Codex (PR #718) : tous les panneaux de tickets comptent, et le rôle
    # de vérification enregistré sous verification_role s'affiche.
    tickets = bot.get_cog("Tickets")
    for nom in ("Support", "Partenariats"):
        panel_id = await tickets.create_panel(guild.id, nom)
        for type_nom in ("A", "B", "C"):
            await tickets.add_type(guild.id, panel_id, f"{nom} {type_nom}")
    await bot.db.set_guild_config(guild.id, "verify_role", None)
    await bot.db.set_guild_config(guild.id, "verification_role", h.MEMBER_ROLE_ID)
    view.page = "section:communaute"
    view.clear_items()
    await view._build_page(view.page)
    texte_verif = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check(f"Vérification : <@&{h.MEMBER_ROLE_ID}>" in texte_verif,
          "le rôle de vérification enregistré sous verification_role est affiché", texte_verif[-200:])

    # Engagement, Outils, Système (23/11/2026) : l'état réel de chaque réglage.
    textes_sections = {}
    for cle in ("engagement", "outils", "systeme"):
        view.page = f"section:{cle}"
        view.clear_items()
        await view._build_page(view.page)
        textes_sections[cle] = "\n".join(
            i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay)
        )
    check(f"annonces : <#{h.CID}>" in textes_sections["engagement"] or "annonces :" in textes_sections["engagement"],
          "Engagement affiche le vrai salon d'annonces des niveaux", textes_sections["engagement"][:160])
    check("2 panneau(x) · 6 type(s) de ticket" in textes_sections["outils"]
          and "commande(s) créée(s)" in textes_sections["outils"],
          "Outils compte les types de TOUS les panneaux de tickets (2 × 3 = 6)", textes_sections["outils"][:200])
    check("préfixe : `" in textes_sections["systeme"] and "demandes par jour" in textes_sections["systeme"],
          "Système affiche le vrai préfixe et la limite IA", textes_sections["systeme"][:160])

    # Section Sécurité tout-en-un (étape 2) : un clic par protection, en base.
    async def antispam_actif() -> bool:
        return (await securite_simple.etats(view))["antispam"]

    view.page = "section:securite"
    view.clear_items()
    await view._build_page(view.page)
    check(bouton(view, "Spam") is not None and bouton(view, "Nuke") is not None,
          "la section Sécurité montre les huit protections en boutons")
    etat_avant = await antispam_actif()
    await cliquer(bot, bouton(view, "Spam"))
    check(await antispam_actif() is (not etat_avant) and view.page == "section:securite",
          "un clic sur « Spam » change la protection en base et reste sur la section")
    await cliquer(bot, bouton(view, "Spam"))
    check(await antispam_actif() is etat_avant, "un second clic la remet comme avant")
    automod = bot.get_cog("Automod")
    check(guild.id not in getattr(automod, "automod_cache", {}),
          "le cache d'AutoMod est purgé : le changement agit tout de suite")
    await cliquer(bot, bouton(view, "Réglages avancés"))
    texte_avance = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check(view.page == "security" and bouton(view, "Retour à /setup") is not None
          and "personnaliser" in texte_avance,
          "« Réglages avancés » ouvre directement l'écran « Personnaliser »", texte_avance[:120])

    # Section Modération (étape 3) : seuil sur place, logs en un choix.
    view.page = "section:moderation"
    view.clear_items()
    await view._build_page(view.page)
    seuil = control(view, lambda i: isinstance(i, discord.ui.Select) and str(i.placeholder or "").startswith("Ban automatique"))
    seuil._values = ["3"]
    await cliquer(bot, seuil)
    conf = await bot.db.get_guild_config(guild.id)
    check(int(conf["warn_ban_threshold"] or 0) == 3 and view.page == "section:moderation",
          "le seuil de ban automatique se règle depuis la section", str(conf["warn_ban_threshold"]))

    # Modération par IA dans la section (24/11/2026) : même état que +sentrixpro aimod.
    from cogs import sentrix_ultimate as ultimate

    check(bouton(view, "Activer") is not None and await ultimate.etat_ia_moderation(bot, guild.id) is None,
          "la section Modération propose la modération par IA, coupée par défaut")
    await cliquer(bot, bouton(view, "Activer"))
    texte_mod = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check(await ultimate.etat_ia_moderation(bot, guild.id) == "timeout" and view.page == "section:moderation"
          and "🟢 Active" in texte_mod and bouton(view, "Désactiver") is not None,
          "« Activer » allume l'IA de modération en base (supprime + exclut 10 min)", texte_mod[-160:])
    cog_ultimate = bot.get_cog("SentriXUltimate")
    check(await cog_ultimate._enabled(guild.id, "ai_moderation"),
          "le moteur _ai_moderate la voit active tout de suite (cache purgé)")
    await cliquer(bot, bouton(view, "Désactiver"))
    check(await ultimate.etat_ia_moderation(bot, guild.id) is None
          and not await cog_ultimate._enabled(guild.id, "ai_moderation"),
          "« Désactiver » coupe les deux interrupteurs (aucun ne la laisse active)")

    from utils import log_service
    from cogs import setup_v2_core as core

    # Revue Codex (PR #716) : une catégorie coupée volontairement garde son salon
    # et doit rester coupée ; module Logs coupé, l'envoi groupé doit le rallumer.
    await log_service.set_log_channel(bot, guild.id, "messages", h.CID)
    await log_service.set_log_enabled(bot, guild.id, "messages", False)
    await core.set_module_enabled(bot, guild.id, "logs", False, actor_id=h.ADMIN_ID)
    view.clear_items()
    await view._build_page(view.page)

    tous = control(view, lambda i: isinstance(i, discord.ui.ChannelSelect))
    check(tous is not None, "la section propose d'envoyer les logs sans salon dans un salon")
    tous._values = [guild.get_channel(h.LOGCID)]
    await cliquer(bot, tous)
    sans_salon = [
        cle for cle in log_service.CATEGORY_KEYS
        if not (await log_service.get_log_setting(bot, guild.id, cle)).get("channel_id")
    ]
    check(not sans_salon, "un seul choix configure toutes les catégories de logs restantes", str(sans_salon))
    messages = await log_service.get_log_setting(bot, guild.id, "messages")
    check(int(messages.get("channel_id") or 0) == h.CID and not messages.get("enabled"),
          "une catégorie coupée volontairement n'est ni réactivée ni redirigée", str(messages))
    check(await core.module_enabled(bot, guild.id, "logs"),
          "l'envoi groupé rallume le module Logs (sinon aucun journal ne part)")
    check(control(view, lambda i: isinstance(i, discord.ui.ChannelSelect)) is None,
          "une fois tout configuré, le sélecteur disparaît")

    await cliquer(bot, bouton(view, "Réglages détaillés"))
    check(view.page == "logs", "« Réglages détaillés » ouvre la page Logs", str(view.page))
    await cliquer(bot, bouton(view, "Retour"))
    check(view.page == "section:moderation", "« Retour » depuis Logs revient à la section Modération", str(view.page))

    # Revue Codex (PR #714) : tout coché, mais SentriX sans « Voir le journal
    # d'audit » ni « Expulser » — l'accueil ne doit pas annoncer « protégé ».
    from unittest.mock import PropertyMock, patch

    bridees = discord.Permissions(manage_guild=True, manage_roles=True, manage_channels=True,
                                  manage_messages=True, moderate_members=True, ban_members=True)
    with patch.object(discord.Member, "guild_permissions", new_callable=PropertyMock, return_value=bridees):
        view.clear_items()
        await view._build_home()
    texte = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check("bridée" in texte and "Serveur protégé" not in texte,
          "permissions manquantes : l'accueil signale les protections bridées au lieu de « protégé »",
          texte[-200:])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
