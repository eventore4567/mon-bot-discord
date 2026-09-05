"""Ajoute une vraie section Invitations au centre +setup.

La section possède sa propre route de logs. Arrivées par invitation, créations et
suppressions d'invitations sont routées vers cette catégorie sans réutiliser le salon
Ressources ni dupliquer la configuration dans la section Logs générale.
"""
from __future__ import annotations

import discord

from utils import embeds, log_categories, log_service
from utils import sentrix_panels as panels
from . import setup_control_center as setup_ui


CATEGORY = "invitations"
LABEL = "Invitations"


class InvitationLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Salon des logs d’invitations",
            min_values=0,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        channel_id = self.values[0].id if self.values else None
        if channel_id is not None:
            ok, reason = log_service.validate_channel(self.owner.guild, channel_id, needs_file=True)
            if not ok:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error(f"Ce salon ne peut pas recevoir les logs : **{reason}**.")),
                    ephemere=True,
                )
        await log_service.set_log_config(
            self.owner.bot,
            self.owner.guild.id,
            CATEGORY,
            channel_id=channel_id,
            enabled=channel_id is not None,
        )
        await self.owner.audit(interaction.user.id, "invitation_log_channel", channel_id)
        await self.owner.refresh(interaction)


def _install_log_category() -> None:
    # La catégorie canonique suffit au transport. On ne l'ajoute volontairement PAS à
    # log_service.LOG_TYPES : sinon elle apparaîtrait aussi dans « Logs », alors que la
    # demande est d'avoir une vraie section Invitations séparée dans +setup.
    log_categories.CATEGORIES[CATEGORY] = LABEL
    if CATEGORY not in log_categories.CATEGORY_ORDER:
        log_categories.CATEGORY_ORDER = tuple(log_categories.CATEGORY_ORDER) + (CATEGORY,)
    log_categories.CATEGORY_META[CATEGORY] = {"label": LABEL, "emits": True}
    log_categories.LEGACY_CATEGORY_KEYS["dossiers"] = CATEGORY
    log_categories.LEGACY_CATEGORY_KEYS["log_dossiers"] = CATEGORY
    for event in ("invite_create", "invite_delete"):
        current = log_categories.LOG_REGISTRY.get(event)
        if current:
            _old_category, emoji, kind = current
            log_categories.LOG_REGISTRY[event] = (CATEGORY, emoji, kind)


def _patch_statuses() -> None:
    current = setup_ui.module_statuses
    if getattr(current, "_sentrix_invites", False):
        return

    async def statuses(bot, guild, conf):
        result = await current(bot, guild, conf)
        setting = await log_service.get_log_setting(bot, guild.id, CATEGORY)
        channel_id = setting.get("channel_id")
        problems = []
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                problems.append("Le salon de logs d’invitations n’existe plus.")
            else:
                ok, reason = log_service.validate_channel(guild, int(channel_id), needs_file=True)
                if not ok:
                    problems.append(f"Le salon de logs d’invitations est invalide : {reason}.")
        if problems:
            state = setup_ui.ConfigState.ERROR
        elif setting.get("enabled") and channel_id:
            state = setup_ui.ConfigState.ACTIVE
        elif channel_id:
            state = setup_ui.ConfigState.INACTIVE
        else:
            state = setup_ui.ConfigState.UNCONFIGURED
        result[CATEGORY] = (
            state,
            "Salon dédié aux arrivées par invitation et aux créations/suppressions d’invitations.",
            tuple(problems),
        )
        return result

    statuses._sentrix_invites = True
    setup_ui.module_statuses = statuses


def _patch_render() -> None:
    current = setup_ui.SetupView.render
    if getattr(current, "_sentrix_invites", False):
        return

    def render(self):
        current(self)
        if self.category != CATEGORY:
            return
        self.ajouter(InvitationLogChannelSelect(self))
        toggle = discord.ui.Button(label="Activer / Désactiver les logs", style=discord.ButtonStyle.primary)
        test = discord.ui.Button(label="Tester", style=discord.ButtonStyle.secondary)

        async def toggle_cb(interaction: discord.Interaction):
            setting = await log_service.get_log_setting(self.bot, self.guild.id, CATEGORY)
            channel_id = setting.get("channel_id")
            if not channel_id:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Choisissez d’abord un salon de logs d’invitations.")),
                    ephemere=True,
                )
            await log_service.set_log_config(
                self.bot,
                self.guild.id,
                CATEGORY,
                channel_id=channel_id,
                enabled=not bool(setting.get("enabled")),
            )
            await self.audit(interaction.user.id, "invitation_logs_enabled", not bool(setting.get("enabled")))
            await self.refresh(interaction)

        async def test_cb(interaction: discord.Interaction):
            setting = await log_service.get_log_setting(self.bot, self.guild.id, CATEGORY)
            channel_id = setting.get("channel_id")
            if not setting.get("enabled") or not channel_id:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Configurez et activez d’abord le salon d’invitations.")),
                    ephemere=True,
                )
            channel = self.guild.get_channel(int(channel_id))
            if channel is None:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Salon introuvable.")), ephemere=True)
            test_embed = embeds.info(
                f"Ce salon recevra les logs d’invitations de **{self.guild.name}**.\n"
                "Les arrivées indiquent l’inviteur et le code détecté lorsque Discord fournit l’information.",
                title="Test — Invitations",
            )
            await channel.send(embed=test_embed, allowed_mentions=discord.AllowedMentions.none())
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success("Log de test envoyé.")), ephemere=True)

        toggle.callback = toggle_cb
        test.callback = test_cb
        self.ajouter(toggle)
        self.ajouter(test)

    render._sentrix_invites = True
    setup_ui.SetupView.render = render


def _patch_embed() -> None:
    current = setup_ui.SetupView.build_embed
    if getattr(current, "_sentrix_invites", False):
        return

    async def build_embed(self):
        panel = await current(self)
        if self.category != CATEGORY:
            return panel
        setting = await log_service.get_log_setting(self.bot, self.guild.id, CATEGORY)
        channel_id = setting.get("channel_id")
        channel = self.guild.get_channel(int(channel_id)) if channel_id else None
        panel.add_field(name="Salon des invitations", value=(channel.mention if channel else "Non configuré"), inline=False)
        panel.add_field(name="État", value="ACTIF" if setting.get("enabled") and channel_id else "INACTIF", inline=True)
        panel.add_field(
            name="Événements",
            value="Arrivée via invitation • invitation créée • invitation supprimée",
            inline=False,
        )
        return panel

    build_embed._sentrix_invites = True
    setup_ui.SetupView.build_embed = build_embed


def install(_bot) -> None:
    if getattr(setup_ui, "_sentrix_invitation_section", False):
        return
    _install_log_category()
    setup_ui.CATEGORIES[CATEGORY] = (
        LABEL,
        "Salon dédié aux logs d’invitations, inviteur détecté et changements de codes.",
    )
    order = list(setup_ui.CATEGORY_ORDER)
    if CATEGORY not in order:
        insert_at = order.index("logs") + 1 if "logs" in order else len(order)
        order.insert(insert_at, CATEGORY)
    setup_ui.CATEGORY_ORDER = tuple(order)
    setup_ui.BOT_PERMS[CATEGORY] = (
        "view_channel", "send_messages", "embed_links", "attach_files", "read_message_history"
    )
    _patch_statuses()
    _patch_render()
    _patch_embed()
    setup_ui._sentrix_invitation_section = True
