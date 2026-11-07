"""Sauvegardes existantes accessibles en boutons, restauration confirmée."""

from __future__ import annotations

import json

import discord

from cogs.complete_setup_common import CompleteView, button, heading, with_actor
from utils import sentrix_emojis as icons
from utils.component_context import ComponentContext


class BackupNameModal(discord.ui.Modal, title="Créer une sauvegarde"):
    name = discord.ui.TextInput(
        label="Nom de la sauvegarde", max_length=100, default="Sauvegarde manuelle"
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    @with_actor
    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        if self.owner.busy:
            return await i.response.send_message(
                "Une opération est déjà en cours.", ephemeral=True
            )
        cog = self.owner.bot.get_cog("Security")
        if cog is None:
            return await i.response.send_message(
                "Le moteur de sauvegarde est indisponible.", ephemeral=True
            )
        self.owner.busy = True
        await i.response.defer()
        try:
            await cog.server_backup.callback(
                cog,
                ComponentContext(self.owner.bot, i),
                label=self.name.value.strip() or "Sauvegarde manuelle",
            )
            await self.owner.refresh(i)
        finally:
            self.owner.busy = False


class DeleteBackupView(CompleteView):
    def __init__(self, owner, row):
        super().__init__(owner.bot, owner.guild, owner.owner_id)
        self.owner, self.row, self.done = owner, row, False

    async def interaction_check(self, i):
        return await self.owner.interaction_check(i)

    async def build(self):
        self.clear_items()
        box = heading(
            "Supprimer cette sauvegarde ?",
            f"**{self.row['label']}** · #{self.row['id']}\nSeul cet instantané sera supprimé. Les salons, rôles et messages du serveur ne sont pas modifiés.",
        )

        async def yes(i):
            if self.done:
                return await i.response.send_message(
                    "Cette confirmation est déjà utilisée.", ephemeral=True
                )
            if self.owner.busy:
                return await i.response.send_message(
                    "Une restauration est déjà en cours.", ephemeral=True
                )
            self.done = True
            await i.response.defer()
            await self.bot.db.execute(
                "DELETE FROM server_backups WHERE guild_id=? AND id=?",
                (self.guild.id, self.row["id"]),
            )
            from utils import config_journal

            await config_journal.record(
                self.bot.db, self.guild.id, "backup.deleted", self.row["id"], None
            )
            self.owner.selected = None
            await self.owner.build()
            await i.edit_original_response(view=self.owner)
            self.stop()

        async def no(i):
            await i.response.defer()
            await i.edit_original_response(view=await self.owner.build())
            self.stop()

        box.add_item(
            discord.ui.ActionRow(
                button("Supprimer cette sauvegarde", yes, danger=True),
                button("Annuler", no),
            )
        )
        return self.finish(box)


class BackupSetupView(CompleteView):
    async def interaction_check(self, i):
        from cogs.economy_setup import AdminView

        return await AdminView.interaction_check(self, i)

    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        self.page = 0
        self.selected = None
        self.busy = False

    async def build(self):
        self.clear_items()
        rows = await self.bot.db.fetchall(
            "SELECT id,label,created_at,data_json FROM server_backups WHERE guild_id=? ORDER BY created_at DESC,id DESC",
            (self.guild.id,),
        )
        self.page = min(self.page, max(0, (len(rows) - 1) // 25))
        conf = await self.bot.db.get_automod(self.guild.id)
        box = heading(
            icons.titre("save", "Sauvegardes et restauration"),
            f"**{len(rows)} sauvegarde(s)** sur ce serveur.\n**Sauvegardes automatiques anti-nuke :** {'Liées à la protection active' if conf and conf['antinuke'] else 'Inactives avec l’anti-nuke désactivé'}.\nLe moteur existant sauvegarde la structure toutes les 6 h lorsqu’il est actif et conserve 5 instantanés automatiques. Les sauvegardes manuelles restent séparées.",
        )
        current = next((row for row in rows if int(row["id"]) == self.selected), None)
        if rows:
            picker = discord.ui.Select(
                placeholder=f"Choisir une sauvegarde — page {self.page + 1}",
                options=[
                    discord.SelectOption(
                        label=str(r["label"] or "Sauvegarde")[:100],
                        value=str(r["id"]),
                        description=f"#{r['id']} · {r['created_at']}",
                        default=int(r["id"]) == self.selected,
                    )
                    for r in rows[self.page * 25 : (self.page + 1) * 25]
                ],
            )

            async def choose(i):
                self.selected = int(picker.values[0])
                await self.refresh(i)

            picker.callback = choose
            box.add_item(discord.ui.ActionRow(picker))
        if current:
            try:
                data = json.loads(current["data_json"])
                roles = len(data.get("roles", []))
                categories = len(data.get("categories", []))
                channels = sum(
                    len(c.get("channels", [])) for c in data.get("categories", [])
                ) + len(data.get("uncategorized", []))
                detail = f"{roles} rôles · {categories} catégories · {channels} salons"
            except (ValueError, TypeError, AttributeError):
                detail = "Contenu non lisible : cette sauvegarde doit être vérifiée avant restauration."
            box.add_item(
                discord.ui.TextDisplay(
                    f"### {current['label']}\n{detail}\nCréée <t:{int(current['created_at'])}:f>.\nLa restauration existante propose une confirmation avant de recréer les éléments manquants. Elle ne restaure pas les anciens messages."
                )
            )

        async def create(i):
            await i.response.send_modal(BackupNameModal(self))

        async def restore(i):
            if self.busy:
                return await i.response.send_message(
                    "Une opération est déjà en cours.", ephemeral=True
                )
            if current is None:
                return await i.response.send_message(
                    "Choisissez une sauvegarde.", ephemeral=True
                )
            cog = self.bot.get_cog("Security")
            if cog is None:
                return await i.response.send_message(
                    "Le moteur de restauration est indisponible.", ephemeral=True
                )
            self.busy = True
            await i.response.defer()
            try:
                await cog.server_restore.callback(
                    cog, ComponentContext(self.bot, i), int(current["id"])
                )
            finally:
                self.busy = False

        async def remove(i):
            if current is None:
                return await i.response.send_message(
                    "Choisissez une sauvegarde.", ephemeral=True
                )
            await i.response.edit_message(
                view=await DeleteBackupView(self, current).build()
            )

        restore_button = button("Préparer la restauration", restore)
        delete_button = button("Supprimer la sauvegarde", remove, danger=True)
        restore_button.disabled = delete_button.disabled = current is None
        box.add_item(
            discord.ui.ActionRow(
                button("Créer une sauvegarde", create), restore_button, delete_button
            )
        )
        if len(rows) > 25:

            async def previous(i):
                self.page = max(0, self.page - 1)
                await self.refresh(i)

            async def next_page(i):
                self.page += 1
                await self.refresh(i)

            box.add_item(
                discord.ui.ActionRow(
                    button("Page précédente", previous),
                    button("Page suivante", next_page),
                )
            )

        async def security(i):
            from cogs.complete_security_setup import SecurityCenterView

            await i.response.defer()
            await i.edit_original_response(
                view=await SecurityCenterView(
                    self.bot, self.guild, self.owner_id, "antinuke"
                ).build(),
                attachments=[],
            )

        async def refresh(i):
            await self.refresh(i)

        box.add_item(
            discord.ui.ActionRow(
                button("Configurer l’anti-nuke", security),
                button("Actualiser", refresh),
            )
        )
        return self.finish(box)
