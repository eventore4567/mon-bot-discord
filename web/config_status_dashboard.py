"""Synchronisation des logs et indicateurs persistants de configuration du dashboard."""

from __future__ import annotations

import json
import logging

import discord
from aiohttp import web

from utils import log_service

logger = logging.getLogger("bot.dashboard.config-status")
_INSTALLED = False


LEGACY_LOG_TYPES = {
    "messages": "log_messages",
    "members": "log_members",
    "voice": "log_voice",
    "roles": "log_roles",
    "server": "log_server",
    "automod": "log_automod",
    "moderation": "log_moderation",
}


CONFIG_STATUS_CSS = r"""
    .config-label-row{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}
    .config-state{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;padding:4px 8px;border-radius:999px;border:1px solid #343d56;background:#151b2a;color:var(--muted);font-size:10px;font-weight:900;letter-spacing:.025em;text-transform:uppercase;line-height:1.1}
    .config-state.configured{border-color:#2f7d64;background:#12382e;color:#84e5c0}
    .config-state.pending{border-color:#896923;background:#3c3012;color:#ffd56b}
    .config-summary{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 16px;border:1px solid #2d3750;border-radius:13px;background:#111827}
    .config-summary-text{display:grid;gap:3px}.config-summary-text b{font-size:14px}.config-summary-text span{font-size:12px;color:var(--muted)}
    .config-summary-count{display:inline-flex;align-items:center;justify-content:center;min-width:86px;padding:8px 12px;border-radius:999px;background:#18243a;border:1px solid #38527c;color:#b9d3ff;font-weight:900;font-size:12px}
    .apply-general-logs{margin-top:9px;width:100%}
    @media(max-width:620px){.config-summary{align-items:flex-start;flex-direction:column}.config-summary-count{min-width:0}}
"""


CONFIG_STATUS_JS = r"""
    function configSerialise(element){
      if(!element)return "";
      if(element.type==="checkbox")return element.checked?"1":"0";
      return String(element.value??"");
    }
    function configHasValue(element){
      if(!element)return false;
      if(element.type==="checkbox")return Boolean(element.checked);
      return String(element.value??"").trim()!=="";
    }
    function configBadgeHost(field){
      const label=field.querySelector(":scope > label");
      if(!label)return null;
      if(label.classList.contains("switch"))return label.querySelector("b")?.parentElement||label;
      if(!label.classList.contains("config-label-row"))label.classList.add("config-label-row");
      return label;
    }
    function updateConfigState(element){
      const field=element?.closest(".field,.switch");
      if(!field)return;
      let badge=field.querySelector(":scope .config-state");
      const host=configBadgeHost(field);
      if(!host)return;
      if(!badge){badge=document.createElement("span");badge.className="config-state";host.appendChild(badge);}
      const saved=element.dataset.configSavedValue??configSerialise(element);
      const current=configSerialise(element);
      const changed=current!==saved;
      badge.classList.toggle("pending",changed);
      badge.classList.toggle("configured",!changed&&configHasValue(element));
      badge.textContent=changed?"À enregistrer":configHasValue(element)?"✓ Configuré":"Non configuré";
    }
    function updateConfigSummary(){
      const root=$("fields");if(!root)return;
      let summary=root.querySelector(":scope > .config-summary");
      if(state.tab!=="logs"){
        if(summary)summary.remove();
        return;
      }
      const selects=[...root.querySelectorAll('select[data-key^="log_"]')];
      if(!selects.length)return;
      if(!summary){
        summary=document.createElement("div");summary.className="config-summary";
        summary.innerHTML='<div class="config-summary-text"><b>État de la configuration</b><span>Les salons enregistrés restent affichés après chaque actualisation.</span></div><div class="config-summary-count"></div>';
        root.prepend(summary);
      }
      const configured=selects.filter(configHasValue).length;
      summary.querySelector(".config-summary-count").textContent=`${configured}/${selects.length} configurés`;
    }
    function installApplyGeneralLogs(){
      if(state.tab!=="logs")return;
      const general=$("fields")?.querySelector('select[data-key="log_channel"]');
      if(!general)return;
      const field=general.closest(".field");if(!field||field.querySelector(".apply-general-logs"))return;
      const button=document.createElement("button");button.type="button";button.className="btn primary apply-general-logs";button.textContent="Appliquer ce salon à tous les logs";
      button.addEventListener("click",()=>{
        if(!general.value){toast("Choisissez d'abord le salon de logs général.",true);return;}
        const selects=[...$("fields").querySelectorAll('select[data-key^="log_"]')].filter(select=>select!==general);
        selects.forEach(select=>{
          select.value=general.value;
          select.dispatchEvent(new Event("input",{bubbles:true}));
        });
        state.dirty=true;
        $("saveStatus").textContent="Salon appliqué à tous les logs — cliquez sur Enregistrer";
        updateConfigSummary();
        toast("Le salon a été appliqué partout. Enregistrez pour confirmer.");
      });
      field.appendChild(button);
    }
    function enhanceConfigurationStates(){
      const root=$("fields");if(!root)return;
      root.querySelectorAll("[data-key]").forEach(element=>{
        if(element.dataset.configStatusReady!=="1"){
          element.dataset.configStatusReady="1";
          element.dataset.configSavedValue=configSerialise(element);
        }
        updateConfigState(element);
      });
      installApplyGeneralLogs();
      updateConfigSummary();
    }
    document.addEventListener("input",event=>{
      const element=event.target;
      if(!(element instanceof Element)||!element.matches("[data-key]"))return;
      updateConfigState(element);updateConfigSummary();
    },true);
    document.addEventListener("change",event=>{
      const element=event.target;
      if(!(element instanceof Element)||!element.matches("[data-key]"))return;
      updateConfigState(element);updateConfigSummary();
    },true);
    const configStatusRoot=$("fields");
    if(configStatusRoot){
      const configStatusObserver=new MutationObserver(()=>enhanceConfigurationStates());
      configStatusObserver.observe(configStatusRoot,{childList:true,subtree:true});
      enhanceConfigurationStates();
    }
"""


def _response_payload(response: web.StreamResponse) -> dict | None:
    body = getattr(response, "body", None)
    if not body:
        return None
    try:
        return json.loads(body.decode(getattr(response, "charset", None) or "utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None


def _optional_id(value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    return int(value)


def _replace_once(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        logger.warning("Dashboard état configuré : point d'insertion introuvable (%s).", label)
        return html
    return html.replace(old, new, 1)


def _patch_html(html: str) -> str:
    html = _replace_once(
        html,
        "  </style>",
        CONFIG_STATUS_CSS + "\n  </style>",
        "css",
    )
    anchor = '    $("serverSelect").addEventListener("change",e=>selectGuild(e.target.value));'
    html = _replace_once(
        html,
        anchor,
        CONFIG_STATUS_JS + "\n" + anchor,
        "javascript",
    )
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_handle_guild = dashboard.handle_guild
    original_handle_update_guild = dashboard.handle_update_guild

    async def handle_guild(request: web.Request):
        response = await original_handle_guild(request)
        if getattr(response, "status", 500) != 200:
            return response
        data = _response_payload(response)
        if not isinstance(data, dict):
            return response
        try:
            guild_id = int(request.match_info["guild_id"])
            bot = request.app["bot"]
            all_logs = await log_service.get_all_log_settings(bot, guild_id)
        except Exception:
            logger.exception("Lecture des réglages de logs impossible depuis le dashboard.")
            return response

        serialised = {}
        settings = data.setdefault("settings", {})
        for log_type, setting in all_logs.items():
            serialised[log_type] = {
                "enabled": bool(setting.get("enabled")),
                "channel_id": str(setting["channel_id"]) if setting.get("channel_id") else None,
                "emits": bool(log_service.LOG_TYPES.get(log_type, {}).get("emits")),
            }
        data["log_settings"] = serialised

        historical_channels = []
        for log_type, legacy_column in LEGACY_LOG_TYPES.items():
            channel_id = all_logs.get(log_type, {}).get("channel_id")
            settings[legacy_column] = channel_id
            if channel_id:
                historical_channels.append(int(channel_id))
        if len(historical_channels) == len(LEGACY_LOG_TYPES) and len(set(historical_channels)) == 1:
            settings["log_channel"] = historical_channels[0]

        return web.json_response(data)

    async def handle_update_guild(request: web.Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        response = await original_handle_update_guild(request)
        if getattr(response, "status", 500) != 200 or not isinstance(payload, dict):
            return response

        settings = payload.get("settings", {})
        if not isinstance(settings, dict):
            return response
        relevant = {"log_channel", *LEGACY_LOG_TYPES.values()}
        if not relevant.intersection(settings):
            return response

        try:
            guild_id = int(request.match_info["guild_id"])
            guild = request.app["bot"].get_guild(guild_id)
            bot = request.app["bot"]
            general_present = "log_channel" in settings
            general_id = _optional_id(settings.get("log_channel")) if general_present else None

            for log_type, legacy_column in LEGACY_LOG_TYPES.items():
                if legacy_column in settings:
                    specific_id = _optional_id(settings.get(legacy_column))
                    channel_id = specific_id if specific_id is not None else general_id
                elif general_present:
                    channel_id = general_id
                else:
                    continue

                if channel_id is not None:
                    channel = guild.get_channel(channel_id) if guild else None
                    if not isinstance(channel, discord.TextChannel):
                        logger.warning(
                            "Dashboard : le salon %s n'est pas textuel, synchronisation du log %s ignorée.",
                            channel_id, log_type,
                        )
                        continue
                await log_service.set_log_channel(bot, guild_id, log_type, channel_id)
                await log_service.set_log_enabled(bot, guild_id, log_type, channel_id is not None)
        except Exception:
            logger.exception("Synchronisation des réglages de logs impossible depuis le dashboard.")
            return dashboard._json_error(
                "La configuration générale a été enregistrée, mais la synchronisation des logs a échoué. Réessayez.",
                500,
            )
        return response

    dashboard.handle_guild = handle_guild
    dashboard.handle_update_guild = handle_update_guild
    dashboard.INDEX_HTML = _patch_html(dashboard.INDEX_HTML)
    logger.info("Synchronisation et indicateurs persistants de configuration chargés.")
