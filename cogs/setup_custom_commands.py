"""Gestion des commandes personnalisées dans /setup, sans nouvelles commandes slash.

Toutes les opérations exigent le propriétaire du panneau de configuration
(V74.interaction_check) et réutilisent les validations du moteur existant.
"""
from __future__ import annotations

import logging
import re
import time

import discord

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-custom-commands")

VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
ROLE_KINDS = {"role_add", "role_remove", "role_temp"}
KINDS = {
    "role_add": "Ajouter un rôle",
    "role_remove": "Retirer un rôle",
    "role_temp": "Rôle temporaire",
    "money": "Ajouter de l'argent",
    "xp": "Ajouter de l'expérience",
}


def parse_action(kind: str, raw_value: str, raw_duration: str, guild: discord.Guild, active_modules: dict) -> tuple[int, int]:
    """Validation avant écriture : hiérarchie Discord, module et limites."""
    kind = str(kind)
    digits = re.sub(r"[^0-9]", "", str(raw_value or ""))
    value = int(digits) if digits else 0
    if kind in ROLE_KINDS:
        role = guild.get_role(value)
        me = guild.me
        if role is None or role.is_default() or role.managed or me is None or role >= me.top_role:
            raise ValueError("Choisissez un rôle modifiable situé sous celui de SentriX.")
        seconds = 0
        if kind == "role_temp":
            from utils.helpers import parse_duration

            seconds = parse_duration(raw_duration or "") or 0
            if not 60 <= seconds <= 90 * 86400:
                raise ValueError("La durée du rôle doit être comprise entre 1 minute et 90 jours.")
        return role.id, seconds
    if kind == "money":
        if active_modules.get("economy") != "enabled":
            raise ValueError("Le système d'économie est désactivé dans /setup.")
        if not 1 <= value <= 1_000_000:
            raise ValueError("L'argent doit être compris entre 1 et 1 000 000.")
        return value, 0
    if kind == "xp":
        if active_modules.get("levels") != "enabled":
            raise ValueError("Le système de niveaux est désactivé dans /setup.")
        if not 1 <= value <= 100_000:
            raise ValueError("L'expérience doit être comprise entre 1 et 100 000.")
        return value, 0
    raise ValueError("Type d'action inconnu.")


async def notify(interaction: discord.Interaction, message: str) -> None:
    await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def selected_row(shell):
    name = getattr(shell, "custom_selected_name", "")
    if not name:
        return None
    return await shell.bot.db.fetchone(
        "SELECT * FROM platform_custom_commands WHERE guild_id=? AND name=?",
        (shell.guild.id, name),
    )


class CommandTextModal(discord.ui.Modal):
    nom = discord.ui.TextInput(label="Nom de la commande", min_length=2, max_length=32, placeholder="bienvenue")
    texte = discord.ui.TextInput(label="Message envoyé par le bot", style=discord.TextStyle.paragraph,
                                 min_length=1, max_length=1850, placeholder="Bienvenue {user} !")

    def __init__(self, shell, row=None):
        super().__init__(title="Modifier la commande" if row else "Créer une commande")
        self.shell = shell
        self.existing = row
        if row:
            self.nom.default = str(row["name"])
            self.nom.label = "Nom (conservé lors de la modification)"
            self.texte.default = str(row["response"])

    async def on_submit(self, interaction: discord.Interaction):
        # Les actions sont indexées par (guild_id, name). La modification du
        # message ne renomme donc jamais la commande et ne perd pas ses actions.
        name = (str(self.existing["name"]) if self.existing else str(self.nom.value or "")).strip().casefold()
        if not VALID_NAME.fullmatch(name):
            return await notify(interaction, "Nom invalide : 2 à 32 lettres, chiffres, tirets ou underscores.")
        platform = self.shell.bot.get_cog("PlatformV4")
        if platform is None:
            return await notify(interaction, "Le moteur de commandes personnalisées n'est pas disponible.")
        try:
            saved = await platform.save_custom_command(
                self.shell.guild, interaction.user.id,
                {"id": int(self.existing["id"]) if self.existing else 0,
                 "name": name, "response": str(self.texte.value or "")},
            )
        except ValueError as exc:
            return await notify(interaction, f"Commande refusée : {exc}")
        self.shell.custom_selected_name = str(saved["name"])
        await notify(interaction, "Commande enregistrée. Sélectionnez une action dans le panneau ou actualisez-le.")


class PrefixModal(discord.ui.Modal, title="Préfixe des commandes personnalisées"):
    prefixe = discord.ui.TextInput(label="Préfixe", placeholder="!", min_length=1, max_length=3)

    def __init__(self, shell):
        super().__init__()
        self.shell = shell

    async def on_submit(self, interaction: discord.Interaction):
        value = str(self.prefixe.value or "").strip()
        if not value or value.startswith("/") or any(ch.isspace() for ch in value):
            return await notify(interaction, "Préfixe invalide : 1 à 3 caractères, sans espaces ni slash.")
        await self.shell.bot.db.set_guild_config(self.shell.guild.id, "prefix", value)
        await notify(interaction, "Préfixe enregistré. Actualisez le panneau pour voir la nouvelle valeur.")


class ActionModal(discord.ui.Modal):
    valeur = discord.ui.TextInput(label="Rôle (mention/ID) ou montant", placeholder="123456789 ou 100", max_length=40)
    duree = discord.ui.TextInput(label="Durée du rôle temporaire (si concerné)", required=False,
                                 max_length=20, placeholder="1h, 7d")

    def __init__(self, shell, name: str, kind: str, module_states: dict):
        super().__init__(title=KINDS[kind])
        self.shell, self.name, self.kind, self.states = shell, name, kind, module_states

    async def on_submit(self, interaction: discord.Interaction):
        row = await self.shell.bot.db.fetchone(
            "SELECT name FROM platform_custom_commands WHERE guild_id=? AND name=?",
            (self.shell.guild.id, self.name),
        )
        if not row:
            return await notify(interaction, "Cette commande a été supprimée.")
        from cogs.custom_commands import actions_de, MAX_ACTIONS
        actions = await actions_de(self.shell.bot.db, self.shell.guild.id, self.name)
        if len(actions) >= MAX_ACTIONS:
            return await notify(interaction, "Limite de 10 actions par commande atteinte.")
        try:
            value, seconds = parse_action(
                self.kind, str(self.valeur.value or ""), str(self.duree.value or ""),
                self.shell.guild, self.states,
            )
        except ValueError as exc:
            return await notify(interaction, str(exc))
        await self.shell.bot.db.execute(
            "INSERT INTO custom_command_actions(guild_id,name,kind,value,duration_s) VALUES(?,?,?,?,?)",
            (self.shell.guild.id, self.name, self.kind, value, seconds),
        )
        await notify(interaction, "Action ajoutée. Vous pouvez en ajouter une autre ou actualiser le panneau.")


async def build_page(shell) -> None:
    from cogs import setup_components_v73 as v73, setup_control_center as setup_ui
    from cogs.custom_commands import actions_de, supprimer_declencheur, decrire

    guild_id = shell.guild.id
    conf = await shell.bot.db.get_guild_config(guild_id)
    prefix = str(conf["prefix"] if conf and conf["prefix"] else "+")
    delete_trigger = await supprimer_declencheur(shell.bot.db, guild_id)
    rows = list(await shell.bot.db.fetchall(
        "SELECT id,name,response FROM platform_custom_commands WHERE guild_id=? ORDER BY name LIMIT 25",
        (guild_id,),
    ))
    selected = await selected_row(shell)
    if selected is None and rows:
        shell.custom_selected_name = str(rows[0]["name"])
        selected = await selected_row(shell)
    elif selected is None:
        shell.custom_selected_name = ""

    container = discord.ui.Container()
    v73.poser_banniere(container)
    container.add_item(discord.ui.TextDisplay(
        "# Commandes personnalisées\n"
        "Créez des commandes pour votre communauté, avec des messages et des actions.\n"
        f"**Préfixe :** {prefix} · **Commandes :** {len(rows)}\n"
        "**Supprimer le déclencheur :** " + ("Activé" if delete_trigger else "Désactivé")
    ))
    container.add_item(discord.ui.Separator())
    if rows:
        options = [discord.SelectOption(label=str(row["name"]), value=str(row["name"]),
                                        description=str(row["response"]).replace("\n", " ")[:80])
                   for row in rows]
        picker = discord.ui.Select(placeholder="Choisir une commande à gérer", options=options)

        async def choose(interaction: discord.Interaction):
            shell.custom_selected_name = picker.values[0]
            await shell.refresh(interaction)

        picker.callback = choose
        container.add_item(discord.ui.ActionRow(picker))

    if selected:
        from cogs import custom_commands
        action_rows = await actions_de(shell.bot.db, guild_id, str(selected["name"]))
        details = "\n".join(
            f"{i}. {decrire(action)}" for i, action in enumerate(action_rows, 1)
        ) or "Aucune action ajoutée."
        container.add_item(discord.ui.TextDisplay(
            f"### {prefix}{selected['name']}\n"
            f"**Message :** {str(selected['response'])[:250]}\n"
            f"**Actions ({len(action_rows)}/10) :**\n{details[:1300]}"
        ))
    else:
        container.add_item(discord.ui.TextDisplay("Aucune commande. Choisissez **Créer**."))

    create_button = discord.ui.Button(label="Créer", style=discord.ButtonStyle.primary)
    edit_button = discord.ui.Button(label="Modifier", style=discord.ButtonStyle.secondary,
                                    disabled=selected is None)
    delete_button = discord.ui.Button(label="Supprimer", style=discord.ButtonStyle.danger,
                                      disabled=selected is None)

    async def create(interaction):
        await interaction.response.send_modal(CommandTextModal(shell))

    async def edit(interaction):
        row = await selected_row(shell)
        if row is None:
            return await notify(interaction, "Sélectionnez d'abord une commande.")
        await interaction.response.send_modal(CommandTextModal(shell, row))

    async def delete(interaction):
        row = await selected_row(shell)
        if row is None:
            return await notify(interaction, "Sélectionnez une commande.")
        confirm_view = discord.ui.View(timeout=60)
        confirm = discord.ui.Button(label="Confirmer la suppression", style=discord.ButtonStyle.danger)

        async def perform(i):
            if i.user.id != shell.author_id:
                return await notify(i, "Cette confirmation ne vous appartient pas.")
            platform = shell.bot.get_cog("PlatformV4")
            if platform is None:
                return await notify(i, "Moteur indisponible.")
            await platform.delete_custom_command(guild_id, i.user.id, int(row["id"]))
            await shell.bot.db.execute(
                "DELETE FROM custom_command_actions WHERE guild_id=? AND name=?",
                (guild_id, str(row["name"])),
            )
            shell.custom_selected_name = ""
            await i.response.edit_message(content="Commande supprimée.", view=None,
                                          allowed_mentions=discord.AllowedMentions.none())
        confirm.callback = perform
        confirm_view.add_item(confirm)
        await interaction.response.send_message(
            f"Supprimer définitivement la commande **{row['name']}** ?",
            ephemeral=True, view=confirm_view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    create_button.callback = create
    edit_button.callback = edit
    delete_button.callback = delete
    container.add_item(discord.ui.ActionRow(create_button, edit_button, delete_button))

    module_states = await setup_ui.module_switch_states(shell.bot, guild_id)
    if selected:
        options = [discord.SelectOption(label=label, value=kind)
                   for kind, label in KINDS.items()]
        action_picker = discord.ui.Select(
            placeholder="Ajouter une action à la commande",
            options=options,
            disabled=len(action_rows) >= 10,
        )

        async def action(interaction):
            kind = action_picker.values[0]
            if kind in {"money", "xp"}:
                required = "economy" if kind == "money" else "levels"
                if module_states.get(required) != "enabled":
                    return await notify(interaction,
                                        "Activez d'abord le système d'économie ou de niveaux dans /setup.")
            await interaction.response.send_modal(
                ActionModal(shell, str(selected["name"]), kind, module_states),
            )
        action_picker.callback = action
        container.add_item(discord.ui.ActionRow(action_picker))

        clear_actions = discord.ui.Button(
            label="Retirer toutes les actions",
            style=discord.ButtonStyle.secondary, disabled=not action_rows,
        )
        async def clear(interaction):
            await shell.bot.db.execute(
                "DELETE FROM custom_command_actions WHERE guild_id=? AND name=?",
                (guild_id, str(selected["name"])),
            )
            await shell.refresh(interaction)
        clear_actions.callback = clear
        container.add_item(discord.ui.ActionRow(clear_actions))

    prefix_button = discord.ui.Button(label="Préfixe", style=discord.ButtonStyle.secondary)
    trigger_button = discord.ui.Button(
        label="Suppression du déclencheur : " + ("ON" if delete_trigger else "OFF"),
        style=discord.ButtonStyle.secondary,
    )
    reset_button = discord.ui.Button(label="Réinitialiser les commandes", style=discord.ButtonStyle.danger)

    async def change_prefix(interaction):
        await interaction.response.send_modal(PrefixModal(shell))

    async def toggle_trigger(interaction):
        await shell.bot.db.execute(
            "INSERT INTO custom_command_settings(guild_id,delete_trigger) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET delete_trigger=excluded.delete_trigger",
            (guild_id, int(not delete_trigger)),
        )
        await shell.refresh(interaction)

    async def reset(interaction):
        confirm_view = discord.ui.View(timeout=60)
        confirm = discord.ui.Button(label="Tout supprimer définitivement", style=discord.ButtonStyle.danger)

        async def perform(i):
            if i.user.id != shell.author_id:
                return await notify(i, "Cette confirmation ne vous appartient pas.")
            await shell.bot.db.execute("DELETE FROM custom_command_actions WHERE guild_id=?", (guild_id,))
            await shell.bot.db.execute("DELETE FROM platform_custom_commands WHERE guild_id=?", (guild_id,))
            shell.custom_selected_name = ""
            await i.response.edit_message(
                content="Les commandes personnalisées de ce serveur ont été réinitialisées.",
                view=None, allowed_mentions=discord.AllowedMentions.none(),
            )
        confirm.callback = perform
        confirm_view.add_item(confirm)
        await interaction.response.send_message(
            "Cette action supprime **toutes** les commandes personnalisées du serveur. Confirmer ?",
            view=confirm_view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    prefix_button.callback = change_prefix
    trigger_button.callback = toggle_trigger
    reset_button.callback = reset
    container.add_item(discord.ui.ActionRow(prefix_button, trigger_button))
    container.add_item(discord.ui.ActionRow(reset_button))

    shell._add_navigation(container)
    shell.add_item(container)
