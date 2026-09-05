"""Final product update requested for SentriX.

This layer is deliberately small and late-binding.  It fixes the pieces that need to win
against the historical compatibility layers without rewriting the large ticket/setup cogs.
Dashboard routes are installed during Railway pre-start, while Discord command/UI patches
are applied after all normal extensions have loaded.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType

import discord
from aiohttp import web
from discord.ext import commands

logger = logging.getLogger("bot.sentrix-product-update")

UNKNOWN_COMMAND_TEXT = "Commande introuvable. Merci de consulter les commandes avec /help."
TICKET_CONFIG_COMMANDS = frozenset({
    "ticketsetup",
    "ticketpanel",
    "ticketpanel-toggle",
    "tickettype",
    "ticketform",
    "ticketconfig",
    "ticketlogs",
    "ticketlimit",
    "ticketautoclose",
    "ticket-role",
})


# ---------------------------------------------------------------------------
# Dashboard: all required routes must exist BEFORE aiohttp build_app() runs.
# ---------------------------------------------------------------------------

_DASHBOARD_RECOVERY_JS = r'''
<script id="sentrix-product-dashboard-recovery">
(() => {
  "use strict";
  if (window.__sentrixProductDashboardRecovery) return;
  window.__sentrixProductDashboardRecovery = true;

  let running = false;
  let lastError = "";
  const S = () => { try { return typeof state !== "undefined" ? state : null; } catch (_) { return null; } };
  const byId = id => document.getElementById(id);
  const selected = () => {
    const value = String(byId("serverSelect")?.value || "");
    return value && !value.startsWith("invite:") ? value : "";
  };
  const visibleDashboard = () => {
    const dashboard = byId("dashboard");
    return dashboard && !dashboard.classList.contains("hidden");
  };
  const request = async url => {
    const response = await fetch(url, {credentials:"same-origin", cache:"no-store", headers:{"Cache-Control":"no-cache"}});
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.error || `Erreur HTTP ${response.status}`);
    return data;
  };
  const number = value => Number(value || 0).toLocaleString("fr-FR");

  function hideLoader(){
    byId("emptyState")?.classList.add("hidden");
    const content = byId("serverContent");
    if (content) content.classList.remove("hidden", "loading");
  }

  function showError(message){
    const empty = byId("emptyState");
    if (!empty) return;
    empty.classList.remove("hidden");
    empty.classList.add("sx-empty-premium");
    const safe = String(message || "Chargement impossible.").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    empty.innerHTML = `<div class="sx-load-card"><h3>Impossible de charger le dashboard</h3><p>${safe}</p><button class="btn primary" id="sentrixProductRetry" type="button">Réessayer</button></div>`;
    byId("sentrixProductRetry")?.addEventListener("click", () => bootstrap(true), {once:true});
  }

  function applyGuild(id, data){
    const s = S();
    if (!s || !data?.guild) return false;
    s.guildId = String(id);
    s.guildData = data;
    s.dirty = false;
    const set = (key, value) => { const node = byId(key); if (node) node.textContent = value; };
    set("pageTitle", data.guild.name || "Serveur");
    set("pageSubtitle", `${number(data.guild.members)} membres · ${number(data.guild.channels_count)} salons · ${number(data.guild.roles_count)} rôles`);
    set("metricMembers", number(data.guild.members));
    set("metricCommands", number(data.metrics?.commands_24h));
    set("metricTickets", number(data.metrics?.open_tickets));
    set("metricWarnings", number(data.metrics?.warnings));
    hideLoader();
    try { if (typeof renderTab === "function") renderTab(); } catch (error) { console.error("SentriX renderTab", error); }
    return true;
  }

  function fillGuildSelect(guilds){
    const select = byId("serverSelect");
    if (!(select instanceof HTMLSelectElement)) return "";
    const installed = (guilds || []).filter(g => g.installed);
    const old = selected();
    if (!select.options.length || ![...select.options].some(option => option.value && !String(option.value).startsWith("invite:"))) {
      select.innerHTML = '<option value="">Choisissez un serveur</option>' + (guilds || []).map(g =>
        `<option value="${g.installed ? String(g.id) : "invite:" + String(g.id)}">${String(g.name || "Serveur")}${g.installed ? "" : " — ajouter SentriX"}</option>`
      ).join("");
    }
    let id = old;
    if (!id || !installed.some(g => String(g.id) === id)) {
      try {
        const saved = localStorage.getItem("sentrix:main:guild");
        if (saved && installed.some(g => String(g.id) === String(saved))) id = String(saved);
      } catch (_) {}
    }
    if (!id && installed[0]) id = String(installed[0].id);
    if (id) select.value = id;
    return id;
  }

  async function bootstrap(force=false){
    if (running || !visibleDashboard()) return;
    const s = S();
    if (!s) return;
    const current = selected();
    if (!force && current && s.guildData && String(s.guildId || "") === current) {
      hideLoader();
      return;
    }
    running = true;
    try {
      // Do not depend on the original loadSession/loadGuilds chain: a stale browser or an
      // HA standby can miss that chain even though the APIs already answer 200.
      const me = await request("/api/me");
      s.user = me.user;
      s.csrf = me.csrf;
      const userName = byId("userName");
      if (userName && me.user?.username) userName.textContent = me.user.username;
      if (me.user?.avatar_url) {
        const avatar = byId("userAvatar");
        if (avatar) avatar.innerHTML = `<img class="avatar" src="${me.user.avatar_url}" alt="">`;
      }

      const guildPayload = await request("/api/guilds");
      s.guilds = guildPayload.guilds || [];
      const id = fillGuildSelect(s.guilds);
      if (!id) {
        showError("Aucun serveur administrable avec SentriX n'est disponible sur ce compte.");
        return;
      }
      const data = await request(`/api/guilds/${encodeURIComponent(id)}`);
      if (!applyGuild(id, data)) throw new Error("Les données du serveur ont été reçues mais l'affichage n'a pas pu être initialisé.");
      try { localStorage.setItem("sentrix:main:guild", id); } catch (_) {}
      lastError = "";
    } catch (error) {
      lastError = String(error?.message || "Chargement impossible.");
      console.warn("SentriX dashboard recovery", error);
      showError(lastError);
    } finally {
      running = false;
    }
  }

  document.addEventListener("change", event => {
    if (event.target?.id !== "serverSelect") return;
    setTimeout(() => bootstrap(true), 120);
  }, true);

  const start = () => {
    [250, 900, 2000, 4500].forEach(delay => setTimeout(() => bootstrap(false), delay));
    setInterval(() => {
      if (!visibleDashboard()) return;
      const s = S(), id = selected();
      const loader = byId("emptyState");
      if (id && (!s?.guildData || String(s.guildId || "") !== id || (loader && !loader.classList.contains("hidden")))) bootstrap(false);
    }, 7000);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
</script>
'''


def _install_no_store_index(dashboard) -> None:
    current = dashboard.handle_index
    if getattr(current, "_sentrix_product_no_store", False):
        return

    async def handle_index_no_store(_request: web.Request):
        response = web.Response(text=dashboard.INDEX_HTML, content_type="text/html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    handle_index_no_store._sentrix_product_no_store = True
    handle_index_no_store._sentrix_original = current
    dashboard.handle_index = handle_index_no_store


def install_dashboard_prestart(dashboard) -> bool:
    """Install dashboard APIs/UI before ``dashboard.build_app`` creates the aiohttp app."""
    installed = []
    try:
        from web import embed_dashboard
        embed_dashboard.install(dashboard)
        installed.append("embeds")
    except Exception:
        logger.exception("Dashboard embed builder pre-start install failed.")

    try:
        from web import ticket_center_v35
        ticket_center_v35.install(dashboard)
        installed.append("tickets")
    except Exception:
        logger.exception("Dashboard ticket center pre-start install failed.")

    try:
        from web import ticket_buttons_editor_v53
        ticket_buttons_editor_v53.install(dashboard)
        installed.append("ticket-buttons")
    except Exception:
        logger.exception("Dashboard ticket button editor pre-start install failed.")

    try:
        from web import ticket_ping_dashboard
        ticket_ping_dashboard.install(dashboard)
        installed.append("ticket-ping")
    except Exception:
        logger.exception("Dashboard ticket ping-role pre-start install failed.")

    _install_no_store_index(dashboard)
    marker = 'id="sentrix-product-dashboard-recovery"'
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if marker not in html:
        dashboard.INDEX_HTML = html.replace("</body>", _DASHBOARD_RECOVERY_JS + "\n</body>", 1) if "</body>" in html else html + _DASHBOARD_RECOVERY_JS

    logger.info("Dashboard product pre-start active: %s", ", ".join(installed) or "recovery-only")
    return marker in dashboard.INDEX_HTML


# ---------------------------------------------------------------------------
# Role reaction builder: custom emoji selection inside the interactive builder.
# ---------------------------------------------------------------------------


def _install_rolepanel_custom_emojis() -> bool:
    import sentrix_regression_runtime as role_runtime

    cls = role_runtime.RolePanelBuilder
    if getattr(cls, "_sentrix_custom_emoji_builder", False):
        return True

    original_rebuild = cls.rebuild
    original_embed = cls.embed
    original_create = cls.create_panel

    class RoleEmojiModal(discord.ui.Modal, title="Choisir les emojis"):
        def __init__(self, builder):
            super().__init__(timeout=300)
            self.builder = builder
            role_count = len(builder.selected_role_ids)
            defaults = list(getattr(builder, "custom_emojis", []) or role_runtime._DEFAULT_REACTION_EMOJIS[:role_count])
            self.values_input = discord.ui.TextInput(
                label="Un emoji par ligne, dans l'ordre des rôles",
                style=discord.TextStyle.paragraph,
                placeholder="✅\n🎉\n🔥",
                default="\n".join(defaults),
                required=True,
                max_length=2000,
            )
            self.add_item(self.values_input)

        async def on_submit(self, interaction: discord.Interaction):
            emojis = [line.strip() for line in str(self.values_input.value).splitlines() if line.strip()]
            expected = len(self.builder.selected_role_ids)
            if not expected:
                return await interaction.response.send_message("Sélectionnez d'abord les rôles du panneau.", ephemeral=True)
            if len(emojis) != expected:
                return await interaction.response.send_message(
                    f"Il faut exactement **{expected} emoji(s)** : un par rôle sélectionné.",
                    ephemeral=True,
                )
            keys = [role_runtime._emoji_key(value) for value in emojis]
            if len(set(keys)) != len(keys):
                return await interaction.response.send_message("Chaque rôle doit avoir un emoji différent.", ephemeral=True)
            self.builder.custom_emojis = emojis
            self.builder.rebuild()
            await interaction.response.edit_message(embed=self.builder.embed(), view=self.builder)

    async def choose_emojis(interaction: discord.Interaction, builder) -> None:
        if not builder.selected_role_ids:
            return await interaction.response.send_message("Sélectionnez d'abord les rôles, puis choisissez leurs emojis.", ephemeral=True)
        await interaction.response.send_modal(RoleEmojiModal(builder))

    def rebuild(self):
        original_rebuild(self)
        if not hasattr(self, "custom_emojis"):
            self.custom_emojis = []
        if self.mode == "reaction":
            button = discord.ui.Button(
                label="Choisir les emojis",
                style=discord.ButtonStyle.primary,
                emoji="😀",
                custom_id=f"sentrix:rolepanel-builder:custom-emojis:{self.owner_id}",
                row=2,
            )
            async def callback(interaction: discord.Interaction):
                await choose_emojis(interaction, self)
            button.callback = callback
            self.add_item(button)

    def embed(self):
        panel = original_embed(self)
        if self.mode != "reaction":
            return panel
        roles = [self.guild.get_role(role_id) for role_id in self.selected_role_ids]
        roles = [role for role in roles if role is not None]
        custom = list(getattr(self, "custom_emojis", []) or [])
        if custom and len(custom) == len(roles):
            value = "\n".join(f"{emoji} → {role.mention}" for emoji, role in zip(custom, roles))
        else:
            value = "Cliquez sur **Choisir les emojis** pour mettre l'emoji exact que vous voulez pour chaque rôle."
        for index, field in enumerate(panel.fields):
            if str(field.name) == "Emojis":
                panel.set_field_at(index, name="Emojis", value=value, inline=False)
                break
        return panel

    async def create_panel(self, interaction: discord.Interaction):
        custom = list(getattr(self, "custom_emojis", []) or [])
        if self.mode != "reaction" or not custom:
            return await original_create(self, interaction)
        if not self.selected_role_ids:
            return await interaction.response.send_message("Sélectionnez au moins un rôle existant avant de créer le panneau.", ephemeral=True)
        roles, errors = role_runtime._valid_roles(self.guild, self.selected_role_ids)
        if not roles:
            return await interaction.response.send_message(
                "Aucun rôle sélectionné n'est modifiable par SentriX.\n" + "\n".join(f"• {item}" for item in errors[:6]),
                ephemeral=True,
            )
        if len(custom) != len(roles):
            return await interaction.response.send_message(
                "Le nombre d'emojis ne correspond plus aux rôles sélectionnés. Cliquez sur **Choisir les emojis** puis validez à nouveau.",
                ephemeral=True,
            )
        keys = [role_runtime._emoji_key(value) for value in custom]
        if len(set(keys)) != len(keys):
            return await interaction.response.send_message("Chaque rôle doit avoir un emoji différent.", ephemeral=True)

        await interaction.response.defer()
        role_ids = [role.id for role in roles]
        mappings = [
            {"emoji": emoji, "key": role_runtime._emoji_key(emoji), "role_id": role.id}
            for emoji, role in zip(custom, roles)
        ]
        try:
            message = await interaction.channel.send(embed=role_runtime._reaction_embed(self.guild, mappings))
            try:
                for item in mappings:
                    await message.add_reaction(item["emoji"])
            except (discord.Forbidden, discord.HTTPException):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
                return await interaction.followup.send(
                    "Un des emojis n'est pas utilisable par SentriX. Vérifiez l'emoji choisi et les permissions, puis réessayez.",
                    ephemeral=True,
                )
            await role_runtime._save_panel(
                self.bot, message, mode="reaction", role_ids=role_ids, mappings=mappings, creator_id=self.owner_id,
            )
            success = discord.Embed(
                title="Panneau créé",
                description=f"Mode : **réactions emoji**\nRôles : **{len(role_ids)}**\nEmojis personnalisés : **{len(mappings)}**\n\nSentriX n'a créé aucun nouveau rôle.",
                colour=0x2FBF71,
            )
            await interaction.message.edit(embed=success, view=None)
            self.stop()
        except discord.Forbidden:
            await interaction.followup.send("SentriX n'a pas la permission d'envoyer le panneau ou de gérer ces rôles.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Discord a refusé la création du panneau. Réessayez dans quelques secondes.", ephemeral=True)

    cls.rebuild = rebuild
    cls.embed = embed
    cls.create_panel = create_panel
    cls._sentrix_custom_emoji_builder = True
    return True


# ---------------------------------------------------------------------------
# Discord command surface: ticket setup is dashboard-only; operations stay intact.
# ---------------------------------------------------------------------------


def _remove_ticket_configuration(bot: commands.Bot) -> tuple[str, ...]:
    removed = []
    for name in sorted(TICKET_CONFIG_COMMANDS):
        command = bot.get_command(name)
        if command is not None:
            bot.remove_command(command.name)
            removed.append(name)
        try:
            bot.tree.remove_command(name, type=discord.AppCommandType.chat_input)
        except Exception:
            pass

    # Hide Tickets from every +setup generation while keeping the runtime ticket commands.
    try:
        from cogs import setup_control_center as setup_ui
        setup_ui.CATEGORIES.pop("tickets", None)
        setup_ui.CATEGORY_ORDER = tuple(item for item in setup_ui.CATEGORY_ORDER if item != "tickets")
    except Exception:
        logger.debug("Legacy setup ticket category cleanup skipped.", exc_info=True)
    try:
        from cogs import setup_experience_v74 as v74
        v74.CATEGORY_META.pop("tickets", None)
        v74.CATEGORY_ORDER = tuple(item for item in v74.CATEGORY_ORDER if item != "tickets")
    except Exception:
        logger.debug("V74 setup ticket category cleanup skipped.", exc_info=True)

    return tuple(removed)


def _unwrap_error_handler(handler):
    current = handler
    seen = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        previous = getattr(current, "_sentrix_previous_error_handler", None)
        if previous is None:
            function = getattr(current, "__func__", None)
            previous = getattr(function, "_sentrix_previous_error_handler", None) if function is not None else None
        if previous is None:
            break
        current = previous
    return current


async def _plain_send(ctx: commands.Context, text: str):
    sender = discord.abc.Messageable.send
    seen = set()
    while hasattr(sender, "_sentrix_original") and id(sender) not in seen:
        seen.add(id(sender))
        sender = getattr(sender, "_sentrix_original")
    return await sender(ctx.channel, text, allowed_mentions=discord.AllowedMentions.none())


def _install_unknown_command(bot: commands.Bot) -> bool:
    current = getattr(bot, "on_command_error", None)
    if not callable(current):
        return False
    base = _unwrap_error_handler(current)

    async def exact_error(self, ctx: commands.Context, error: commands.CommandError):
        root = getattr(error, "original", error)
        if isinstance(root, commands.CommandNotFound):
            await _plain_send(ctx, UNKNOWN_COMMAND_TEXT)
            return
        result = base(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    exact_error._sentrix_exact_unknown_command = True
    exact_error._sentrix_previous_error_handler = base
    bot.on_command_error = MethodType(exact_error, bot)
    return True


async def install_runtime(bot: commands.Bot) -> None:
    custom_emoji = _install_rolepanel_custom_emojis()
    removed = _remove_ticket_configuration(bot)
    unknown = _install_unknown_command(bot)

    # setup_invitations has its own on_ready repair. Make that repair call the exact final
    # policy too, otherwise it could reintroduce the old suggestion embed/text after us.
    try:
        from cogs import setup_invitations
        setup_invitations._patch_unknown_command_final = _install_unknown_command
    except Exception:
        logger.debug("Invitation final error hook replacement skipped.", exc_info=True)

    if not getattr(bot, "_sentrix_product_update_ready_listener", False):
        async def final_ready_repair():
            _remove_ticket_configuration(bot)
            _install_unknown_command(bot)
        bot.add_listener(final_ready_repair, "on_ready")
        bot._sentrix_product_update_ready_listener = True

    bot.sentrix_product_update_state = {
        "rolepanel_custom_emojis": custom_emoji,
        "ticket_setup_dashboard_only": True,
        "removed_ticket_config_commands": removed,
        "unknown_command_plain_text": unknown,
    }
    logger.info("SentriX product update active: %s", bot.sentrix_product_update_state)
