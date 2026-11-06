"""Panneaux publics économie et jeux : préparation, aperçu et restauration."""

from __future__ import annotations

import json
import logging

import discord

from cogs.economy_setup import GOLD, AdminView, button, panel_header
from utils.component_context import ComponentContext
from utils.economy_settings import enabled_or_reply

log = logging.getLogger(__name__)
SCHEMA = """CREATE TABLE IF NOT EXISTS sentrix_public_activity_panels (
 guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL, message_id BIGINT PRIMARY KEY,
 config TEXT NOT NULL)"""
ACTIONS = {
    "daily": ("Récompense quotidienne", "Economy"),
    "work": ("Travailler", "Economy"),
    "balance": ("Mon solde", "Economy"),
    "shop": ("Boutique", "Economy"),
    "economyleaderboard": ("Classement", "Economy"),
    "highlow": ("Plus ou moins", "GamesRapides"),
    "emojiquiz": ("Quiz emoji", "GamesRapides"),
    "colorquiz": ("Quiz couleurs", "GamesRapides"),
    "minesweeper": ("Démineur", "GamesRapides"),
    "doors": ("Les trois portes", "GamesRapides"),
    "bossfight": ("Combat de boss", "GamesRapides"),
}


class ActivityPublicView(discord.ui.LayoutView):
    def __init__(self, bot, config):
        super().__init__(timeout=None)
        self.bot, self.config = bot, config
        box = discord.ui.Container(accent_colour=GOLD)
        panel_header(box)
        box.add_item(discord.ui.TextDisplay(f"## {config['title']}\n{config['text']}"))
        for group in ("Economy", "GamesRapides"):
            names = [
                n for n in config["actions"] if n in ACTIONS and ACTIONS[n][1] == group
            ]
            if not names:
                continue
            picker = discord.ui.Select(
                placeholder="Choisir une action économique"
                if group == "Economy"
                else "Choisir un jeu à lancer",
                custom_id="sentrix:activity:" + group,
                options=[
                    discord.SelectOption(label=ACTIONS[n][0], value=n) for n in names
                ],
            )

            async def launch(i, _picker=picker, _group=group):
                name = _picker.values[0]
                if (
                    name not in self.config["actions"]
                    or name not in ACTIONS
                    or ACTIONS[name][1] != _group
                ):
                    return await i.response.send_message(
                        "Cette option n'est pas proposée sur ce panneau.",
                        ephemeral=True,
                    )
                cog = bot.get_cog(_group)
                if cog is None:
                    return await i.response.send_message(
                        "Cette activité est temporairement indisponible.",
                        ephemeral=True,
                    )
                ctx = ComponentContext(bot, i)
                command = getattr(cog, name)
                ctx.command = command
                if _group == "Economy" and not await enabled_or_reply(bot, ctx):
                    return
                await i.response.defer(ephemeral=True, thinking=True)
                await command.callback(cog, ctx)

            picker.callback = launch
            box.add_item(discord.ui.ActionRow(picker))
        self.add_item(box)


async def restore_activity_panels(bot):
    await bot.db.execute(SCHEMA)
    rows = await bot.db.fetchall(
        "SELECT message_id,config FROM sentrix_public_activity_panels"
    )
    for row in rows:
        try:
            config = json.loads(row["config"])
            if not config.get("actions") or not all(
                n in ACTIONS for n in config["actions"]
            ):
                continue
            bot.add_view(
                ActivityPublicView(bot, config), message_id=int(row["message_id"])
            )
        except (ValueError, KeyError, TypeError):
            log.warning(
                "Configuration de panneau invalide : %s",
                row["message_id"],
                exc_info=True,
            )


class ActivityTextModal(discord.ui.Modal, title="Personnaliser le panneau"):
    heading = discord.ui.TextInput(label="Titre", max_length=150)
    text = discord.ui.TextInput(
        label="Texte du panneau",
        style=discord.TextStyle.paragraph,
        max_length=1800,
        required=False,
    )

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.heading.default = owner.config["title"]
        self.text.default = owner.config["text"]

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        self.owner.config.update(
            title=self.heading.value.strip() or "Économie et jeux",
            text=self.text.value.strip(),
        )
        self.owner.stage = "channel"
        await self.owner.refresh(i)


class EconomyPanelBuilder(AdminView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        self.config = {
            "title": "Économie et jeux",
            "text": "Choisissez une activité ci-dessous. Votre partie et vos réponses restent privées.",
            "actions": [],
        }
        self.stage = "type"
        self.channel_id = None
        self.busy = False
        self.published = False
        self.build()

    async def refresh(self, i):
        if not i.response.is_done():
            await i.response.defer()
        self.build()
        await i.edit_original_response(view=self)

    def build(self):
        self.clear_items()
        box = discord.ui.Container(accent_colour=GOLD)
        panel_header(box)
        box.add_item(
            discord.ui.TextDisplay(
                "## Créer un panneau\nChoisissez le contenu, personnalisez le texte puis publiez dans un salon."
            )
        )
        if self.stage == "type":
            picker = discord.ui.Select(
                placeholder="Quel panneau voulez-vous ?",
                options=[
                    discord.SelectOption(label="Économie", value="economy"),
                    discord.SelectOption(label="Jeux", value="games"),
                    discord.SelectOption(label="Économie et jeux", value="both"),
                ],
            )

            async def kind(i):
                self.kind = picker.values[0]
                self.config["actions"] = [
                    n
                    for n, (_, group) in ACTIONS.items()
                    if self.kind == "both"
                    or (group == "Economy") == (self.kind == "economy")
                ]
                self.stage = "actions"
                await self.refresh(i)

            picker.callback = kind
            box.add_item(discord.ui.ActionRow(picker))
        elif self.stage == "actions":
            candidates = [
                n
                for n, (_, group) in ACTIONS.items()
                if self.kind == "both"
                or (group == "Economy") == (self.kind == "economy")
            ]
            picker = discord.ui.Select(
                placeholder="Activités à afficher sur le panneau",
                min_values=1,
                max_values=len(candidates),
                options=[
                    discord.SelectOption(
                        label=ACTIONS[n][0],
                        value=n,
                        default=n in self.config["actions"],
                    )
                    for n in candidates
                ],
            )

            async def select(i):
                self.config["actions"] = list(picker.values)
                await self.refresh(i)

            async def text(i):
                await i.response.send_modal(ActivityTextModal(self))

            picker.callback = select
            box.add_item(discord.ui.ActionRow(picker))
            box.add_item(
                discord.ui.ActionRow(button("Continuer : texte du panneau", text))
            )
        elif self.stage == "channel":
            picker = discord.ui.ChannelSelect(
                placeholder="Salon de publication",
                channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            )

            async def channel(i):
                self.channel_id = picker.values[0].id
                self.stage = "preview"
                await self.refresh(i)

            picker.callback = channel
            box.add_item(discord.ui.ActionRow(picker))
        else:
            box.add_item(
                discord.ui.TextDisplay(
                    f"### Aperçu — {self.config['title']}\n{self.config['text']}\n\n**Activités :** "
                    + ", ".join(ACTIONS[n][0] for n in self.config["actions"])
                    + f"\n**Salon :** <#{self.channel_id}>"
                )
            )
            box.add_item(discord.ui.ActionRow(button("Publier", self.publish)))

        async def back(i):
            self.stage = "type"
            await self.refresh(i)

        box.add_item(discord.ui.ActionRow(button("Recommencer le choix", back)))
        self.add_item(box)
        return self

    async def publish(self, i):
        if not await self.interaction_check(i):
            return
        if self.busy or self.published:
            return await i.response.send_message(
                "Publication déjà en cours ou terminée.", ephemeral=True
            )
        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        if channel is None or not self.config["actions"]:
            return await i.response.send_message(
                "Choisissez des activités et un salon.", ephemeral=True
            )
        perms = channel.permissions_for(self.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await i.response.send_message(
                "SentriX doit voir le salon, envoyer des messages et intégrer des liens.",
                ephemeral=True,
            )
        self.busy = True
        await i.response.defer(ephemeral=True, thinking=True)
        message = None
        try:
            await self.bot.db.execute(SCHEMA)
            view = ActivityPublicView(self.bot, self.config)
            message = await channel.send(
                view=view, allowed_mentions=discord.AllowedMentions.none()
            )
            await self.bot.db.execute(
                "INSERT INTO sentrix_public_activity_panels (guild_id,channel_id,message_id,config) VALUES (?,?,?,?)",
                (
                    self.guild.id,
                    channel.id,
                    message.id,
                    json.dumps(self.config, ensure_ascii=False),
                ),
            )
            from utils import config_journal

            await config_journal.record(
                self.bot.db, self.guild.id, "activity_panel.created", None, message.id
            )
            self.bot.add_view(view, message_id=message.id)
        except Exception:
            log.exception("Publication du panneau impossible")
            if message is not None:
                await self.bot.db.execute(
                    "DELETE FROM sentrix_public_activity_panels WHERE message_id=?",
                    (message.id,),
                )
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
            self.busy = False
            return await i.followup.send(
                "Publication impossible. Vérifiez les permissions puis réessayez.",
                ephemeral=True,
            )
        self.published = True
        self.busy = False
        self.clear_items()
        box = discord.ui.Container(accent_colour=GOLD)
        panel_header(box)
        box.add_item(discord.ui.TextDisplay("## Panneau publié\n" + message.jump_url))
        self.add_item(box)
        await i.edit_original_response(view=self)
        self.stop()
