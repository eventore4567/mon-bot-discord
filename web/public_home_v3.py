"""Landing page publique SentriX V3 — expérience premium interactive.

La page est autonome, sans dépendance externe, sans donnée privée et sans métrique inventée.
Les seules statistiques affichées proviennent de /api/public. Le dashboard reste sur /app.
"""
from __future__ import annotations

import html


PAGE_TEMPLATE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05060a">
<meta name="color-scheme" content="dark">
<title>SentriX — Contrôlez votre serveur Discord</title>
<meta name="description" content="SentriX centralise sécurité, AutoMod, tickets, logs, niveaux, économie, rôles, notifications, automatisations et intelligence artificielle dans une seule plateforme Discord.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Contrôlez votre serveur Discord">
<meta property="og:description" content="Une plateforme Discord moderne pour protéger, modérer, automatiser et faire vivre votre communauté.">
<meta property="og:url" content="__CANONICAL__">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{
  --bg:#05060a;--bg2:#080b11;--panel:#0d121a;--panel2:#111823;--panel3:#161f2e;
  --line:#202a39;--line2:#314056;--text:#f8f9fc;--soft:#c8d0dc;--muted:#8d99aa;
  --violet:#7c6cff;--violet2:#aa9eff;--blue:#4ca9ff;--cyan:#65d8f0;--green:#59dda0;
  --amber:#efbd62;--red:#ff6f7d;--nav:72px;--mx:50vw;--my:30vh;
  --shadow:0 40px 120px rgba(0,0,0,.52);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--bg)}
body{margin:0;min-height:100vh;overflow-x:hidden;color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;background:
  radial-gradient(900px 650px at 12% -12%,rgba(124,108,255,.18),transparent 62%),
  radial-gradient(760px 560px at 92% 2%,rgba(76,169,255,.10),transparent 60%),
  linear-gradient(180deg,#05060a 0%,#070a10 48%,#05070b 100%);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-5;background-image:
  linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),
  linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);
  background-size:54px 54px;mask-image:linear-gradient(to bottom,black 0 55%,transparent 92%)}
body:after{content:"";position:fixed;inset:0;pointer-events:none;z-index:-3;background:
  radial-gradient(520px circle at var(--mx) var(--my),rgba(124,108,255,.12),transparent 64%)}
canvas#fx{position:fixed;inset:0;z-index:-4;width:100%;height:100%;pointer-events:none;opacity:.72}
a{color:inherit;text-decoration:none}
button{font:inherit}
img{display:block;max-width:100%}
::selection{background:rgba(124,108,255,.4)}
:focus-visible{outline:2px solid var(--violet2);outline-offset:3px}
.skip{position:fixed;left:16px;top:-80px;z-index:300;padding:10px 14px;border-radius:10px;background:#fff;color:#05060a;font-weight:900}.skip:focus{top:14px}
.wrap{width:min(1240px,calc(100% - 42px));margin:0 auto}
.progress{position:fixed;z-index:140;left:0;top:0;height:2px;width:100%;transform-origin:left;transform:scaleX(0);background:linear-gradient(90deg,var(--violet),var(--blue),var(--cyan));box-shadow:0 0 16px rgba(124,108,255,.65)}
.noise{position:fixed;inset:0;pointer-events:none;z-index:120;opacity:.025;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E")}

/* navigation */
.topbar{position:sticky;top:0;z-index:130;height:var(--nav);background:rgba(5,6,10,.64);border-bottom:1px solid rgba(255,255,255,.05);backdrop-filter:blur(20px) saturate(140%);transition:.25s ease}
.topbar.scrolled{background:rgba(5,6,10,.92);box-shadow:0 15px 50px rgba(0,0,0,.24)}
.navbar{height:100%;display:flex;align-items:center;justify-content:space-between;gap:24px}
.brand{display:flex;align-items:center;gap:11px;font-size:18px;font-weight:950;letter-spacing:-.035em;white-space:nowrap}
.brand img{width:40px;height:40px;border-radius:13px;border:1px solid rgba(255,255,255,.12);box-shadow:0 10px 30px rgba(0,0,0,.42)}
.navlinks{display:flex;align-items:center;gap:3px}.navlinks a{padding:9px 10px;border-radius:9px;color:var(--muted);font-size:12px;font-weight:780;transition:.16s ease}.navlinks a:hover{color:#fff;background:rgba(255,255,255,.05)}
.nav-actions{display:flex;align-items:center;gap:8px}
.menu-btn{display:none;width:42px;height:42px;border:1px solid var(--line);border-radius:11px;background:var(--panel);color:#fff;cursor:pointer}.menu-btn i{display:block;width:18px;height:2px;margin:4px auto;border-radius:99px;background:currentColor}
.btn{position:relative;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:10px 16px;border:1px solid var(--line);border-radius:11px;background:rgba(16,23,34,.86);color:#fff;font-size:13px;font-weight:850;overflow:hidden;cursor:pointer;transition:transform .18s ease,border-color .18s ease,background .18s ease,box-shadow .18s ease}
.btn:before{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 24%,rgba(255,255,255,.1) 48%,transparent 72%);transform:translateX(-130%);transition:transform .55s ease}
.btn:hover{transform:translateY(-2px);border-color:#42516b;background:#182131;box-shadow:0 15px 38px rgba(0,0,0,.26)}.btn:hover:before{transform:translateX(130%)}
.btn.primary{border-color:transparent;background:linear-gradient(135deg,#7d6fff,#665ce9 58%,#4b8cf2);box-shadow:0 15px 38px rgba(100,91,245,.27)}.btn.primary:hover{box-shadow:0 20px 50px rgba(100,91,245,.39)}
.btn.ghost{background:transparent}

/* hero */
.hero{position:relative;min-height:calc(100vh - var(--nav));display:grid;grid-template-columns:.88fr 1.12fr;gap:64px;align-items:center;padding:76px 0 58px}
.hero:before{content:"";position:absolute;left:50%;top:-260px;width:1100px;height:760px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(124,108,255,.18),rgba(76,169,255,.05) 42%,transparent 68%);filter:blur(20px);animation:heroBreath 8s ease-in-out infinite alternate}
.hero-copy{position:relative;z-index:4;max-width:690px}
.badge{display:inline-flex;align-items:center;gap:9px;padding:7px 11px;border:1px solid rgba(170,158,255,.25);border-radius:999px;background:rgba(124,108,255,.08);color:#c7c0ff;font-size:10px;font-weight:950;letter-spacing:.11em;text-transform:uppercase;animation:rise .55s .02s both}.badge i{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 16px rgba(89,221,160,.86);animation:statusPulse 1.9s ease-in-out infinite}
.hero h1{margin:20px 0 19px;font-size:clamp(48px,6.5vw,84px);line-height:.95;letter-spacing:-.068em;text-wrap:balance;animation:rise .68s .08s both}.hero h1 span{background:linear-gradient(112deg,#fff 0 18%,#c7c0ff 50%,#72baff 96%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero .lead{margin:0;max-width:650px;color:var(--muted);font-size:18px;line-height:1.76;animation:rise .68s .15s both}
.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:29px;animation:rise .68s .22s both}
.hero-meta{display:flex;flex-wrap:wrap;gap:9px 18px;margin-top:21px;color:var(--muted);font-size:11px;animation:rise .68s .29s both}.hero-meta span{display:inline-flex;align-items:center;gap:7px}.hero-meta i{width:5px;height:5px;border-radius:50%;background:var(--violet2)}
.hero-art{position:relative;z-index:3;min-height:620px;perspective:1500px;animation:heroArt .85s .12s both}
.orbit{position:absolute;inset:28px 12px;border:1px solid rgba(124,108,255,.10);border-radius:50%;transform:rotate(-10deg);animation:orbit 22s linear infinite}.orbit:before,.orbit:after{content:"";position:absolute;width:8px;height:8px;border-radius:50%;background:var(--violet2);box-shadow:0 0 22px rgba(170,158,255,.85)}.orbit:before{left:13%;top:9%}.orbit:after{right:10%;bottom:14%;background:var(--blue)}
.product-shell{position:absolute;inset:42px 4px 36px 26px;overflow:hidden;border:1px solid rgba(255,255,255,.12);border-radius:26px;background:linear-gradient(145deg,rgba(17,22,32,.98),rgba(7,10,15,.99));box-shadow:0 50px 140px rgba(0,0,0,.62),0 0 90px rgba(124,108,255,.08);transform:rotateY(-5deg) rotateX(2deg);animation:floatPanel 6.8s ease-in-out infinite}
.product-top{height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 16px;border-bottom:1px solid var(--line);background:rgba(11,15,22,.75)}.window-dots{display:flex;gap:6px}.window-dots i{width:7px;height:7px;border-radius:50%;background:#333e52}.window-dots i:nth-child(1){background:#ff7583}.window-dots i:nth-child(2){background:#f1bf65}.window-dots i:nth-child(3){background:#5bdd9f}.product-top small{color:#667286;font-size:8px}
.product-body{display:grid;grid-template-columns:92px 1fr;height:calc(100% - 48px)}
.side{padding:18px 11px;border-right:1px solid var(--line);background:rgba(7,10,15,.72)}.side-logo{width:44px;height:44px;margin:0 auto 20px;border-radius:14px;background:linear-gradient(145deg,var(--violet),#536ce7);display:grid;place-items:center;font-weight:950;box-shadow:0 12px 28px rgba(124,108,255,.26)}.side-nav{display:grid;gap:8px}.side-nav span{height:34px;border-radius:9px;background:#111720;position:relative;overflow:hidden}.side-nav span:before{content:"";position:absolute;left:11px;top:12px;width:29px;height:7px;border-radius:99px;background:#2b3546}.side-nav span.active{background:rgba(124,108,255,.14);box-shadow:inset 3px 0 0 var(--violet)}.side-nav span.active:before{background:#786cff}
.mainpane{padding:21px;min-width:0}.pane-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:15px}.pane-head b{display:block;font-size:16px}.pane-head small{display:block;color:var(--muted);font-size:9px;margin-top:2px}.status{display:inline-flex;align-items:center;gap:7px;padding:6px 9px;border:1px solid rgba(89,221,160,.22);border-radius:99px;background:rgba(89,221,160,.07);color:#8fe4ba;font-size:8px;font-weight:900}.status i{width:6px;height:6px;border-radius:50%;background:var(--green)}
.kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-bottom:10px}.kpi{padding:11px;border:1px solid var(--line);border-radius:11px;background:#0b1017}.kpi small{display:block;color:var(--muted);font-size:7px;text-transform:uppercase;letter-spacing:.08em}.kpi b{display:block;margin-top:4px;font-size:12px}
.preview-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:10px}.preview-card{padding:13px;border:1px solid var(--line);border-radius:12px;background:linear-gradient(155deg,#111721,#0b1017)}.preview-card h3{margin:0 0 3px;font-size:10px}.preview-card p{margin:0;color:var(--muted);font-size:7px}.preview-card.tall{grid-row:span 2}.chart{height:104px;margin-top:12px;position:relative;overflow:hidden;border-radius:9px;background:linear-gradient(180deg,rgba(124,108,255,.08),transparent)}.chart svg{width:100%;height:100%}.chart-path{stroke-dasharray:320;stroke-dashoffset:320;animation:draw 2.4s .8s ease forwards}.chart-fill{opacity:0;animation:fade .8s 1.5s forwards}
.switches{display:grid;gap:7px;margin-top:10px}.switch{display:flex;align-items:center;justify-content:space-between;padding:8px;border-radius:8px;background:#090e14;color:var(--soft);font-size:8px}.switch i{width:27px;height:15px;border-radius:99px;background:rgba(124,108,255,.3);position:relative}.switch i:after{content:"";position:absolute;right:3px;top:3px;width:9px;height:9px;border-radius:50%;background:#aa9eff}
.feed{display:grid;gap:6px;margin-top:9px}.feed-row{display:grid;grid-template-columns:23px 1fr;gap:7px;align-items:center;padding:7px;border-radius:8px;background:#090e14}.feed-row i{width:23px;height:23px;border-radius:7px;background:rgba(76,169,255,.11);display:grid;place-items:center;color:#8cc8ff;font-style:normal;font-size:6px;font-weight:950}.feed-row b{display:block;font-size:7px}.feed-row small{display:block;color:var(--muted);font-size:6px}
.float-card{position:absolute;z-index:5;padding:13px 14px;border:1px solid rgba(170,158,255,.24);border-radius:14px;background:rgba(13,18,26,.94);backdrop-filter:blur(15px);box-shadow:0 20px 55px rgba(0,0,0,.38);animation:floatCard 5.2s ease-in-out infinite}.float-card b{display:block;font-size:10px}.float-card span{display:block;margin-top:3px;color:var(--muted);font-size:8px}.float-a{right:-8px;top:82px}.float-b{left:0;bottom:30px;animation-delay:-2s}.pulse-dots{display:flex;gap:5px;margin-top:8px}.pulse-dots i{width:5px;height:5px;border-radius:50%;background:var(--violet);animation:wave 1.35s ease-in-out infinite}.pulse-dots i:nth-child(2){animation-delay:.15s}.pulse-dots i:nth-child(3){animation-delay:.30s}

/* status strip */
.status-strip{position:relative;z-index:5;margin-top:-18px;display:grid;grid-template-columns:1.4fr repeat(4,1fr);border:1px solid var(--line);border-radius:19px;background:rgba(12,16,23,.88);backdrop-filter:blur(16px);box-shadow:0 20px 60px rgba(0,0,0,.28);overflow:hidden}.status-cell{padding:16px 18px;border-left:1px solid var(--line)}.status-cell:first-child{border-left:0}.status-cell small{display:block;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.09em;font-weight:900}.status-cell strong{display:block;margin-top:4px;font-size:19px;letter-spacing:-.03em}.live{display:flex;align-items:center;gap:11px}.live-dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 18px rgba(89,221,160,.65)}.live b,.live span{display:block}.live b{font-size:11px}.live span{color:var(--muted);font-size:8px;margin-top:2px}

/* module rail */
.rail{overflow:hidden;margin:48px 0 0;border-top:1px solid rgba(255,255,255,.05);border-bottom:1px solid rgba(255,255,255,.05);background:rgba(255,255,255,.012)}.rail-track{display:flex;width:max-content;gap:10px;padding:13px 0;animation:marquee 30s linear infinite}.chip{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid var(--line);border-radius:999px;background:#0c1118;color:var(--soft);font-size:9px;font-weight:850;white-space:nowrap}.chip i{width:6px;height:6px;border-radius:50%;background:var(--violet)}

/* sections */
.section{padding:116px 0}.section-head{display:flex;align-items:end;justify-content:space-between;gap:36px;margin-bottom:42px}.section-head>div{max-width:760px}.eyebrow{color:var(--violet2);font-size:10px;font-weight:950;letter-spacing:.12em;text-transform:uppercase}.section h2{margin:9px 0 0;font-size:clamp(33px,4.7vw,56px);line-height:1.03;letter-spacing:-.052em;text-wrap:balance}.section-head p{max-width:460px;margin:0;color:var(--muted);line-height:1.75}

/* Bento */
.bento{display:grid;grid-template-columns:repeat(12,1fr);grid-auto-rows:minmax(160px,auto);gap:13px}.card{position:relative;overflow:hidden;padding:23px;border:1px solid var(--line);border-radius:19px;background:linear-gradient(145deg,rgba(18,24,35,.94),rgba(9,13,19,.96));transition:transform .22s ease,border-color .22s ease,box-shadow .22s ease}.card:hover{transform:translateY(-5px);border-color:#3d4c64;box-shadow:0 22px 60px rgba(0,0,0,.28)}.card:after{content:"";position:absolute;right:-75px;bottom:-75px;width:190px;height:190px;border-radius:50%;background:radial-gradient(circle,rgba(124,108,255,.13),transparent 68%);pointer-events:none}.card.big{grid-column:span 6;grid-row:span 2}.card.med{grid-column:span 3}.card.wide{grid-column:span 6}.card.small{grid-column:span 3}.icon{width:44px;height:44px;border:1px solid var(--line2);border-radius:13px;background:#182131;display:grid;place-items:center;color:#cbc5ff;font-size:9px;font-weight:950;letter-spacing:.05em}.card h3{margin:18px 0 7px;font-size:18px}.card p{margin:0;color:var(--muted);font-size:12px;line-height:1.68}.card.big h3{font-size:23px}
.flow{display:grid;gap:8px;margin-top:22px}.flow-row{display:grid;grid-template-columns:34px 1fr auto;align-items:center;gap:9px;padding:9px;border:1px solid var(--line);border-radius:10px;background:#090e14}.flow-row i{width:32px;height:32px;border-radius:9px;background:rgba(124,108,255,.12);display:grid;place-items:center;color:#c4bdff;font-style:normal;font-size:7px;font-weight:950}.flow-row b{font-size:9px}.flow-row small{display:block;color:var(--muted);font-size:7px}.flow-row em{font-style:normal;color:#8be2b8;font-size:7px;font-weight:900}

/* security */
.split{display:grid;grid-template-columns:.82fr 1.18fr;gap:40px;align-items:center}.copy p{color:var(--muted);line-height:1.78}.points{display:grid;gap:9px;margin:24px 0}.point{display:flex;gap:10px;align-items:flex-start;padding:11px 12px;border:1px solid var(--line);border-radius:11px;background:#0b1017;color:var(--soft);font-size:12px}.point i{flex:none;width:20px;height:20px;border-radius:7px;background:rgba(124,108,255,.14);display:grid;place-items:center;color:#c8c1ff;font-style:normal;font-size:7px;font-weight:950}
.security-box{position:relative;min-height:490px;padding:22px;border:1px solid rgba(124,108,255,.17);border-radius:24px;background:radial-gradient(circle at 72% 10%,rgba(124,108,255,.12),transparent 35%),linear-gradient(150deg,#0f151f,#080c12);box-shadow:var(--shadow);overflow:hidden}.security-box:before{content:"";position:absolute;inset:0;background:linear-gradient(120deg,transparent 0 48%,rgba(124,108,255,.05) 49% 51%,transparent 52%);background-size:160px 160px;animation:scanGrid 6s linear infinite}
.radar{position:absolute;right:32px;top:30px;width:200px;height:200px;border:1px solid rgba(124,108,255,.15);border-radius:50%;background:repeating-radial-gradient(circle,transparent 0 32px,rgba(124,108,255,.08) 33px 34px);overflow:hidden}.radar:before{content:"";position:absolute;inset:0;background:conic-gradient(from -10deg,rgba(124,108,255,.28),transparent 48deg);animation:radar 4s linear infinite}.rd{position:absolute;width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 15px rgba(89,221,160,.85)}.r1{left:56px;top:48px}.r2{right:42px;bottom:55px}.r3{left:84px;bottom:36px}
.alerts{position:absolute;left:22px;right:22px;bottom:22px;display:grid;gap:8px}.alert{display:grid;grid-template-columns:39px 1fr auto;gap:10px;align-items:center;padding:11px;border:1px solid var(--line);border-radius:11px;background:rgba(8,12,18,.93);opacity:0;transform:translateX(-12px)}.alert.play{animation:rowIn .48s forwards}.alert:nth-child(2){animation-delay:.12s}.alert:nth-child(3){animation-delay:.24s}.alert i{width:36px;height:36px;border-radius:10px;background:rgba(76,169,255,.11);display:grid;place-items:center;color:#8ac8ff;font-style:normal;font-size:7px;font-weight:950}.alert b{display:block;font-size:9px}.alert small{display:block;color:var(--muted);font-size:7px}.alert em{font-style:normal;padding:5px 7px;border-radius:99px;background:rgba(89,221,160,.08);color:#8ce2b8;font-size:7px;font-weight:900}

/* product tour */
.tour{display:grid;grid-template-columns:310px 1fr;gap:20px;align-items:stretch}.tour-tabs{display:grid;gap:8px}.tour-tab{width:100%;text-align:left;padding:15px;border:1px solid var(--line);border-radius:13px;background:#0b1017;color:var(--muted);cursor:pointer;transition:.2s ease}.tour-tab b{display:block;color:var(--soft);font-size:12px}.tour-tab span{display:block;margin-top:4px;font-size:10px;line-height:1.5}.tour-tab.active{border-color:rgba(124,108,255,.45);background:linear-gradient(145deg,rgba(124,108,255,.14),rgba(12,17,24,.92));box-shadow:inset 3px 0 0 var(--violet)}
.tour-screen{position:relative;min-height:500px;padding:13px;border:1px solid var(--line);border-radius:23px;background:#070a0f;box-shadow:var(--shadow);overflow:hidden}.tour-browser{height:38px;display:flex;align-items:center;gap:6px;padding:0 11px;border-bottom:1px solid var(--line)}.tour-browser i{width:7px;height:7px;border-radius:50%;background:#343e52}.tour-browser i:nth-child(1){background:#ff7583}.tour-browser i:nth-child(2){background:#f1bf65}.tour-browser i:nth-child(3){background:#59dda0}.tour-browser span{margin-left:10px;color:#657185;font-size:8px}
.tour-pane{display:none;min-height:430px;padding:20px}.tour-pane.active{display:grid;animation:paneIn .36s ease both}.tour-pane.security{grid-template-columns:150px 1fr;gap:15px}.tour-side{padding:14px;border-right:1px solid var(--line)}.tour-side b{display:block;margin-bottom:12px;font-size:11px}.tour-side span{display:block;padding:8px;border-radius:8px;color:var(--muted);font-size:8px}.tour-side span.active{background:rgba(124,108,255,.13);color:#d1ccff}.tour-main h3{margin:0;font-size:16px}.tour-main>p{margin:3px 0 14px;color:var(--muted);font-size:9px}.config-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.config-panel{padding:12px;border:1px solid var(--line);border-radius:11px;background:#0f151e}.config-panel.full{grid-column:1/-1}.config-panel b{display:block;font-size:9px}.config-panel small{display:block;color:var(--muted);font-size:7px;margin-top:2px}.settings{display:grid;gap:7px;margin-top:10px}.setting{display:flex;justify-content:space-between;align-items:center;padding:8px;border-radius:8px;background:#090e14;color:var(--soft);font-size:8px}.setting i{width:28px;height:16px;border-radius:99px;background:rgba(124,108,255,.28);position:relative}.setting i:after{content:"";position:absolute;right:3px;top:3px;width:10px;height:10px;border-radius:50%;background:#aa9eff}
.bars{display:flex;align-items:end;gap:6px;height:82px;margin-top:13px}.bars i{flex:1;min-width:5px;border-radius:5px 5px 2px 2px;background:linear-gradient(#8074ff,#4457c9);height:var(--h);transform-origin:bottom;animation:bars 2.8s ease-in-out infinite}.bars i:nth-child(2n){animation-delay:-.5s}.bars i:nth-child(3n){animation-delay:-1s}
.ticket-pane,.economy-pane{grid-template-columns:1fr 1fr;gap:12px;align-content:center}.ticket-stack,.wallet{padding:18px;border:1px solid var(--line);border-radius:15px;background:#0d131b}.ticket-stack h3,.wallet h3{margin:0 0 4px}.ticket-stack p,.wallet p{margin:0;color:var(--muted);font-size:9px}.ticket-item{margin-top:10px;padding:11px;border:1px solid var(--line);border-radius:10px;background:#080d13}.ticket-item b{display:block;font-size:9px}.ticket-item small{display:block;color:var(--muted);font-size:7px}.coin{width:84px;height:84px;margin:8px auto 15px;border-radius:50%;background:radial-gradient(circle at 32% 28%,#fff4c1,#e7b74d 38%,#a56d14 72%,#6d4709);box-shadow:0 0 34px rgba(239,189,98,.18),inset 0 0 0 6px rgba(255,255,255,.14);display:grid;place-items:center;color:#5d3b08;font-size:26px;font-weight:950;animation:coinFloat 3s ease-in-out infinite}
.econ-list{display:grid;gap:8px}.econ-row{display:flex;justify-content:space-between;padding:10px;border:1px solid var(--line);border-radius:9px;background:#080d13;color:var(--soft);font-size:8px}.econ-row span:last-child{color:#e8c978}

/* automation */
.timeline{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.step{position:relative;overflow:hidden;padding:23px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#101620,#0a0f16)}.step:before{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:linear-gradient(90deg,transparent,var(--violet),transparent);transform:scaleX(0);transition:.3s ease}.step:hover:before{transform:scaleX(1)}.step-num{font-size:48px;font-weight:950;line-height:1;letter-spacing:-.06em;color:rgba(170,158,255,.15)}.step h3{margin:9px 0 6px}.step p{margin:0;color:var(--muted);font-size:12px}
.workflow-demo{margin-top:18px;padding:18px;border:1px solid var(--line);border-radius:18px;background:#0a0f16;overflow:hidden}.workflow-line{display:flex;align-items:center;justify-content:center;gap:12px;min-height:110px}.node{min-width:160px;padding:13px;border:1px solid var(--line);border-radius:12px;background:#111823;text-align:center}.node b{display:block;font-size:10px}.node span{display:block;margin-top:3px;color:var(--muted);font-size:8px}.connector{position:relative;width:80px;height:2px;background:#252f40;overflow:hidden}.connector:after{content:"";position:absolute;top:0;left:-25px;width:25px;height:2px;background:linear-gradient(90deg,transparent,#8b80ff);animation:flowMove 1.7s linear infinite}

/* ai */
.ai-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.ai-card,.terminal{padding:25px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,#101620,#090e14)}.ai-card p{color:var(--muted);line-height:1.72}.chat{margin-top:20px;padding:15px;border:1px solid var(--line);border-radius:14px;background:#070c12}.bubble{max-width:88%;padding:10px 12px;border-radius:11px;margin:7px 0;font-size:10px;opacity:0;transform:translateY(6px)}.bubble.show{animation:bubble .42s forwards}.bubble.user{margin-left:auto;background:rgba(124,108,255,.16);color:#e7e4ff}.bubble.bot{border:1px solid var(--line);background:#141b26;color:var(--soft)}
.terminal-head{display:flex;align-items:center;gap:6px;padding-bottom:13px;border-bottom:1px solid var(--line)}.terminal-head i{width:7px;height:7px;border-radius:50%;background:#354054}.terminal-head span{margin-left:7px;color:var(--muted);font-size:9px}.terminal-body{padding-top:18px;font:11px/1.9 ui-monospace,SFMono-Regular,Menlo,monospace}.prompt{color:#8ce2b8}.command{color:#dedaff}.dim{color:#6c788b}.cursor{display:inline-block;width:7px;height:12px;margin-left:2px;vertical-align:-2px;background:#aa9eff;animation:blink 1s steps(1) infinite}

/* FAQ & final */
.faq{display:grid;grid-template-columns:.78fr 1.22fr;gap:38px}.faq-copy p{color:var(--muted);line-height:1.74}.faq-list{display:grid;gap:8px}details{border:1px solid var(--line);border-radius:12px;background:#0c1118;overflow:hidden;transition:border-color .18s ease}details[open]{border-color:#3b4960}summary{padding:15px 17px;cursor:pointer;font-weight:850;list-style:none}summary::-webkit-details-marker{display:none}details p{padding:0 17px 16px;margin:0;color:var(--muted);font-size:12px;line-height:1.68}
.final{position:relative;overflow:hidden;padding:76px 25px;text-align:center;border:1px solid rgba(124,108,255,.22);border-radius:28px;background:linear-gradient(145deg,rgba(124,108,255,.13),rgba(12,16,23,.95));box-shadow:var(--shadow)}.final:before{content:"";position:absolute;left:50%;top:-250px;width:720px;height:550px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(170,158,255,.22),transparent 65%);animation:heroBreath 7s ease-in-out infinite alternate}.final>*{position:relative}.final h2{max-width:800px;margin:10px auto 13px}.final p{max-width:640px;margin:0 auto;color:var(--muted)}.final .hero-actions{justify-content:center}

/* footer */
footer{margin-top:116px;padding:42px 0 34px;border-top:1px solid rgba(255,255,255,.06)}.footer-grid{display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:28px}.footer-brand p{max-width:340px;color:var(--muted);font-size:11px}.footer-col b{display:block;margin-bottom:10px;font-size:10px;text-transform:uppercase;letter-spacing:.09em}.footer-col a{display:block;width:max-content;max-width:100%;margin:7px 0;color:var(--muted);font-size:11px}.footer-col a:hover{color:#fff}.footer-bottom{display:flex;justify-content:space-between;gap:18px;margin-top:30px;padding-top:19px;border-top:1px solid var(--line);color:var(--muted);font-size:10px}

/* pointer depth */
.card,.step,.security-box,.tour-screen,.ai-card,.terminal,.status-strip,.workflow-demo{transform-style:preserve-3d;will-change:transform;transition:border-color .18s ease,box-shadow .18s ease}
.card:hover,.step:hover,.ai-card:hover,.terminal:hover{box-shadow:0 24px 62px rgba(0,0,0,.30)}
.card>*:not(.flow),.step>*,.ai-card>*,.terminal>*{position:relative;z-index:1}
.pointer-ring{position:fixed;z-index:125;width:13px;height:13px;border-radius:50%;pointer-events:none;opacity:0;transform:translate(-50%,-50%);background:rgba(170,158,255,.24);box-shadow:0 0 34px rgba(124,108,255,.45);transition:opacity .15s ease}

/* reveal + loader */
.reveal{opacity:0;transform:translateY(24px) scale(.985);transition:opacity .65s cubic-bezier(.2,.8,.2,1),transform .65s cubic-bezier(.2,.8,.2,1)}.reveal.visible{opacity:1;transform:none}.stagger>*{opacity:0;transform:translateY(16px)}.stagger.visible>*{animation:stagger .5s forwards}.stagger.visible>*:nth-child(2){animation-delay:.05s}.stagger.visible>*:nth-child(3){animation-delay:.1s}.stagger.visible>*:nth-child(4){animation-delay:.15s}.stagger.visible>*:nth-child(5){animation-delay:.2s}.stagger.visible>*:nth-child(6){animation-delay:.25s}
.auth-notice{width:min(760px,calc(100% - 40px));margin:15px auto -24px;padding:12px 15px;border:1px solid rgba(239,189,98,.28);border-radius:11px;background:rgba(239,189,98,.07);color:#f5d8a2;font-size:12px}
.loader{position:fixed;inset:0;z-index:400;display:grid;place-items:center;background:rgba(4,5,8,.84);backdrop-filter:blur(15px);opacity:0;visibility:hidden;transition:.18s ease}.loader.show{opacity:1;visibility:visible}.loader-card{width:min(360px,calc(100vw - 34px));padding:28px;text-align:center;border:1px solid var(--line2);border-radius:19px;background:linear-gradient(#171e29,#0a0f16);box-shadow:var(--shadow)}.spinner{width:40px;height:40px;margin:0 auto 15px;border:3px solid rgba(255,255,255,.08);border-top-color:var(--violet2);border-right-color:var(--blue);border-radius:50%;animation:spin .7s linear infinite}.loader-card b{display:block}.loader-card span{display:block;margin-top:6px;color:var(--muted);font-size:10px}

/* animations */
@keyframes rise{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}
@keyframes heroArt{from{opacity:0;transform:translateX(36px) scale(.95)}to{opacity:1;transform:none}}
@keyframes heroBreath{to{transform:translateX(-50%) scale(1.08);opacity:.72}}
@keyframes statusPulse{50%{transform:scale(1.18);box-shadow:0 0 26px rgba(89,221,160,1)}}
@keyframes orbit{to{transform:rotate(350deg)}}
@keyframes floatPanel{50%{transform:rotateY(-3deg) rotateX(1deg) translateY(-10px)}}
@keyframes floatCard{50%{transform:translateY(-8px)}}
@keyframes wave{50%{transform:translateY(-4px);opacity:.45}}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes fade{to{opacity:1}}
@keyframes marquee{to{transform:translateX(-50%)}}
@keyframes scanGrid{to{background-position:160px 160px}}
@keyframes radar{to{transform:rotate(360deg)}}
@keyframes rowIn{to{opacity:1;transform:none}}
@keyframes paneIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes bars{50%{transform:scaleY(.72);opacity:.75}}
@keyframes coinFloat{50%{transform:translateY(-7px) rotate(4deg)}}
@keyframes flowMove{to{left:100%}}
@keyframes bubble{to{opacity:1;transform:none}}
@keyframes blink{50%{opacity:0}}
@keyframes stagger{to{opacity:1;transform:none}}
@keyframes spin{to{transform:rotate(360deg)}}

/* responsive */
@media(max-width:1080px){
  .navlinks{display:none}.menu-btn{display:block}.navbar.open .navlinks{display:flex;position:absolute;top:calc(var(--nav) - 1px);left:20px;right:20px;flex-direction:column;align-items:stretch;padding:10px;border:1px solid var(--line);border-radius:14px;background:rgba(8,11,16,.98);box-shadow:var(--shadow)}.navbar.open .navlinks a{padding:11px}
  .hero{grid-template-columns:1fr;min-height:auto;padding-top:68px}.hero-copy{max-width:820px}.hero-art{width:min(780px,100%);margin:0 auto}.status-strip{grid-template-columns:1.4fr repeat(3,1fr)}.status-cell:last-child{display:none}
  .card.big{grid-column:span 8}.card.med{grid-column:span 4}.card.wide{grid-column:span 8}.card.small{grid-column:span 4}
  .split{grid-template-columns:1fr}.tour{grid-template-columns:1fr}.tour-tabs{grid-template-columns:repeat(3,1fr)}.timeline{grid-template-columns:1fr 1fr}.ai-grid{grid-template-columns:1fr}.footer-grid{grid-template-columns:1.3fr 1fr 1fr}.footer-col:last-child{display:none}
}
@media(max-width:720px){
  :root{--nav:66px}.wrap{width:min(calc(100% - 28px),1240px)}.nav-actions>.btn.ghost{display:none}.nav-actions>.btn.primary{padding:9px 11px}.hero{padding:52px 0 42px;gap:26px}.hero h1{font-size:clamp(42px,13vw,62px)}.hero .lead{font-size:16px}.hero-art{min-height:410px}.product-shell{inset:8px 0 12px;transform:none;animation:none}.product-body{grid-template-columns:64px 1fr}.side{padding:12px 8px}.side-logo{width:35px;height:35px}.mainpane{padding:13px}.kpi-row{grid-template-columns:1fr 1fr}.kpi:last-child{display:none}.preview-grid{grid-template-columns:1fr}.preview-card.tall{grid-row:auto}.float-card,.orbit{display:none}
  .status-strip{grid-template-columns:1fr 1fr;margin-top:0}.status-cell{border-left:0;border-top:1px solid var(--line)}.status-cell:first-child{grid-column:1/-1;border-top:0}.status-cell:last-child{display:block}
  .section{padding:80px 0}.section-head{display:block}.section-head p{margin-top:14px}.bento{grid-template-columns:1fr}.card.big,.card.med,.card.wide,.card.small{grid-column:auto;grid-row:auto}
  .security-box{min-height:530px}.radar{width:155px;height:155px}.alert{grid-template-columns:35px 1fr}.alert em{display:none}
  .tour-tabs{grid-template-columns:1fr}.tour-screen{min-height:460px}.tour-pane.security{grid-template-columns:92px 1fr}.config-grid{grid-template-columns:1fr}.config-panel.full{grid-column:auto}.ticket-pane,.economy-pane{grid-template-columns:1fr}
  .timeline{grid-template-columns:1fr}.workflow-line{flex-direction:column}.connector{width:2px;height:52px}.connector:after{left:0;top:-18px;width:2px;height:18px;background:linear-gradient(transparent,#8b80ff);animation:flowMoveY 1.7s linear infinite}
  .faq{grid-template-columns:1fr}.footer-grid{grid-template-columns:1fr 1fr}.footer-brand{grid-column:1/-1}.footer-bottom{display:block}.footer-bottom span{display:block;margin-top:5px}
}
@media(max-width:430px){
  .hero-actions .btn{width:100%}.hero-art{min-height:365px}.side-nav span{height:27px}.kpi-row{display:none}.chart{height:78px}.section h2{font-size:34px}.security-box{min-height:575px}.radar{right:50%;transform:translateX(50%)}.alerts{top:225px;bottom:auto}.tour-pane.security{grid-template-columns:74px 1fr}.tour-side{padding:10px 5px}
}
@keyframes flowMoveY{to{top:100%}}
@media(max-width:380px){
  .wrap{width:min(calc(100% - 22px),1240px)}
  .brand span{font-size:15px}.nav-actions>.btn.primary{font-size:11px;padding:8px 9px}
  .hero h1{font-size:40px}.hero .lead{font-size:14px}.hero-meta{gap:8px 12px}
  .status-cell{padding:13px}.status-cell strong{font-size:16px}
  .section{padding:68px 0}.section h2{font-size:31px}.card{padding:18px}.final{padding:52px 16px}
}
@media(pointer:coarse){
  .pointer-ring{display:none}
  .card,.step,.security-box,.tour-screen,.ai-card,.terminal,.status-strip,.workflow-demo{will-change:auto}
}
@media(prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}body:after,canvas#fx{display:none}.hero:before,.badge i,.orbit,.product-shell,.float-card,.pulse-dots i,.chart-path,.chart-fill,.rail-track,.security-box:before,.radar:before,.bars i,.coin,.connector:after,.cursor,.final:before,.spinner{animation:none!important}.pointer-ring{display:none}.badge,.hero h1,.hero .lead,.hero-actions,.hero-meta,.hero-art,.alert,.bubble,.reveal,.stagger>*{opacity:1!important;transform:none!important;animation:none!important;transition:none!important}.btn,.card,.tour-tab,.topbar{transition:none!important}
}
</style>
</head>
<body>
<div class="pointer-ring" id="pointerRing" aria-hidden="true"></div>
<a class="skip" href="#main">Aller au contenu</a>
<div class="noise" aria-hidden="true"></div>
<canvas id="fx" aria-hidden="true"></canvas>
<div class="progress" id="progress"></div>

<header class="topbar" id="topbar">
  <div class="wrap navbar" id="navbar">
    <a class="brand" href="/" aria-label="SentriX, accueil"><img src="/sentrix-avatar.png?v=55" width="40" height="40" alt=""><span>SentriX</span></a>
    <nav class="navlinks" id="navlinks" aria-label="Navigation principale">
      <a href="#platform">Plateforme</a><a href="#security">Sécurité</a><a href="#dashboard">Dashboard</a><a href="#automation">Automatisation</a><a href="#ai">IA</a><a href="#faq">FAQ</a><a href="/support">Support</a>
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
    <div class="badge"><i></i>SentriX · contrôle Discord nouvelle génération</div>
    <h1>Moins de chaos. <span>Plus de contrôle.</span></h1>
    <p class="lead">Protégez, modérez, automatisez et faites vivre votre communauté depuis une seule plateforme. SentriX relie le bot Discord, le dashboard, les logs, l’économie, les niveaux, les tickets et l’IA au lieu de les empiler.</p>
    <div class="hero-actions">
      <a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a>
      <a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX à Discord</a>
      <a class="btn ghost" href="#platform">Voir la plateforme</a>
    </div>
    <div class="hero-meta"><span><i></i>Dashboard web</span><span><i></i>Slash + préfixe</span><span><i></i>Configuration par serveur</span><span><i></i>Architecture HA</span></div>
  </div>

  <div class="hero-art" id="heroArt" aria-label="Aperçu animé de SentriX">
    <div class="orbit"></div>
    <div class="product-shell">
      <div class="product-top"><div class="window-dots"><i></i><i></i><i></i></div><small>SentriX · Control Center</small></div>
      <div class="product-body">
        <aside class="side"><div class="side-logo">S</div><div class="side-nav"><span class="active"></span><span></span><span></span><span></span><span></span><span></span><span></span></div></aside>
        <div class="mainpane">
          <div class="pane-head"><div><b>Vue d’ensemble</b><small>Aperçu sans données privées</small></div><div class="status"><i></i>Synchronisé</div></div>
          <div class="kpi-row"><div class="kpi"><small>Sécurité</small><b>Protection active</b></div><div class="kpi"><small>Staff</small><b>Outils centralisés</b></div><div class="kpi"><small>Communauté</small><b>Modules reliés</b></div></div>
          <div class="preview-grid">
            <div class="preview-card tall"><h3>Activité</h3><p>Illustration de l’interface, pas une statistique inventée.</p><div class="chart"><svg viewBox="0 0 320 105" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7c6cff" stop-opacity=".30"/><stop offset="1" stop-color="#7c6cff" stop-opacity="0"/></linearGradient></defs><path class="chart-fill" d="M0 84 C35 73 52 84 82 62 S127 42 152 57 S194 82 222 50 S265 45 320 20 L320 105 L0 105Z" fill="url(#area)"/><path class="chart-path" d="M0 84 C35 73 52 84 82 62 S127 42 152 57 S194 82 222 50 S265 45 320 20" fill="none" stroke="#9185ff" stroke-width="2.4"/></svg></div></div>
            <div class="preview-card"><h3>Modules</h3><p>Activation centralisée.</p><div class="switches"><div class="switch"><span>AutoMod</span><i></i></div><div class="switch"><span>Logs</span><i></i></div><div class="switch"><span>Tickets</span><i></i></div></div></div>
            <div class="preview-card"><h3>Événements</h3><div class="feed"><div class="feed-row"><i>LG</i><div><b>Journal mis à jour</b><small>Contexte enregistré</small></div></div><div class="feed-row"><i>SC</i><div><b>Protection active</b><small>Règles synchronisées</small></div></div></div></div>
          </div>
        </div>
      </div>
    </div>
    <div class="float-card float-a"><b>Protection multicouche</b><span>AutoMod · anti-raid · logs</span><div class="pulse-dots"><i></i><i></i><i></i></div></div>
    <div class="float-card float-b"><b>Une seule plateforme</b><span>Bot, dashboard et communauté connectés.</span></div>
  </div>
</section>

<section class="wrap status-strip reveal" aria-label="État public SentriX">
  <div class="status-cell live"><i class="live-dot" id="publicDot"></i><div><b id="publicStatus">Service web disponible</b><span id="publicStatusDetail">Chargement de l’état Discord…</span></div></div>
  <div class="status-cell"><small>Serveurs</small><strong id="publicGuilds">—</strong></div>
  <div class="status-cell"><small>Membres accessibles</small><strong id="publicMembers">—</strong></div>
  <div class="status-cell"><small>Latence</small><strong id="publicLatency">—</strong></div>
  <div class="status-cell"><small>Uptime</small><strong id="publicUptime">—</strong></div>
</section>

<div class="rail" aria-hidden="true"><div class="rail-track">
  <span class="chip"><i></i>AutoMod</span><span class="chip"><i></i>Sécurité</span><span class="chip"><i></i>Tickets</span><span class="chip"><i></i>Logs</span><span class="chip"><i></i>Niveaux</span><span class="chip"><i></i>Économie</span><span class="chip"><i></i>Rôles</span><span class="chip"><i></i>Bienvenue</span><span class="chip"><i></i>Notifications</span><span class="chip"><i></i>Invitations</span><span class="chip"><i></i>IA</span><span class="chip"><i></i>Jeux</span>
  <span class="chip"><i></i>AutoMod</span><span class="chip"><i></i>Sécurité</span><span class="chip"><i></i>Tickets</span><span class="chip"><i></i>Logs</span><span class="chip"><i></i>Niveaux</span><span class="chip"><i></i>Économie</span><span class="chip"><i></i>Rôles</span><span class="chip"><i></i>Bienvenue</span><span class="chip"><i></i>Notifications</span><span class="chip"><i></i>Invitations</span><span class="chip"><i></i>IA</span><span class="chip"><i></i>Jeux</span>
</div></div>

<section class="wrap section" id="platform">
  <div class="section-head reveal"><div><span class="eyebrow">Une plateforme, pas une collection de commandes</span><h2>Tout ce qui fait tourner votre serveur, au même endroit.</h2></div><p>SentriX relie les fonctions staff et communauté dans une interface cohérente. Pas besoin de jongler entre une multitude de bots pour chaque besoin.</p></div>
  <div class="bento stagger">
    <article class="card big"><div class="icon">SE</div><h3>Sécurité & AutoMod</h3><p>Anti-spam, anti-raid, protections sensibles, vérification, contrôles de permissions et journalisation partagent la même logique.</p><div class="flow"><div class="flow-row"><i>01</i><div><b>Événement détecté</b><small>Une règle correspond au contexte.</small></div><em>Analyse</em></div><div class="flow-row"><i>02</i><div><b>Action contrôlée</b><small>Permissions et paramètres vérifiés.</small></div><em>Protection</em></div><div class="flow-row"><i>03</i><div><b>Trace disponible</b><small>Le staff retrouve le contexte dans les logs.</small></div><em>Journal</em></div></div></article>
    <article class="card med"><div class="icon">TK</div><h3>Tickets</h3><p>Assistance structurée, formulaires, organisation du staff et historique.</p></article>
    <article class="card med"><div class="icon">LG</div><h3>Logs</h3><p>Messages, membres, rôles, salons, sécurité et modération.</p></article>
    <article class="card med"><div class="icon">EC</div><h3>Économie</h3><p>Portefeuille, récompenses, objets, boutique et activités.</p></article>
    <article class="card med"><div class="icon">LV</div><h3>Niveaux</h3><p>XP, progression, classements et récompenses de communauté.</p></article>
    <article class="card wide"><div class="icon">AI</div><h3>Intelligence artificielle</h3><p>Une couche conversationnelle qui aide à comprendre SentriX, trouver le bon réglage et utiliser les fonctions réellement disponibles.</p></article>
    <article class="card small"><div class="icon">RL</div><h3>Rôles</h3><p>Autoroles et systèmes interactifs.</p></article>
    <article class="card small"><div class="icon">NT</div><h3>Notifications</h3><p>Alertes et sources regroupées.</p></article>
    <article class="card small"><div class="icon">IV</div><h3>Invitations</h3><p>Suivi et récompenses configurables.</p></article>
    <article class="card small"><div class="icon">GM</div><h3>Jeux</h3><p>Activités communautaires reliées à l’écosystème.</p></article>
  </div>
</section>

<section class="wrap section" id="security">
  <div class="split">
    <div class="copy reveal"><span class="eyebrow">Sécurité</span><h2>Ne modérez plus à l’aveugle.</h2><p>SentriX ne promet pas un serveur impossible à attaquer. Il donne au staff des protections, des traces et un contexte clair pour réduire les abus et réagir plus vite.</p><div class="points"><div class="point"><i>01</i><span>AutoMod et protections configurables pour les comportements indésirables.</span></div><div class="point"><i>02</i><span>Contrôles dédiés aux changements sensibles sur rôles, salons et permissions.</span></div><div class="point"><i>03</i><span>Logs et historique pour comprendre ce qui s’est réellement passé.</span></div></div><a class="btn" href="/start">Découvrir la mise en route</a></div>
    <div class="security-box reveal" id="securityBox"><div class="radar"><i class="rd r1"></i><i class="rd r2"></i><i class="rd r3"></i></div><div class="alerts"><div class="alert"><i>AM</i><div><b>AutoMod</b><small>Une règle vient d’être évaluée.</small></div><em>Analysé</em></div><div class="alert"><i>LG</i><div><b>Journalisation</b><small>Le contexte utile a été associé à l’événement.</small></div><em>Enregistré</em></div><div class="alert"><i>ST</i><div><b>Staff</b><small>Les informations sont prêtes pour décision.</small></div><em>Prêt</em></div></div></div>
  </div>
</section>

<section class="wrap section" id="dashboard">
  <div class="section-head reveal"><div><span class="eyebrow">Product tour</span><h2>Un dashboard qui ressemble enfin à un vrai produit.</h2></div><p>Explorez plusieurs facettes de SentriX sans quitter la page. Les visuels ci-dessous illustrent l’interface, sans inventer de données serveur.</p></div>
  <div class="tour reveal">
    <div class="tour-tabs" role="tablist" aria-label="Aperçus du dashboard">
      <button class="tour-tab active" type="button" data-pane="pane-security"><b>Sécurité</b><span>Protections et règles du serveur.</span></button>
      <button class="tour-tab" type="button" data-pane="pane-tickets"><b>Tickets</b><span>Organisation du support et du staff.</span></button>
      <button class="tour-tab" type="button" data-pane="pane-economy"><b>Économie</b><span>Progression et activités communautaires.</span></button>
    </div>
    <div class="tour-screen">
      <div class="tour-browser"><i></i><i></i><i></i><span>SentriX / Dashboard</span></div>
      <div class="tour-pane security active" id="pane-security"><aside class="tour-side"><b>SentriX</b><span>Vue d’ensemble</span><span class="active">Sécurité</span><span>Logs</span><span>Tickets</span><span>Économie</span></aside><div class="tour-main"><h3>Protections</h3><p>Les réglages sont isolés par serveur.</p><div class="config-grid"><div class="config-panel"><b>Modules actifs</b><small>État de la configuration</small><div class="settings"><div class="setting"><span>Anti-spam</span><i></i></div><div class="setting"><span>Anti-liens</span><i></i></div><div class="setting"><span>Vérification</span><i></i></div></div></div><div class="config-panel"><b>Activité</b><small>Illustration visuelle</small><div class="bars"><i style="--h:46%"></i><i style="--h:72%"></i><i style="--h:58%"></i><i style="--h:84%"></i><i style="--h:66%"></i><i style="--h:92%"></i><i style="--h:70%"></i></div></div><div class="config-panel full"><b>Règles du serveur</b><small>Les changements réels sont enregistrés depuis le dashboard connecté.</small><div class="settings"><div class="setting"><span>Protection des mentions massives</span><i></i></div><div class="setting"><span>Journalisation des actions sensibles</span><i></i></div></div></div></div></div></div>
      <div class="tour-pane ticket-pane" id="pane-tickets"><div class="ticket-stack"><h3>File des tickets</h3><p>Vue illustrée du flux d’assistance.</p><div class="ticket-item"><b>Demande ouverte</b><small>En attente de prise en charge</small></div><div class="ticket-item"><b>Conversation staff</b><small>Contexte regroupé dans le ticket</small></div><div class="ticket-item"><b>Résolution</b><small>Historique conservé selon la configuration</small></div></div><div class="ticket-stack"><h3>Centre staff</h3><p>Les outils support restent séparés des données publiques.</p><div class="flow"><div class="flow-row"><i>01</i><div><b>Ouverture</b><small>Le membre crée une demande.</small></div><em>Nouveau</em></div><div class="flow-row"><i>02</i><div><b>Traitement</b><small>Le staff prend en charge.</small></div><em>Actif</em></div><div class="flow-row"><i>03</i><div><b>Clôture</b><small>L’historique est finalisé.</small></div><em>Terminé</em></div></div></div></div>
      <div class="tour-pane economy-pane" id="pane-economy"><div class="wallet"><div class="coin">S</div><h3>Économie communautaire</h3><p>Portefeuille, récompenses, boutique et activités reliées à la même base économique.</p></div><div class="econ-list"><div class="econ-row"><span>Progression</span><span>XP & niveaux</span></div><div class="econ-row"><span>Activités</span><span>Jeux & récompenses</span></div><div class="econ-row"><span>Objets</span><span>Inventaire</span></div><div class="econ-row"><span>Boutique</span><span>Économie</span></div></div></div>
    </div>
  </div>
</section>

<section class="wrap section" id="automation">
  <div class="section-head reveal"><div><span class="eyebrow">Automatisation</span><h2>Les tâches répétitives deviennent des flux.</h2></div><p>Bienvenue, rôles, notifications et progression peuvent être configurés pour réduire les manipulations manuelles du staff.</p></div>
  <div class="timeline stagger"><article class="step"><div class="step-num">01</div><h3>Déclencheur</h3><p>Un membre arrive, gagne un niveau ou une source publie un nouvel événement.</p></article><article class="step"><div class="step-num">02</div><h3>Règles</h3><p>SentriX applique les paramètres propres au serveur et contrôle les permissions.</p></article><article class="step"><div class="step-num">03</div><h3>Action</h3><p>Message, rôle, notification ou progression selon le module concerné.</p></article><article class="step"><div class="step-num">04</div><h3>Trace</h3><p>Les événements importants restent visibles dans les outils prévus pour le staff.</p></article></div>
  <div class="workflow-demo reveal"><div class="workflow-line"><div class="node"><b>Nouveau membre</b><span>Événement Discord</span></div><div class="connector"></div><div class="node"><b>Règles SentriX</b><span>Configuration du serveur</span></div><div class="connector"></div><div class="node"><b>Accueil + rôle</b><span>Action configurée</span></div></div></div>
</section>

<section class="wrap section" id="ai">
  <div class="section-head reveal"><div><span class="eyebrow">IA & commandes</span><h2>Utilisez SentriX comme un outil, pas comme un manuel.</h2></div><p>Les commandes restent disponibles, tandis que l’IA peut aider à retrouver une fonction ou comprendre un réglage sans inventer ce qui n’existe pas.</p></div>
  <div class="ai-grid">
    <div class="ai-card reveal"><h3>Assistance naturelle</h3><p>Posez une question sur SentriX et obtenez une orientation vers les fonctions réellement disponibles.</p><div class="chat" id="chatDemo"><div class="bubble user">Où je configure les logs de modération ?</div><div class="bubble bot">Dans le dashboard, choisissez votre serveur puis ouvrez la section Logs.</div><div class="bubble user">Je peux encore utiliser le préfixe + ?</div><div class="bubble bot">Oui pour les commandes préfixées encore réellement chargées. Les slash commands restent aussi disponibles.</div></div></div>
    <div class="terminal reveal"><div class="terminal-head"><i></i><i></i><i></i><span>Discord · SentriX</span></div><div class="terminal-body"><div><span class="prompt">membre</span> <span class="dim">›</span> <span class="command">+help</span></div><div class="dim">Affiche les commandes préfixées disponibles.</div><br><div><span class="prompt">membre</span> <span class="dim">›</span> <span class="command">/help</span></div><div class="dim">Les commandes slash restent disponibles.</div><br><div><span class="prompt">membre</span> <span class="dim">›</span> <span class="command">SentriX, où est la sécurité ?</span><span class="cursor"></span></div></div></div>
  </div>
</section>

<section class="wrap section">
  <div class="section-head reveal"><div><span class="eyebrow">Démarrage</span><h2>Trois minutes pour comprendre le parcours.</h2></div><p>La page publique reste ouverte à tous. La connexion Discord intervient uniquement quand vous entrez dans l’administration.</p></div>
  <div class="timeline stagger"><article class="step"><div class="step-num">01</div><h3>Ajoutez SentriX</h3><p>Choisissez le serveur Discord sur lequel installer le bot.</p></article><article class="step"><div class="step-num">02</div><h3>Connectez-vous</h3><p>Ouvrez le dashboard avec Discord OAuth.</p></article><article class="step"><div class="step-num">03</div><h3>Configurez</h3><p>Activez uniquement les modules utiles à votre communauté.</p></article><article class="step"><div class="step-num">04</div><h3>Faites évoluer</h3><p>Ajustez les règles et modules au fil de la vie du serveur.</p></article></div>
</section>

<section class="wrap section" id="faq">
  <div class="faq"><div class="faq-copy reveal"><span class="eyebrow">FAQ</span><h2>Les réponses utiles, sans marketing inventé.</h2><p>La page ne fabrique ni statistiques ni promesses absolues. Les informations reflètent les fonctions réelles du projet.</p><a class="btn ghost" href="/support">Ouvrir le support</a></div><div class="faq-list reveal"><details><summary>Dois-je me connecter pour voir le site ?</summary><p>Non. La landing et les ressources publiques sont accessibles sans session. Discord OAuth est demandé uniquement pour administrer un serveur via le dashboard.</p></details><details><summary>Pourquoi SentriX plutôt que plusieurs bots ?</summary><p>SentriX centralise plusieurs fonctions courantes dans la même logique de configuration, de permissions et de dashboard. Vous pouvez malgré tout continuer à utiliser d’autres outils selon vos besoins.</p></details><details><summary>Les commandes avec + restent-elles disponibles ?</summary><p>Les commandes préfixées utiles peuvent rester disponibles en parallèle des commandes slash. La page Commandes reflète ce qui est réellement chargé.</p></details><details><summary>SentriX garantit-il une sécurité totale ?</summary><p>Non. SentriX fournit plusieurs couches de protection et de journalisation, mais la sécurité dépend aussi des permissions, de la configuration et des pratiques du staff.</p></details><details><summary>Les réglages sont-ils partagés entre serveurs ?</summary><p>Non. La configuration est conçue pour rester isolée par serveur.</p></details><details><summary>Où voir les commandes disponibles ?</summary><p>La page publique Commandes liste les interfaces préfixées et slash réellement exposées.</p></details></div></div>
</section>

<section class="wrap final reveal"><span class="eyebrow">SentriX</span><h2>Votre serveur mérite mieux qu’un empilement de bots.</h2><p>Ajoutez SentriX à Discord ou ouvrez le dashboard pour commencer à construire une configuration cohérente.</p><div class="hero-actions"><a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a><a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a></div></section>
</main>

<footer><div class="wrap"><div class="footer-grid"><div class="footer-brand"><a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" width="40" height="40" alt=""><span>SentriX</span></a><p>Plateforme Discord pour centraliser modération, sécurité, communauté et automatisations dans un environnement cohérent.</p></div><div class="footer-col"><b>Produit</b><a href="#platform">Plateforme</a><a href="#security">Sécurité</a><a href="/dashboard-sentrix">Dashboard</a><a href="/stats">Statistiques</a></div><div class="footer-col"><b>Ressources</b><a href="/commands">Commandes</a><a href="/start">Commencer</a><a href="/support">Support</a><a href="/media-kit">Media kit</a></div><div class="footer-col"><b>Légal</b><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a></div></div><div class="footer-bottom"><span>SentriX — plateforme Discord tout-en-un.</span><span>Les données publiques ne sont affichées que lorsqu’elles viennent du service réel.</span></div></div></footer>

<div class="loader" id="loader" aria-hidden="true"><div class="loader-card"><div class="spinner"></div><b>Ouverture du dashboard</b><span id="loaderText">Vérification de votre session Discord…</span></div></div>

<script>
(()=>{
"use strict";
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>Array.from(r.querySelectorAll(s));
const reduced=matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
const nav=$("#navbar"), menu=$("#menuBtn"), topbar=$("#topbar"), progress=$("#progress");

function closeMenu(){nav?.classList.remove("open");menu?.setAttribute("aria-expanded","false")}
menu?.addEventListener("click",()=>{const o=nav?.classList.toggle("open");menu.setAttribute("aria-expanded",o?"true":"false")});
$$("#navlinks a").forEach(a=>a.addEventListener("click",closeMenu));
document.addEventListener("click",e=>{if(nav?.classList.contains("open")&&!nav.contains(e.target))closeMenu()});

function onScroll(){const y=scrollY,max=Math.max(1,document.documentElement.scrollHeight-innerHeight);topbar?.classList.toggle("scrolled",y>12);if(progress)progress.style.transform="scaleX("+Math.min(1,y/max)+")"}
addEventListener("scroll",onScroll,{passive:true});onScroll();
if(!reduced)addEventListener("pointermove",e=>{document.documentElement.style.setProperty("--mx",e.clientX+"px");document.documentElement.style.setProperty("--my",e.clientY+"px")},{passive:true});

const reveals=$$(".reveal,.stagger");
if(!reduced&&"IntersectionObserver" in window){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("visible");io.unobserve(e.target)}}),{threshold:.10,rootMargin:"0px 0px -40px"});reveals.forEach(x=>io.observe(x))}else reveals.forEach(x=>x.classList.add("visible"));

const box=$("#securityBox");
if(box){const rows=$$(".alert",box);if(!reduced&&"IntersectionObserver" in window){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){rows.forEach(r=>r.classList.add("play"));io.disconnect()}}),{threshold:.28});io.observe(box)}else rows.forEach(r=>r.classList.add("play"))}

const chat=$("#chatDemo");
if(chat){const bubbles=$$(".bubble",chat);if(!reduced&&"IntersectionObserver" in window){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){bubbles.forEach((b,i)=>setTimeout(()=>b.classList.add("show"),i*190));io.disconnect()}}),{threshold:.35});io.observe(chat)}else bubbles.forEach(b=>b.classList.add("show"))}

$$(".tour-tab").forEach(tab=>tab.addEventListener("click",()=>{$$(".tour-tab").forEach(x=>x.classList.remove("active"));$$(".tour-pane").forEach(x=>x.classList.remove("active"));tab.classList.add("active");document.getElementById(tab.dataset.pane)?.classList.add("active")}));

if(!reduced){
  const ring=$("#pointerRing");
  addEventListener("pointermove",e=>{if(ring){ring.style.left=e.clientX+"px";ring.style.top=e.clientY+"px";ring.style.opacity="1"}},{passive:true});
  addEventListener("pointerleave",()=>{if(ring)ring.style.opacity="0"});

  const art=$("#heroArt");
  art?.addEventListener("pointermove",e=>{const r=art.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;art.style.transform="perspective(1500px) rotateX("+(-y*3)+"deg) rotateY("+(x*3)+"deg)"});
  art?.addEventListener("pointerleave",()=>art.style.transform="");

  const interactive=$(".card,.step,.security-box,.tour-screen,.ai-card,.terminal,.status-strip,.workflow-demo");
  const motion=new WeakMap();
  function getMotion(el){let s=motion.get(el);if(!s){s={rx:0,ry:0,tx:0,ty:0,trx:0,try:0,ttx:0,tty:0,raf:0};motion.set(el,s)}return s}
  function animateTilt(el){
    const s=getMotion(el),ease=.145;
    s.rx+=(s.trx-s.rx)*ease;s.ry+=(s.try-s.ry)*ease;s.tx+=(s.ttx-s.tx)*ease;s.ty+=(s.tty-s.ty)*ease;
    el.style.transform="perspective(1100px) rotateX("+s.rx.toFixed(2)+"deg) rotateY("+s.ry.toFixed(2)+"deg) translate3d("+s.tx.toFixed(1)+"px,"+s.ty.toFixed(1)+"px,0)";
    el.style.boxShadow=(-s.ry*3).toFixed(1)+"px "+(20+s.rx*1.5).toFixed(1)+"px 62px rgba(0,0,0,.31)";
    const delta=Math.abs(s.trx-s.rx)+Math.abs(s.try-s.ry)+Math.abs(s.ttx-s.tx)+Math.abs(s.tty-s.ty);
    if(delta>.05)s.raf=requestAnimationFrame(()=>animateTilt(el));else{s.raf=0;if(!s.trx&&!s.try&&!s.ttx&&!s.tty){el.style.transform="";el.style.boxShadow=""}}
  }
  function aimTilt(el,x,y,scale=1){const r=el.getBoundingClientRect(),nx=Math.max(0,Math.min(1,(x-r.left)/r.width))-.5,ny=Math.max(0,Math.min(1,(y-r.top)/r.height))-.5,s=getMotion(el),max=el.classList.contains("card")?9:el.classList.contains("step")?7:5.2;s.trx=-ny*max*scale;s.try=nx*max*scale;s.ttx=nx*12*scale;s.tty=ny*8*scale;if(!s.raf)s.raf=requestAnimationFrame(()=>animateTilt(el))}
  function releaseTilt(el){const s=getMotion(el);s.trx=s.try=s.ttx=s.tty=0;if(!s.raf)s.raf=requestAnimationFrame(()=>animateTilt(el))}
  interactive.forEach(el=>{
    el.addEventListener("pointermove",e=>{if(e.pointerType!=="touch")aimTilt(el,e.clientX,e.clientY)});
    el.addEventListener("pointerleave",()=>releaseTilt(el));
    el.addEventListener("pointerdown",e=>{if(e.pointerType==="touch"){aimTilt(el,e.clientX,e.clientY,.8);setTimeout(()=>releaseTilt(el),220)}});
  });

  const canvas=$("#fx"),ctx=canvas?.getContext("2d");let dots=[];
  function resize(){if(!canvas||!ctx)return;const d=Math.min(devicePixelRatio||1,2);canvas.width=innerWidth*d;canvas.height=innerHeight*d;canvas.style.width=innerWidth+"px";canvas.style.height=innerHeight+"px";ctx.setTransform(d,0,0,d,0,0);dots=Array.from({length:Math.min(70,Math.max(34,Math.floor(innerWidth/20)))},()=>({x:Math.random()*innerWidth,y:Math.random()*innerHeight,r:.45+Math.random()*1.2,v:.08+Math.random()*.22,a:.10+Math.random()*.35}))}
  function tick(){if(!ctx)return;ctx.clearRect(0,0,innerWidth,innerHeight);for(const p of dots){p.y-=p.v;if(p.y<-4){p.y=innerHeight+4;p.x=Math.random()*innerWidth}ctx.beginPath();ctx.fillStyle="rgba(170,158,255,"+p.a+")";ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fill()}requestAnimationFrame(tick)}
  resize();addEventListener("resize",resize,{passive:true});tick();
}

const fmt=n=>new Intl.NumberFormat("fr-FR").format(Number(n)||0);
function age(sec){sec=Math.max(0,Number(sec)||0);const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);return d?d+" j "+h+" h":h?h+" h "+m+" min":m+" min"}
function count(id,value){const el=document.getElementById(id);if(!el)return;const target=Math.max(0,Number(value)||0);if(reduced||!Number.isFinite(target)){el.textContent=fmt(target);return}const start=performance.now(),dur=760;function frame(now){const p=Math.min(1,(now-start)/dur),e=1-Math.pow(1-p,3);el.textContent=fmt(Math.round(target*e));if(p<1)requestAnimationFrame(frame)}requestAnimationFrame(frame)}

async function loadPublic(){try{const r=await fetch("/api/public",{cache:"no-store",credentials:"same-origin"});if(!r.ok)throw new Error("public");const d=await r.json(),active=Boolean(d.online),dot=$("#publicDot");$("#publicStatus").textContent=active?"Bot Discord connecté":"Service web disponible";$("#publicStatusDetail").textContent=active?"État public reçu depuis SentriX":"Cette instance web reste disponible pendant la bascule HA";dot.style.background=active?"var(--green)":"var(--amber)";dot.style.boxShadow=active?"0 0 18px rgba(89,221,160,.65)":"0 0 18px rgba(239,189,98,.45)";if(active||Number(d.guilds)>0){count("publicGuilds",d.guilds);count("publicMembers",d.members)}$("#publicLatency").textContent=d.latency_ms==null?"—":Math.round(d.latency_ms)+" ms";$("#publicUptime").textContent=age(d.uptime_seconds)}catch(_){$("#publicStatus").textContent="Site web disponible";$("#publicStatusDetail").textContent="Les statistiques Discord sont momentanément indisponibles";const dot=$("#publicDot");dot.style.background="var(--amber)";dot.style.boxShadow="0 0 18px rgba(239,189,98,.45)"}}
loadPublic();

const loader=$("#loader"),loaderText=$("#loaderText");let opening=false;
async function openDashboard(e){if(opening)return;e.preventDefault();opening=true;loader?.classList.add("show");loader?.setAttribute("aria-hidden","false");let target="/login";if(loaderText)loaderText.textContent="Vérification de votre session Discord…";try{const r=await fetch("/api/me",{cache:"no-store",credentials:"same-origin"});if(r.ok){target="/app";if(loaderText)loaderText.textContent="Session trouvée. Ouverture du dashboard…"}else if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}catch(_){if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}setTimeout(()=>location.assign(target),180)}
$$("[data-dashboard-entry]").forEach(a=>a.addEventListener("click",openDashboard));
addEventListener("pageshow",()=>{opening=false;loader?.classList.remove("show");loader?.setAttribute("aria-hidden","true")});

const params=new URLSearchParams(location.search);
if(params.get("auth")==="missing"){const notice=$("#sxAuthNotice");if(notice){notice.textContent="Connexion Discord momentanément indisponible. Réessayez dans quelques instants ou consultez le support.";notice.hidden=false}history.replaceState(null,"",location.pathname)}
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
