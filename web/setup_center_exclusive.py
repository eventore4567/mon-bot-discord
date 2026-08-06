"""Rend les listes autorisées/bloquées du Centre Setup mutuellement exclusives."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.setup-center-exclusive")
_INSTALLED = False


EXCLUSIVE_UI = r"""
<style>
  select[multiple] option:checked{
    color:#fff;
    background:linear-gradient(135deg,#7c6cff,#5142ca);
    font-weight:800;
  }
  .exclusive-help{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:10px;
    margin-top:7px;
    color:var(--muted);
    font-size:12px;
    line-height:1.4;
  }
  .exclusive-count{
    flex:0 0 auto;
    padding:3px 8px;
    border:1px solid #3b4666;
    border-radius:999px;
    background:#151b2a;
    color:#cbd3ea;
    font-weight:900;
  }
  .exclusive-count.active{
    border-color:#6f62da;
    background:#292052;
    color:#ddd8ff;
  }
</style>
<script>
(() => {
  const pairs = [
    ["game_allowed_channels", "game_blocked_channels", "salon"],
    ["game_allowed_roles", "game_blocked_roles", "rôle"]
  ];
  const originals = new WeakMap();

  function selectedValues(select) {
    return new Set([...select.selectedOptions].map(option => String(option.value)));
  }

  function remember(select) {
    if (originals.has(select)) return;
    originals.set(select, [...select.options].map(option => ({
      value: String(option.value),
      text: option.textContent || ""
    })));
  }

  function rebuild(select, forbidden) {
    remember(select);
    const selected = selectedValues(select);
    const entries = originals.get(select) || [];
    const scrollTop = select.scrollTop;
    select.replaceChildren();
    for (const entry of entries) {
      if (forbidden.has(entry.value)) continue;
      const option = document.createElement("option");
      option.value = entry.value;
      option.textContent = entry.text;
      option.selected = selected.has(entry.value);
      select.appendChild(option);
    }
    select.scrollTop = scrollTop;
  }

  function installHelp(select, noun, side) {
    const field = select.closest(".field");
    if (!field) return null;
    let help = field.querySelector(`.exclusive-help[data-for="${select.id}"]`);
    if (!help) {
      help = document.createElement("div");
      help.className = "exclusive-help";
      help.dataset.for = select.id;
      help.innerHTML = `<span>Maintenez <b>Cmd</b> sur Mac pour choisir plusieurs ${noun}s. Un élément choisi ici disparaît automatiquement de l’autre liste.</span><span class="exclusive-count">0 choisi</span>`;
      field.appendChild(help);
      const label = field.querySelector("label");
      if (label && !label.dataset.baseLabel) label.dataset.baseLabel = label.textContent || side;
    }
    return help;
  }

  function updateCount(select, noun, side) {
    const count = select.selectedOptions.length;
    const help = installHelp(select, noun, side);
    const badge = help?.querySelector(".exclusive-count");
    if (badge) {
      badge.textContent = `${count} choisi${count > 1 ? "s" : ""}`;
      badge.classList.toggle("active", count > 0);
    }
    const label = select.closest(".field")?.querySelector("label");
    if (label) label.textContent = `${label.dataset.baseLabel || side} — ${count}`;
  }

  function refreshPair(left, right, noun, changed) {
    remember(left);
    remember(right);

    if (changed === left) {
      const chosen = selectedValues(left);
      [...right.options].forEach(option => {
        if (chosen.has(String(option.value))) option.selected = false;
      });
    } else if (changed === right) {
      const chosen = selectedValues(right);
      [...left.options].forEach(option => {
        if (chosen.has(String(option.value))) option.selected = false;
      });
    } else {
      const allowed = selectedValues(left);
      [...right.options].forEach(option => {
        if (allowed.has(String(option.value))) option.selected = false;
      });
    }

    const leftSelected = selectedValues(left);
    const rightSelected = selectedValues(right);
    rebuild(left, rightSelected);
    rebuild(right, leftSelected);
    updateCount(left, noun, "Autorisés");
    updateCount(right, noun, "Bloqués");
  }

  function bindPair(leftId, rightId, noun) {
    const left = document.getElementById(leftId);
    const right = document.getElementById(rightId);
    if (!(left instanceof HTMLSelectElement) || !(right instanceof HTMLSelectElement)) return;
    if (left.dataset.exclusiveReady === "1" && right.dataset.exclusiveReady === "1") return;

    left.dataset.exclusiveReady = "1";
    right.dataset.exclusiveReady = "1";
    left.addEventListener("change", () => refreshPair(left, right, noun, left));
    right.addEventListener("change", () => refreshPair(left, right, noun, right));
    refreshPair(left, right, noun, null);
  }

  function bindAll() {
    for (const [left, right, noun] of pairs) bindPair(left, right, noun);
  }

  const content = document.getElementById("content");
  if (content) {
    new MutationObserver(bindAll).observe(content, {childList:true});
  }
  bindAll();
})();
</script>
"""


def _inject_ui(html: str) -> str:
    marker = "</body>"
    if marker not in html:
        logger.warning("Centre Setup : insertion de l'interface exclusive impossible.")
        return html
    return html.replace(marker, EXCLUSIVE_UI + "\n" + marker, 1)


def install(setup_center, setup_dashboard) -> None:
    """Installe l'interface exclusive et une validation serveur anti-doublon."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_center = setup_center.handle_setup_center
    original_save_games = setup_dashboard.handle_save_games

    async def handle_setup_center(request: web.Request) -> web.Response:
        response = await original_center(request)
        text = response.text or ""
        response.text = _inject_ui(text)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    async def handle_save_games(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"ok": False, "error": "Le formulaire envoyé est invalide."},
                status=400,
            )

        allowed_channels = {str(value) for value in payload.get("allowed_channel_ids", [])}
        blocked_channels = {str(value) for value in payload.get("blocked_channel_ids", [])}
        allowed_roles = {str(value) for value in payload.get("allowed_role_ids", [])}
        blocked_roles = {str(value) for value in payload.get("blocked_role_ids", [])}

        if allowed_channels & blocked_channels:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Un même salon ne peut pas être autorisé et bloqué en même temps.",
                },
                status=400,
            )
        if allowed_roles & blocked_roles:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Un même rôle ne peut pas être autorisé et bloqué en même temps.",
                },
                status=400,
            )
        return await original_save_games(request)

    setup_center.handle_setup_center = handle_setup_center
    setup_dashboard.handle_save_games = handle_save_games
    logger.info("Listes autorisées/bloquées exclusives chargées.")
