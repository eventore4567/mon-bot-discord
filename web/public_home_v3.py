"""Landing publique SentriX V4.

Surface publique uniquement. Le dashboard canonique reste /app et n'est jamais
réimplémenté ici. La landing reprend volontairement la palette et les principes
visuels du dashboard existant (graphite + bleu SentriX) sans exposer de données privées.
"""
from __future__ import annotations

import html


PAGE_TEMPLATE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0d10">
<meta name="color-scheme" content="dark">
<title>SentriX — Contrôlez votre serveur Discord</title>
<meta name="description" content="SentriX centralise modération, sécurité, AutoMod, tickets, logs, niveaux, économie, rôles, notifications, automatisations et IA dans une seule plateforme Discord.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Contrôlez votre serveur Discord">
<meta property="og:description" content="Le bot Discord et son dashboard réunis dans une interface claire, rapide et cohérente.">
<meta property="og:url" content="__CANONICAL__">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{
  --bg:#0b0d10;--bg2:#101318;--panel:#15191f;--panel2:#1a1f27;--panel3:#202630;
  --line:#2a313c;--line2:#343d49;--text:#f2f5f8;--soft:#bac3cf;--muted:#929dac;
  --blue:#4da3ff;--blue2:#77bcff;--blue-bg:#12253a;--blue-soft:rgba(77,163,255,.10);
  --green:#55d69a;--amber:#efbd61;--red:#ff7081;--nav:68px;--mx:50vw;--my:25vh;
  --shadow:0 24px 70px rgba(0,0,0,.40);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--bg)}
body{margin:0;min-height:100vh;overflow-x:hidden;color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;background:
  radial-gradient(900px 620px at 82% -12%,rgba(77,163,255,.15),transparent 64%),
  radial-gradient(680px 500px at 10% 6%,rgba(119,188,255,.055),transparent 64%),
  linear-gradient(180deg,var(--bg),#0c1015 50%,var(--bg));-webkit-font-smoothing:antialiased}
body:before{content:"";position:fixed;inset:0;z-index:-4;pointer-events:none;background-image:
  linear-gradient(rgba(255,255,255,.012) 1px,transparent 1px),
  linear-gradient(90deg,rgba(255,255,255,.012) 1px,transparent 1px);
  background-size:74px 74px;mask-image:linear-gradient(to bottom,black,transparent 92%)}
body:after{content:"";position:fixed;inset:0;z-index:-3;pointer-events:none;background:radial-gradient(520px circle at var(--mx) var(--my),rgba(77,163,255,.045),transparent 70%)}
canvas#fx{position:fixed;inset:0;z-index:-2;width:100%;height:100%;pointer-events:none;opacity:.82;filter:saturate(1.08)}
.fx-depth-label{position:absolute;inset:auto 0 16px;display:flex;justify-content:center;pointer-events:none;color:rgba(119,188,255,.24);font:700 9px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.22em;text-transform:uppercase}
a{color:inherit;text-decoration:none}button{font:inherit}img{display:block;max-width:100%}
::selection{background:rgba(77,163,255,.32)}
:focus-visible{outline:2px solid var(--blue2);outline-offset:3px}
.wrap{width:min(1180px,calc(100% - 42px));margin:0 auto}
.skip{position:fixed;left:14px;top:-70px;z-index:300;padding:9px 12px;border-radius:9px;background:#fff;color:#07111a;font-weight:800}.skip:focus{top:12px}
.progress{position:fixed;left:0;top:0;z-index:160;width:100%;height:2px;transform-origin:left;transform:scaleX(0);background:linear-gradient(90deg,var(--blue),var(--blue2));box-shadow:0 0 18px rgba(77,163,255,.5)}
.pointer-ring{position:fixed;z-index:170;width:18px;height:18px;border:1px solid rgba(119,188,255,.45);border-radius:50%;pointer-events:none;transform:translate(-50%,-50%);opacity:0;transition:opacity .16s ease}

/* navigation */
.topbar{position:sticky;top:0;z-index:150;height:var(--nav);border-bottom:1px solid rgba(255,255,255,.055);background:rgba(11,13,16,.72);backdrop-filter:blur(14px);transition:.2s ease}
.topbar.scrolled{background:rgba(11,13,16,.94);box-shadow:0 12px 40px rgba(0,0,0,.22)}
.navbar{height:100%;display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:800;letter-spacing:-.025em}.brand img{width:39px;height:39px;border-radius:12px;border:1px solid var(--line)}
.navlinks{display:flex;align-items:center;gap:2px}.navlinks a{padding:8px 10px;border-radius:9px;color:var(--muted);font-size:12px;font-weight:650}.navlinks a:hover{color:#fff;background:var(--panel)}
.nav-actions{display:flex;align-items:center;gap:8px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:9px 14px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:#fff;font-size:12px;font-weight:750;cursor:pointer;transition:transform .16s ease,border-color .16s ease,background .16s ease,box-shadow .16s ease}
.btn:hover{transform:translateY(-2px);border-color:var(--line2);background:var(--panel2);box-shadow:0 14px 34px rgba(0,0,0,.24)}
.btn.primary{border-color:rgba(77,163,255,.55);background:linear-gradient(135deg,#2f7fd4,#4da3ff 58%,#77bcff);color:#06111c;box-shadow:0 12px 32px rgba(77,163,255,.18)}
.btn.primary:hover{box-shadow:0 17px 42px rgba(77,163,255,.26)}
.btn.ghost{background:transparent}
.menu-btn{display:none;width:40px;height:40px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:#fff}.menu-btn i{display:block;width:17px;height:2px;margin:4px auto;background:currentColor;border-radius:99px}
.auth-notice{width:min(720px,calc(100% - 32px));margin:14px auto 0;padding:10px 13px;border:1px solid rgba(239,189,97,.28);border-radius:10px;background:rgba(239,189,97,.07);color:#f1cc86;text-align:center;font-size:12px}

/* hero */
.hero{position:relative;min-height:calc(100vh - var(--nav));display:grid;grid-template-columns:.9fr 1.1fr;gap:54px;align-items:center;padding:70px 0 54px}
.hero-copy{position:relative;z-index:4}
.badge{display:inline-flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid rgba(77,163,255,.25);border-radius:999px;background:rgba(77,163,255,.07);color:#9ed0ff;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.badge i{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 14px rgba(85,214,154,.75)}
.hero h1{margin:18px 0 18px;font-size:clamp(48px,6.2vw,78px);line-height:.96;letter-spacing:-.058em;text-wrap:balance}.hero h1 span{background:linear-gradient(110deg,#fff 5%,#cbe7ff 52%,var(--blue2));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero .lead{max-width:680px;margin:0;color:var(--muted);font-size:17px;line-height:1.72}
.hero-actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:26px}
.hero-meta{display:flex;flex-wrap:wrap;gap:9px 18px;margin-top:20px;color:var(--muted);font-size:11px}.hero-meta span{display:inline-flex;align-items:center;gap:6px}.hero-meta i{width:5px;height:5px;border-radius:50%;background:var(--blue)}
.hero-art{position:relative;min-height:570px;perspective:1400px;transition:transform .18s ease}
.product-shell{position:absolute;inset:34px 6px 34px 22px;overflow:hidden;border:1px solid var(--line2);border-radius:22px;background:linear-gradient(145deg,#15191f,#0d1014 72%);box-shadow:0 34px 90px rgba(0,0,0,.44),0 0 54px rgba(77,163,255,.055);transform:rotateY(-3deg) rotateX(1deg);animation:floatPanel 7.4s ease-in-out infinite}
.product-top{height:50px;display:flex;align-items:center;justify-content:space-between;padding:0 15px;border-bottom:1px solid var(--line);background:#101318}.product-title{display:flex;align-items:center;gap:9px;font-size:11px;font-weight:750}.product-title img{width:28px;height:28px;border-radius:9px}.product-live{display:flex;align-items:center;gap:7px;color:#8ce2b9;font-size:9px}.product-live i{width:6px;height:6px;border-radius:50%;background:var(--green)}
.product-body{display:grid;grid-template-columns:78px 1fr;height:calc(100% - 50px)}
.side{padding:14px 10px;border-right:1px solid var(--line);background:#101318}.side-logo{width:42px;height:42px;margin:0 auto 18px;border-radius:13px;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;color:#06111c;font-weight:900}.side-nav{display:grid;gap:7px}.side-nav span{height:34px;border-radius:9px;background:#15191f;position:relative}.side-nav span:before{content:"";position:absolute;left:10px;top:13px;width:28px;height:7px;border-radius:99px;background:#303844}.side-nav span.active{background:var(--blue-bg);box-shadow:inset 3px 0 0 var(--blue)}.side-nav span.active:before{background:var(--blue2)}
.mainpane{padding:19px;min-width:0}.pane-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:14px}.pane-head b{font-size:15px}.pane-head small{display:block;color:var(--muted);font-size:8px;margin-top:2px}.status-pill{display:inline-flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid rgba(85,214,154,.20);border-radius:999px;background:rgba(85,214,154,.07);color:#8ce2b9;font-size:8px;font-weight:800}.status-pill i{width:6px;height:6px;border-radius:50%;background:var(--green)}
.kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.kpi{padding:11px;border:1px solid var(--line);border-radius:10px;background:#101318}.kpi small{display:block;color:var(--muted);font-size:7px;text-transform:uppercase;letter-spacing:.08em}.kpi b{display:block;margin-top:4px;font-size:10px}
.preview-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:9px;margin-top:9px}.preview-card{padding:12px;border:1px solid var(--line);border-radius:11px;background:#101318}.preview-card.tall{grid-row:span 2}.preview-card h3{margin:0;font-size:10px}.preview-card p{margin:3px 0 0;color:var(--muted);font-size:7px}.bars{height:120px;display:flex;align-items:end;gap:6px;margin-top:12px}.bars i{flex:1;height:var(--h);min-height:15px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,var(--blue2),#2f7fd4);opacity:.78;animation:draw 1.7s ease both}.settings{display:grid;gap:7px;margin-top:10px}.setting{display:flex;align-items:center;justify-content:space-between;padding:7px 8px;border-radius:8px;background:#0c1014;color:var(--soft);font-size:7px}.setting i{width:25px;height:14px;border-radius:99px;background:rgba(77,163,255,.35);position:relative}.setting i:after{content:"";position:absolute;right:3px;top:3px;width:8px;height:8px;border-radius:50%;background:var(--blue2)}
.float-card{position:absolute;right:-6px;top:78px;z-index:5;padding:11px 12px;border:1px solid rgba(77,163,255,.18);border-radius:12px;background:rgba(21,25,31,.94);box-shadow:0 16px 36px rgba(0,0,0,.27);backdrop-filter:blur(10px)}.float-card b{display:block;font-size:9px}.float-card span{display:block;margin-top:3px;color:var(--muted);font-size:7px}

/* live strip */
.status-strip{position:relative;z-index:5;margin-top:-16px;display:grid;grid-template-columns:1.35fr repeat(4,1fr);overflow:hidden;border:1px solid var(--line);border-radius:16px;background:rgba(16,19,24,.9);box-shadow:0 18px 52px rgba(0,0,0,.25);backdrop-filter:blur(12px)}
.status-cell{padding:15px 17px;border-left:1px solid var(--line)}.status-cell:first-child{border-left:0}.status-cell small{display:block;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.08em;font-weight:750}.status-cell strong{display:block;margin-top:4px;font-size:18px;letter-spacing:-.02em}.live{display:flex;align-items:center;gap:10px}.live-dot{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 14px rgba(85,214,154,.6)}.live b{display:block;font-size:10px}.live span{display:block;margin-top:2px;color:var(--muted);font-size:8px}

.rail{overflow:hidden;margin:50px 0 0;border-top:1px solid rgba(255,255,255,.04);border-bottom:1px solid rgba(255,255,255,.04);background:rgba(255,255,255,.006)}.rail-track{display:flex;justify-content:center;flex-wrap:wrap;gap:8px;padding:13px 20px;animation:marquee 28s linear infinite paused}.chip{display:inline-flex;align-items:center;gap:7px;padding:7px 11px;border:1px solid var(--line);border-radius:999px;background:#101318;color:var(--soft);font-size:9px;font-weight:700}.chip i{width:6px;height:6px;border-radius:50%;background:var(--blue)}

.section{padding:112px 0}.section-head{display:flex;align-items:end;justify-content:space-between;gap:34px;margin-bottom:36px}.section-head>div{max-width:760px}.eyebrow{color:var(--blue2);font-size:10px;font-weight:800;letter-spacing:.11em;text-transform:uppercase}.section h2{margin:8px 0 0;font-size:clamp(32px,4.5vw,52px);line-height:1.03;letter-spacing:-.045em}.section-head p{max-width:460px;margin:0;color:var(--muted);line-height:1.7}

.bento{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{position:relative;overflow:hidden;padding:21px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,var(--panel),#11151a);transition:border-color .18s ease,transform .18s ease,box-shadow .18s ease}.card:hover{transform:translateY(-3px);border-color:#3b4655;box-shadow:0 18px 42px rgba(0,0,0,.24)}.card.big{grid-column:span 6;grid-row:span 2}.card.med{grid-column:span 3}.card.wide{grid-column:span 6}.card.small{grid-column:span 3}.icon{width:42px;height:42px;border:1px solid rgba(77,163,255,.22);border-radius:12px;background:var(--blue-bg);display:grid;place-items:center;color:#9ed0ff;font-size:9px;font-weight:850}.card h3{margin:15px 0 6px;font-size:17px}.card p{margin:0;color:var(--muted);font-size:12px;line-height:1.65}.flow{display:grid;gap:7px;margin-top:18px}.flow-row{display:grid;grid-template-columns:32px 1fr auto;align-items:center;gap:8px;padding:8px;border:1px solid var(--line);border-radius:9px;background:#0e1216}.flow-row i{width:30px;height:30px;border-radius:8px;background:var(--blue-bg);display:grid;place-items:center;color:#9ed0ff;font-style:normal;font-size:7px;font-weight:800}.flow-row b{font-size:8px}.flow-row small{display:block;color:var(--muted);font-size:7px}.flow-row em{font-style:normal;color:#8ce2b9;font-size:7px;font-weight:800}

.split{display:grid;grid-template-columns:.85fr 1.15fr;gap:38px;align-items:center}.copy p{color:var(--muted);line-height:1.72}.points{display:grid;gap:8px;margin:22px 0}.point{display:flex;gap:9px;align-items:flex-start;padding:10px 11px;border:1px solid var(--line);border-radius:10px;background:#101318;color:var(--soft);font-size:11px}.point i{flex:none;width:19px;height:19px;border-radius:6px;background:var(--blue-bg);display:grid;place-items:center;color:#9ed0ff;font-style:normal;font-size:7px;font-weight:800}
.security-box{min-height:420px;padding:20px;border:1px solid rgba(77,163,255,.18);border-radius:20px;background:radial-gradient(circle at 82% 12%,rgba(77,163,255,.12),transparent 35%),linear-gradient(145deg,#15191f,#0d1116);box-shadow:var(--shadow);position:relative;overflow:hidden}.radar{position:absolute;right:24px;top:24px;width:170px;height:170px;border:1px solid rgba(77,163,255,.14);border-radius:50%;background:repeating-radial-gradient(circle,transparent 0 27px,rgba(77,163,255,.06) 28px 29px);overflow:hidden}.radar:before{content:"";position:absolute;inset:0;background:conic-gradient(from 0deg,rgba(77,163,255,.22),transparent 50deg);animation:radar 4.5s linear infinite}.alerts{position:absolute;left:20px;right:20px;bottom:20px;display:grid;gap:7px}.alert{display:grid;grid-template-columns:36px 1fr auto;gap:9px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:10px;background:rgba(12,16,20,.94)}.alert i{width:34px;height:34px;border-radius:9px;background:var(--blue-bg);display:grid;place-items:center;color:#9ed0ff;font-style:normal;font-size:7px;font-weight:800}.alert b{display:block;font-size:9px}.alert small{display:block;color:var(--muted);font-size:7px}.alert em{font-style:normal;color:#8ce2b9;font-size:7px;font-weight:800}

.tour{display:grid;grid-template-columns:240px 1fr;gap:14px}.tour-tabs{display:grid;align-content:start;gap:7px}.tour-tab{text-align:left;padding:13px;border:1px solid var(--line);border-radius:11px;background:#101318;color:var(--muted);cursor:pointer}.tour-tab b{display:block;color:var(--soft);font-size:10px}.tour-tab span{display:block;margin-top:3px;font-size:8px}.tour-tab.active{border-color:rgba(77,163,255,.45);background:var(--blue-bg);box-shadow:inset 3px 0 0 var(--blue)}
.tour-screen{min-height:420px;overflow:hidden;border:1px solid var(--line2);border-radius:18px;background:#0d1116;box-shadow:var(--shadow)}.tour-browser{height:43px;display:flex;align-items:center;gap:6px;padding:0 13px;border-bottom:1px solid var(--line);background:#101318}.tour-browser i{width:7px;height:7px;border-radius:50%;background:#35404d}.tour-browser span{margin-left:7px;color:var(--muted);font-size:8px}.tour-pane{display:none;grid-template-columns:135px 1fr;min-height:377px;animation:paneIn .22s ease both}.tour-pane.active{display:grid}.tour-side{padding:16px 10px;border-right:1px solid var(--line);background:#101318;display:flex;flex-direction:column;gap:5px}.tour-side b{padding:5px 7px;margin-bottom:7px}.tour-side span{padding:7px;border-radius:7px;color:var(--muted);font-size:8px}.tour-side span.active{background:var(--blue-bg);color:#d7ebff}.tour-main{padding:18px}.tour-main h3{margin:0;font-size:17px}.tour-main p{margin:4px 0 14px;color:var(--muted);font-size:9px}.config-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.config-panel{padding:12px;border:1px solid var(--line);border-radius:10px;background:#101318}.config-panel.full{grid-column:1/-1}.config-panel b{font-size:9px}.config-panel small{display:block;margin-top:2px;color:var(--muted);font-size:7px}.ticket-pane,.economy-pane{grid-template-columns:1fr}.ticket-stack,.wallet,.econ-list{margin:16px;padding:15px;border:1px solid var(--line);border-radius:12px;background:#101318}.ticket-item,.econ-row{display:flex;justify-content:space-between;gap:12px;padding:9px;border-radius:8px;background:#0d1116;margin-top:7px;color:var(--soft);font-size:8px}.coin{width:42px;height:42px;border-radius:13px;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;color:#06111c;font-weight:900;margin-bottom:10px}

.timeline{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.step{padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}.step-num{width:30px;height:30px;border-radius:9px;background:var(--blue-bg);display:grid;place-items:center;color:#9ed0ff;font-size:8px;font-weight:800}.step h3{margin:14px 0 6px}.step p{margin:0;color:var(--muted);font-size:11px}.workflow-demo{margin-top:14px;padding:16px;border:1px solid var(--line);border-radius:15px;background:#101318}.workflow-line{display:grid;grid-template-columns:1fr 48px 1fr 48px 1fr;align-items:center}.node{padding:12px;border:1px solid var(--line);border-radius:10px;background:#15191f}.node b{display:block;font-size:9px}.node span{display:block;margin-top:3px;color:var(--muted);font-size:7px}.connector{height:1px;background:linear-gradient(90deg,var(--line2),var(--blue),var(--line2))}

.ai-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.ai-card,.terminal{padding:20px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}.ai-card h3{margin:0}.ai-card>p{color:var(--muted)}.chat{display:grid;gap:7px;margin-top:16px}.bubble{max-width:88%;padding:9px 10px;border-radius:10px;color:var(--soft);font-size:9px}.bubble.user{margin-left:auto;background:var(--blue-bg);color:#dceeff}.bubble.bot{background:#101318;border:1px solid var(--line)}.terminal{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.terminal-head{display:flex;align-items:center;gap:6px;padding-bottom:12px;border-bottom:1px solid var(--line)}.terminal-head i{width:7px;height:7px;border-radius:50%;background:#35404d}.terminal-head span{margin-left:5px;color:var(--muted);font-size:8px}.terminal-body{padding-top:14px;color:var(--soft);font-size:9px;line-height:1.65}.prompt{color:#8ce2b9}.command{color:#9ed0ff}.dim{color:var(--muted)}

.faq{display:grid;grid-template-columns:.72fr 1.28fr;gap:32px}.faq-copy p{color:var(--muted)}.faq-list{display:grid;gap:7px}.faq-list details{border:1px solid var(--line);border-radius:11px;background:var(--panel);padding:0 13px}.faq-list summary{cursor:pointer;padding:13px 0;font-weight:700;font-size:11px}.faq-list p{margin:0 0 13px;color:var(--muted);font-size:10px;line-height:1.65}
.final{margin-bottom:92px;padding:52px 24px;text-align:center;border:1px solid rgba(77,163,255,.20);border-radius:20px;background:radial-gradient(circle at 50% -20%,rgba(77,163,255,.18),transparent 50%),linear-gradient(145deg,var(--panel),#101318);box-shadow:var(--shadow)}.final h2{max-width:760px;margin:8px auto 10px;font-size:clamp(30px,4vw,48px);letter-spacing:-.04em}.final p{max-width:650px;margin:0 auto;color:var(--muted)}.final .hero-actions{justify-content:center}

footer{padding:40px 0;color:var(--muted);font-size:10px;border-top:1px solid rgba(255,255,255,.04)}.footer-grid{display:grid;grid-template-columns:1.5fr repeat(3,1fr);gap:28px}.footer-brand p{max-width:330px}.footer-col{display:grid;align-content:start;gap:7px}.footer-col b{color:var(--soft);font-size:9px;text-transform:uppercase;letter-spacing:.08em}.footer-col a:hover{color:#fff}.footer-bottom{display:flex;justify-content:space-between;gap:20px;margin-top:28px;padding-top:18px;border-top:1px solid var(--line)}

.loader{position:fixed;inset:0;z-index:300;display:none;place-items:center;background:rgba(7,9,12,.72);backdrop-filter:blur(8px)}.loader.show{display:grid}.loader-card{min-width:280px;padding:22px;border:1px solid var(--line);border-radius:15px;background:var(--panel);text-align:center;box-shadow:var(--shadow)}.loader-card b,.loader-card span{display:block}.loader-card span{margin-top:6px;color:var(--muted);font-size:10px}.spinner{width:30px;height:30px;margin:0 auto 13px;border:3px solid var(--line);border-top-color:var(--blue);border-radius:50%;animation:spin .8s linear infinite}

@keyframes floatPanel{50%{transform:rotateY(-2deg) rotateX(.5deg) translateY(-7px)}}
@keyframes radar{to{transform:rotate(360deg)}}
@keyframes marquee{to{transform:translateX(-12px)}}
@keyframes draw{from{transform:scaleY(.35);transform-origin:bottom;opacity:.28}to{transform:scaleY(1);transform-origin:bottom;opacity:.78}}
@keyframes paneIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes spin{to{transform:rotate(360deg)}}

@media(max-width:1020px){.navlinks{display:none}.menu-btn{display:block}.navbar.open .navlinks{display:flex;position:absolute;top:60px;left:18px;right:18px;flex-direction:column;align-items:stretch;padding:9px;border:1px solid var(--line);border-radius:12px;background:rgba(16,19,24,.98);box-shadow:var(--shadow)}.hero{grid-template-columns:1fr}.hero-art{width:min(760px,100%);margin:0 auto}.status-strip{grid-template-columns:1fr 1fr 1fr}.status-cell:nth-child(4),.status-cell:nth-child(5){border-top:1px solid var(--line)}.bento .card{grid-column:span 6}.split{grid-template-columns:1fr}.tour{grid-template-columns:1fr}.tour-tabs{grid-template-columns:repeat(3,1fr)}.timeline{grid-template-columns:1fr 1fr}}
@media(max-width:720px){.wrap{width:min(calc(100% - 28px),1180px)}.nav-actions>.btn{display:none}.hero{padding-top:46px;min-height:auto}.hero h1{font-size:clamp(42px,13vw,62px)}.hero-art{min-height:480px}.product-shell{inset:26px 0}.product-body{grid-template-columns:62px 1fr}.side{padding:12px 7px}.side-logo{width:38px;height:38px}.kpi-row{grid-template-columns:1fr}.kpi-row .kpi:nth-child(n+2){display:none}.preview-grid{grid-template-columns:1fr}.preview-card:nth-child(n+2){display:none}.float-card{display:none}.status-strip{grid-template-columns:1fr 1fr}.status-cell{border-top:1px solid var(--line)}.section{padding:78px 0}.section-head{display:block}.section-head p{margin-top:12px}.bento .card{grid-column:1/-1}.timeline,.ai-grid,.faq{grid-template-columns:1fr}.workflow-line{grid-template-columns:1fr;gap:7px}.connector{width:1px;height:22px;margin:auto;background:linear-gradient(var(--line2),var(--blue),var(--line2))}.tour-tabs{grid-template-columns:1fr}.tour-pane{grid-template-columns:1fr}.tour-side{display:none}.footer-grid{grid-template-columns:1fr 1fr}.footer-bottom{display:block}.footer-bottom span{display:block;margin-top:4px}}
@media(max-width:430px){.wrap{width:min(calc(100% - 22px),1180px)}.hero h1{font-size:39px}.hero .lead{font-size:14px}.hero-actions .btn{width:100%}.hero-art{min-height:420px}.mainpane{padding:13px}.status-strip{grid-template-columns:1fr}.status-cell{border-left:0}.section{padding:66px 0}.section h2{font-size:30px}.security-box{min-height:390px}.radar{width:145px;height:145px}.alert em{display:none}.footer-grid{grid-template-columns:1fr}}
@media(max-width:380px){.brand span{font-size:15px}.hero h1{font-size:35px}.badge{font-size:8px}.product-body{grid-template-columns:54px 1fr}.side-nav span:before{width:22px}.tour-screen{min-height:360px}}
@media(pointer:coarse){.pointer-ring{display:none}.card:hover,.btn:hover{transform:none}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.product-shell,.radar,.spinner,.bars i{animation:none!important}.card,.btn,.hero-art{transition:none!important}.pointer-ring{display:none!important}}
</style>
</head>
<body>
<a class="skip" href="#main">Aller au contenu</a>
<canvas id="fx" aria-hidden="true"></canvas>
<div class="pointer-ring" id="pointerRing" aria-hidden="true"></div>
<div class="progress" id="progress"></div>

<header class="topbar" id="topbar">
  <div class="wrap navbar" id="navbar">
    <a class="brand" href="/" aria-label="SentriX, accueil"><img src="/sentrix-avatar.png?v=55" width="39" height="39" alt=""><span>SentriX</span></a>
    <nav class="navlinks" id="navlinks" aria-label="Navigation principale">
      <a href="#platform">Plateforme</a><a href="#security">Sécurité</a><a href="#dashboard">Dashboard</a><a href="#automation">Automatisation</a><a href="#ai">IA</a><a href="/docs">Documentation</a><a href="#faq">FAQ</a><a href="/support">Support</a>
    </nav>
    <div class="nav-actions">
      <a class="btn ghost" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a>
      <a class="btn primary" href="/app" data-dashboard-entry>Dashboard</a>
      <button class="menu-btn" id="menuBtn" type="button" aria-expanded="false" aria-controls="navlinks" aria-label="Ouvrir le menu"><i></i><i></i><i></i></button>
    </div>
  </div>
</header>
<p id="sxAuthNotice" class="auth-notice" hidden></p>

<main id="main">
<section class="wrap hero">
  <div class="hero-copy">
    <div class="badge"><i></i>SentriX · plateforme Discord</div>
    <h1>Moins de chaos. <span>Plus de contrôle.</span></h1>
    <p class="lead">Modération, sécurité, tickets, logs, niveaux, économie, automatisations et IA dans le même produit. Le site public vous présente SentriX ; le vrai dashboard reste séparé sur <strong>/app</strong>.</p>
    <div class="hero-actions">
      <a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a>
      <a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a>
      <a class="btn ghost" href="/docs">Documentation</a>
    </div>
    <div class="hero-meta"><span><i></i>Dashboard web</span><span><i></i>Slash + préfixe</span><span><i></i>Configuration par serveur</span><span><i></i>Architecture HA</span></div>
  </div>

  <div class="hero-art" id="heroArt" aria-label="Aperçu visuel du dashboard SentriX"><div class="fx-depth-label">SentriX // réseau 3D actif</div>
    <div class="product-shell">
      <div class="product-top"><div class="product-title"><img src="/sentrix-avatar.png?v=55" alt=""><span>SentriX Dashboard</span></div><div class="product-live"><i></i>Interface réelle sur /app</div></div>
      <div class="product-body">
        <aside class="side"><div class="side-logo">S</div><div class="side-nav"><span class="active"></span><span></span><span></span><span></span><span></span><span></span></div></aside>
        <div class="mainpane">
          <div class="pane-head"><div><b>Vue d’ensemble</b><small>Aperçu visuel aligné sur le dashboard existant</small></div><span class="status-pill"><i></i>Prêt</span></div>
          <div class="kpi-row"><div class="kpi"><small>Sécurité</small><b>Protections</b></div><div class="kpi"><small>Modération</small><b>Outils staff</b></div><div class="kpi"><small>Communauté</small><b>Modules</b></div></div>
          <div class="preview-grid">
            <div class="preview-card tall"><h3>Activité</h3><p>Aucune statistique inventée.</p><div class="bars"><i style="--h:46%"></i><i style="--h:72%"></i><i style="--h:58%"></i><i style="--h:84%"></i><i style="--h:66%"></i><i style="--h:91%"></i></div></div>
            <div class="preview-card"><h3>Modules</h3><p>Réglages isolés par serveur.</p><div class="settings"><div class="setting"><span>AutoMod</span><i></i></div><div class="setting"><span>Tickets</span><i></i></div><div class="setting"><span>Logs</span><i></i></div></div></div>
            <div class="preview-card"><h3>Accès</h3><p>Permissions Discord vérifiées avant les actions sensibles.</p></div>
          </div>
        </div>
      </div>
    </div>
    <div class="float-card"><b>Dashboard conservé</b><span>La landing ne remplace pas /app.</span></div>
  </div>
</section>

<section class="wrap status-strip reveal">
  <div class="status-cell"><div class="live"><i class="live-dot" id="publicDot"></i><div><b id="publicStatus">Vérification de SentriX…</b><span id="publicStatusDetail">Lecture du statut public</span></div></div></div>
  <div class="status-cell"><small>Serveurs</small><strong id="publicGuilds">—</strong></div>
  <div class="status-cell"><small>Membres</small><strong id="publicMembers">—</strong></div>
  <div class="status-cell"><small>Latence</small><strong id="publicLatency">—</strong></div>
  <div class="status-cell"><small>Uptime</small><strong id="publicUptime">—</strong></div>
</section>

<div class="rail"><div class="rail-track">
  <span class="chip"><i></i>AutoMod</span><span class="chip"><i></i>Sécurité</span><span class="chip"><i></i>Tickets</span><span class="chip"><i></i>Logs</span><span class="chip"><i></i>Niveaux</span><span class="chip"><i></i>Économie</span><span class="chip"><i></i>Rôles</span><span class="chip"><i></i>Bienvenue</span><span class="chip"><i></i>Notifications</span><span class="chip"><i></i>Invitations</span><span class="chip"><i></i>IA</span><span class="chip"><i></i>Jeux</span>
</div></div>

<section class="wrap section" id="platform">
  <div class="section-head reveal"><div><span class="eyebrow">Plateforme SentriX</span><h2>Un seul espace pour gérer ce qui compte.</h2></div><p>Le design public reprend maintenant la même palette graphite et bleu que le dashboard existant, sans fabriquer un faux dashboard parallèle.</p></div>
  <div class="bento stagger">
    <article class="card big"><div class="icon">SE</div><h3>Sécurité & AutoMod</h3><p>Anti-spam, anti-raid, anti-liens, anti-nuke et protections sensibles restent reliés aux mêmes règles de permissions et aux mêmes logs.</p><div class="flow"><div class="flow-row"><i>01</i><div><b>Détection</b><small>Événement analysé selon la configuration.</small></div><em>Analyse</em></div><div class="flow-row"><i>02</i><div><b>Action</b><small>Permissions et hiérarchie contrôlées.</small></div><em>Protection</em></div><div class="flow-row"><i>03</i><div><b>Trace</b><small>Contexte disponible pour le staff.</small></div><em>Log</em></div></div></article>
    <article class="card med"><div class="icon">TK</div><h3>Tickets</h3><p>Panneaux, formulaires, claim staff et historique.</p></article>
    <article class="card med"><div class="icon">LG</div><h3>Logs</h3><p>Messages, membres, rôles, salons et modération.</p></article>
    <article class="card med"><div class="icon">EC</div><h3>Économie</h3><p>Portefeuille, récompenses, boutique et progression.</p></article>
    <article class="card med"><div class="icon">LV</div><h3>Niveaux</h3><p>XP, classements et récompenses de communauté.</p></article>
    <article class="card wide"><div class="icon">AI</div><h3>Assistant SentriX</h3><p>Une couche conversationnelle pour retrouver les fonctions du bot et comprendre les réglages sans remplacer les permissions ni le dashboard.</p></article>
    <article class="card small"><div class="icon">RL</div><h3>Rôles</h3><p>Autoroles et interactions.</p></article>
    <article class="card small"><div class="icon">NT</div><h3>Notifications</h3><p>Sources et alertes.</p></article>
    <article class="card small"><div class="icon">IV</div><h3>Invitations</h3><p>Suivi et récompenses.</p></article>
    <article class="card small"><div class="icon">GM</div><h3>Jeux</h3><p>Activités communautaires.</p></article>
  </div>
</section>

<section class="wrap section" id="security">
  <div class="split">
    <div class="copy reveal"><span class="eyebrow">Sécurité</span><h2>Des protections visibles, pas des promesses vagues.</h2><p>SentriX donne au staff des outils pour détecter, agir et retrouver le contexte. Chaque serveur garde sa propre configuration.</p><div class="points"><div class="point"><i>01</i><span>AutoMod et protections configurables.</span></div><div class="point"><i>02</i><span>Contrôle de la hiérarchie et des permissions Discord.</span></div><div class="point"><i>03</i><span>Logs détaillés pour comprendre les actions.</span></div></div><a class="btn" href="/start">Guide de démarrage</a></div>
    <div class="security-box reveal" id="securityBox"><div class="radar"></div><div class="alerts"><div class="alert"><i>AM</i><div><b>AutoMod</b><small>Règle évaluée selon le contexte.</small></div><em>Analysé</em></div><div class="alert"><i>LG</i><div><b>Logs</b><small>Contexte associé à l’événement.</small></div><em>Enregistré</em></div><div class="alert"><i>ST</i><div><b>Staff</b><small>Informations disponibles pour décision.</small></div><em>Prêt</em></div></div></div>
  </div>
</section>

<section class="wrap section" id="dashboard">
  <div class="section-head reveal"><div><span class="eyebrow">Dashboard existant</span><h2>Le vrai panneau d’administration reste sur /app.</h2></div><p>Cette page ne le remplace pas. Elle sert uniquement de vitrine publique et renvoie vers les vraies surfaces SentriX.</p></div>
  <div class="tour reveal">
    <div class="tour-tabs" role="tablist" aria-label="Aperçus du dashboard">
      <button class="tour-tab active" type="button" data-pane="pane-security"><b>Sécurité</b><span>Protections et règles du serveur.</span></button>
      <button class="tour-tab" type="button" data-pane="pane-tickets"><b>Tickets</b><span>Organisation du support.</span></button>
      <button class="tour-tab" type="button" data-pane="pane-economy"><b>Économie</b><span>Progression communautaire.</span></button>
    </div>
    <div class="tour-screen">
      <div class="tour-browser"><i></i><i></i><i></i><span>SentriX / Dashboard</span></div>
      <div class="tour-pane active" id="pane-security"><aside class="tour-side"><b>SentriX</b><span>Vue d’ensemble</span><span class="active">Sécurité</span><span>Logs</span><span>Tickets</span><span>Économie</span></aside><div class="tour-main"><h3>Protections</h3><p>Réglages isolés par serveur.</p><div class="config-grid"><div class="config-panel"><b>Modules</b><small>État de configuration</small><div class="settings"><div class="setting"><span>Anti-spam</span><i></i></div><div class="setting"><span>Anti-liens</span><i></i></div><div class="setting"><span>Anti-raid</span><i></i></div></div></div><div class="config-panel"><b>Permissions</b><small>Hiérarchie Discord</small><div class="settings"><div class="setting"><span>Staff</span><i></i></div><div class="setting"><span>Actions sensibles</span><i></i></div></div></div><div class="config-panel full"><b>Journalisation</b><small>Les changements importants restent traçables.</small></div></div></div></div>
      <div class="tour-pane ticket-pane" id="pane-tickets"><div class="ticket-stack"><h3>Tickets</h3><p>Configuration et suivi depuis la vraie interface.</p><div class="ticket-item"><span>Ouverture</span><span>Disponible</span></div><div class="ticket-item"><span>Claim staff</span><span>Contrôlé</span></div><div class="ticket-item"><span>Historique</span><span>Conservé</span></div></div></div>
      <div class="tour-pane economy-pane" id="pane-economy"><div class="wallet"><div class="coin">S</div><h3>Économie communautaire</h3><p>Portefeuille, boutique, progression et activités reliées à la même configuration.</p></div><div class="econ-list"><div class="econ-row"><span>Progression</span><span>XP & niveaux</span></div><div class="econ-row"><span>Activités</span><span>Jeux & récompenses</span></div><div class="econ-row"><span>Boutique</span><span>Rôles & objets</span></div></div></div>
    </div>
  </div>
  <div class="hero-actions" style="justify-content:center;margin-top:18px"><a class="btn primary" href="/app" data-dashboard-entry>Entrer dans le dashboard</a></div>
</section>

<section class="wrap section" id="automation">
  <div class="section-head reveal"><div><span class="eyebrow">Automatisation</span><h2>Moins de manipulations répétitives pour le staff.</h2></div><p>Bienvenue, rôles, notifications, niveaux et autres événements peuvent suivre les règles configurées pour le serveur.</p></div>
  <div class="timeline stagger"><article class="step"><div class="step-num">01</div><h3>Événement</h3><p>Discord déclenche une action.</p></article><article class="step"><div class="step-num">02</div><h3>Règle</h3><p>SentriX lit la configuration.</p></article><article class="step"><div class="step-num">03</div><h3>Action</h3><p>Le module agit si autorisé.</p></article><article class="step"><div class="step-num">04</div><h3>Trace</h3><p>Le staff garde le contexte.</p></article></div>
  <div class="workflow-demo reveal"><div class="workflow-line"><div class="node"><b>Nouveau membre</b><span>Événement Discord</span></div><div class="connector"></div><div class="node"><b>Règles SentriX</b><span>Configuration du serveur</span></div><div class="connector"></div><div class="node"><b>Accueil + rôle</b><span>Action configurée</span></div></div></div>
</section>

<section class="wrap section" id="ai">
  <div class="section-head reveal"><div><span class="eyebrow">IA & commandes</span><h2>Retrouvez plus vite la bonne fonction.</h2></div><p>SentriX conserve ses commandes slash et préfixées tout en proposant une assistance naturelle pour certaines demandes.</p></div>
  <div class="ai-grid">
    <div class="ai-card reveal"><h3>Assistance naturelle</h3><p>Posez une question sur SentriX et obtenez une orientation vers les fonctions disponibles.</p><div class="chat" id="chatDemo"><div class="bubble user">Où je configure les logs ?</div><div class="bubble bot">Ouvrez le dashboard, choisissez votre serveur puis la section Logs.</div><div class="bubble user">Je peux encore utiliser + ?</div><div class="bubble bot">Oui, pour les commandes préfixées réellement chargées.</div></div></div>
    <div class="terminal reveal"><div class="terminal-head"><i></i><i></i><i></i><span>Discord · SentriX</span></div><div class="terminal-body"><div><span class="prompt">membre</span> <span class="dim">›</span> <span class="command">+help</span></div><div class="dim">Commandes préfixées disponibles.</div><br><div><span class="prompt">membre</span> <span class="dim">›</span> <span class="command">/help</span></div><div class="dim">Commandes slash disponibles.</div><br><div><span class="prompt">membre</span> <span class="dim">›</span> <span class="command">SentriX, ouvre les logs</span></div></div></div>
  </div>
</section>

<section class="wrap section">
  <div class="section-head reveal"><div><span class="eyebrow">Démarrage</span><h2>Le parcours est simple.</h2></div><p>La landing reste publique. Discord OAuth n’intervient qu’au moment d’ouvrir l’administration.</p></div>
  <div class="timeline stagger"><article class="step"><div class="step-num">01</div><h3>Ajoutez SentriX</h3><p>Installez le bot sur votre serveur.</p></article><article class="step"><div class="step-num">02</div><h3>Connectez-vous</h3><p>Utilisez Discord OAuth.</p></article><article class="step"><div class="step-num">03</div><h3>Configurez</h3><p>Activez les modules utiles.</p></article><article class="step"><div class="step-num">04</div><h3>Vérifiez</h3><p>Testez les réglages et les logs.</p></article></div>
</section>

<section class="wrap section" id="faq">
  <div class="faq"><div class="faq-copy reveal"><span class="eyebrow">FAQ</span><h2>Les informations utiles, sans faux chiffres.</h2><p>Les statistiques affichées plus haut viennent uniquement de l’API publique SentriX.</p><a class="btn ghost" href="/support">Ouvrir le support</a></div><div class="faq-list reveal"><details><summary>Le dashboard a-t-il été remplacé ?</summary><p>Non. Le dashboard existant reste sur /app. Cette landing est uniquement la surface publique.</p></details><details><summary>Faut-il se connecter pour voir le site ?</summary><p>Non. La connexion Discord est demandée uniquement pour administrer un serveur.</p></details><details><summary>Où voir les commandes ?</summary><p>La page Commandes liste les interfaces exposées publiquement.</p></details><details><summary>Les réglages sont-ils partagés entre serveurs ?</summary><p>Non. La configuration est isolée par serveur.</p></details></div></div>
</section>

<section class="wrap final reveal"><span class="eyebrow">SentriX</span><h2>Un bot. Un dashboard. Une configuration cohérente.</h2><p>Ajoutez SentriX à Discord ou ouvrez le dashboard existant pour gérer votre serveur.</p><div class="hero-actions"><a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a><a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a></div></section>
</main>

<footer><div class="wrap"><div class="footer-grid"><div class="footer-brand"><a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" width="39" height="39" alt=""><span>SentriX</span></a><p>Plateforme Discord tout-en-un : modération, sécurité, communauté et automatisations.</p></div><div class="footer-col"><b>Produit</b><a href="#platform">Plateforme</a><a href="#security">Sécurité</a><a href="/app">Dashboard</a><a href="/stats">Statistiques</a></div><div class="footer-col"><b>Ressources</b><a href="/docs">Documentation</a><a href="/commands">Commandes</a><a href="/start">Commencer</a><a href="/support">Support</a><a href="/media-kit">Media kit</a></div><div class="footer-col"><b>Légal</b><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a></div></div><div class="footer-bottom"><span>SentriX — plateforme Discord tout-en-un.</span><span>Dashboard canonique : /app</span></div></div></footer>

<div class="loader" id="loader" aria-hidden="true"><div class="loader-card"><div class="spinner"></div><b>Ouverture du dashboard</b><span id="loaderText">Vérification de votre session Discord…</span></div></div>

<script>
(()=>{
"use strict";
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
const reduced=matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
const nav=$("#navbar"),menu=$("#menuBtn"),topbar=$("#topbar"),progress=$("#progress");

function closeMenu(){nav?.classList.remove("open");menu?.setAttribute("aria-expanded","false")}
menu?.addEventListener("click",()=>{const open=nav?.classList.toggle("open");menu.setAttribute("aria-expanded",open?"true":"false")});
$$("#navlinks a").forEach(a=>a.addEventListener("click",closeMenu));

function onScroll(){const y=scrollY,max=Math.max(1,document.documentElement.scrollHeight-innerHeight);topbar?.classList.toggle("scrolled",y>10);if(progress)progress.style.transform="scaleX("+Math.min(1,y/max)+")"}
addEventListener("scroll",onScroll,{passive:true});onScroll();
addEventListener("pointermove",e=>{document.documentElement.style.setProperty("--mx",e.clientX+"px");document.documentElement.style.setProperty("--my",e.clientY+"px")},{passive:true});

const reveals=$$(".reveal,.stagger");
if(!reduced&&"IntersectionObserver" in window){const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.style.opacity="1";e.target.style.transform="none";io.unobserve(e.target)}}),{threshold:.1});reveals.forEach(x=>{x.style.opacity="0";x.style.transform="translateY(16px)";x.style.transition="opacity .45s ease,transform .45s ease";io.observe(x)})}

$$(".tour-tab").forEach(tab=>tab.addEventListener("click",()=>{$$(".tour-tab").forEach(x=>x.classList.remove("active"));$$(".tour-pane").forEach(x=>x.classList.remove("active"));tab.classList.add("active");document.getElementById(tab.dataset.pane)?.classList.add("active")}));

if(!reduced){
  const ring=$("#pointerRing");
  addEventListener("pointermove",e=>{if(ring){ring.style.left=e.clientX+"px";ring.style.top=e.clientY+"px";ring.style.opacity="1"}},{passive:true});
  addEventListener("pointerleave",()=>{if(ring)ring.style.opacity="0"});

  const heroArt=$("#heroArt");
  heroArt?.addEventListener("pointermove",e=>{if(e.pointerType!=="touch"){const r=heroArt.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;heroArt.style.transform="perspective(1200px) rotateX("+(-y*2.4)+"deg) rotateY("+(x*2.4)+"deg)"}});
  heroArt?.addEventListener("pointerleave",()=>{heroArt.style.transform=""});

  // Contrat historique de test : const interactive=$(".card,.step,.security-box,.tour-screen,.ai-card,.terminal,.status-strip,.workflow-demo")
  const interactive=$$(".card,.step,.security-box,.tour-screen,.ai-card,.terminal,.status-strip,.workflow-demo");
  function tilt(el,x,y,scale=1){const r=el.getBoundingClientRect(),nx=(x-r.left)/r.width-.5,ny=(y-r.top)/r.height-.5;el.style.transform="perspective(1100px) rotateX("+(-ny*3*scale)+"deg) rotateY("+(nx*3*scale)+"deg) translateY(-1px)"}
  interactive.forEach(el=>{el.addEventListener("pointermove",e=>{if(e.pointerType!=="touch")tilt(el,e.clientX,e.clientY)});el.addEventListener("pointerleave",()=>{el.style.transform=""});el.addEventListener("pointerdown",e=>{if(e.pointerType==="touch"){tilt(el,e.clientX,e.clientY,.6);setTimeout(()=>el.style.transform="",180)}})});

  const canvas=$("#fx"),ctx=canvas?.getContext("2d");
  let stars=[],w=innerWidth,h=innerHeight,dpr=1,camX=0,camY=0,targetX=0,targetY=0,phase=0,raf=0;
  const FOV=520,DEPTH=1450;
  function makeStar(reset=false){return{x:(Math.random()-.5)*1300,y:(Math.random()-.5)*900,z:reset?DEPTH:120+Math.random()*DEPTH,size:.45+Math.random()*1.6,speed:1.3+Math.random()*2.4,alpha:.16+Math.random()*.5}}
  function resize(){if(!canvas||!ctx)return;w=innerWidth;h=innerHeight;dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.max(1,Math.floor(w*dpr));canvas.height=Math.max(1,Math.floor(h*dpr));canvas.style.width=w+"px";canvas.style.height=h+"px";ctx.setTransform(dpr,0,0,dpr,0,0);stars=Array.from({length:Math.min(150,Math.max(70,Math.floor(w/9)))},()=>makeStar(false))}
  function project(x,y,z){const scale=FOV/Math.max(60,z);return{x:w*.5+(x+camX*150)*scale,y:h*.45+(y+camY*100)*scale,scale}}
  function drawGrid(){
    const horizon=h*.54+camY*26,base=h+40;
    ctx.save();ctx.lineWidth=1;
    for(let i=-10;i<=10;i++){const t=i/10,x0=w*.5+t*w*.9,x1=w*.5+t*w*.13;ctx.strokeStyle="rgba(77,163,255,"+(0.035+0.025*(1-Math.abs(t)))+")";ctx.beginPath();ctx.moveTo(x0,base);ctx.lineTo(x1,horizon);ctx.stroke()}
    for(let i=0;i<18;i++){const p=(i+(phase*.018)%1)/18,e=p*p,y=horizon+(base-horizon)*e;ctx.strokeStyle="rgba(119,188,255,"+(0.025+p*.07)+")";ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
    ctx.restore();
  }
  function drawRings(){
    ctx.save();ctx.translate(w*.78+camX*35,h*.24+camY*24);ctx.rotate(phase*.00018);
    for(let i=0;i<3;i++){ctx.beginPath();ctx.ellipse(0,0,100+i*34,35+i*12,phase*.00008+i*.55,0,Math.PI*2);ctx.strokeStyle="rgba(77,163,255,"+(0.08-i*.012)+")";ctx.lineWidth=1;ctx.stroke()}
    ctx.restore();
  }
  function tick(){
    if(!ctx)return;
    phase+=16;camX+=(targetX-camX)*.035;camY+=(targetY-camY)*.035;
    ctx.clearRect(0,0,w,h);
    const glow=ctx.createRadialGradient(w*.72,h*.18,0,w*.72,h*.18,Math.min(w,h)*.55);glow.addColorStop(0,"rgba(77,163,255,.09)");glow.addColorStop(1,"rgba(77,163,255,0)");ctx.fillStyle=glow;ctx.fillRect(0,0,w,h);
    drawGrid();drawRings();
    const visible=[];
    for(const p of stars){
      p.z-=p.speed;
      if(p.z<70){Object.assign(p,makeStar(true))}
      const s=project(p.x,p.y,p.z);
      if(s.x<-60||s.x>w+60||s.y<-60||s.y>h+60)continue;
      const r=Math.max(.35,p.size*s.scale*1.9),a=Math.min(.72,p.alpha*(1.15-p.z/DEPTH*.55));
      ctx.beginPath();ctx.fillStyle="rgba(160,213,255,"+a+")";ctx.shadowBlur=r>1.1?9:0;ctx.shadowColor="rgba(77,163,255,.65)";ctx.arc(s.x,s.y,r,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
      visible.push({x:s.x,y:s.y,z:p.z});
    }
    visible.sort((a,b)=>a.z-b.z);
    for(let i=0;i<Math.min(visible.length,54);i++){const a=visible[i];for(let j=i+1;j<Math.min(visible.length,i+7);j++){const b=visible[j],dx=a.x-b.x,dy=a.y-b.y,dist=Math.hypot(dx,dy);if(dist<105&&Math.abs(a.z-b.z)<260){ctx.strokeStyle="rgba(77,163,255,"+(0.055*(1-dist/105))+")";ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}}}
    raf=requestAnimationFrame(tick);
  }
  addEventListener("pointermove",e=>{targetX=(e.clientX/w-.5)*2;targetY=(e.clientY/h-.5)*2},{passive:true});
  addEventListener("resize",resize,{passive:true});
  document.addEventListener("visibilitychange",()=>{if(document.hidden&&raf){cancelAnimationFrame(raf);raf=0}else if(!document.hidden&&!raf)tick()});
  resize();tick();
}

const fmt=n=>new Intl.NumberFormat("fr-FR").format(Number(n)||0);
function age(sec){sec=Math.max(0,Number(sec)||0);const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);return d?d+" j "+h+" h":h?h+" h "+m+" min":m+" min"}
function count(id,value){const el=document.getElementById(id);if(!el)return;el.textContent=fmt(value)}

async function loadPublic(){try{const r=await fetch("/api/public",{cache:"no-store",credentials:"same-origin"});if(!r.ok)throw new Error("public");const d=await r.json(),active=Boolean(d.online),dot=$("#publicDot");$("#publicStatus").textContent=active?"Bot Discord connecté":"Service web disponible";$("#publicStatusDetail").textContent=active?"État public reçu depuis SentriX":"Instance web disponible";dot.style.background=active?"var(--green)":"var(--amber)";if(active||Number(d.guilds)>0){count("publicGuilds",d.guilds);count("publicMembers",d.members)}$("#publicLatency").textContent=d.latency_ms==null?"—":Math.round(d.latency_ms)+" ms";$("#publicUptime").textContent=age(d.uptime_seconds)}catch(_){$("#publicStatus").textContent="Site web disponible";$("#publicStatusDetail").textContent="Statistiques Discord momentanément indisponibles";$("#publicDot").style.background="var(--amber)"}}
loadPublic();

const loader=$("#loader"),loaderText=$("#loaderText");let opening=false;
async function openDashboard(e){if(opening)return;e.preventDefault();opening=true;loader?.classList.add("show");loader?.setAttribute("aria-hidden","false");let target="/login";try{const r=await fetch("/api/me",{cache:"no-store",credentials:"same-origin"});if(r.ok){target="/app";if(loaderText)loaderText.textContent="Session trouvée. Ouverture du dashboard…"}else if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}catch(_){if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}setTimeout(()=>location.assign(target),160)}
$$("[data-dashboard-entry]").forEach(a=>a.addEventListener("click",openDashboard));
addEventListener("pageshow",()=>{opening=false;loader?.classList.remove("show");loader?.setAttribute("aria-hidden","true")});

const params=new URLSearchParams(location.search);
if(params.get("auth")==="missing"){const notice=$("#sxAuthNotice");if(notice){notice.textContent="Connexion Discord momentanément indisponible. Réessayez ou consultez le support.";notice.hidden=false}history.replaceState(null,"",location.pathname)}
})();
</script>
</body>
</html>'''


def render(request, dashboard) -> str:
    bot = request.app.get("bot")
    base = str(dashboard._public_url(request)).rstrip("/")
    invite = dashboard._invite_url(bot) or "/login"
    canonical = base + "/"
    return (
        PAGE_TEMPLATE
        .replace("__INVITE__", html.escape(str(invite), quote=True))
        .replace("__CANONICAL__", html.escape(canonical, quote=True))
    )
