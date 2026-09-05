"""Correctifs ciblés du dashboard sans recopier le gros fichier web/dashboard.py.

Installé avant ``start_dashboard`` : les routes utilisent donc les fonctions corrigées et
la page HTML finale possède un chargement initial déterministe, un changement de serveur
atomique et un filet de récupération qui ne peut pas réafficher un ancien serveur.
"""
from __future__ import annotations

import logging

import discord


logger = logging.getLogger("bot.dashboard-runtime-patch")
MANAGE_GUILD = 1 << 5


async def _manager_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    """Accès dashboard : propriétaire, Administrateur ou Gérer le serveur."""
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


def _patch_initial_load(html: str) -> tuple[str, bool]:
    """Rend le premier chargement total : succès, liste vide et erreur ont tous une fin.

    L'ancienne version laissait ``Chargement des serveurs…`` dans le select si /api/guilds
    échouait, car loadSession avalait toute exception. Désormais l'état visuel est toujours
    nettoyé et l'utilisateur peut distinguer absence de serveur et erreur réseau/API.
    """
    start_marker = "    async function loadSession(){"
    end_marker = "    async function selectGuild(value){"
    start = html.find(start_marker)
    end = html.find(end_marker, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return html, False

    replacement = r'''    async function loadSession(){
      let authenticated=false;
      try{
        const me=await json("/api/me");
        authenticated=true;
        state.user=me.user;state.csrf=me.csrf;
        $("landing").classList.add("hidden");$("dashboard").classList.remove("hidden");
        $("userName").textContent=me.user.username;
        if(me.user.avatar_url)$("userAvatar").innerHTML=`<img class="avatar" src="${esc(me.user.avatar_url)}" alt="">`;
        await loadGuilds();
      }catch(e){
        if(!authenticated){
          if(location.pathname==="/app")history.replaceState({},"","/");
          return;
        }
        state.guilds=[];state.guildId=null;state.guildData=null;
        const select=$("serverSelect");
        select.disabled=false;
        select.innerHTML='<option value="">Impossible de charger les serveurs</option>';
        $("serverContent").classList.add("hidden");$("serverContent").classList.remove("loading");
        $("emptyState").classList.remove("hidden");
        $("emptyState").textContent="Impossible de charger vos serveurs. Réessayez dans un instant.";
        toast(String(e?.message||"Impossible de charger les serveurs."),true);
      }
    }
    async function loadGuilds(){
      const select=$("serverSelect");
      select.disabled=true;
      select.innerHTML='<option value="">Chargement des serveurs…</option>';
      $("serverContent").classList.add("hidden");$("serverContent").classList.remove("loading");
      $("emptyState").classList.remove("hidden");
      $("emptyState").textContent="Chargement de vos serveurs…";
      try{
        const data=await json("/api/guilds");
        state.guilds=Array.isArray(data.guilds)?data.guilds:[];
        select.innerHTML='<option value="">Choisissez un serveur</option>'+state.guilds.map(g=>`<option value="${g.installed?esc(g.id):"invite:"+esc(g.id)}">${esc(g.name)}${g.installed?"":" — ajouter SentriX"}</option>`).join("");
        const first=state.guilds.find(g=>g.installed);
        if(first){
          select.value=String(first.id);
          await selectGuild(String(first.id));
        }else{
          state.guildId=null;state.guildData=null;
          $("serverContent").classList.add("hidden");$("serverContent").classList.remove("loading");
          $("emptyState").classList.remove("hidden");
          $("emptyState").textContent=state.guilds.length
            ?"SentriX n’est encore installé sur aucun des serveurs que vous gérez. Choisissez-en un pour l’ajouter."
            :"Aucun serveur administrable n’a été trouvé sur ce compte Discord.";
        }
      }catch(e){
        state.guilds=[];state.guildId=null;state.guildData=null;
        select.innerHTML='<option value="">Erreur de chargement</option>';
        $("serverContent").classList.add("hidden");$("serverContent").classList.remove("loading");
        $("emptyState").classList.remove("hidden");
        $("emptyState").textContent="Impossible de charger vos serveurs. Réessayez dans un instant.";
        throw e;
      }finally{
        select.disabled=false;
      }
    }
'''
    return html[:start] + replacement + html[end:], True


def _patch_switch_html(html: str) -> tuple[str, bool]:
    start_marker = "    async function selectGuild(value){"
    end_marker = "    function optionList(type,current){"
    start = html.find(start_marker)
    end = html.find(end_marker, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return html, False
    replacement = r'''    async function selectGuild(value){
      state.guildLoadToken=(state.guildLoadToken||0)+1;
      const requestToken=state.guildLoadToken;
      if(!value){
        state.guildId=null;state.guildData=null;state.dirty=false;
        $("serverContent").classList.add("hidden");$("serverContent").classList.remove("loading");
        $("emptyState").classList.remove("hidden");
        $("emptyState").textContent="Sélectionnez un serveur pour commencer. Les serveurs sans SentriX proposent directement le bouton d’invitation.";
        return;
      }
      if(String(value).startsWith("invite:")){
        const id=String(value).slice(7),g=state.guilds.find(x=>String(x.id)===id);
        if(g?.invite_url)window.open(g.invite_url,"_blank","noopener");
        $("serverSelect").value=state.guildId||"";
        return;
      }
      value=String(value);
      state.guildId=value;state.guildData=null;state.dirty=false;
      $("emptyState").classList.add("hidden");
      $("serverContent").classList.remove("hidden");$("serverContent").classList.add("loading");
      $("pageTitle").textContent="Chargement du serveur…";
      $("pageSubtitle").textContent="Les données précédentes ont été retirées.";
      for(const id of ["metricMembers","metricCommands","metricTickets","metricWarnings"])$(id).textContent="—";
      $("fields").innerHTML='<div class="notification-empty">Chargement de ce serveur…</div>';
      try{
        const data=await json(`/api/guilds/${value}`);
        if(state.guildLoadToken!==requestToken||String(state.guildId)!==value)return;
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
        if(state.guildLoadToken===requestToken&&String(state.guildId)===value){
          state.guildData=null;
          $("serverContent").classList.add("hidden");
          $("emptyState").classList.remove("hidden");
          $("emptyState").textContent="Impossible de charger ce serveur. Sélectionnez-le à nouveau ou réessayez dans un instant.";
          toast(String(e?.message||"Impossible de charger ce serveur."),true);
        }
      }finally{
        if(state.guildLoadToken===requestToken&&String(state.guildId)===value)$("serverContent").classList.remove("loading");
      }
    }
'''
    return html[:start] + replacement + html[end:], True


def _patch_recovery_loader(html: str) -> tuple[str, bool]:
    """Le hotfix Oxyde possède son propre fetch différé : lui aussi doit ignorer le stale."""
    marker = '      if(!applyGuildData(id,data)) throw new Error("Les données du serveur ont été reçues mais leur affichage a échoué.");'
    if marker not in html:
        return html, False
    replacement = (
        '      const selectedNow=String(document.getElementById("serverSelect")?.value||"");\n'
        '      const stateNow=(typeof state!=="undefined"&&state)?String(state.guildId||""):"";\n'
        '      if((selectedNow&&!selectedNow.startsWith("invite:")&&selectedNow!==id)||(stateNow&&stateNow!==id)) return;\n'
        + marker
    )
    return html.replace(marker, replacement, 1), True


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

    html, initial_ok = _patch_initial_load(dashboard.INDEX_HTML)
    html, native_ok = _patch_switch_html(html)
    html, recovery_ok = _patch_recovery_loader(html)
    dashboard.INDEX_HTML = html
    if not initial_ok:
        logger.error("Correctif dashboard : chargeur initial loadSession/loadGuilds introuvable dans INDEX_HTML.")
    if not native_ok:
        logger.error("Correctif dashboard : chargeur natif selectGuild introuvable dans INDEX_HTML.")
    if not recovery_ok:
        logger.warning("Correctif dashboard : chargeur de récupération Oxyde introuvable ; garde native seule.")
    dashboard._sentrix_runtime_patch_installed = True
