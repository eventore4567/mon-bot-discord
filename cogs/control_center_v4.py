"""SentriX Control Center V4.

Complète V3 sans dupliquer les moteurs métier :
- Sécurité : vérification automatique 20 facteurs, seuil 16..20, honeypot séparé ;
- Tickets : accès direct au vrai Ticket Center complet déjà fourni par cogs.tickets ;
- Bienvenue : édition des messages/images depuis Setup ;
- Niveaux/économie : monnaie configurable depuis Setup ;
- IA : diagnostic du déclencheur naturel `sentrix ...` et accès aux réglages existants.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from . import automatic_verification_v4 as auto_verify
from . import control_center_v3
from . import setup_control_center as setup_ui
from . import setup_v2_core

logger = logging.getLogger("bot.control-center-v4")


class V4CategorySelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        options = [discord.SelectOption(label="Accueil", value="__home__", description="Vue générale du Control Center")]
        for key in setup_ui.CATEGORY_ORDER:
            if key not in setup_ui.CATEGORIES:
                continue
            label, description = setup_ui.CATEGORIES[key]
            options.append(discord.SelectOption(label=label, value=key, description=description[:100]))
        extras = [
            ("security_auto", "Sécurité — Vérification auto", "20 facteurs automatiques, seuil et honeypot"),
            ("tickets_center", "Tickets — Ticket Center", "Panels, types, formulaires, boutons staff et transcripts"),
            ("welcome_messages", "Accueil — Messages", "Textes, variables et image de bienvenue/départ"),
            ("roles_panel", "Rôles — Panel de choix", "Salon et rôles proposés aux membres"),
            ("levels_economy", "Niveaux — Économie", "Monnaie et paramètres économie"),
            ("ai_natural", "IA — Conversation naturelle", "Déclencheur sentrix ..., limites et mémoire"),
        ]
        for value, label, description in extras:
            options.append(discord.SelectOption(label=label, value=value, description=description))
        super().__init__(placeholder="Choisir une page du Control Center", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.owner._v3_subpage = None
        self.owner._v4_subpage = None
        mapping = {
            "security_auto": ("security", "auto_verification"),
            "tickets_center": ("tickets", "ticket_center"),
            "welcome_messages": ("welcome", "messages"),
            "roles_panel": ("roles", "panel"),
            "levels_economy": ("levels", "economy"),
            "ai_natural": ("ai", "natural"),
        }
        if value == "__home__":
            self.owner.category = None
        elif value in mapping:
            self.owner.category, self.owner._v4_subpage = mapping[value]
            if value == "roles_panel":
                self.owner._v3_subpage = "panel"
        else:
            self.owner.category = value
        self.owner.selected_log = self.owner.selected_ticket = self.owner.selected_notification = None
        await self.owner.refresh(interaction)


class AutoVerifyActionSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Vérification automatique & honeypot",
            options=[
                discord.SelectOption(label="Activer / actualiser", value="enable", description="Crée/actualise les rôles et salons, sans captcha"),
                discord.SelectOption(label="Honeypot : softban", value="softban", description="Le piège softban uniquement les comptes qui écrivent dedans"),
                discord.SelectOption(label="Honeypot : expulsion", value="kick", description="Le piège expulse les comptes qui écrivent dedans"),
                discord.SelectOption(label="Désactiver la vérification", value="disable", description="Conserve les salons et rôles"),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        cog = self.owner.bot.get_cog(auto_verify._COG_NAME)
        if cog is None:
            return await interaction.response.send_message("Le moteur de vérification automatique n'est pas chargé.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        value = self.values[0]
        if value == "disable":
            _ok, message = await cog.disable_system(self.owner.guild)
        else:
            sanction = "kick" if value == "kick" else "softban"
            result, error = await cog.create_or_refresh_system(self.owner.guild, sanction=sanction)
            if error:
                return await interaction.followup.send(error, ephemeral=True)
            settings = await cog.settings(self.owner.guild.id)
            message = (
                f"Vérification automatique active : **{settings['threshold']}/20** minimum. "
                f"Info : {result['verify'].mention} • Honeypot : {result['trap'].mention}."
            )
        await interaction.followup.send(message, ephemeral=True)
        try:
            await self.owner.refresh_from_followup(interaction)
        except Exception:
            pass


class AutoThresholdSelect(discord.ui.Select):
    def __init__(self, owner, current: int = 16):
        self.owner = owner
        options = [
            discord.SelectOption(label=f"{value}/20", value=str(value), description=("Recommandé" if value == 16 else "Plus strict"), default=value == current)
            for value in range(16, 21)
        ]
        super().__init__(placeholder="Seuil automatique minimum", options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        cog = self.owner.bot.get_cog(auto_verify._COG_NAME)
        if cog is None:
            return await interaction.response.send_message("Moteur indisponible.", ephemeral=True)
        value = auto_verify.clamp_threshold(self.values[0])
        await cog.update_settings(self.owner.guild.id, threshold=value, actor_id=interaction.user.id)
        await interaction.response.send_message(f"Seuil enregistré : **{value}/20** minimum.", ephemeral=True)


class AutoAgeSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Ancienneté du compte utilisée par le score",
            options=[
                discord.SelectOption(label="30 minutes", value="30"),
                discord.SelectOption(label="1 heure", value="60"),
                discord.SelectOption(label="6 heures", value="360"),
                discord.SelectOption(label="1 jour", value="1440"),
                discord.SelectOption(label="7 jours", value="10080"),
            ],
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        cog = self.owner.bot.get_cog(auto_verify._COG_NAME)
        if cog is None:
            return await interaction.response.send_message("Moteur indisponible.", ephemeral=True)
        minutes = int(self.values[0])
        await cog.update_settings(self.owner.guild.id, min_account_age_minutes=minutes, actor_id=interaction.user.id)
        await interaction.response.send_message(f"Ancienneté de référence enregistrée : **{minutes} min**.", ephemeral=True)


class TicketCenterSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Configurer le Ticket Center",
            options=[
                discord.SelectOption(label="Ouvrir le Ticket Center complet", value="hub", description="Panels, types, formulaires et boutons staff"),
                discord.SelectOption(label="Statistiques des tickets", value="stats", description="Ouverts, fermés, notes et répartition"),
                discord.SelectOption(label="Transcript DM : activer/désactiver", value="transcript", description="Envoi du transcript au créateur à la fermeture"),
                discord.SelectOption(label="Satisfaction : activer/désactiver", value="rating", description="Demande une note après fermeture"),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        cog = self.owner.bot.get_cog("Tickets")
        if cog is None:
            return await interaction.response.send_message("Le moteur de tickets n'est pas chargé.", ephemeral=True)
        value = self.values[0]
        if value == "hub":
            from . import tickets as ticket_module
            panels = await self.owner.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE guild_id=?", (self.owner.guild.id,))
            types = await self.owner.bot.db.fetchall("SELECT * FROM ticket_types WHERE guild_id=?", (self.owner.guild.id,))
            opened = await self.owner.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='ouvert'", (self.owner.guild.id,))
            panel = embeds.brand(
                "SentriX — Ticket Center",
                "Configuration complète : panels, apparence, types, catégories, rôles support, formulaires, limites, fermeture automatique, logs et boutons staff.",
            )
            panel.add_field(name="Panels", value=str(len(panels)), inline=True)
            panel.add_field(name="Types", value=str(len(types)), inline=True)
            panel.add_field(name="Ouverts", value=str(opened["c"] if opened else 0), inline=True)
            view_cls = getattr(ticket_module, "TicketSetupHubView", None)
            if view_cls is None:
                return await interaction.response.send_message("Le hub Ticket Center est indisponible.", ephemeral=True)
            return await interaction.response.send_message(embed=panel, view=view_cls(cog, interaction.user.id), ephemeral=True)
        if value == "stats":
            return await cog.send_stats(interaction)
        conf = await self.owner.bot.db.get_guild_config(self.owner.guild.id)
        if value == "transcript":
            new_value = 0 if bool(conf["ticket_transcript_dm"]) else 1
            await self.owner.bot.db.set_guild_config(self.owner.guild.id, "ticket_transcript_dm", new_value)
            text = "activé" if new_value else "désactivé"
            return await interaction.response.send_message(f"Transcript en DM **{text}**.", ephemeral=True)
        if value == "rating":
            new_value = 0 if bool(conf["ticket_rating_enabled"]) else 1
            await self.owner.bot.db.set_guild_config(self.owner.guild.id, "ticket_rating_enabled", new_value)
            text = "activée" if new_value else "désactivée"
            return await interaction.response.send_message(f"Note de satisfaction **{text}**.", ephemeral=True)


class TicketCommandsSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Outils tickets disponibles",
            options=[
                discord.SelectOption(label="Panels : créer / modifier / dupliquer / envoyer", value="panels"),
                discord.SelectOption(label="Types : rôle support / catégorie / nom / message", value="types"),
                discord.SelectOption(label="Formulaires : jusqu'à 5 questions", value="forms"),
                discord.SelectOption(label="Staff : claim / unclaim / add / remove / rename", value="staff"),
                discord.SelectOption(label="Automatisation : limite / autoclose / transcript / logs", value="automation"),
            ],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        docs = {
            "panels": "Le **Ticket Center complet** permet de créer, éditer, supprimer, prévisualiser, envoyer et dupliquer les panels.",
            "types": "Chaque type peut avoir son **rôle support**, sa **catégorie**, son format de salon, emoji, message d'ouverture, logs et limite.",
            "forms": "Chaque type peut avoir un formulaire personnalisé jusqu'à **5 questions**.",
            "staff": "Boutons staff configurables : **claim, unclaim, ajouter, retirer, renommer, transférer, note, relancer, fermer**.",
            "automation": "Réglages disponibles : **transcript**, DM, satisfaction, limite par membre, logs par type et fermeture automatique par inactivité.",
        }
        await interaction.response.send_message(docs[self.values[0]], ephemeral=True)


class WelcomeMessagesModal(discord.ui.Modal, title="SentriX • Messages d'accueil"):
    def __init__(self, owner, conf):
        super().__init__()
        self.owner = owner
        self.welcome = discord.ui.TextInput(
            label="Message de bienvenue",
            style=discord.TextStyle.paragraph,
            default=(conf["welcome_message"] or "Bienvenue {mention} sur **{server}** !"),
            max_length=1000,
        )
        self.goodbye = discord.ui.TextInput(
            label="Message de départ",
            style=discord.TextStyle.paragraph,
            default=(conf["goodbye_message"] or "{user} a quitté **{server}**."),
            max_length=1000,
        )
        self.image = discord.ui.TextInput(
            label="Image de bienvenue (URL, optionnel)",
            default=(conf["welcome_image_url"] or ""),
            required=False,
            max_length=500,
        )
        self.add_item(self.welcome)
        self.add_item(self.goodbye)
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "welcome_message", self.welcome.value)
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "goodbye_message", self.goodbye.value)
        await self.owner.bot.db.set_guild_config(self.owner.guild.id, "welcome_image_url", self.image.value.strip() or None)
        await interaction.response.send_message("Messages d'accueil enregistrés.", ephemeral=True)


class WelcomeActionSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Configurer les messages d'accueil",
            options=[
                discord.SelectOption(label="Modifier bienvenue / départ / image", value="edit"),
                discord.SelectOption(label="Afficher les variables disponibles", value="vars"),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "vars":
            return await interaction.response.send_message(
                "Variables : `{mention}` `{member}` `{user}` `{username}` `{display_name}` `{server}` `{member_count}`",
                ephemeral=True,
            )
        conf = await self.owner.bot.db.get_guild_config(self.owner.guild.id)
        await interaction.response.send_modal(WelcomeMessagesModal(self.owner, conf))


class EconomyModal(discord.ui.Modal, title="SentriX • Monnaie du serveur"):
    def __init__(self, owner, settings: dict[str, Any]):
        super().__init__()
        self.owner = owner
        self.singular = discord.ui.TextInput(label="Nom au singulier", default=settings["currency_singular"], max_length=32)
        self.plural = discord.ui.TextInput(label="Nom au pluriel", default=settings["currency_plural"], max_length=32)
        self.symbol = discord.ui.TextInput(label="Symbole / emoji", default=settings["currency_symbol"], max_length=16)
        self.add_item(self.singular)
        self.add_item(self.plural)
        self.add_item(self.symbol)

    async def on_submit(self, interaction: discord.Interaction):
        await setup_v2_core.set_currency(
            self.owner.bot,
            self.owner.guild.id,
            self.singular.value,
            self.plural.value,
            self.symbol.value,
            actor_id=interaction.user.id,
        )
        await interaction.response.send_message("Monnaie enregistrée.", ephemeral=True)


class EconomyActionSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(placeholder="Configurer l'économie", options=[discord.SelectOption(label="Modifier la monnaie", value="currency")], row=2)

    async def callback(self, interaction: discord.Interaction):
        settings = await setup_v2_core.economy_settings(self.owner.bot, self.owner.guild.id)
        await interaction.response.send_modal(EconomyModal(self.owner, settings))


class NaturalAiSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Conversation naturelle SentriX",
            options=[
                discord.SelectOption(label="Tester `sentrix salut`", value="test", description='Vérifiez que le listener naturel est chargé'),
                discord.SelectOption(label="Ouvrir les limites IA", value="limits", description="Cooldown, minute et limites quotidiennes"),
            ],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "limits":
            return await interaction.response.send_modal(setup_ui.AiModal(self.owner))
        cog = self.owner.bot.get_cog("Ai") or self.owner.bot.get_cog("AI")
        listener_ok = bool(cog and hasattr(cog, "on_message") and hasattr(cog, "send_sentrix_reply"))
        text = (
            "Listener naturel **chargé** : `sentrix salut`, `sentrix bonjour`, `sentrix aide moi` sont reconnus."
            if listener_ok else
            "Le listener naturel IA n'est pas chargé : vérifie le chargement de `cogs.ai`."
        )
        await interaction.response.send_message(text, ephemeral=True)


def _remove_rows_from(view, minimum_row: int = 2) -> None:
    for child in list(view.children):
        row = getattr(child, "row", None)
        if row is not None and row >= minimum_row:
            view.remove_item(child)


async def _build_embed_v4(self):
    panel = await self._sentrix_v4_previous_build_embed()
    category = getattr(self, "category", None)
    sub = getattr(self, "_v4_subpage", None)

    if category == "security" and sub == "auto_verification":
        # Retire les descriptions de l'ancien challenge V3 si présentes.
        for index in reversed(range(len(panel.fields))):
            if panel.fields[index].name in {"Portail de vérification", "Contrôles", "Honeypot"}:
                panel.remove_field(index)
        cog = self.bot.get_cog(auto_verify._COG_NAME)
        conf = await cog.config(self.guild.id, enabled_only=False) if cog else None
        settings = await cog.settings(self.guild.id) if cog else {"threshold": 16, "min_account_age_minutes": 60}
        panel.title = "SentriX — Sécurité • Vérification automatique"
        panel.description = "Aucun captcha ni calcul : SentriX décide automatiquement à partir de **20 facteurs**."
        panel.add_field(name="Décision", value=f"Validation à **{settings['threshold']}/20 minimum**\nUn score inférieur laisse le membre Non vérifié ; il n'est pas banni.", inline=True)
        panel.add_field(name="Compte", value=f"Ancienneté de référence : **{settings['min_account_age_minutes']} min**\nMembership Screening : pris en compte automatiquement", inline=True)
        panel.add_field(name="Honeypot", value=("ACTIF" if conf and int(conf["enabled"]) else "INACTIF") + "\nProtection séparée du score de vérification.", inline=True)
        panel.add_field(
            name="20 facteurs analysés",
            value=(
                "Type de compte • système • règles Discord • ancienneté configurée • 1j • 7j • 30j • cohérence snowflake • "
                "date d'entrée • profil • timeout • honeypot entrée • historique honeypot • réentrées • échecs récents • "
                "rafale de raid • stabilité d'entrée • historique sécurité • historique de vérification • état des rôles"
            )[:1024],
            inline=False,
        )

    elif category == "tickets":
        panels = await self.bot.db.fetchall("SELECT id,enabled FROM ticket_panels_v2 WHERE guild_id=?", (self.guild.id,))
        types = await self.bot.db.fetchall("SELECT id FROM ticket_types WHERE guild_id=?", (self.guild.id,))
        opened = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='ouvert'", (self.guild.id,))
        buttons = 0
        try:
            from .tickets import get_button_settings
            settings = await get_button_settings(self.bot, self.guild.id)
            buttons = sum(1 for cfg in settings.values() if cfg.get("enabled"))
        except Exception:
            pass
        conf = await self.bot.db.get_guild_config(self.guild.id)
        panel.title = "SentriX — Tickets • Ticket Center"
        panel.description = "Gestion complète des tickets, basée sur le moteur Ticket V2 existant — pas un simple résumé."
        panel.add_field(name="Structure", value=f"**{len(panels)}** panel(s) • **{len(types)}** type(s) • **{opened['c'] if opened else 0}** ticket(s) ouvert(s)", inline=False)
        panel.add_field(name="Panels", value="Créer • modifier • supprimer • prévisualiser • envoyer • dupliquer • activer/désactiver", inline=True)
        panel.add_field(name="Types", value="Rôle support • catégorie • emoji • nom salon • message d'ouverture • limite • autoclose • logs", inline=True)
        panel.add_field(name="Formulaires", value="Jusqu'à **5 questions** par type, texte court/long et obligatoire/facultatif.", inline=True)
        panel.add_field(name="Contrôles staff", value=f"**{buttons}/9** boutons actifs\nClaim • unclaim • add • remove • rename • transfer • note • bump • close", inline=True)
        panel.add_field(name="Fermeture", value=f"Transcript DM : **{'OUI' if conf['ticket_transcript_dm'] else 'NON'}**\nSatisfaction : **{'OUI' if conf['ticket_rating_enabled'] else 'NON'}**", inline=True)
        panel.add_field(name="Outils", value="Transcript manuel • statistiques • réouverture • notes • historique • suppression différée", inline=True)

    elif category == "welcome" and sub == "messages":
        conf = await self.bot.db.get_guild_config(self.guild.id)
        panel.title = "SentriX — Accueil • Messages"
        panel.add_field(name="Bienvenue", value=(conf["welcome_message"] or "Message par défaut")[:1024], inline=False)
        panel.add_field(name="Départ", value=(conf["goodbye_message"] or "Message par défaut")[:1024], inline=False)
        panel.add_field(name="Variables", value="`{mention}` `{member}` `{user}` `{username}` `{display_name}` `{server}` `{member_count}`", inline=False)

    elif category == "levels" and sub == "economy":
        currency = await setup_v2_core.economy_settings(self.bot, self.guild.id)
        panel.title = "SentriX — Niveaux • Économie"
        panel.add_field(name="Monnaie", value=f"{currency['currency_singular']} / {currency['currency_plural']} • symbole {currency['currency_symbol']}", inline=False)

    elif category == "ai" and sub == "natural":
        panel.title = "SentriX — IA • Conversation naturelle"
        panel.add_field(name="Déclenchement", value="`sentrix salut`\n`sentrix bonjour`\n`sentrix ça va`\n`sentrix aide moi`", inline=True)
        panel.add_field(name="Comportement", value="Le préfixe `sentrix ...` est capté par le listener IA puis répond en conversation libre, sans `+ai` obligatoire.", inline=True)
    return panel


def _render_v4(self) -> None:
    self._sentrix_v4_previous_render()
    # Une seule navigation, enrichie avec les sous-centres V4.
    for child in list(self.children):
        if isinstance(child, control_center_v3.V3CategorySelect):
            self.remove_item(child)
    try:
        self.add_item(V4CategorySelect(self))
    except ValueError:
        # Au cas où une vue historique occupe déjà la ligne 0, ne jamais casser Setup.
        pass

    category = getattr(self, "category", None)
    sub = getattr(self, "_v4_subpage", None)
    if category == "security" and sub == "auto_verification":
        _remove_rows_from(self, 2)
        self.add_item(AutoVerifyActionSelect(self))
        self.add_item(AutoThresholdSelect(self))
        self.add_item(AutoAgeSelect(self))
    elif category == "tickets":
        _remove_rows_from(self, 2)
        self.add_item(TicketCenterSelect(self))
        self.add_item(TicketCommandsSelect(self))
    elif category == "welcome" and sub == "messages":
        _remove_rows_from(self, 2)
        self.add_item(WelcomeActionSelect(self))
    elif category == "levels" and sub == "economy":
        _remove_rows_from(self, 2)
        self.add_item(EconomyActionSelect(self))
    elif category == "ai" and sub == "natural":
        # Conserve le vrai modal limite V3 + ajoute seulement le diagnostic naturel.
        if not any(isinstance(x, NaturalAiSelect) for x in self.children):
            try:
                self.add_item(NaturalAiSelect(self))
            except ValueError:
                pass


async def install(bot: commands.Bot) -> None:
    await auto_verify.install(bot)
    view_cls = setup_ui.SetupView
    if getattr(view_cls, "_sentrix_control_center_v4", False):
        return
    view_cls._sentrix_v4_previous_render = view_cls.render
    view_cls._sentrix_v4_previous_build_embed = view_cls.build_embed
    view_cls.render = _render_v4
    view_cls.build_embed = _build_embed_v4
    view_cls._sentrix_control_center_v4 = True
    bot._sentrix_control_center_v4 = True
    logger.info("Control Center V4 chargé : tickets avancés + vérification auto 20 facteurs.")


__all__ = ["install", "V4CategorySelect", "TicketCenterSelect", "AutoVerifyActionSelect"]
