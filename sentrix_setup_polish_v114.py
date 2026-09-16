"""SentriX V114 — Smart Setup compact, lisible et sûr.

Cette couche garde le moteur V113/V4 mais remplace son rendu par une interface courte :
aucune fausse barre de progression, aucun mur de sections, navigation regroupée, résumé
clair et fin de session sans boutons morts.

Garanties conservées :
- Smart Setup ne diminue jamais une protection déjà active ;
- snapshot obligatoire avant toute application automatique ;
- aucune suppression automatique de rôle ou salon ;
- création idempotente des ressources proposées ;
- aperçu obligatoire avant application.
"""
from __future__ import annotations

import logging
from typing import Any

import discord

import sentrix_setup_compact_v113 as v4
from utils import embeds, helpers
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-v114")
_INSTALLED = False
_ORIGINAL_BUILD_SMART_PLAN = None
_ORIGINAL_PANEL_FROM_EMBED = None
_ORIGINAL_PANEL_ROWS = None


def _progress_bar(score: int, width: int = 10) -> str:
    """Compatibilité tests/anciens appels. Le Setup V114 n'affiche plus cette barre."""
    width = max(4, min(20, int(width)))
    score = max(0, min(100, int(score)))
    filled = round((score / 100) * width)
    return "█" * filled + "░" * (width - filled)


def _status_label(score: int) -> str:
    score = max(0, min(100, int(score)))
    if score >= 90:
        return "EXCELLENT"
    if score >= 75:
        return "BON"
    if score >= 50:
        return "À RENFORCER"
    return "PRIORITAIRE"


def _status_text(score: int) -> str:
    return {
        "EXCELLENT": "Excellent",
        "BON": "Bon",
        "À RENFORCER": "À renforcer",
        "PRIORITAIRE": "Prioritaire",
    }[_status_label(score)]


def _upgrade_only_values(current: dict[str, Any], target: dict[str, Any]) -> dict[str, int]:
    """Retourne uniquement les protections à activer, jamais celles à désactiver."""
    return {
        field: 1
        for field, target_value in target.items()
        if bool(target_value) and not bool(current.get(field))
    }


def _normalised_exact(items, name: str, *, attr: str = "name"):
    wanted = v4._clean_name(name)
    for item in items:
        if v4._clean_name(getattr(item, attr, "")) == wanted:
            return item
    return None


def _effective_scopes(view) -> set[str]:
    mode = getattr(view, "_v4_mode", "complete")
    if mode == "custom":
        return set(getattr(view, "_v4_scopes", set(v4.AUTO_SCOPES)))
    if mode == "essential":
        return {"security", "logs", "roles"}
    return set(v4.AUTO_SCOPES)


async def _build_smart_plan(view) -> list[dict[str, Any]]:
    base = await _ORIGINAL_BUILD_SMART_PLAN(view)
    plan = [item for item in base if item.get("kind") != "security_preset"]
    if "security" not in _effective_scopes(view):
        return plan

    template = v4.SMART_TEMPLATES.get(view._v4_template) or v4.SMART_TEMPLATES["balanced"]
    preset = template["security"]
    current_row = await view.bot.db.get_automod(view.guild_id)
    current = dict(current_row) if current_row else {}
    target = v4._CONFIG_MODULE.SECURITY_PRESETS.get(preset, {})
    missing = _upgrade_only_values(current, target)
    if not missing:
        return plan

    item = {
        "kind": "security_preset",
        "scope": "security",
        "automatic": True,
        "preset": preset,
        "label": f"Renforcer la sécurité {preset} ({len(missing)} protection(s))",
    }
    insert_at = 0
    while insert_at < len(plan):
        candidate = plan[insert_at]
        if candidate.get("scope") != "security" or candidate.get("automatic"):
            break
        insert_at += 1
    plan.insert(insert_at, item)
    return plan


def _decorate(view, embed: discord.Embed, *, section: str) -> discord.Embed:
    embed.set_footer(text=f"SentriX • Setup • {section}")
    return embed


def _priority_lines(findings, essentials, *, limit: int = 2) -> list[str]:
    lines: list[str] = []
    for item in findings[:limit]:
        lines.append(f"• {item.title}")
    if len(lines) < limit:
        for label, ok in essentials.items():
            if ok:
                continue
            lines.append(f"• Configurer {label.lower()}")
            if len(lines) >= limit:
                break
    return lines or ["• Rien d’important à corriger"]


def _short(value: Any, limit: int = 56) -> str:
    text = str(value or "—").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clean_check_line(value: str) -> str:
    text = str(value or "").strip()
    while text and text[0] in "●○•✓✔✗✖-— ":
        text = text[1:].lstrip()
    return text or "Vérification"


async def _home_embed(self) -> discord.Embed:
    await v4._reload_security(self)
    v4._invalidate_health(self)
    health = await v4._health_snapshot(self)
    guild = self._guild()
    actions = "\n".join(_priority_lines(health["findings"], health["essentials"], limit=2))
    pending = "\n\n**Non enregistré** · pense à enregistrer tes changements." if self.dirty else ""
    restore = (
        f"\n**Restauration** · snapshot #{self._v4_last_snapshot}"
        if self._v4_last_snapshot else ""
    )
    description = (
        f"**{guild.name if guild else 'Serveur'}**\n"
        f"Santé **{health['score']}/100** · Sécurité **{health['security_score']}/100** · "
        f"Essentiel **{health['essential_done']}/5**\n\n"
        f"**À faire**\n{actions}{pending}{restore}"
    )
    e = discord.Embed(
        title="SentriX Setup",
        description=description[:400],
        colour=v4._score_colour(health["score"]),
    )
    return _decorate(self, e, section="Accueil")


async def _configuration_embed(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    simple = (
        f"Staff {_short(v4._mention(self, 'mod_role', conf), 38)} · "
        f"Logs {_short(v4._mention(self, 'log_channel', conf), 38)}\n"
        f"Bienvenue {_short(v4._mention(self, 'welcome_channel', conf), 38)} · "
        f"Annonces {_short(v4._mention(self, 'announce_channel', conf), 38)}\n"
        f"Autorôle {_short(v4._mention(self, 'autorole', conf), 38)} · "
        f"Vérif. {_short(v4._mention(self, 'verify_role', conf), 38)}"
    )
    advanced = ""
    if self._v4_expert:
        advanced = (
            "\n\n**Avancé**\n"
            f"Départ {_short(v4._mention(self, 'goodbye_channel', conf), 34)} · "
            f"Suggestions {_short(v4._mention(self, 'suggest_channel', conf), 34)}\n"
            f"Giveaways {_short(v4._mention(self, 'giveaway_channel', conf), 34)} · "
            f"Niveaux {_short(v4._mention(self, 'level_channel', conf), 34)}"
        )
    selected = ""
    if self.picker_selected:
        settings = v4._EXPERT_SETTINGS if self._v4_expert else v4._SIMPLE_SETTINGS
        label = next((item[2] for item in settings if item[0] == self.picker_selected), self.picker_selected)
        selected = f"\n\nSélection : **{label}**"
    state = "À enregistrer" if self.dirty else "À jour"
    e = discord.Embed(
        title="Configuration",
        description=(
            f"**Essentiel**\n{simple}{advanced}{selected}\n\n"
            f"Mode **{'Expert' if self._v4_expert else 'Simple'}** · **{state}**"
        )[:400],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    return _decorate(self, e, section="Configuration")


async def _security_embed(self) -> discord.Embed:
    await v4._reload_security(self)
    v4._invalidate_health(self)
    health = await v4._health_snapshot(self)
    labels = v4._CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS
    findings = [
        item for item in health["findings"]
        if str(item.code).startswith(("automod.", "botperm.", "hierarchy."))
    ]
    detail = "\n".join(f"• {item.title}" for item in findings[:3])
    if not detail:
        detail = "• Aucun problème prioritaire"
    e = discord.Embed(
        title="Sécurité",
        description=(
            f"Score **{health['security_score']}/100** · "
            f"**{health['active_security']}/{len(labels)}** protections · "
            f"{_status_text(health['security_score'])}\n\n"
            f"**À vérifier**\n{detail}"
        )[:400],
        colour=v4._score_colour(health["security_score"]),
    )
    return _decorate(self, e, section="Sécurité")


def _module_token(status: str) -> str:
    return {
        "Configuré": "Prêt",
        "Disponible": "Dispo",
        "À configurer": "À faire",
        "Indisponible": "Indispo",
    }.get(status, status)


async def _modules_embed(self) -> discord.Embed:
    states = await v4._module_states(self)
    configured = sum(1 for _name, status in states if status == "Configuré")
    lines = [f"**{_module_token(status)}** · {name}" for name, status in states[:8]]
    if len(states) > 8:
        lines.append(f"… +{len(states) - 8} autres")
    e = discord.Embed(
        title="Modules",
        description=(
            f"**{configured}/{len(states)} configurés**\n"
            + "\n".join(lines)
            + "\n\nChoisis un module dans le menu."
        )[:400],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    return _decorate(self, e, section="Modules")


async def _auto_embed(self) -> discord.Embed:
    plan = await v4._build_smart_plan(self)
    automatic = [item for item in plan if item.get("automatic")]
    manual = [item for item in plan if not item.get("automatic")]
    template = v4.SMART_TEMPLATES.get(self._v4_template) or v4.SMART_TEMPLATES["balanced"]
    mode_labels = {"essential": "Essentiel", "complete": "Complet", "custom": "Personnalisé"}
    stage = "Aperçu prêt" if self._v4_preview_ready else "À prévisualiser"
    preview = automatic if self._v4_preview_ready else plan
    lines = [f"• {item['label']}" for item in preview[:4]]
    if len(preview) > 4:
        lines.append(f"• +{len(preview) - 4} autre(s)")
    if not lines:
        lines = ["• Rien à modifier"]
    result = f"\n\nDernière opération : {_short(self._v4_last_result, 100)}" if self._v4_last_result else ""
    e = discord.Embed(
        title="Smart Setup",
        description=(
            f"Mode **{mode_labels.get(self._v4_mode, 'Complet')}** · "
            f"Modèle **{template['label']}** · **{stage}**\n"
            f"{len(automatic)} auto · {len(manual)} manuel\n\n"
            + "\n".join(lines)
            + result
            + "\n\nAucune suppression automatique."
        )[:400],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_SECONDARY,
    )
    return _decorate(self, e, section="Smart Setup")


async def _summary_embed(self) -> discord.Embed:
    diagnostic = await v4._diagnostic(self)
    warnings = []
    for line in diagnostic["lines"]:
        clean = _clean_check_line(line)
        lowered = clean.casefold()
        if any(token in lowered for token in ("n'existe", "manquant", "absent", "erreur", "impossible", "non configur")):
            warnings.append(f"• {clean}")
    if not warnings and diagnostic["passed"] < diagnostic["total"]:
        warnings = [f"• {diagnostic['total'] - diagnostic['passed']} point(s) à vérifier"]
    if not warnings:
        warnings = ["• Tout est prêt"]
    pending = "\n\n**Modifications non enregistrées.**" if self.dirty else ""
    e = discord.Embed(
        title="Diagnostic",
        description=(
            f"Score **{diagnostic['score']}/100** · "
            f"**{diagnostic['passed']}/{diagnostic['total']}** tests réussis\n\n"
            f"**Résultat**\n" + "\n".join(warnings[:4]) + pending
        )[:400],
        colour=v4._score_colour(diagnostic["score"]),
    )
    return _decorate(self, e, section="Diagnostic")


def _render_home(self):
    self.clear_items()
    button = v4._CONFIG_MODULE.SetupNavButton
    self.add_item(button("prev", self.message_id, label="Configuration", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("next", self.message_id, label="Sécurité", style=discord.ButtonStyle.secondary, row=0))
    self.add_item(button("preview", self.message_id, label="Modules", style=discord.ButtonStyle.secondary, row=0))
    self.add_item(button("restart", self.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    self.add_item(button("summary", self.message_id, label="Diagnostic", style=discord.ButtonStyle.secondary, row=1))
    tools = discord.ui.Select(
        placeholder="Outils",
        options=[
            discord.SelectOption(label="Actualiser", value="refresh", description="Recalculer l’état du serveur"),
            discord.SelectOption(label="Historique", value="history", description="Voir les dernières modifications"),
            discord.SelectOption(label="Créer un snapshot", value="snapshot", description="Sauvegarder la configuration"),
        ],
        row=2,
    )
    tools.callback = v4._home_tools_callback(self, tools)
    self.add_item(tools)


def _add_nav(view, *, save: bool = False, summary: bool = True, cancel: bool = True, row: int = 4):
    button = v4._CONFIG_MODULE.SetupNavButton
    view.add_item(button("home", view.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=row))
    if save:
        view.add_item(button("save", view.message_id, label="Enregistrer", style=discord.ButtonStyle.primary, row=row))
    if summary:
        view.add_item(button("summary", view.message_id, label="Diagnostic", style=discord.ButtonStyle.secondary, row=row))
    if cancel:
        view.add_item(button("cancel", view.message_id, label="Fermer", style=discord.ButtonStyle.secondary, row=row))


def _render_page(self):
    v4._ensure_v4_state(self)
    if self.page == v4.PAGE_HOME:
        _render_home(self)
        return

    if self.page == v4.PAGE_CONFIGURATION:
        self.clear_items()
        settings = v4._EXPERT_SETTINGS if self._v4_expert else v4._SIMPLE_SETTINGS
        picker = discord.ui.Select(
            placeholder="Choisir un réglage",
            options=[
                discord.SelectOption(label=label, value=field, description=description[:100])
                for field, _kind, label, description in settings
            ],
            row=0,
        )
        picker.callback = v4._configuration_picker_callback(self, picker)
        self.add_item(picker)
        if self.picker_selected:
            meta = next((item for item in settings if item[0] == self.picker_selected), None)
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
        text_button = discord.ui.Button(label="Textes", style=discord.ButtonStyle.secondary, row=2)
        text_button.callback = self._open_text_modal
        self.add_item(text_button)
        search_button = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, row=2)
        async def search_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(v4.SetupSearchModal(self))
        search_button.callback = search_callback
        self.add_item(search_button)
        expert_button = discord.ui.Button(
            label="Mode simple" if self._v4_expert else "Mode expert",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        expert_button.callback = v4._toggle_expert_callback(self)
        self.add_item(expert_button)
        _add_nav(self, save=self.dirty, row=3)
        return

    if self.page == v4.PAGE_SECURITY:
        self.clear_items()
        for label, level, style in (
            ("Faible", "faible", discord.ButtonStyle.secondary),
            ("Moyen", "moyen", discord.ButtonStyle.primary),
            ("Élevé", "eleve", discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(label=label, style=style, row=0)
            button.callback = self._make_security_preset_callback(level)
            self.add_item(button)
        options = [
            discord.SelectOption(label=label, value=field, default=bool(self.security_choices.get(field)))
            for field, label in list(v4._CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS.items())[:25]
        ]
        precise = discord.ui.Select(
            placeholder="Protections actives",
            min_values=0,
            max_values=len(options),
            options=options,
            row=1,
        )
        precise.callback = self._make_security_select_callback(precise)
        self.add_item(precise)
        fix_button = discord.ui.Button(label="Corriger automatiquement", style=discord.ButtonStyle.success, row=2)
        async def fix_callback(interaction: discord.Interaction):
            await _apply_safe_security_fixes(self, interaction)
        fix_button.callback = fix_callback
        self.add_item(fix_button)
        _add_nav(self, save=False, row=3)
        return

    if self.page == v4.PAGE_MODULES:
        self.clear_items()
        select = discord.ui.Select(
            placeholder="Choisir un module",
            options=[
                discord.SelectOption(label="Configuration", value="configuration"),
                discord.SelectOption(label="Sécurité", value="security"),
                discord.SelectOption(label="Rôles", value="roles"),
                discord.SelectOption(label="Tickets", value="tickets"),
                discord.SelectOption(label="Vérification", value="verification"),
                discord.SelectOption(label="Niveaux", value="levels"),
                discord.SelectOption(label="Logs", value="logs"),
                discord.SelectOption(label="Gestionnaires", value="managers"),
                discord.SelectOption(label="IA", value="ai"),
                discord.SelectOption(label="Notifications", value="notifications"),
            ],
            row=0,
        )
        select.callback = _modules_picker_callback(self, select)
        self.add_item(select)
        _add_nav(self, save=False, summary=False, row=1)
        return

    if self.page == v4.PAGE_AUTO:
        self.clear_items()
        for label, mode, style in (
            ("Essentiel", "essential", discord.ButtonStyle.secondary),
            ("Complet", "complete", discord.ButtonStyle.primary),
            ("Personnalisé", "custom", discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(
                label=label, style=style, row=0, disabled=self._v4_mode == mode
            )
            button.callback = v4._set_auto_mode(self, mode)
            self.add_item(button)
        template_select = discord.ui.Select(
            placeholder="Modèle de serveur",
            options=[
                discord.SelectOption(
                    label=meta["label"],
                    value=key,
                    description=meta["description"][:100],
                    default=self._v4_template == key,
                )
                for key, meta in v4.SMART_TEMPLATES.items()
            ],
            row=1,
        )
        template_select.callback = v4._template_callback(self, template_select)
        self.add_item(template_select)
        if self._v4_mode == "custom":
            scope_select = discord.ui.Select(
                placeholder="Ce que Smart Setup peut modifier",
                min_values=1,
                max_values=len(v4.AUTO_SCOPES),
                options=[
                    discord.SelectOption(
                        label=label, value=key, default=key in self._v4_scopes
                    )
                    for key, label in v4.AUTO_SCOPES.items()
                ],
                row=2,
            )
            scope_select.callback = v4._scope_callback(self, scope_select)
            self.add_item(scope_select)
        action_row = 3
        preview = discord.ui.Button(label="Prévisualiser", style=discord.ButtonStyle.secondary, row=action_row)
        async def preview_callback(interaction: discord.Interaction):
            await v4._preview_auto(self, interaction)
        preview.callback = preview_callback
        self.add_item(preview)
        apply_button = discord.ui.Button(
            label="Appliquer",
            style=discord.ButtonStyle.success,
            row=action_row,
            disabled=not self._v4_preview_ready,
        )
        async def apply_callback(interaction: discord.Interaction):
            await _apply_auto(self, interaction)
        apply_button.callback = apply_callback
        self.add_item(apply_button)
        if self._v4_last_snapshot:
            rollback = discord.ui.Button(label="Restaurer", style=discord.ButtonStyle.danger, row=action_row)
            async def rollback_callback(interaction: discord.Interaction):
                await v4._rollback_auto(self, interaction)
            rollback.callback = rollback_callback
            self.add_item(rollback)
        _add_nav(self, save=False, row=4)
        return

    if self.page == v4.PAGE_SUMMARY:
        self.clear_items()
        button = v4._CONFIG_MODULE.SetupNavButton
        self.add_item(button("home", self.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=0))
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, row=0)
        async def refresh_callback(interaction: discord.Interaction):
            v4._invalidate_health(self)
            await self._refresh_message(interaction)
        refresh.callback = refresh_callback
        self.add_item(refresh)
        if self.dirty:
            self.add_item(button("save", self.message_id, label="Enregistrer", style=discord.ButtonStyle.primary, row=0))
        self.add_item(button("finish", self.message_id, label="Terminer", style=discord.ButtonStyle.success, row=0))
        return

    self._sentrix_v113_original_render_page()


def _modules_picker_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        target = select.values[0]
        if target == "configuration":
            view.page = v4.PAGE_CONFIGURATION
            view._v4_expert = False
            view.picker_selected = None
        elif target == "security":
            view.page = v4.PAGE_SECURITY
            view.picker_selected = None
        elif target == "verification":
            view.page = v4.PAGE_CONFIGURATION
            view._v4_expert = True
            view.picker_selected = "verify_role"
        elif target == "roles":
            view.page = v4.PAGE_CONFIGURATION
            view._v4_expert = True
            view.picker_selected = "autorole"
        elif target == "logs":
            view.page = v4.PAGE_CONFIGURATION
            view._v4_expert = False
            view.picker_selected = "log_channel"
        elif target == "tickets":
            return await _module_hint(view, interaction, "Tickets", "+ticketsetup", "Panels, formulaires et rôles staff.")
        elif target == "levels":
            return await _module_hint(view, interaction, "Niveaux", "+levelroles", "Rôles de niveau et progression.")
        elif target == "managers":
            return await _module_hint(view, interaction, "Gestionnaires", "/setup", "Les administrateurs gardent l’accès complet au setup.")
        elif target == "ai":
            return await _module_hint(view, interaction, "IA", "+aisetup", "Assistant, accès et génération d’images.")
        elif target == "notifications":
            return await _module_hint(view, interaction, "Notifications", "+notifs-list", "YouTube, Twitch, TikTok et rôles de notification.")
        else:
            return await interaction.response.defer()
        view.render_page()
        await view.persist_session()
        return await view._refresh_message(interaction)
    return callback


async def _apply_auto(view, interaction: discord.Interaction):
    plan = await v4._build_smart_plan(view)
    signature = v4._plan_signature(plan)
    if not view._v4_preview_ready or view._v4_preview_signature != signature:
        view._v4_preview_ready = False
        view._v4_preview_signature = None
        view.render_page()
        await view._refresh_message(interaction)
        message = "Le plan a changé. Prévisualise-le à nouveau avant application."
        if interaction.response.is_done():
            return await interaction.followup.send(message, ephemeral=True)
        return await interaction.response.send_message(message, ephemeral=True)

    automatic = [item for item in plan if item.get("automatic")]
    if not automatic:
        return await interaction.response.send_message("Aucun changement automatique nécessaire.", ephemeral=True)

    ops = getattr(view.bot, "sentrix_ops", None)
    if ops is None:
        return await interaction.response.send_message(
            "Smart Setup indisponible : le snapshot de sécurité ne peut pas être créé.",
            ephemeral=True,
        )

    await interaction.response.defer()
    try:
        snapshot_id = await ops.capture_snapshot(
            view.guild_id,
            interaction.user.id,
            label=f"Avant Smart Setup {v4.SMART_TEMPLATES.get(view._v4_template, v4.SMART_TEMPLATES['balanced'])['label']}",
            source="setup-v114-auto",
        )
    except Exception:
        logger.exception("V114 : snapshot obligatoire impossible guild=%s", view.guild_id)
        return await interaction.followup.send(
            "Smart Setup annulé : snapshot impossible. Aucun changement appliqué.",
            ephemeral=True,
        )

    guild = interaction.guild
    config_cog = view.bot.get_cog("Configuration")
    applied: list[str] = []
    skipped: list[str] = []

    for item in automatic:
        try:
            kind = item["kind"]
            if kind == "security_preset":
                current_row = await view.bot.db.get_automod(view.guild_id)
                current = dict(current_row) if current_row else {}
                target = v4._CONFIG_MODULE.SECURITY_PRESETS.get(item["preset"], {})
                upgrades = _upgrade_only_values(current, target)
                for field, value in upgrades.items():
                    await view.bot.db.set_automod(view.guild_id, field, value)
                    view.security_choices[field] = value
                automod = view.bot.get_cog("Automod")
                if automod:
                    automod.automod_cache.pop(view.guild_id, None)
                view.security_touched = bool(upgrades) or view.security_touched
                if not upgrades:
                    continue
            elif kind == "logs":
                if config_cog is None:
                    raise RuntimeError("Configuration cog absent")
                created = await config_cog.create_log_channels(guild, interaction.user)
                view.logs_created.extend(created)
            elif kind == "set_config":
                await view.bot.db.set_guild_config(view.guild_id, item["key"], item["value"])
            elif kind == "create_channel":
                existing = _normalised_exact(guild.text_channels, item["name"])
                channel = existing or await guild.create_text_channel(
                    item["name"], reason=f"SentriX Smart Setup par {interaction.user}"
                )
                await view.bot.db.set_guild_config(view.guild_id, item["key"], channel.id)
            elif kind == "create_role":
                roles = [role for role in guild.roles if not role.managed and role != guild.default_role]
                existing = _normalised_exact(roles, item["name"])
                role = existing or await guild.create_role(
                    name=item["name"], reason=f"SentriX Smart Setup par {interaction.user}"
                )
                await view.bot.db.set_guild_config(view.guild_id, item["key"], role.id)
            else:
                continue

            applied.append(item["label"])
            await view.bot.db.log_setup_history(
                view.guild_id,
                interaction.user.id,
                "Smart Setup",
                "réglage automatique",
                new_value=item["label"],
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            skipped.append(f"{item['label']} ({type(exc).__name__})")
        except Exception as exc:
            logger.exception("V114 : échec Smart Setup action=%s guild=%s", item.get("kind"), view.guild_id)
            skipped.append(f"{item['label']} ({type(exc).__name__})")

    try:
        await ops.log_admin_action(
            view.guild_id,
            interaction.user.id,
            "setup.smart-apply",
            target_type="setup",
            target_id=view._v4_template,
            before={"snapshot": snapshot_id},
            after={"applied": applied, "skipped": skipped, "mode": view._v4_mode},
            reversible=True,
        )
    except Exception:
        logger.exception("V114 : journal admin impossible guild=%s", view.guild_id)

    view._v4_last_snapshot = snapshot_id
    view._v4_last_result = (
        f"{len(applied)} changement(s) appliqué(s)"
        + (f" · {len(skipped)} à vérifier" if skipped else "")
    )
    view._v4_preview_ready = False
    view._v4_preview_signature = None
    v4._invalidate_health(view)
    await v4._reload_security(view)
    await view.persist_session()
    view.render_page()
    await view._refresh_message(interaction)

    text = f"Smart Setup terminé : {len(applied)} changement(s)."
    if skipped:
        text += f" {len(skipped)} point(s) à vérifier."
    await interaction.followup.send(text, ephemeral=True)


async def _apply_safe_security_fixes(view, interaction: discord.Interaction):
    health = await v4._health_snapshot(view, force=True)
    fixable = [item for item in health["findings"] if getattr(item, "auto_fixable", False)]
    if not fixable:
        return await interaction.response.send_message("Aucune correction sûre nécessaire.", ephemeral=True)
    ops = getattr(view.bot, "sentrix_ops", None)
    if ops is None:
        return await interaction.response.send_message("Le moteur de corrections n’est pas disponible.", ephemeral=True)

    confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
    await interaction.response.send_message(
        f"Appliquer {len(fixable)} correction(s) sûre(s) ? Un snapshot sera créé avant.",
        view=confirm,
        ephemeral=True,
    )
    await confirm.wait()
    if not confirm.value:
        return

    try:
        sid = await ops.capture_snapshot(
            view.guild_id,
            interaction.user.id,
            label="Avant corrections sécurité /setup",
            source="setup-v114-security",
        )
    except Exception:
        logger.exception("V114 : snapshot sécurité impossible guild=%s", view.guild_id)
        return await interaction.followup.send("Corrections annulées : snapshot impossible.", ephemeral=True)

    done: list[str] = []
    failed: list[str] = []
    for finding in fixable:
        try:
            await ops.apply_safe_fix(interaction.guild, interaction.user.id, finding.code)
            done.append(finding.code)
        except Exception:
            failed.append(finding.code)

    view._v4_last_snapshot = sid
    await v4._reload_security(view)
    v4._invalidate_health(view)
    view.render_page()
    await view._refresh_message(interaction)

    text = f"{len(done)} correction(s) appliquée(s)."
    if failed:
        text += f" {len(failed)} échec(s)."
    await interaction.followup.send(text, ephemeral=True)


async def _module_hint(view, interaction: discord.Interaction, title: str, command: str, detail: str):
    e = discord.Embed(
        title=title,
        description=f"{detail}\n\nCommande : **`{command}`**",
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.set_footer(text="SentriX • Setup • Module")
    return await panels.envoyer(interaction.response, panels.depuis_embed(e), ephemere=True)


async def _finish_compact(self, interaction: discord.Interaction):
    pending_keys = list(self.choices)
    if self.choices:
        for field, value in self.choices.items():
            await self.bot.db.set_guild_config(self.guild_id, field, value)
        if "prefix" in self.choices:
            self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]

    conf = await self.bot.db.get_guild_config(self.guild_id)
    checks = await self._run_final_checks(self._guild(), conf)
    warnings = []
    for line in checks:
        clean = _clean_check_line(line)
        lowered = clean.casefold()
        if any(token in lowered for token in ("n'existe", "manquant", "absent", "erreur", "impossible", "non configur")):
            warnings.append(clean)

    changes = len(pending_keys)
    changes += len(self.level_role_additions)
    changes += len(self.logs_created)
    changes += 1 if self.security_touched else 0

    await self.bot.db.log_setup_history(
        self.guild_id,
        self.author_id,
        "Configuration",
        "setup terminé",
        new_value=f"{changes} changement(s)",
    )

    self.dirty = False
    await self.bot.db.delete_setup_session(self.message_id)
    cog = self.bot.get_cog("Configuration")
    if cog:
        cog.active_setups.pop(self.message_id, None)
        cog.release_lock(self.guild_id, self.message_id)

    description = "Configuration enregistrée."
    if changes:
        description += f"\n**{changes}** changement(s) appliqué(s)."
    if warnings:
        description += "\n\n**À vérifier**\n" + "\n".join(f"• {item}" for item in warnings[:3])
    else:
        description += "\n\nTout est prêt."

    final_embed = discord.Embed(
        title="Setup terminé",
        description=description[:400],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_SUCCESS,
    )
    final_embed.set_footer(text="SentriX • Setup")

    await panels.editer(interaction.response, panels.depuis_embed(final_embed))
    self.stop()


def _is_button_like(item: Any) -> bool:
    if isinstance(item, discord.ui.Button):
        return True
    inner = getattr(item, "item", None)
    return isinstance(inner, discord.ui.Button)


def _compact_component_rows(items):
    rows: list[discord.ui.ActionRow] = []
    current: discord.ui.ActionRow | None = None
    places = 0
    last_declared = None
    for item in list(items)[:25]:
        alone = not _is_button_like(item)
        declared = getattr(item, "row", None)
        rupture = (
            current is None
            or alone
            or places >= 5
            or (declared is not None and declared != last_declared)
        )
        if rupture:
            current = discord.ui.ActionRow()
            rows.append(current)
            places = 0
        last_declared = declared
        try:
            item.row = None
            current.add_item(item)
            places += 1
        except Exception:
            continue
        if alone:
            places = 5
    return [row for row in rows if len(row.children)][:5]


def _is_setup_embed(embed: discord.Embed) -> bool:
    title = str(getattr(embed, "title", "") or "")
    footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
    return (
        footer.startswith("SentriX • Setup")
        or title.startswith("SentriX Setup")
        or "CENTRE DE CONFIGURATION SENTRIX" in title
    )


def _remove_panel_banner(panel):
    container = next(
        (child for child in getattr(panel, "children", ()) if isinstance(child, discord.ui.Container)),
        None,
    )
    if container is None:
        return panel
    children = list(getattr(container, "children", ()) or ())
    for child in children[:2]:
        if not isinstance(child, discord.ui.MediaGallery):
            continue
        remover = getattr(container, "remove_item", None)
        if not callable(remover):
            return panel
        try:
            remover(child)
            panel.avec_banniere = False
        except Exception:
            logger.debug("Impossible de retirer la bannière setup.", exc_info=True)
        break
    return panel


def _panel_from_embed_compact(embed: discord.Embed, *args, **kwargs):
    panel = _ORIGINAL_PANEL_FROM_EMBED(embed, *args, **kwargs)
    if _is_setup_embed(embed):
        _remove_panel_banner(panel)
    return panel


def _install_panel_compact_mode():
    global _ORIGINAL_PANEL_FROM_EMBED, _ORIGINAL_PANEL_ROWS
    if _ORIGINAL_PANEL_FROM_EMBED is None:
        _ORIGINAL_PANEL_FROM_EMBED = panels.depuis_embed
    if _ORIGINAL_PANEL_ROWS is None:
        _ORIGINAL_PANEL_ROWS = panels._rangees_d_items
    panels.depuis_embed = _panel_from_embed_compact
    panels._rangees_d_items = _compact_component_rows


def _install_session_recovery(configuration):
    if configuration is None or getattr(configuration, "_sentrix_v114_session_recovery", False):
        return
    original = configuration.handle_setup_nav

    async def handle_setup_nav_v114(interaction: discord.Interaction, action: str, message_id: int):
        view = configuration.active_setups.get(message_id)
        if view is None:
            session = await configuration.bot.db.get_setup_session(message_id)
            if not session or interaction.guild is None or session["guild_id"] != interaction.guild.id:
                return await interaction.response.send_message(
                    "Cette session n’est plus active. Lance `/setup` pour en ouvrir une nouvelle.",
                    ephemeral=True,
                )
        return await original(interaction, action, message_id)

    configuration.handle_setup_nav = handle_setup_nav_v114
    configuration._sentrix_v114_session_recovery = True


def install_for_bot(bot) -> None:
    global _INSTALLED, _ORIGINAL_BUILD_SMART_PLAN
    if _INSTALLED:
        return

    if not getattr(v4, "_INSTALLED", False):
        v4.install_for_bot(bot)
    if not getattr(v4, "_INSTALLED", False):
        logger.warning("V114 non installé : Setup V4 indisponible.")
        return

    if _ORIGINAL_BUILD_SMART_PLAN is None:
        _ORIGINAL_BUILD_SMART_PLAN = v4._build_smart_plan

    _install_panel_compact_mode()

    v4._decorate_embed = _decorate
    v4._home_embed = _home_embed
    v4._configuration_embed = _configuration_embed
    v4._security_embed = _security_embed
    v4._modules_embed = _modules_embed
    v4._build_smart_plan = _build_smart_plan
    v4._auto_embed = _auto_embed
    v4._summary_embed = _summary_embed
    v4._render_home = _render_home
    v4._add_nav = _add_nav
    v4._render_page = _render_page
    v4._modules_picker_callback = _modules_picker_callback
    v4._apply_auto = _apply_auto
    v4._apply_safe_security_fixes = _apply_safe_security_fixes
    v4._module_hint = _module_hint

    configuration = bot.get_cog("Configuration")
    if configuration is not None:
        view_cls = v4._CONFIG_MODULE.SetupView
        view_cls.render_page = _render_page
        view_cls._finish = _finish_compact
        _install_session_recovery(configuration)

        for active_view in list(getattr(configuration, "active_setups", {}).values()):
            try:
                active_view.render_page()
            except Exception:
                logger.exception("V114 : rafraîchissement d'une session active impossible.")

    _INSTALLED = True
    v4._V114_INSTALLED = True
    logger.info(
        "SentriX Setup V114 actif : interface compacte, boutons regroupés, "
        "aucune barre visuelle et fin de session sans boutons morts."
    )


__all__ = [
    "_progress_bar",
    "_status_label",
    "_status_text",
    "_upgrade_only_values",
    "_is_button_like",
    "_is_setup_embed",
    "install_for_bot",
]
