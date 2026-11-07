"""Panneaux publics économie et jeux : préparation, aperçu et restauration."""

from __future__ import annotations

import json
import logging

import discord

from cogs.economy_setup import GOLD, AdminView, button
from utils import sentrix_emojis as icons
from utils.component_context import ComponentContext
from utils.economy_settings import enabled_or_reply
from utils.sentrix_panel_style import banner, decorate_controls

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
    "fight": ("Combat au tour par tour", "GamesDuels"),
    "duel": ("Pierre-feuille-ciseaux", "GamesDuels"),
    "numberduel": ("Duel de nombres", "GamesDuels"),
    "quizduel": ("Duel de quiz", "GamesDuels"),
    "reactionduel": ("Duel de réflexes", "GamesDuels"),
    "connect4": ("Puissance 4", "GamesDuels"),
    "tictactoe": ("Morpion", "Minigames"),
    "triviastart": ("Quiz du salon", "GamesCommunity"),
    "wordrace": ("Course aux mots", "GamesCommunity"),
    "mathrace": ("Course au calcul", "GamesCommunity"),
    "guessrace": ("Course au nombre", "GamesCommunity"),
    "reactionevent": ("Défi de réflexes", "GamesCommunity"),
    "emoji_race": ("Course aux emojis", "GamesCommunity"),
    "lastmessage": ("Dernier message gagne", "GamesCommunity"),
}


class ActivityPublicView(discord.ui.LayoutView):
    def __init__(self, bot, config):
        super().__init__(timeout=None)
        self.bot, self.config = bot, config
        box = discord.ui.Container(accent_colour=0x5865F2)
        banner(box)
        box.add_item(
            discord.ui.TextDisplay(
                f"## {icons.titre('gamepad', config['title'])}\n{config['text']}"
            )
        )
        for group in ("Economy", "GamesRapides", "Duels", "GamesCommunity"):
            names = [
                n
                for n in config["actions"]
                if n in ACTIONS
                and (
                    "Duels"
                    if ACTIONS[n][1] in {"GamesDuels", "Minigames"}
                    else ACTIONS[n][1]
                )
                == group
            ]
            if not names:
                continue
            titles = {
                "Economy": ("Mon économie", "Récompenses, solde et boutique."),
                "GamesRapides": ("En solo", "Une partie rapide, à votre rythme."),
                "Duels": ("À deux", "Choisissez un jeu, puis votre adversaire."),
                "GamesCommunity": (
                    "En groupe",
                    "Choisissez un jeu et invitez le salon à rejoindre.",
                ),
            }
            title, help_text = titles[group]
            icon = {
                "Economy": "wallet",
                "GamesRapides": "gamepad",
                "Duels": "users",
                "GamesCommunity": "party",
            }[group]
            box.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
            box.add_item(
                discord.ui.TextDisplay(f"**{icons.titre(icon, title)}** · {help_text}")
            )
            picker = discord.ui.Select(
                placeholder={
                    "Economy": "Mon économie",
                    "GamesRapides": "Jouer en solo",
                    "Duels": "Défier un membre",
                    "GamesCommunity": "Ouvrir une partie de groupe",
                }[group],
                custom_id="sentrix:activity:" + group,
                options=[
                    discord.SelectOption(
                        label=ACTIONS[n][0], value=n, emoji=icons.partiel(icon)
                    )
                    for n in names
                ],
            )

            async def launch(i, _picker=picker, _group=group):
                name = _picker.values[0]
                if (
                    name not in self.config["actions"]
                    or name not in ACTIONS
                    or (
                        "Duels"
                        if ACTIONS[name][1] in {"GamesDuels", "Minigames"}
                        else ACTIONS[name][1]
                    )
                    != _group
                ):
                    return await i.response.send_message(
                        "Cette option n'est pas proposée sur ce panneau.",
                        ephemeral=True,
                    )
                if _group in {"Duels", "GamesCommunity"} and i.guild is None:
                    return await i.response.send_message(
                        "Les parties multijoueurs se lancent sur un serveur.",
                        ephemeral=True,
                    )
                if _group == "Duels":
                    from cogs.community_game_panels import DuelMemberPicker

                    return await i.response.send_message(
                        view=DuelMemberPicker(
                            bot,
                            i.guild,
                            i.user.id,
                            ACTIONS[name][1],
                            name,
                            ACTIONS[name][0],
                        ),
                        ephemeral=True,
                    )
                if _group == "GamesCommunity":
                    from cogs.community_game_panels import open_community_lobby

                    return await open_community_lobby(bot, i, name, ACTIONS[name][0])
                cog = bot.get_cog(ACTIONS[name][1])
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
        if any(n in ACTIONS and ACTIONS[n][1] != "Economy" for n in config["actions"]):
            box.add_item(discord.ui.Separator())
            tools = []
            for label, name in (
                ("Mes statistiques", "gamestats"),
                ("Classement des joueurs", "gametop"),
            ):
                item = discord.ui.Button(
                    label=label, custom_id="sentrix:activity:profile:" + name
                )

                async def profile(i, _name=name):
                    cog = bot.get_cog("GamesPlayerCommands")
                    if cog is None:
                        return await i.response.send_message(
                            "Les statistiques sont temporairement indisponibles.",
                            ephemeral=True,
                        )
                    await i.response.defer(ephemeral=True, thinking=True)
                    ctx = ComponentContext(bot, i)
                    command = getattr(cog, _name)
                    ctx.command = command
                    await command.callback(cog, ctx)

                item.callback = profile
                tools.append(item)
            box.add_item(discord.ui.ActionRow(*tools))
        self.add_item(box)
        decorate_controls(self)


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
            "text": "Choisissez votre façon de jouer ci-dessous.",
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
        banner(box)
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
        banner(box)
        box.add_item(discord.ui.TextDisplay("## Panneau publié\n" + message.jump_url))
        self.add_item(box)
        await i.edit_original_response(view=self)
        self.stop()
