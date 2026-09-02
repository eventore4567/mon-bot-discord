"""V89 — correctif final Logs Setup et preset privé ``+create manox``.

- branche les callbacks sur la CLASSE réellement utilisée par le Setup Components V2 ;
- une sauvegarde de salon de logs réussie ne peut plus devenir une fausse erreur si le
  refresh/audit échoue ensuite ;
- ``+create manox`` devient reprenable/idempotent : une ressource Discord refusée n'arrête
  plus toute l'installation ;
- le preset configure les routes de logs, Tickets, bienvenue, niveaux et les règlements.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_service
from . import runtime_finish_v84 as v84
from . import runtime_finish_v88 as v88
from . import setup_experience_v74 as v74
from . import setup_v2_core as core

logger = logging.getLogger("bot.runtime-finish-v89")

TICKET_OPEN_MESSAGE = (
    "Bienvenue dans votre ticket !\n\n"
    "Merci d'avoir contacté le support. Expliquez clairement votre demande et ajoutez "
    "les informations utiles afin que l'équipe puisse vous aider rapidement.\n\n"
    "Un membre du staff prendra en charge votre ticket dès que possible. "
    "Merci d'éviter les pings inutiles et de patienter jusqu'à une réponse."
)

RULE_MESSAGES: dict[str, tuple[str, str]] = {
    "📜・règlement": (
        "Règlement du serveur",
        "**1. Respect** — Aucun harcèlement, insulte grave ou provocation répétée.\n"
        "**2. Spam et publicité** — Pas de spam, flood ou publicité sans autorisation.\n"
        "**3. Contenu** — Respectez les règles Discord et les salons prévus pour chaque sujet.\n"
        "**4. Arnaques** — Les scams, faux échanges et tentatives de vol sont interdits.\n"
        "**5. Staff** — Respectez les décisions du staff et utilisez le support en cas de contestation.\n\n"
        "Le règlement peut être complété par l'équipe du serveur.",
    ),
    "📏・règlement-staff": (
        "Règlement du staff",
        "**Respect et neutralité** — Restez calme et professionnel avec les membres.\n"
        "**Sanctions** — Vérifiez les preuves et appliquez une sanction proportionnée.\n"
        "**Permissions** — N'utilisez jamais vos permissions pour un avantage personnel.\n"
        "**Traçabilité** — Les actions importantes doivent rester visibles dans les logs.\n"
        "**Doute** — En cas de situation importante ou ambiguë, demandez l'avis d'un responsable.",
    ),
    "📕・règlement-ticket-staff": (
        "Règlement des tickets — Staff",
        "**1.** Prenez en charge le ticket avant de traiter la demande.\n"
        "**2.** Lisez l'historique avant de répondre et évitez les réponses contradictoires.\n"
        "**3.** Ne fermez pas un ticket sans raison claire.\n"
        "**4.** Gardez les preuves et le transcript lorsqu'ils sont utiles.\n"
        "**5.** Pour un échange à risque ou un litige, faites intervenir un responsable.",
    ),
}


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def _iter_components(items):
    for item in items:
        yield item
        children = getattr(item, "children", None)
        if children:
            yield from _iter_components(children)


async def _best_effort_refresh(view, interaction: discord.Interaction) -> bool:
    try:
        await view.refresh(interaction)
        return True
    except Exception:
        logger.exception("Refresh Setup post-sauvegarde impossible guild=%s", view.guild.id)
        return False


def _patch_setup_logs_final() -> None:
    """Patche la classe finale, pas seulement une variable du module V75/V86."""
    cls = v74.SentriXSetupV74
    current = cls._build_page
    if getattr(current, "_sentrix_v89_logs", False):
        return

    async def build_page_v89(self, page: str):
        result = await current(self, page)
        if page != "logs":
            return result

        for item in _iter_components(getattr(self, "children", ())):
            placeholder = str(getattr(item, "placeholder", "") or "")

            if isinstance(item, discord.ui.Select) and placeholder.startswith("1. Choisir la catégorie"):
                category_select = item

                async def choose_category(interaction: discord.Interaction, *, _select=category_select):
                    if not interaction.response.is_done():
                        await interaction.response.defer()
                    if _select.values:
                        self.backend.selected_log = str(_select.values[0])
                    if not await _best_effort_refresh(self, interaction):
                        try:
                            await interaction.followup.send(
                                embed=embeds.success(
                                    "Catégorie sélectionnée. Utilisez **Actualiser** si le panneau ne s'est pas redessiné."
                                ),
                                ephemeral=True,
                            )
                        except discord.HTTPException:
                            pass

                category_select.callback = choose_category
                continue

            if isinstance(item, discord.ui.ChannelSelect) and placeholder.startswith("2. Choisir le salon pour"):
                channel_select = item

                async def choose_channel(interaction: discord.Interaction, *, _select=channel_select):
                    log_type = str(getattr(self.backend, "selected_log", None) or "moderation")
                    if not interaction.response.is_done():
                        await interaction.response.defer()

                    chosen = _select.values[0] if _select.values else None
                    channel_id = int(chosen.id) if chosen is not None else None

                    try:
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
                    except Exception as exc:
                        logger.exception(
                            "Sauvegarde réelle log impossible guild=%s type=%s channel=%s",
                            self.guild.id,
                            log_type,
                            channel_id,
                        )
                        try:
                            await interaction.followup.send(
                                embed=embeds.error(
                                    f"Erreur de sauvegarde réelle : `{type(exc).__name__}: {str(exc)[:160]}`"
                                ),
                                ephemeral=True,
                            )
                        except discord.HTTPException:
                            pass
                        return

                    # Tout ce qui suit est non critique : la route est DÉJÀ sauvegardée.
                    try:
                        await self.backend.audit(
                            interaction.user.id,
                            f"log:{log_type}",
                            channel_id,
                        )
                    except Exception:
                        logger.debug("Audit choix log V89 ignoré", exc_info=True)

                    refreshed = await _best_effort_refresh(self, interaction)
                    if not refreshed:
                        try:
                            text = (
                                f"Salon enregistré : <#{channel_id}>."
                                if channel_id
                                else "Cette catégorie de logs est maintenant désactivée."
                            )
                            await interaction.followup.send(embed=embeds.success(text), ephemeral=True)
                        except discord.HTTPException:
                            pass

                channel_select.callback = choose_channel
                continue

            if isinstance(item, discord.ui.Button):
                label = str(getattr(item, "label", "") or "")
                if label not in {"Activer cette catégorie", "Désactiver cette catégorie"}:
                    continue
                toggle = item

                async def toggle_category(interaction: discord.Interaction):
                    log_type = str(getattr(self.backend, "selected_log", None) or "moderation")
                    if not interaction.response.is_done():
                        await interaction.response.defer()
                    try:
                        setting = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
                        new_enabled = not bool(setting.get("enabled"))
                        if new_enabled and not setting.get("dedicated_channel_id"):
                            await interaction.followup.send(
                                embed=embeds.warning(
                                    "Choisissez d'abord **le salon exact** de cette catégorie avec le deuxième menu."
                                ),
                                ephemeral=True,
                            )
                            return
                        await log_service.set_log_enabled(
                            self.bot,
                            self.guild.id,
                            log_type,
                            new_enabled,
                        )
                    except Exception as exc:
                        logger.exception("Toggle log V89 impossible guild=%s type=%s", self.guild.id, log_type)
                        try:
                            await interaction.followup.send(
                                embed=embeds.error(
                                    f"Impossible de modifier cette catégorie : `{type(exc).__name__}: {str(exc)[:150]}`"
                                ),
                                ephemeral=True,
                            )
                        except discord.HTTPException:
                            pass
                        return

                    try:
                        await self.backend.audit(
                            interaction.user.id,
                            f"log:{log_type}",
                            "enabled" if new_enabled else "disabled",
                        )
                    except Exception:
                        pass
                    if not await _best_effort_refresh(self, interaction):
                        try:
                            await interaction.followup.send(
                                embed=embeds.success(
                                    "Catégorie activée." if new_enabled else "Catégorie désactivée."
                                ),
                                ephemeral=True,
                            )
                        except discord.HTTPException:
                            pass

                toggle.callback = toggle_category

        return result

    build_page_v89._sentrix_v89_logs = True
    build_page_v89._sentrix_previous = current
    cls._build_page = build_page_v89
    logger.info("Setup Logs V89 actif : callbacks finaux branchés sur la classe réelle.")


def _find_any_channel(guild: discord.Guild, name: str):
    return discord.utils.get(guild.channels, name=name)


async def _ensure_structure_resilient(
    guild: discord.Guild,
    author: discord.Member,
) -> tuple[dict[str, Any], dict[str, discord.CategoryChannel], int, int, list[str]]:
    channels: dict[str, Any] = {}
    categories: dict[str, discord.CategoryChannel] = {}
    created_channels = 0
    created_categories = 0
    warnings: list[str] = []

    for kind, name in v84.ROOT_CHANNELS:
        try:
            channel, made = await v84._ensure_channel(
                guild,
                kind=kind,
                name=name,
                category=None,
            )
            channels[name] = channel
            created_channels += int(made)
        except Exception as exc:
            existing = _find_any_channel(guild, name)
            if existing is not None:
                channels[name] = existing
            warnings.append(f"salon {name}")
            logger.warning("Manox V89 : salon racine %s non créé/réparé: %s", name, exc)

    for category_name, private, specs in v84.MANOX_STRUCTURE:
        category = discord.utils.get(guild.categories, name=category_name)
        try:
            ensured, made = await v84._ensure_category(
                guild,
                category_name,
                private=private,
                author=author,
            )
            category = ensured
            created_categories += int(made)
        except Exception as exc:
            # Une permission de catégorie refusée ne doit pas empêcher la reprise si la
            # catégorie existe déjà.
            category = discord.utils.get(guild.categories, name=category_name)
            warnings.append(f"catégorie {category_name}")
            logger.warning("Manox V89 : catégorie %s partiellement réparée: %s", category_name, exc)

        if category is None:
            continue
        categories[category_name] = category

        for kind, name, user_limit in specs:
            try:
                channel, made = await v84._ensure_channel(
                    guild,
                    kind=kind,
                    name=name,
                    category=category,
                    user_limit=user_limit,
                )
                channels[name] = channel
                created_channels += int(made)
            except Exception as exc:
                existing = _find_any_channel(guild, name)
                if existing is not None:
                    channels[name] = existing
                warnings.append(f"salon {name}")
                logger.warning("Manox V89 : salon %s non créé/réparé: %s", name, exc)

    return channels, categories, created_channels, created_categories, warnings


def _route_name_for(log_type: str, meta: dict[str, Any]) -> str:
    if log_type in v84.LOG_ROUTE_NAMES:
        return v84.LOG_ROUTE_NAMES[log_type]
    text = _fold(" ".join((log_type, meta.get("label", ""), meta.get("category", ""))))
    if "fichier" in text or "attachment" in text or "piece" in text:
        return "💾・logs-dossiers"
    if "ticket" in text:
        return "💾・logs-tickets"
    if "message" in text:
        return "💾・logs-messages"
    if "membre" in text or "member" in text:
        return "💾・logs-membre"
    if "salon" in text or "channel" in text:
        return "💾・logs-salons"
    if "role" in text:
        return "💾・logs-rôles"
    if "vocal" in text or "voice" in text:
        return "💾・logs-vocal"
    if "protection" in text or "automod" in text or "spam" in text or "raid" in text:
        return "💾・automod"
    if "moder" in text or "sanction" in text:
        return "💾・logs-modération"
    return "💾・logs-serveur"


async def _configure_logs(
    bot: commands.Bot,
    guild: discord.Guild,
    channels: dict[str, Any],
) -> tuple[int, list[str]]:
    ready = 0
    warnings: list[str] = []
    for log_type, meta in list(log_service.LOG_TYPES.items()):
        target_name = _route_name_for(log_type, meta)
        channel = channels.get(target_name) or _find_any_channel(guild, target_name)
        if not isinstance(channel, discord.TextChannel):
            warnings.append(f"log {log_type}")
            continue
        try:
            await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
            await log_service.set_log_enabled(bot, guild.id, log_type, True)
            ready += 1
        except Exception:
            warnings.append(f"log {log_type}")
            logger.exception("Manox V89 : route log %s impossible", log_type)

    general = channels.get("💾・logs-serveur") or _find_any_channel(guild, "💾・logs-serveur")
    if isinstance(general, discord.TextChannel):
        try:
            await bot.db.set_guild_config(guild.id, "log_channel", general.id)
        except Exception:
            warnings.append("repli logs serveur")
    try:
        await core.set_module_enabled(bot, guild.id, "logs", True)
    except Exception:
        warnings.append("module logs")
    return ready, warnings


async def _ensure_ticket_panel_on_support(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
    channels: dict[str, Any],
    categories: dict[str, discord.CategoryChannel],
) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    support_channel = channels.get("🧰・support") or _find_any_channel(guild, "🧰・support")
    ticket_log = channels.get("💾・logs-tickets") or _find_any_channel(guild, "💾・logs-tickets")
    support_category = categories.get("📞 Support") or discord.utils.get(guild.categories, name="📞 Support")
    if not isinstance(support_channel, discord.TextChannel):
        return False, ["salon support"]
    if not isinstance(ticket_log, discord.TextChannel):
        return False, ["logs tickets"]
    if support_category is None:
        return False, ["catégorie Support"]

    try:
        await bot.db.set_guild_config(guild.id, "ticket_category", support_category.id)
        await bot.db.set_guild_config(guild.id, "ticket_log_channel", ticket_log.id)
    except Exception:
        warnings.append("configuration tickets")

    cog = bot.get_cog("Tickets")
    if cog is None:
        return False, warnings + ["moteur Tickets"]

    try:
        panels = await bot.db.fetchall(
            "SELECT id FROM ticket_panels_v2 WHERE guild_id=? ORDER BY enabled DESC,id LIMIT 1",
            (guild.id,),
        )
        if panels:
            panel_id = int(panels[0]["id"])
        else:
            panel_id = int(await cog.create_panel(guild.id, "Support"))

        # Avant l'autoconfiguration V72 : elle réutilisera donc #support au lieu de créer
        # un salon ouvrir-un-ticket supplémentaire.
        await bot.db.execute(
            "UPDATE ticket_panels_v2 SET channel_id=?,enabled=1,title=?,description=?,footer_text=? WHERE id=?",
            (
                support_channel.id,
                "Support",
                "Besoin d'aide, d'informations ou d'un problème avec une commande ?\nOuvrez un ticket et explique clairement votre demande. Un membre du staff vous répondra dès que possible.",
                "SentriX",
                panel_id,
            ),
        )
    except Exception:
        logger.exception("Manox V89 : préparation du panel Support impossible")
        return False, warnings + ["panel ticket"]

    try:
        from . import setup_ticket_autoconfig_v72 as ticket_v72

        result = await ticket_v72.ensure_ticket_configuration(
            bot,
            guild,
            actor_id=author.id,
        )
        panel_id = int(result["panel_id"])

        # Message d'accueil de tous les types + bouton lisible.
        await bot.db.execute(
            "UPDATE ticket_types SET open_message=?,button_label=COALESCE(NULLIF(button_label,''),'Support'),"
            "description=COALESCE(NULLIF(description,''),'Contacter le support SentriX') "
            "WHERE panel_id=?",
            (TICKET_OPEN_MESSAGE, panel_id),
        )

        # Le log du type doit lui aussi pointer explicitement sur logs-tickets.
        await bot.db.execute(
            "UPDATE ticket_types SET log_channel_id=?,category_id=COALESCE(category_id,?) WHERE panel_id=?",
            (ticket_log.id, support_category.id, panel_id),
        )
        await log_service.set_log_channel(bot, guild.id, "tickets", ticket_log.id)
        await log_service.set_log_enabled(bot, guild.id, "tickets", True)
        await core.set_module_enabled(bot, guild.id, "tickets", True, actor_id=author.id)

        # Republie après personnalisation pour que le bouton/texte visibles soient à jour.
        try:
            await ticket_v72._publish_panel(bot, cog, panel_id, support_channel)
        except Exception:
            logger.exception("Manox V89 : republication panel Support impossible")
            warnings.append("publication panel ticket")
        return True, warnings
    except Exception:
        logger.exception("Manox V89 : autoconfiguration Tickets impossible")
        return False, warnings + ["tickets"]


async def _seed_message(bot: commands.Bot, channel: Any, title: str, description: str) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    try:
        async for message in channel.history(limit=30):
            if bot.user is not None and message.author.id == bot.user.id:
                if any(str(embed.title or "") == title for embed in message.embeds):
                    return True
    except (discord.Forbidden, discord.HTTPException):
        pass

    panel = discord.Embed(
        title=title,
        description=description,
        colour=discord.Colour(0x7C5CFC),
    )
    panel.set_footer(text="SentriX • Configuration manox")
    try:
        await channel.send(embed=panel, allowed_mentions=discord.AllowedMentions.none())
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def _configure_welcome_levels_rules(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
    channels: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    arrivals = channels.get("🛬・arrivées") or _find_any_channel(guild, "🛬・arrivées")
    levels = channels.get("📊・niveaux") or _find_any_channel(guild, "📊・niveaux")

    if isinstance(arrivals, discord.TextChannel):
        try:
            await bot.db.set_guild_config(guild.id, "welcome_channel", arrivals.id)
            await bot.db.set_guild_config(guild.id, "goodbye_channel", arrivals.id)
            await core.set_module_enabled(bot, guild.id, "welcome", True, actor_id=author.id)
        except Exception:
            warnings.append("bienvenue")
    else:
        warnings.append("salon arrivées")

    if isinstance(levels, discord.TextChannel):
        try:
            await bot.db.set_guild_config(guild.id, "level_channel", levels.id)
            await core.set_module_enabled(bot, guild.id, "levels", True, actor_id=author.id)
        except Exception:
            warnings.append("niveaux")

    for channel_name, (title, description) in RULE_MESSAGES.items():
        channel = channels.get(channel_name) or _find_any_channel(guild, channel_name)
        if not await _seed_message(bot, channel, title, description):
            warnings.append(channel_name)

    return warnings


async def _apply_security_best_effort(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
) -> tuple[bool, list[str]]:
    try:
        from .security_runtime_hardening import apply_recommended_security

        result = await apply_recommended_security(bot, guild)
        await core.set_module_enabled(bot, guild.id, "security", True, actor_id=author.id)
        missing = list(result.get("missing_permissions") or [])
        return not missing, (["permissions sécurité : " + ", ".join(missing)] if missing else [])
    except Exception:
        logger.exception("Manox V89 : sécurité recommandée impossible")
        return False, ["sécurité"]


async def _repair_manox(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
) -> dict[str, Any]:
    channels, categories, made_channels, made_categories, warnings = await _ensure_structure_resilient(
        guild,
        author,
    )

    logs_ready, log_warnings = await _configure_logs(bot, guild, channels)
    warnings.extend(log_warnings)

    ticket_ready, ticket_warnings = await _ensure_ticket_panel_on_support(
        bot,
        guild,
        author,
        channels,
        categories,
    )
    warnings.extend(ticket_warnings)

    warnings.extend(
        await _configure_welcome_levels_rules(bot, guild, author, channels)
    )

    security_ready, security_warnings = await _apply_security_best_effort(bot, guild, author)
    warnings.extend(security_warnings)

    # Déduplique les avertissements tout en conservant l'ordre.
    warnings = list(dict.fromkeys(str(item) for item in warnings if item))
    return {
        "categories_created": made_categories,
        "categories_total": len(v84.MANOX_STRUCTURE),
        "channels_created": made_channels,
        "channels_total": len(v84.ROOT_CHANNELS)
        + sum(len(specs) for _name, _private, specs in v84.MANOX_STRUCTURE),
        "logs_ready": logs_ready,
        "ticket_ready": ticket_ready,
        "security_ready": security_ready,
        "warnings": warnings,
    }


def _patch_manox_resilient() -> None:
    current = v84.build_manox_server
    if getattr(current, "_sentrix_v89_resilient", False):
        return

    async def build_manox_v89(bot, guild, author):
        previous_warnings: list[str] = []
        try:
            previous = await current(bot, guild, author)
            previous_warnings.extend(previous.get("warnings") or [])
        except Exception as exc:
            # Le preset historique peut s'arrêter au milieu. V89 reprend alors à partir de
            # ce qui existe déjà, sans supprimer et sans recréer les ressources terminées.
            logger.exception("Preset manox précédent interrompu ; reprise V89 guild=%s", guild.id)
            previous_warnings.append(f"reprise après {type(exc).__name__}")

        repaired = await _repair_manox(bot, guild, author)
        repaired["warnings"] = list(
            dict.fromkeys(previous_warnings + list(repaired.get("warnings") or []))
        )
        return repaired

    build_manox_v89._sentrix_v89_resilient = True
    build_manox_v89._sentrix_previous = current
    v84.build_manox_server = build_manox_v89
    logger.info("Preset +create manox V89 actif : reprise idempotente + configuration complète.")


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v89", False):
        return
    await v88.install(bot)
    _patch_setup_logs_final()
    _patch_manox_resilient()
    bot._sentrix_runtime_finish_v89 = True
    logger.info("Runtime Finish V89 actif : Logs Setup + manox réparés.")


__all__ = ["install"]
