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
                 "name": name, "response": str(self.texte.value or ""),
                 "embed_title": str(self.existing["embed_title"]) if self.existing else "",
                 "embed_color": int(self.existing["embed_color"]) if self.existing else 0x6C57CC,
                 "ping_role_id": int(self.existing["ping_role_id"]) if self.existing else 0,
                 "enabled": bool(self.existing["enabled"]) if self.existing else True},
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
        # Éviter le cache périmé : + reste actif dans tous les cas.
        self.shell.bot.prefix_cache[self.shell.guild.id] = value
        await notify(interaction, "Préfixe personnalisé enregistré. Le préfixe + reste disponible.")


async def enregistrer_action(shell, name: str, kind: str, value: int, seconds: int) -> None:
    """Stockage partagé par le formulaire numérique et le sélecteur de rôles."""
    row = await shell.bot.db.fetchone(
        "SELECT name FROM platform_custom_commands WHERE guild_id=? AND name=?",
        (shell.guild.id, name),
    )
    if not row:
        raise ValueError("Cette commande a été supprimée.")
    from cogs.custom_commands import actions_de, MAX_ACTIONS
    actions = await actions_de(shell.bot.db, shell.guild.id, name)
    if len(actions) >= MAX_ACTIONS:
        raise ValueError("Limite de 10 actions par commande atteinte.")
    await shell.bot.db.execute(
        "INSERT INTO custom_command_actions(guild_id,name,kind,value,duration_s) VALUES(?,?,?,?,?)",
        (shell.guild.id, name, kind, value, seconds),
    )


class ActionModal(discord.ui.Modal):
    """Argent et expérience : aucun champ rôle inutile."""
    def __init__(self, shell, name: str, kind: str, module_states: dict):
        super().__init__(title=KINDS[kind])
        self.shell, self.name, self.kind, self.states = shell, name, kind, module_states
        self.valeur = discord.ui.TextInput(
            label="Montant" if kind == "money" else "Points d'expérience",
            placeholder="Exemple : 100", max_length=9,
            min_length=1,
        )
        self.add_item(self.valeur)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value, seconds = parse_action(
                self.kind, str(self.valeur.value or ""), "",
                self.shell.guild, self.states,
            )
            await enregistrer_action(self.shell, self.name, self.kind, value, seconds)
        except ValueError as exc:
            return await notify(interaction, str(exc))
        await notify(interaction, "Action ajoutée. Actualise le panneau pour la voir.")


class DureeRoleModal(discord.ui.Modal, title="Durée du rôle temporaire"):
    def __init__(self, shell, name: str, role_id: int, states: dict):
        super().__init__()
        self.shell, self.name, self.role_id, self.states = shell, name, role_id, states
        self.duree = discord.ui.TextInput(
            label="Durée", placeholder="10m, 1h ou 7d", max_length=20,
        )
        self.add_item(self.duree)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value, seconds = parse_action(
                "role_temp", str(self.role_id), str(self.duree.value),
                self.shell.guild, self.states,
            )
            await enregistrer_action(self.shell, self.name, "role_temp", value, seconds)
        except ValueError as exc:
            return await notify(interaction, str(exc))
        await notify(interaction, "Rôle temporaire ajouté à la commande.")


class ChoisirRoleAction(discord.ui.View):
    """Le menu natif Discord présente les vrais rôles sans demander d'ID."""
    def __init__(self, shell, name: str, kind: str, states: dict):
        super().__init__(timeout=180)
        self.shell, self.name, self.kind, self.states = shell, name, kind, states
        select = discord.ui.RoleSelect(
            placeholder="Choisir le rôle à ajouter ou retirer…",
            min_values=1, max_values=1,
        )

        async def selection(interaction: discord.Interaction):
            if interaction.user.id != shell.author_id:
                return await notify(interaction, "Seul l'auteur du panneau peut choisir un rôle.")
            role = select.values[0]
            if kind == "role_temp":
                return await interaction.response.send_modal(
                    DureeRoleModal(shell, name, role.id, states)
                )
            try:
                value, seconds = parse_action(
                    kind, str(role.id), "", shell.guild, states,
                )
                await enregistrer_action(shell, name, kind, value, seconds)
            except ValueError as exc:
                return await notify(interaction, str(exc))
            return await notify(interaction, f"Action enregistrée pour {role.mention}.")

        select.callback = selection
        self.add_item(select)


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
            f"**Format :** {'Embed Discord' if selected['embed_title'] else 'Texte simple'}\n"
            f"**Ping :** {(shell.guild.get_role(int(selected['ping_role_id'])).mention if selected['ping_role_id'] and shell.guild.get_role(int(selected['ping_role_id'])) else 'Aucun')}\n"
            f"**Message :** {str(selected['response'])[:250]}\n\n"
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
            if kind in ROLE_KINDS:
                return await interaction.response.send_message(
                    "Choisis un rôle ci-dessous. SentriX vérifie les permissions avant l'enregistrement.",
                    view=ChoisirRoleAction(
                        shell, str(selected["name"]), kind, module_states,
                    ),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
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

    # Le modèle platform_custom_commands dispose déjà de embed_title et
    # embed_color : aucune migration, aucun nouveau message de configuration.
    format_button = discord.ui.Button(
        label=("Mode : embed" if selected and selected["embed_title"] else "Mode : texte"),
        style=discord.ButtonStyle.secondary, disabled=selected is None,
    )

    async def toggle_format(interaction):
        row = await selected_row(shell)
        if row is None:
            return await notify(interaction, "Choisis d'abord une commande.")
        platform = shell.bot.get_cog("PlatformV4")
        if platform is None:
            return await notify(interaction, "Créateur de commandes indisponible.")
        try:
            await platform.save_custom_command(
                shell.guild, interaction.user.id,
                {
                    "id": row["id"], "name": row["name"],
                    "response": row["response"],
                    "embed_title": "" if row["embed_title"] else row["name"].capitalize(),
                    "embed_color": row["embed_color"],
                    "ping_role_id": row["ping_role_id"],
                    "enabled": bool(row["enabled"]),
                },
            )
        except ValueError as exc:
            return await notify(interaction, str(exc))
        await shell.refresh(interaction)

    format_button.callback = toggle_format
    container.add_item(discord.ui.ActionRow(format_button))

    # RoleSelect affiche les rôles existants, sans demander aux admins de
    # chercher un ID dans le mode développeur. Le ping reste OFF par défaut.
    if selected:
        ping_select = discord.ui.RoleSelect(
            placeholder="Rôle à mentionner (facultatif)",
            min_values=0, max_values=1,
        )

        async def change_ping(interaction):
            if interaction.user.id != shell.author_id:
                return await notify(interaction, "Ce panneau ne t'appartient pas.")
            row = await selected_row(shell)
            if row is None:
                return await notify(interaction, "Commande supprimée.")
            new_role = ping_select.values[0] if ping_select.values else None
            platform = shell.bot.get_cog("PlatformV4")
            if platform is None:
                return await notify(interaction, "Moteur indisponible.")
            try:
                await platform.save_custom_command(
                    shell.guild, interaction.user.id,
                    {
                        "id": row["id"], "name": row["name"], "response": row["response"],
                        "embed_title": row["embed_title"], "embed_color": row["embed_color"],
                        "ping_role_id": new_role.id if new_role is not None else 0,
                        "enabled": bool(row["enabled"]),
                    },
                )
            except ValueError as exc:
                return await notify(interaction, str(exc))
            await shell.refresh(interaction)

        ping_select.callback = change_ping
        container.add_item(discord.ui.ActionRow(ping_select))

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
