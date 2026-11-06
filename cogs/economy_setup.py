"""Configuration économique en Components V2 ; aucune commande supplémentaire."""

from __future__ import annotations

import discord

from utils import sentrix_emojis as icons
from utils.component_context import ComponentContext
from utils.economy_settings import (
    enabled_or_reply,
    get_economy_settings,
    save_economy_settings,
)

GOLD = 0xF1C40F
FIELDS = {
    "rewards": [
        ("daily_amount", "Daily", int),
        ("weekly_amount", "Weekly", int),
        ("work_min", "Work : minimum", int),
        ("work_max", "Work : maximum", int),
        ("work_cooldown", "Délai work (minutes)", lambda x: int(x) * 60),
    ],
    "jobs": [("salary_multiplier", "Multiplicateur salaire (0.5 à 5)", float)],
    "bank": [
        (
            "interest_rate",
            "Intérêts par jour en % (0 à 5)",
            lambda x: float(x.replace(",", ".")) / 100,
        ),
        ("interest_cap", "Plafond quotidien (0 à 100000)", int),
    ],
    "rob": [
        ("rob_success", "Réussite du vol en % (5 à 90)", int),
        ("rob_fine", "Amende (0 à 1000000)", int),
    ],
    "games": [("games_multiplier", "Multiplicateur gains (0 à 5)", float)],
    "currency": [
        ("currency_name", "Nom de la monnaie", str),
        ("economy_emoji", "Emoji de monnaie", str),
    ],
}


def button(label, callback, *, danger=False):
    item = discord.ui.Button(
        label=label,
        style=discord.ButtonStyle.danger if danger else discord.ButtonStyle.secondary,
    )
    item.callback = callback
    return item


class AdminView(discord.ui.LayoutView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(timeout=600)
        self.bot, self.guild, self.owner_id = bot, guild, owner_id

    async def interaction_check(self, interaction):
        if (
            interaction.guild_id != self.guild.id
            or interaction.user.id != self.owner_id
            or not interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "Ce panneau est réservé à son administrateur.", ephemeral=True
            )
            return False
        return True


class EconomySettingsModal(discord.ui.Modal):
    def __init__(self, owner, kind, values):
        super().__init__(
            title={
                "rewards": "Récompenses",
                "jobs": "Métiers",
                "bank": "Banque",
                "rob": "Vol",
                "games": "Gains des jeux",
                "currency": "Monnaie",
            }[kind]
        )
        self.owner, self.kind = owner, kind
        self.inputs = {}
        for key, label, _ in FIELDS[kind]:
            value = values.get(key, "")
            if key == "work_cooldown":
                value = int(value) // 60
            if key == "interest_rate":
                value = float(value) * 100
            if key == "rob_fine" and value == -1:
                value = 60
            item = discord.ui.TextInput(label=label, default=str(value), max_length=60)
            self.inputs[key] = item
            self.add_item(item)

    async def on_submit(self, interaction):
        if not await self.owner.interaction_check(interaction):
            return
        try:
            values = {
                key: converter(self.inputs[key].value.strip())
                for key, _, converter in FIELDS[self.kind]
            }
            emoji = values.pop("economy_emoji", None)
            if emoji is not None and (not emoji or len(emoji) > 60):
                raise ValueError("Emoji invalide.")
            await save_economy_settings(
                self.owner.bot, self.owner.guild.id, values, interaction.user.id
            )
            if emoji is not None:
                from cogs.setup_v2_core import set_currency

                name = values["currency_name"]
                await set_currency(
                    self.owner.bot,
                    self.owner.guild.id,
                    name,
                    name,
                    emoji,
                    actor_id=interaction.user.id,
                )
        except (ValueError, TypeError, OverflowError) as exc:
            return await interaction.response.send_message(
                f"Valeur refusée : {exc}", ephemeral=True
            )
        await self.owner.refresh(interaction)


class EconomySetupView(AdminView):
    async def build(self):
        self.clear_items()
        s = await get_economy_settings(self.bot, self.guild.id)
        stats = await self.bot.db.get_stats_settings(self.guild.id)
        box = discord.ui.Container(accent_colour=GOLD)
        work_range = (
            f"{s['work_min']}–{s['work_max']}"
            if (s["work_min"], s["work_max"]) != (50, 250)
            else "selon le métier"
        )
        text = (
            f"## {icons.titre('coin', 'Économie')}\n"
            f"**État** · {'Activée' if s['enabled'] else 'Désactivée'}\n"
            f"**Monnaie** · {stats.get('economy_emoji', '')} {s['currency_name']}\n"
            f"**Récompenses** · daily {s['daily_amount']} · weekly {s['weekly_amount']}\n"
            f"**Work** · {work_range} · toutes les {int(s['work_cooldown']) // 60} min · métiers ×{s['salary_multiplier']:g}\n"
            f"**Banque** · intérêts {s['interest_rate'] * 100:g} % · plafond {s['interest_cap']}\n"
            f"**Vol** · {'Activé' if s['rob_enabled'] else 'Désactivé'} · réussite {s['rob_success']} %\n"
            f"**Boutique** · rôles et prix gérés ci-dessous\n"
            f"**Jeux reliés** · {'Gains activés' if s['games_pay'] else 'Aucun gain'} · ×{s['games_multiplier']:g}"
        )
        box.add_item(discord.ui.TextDisplay(text))
        actions = []

        async def toggle(i):
            await save_economy_settings(
                self.bot,
                self.guild.id,
                {"enabled": 0 if s["enabled"] else 1},
                i.user.id,
            )
            await self.refresh(i)

        actions.append(button("Activer / Désactiver", toggle))
        for kind, label in [
            ("currency", "Monnaie"),
            ("rewards", "Récompenses"),
            ("jobs", "Métiers"),
            ("bank", "Banque"),
            ("rob", "Vol (rob)"),
        ]:

            async def edit(i, _kind=kind):
                values = {
                    **await get_economy_settings(self.bot, self.guild.id),
                    **await self.bot.db.get_stats_settings(self.guild.id),
                }
                if _kind == "rob":
                    return await i.response.send_message(
                        view=await EconomyFeatureView(
                            self.bot, self.guild, self.owner_id, "rob"
                        ).build(),
                        ephemeral=True,
                    )
                if _kind == "jobs":
                    await i.response.send_message(
                        view=await JobsView(
                            self.bot, self.guild, self.owner_id
                        ).build(),
                        ephemeral=True,
                    )
                else:
                    await i.response.send_modal(
                        EconomySettingsModal(self, _kind, values)
                    )

            actions.append(button(label, edit))

        async def games(i):
            await i.response.send_message(
                view=await EconomyFeatureView(
                    self.bot, self.guild, self.owner_id, "games"
                ).build(),
                ephemeral=True,
            )

        async def shop(i):
            await i.response.send_message(
                view=ShopSetupView(self.bot, self.guild, self.owner_id), ephemeral=True
            )

        async def publish(i):
            await i.response.send_message(
                view=ChannelPublishView(self.bot, self.guild, self.owner_id, "economy"),
                ephemeral=True,
            )

        async def reset(i):
            await i.response.send_message(
                view=ResetEconomyView(self.bot, self.guild, self.owner_id),
                ephemeral=True,
            )

        actions.extend(
            [
                button("Jeux", games),
                button("Boutique", shop),
                button("Panneau économie", publish),
                button("Réinitialiser l'économie", reset, danger=True),
            ]
        )
        for start in range(0, len(actions), 4):
            box.add_item(discord.ui.ActionRow(*actions[start : start + 4]))
        self.add_item(box)
        return self

    async def refresh(self, interaction):
        await self.build()
        await interaction.response.edit_message(view=self)


class EconomyFeatureView(AdminView):
    def __init__(self, bot, guild, owner_id, kind):
        super().__init__(bot, guild, owner_id)
        self.kind = kind

    async def build(self):
        self.clear_items()
        s = await get_economy_settings(self.bot, self.guild.id)
        is_rob = self.kind == "rob"
        key = "rob_enabled" if is_rob else "games_pay"
        title = "Vol" if is_rob else "Jeux et récompenses"
        detail = (
            f"Réussite : {s['rob_success']} % · Amende : {s['rob_fine'] if s['rob_fine'] >= 0 else 'aléatoire'}"
            if is_rob
            else f"Multiplicateur des gains : ×{s['games_multiplier']:g}"
        )
        box = discord.ui.Container(accent_colour=GOLD)
        box.add_item(
            discord.ui.TextDisplay(
                f"## {title}\n**{'Activé' if s[key] else 'Désactivé'}**\n{detail}"
            )
        )

        async def toggle(i):
            await save_economy_settings(
                self.bot, self.guild.id, {key: 0 if s[key] else 1}, i.user.id
            )
            await self.refresh(i)

        async def settings(i):
            await i.response.send_modal(EconomySettingsModal(self, self.kind, s))

        async def back(i):
            await i.response.edit_message(
                view=await EconomySetupView(self.bot, self.guild, self.owner_id).build()
            )

        row = [
            button("Activer / Désactiver", toggle),
            button("Réglages" if is_rob else "Multiplicateur des gains", settings),
        ]
        if not is_rob:

            async def configure_games(i):
                cog = self.bot.get_cog("GamesSetup")
                if cog is None:
                    return await i.response.send_message(
                        "Réglages des jeux indisponibles.", ephemeral=True
                    )
                from cogs.games_setup import GamesSetupView

                embed, _ = await cog._build_home(self.guild.id)
                await i.response.send_message(
                    embed=embed,
                    view=GamesSetupView(
                        cog, author_id=i.user.id, guild_id=self.guild.id
                    ),
                    ephemeral=True,
                )

            row.append(button("Paramètres des jeux", configure_games))
        row.append(button("Retour économie", back))
        box.add_item(discord.ui.ActionRow(*row))
        self.add_item(box)
        return self

    async def refresh(self, interaction):
        await self.build()
        await interaction.response.edit_message(view=self)


class JobsView(AdminView):
    async def build(self):
        from utils.economy_progress import METIERS

        s = await get_economy_settings(self.bot, self.guild.id)
        box = discord.ui.Container(accent_colour=GOLD)
        box.add_item(
            discord.ui.TextDisplay(
                "## Métiers et promotions\n"
                + "\n".join(
                    f"{m.emoji} **{m.nom}** · {m.seuil} travaux · {int(m.salaire_min * s['salary_multiplier'])}–{int(m.salaire_max * s['salary_multiplier'])}"
                    for m in METIERS
                )
            )
        )

        async def edit(i):
            await i.response.send_modal(
                EconomySettingsModal(
                    EconomySetupView(self.bot, self.guild, self.owner_id), "jobs", s
                )
            )

        async def back(i):
            await i.response.edit_message(
                view=await EconomySetupView(self.bot, self.guild, self.owner_id).build()
            )

        box.add_item(
            discord.ui.ActionRow(
                button("Multiplicateur de salaire", edit),
                button("Retour économie", back),
            )
        )
        self.add_item(box)
        return self


class EconomyPublicView(discord.ui.LayoutView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        box = discord.ui.Container(accent_colour=GOLD)
        box.add_item(
            discord.ui.TextDisplay(
                "## Économie\nRécompenses, travail et boutique : vos réponses restent privées."
            )
        )
        actions = []
        for label, name in [
            ("Daily", "daily"),
            ("Work", "work"),
            ("Mon solde", "balance"),
            ("Boutique", "shop"),
            ("Classement", "economyleaderboard"),
        ]:
            item = discord.ui.Button(
                label=label, custom_id="sentrix:economy:public:" + name
            )

            async def call(i, _name=name):
                ctx = ComponentContext(self.bot, i)
                if not await enabled_or_reply(self.bot, ctx):
                    return
                cog = self.bot.get_cog("Economy")
                if cog is None:
                    return await ctx.send("Économie temporairement indisponible.")
                await i.response.defer(ephemeral=True, thinking=True)
                command = getattr(cog, _name)
                await command.callback(cog, ctx)

            item.callback = call
            actions.append(item)
        box.add_item(discord.ui.ActionRow(*actions))
        self.add_item(box)


class ChannelPublishView(AdminView):
    def __init__(self, bot, guild, owner_id, kind):
        super().__init__(bot, guild, owner_id)
        box = discord.ui.Container(accent_colour=GOLD)
        box.add_item(discord.ui.TextDisplay("### Choisissez le salon de publication"))
        picker = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text, discord.ChannelType.news]
        )

        async def choose(i):
            channel = guild.get_channel(picker.values[0].id)
            if channel is None:
                return await i.response.send_message(
                    "Salon introuvable.", ephemeral=True
                )
            perms = channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                return await i.response.send_message(
                    "SentriX doit voir le salon, envoyer des messages et intégrer des liens.",
                    ephemeral=True,
                )
            await i.response.defer(ephemeral=True, thinking=True)
            if kind == "shop":
                cog = bot.get_cog("Economy")
                await cog.shoppanel.callback(
                    cog, ComponentContext(bot, i, channel=channel)
                )
                return await i.followup.send(
                    "Panneau boutique publié dans " + channel.mention, ephemeral=True
                )
            message = await channel.send(
                view=EconomyPublicView(bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await save_economy_settings(
                bot,
                guild.id,
                {"panel_channel_id": channel.id, "panel_message_id": message.id},
                i.user.id,
            )
            await i.followup.send(
                "Panneau économie publié : " + message.jump_url, ephemeral=True
            )

        picker.callback = choose
        box.add_item(discord.ui.ActionRow(picker))

        async def back(i):
            await i.response.edit_message(
                view=await EconomySetupView(bot, guild, owner_id).build()
            )

        box.add_item(discord.ui.ActionRow(button("Retour économie", back)))
        self.add_item(box)


class ShopPriceModal(discord.ui.Modal, title="Prix du rôle"):
    price = discord.ui.TextInput(label="Prix (1 à 1000000000000)", max_length=13)

    def __init__(self, owner, action):
        super().__init__()
        self.owner, self.action = owner, action

    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        try:
            price = int(self.price.value)
        except ValueError:
            return await i.response.send_message(
                "Entrez un prix entier.", ephemeral=True
            )
        if not 1 <= price <= 1000000000000:
            return await i.response.send_message("Prix hors bornes.", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        cog = self.owner.bot.get_cog("Economy")
        ctx = ComponentContext(self.owner.bot, i)
        if self.action == "add":
            await cog.shoprole_add.callback(cog, ctx, [self.owner.role], price)
        else:
            await cog.shoprole_price.callback(cog, ctx, self.owner.role, price)


class ShopSetupView(AdminView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        self.role = None
        box = discord.ui.Container(accent_colour=GOLD)
        box.add_item(
            discord.ui.TextDisplay(
                "## Boutique\nChoisissez un rôle, puis ajoutez-le, retirez-le ou modifiez son prix."
            )
        )
        picker = discord.ui.RoleSelect(placeholder="Rôle de boutique")

        async def choose(i):
            self.role = guild.get_role(picker.values[0].id)
            await i.response.defer()

        picker.callback = choose
        box.add_item(discord.ui.ActionRow(picker))

        async def manage(i, action):
            if self.role is None:
                return await i.response.send_message(
                    "Choisissez un rôle.", ephemeral=True
                )
            if action == "remove":
                await i.response.defer(ephemeral=True, thinking=True)
                cog = bot.get_cog("Economy")
                await cog.shoprole_remove.callback(
                    cog, ComponentContext(bot, i), self.role
                )
            else:
                await i.response.send_modal(ShopPriceModal(self, action))

        async def add(i):
            await manage(i, "add")

        async def price(i):
            await manage(i, "price")

        async def remove(i):
            await manage(i, "remove")

        async def publish(i):
            await i.response.send_message(
                view=ChannelPublishView(bot, guild, owner_id, "shop"), ephemeral=True
            )

        box.add_item(
            discord.ui.ActionRow(
                button("Ajouter un rôle", add),
                button("Changer le prix", price),
                button("Retirer le rôle", remove),
                button("Publier la boutique", publish),
            )
        )

        async def back(i):
            await i.response.edit_message(
                view=await EconomySetupView(bot, guild, owner_id).build()
            )

        async def listing(i):
            cog = bot.get_cog("Economy")
            await cog.shoprole_list.callback(cog, ComponentContext(bot, i))

        box.add_item(
            discord.ui.ActionRow(
                button("Voir la boutique", listing), button("Retour économie", back)
            )
        )
        self.add_item(box)


class ResetEconomyView(AdminView):
    def __init__(self, bot, guild, owner_id):
        super().__init__(bot, guild, owner_id)
        self.done = False
        box = discord.ui.Container(accent_colour=GOLD)
        box.add_item(
            discord.ui.TextDisplay(
                "## Réinitialiser l'économie ?\nTous les soldes portefeuille et banque seront remis à zéro. L'historique d'audit est conservé."
            )
        )

        async def yes(i):
            if self.done:
                return await i.response.send_message(
                    "Confirmation déjà utilisée.", ephemeral=True
                )
            self.done = True
            await i.response.defer(ephemeral=True, thinking=True)
            cog = bot.get_cog("Economy")
            from cogs.member_data_retention_v17 import explicit_data_reset

            with explicit_data_reset():
                await cog._reset_economy_confirmed(ComponentContext(bot, i))
            self.stop()

        async def no(i):
            await i.response.edit_message(
                view=await EconomySetupView(bot, guild, owner_id).build()
            )
            self.stop()

        box.add_item(
            discord.ui.ActionRow(
                button("Oui, tout remettre à zéro", yes, danger=True),
                button("Annuler", no),
            )
        )
        self.add_item(box)
