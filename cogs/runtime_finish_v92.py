"""V92 — gestion des types de tickets directement depuis +setup > Tickets."""
from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import runtime_finish_v91 as v91
from . import setup_experience_v74 as v74

logger = logging.getLogger("bot.runtime-finish-v92")


def _tickets():
    from . import tickets
    return tickets


async def _refresh_panel(cog, guild: discord.Guild | None, panel_id: int | None) -> None:
    """Met à jour un panel déjà publié après une modification de ses types."""
    if guild is None or not panel_id:
        return
    try:
        panel = await cog.get_panel(int(panel_id))
        if not panel or not panel["channel_id"] or not panel["message_id"]:
            return
        channel = guild.get_channel(int(panel["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        message = await channel.fetch_message(int(panel["message_id"]))
        types = await cog.get_panel_types(int(panel_id))
        view = _tickets().TicketPanelView(panel, types) if types else None
        await message.edit(embed=cog.build_panel_embed(panel), view=view)
    except (discord.NotFound, discord.Forbidden):
        return
    except Exception:
        logger.exception("V92: impossible d'actualiser le panel %s", panel_id)


async def _renumber(cog, panel_id: int | None) -> None:
    if not panel_id:
        return
    rows = await cog.bot.db.fetchall(
        "SELECT id FROM ticket_types WHERE panel_id=? ORDER BY position,id", (int(panel_id),)
    )
    for pos, row in enumerate(rows):
        await cog.bot.db.execute(
            "UPDATE ticket_types SET position=? WHERE id=?", (pos, row["id"])
        )


class DeleteTypeView(discord.ui.View):
    def __init__(self, cog, type_id: int, author_id: int):
        super().__init__(timeout=90)
        self.cog, self.type_id, self.author_id = cog, int(type_id), int(author_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        if not t:
            return await interaction.response.edit_message(
                embed=embeds.warning("Ce type n'existe déjà plus."), view=None
            )
        panel_id, name = t["panel_id"], t["name"]
        await self.cog.bot.db.execute(
            "DELETE FROM ticket_form_questions WHERE ticket_type_id=?", (self.type_id,)
        )
        await self.cog.bot.db.execute("DELETE FROM ticket_types WHERE id=?", (self.type_id,))
        await _renumber(self.cog, panel_id)
        await _refresh_panel(self.cog, interaction.guild, panel_id)
        await interaction.response.edit_message(
            embed=embeds.success(f"Type **{name}** supprimé et panel mis à jour."), view=None
        )
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=embeds.info("Suppression annulée."), view=None)
        self.stop()


class MoveTypeView(discord.ui.View):
    def __init__(self, cog, ticket_type, panels: list, author_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.type_id = int(ticket_type["id"])
        self.old_panel_id = int(ticket_type["panel_id"]) if ticket_type["panel_id"] else None
        self.author_id = int(author_id)
        options = [
            discord.SelectOption(label=str(p["name"])[:100], value=str(p["id"]))
            for p in panels
            if int(p["id"]) != (self.old_panel_id or 0)
        ][:25]
        select = discord.ui.Select(
            placeholder="Choisir le nouveau panel", options=options, min_values=1, max_values=1
        )

        async def chosen(interaction: discord.Interaction):
            target_id = int(select.values[0])
            target = await self.cog.get_panel(target_id)
            t = await self.cog.get_type(self.type_id)
            if not target or not t or int(target["guild_id"]) != interaction.guild.id:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Le type ou le panel n'existe plus.")), ephemere=True)
            count = await self.cog.bot.db.fetchone(
                "SELECT COUNT(*) c FROM ticket_types WHERE panel_id=?", (target_id,)
            )
            if int(count["c"]) >= 25:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Ce panel contient déjà 25 types de tickets.')), ephemere=True)
            await self.cog.bot.db.execute(
                "UPDATE ticket_types SET panel_id=?, position=? WHERE id=?",
                (target_id, int(count["c"]), self.type_id),
            )
            await _renumber(self.cog, self.old_panel_id)
            await _refresh_panel(self.cog, interaction.guild, self.old_panel_id)
            await _refresh_panel(self.cog, interaction.guild, target_id)
            await interaction.response.edit_message(
                embed=embeds.success(
                    f"Type **{t['name']}** déplacé vers **{target['name']}**. Les panels sont à jour."
                ),
                view=None,
            )
            self.stop()

        select.callback = chosen
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


async def _move_flow(cog, type_id: int, author_id: int, interaction: discord.Interaction):
    t = await cog.get_type(type_id)
    if not t:
        return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Type introuvable.')), ephemere=True)
    panneaux = await cog.bot.db.fetchall(
        "SELECT * FROM ticket_panels_v2 WHERE guild_id=? ORDER BY id", (interaction.guild.id,)
    )
    others = [p for p in panneaux if int(p["id"]) != int(t["panel_id"] or 0)]
    if not others:
        return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.info("Il n'y a aucun autre panel vers lequel déplacer ce type.")), ephemere=True)
    await interaction.response.send_message(
        embed=embeds.neutral("Modifier le panel", f"Nouveau panel pour **{t['name']}** :"),
        view=MoveTypeView(cog, t, panneaux, author_id),
        ephemeral=True,
    )


class TypeActionsView(discord.ui.View):
    def __init__(self, cog, type_id: int, author_id: int):
        super().__init__(timeout=180)
        self.cog, self.type_id, self.author_id = cog, int(type_id), int(author_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Modifier", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        if not t:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Type introuvable.')), ephemere=True)
        await interaction.response.send_message(
            embed=embeds.neutral(f"Modifier « {t['name']} »", "Choisissez le réglage à modifier."),
            view=_tickets().TypeEditView(self.cog, self.type_id, self.author_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Modifier le panel", style=discord.ButtonStyle.secondary, emoji="📋")
    async def move(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _move_flow(self.cog, self.type_id, self.author_id, interaction)

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        t = await self.cog.get_type(self.type_id)
        if not t:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Type introuvable.')), ephemere=True)
        await interaction.response.send_message(
            embed=embeds.warning(f"Supprimer **{t['name']}** et son formulaire ?"),
            view=DeleteTypeView(self.cog, self.type_id, self.author_id),
            ephemeral=True,
        )


class TypeManagerView(discord.ui.View):
    def __init__(self, cog, types: list, author_id: int):
        super().__init__(timeout=180)
        self.cog, self.author_id = cog, int(author_id)
        options = [
            discord.SelectOption(
                label=str(t["name"])[:100],
                value=str(t["id"]),
                description=f"Panel #{t['panel_id']}"[:100],
                emoji=_tickets().parse_component_emoji(t["emoji"]),
            )
            for t in types[:25]
        ]
        select = discord.ui.Select(placeholder="Choisir un type de ticket", options=options)

        async def chosen(interaction: discord.Interaction):
            type_id = int(select.values[0])
            t = await self.cog.get_type(type_id)
            if not t:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Type introuvable.')), ephemere=True)
            panel = await self.cog.get_panel(t["panel_id"])
            panel_name = panel["name"] if panel else "introuvable"
            await interaction.response.send_message(
                embed=embeds.neutral(
                    f"🎫 {t['name']}",
                    f"Panel actuel : **{panel_name}**\nChoisissez une action.",
                ),
                view=TypeActionsView(self.cog, type_id, self.author_id),
                ephemeral=True,
            )

        select.callback = chosen
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


class CreateTypeModal(discord.ui.Modal, title="Créer un type de ticket"):
    def __init__(self, cog, panel_id: int, author_id: int):
        super().__init__()
        self.cog, self.panel_id, self.author_id = cog, int(panel_id), int(author_id)
        self.name = discord.ui.TextInput(label="Nom du type", placeholder="Ex : Support", max_length=80)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip()
        if not name:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Nom vide.')), ephemere=True)
        if await self.cog.get_type_by_name(interaction.guild.id, name):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error(f'Un type nommé « {name} » existe déjà.')), ephemere=True)
        panel = await self.cog.get_panel(self.panel_id)
        if not panel:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Panel introuvable.')), ephemere=True)
        count = await self.cog.bot.db.fetchone(
            "SELECT COUNT(*) c FROM ticket_types WHERE panel_id=?", (self.panel_id,)
        )
        if int(count["c"]) >= 25:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Ce panel contient déjà 25 types.')), ephemere=True)
        type_id = await self.cog.add_type(interaction.guild.id, self.panel_id, name)
        await _refresh_panel(self.cog, interaction.guild, self.panel_id)
        await interaction.response.send_message(
            embed=embeds.success(f"Type **{name}** créé dans **{panel['name']}**."),
            view=TypeActionsView(self.cog, type_id, self.author_id),
            ephemeral=True,
        )


class CreateTypePanelView(discord.ui.View):
    def __init__(self, cog, panels: list, author_id: int):
        super().__init__(timeout=120)
        self.cog, self.author_id = cog, int(author_id)
        select = discord.ui.Select(
            placeholder="Choisir le panel",
            options=[discord.SelectOption(label=str(p["name"])[:100], value=str(p["id"])) for p in panels[:25]],
        )

        async def chosen(interaction: discord.Interaction):
            await interaction.response.send_modal(
                CreateTypeModal(self.cog, int(select.values[0]), self.author_id)
            )

        select.callback = chosen
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


async def _create_flow(cog, interaction: discord.Interaction):
    panneaux = await cog.bot.db.fetchall(
        "SELECT * FROM ticket_panels_v2 WHERE guild_id=? ORDER BY id", (interaction.guild.id,)
    )
    if not panneaux:
        return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning("Créez d'abord un panel : un type doit appartenir à un panel.")), ephemere=True)
    if len(panneaux) == 1:
        return await interaction.response.send_modal(
            CreateTypeModal(cog, panneaux[0]["id"], interaction.user.id)
        )
    await interaction.response.send_message(
        embed=embeds.neutral("Créer un type", "Choisissez le panel dans lequel il apparaîtra."),
        view=CreateTypePanelView(cog, panneaux, interaction.user.id),
        ephemeral=True,
    )


async def _manage_flow(cog, interaction: discord.Interaction):
    types = await cog.bot.db.fetchall(
        "SELECT * FROM ticket_types WHERE guild_id=? ORDER BY panel_id,position,id", (interaction.guild.id,)
    )
    if not types:
        return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.info('Aucun type créé.')), ephemere=True)
    await interaction.response.send_message(
        embed=embeds.neutral(
            "Types de tickets",
            "Choisissez un type puis utilisez **Modifier**, **Modifier le panel** ou **Supprimer**.",
        ),
        view=TypeManagerView(cog, types, interaction.user.id),
        ephemeral=True,
    )


def _patch_setup() -> None:
    cls = v74.SentriXSetupV74
    current = cls._build_tickets
    if getattr(current, "_sentrix_v92_types", False):
        return

    async def build_v92(self):
        await current(self)
        cog = self.bot.get_cog("Tickets")
        panels = await self.bot.db.fetchall(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id=? ORDER BY id", (self.guild.id,)
        )
        types = await self.bot.db.fetchall(
            "SELECT * FROM ticket_types WHERE guild_id=? ORDER BY panel_id,position,id", (self.guild.id,)
        )
        names = {int(p["id"]): p["name"] for p in panels}
        lines = ["## 🎫 Types de tickets"]
        if types:
            for t in types[:12]:
                lines.append(f"{t['emoji'] or '🎫'} **{t['name']}** → {names.get(int(t['panel_id'] or 0), 'Panel introuvable')}")
            if len(types) > 12:
                lines.append(f"… et **{len(types)-12}** autre(s).")
        else:
            lines.append("Aucun type créé. Utilisez **Créer un type**.")
        box = discord.ui.Container(accent_colour=v74.v73.ACCENT)
        box.add_item(discord.ui.TextDisplay("\n".join(lines)))
        create = discord.ui.Button(label="Créer un type", style=discord.ButtonStyle.success, emoji="➕", disabled=cog is None)
        manage = discord.ui.Button(label="Gérer les types", style=discord.ButtonStyle.primary, emoji="🎫", disabled=cog is None or not types)

        async def create_cb(interaction: discord.Interaction):
            await _create_flow(cog, interaction)

        async def manage_cb(interaction: discord.Interaction):
            await _manage_flow(cog, interaction)

        create.callback, manage.callback = create_cb, manage_cb
        box.add_item(discord.ui.ActionRow(create, manage))
        self.add_item(box)

    build_v92._sentrix_v92_types = True
    build_v92._sentrix_previous = current
    cls._build_tickets = build_v92


def _patch_type_editor() -> None:
    cls = _tickets().TypeEditView
    current = cls.__init__
    if getattr(current, "_sentrix_v92_actions", False):
        return

    def init_v92(self, cog, type_id: int, author_id: int):
        current(self, cog, type_id, author_id)
        move = discord.ui.Button(label="Modifier le panel", style=discord.ButtonStyle.secondary, emoji="📋", row=1)
        delete = discord.ui.Button(label="Supprimer", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)

        async def move_cb(interaction: discord.Interaction):
            await _move_flow(cog, type_id, author_id, interaction)

        async def delete_cb(interaction: discord.Interaction):
            t = await cog.get_type(type_id)
            if not t:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Type introuvable.')), ephemere=True)
            await interaction.response.send_message(
                embed=embeds.warning(f"Supprimer **{t['name']}** et son formulaire ?"),
                view=DeleteTypeView(cog, type_id, author_id),
                ephemeral=True,
            )

        move.callback, delete.callback = move_cb, delete_cb
        self.add_item(move)
        self.add_item(delete)

    init_v92._sentrix_v92_actions = True
    init_v92._sentrix_previous = current
    cls.__init__ = init_v92


def _patch_type_text_refresh() -> None:
    cls = _tickets().TypeTextModal
    current = cls.on_submit
    if getattr(current, "_sentrix_v92_refresh", False):
        return

    async def submit_v92(self, interaction: discord.Interaction):
        t = await self.cog.get_type(self.type_id)
        panel_id = t["panel_id"] if t else None
        await current(self, interaction)
        await _refresh_panel(self.cog, interaction.guild, panel_id)

    submit_v92._sentrix_v92_refresh = True
    submit_v92._sentrix_previous = current
    cls.on_submit = submit_v92


def _apply() -> None:
    _patch_setup()
    _patch_type_editor()
    _patch_type_text_refresh()


def _post_v83_hook() -> None:
    package = sys.modules.get(__package__)
    current = getattr(package, "run_late_runtime_hooks", None) if package else None
    if not callable(current) or getattr(current, "_sentrix_v92_late_hook", False):
        return

    def wrapped(bot: commands.Bot):
        result = current(bot)
        _apply()
        return result

    wrapped._sentrix_v92_late_hook = True
    wrapped._sentrix_previous = current
    setattr(package, "run_late_runtime_hooks", wrapped)


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v92", False):
        return
    await v91.install(bot)
    _apply()
    _post_v83_hook()
    bot._sentrix_runtime_finish_v92 = True
    logger.info("Runtime Finish V92 actif : gestion complète des types de tickets dans +setup.")


__all__ = ["install"]
