"""Private-owner-controlled prefix +sticky mini configuration panel."""
from __future__ import annotations

import logging
import discord
from discord.ext import commands
from utils import sentrix_panels as panels

log = logging.getLogger("bot.sticky-setup")


class StickyTextModal(discord.ui.Modal, title="Texte du sticky"):
    text = discord.ui.TextInput(
        label="Message", style=discord.TextStyle.paragraph, min_length=1,
        max_length=1700, required=True, placeholder="Écris le message à conserver en bas du salon",
    )

    def __init__(self, owner: "StickySetupView"):
        super().__init__()
        self.owner = owner
        if owner.content:
            self.text.default = owner.content

    async def on_submit(self, interaction: discord.Interaction):
        self.owner.content = str(self.text.value).strip()
        await interaction.response.send_message(
            "Texte enregistré. Choisis les salons puis clique sur Appliquer.",
            ephemeral=True,
        )


class StickySetupView(discord.ui.View):
    """All +sticky interactions; slash commands use their native parameter boxes."""

    def __init__(self, cog, guild_id: int, author_id: int, *, default_channel=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)
        self.channel_ids = [default_channel.id] if isinstance(default_channel, discord.TextChannel) else []
        self.action = "add"
        self.mode = "banner"
        self.content = ""
        self._busy = False

        channel_pick = discord.ui.ChannelSelect(
            placeholder="Choisir 1 à 5 salons", min_values=1, max_values=5,
            channel_types=[discord.ChannelType.text],
        )
        async def choose_channels(interaction: discord.Interaction):
            self.channel_ids = list(dict.fromkeys(int(c.id) for c in channel_pick.values))
            await interaction.response.defer()
        channel_pick.callback = choose_channels
        self.add_item(channel_pick)

        action_pick = discord.ui.Select(
            placeholder="Action : créer / modifier / supprimer / consulter",
            options=[
                discord.SelectOption(label="Créer un sticky", value="add", default=True),
                discord.SelectOption(label="Modifier un sticky", value="edit"),
                discord.SelectOption(label="Supprimer un sticky", value="remove"),
                discord.SelectOption(label="Voir les sticky", value="list"),
            ],
        )
        async def choose_action(interaction: discord.Interaction):
            self.action = action_pick.values[0]
            await interaction.response.defer()
        action_pick.callback = choose_action
        self.add_item(action_pick)

        format_pick = discord.ui.Select(
            placeholder="Format : texte / embed / bannière ultra-fine",
            options=[
                discord.SelectOption(label="Texte normal", value="text"),
                discord.SelectOption(label="Embed sans bannière", value="embed"),
                discord.SelectOption(label="Embed avec bannière ultra-fine", value="banner", default=True),
            ],
        )
        async def choose_format(interaction: discord.Interaction):
            self.mode = format_pick.values[0]
            await interaction.response.defer()
        format_pick.callback = choose_format
        self.add_item(format_pick)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        if (interaction.guild_id != self.guild_id or user.id != self.author_id
                or not isinstance(user, discord.Member)
                or not user.guild_permissions.manage_messages):
            await interaction.response.send_message(
                "Ce mini-setup est réservé au modérateur qui l'a ouvert.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Écrire le texte", style=discord.ButtonStyle.primary)
    async def write_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyTextModal(self))

    @discord.ui.button(label="Prévisualiser", style=discord.ButtonStyle.secondary)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.content and self.action not in {"list", "remove"}:
            return await interaction.response.send_message("Écris d'abord le texte du sticky.", ephemeral=True)
        if self.action in {"list", "remove"}:
            return await interaction.response.send_message(
                "Cette action n'a pas besoin d'aperçu de texte.", ephemeral=True
            )
        if self.mode == "text":
            return await interaction.response.send_message(
                self.content, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        if self.mode == "embed":
            return await interaction.response.send_message(
                embed=discord.Embed(description=self.content), ephemeral=True
            )
        from utils.premium_log_banners import get_premium_log_banner, BANNER_FILENAME
        banner = discord.Embed()
        banner.set_image(url=f"attachment://{BANNER_FILENAME}")
        await interaction.response.send_message(
            embeds=[banner, discord.Embed(description=self.content)],
            file=discord.File(str(get_premium_log_banner()), filename=BANNER_FILENAME),
            ephemeral=True,
        )

    @discord.ui.button(label="Appliquer", style=discord.ButtonStyle.success)
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._busy:
            return await interaction.response.send_message("Une opération est déjà en cours.", ephemeral=True)
        if self.action != "list" and not self.channel_ids:
            return await interaction.response.send_message("Choisis au moins un salon.", ephemeral=True)
        if self.action in {"add", "edit"} and not self.content:
            return await interaction.response.send_message("Écris le texte à publier.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        self._busy = True
        try:
            if self.action == "list":
                rows = await self.cog.bot.db.fetchall(
                    "SELECT channel_id,content FROM sentrix_sticky WHERE guild_id=? ORDER BY channel_id LIMIT 30",
                    (self.guild_id,),
                )
                result = []
                for row in rows:
                    mode, content = self.cog._sticky_decode(row["content"])
                    ch = interaction.guild.get_channel(int(row["channel_id"]))
                    result.append(f"{ch.mention if ch else 'Salon supprimé'} · {mode} · {content[:75]}")
                return await interaction.followup.send(
                    "\n".join(result) if result else "Aucun sticky configuré.",
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
                )

            ok, failures = [], []
            for channel_id in self.channel_ids[:5]:
                channel = interaction.guild.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    failures.append(str(channel_id))
                    continue
                permissions = channel.permissions_for(interaction.guild.me)
                own_perms = channel.permissions_for(interaction.user)
                if not (own_perms.manage_messages and permissions.view_channel
                        and permissions.send_messages and permissions.manage_messages
                        and (self.action == "remove" or (
                            permissions.embed_links and permissions.attach_files))):
                    failures.append(channel.mention)
                    continue
                try:
                    old = await self.cog.bot.db.fetchone(
                        "SELECT message_id FROM sentrix_sticky WHERE guild_id=? AND channel_id=?",
                        (self.guild_id, channel_id),
                    )
                    if self.action == "edit" and not old:
                        failures.append(channel.mention)
                        continue
                    if self.action == "remove":
                        if old and old["message_id"]:
                            try:
                                await (await channel.fetch_message(int(old["message_id"]))).delete()
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                pass
                        await self.cog.bot.db.execute(
                            "DELETE FROM sentrix_sticky WHERE guild_id=? AND channel_id=?",
                            (self.guild_id, channel_id),
                        )
                        self.cog._no_sticky[channel_id] = True
                    else:
                        await self.cog._sticky_store(self.guild_id, channel, self.content, self.mode)
                    ok.append(channel.mention)
                except (discord.HTTPException, ValueError, OSError):
                    log.exception("Erreur sticky dans %s", channel_id)
                    failures.append(channel.mention)
            answer = (f"{len(ok)} salon(s) mis à jour" if ok else "Aucun changement effectué.")
            if failures:
                answer += "\nÀ vérifier : " + ", ".join(failures)
            await interaction.followup.send(
                answer, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
        finally:
            self._busy = False

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(view=None)


async def open_sticky_setup(ctx: commands.Context, cog) -> None:
    view = StickySetupView(cog, ctx.guild.id, ctx.author.id, default_channel=ctx.channel)
    panneau = panels.Panneau(
        titre="Sticky · configuration",
        sous_titre="Crée, modifie ou supprime tes messages persistants.",
        kind="moderation",
        banniere=True,
        sections=[
            panels.Section("01 · Salons", texte="Sélectionne jusqu'à cinq salons."),
            panels.Section("02 · Format", texte="Texte normal, embed, ou embed avec bande ultra-fine."),
            panels.Section("03 · Texte", texte="Utilise Écrire le texte, puis Appliquer."),
        ],
    )
    panneau = panels.avec_composants(panneau, view)
    await panels.envoyer(ctx, panneau, ephemere=bool(ctx.interaction))
