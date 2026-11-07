"""Configuration SentriX des protections existantes, sans nouveau moteur."""

from __future__ import annotations

import discord

from cogs.complete_setup_common import CompleteView, button, heading, with_actor
from utils import config_journal, spam_sensitivity
from utils import sentrix_emojis as icons


def specs():
    from cogs.setup_v2_ui import SECURITY_CENTER_PROTECTIONS

    labels = {
        "join_gate": "Filtre des arrivées",
        "risk_engine": "Analyse des risques",
        "security_vanity": "Lien personnalisé",
        "security_prune": "Expulsions massives",
        "honeypot": "Salon piège anti-bot",
    }
    return tuple(
        (key, labels.get(key, label), group, text)
        for key, label, group, text in SECURITY_CENTER_PROTECTIONS
        if key != "antilink_strict"
    )


class SecurityLimitsModal(discord.ui.Modal):
    def __init__(self, owner, values):
        super().__init__(title="Limites de la protection")
        self.owner, self.fields = owner, {}
        definitions = (
            [
                ("messages", "Nombre de messages (3 à 20)", values.messages),
                ("seconds", "Fenêtre en secondes (3 à 30)", values.secondes),
            ]
            if owner.feature == "antispam"
            else [
                (
                    "action_threshold",
                    "Actions avant intervention (2 à 15)",
                    values["action_threshold"],
                ),
                (
                    "window_seconds",
                    "Fenêtre en secondes (5 à 120)",
                    values["window_seconds"],
                ),
            ]
        )
        for name, label, value in definitions:
            field = discord.ui.TextInput(label=label, default=str(value), max_length=6)
            self.fields[name] = field
            self.add_item(field)

    @with_actor
    async def on_submit(self, i):
        if not await self.owner.interaction_check(i):
            return
        try:
            values = {k: int(v.value) for k, v in self.fields.items()}
            spam = self.owner.feature == "antispam"
            if spam and (
                not 3 <= values["messages"] <= 20 or not 3 <= values["seconds"] <= 30
            ):
                raise ValueError("Choisissez 3 à 20 messages et 3 à 30 secondes.")
            if not spam and (
                not 2 <= values["action_threshold"] <= 15
                or not 5 <= values["window_seconds"] <= 120
            ):
                raise ValueError("Choisissez 2 à 15 actions et 5 à 120 secondes.")
        except (ValueError, TypeError) as exc:
            return await i.response.send_message(
                f"Valeurs refusées : {exc}", ephemeral=True
            )
        await i.response.defer()
        if spam:
            await spam_sensitivity.personnaliser(
                self.owner.bot,
                self.owner.guild.id,
                values["messages"],
                values["seconds"],
                i.user.id,
            )
            cog = self.owner.bot.get_cog("Automod")
            if cog is not None:
                getattr(cog, "_reglages_spam", {}).pop(self.owner.guild.id, None)
        else:
            from cogs.security_v2_runtime import set_policy

            await set_policy(
                self.owner.bot,
                self.owner.guild.id,
                threshold=values["action_threshold"],
                window=values["window_seconds"],
                updated_by=i.user.id,
            )
        await config_journal.record(
            self.owner.bot.db,
            self.owner.guild.id,
            f"security.limits.{self.owner.feature}",
            None,
            values,
        )
        await self.owner.refresh(i)


class SecurityCenterView(CompleteView):
    def __init__(self, bot, guild, owner_id, feature=None):
        super().__init__(bot, guild, owner_id)
        self.feature = feature
        self.section = "main"

    async def build(self):
        self.clear_items()
        from cogs import setup_v2_ui as policy

        if self.feature is None:
            from cogs import setup_security_choice_v75 as choices

            ready = await choices._honeypot_resources_ready(self)
            available = [
                x for x in specs() if ready or x[0] not in {"honeypot", "verification"}
            ]
            states = {
                key: (
                    await policy._security_center_state(self.bot, self.guild.id, key)
                )[0]
                for key, *_ in available
            }
            lines = []
            for group in ("Messages", "Arrivées", "Serveur", "Réponse", "Avancé"):
                entries = [x for x in available if x[2] == group]
                lines.append(
                    f"**{group}** · {sum(bool(states[x[0]]) for x in entries)}/{len(entries)} actives"
                )
            box = heading(
                icons.titre("security", "Sécurité"),
                "\n".join(lines)
                + "\n\nChoisissez une protection : état, réglages et exceptions au même endroit.",
            )
            from utils.protection_requirements import diagnostic

            perms = (
                self.guild.me.guild_permissions
                if self.guild.me
                else discord.Permissions.none()
            )
            blocked, degraded = diagnostic(perms, {k for k, v in states.items() if v})
            if blocked or degraded:
                box.add_item(
                    discord.ui.TextDisplay(
                        f"**Permissions du bot :** {len(blocked)} protection(s) inopérante(s), {len(degraded)} dégradée(s). Ouvrez la protection concernée pour le détail."
                    )
                )
            picker = discord.ui.Select(
                placeholder="Configurer une protection",
                options=[
                    discord.SelectOption(
                        label=label,
                        value=key,
                        description=f"{'Activé' if states[key] else 'Désactivé'} · {group}"[
                            :100
                        ],
                    )
                    for key, label, group, text in available
                ],
            )

            async def choose(i):
                self.feature = picker.values[0]
                self.section = "main"
                await self.refresh(i)

            picker.callback = choose
            box.add_item(discord.ui.ActionRow(picker))
            if not ready:
                box.add_item(discord.ui.TextDisplay(choices.EXTRAS_NOT_INSTALLED))

                async def install_verification(i):
                    from cogs.setup_v118_integrations import VerificationSetupView
                    from utils import sentrix_panels as panels

                    await i.response.defer(ephemeral=True, thinking=True)
                    installer = VerificationSetupView(
                        self.bot, self.guild.id, i.user.id, panneau=True
                    )
                    await panels.envoyer(
                        i.followup,
                        panels.avec_composants(
                            panels.depuis_embed(await installer.build_embed()),
                            installer,
                        ),
                        ephemere=True,
                    )

                box.add_item(
                    discord.ui.ActionRow(
                        button(
                            "Ouvrir l’installation de la vérification",
                            install_verification,
                        )
                    )
                )

            async def words(i):
                from cogs import mots_bloques

                await mots_bloques.ouvrir(i, self.guild)

            async def backups(i):
                from cogs.complete_backup_setup import BackupSetupView

                if not i.user.guild_permissions.administrator:
                    return await i.response.send_message(
                        "Les sauvegardes nécessitent la permission Administrateur.",
                        ephemeral=True,
                    )
                await i.response.defer()
                await i.edit_original_response(
                    view=await BackupSetupView(
                        self.bot, self.guild, self.owner_id
                    ).build(),
                    attachments=[],
                )

            async def exceptions(i):
                self.section = "global"
                await self.refresh(i)

            async def native(i):
                cog = self.bot.get_cog("Automod")
                if cog is None:
                    return await i.response.send_message(
                        "AutoMod indisponible.", ephemeral=True
                    )
                await i.response.defer(ephemeral=True, thinking=True)
                # La protection native existante reste celle du moteur courant.
                ok = await cog._sync_native_antieveryone_rule(self.guild)
                await i.followup.send(
                    "Protection native des mentions générales actualisée."
                    if ok
                    else "La règle native ne peut pas être activée avec les réglages ou permissions actuels. Les filtres locaux restent indépendants.",
                    ephemeral=True,
                )

            box.add_item(
                discord.ui.ActionRow(
                    button("Mots bloqués", words),
                    button("Exceptions générales", exceptions),
                    button("Sauvegardes et restauration", backups),
                )
            )
            box.add_item(
                discord.ui.ActionRow(button("Actualiser AutoMod Discord", native))
            )
            if self.section == "global":
                await self.global_exceptions(box)
            return self.finish(box)
        key, label, group, text = next(x for x in specs() if x[0] == self.feature)
        enabled, _advanced = await policy._security_center_state(
            self.bot, self.guild.id, key
        )
        box = heading(
            icons.titre("security", label),
            f"{text}\n\n**État : {'Activé' if enabled else 'Désactivé'}**",
        )
        from utils.protection_requirements import diagnostic

        perms = (
            self.guild.me.guild_permissions
            if self.guild.me
            else discord.Permissions.none()
        )
        blocked, degraded = diagnostic(perms, {key} if enabled else set())
        for _, missing in blocked:
            box.add_item(
                discord.ui.TextDisplay(
                    "**Protection inopérante :** permissions manquantes — "
                    + ", ".join(missing)
                )
            )
        for _, missing in degraded:
            box.add_item(
                discord.ui.TextDisplay(
                    "**Protection dégradée :** permissions manquantes — "
                    + ", ".join(missing)
                )
            )
        if key == "antinuke":
            from cogs.security_v2_runtime import get_policy

            limits = await get_policy(self.bot, self.guild.id)
            box.add_item(
                discord.ui.TextDisplay(
                    f"**Seuil partagé :** {limits['action_threshold']} actions en {limits['window_seconds']} s\nCouvre bans, expulsions, salons, rôles, webhooks et modifications du serveur. La restauration après attaque utilise les instantanés disponibles ; elle ne recrée pas l’historique des messages."
                )
            )
        elif key == "antispam":
            limits = (await spam_sensitivity.lire(self.bot, self.guild.id)).seuils
            box.add_item(discord.ui.TextDisplay("**Seuil :** " + limits.phrase()))
        else:
            limits = None

        if key == "antimention":
            from cogs.automod import PINGS_FENETRE, PINGS_MEME_CIBLE, PINGS_TOTAL

            box.add_item(
                discord.ui.TextDisplay(
                    f"**Seuils actuels :** {PINGS_TOTAL} mentions au total ou {PINGS_MEME_CIBLE} vers la même cible sur {PINGS_FENETRE} s. Les mentions @everyone et @here gardent leur protection native existante."
                )
            )
        elif key == "anticaps":
            from cogs.automod import CAPS_LETTRES_MIN, CAPS_RATIO

            box.add_item(
                discord.ui.TextDisplay(
                    f"**Seuil actuel :** plus de {CAPS_RATIO * 100:g} % de majuscules à partir de {CAPS_LETTRES_MIN} lettres."
                )
            )
        elif key == "antiemoji":
            box.add_item(
                discord.ui.TextDisplay(
                    "**Seuil actuel :** plus de 10 emojis dans un message."
                )
            )

        async def back(i):
            self.feature = None
            self.section = "main"
            await self.refresh(i)

        async def toggle(i):
            await i.response.defer()
            if key in {"honeypot", "verification"}:
                from cogs import setup_security_choice_v75 as choices

                chosen = await choices._selected_protections(self)
                chosen.discard(key) if enabled else chosen.add(key)
                notice = await choices._save_protections(
                    self, chosen, actor_id=i.user.id
                )
                if notice:
                    await i.followup.send(notice, ephemeral=True)
            else:
                await self.bot.db.execute(
                    "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
                    (self.guild.id,),
                )
                await self.bot.db.set_automod(self.guild.id, key, 0 if enabled else 1)
                await config_journal.record(
                    self.bot.db,
                    self.guild.id,
                    "automod." + key,
                    int(enabled),
                    int(not enabled),
                )
            await self.refresh(i)

        box.add_item(
            discord.ui.ActionRow(
                button(
                    "Désactiver" if enabled else "Activer", toggle, danger=bool(enabled)
                ),
                button("Toutes les protections", back),
            )
        )
        supports = key in policy._SECURITY_POLICY_LABELS
        if self.section == "exceptions" and supports:
            await self.filter_exceptions(box, key, policy)
        elif self.section == "sanctions":
            from cogs.automod import SPAM_FILTERS, SPAM_MUTE_DURATIONS_SECONDS

            if key in SPAM_FILTERS and key != "antimention":
                text = (
                    "Progression actuelle : rappel, avertissement enregistré, puis timeouts de "
                    + ", ".join(f"{n // 60} min" for n in SPAM_MUTE_DURATIONS_SECONDS)
                    + "."
                )
            elif key == "antiscam":
                text = "Suppression du contenu dangereux et réponse anti-arnaque du moteur actuel."
            elif key == "antimention":
                text = "Mentions générales et abus de mentions : avertissements et timeouts selon les seuils du moteur actuel."
            elif key == "antinuke":
                text = "Réponse anti-nuke actuelle : vérification de l’auteur, exemptions et hiérarchie avant neutralisation et restauration disponible."
            else:
                text = "Le filtre conserve sa réponse actuelle. L’escalade globale peut compter les récidives ; elle ne modifie pas les seuils de détection."
            conf = await self.bot.db.get_automod(self.guild.id)
            escalation = bool(conf and conf["escalation"])
            box.add_item(
                discord.ui.TextDisplay(
                    "### Sanctions en place\n"
                    + text
                    + f"\n\n**Escalade AutoMod globale :** {'Activée' if escalation else 'Désactivée'}"
                )
            )

            async def escalate(i):
                await i.response.defer()
                await self.bot.db.set_automod(
                    self.guild.id, "escalation", int(not escalation)
                )
                await config_journal.record(
                    self.bot.db,
                    self.guild.id,
                    "automod.escalation",
                    int(escalation),
                    int(not escalation),
                )
                await self.refresh(i)

            box.add_item(
                discord.ui.ActionRow(button("Modifier l’escalade globale", escalate))
            )
        else:
            row = []
            if limits is not None:

                async def edit_limits(i):
                    await i.response.send_modal(SecurityLimitsModal(self, limits))

                row.append(button("Configurer les limites", edit_limits))
            if supports or key == "antinuke":

                async def sanctions(i):
                    self.section = "sanctions"
                    await self.refresh(i)

                row.append(button("Voir et régler les sanctions", sanctions))
            if supports:

                async def exceptions(i):
                    self.section = "exceptions"
                    await self.refresh(i)

                row.append(button("Rôles et salons", exceptions))
            if row:
                box.add_item(discord.ui.ActionRow(*row))
            if key == "antiraid":
                from cogs import security_verification_v71 as v71

                cfg = await v71.settings(self.bot, self.guild.id)
                intensity = discord.ui.Select(
                    placeholder="Intensité anti-raid",
                    options=[
                        discord.SelectOption(
                            label=v, value=k, default=cfg["raid_intensity"] == k
                        )
                        for k, v in v71.RAID_LABELS.items()
                    ],
                )

                async def raid(i):
                    await i.response.defer()
                    await v71.update_setting(
                        self.bot,
                        self.guild.id,
                        "raid_intensity",
                        intensity.values[0],
                        i.user.id,
                    )
                    await self.refresh(i)

                intensity.callback = raid
                box.add_item(discord.ui.ActionRow(intensity))
            if key in {"honeypot", "verification"}:

                async def advanced_options(i):
                    from utils import sentrix_panels as panels

                    await i.response.defer(ephemeral=True, thinking=True)
                    await panels.envoyer(
                        i.followup,
                        await policy._security_policy_setup_panel(self, i.user.id, key),
                        ephemere=True,
                    )

                box.add_item(
                    discord.ui.ActionRow(
                        button("Options de vérification", advanced_options)
                    )
                )
            if key == "antinuke":

                async def whitelist(i):
                    self.section = "trusted"
                    await self.refresh(i)

                box.add_item(
                    discord.ui.ActionRow(
                        button("Membres de confiance anti-nuke", whitelist)
                    )
                )
                if self.section == "trusted":
                    await self.nuke_whitelist(box)
        if self.section not in {"main", "trusted"}:

            async def detail(i):
                self.section = "main"
                await self.refresh(i)

            box.add_item(discord.ui.ActionRow(button("Retour à la protection", detail)))
        return self.finish(box)

    async def filter_exceptions(self, box, key, policy):
        value = await policy._get_security_filter_policy(self.bot, self.guild.id, key)
        box.add_item(
            discord.ui.TextDisplay(
                "### Exceptions du filtre\nLes rôles exemptés contournent ce filtre. Les salons stricts renforcent les contrôles des autres membres, même si le salon est ignoré globalement."
            )
        )
        roles = discord.ui.RoleSelect(
            placeholder="Rôles exemptés (vide = aucun)",
            min_values=0,
            max_values=25,
            default_values=[
                discord.Object(id=v)
                for v in value["role_ids"]
                if self.guild.get_role(v)
            ],
        )
        channels = discord.ui.ChannelSelect(
            placeholder="Salons stricts (vide = aucun)",
            min_values=0,
            max_values=25,
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
                discord.ChannelType.forum,
            ],
            default_values=[
                discord.Object(id=v)
                for v in value["strict_channel_ids"]
                if self.guild.get_channel(v)
            ],
        )

        async def save_roles(i):
            if any(v.id == self.guild.id for v in roles.values):
                return await i.response.send_message(
                    "Le rôle @everyone ne peut pas exempter tout le serveur.",
                    ephemeral=True,
                )
            await i.response.defer()
            await policy._replace_security_filter_policy(
                self.bot,
                self.guild.id,
                key,
                role_ids=[v.id for v in roles.values],
                strict_channel_ids=value["strict_channel_ids"],
            )
            await config_journal.record(
                self.bot.db,
                self.guild.id,
                f"security.{key}.roles",
                value["role_ids"],
                [v.id for v in roles.values],
            )
            await self.refresh(i)

        async def save_channels(i):
            await i.response.defer()
            await policy._replace_security_filter_policy(
                self.bot,
                self.guild.id,
                key,
                role_ids=value["role_ids"],
                strict_channel_ids=[v.id for v in channels.values],
            )
            await config_journal.record(
                self.bot.db,
                self.guild.id,
                f"security.{key}.strict",
                value["strict_channel_ids"],
                [v.id for v in channels.values],
            )
            await self.refresh(i)

        roles.callback = save_roles
        channels.callback = save_channels
        box.add_item(discord.ui.ActionRow(roles))
        box.add_item(discord.ui.ActionRow(channels))

    async def global_exceptions(self, box):
        ids = [
            int(row["channel_id"])
            for row in await self.bot.db.fetchall(
                "SELECT channel_id FROM ignored_channels WHERE guild_id=?",
                (self.guild.id,),
            )
        ]
        picker = discord.ui.ChannelSelect(
            placeholder="Salons ignorés par le bot et AutoMod",
            min_values=0,
            max_values=25,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            default_values=[
                discord.Object(id=v) for v in ids[:25] if self.guild.get_channel(v)
            ],
        )

        async def save(i):
            from cogs.complete_setup_common import QuietConfigContext

            await i.response.defer()
            cog = self.bot.get_cog("Configuration")
            if cog is None:
                return await i.followup.send(
                    "Le moteur de configuration est indisponible.", ephemeral=True
                )
            chosen = {v.id for v in picker.values}
            # Un serveur peut en avoir plus de 25 : seules les entrées affichées
            # sont remplacées ; les autres restent en place.
            for ident in set(ids[:25]) | chosen:
                channel = self.guild.get_channel(ident)
                if channel is not None and ((ident in chosen) != (ident in ids)):
                    command = (
                        cog.ignorechannel if ident in chosen else cog.unignorechannel
                    )
                    await command.callback(
                        cog, QuietConfigContext(self.bot, i), channel
                    )
            await self.refresh(i)

        picker.callback = save
        box.add_item(
            discord.ui.TextDisplay(
                "### Exceptions générales\nCes salons sont ignorés par le bot et par AutoMod, sauf priorité des salons stricts."
            )
        )
        box.add_item(discord.ui.ActionRow(picker))

        cog = self.bot.get_cog("Automod")
        if cog is not None:
            role_rows = await self.bot.db.list_automod_exempt_roles(self.guild.id)
            role_ids = [int(r["role_id"]) for r in role_rows]
            role_picker = discord.ui.RoleSelect(
                placeholder="Rôles exemptés de tous les filtres",
                min_values=0,
                max_values=25,
                default_values=[
                    discord.Object(id=v)
                    for v in role_ids[:25]
                    if self.guild.get_role(v)
                ],
            )

            async def save_global_roles(i):
                if any(v.id == self.guild.id for v in role_picker.values):
                    return await i.response.send_message(
                        "Le rôle @everyone ne peut pas exempter tout le serveur.",
                        ephemeral=True,
                    )
                from cogs.complete_setup_common import QuietConfigContext

                await i.response.defer()
                chosen = {v.id for v in role_picker.values}
                for ident in set(role_ids[:25]) | chosen:
                    role = self.guild.get_role(ident)
                    if role is not None and ((ident in chosen) != (ident in role_ids)):
                        command = (
                            cog.automod_exempt_role_add
                            if ident in chosen
                            else cog.automod_exempt_role_remove
                        )
                        await command.callback(
                            cog, QuietConfigContext(self.bot, i), role
                        )
                await self.refresh(i)

            role_picker.callback = save_global_roles
            box.add_item(discord.ui.ActionRow(role_picker))
            strict = bool(await cog.admins_soumis(self.guild.id))

            async def admins(i):
                if i.user.id != self.guild.owner_id:
                    return await i.response.send_message(
                        "Seul le propriétaire du serveur peut modifier cette option.",
                        ephemeral=True,
                    )
                await i.response.defer()
                await cog.definir_admins_soumis(self.guild.id, not strict, i.user.id)
                await self.refresh(i)

            box.add_item(
                discord.ui.ActionRow(
                    button(
                        f"Sanctionner les admins : {'Oui' if strict else 'Non'}", admins
                    )
                )
            )

    async def nuke_whitelist(self, box):
        rows = await self.bot.db.fetchall(
            "SELECT user_id FROM antinuke_whitelist WHERE guild_id=?", (self.guild.id,)
        )
        ids = {int(r["user_id"]) for r in rows}
        box.add_item(
            discord.ui.TextDisplay(
                "### Membres de confiance\n"
                + (
                    ", ".join(f"<@{v}>" for v in sorted(ids))[:1500]
                    or "Aucun membre ajouté."
                )
            )
        )
        picker = discord.ui.UserSelect(
            placeholder="Membre à ajouter ou retirer", max_values=1
        )

        async def choose(i):
            from utils.component_context import ComponentContext

            await i.response.defer()
            cog = self.bot.get_cog("Automod")
            user = picker.values[0]
            command = (
                cog.antinuke_whitelist_remove
                if user.id in ids
                else cog.antinuke_whitelist_add
            )
            await command.callback(cog, ComponentContext(self.bot, i), user)
            await self.refresh(i)

        picker.callback = choose
        box.add_item(discord.ui.ActionRow(picker))


async def build_security_page(owner):
    view = await SecurityCenterView(owner.bot, owner.guild, owner.author_id).build()
    for item in list(view.children):
        view.remove_item(item)
        owner.add_item(item)
