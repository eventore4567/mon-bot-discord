from __future__ import annotations

_INSTALLED = False

_MODAL_CSS = r"""
<style id="sentrix-confirm-modal-v47">
.sentrix-confirm-backdrop{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(3,5,10,.76);backdrop-filter:blur(7px);-webkit-backdrop-filter:blur(7px)}
.sentrix-confirm-backdrop.hidden{display:none!important}
.sentrix-confirm-card{width:min(440px,100%);background:linear-gradient(180deg,#171b29,#10131e);border:1px solid #303750;border-radius:20px;box-shadow:0 30px 100px rgba(0,0,0,.62);overflow:hidden;transform:translateY(0);animation:sentrixConfirmIn .16s ease-out}
@keyframes sentrixConfirmIn{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
.sentrix-confirm-body{padding:25px 25px 20px}.sentrix-confirm-title{font-size:20px;font-weight:850;letter-spacing:-.02em;margin:0 0 9px;color:#f2f4ff}.sentrix-confirm-text{margin:0;color:#a3abc0;line-height:1.6;font-size:14px}.sentrix-confirm-actions{display:flex;justify-content:flex-end;gap:10px;padding:17px 20px;border-top:1px solid #262d43;background:#0d1019}.sentrix-confirm-btn{border:1px solid #303850;border-radius:11px;padding:10px 16px;font:inherit;font-weight:750;cursor:pointer;color:#eef1ff;background:#171c2c;transition:.16s}.sentrix-confirm-btn:hover{transform:translateY(-1px);border-color:#505a7a}.sentrix-confirm-btn.primary{border-color:transparent;background:linear-gradient(135deg,#7c6cff,#5d4de1);box-shadow:0 10px 25px rgba(93,77,225,.24)}.sentrix-confirm-btn.danger{border-color:#713044;background:#3a1520;color:#ff9aaa}.sentrix-confirm-btn:focus-visible{outline:2px solid #a897ff;outline-offset:2px}
</style>
"""

_MODAL_HTML = r"""
<div id="sentrixConfirmBackdrop" class="sentrix-confirm-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="sentrixConfirmTitle" aria-describedby="sentrixConfirmText">
  <div class="sentrix-confirm-card">
    <div class="sentrix-confirm-body">
      <h2 id="sentrixConfirmTitle" class="sentrix-confirm-title">Confirmation</h2>
      <p id="sentrixConfirmText" class="sentrix-confirm-text">Confirmer cette action ?</p>
    </div>
    <div class="sentrix-confirm-actions">
      <button id="sentrixConfirmCancel" class="sentrix-confirm-btn" type="button">Annuler</button>
      <button id="sentrixConfirmOk" class="sentrix-confirm-btn primary" type="button">Confirmer</button>
    </div>
  </div>
</div>
"""

_MODAL_JS = r"""
<script id="sentrix-confirm-modal-js-v47">
(() => {
  "use strict";
  let pendingResolve = null;

  function closeSentrixConfirm(result) {
    const backdrop = document.getElementById("sentrixConfirmBackdrop");
    if (backdrop) backdrop.classList.add("hidden");
    const resolve = pendingResolve;
    pendingResolve = null;
    if (resolve) resolve(Boolean(result));
  }

  window.sentrixConfirm = function(message, options = {}) {
    const backdrop = document.getElementById("sentrixConfirmBackdrop");
    const title = document.getElementById("sentrixConfirmTitle");
    const text = document.getElementById("sentrixConfirmText");
    const ok = document.getElementById("sentrixConfirmOk");
    const cancel = document.getElementById("sentrixConfirmCancel");
    if (!backdrop || !title || !text || !ok || !cancel) return Promise.resolve(false);

    if (pendingResolve) {
      pendingResolve(false);
      pendingResolve = null;
    }

    title.textContent = options.title || "Confirmer l’action";
    text.textContent = String(message || "Confirmer cette action ?");
    ok.textContent = options.confirmText || "Confirmer";
    cancel.textContent = options.cancelText || "Annuler";
    ok.classList.toggle("danger", Boolean(options.danger));
    ok.classList.toggle("primary", !options.danger);
    backdrop.classList.remove("hidden");

    return new Promise(resolve => {
      pendingResolve = resolve;
      setTimeout(() => ok.focus(), 0);
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    const backdrop = document.getElementById("sentrixConfirmBackdrop");
    const ok = document.getElementById("sentrixConfirmOk");
    const cancel = document.getElementById("sentrixConfirmCancel");
    if (!backdrop || !ok || !cancel) return;
    ok.addEventListener("click", () => closeSentrixConfirm(true));
    cancel.addEventListener("click", () => closeSentrixConfirm(false));
    backdrop.addEventListener("click", event => {
      if (event.target === backdrop) closeSentrixConfirm(false);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !backdrop.classList.contains("hidden")) closeSentrixConfirm(false);
    });
  });
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    source = dashboard.INDEX_HTML
    if "sentrix-confirm-modal-v47" in source:
        return

    # Remplace la confirmation native du navigateur utilisée pour les sanctions.
    old = 'if(!confirm(`Confirmer : ${labels[action]||"effectuer cette action"} ?`))return;'
    new = 'if(!(await sentrixConfirm(`${labels[action]||"Effectuer cette action"} ?`,{title:"Confirmation de sanction",confirmText:"Confirmer",cancelText:"Annuler",danger:["unban","clear-warnings"].includes(action)})))return;'
    source = source.replace(old, new)

    if "</head>" in source:
        source = source.replace("</head>", _MODAL_CSS + "\n</head>", 1)
    if "</body>" in source:
        source = source.replace("</body>", _MODAL_HTML + "\n" + _MODAL_JS + "\n</body>", 1)

    dashboard.INDEX_HTML = source
