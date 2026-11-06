"""Gestion des panneaux de réactions depuis /setup, sans nouvelle commande."""

from __future__ import annotations

import re

import discord

from cogs.economy_setup import AdminView, button
from utils import config_journal
from utils import sentrix_emojis as icons
from utils.component_context import ComponentContext
from utils.reaction_role_options import options, save_options

PURPLE = 0x9B59B6


class RolePanelHubView(AdminView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        box = discord.ui.Container(accent_colour=PURPLE)
        box.add_item(
            discord.ui.TextDisplay(
                "## Panneaux de rôles\nChoisissez comment les membres prennent leurs rôles."
            )
        )

        async def dropdown(i):
            from sentrix_regression_runtime import RolePanelBuilder

            builder = RolePanelBuilder(
                bot, guild, owner_id, mode="dropdown", allow_mode_switch=False
            )
            await i.response.send_message(view=builder, ephemeral=True)
            builder.message = await i.original_response()

        async def reactions(i):
            await i.response.send_message(
                view=await ReactionRoleSetupView(bot, guild, owner_id).build(),
                ephemeral=True,
            )

        box.add_item(
            discord.ui.ActionRow(
                button("Menu déroulant", dropdown), button("Réactions emoji", reactions)
            )
        )
        self.add_item(box)


class PanelTextModal(discord.ui.Modal, title="Créer un panneau de rôles"):
    title_input = discord.ui.TextInput(
        label="Titre", default="Choisissez vos rôles", max_length=150
    )
    text = discord.ui.TextInput(
        label="Texte",
        default="Cliquez sur les réactions pour prendre vos rôles.",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        channel = self.owner.guild.get_channel(self.owner.channel_id)
        if channel is None:
            return await i.response.send_message("Choisissez un salon.", ephemeral=True)
        if not await self.owner.check_permissions(i, channel):
            return
        await i.response.defer(ephemeral=True, thinking=True)
        card = discord.ui.LayoutView(timeout=None)
        box = discord.ui.Container(accent_colour=PURPLE)
        box.add_item(
            discord.ui.TextDisplay(
                "## " + self.title_input.value + "\n" + self.text.value
            )
        )
        card.add_item(box)
        message = await channel.send(
            view=card, allowed_mentions=discord.AllowedMentions.none()
        )
        cog = self.owner.cog()
        await cog._register_panel_if_needed(
            ComponentContext(self.owner.bot, i), message
        )
        await self.owner.bot.db.execute(
            "UPDATE reaction_role_panels SET title=?,description=? WHERE guild_id=? AND message_id=?",
            (self.title_input.value, self.text.value, self.owner.guild.id, message.id),
        )
        await config_journal.record(
            self.owner.bot.db,
            self.owner.guild.id,
            "reaction_panel.created",
            None,
            message.id,
        )
        self.owner.message_id = message.id
        await self.owner.build()
        await i.followup.send(view=self.owner, ephemeral=True)


class ExistingMessageModal(discord.ui.Modal, title="Utiliser un message existant"):
    link = discord.ui.TextInput(label="Lien ou ID du message", max_length=220)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        raw = self.link.value.strip()
        match = re.fullmatch(
            r"https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)",
            raw,
        )
        if match:
            gid, cid, mid = map(int, match.groups())
            if gid != self.owner.guild.id:
                return await i.response.send_message(
                    "Le message doit appartenir à ce serveur.", ephemeral=True
                )
        elif raw.isdigit() and self.owner.channel_id:
            cid, mid = self.owner.channel_id, int(raw)
        else:
            return await i.response.send_message(
                "Collez un lien Discord, ou choisissez le salon avant de saisir un ID.",
                ephemeral=True,
            )
        channel = self.owner.guild.get_channel(cid)
        if channel is None or not await self.owner.check_permissions(i, channel):
            return
        try:
            message = await channel.fetch_message(mid)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await i.response.send_message(
                "Message introuvable ou inaccessible.", ephemeral=True
            )
        await self.owner.cog()._register_panel_if_needed(
            ComponentContext(self.owner.bot, i), message
        )
        self.owner.message_id = mid
        await self.owner.build()
        await i.response.edit_message(view=self.owner)


class EmojiModal(discord.ui.Modal, title="Ajouter une réaction"):
    emoji = discord.ui.TextInput(label="Emoji standard ou <:nom:id>", max_length=100)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        from cogs.verification import _emoji_parts

        try:
            _emoji_parts(self.emoji.value)
        except ValueError:
            return await i.response.send_message("Emoji invalide.", ephemeral=True)
        view = AddReactionRoleView(self.owner, self.emoji.value)
        await i.response.send_message(view=view, ephemeral=True)


class AddReactionRoleView(AdminView):
    def __init__(self, owner, emoji):
        super().__init__(owner.bot, owner.guild, owner.owner_id)
        box = discord.ui.Container(accent_colour=PURPLE)
        box.add_item(discord.ui.TextDisplay("### Rôle lié à " + emoji))
        select = discord.ui.RoleSelect(placeholder="Choisissez le rôle à distribuer")

        async def choose(i):
            from cogs.economy import _self_assignable_role_error

            role = self.guild.get_role(select.values[0].id)
            error = (
                _self_assignable_role_error(self.guild, role)
                if role
                else "Rôle supprimé."
            )
            if error:
                return await i.response.send_message(error, ephemeral=True)
            _panel, message = await owner.cog()._panel_and_message(
                self.guild, owner.message_id
            )
            if message is None:
                return await i.response.send_message(
                    "Message introuvable.", ephemeral=True
                )
            if not await owner.check_permissions(i, message.channel):
                return
            await i.response.defer(ephemeral=True, thinking=True)
            await owner.cog()._add_reaction_role(
                ComponentContext(self.bot, i), message, emoji, role
            )
            await config_journal.record(
                self.bot.db,
                self.guild.id,
                f"reaction_panel.{message.id}.role",
                None,
                role.id,
            )

        select.callback = choose
        box.add_item(discord.ui.ActionRow(select))
        self.add_item(box)


class DeletePanelView(AdminView):
    def __init__(self, owner):
        super().__init__(owner.bot, owner.guild, owner.owner_id)
        self.done = False
        self.message_id = owner.message_id
        box = discord.ui.Container(accent_colour=PURPLE)
        box.add_item(
            discord.ui.TextDisplay(
                "## Supprimer ce panneau ?\nLes associations seront supprimées. Vous pouvez conserver ou supprimer le message."
            )
        )

        async def remove(i, delete_message):
            if self.done:
                return await i.response.send_message("Déjà supprimé.", ephemeral=True)
            _panel, message = await owner.cog()._panel_and_message(
                self.guild, self.message_id
            )
            if delete_message and message:
                if (
                    message.author.id != self.bot.user.id
                    and not message.channel.permissions_for(
                        self.guild.me
                    ).manage_messages
                ):
                    return await i.response.send_message(
                        "Permission Gérer les messages nécessaire.", ephemeral=True
                    )
                await message.delete()
            self.done = True
            for table in (
                "reaction_roles",
                "reaction_role_panels",
                "sentrix_reaction_role_options",
            ):
                await self.bot.db.execute(
                    f"DELETE FROM {table} WHERE guild_id=? AND message_id=?",
                    (self.guild.id, self.message_id),
                )
            await config_journal.record(
                self.bot.db,
                self.guild.id,
                "reaction_panel.deleted",
                self.message_id,
                None,
            )
            import sqlite3

            for table in ("sentrix_role_panels", "sentrix_reaction_role_panels"):
                try:
                    await self.bot.db.execute(
                        f"DELETE FROM {table} WHERE guild_id=? AND message_id=?",
                        (self.guild.id, self.message_id),
                    )
                except sqlite3.OperationalError:
                    pass
            owner.message_id = None
            await owner.build()
            await i.response.edit_message(view=owner)
            self.stop()

        async def keep(i):
            await remove(i, False)

        async def both(i):
            await remove(i, True)

        async def cancel(i):
            await owner.build()
            await i.response.edit_message(view=owner)

        box.add_item(
            discord.ui.ActionRow(
                button("Supprimer les associations", keep, danger=True),
                button("Supprimer aussi le message", both, danger=True),
                button("Annuler", cancel),
            )
        )
        self.add_item(box)


class ReactionRoleSetupView(AdminView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        self.channel_id = None
        self.message_id = None
        self.page = 0

    def cog(self):
        return self.bot.get_cog("Verification")

    async def check_permissions(self, i, channel):
        me = self.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await self.refuse(i, "SentriX a besoin de Gérer les rôles.")
        p = channel.permissions_for(me)
        if not (p.view_channel and p.add_reactions and p.read_message_history):
            return await self.refuse(
                i,
                "SentriX doit voir le salon, lire l'historique et Ajouter des réactions.",
            )
        if not (p.send_messages and p.embed_links):
            return await self.refuse(
                i, "SentriX doit pouvoir envoyer des messages et intégrer des liens."
            )
        return True

    async def refuse(self, i, text):
        await i.response.send_message(text, ephemeral=True)
        return False

    async def build(self):
        self.clear_items()
        box = discord.ui.Container(accent_colour=PURPLE)
        me = self.guild.me
        warning = (
            ""
            if me and me.guild_permissions.manage_roles
            else "\n**Permission manquante : Gérer les rôles.**"
        )
        if me and not me.guild_permissions.add_reactions:
            warning += "\n**Permission manquante : Ajouter des réactions.**"
        from utils.reaction_role_options import import_legacy_panels

        await import_legacy_panels(self.bot, self.guild.id)
        panels = await self.bot.db.fetchall(
            "SELECT * FROM reaction_role_panels WHERE guild_id=? ORDER BY message_id DESC",
            (self.guild.id,),
        )
        lines = []
        for panel in panels:
            row = await self.bot.db.fetchone(
                "SELECT COUNT(*) AS total FROM reaction_roles WHERE guild_id=? AND message_id=?",
                (self.guild.id, panel["message_id"]),
            )
            lines.append(
                f"<#{panel['channel_id']}> · [message](https://discord.com/channels/{self.guild.id}/{panel['channel_id']}/{panel['message_id']}) · {row['total'] if row else 0} réaction(s)"
            )
        box.add_item(
            discord.ui.TextDisplay(
                "## "
                + icons.titre("role", "Rôles par réaction")
                + warning
                + "\n"
                + ("\n".join(lines)[:3200] or "Aucun panneau.")
            )
        )
        channel = discord.ui.ChannelSelect(
            placeholder="Salon du panneau",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        )

        async def choose_channel(i):
            self.channel_id = channel.values[0].id
            await i.response.defer()

        channel.callback = choose_channel
        box.add_item(discord.ui.ActionRow(channel))
        if panels:
            self.page = min(self.page, (len(panels) - 1) // 25)
            page_panels = panels[self.page * 25 : (self.page + 1) * 25]
            select = discord.ui.Select(
                placeholder="Gérer un panneau existant",
                options=[
                    discord.SelectOption(
                        label=str(p["title"])[:100],
                        value=str(p["message_id"]),
                        default=self.message_id == p["message_id"],
                    )
                    for p in page_panels
                ],
            )

            async def choose_panel(i):
                self.message_id = int(select.values[0])
                await self.build()
                await i.response.edit_message(view=self)

            select.callback = choose_panel
            box.add_item(discord.ui.ActionRow(select))
            if len(panels) > 25:

                async def next_page(i):
                    self.page = (self.page + 1) % ((len(panels) + 24) // 25)
                    await self.build()
                    await i.response.edit_message(view=self)

                box.add_item(
                    discord.ui.ActionRow(
                        button("Page suivante des panneaux", next_page)
                    )
                )

        async def create(i):
            if not self.channel_id:
                return await i.response.send_message(
                    "Choisissez le salon.", ephemeral=True
                )
            await i.response.send_modal(PanelTextModal(self))

        async def existing(i):
            await i.response.send_modal(ExistingMessageModal(self))

        box.add_item(
            discord.ui.ActionRow(
                button("Créer un panneau", create),
                button("Utiliser un message existant", existing),
            )
        )
        if self.message_id:
            settings = await options(self.bot, self.guild.id, self.message_id)
            rows = await self.bot.db.fetchall(
                "SELECT * FROM reaction_roles WHERE guild_id=? AND message_id=?",
                (self.guild.id, self.message_id),
            )

            async def add(i):
                await i.response.send_modal(EmojiModal(self))

            async def delete(i):
                await i.response.send_message(
                    view=DeletePanelView(self), ephemeral=True
                )

            box.add_item(
                discord.ui.ActionRow(
                    button("Ajouter une réaction", add),
                    button("Supprimer le panneau", delete, danger=True),
                )
            )
            if rows:
                remove = discord.ui.Select(
                    placeholder="Retirer une réaction",
                    options=[
                        discord.SelectOption(
                            label=str(r["label"] or r["role_id"])[:100],
                            value=str(n),
                            description=str(r["emoji"])[:100],
                        )
                        for n, r in enumerate(rows[:20])
                    ],
                )

                async def remove_cb(i):
                    row = rows[int(remove.values[0])]
                    cog = self.cog()
                    await cog.rolepanel_remove.callback(
                        cog,
                        ComponentContext(self.bot, i),
                        self.message_id,
                        row["emoji"],
                    )

                remove.callback = remove_cb
                box.add_item(discord.ui.ActionRow(remove))
            controls = []
            for key, label in [
                ("single_role", "Un seul rôle à la fois"),
                ("remove_on_unreact", "Retirer le rôle sans réaction"),
            ]:

                async def toggle(i, _key=key):
                    await save_options(
                        self.bot,
                        self.guild.id,
                        self.message_id,
                        {_key: 0 if settings[_key] else 1},
                    )
                    await self.build()
                    await i.response.edit_message(view=self)

                controls.append(
                    button(label + (" : oui" if settings[key] else " : non"), toggle)
                )
            box.add_item(discord.ui.ActionRow(*controls))
            required = discord.ui.RoleSelect(
                placeholder="Rôle requis pour réagir (vide = aucun)",
                min_values=0,
                max_values=1,
                default_values=[discord.Object(id=settings["required_role_id"])]
                if settings["required_role_id"]
                and self.guild.get_role(settings["required_role_id"])
                else [],
            )

            async def required_cb(i):
                await save_options(
                    self.bot,
                    self.guild.id,
                    self.message_id,
                    {
                        "required_role_id": required.values[0].id
                        if required.values
                        else 0
                    },
                )
                await self.build()
                await i.response.edit_message(view=self)

            required.callback = required_cb
            box.add_item(discord.ui.ActionRow(required))
        self.add_item(box)
        return self
