"""Invitations Setup et correctifs finaux de régression visibles par l'utilisateur.

Cette extension est chargée tôt par GiveawayCenter, puis réapplique au on_ready les trois
contrats qui doivent gagner sur les couches V74/V5/dashboard installées plus tard :
- une vraie page Invitations dans +setup, accessible directement par texte ;
- CommandNotFound en texte Discord brut, jamais en embed/carte ;
- un dernier garde navigateur qui empêche le dashboard de rester sur son loader alors que
  /api/guilds/{id} a déjà répondu correctement.
"""
from __future__ import annotations

import difflib
import inspect
import logging
from types import MethodType

import discord
from discord.ext import commands

from utils import embeds, log_categories, log_service
from utils import sentrix_panels as panels
from . import setup_control_center as setup_ui

logger = logging.getLogger("bot.setup-invitations")

CATEGORY = "invitations"
LABEL = "Invitations"
# On accepte aussi la faute montrée en production : +setup invition.
SETUP_ALIASES = frozenset({
    "invite", "invites", "invitation", "invitations", "invition", "invitions"
})


class InvitationLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Salon des logs d’invitations",
            min_values=0,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        channel_id = self.values[0].id if self.values else None
        if channel_id is not None:
            ok, reason = log_service.validate_channel(self.owner.guild, channel_id, needs_file=True)
            if not ok:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error(f"Ce salon ne peut pas recevoir les logs : **{reason}**.")),
                    ephemere=True,
                )
        await log_service.set_log_config(
            self.owner.bot,
            self.owner.guild.id,
            CATEGORY,
            channel_id=channel_id,
            enabled=channel_id is not None,
        )
        await self.owner.audit(interaction.user.id, "invitation_log_channel", channel_id)
        await self.owner.refresh(interaction)


def _install_log_category() -> None:
    log_categories.CATEGORIES[CATEGORY] = LABEL
    if CATEGORY not in log_categories.CATEGORY_ORDER:
        log_categories.CATEGORY_ORDER = tuple(log_categories.CATEGORY_ORDER) + (CATEGORY,)
    log_categories.CATEGORY_META[CATEGORY] = {"label": LABEL, "emits": True}
    log_categories.LEGACY_CATEGORY_KEYS["dossiers"] = CATEGORY
    log_categories.LEGACY_CATEGORY_KEYS["log_dossiers"] = CATEGORY
    for event in ("invite_create", "invite_delete"):
        current = log_categories.LOG_REGISTRY.get(event)
        if current:
            _old_category, emoji, kind = current
            log_categories.LOG_REGISTRY[event] = (CATEGORY, emoji, kind)


def _patch_statuses() -> None:
    current = setup_ui.module_statuses
    if getattr(current, "_sentrix_invites", False):
        return

    async def statuses(bot, guild, conf):
        result = await current(bot, guild, conf)
        setting = await log_service.get_log_setting(bot, guild.id, CATEGORY)
        channel_id = setting.get("channel_id")
        problems = []
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                problems.append("Le salon de logs d’invitations n’existe plus.")
            else:
                ok, reason = log_service.validate_channel(guild, int(channel_id), needs_file=True)
                if not ok:
                    problems.append(f"Le salon de logs d’invitations est invalide : {reason}.")
        if problems:
            state = setup_ui.ConfigState.ERROR
        elif setting.get("enabled") and channel_id:
            state = setup_ui.ConfigState.ACTIVE
        elif channel_id:
            state = setup_ui.ConfigState.INACTIVE
        else:
            state = setup_ui.ConfigState.UNCONFIGURED
        result[CATEGORY] = (
            state,
            "Salon dédié aux arrivées par invitation et aux créations/suppressions d’invitations.",
            tuple(problems),
        )
        return result

    statuses._sentrix_invites = True
    setup_ui.module_statuses = statuses


def _patch_render() -> None:
    current = setup_ui.SetupView.render
    if getattr(current, "_sentrix_invites", False):
        return

    def render(self):
        current(self)
        if self.category != CATEGORY:
            return
        self.ajouter(InvitationLogChannelSelect(self))
        toggle = discord.ui.Button(label="Activer / Désactiver les logs", style=discord.ButtonStyle.primary)
        test = discord.ui.Button(label="Tester", style=discord.ButtonStyle.secondary)

        async def toggle_cb(interaction: discord.Interaction):
            setting = await log_service.get_log_setting(self.bot, self.guild.id, CATEGORY)
            channel_id = setting.get("channel_id")
            if not channel_id:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Choisissez d’abord un salon de logs d’invitations.")),
                    ephemere=True,
                )
            await log_service.set_log_config(
                self.bot, self.guild.id, CATEGORY,
                channel_id=channel_id,
                enabled=not bool(setting.get("enabled")),
            )
            await self.audit(interaction.user.id, "invitation_logs_enabled", not bool(setting.get("enabled")))
            await self.refresh(interaction)

        async def test_cb(interaction: discord.Interaction):
            setting = await log_service.get_log_setting(self.bot, self.guild.id, CATEGORY)
            channel_id = setting.get("channel_id")
            if not setting.get("enabled") or not channel_id:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Configurez et activez d’abord le salon d’invitations.")),
                    ephemere=True,
                )
            channel = self.guild.get_channel(int(channel_id))
            if channel is None:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error("Salon introuvable.")),
                    ephemere=True,
                )
            test_embed = embeds.info(
                f"Ce salon recevra les logs d’invitations de **{self.guild.name}**.\n"
                "Les arrivées indiquent l’inviteur et le code détecté lorsque Discord fournit l’information.",
                title="Test — Invitations",
            )
            await channel.send(embed=test_embed, allowed_mentions=discord.AllowedMentions.none())
            await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.success("Log de test envoyé.")),
                ephemere=True,
            )

        toggle.callback = toggle_cb
        test.callback = test_cb
        self.ajouter(toggle)
        self.ajouter(test)

    render._sentrix_invites = True
    setup_ui.SetupView.render = render


def _patch_embed() -> None:
    current = setup_ui.SetupView.build_embed
    if getattr(current, "_sentrix_invites", False):
        return

    async def build_embed(self):
        panel = await current(self)
        if self.category != CATEGORY:
            return panel
        setting = await log_service.get_log_setting(self.bot, self.guild.id, CATEGORY)
        channel_id = setting.get("channel_id")
        channel = self.guild.get_channel(int(channel_id)) if channel_id else None
        panel.add_field(name="Salon des invitations", value=(channel.mention if channel else "Non configuré"), inline=False)
        panel.add_field(name="État", value="ACTIF" if setting.get("enabled") and channel_id else "INACTIF", inline=True)
        panel.add_field(
            name="Événements",
            value="Arrivée via invitation • invitation créée • invitation supprimée",
            inline=False,
        )
        return panel

    build_embed._sentrix_invites = True
    setup_ui.SetupView.build_embed = build_embed


def _requested_setup_category(target) -> str | None:
    message = getattr(target, "message", None)
    content = str(getattr(message, "content", "") or "").strip()
    if not content:
        return None
    parts = content.split()
    if len(parts) < 2:
        return None
    requested = parts[1].casefold().strip(" ,.;:!?/")
    return CATEGORY if requested in SETUP_ALIASES else None


def _patch_setup_entry(bot) -> None:
    current = setup_ui.OfficialSetup.send_setup
    if not getattr(current, "_sentrix_invitation_route", False):
        async def send_setup(self, target):
            guild = getattr(target, "guild", None)
            member = getattr(target, "author", None) or getattr(target, "user", None)
            if not await setup_ui._can_setup(self.bot, member, guild):
                return await setup_ui._permission_error(target)
            view = setup_ui.SetupView(self.bot, guild, member.id)
            requested = _requested_setup_category(target)
            if requested is not None:
                view.category = requested
            await view.composer()
            return await panels.envoyer(target, view)

        send_setup._sentrix_invitation_route = True
        send_setup._sentrix_previous = current
        setup_ui.OfficialSetup.send_setup = send_setup

    command = bot.get_command("setup")
    if command is not None:
        command.ignore_extra = True
        command._sentrix_invitation_aliases = tuple(sorted(SETUP_ALIASES))


# ---------------------------------------------------------------------------
# Couche finale V74 : c'est elle qui possède réellement le Setup visible.
# ---------------------------------------------------------------------------

async def _v74_invitation_state(bot, guild) -> str:
    setting = await log_service.get_log_setting(bot, guild.id, CATEGORY)
    channel_id = setting.get("channel_id")
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            return "! À CORRIGER"
        ok, _reason = log_service.validate_channel(guild, int(channel_id), needs_file=True)
        if not ok:
            return "! À CORRIGER"
    if setting.get("enabled") and channel_id:
        return "● ACTIF"
    if channel_id:
        return "○ INACTIF"
    return "— À CONFIGURER"


async def _build_v74_invitations(view) -> None:
    from . import setup_components_v73 as v73

    setting = await log_service.get_log_setting(view.bot, view.guild.id, CATEGORY)
    channel_id = setting.get("channel_id")
    channel = view.guild.get_channel(int(channel_id)) if channel_id else None
    enabled = bool(setting.get("enabled") and channel_id)

    container = discord.ui.Container(accent_colour=v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 🔗 Invitations\n"
                "Configurez ici les logs dédiés aux invitations Discord.\n"
                "SentriX journalise les arrivées détectées par invitation, les codes créés et les codes supprimés."
            ),
            accessory=v73._thumbnail(view.bot),
        )
    )
    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(
            "### État\n"
            f"**{'Activé' if enabled else 'Inactif'}**\n"
            f"Salon : {channel.mention if channel else '**Non configuré**'}"
        )
    )

    select = discord.ui.ChannelSelect(
        placeholder="Salon des logs d’invitations",
        min_values=0,
        max_values=1,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
    )

    async def choose_channel(interaction: discord.Interaction):
        selected_id = select.values[0].id if select.values else None
        if selected_id is not None:
            ok, reason = log_service.validate_channel(view.guild, selected_id, needs_file=True)
            if not ok:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error(f"Ce salon ne peut pas recevoir les logs : **{reason}**.")),
                    ephemere=True,
                )
        await log_service.set_log_config(
            view.bot, view.guild.id, CATEGORY,
            channel_id=selected_id,
            enabled=selected_id is not None,
        )
        try:
            await view.backend.audit(interaction.user.id, "invitation_log_channel", selected_id)
        except Exception:
            logger.debug("Audit invitation V74 indisponible", exc_info=True)
        await view.refresh(interaction)

    select.callback = choose_channel
    container.add_item(discord.ui.ActionRow(select))

    toggle = discord.ui.Button(
        label="Désactiver les logs" if enabled else "Activer les logs",
        style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
    )
    test = discord.ui.Button(label="Tester", style=discord.ButtonStyle.secondary)

    async def toggle_logs(interaction: discord.Interaction):
        current = await log_service.get_log_setting(view.bot, view.guild.id, CATEGORY)
        current_channel = current.get("channel_id")
        if not current_channel:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Choisissez d’abord un salon de logs d’invitations.")),
                ephemere=True,
            )
        await log_service.set_log_config(
            view.bot, view.guild.id, CATEGORY,
            channel_id=current_channel,
            enabled=not bool(current.get("enabled")),
        )
        await view.refresh(interaction)

    async def send_test(interaction: discord.Interaction):
        current = await log_service.get_log_setting(view.bot, view.guild.id, CATEGORY)
        current_channel = current.get("channel_id")
        if not current.get("enabled") or not current_channel:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Configurez et activez d’abord le salon d’invitations.")),
                ephemere=True,
            )
        destination = view.guild.get_channel(int(current_channel))
        if destination is None:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Salon introuvable.")),
                ephemere=True,
            )
        await destination.send(
            embed=embeds.info(
                f"Ce salon recevra les logs d’invitations de **{view.guild.name}**.",
                title="Test — Invitations",
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await panels.envoyer(
            interaction.response,
            panels.depuis_embed(embeds.success("Log de test envoyé.")),
            ephemere=True,
        )

    toggle.callback = toggle_logs
    test.callback = send_test
    container.add_item(discord.ui.ActionRow(toggle, test))
    view._add_navigation(container)
    view.add_item(container)


def _patch_setup_v74(bot: commands.Bot) -> None:
    try:
        from . import setup_experience_v74 as v74
    except Exception:
        return

    if CATEGORY not in v74.CATEGORY_ORDER:
        order = list(v74.CATEGORY_ORDER)
        at = order.index("logs") + 1 if "logs" in order else len(order)
        order.insert(at, CATEGORY)
        v74.CATEGORY_ORDER = tuple(order)
    v74.CATEGORY_META[CATEGORY] = (
        "🔗",
        "Invitations",
        "Logs dédiés aux invitations, inviteur détecté et changements de codes.",
    )

    cls = v74.SentriXSetupV74
    if not getattr(cls, "_sentrix_invitation_final", False):
        previous_states = cls._effective_states
        previous_page = cls._build_page

        async def effective_states(self):
            states = await previous_states(self)
            states[CATEGORY] = await _v74_invitation_state(self.bot, self.guild)
            return states

        async def build_page(self, page: str):
            if page == CATEGORY:
                self.backend.category = CATEGORY
                return await _build_v74_invitations(self)
            return await previous_page(self, page)

        effective_states._sentrix_invitation_final = True
        build_page._sentrix_invitation_final = True
        cls._effective_states = effective_states
        cls._build_page = build_page
        cls._sentrix_invitation_final = True

    async def final_send_setup(self, target):
        guild = getattr(target, "guild", None)
        member = getattr(target, "author", None) or getattr(target, "user", None)
        if not await setup_ui._can_setup(self.bot, member, guild):
            return await setup_ui._permission_error(target)
        view = cls(self.bot, guild, member.id)
        requested = _requested_setup_category(target)
        if requested == CATEGORY:
            view.page = CATEGORY
            view.backend = view._new_backend(CATEGORY)
        await view.prepare()
        if isinstance(target, commands.Context):
            return await target.send(view=view)
        if target.response.is_done():
            return await target.followup.send(view=view)
        return await target.response.send_message(view=view)

    current = setup_ui.OfficialSetup.send_setup
    if not getattr(current, "_sentrix_invitation_v74_final", False):
        final_send_setup._sentrix_invitation_v74_final = True
        final_send_setup._sentrix_previous = current
        setup_ui.OfficialSetup.send_setup = final_send_setup

    command = bot.get_command("setup")
    if command is not None:
        command.ignore_extra = True


# ---------------------------------------------------------------------------
# CommandNotFound final : texte Discord brut, donc aucune bannière/embed.
# ---------------------------------------------------------------------------

def _unwrap_sender(sender):
    seen = set()
    current = sender
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _unknown_suggestions(bot: commands.Bot, typed: str) -> list[str]:
    typed = str(typed or "").casefold().strip()
    if not typed:
        return []
    names = []
    canonical = {}
    for command in bot.walk_commands():
        if getattr(command, "hidden", False):
            continue
        for value in (command.qualified_name, command.name, *(getattr(command, "aliases", ()) or ())):
            key = str(value or "").casefold().strip()
            if key:
                names.append(key)
                canonical[key] = command.qualified_name
    matches = difflib.get_close_matches(typed, list(dict.fromkeys(names)), n=4, cutoff=0.56)
    result = []
    for match in matches:
        name = canonical.get(match, match)
        if name not in result:
            result.append(name)
        if len(result) == 2:
            break
    return result


async def _raw_text(ctx: commands.Context, text: str):
    sender = _unwrap_sender(discord.abc.Messageable.send)
    return await sender(
        ctx.channel,
        text,
        allowed_mentions=discord.AllowedMentions.none(),
    )


def _patch_unknown_command_final(bot: commands.Bot) -> None:
    current = getattr(bot, "on_command_error", None)
    if not callable(current) or getattr(current, "_sentrix_plain_unknown_final", False):
        return

    async def final_error(self, ctx: commands.Context, error: commands.CommandError):
        base = getattr(error, "original", error)
        if isinstance(base, commands.CommandNotFound):
            prefix = str(getattr(ctx, "clean_prefix", None) or "+")
            typed = str(getattr(ctx, "invoked_with", "") or "").strip()
            shown = f"{prefix}{typed}" if typed else "cette commande"
            suggestions = _unknown_suggestions(self, typed)
            if suggestions:
                formatted = ", ".join(f"`{prefix}{name}`" for name in suggestions)
                text = f"Commande introuvable : `{shown}`\nVouliez-vous dire : {formatted} ?"
            else:
                text = f"Commande introuvable : `{shown}`\nUtilisez `{prefix}help` pour voir toutes les commandes."
            await _raw_text(ctx, text)
            return
        result = current(ctx, error)
        if inspect.isawaitable(result):
            return await result
        return result

    final_error._sentrix_plain_unknown_final = True
    final_error._sentrix_previous_error_handler = current
    bot.on_command_error = MethodType(final_error, bot)


# ---------------------------------------------------------------------------
# Dashboard final : gagne sur Oxyde et ferme explicitement le loader courant.
# ---------------------------------------------------------------------------

_DASHBOARD_FINAL_SCRIPT = r'''
<script id="sentrix-dashboard-final-loader-fix">
(() => {
  "use strict";
  if(window.__sentrixDashboardFinalLoaderFix)return;
  window.__sentrixDashboardFinalLoaderFix=true;
  let generation=0;
  let controller=null;

  const getState=()=>{try{return typeof state!=="undefined"?state:null}catch(_){return null}};
  const selected=()=>{
    const value=String(document.getElementById("serverSelect")?.value||"");
    return value && !value.startsWith("invite:") ? value : "";
  };
  const hideLoader=()=>{
    const empty=document.getElementById("emptyState");
    const content=document.getElementById("serverContent");
    if(empty)empty.classList.add("hidden");
    if(content){content.classList.remove("hidden");content.classList.remove("loading");}
  };
  const readyFor=id=>{
    const s=getState();
    return !!(s?.guildData && String(s.guildId||"")===String(id) && selected()===String(id));
  };
  const enforceReady=id=>{
    if(!readyFor(id))return false;
    hideLoader();
    try{renderTab()}catch(_){}
    return true;
  };
  const apply=(id,data)=>{
    if(selected()!==String(id))return false;
    const s=getState();
    if(!s||!data?.guild)return false;
    s.guildId=String(id);s.guildData=data;s.dirty=false;
    const set=(key,value)=>{const el=document.getElementById(key);if(el)el.textContent=value};
    const n=value=>Number(value||0).toLocaleString("fr-FR");
    set("pageTitle",data.guild.name||"Serveur");
    set("pageSubtitle",`${n(data.guild.members)} membres · ${data.guild.channels_count||0} salons · ${data.guild.roles_count||0} rôles`);
    set("metricMembers",n(data.guild.members));
    set("metricCommands",n(data.metrics?.commands_24h));
    set("metricTickets",n(data.metrics?.open_tickets));
    set("metricWarnings",n(data.metrics?.warnings));
    hideLoader();
    try{renderTab()}catch(_){}
    return true;
  };
  async function loadCurrent(force=false){
    const id=selected();
    if(!id)return;
    if(!force&&enforceReady(id))return;
    const my=++generation;
    if(controller)controller.abort();
    controller=new AbortController();
    try{
      const response=await fetch(`/api/guilds/${encodeURIComponent(id)}`,{credentials:"same-origin",cache:"no-store",signal:controller.signal});
      let data={};try{data=await response.json()}catch(_){}
      if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
      if(my!==generation||selected()!==id)return;
      apply(id,data);
    }catch(error){
      if(error?.name==="AbortError"||my!==generation||selected()!==id)return;
      console.warn("SentriX dashboard final loader recovery:",error);
    }finally{
      if(my===generation)controller=null;
    }
  }

  document.addEventListener("change",event=>{
    if(event.target?.id!=="serverSelect")return;
    ++generation;if(controller)controller.abort();
    const id=selected();
    setTimeout(()=>{if(selected()===id)loadCurrent(true)},100);
  },true);

  const repair=()=>{
    const id=selected();
    if(!id)return;
    if(enforceReady(id))return;
    const title=String(document.getElementById("pageTitle")?.textContent||"");
    const loaderVisible=!document.getElementById("emptyState")?.classList.contains("hidden");
    if(loaderVisible||title.startsWith("Chargement"))loadCurrent(false);
  };
  const start=()=>{
    [80,350,900,1800,3500].forEach(delay=>setTimeout(repair,delay));
    const root=document.getElementById("dashboard")||document.body;
    new MutationObserver(()=>setTimeout(repair,0)).observe(root,{childList:true,subtree:true,attributes:true,attributeFilter:["class"]});
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
</script>
'''


def _patch_dashboard_final() -> None:
    try:
        from web import dashboard
    except Exception:
        return
    html = getattr(dashboard, "INDEX_HTML", None)
    if not isinstance(html, str) or 'id="sentrix-dashboard-final-loader-fix"' in html:
        return
    if "</body>" in html:
        dashboard.INDEX_HTML = html.replace("</body>", _DASHBOARD_FINAL_SCRIPT + "\n</body>", 1)
    else:
        dashboard.INDEX_HTML = html + _DASHBOARD_FINAL_SCRIPT
    logger.info("Dashboard : garde final anti-loader bloqué installé.")


def _install_final_runtime(bot: commands.Bot) -> None:
    _patch_setup_v74(bot)
    _patch_unknown_command_final(bot)
    _patch_dashboard_final()


def _register_final_runtime(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_invitation_final_listener", False):
        return

    async def on_ready_final_repairs():
        _install_final_runtime(bot)

    bot.add_listener(on_ready_final_repairs, "on_ready")
    bot._sentrix_invitation_final_listener = True


def install(_bot) -> None:
    # Le listener doit être enregistré même si l'ancienne section a déjà été installée.
    _register_final_runtime(_bot)

    if not getattr(setup_ui, "_sentrix_invitation_section", False):
        _install_log_category()
        setup_ui.CATEGORIES[CATEGORY] = (
            LABEL,
            "Salon dédié aux logs d’invitations, inviteur détecté et changements de codes.",
        )
        order = list(setup_ui.CATEGORY_ORDER)
        if CATEGORY not in order:
            insert_at = order.index("logs") + 1 if "logs" in order else len(order)
            order.insert(insert_at, CATEGORY)
        setup_ui.CATEGORY_ORDER = tuple(order)
        setup_ui.BOT_PERMS[CATEGORY] = (
            "view_channel", "send_messages", "embed_links", "attach_files", "read_message_history"
        )
        _patch_statuses()
        _patch_render()
        _patch_embed()
        setup_ui._sentrix_invitation_section = True

    _patch_setup_entry(_bot)
    # Si l'installation arrive tard lors d'un reload, applique immédiatement aussi.
    _install_final_runtime(_bot)
