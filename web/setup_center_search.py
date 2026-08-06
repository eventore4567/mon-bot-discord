"""Ajoute une recherche intelligente aux listes de salons du Centre Setup."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.setup-center-search")
_INSTALLED = False


SEARCH_UI = r"""
<style>
  .setup-channel-search{
    position:relative;
    margin:0 0 8px;
  }
  .setup-channel-search input{
    padding-left:38px;
  }
  .setup-channel-search::before{
    content:"⌕";
    position:absolute;
    left:13px;
    top:50%;
    transform:translateY(-50%);
    color:var(--muted);
    font-size:18px;
    pointer-events:none;
  }
  .setup-channel-search-status{
    margin:6px 0 0;
    color:var(--muted);
    font-size:12px;
    min-height:17px;
  }
  .setup-channel-search-status.exact{
    color:#8be4c3;
    font-weight:800;
  }
</style>
<script>
(() => {
  const targets = [
    ["game_allowed_channels", "Rechercher un salon autorisé…"],
    ["game_blocked_channels", "Rechercher un salon bloqué…"]
  ];
  const originalOrder = new WeakMap();

  function normalise(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function levenshtein(left, right) {
    if (left === right) return 0;
    if (!left.length) return right.length;
    if (!right.length) return left.length;
    const previous = Array.from({length:right.length + 1}, (_, index) => index);
    const current = new Array(right.length + 1);
    for (let i = 1; i <= left.length; i += 1) {
      current[0] = i;
      for (let j = 1; j <= right.length; j += 1) {
        const cost = left[i - 1] === right[j - 1] ? 0 : 1;
        current[j] = Math.min(
          current[j - 1] + 1,
          previous[j] + 1,
          previous[j - 1] + cost
        );
      }
      for (let j = 0; j <= right.length; j += 1) previous[j] = current[j];
    }
    return previous[right.length];
  }

  function score(name, query) {
    if (!query) return 0;
    if (name === query) return -1000;
    if (name.startsWith(query)) return -500 + (name.length - query.length);
    const containedAt = name.indexOf(query);
    if (containedAt >= 0) return -300 + containedAt;

    const queryWords = query.split(" ").filter(Boolean);
    const nameWords = name.split(" ").filter(Boolean);
    let tokenScore = 0;
    for (const word of queryWords) {
      let best = Infinity;
      for (const candidate of nameWords) {
        if (candidate.startsWith(word)) best = Math.min(best, 0);
        else if (candidate.includes(word)) best = Math.min(best, 1);
        else best = Math.min(best, levenshtein(word, candidate));
      }
      tokenScore += best;
    }
    return tokenScore * 20 + levenshtein(query, name);
  }

  function rememberOrder(select) {
    if (originalOrder.has(select)) return;
    const order = new Map();
    [...select.options].forEach((option, index) => order.set(String(option.value), index));
    originalOrder.set(select, order);
  }

  function restoreOrder(select) {
    const order = originalOrder.get(select);
    if (!order) return;
    [...select.options]
      .sort((a, b) => (order.get(String(a.value)) ?? 99999) - (order.get(String(b.value)) ?? 99999))
      .forEach(option => select.appendChild(option));
  }

  function filter(select, input, status) {
    rememberOrder(select);
    const query = normalise(input.value);
    const options = [...select.options];

    if (!query) {
      restoreOrder(select);
      options.forEach(option => {
        option.hidden = false;
        option.style.display = "";
      });
      status.textContent = `${options.length} salons disponibles`;
      status.classList.remove("exact");
      return;
    }

    const ranked = options.map(option => {
      const name = normalise(option.textContent);
      return {option, name, score:score(name, query)};
    }).sort((a, b) => a.score - b.score);

    const exact = ranked.find(item => item.name === query);
    const maximum = query.length <= 3 ? 45 : Math.max(35, query.length * 18);
    let matches = ranked.filter(item => item.score < 0 || item.score <= maximum).slice(0, 8);
    if (!matches.length) matches = ranked.slice(0, Math.min(6, ranked.length));
    const visible = new Set(matches.map(item => item.option));

    ranked.forEach(item => {
      item.option.hidden = !visible.has(item.option);
      item.option.style.display = visible.has(item.option) ? "" : "none";
    });
    ranked.forEach(item => select.appendChild(item.option));

    if (exact) {
      status.textContent = "✓ Salon exact trouvé";
      status.classList.add("exact");
    } else {
      status.textContent = `${matches.length} salon${matches.length > 1 ? "s" : ""} proche${matches.length > 1 ? "s" : ""}`;
      status.classList.remove("exact");
    }

    if (matches[0]?.option) select.scrollTop = 0;
  }

  function bind(selectId, placeholder) {
    const select = document.getElementById(selectId);
    if (!(select instanceof HTMLSelectElement) || select.dataset.searchReady === "1") return;
    select.dataset.searchReady = "1";

    const field = select.closest(".field");
    if (!field) return;
    const wrapper = document.createElement("div");
    wrapper.className = "setup-channel-search";
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = placeholder;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("aria-label", placeholder);
    wrapper.appendChild(input);

    const status = document.createElement("div");
    status.className = "setup-channel-search-status";

    field.insertBefore(wrapper, select);
    field.insertBefore(status, select.nextSibling);

    input.addEventListener("input", () => filter(select, input, status));
    input.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      const first = [...select.options].find(option => !option.hidden);
      if (!first) return;
      first.selected = true;
      select.dispatchEvent(new Event("change", {bubbles:true}));
      input.value = "";
      setTimeout(() => filter(select, input, status), 0);
    });
    filter(select, input, status);
  }

  function bindAll() {
    for (const [selectId, placeholder] of targets) bind(selectId, placeholder);
  }

  const content = document.getElementById("content");
  if (content) new MutationObserver(bindAll).observe(content, {childList:true});
  bindAll();
})();
</script>
"""


def _inject_search(html: str) -> str:
    marker = "</body>"
    if marker not in html:
        logger.warning("Centre Setup : insertion de la recherche de salons impossible.")
        return html
    return html.replace(marker, SEARCH_UI + "\n" + marker, 1)


def install(setup_center) -> None:
    """Ajoute la recherche sans modifier le JavaScript principal du Centre Setup."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_handle_setup_center = setup_center.handle_setup_center

    async def handle_setup_center(request: web.Request) -> web.Response:
        response = await original_handle_setup_center(request)
        response.text = _inject_search(response.text or "")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    setup_center.handle_setup_center = handle_setup_center
    logger.info("Recherche intelligente des salons du Centre Setup chargée.")
