"""V5.2 compact readability pass for the SentriX dashboard.

This final layer keeps the clearer V5.1 structure and makes it feel slightly zoomed out:
more content fits on screen, without using browser zoom or making controls hard to read.
"""

from __future__ import annotations


COMPACT_V52_CSS = r"""
<style id="sentrix-dashboard-v52-compact-css">
  /* Slightly denser desktop scale — visual equivalent of a small zoom-out. */
  #dashboard{font-size:14px!important}
  #dashboard .shell{grid-template-columns:248px minmax(0,1fr)!important}

  #dashboard .side{padding-left:12px!important;padding-right:12px!important}
  #dashboard .side .brand{
    height:70px!important;
    margin-left:-12px!important;margin-right:-12px!important;
    padding-left:17px!important;padding-right:17px!important;
    font-size:18px!important;
  }
  #dashboard .side .brand-logo{width:38px!important;height:38px!important;border-radius:12px!important}
  #dashboard .side .user{margin:5px 0 11px!important;padding:9px 10px!important;border-radius:11px!important}
  #dashboard .side .user .brand-logo{width:33px!important;height:33px!important}
  #dashboard .sx-nav-group{padding:14px 9px 5px!important;font-size:9px!important}
  #dashboard #navigation button{
    min-height:39px!important;padding:8px 11px!important;border-radius:9px!important;
    font-size:12.5px!important;
  }
  #dashboard .side-bottom{padding-top:10px!important}
  #dashboard .side-bottom .btn{min-height:35px!important;font-size:11.5px!important}

  #dashboard .sx-topbar{height:58px!important;padding-left:27px!important;padding-right:27px!important}
  #dashboard .sx-breadcrumb{font-size:11px!important}
  #dashboard .sx-top-status{height:31px!important;padding:0 11px!important;font-size:10px!important}
  #dashboard .sx-top-save{height:33px!important;padding:0 13px!important;font-size:12px!important}

  #dashboard .workspace-head{
    padding:21px 27px 19px!important;
    gap:20px!important;
  }
  #dashboard .workspace-head h1{font-size:27px!important}
  #dashboard .workspace-head p{font-size:12px!important;line-height:1.45!important}
  .sx-server-box{min-width:275px!important}
  #dashboard .server-select{height:41px!important;font-size:13px!important;padding-top:8px!important;padding-bottom:8px!important}

  #dashboard #serverContent{padding:0 27px 58px!important}
  #dashboard .fields{gap:11px!important}
  #dashboard .sx-section-head{padding:21px 0 5px!important}
  #dashboard .sx-section-head h2{font-size:21px!important}
  #dashboard .sx-section-head p{margin-top:5px!important;font-size:12px!important;max-width:680px!important}

  /* Compact settings cards while preserving clear hit targets. */
  #dashboard .field,#dashboard label.switch{
    padding:17px!important;
    border-radius:12px!important;
  }
  #dashboard .field label,#dashboard label.switch b{font-size:13px!important}
  #dashboard .field .hint,#dashboard label.switch span{margin-top:5px!important;font-size:11px!important;line-height:1.42!important}
  #dashboard .select,#dashboard input:not([type="checkbox"]),#dashboard textarea{
    margin-top:8px!important;
    min-height:40px!important;
    padding:9px 11px!important;
    border-radius:9px!important;
    font-size:13px!important;
  }
  #dashboard textarea{min-height:96px!important}
  #dashboard label.switch{min-height:64px!important;gap:18px!important}
  #dashboard label.switch input[type="checkbox"]{width:40px!important;height:22px!important}

  #dashboard .savebar{
    bottom:10px!important;
    margin-top:13px!important;
    padding:9px 11px!important;
    border-radius:10px!important;
  }
  #dashboard .save-status{font-size:11px!important}
  #dashboard .savebar .btn.primary{min-width:112px!important;min-height:36px!important;font-size:12px!important}

  /* Overview fits substantially more useful information above the fold. */
  .sx-v51-overview{gap:13px!important;padding-top:20px!important}
  .sx-v51-head{
    padding:20px!important;
    gap:18px!important;
    border-radius:15px!important;
  }
  .sx-v51-server{gap:13px!important}
  .sx-v51-avatar{width:52px!important;height:52px!important;flex-basis:52px!important;border-radius:13px!important;font-size:19px!important}
  .sx-v51-server h2{font-size:22px!important}
  .sx-v51-server p{margin-top:5px!important;font-size:12px!important;line-height:1.42!important}
  .sx-v51-ready strong{font-size:24px!important}

  .sx-v51-stats{gap:9px!important}
  .sx-v51-stat{padding:14px!important;border-radius:12px!important}
  .sx-v51-stat small{font-size:9px!important}
  .sx-v51-stat strong{margin-top:6px!important;font-size:21px!important}
  .sx-v51-stat span{font-size:10px!important}

  .sx-v51-title{margin:3px 0 -2px!important;font-size:16px!important}
  .sx-v51-title span{margin-top:3px!important;font-size:11px!important}
  .sx-v51-grid{gap:10px!important}
  .sx-v51-card{padding:17px!important;border-radius:13px!important}
  .sx-v51-card small{font-size:8px!important}
  .sx-v51-card h3{margin:6px 0 5px!important;font-size:16px!important}
  .sx-v51-card p{font-size:11px!important;line-height:1.45!important}
  .sx-v51-actions{gap:6px!important;margin-top:13px!important}
  .sx-v51-actions button{min-height:34px!important;padding:0 10px!important;border-radius:8px!important;font-size:11px!important}

  /* At large desktop widths, show the four main destinations in one clean row. */
  @media(min-width:1380px){
    .sx-v51-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important}
    .sx-v51-card{min-height:165px;display:flex;flex-direction:column}
    .sx-v51-actions{margin-top:auto!important;padding-top:12px!important}
  }

  /* Lists and moderation also become easier to scan. */
  #dashboard .sanction-toolbar{padding:9px!important;gap:8px!important}
  #dashboard .sanction-card,#dashboard .notification-item,#dashboard .notification-empty{border-radius:11px!important}
  #dashboard .sanction-head,#dashboard .sanction-body{padding-left:15px!important;padding-right:15px!important}
  #dashboard .sanction-body p,#dashboard .notification-item span{font-size:11px!important}
  #dashboard .notification-builder{gap:11px!important}

  .sx-v5-discord-preview{padding:14px!important;border-radius:12px!important}
  .sx-v5-discord-text{font-size:11px!important}

  @media(max-width:1100px){
    #dashboard .shell{grid-template-columns:235px minmax(0,1fr)!important}
    .sx-server-box{min-width:245px!important}
  }
  @media(max-width:980px){
    #dashboard{font-size:14px!important}
    #dashboard .shell{grid-template-columns:1fr!important}
    #dashboard .workspace-head,#dashboard #serverContent{padding-left:18px!important;padding-right:18px!important}
    #dashboard .sx-topbar{padding-left:18px!important;padding-right:18px!important}
    #dashboard .workspace-head{padding-top:20px!important}
    .sx-server-box{min-width:0!important}
  }
  @media(max-width:680px){
    #dashboard .workspace-head h1{font-size:24px!important}
    .sx-v51-head{padding:17px!important}
    .sx-v51-stats{gap:8px!important}
    .sx-v51-stat{padding:12px!important}
    .sx-v51-card{padding:15px!important}
  }
</style>
"""


def apply_compact_v52(html: str) -> str:
    if not isinstance(html, str):
        return html
    if 'id="sentrix-dashboard-v52-compact-css"' not in html:
        html = html.replace("</head>", COMPACT_V52_CSS + "\n</head>", 1)
    return html


__all__ = ["apply_compact_v52"]
