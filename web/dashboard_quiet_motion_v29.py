"""Request-time minimal-motion skin for the real SentriX /app response.

The native dashboard already animates actual page navigation. Historical V25/V26/V27
controllers layered multiple MutationObservers, ripples and Web Animations on top.
Quiet mode keeps one short native page transition and static, low-cost surfaces.
No business logic, routes, persistence, polling or navigation is changed.
"""
from __future__ import annotations

STYLE_MARKER = "sentrix-dashboard-quiet-motion-v29"
FLAG_MARKER = "__sentrixQuietMotionV29"

STYLE = r'''<style id="sentrix-dashboard-quiet-motion-v29">
/* Keep the UI stable during live data updates and limit GPU pressure. */
:root{--sx29-ease:cubic-bezier(.2,.8,.2,1);--sx29-ui:140ms;--sx29-page:170ms}
body.dashboard-locked::before,
body.dashboard-locked::after,
body.dashboard-locked .workspace::before{
  display:none!important;animation:none!important;filter:none!important;will-change:auto!important;
}
body.dashboard-locked{
  background:radial-gradient(circle at 84% 0%,color-mix(in srgb,var(--blue) 5%,transparent),transparent 36%),var(--bg);
}
body.dashboard-locked .topbar,
body.dashboard-locked .sidebar,
body.dashboard-locked .server-rail{backdrop-filter:blur(7px) saturate(105%)}
#content.page-leave{opacity:1!important;transform:none!important;transition:none!important}
#content.page-enter{animation:sx29-page-in var(--sx29-page) var(--sx29-ease) both!important}
@keyframes sx29-page-in{
  from{opacity:.93;transform:translate3d(0,4px,0)}
  to{opacity:1;transform:none}
}
/* No repeated page/card bounce, ripple, flash or progress overlay. */
#content.sx25-page-in,#content.sx26-in,
.sx25-enter,.sx25-row-enter,.sx25-state-change,
.sx26-stagger,.sx26-row,.sx26-active-pop,.sx26-success{
  animation:none!important;transform:none!important;
}
.sx25-ripple,.sx26-ripple,.sx27-ring,#sx27Flash{display:none!important}
.cc-hero-glow,.cc-live.on i,.cc-pulse,.cc-event,
.startup-screen::before,.startup-screen::after,.startup-center::before{
  animation:none!important;will-change:auto!important;
}
.sx12-skeleton::after,.skeleton::after,[data-skeleton]::after{
  animation:none!important;opacity:.06;
}
:where(.card,.module-card,.row,.log-route-card,.nav button,.nav a.nav-link,
.subnav button,.btn,.profile,.top-search,.icon-btn){
  transition:background-color var(--sx29-ui) ease,border-color var(--sx29-ui) ease,
             color var(--sx29-ui) ease,box-shadow var(--sx29-ui) ease!important;
  will-change:auto!important;
}
@media(hover:hover) and (pointer:fine){
  :where(.btn,.nav button,.subnav button,.icon-btn):not(:disabled):hover{
    filter:brightness(1.035);
  }
}
:where(.btn,.nav button,.subnav button,.icon-btn):not(:disabled):active{
  filter:brightness(.95);transform:none!important;
}
:where(.card,.module-card,.log-route-card):hover{
  border-color:color-mix(in srgb,var(--blue) 17%,var(--line2));
}
@media(max-width:768px){
  :root{--sx29-page:125ms}
  body.dashboard-locked .topbar,body.dashboard-locked .sidebar,
  body.dashboard-locked .server-rail{backdrop-filter:none}
}
@media(prefers-reduced-motion:reduce){
  #content.page-enter{animation:none!important;transform:none!important;opacity:1!important}
  :where(.card,.module-card,.row,.nav button,.btn){transition:none!important}
}
</style>'''

BOOT = '''<script id="sentrix-dashboard-quiet-motion-v29-boot">
window.__sentrixQuietMotionV29=true;
</script>'''


def enhance(html: str) -> str:
    """Install once in <head>, before native V2 and old V25–V27 scripts execute."""
    if STYLE_MARKER in html:
        return html
    if "</head>" not in html:
        return html
    return html.replace("</head>", STYLE + "\n" + BOOT + "\n</head>", 1)


__all__ = ["STYLE_MARKER", "FLAG_MARKER", "STYLE", "BOOT", "enhance"]
