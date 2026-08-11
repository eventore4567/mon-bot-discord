"""Micro-interactions visuelles et sonores légères pour les boutons du dashboard."""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.button-feedback")


FEEDBACK_CSS = r"""
<style id="sentrix-button-feedback-css">
  button,.btn,a.btn,[role="button"]{
    transform-origin:center;
    transition:
      transform .14s cubic-bezier(.2,.8,.2,1),
      filter .14s ease,
      box-shadow .14s ease,
      border-color .14s ease;
  }
  @media (hover:hover) and (pointer:fine){
    button:not(:disabled):hover,
    .btn:not([aria-disabled="true"]):hover,
    a.btn:hover,
    [role="button"]:not([aria-disabled="true"]):hover{
      transform:translateY(-2px) scale(1.035);
      filter:brightness(1.06);
      box-shadow:0 9px 24px rgba(0,0,0,.22);
    }
  }
  button:not(:disabled):active,
  .btn:not([aria-disabled="true"]):active,
  a.btn:active,
  [role="button"]:not([aria-disabled="true"]):active{
    transform:translateY(0) scale(.975);
    transition-duration:.07s;
  }
  @media (prefers-reduced-motion:reduce){
    button,.btn,a.btn,[role="button"]{transition:none!important}
    button:hover,.btn:hover,a.btn:hover,[role="button"]:hover,
    button:active,.btn:active,a.btn:active,[role="button"]:active{transform:none!important}
  }
</style>
"""


FEEDBACK_JS = r"""
<script id="sentrix-button-feedback-js">
(() => {
  "use strict";
  if (window.__sentrixButtonFeedback) return;
  window.__sentrixButtonFeedback = true;

  const interactiveSelector = 'button,.btn,a.btn,[role="button"]';
  const canHover = window.matchMedia && window.matchMedia('(hover:hover) and (pointer:fine)').matches;
  let audioContext = null;
  let unlocked = false;
  let lastSoundAt = 0;

  function isDisabled(node){
    return !node || node.disabled || node.getAttribute('aria-disabled') === 'true' || node.classList.contains('disabled');
  }

  function context(){
    if (audioContext) return audioContext;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    try { audioContext = new AudioCtx(); } catch (_) { audioContext = null; }
    return audioContext;
  }

  async function unlockAudio(){
    const ctx = context();
    if (!ctx) return;
    try {
      if (ctx.state === 'suspended') await ctx.resume();
      unlocked = ctx.state === 'running';
    } catch (_) {}
  }

  function hoverTick(){
    if (!unlocked || !canHover) return;
    const now = performance.now();
    if (now - lastSoundAt < 55) return;
    lastSoundAt = now;

    const ctx = context();
    if (!ctx || ctx.state !== 'running') return;
    try {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(690, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(820, ctx.currentTime + .045);
      gain.gain.setValueAtTime(.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(.018, ctx.currentTime + .008);
      gain.gain.exponentialRampToValueAtTime(.0001, ctx.currentTime + .055);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + .06);
    } catch (_) {}
  }

  // Les navigateurs bloquent l'audio avant le premier geste utilisateur. Un seul clic/tap
  // déverrouille donc Web Audio ; ensuite le petit son se joue au survol des boutons.
  document.addEventListener('pointerdown', unlockAudio, {capture:true, passive:true});
  document.addEventListener('keydown', unlockAudio, {capture:true});

  document.addEventListener('pointerover', event => {
    if (!canHover) return;
    const node = event.target && event.target.closest ? event.target.closest(interactiveSelector) : null;
    if (!node || isDisabled(node)) return;
    const previous = event.relatedTarget;
    if (previous && node.contains(previous)) return;
    hoverTick();
  }, {capture:true, passive:true});
})();
</script>
"""


def _inject(value: str) -> str:
    if not isinstance(value, str):
        return value
    if 'id="sentrix-button-feedback-js"' in value:
        return value
    if "</body>" not in value:
        return value
    if "</head>" in value:
        value = value.replace("</head>", FEEDBACK_CSS + "\n</head>", 1)
    return value.replace("</body>", FEEDBACK_JS + "\n</body>", 1)


def install(*modules) -> None:
    """Injecte le feedback dans toutes les pages HTML connues, sans toucher à leur logique."""
    changed = 0
    for module in modules:
        if module is None:
            continue
        for name in tuple(vars(module)):
            if name != "INDEX_HTML" and not name.endswith("_HTML"):
                continue
            value = getattr(module, name, None)
            updated = _inject(value)
            if updated != value:
                setattr(module, name, updated)
                changed += 1
    logger.info("Feedback boutons dashboard installé sur %s page(s).", changed)
