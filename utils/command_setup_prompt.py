"""Mini-setup interactif pour les commandes + complexes.

Quand une commande de configuration reçoit des arguments manquants, SentriX ne
répond plus avec une longue ligne "Usage". Il propose un bouton Configurer,
collecte les paramètres obligatoires dans un ou plusieurs modals, convertit les
valeurs avec les convertisseurs discord.py de la vraie commande puis invoque
cette même commande.

Aucune ressource Discord n'est créée automatiquement par ce module.
"""
from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import discord
from discord.ext import commands
from discord.ext.commands.converter import run_converters

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.command-setup-prompt")

_SETUP_HINTS = (
    "setup",
    "config",
    "panel",
    "reactionrole",
    "ticket",
    "log",
    "automod",
    "whitelist",
    "blacklist",
    "notification",
    "welcome",
    "goodbye",
    "giveaway",
    "security",
    "proof",
    "invite",
    "emoji",
    "role",
)

_FAST_COMMANDS = frozenset({
    "ban",
    "unban",
    "kick",
    "mute",
    "unmute",
    "warn",
    "clear",
    "slowmode",
    "nickname",
    "resetnick",
    "giverole",
    "removerole",
    "pay",
    "deposit",
    "withdraw",
    "rob",
    "play",
    "roll",
})

_FIELD_LABELS = {
    "message_id": "ID du message",
    "message": "Message",
    "emoji": "Emoji",
    "role": "Rôle",
    "member": "Membre",
    "user": "Utilisateur",
    "channel": "Salon",
    "salon": "Salon",
    "reason": "Raison",
    "raison": "Raison",
    "duration": "Durée",
    "duree": "Durée",
    "amount": "Montant",
    "nombre": "Nombre",
    "count": "Nombre",
    "action": "Action",
    "name": "Nom",
    "url": "URL",
}

_FIELD_PLACEHOLDERS = {
    "message_id": "Ex. 123456789012345678",
    "emoji": "Ex. ✅ ou :nom:",
    "role": "@Rôle, nom ou ID",
    "member": "@Membre, nom ou ID",
    "user": "@Utilisateur, nom ou ID",
    "channel": "#salon, nom ou ID",
    "salon": "#salon, nom ou ID",
    "duration": "Ex. 10m, 2h, 1d",
    "duree": "Ex. 10m, 2h, 1d",
    "amount": "Ex. 100",
    "nombre": "Ex. 10",
    "count": "Ex. 10",
    "action": "Ex. add / remove",
}

_MAX_MODAL_FIELDS = 5
_SETUP_TIMEOUT = 180.0


def _required_params(command: commands.Command) -> list[Any]:
    result: list[Any] = []
    for param in command.clean_params.values():
        kind = getattr(param, "kind", None)
        if kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        required = getattr(param, "required", None)
        if required is None:
            required = getattr(param, "default", inspect.Parameter.empty) is inspect.Parameter.empty
        if required:
            result.append(param)
    return result


def _unsupported_param(param: Any) -> bool:
    converter = getattr(param, "converter", None)
    annotation = getattr(param, "annotation", None)
    text = f"{converter!r} {annotation!r}"
    return "Attachment" in text


def should_offer_setup(command: commands.Command | None) -> bool:
    """Vrai pour les commandes + complexes/configurables avec arguments requis."""
    if command is None:
        return False

    params = _required_params(command)
    if not params or any(_unsupported_param(param) for param in params):
        return False

    root = str(command.qualified_name or command.name).split(" ", 1)[0].casefold()
    if root in _FAST_COMMANDS:
        return False

    name = str(command.qualified_name or command.name).casefold()
    if len(params) >= 2:
        return True
    return any(hint in name for hint in _SETUP_HINTS)


def _field_label(param: Any) -> str:
    name = str(getattr(param, "name", "valeur") or "valeur")
    normalized = name.casefold()
    label = _FIELD_LABELS.get(normalized)
    if label:
        return label
    return name.replace("_", " ").replace("-", " ").strip().capitalize()[:45]


def _field_placeholder(param: Any) -> str:
    name = str(getattr(param, "name", "") or "").casefold()
    return _FIELD_PLACEHOLDERS.get(name, f"Valeur pour {name or 'ce champ'}")[:100]


def _command_label(ctx: commands.Context) -> str:
    command = ctx.command
    if command is None:
        return "commande"
    prefix = str(getattr(ctx, "clean_prefix", None) or "+")
    invoked = str(getattr(ctx, "invoked_with", "") or "").strip()
    if invoked and command.parent is None:
        return f"{prefix}{invoked}"
    return f"{prefix}{command.qualified_name}"


async def _send_setup_message(
    ctx: commands.Context,
    session: "CommandSetupSession",
) -> bool:
    token = panels.TEXTE_BRUT.set(True)
    try:
        message = await ctx.send(
            f"Configure {_command_label(ctx)} avec le bouton ci-dessous.",
            view=CommandSetupOpenView(session),
            delete_after=_SETUP_TIMEOUT,
        )
        session.prompt_message = message if isinstance(message, discord.Message) else None
        return True
    finally:
        panels.TEXTE_BRUT.reset(token)


async def offer_setup_for_missing_argument(
    ctx: commands.Context,
    error: commands.MissingRequiredArgument,
) -> bool:
    """Affiche le mini-setup si la commande s'y prête.

    Retourne True si l'erreur a été prise en charge.
    """
    command = ctx.command
    if not should_offer_setup(command):
        return False

    params = _required_params(command)
    if not params:
        return False

    session = CommandSetupSession(
        ctx=ctx,
        command=command,
        params=params,
    )
    try:
        return await _send_setup_message(ctx, session)
    except discord.HTTPException:
        logger.exception(
            "Mini-setup impossible pour +%s.",
            getattr(command, "qualified_name", "?"),
        )
        return False


@dataclass
class CommandSetupSession:
    ctx: commands.Context
    command: commands.Command
    params: list[Any]
    values: dict[str, str] = field(default_factory=dict)
    page: int = 0
    prompt_message: discord.Message | None = None

    @property
    def owner_id(self) -> int:
        return int(self.ctx.author.id)

    @property
    def page_count(self) -> int:
        return max(1, (len(self.params) + _MAX_MODAL_FIELDS - 1) // _MAX_MODAL_FIELDS)

    def params_for_page(self, page: int | None = None) -> list[Any]:
        page = self.page if page is None else max(0, int(page))
        start = page * _MAX_MODAL_FIELDS
        return self.params[start : start + _MAX_MODAL_FIELDS]

    def page_for_param(self, name: str) -> int:
        for index, param in enumerate(self.params):
            if str(getattr(param, "name", "")) == name:
                return index // _MAX_MODAL_FIELDS
        return 0

    async def convert(self, param: Any, raw: str) -> Any:
        converter = getattr(param, "converter", None)
        if converter is None:
            converter = getattr(param, "annotation", str)
        old_current = getattr(self.ctx, "current_parameter", None)
        try:
            self.ctx.current_parameter = param
            return await run_converters(self.ctx, converter, raw, param)
        finally:
            self.ctx.current_parameter = old_current

    async def execute(self, interaction: discord.Interaction) -> None:
        converted: dict[str, Any] = {}

        for param in self.params:
            name = str(getattr(param, "name", ""))
            raw = self.values.get(name, "").strip()
            try:
                converted[name] = await self.convert(param, raw)
            except commands.CommandError:
                self.page = self.page_for_param(name)
                return await interaction.response.send_message(
                    f"Valeur invalide pour `{_field_label(param)}`.",
                    view=CommandSetupRetryView(self),
                    ephemeral=True,
                )
            except Exception:
                logger.exception(
                    "Conversion setup impossible command=%s param=%s",
                    self.command.qualified_name,
                    name,
                )
                self.page = self.page_for_param(name)
                return await interaction.response.send_message(
                    f"Valeur invalide pour `{_field_label(param)}`.",
                    view=CommandSetupRetryView(self),
                    ephemeral=True,
                )

        try:
            allowed = await self.command.can_run(self.ctx)
        except commands.CommandError:
            allowed = False
        if not allowed:
            return await interaction.response.send_message(
                "Tu n'as pas la permission d'utiliser cette commande.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            positional: list[Any] = []
            keyword: dict[str, Any] = {}
            for param in self.params:
                name = str(getattr(param, "name", ""))
                value = converted[name]
                if getattr(param, "kind", None) is inspect.Parameter.POSITIONAL_ONLY:
                    positional.append(value)
                else:
                    keyword[name] = value

            await self.ctx.invoke(self.command, *positional, **keyword)
        except commands.CommandError as exc:
            logger.warning(
                "Commande setup échouée +%s : %s",
                self.command.qualified_name,
                type(exc).__name__,
            )
            return await interaction.followup.send(
                "Une erreur est survenue. Merci de réessayer.",
                ephemeral=True,
            )
        except Exception:
            logger.exception(
                "Exécution du mini-setup échouée +%s.",
                self.command.qualified_name,
            )
            return await interaction.followup.send(
                "Une erreur est survenue. Merci de réessayer.",
                ephemeral=True,
            )

        if self.prompt_message is not None:
            try:
                await self.prompt_message.edit(
                    content=f"Configuration de `{_command_label(self.ctx)}` envoyée.",
                    view=None,
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            "Configuration appliquée.",
            ephemeral=True,
        )


class _OwnedSetupView(discord.ui.View):
    def __init__(self, session: CommandSetupSession):
        super().__init__(timeout=_SETUP_TIMEOUT)
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.session.owner_id:
            return True
        await interaction.response.send_message(
            "Ce setup appartient à un autre membre.",
            ephemeral=True,
        )
        return False


class CommandSetupOpenView(_OwnedSetupView):
    @discord.ui.button(label="Configurer", style=discord.ButtonStyle.primary)
    async def configure(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        self.session.page = 0
        await interaction.response.send_modal(CommandSetupModal(self.session))


class CommandSetupRetryView(_OwnedSetupView):
    @discord.ui.button(label="Corriger", style=discord.ButtonStyle.primary)
    async def retry(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(CommandSetupModal(self.session))


class CommandSetupContinueView(_OwnedSetupView):
    @discord.ui.button(label="Continuer", style=discord.ButtonStyle.primary)
    async def continue_setup(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(CommandSetupModal(self.session))


class CommandSetupModal(discord.ui.Modal):
    def __init__(self, session: CommandSetupSession):
        self.session = session
        title = f"Configurer {session.command.name}"[:45]
        super().__init__(title=title, timeout=_SETUP_TIMEOUT)

        self._inputs: list[tuple[Any, discord.ui.TextInput]] = []
        for param in session.params_for_page():
            name = str(getattr(param, "name", ""))
            existing = session.values.get(name)
            item = discord.ui.TextInput(
                label=_field_label(param),
                placeholder=_field_placeholder(param),
                default=existing[:4000] if existing else None,
                required=True,
                max_length=4000,
            )
            self._inputs.append((param, item))
            self.add_item(item)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.session.owner_id:
            return True
        await interaction.response.send_message(
            "Ce setup appartient à un autre membre.",
            ephemeral=True,
        )
        return False

    async def on_submit(self, interaction: discord.Interaction) -> None:
        for param, item in self._inputs:
            self.session.values[str(getattr(param, "name", ""))] = str(item.value)

        if self.session.page + 1 < self.session.page_count:
            self.session.page += 1
            return await interaction.response.send_message(
                f"Étape `{self.session.page + 1}/{self.session.page_count}`.",
                view=CommandSetupContinueView(self.session),
                ephemeral=True,
            )

        await self.session.execute(interaction)
