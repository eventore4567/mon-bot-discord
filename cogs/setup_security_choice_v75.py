"""SentriX V75 — protections choisies manuellement, permissions Discord vérifiées.

Cette couche corrige la page Sécurité de V74 :
- l'administrateur choisit exactement les protections anti-* à activer ;
- les permissions Kick/Ban/Timeout/Gérer les messages/etc. ne sont jamais demandées ici ;
- SentriX s'appuie sur les permissions Discord réelles et la hiérarchie au moment de l'action ;
- les permissions propres au bot sont seulement auditées, car Discord interdit à un bot de
  modifier lui-même son rôle d'intégration géré.

Elle possède aussi la page Logs finale. Cette page n'utilise plus les anciens Select du
ancien backend déplacés dans Components V2 : catégorie et salon sont des composants natifs
de la façade finale, ce qui évite les erreurs de parent/rebuild et rend le choix du salon
visible immédiatement.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import log_service, protection_requirements
from utils import sentrix_panels as panels
from . import security_verification_v71 as security_v71
from . import setup_control_center as setup_ui
from . import setup_experience_v74 as v74
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-security-choice-v75")

RUNTIME_MARKER = "Setup Security Choice V75"

EXTRA_PROTECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "honeypot",
        "Salon piège",
        "Piège les comptes suspects qui interagissent avec le salon de sécurité.",
    ),
    (
        "verification",
        "Vérification des nouveaux membres",
        "Ajoute la vérification humaine et le score de confiance SentriX.",
    ),
)

AUTOMOD_DESCRIPTIONS = {
    "antispam": "Bloque les messages envoyés trop rapidement.",
    "antiraid": "Détecte les arrivées massives et active le mode raid.",
    "antilink": "Bloque les liens selon la configuration du serveur.",
    "antiinvite": "Bloque les invitations Discord non autorisées.",
    "antimention": "Bloque les abus de mentions et de pings.",
    "anticaps": "Limite les messages abusivement en majuscules.",
    "antiemoji": "Limite le spam massif d'emojis.",
    "antibot": "Protège contre les ajouts de bots suspects.",
    "antiaccount": "Filtre les comptes Discord trop récents.",
    "antiscam": "Détecte et bloque les contenus typiques de scam.",
    "antinuke": "Protège les rôles, salons et actions serveur sensibles.",
    "security_vanity": "Surveille le lien personnalisé du serveur et tente de restaurer l'ancien code.",
    "security_prune": "Détecte les suppressions massives de membres via le journal d'audit.",
    "security_permissions": "Bloque et restaure les élévations de permissions dangereuses sur rôles et salons.",
    "join_gate": "Contrôle l'âge du compte, l'avatar et la vitesse d'arrivée.",
    "risk_engine": "Regroupe plusieurs alertes récentes pour repérer un comportement dangereux.",
}


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


async def _selected_protections(view: v74.SentriXSetupV74) -> set[str]:
    row = await view.bot.db.fetchone(
        "SELECT * FROM automod_settings WHERE guild_id = ?",
        (view.guild.id,),
    )
    selected = {
        field
        for field, _label in setup_ui.AUTOMOD
        if bool(_row_get(row, field, 0))
    }

    try:
        advanced = await security_v71.settings(view.bot, view.guild.id)
    except Exception:
        logger.debug("Lecture des réglages sécurité V71 impossible", exc_info=True)
        advanced = {}

    # La vérification peut fonctionner sans le salon piège (mode 1).
    # Ne pas cacher son état simplement parce que stay-muted est absent.
    if advanced.get("verification_enabled") and await _honeypot_resources_ready(view):
        selected.add("verification")
    if advanced.get("honeypot_enabled") and await _honeypot_resources_ready(view, require_trap=True):
        selected.add("honeypot")
    return selected


EXTRAS_NOT_INSTALLED = (
    "-# **Salon piège** et **Vérification** demandent d'installer la vérification "
    "(rôle Vérifié choisi dans **Règlement & accès**)."
)


async def _honeypot_resources_ready(
    view: v74.SentriXSetupV74, *, require_trap: bool = False,
) -> bool:
    """Portail seul (mode 1) ou portail + salon piège (mode 2).

    Ce contrôle ne crée rien ; la création du Honeypot se fait toujours dans
    l'assistant explicite « Vérification & Honeypot ».
    """
    honeypot = view.bot.get_cog("HoneypotVerification")
    if honeypot is None:
        return False
    try:
        conf = await honeypot.config(view.guild.id, enabled_only=False)
    except Exception:
        logger.debug("Lecture Honeypot impossible", exc_info=True)
        return False
    if not conf:
        return False

    unverified = view.guild.get_role(int(_row_get(conf, "unverified_role_id", 0) or 0))
    verified = view.guild.get_role(int(_row_get(conf, "verified_role_id", 0) or 0))
    category = view.guild.get_channel(int(_row_get(conf, "category_id", 0) or 0))
    verify_channel = view.guild.get_channel(int(_row_get(conf, "verify_channel_id", 0) or 0))
    trap_channel = view.guild.get_channel(int(_row_get(conf, "trap_channel_id", 0) or 0))

    return bool(
        isinstance(unverified, discord.Role)
        and isinstance(verified, discord.Role)
        and isinstance(category, discord.CategoryChannel)
        and isinstance(verify_channel, discord.TextChannel)
        and (not require_trap or isinstance(trap_channel, discord.TextChannel))
    )


async def _refresh_security_runtime(view: v74.SentriXSetupV74) -> None:
    security_v71._invalidate_automod(view.bot, view.guild.id)
    automod = view.bot.get_cog("Automod")
    if automod is not None:
        cache = getattr(automod, "automod_cache", None)
        if isinstance(cache, dict):
            cache.pop(view.guild.id, None)
    runtime = getattr(view.bot, "_sentrix_security_v71_runtime", None)
    if runtime is not None:
        try:
            await runtime.refresh_gateway_panels(view.guild)
        except Exception:
            logger.debug("Rafraîchissement du runtime sécurité indisponible", exc_info=True)


async def _save_protections(
    view: v74.SentriXSetupV74,
    chosen: set[str],
    *,
    actor_id: int,
) -> str | None:
    automod_fields = {field for field, _label in setup_ui.AUTOMOD}
    chosen_automod = chosen & automod_fields

    await view.bot.db.execute(
        "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (view.guild.id,),
    )
    columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
    values = tuple(1 if field in chosen_automod else 0 for field, _label in setup_ui.AUTOMOD)
    await view.bot.db.execute(
        f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
        (*values, view.guild.id),
    )

    await security_v71.ensure_schema(view.bot)
    notice = None
    if "verification" in chosen and not await _honeypot_resources_ready(view):
        chosen.discard("verification")
        chosen.discard("honeypot")
        notice = (
            "Portail de vérification absent : ouvrez « Vérification & Honeypot » "
            "et activez le mode de votre choix avant d'utiliser ce filtre."
        )
    if "honeypot" in chosen:
        if not await _honeypot_resources_ready(view, require_trap=True):
            chosen.discard("honeypot")
            notice = (
                "Le salon Honeypot n'existe pas. Activez d'abord "
                "« Vérification + Honeypot » dans l'assistant ; rien n'a été créé."
            )
        else:
            # Le Honeypot est toujours un supplément au portail web, pas un
            # troisième mode piège indépendant et incohérent.
            chosen.add("verification")
    honeypot_enabled = int("honeypot" in chosen)
    verification_enabled = int("verification" in chosen)
    await security_v71.update_setting(
        view.bot,
        view.guild.id,
        "honeypot_enabled",
        honeypot_enabled,
        actor_id,
    )
    await security_v71.update_setting(
        view.bot,
        view.guild.id,
        "verification_enabled",
        verification_enabled,
        actor_id,
    )

    await view.bot.db.execute(
        "INSERT INTO honeypot_verification(guild_id,enabled,created_at) "
        "VALUES(?,?,strftime('%s','now')) "
        "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
        (view.guild.id, int(bool(honeypot_enabled or verification_enabled))),
    )

    await core.set_module_enabled(
        view.bot,
        view.guild.id,
        "security",
        bool(chosen),
        actor_id=actor_id,
    )

    # Aucune création de ressource ici. Si Honeypot est déjà configuré avec des
    # ressources existantes, on active simplement son état ; sinon il reste off.
    honeypot = view.bot.get_cog("HoneypotVerification")
    if honeypot is not None and not (chosen & {"honeypot", "verification"}):
        try:
            conf = await honeypot.config(view.guild.id, enabled_only=False)
            if conf and conf["enabled"]:
                await honeypot.disable_system(view.guild)
        except Exception:
            logger.exception("Setup sécurité : désactivation Honeypot impossible guild=%s", view.guild.id)

    # Le même moteur V5 gère aussi le mode choisi et retire les anciens
    # panneaux piège. Une simple mise à jour AutoMod ne doit jamais
    # réactiver stay-muted ou recréer des salons à l'insu de l'admin.
    if honeypot is not None and chosen & {"honeypot", "verification"}:
        try:
            active_trap = "honeypot" in chosen
            await honeypot.ensure_verified_panel_hidden(
                view.guild, honeypot_enabled=active_trap,
            )
            await honeypot.refresh_existing_panels(
                view.guild, honeypot_enabled=active_trap,
            )
        except Exception:
            logger.exception("Impossible de synchroniser les permissions du Honeypot.")
    await _refresh_security_runtime(view)
    return notice


async def _effective_states_v75(self: v74.SentriXSetupV74) -> dict[str, str]:
    previous = getattr(_effective_states_v75, "_sentrix_previous")
    states = await previous(self)
    selected = await _selected_protections(self)
    states["security"] = "● ACTIF" if selected else "○ INACTIF"
    return states


# Inspiré de la lisibilité des familles RaidProtect, mais sans modifier le
# moteur existant ni les sanctions choisies par le serveur. Chaque filtre
# conserve son interrupteur propre et reste OFF sans activation explicite.
AUTOMOD_FAMILLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Messages et mentions", ("antispam", "antimention", "anticaps", "antiemoji", "antiinsult")),
    ("Liens et arnaques", ("antilink", "antiinvite", "antiscam")),
    ("Arrivées et raids", ("antiraid", "antibot", "antiaccount", "join_gate", "risk_engine")),
    ("Intégrité du serveur", ("antinuke", "security_vanity", "security_prune", "security_permissions")),
)


def _resume_familles_automod(
    selected: set[str],
    options: list[tuple[str, str, str]],
) -> str:
    """Synthèse visuelle, uniquement des états réellement enregistrés."""
    available = {key: label for key, label, _description in options}
    lines = ["### AutoMod par famille", "Chaque filtre se règle individuellement. Aucune protection n'est activée automatiquement."]
    for title, keys in AUTOMOD_FAMILLES:
        valid = [key for key in keys if key in available]
        if not valid:
            continue
        enabled = [available[key] for key in valid if key in selected]
        lines.append(
            f"**{title}** · {len(enabled)}/{len(valid)} actifs"
            + (f"\n-# Activés : {', '.join(enabled)}" if enabled else "\n-# Aucun filtre actif")
        )
    others = [key for key in available if not any(key in keys for _title, keys in AUTOMOD_FAMILLES)]
    if others:
        lines.append(
            f"**Autres protections** · {sum(key in selected for key in others)}/{len(others)} actifs"
        )
    lines.append("-# Seuils, rôles exemptés, salons stricts et sanctions : Centre de sécurité.")
    return "\n\n".join(lines)[:3000]


async def _build_security_v75(self: v74.SentriXSetupV74) -> None:
    selected = await _selected_protections(self)
    _ok, missing = v74._bot_permission_audit(self.guild)

    option_specs: list[tuple[str, str, str]] = [
        (
            field,
            label,
            AUTOMOD_DESCRIPTIONS.get(field, f"Protection {label} SentriX."),
        )
        for field, label in setup_ui.AUTOMOD
    ]
    extras_ready = await _honeypot_resources_ready(self)
    if extras_ready:
        option_specs.extend(EXTRA_PROTECTIONS)
    total = len(option_specs)

    status = discord.ui.Button(
        label=f"{len(selected)}/{total} actives",
        style=discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary,
        disabled=True,
    )

    container = discord.ui.Container()
    v74.v73.poser_banniere(container)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 🔒 Sécurité\n"
                "Choisissez les protections à activer."
            ),
            accessory=v74.v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())

    permissions_text = (
        "🟢 SentriX a les permissions nécessaires."
        if not missing
        else (
            "### Permissions requises\n"
            "SentriX vérifie les permissions requises pour chaque action, "
            "mais **son propre rôle Discord** ne possède pas encore : "
            + ", ".join(missing[:12])
            + ".\nDiscord ne permet pas au bot de modifier lui-même son rôle d'intégration géré ; "
            "ces permissions doivent être accordées au rôle SentriX dans les paramètres du serveur."
        )
    )
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(permissions_text),
            accessory=status,
        )
    )

    container.add_item(discord.ui.Separator())

    # Une protection cochée mais incapable d'agir est pire qu'une protection
    # désactivée : elle donne un sentiment de sécurité qui n'existe pas. Le
    # panneau listait les permissions manquantes dans un fourre-tout, sans
    # jamais dire LAQUELLE des protections en mourait.
    libelles = {champ: nom for champ, nom in setup_ui.AUTOMOD}
    inertes, degradees = protection_requirements.diagnostic(
        self.guild.me.guild_permissions if self.guild.me else discord.Permissions.none(),
        selected,
    )
    if inertes or degradees:
        lignes = ["### ⚠️ Protections activées qui ne protègent pas"]
        for champ, manquantes in inertes:
            lignes.append(
                f"🔴 **{libelles.get(champ, champ)}** ne se déclenchera jamais — "
                f"il manque au rôle SentriX : {', '.join(manquantes)}."
            )
        for champ, manquantes in degradees:
            lignes.append(
                f"🟠 **{libelles.get(champ, champ)}** détecte et journalise, mais ne peut pas "
                f"sanctionner — il manque : {', '.join(manquantes)}."
            )
        lignes.append(
            "-# Ces permissions s'accordent au rôle SentriX dans les paramètres du serveur."
        )
        container.add_item(discord.ui.TextDisplay("\n".join(lignes)))
        container.add_item(discord.ui.Separator())

    container.add_item(discord.ui.TextDisplay(
        _resume_familles_automod(selected, option_specs)
    ))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay("### Choisir les protections"))

    protection_select = discord.ui.Select(
        placeholder="Choisir les protections anti à activer",
        min_values=0,
        max_values=total,
        options=[
            discord.SelectOption(
                label=label,
                value=key,
                description=description[:100],
                default=key in selected,
            )
            for key, label, description in option_specs
        ],
    )

    async def save_selection(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        notice = await _save_protections(
            self,
            set(protection_select.values),
            actor_id=interaction.user.id,
        )
        await self.refresh(interaction)
        if notice:
            try:
                await interaction.followup.send(notice, ephemeral=True)
            except discord.HTTPException:
                pass

    protection_select.callback = save_selection
    container.add_item(discord.ui.ActionRow(protection_select))

    if not extras_ready:
        install = discord.ui.Button(
            label="Ouvrir l'installation de la vérification",
            style=discord.ButtonStyle.primary,
        )

        async def install_verification(interaction: discord.Interaction):
            # Cette page ne crée rien : elle ouvre l'installateur existant, où
            # l'administrateur choisit lui-même « Activer » (salons et panneaux).
            from .setup_v118_integrations import VerificationSetupView

            subview = VerificationSetupView(self.bot, self.guild.id, interaction.user.id, panneau=True)
            await panels.envoyer(
                interaction.response,
                panels.avec_composants(panels.depuis_embed(await subview.build_embed()), subview),
                ephemere=True,
            )

        install.callback = install_verification
        container.add_item(discord.ui.TextDisplay(EXTRAS_NOT_INSTALLED))
        container.add_item(discord.ui.ActionRow(install))

    all_on = discord.ui.Button(label="Activer toutes les protections", style=discord.ButtonStyle.success)
    all_off = discord.ui.Button(label="Désactiver toutes les protections", style=discord.ButtonStyle.danger)

    async def enable_all(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _save_protections(
            self,
            {key for key, _label, _description in option_specs},
            actor_id=interaction.user.id,
        )
        await self.refresh(interaction)

    async def disable_all(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _save_protections(self, set(), actor_id=interaction.user.id)
        await self.refresh(interaction)

    all_on.callback = enable_all
    all_off.callback = disable_all
    container.add_item(discord.ui.ActionRow(all_on, all_off))

    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(
            "### Centre de sécurité\n"
            "Seuils, rôles exemptés et salons stricts, protection par protection."
        )
    )
    exceptions = discord.ui.Button(
        label="Ouvrir le centre de sécurité",
        style=discord.ButtonStyle.primary,
    )

    async def open_exceptions(interaction: discord.Interaction):
        from . import setup_v2_ui as v2_ui
        await panels.envoyer(
            interaction.response,
            await v2_ui._security_policy_setup_panel(self, interaction.user.id, "antispam"),
            ephemere=True,
        )

    exceptions.callback = open_exceptions

    diagnostic = discord.ui.Button(
        label="Diagnostic AutoMod", style=discord.ButtonStyle.secondary,
    )

    async def diagnostic_automod(interaction: discord.Interaction):
        # Contrôle strictement en lecture seule : aucune activation, aucun
        # salon créé, aucune sanction et aucun message de membre analysé.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        active = await _selected_protections(self)
        perms = (
            self.guild.me.guild_permissions
            if self.guild.me is not None else discord.Permissions.none()
        )
        blocked, degraded = protection_requirements.diagnostic(perms, active)
        log_route = await log_service.get_log_setting(self.bot, self.guild.id, "automod")
        log_id = log_route.get("channel_id")
        valid, detail = log_service.validate_channel(
            self.guild, log_id, needs_file=True,
        )
        logs_ready = bool(log_route.get("enabled")) and valid
        lines = [
            f"**Protections activées :** {len(active)}",
            f"**Protections sans permissions :** {len(blocked)}",
            f"**Protections dégradées :** {len(degraded)}",
            f"**Journal AutoMod :** {'Prêt' if logs_ready else 'À corriger'}",
        ]
        if blocked:
            lines.append(
                "**Inactives faute de permissions :**\n"
                + "\n".join(
                    f"- {name} : {', '.join(missing)}"
                    for name, missing in blocked[:8]
                )
            )
        if degraded:
            lines.append(
                "**Sanctions impossibles :**\n"
                + "\n".join(
                    f"- {name} : {', '.join(missing)}"
                    for name, missing in degraded[:8]
                )
            )
        if not logs_ready:
            status = "catégorie désactivée" if not log_route.get("enabled") else detail
            lines.append(
                f"**Logs :** {status}. Choisissez un salon dans `/setup` → Logs."
            )
        if not active:
            lines.append("Aucune protection activée : configurez les filtres dans cette page.")
        else:
            lines.append(
                "Ce diagnostic vérifie la configuration ; il ne garantit pas "
                "qu'une sanction a été exécutée."
            )
        report = discord.Embed(
            title="Diagnostic AutoMod",
            description="\n\n".join(lines)[:3900],
            colour=discord.Color.green() if logs_ready and not blocked else discord.Color.orange(),
        )
        await panels.envoyer(
            interaction.followup, panels.depuis_embed(report), ephemere=True,
        )

    diagnostic.callback = diagnostic_automod
    container.add_item(discord.ui.ActionRow(exceptions, diagnostic))

    # Accès direct à CHAQUE règle, inspiré des écrans de réglages par filtre :
    # état réel et configuration explicite. Ce menu ne coche rien et n'active
    # aucune protection à la place de l'administrateur.
    from . import setup_v2_ui as security_ui
    # Le parcours Honeypot/Vérification a son installateur transactionnel
    # dédié. Un simple bouton ON ici pourrait activer le piège sans salon.
    known_filters = {key for key, _label in setup_ui.AUTOMOD}
    policy_options = tuple(
        entry for entry in security_ui.SECURITY_CENTER_PROTECTIONS
        if entry[0] in known_filters
    )
    policy_select = discord.ui.Select(
        placeholder="Configurer un filtre précis (sanction, whitelist, seuils)",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label=label[:100], value=key,
                description=f"{group} · {description}"[:100],
            )
            for key, label, group, description in policy_options
        ],
    )

    async def open_specific_policy(interaction: discord.Interaction):
        chosen = policy_select.values[0]
        await panels.envoyer(
            interaction.response,
            await security_ui._security_policy_setup_panel(
                self, interaction.user.id, chosen,
            ),
            ephemere=True,
        )

    policy_select.callback = open_specific_policy
    container.add_item(discord.ui.ActionRow(policy_select))

    # La liste « Actuellement : … » répétait mot pour mot les choix déjà visibles
    # dans le menu ci-dessus (capture du 28/10/2026) : un compteur suffit.
    container.add_item(discord.ui.TextDisplay(
        f"-# {len(selected)} protection(s) active(s) sur {total}." if selected
        else "-# Aucune protection active."
    ))

    self._add_navigation(container)
    self.add_item(container)


def _log_options() -> list[discord.SelectOption]:
    """Construit les catégories au moment du rendu afin d'inclure les extensions runtime."""
    return [
        discord.SelectOption(
            label=str(meta.get("label") or meta.get("category") or key).strip()[:100],
            value=key,
            description=(
                f"Choisir le salon pour {str(meta.get('label') or key).strip()}"
            )[:100],
        )
        for key, meta in log_service.LOG_TYPES.items()
        if meta.get("emits", True)
    ][:25]


async def _audit_log_choice(
    view: v74.SentriXSetupV74,
    actor_id: int,
    log_type: str,
    value: object,
) -> None:
    try:
        await view.backend.audit(actor_id, f"log:{log_type}", value)
    except Exception:
        logger.debug("Audit du choix de salon de logs indisponible", exc_info=True)


async def _safe_log_refresh(
    view: v74.SentriXSetupV74,
    interaction: discord.Interaction,
) -> None:
    """ACK puis refresh du message Components V2 sans réutiliser la vue legacy."""
    if not interaction.response.is_done():
        await interaction.response.defer()
    await view.refresh(interaction)


async def _build_logs_v75(self: v74.SentriXSetupV74) -> None:
    """Page Logs native Components V2 : catégorie ET salon sont toujours accessibles."""
    self.backend.category = "logs"

    options = _log_options()
    options.sort(key=lambda option: (option.value != "soundboard", option.label.casefold()))
    available = [option.value for option in options]
    if not available:
        container = discord.ui.Container()
        v74.v73.poser_banniere(container)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 📜 Logs du serveur\nAucune catégorie de logs n'est disponible dans ce runtime."
                ),
                accessory=v74.v73._thumbnail(self.bot),
            )
        )
        self._add_navigation(container)
        self.add_item(container)
        return

    selected = getattr(self.backend, "selected_log", None)
    if selected not in available:
        selected = "moderation" if "moderation" in available else available[0]
        self.backend.selected_log = selected

    # Statut complet du routage. Le salon dédié est affiché en priorité ; sinon on montre
    # le fallback général afin que l'administrateur voie immédiatement pourquoi un log est
    # envoyé dans un autre salon.
    route_lines: list[str] = []
    all_settings: dict[str, dict] = {}
    for key in available:
        meta = log_service.LOG_TYPES.get(key, {})
        setting = await log_service.get_log_setting(self.bot, self.guild.id, key)
        all_settings[key] = setting
        enabled = bool(setting.get("enabled"))
        dedicated = setting.get("dedicated_channel_id")
        fallback = setting.get("fallback_channel_id")
        effective = setting.get("channel_id")
        channel_id = dedicated or effective
        channel = self.guild.get_channel(int(channel_id)) if channel_id else None
        if channel is not None:
            destination = channel.mention
            if not dedicated and fallback:
                destination += " *(repli général)*"
        elif channel_id:
            destination = f"`{channel_id}` *(salon introuvable)*"
        else:
            destination = "*aucun salon*"
        label = str(meta.get("label") or meta.get("category") or key)
        # État réel (brief V6, points 7 et 36) : « ACTIF — aucun salon »
        # laissait croire que des logs partaient alors que rien n'était envoyé.
        if not enabled:
            etat = "⚪ Inactif"
        elif channel is None and channel_id:
            etat = "🔴 Erreur"
        elif channel is None:
            etat = "🟠 Non configuré"
        elif not log_service.validate_channel(self.guild, channel.id, needs_file=(key == "tickets"))[0]:
            etat = "🟠 Permissions manquantes"
        else:
            etat = "🟢 Actif"
        route_lines.append(f"**{label}** — {etat} — {destination}")

    selected_meta = log_service.LOG_TYPES.get(selected, {})
    selected_label = str(
        selected_meta.get("label") or selected_meta.get("category") or selected
    )
    selected_setting = all_settings[selected]
    selected_channel_id = (
        selected_setting.get("dedicated_channel_id")
        or selected_setting.get("channel_id")
    )
    selected_channel = (
        self.guild.get_channel(int(selected_channel_id)) if selected_channel_id else None
    )

    if selected_channel is not None:
        valid, detail = log_service.validate_channel(
            self.guild,
            selected_channel.id,
            needs_file=(selected == "tickets"),
        )
        selected_route = selected_channel.mention
        permission_line = "🟢 Tout est prêt." if valid else f"🟠 {detail[:1].upper()}{detail[1:]}."
    else:
        selected_route = "aucun salon choisi"
        permission_line = "⚠️ Choisissez un salon ci-dessous."

    status = discord.ui.Button(
        label="Actif" if bool(selected_setting.get("enabled")) else "Inactif",
        style=(
            discord.ButtonStyle.success
            if bool(selected_setting.get("enabled"))
            else discord.ButtonStyle.secondary
        ),
        disabled=True,
    )

    container = discord.ui.Container()
    v74.v73.poser_banniere(container)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 📜 Logs du serveur\n"
                "Une catégorie, un salon."
            ),
            accessory=v74.v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "### Destinations\n"
                + "\n".join(route_lines)[:3000]
                + "\n\n"
                + permission_line
            ),
            accessory=status,
        )
    )

    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(
            f"### Réglages\n**Catégorie sélectionnée : {selected_label}**\n"
            f"Salon actuel : {selected_route}"
        )
    )

    category_select = discord.ui.Select(
        placeholder="1. Choisir la catégorie de logs",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label=option.label,
                value=option.value,
                description=option.description,
                default=option.value == selected,
            )
            for option in options
        ],
    )

    async def choose_category(interaction: discord.Interaction):
        try:
            self.backend.selected_log = category_select.values[0]
            await _safe_log_refresh(self, interaction)
        except Exception as exc:
            logger.error(
                "Erreur choix catégorie logs Setup guild=%s user=%s",
                self.guild.id,
                interaction.user.id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            if not interaction.response.is_done():
                await panels.envoyer(interaction.response, panels.depuis_embed(discord.Embed(title='Action impossible', description='Impossible de charger cette catégorie de logs. Réessayez après un instant.', colour=discord.Colour.red())), ephemere=True)

    category_select.callback = choose_category
    container.add_item(discord.ui.ActionRow(category_select))

    channel_select = discord.ui.ChannelSelect(
        placeholder=f"2. Choisir le salon pour {selected_label}"[:150],
        min_values=0,
        max_values=1,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
    )

    async def choose_channel(interaction: discord.Interaction):
        log_type = getattr(self.backend, "selected_log", None) or selected
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            channel = channel_select.values[0] if channel_select.values else None
            channel_id = int(channel.id) if channel is not None else None

            await log_service.set_log_channel(
                self.bot,
                self.guild.id,
                log_type,
                channel_id,
            )
            await log_service.set_log_enabled(
                self.bot,
                self.guild.id,
                log_type,
                channel_id is not None,
            )
            if channel_id is not None:
                # Choisir un salon autorisé active immédiatement les journaux.
                await v74.core.set_module_enabled(
                    self.bot, self.guild.id, "logs", True,
                    actor_id=interaction.user.id,
                )
            await _audit_log_choice(
                self,
                interaction.user.id,
                log_type,
                channel_id,
            )
            await self.refresh(interaction)
        except Exception as exc:
            logger.error(
                "Erreur choix salon logs Setup guild=%s type=%s user=%s",
                self.guild.id,
                log_type,
                interaction.user.id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            message = (
                "Impossible d'enregistrer ce salon. Vérifiez que SentriX peut le voir et y envoyer des messages."
            )
            try:
                await panels.envoyer(interaction.followup, panels.depuis_embed(discord.Embed(title='Salon non enregistré', description=message, colour=discord.Colour.red())), ephemere=True)
            except discord.HTTPException:
                pass

    channel_select.callback = choose_channel
    container.add_item(discord.ui.ActionRow(channel_select))

    toggle = discord.ui.Button(
        label=(
            "Désactiver cette catégorie"
            if bool(selected_setting.get("enabled"))
            else "Activer cette catégorie"
        ),
        style=(
            discord.ButtonStyle.danger
            if bool(selected_setting.get("enabled"))
            else discord.ButtonStyle.success
        ),
    )

    async def toggle_category(interaction: discord.Interaction):
        log_type = getattr(self.backend, "selected_log", None) or selected
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            current = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
            new_enabled = not bool(current.get("enabled"))
            if new_enabled and not current.get("channel_id"):
                await panels.envoyer(interaction.followup, panels.depuis_embed(discord.Embed(title="Choisissez d'abord un salon", description='Sélectionnez le salon de cette catégorie avec le deuxième menu, puis activez-la.', colour=discord.Colour.orange())), ephemere=True)
                return
            await log_service.set_log_enabled(
                self.bot,
                self.guild.id,
                log_type,
                new_enabled,
            )
            await _audit_log_choice(
                self,
                interaction.user.id,
                log_type,
                "enabled" if new_enabled else "disabled",
            )
            await self.refresh(interaction)
        except Exception as exc:
            logger.error(
                "Erreur toggle logs Setup guild=%s type=%s user=%s",
                self.guild.id,
                log_type,
                interaction.user.id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            try:
                await panels.envoyer(interaction.followup, panels.depuis_embed(discord.Embed(title='Action impossible', description="Impossible de modifier l'état de cette catégorie de logs.", colour=discord.Colour.red())), ephemere=True)
            except discord.HTTPException:
                pass

    toggle.callback = toggle_category

    test = discord.ui.Button(label="Envoyer un test", style=discord.ButtonStyle.secondary)

    async def send_test(interaction: discord.Interaction):
        """Une vraie carte par le pipeline des logs : arrive-t-elle, sinon pourquoi."""
        log_type = getattr(self.backend, "selected_log", None) or selected
        label = str(log_service.LOG_TYPES.get(log_type, {}).get("label") or log_type)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        setting = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
        channel_id = setting.get("dedicated_channel_id") or setting.get("channel_id")
        if not setting.get("enabled") or not channel_id:
            texte = f"Test impossible : « {label} » n'a pas de salon actif. Choisissez un salon avec le menu 2."
        else:
            valide, detail = log_service.validate_channel(self.guild, int(channel_id), needs_file=(log_type == "tickets"))
            if not valide:
                texte = f"Test impossible dans <#{channel_id}> : {detail}."
            else:
                carte = discord.Embed(
                    title="Test des logs",
                    description=f"Ce salon reçoit bien les logs « {label} ». Test demandé par {interaction.user.mention}.",
                )
                envoye = await log_service.send_log(self.bot, self.guild, log_type, carte)
                texte = (
                    f"Test envoyé dans <#{channel_id}>."
                    if envoye else
                    f"Le test n'est pas parti dans <#{channel_id}> : vérifiez les permissions de SentriX."
                )
        await interaction.followup.send(texte, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    test.callback = send_test
    container.add_item(discord.ui.ActionRow(toggle, test))

    self._add_navigation(container)
    self.add_item(container)


async def _build_page_v75(self: v74.SentriXSetupV74, page: str) -> None:
    """Intercepte uniquement Logs ; toutes les autres pages gardent V74/V75."""
    if page == "logs":
        return await _build_logs_v75(self)
    previous = getattr(_build_page_v75, "_sentrix_previous")
    return await previous(self, page)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_security_choice_v75", False):
        return

    cls = v74.SentriXSetupV74

    current_security = cls._build_security
    if not getattr(current_security, "_sentrix_security_choice_v75", False):
        _build_security_v75._sentrix_security_choice_v75 = True
        _build_security_v75._sentrix_previous = current_security
        cls._build_security = _build_security_v75

    current_states = cls._effective_states
    if not getattr(current_states, "_sentrix_security_choice_v75", False):
        _effective_states_v75._sentrix_security_choice_v75 = True
        _effective_states_v75._sentrix_previous = current_states
        cls._effective_states = _effective_states_v75

    current_page = cls._build_page
    if not getattr(current_page, "_sentrix_native_logs_v75", False):
        _build_page_v75._sentrix_native_logs_v75 = True
        _build_page_v75._sentrix_previous = current_page
        cls._build_page = _build_page_v75

    v74.CATEGORY_META["security"] = (
        "🔒",
        "Sécurité",
        "Choisissez individuellement les protections ; SentriX vérifie les permissions nécessaires.",
    )
    v74.CATEGORY_META["logs"] = (
        "📜",
        "Logs du serveur",
        "Choisissez chaque catégorie et son salon de destination directement dans le panneau.",
    )

    from . import setup_moderation_clear_v76 as moderation_v76
    moderation_v76.install(bot)

    # Le help officiel est déjà chargé à ce stade du finaliseur runtime. V77 remplace
    # son rendu, puis V78 garde le même style tout en respectant la limite Discord de
    # composants sur la page d'accueil.
    from . import help_components_v77 as help_v77
    help_v77.install(bot)
    from . import help_components_v78 as help_v78
    help_v78.install(bot)

    bot._sentrix_setup_security_choice_v75 = True
    logger.info(
        "%s installé : protections anti sélectionnables + page Logs native avec choix de salon.",
        RUNTIME_MARKER,
    )


__all__ = ["install"]
