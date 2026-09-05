"""Correctifs ciblés du dashboard sans recopier le gros fichier web/dashboard.py.

Installé avant ``start_dashboard`` : les routes utilisent donc les fonctions corrigées et
la page HTML finale contient le sélecteur de serveur isolé contre les réponses réseau
arrivant dans le désordre.
"""
from __future__ import annotations

import discord


MANAGE_GUILD = 1 << 5


async def _manager_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    perms = member.guild_permissions
    if guild.owner_id == user_id or perms.administrator or perms.manage_guild:
        return member
    return None


def _patch_switch_html(html: str) -> str:
    start_token = "    async function selectGuild(value){"
    end_token = "    function optionList(type,current){"
    start = html.find(start_token)
    end = html.find(end_token, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return html
    replacement = r'''    async function selectGuild(value){
      state.guildLoadToken=(state.guildLoadToken||0)+1;
      const requestToken=state.guildLoadToken;
      if(!value){
        state.guildId=null;state.guildData=null;
        $("serverContent").classList.add("hidden");$("serverContent").classList.remove("loading");
        $("emptyState").classList.remove("hidden");
        return;
      }
      if(String(value).startsWith("invite:")){
        const id=String(value).slice(7),g=state.guilds.find(x=>x.id===id);
        if(g?.invite_url)window.open(g.invite_url,"_blank","noopener");
        $("serverSelect").value=state.guildId||"";
        return;
      }
      state.guildId=String(value);state.guildData=null;state.dirty=false;
      $("serverContent").classList.add("loading");
      $("pageTitle").textContent="Chargement du serveur…";
      $("pageSubtitle").textContent="Les données précédentes ont été retirées.";
      for(const id of ["metricMembers","metricCommands","metricTickets","metricWarnings"])$(id).textContent="—";
      $("fields").innerHTML='<div class="notification-empty">Chargement de ce serveur…</div>';
      try{
        const data=await json(`/api/guilds/${value}`);
        if(state.guildLoadToken!==requestToken||String(state.guildId)!==String(value))return;
        state.guildData=data;
        const d=data;
        $("pageTitle").textContent=d.guild.name;
        $("pageSubtitle").textContent=`${number(d.guild.members)} membres · ${d.guild.channels_count} salons · ${d.guild.roles_count} rôles`;
        $("metricMembers").textContent=number(d.guild.members);
        $("metricCommands").textContent=number(d.metrics.commands_24h);
        $("metricTickets").textContent=number(d.metrics.open_tickets);
        $("metricWarnings").textContent=number(d.metrics.warnings);
        $("emptyState").classList.add("hidden");$("serverContent").classList.remove("hidden");
        renderTab();
      }catch(e){
        if(state.guildLoadToken===requestToken&&String(state.guildId)===String(value))toast(e.message,true);
      }finally{
        if(state.guildLoadToken===requestToken&&String(state.guildId)===String(value))$("serverContent").classList.remove("loading");
      }
    }
'''
    return html[:start] + replacement + html[end:]


def install() -> None:
    from web import dashboard

    if getattr(dashboard, "_sentrix_runtime_patch_installed", False):
        return

    # Le filtre OAuth utilisait seulement le bit Administrateur. Avec ce masque, la
    # condition existante accepte aussi « Gérer le serveur » ; les propriétaires restent
    # acceptés par le test owner déjà présent.
    dashboard.ADMINISTRATOR = (1 << 3) | MANAGE_GUILD
    # Toutes les lectures/écritures API repassent ensuite par cette vérification live ;
    # perdre la permission retire donc immédiatement l'accès, même avec une session ouverte.
    dashboard._administrator_member = _manager_member
    dashboard.INDEX_HTML = _patch_switch_html(dashboard.INDEX_HTML)
    dashboard._sentrix_runtime_patch_installed = True
