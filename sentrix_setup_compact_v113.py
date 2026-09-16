"""SentriX V113 — /setup compact, lisible et réellement utile.

Cette couche ne duplique pas la logique métier du cog Configuration. Elle réutilise les
sélecteurs, validations, sauvegardes, logs, AutoMod et assistants existants, puis réduit
la surface principale de /setup à cinq entrées : Configuration, Sécurité, Modules,
Setup Auto et Terminer.

Le branchement est effectué après le chargement des cogs par V112. Les actions de
navigation utilisent volontairement les custom_id dynamiques déjà persistants de V2,
ce qui conserve le comportement après redémarrage pour les boutons principaux.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

import discord

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-v113")

_CONFIG_MODULE = None
_INSTALLED = False

# Pages existantes réutilisées comme emplacements persistants. Les anciennes pages
# avancées restent accessibles depuis Modules (rôles, niveaux, logs, gestionnaires).
PAGE_HOME = -1
PAGE_CONFIGURATION = 0
PAGE_MANAGERS_PROXY = 2
PAGE_MODULES = 3
PAGE_LEVELS = 4
PAGE_LOGS = 5
PAGE_AUTO = 6
PAGE_SECURITY = 7
PAGE_SUMMARY = 8

_COMPACT_SETTINGS = (
    ("mod_role", "role", "Rôle staff", "Rôle utilisé pour la modération"),
    ("log_channel", "channel", "Salon principal des logs", "Salon de repli pour les journaux"),
    ("welcome_channel", "channel", "Salon de bienvenue", "Arrivées des membres"),
    ("goodbye_channel", "channel", "Salon de départ", "Départs des membres"),
    ("announce_channel", "channel", "Salon des annonces", "Annonces générales"),
    ("suggest_channel", "channel", "Salon des suggestions", "Suggestions des membres"),
    ("giveaway_channel", "channel", "Salon des giveaways", "Tirages au sort"),
    ("level_channel", "channel", "Salon des niveaux", "Annonces de niveau"),
    ("autorole", "role", "Rôle automatique", "Rôle donné à l'arrivée"),
    ("verify_role", "role", "Rôle de vérification", "Rôle donné après vérification"),
)


def _row_value(row: Any, key: str, default=None):
    if row is None:
        return default
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
        value = row[key]
        return default if value is None else value
    except (KeyError, TypeError, IndexError):
        return default


def _clean_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()


def _find_text_channel(guild: discord.Guild, names: tuple[str, ...]):
    wanted = {_clean_name(name) for name in names}
    # Exact d'abord, puis inclusion : évite qu'un salon aléatoire contenant "news" gagne.
    for channel in guild.text_channels:
        if _clean_name(channel.name) in wanted:
            return channel
    for channel in guild.text_channels:
        cleaned = _clean_name(channel.name)
        if any(name in cleaned for name in wanted):
            return channel
    return None


def _find_staff_role(guild: discord.Guild):
    me = guild.me
    exact = {
        "staff", "moderateur", "moderator", "mod", "administrateur", "administrator", "admin"
    }
    roles = [
        role for role in guild.roles
        if role != guild.default_role and not role.managed and (me is None or role < me.top_role)
    ]
    for role in reversed(roles):
        if _clean_name(role.name) in exact:
            return role
    for role in reversed(roles):
        name = _clean_name(role.name)
        if any(token in name for token in ("staff", "moder", "admin")):
            return role
    return None


def _find_member_role(guild: discord.Guild):
    me = guild.me
    exact = {"membre", "member", "members"}
    for role in reversed(guild.roles):
        if role == guild.default_role or role.managed:
            continue
        if me is not None and role >= me.top_role:
            continue
        if _clean_name(role.name) in exact:
            return role
    return None


def _logs_configured(conf) -> bool:
    if not conf:
        return False
    keys = (
        "log_channel", "log_server", "log_messages", "log_members", "log_voice",
        "log_roles", "log_moderation", "log_automod",
    )
    return any(bool(_row_value(conf, key)) for key in keys)


def _mention(view, field: str, conf) -> str:
    if field == "prefix":
        value = view.choices.get("prefix", _row_value(conf, "prefix", "+")) or "+"
        return f"`{value}`"
    return view._mention_current(field, conf)


async def _home_embed(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    ticket_count = int(_row_value(ticket_row, "n", 0) or 0)
    active_security = sum(1 for value in self.security_choices.values() if value)

    states = [
        ("Configuration", bool(_row_value(conf, "mod_role") or _row_value(conf, "welcome_channel") or _logs_configured(conf))),
        ("Protection", active_security > 0),
        ("Logs", _logs_configured(conf)),
        ("Tickets", ticket_count > 0),
        ("Bienvenue", bool(_row_value(conf, "welcome_channel"))),
    ]
    done = sum(1 for _label, ok in states if ok)
    lines = [f"**{label}** — {'Configuré' if ok else 'À configurer'}" for label, ok in states]

    e = embeds.neutral(
        "SentriX Setup",
        "Configure ton serveur rapidement. Choisis seulement la partie que tu veux modifier.",
        color=_CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="État du serveur", value="\n".join(lines), inline=False)
    e.add_field(name="Progression", value=f"**{done}/5** éléments essentiels configurés", inline=False)
    if self.dirty:
        e.add_field(name="À enregistrer", value="Des modifications sont en attente.", inline=False)
    e.set_footer(text="SentriX • Setup compact")
    return e


async def _configuration_embed(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    lines = [
        f"**Préfixe** — {_mention(self, 'prefix', conf)}",
        f"**Rôle staff** — {_mention(self, 'mod_role', conf)}",
        f"**Logs** — {_mention(self, 'log_channel', conf)}",
        f"**Bienvenue** — {_mention(self, 'welcome_channel', conf)}",
        f"**Annonces** — {_mention(self, 'announce_channel', conf)}",
        f"**Rôle automatique** — {_mention(self, 'autorole', conf)}",
    ]
    e = embeds.neutral(
        "SentriX Setup • Configuration",
        "Sélectionne un réglage, puis choisis directement le rôle ou le salon correspondant.",
        color=_CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="Configuration actuelle", value="\n".join(lines), inline=False)
    if self.picker_selected:
        label = next((item[2] for item in _COMPACT_SETTINGS if item[0] == self.picker_selected), self.picker_selected)
        e.add_field(name="En cours", value=label, inline=False)
    if self.dirty:
        e.add_field(name="Modifications", value="Non enregistrées — clique sur **Enregistrer**.", inline=False)
    return e


async def _security_embed(self) -> discord.Embed:
    labels = _CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS
    active = [label for field, label in labels.items() if self.security_choices.get(field)]
    inactive = [label for field, label in labels.items() if not self.security_choices.get(field)]
    total = max(1, len(labels))
    score = round(len(active) / total * 100)
    e = embeds.neutral(
        "SentriX Setup • Sécurité",
        "Choisis un niveau rapide ou règle précisément les protections actives.",
        color=_CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="Protection", value=f"**{score}%** · {len(active)}/{len(labels)} protections actives", inline=False)
    e.add_field(name="Actives", value=", ".join(active)[:1024] if active else "Aucune", inline=False)
    if inactive:
        e.add_field(name="Désactivées", value=", ".join(inactive)[:1024], inline=False)
    return e


async def _modules_embed(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    level_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (self.guild_id,)
    )
    ticket_count = int(_row_value(ticket_row, "n", 0) or 0)
    level_count = int(_row_value(level_row, "n", 0) or 0)
    lines = [
        "**Modération** — Disponible",
        f"**Bienvenue** — {'Configurée' if _row_value(conf, 'welcome_channel') else 'À configurer'}",
        f"**Tickets** — {ticket_count} panel(s)",
        f"**Niveaux** — {level_count} palier(s)",
        f"**Logs** — {'Configurés' if _logs_configured(conf) else 'À configurer'}",
        f"**Auto-rôle** — {'Configuré' if _row_value(conf, 'autorole') else 'À configurer'}",
        f"**Gestionnaires** — {len(self.managers)}",
    ]
    e = embeds.neutral(
        "SentriX Setup • Modules",
        "Vue compacte des fonctions importantes. Utilise le menu pour ouvrir uniquement celle dont tu as besoin.",
        color=_CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="État", value="\n".join(lines), inline=False)
    return e


async def _auto_plan(self) -> list[dict[str, Any]]:
    guild = self._guild()
    conf = await self.bot.db.get_guild_config(self.guild_id)
    if guild is None:
        return []
    plan: list[dict[str, Any]] = []

    if not _logs_configured(conf):
        plan.append({"kind": "logs", "label": "Créer et connecter le système de logs"})

    active_security = sum(1 for value in self.security_choices.values() if value)
    if active_security < max(3, len(_CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS) // 2):
        plan.append({"kind": "security", "label": "Appliquer la protection recommandée (niveau moyen)"})

    if not _row_value(conf, "mod_role"):
        role = _find_staff_role(guild)
        if role:
            plan.append({"kind": "mod_role", "label": f"Utiliser {role.name} comme rôle staff", "value": role.id})

    if not _row_value(conf, "welcome_channel"):
        channel = _find_text_channel(guild, ("bienvenue", "welcome", "accueil"))
        if channel:
            plan.append({"kind": "welcome_channel", "label": f"Utiliser #{channel.name} pour la bienvenue", "value": channel.id})

    if not _row_value(conf, "announce_channel"):
        channel = _find_text_channel(guild, ("annonces", "announcements", "announcement", "news"))
        if channel:
            plan.append({"kind": "announce_channel", "label": f"Utiliser #{channel.name} pour les annonces", "value": channel.id})

    if not _row_value(conf, "autorole"):
        role = _find_member_role(guild)
        if role:
            plan.append({"kind": "autorole", "label": f"Utiliser {role.name} comme rôle automatique", "value": role.id})

    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    if int(_row_value(ticket_row, "n", 0) or 0) == 0:
        plan.append({"kind": "tickets_manual", "label": "Tickets : configuration détaillée encore nécessaire"})

    return plan


async def _auto_embed(self) -> discord.Embed:
    plan = await _auto_plan(self)
    applicable = [item for item in plan if item["kind"] != "tickets_manual"]
    e = embeds.neutral(
        "SentriX Setup Auto",
        "SentriX analyse ce qui existe déjà et n'applique que des changements sûrs et prévisibles.",
        color=_CONFIG_MODULE.SETUP_COLOR_SECONDARY,
    )
    if plan:
        e.add_field(
            name=f"Analyse terminée · {len(plan)} recommandation(s)",
            value="\n".join(f"• {item['label']}" for item in plan)[:1024],
            inline=False,
        )
    else:
        e.add_field(name="Analyse terminée", value="Aucune amélioration automatique nécessaire.", inline=False)
    e.add_field(
        name="Avant application",
        value=(
            f"**{len(applicable)}** changement(s) peuvent être appliqués automatiquement. "
            "Aucun salon ou rôle existant n'est supprimé. Les tickets détaillés restent manuels."
        ),
        inline=False,
    )
    return e


async def _summary_embed(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    active_security = sum(1 for value in self.security_choices.values() if value)
    lines = [
        f"**Rôle staff** — {'OK' if _row_value(conf, 'mod_role') else 'À configurer'}",
        f"**Logs** — {'OK' if _logs_configured(conf) else 'À configurer'}",
        f"**Sécurité** — {active_security}/{len(_CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS)} protections",
        f"**Bienvenue** — {'OK' if _row_value(conf, 'welcome_channel') else 'À configurer'}",
        f"**Tickets** — {int(_row_value(ticket_row, 'n', 0) or 0)} panel(s)",
    ]
    e = embeds.neutral(
        "SentriX Setup • Terminer",
        "Vérifie l'essentiel avant de fermer l'assistant.",
        color=_CONFIG_MODULE.SETUP_COLOR_SUCCESS,
    )
    e.add_field(name="Résumé", value="\n".join(lines), inline=False)
    checks = await self._run_final_checks(self._guild(), conf)
    e.add_field(name="Vérifications finales", value="\n".join(checks)[:1024], inline=False)
    if self.dirty:
        e.add_field(name="Attention", value="Des changements ne sont pas encore enregistrés.", inline=False)
    return e


def _add_nav(view, *, save: bool = False, summary: bool = True, cancel: bool = True, row: int = 4):
    button = _CONFIG_MODULE.SetupNavButton
    view.add_item(button("home", view.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=row))
    if save:
        view.add_item(button("save", view.message_id, label="Enregistrer", style=discord.ButtonStyle.success, row=row))
    if summary:
        view.add_item(button("summary", view.message_id, label="Terminer", style=discord.ButtonStyle.primary, row=row))
    if cancel:
        view.add_item(button("cancel", view.message_id, label="Fermer", style=discord.ButtonStyle.danger, row=row))


def _render_home(self):
    self.clear_items()
    button = _CONFIG_MODULE.SetupNavButton
    self.add_item(button("prev", self.message_id, label="Configuration", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("next", self.message_id, label="Sécurité", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("preview", self.message_id, label="Modules", style=discord.ButtonStyle.secondary, row=0))
    self.add_item(button("restart", self.message_id, label="Setup Auto", style=discord.ButtonStyle.success, row=1))
    self.add_item(button("summary", self.message_id, label="Terminer", style=discord.ButtonStyle.secondary, row=1))


def _configuration_picker_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view.picker_selected = select.values[0]
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    return callback


def _modules_picker_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        target = select.values[0]
        if target == "tickets":
            return await view._tickets_hint(interaction)
        mapping = {
            "configuration": PAGE_CONFIGURATION,
            "security": PAGE_SECURITY,
            "roles": 1,
            "managers": PAGE_MANAGERS_PROXY,
            "levels": PAGE_LEVELS,
            "logs": PAGE_LOGS,
        }
        view.page = mapping.get(target, PAGE_MODULES)
        view.picker_selected = None
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    return callback


async def _auto_apply(view, interaction: discord.Interaction):
    plan = await _auto_plan(view)
    applicable = [item for item in plan if item["kind"] != "tickets_manual"]
    if not applicable:
        return await interaction.response.send_message("Aucun changement automatique nécessaire.", ephemeral=True)

    await interaction.response.defer()
    progress = embeds.neutral(
        "SentriX Setup Auto",
        "Configuration en cours…\n\nAnalyse terminée · application des réglages sûrs.",
        color=_CONFIG_MODULE.SETUP_COLOR_SECONDARY,
    )
    try:
        await interaction.edit_original_response(embed=progress, view=None)
    except discord.HTTPException:
        pass

    guild = interaction.guild
    config_cog = view.bot.get_cog("Configuration")
    applied: list[str] = []
    skipped: list[str] = []

    for item in applicable:
        kind = item["kind"]
        try:
            if kind == "security":
                for field, value in _CONFIG_MODULE.SECURITY_PRESETS.get("moyen", {}).items():
                    await view.bot.db.set_automod(view.guild_id, field, value)
                    view.security_choices[field] = value
                await view.bot.db.set_guild_config(view.guild_id, "security_level", "moyen")
                automod = view.bot.get_cog("Automod")
                if automod:
                    automod.automod_cache.pop(view.guild_id, None)
                view.security_touched = True
            elif kind == "logs":
                if not guild.me or not guild.me.guild_permissions.manage_channels:
                    skipped.append("Logs : permission Gérer les salons manquante")
                    continue
                created = await config_cog.create_log_channels(guild, interaction.user)
                view.logs_created.extend(created)
            elif kind in {"mod_role", "welcome_channel", "announce_channel", "autorole"}:
                await view.bot.db.set_guild_config(view.guild_id, kind, item["value"])
            else:
                continue
            applied.append(item["label"])
            await view.bot.db.log_setup_history(
                view.guild_id,
                interaction.user.id,
                "Setup Auto",
                "réglage automatique",
                new_value=item["label"],
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            skipped.append(f"{item['label']} : {type(exc).__name__}")
        except Exception as exc:  # une recommandation ne doit pas annuler les autres
            logger.exception("Setup Auto V113 : échec sur %s guild=%s", kind, view.guild_id)
            skipped.append(f"{item['label']} : {type(exc).__name__}")

    await view.persist_session()
    view.render_page()
    await view._refresh_message(interaction)

    text = f"Setup Auto terminé : **{len(applied)}** changement(s) appliqué(s)."
    if skipped:
        text += "\nÀ vérifier : " + " ; ".join(skipped)[:1200]
    await interaction.followup.send(text, ephemeral=True)


def _render_page(self):
    # Accueil compact.
    if self.page == PAGE_HOME:
        _render_home(self)
        return

    # Page Configuration : un menu de réglages + un seul sélecteur contextuel.
    if self.page == PAGE_CONFIGURATION:
        self.clear_items()
        picker = discord.ui.Select(
            placeholder="Choisir un réglage à modifier",
            options=[
                discord.SelectOption(label=label, value=field, description=description[:100])
                for field, _kind, label, description in _COMPACT_SETTINGS
            ],
            row=0,
        )
        picker.callback = _configuration_picker_callback(self, picker)
        self.add_item(picker)

        if self.picker_selected:
            meta = next((item for item in _COMPACT_SETTINGS if item[0] == self.picker_selected), None)
            if meta:
                field, kind, label, _description = meta
                if kind == "role":
                    value_select = discord.ui.RoleSelect(placeholder=f"Choisir : {label}"[:100], row=1)
                    value_select.callback = self._make_picker_role_value_callback(field, value_select)
                else:
                    value_select = discord.ui.ChannelSelect(
                        placeholder=f"Choisir : {label}"[:100],
                        channel_types=[discord.ChannelType.text],
                        row=1,
                    )
                    value_select.callback = self._make_picker_channel_value_callback(field, value_select)
                self.add_item(value_select)

        text_button = discord.ui.Button(label="Préfixe & messages", style=discord.ButtonStyle.secondary, row=2)
        text_button.callback = self._open_text_modal
        self.add_item(text_button)
        _add_nav(self, save=True)
        return

    # Sécurité : 3 presets + sélection précise, pas de mur de boutons.
    if self.page == PAGE_SECURITY:
        self.clear_items()
        for label, level, style in (
            ("Faible", "faible", discord.ButtonStyle.secondary),
            ("Moyen", "moyen", discord.ButtonStyle.primary),
            ("Élevé", "eleve", discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(label=label, style=style, row=0)
            button.callback = self._make_security_preset_callback(level)
            self.add_item(button)
        precise = discord.ui.Select(
            placeholder="Choisir précisément les protections",
            min_values=0,
            max_values=len(_CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS),
            options=[
                discord.SelectOption(label=label, value=field, default=bool(self.security_choices.get(field)))
                for field, label in _CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS.items()
            ],
            row=1,
        )
        precise.callback = self._make_security_select_callback(precise)
        self.add_item(precise)
        _add_nav(self, save=False)
        return

    # Modules : hub compact vers les écrans avancés déjà existants.
    if self.page == PAGE_MODULES:
        self.clear_items()
        select = discord.ui.Select(
            placeholder="Ouvrir un module",
            options=[
                discord.SelectOption(label="Configuration / salons", value="configuration"),
                discord.SelectOption(label="Sécurité", value="security"),
                discord.SelectOption(label="Rôles", value="roles"),
                discord.SelectOption(label="Tickets", value="tickets", description="Ouvre l'assistant tickets dédié"),
                discord.SelectOption(label="Niveaux", value="levels"),
                discord.SelectOption(label="Logs", value="logs"),
                discord.SelectOption(label="Gestionnaires", value="managers"),
            ],
            row=0,
        )
        select.callback = _modules_picker_callback(self, select)
        self.add_item(select)
        _add_nav(self, save=False)
        return

    # Setup Auto : analyse visible avant toute application.
    if self.page == PAGE_AUTO:
        self.clear_items()
        apply_button = discord.ui.Button(label="Appliquer les recommandations", style=discord.ButtonStyle.success, row=0)
        async def apply_callback(interaction: discord.Interaction):
            await _auto_apply(self, interaction)
        apply_button.callback = apply_callback
        self.add_item(apply_button)
        _add_nav(self, save=False, row=1)
        return

    # Résumé final très court.
    if self.page == PAGE_SUMMARY:
        self.clear_items()
        button = _CONFIG_MODULE.SetupNavButton
        self.add_item(button("home", self.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=0))
        self.add_item(button("save", self.message_id, label="Enregistrer", style=discord.ButtonStyle.primary, row=0))
        self.add_item(button("finish", self.message_id, label="Terminer le setup", style=discord.ButtonStyle.success, row=0))
        return

    # Page 2 devient un proxy persistant vers l'ancien écran Gestionnaires (ancienne page 6).
    if self.page == PAGE_MANAGERS_PROXY:
        current = self.page
        self.page = 6
        try:
            self._sentrix_v113_original_render_page()
        finally:
            self.page = current
        return

    # Rôles (1), niveaux (4), logs (5) : logique historique conservée telle quelle.
    self._sentrix_v113_original_render_page()


async def _build_embed(self) -> discord.Embed:
    if self.page == PAGE_HOME:
        return await _home_embed(self)
    if self.page == PAGE_CONFIGURATION:
        return await _configuration_embed(self)
    if self.page == PAGE_SECURITY:
        return await _security_embed(self)
    if self.page == PAGE_MODULES:
        return await _modules_embed(self)
    if self.page == PAGE_AUTO:
        return await _auto_embed(self)
    if self.page == PAGE_SUMMARY:
        return await _summary_embed(self)
    if self.page == PAGE_MANAGERS_PROXY:
        current = self.page
        self.page = 6
        try:
            return await self._sentrix_v113_original_build_embed()
        finally:
            self.page = current
    return await self._sentrix_v113_original_build_embed()


async def _handle_nav_action(self, interaction: discord.Interaction, action: str):
    # Les 5 boutons de l'accueil réutilisent les actions dynamiques historiques : aucune
    # nouvelle famille de custom_id n'est nécessaire et les boutons continuent à survivre
    # aux redémarrages via Configuration.handle_setup_nav.
    if self.page == PAGE_HOME:
        target = {
            "prev": PAGE_CONFIGURATION,
            "next": PAGE_SECURITY,
            "preview": PAGE_MODULES,
            "restart": PAGE_AUTO,
            "summary": PAGE_SUMMARY,
        }.get(action)
        if target is not None:
            self.page = target
            self.picker_selected = None
            self.render_page()
            await self.persist_session()
            return await self._refresh_message(interaction)

    if action == "home" and self.page != PAGE_HOME:
        self.page = PAGE_HOME
        self.picker_selected = None
        self.render_page()
        await self.persist_session()
        return await self._refresh_message(interaction)

    if action == "summary" and self.page != PAGE_SUMMARY:
        self.page = PAGE_SUMMARY
        self.picker_selected = None
        self.render_page()
        await self.persist_session()
        return await self._refresh_message(interaction)

    return await self._sentrix_v113_original_handle_nav_action(interaction, action)


def install_for_bot(bot) -> None:
    """Patche le SetupView déjà chargé, sans remplacer le cog ni ses données."""
    global _CONFIG_MODULE, _INSTALLED
    if _INSTALLED:
        return

    configuration = bot.get_cog("Configuration")
    if configuration is None:
        logger.warning("V113 non installé : cog Configuration absent.")
        return

    from cogs import configuration as config_module

    _CONFIG_MODULE = config_module
    view_cls = config_module.SetupView
    if getattr(view_cls, "_sentrix_v113", False):
        _INSTALLED = True
        return

    view_cls._sentrix_v113_original_render_page = view_cls.render_page
    view_cls._sentrix_v113_original_build_embed = view_cls.build_embed
    view_cls._sentrix_v113_original_handle_nav_action = view_cls.handle_nav_action

    view_cls.render_page = _render_page
    view_cls.build_embed = _build_embed
    view_cls.handle_nav_action = _handle_nav_action
    view_cls._sentrix_v113 = True

    # Les sessions déjà ouvertes en mémoire prennent immédiatement le nouveau rendu.
    for active_view in list(getattr(configuration, "active_setups", {}).values()):
        try:
            if active_view.page not in {PAGE_HOME, PAGE_CONFIGURATION, PAGE_MANAGERS_PROXY, PAGE_MODULES, PAGE_LEVELS, PAGE_LOGS, PAGE_AUTO, PAGE_SECURITY, PAGE_SUMMARY, 1}:
                active_view.page = PAGE_HOME
            active_view.render_page()
        except Exception:
            logger.exception("V113 : impossible de migrer une session /setup déjà ouverte.")

    _INSTALLED = True
    logger.info("SentriX Setup V113 installé : accueil 5 actions, sécurité compacte et Setup Auto.")


__all__ = ["install_for_bot"]
