"""Refonte premium et compréhensible de +setup.

Cette couche garde toute la logique existante (permissions, persistance, callbacks,
création de rôles/logs, sécurité...) et remplace uniquement la manière de présenter
le centre de configuration. L'objectif est qu'un administrateur comprenne immédiatement
quoi régler, dans quel ordre, et si son serveur est prêt.
"""
from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

logger = logging.getLogger("bot.setup-premium-style")
_INSTALLED = False

PURPLE_MAIN = 0x8B5CF6
PURPLE_SECONDARY = 0xA855F7
DASHBOARD_FALLBACK = "https://mon-bot-discord-production-8944.up.railway.app"


STEP_META = {
    "general": {
        "title": "Base du serveur",
        "summary": "Les réglages indispensables : staff, préfixe, accueil et salon principal de logs.",
        "details": "Définis qui gère SentriX, où arrivent les informations importantes et comment le bot accueille les membres.",
        "tip": "Commence par ce module : les autres fonctions dépendent souvent du rôle staff et des salons principaux.",
    },
    "roles": {
        "title": "Rôles automatiques",
        "summary": "Rôles membre, booster, vérification, mute et rôle donné à l'arrivée.",
        "details": "Choisis les rôles que SentriX doit attribuer automatiquement ou utiliser pour ses systèmes.",
        "tip": "Place toujours le rôle SentriX au-dessus des rôles qu'il doit attribuer.",
    },
    "tickets": {
        "title": "Tickets & support",
        "summary": "Configure l'ouverture des tickets, le staff à prévenir et le système de support.",
        "details": "Ce module relie le centre principal au configurateur complet des tickets sans mélanger les réglages.",
        "tip": "Teste toujours un ticket avec un compte membre après la configuration.",
    },
    "channels": {
        "title": "Salons utiles",
        "summary": "Suggestions, annonces, giveaways, niveaux, rapports, commandes du bot et autres salons dédiés.",
        "details": "Indique à SentriX dans quels salons envoyer chaque type de contenu au lieu de tout mélanger.",
        "tip": "Tu peux laisser un salon vide si tu n'utilises pas encore la fonction correspondante.",
    },
    "levels": {
        "title": "Niveaux & récompenses",
        "summary": "Associe des rôles aux niveaux atteints par les membres.",
        "details": "Crée des paliers de récompense : par exemple niveau 10 → rôle Actif, niveau 25 → rôle VIP.",
        "tip": "Utilise quelques paliers importants plutôt qu'un rôle à chaque niveau.",
    },
    "logs": {
        "title": "Logs & surveillance",
        "summary": "Crée et organise les salons qui enregistrent les actions importantes du serveur.",
        "details": "Messages supprimés, arrivées, rôles, vocal, sanctions et sécurité peuvent être séparés dans leurs propres salons.",
        "tip": "Le bouton de création automatique est recommandé si tu pars de zéro.",
    },
    "managers": {
        "title": "Accès administrateurs",
        "summary": "Autorise certaines personnes à gérer SentriX sans leur donner Administrateur sur Discord.",
        "details": "Ajoute des gestionnaires puis limite précisément les catégories qu'ils ont le droit de modifier.",
        "tip": "Donne uniquement les catégories nécessaires à chaque gestionnaire.",
    },
    "security": {
        "title": "Protection AutoMod",
        "summary": "Anti-spam, liens, mentions, caps, raids, scams et protections automatiques.",
        "details": "Choisis un niveau de protection ou active uniquement les filtres adaptés à ton serveur.",
        "tip": "Le préréglage Moyen est un bon point de départ pour la majorité des serveurs.",
    },
    "summary": {
        "title": "Vérification finale",
        "summary": "Contrôle les réglages importants avant de quitter le centre de configuration.",
        "details": "SentriX vérifie les permissions, les rôles, les salons de logs et la protection du serveur.",
        "tip": "Corrige les avertissements affichés avant de considérer la configuration terminée.",
    },
}


def _avatar_url(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    if not user:
        return None
    try:
        return user.display_avatar.url
    except Exception:
        return None


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return None


def _set_author(embed: discord.Embed, bot: commands.Bot) -> None:
    avatar = _avatar_url(bot)
    if avatar:
        embed.set_author(name="SENTRIX • CONTROL CENTER", icon_url=avatar)
    else:
        embed.set_author(name="SENTRIX • CONTROL CENTER")


def _status_icon(status: str) -> str:
    if status == "Configuré":
        return "✅"
    if status == "Partiel":
        return "⚠️"
    return "❌"


def _clean_button_label(label: str | None) -> str | None:
    if not label:
        return label
    text = str(label).strip()
    # Les anciens ronds étaient utilisés partout comme décoration. On garde les vrais
    # emojis utiles mais on retire ces glyphes qui donnent un rendu brouillon.
    for prefix in ("● ", "○ ", "◉ ", "◈ "):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
    return text


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    configuration.SETUP_COLOR_MAIN = PURPLE_MAIN
    configuration.SETUP_COLOR_SECONDARY = PURPLE_SECONDARY

    # Les titres servent partout dans le setup : menu, page, résumé. On remplace donc les
    # termes vagues comme « Général » ou « Salons annexes » par des intitulés explicites.
    for step in configuration.SETUP_STEPS:
        meta = STEP_META.get(step["key"])
        if not meta:
            continue
        step["title"] = meta["title"]
        step["description"] = meta["summary"]

    original_build_embed = configuration.SetupView.build_embed
    original_render_page = configuration.SetupView.render_page

    async def build_home_embed(self) -> discord.Embed:
        conf = await self.bot.db.get_guild_config(self.guild_id)
        guild = self._guild()
        category_states = await self._compute_categories(conf)
        steps = [step for step in configuration.SETUP_STEPS if step["key"] != "summary"]
        prefix = conf["prefix"] if conf and conf["prefix"] else "+"

        # _compute_categories suit le même ordre historique que SETUP_STEPS. On associe
        # les statuts aux nouveaux titres sans toucher aux calculs de configuration.
        statuses = [status for _old_name, status in category_states]
        paired = list(zip(steps, statuses))
        configured = sum(1 for _step, status in paired if status == "Configuré")
        partial = sum(1 for _step, status in paired if status == "Partiel")
        missing = sum(1 for _step, status in paired if status == "Non configuré")

        if missing == 0 and partial == 0:
            state = "✅ Prêt à utiliser"
            state_sentence = "Les modules principaux sont configurés."
        elif missing == 0:
            state = "⚠️ Presque prêt"
            state_sentence = "Il reste quelques réglages facultatifs ou incomplets."
        else:
            state = "🟣 Configuration à terminer"
            state_sentence = "Quelques éléments importants doivent encore être réglés."

        e = discord.Embed(
            title="⚡ SentriX • Centre de contrôle",
            description=(
                "**Tout ce qui compte est regroupé ici.** Choisis simplement ce que tu veux "
                "configurer dans le menu : SentriX t'explique ensuite quoi faire, sans jargon.\n\n"
                f"Préfixe actuel : **`{prefix}`**  •  État : **{state}**"
            ),
            color=PURPLE_MAIN,
        )
        _set_author(e, self.bot)
        avatar = _avatar_url(self.bot)
        if avatar:
            e.set_thumbnail(url=avatar)

        e.add_field(
            name="📊 État de la configuration",
            value=(
                f"**{configured}/{len(paired)} modules prêts**\n"
                f"{partial} à compléter • {missing} non configuré(s)\n"
                f"{state_sentence}"
            ),
            inline=False,
        )

        todo = []
        for step, status in paired:
            if status == "Configuré":
                continue
            meta = STEP_META[step["key"]]
            todo.append(f"{_status_icon(status)} **{meta['title']}** — {meta['summary']}")
            if len(todo) >= 3:
                break
        if todo:
            e.add_field(
                name="🎯 À faire maintenant",
                value="\n".join(todo),
                inline=False,
            )
        else:
            e.add_field(
                name="🎯 À faire maintenant",
                value="✅ Rien d'obligatoire. Tu peux ouvrir un module pour ajuster un détail.",
                inline=False,
            )

        module_lines = []
        for step, status in paired:
            module_lines.append(
                f"{_status_icon(status)} **{STEP_META[step['key']]['title']}**"
            )
        e.add_field(
            name="🧩 Modules",
            value="\n".join(module_lines),
            inline=True,
        )
        e.add_field(
            name="🪄 Comment l'utiliser",
            value=(
                "**1.** Choisis un module dans le menu.\n"
                "**2.** Modifie uniquement ce dont tu as besoin.\n"
                "**3.** Clique sur **Enregistrer** quand il apparaît.\n"
                "**4.** Termine par **Résumé** pour tout vérifier."
            ),
            inline=True,
        )

        server_name = guild.name if guild else "Serveur"
        e.set_footer(text=f"SentriX • {server_name} • Les réglages sont conservés après redémarrage")
        return e

    async def build_embed(self) -> discord.Embed:
        if self.page == -1:
            return await build_home_embed(self)

        e = await original_build_embed(self)
        step = configuration.SETUP_STEPS[self.page]
        meta = STEP_META.get(step["key"], {
            "title": step["title"],
            "summary": "Configure ce module.",
            "details": "Modifie les réglages proposés ci-dessous.",
            "tip": "Enregistre tes changements avant de quitter.",
        })
        guild = self._guild()
        avatar = _avatar_url(self.bot)

        e.colour = discord.Colour(PURPLE_MAIN)
        e.title = f"{step['icon']} {meta['title']}"
        _set_author(e, self.bot)
        if avatar:
            e.set_thumbnail(url=avatar)

        # Retire le vieux champ séparateur/statut vide quand il existe.
        for index in range(len(e.fields) - 1, -1, -1):
            name = str(e.fields[index].name or "").replace("\u200b", "").strip()
            if not name:
                e.remove_field(index)

        old_description = str(e.description or "").strip()
        if old_description and old_description != meta["summary"]:
            e.description = f"**{meta['summary']}**\n\n{old_description}"
        else:
            e.description = f"**{meta['summary']}**"

        if step["key"] != "summary":
            e.insert_field_at(
                0,
                name="🎯 Ce que tu règles ici",
                value=meta["details"],
                inline=False,
            )
            e.add_field(name="💡 Conseil", value=meta["tip"], inline=False)

        save_state = "Modifications en attente" if getattr(self, "dirty", False) else "Tout est enregistré"
        e.set_footer(
            text=f"SentriX • {guild.name if guild else 'Serveur'} • {save_state}"
        )
        return e

    def render_home(self) -> None:
        self.clear_items()

        options = []
        for index, step in enumerate(configuration.SETUP_STEPS):
            if step["key"] == "summary":
                continue
            meta = STEP_META[step["key"]]
            options.append(
                discord.SelectOption(
                    label=f"{step['icon']} {meta['title']}"[:100],
                    value=str(index),
                    description=meta["summary"][:100],
                )
            )

        category_select = discord.ui.Select(
            placeholder="Choisis ce que tu veux configurer…",
            options=options,
            row=0,
        )
        category_select.callback = self._make_home_category_callback(category_select)
        self.add_item(category_select)

        # Boutons réellement utiles au setup. On retire l'ancien bloc marketing
        # Inviter/Sécurité/Tickets qui donnait l'impression d'un panneau générique.
        self.add_item(configuration.SetupNavButton(
            "summary", self.message_id,
            label="📋 Résumé", style=discord.ButtonStyle.primary, row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "history", self.message_id,
            label="📜 Historique", style=discord.ButtonStyle.secondary, row=1,
        ))
        self.add_item(configuration.SetupNavButton(
            "cancel", self.message_id,
            label="Fermer", style=discord.ButtonStyle.danger, row=1,
        ))

        dashboard_url = (_safe_http_url(os.getenv("DASHBOARD_PUBLIC_URL")) or DASHBOARD_FALLBACK).rstrip("/")
        self.add_item(discord.ui.Button(
            label="Ouvrir le dashboard web",
            emoji="🌐",
            style=discord.ButtonStyle.link,
            url=f"{dashboard_url}/app?guild={self.guild_id}&tab=overview",
            row=2,
        ))

    def render_page(self) -> None:
        if self.page == -1:
            render_home(self)
            return

        original_render_page(self)

        # Nettoyage transversal des composants des pages internes : labels simples,
        # placeholders explicites et aucun symbole décoratif ambigu.
        for item in self.children:
            try:
                if isinstance(item, discord.ui.Button):
                    item.label = _clean_button_label(item.label)
                elif isinstance(item, discord.ui.Select):
                    placeholder = str(item.placeholder or "").strip()
                    placeholder = placeholder.replace("Choisissez", "Choisis").replace("Choisir", "Sélectionner")
                    item.placeholder = placeholder[:150] if placeholder else "Sélectionne une option…"
            except Exception:
                logger.debug("Composant +setup non nettoyable.", exc_info=True)

    configuration.SetupView._build_home_embed = build_home_embed
    configuration.SetupView.build_embed = build_embed
    configuration.SetupView._render_home = render_home
    configuration.SetupView.render_page = render_page

    _INSTALLED = True
    logger.info("Nouveau +setup chargé : centre de contrôle clair, modules guidés et navigation utile.")
