"""Configuration des accueils existants ; aucune modification des envois automatiques."""

from __future__ import annotations

import discord

from cogs import setup_v2_completion as engine
from cogs import setup_v2_core as core
from cogs.complete_setup_common import CompleteView, button, heading, with_actor
from utils import sentrix_emojis as icons


class WelcomeMessageModal(discord.ui.Modal):
    def __init__(self, owner, conf, presentation):
        super().__init__(
            title="Message de bienvenue"
            if owner.kind == "welcome"
            else "Message de départ"
        )
        self.owner = owner
        self.heading = None
        if owner.kind == "welcome":
            self.heading = discord.ui.TextInput(
                label="Titre", default=presentation["title"], max_length=200
            )
            self.add_item(self.heading)
        default = (
            engine.WELCOME_DEFAULT_TEXT
            if owner.kind == "welcome"
            else engine.GOODBYE_DEFAULT_TEXT
        )
        self.text = discord.ui.TextInput(
            label="Message — variables : {mention}, {server}",
            default=str(conf[owner.kind + "_message"] or default),
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.add_item(self.text)

    @with_actor
    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        await i.response.defer()
        await self.owner.bot.db.set_guild_config(
            self.owner.guild.id,
            self.owner.kind + "_message",
            self.text.value.strip() or None,
        )
        if self.heading is not None:
            p = await engine._welcome_presentation(self.owner.bot, self.owner.guild.id)
            await self.owner.presentation(
                p,
                {"title": self.heading.value.strip() or engine.WELCOME_DEFAULT_TITLE},
                i.user.id,
            )
        await self.owner.refresh(i)


class WelcomeSetupView(CompleteView):
    def __init__(self, bot, guild, owner_id, kind="welcome"):
        super().__init__(bot, guild, owner_id)
        self.kind = kind if kind in {"welcome", "goodbye"} else "welcome"
        self.options = False

    async def presentation(self, p, updates, actor):
        values = {**p, **updates}
        await engine._save_welcome_presentation(
            self.bot, self.guild.id, **values, actor_id=actor
        )

    async def build(self):
        self.clear_items()
        conf = await self.bot.db.get_guild_config(self.guild.id)
        p = await engine._welcome_presentation(self.bot, self.guild.id)
        enabled = await core.module_enabled(self.bot, self.guild.id, self.kind)
        channel = self.guild.get_channel(int(conf[self.kind + "_channel"] or 0))
        default = (
            engine.WELCOME_DEFAULT_TEXT
            if self.kind == "welcome"
            else engine.GOODBYE_DEFAULT_TEXT
        )
        message = str(conf[self.kind + "_message"] or default)
        name = "Bienvenue" if self.kind == "welcome" else "Départ"
        modekey = "mode" if self.kind == "welcome" else "goodbye_mode"
        pingkey = "ping" if self.kind == "welcome" else "goodbye_ping"
        box = heading(
            icons.titre(
                "member_join" if self.kind == "welcome" else "member_leave", name
            ),
            f"**État : {'Activé' if enabled else 'Désactivé'}**\n**Salon :** {channel.mention if channel else 'Aucun salon choisi'}\n**Format :** {'Texte simple' if p[modekey] == 'text' else 'Carte SentriX'}\n**Notification du membre :** {'Oui' if p[pingkey] else 'Non'}",
        )
        box.add_item(discord.ui.TextDisplay("### Message actuel\n" + message[:1200]))
        picker = discord.ui.ChannelSelect(
            placeholder="Salon de bienvenue"
            if self.kind == "welcome"
            else "Salon de départ",
            min_values=0,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            default_values=[channel] if channel else [],
        )

        async def choose(i):
            await i.response.defer()
            target = (
                self.guild.get_channel(picker.values[0].id) if picker.values else None
            )
            if target is not None:
                perms = target.permissions_for(self.guild.me)
                if not (perms.view_channel and perms.send_messages):
                    return await i.followup.send(
                        "SentriX doit voir ce salon et pouvoir y envoyer des messages.",
                        ephemeral=True,
                    )
            await self.bot.db.set_guild_config(
                self.guild.id, self.kind + "_channel", target.id if target else None
            )
            if target is None:
                await core.set_module_enabled(
                    self.bot, self.guild.id, self.kind, False, actor_id=i.user.id
                )
            await self.refresh(i)

        picker.callback = choose
        box.add_item(discord.ui.ActionRow(picker))
        # 10/11/2026 : ne demander que ce que SentriX ne peut pas décider seul. Un
        # serveur qui a déjà désigné son salon d'arrivée à Discord répond déjà à la
        # question : un bouton suffit, au lieu de parcourir la liste des salons.
        if channel is None:
            from utils import salons_evidents

            besoin = "bienvenue" if self.kind == "welcome" else "depart"
            propose = salons_evidents.salon_evident(self.guild, besoin)
            if propose is not None:
                async def adopter(i, cible=propose):
                    await i.response.defer()
                    await self.bot.db.set_guild_config(
                        self.guild.id, self.kind + "_channel", cible.id,
                    )
                    await core.set_module_enabled(
                        self.bot, self.guild.id, self.kind, True, actor_id=i.user.id,
                    )
                    await self.refresh(i)

                box.add_item(discord.ui.Section(
                    discord.ui.TextDisplay(
                        "### Rien à choisir\n"
                        + salons_evidents.pourquoi(self.guild, besoin, propose)
                    ),
                    accessory=button(f"Utiliser {propose.name}", adopter),
                ))
        if self.kind == "welcome":
            from cogs.control_center_v3 import WelcomeAutoRolesSelect
            from utils import config_journal, welcome_autoroles

            ids = await welcome_autoroles.configured_ids(self.bot, self.guild.id)
            autoroles = WelcomeAutoRolesSelect(
                self, "Rôles donnés à l’arrivée (5 max.)", row=None
            )
            autoroles.default_values = [
                discord.SelectDefaultValue(
                    id=v, type=discord.SelectDefaultValueType.role
                )
                for v in ids
                if self.guild.get_role(v)
            ]

            async def save_autoroles(i):
                for role in autoroles.values:
                    error = welcome_autoroles.role_problem(
                        self.guild, self.guild.get_role(role.id)
                    )
                    if error:
                        return await i.response.send_message(error, ephemeral=True)
                await i.response.defer()
                new_ids = await welcome_autoroles.save(
                    self.bot, self.guild.id, [v.id for v in autoroles.values]
                )
                await config_journal.record(
                    self.bot.db, self.guild.id, "welcome.autoroles", ids, new_ids
                )
                await self.refresh(i)

            autoroles.callback = save_autoroles
            box.add_item(discord.ui.ActionRow(autoroles))

        async def toggle(i):
            if not enabled and channel is None:
                return await i.response.send_message(
                    "Choisissez d’abord un salon.", ephemeral=True
                )
            await i.response.defer()
            await core.set_module_enabled(
                self.bot, self.guild.id, self.kind, not enabled, actor_id=i.user.id
            )
            await self.refresh(i)

        async def text(i):
            await i.response.send_modal(WelcomeMessageModal(self, conf, p))

        async def options(i):
            self.options = not self.options
            await self.refresh(i)

        box.add_item(
            discord.ui.ActionRow(
                button("Désactiver" if enabled else "Activer", toggle, danger=enabled),
                button("Modifier le message", text),
                button("Options d’affichage", options),
            )
        )
        if self.options:
            fmt = discord.ui.Select(
                placeholder="Format du message",
                options=[
                    discord.SelectOption(
                        label="Carte SentriX",
                        value="embed",
                        default=p[modekey] == "embed",
                    ),
                    discord.SelectOption(
                        label="Texte simple, sans image",
                        value="text",
                        default=p[modekey] == "text",
                    ),
                ],
            )

            async def format_cb(i):
                await i.response.defer()
                await self.presentation(p, {modekey: fmt.values[0]}, i.user.id)
                await self.refresh(i)

            fmt.callback = format_cb
            box.add_item(discord.ui.ActionRow(fmt))
            from utils.member_event_cards import EVENT_BACKGROUND_PRESETS

            background = str(conf[self.kind + "_image_url"] or "preset:sentrix")
            labels = {
                "preset:sentrix": "SentriX",
                "preset:dark": "Sombre",
                "preset:gray": "Gris",
                "preset:light": "Clair",
            }
            preset = discord.ui.Select(
                placeholder="Fond de la carte SentriX",
                disabled=p[modekey] == "text",
                options=[
                    discord.SelectOption(
                        label=labels[k], value=k, default=k == background
                    )
                    for k in EVENT_BACKGROUND_PRESETS
                ],
            )

            async def image(i):
                await i.response.defer()
                await self.bot.db.set_guild_config(
                    self.guild.id, self.kind + "_image_url", preset.values[0]
                )
                await self.refresh(i)

            preset.callback = image
            box.add_item(discord.ui.ActionRow(preset))
            controls = []
            for key, label in (
                [
                    (pingkey, "Notifier le membre"),
                    ("show_avatar", "Avatar"),
                    ("show_member_count", "Compteur de membres"),
                    ("dm", "Message privé"),
                ]
                if self.kind == "welcome"
                else [(pingkey, "Mention au départ")]
            ):

                async def switch(i, _key=key):
                    await i.response.defer()
                    await self.presentation(p, {_key: not p[_key]}, i.user.id)
                    await self.refresh(i)

                controls.append(
                    button(f"{label} : {'Oui' if p[key] else 'Non'}", switch)
                )
            box.add_item(discord.ui.ActionRow(*controls))

        async def preview(i):
            body = engine._format_welcome(message, i.user)
            title = (
                p["title"] if self.kind == "welcome" else "Un membre vient de partir"
            )
            await i.response.send_message(
                view=private_preview(engine._format_welcome(title, i.user), body),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        async def test(i):
            await i.response.defer(ephemeral=True, thinking=True)
            if self.kind == "welcome":
                ok, result = await engine._send_welcome(self.bot, i.user, test=True)
            else:
                destination = await engine._send_goodbye(self.bot, i.user, test=True)
                ok = destination is not None
                result = (
                    "Test envoyé dans " + destination.mention
                    if ok
                    else "Aucun salon de départ accessible."
                )
            await i.followup.send(result, ephemeral=True)

        async def other(i):
            self.kind = "goodbye" if self.kind == "welcome" else "welcome"
            self.options = False
            await self.refresh(i)

        box.add_item(
            discord.ui.ActionRow(
                button("Aperçu du texte en privé", preview),
                button("Envoyer un test dans le salon", test),
                button(
                    "Configurer le départ"
                    if self.kind == "welcome"
                    else "Configurer la bienvenue",
                    other,
                ),
            )
        )
        box.add_item(
            discord.ui.TextDisplay(
                "-# Variables : {mention}, {username}, {server}. Les images choisies ici sont les cartes d’accueil existantes ; aucune bannière décorative n’est ajoutée à la configuration."
            )
        )
        return self.finish(box)


def private_preview(title, text):
    view = discord.ui.LayoutView(timeout=120)
    view.add_item(heading(title, text))
    return view


async def build_welcome_page(owner, kind):
    view = await WelcomeSetupView(owner.bot, owner.guild, owner.author_id, kind).build()
    for item in list(view.children):
        view.remove_item(item)
        owner.add_item(item)
