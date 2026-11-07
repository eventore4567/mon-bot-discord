"""Défis et salons d’attente publics, branchés sur les jeux existants."""

from __future__ import annotations

import asyncio
import logging

import discord

from cogs.complete_setup_common import button, heading, setting_line
from utils import game_rewards
from utils import sentrix_emojis as icons
from utils.component_context import ComponentContext
from utils.sentrix_panel_style import decorate_controls

log = logging.getLogger(__name__)


class PublicGameContext(ComponentContext):
    def __init__(self, bot, interaction):
        super().__init__(bot, interaction)
        self.sent = []

    async def send(self, content=None, **kwargs):
        kwargs.pop("ephemeral", None)
        kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
        if content is not None:
            kwargs["content"] = content
        message = await self.channel.send(**kwargs)
        self.sent.append(message)
        return message


async def game_ready(bot, i, command):
    if i.guild is None or i.channel is None or i.user.bot:
        return False, "Choisissez cette activité depuis un salon du serveur."
    perms = (
        i.channel.permissions_for(i.guild.me)
        if i.guild.me
        else discord.Permissions.none()
    )
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        return (
            False,
            "SentriX doit voir ce salon, envoyer des messages et intégrer des liens.",
        )
    ok, reason = await game_rewards.is_game_enabled(
        bot,
        i.guild.id,
        command.name,
        i.channel.id,
        {r.id for r in getattr(i.user, "roles", [])},
    )
    return ok, reason


class DuelMemberPicker(discord.ui.LayoutView):
    def __init__(self, bot, guild, owner_id, cog_name, command_name, label):
        super().__init__(timeout=120)
        self.bot, self.guild, self.owner_id = bot, guild, owner_id
        self.busy = False
        box = heading(
            "Défier un membre",
            f"**{label}**\nChoisissez votre adversaire. Le défi sera visible dans ce salon ; il devra l’accepter avant le début de la partie.",
        )
        picker = discord.ui.UserSelect(placeholder="Choisir l’adversaire", max_values=1)

        async def choose(i):
            if self.busy:
                return await i.response.send_message(
                    "Ce défi est déjà en préparation.", ephemeral=True
                )
            cog = bot.get_cog(cog_name)
            command = getattr(cog, command_name, None) if cog else None
            if command is None:
                return await i.response.send_message(
                    "Ce jeu est temporairement indisponible.", ephemeral=True
                )
            self.busy = True
            await i.response.defer(ephemeral=True, thinking=True)
            try:
                opponent = guild.get_member(picker.values[0].id)
                if opponent is None:
                    opponent = await guild.fetch_member(picker.values[0].id)
                invalid = game_rewards.validate_opponent(i.user, opponent)
                if invalid:
                    return await i.followup.send(invalid, ephemeral=True)
                ok, reason = await game_ready(bot, i, command)
                if not ok:
                    return await i.followup.send(reason, ephemeral=True)
                ctx = PublicGameContext(bot, i)
                ctx.command = command
                await command.callback(cog, ctx, opponent)
                link = ctx.sent[-1].jump_url if ctx.sent else i.channel.mention
                await i.edit_original_response(
                    view=result_view(
                        "Résultat du défi", f"Consultez le message du salon : {link}"
                    )
                )
                self.stop()
            except (discord.NotFound, discord.Forbidden):
                await i.followup.send(
                    "Adversaire introuvable ou permissions insuffisantes.",
                    ephemeral=True,
                )
            finally:
                self.busy = False

        picker.callback = choose
        box.add_item(discord.ui.ActionRow(picker))
        self.add_item(box)

    async def interaction_check(self, i):
        if i.guild_id != self.guild.id or i.user.id != self.owner_id:
            await i.response.send_message(
                "Ce choix d’adversaire appartient à une autre personne.", ephemeral=True
            )
            return False
        return True


def result_view(title, text):
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(heading(title, text))
    return view


class CommunityLobby(discord.ui.LayoutView):
    def __init__(self, bot, guild, channel, host, command_name, label):
        super().__init__(timeout=180)
        self.bot, self.guild, self.channel = bot, guild, channel
        self.host_id = host.id
        self.command_name, self.label = command_name, label
        self.players = {host.id: host.display_name}
        self.state = "waiting"
        self.message = None
        self.lock = asyncio.Lock()
        self._watcher = None
        self.build()

    def build(self):
        self.clear_items()
        states = {
            "waiting": "En attente de joueurs",
            "starting": "Préparation de la partie",
            "playing": "Partie en cours",
            "finished": "Partie terminée",
            "closed": "Salon d’attente fermé",
        }
        text = (
            f"**{self.label}** · {states[self.state]}\nHôte : <@{self.host_id}>\n\n**Joueurs inscrits ({len(self.players)}/20)**\n"
            + " · ".join(f"<@{ident}>" for ident in self.players)
        )
        text += "\n\nPartie ouverte au salon : les autres membres autorisés peuvent aussi jouer."
        box = heading(icons.titre("users", "Jouer ensemble"), text)
        if self.state == "waiting":
            box.add_item(discord.ui.Separator())
            join_button = button("Rejoindre", self.join)
            join_button.style = discord.ButtonStyle.primary
            start_button = button("Lancer la partie", self.start)
            start_button.style = discord.ButtonStyle.success
            setting_line(
                box, "1 · Rejoindre", "Inscrivez-vous pour jouer ensemble.", join_button
            )
            setting_line(
                box,
                "2 · Lancer",
                "L’hôte lance dès que 2 joueurs sont inscrits.",
                start_button,
            )
            box.add_item(discord.ui.Separator())
            box.add_item(
                discord.ui.ActionRow(
                    button("Quitter", self.leave), button("Annuler", self.cancel)
                )
            )
            box.add_item(
                discord.ui.TextDisplay(
                    "-# Seul l’hôte peut annuler. Expiration après 3 min d’inactivité."
                )
            )
        self.add_item(box)
        decorate_controls(self)
        return self

    async def interaction_check(self, i):
        if i.guild_id != self.guild.id or i.channel_id != self.channel.id or i.user.bot:
            await i.response.send_message(
                "Cette partie appartient à un autre salon.", ephemeral=True
            )
            return False
        return True

    def release(self):
        registry = getattr(self.bot, "_sentrix_public_game_lobbies", {})
        if registry.get(self.channel.id) is self:
            registry.pop(self.channel.id, None)

    async def join(self, i):
        async with self.lock:
            if self.state != "waiting":
                return await i.response.send_message(
                    "Les inscriptions sont fermées.", ephemeral=True
                )
            if i.user.id in self.players:
                return await i.response.send_message(
                    "Vous êtes déjà inscrit.", ephemeral=True
                )
            if len(self.players) >= 20:
                return await i.response.send_message(
                    "Cette liste est complète (20 joueurs).", ephemeral=True
                )
            await i.response.defer()
            cog = self.bot.get_cog("GamesCommunity")
            command = getattr(cog, self.command_name, None) if cog else None
            if command is None:
                return await i.followup.send("Ce jeu est indisponible.", ephemeral=True)
            ok, reason = await game_ready(self.bot, i, command)
            if not ok:
                return await i.followup.send(reason, ephemeral=True)
            self.players[i.user.id] = i.user.display_name
            self.build()
            await i.edit_original_response(
                view=self, allowed_mentions=discord.AllowedMentions.none()
            )

    async def leave(self, i):
        async with self.lock:
            if self.state != "waiting":
                return await i.response.send_message(
                    "La partie a déjà démarré.", ephemeral=True
                )
            if i.user.id not in self.players:
                return await i.response.send_message(
                    "Vous n’êtes pas inscrit.", ephemeral=True
                )
            if i.user.id == self.host_id:
                self.state = "closed"
                self.release()
            else:
                self.players.pop(i.user.id, None)
            self.build()
            await i.response.edit_message(
                view=self, allowed_mentions=discord.AllowedMentions.none()
            )
            if self.state == "closed":
                self.stop()

    async def cancel(self, i):
        async with self.lock:
            if i.user.id != self.host_id:
                return await i.response.send_message(
                    "Seul l’hôte peut annuler cette partie.", ephemeral=True
                )
            if self.state != "waiting":
                return await i.response.send_message(
                    "Cette partie n’attend plus de joueurs.", ephemeral=True
                )
            self.state = "closed"
            self.release()
            self.build()
            await i.response.edit_message(
                view=self, allowed_mentions=discord.AllowedMentions.none()
            )
            self.stop()

    async def start(self, i):
        async with self.lock:
            if i.user.id != self.host_id:
                return await i.response.send_message(
                    "Seul l’hôte peut lancer la partie.", ephemeral=True
                )
            if self.state != "waiting":
                return await i.response.send_message(
                    "Lancement déjà en cours ou terminé.", ephemeral=True
                )
            if len(self.players) < 2:
                return await i.response.send_message(
                    "Il faut au moins deux joueurs inscrits.", ephemeral=True
                )
            await i.response.defer()
            cog = self.bot.get_cog("GamesCommunity")
            command = getattr(cog, self.command_name, None) if cog else None
            if command is None:
                return await i.followup.send("Ce jeu est indisponible.", ephemeral=True)
            ok, reason = await game_ready(self.bot, i, command)
            if not ok:
                return await i.followup.send(reason, ephemeral=True)
            self.state = "starting"
            self.build()
            await i.edit_original_response(
                view=self, allowed_mentions=discord.AllowedMentions.none()
            )
            before = set(cog._community_tasks)
            ctx = PublicGameContext(self.bot, i)
            ctx.command = command
            try:
                await command.callback(cog, ctx)
            except Exception:
                self.state = "closed"
                self.release()
                self.build()
                await i.edit_original_response(
                    view=self, allowed_mentions=discord.AllowedMentions.none()
                )
                log.exception("Lancement de partie communautaire impossible")
                return await i.followup.send(
                    "La partie n’a pas pu démarrer. Consultez le message du salon ou réessayez.",
                    ephemeral=True,
                )
            tasks = {
                task
                for task in set(cog._community_tasks) - before
                if task.get_name().endswith(f":{self.channel.id}")
            }
            self.state = "playing" if tasks else "finished"
            self.build()
            await i.edit_original_response(
                view=self, allowed_mentions=discord.AllowedMentions.none()
            )
            if not tasks:
                self.release()
                self.stop()
            else:
                self._watcher = asyncio.create_task(
                    self.watch(tasks), name=f"sentrix:lobby:{self.channel.id}"
                )

    async def watch(self, tasks):
        await asyncio.gather(*tasks, return_exceptions=True)
        self.state = "finished"
        self.release()
        self.build()
        if self.message:
            try:
                await self.message.edit(
                    view=self, allowed_mentions=discord.AllowedMentions.none()
                )
            except discord.HTTPException:
                log.debug("Fin de salon de jeu non affichable", exc_info=True)
        self.stop()

    async def on_timeout(self):
        async with self.lock:
            if self.state != "waiting":
                return
            self.state = "closed"
            self.release()
            self.build()
            if self.message:
                try:
                    await self.message.edit(
                        view=self, allowed_mentions=discord.AllowedMentions.none()
                    )
                except discord.HTTPException:
                    log.debug("Salon d’attente expiré non affichable", exc_info=True)


async def open_community_lobby(bot, i, name, label):
    await i.response.defer(ephemeral=True, thinking=True)
    cog = bot.get_cog("GamesCommunity")
    command = getattr(cog, name, None) if cog else None
    if command is None:
        return await i.followup.send("Ce jeu est indisponible.", ephemeral=True)
    ok, reason = await game_ready(bot, i, command)
    if not ok:
        return await i.followup.send(reason, ephemeral=True)
    registry = getattr(bot, "_sentrix_public_game_lobbies", None)
    if registry is None:
        registry = bot._sentrix_public_game_lobbies = {}
    if i.channel.id in registry:
        current = registry[i.channel.id]
        link = current.message.jump_url if current.message else i.channel.mention
        return await i.followup.send(
            "Une partie est déjà ouverte dans ce salon : " + link, ephemeral=True
        )
    lobby = CommunityLobby(bot, i.guild, i.channel, i.user, name, label)
    registry[i.channel.id] = lobby
    try:
        lobby.message = await i.channel.send(
            view=lobby, allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        lobby.release()
        lobby.stop()
        raise
    await i.followup.send(
        "Salon d’attente ouvert : " + lobby.message.jump_url, ephemeral=True
    )
    return lobby
