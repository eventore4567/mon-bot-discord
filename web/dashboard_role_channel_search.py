"""Recherche universelle des rôles et salons dans le dashboard SentriX.

Ajoute une barre de recherche à chaque sélecteur qui sert à choisir un rôle, un salon ou
une catégorie, y compris les sélecteurs ajoutés dynamiquement. Ne remplace aucune fonction
critique du dashboard et ne modifie pas les valeurs envoyées au backend.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.role-channel-search")
_INSTALLED = False

SEARCH_CSS = r"""
<style id="sentrix-role-channel-search-css">
  .sx-picker-search{display:grid;gap:7px;margin:0 0 8px;width:100%}
  .sx-picker-search-box{position:relative}
  .sx-picker-search-box::before{
    content:"⌕";position:absolute;left:12px;top:50%;transform:translateY(-50%);
    color:var(--muted,#949db5);font-size:18px;pointer-events:none;z-index:1
  }
  .sx-picker-search-input{
    width:100%!important;padding-left:38px!important;
    background:#0a0e18!important;border:1px solid #303852!important;
    border-radius:10px!important;min-height:40px!important
  }
  .sx-picker-search-input:focus{
    border-color:var(--brand,#7c6cff)!important;
    box-shadow:0 0 0 3px #7c6cff1f!important
  }
  .sx-picker-search-status{
    min-height:15px;color:var(--muted,#949db5);font-size:11px;line-height:1.35
  }
  .sx-picker-search-status.good{color:#70d9af}
  .sx-picker-search-status.warn{color:#e4b966}
</style>
"""

SEARCH_JS = r"""
<script id="sentrix-role-channel-search-js">
(() => {
  "use strict";
  if (window.__sentrixRoleChannelSearch) return;
  window.__sentrixRoleChannelSearch = true;

  const explicitKeys = new Set([
    "mod_role","admin_role","mute_role","verification_role","verify_role","autorole",
    "warn_role","member_role","booster_role","role_id",
    "log_channel","welcome_channel","goodbye_channel","rules_channel","verification_channel",
    "ticket_log_channel","level_channel","suggest_channel","announce_channel","giveaway_channel",
    "bot_commands_channel","report_channel","partner_channel","stats_channel","afk_channel",
    "error_channel","log_messages","log_members","log_voice","log_roles","log_server",
    "log_automod","log_moderation","ticket_category","discord_channel_id"
  ]);

  const explicitIds = new Set([
    "ticketPingRoleSelect","game_allowed_channels","game_blocked_channels",
    "game_allowed_roles","game_blocked_roles"
  ]);

  const excludedIds = new Set([
    "serverSelect","guild","sanctionFilter","game_difficulty"
  ]);

  const originalOptions = new WeakMap();

  function normalise(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase("fr")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function labelText(select) {
    const field = select.closest(".field,.card,.switch,.row");
    const label = field?.querySelector("label");
    return normalise(label?.textContent || select.getAttribute("aria-label") || "");
  }

  function semanticText(select) {
    return normalise([
      select.dataset.key,
      select.id,
      select.name,
      labelText(select)
    ].filter(Boolean).join(" "));
  }

  function pickerKind(select) {
    if (!(select instanceof HTMLSelectElement)) return null;
    if (excludedIds.has(select.id)) return null;
    const key = select.dataset.key || "";
    if (explicitKeys.has(key) || explicitIds.has(select.id)) {
      const text = semanticText(select);
      return /(^| )(role|roles)( |$)/.test(text) ? "role" : "channel";
    }

    const text = semanticText(select);
    if (/(^| )(role|roles)( |$)/.test(text)) return "role";
    if (/(salon|salons|channel|channels|categorie|categories|category)/.test(text)) return "channel";

    const optionTexts = [...select.options].slice(0, 12).map(o => normalise(o.textContent));
    if (optionTexts.some(text => /\b(text|voice|category|news|forum|stage)\b/.test(text))) return "channel";
    return null;
  }

  function remember(select) {
    if (originalOptions.has(select)) return;
    originalOptions.set(select, [...select.options].map((option, index) => ({option,index})));
  }

  function restore(select) {
    const saved = originalOptions.get(select);
    if (!saved) return;
    saved.sort((a,b) => a.index - b.index).forEach(item => {
      item.option.hidden = false;
      item.option.style.display = "";
      select.appendChild(item.option);
    });
  }

  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    let prev = Array.from({length:b.length + 1}, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const curr = [i];
      for (let j = 1; j <= b.length; j++) {
        curr[j] = Math.min(
          curr[j - 1] + 1,
          prev[j] + 1,
          prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
        );
      }
      prev = curr;
    }
    return prev[b.length];
  }

  function score(query, name) {
    if (!query) return 0;
    if (query === name) return 1000;
    if (name.startsWith(query)) return 900 - Math.min(100, name.length - query.length);
    const at = name.indexOf(query);
    if (at >= 0) return 800 - at * 5;
    const max = Math.max(query.length, name.length) || 1;
    return Math.round((1 - levenshtein(query, name) / max) * 500);
  }

  function filter(select, input, status, kind) {
    remember(select);
    const query = normalise(input.value);
    if (!query) {
      restore(select);
      status.textContent = `${Math.max(0, select.options.length - (select.multiple ? 0 : 1))} ${kind === "role" ? "rôle(s)" : "salon(s)"} disponible(s)`;
      status.className = "sx-picker-search-status";
      return;
    }

    const saved = originalOptions.get(select) || [];
    const candidates = saved.map(item => ({
      ...item,
      name: normalise(item.option.textContent),
      selected: item.option.selected
    })).map(item => ({...item, score: score(query, item.name)}));

    const placeholder = !select.multiple ? candidates.find(item => item.index === 0) : null;
    const ranked = candidates
      .filter(item => item !== placeholder)
      .sort((a,b) => (b.selected - a.selected) || b.score - a.score || a.index - b.index);

    const threshold = query.length <= 2 ? 420 : 260;
    let visible = ranked.filter(item => item.selected || item.score >= threshold).slice(0, 18);
    if (!visible.length) visible = ranked.slice(0, Math.min(8, ranked.length));

    const visibleSet = new Set(visible.map(item => item.option));
    if (placeholder) {
      placeholder.option.hidden = false;
      placeholder.option.style.display = "";
      select.appendChild(placeholder.option);
    }
    visible.forEach(item => {
      item.option.hidden = false;
      item.option.style.display = "";
      select.appendChild(item.option);
    });
    ranked.forEach(item => {
      if (!visibleSet.has(item.option)) {
        item.option.hidden = true;
        item.option.style.display = "none";
      }
    });

    const exact = visible.some(item => item.name === query);
    status.textContent = exact ? "Correspondance exacte trouvée" : `${visible.length} résultat(s) proche(s)`;
    status.className = `sx-picker-search-status ${exact ? "good" : "warn"}`;
  }

  function enhance(select) {
    const kind = pickerKind(select);
    if (!kind || select.dataset.sxSearchReady === "1") return;
    select.dataset.sxSearchReady = "1";
    remember(select);

    const input = document.createElement("input");
    input.type = "search";
    input.className = "sx-picker-search-input";
    input.placeholder = kind === "role" ? "Rechercher un rôle…" : "Rechercher un salon…";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.dataset.noDirty = "1";
    input.setAttribute("aria-label", input.placeholder);

    const box = document.createElement("div");
    box.className = "sx-picker-search-box";
    box.appendChild(input);

    const status = document.createElement("div");
    status.className = "sx-picker-search-status";

    const wrapper = document.createElement("div");
    wrapper.className = "sx-picker-search";
    wrapper.dataset.kind = kind;
    wrapper.append(box, status);

    select.parentNode?.insertBefore(wrapper, select);

    input.addEventListener("input", () => filter(select, input, status, kind));
    input.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        input.value = "";
        filter(select, input, status, kind);
        input.blur();
      }
      if (event.key === "Enter") {
        const first = [...select.options].find(option => !option.hidden && option.value);
        if (!first) return;
        event.preventDefault();
        if (!select.multiple) {
          select.value = first.value;
          select.dispatchEvent(new Event("change", {bubbles:true}));
        } else {
          first.selected = true;
          select.dispatchEvent(new Event("change", {bubbles:true}));
        }
      }
    });

    select.addEventListener("change", () => {
      if (!input.value) return;
      input.value = "";
      filter(select, input, status, kind);
    });

    filter(select, input, status, kind);
  }

  function scan(root = document) {
    root.querySelectorAll?.("select").forEach(enhance);
  }

  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches?.("select")) enhance(node);
        scan(node);
      }
    }
  });

  const start = () => {
    scan(document);
    observer.observe(document.body, {childList:true, subtree:true});
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();

  window.addEventListener("pageshow", () => scan(document));
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-role-channel-search-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", SEARCH_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", SEARCH_JS + "\n</body>", 1)
    return html


def install(dashboard, setup_center=None) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    if setup_center is not None:
        setup_center.SETUP_CENTER_HTML = _inject(setup_center.SETUP_CENTER_HTML)

    logger.info("Recherche universelle rôles/salons chargée sur tout le dashboard.")
