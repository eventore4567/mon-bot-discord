"""Rôle de ping dédié aux tickets + intégration sûre dans +setup.

Le rôle qui reçoit la mention à l'ouverture est séparé du rôle staff qui possède les
permissions du salon. Les anciens types restent compatibles : sans rôle de ping dédié,
SentriX utilise le rôle staff comme repli.
"""

from __future__ import annotations

import logging

import discord

from database.db import now
from utils import embeds, helpers, design_system

logger = logging.getLogger("bot.ticket-ping-role")
_SCHEMA_READY = False
_SETUP_PATCHED = False
_TICKETS_PATCHED = False


def _row_value(row, key: str, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


async def _ensure_schema(bot) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    rows = await bot.db.fetchall("PRAGMA table_info(ticket_types)")
    names = set()
    for row in rows:
        try:
            names.add(row["name"])
        except (KeyError, IndexError, TypeError):
            names.add(row[1])
    if "ping_role_id" not in names:
        await bot.db.execute("ALTER TABLE ticket_types ADD COLUMN ping_role_id INTEGER")
        logger.info("Colonne ticket_types.ping_role_id ajoutée.")
    _SCHEMA_READY = True


async def _create_ticket_with_ping(self, interaction: discord.Interaction, ticket_type, answers: list):
    """Copie ciblée de Tickets.create_ticket avec uniquement le rôle de mention séparé."""
    from cogs.tickets import format_channel_name, get_button_settings, TicketControlView

    guild = interaction.guild
    user = interaction.user

    count_row = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ?", (guild.id,))
    number = (count_row["c"] or 0) + 1
    channel_name = format_channel_name(ticket_type["name_format"], user, number)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True
        ),
    }
    staff_role_id = _row_value(ticket_type, "staff_role_id")
    staff_role = guild.get_role(staff_role_id) if staff_role_id else None
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    category_id = _row_value(ticket_type, "category_id")
    category = guild.get_channel(category_id) if category_id else None
    category = category if isinstance(category, discord.CategoryChannel) else None

    try:
        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            category=category,
            reason=f"Ticket « {ticket_type['name']} » ouvert par {user}",
        )
    except discord.HTTPException:
        return await interaction.followup.send(
            embed=embeds.error("Impossible de créer le salon (permissions du bot ou catégorie pleine)."),
            ephemeral=True,
        )

    cur = await self.bot.db.execute(
        "INSERT INTO tickets (guild_id, channel_id, user_id, status, category, type_id, priority, created_at, last_activity_at) "
        "VALUES (?, ?, ?, 'ouvert', ?, ?, 'normale', ?, ?)",
        (guild.id, channel.id, user.id, ticket_type["name"], ticket_type["id"], now(), now()),
    )
    ticket_id = cur.lastrowid
    for label, value in answers:
        if value:
            await self.bot.db.execute(
                "INSERT INTO ticket_answers (ticket_id, question_label, answer) VALUES (?, ?, ?)",
                (ticket_id, label, value[:1000]),
            )

    style = design_system.CATEGORY_STYLES["tickets"]
    e = design_system.create_embed(
        title=f"{ticket_type['emoji'] or style['emoji']} {ticket_type['name']} — Ticket #{number}",
        description=ticket_type["open_message"] or f"Bonjour {user.mention}, le staff vous répondra bientôt.",
        colour=style["colour"],
        user=user,
        thumbnail=user.display_avatar.url,
        footer="SentriX",
    )
    e.add_field(name="👤 Ouvert par", value=user.mention, inline=True)
    e.add_field(name="📂 Type", value=ticket_type["name"], inline=True)
    for label, value in answers:
        if value:
            e.add_field(name=label[:256], value=helpers.truncate(value, 1024), inline=False)

    button_settings = await get_button_settings(self.bot, guild.id)
    content = user.mention
    ping_role_id = _row_value(ticket_type, "ping_role_id")
    ping_role = guild.get_role(ping_role_id) if ping_role_id else staff_role
    if _row_value(ticket_type, "mention_staff", 0) and ping_role:
        content += f" {ping_role.mention}"

    await channel.send(content=content, embed=e, view=TicketControlView(button_settings))
    await interaction.followup.send(
        embed=embeds.success(f"Votre ticket a été créé : {channel.mention}"), ephemeral=True
    )

    log_e = embeds.log_entry(
        "🎫 Ticket ouvert",
        0x5865F2,
        cible=user,
        extra={"📂 Type": ticket_type["name"], "📌 Salon": channel.mention, "🔢 Numéro": f"#{number}"},
    )
    await self.log_action(guild, log_e, _row_value(ticket_type, "log_channel_id"))


class TicketPingSetupView(discord.ui.View):
    def __init__(self, bot, guild: discord.Guild, author_id: int, rows):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.author_id = author_id
        self.types = {int(row["id"]): dict(row) for row in rows}
        self.selected_type_id: int | None = None

        options = []
        for item in list(self.types.values())[:25]:
            panel = item.get("panel_name") or "Panel"
            options.append(
                discord.SelectOption(
                    label=str(item.get("name") or "Ticket")[:100],
                    value=str(item["id"]),
                    description=f"{panel} • type #{item['id']}"[:100],
                )
            )
        type_select = discord.ui.Select(
            placeholder="🎫 Choisir le type de ticket",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        type_select.callback = self._select_type
        self.add_item(type_select)

        role_select = discord.ui.RoleSelect(
            placeholder="🔔 Choisir le rôle à ping",
            min_values=1,
            max_values=1,
            row=1,
        )
        role_select.callback = self._select_role
        self.add_item(role_select)

        disable = discord.ui.Button(label="🔕 Désactiver le ping", style=discord.ButtonStyle.secondary, row=2)
        disable.callback = self._disable_ping
        self.add_item(disable)

        fallback = discord.ui.Button(label="🛡️ Utiliser le rôle staff", style=discord.ButtonStyle.secondary, row=2)
        fallback.callback = self._use_staff_role
        self.add_item(fallback)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce réglage appartient à une autre session +setup.", ephemeral=True)
            return False
        return True

    def _current(self):
        return self.types.get(self.selected_type_id) if self.selected_type_id else None

    def build_embed(self) -> discord.Embed:
        e = discord.Embed(
            title="🔔 Rôle ping à l'ouverture des tickets",
            description=(
                "Choisissez d'abord un **type de ticket**, puis le **rôle à mentionner**.\n"
                "Le rôle ping est indépendant du rôle staff qui possède l'accès au salon."
            ),
            color=0x7C5CFC,
        )
        item = self._current()
        if not item:
            e.add_field(name="Étape 1", value="Sélectionnez un type de ticket dans le menu.", inline=False)
            return e
        explicit_id = item.get("ping_role_id")
        staff_id = item.get("staff_role_id")
        effective_id = explicit_id or staff_id
        role = self.guild.get_role(int(effective_id)) if effective_id else None
        enabled = bool(item.get("mention_staff"))
        source = "rôle ping dédié" if explicit_id else "rôle staff (repli)"
        e.add_field(name="🎫 Type", value=str(item.get("name") or "Ticket"), inline=True)
        e.add_field(name="🔔 Ping", value="● Activé" if enabled else "○ Désactivé", inline=True)
        e.add_field(
            name="👥 Rôle actuellement mentionné",
            value=f"{role.mention} — {source}" if role else "*Aucun rôle défini*",
            inline=False,
        )
        return e

    async def _select_type(self, interaction: discord.Interaction):
        select = interaction.data.get("values", []) if interaction.data else []
        if not select:
            return
        self.selected_type_id = int(select[0])
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _select_role(self, interaction: discord.Interaction):
        if not self.selected_type_id:
            return await interaction.response.send_message("Choisissez d'abord un type de ticket.", ephemeral=True)
        select = next((child for child in self.children if isinstance(child, discord.ui.RoleSelect)), None)
        if not select or not select.values:
            return await interaction.response.send_message("Aucun rôle sélectionné.", ephemeral=True)
        role = select.values[0]
        if role.id == interaction.guild.default_role.id:
            return await interaction.response.send_message("`@everyone` ne peut pas être utilisé pour ce ping.", ephemeral=True)
        await self.bot.db.execute(
            "UPDATE ticket_types SET ping_role_id = ?, mention_staff = 1 WHERE id = ? AND guild_id = ?",
            (role.id, self.selected_type_id, self.guild.id),
        )
        item = self.types[self.selected_type_id]
        item["ping_role_id"] = role.id
        item["mention_staff"] = 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _disable_ping(self, interaction: discord.Interaction):
        if not self.selected_type_id:
            return await interaction.response.send_message("Choisissez d'abord un type de ticket.", ephemeral=True)
        await self.bot.db.execute(
            "UPDATE ticket_types SET mention_staff = 0 WHERE id = ? AND guild_id = ?",
            (self.selected_type_id, self.guild.id),
        )
        self.types[self.selected_type_id]["mention_staff"] = 0
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _use_staff_role(self, interaction: discord.Interaction):
        if not self.selected_type_id:
            return await interaction.response.send_message("Choisissez d'abord un type de ticket.", ephemeral=True)
        await self.bot.db.execute(
            "UPDATE ticket_types SET ping_role_id = NULL, mention_staff = 1 WHERE id = ? AND guild_id = ?",
            (self.selected_type_id, self.guild.id),
        )
        item = self.types[self.selected_type_id]
        item["ping_role_id"] = None
        item["mention_staff"] = 1
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


def _patch_setup(bot) -> None:
    global _SETUP_PATCHED
    if _SETUP_PATCHED:
        return
    try:
        from cogs import configuration
    except Exception:
        return

    original = configuration.SetupView.render_page
    if getattr(original, "_sentrix_ticket_ping_patch", False):
        _SETUP_PATCHED = True
        return

    def render_page(self):
        original(self)
        if self.page < 0:
            return
        try:
            step = configuration.SETUP_STEPS[self.page]
        except (IndexError, TypeError):
            return
        if step.get("key") != "tickets":
            return
        button = discord.ui.Button(
            label="🔔 Rôle ping à l'ouverture",
            style=discord.ButtonStyle.secondary,
            row=0,
        )

        async def callback(interaction: discord.Interaction):
            rows = await self.bot.db.fetchall(
                "SELECT tt.id, tt.name, tt.staff_role_id, tt.ping_role_id, tt.mention_staff, "
                "p.name AS panel_name FROM ticket_types tt "
                "LEFT JOIN ticket_panels_v2 p ON p.id = tt.panel_id "
                "WHERE tt.guild_id = ? ORDER BY p.id, tt.position, tt.id",
                (self.guild_id,),
            )
            if not rows:
                return await interaction.response.send_message(
                    embed=embeds.warning(
                        "Créez d'abord au moins un type de ticket avec `+ticketsetup`, puis revenez ici."
                    ),
                    ephemeral=True,
                )
            view = TicketPingSetupView(self.bot, interaction.guild, interaction.user.id, rows)
            await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

        button.callback = callback
        self.add_item(button)

    render_page._sentrix_ticket_ping_patch = True
    configuration.SetupView.render_page = render_page
    _SETUP_PATCHED = True
    logger.info("Sélecteur de rôle ping ajouté à +setup > Tickets.")


def _patch_tickets(bot) -> None:
    global _TICKETS_PATCHED
    if _TICKETS_PATCHED:
        return
    cog = bot.get_cog("Tickets")
    if cog is None:
        return
    cls = type(cog)
    if not getattr(cls, "_sentrix_ticket_ping_patch", False):
        cls.create_ticket = _create_ticket_with_ping
        cls._sentrix_ticket_ping_patch = True
    _TICKETS_PATCHED = True
    logger.info("Rôle ping dédié appliqué à l'ouverture des tickets.")


async def install(bot) -> None:
    await _ensure_schema(bot)
    _patch_setup(bot)
    _patch_tickets(bot)
