"""Compact, private Components V2 AutoMod and security-log panels for SentriX.

Uses the existing AutoMod settings, canonical log_config routes, and automod_logs
history. No duplicate listeners, logging tables, or new commands are introduced.
"""
from __future__ import annotations

import logging

import discord

from cogs.automod import AUTOMOD_TOGGLE_LABELS
from utils import log_service

logger = logging.getLogger("bot.automod-center-v118")

GROUPS = (
    ("raid", "Anti-Raid", "Join raids, suspicious bots and new accounts.",
     ("antiraid", "antibot", "antiaccount")),
    ("spam", "Anti-Spam", "Flood, links, invites, pings and message spam.",
     ("antispam", "antilink", "antiinvite",
      "antimention", "anticaps", "antiemoji")),
    ("server", "Server Guard", "Protect critical channels, roles and permissions.",
     ("antinuke",)),
    ("content", "Content Filter", "Detect scams and prohibited language.",
     ("antiscam", "antiinsult")),
)
LOG_CATEGORIES = ("automod", "spam", "raid")
LOG_LABELS = {"automod": "AutoMod", "spam": "Anti-Spam", "raid": "Anti-Raid"}
HISTORY_PAGE_SIZE = 5


def _value(row, key: str, default=0):
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def history_clause(guild_id: int, member_id: int | None, kind: str):
    """Build a parameterized, guild-scoped audit query. Never interpolate user data."""
    clauses = ["guild_id = ?"]
    params = [int(guild_id)]
    if member_id is not None:
        clauses.append("user_id = ?")
        params.append(int(member_id))
    if kind == "spam":
        clauses.append("filter_name IN (?,?,?,?)")
        params.extend(("antispam", "antispam_duplicate", "antiemoji", "antimention"))
    elif kind == "raid":
        clauses.append("filter_name IN (?,?,?)")
        params.extend(("antiraid", "antibot", "antiaccount"))
    elif kind == "content":
        clauses.append("filter_name IN (?,?,?,?,?,?)")
        params.extend(("antilink", "antiinvite", "antiscam", "antiinsult", "blacklist_word", "blacklist_link"))
    return " AND ".join(clauses), tuple(params)


class PrivatePanel(discord.ui.LayoutView):
    def __init__(self, bot, guild, author_id: int):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.author_id = int(author_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild.id or interaction.user.id != self.author_id:
            await interaction.response.send_message("This panel belongs to another user.", ephemeral=True)
            return False
        from cogs.setup_control_center import _can_setup
        if not await _can_setup(self.bot, interaction.user, interaction.guild):
            await interaction.response.send_message("You cannot configure SentriX on this server.", ephemeral=True)
            return False
        return True

    def _container(self, title: str, subtitle: str):
        self.clear_items()
        box = discord.ui.Container(accent_colour=discord.Colour(0x5865F2))
        box.add_item(discord.ui.TextDisplay(
            f"**SENTRIX**  /  SECURITY\n## {title}\n{subtitle}"
        ))
        box.add_item(discord.ui.Separator())
        self.add_item(box)
        return box

    @staticmethod
    def _buttons(box, *items):
        for start in range(0, len(items), 5):
            box.add_item(discord.ui.ActionRow(*items[start:start + 5]))

    @staticmethod
    def _button(label: str, callback, *, primary=False, disabled=False):
        button = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.primary if primary else discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        button.callback = callback
        return button

    async def show(self, interaction: discord.Interaction):
        await self.render()
        await interaction.response.edit_message(content=None, embeds=[], view=self, attachments=[])

    async def open(self, interaction: discord.Interaction):
        await self.render()
        await interaction.response.send_message(view=self, ephemeral=True)

    async def render(self):
        raise NotImplementedError


class AutoModCenterView(PrivatePanel):
    def __init__(self, bot, guild, author_id: int):
        super().__init__(bot, guild, author_id)
        self.group = None

    async def render(self):
        current = await self.bot.db.get_automod(self.guild.id)
        if self.group is None:
            total = sum(bool(_value(current, field)) for field in AUTOMOD_TOGGLE_LABELS)
            box = self._container(
                "AutoMod",
                f"{total}/{len(AUTOMOD_TOGGLE_LABELS)} protections enabled. "
                "Choose a category to configure.",
            )
            for key, label, description, fields in GROUPS:
                active = sum(bool(_value(current, field)) for field in fields)
                box.add_item(discord.ui.TextDisplay(
                    f"**{label}**  ·  {active}/{len(fields)} enabled\n-# {description}"
                ))
            async def open_raid(interaction):
                self.group = "raid"
                await self.show(interaction)
            async def open_spam(interaction):
                self.group = "spam"
                await self.show(interaction)
            async def open_server(interaction):
                self.group = "server"
                await self.show(interaction)
            async def open_content(interaction):
                self.group = "content"
                await self.show(interaction)
            async def open_logs(interaction):
                await AutoModLogsView(self.bot, self.guild, self.author_id).open(interaction)
            self._buttons(box,
                self._button("Anti-Raid", open_raid, primary=True),
                self._button("Anti-Spam", open_spam),
                self._button("Server Guard", open_server),
                self._button("Content Filter", open_content),
                self._button("Logs & History", open_logs),
            )
        else:
            _key, label, description, fields = next(g for g in GROUPS if g[0] == self.group)
            enabled = {field for field in fields if _value(current, field)}
            box = self._container(label, description)
            box.add_item(discord.ui.TextDisplay(
                f"**{len(enabled)}/{len(fields)} enabled**\n"
                "Select the protections you want. Changes save automatically."
            ))
            select = discord.ui.Select(
                placeholder="Choose active protections",
                min_values=0,
                max_values=len(fields),
                options=[
                    discord.SelectOption(
                        label=AUTOMOD_TOGGLE_LABELS[field][:100],
                        value=field,
                        default=field in enabled,
                    ) for field in fields
                ],
            )
            async def change(interaction):
                selected = set(select.values)
                try:
                    for field in fields:
                        new_value = int(field in selected)
                        if new_value != int(bool(_value(current, field))):
                            await self.bot.db.set_automod(self.guild.id, field, new_value)
                except Exception:
                    logger.exception("Failed to save AutoMod protections for guild=%s", self.guild.id)
                    return await interaction.response.send_message("Unable to save the protection settings.", ephemeral=True)
                await self.show(interaction)
            select.callback = change
            box.add_item(discord.ui.ActionRow(select))
            async def back(interaction):
                self.group = None
                await self.show(interaction)
            async def open_logs(interaction):
                await AutoModLogsView(self.bot, self.guild, self.author_id).open(interaction)
            self._buttons(box,
                self._button("Back to AutoMod", back),
                self._button("Logs & History", open_logs),
            )
        box.add_item(discord.ui.TextDisplay(
            "-# SentriX · Existing security protections only · Settings saved instantly"
        ))


class AutoModLogsView(PrivatePanel):
    def __init__(self, bot, guild, author_id: int):
        super().__init__(bot, guild, author_id)
        self.page = "settings"
        self.filter_kind = "all"
        self.member_id = None
        self.offset = 0

    async def render(self):
        if self.page == "history":
            return await self._history()
        routes = {
            key: await log_service.get_log_config(self.bot, self.guild.id, key)
            for key in LOG_CATEGORIES
        }
        active = [
            key for key in LOG_CATEGORIES
            if routes[key] and routes[key]["enabled"] and routes[key]["channel_id"]
        ]
        box = self._container(
            "AutoMod Logs",
            f"{len(active)}/3 log types configured. "
            "Logs are enabled by default once a valid channel is selected.",
        )
        lines = []
        for key in LOG_CATEGORIES:
            config = routes[key] or {}
            channel_id = config.get("channel_id")
            status = ("ON" if config.get("enabled") and channel_id
                      else "OFF" if not config.get("enabled") else "Needs a channel")
            lines.append(f"**{LOG_LABELS[key]}**  ·  {status}  ·  "
                         f"{f'<#{channel_id}>' if channel_id else 'No channel'}")
        box.add_item(discord.ui.TextDisplay("\n".join(lines)))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay(
            "**Log channel**\n-# Choose a private text channel for these three security categories."
        ))
        channel_select = discord.ui.ChannelSelect(
            placeholder="Set channel for AutoMod / Spam / Raid",
            min_values=1, max_values=1,
            channel_types=[discord.ChannelType.text],
        )
        async def set_channel(interaction):
            channel = self.guild.get_channel(channel_select.values[0].id)
            if not isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message(
                    "Choose an existing text channel.", ephemeral=True
                )
            ok, reason = log_service.validate_channel(self.guild, channel.id, needs_file=True)
            if not ok:
                return await interaction.response.send_message(
                    f"Cannot use this channel: {reason}", ephemeral=True
                )
            # Security logs can contain sensitive moderation details.
            if channel.permissions_for(self.guild.default_role).view_channel:
                return await interaction.response.send_message(
                    "Use a private staff-only channel for security logs.", ephemeral=True
                )
            try:
                for key in LOG_CATEGORIES:
                    await log_service.set_log_config(
                        self.bot, self.guild.id, key,
                        channel_id=channel.id, enabled=True,
                    )
            except Exception:
                logger.exception("Failed to configure security log channels guild=%s", self.guild.id)
                return await interaction.response.send_message("Unable to save the log channel.", ephemeral=True)
            await self.show(interaction)
        channel_select.callback = set_channel
        box.add_item(discord.ui.ActionRow(channel_select))
        toggle = discord.ui.Select(
            placeholder="Select enabled log types",
            min_values=0, max_values=len(LOG_CATEGORIES),
            options=[
                discord.SelectOption(
                    label=LOG_LABELS[key], value=key,
                    default=key in active,
                ) for key in LOG_CATEGORIES
            ],
        )
        async def set_enabled(interaction):
            selected = set(toggle.values)
            if any(not routes[key]["channel_id"] for key in selected):
                return await interaction.response.send_message(
                    "Choose a log channel before enabling a log type.", ephemeral=True
                )
            try:
                for key in LOG_CATEGORIES:
                    conf = routes[key]
                    if bool(conf["enabled"]) != (key in selected):
                        await log_service.set_log_config(
                            self.bot, self.guild.id, key,
                            channel_id=conf["channel_id"], enabled=key in selected,
                        )
            except Exception:
                logger.exception("Failed to toggle security logs guild=%s", self.guild.id)
                return await interaction.response.send_message("Unable to save log settings.", ephemeral=True)
            await self.show(interaction)
        toggle.callback = set_enabled
        box.add_item(discord.ui.ActionRow(toggle))

        async def history(interaction):
            self.page = "history"
            self.offset = 0
            await self.show(interaction)
        async def send_test(interaction):
            key = next(iter(active), None)
            if key is None:
                return await interaction.response.send_message(
                    "Configure at least one log channel first.", ephemeral=True
                )
            ok, msg = await log_service.send_test_log(
                self.bot, self.guild, key, interaction.user,
            )
            await interaction.response.send_message(
                "Test log sent." if ok else f"Test failed: {msg}", ephemeral=True
            )
        self._buttons(box,
            self._button("View History", history, primary=True),
            self._button("Send Test", send_test, disabled=not bool(active)),
        )
        box.add_item(discord.ui.TextDisplay(
            "-# SentriX · Existing log routing · No extra duplicate log messages"
        ))

    async def _history(self):
        clause, values = history_clause(self.guild.id, self.member_id, self.filter_kind)
        total_row = await self.bot.db.fetchone(
            f"SELECT COUNT(*) AS total FROM automod_logs WHERE {clause}", values
        )
        total = int(_value(total_row, "total", 0) or 0)
        self.offset = min(self.offset, max(0, ((total - 1) // HISTORY_PAGE_SIZE) * HISTORY_PAGE_SIZE))
        rows = await self.bot.db.fetchall(
            f"SELECT user_id, filter_name, action, reason, timestamp "
            f"FROM automod_logs WHERE {clause} ORDER BY timestamp DESC "
            f"LIMIT ? OFFSET ?",
            (*values, HISTORY_PAGE_SIZE, self.offset),
        )
        page_num = self.offset // HISTORY_PAGE_SIZE + 1
        page_count = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
        box = self._container(
            "Security History",
            f"{total} recorded action(s) · Page {page_num}/{page_count}",
        )
        if rows:
            entries = []
            for row in rows:
                user = f"<@{row['user_id']}>" if row["user_id"] else "Unknown member"
                reason = str(row["reason"] or "No reason supplied").replace("\n", " ")[:220]
                action = str(row["action"] or "Detected")[:50]
                category = str(row["filter_name"] or "AutoMod")[:50]
                entries.append(
                    f"**{category}**  ·  <t:{int(row['timestamp'])}:R>\n"
                    f"{user}  ·  **{action}**\n-# {discord.utils.escape_markdown(reason)}"
                )
            box.add_item(discord.ui.TextDisplay("\n\n".join(entries)))
        else:
            box.add_item(discord.ui.TextDisplay("No matching AutoMod actions yet."))
        filter_select = discord.ui.Select(
            placeholder="Filter events",
            options=[
                discord.SelectOption(label=label, value=key, default=self.filter_kind == key)
                for key, label in (
                    ("all", "All actions"), ("spam", "Spam & mentions"),
                    ("raid", "Raids & bots"), ("content", "Content & links"),
                )
            ],
        )
        async def set_filter(interaction):
            self.filter_kind = filter_select.values[0]
            self.offset = 0
            await self.show(interaction)
        filter_select.callback = set_filter
        box.add_item(discord.ui.ActionRow(filter_select))
        user_select = discord.ui.UserSelect(
            placeholder="Filter by member (optional)",
            min_values=0, max_values=1,
        )
        async def set_member(interaction):
            self.member_id = user_select.values[0].id if user_select.values else None
            self.offset = 0
            await self.show(interaction)
        user_select.callback = set_member
        box.add_item(discord.ui.ActionRow(user_select))

        async def prev(interaction):
            self.offset = max(0, self.offset - HISTORY_PAGE_SIZE)
            await self.show(interaction)
        async def next_page(interaction):
            self.offset += HISTORY_PAGE_SIZE
            await self.show(interaction)
        async def settings(interaction):
            self.page = "settings"
            await self.show(interaction)
        self._buttons(box,
            self._button("Previous", prev, disabled=self.offset == 0),
            self._button("Next", next_page, disabled=self.offset + HISTORY_PAGE_SIZE >= total),
            self._button("Settings", settings, primary=True),
        )
        box.add_item(discord.ui.TextDisplay(
            "-# Stored audit history · Older entries may not include channel or actor details"
        ))


__all__ = [
    "GROUPS", "LOG_CATEGORIES", "HISTORY_PAGE_SIZE", "history_clause",
    "AutoModCenterView", "AutoModLogsView",
]
