"""SentriX V78 — configurateur complet du règlement, intégré au Setup.

L'administrateur choisit le salon et le rôle Vérifié, écrit lui-même le règlement,
ajoute éventuellement une image, règle le CAPTCHA puis publie directement le vrai panneau
de vérification. Les anciennes commandes verify-setup / verify-panel ne sont plus publiques.
"""
from __future__ import annotations

import asyncio

import logging
import time

import discord
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.verify-setup-v78")

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS dashboard_verification_panels ("
    "guild_id INTEGER PRIMARY KEY, rules_text TEXT NOT NULL DEFAULT '', "
    "image_url TEXT, message_id INTEGER, updated_at INTEGER NOT NULL DEFAULT 0)"
)


def _conf(conf, key: str, default=None):
    if conf is None:
        return default
    try:
        value = conf[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _safe_image(value: str) -> str:
    raw = str(value or "").strip()[:1000]
    if raw and not raw.lower().startswith("https://"):
        raise ValueError("L'image doit utiliser une URL HTTPS publique.")
    return raw


async def _send_access_feedback(followup, message: str, *, kind: str = "info"):
    """Retour court Components V2 avec la bannière très fine de SentriX.

    Pas de texte/mention joint à une LayoutView : le texte vit dans le panneau,
    et son fichier de bannière est transmis dans le même message.
    """
    panel = panels.Panneau(
        titre="Accès au serveur",
        sous_titre=message,
        kind=kind,
        banniere=True,
    )
    return await followup.send(
        view=panel,
        files=panel.fichiers(),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def published_rules_state(bot: commands.Bot, guild: discord.Guild) -> dict | None:
    """La publication est sauvegardée : aucune nouvelle session /setup requise.

    Un rôle/salon défini ou un règlement écrit en brouillon ne constituent PAS
    une publication valide : le panneau doit avoir un message_id enregistré.
    """
    await bot.db.execute(_SCHEMA)
    row = await bot.db.fetchone(
        "SELECT rules_text,message_id FROM dashboard_verification_panels WHERE guild_id=?",
        (guild.id,),
    )
    conf = await bot.db.get_guild_config(guild.id)
    role_id = _conf(conf, "verify_role", _conf(conf, "verification_role"))
    channel_id = _conf(conf, "verification_channel")
    try:
        message_id = int(row["message_id"] or 0) if row else 0
        role_id = int(role_id or 0)
        channel_id = int(channel_id or 0)
    except (TypeError, ValueError):
        return None
    if not (
        row and str(row["rules_text"] or "").strip()
        and message_id and role_id and channel_id
    ):
        return None
    return {
        "channel_id": channel_id,
        "role_id": role_id,
        "message_id": message_id,
    }


async def preview_published_channels(
    bot, guild, *, include_ids=(), exclude_ids=(), release_onboarding=False,
) -> tuple[object, discord.Role, object]:
    """Simule les accès réels après publication, sans toucher à Discord."""
    state = await published_rules_state(bot, guild)
    if state is None:
        raise ValueError("Publiez d'abord le règlement et son panneau public.")
    channel = guild.get_channel(state["channel_id"])
    role = guild.get_role(state["role_id"])
    if not isinstance(channel, discord.TextChannel) or not isinstance(role, discord.Role):
        raise ValueError("Salon du règlement ou rôle Vérifié introuvable.")
    try:
        await channel.fetch_message(state["message_id"])
    except discord.NotFound as exc:
        raise ValueError("Panneau du règlement supprimé : republiez-le.") from exc
    from sentrix_verification_v96 import VerificationConfigV96
    manager = bot.get_cog("VerificationConfigV96") or VerificationConfigV96(bot)
    issues = await manager._preflight(guild, channel=channel, role=role, auto_access=True)
    if issues:
        raise ValueError("Permissions insuffisantes : " + " ".join(issues))
    selection = {}
    if include_ids:
        selection["include_ids"] = tuple(include_ids)
    if exclude_ids:
        selection["exclude_ids"] = tuple(exclude_ids)
    if release_onboarding:
        selection["release_onboarding"] = True
    plan = await manager._access_plan(
        guild, verification_channel=channel, verified_role=role, **selection,
    )
    return plan, role, state


def log_plan_decisions(guild, plan) -> None:
    """Relevé en LECTURE SEULE de chaque décision, pour diagnostic en prod.

    Permet de comparer l'aperçu à la structure réelle du serveur (type,
    catégorie, rôle d'arrivée qui ouvre le salon) sans modifier Discord.
    """
    from utils.verification_access_intelligence import decision_rows

    try:
        rows = decision_rows(guild, plan)
    except Exception:
        # Le diagnostic ne doit jamais empêcher l'aperçu.
        logger.debug("Relevé d'aperçu impossible guild=%s", guild.id, exc_info=True)
        return
    logger.info(
        "Aperçu verrouillage guild=%s : %s à verrouiller, %s à confirmer, %s inchangés, "
        "rôles d'arrivée=%s",
        guild.id, len(plan.gate) + len(getattr(plan, "category_gates", ())),
        len(getattr(plan, "review", ())), len(getattr(plan, "protected", {})),
        [getattr(r, "name", "?") for r in getattr(plan, "entry_roles", ())],
    )
    # Une seule ligne : le limiteur de répétitions masquait les suivantes.
    logger.info("Aperçu verrouillage guild=%s détail | %s", guild.id, " | ".join(rows))


def _lock_preview_card(plan) -> discord.Embed:
    """Carte titrée : un texte brut était transformé en « Action effectuée »
    par la couche globale (le mot « retiré » suffisait), alors que rien n'a
    encore été modifié."""
    from utils import embeds

    return embeds.standard("Vérifier les accès", plan.preview())


async def send_lock_preview(bot, guild, interaction: discord.Interaction) -> None:
    """Aperçu + sélection manuelle + confirmation, depuis n'importe quel bouton.

    L'interaction doit déjà être différée. Aucune permission n'est modifiée
    avant le clic sur « Confirmer le verrouillage ».
    """
    try:
        plan, role, state = await preview_published_channels(bot, guild)
    except ValueError as exc:
        return await interaction.followup.send(str(exc), ephemeral=True)
    except Exception:
        logger.exception("Aperçu du verrouillage impossible guild=%s", guild.id)
        return await interaction.followup.send(
            "Impossible de vérifier les permissions. Aucun salon n'a été modifié.",
            ephemeral=True,
        )
    log_plan_decisions(guild, plan)
    # Correction complète par défaut : si des salons sont bloqués par
    # l'Onboarding Discord, l'aperçu montre directement le plan qui le libère.
    release = bool(getattr(plan, "onboarding", ()))
    if release:
        try:
            plan, role, state = await preview_published_channels(bot, guild, release_onboarding=True)
        except Exception:
            logger.exception("Aperçu avec Onboarding libéré impossible guild=%s", guild.id)
            release = False
    # Un aperçu sans aucun salon, ni verrouillable ni à confirmer, ne doit
    # pas proposer un bouton dangereux qui ne changerait rien.
    if not getattr(plan, "gate", ()) and not getattr(plan, "category_gates", ()) \
            and not getattr(plan, "review", ()) and not getattr(plan, "secure_targets", ()):
        return await _send_access_feedback(
            interaction.followup,
            "Aucun salon membre à verrouiller. Les espaces staff, logs et "
            "vérification restent inchangés.",
        )
    await interaction.followup.send(
        embed=_lock_preview_card(plan),
        view=RulesLockConfirmView(
            bot, guild, interaction.user.id,
            plan_signature(plan, role=role, state=state, guild=guild),
            plan=plan, release_onboarding=release,
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


def plan_signature(plan, *, role=None, state=None, guild=None) -> tuple:
    """Empreinte du plan affiché et des ressources réellement autorisées.

    La liste de salons seule ne suffit pas : si le rôle Vérifié, le panneau
    public ou une permission change entre aperçu et clic, la confirmation
    précédente doit devenir caduque.
    """
    state = state or {}
    everyone = getattr(guild, "default_role", None)
    channel_state = []
    for channel in getattr(guild, "channels", ()) if guild is not None else ():
        perms = channel.permissions_for(everyone) if everyone is not None else None
        overwrites = getattr(channel, "overwrites", {}) or {}
        everyone_rule = overwrites.get(everyone)
        role_rule = overwrites.get(role)
        # Les rôles du serveur ou les overrides staff ont pu changer : la
        # confirmation reste conservatrice et impose un nouvel aperçu.
        role_access = tuple(sorted(
            (int(getattr(target, "id", 0)), str(getattr(value, "view_channel", None)))
            for target, value in overwrites.items()
            if getattr(target, "id", None) is not None
        ))
        channel_state.append((
            int(channel.id),
            str(getattr(channel, "name", "")),
            int(getattr(channel, "category_id", 0) or 0),
            bool(getattr(channel, "permissions_synced", False)),
            getattr(perms, "view_channel", None),
            getattr(everyone_rule, "view_channel", None),
            getattr(role_rule, "view_channel", None),
            role_access,
        ))
    return (
        int(state.get("message_id") or 0),
        int(state.get("channel_id") or 0),
        int(state.get("role_id") or 0),
        int(getattr(role, "id", 0) or 0),
        tuple(sorted(channel_state)),
        tuple(sorted(c.id for c in plan.gate)),
        tuple(sorted(c.id for c in getattr(plan, "category_gates", ()))),
        tuple(sorted(c.id for c in plan.secure_sensitive)),
        tuple(sorted((int(k), str(v)) for k, v in plan.protected.items())),
        tuple(sorted((int(k), str(v)) for k, v in plan.untouched.items())),
        tuple(sorted(c.id for c in plan.log_destinations)),
        tuple(sorted(c.id for c in plan.staff_channels)),
    )


_SELECT_TYPES = [
    discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.forum,
    discord.ChannelType.voice, discord.ChannelType.stage_voice,
]


class RulesLockConfirmView(discord.ui.View):
    def __init__(self, bot, guild, owner_id: int, signature: tuple, *, plan=None, release_onboarding=False):
        super().__init__(timeout=300)
        self.release_onboarding = bool(release_onboarding)
        self.bot, self.guild, self.owner_id = bot, guild, int(owner_id)
        self.signature = signature
        self.running = False
        # Sélection manuelle : ces ID sont revalidés par le planificateur à
        # chaque aperçu ; un salon staff, logs, privé ou portail enregistré
        # est refusé quoi qu'on sélectionne ici.
        self.include_ids: set[int] = set()
        self.exclude_ids: set[int] = set()
        self._add_selection(plan)

    def _add_selection(self, plan) -> None:
        exclude = discord.ui.ChannelSelect(
            placeholder="Retirer des salons du verrouillage",
            channel_types=_SELECT_TYPES, min_values=0, max_values=25, row=0,
        )
        include = discord.ui.ChannelSelect(
            placeholder="Ajouter des salons « à confirmer »",
            channel_types=_SELECT_TYPES, min_values=0, max_values=25, row=1,
        )

        async def on_exclude(interaction: discord.Interaction):
            self.exclude_ids = {int(value.id) for value in exclude.values}
            await self._refresh(interaction)

        async def on_include(interaction: discord.Interaction):
            self.include_ids = {int(value.id) for value in include.values}
            await self._refresh(interaction)

        exclude.callback = on_exclude
        include.callback = on_include
        self.add_item(exclude)
        if plan is None or getattr(plan, "review", None) or self.include_ids:
            self.add_item(include)
        if self.release_onboarding or getattr(plan, "onboarding", None):
            toggle = discord.ui.Button(row=3, style=discord.ButtonStyle.secondary)

            def label() -> None:
                toggle.label = (
                    "Onboarding Discord : libéré puis verrouillé"
                    if self.release_onboarding else "Onboarding Discord : conservé"
                )

            async def on_toggle(interaction: discord.Interaction):
                self.release_onboarding = not self.release_onboarding
                label()
                await self._refresh(interaction)

            label()
            toggle.callback = on_toggle
            self.add_item(toggle)
        self._sync_confirm(plan)

    def _sync_confirm(self, plan) -> None:
        empty = plan is not None and not getattr(plan, "gate", ()) \
            and not getattr(plan, "category_gates", ()) \
            and not getattr(plan, "secure_targets", ())
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label == "Confirmer le verrouillage":
                item.disabled = empty

    async def _refresh(self, interaction: discord.Interaction) -> None:
        """Recalcule l'aperçu avec la sélection ; rien n'est encore écrit."""
        try:
            plan, role, state = await preview_published_channels(
                self.bot, self.guild,
                include_ids=self.include_ids, exclude_ids=self.exclude_ids,
                release_onboarding=self.release_onboarding,
            )
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        self.signature = plan_signature(plan, role=role, state=state, guild=self.guild)
        self._sync_confirm(plan)
        await interaction.response.edit_message(
            content=None, embed=_lock_preview_card(plan), view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (
            interaction.user.id != self.owner_id
            or interaction.guild_id != self.guild.id
            or not (
                interaction.user.id == self.guild.owner_id
                or interaction.user.guild_permissions.administrator
            )
        ):
            await interaction.response.send_message(
                "Confirmation réservée à l'administrateur ayant ouvert cet aperçu.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirmer le verrouillage", style=discord.ButtonStyle.danger, row=2)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if self.running:
            return await interaction.response.send_message(
                "Un verrouillage est déjà en cours.", ephemeral=True,
            )
        self.running = True
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            plan, current_role, current_state = await preview_published_channels(
                self.bot, self.guild,
                include_ids=self.include_ids, exclude_ids=self.exclude_ids,
                release_onboarding=self.release_onboarding,
            )
            if plan_signature(
                plan, role=current_role, state=current_state, guild=self.guild,
            ) != self.signature:
                return await _send_access_feedback(
                    interaction.followup,
                    "La configuration des salons a changé. Relancez l'aperçu avant de confirmer.",
                    kind="warning",
                )
            if not getattr(plan, "gate", ()) and not getattr(plan, "category_gates", ()) \
                    and not getattr(plan, "secure_targets", ()):
                return await _send_access_feedback(
                    interaction.followup,
                    "Aucun salon membre à verrouiller. Rien n'a été modifié.",
                )
            changed, protected = await lock_published_channels(
                self.bot, self.guild, interaction.user,
                include_ids=self.include_ids, exclude_ids=self.exclude_ids,
                release_onboarding=self.release_onboarding,
            )
        except ValueError as exc:
            return await _send_access_feedback(
                interaction.followup, str(exc), kind="warning",
            )
        except Exception:
            logger.exception("Verrouillage après aperçu impossible guild=%s", self.guild.id)
            return await _send_access_feedback(
                interaction.followup,
                "Discord a refusé une modification. Consultez le diagnostic des accès. "
                "Les salons d'accueil Discord restent protégés.",
                kind="warning",
            )
        finally:
            self.running = False
        self.stop()
        for item in self.children:
            item.disabled = True
        await _send_access_feedback(
            interaction.followup,
            f"Accès appliqués : {changed} salons membres verrouillés, "
            f"{protected} espaces protégés ou inchangés."
            + (
                f"\n{len(plan.secure_targets)} salon(s) staff/logs masqués aux arrivants ; "
                "le staff et SentriX gardent l'accès."
                if getattr(plan, "secure_targets", None) else ""
            )
            + (
                "\nOnboarding Discord désactivé (sauvegardé) pour verrouiller ses salons."
                if self.release_onboarding and getattr(plan, "onboarding_released", None) else ""
            ),
            kind="success",
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Verrouillage annulé : aucune permission modifiée.",
            view=self,
        )


async def lock_published_channels(
    bot: commands.Bot, guild: discord.Guild, actor: discord.abc.User,
    *, include_ids=(), exclude_ids=(), release_onboarding=False,
) -> tuple[int, int]:
    """Applique les permissions en relisant l'état publié, sans republier.

    Le moteur V96 existe déjà : il protège salons staff/privés, laisse visible
    le règlement et effectue un rollback si Discord refuse une écriture.
    """
    state = await published_rules_state(bot, guild)
    if state is None:
        raise ValueError(
            "Publiez d'abord votre règlement et son panneau public. "
            "Vous pourrez ensuite verrouiller les salons sans refaire la configuration."
        )
    channel = guild.get_channel(state["channel_id"])
    role = guild.get_role(state["role_id"])
    if not isinstance(channel, discord.TextChannel) or not isinstance(role, discord.Role):
        raise ValueError(
            "Le salon du règlement ou le rôle Vérifié n'existe plus. "
            "Corrigez ces ressources avant le verrouillage."
        )
    try:
        await channel.fetch_message(state["message_id"])
    except discord.NotFound as exc:
        raise ValueError(
            "Le message public du règlement a été supprimé. Republiez le panneau."
        ) from exc

    from sentrix_verification_v96 import VerificationConfigV96

    manager = bot.get_cog("VerificationConfigV96") or VerificationConfigV96(bot)
    issues = await manager._preflight(
        guild, channel=channel, role=role, auto_access=True,
    )
    if issues:
        raise ValueError("Verrouillage impossible : " + " ".join(issues))
    # Vérifier la persistance AVANT de changer les permissions Discord.
    await manager._ensure_table()
    # La sélection n'est transmise que si elle existe : un moteur remplacé
    # avec l'ancienne signature reste utilisable sans sélection manuelle.
    selection = {}
    if include_ids:
        selection["include_ids"] = tuple(include_ids)
    if exclude_ids:
        selection["exclude_ids"] = tuple(exclude_ids)
    if release_onboarding:
        selection["release_onboarding"] = True
    changed, protected = await manager._apply_auto_access(
        guild, verification_channel=channel, verified_role=role, actor=actor,
        **selection,
    )
    await bot.db.set_guild_config(guild.id, "verification_auto_access", 1)
    return changed, protected


def _is_rules_panel(message) -> bool:
    me = getattr(getattr(message, "guild", None), "me", None)
    if me is None or getattr(message.author, "id", None) != me.id:
        return False
    for row in getattr(message, "components", ()) or ():
        for child in getattr(row, "children", ()) or ():
            if getattr(child, "custom_id", None) == "verify_panel_btn":
                return True
    return False


async def remove_stale_rules_panels(channel, *, limit: int = 50) -> int:
    """Supprime les panneaux du règlement SentriX déjà présents dans ce salon."""
    removed = 0
    if not hasattr(channel, "history"):
        return 0
    try:
        async for message in channel.history(limit=limit):
            if _is_rules_panel(message):
                try:
                    await message.delete()
                    removed += 1
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("Historique du salon du règlement illisible", exc_info=True)
    return removed


async def delete_published_rules(bot, guild) -> bool:
    """Retire le panneau public du règlement ; les salons ne sont pas touchés."""
    await bot.db.execute(_SCHEMA)
    row = await bot.db.fetchone(
        "SELECT message_id FROM dashboard_verification_panels WHERE guild_id=?", (guild.id,),
    )
    conf = await bot.db.get_guild_config(guild.id)
    try:
        channel_id = conf["verification_channel"] if conf is not None else None
    except (KeyError, IndexError, TypeError):
        channel_id = None
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    removed = 0
    if isinstance(channel, discord.TextChannel):
        message_id = (dict(row).get("message_id") if row else None)
        if message_id:
            try:
                await (await channel.fetch_message(int(message_id))).delete()
                removed += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        removed += await remove_stale_rules_panels(channel)
    await bot.db.execute(
        "UPDATE dashboard_verification_panels SET message_id=NULL WHERE guild_id=?", (guild.id,),
    )
    return bool(removed)


async def _publish_public_panel(
    bot: commands.Bot,
    guild: discord.Guild,
    channel: discord.TextChannel,
    *,
    rules: str,
    image_url: str,
    previous_channel_id: int | None,
    message_id: int | None,
) -> discord.Message:
    """Publie ou met à jour le vrai panneau public de vérification."""
    from cogs.verification import VerifyView

    previous_channel = guild.get_channel(previous_channel_id) if previous_channel_id else None
    previous_message = None
    if message_id and isinstance(previous_channel, discord.TextChannel):
        try:
            previous_message = await previous_channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            previous_message = None

    verification_cog = bot.get_cog("Verification")
    if verification_cog is not None and hasattr(verification_cog, "_embed"):
        public_embed = await verification_cog._embed(
            guild.id,
            title="Règlement du serveur",
            description=rules,
        )
    else:
        public_embed = discord.Embed(
            title="Règlement du serveur",
            description=rules,
            colour=discord.Colour(0x4DA3FF),
        )
    banner = None
    if image_url:
        public_embed.set_image(url=image_url)
    else:
        # Bannière SentriX en pièce jointe : l'image par URL est effacée par
        # la couche visuelle globale. Si Discord refuse le message avec elle,
        # on republie sans : le panneau ne doit jamais manquer pour une image.
        banner = _rules_banner_file()
        if banner is not None:
            public_embed.set_image(url=f"attachment://{_RULES_BANNER_NAME}")

    def without_banner():
        public_embed.set_image(url=None)

    if previous_message is not None and previous_channel.id == channel.id:
        try:
            await previous_message.edit(
                embed=public_embed, view=VerifyView(),
                attachments=[banner] if banner is not None else [],
            )
        except discord.HTTPException:
            if banner is None:
                raise
            without_banner()
            await previous_message.edit(embed=public_embed, view=VerifyView(), attachments=[])
        return previous_message

    if previous_message is not None:
        try:
            await previous_message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    # Jamais deux règlements dans le même salon : les anciens panneaux SentriX
    # (bouton « J'ai lu les règles ») dont on a perdu la trace sont retirés.
    await remove_stale_rules_panels(channel)
    if banner is not None:
        try:
            return await channel.send(embed=public_embed, view=VerifyView(), file=banner)
        except discord.Forbidden:
            raise
        except discord.HTTPException:
            logger.warning("Panneau du règlement refusé avec bannière guild=%s : republié sans.", guild.id)
            without_banner()
    return await channel.send(embed=public_embed, view=VerifyView())


_RULES_BANNER_NAME = "sentrix-reglement.png"


def _rules_banner_file():
    """La bande neutre ultra-fine des logs pour le panneau du règlement, ou None.

    27/10/2026 (Jayden, capture) : l'ancienne bannière « special » avec l'écusson
    était trop haute ; il veut la même bande quasi invisible que les journaux.
    """
    try:
        from utils.premium_log_banners import get_premium_log_banner

        path = get_premium_log_banner()
        if path.is_file():
            return discord.File(str(path), filename=_RULES_BANNER_NAME)
    except Exception:
        logger.debug("Bannière du règlement indisponible", exc_info=True)
    return None


class RulesModal(discord.ui.Modal):
    def __init__(self, parent: "VerifySetupView"):
        super().__init__(title="Écrire le règlement", timeout=300)
        self.parent_view = parent
        self.rules = discord.ui.TextInput(
            label="Votre règlement",
            style=discord.TextStyle.paragraph,
            placeholder="1. Respectez les membres.\n2. Pas de spam.\n3. ...",
            default=parent.rules_text[:3900],
            required=True,
            min_length=1,
            max_length=3900,
        )
        self.add_item(self.rules)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.rules_text = str(self.rules.value).strip()[:3900]
        await interaction.response.defer(ephemeral=True)
        await self.parent_view.refresh_message()
        await interaction.followup.send("Règlement enregistré dans le configurateur.", ephemeral=True)


class ImageModal(discord.ui.Modal):
    def __init__(self, parent: "VerifySetupView"):
        super().__init__(title="Image du règlement", timeout=300)
        self.parent_view = parent
        self.image = discord.ui.TextInput(
            label="URL HTTPS de l'image (facultatif)",
            placeholder="https://.../reglement.png",
            default=parent.image_url[:1000],
            required=False,
            max_length=1000,
        )
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.parent_view.image_url = _safe_image(str(self.image.value))
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.parent_view.refresh_message()
        await interaction.followup.send(
            "Image mise à jour." if self.parent_view.image_url else "Image retirée du règlement.",
            ephemeral=True,
        )


class VerifySetupView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        owner_id: int,
        *,
        channel_id: int | None,
        role_id: int | None,
        rules_text: str,
        image_url: str,
        captcha_enabled: bool,
        captcha_max_attempts: int,
        message_id: int | None,
    ):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.channel_id = int(channel_id) if channel_id else None
        self.previous_channel_id = self.channel_id
        self.role_id = int(role_id) if role_id else None
        self.rules_text = str(rules_text or "")[:3900]
        self.image_url = str(image_url or "")[:1000]
        self.captcha_enabled = bool(captcha_enabled)
        self.captcha_max_attempts = max(1, min(10, int(captcha_max_attempts or 3)))
        self.message_id = int(message_id) if message_id else None
        self.message: discord.Message | None = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Ce configurateur ne vous appartient pas.", ephemeral=True)
        return False

    def _build_components(self) -> None:
        self.clear_items()

        channel_select = discord.ui.ChannelSelect(
            placeholder="1. Choisir le salon du règlement",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )

        async def choose_channel(interaction: discord.Interaction):
            self.channel_id = int(channel_select.values[0].id)
            await panels.editer(interaction.response, self.panel())

        channel_select.callback = choose_channel
        self.add_item(channel_select)

        role_select = discord.ui.RoleSelect(
            placeholder="2. Choisir le rôle Vérifié",
            min_values=1,
            max_values=1,
            row=1,
        )

        async def choose_role(interaction: discord.Interaction):
            self.role_id = int(role_select.values[0].id)
            await panels.editer(interaction.response, self.panel())

        role_select.callback = choose_role
        self.add_item(role_select)

        rules_button = discord.ui.Button(
            label="Écrire / modifier le règlement",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        image_button = discord.ui.Button(
            label="Configurer l'image",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def edit_rules(interaction: discord.Interaction):
            await interaction.response.send_modal(RulesModal(self))

        async def edit_image(interaction: discord.Interaction):
            await interaction.response.send_modal(ImageModal(self))

        rules_button.callback = edit_rules
        image_button.callback = edit_image
        self.add_item(rules_button)
        self.add_item(image_button)

        captcha_button = discord.ui.Button(
            label=f"CAPTCHA : {'ACTIF' if self.captcha_enabled else 'INACTIF'}",
            style=discord.ButtonStyle.primary if self.captcha_enabled else discord.ButtonStyle.secondary,
            row=3,
        )
        attempts_button = discord.ui.Button(
            label=f"Tentatives : {self.captcha_max_attempts}",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

        async def toggle_captcha(interaction: discord.Interaction):
            self.captcha_enabled = not self.captcha_enabled
            await panels.editer(interaction.response, self.panel())

        async def cycle_attempts(interaction: discord.Interaction):
            choices = (1, 3, 5, 10)
            try:
                self.captcha_max_attempts = choices[(choices.index(self.captcha_max_attempts) + 1) % len(choices)]
            except ValueError:
                self.captcha_max_attempts = 3
            await panels.editer(interaction.response, self.panel())

        captcha_button.callback = toggle_captcha
        attempts_button.callback = cycle_attempts
        self.add_item(captcha_button)
        self.add_item(attempts_button)

        publish_button = discord.ui.Button(
            label="Enregistrer et publier",
            style=discord.ButtonStyle.success,
            row=4,
        )
        close_button = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger, row=4)

        async def publish_callback(interaction: discord.Interaction):
            await self.publish(interaction)

        async def close_callback(interaction: discord.Interaction):
            self.stop()
            await panels.editer(interaction.response, self.panel(closed=True, disabled=True))

        publish_button.callback = publish_callback
        close_button.callback = close_callback
        self.add_item(publish_button)
        self.add_item(close_button)

    def embed(self, *, closed: bool = False) -> discord.Embed:
        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        role = self.guild.get_role(self.role_id) if self.role_id else None
        preview = self.rules_text.strip()
        if len(preview) > 850:
            preview = preview[:847].rstrip() + "…"
        if not preview:
            preview = "*Aucun règlement écrit pour le moment.*"
        embed = discord.Embed(
            title="Règlement & accès",
            description="Choisissez le salon et le rôle, écrivez le règlement, puis publiez-le.",
            colour=discord.Colour(0x4DA3FF),
        )
        embed.add_field(name="Salon", value=channel.mention if channel else "Non configuré", inline=True)
        embed.add_field(name="Rôle Vérifié", value=role.mention if role else "Non configuré", inline=True)
        embed.add_field(
            name="CAPTCHA",
            value=(
                f"ACTIF · {self.captcha_max_attempts} tentative(s) · mode simple"
                if self.captcha_enabled else "INACTIF · mode simple"
            ),
            inline=True,
        )
        embed.add_field(name="Votre règlement", value=preview, inline=False)
        if self.image_url:
            embed.add_field(name="Image", value=self.image_url, inline=False)
        embed.set_footer(
            text="Configurateur fermé — rouvrez « Règlement & accès » dans +setup pour modifier."
            if closed
            else "SentriX • Les changements sont persistés lors de la publication"
        )
        return embed

    def panel(self, *, closed: bool = False, disabled: bool = False):
        # avec_composants déplace les items dans le LayoutView final. On reconstruit donc
        # une vue source fraîche à chaque rendu avant de la convertir.
        self._build_components()
        if disabled:
            for item in self.children:
                item.disabled = True
        base = panels.depuis_embed(self.embed(closed=closed), kind="info", compact=True)
        return panels.avec_composants(base, self)

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        try:
            await panels.editer(self.message, self.panel())
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def publish(self, interaction: discord.Interaction) -> None:
        from cogs.verification import role_grant_problem

        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        role = self.guild.get_role(self.role_id) if self.role_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Choisissez d'abord un salon textuel valide.", ephemeral=True)
        problem = role_grant_problem(self.guild, role)
        if problem:
            return await interaction.response.send_message(f"Rôle de vérification invalide : {problem}", ephemeral=True)
        rules = self.rules_text.strip()
        if not rules:
            return await interaction.response.send_message("Écrivez votre règlement avant de publier.", ephemeral=True)
        try:
            image_url = _safe_image(self.image_url)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)

        me = self.guild.me
        if me is None:
            return await interaction.response.send_message("SentriX n'est pas disponible dans le cache du serveur.", ephemeral=True)
        permissions = channel.permissions_for(me)
        if not permissions.send_messages or not permissions.embed_links:
            return await interaction.response.send_message(
                "SentriX a besoin des permissions **Envoyer des messages** et **Intégrer des liens** dans ce salon.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.db.execute(_SCHEMA)
        try:
            published = await _publish_public_panel(
                self.bot,
                self.guild,
                channel,
                rules=rules,
                image_url=image_url,
                previous_channel_id=self.previous_channel_id,
                message_id=self.message_id,
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "Discord a refusé la publication. Vérifiez les permissions de SentriX dans ce salon.",
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception("V78 : publication du règlement impossible guild=%s", self.guild.id)
            return await interaction.followup.send("Discord a refusé la publication du règlement.", ephemeral=True)

        await self.bot.db.set_guild_config(self.guild.id, "verify_role", role.id)
        await self.bot.db.set_guild_config(self.guild.id, "verification_role", role.id)
        await self.bot.db.set_guild_config(self.guild.id, "verification_channel", channel.id)

        # Le rôle choisi ici est l'unique rôle final. Synchronise aussi la
        # vérification renforcée et nettoie l'ancien rôle final uniquement chez
        # les membres encore "Non vérifié" (donc encore en attente).
        reinforced_row = await self.bot.db.fetchone(
            "SELECT unverified_role_id,verified_role_id FROM honeypot_verification WHERE guild_id=?",
            (self.guild.id,),
        )
        if reinforced_row:
            old_verified_id = int(reinforced_row["verified_role_id"] or 0)
            unverified_id = int(reinforced_row["unverified_role_id"] or 0)
            await self.bot.db.execute(
                "UPDATE honeypot_verification SET verified_role_id=? WHERE guild_id=?",
                (role.id, self.guild.id),
            )
            old_verified = self.guild.get_role(old_verified_id) if old_verified_id else None
            unverified = self.guild.get_role(unverified_id) if unverified_id else None
            if (
                old_verified is not None
                and old_verified.id != role.id
                and unverified is not None
            ):
                for pending_member in list(unverified.members):
                    if old_verified in pending_member.roles:
                        try:
                            await pending_member.remove_roles(
                                old_verified,
                                reason="SentriX : ancien rôle final remplacé dans +setup",
                            )
                        except (discord.Forbidden, discord.HTTPException):
                            logger.warning(
                                "Impossible de retirer l'ancien rôle final user=%s guild=%s.",
                                pending_member.id,
                                self.guild.id,
                            )
        await self.bot.db.set_guild_config(self.guild.id, "verify_captcha_enabled", int(self.captcha_enabled))
        await self.bot.db.set_guild_config(self.guild.id, "verify_captcha_max_attempts", self.captcha_max_attempts)
        await self.bot.db.execute(
            "INSERT INTO dashboard_verification_panels (guild_id,rules_text,image_url,message_id,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET rules_text=excluded.rules_text,image_url=excluded.image_url,message_id=excluded.message_id,updated_at=excluded.updated_at",
            (self.guild.id, rules, image_url or None, published.id, int(time.time())),
        )

        # Si la vérification renforcée est active, le règlement reste obligatoirement
        # visible aux membres "Non vérifié". Changer de salon ne doit jamais créer une
        # porte de contournement : l'ancien salon redevient masqué et le nouveau est en lecture seule.
        honeypot = self.bot.get_cog("HoneypotVerification")
        if honeypot is not None:
            try:
                reinforced = await honeypot.config(self.guild.id)
            except Exception:
                reinforced = None
            if reinforced:
                unverified = self.guild.get_role(int(reinforced["unverified_role_id"] or 0))
                if unverified is not None:
                    if self.previous_channel_id and self.previous_channel_id != channel.id:
                        previous_rules = self.guild.get_channel(int(self.previous_channel_id))
                        protected_ids = {
                            int(reinforced["verify_channel_id"] or 0),
                            int(reinforced["trap_channel_id"] or 0),
                            int(reinforced["category_id"] or 0),
                        }
                        if isinstance(previous_rules, discord.TextChannel) and previous_rules.id not in protected_ids:
                            try:
                                await previous_rules.set_permissions(
                                    unverified,
                                    overwrite=honeypot._unverified_overwrite(),
                                    reason="SentriX : ancien salon de règlement masqué avant vérification",
                                )
                            except (discord.Forbidden, discord.HTTPException):
                                logger.warning("Impossible de reverrouiller l'ancien salon de règlement guild=%s.", self.guild.id)
                    try:
                        await channel.set_permissions(
                            unverified,
                            view_channel=True,
                            read_message_history=True,
                            send_messages=False,
                            add_reactions=False,
                            create_public_threads=False,
                            create_private_threads=False,
                            reason="SentriX : règlement lisible avant vérification",
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        logger.warning("Impossible d'ouvrir le règlement aux non vérifiés guild=%s.", self.guild.id)

        try:
            await self.bot.db.log_setup_history(
                self.guild.id,
                self.owner_id,
                "rules",
                "Règlement",
                None,
                f"salon={channel.id}; rôle={role.id}; captcha={self.captcha_enabled}",
            )
        except Exception:
            logger.warning("Étape non critique ignorée dans publish", exc_info=True)

        self.message_id = int(published.id)
        self.previous_channel_id = int(channel.id)
        await self.refresh_message()
        await interaction.followup.send(
            f"Règlement enregistré et panneau publié dans {channel.mention}. Toute modification future invalidera automatiquement les anciennes acceptations.",
            ephemeral=True,
        )
        # Les salons se configurent seuls derrière le règlement, avec 10 s
        # pour annuler : plus d'aperçu ni de bouton de verrouillage à part.
        await start_auto_configuration(self.bot, self.guild, interaction)

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            await panels.editer(self.message, self.panel(disabled=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


async def build_setup_view(
    bot: commands.Bot,
    guild: discord.Guild,
    owner_id: int,
) -> VerifySetupView:
    """Construit le configurateur Règlement utilisé par le Setup officiel."""
    await bot.db.execute(_SCHEMA)
    conf = await bot.db.get_guild_config(guild.id)
    row = await bot.db.fetchone(
        "SELECT rules_text,image_url,message_id FROM dashboard_verification_panels WHERE guild_id = ?",
        (guild.id,),
    )
    row = dict(row) if row else {}
    return VerifySetupView(
        bot,
        guild,
        owner_id,
        channel_id=_conf(conf, "verification_channel"),
        role_id=_conf(conf, "verify_role", _conf(conf, "verification_role")),
        rules_text=row.get("rules_text") or "",
        image_url=row.get("image_url") or "",
        captcha_enabled=bool(_conf(conf, "verify_captcha_enabled", 1)),
        captcha_max_attempts=int(_conf(conf, "verify_captcha_max_attempts", 3) or 3),
        message_id=row.get("message_id"),
    )


async def open_setup_interaction(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return await interaction.response.send_message(
            "Cette configuration doit être utilisée sur un serveur.", ephemeral=True
        )
    if not (
        interaction.user.id == interaction.guild.owner_id
        or getattr(interaction.user.guild_permissions, "administrator", False)
    ):
        return await interaction.response.send_message(
            "Cette configuration est réservée au propriétaire ou aux administrateurs du serveur.",
            ephemeral=True,
        )
    view = await build_setup_view(
        interaction.client,
        interaction.guild,
        interaction.user.id,
    )
    await interaction.response.send_message(view=view, embed=view.embed(), ephemeral=True)
    try:
        view.message = await interaction.original_response()
    except (discord.NotFound, discord.HTTPException):
        view.message = None


async def _open_setup(ctx: commands.Context) -> None:
    if ctx.guild is None:
        return await ctx.send("Cette commande doit être utilisée sur un serveur.")
    if not (ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator):
        return await ctx.send("Cette configuration est réservée au propriétaire ou aux administrateurs du serveur.")

    view = await build_setup_view(ctx.bot, ctx.guild, ctx.author.id)
    view.message = await panels.envoyer(ctx, view.panel())


def install(bot: commands.Bot) -> bool:
    """Installe uniquement le moteur du configurateur.

    Toute configuration passe désormais par +setup / /setup. Les anciennes commandes
    sont retirées afin d'éviter deux chemins différents pour le même réglage.
    """
    if getattr(bot, "_sentrix_verify_setup_v78", False):
        return True

    for name in ("verify-setup", "verify-panel", "rules-setup", "reglement-setup"):
        try:
            bot.remove_command(name)
        except Exception:
            pass
        try:
            bot.tree.remove_command(name, type=discord.AppCommandType.chat_input)
        except Exception:
            pass

    bot._sentrix_verify_setup_v78 = True
    logger.info("V78 actif : règlement configurable uniquement depuis le Setup officiel.")
    return True


__all__ = ["install", "VerifySetupView", "build_setup_view", "open_setup_interaction", "_safe_image"]


# ---------------------------------------------------------------------------
# Configurer les salons par type (lecture seule, staff, discussion, vocal)
# ---------------------------------------------------------------------------

async def _profile_context(bot, guild) -> dict:
    """Rôle Vérifié, rôles d'arrivée et salons à ne jamais toucher."""
    conf = await bot.db.get_guild_config(guild.id)
    protected: set[int] = set()
    for key in ("verification_channel", "rules_channel", "welcome_channel"):
        value = _conf(conf, key)
        if value:
            protected.add(int(value))
    rules = getattr(guild, "rules_channel", None)
    if rules is not None:
        protected.add(int(rules.id))
    honeypot = None
    try:
        honeypot = await bot.db.fetchone(
            "SELECT category_id, verify_channel_id, trap_channel_id, unverified_role_id "
            "FROM honeypot_verification WHERE guild_id=?", (guild.id,),
        )
    except Exception:
        honeypot = None
    for field_name in ("verify_channel_id", "trap_channel_id"):
        try:
            value = honeypot[field_name] if honeypot else None
        except (KeyError, IndexError, TypeError):
            value = None
        if value:
            protected.add(int(value))
    role_id = _conf(conf, "verify_role", _conf(conf, "verification_role"))
    verified = guild.get_role(int(role_id)) if role_id else None
    entry = []
    try:
        from sentrix_verification_v96 import VerificationConfigV96

        manager = bot.get_cog("VerificationConfigV96") or VerificationConfigV96(bot)
        entry = await manager._entry_roles(guild, verified, honeypot)
    except Exception:
        logger.debug("Rôles d'arrivée illisibles guild=%s", guild.id, exc_info=True)
    return {"verified_role": verified, "entry_roles": entry, "protected_ids": frozenset(protected)}


def _profile_card(plan) -> discord.Embed:
    from utils import embeds

    return embeds.standard("Configurer les salons", plan.preview())


async def send_profile_preview(bot, guild, interaction: discord.Interaction) -> None:
    """Aperçu de la configuration par type ; l'interaction doit être différée."""
    from utils import channel_profiles

    try:
        context = await _profile_context(bot, guild)
        plan = channel_profiles.plan_profiles(guild, **context)
    except Exception:
        logger.exception("Aperçu de configuration des salons impossible guild=%s", guild.id)
        return await interaction.followup.send(
            "Impossible d'analyser les salons. Aucun salon n'a été modifié.", ephemeral=True,
        )
    await interaction.followup.send(
        embed=_profile_card(plan),
        view=ChannelProfileView(bot, guild, interaction.user.id, context, plan),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def apply_profile_plan(guild, plan, actor) -> int:
    """Applique les dérogations prévues ; annule tout si Discord en refuse une."""
    me = getattr(guild, "me", None)
    blocked = [
        channel for channel in {op[0] for op in plan.operations}
        if me is not None and not channel.permissions_for(me).manage_channels
    ]
    if blocked:
        raise ValueError(
            "SentriX ne peut pas gérer ces salons : "
            + ", ".join(f"#{c.name}" for c in blocked[:8])
            + ". Remontez son rôle ou donnez-lui « Gérer les salons »."
        )
    reason = f"SentriX : configuration des salons par type, demandée par {actor} ({actor.id})"
    done = []
    try:
        for channel, target, old, new, had in plan.operations:
            await channel.set_permissions(target, overwrite=new, reason=reason)
            done.append((channel, target, old, had))
    except (discord.Forbidden, discord.HTTPException) as exc:
        for channel, target, old, had in reversed(done):
            try:
                await channel.set_permissions(
                    target, overwrite=old if had else None,
                    reason="SentriX : annulation après refus de Discord",
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Annulation impossible salon=%s", getattr(channel, "id", "?"))
        raise RuntimeError(f"Discord a refusé une permission sur #{getattr(channel, 'name', '?')}") from exc
    return len({channel.id for channel, *_rest in done})


_PROFILE_CHOICES = [
    ("auto", "Type automatique (d'après le nom)"),
    ("lecture", "📢 Lecture seule"),
    ("discussion", "💬 Discussion"),
    ("staff", "🛡️ Staff seulement"),
    ("ignore", "⏭️ Ne pas toucher"),
]


class ChannelProfileView(discord.ui.View):
    def __init__(self, bot, guild, owner_id: int, context: dict, plan):
        super().__init__(timeout=300)
        self.bot, self.guild, self.owner_id = bot, guild, int(owner_id)
        self.context = context
        self.only_ids: set[int] = set()
        self.forced: dict[int, str] = {}
        self.running = False

        channels = discord.ui.ChannelSelect(
            placeholder="Choisir des salons (sinon : tous)",
            channel_types=_SELECT_TYPES, min_values=0, max_values=25, row=0,
        )
        kind = discord.ui.Select(
            placeholder="Type pour les salons choisis",
            options=[discord.SelectOption(label=label, value=value) for value, label in _PROFILE_CHOICES],
            row=1,
        )

        async def on_channels(interaction: discord.Interaction):
            self.only_ids = {int(value.id) for value in channels.values}
            await self._refresh(interaction)

        async def on_kind(interaction: discord.Interaction):
            value = kind.values[0]
            if not self.only_ids:
                return await interaction.response.send_message(
                    "Choisissez d'abord un ou plusieurs salons, puis leur type.", ephemeral=True,
                )
            for channel_id in self.only_ids:
                if value == "auto":
                    self.forced.pop(channel_id, None)
                else:
                    self.forced[channel_id] = value
            await self._refresh(interaction)

        channels.callback = on_channels
        kind.callback = on_kind
        self.add_item(channels)
        self.add_item(kind)
        self._sync_apply(plan)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        allowed = (
            user.id == self.owner_id
            and interaction.guild_id == self.guild.id
            and (user.id == self.guild.owner_id or user.guild_permissions.administrator)
        )
        if not allowed:
            await interaction.response.send_message(
                "Réservé à l'administrateur qui a ouvert cette configuration.", ephemeral=True,
            )
        return allowed

    def _plan(self):
        from utils import channel_profiles

        return channel_profiles.plan_profiles(
            self.guild, **self.context, only_ids=self.only_ids, forced=self.forced,
        )

    def _sync_apply(self, plan) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label == "Appliquer":
                item.disabled = not plan.operations

    async def _refresh(self, interaction: discord.Interaction) -> None:
        plan = self._plan()
        self._sync_apply(plan)
        await interaction.response.edit_message(
            content=None, embed=_profile_card(plan), view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Appliquer", style=discord.ButtonStyle.success, row=2)
    async def apply(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if self.running:
            return await interaction.response.send_message("Configuration déjà en cours.", ephemeral=True)
        self.running = True
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            # Recalcul au clic : les salons ont pu changer depuis l'aperçu.
            plan = self._plan()
            if not plan.operations:
                return await _send_access_feedback(
                    interaction.followup, "Tout est déjà réglé : aucun salon modifié.",
                )
            changed = await apply_profile_plan(self.guild, plan, interaction.user)
        except ValueError as exc:
            return await _send_access_feedback(interaction.followup, str(exc), kind="warning")
        except Exception:
            logger.exception("Configuration des salons impossible guild=%s", self.guild.id)
            return await _send_access_feedback(
                interaction.followup,
                "Discord a refusé une modification : tout a été remis comme avant.",
                kind="warning",
            )
        finally:
            self.running = False
        self.stop()
        logger.info("Salons configurés par type guild=%s : %s salon(s)", self.guild.id, changed)
        await _send_access_feedback(
            interaction.followup, f"{changed} salon(s) configuré(s) selon leur type.", kind="success",
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Configuration annulée : aucun salon modifié.", embed=None, view=None,
        )


# ---------------------------------------------------------------------------
# Configuration automatique à la publication du règlement (10 s pour annuler)
# ---------------------------------------------------------------------------

AUTO_CONFIG_DELAY_SECONDS = 10


async def prepare_auto_configuration(bot, guild) -> dict:
    """Tout le plan, sans rien écrire : verrou, staff, lecture seule, Onboarding."""
    from utils import channel_profiles

    lock, _role, _state = await preview_published_channels(bot, guild)
    release = bool(getattr(lock, "onboarding", ()))
    if release:
        lock, _role, _state = await preview_published_channels(bot, guild, release_onboarding=True)
    context = await _profile_context(bot, guild)
    profiles = channel_profiles.plan_profiles(guild, **context)
    forced = await channel_profiles.ai_reclassify(guild, profiles)
    if forced:
        profiles = channel_profiles.plan_profiles(guild, **context, forced=forced)
    return {"lock": lock, "release": release, "context": context, "forced": forced, "profiles": profiles}


def _auto_configuration_text(guild, prepared: dict, deadline: int) -> str:
    from utils import channel_profiles

    lock, profiles = prepared["lock"], prepared["profiles"]
    members = len(getattr(lock, "gate", ()))
    staff = len(getattr(lock, "secure_targets", ()))
    read_only = len(profiles.channels(channel_profiles.READ_ONLY))
    lines = [f"**SentriX configure vos salons <t:{deadline}:R>.**"]
    lines.append(f"🔒 {members} salon(s) réservés aux membres vérifiés")
    if staff:
        lines.append(f"🛡️ {staff} salon(s) staff/logs invisibles des membres")
    if read_only:
        lines.append(f"📢 {read_only} salon(s) en lecture seule : seuls les administrateurs publient")
    if prepared["release"]:
        lines.append("📌 Onboarding Discord désactivé (sauvegardé) pour verrouiller ses salons")
    if prepared["forced"]:
        reviewed = [
            str(getattr(channel, "name", "?")) for channel in profiles.kinds
            if int(channel.id) in prepared["forced"]
        ]
        lines.append("🤖 L'IA a resserré : " + ", ".join(reviewed[:5]) + (" …" if len(reviewed) > 5 else ""))
    lines.append("\nLes nouveaux membres ne verront que le règlement ; une fois le rôle reçu, "
                 "les salons membres s'ouvrent, jamais ceux du staff.")
    lines.append("-# « Configurer maintenant » pour ne pas attendre, "
                 "« Ne pas configurer les salons » pour garder vos permissions.")
    return "\n".join(lines)


async def run_auto_configuration(bot, guild, actor, prepared: dict) -> str:
    """Applique le verrou puis les types de salons ; chaque étape s'annule seule en cas de refus."""
    from utils import channel_profiles

    changed, protected = await lock_published_channels(
        bot, guild, actor, release_onboarding=prepared["release"],
    )
    # Recalcul après le verrou : les dérogations viennent de changer.
    profiles = channel_profiles.plan_profiles(guild, **prepared["context"], forced=prepared["forced"])
    configured = await apply_profile_plan(guild, profiles, actor) if profiles.operations else 0
    secured = len(getattr(prepared["lock"], "secure_targets", ()))
    lines = [f"🔒 {changed} salon(s) réservés aux membres vérifiés."]
    if secured:
        lines.append(f"🛡️ {secured} salon(s) staff/logs invisibles des membres.")
    if configured:
        lines.append(f"⚙️ {configured} salon(s) réglés selon leur type (lecture seule, discussion, vocal).")
    if prepared["release"]:
        lines.append("📌 Onboarding Discord désactivé (sauvegardé).")
    lines.append(f"-# {protected} espace(s) laissés tels quels : règlement, vérification, salons privés.")
    return "\n".join(lines)


class AutoConfigCountdownView(discord.ui.View):
    def __init__(self, guild, owner_id: int):
        super().__init__(timeout=AUTO_CONFIG_DELAY_SECONDS + 60)
        self.guild, self.owner_id = guild, int(owner_id)
        self.cancelled = False
        # Pressé par « Configurer maintenant » : le compte à rebours s'arrête là.
        self.go_now = asyncio.Event()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        allowed = user.id == self.owner_id or getattr(user.guild_permissions, "administrator", False)
        if not allowed:
            await interaction.response.send_message("Réservé à l'administrateur qui a publié le règlement.", ephemeral=True)
        return allowed

    @discord.ui.button(label="Configurer maintenant", emoji="✅", style=discord.ButtonStyle.success)
    async def now(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.defer()
        self.go_now.set()

    @discord.ui.button(label="Ne pas configurer les salons", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.cancelled = True
        self.go_now.set()
        self.stop()
        from utils import embeds

        await interaction.response.edit_message(
            embed=embeds.standard(
                "Salons laissés tels quels",
                "Le règlement est publié ; aucun salon n'a été modifié.",
            ),
            view=None,
        )


async def start_auto_configuration(bot, guild, interaction: discord.Interaction) -> None:
    """Annonce le plan, laisse 10 s pour annuler, puis applique en arrière-plan."""
    import asyncio

    from utils import embeds

    try:
        prepared = await prepare_auto_configuration(bot, guild)
    except ValueError as exc:
        return await interaction.followup.send(str(exc), ephemeral=True)
    except Exception:
        logger.exception("Préparation de la configuration automatique impossible guild=%s", guild.id)
        return await interaction.followup.send(
            "Impossible d'analyser les salons : aucun salon n'a été modifié.", ephemeral=True,
        )
    lock, profiles = prepared["lock"], prepared["profiles"]
    if not (
        getattr(lock, "gate", ()) or getattr(lock, "category_gates", ())
        or getattr(lock, "secure_targets", ()) or profiles.operations
    ):
        return await interaction.followup.send(
            embed=embeds.standard("Salons déjà configurés", "Tout est en place : rien à modifier."),
            ephemeral=True,
        )
    log_plan_decisions(guild, lock)
    deadline = int(time.time()) + AUTO_CONFIG_DELAY_SECONDS
    view = AutoConfigCountdownView(guild, interaction.user.id)
    message = await interaction.followup.send(
        embed=embeds.standard("Configuration des salons", _auto_configuration_text(guild, prepared, deadline)),
        view=view, ephemeral=True, wait=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    async def countdown() -> None:
        try:
            await asyncio.wait_for(view.go_now.wait(), AUTO_CONFIG_DELAY_SECONDS)
        except asyncio.TimeoutError:
            pass
        if view.cancelled:
            return
        view.stop()
        title = "Salons configurés"
        try:
            text = await run_auto_configuration(bot, guild, interaction.user, prepared)
        except ValueError as exc:
            title, text = "Configuration interrompue", str(exc)
            # 27/10/2026 : deux échecs en production sur le même serveur, raison
            # affichée à l'admin mais absente des journaux — introuvable après coup.
            logger.warning("Configuration automatique refusée guild=%s : %s", guild.id, text)
        except Exception:
            logger.exception("Configuration automatique impossible guild=%s", guild.id)
            title, text = "Configuration interrompue", "Discord a refusé une modification : tout a été remis comme avant."
        logger.info("Configuration automatique guild=%s : %s", guild.id, title)
        try:
            await message.edit(embed=embeds.standard(title, text), view=None)
        except (discord.NotFound, discord.HTTPException):
            pass

    asyncio.create_task(countdown())
