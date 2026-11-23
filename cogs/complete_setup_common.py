"""Composants communs aux centres de configuration privés."""

from functools import wraps

import discord

from cogs.economy_setup import AdminView, button
from utils.component_context import ComponentContext


def with_actor(callback):
    @wraps(callback)
    async def traced(self, i):
        from utils.sentrix_trace import ACTOR

        token = ACTOR.set((i.user.id, "menu"))
        try:
            return await callback(self, i)
        finally:
            ACTOR.reset(token)

    return traced


class QuietConfigContext(ComponentContext):
    """Les commandes enregistrent leurs vrais réglages ; la vue confirme le lot."""

    async def send(self, content=None, **kwargs):
        return None


class CompleteView(AdminView):
    async def interaction_check(self, i):
        from cogs.setup_components_v73 import peut_configurer

        if (
            i.guild_id != self.guild.id
            or i.user.id != self.owner_id
            or not peut_configurer(i.user, self.guild)
        ):
            await i.response.send_message(
                "Ce panneau est réservé à son auteur avec Administrateur ou Gérer le serveur.",
                ephemeral=True,
            )
            return False
        return True

    def page_setup(self) -> str | None:
        """La page du /setup que ce panneau représente (pour revenir à sa section)."""
        return getattr(self, "kind", None)

    def finish(self, box):
        async def home(i):
            from cogs.setup_experience_v74 import SECTIONS, SentriXSetupV74

            await i.response.defer()
            root = SentriXSetupV74(self.bot, self.guild, self.owner_id)
            # 22/11/2026 : on revient à la SECTION de cette page (Sécurité,
            # Communauté…), pas à l'accueil — même règle que les autres pages.
            page = self.page_setup()
            section = next((s[0] for s in SECTIONS if page in s[6]), None)
            if section is not None:
                root._section = section
                root.page = f"section:{section}"
                root.backend = root._new_backend(None)
            await root.prepare()
            await i.edit_original_response(view=root, attachments=root.fichiers())

        async def close(i):
            self.clear_items()
            self.add_item(
                heading("Configuration fermée", "Relancez `/setup` pour la rouvrir.")
            )
            await i.response.edit_message(view=self)
            self.stop()

        box.add_item(discord.ui.Separator())
        box.add_item(
            discord.ui.ActionRow(
                button("Retour à /setup", home), button("Fermer", close)
            )
        )
        self.add_item(box)
        # Le premier rendu peut être intégré à la façade /setup : vérifier aussi
        # l'administrateur ici, avant toute mutation, puis conserver la vue privée.
        for item in self.walk_children():
            if isinstance(
                item,
                (
                    discord.ui.Button,
                    discord.ui.Select,
                    discord.ui.RoleSelect,
                    discord.ui.ChannelSelect,
                    discord.ui.UserSelect,
                ),
            ):
                callback = item.callback

                async def guarded(i, _callback=callback):
                    if await self.interaction_check(i):
                        from utils.sentrix_trace import ACTOR

                        token = ACTOR.set((i.user.id, "menu"))
                        try:
                            await _callback(i)
                        finally:
                            ACTOR.reset(token)

                item.callback = guarded
        # 10/11/2026 : ces centres construisent leurs TextDisplay et leurs boutons
        # directement, sans passer par Panneau ni par la vue V73 : la traduction des
        # icônes ne les atteignait jamais et ils gardaient les emojis Unicode.
        from utils import sentrix_emojis

        sentrix_emojis.appliquer_a_la_vue(self)
        return self

    async def refresh(self, i):
        if not i.response.is_done():
            await i.response.defer()
        await self.build()
        await i.edit_original_response(view=self, attachments=[])


def setting_line(box, title, description, action):
    """Une ligne lisible avec son action à droite, plutôt qu’une grille."""
    box.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(f"**{title}**\n{description}"), accessory=action
        )
    )


def heading(title, text, *, colour=None):
    box = discord.ui.Container(accent_colour=0x5865F2 if colour is None else colour)
    box.add_item(discord.ui.TextDisplay(f"## {title}\n{text}"))
    return box


__all__ = ["CompleteView", "button", "heading"]
