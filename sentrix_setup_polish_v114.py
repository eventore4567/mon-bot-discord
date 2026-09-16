"""SentriX V114 — polish visuel et durcissement du Smart Setup V4.

Cette couche reste volontairement petite : elle améliore l'interface V4 déjà installée
et corrige les points de sécurité découverts pendant la revue finale, sans dupliquer le
moteur de configuration historique.

Garanties ajoutées :
- Smart Setup ne diminue jamais une protection AutoMod déjà active ;
- aucun Smart Setup automatique ne démarre sans snapshot valide ;
- création de rôles/salons idempotente avec comparaison de nom normalisée ;
- corrections de sécurité groupées bloquées si le snapshot préalable échoue ;
- rendu plus compact et cohérent, sans surcharge d'emojis.
"""
from __future__ import annotations

import logging
from typing import Any

import discord

import sentrix_setup_compact_v113 as v4
from utils import embeds, helpers

logger = logging.getLogger("bot.setup-v114")
_INSTALLED = False


def _progress_bar(score: int, width: int = 10) -> str:
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


def _upgrade_only_values(current: dict[str, Any], target: dict[str, Any]) -> dict[str, int]:
    """Retourne uniquement les protections à ACTIVER.

    Une valeur 0 d'un preset n'est jamais appliquée par Smart Setup : un profil Moyen ne
    doit pas désactiver Anti-liens si l'administrateur l'avait déjà activé manuellement.
    """
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


def _decorate(view, embed: discord.Embed, *, section: str) -> discord.Embed:
    guild = view._guild()
    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"SentriX • Setup • {section}")
    return embed


def _priority_lines(findings, essentials) -> list[str]:
    lines: list[str] = []
    for item in findings[:3]:
        lines.append(f"**{len(lines) + 1}.** {item.title}")
    if len(lines) < 3:
        for label, ok in essentials.items():
            if ok:
                continue
            lines.append(f"**{len(lines) + 1}.** Configurer {label.lower()}")
            if len(lines) >= 3:
                break
    return lines or ["Aucune action prioritaire détectée."]


async def _home_embed(self) -> discord.Embed:
    await v4._reload_security(self)
    v4._invalidate_health(self)
    health = await v4._health_snapshot(self)
    guild = self._guild()

    e = discord.Embed(
        title="SentriX Setup",
        description=(
            f"**{guild.name if guild else 'Serveur'}**\n"
            "Centre de configuration intelligent. Les réglages importants restent visibles, "
            "les options avancées restent à un clic."
        ),
        colour=v4._score_colour(health["score"]),
    )
    e.add_field(
        name="État du serveur",
        value=(
            f"**Santé**  `{health['score']:>3}/100`  `{_status_label(health['score'])}`\n"
            f"`{_progress_bar(health['score'])}`\n\n"
            f"**Sécurité**  `{health['security_score']:>3}/100`  "
            f"`{health['active_security']}/{health['total_security']} protections`\n"
            f"`{_progress_bar(health['security_score'])}`\n\n"
            f"**Essentiel**  `{health['essential_done']}/5 prêt`"
        ),
        inline=False,
    )
    e.add_field(
        name="Prochaines actions",
        value="\n".join(_priority_lines(health["findings"], health["essentials"]))[:1024],
        inline=False,
    )
    if self.dirty:
        e.add_field(
            name="Modifications en attente",
            value="Des réglages n'ont pas encore été enregistrés. Utilise **Enregistrer** avant de terminer.",
            inline=False,
        )
    if self._v4_last_snapshot:
        e.add_field(
            name="Restauration disponible",
            value=f"Snapshot **#{self._v4_last_snapshot}** prêt si tu dois revenir en arrière.",
            inline=False,
        )
    return _decorate(self, e, section="Accueil")


async def _configuration_embed(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    e = discord.Embed(
        title="Configuration",
        description="Modifie l'essentiel rapidement. Le mode expert affiche les réglages secondaires.",
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(
        name="Base",
        value=(
            f"**Préfixe** — {v4._mention(self, 'prefix', conf)}\n"
            f"**Rôle staff** — {v4._mention(self, 'mod_role', conf)}\n"
            f"**Logs principaux** — {v4._mention(self, 'log_channel', conf)}"
        ),
        inline=False,
    )
    e.add_field(
        name="Communauté",
        value=(
            f"**Bienvenue** — {v4._mention(self, 'welcome_channel', conf)}\n"
            f"**Annonces** — {v4._mention(self, 'announce_channel', conf)}\n"
            f"**Rôle automatique** — {v4._mention(self, 'autorole', conf)}\n"
            f"**Vérification** — {v4._mention(self, 'verify_role', conf)}"
        ),
        inline=False,
    )
    if self._v4_expert:
        e.add_field(
            name="Avancé",
            value=(
                f"**Départ** — {v4._mention(self, 'goodbye_channel', conf)}\n"
                f"**Suggestions** — {v4._mention(self, 'suggest_channel', conf)}\n"
                f"**Giveaways** — {v4._mention(self, 'giveaway_channel', conf)}\n"
                f"**Niveaux** — {v4._mention(self, 'level_channel', conf)}"
            ),
            inline=False,
        )
    e.add_field(name="Mode", value=f"**{'Expert' if self._v4_expert else 'Simple'}**", inline=True)
    e.add_field(name="État", value=f"**{'À enregistrer' if self.dirty else 'À jour'}**", inline=True)
    if self.picker_selected:
        settings = v4._EXPERT_SETTINGS if self._v4_expert else v4._SIMPLE_SETTINGS
        label = next((item[2] for item in settings if item[0] == self.picker_selected), self.picker_selected)
        e.add_field(name="Réglage sélectionné", value=f"**{label}**", inline=False)
    return _decorate(self, e, section="Configuration")


async def _security_embed(self) -> discord.Embed:
    await v4._reload_security(self)
    v4._invalidate_health(self)
    health = await v4._health_snapshot(self)
    labels = v4._CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS
    security_findings = [
        item for item in health["findings"]
        if str(item.code).startswith(("automod.", "botperm.", "hierarchy."))
    ]
    e = discord.Embed(
        title="Sécurité",
        description="Vue claire des protections et des problèmes réellement actionnables.",
        colour=v4._score_colour(health["security_score"]),
    )
    e.add_field(
        name="Niveau actuel",
        value=(
            f"**{health['security_score']}/100 — {_status_label(health['security_score'])}**\n"
            f"`{_progress_bar(health['security_score'])}`\n"
            f"{health['active_security']}/{len(labels)} protections actives"
        ),
        inline=False,
    )
    if security_findings:
        e.add_field(
            name="À corriger",
            value="\n".join(f"**{index}.** {item.title}" for index, item in enumerate(security_findings[:5], 1))[:1024],
            inline=False,
        )
    else:
        e.add_field(name="À corriger", value="Aucun problème de sécurité prioritaire détecté.", inline=False)
    e.add_field(
        name="Actions",
        value="Choisis un niveau rapide, règle les protections précisément, ou applique uniquement les corrections marquées sûres.",
        inline=False,
    )
    return _decorate(self, e, section="Sécurité")


def _module_token(status: str) -> str:
    return {
        "Configuré": "PRÊT",
        "Disponible": "DISPONIBLE",
        "À configurer": "À FAIRE",
        "Indisponible": "INDISPONIBLE",
    }.get(status, status.upper())


async def _modules_embed(self) -> discord.Embed:
    states = await v4._module_states(self)
    configured = sum(1 for _name, status in states if status == "Configuré")
    available = sum(1 for _name, status in states if status in {"Configuré", "Disponible"})
    lines = [f"`{_module_token(status):<11}`  **{name}**" for name, status in states]
    e = discord.Embed(
        title="Modules",
        description="Tous les modules importants dans une seule vue, sans ouvrir dix panneaux en même temps.",
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="Résumé", value=f"**{configured} configurés** · **{available}/{len(states)} disponibles**", inline=False)
    e.add_field(name="État des modules", value="\n".join(lines)[:1024], inline=False)
    return _decorate(self, e, section="Modules")


async def _auto_embed(self) -> discord.Embed:
    plan = await v4._build_smart_plan(self)
    automatic = [item for item in plan if item.get("automatic")]
    manual = [item for item in plan if not item.get("automatic")]
    template = v4.SMART_TEMPLATES.get(self._v4_template) or v4.SMART_TEMPLATES["balanced"]
    mode_labels = {"essential": "Essentiel", "complete": "Complet", "custom": "Personnalisé"}

    e = discord.Embed(
        title="Smart Setup",
        description="Analyse → aperçu → snapshot → application → diagnostic. Rien de destructif n'est appliqué silencieusement.",
        colour=v4._CONFIG_MODULE.SETUP_COLOR_SECONDARY,
    )
    e.add_field(name="Mode", value=f"**{mode_labels.get(self._v4_mode, 'Complet')}**", inline=True)
    e.add_field(name="Modèle", value=f"**{template['label']}**", inline=True)
    e.add_field(name="Plan", value=f"**{len(automatic)} auto / {len(manual)} manuel**", inline=True)

    if self._v4_preview_ready:
        e.add_field(
            name="Changements automatiques",
            value="\n".join(f"**{i}.** {item['label']}" for i, item in enumerate(automatic, 1))[:1024]
            if automatic else "Aucun changement automatique nécessaire.",
            inline=False,
        )
        if manual:
            e.add_field(
                name="Décisions manuelles",
                value="\n".join(f"**{i}.** {item['label']}" for i, item in enumerate(manual, 1))[:1024],
                inline=False,
            )
        e.add_field(
            name="Garanties",
            value=(
                "**Aucune suppression automatique.**\n"
                "**Snapshot obligatoire avant application.**\n"
                "Une protection déjà active n'est jamais désactivée par un modèle Smart Setup."
            ),
            inline=False,
        )
    else:
        preview_lines = [f"**{i}.** {item['label']}" for i, item in enumerate(plan[:7], 1)]
        e.add_field(
            name="Analyse proposée",
            value="\n".join(preview_lines)[:1024] if preview_lines else "Aucune modification importante détectée.",
            inline=False,
        )
        e.add_field(
            name="Étape suivante",
            value="Utilise **Prévisualiser** pour figer le plan exact. **Appliquer** reste désactivé jusque-là.",
            inline=False,
        )

    if self._v4_last_result:
        e.add_field(name="Dernière opération", value=self._v4_last_result[:1024], inline=False)
    if self._v4_last_snapshot:
        e.add_field(name="Restauration", value=f"Snapshot **#{self._v4_last_snapshot}** disponible.", inline=False)
    return _decorate(self, e, section="Smart Setup")


async def _summary_embed(self) -> discord.Embed:
    diagnostic = await v4._diagnostic(self)
    e = discord.Embed(
        title="Diagnostic final",
        description="Dernière vérification avant de fermer le setup. Aucun changement n'est appliqué depuis cet écran.",
        colour=v4._score_colour(diagnostic["score"]),
    )
    e.add_field(
        name="Résultat",
        value=(
            f"**{diagnostic['score']}/100 — {_status_label(diagnostic['score'])}**\n"
            f"`{_progress_bar(diagnostic['score'])}`\n"
            f"{diagnostic['passed']}/{diagnostic['total']} tests réussis"
        ),
        inline=False,
    )
    e.add_field(name="Vérifications", value="\n".join(diagnostic["lines"])[:1024], inline=False)
    if self.dirty:
        e.add_field(name="Avant de terminer", value="Des modifications sont encore en attente. Enregistre-les d'abord.", inline=False)
    if self._v4_last_snapshot:
        e.add_field(name="Restauration", value=f"Dernier snapshot : **#{self._v4_last_snapshot}**.", inline=False)
    return _decorate(self, e, section="Diagnostic")


def _render_home(self):
    self.clear_items()
    button = v4._CONFIG_MODULE.SetupNavButton
    self.add_item(button("prev", self.message_id, label="Configuration", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("next", self.message_id, label="Sécurité", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("preview", self.message_id, label="Modules", style=discord.ButtonStyle.secondary, row=0))
    self.add_item(button("restart", self.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    self.add_item(button("summary", self.message_id, label="Diagnostic final", style=discord.ButtonStyle.secondary, row=1))
    tools = discord.ui.Select(
        placeholder="Outils et historique",
        options=[
            discord.SelectOption(label="Relancer le diagnostic", value="diagnostic", description="Vérifier la configuration actuelle"),
            discord.SelectOption(label="Historique", value="history", description="Voir les dernières modifications"),
            discord.SelectOption(label="Actualiser l'analyse", value="refresh", description="Recalculer l'état du serveur"),
            discord.SelectOption(label="Créer un snapshot", value="snapshot", description="Sauvegarder la configuration SentriX"),
        ],
        row=2,
    )
    tools.callback = v4._home_tools_callback(self, tools)
    self.add_item(tools)


def _add_nav(view, *, save: bool = False, summary: bool = True, cancel: bool = True, row: int = 4):
    button = v4._CONFIG_MODULE.SetupNavButton
    view.add_item(button("home", view.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=row))
    if save:
        view.add_item(button("save", view.message_id, label="Enregistrer", style=discord.ButtonStyle.success, row=row))
    if summary:
        view.add_item(button("summary", view.message_id, label="Diagnostic", style=discord.ButtonStyle.primary, row=row))
    if cancel:
        view.add_item(button("cancel", view.message_id, label="Fermer", style=discord.ButtonStyle.secondary, row=row))


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
            "Smart Setup protégé est indisponible : impossible de créer le snapshot obligatoire.",
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
            "Smart Setup annulé : le snapshot de sécurité n'a pas pu être créé. Aucun changement n'a été appliqué.",
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
        + (f" · {len(skipped)} à vérifier" if skipped else " · aucun échec")
    )
    view._v4_preview_ready = False
    view._v4_preview_signature = None
    v4._invalidate_health(view)
    await v4._reload_security(view)
    await view.persist_session()
    view.render_page()
    await view._refresh_message(interaction)

    result = embeds.success(
        f"Smart Setup terminé : **{len(applied)}** changement(s) appliqué(s).\n"
        f"Snapshot de sécurité : **#{snapshot_id}**."
    )
    if skipped:
        result.add_field(name="À vérifier", value="\n".join(f"• {item}" for item in skipped)[:1024], inline=False)
    await interaction.followup.send(embed=result, ephemeral=True)


async def _apply_safe_security_fixes(view, interaction: discord.Interaction):
    health = await v4._health_snapshot(view, force=True)
    fixable = [item for item in health["findings"] if getattr(item, "auto_fixable", False)]
    if not fixable:
        return await interaction.response.send_message("Aucune correction automatique sûre n'est nécessaire.", ephemeral=True)
    ops = getattr(view.bot, "sentrix_ops", None)
    if ops is None:
        return await interaction.response.send_message("Le moteur de corrections sûres n'est pas disponible.", ephemeral=True)

    confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
    await interaction.response.send_message(
        f"Appliquer **{len(fixable)}** correction(s) sûres ? Un snapshot obligatoire sera créé avant.",
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
        return await interaction.followup.send(
            "Corrections annulées : le snapshot de sécurité n'a pas pu être créé.",
            ephemeral=True,
        )

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

    result = embeds.success(f"Corrections appliquées : **{len(done)}**. Snapshot : **#{sid}**.")
    if failed:
        result.add_field(name="Échecs", value="\n".join(f"• {code}" for code in failed)[:1024], inline=False)
    await interaction.followup.send(embed=result, ephemeral=True)


async def _module_hint(view, interaction: discord.Interaction, title: str, command: str, detail: str):
    e = discord.Embed(
        title=title,
        description=detail,
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="Ouvrir le module", value=f"`{command}`", inline=False)
    return await interaction.response.send_message(embed=_decorate(view, e, section="Module dédié"), ephemeral=True)


def install_for_bot(bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    if not getattr(v4, "_INSTALLED", False):
        v4.install_for_bot(bot)
    if not getattr(v4, "_INSTALLED", False):
        logger.warning("V114 non installé : Setup V4 indisponible.")
        return

    v4._decorate_embed = _decorate
    v4._home_embed = _home_embed
    v4._configuration_embed = _configuration_embed
    v4._security_embed = _security_embed
    v4._modules_embed = _modules_embed
    v4._auto_embed = _auto_embed
    v4._summary_embed = _summary_embed
    v4._render_home = _render_home
    v4._add_nav = _add_nav
    v4._apply_auto = _apply_auto
    v4._apply_safe_security_fixes = _apply_safe_security_fixes
    v4._module_hint = _module_hint

    configuration = bot.get_cog("Configuration")
    for active_view in list(getattr(configuration, "active_setups", {}).values()) if configuration else []:
        try:
            active_view.render_page()
        except Exception:
            logger.exception("V114 : rafraîchissement d'une session active impossible.")

    _INSTALLED = True
    v4._V114_INSTALLED = True
    logger.info("SentriX Setup V114 actif : style final, snapshot obligatoire et sécurité sans downgrade.")


__all__ = [
    "_progress_bar",
    "_status_label",
    "_upgrade_only_values",
    "install_for_bot",
]
