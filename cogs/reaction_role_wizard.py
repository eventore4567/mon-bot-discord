"""Préparation privée des associations, puis publication du panneau."""

from __future__ import annotations

import logging

import discord

from cogs.economy_setup import AdminView, button
from utils import config_journal
from utils.reaction_role_options import save_options

log = logging.getLogger(__name__)

PURPLE = 0x9B59B6


class RoleEmojiModal(discord.ui.Modal, title="Emoji de ce rôle"):
    emoji = discord.ui.TextInput(label="Emoji (ex. 🎮 ou <:nom:id>)", max_length=100)

    def __init__(self, owner, role):
        super().__init__()
        self.owner, self.role = owner, role

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        from cogs.economy import _self_assignable_role_error
        from cogs.verification import _emoji_parts

        role = self.owner.guild.get_role(self.role.id)
        error = (
            _self_assignable_role_error(self.owner.guild, role)
            if role
            else "Rôle supprimé."
        )
        if error:
            return await i.response.send_message(error, ephemeral=True)
        try:
            key, display, _ = _emoji_parts(self.emoji.value.strip())
        except ValueError:
            return await i.response.send_message(
                "Choisissez un emoji valide.", ephemeral=True
            )
        if any(row[0] == key for row in self.owner.mappings):
            return await i.response.send_message(
                "Cet emoji est déjà associé à un rôle.", ephemeral=True
            )
        if any(row[2] == role.id for row in self.owner.mappings):
            return await i.response.send_message(
                "Ce rôle a déjà son emoji.", ephemeral=True
            )
        if len(self.owner.mappings) >= 20:
            return await i.response.send_message(
                "Maximum 20 associations par panneau.", ephemeral=True
            )
        self.owner.mappings.append((key, display, role.id))
        await self.owner.refresh(i)


class RoleTextModal(discord.ui.Modal, title="Texte du panneau"):
    heading = discord.ui.TextInput(label="Titre", max_length=150)
    text = discord.ui.TextInput(
        label="Votre texte",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.heading.default = owner.title
        self.text.default = owner.text

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        self.owner.title = self.heading.value.strip() or "Choisissez vos rôles"
        self.owner.text = self.text.value.strip()
        self.owner.stage = "channel"
        await self.owner.refresh(i)


class ReactionRoleWizard(AdminView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        self.mappings = []
        self.stage = "roles"
        self.title = "Choisissez vos rôles"
        self.text = (
            "Réagissez pour recevoir un rôle. Retirez votre réaction pour l'enlever."
        )
        self.channel_id = None
        self.publishing = False
        self.published = False
        self.build()

    def public_view(self):
        view = discord.ui.LayoutView(timeout=None)
        box = discord.ui.Container(accent_colour=PURPLE)
        box.add_item(discord.ui.TextDisplay(f"## {self.title}\n{self.text}"))
        box.add_item(discord.ui.Separator())
        box.add_item(
            discord.ui.TextDisplay(
                "\n".join(f"{emoji} → <@&{rid}>" for _, emoji, rid in self.mappings)
            )
        )
        view.add_item(box)
        return view

    async def refresh(self, i):
        if not i.response.is_done():
            await i.response.defer()
        self.build()
        await i.edit_original_response(view=self)

    def build(self):
        self.clear_items()
        box = discord.ui.Container(accent_colour=PURPLE)
        summary = "\n".join(f"{emoji} → <@&{rid}>" for _, emoji, rid in self.mappings)
        box.add_item(
            discord.ui.TextDisplay(
                "## Créer un panneau de rôles\n"
                + (summary or "Choisissez un rôle, puis l'emoji qui lui correspond.")
            )
        )
        if self.stage == "roles":
            picker = discord.ui.RoleSelect(
                placeholder="Choisir un rôle à associer",
                disabled=len(self.mappings) >= 20,
            )

            async def choose(i):
                role = self.guild.get_role(picker.values[0].id)
                from cogs.economy import _self_assignable_role_error

                error = (
                    _self_assignable_role_error(self.guild, role)
                    if role
                    else "Rôle supprimé."
                )
                if error:
                    return await i.response.send_message(error, ephemeral=True)
                await i.response.send_modal(RoleEmojiModal(self, role))

            picker.callback = choose
            box.add_item(discord.ui.ActionRow(picker))
            if self.mappings:
                box.add_item(
                    discord.ui.TextDisplay(
                        "Ajoutez un autre rôle avec le sélecteur, ou continuez."
                    )
                )

                async def remove(i):
                    self.mappings.pop()
                    await self.refresh(i)

                async def next_step(i):
                    await i.response.send_modal(RoleTextModal(self))

                box.add_item(
                    discord.ui.ActionRow(
                        button("Retirer la dernière association", remove),
                        button("Continuer : texte du panneau", next_step),
                    )
                )
        elif self.stage == "channel":
            box.add_item(
                discord.ui.TextDisplay(
                    "### Où publier le panneau ?\nChoisissez le salon. Vous pourrez vérifier le résultat avant de publier."
                )
            )
            picker = discord.ui.ChannelSelect(
                placeholder="Choisir le salon de publication",
                channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            )

            async def choose_channel(i):
                self.channel_id = picker.values[0].id
                self.stage = "preview"
                await self.refresh(i)

            picker.callback = choose_channel
            box.add_item(discord.ui.ActionRow(picker))
        else:
            box.add_item(
                discord.ui.TextDisplay(
                    f"### Aperçu — {self.title}\n{self.text}\n\n**Salon :** <#{self.channel_id}>\nSentriX ajoutera les réactions. Réagir donne le rôle ; retirer sa réaction le retire."
                )
            )
            box.add_item(discord.ui.ActionRow(button("Publier", self.publish)))
        if self.stage != "roles":

            async def back(i):
                self.stage = "roles"
                await self.refresh(i)

            async def edit_text(i):
                await i.response.send_modal(RoleTextModal(self))

            box.add_item(
                discord.ui.ActionRow(
                    button("Modifier les rôles", back),
                    button("Modifier le texte", edit_text),
                )
            )
        self.add_item(box)
        return self

    async def publish(self, i):
        if not await self.interaction_check(i):
            return
        if self.publishing or self.published:
            return await i.response.send_message(
                "Publication déjà en cours ou terminée.", ephemeral=True
            )
        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        if channel is None or not self.mappings:
            return await i.response.send_message(
                "Choisissez les rôles et le salon avant de publier.", ephemeral=True
            )
        from cogs.economy import _self_assignable_role_error

        for _, _, rid in self.mappings:
            role = self.guild.get_role(rid)
            error = (
                _self_assignable_role_error(self.guild, role)
                if role
                else "Un rôle a été supprimé."
            )
            if error:
                return await i.response.send_message(error, ephemeral=True)
        perms = channel.permissions_for(self.guild.me)
        if not (
            perms.view_channel
            and perms.send_messages
            and perms.embed_links
            and perms.add_reactions
            and perms.read_message_history
        ):
            return await i.response.send_message(
                "SentriX doit voir le salon, envoyer des messages, intégrer des liens, lire l'historique et ajouter des réactions.",
                ephemeral=True,
            )
        self.publishing = True
        await i.response.defer(ephemeral=True, thinking=True)
        message = None
        try:
            from utils.reaction_role_options import SCHEMA

            await self.bot.db.execute(SCHEMA)
            from cogs.verification import _emoji_parts

            message = await channel.send(
                view=self.public_view(), allowed_mentions=discord.AllowedMentions.none()
            )
            for _, emoji, _ in self.mappings:
                await message.add_reaction(_emoji_parts(emoji)[2])
            import time

            await self.bot.db.execute(
                "INSERT INTO reaction_role_panels (guild_id,channel_id,message_id,title,description,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    self.guild.id,
                    channel.id,
                    message.id,
                    self.title,
                    self.text,
                    self.owner_id,
                    int(time.time()),
                ),
            )
            for key, emoji, rid in self.mappings:
                await self.bot.db.execute(
                    "INSERT INTO reaction_roles (guild_id,channel_id,message_id,emoji,emoji_key,role_id,label,created_by) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        self.guild.id,
                        channel.id,
                        message.id,
                        emoji,
                        key,
                        rid,
                        self.guild.get_role(rid).name,
                        self.owner_id,
                    ),
                )
            await save_options(
                self.bot,
                self.guild.id,
                message.id,
                {"remove_on_unreact": 1, "single_role": 0, "required_role_id": 0},
            )
            await config_journal.record(
                self.bot.db, self.guild.id, "reaction_panel.created", None, message.id
            )
        except Exception:
            log.exception("Publication du panneau de rôles impossible")
            if message is not None:
                for table in (
                    "reaction_roles",
                    "reaction_role_panels",
                    "sentrix_reaction_role_options",
                ):
                    await self.bot.db.execute(
                        f"DELETE FROM {table} WHERE guild_id=? AND message_id=?",
                        (self.guild.id, message.id),
                    )
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
            self.publishing = False
            await i.followup.send(
                "Publication impossible. Vérifiez les permissions et que les emojis sont accessibles à SentriX, puis réessayez.",
                ephemeral=True,
            )
            return
        self.published = True
        self.publishing = False
        self.clear_items()
        box = discord.ui.Container(accent_colour=PURPLE)
        box.add_item(discord.ui.TextDisplay("## Panneau publié\n" + message.jump_url))
        self.add_item(box)
        await i.edit_original_response(view=self)
        self.stop()
