"""Landing page publique SentriX V2 — vitrine premium animée.

Aucune donnée privée n'est chargée. Les seuls chiffres dynamiques viennent de /api/public.
Le dashboard reste indépendant sur /app.
"""
from __future__ import annotations

import html


PAGE_TEMPLATE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07080c">
<meta name="color-scheme" content="dark">
<title>SentriX — Le centre de contrôle de votre serveur Discord</title>
<meta name="description" content="SentriX centralise modération, sécurité, tickets, logs, niveaux, économie, rôles, notifications, automatisations et intelligence artificielle dans une plateforme Discord moderne.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Le centre de contrôle de votre serveur Discord">
<meta property="og:description" content="Modération, sécurité, tickets, logs, économie, niveaux, automatisations et IA dans une seule expérience.">
<meta property="og:url" content="__CANONICAL__">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{
 --bg:#07080c;--bg2:#0a0d13;--surface:#0f131b;--surface2:#141a25;--surface3:#1a2230;
 --line:#242d3b;--line2:#344154;--text:#f7f8fb;--muted:#929dad;--soft:#cad1dc;
 --violet:#7568ff;--violet2:#a798ff;--blue:#51a8ff;--cyan:#64d5e8;--green:#5cdda0;--amber:#f0bf63;
 --nav:74px;--shadow:0 36px 100px rgba(0,0,0,.48);--mx:50vw;--my:20vh;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--bg)}
body{margin:0;min-height:100vh;overflow-x:hidden;color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;background:
 radial-gradient(900px 620px at 8% -10%,rgba(117,104,255,.20),transparent 62%),
 radial-gradient(820px 600px at 92% 8%,rgba(81,168,255,.13),transparent 58%),
 linear-gradient(180deg,#07080c 0%,#090c12 46%,#07090d 100%);-webkit-font-smoothing:antialiased}
body:before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:56px 56px;mask-image:linear-gradient(to bottom,black,transparent 80%)}
body:after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(480px circle at var(--mx) var(--my),rgba(117,104,255,.11),transparent 62%);transition:opacity .2s ease}
a{color:inherit;text-decoration:none}
button{font:inherit}
img{display:block;max-width:100%}
svg{display:block}
::selection{background:rgba(117,104,255,.38)}
:focus-visible{outline:2px solid var(--violet2);outline-offset:3px}
.skip{position:fixed;z-index:200;left:18px;top:-80px;padding:10px 14px;border-radius:10px;background:#fff;color:#07080c;font-weight:900}.skip:focus{top:14px}
.wrap{width:min(1220px,calc(100% - 42px));margin:0 auto}
.topbar{position:sticky;top:0;z-index:100;height:var(--nav);border-bottom:1px solid rgba(255,255,255,.055);background:rgba(7,8,12,.66);backdrop-filter:blur(20px) saturate(135%);transition:.25s ease}
.topbar.scrolled{background:rgba(7,8,12,.93);box-shadow:0 14px 45px rgba(0,0,0,.25)}
.navbar{height:100%;display:flex;align-items:center;justify-content:space-between;gap:24px}
.brand{display:flex;align-items:center;gap:11px;font-size:18px;font-weight:950;letter-spacing:-.03em;white-space:nowrap}
.brand img{width:40px;height:40px;border-radius:13px;border:1px solid rgba(255,255,255,.12);box-shadow:0 9px 28px rgba(0,0,0,.4)}
.navlinks{display:flex;align-items:center;gap:3px}.navlinks a{padding:9px 10px;border-radius:9px;color:var(--muted);font-size:13px;font-weight:760;transition:.17s ease}.navlinks a:hover{color:#fff;background:rgba(255,255,255,.05)}
.nav-actions{display:flex;align-items:center;gap:8px}.menu-btn{display:none;width:42px;height:42px;border:1px solid var(--line);border-radius:11px;background:var(--surface);color:#fff;cursor:pointer}.menu-btn i{display:block;width:18px;height:2px;margin:4px auto;border-radius:99px;background:currentColor}
.btn{position:relative;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:10px 16px;border:1px solid var(--line);border-radius:11px;background:rgba(20,26,37,.86);color:#fff;font-size:13px;font-weight:850;cursor:pointer;overflow:hidden;transition:transform .18s ease,border-color .18s ease,background .18s ease,box-shadow .18s ease}
.btn:before{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 30%,rgba(255,255,255,.09) 50%,transparent 70%);transform:translateX(-120%);transition:transform .5s ease}
.btn:hover{transform:translateY(-2px);border-color:#435067;background:#1a2130;box-shadow:0 14px 35px rgba(0,0,0,.25)}.btn:hover:before{transform:translateX(120%)}
.btn.primary{border-color:transparent;background:linear-gradient(135deg,#786cff,#5d59ea 60%,#4f87f5);box-shadow:0 13px 34px rgba(99,92,255,.27)}.btn.primary:hover{box-shadow:0 18px 44px rgba(99,92,255,.37)}
.btn.ghost{background:transparent}
.auth-notice{width:min(760px,calc(100% - 40px));margin:15px auto -25px;padding:12px 15px;border:1px solid rgba(240,191,99,.28);border-radius:11px;background:rgba(240,191,99,.07);color:#f5d8a1;font-size:12px}

/* HERO */
.hero-shell{position:relative;overflow:hidden}.hero-shell:before{content:"";position:absolute;left:50%;top:-300px;width:1050px;height:760px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(117,104,255,.18),rgba(81,168,255,.06) 40%,transparent 68%);filter:blur(18px);animation:heroGlow 7s ease-in-out infinite alternate}
.hero{position:relative;display:grid;grid-template-columns:minmax(0,.94fr) minmax(500px,1.06fr);gap:60px;align-items:center;min-height:calc(100vh - var(--nav));padding:78px 0 64px}
.hero-copy{position:relative;z-index:3;max-width:690px}
.eyebrow{display:inline-flex;align-items:center;gap:9px;padding:7px 11px;border:1px solid rgba(167,152,255,.25);border-radius:999px;background:rgba(117,104,255,.08);color:#c5bcff;font-size:11px;font-weight:950;letter-spacing:.10em;text-transform:uppercase;animation:heroUp .6s .04s both}
.eyebrow i{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 14px rgba(92,221,160,.8);animation:pulseDot 1.8s ease-in-out infinite}
.hero h1{margin:20px 0 20px;font-size:clamp(48px,6.2vw,82px);line-height:.96;letter-spacing:-.065em;text-wrap:balance;animation:heroUp .7s .10s both}.hero h1 span{background:linear-gradient(110deg,#fff 3%,#c7c0ff 45%,#70b7ff 92%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero .lead{margin:0;max-width:650px;color:var(--muted);font-size:18px;line-height:1.75;animation:heroUp .7s .18s both}
.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:30px;animation:heroUp .7s .26s both}
.hero-proof{display:flex;flex-wrap:wrap;gap:9px 20px;margin-top:22px;color:var(--muted);font-size:11px;animation:heroUp .7s .34s both}.hero-proof span{display:inline-flex;gap:7px;align-items:center}.hero-proof i{width:6px;height:6px;border-radius:50%;background:var(--violet)}
.hero-visual{position:relative;z-index:2;min-height:580px;perspective:1400px;animation:heroVisual .85s .16s both}
.hero-orbit{position:absolute;inset:40px 20px;border:1px solid rgba(117,104,255,.10);border-radius:50%;transform:rotate(-8deg);animation:orbitSpin 18s linear infinite}.hero-orbit:before,.hero-orbit:after{content:"";position:absolute;width:9px;height:9px;border-radius:50%;background:var(--violet2);box-shadow:0 0 22px rgba(167,152,255,.8)}.hero-orbit:before{left:14%;top:9%}.hero-orbit:after{right:9%;bottom:16%;background:var(--blue)}
.console{position:absolute;inset:36px 4px 40px 26px;display:grid;grid-template-columns:92px 1fr;overflow:hidden;border:1px solid rgba(255,255,255,.12);border-radius:25px;background:linear-gradient(145deg,rgba(19,24,34,.97),rgba(8,11,16,.99));box-shadow:0 42px 120px rgba(0,0,0,.58),0 0 70px rgba(117,104,255,.08);transform:rotateY(-5deg) rotateX(2deg);animation:consoleFloat 6.5s ease-in-out infinite}
.console-side{padding:18px 12px;border-right:1px solid var(--line);background:rgba(8,11,16,.75)}.console-logo{width:45px;height:45px;margin:0 auto 20px;border-radius:14px;background:linear-gradient(145deg,var(--violet),#5568e9);display:grid;place-items:center;font-weight:950;box-shadow:0 10px 28px rgba(117,104,255,.28)}
.console-nav{display:grid;gap:8px}.console-nav span{height:34px;border-radius:9px;background:#121722;position:relative;overflow:hidden}.console-nav span:before{content:"";position:absolute;left:10px;top:12px;width:30px;height:7px;border-radius:99px;background:#2d3648}.console-nav span.active{background:rgba(117,104,255,.14);box-shadow:inset 3px 0 0 var(--violet)}.console-nav span.active:before{background:#776bff}
.console-main{padding:22px 22px 18px;min-width:0}.console-top{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:18px}.console-title b{display:block;font-size:17px}.console-title small{color:var(--muted);font-size:10px}.status-pill{display:inline-flex;gap:7px;align-items:center;padding:6px 9px;border:1px solid rgba(92,221,160,.22);border-radius:99px;background:rgba(92,221,160,.07);color:#92e6bc;font-size:9px;font-weight:900}.status-pill i{width:6px;height:6px;border-radius:50%;background:var(--green)}
.console-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-bottom:10px}.metric-mini{padding:11px;border:1px solid var(--line);border-radius:11px;background:#0c1017}.metric-mini small{display:block;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.07em}.metric-mini b{display:block;margin-top:4px;font-size:15px}
.console-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:10px}.dash-card{padding:14px;border:1px solid var(--line);border-radius:13px;background:linear-gradient(160deg,#111620,#0c1017)}.dash-card h4{margin:0 0 3px;font-size:11px}.dash-card p{margin:0;color:var(--muted);font-size:8px}.dash-card.tall{grid-row:span 2}
.live-chart{height:84px;margin-top:14px;position:relative;overflow:hidden;border-radius:9px;background:linear-gradient(180deg,rgba(117,104,255,.07),transparent)}.live-chart svg{width:100%;height:100%}.chart-line{stroke-dasharray:260;stroke-dashoffset:260;animation:drawLine 2.2s .8s ease forwards}.chart-area{opacity:0;animation:fadeIn .8s 1.5s forwards}
.module-list{display:grid;gap:7px;margin-top:11px}.module-line{display:flex;justify-content:space-between;align-items:center;padding:8px;border-radius:8px;background:#0b0f16;font-size:8px;color:var(--soft)}.mini-toggle{width:27px;height:15px;border-radius:99px;background:rgba(117,104,255,.28);position:relative}.mini-toggle:after{content:"";position:absolute;right:3px;top:3px;width:9px;height:9px;border-radius:50%;background:#a798ff}
.event-feed{display:grid;gap:7px;margin-top:10px}.event{display:grid;grid-template-columns:24px 1fr;gap:7px;align-items:center;padding:7px;border-radius:8px;background:#0b0f16}.event i{width:24px;height:24px;border-radius:7px;background:rgba(81,168,255,.11);display:grid;place-items:center;color:#87c3ff;font-style:normal;font-size:7px;font-weight:900}.event b{display:block;font-size:8px}.event small{display:block;color:var(--muted);font-size:7px}
.floating-card{position:absolute;z-index:4;padding:13px 14px;border:1px solid rgba(167,152,255,.22);border-radius:14px;background:rgba(15,19,27,.94);backdrop-filter:blur(14px);box-shadow:0 18px 48px rgba(0,0,0,.35);animation:floatCard 5s ease-in-out infinite}.floating-card b{display:block;font-size:10px}.floating-card span{display:block;color:var(--muted);font-size:8px;margin-top:3px}.fc-one{right:-12px;top:82px}.fc-two{left:0;bottom:26px;animation-delay:-2.1s}
.command-pulse{display:flex;gap:5px;margin-top:8px}.command-pulse i{width:5px;height:5px;border-radius:50%;background:var(--violet);animation:dotWave 1.4s ease-in-out infinite}.command-pulse i:nth-child(2){animation-delay:.16s}.command-pulse i:nth-child(3){animation-delay:.32s}

/* LIVE STRIP */
.live-strip{position:relative;z-index:3;margin-top:-22px;display:grid;grid-template-columns:1.4fr repeat(4,1fr);gap:0;border:1px solid var(--line);border-radius:19px;background:rgba(13,17,24,.88);backdrop-filter:blur(14px);box-shadow:0 18px 55px rgba(0,0,0,.26);overflow:hidden}.live-cell{padding:16px 18px;border-left:1px solid var(--line)}.live-cell:first-child{border-left:0}.live-cell small{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.08em;font-weight:850}.live-cell strong{display:block;margin-top:4px;font-size:20px;letter-spacing:-.03em}.live-state{display:flex;align-items:center;gap:11px}.live-dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 18px rgba(92,221,160,.65)}.live-state b,.live-state span{display:block}.live-state b{font-size:12px}.live-state span{color:var(--muted);font-size:9px;margin-top:2px}

/* MARQUEE */
.module-marquee{overflow:hidden;margin:48px 0 0;border-top:1px solid rgba(255,255,255,.05);border-bottom:1px solid rgba(255,255,255,.05);background:rgba(255,255,255,.012)}.marquee-track{display:flex;width:max-content;gap:10px;padding:13px 0;animation:marquee 34s linear infinite}.module-chip{display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid var(--line);border-radius:999px;background:#0d1118;color:var(--soft);font-size:10px;font-weight:800;white-space:nowrap}.module-chip i{width:6px;height:6px;border-radius:50%;background:var(--violet)}

/* SECTIONS */
.section{padding:112px 0}.section-head{display:flex;justify-content:space-between;gap:36px;align-items:end;margin-bottom:42px}.section-head>div{max-width:720px}.kicker{color:var(--violet2);font-size:10px;font-weight:950;letter-spacing:.12em;text-transform:uppercase}.section h2{margin:9px 0 0;font-size:clamp(32px,4.6vw,54px);line-height:1.04;letter-spacing:-.05em;text-wrap:balance}.section-head p{max-width:450px;margin:0;color:var(--muted);line-height:1.75}

/* BENTO */
.bento{display:grid;grid-template-columns:repeat(12,1fr);grid-auto-rows:minmax(160px,auto);gap:13px}.bento-card{position:relative;overflow:hidden;padding:23px;border:1px solid var(--line);border-radius:19px;background:linear-gradient(145deg,rgba(20,26,37,.92),rgba(11,15,21,.94));transition:transform .22s ease,border-color .22s ease,box-shadow .22s ease}.bento-card:hover{transform:translateY(-4px);border-color:#3e4a60;box-shadow:0 20px 55px rgba(0,0,0,.26)}.bento-card:after{content:"";position:absolute;right:-70px;bottom:-70px;width:170px;height:170px;border-radius:50%;background:radial-gradient(circle,rgba(117,104,255,.12),transparent 68%);pointer-events:none}.bento-card.large{grid-column:span 6;grid-row:span 2}.bento-card.medium{grid-column:span 3}.bento-card.wide{grid-column:span 6}.bento-card.small{grid-column:span 3}.bento-icon{width:44px;height:44px;border:1px solid var(--line2);border-radius:13px;background:#192130;display:grid;place-items:center;color:#c8c0ff;font-size:10px;font-weight:950;letter-spacing:.04em}.bento-card h3{margin:18px 0 8px;font-size:18px}.bento-card p{margin:0;color:var(--muted);font-size:12px;line-height:1.68}.bento-card.large h3{font-size:23px}.mini-flow{display:grid;gap:8px;margin-top:22px}.flow-row{display:grid;grid-template-columns:34px 1fr auto;align-items:center;gap:9px;padding:9px;border:1px solid var(--line);border-radius:10px;background:#0b0f16}.flow-row i{width:32px;height:32px;border-radius:9px;background:rgba(117,104,255,.12);display:grid;place-items:center;color:#bbb3ff;font-style:normal;font-size:8px;font-weight:900}.flow-row b{font-size:9px}.flow-row small{display:block;color:var(--muted);font-size:7px}.flow-row em{font-style:normal;font-size:8px;color:#83ddb4}

/* SECURITY STORY */
.story{display:grid;grid-template-columns:.82fr 1.18fr;gap:38px;align-items:center}.story-copy p{color:var(--muted);line-height:1.75}.story-points{display:grid;gap:9px;margin:24px 0}.story-points div{display:flex;gap:10px;align-items:flex-start;padding:11px 12px;border:1px solid var(--line);border-radius:11px;background:#0c1017;color:var(--soft);font-size:12px}.story-points i{flex:none;width:20px;height:20px;border-radius:7px;background:rgba(117,104,255,.14);display:grid;place-items:center;color:#c6c0ff;font-style:normal;font-size:8px;font-weight:950}
.security-stage{position:relative;min-height:470px;padding:22px;border:1px solid rgba(117,104,255,.17);border-radius:24px;background:radial-gradient(circle at 70% 10%,rgba(117,104,255,.12),transparent 35%),linear-gradient(150deg,#10151f,#0a0d13);box-shadow:var(--shadow)}
.radar{position:absolute;right:28px;top:28px;width:190px;height:190px;border:1px solid rgba(117,104,255,.15);border-radius:50%;background:repeating-radial-gradient(circle,transparent 0 31px,rgba(117,104,255,.08) 32px 33px);overflow:hidden}.radar:before,.radar:after{content:"";position:absolute;left:50%;top:50%;background:rgba(117,104,255,.11);transform-origin:left center}.radar:before{width:50%;height:1px}.radar:after{width:50%;height:50%;background:conic-gradient(from -12deg,rgba(117,104,255,.28),transparent 46deg);animation:radarSpin 4s linear infinite}.radar-dot{position:absolute;width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 15px rgba(92,221,160,.8)}.rd1{left:60px;top:48px}.rd2{right:43px;bottom:58px}.rd3{left:80px;bottom:38px}
.security-feed{position:absolute;left:22px;bottom:22px;width:calc(100% - 44px);display:grid;gap:8px}.security-row{display:grid;grid-template-columns:40px 1fr auto;gap:10px;align-items:center;padding:11px;border:1px solid var(--line);border-radius:11px;background:rgba(10,14,20,.92);transform:translateX(-10px);opacity:0}.security-row.visible{animation:rowIn .5s forwards}.security-row:nth-child(2){animation-delay:.12s}.security-row:nth-child(3){animation-delay:.24s}.security-row i{width:36px;height:36px;border-radius:10px;background:rgba(81,168,255,.11);display:grid;place-items:center;color:#86c2ff;font-style:normal;font-size:8px;font-weight:900}.security-row b{display:block;font-size:10px}.security-row small{display:block;color:var(--muted);font-size:8px}.security-row em{font-style:normal;padding:5px 7px;border-radius:99px;background:rgba(92,221,160,.08);color:#8ce2b8;font-size:7px;font-weight:900}

/* DASHBOARD SHOWCASE */
.dashboard-zone{position:relative;display:grid;grid-template-columns:.72fr 1.28fr;gap:40px;align-items:center}.dashboard-copy p{color:var(--muted);line-height:1.75}.checklist{display:grid;gap:9px;margin:24px 0}.check{display:flex;gap:10px;align-items:center;color:var(--soft);font-size:12px}.check i{width:21px;height:21px;border-radius:7px;background:rgba(92,221,160,.10);display:grid;place-items:center;color:#88dfb5;font-style:normal;font-size:8px;font-weight:950}
.big-dashboard{position:relative;padding:12px;border:1px solid var(--line);border-radius:23px;background:#090c12;box-shadow:var(--shadow);transform:perspective(1400px) rotateY(2deg);transition:transform .3s ease}.big-dashboard:hover{transform:perspective(1400px) rotateY(0deg) translateY(-4px)}
.browserbar{height:38px;display:flex;align-items:center;gap:6px;padding:0 11px;border-bottom:1px solid var(--line)}.browserbar i{width:7px;height:7px;border-radius:50%;background:#323a4d}.browserbar i:nth-child(1){background:#ff7582}.browserbar i:nth-child(2){background:#f1c36b}.browserbar i:nth-child(3){background:#5cdda0}.browserbar span{margin-left:10px;color:#657084;font-size:8px}
.dashboard-inner{display:grid;grid-template-columns:160px 1fr;min-height:390px}.db-sidebar{padding:17px 11px;border-right:1px solid var(--line)}.db-sidebar b{display:block;margin:3px 8px 13px;font-size:12px}.db-sidebar span{display:block;margin:4px 0;padding:8px;border-radius:8px;color:var(--muted);font-size:8px}.db-sidebar span.active{background:rgba(117,104,255,.13);color:#d2cdff}.db-main{padding:18px}.db-main h3{margin:0;font-size:15px}.db-main>p{margin:3px 0 14px;color:var(--muted);font-size:9px}.db-cards{display:grid;grid-template-columns:1fr 1fr;gap:9px}.db-panel{padding:12px;border:1px solid var(--line);border-radius:11px;background:#10151e}.db-panel.full{grid-column:1/-1}.db-panel b{display:block;font-size:9px}.db-panel small{display:block;color:var(--muted);font-size:7px;margin-top:2px}.switch-list{display:grid;gap:7px;margin-top:11px}.switch-row{display:flex;justify-content:space-between;align-items:center;padding:8px;border-radius:8px;background:#0b0f15;color:var(--soft);font-size:8px}.switch-row i{width:28px;height:16px;border-radius:99px;background:rgba(117,104,255,.28);position:relative}.switch-row i:after{content:"";position:absolute;right:3px;top:3px;width:10px;height:10px;border-radius:50%;background:#a798ff}
.activity-bars{display:flex;align-items:end;gap:6px;height:70px;margin-top:12px}.activity-bars i{flex:1;min-width:5px;border-radius:5px 5px 2px 2px;background:linear-gradient(#7a6fff,#4357c8);height:var(--h);transform-origin:bottom;animation:barPulse 2.8s ease-in-out infinite}.activity-bars i:nth-child(2n){animation-delay:-.6s}.activity-bars i:nth-child(3n){animation-delay:-1.2s}

/* WORKFLOWS */
.workflows{display:grid;grid-template-columns:repeat(3,1fr);gap:13px}.workflow{position:relative;padding:23px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#111620,#0b0f15);overflow:hidden}.workflow-num{font-size:46px;font-weight:950;letter-spacing:-.06em;color:rgba(167,152,255,.16);line-height:1}.workflow h3{margin:8px 0 7px}.workflow p{margin:0;color:var(--muted);font-size:12px}.workflow:after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:linear-gradient(90deg,transparent,var(--violet),transparent);transform:scaleX(0);transition:transform .3s ease}.workflow:hover:after{transform:scaleX(1)}

/* AI + COMMAND */
.ai-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.ai-card,.terminal{padding:25px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,#111620,#0b0f15)}.ai-card p{color:var(--muted);line-height:1.7}.chat{margin-top:22px;padding:15px;border:1px solid var(--line);border-radius:14px;background:#090d13}.bubble{max-width:88%;padding:10px 12px;border-radius:11px;margin:7px 0;font-size:10px;opacity:0;transform:translateY(6px)}.bubble.visible{animation:bubbleIn .42s forwards}.bubble.user{margin-left:auto;background:rgba(117,104,255,.16);color:#e6e3ff}.bubble.bot{border:1px solid var(--line);background:#151b26;color:var(--soft)}
.terminal-head{display:flex;align-items:center;gap:6px;padding-bottom:13px;border-bottom:1px solid var(--line)}.terminal-head i{width:7px;height:7px;border-radius:50%;background:#343d50}.terminal-head span{margin-left:7px;color:var(--muted);font-size:9px}.terminal-body{padding-top:18px;font:11px/1.9 ui-monospace,SFMono-Regular,Menlo,monospace}.prompt{color:#8ee2b8}.cmd{color:#dcd8ff}.term-muted{color:#6f7a8c}.cursor{display:inline-block;width:7px;height:12px;margin-left:2px;vertical-align:-2px;background:#a798ff;animation:blink 1s steps(1) infinite}

/* FAQ + CTA */
.faq{display:grid;grid-template-columns:.78fr 1.22fr;gap:38px}.faq-copy p{color:var(--muted);line-height:1.7}.faq-list{display:grid;gap:8px}details{border:1px solid var(--line);border-radius:12px;background:#0e131b;overflow:hidden;transition:border-color .18s ease}details[open]{border-color:#3b465a}summary{padding:15px 17px;cursor:pointer;font-weight:850;list-style:none}summary::-webkit-details-marker{display:none}details p{padding:0 17px 16px;margin:0;color:var(--muted);font-size:12px;line-height:1.68}
.final{position:relative;overflow:hidden;padding:72px 25px;text-align:center;border:1px solid rgba(117,104,255,.22);border-radius:28px;background:linear-gradient(145deg,rgba(117,104,255,.13),rgba(13,17,24,.94));box-shadow:var(--shadow)}.final:before{content:"";position:absolute;left:50%;top:-220px;width:650px;height:500px;transform:translateX(-50%);border-radius:50%;background:radial-gradient(circle,rgba(167,152,255,.22),transparent 66%);animation:heroGlow 6s ease-in-out infinite alternate}.final>*{position:relative}.final h2{max-width:760px;margin:10px auto 13px}.final p{max-width:620px;margin:0 auto;color:var(--muted)}.final .hero-actions{justify-content:center}

/* FOOTER */
footer{margin-top:112px;padding:42px 0 34px;border-top:1px solid rgba(255,255,255,.06)}.footer-grid{display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:28px}.footer-brand p{max-width:340px;color:var(--muted);font-size:11px}.footer-col b{display:block;margin-bottom:10px;font-size:10px;text-transform:uppercase;letter-spacing:.09em}.footer-col a{display:block;width:max-content;max-width:100%;margin:7px 0;color:var(--muted);font-size:11px}.footer-col a:hover{color:#fff}.footer-bottom{display:flex;justify-content:space-between;gap:18px;margin-top:30px;padding-top:19px;border-top:1px solid var(--line);color:var(--muted);font-size:10px}

/* MOTION */
.reveal{opacity:0;transform:translateY(24px) scale(.985);transition:opacity .65s cubic-bezier(.2,.8,.2,1),transform .65s cubic-bezier(.2,.8,.2,1)}.reveal.visible{opacity:1;transform:none}.stagger>*{opacity:0;transform:translateY(16px)}.stagger.visible>*{animation:staggerIn .52s forwards}.stagger.visible>*:nth-child(2){animation-delay:.05s}.stagger.visible>*:nth-child(3){animation-delay:.10s}.stagger.visible>*:nth-child(4){animation-delay:.15s}.stagger.visible>*:nth-child(5){animation-delay:.20s}.stagger.visible>*:nth-child(6){animation-delay:.25s}
.progress-line{position:fixed;z-index:110;left:0;top:0;width:100%;height:2px;transform-origin:left;transform:scaleX(0);background:linear-gradient(90deg,var(--violet),var(--blue));box-shadow:0 0 14px rgba(117,104,255,.6)}
.sx-loader{position:fixed;inset:0;z-index:999;display:grid;place-items:center;background:rgba(5,7,10,.82);backdrop-filter:blur(15px);opacity:0;visibility:hidden;transition:.18s ease}.sx-loader.show{opacity:1;visibility:visible}.loader-card{width:min(360px,calc(100vw - 34px));padding:28px;text-align:center;border:1px solid var(--line2);border-radius:19px;background:linear-gradient(#171d28,#0c1017);box-shadow:var(--shadow)}.spinner{width:40px;height:40px;margin:0 auto 15px;border:3px solid rgba(255,255,255,.08);border-top-color:var(--violet2);border-right-color:var(--blue);border-radius:50%;animation:spin .7s linear infinite}.loader-card b{display:block}.loader-card span{display:block;margin-top:6px;color:var(--muted);font-size:10px}
@keyframes heroUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}@keyframes heroVisual{from{opacity:0;transform:translateX(34px) scale(.95)}to{opacity:1;transform:none}}@keyframes heroGlow{to{transform:translateX(-50%) scale(1.08);opacity:.72}}@keyframes pulseDot{50%{box-shadow:0 0 25px rgba(92,221,160,1);transform:scale(1.15)}}@keyframes consoleFloat{50%{transform:rotateY(-3deg) rotateX(1deg) translateY(-10px)}}@keyframes floatCard{50%{transform:translateY(-8px)}}@keyframes orbitSpin{to{transform:rotate(352deg)}}@keyframes drawLine{to{stroke-dashoffset:0}}@keyframes fadeIn{to{opacity:1}}@keyframes dotWave{50%{transform:translateY(-4px);opacity:.45}}@keyframes marquee{to{transform:translateX(-50%)}}@keyframes radarSpin{to{transform:rotate(360deg)}}@keyframes rowIn{to{opacity:1;transform:none}}@keyframes barPulse{50%{transform:scaleY(.72);opacity:.75}}@keyframes bubbleIn{to{opacity:1;transform:none}}@keyframes blink{50%{opacity:0}}@keyframes staggerIn{to{opacity:1;transform:none}}@keyframes spin{to{transform:rotate(360deg)}}

/* RESPONSIVE */
@media(max-width:1080px){
 .navlinks{display:none}.menu-btn{display:block}.navbar.open .navlinks{display:flex;position:absolute;top:calc(var(--nav) - 1px);left:20px;right:20px;flex-direction:column;align-items:stretch;padding:10px;border:1px solid var(--line);border-radius:14px;background:rgba(11,14,20,.98);box-shadow:var(--shadow)}.navbar.open .navlinks a{padding:11px}
 .hero{grid-template-columns:1fr;min-height:auto;padding-top:70px}.hero-copy{max-width:800px}.hero-visual{width:min(760px,100%);margin:0 auto}.live-strip{grid-template-columns:1.4fr repeat(3,1fr)}.live-cell:last-child{display:none}
 .bento-card.large{grid-column:span 8}.bento-card.medium{grid-column:span 4}.bento-card.wide{grid-column:span 8}.bento-card.small{grid-column:span 4}
 .story,.dashboard-zone{grid-template-columns:1fr}.security-stage{min-height:460px}.ai-grid{grid-template-columns:1fr}.footer-grid{grid-template-columns:1.3fr 1fr 1fr}.footer-col:last-child{display:none}
}
@media(max-width:720px){
 :root{--nav:66px}.wrap{width:min(100% - 28px,1220px)}.nav-actions>.btn.ghost{display:none}.nav-actions>.btn.primary{padding:9px 11px}.hero{padding:52px 0 42px;gap:26px}.hero h1{font-size:clamp(42px,13vw,61px)}.hero .lead{font-size:16px}.hero-visual{min-height:400px}.console{inset:8px 0 12px;grid-template-columns:64px 1fr;transform:none;animation:none}.console-side{padding:12px 8px}.console-logo{width:35px;height:35px}.console-main{padding:13px}.console-metrics{grid-template-columns:1fr 1fr}.metric-mini:last-child{display:none}.console-grid{grid-template-columns:1fr}.dash-card.tall{grid-row:auto}.floating-card,.hero-orbit{display:none}
 .live-strip{grid-template-columns:1fr 1fr;margin-top:0}.live-cell{border-left:0;border-top:1px solid var(--line)}.live-cell:first-child{grid-column:1/-1;border-top:0}.live-cell:last-child{display:block}
 .section{padding:78px 0}.section-head{display:block}.section-head p{margin-top:14px}.bento{grid-template-columns:1fr}.bento-card.large,.bento-card.medium,.bento-card.wide,.bento-card.small{grid-column:auto;grid-row:auto}
 .security-stage{min-height:520px}.radar{width:150px;height:150px}.security-row{grid-template-columns:35px 1fr}.security-row em{display:none}.big-dashboard{transform:none}.dashboard-inner{grid-template-columns:100px 1fr}.db-sidebar{padding:12px 6px}.db-main{padding:12px}.db-cards{grid-template-columns:1fr}.db-panel.full{grid-column:auto}
 .workflows{grid-template-columns:1fr}.faq{grid-template-columns:1fr}.footer-grid{grid-template-columns:1fr 1fr}.footer-brand{grid-column:1/-1}.footer-bottom{display:block}.footer-bottom span{display:block;margin-top:5px}
}
@media(max-width:430px){
 .hero-actions .btn{width:100%}.hero-visual{min-height:355px}.console-nav span{height:27px}.console-metrics{display:none}.live-chart{height:70px}.section h2{font-size:34px}.security-stage{min-height:560px}.radar{right:50%;transform:translateX(50%)}.security-feed{top:220px;bottom:auto}.dashboard-inner{grid-template-columns:80px 1fr}.db-sidebar span{font-size:7px;padding:7px 5px}
}
@media(prefers-reduced-motion:reduce){
 html{scroll-behavior:auto}body:after{display:none}.hero-shell:before,.eyebrow i,.hero-orbit,.console,.floating-card,.chart-line,.chart-area,.command-pulse i,.marquee-track,.radar:after,.activity-bars i,.final:before,.spinner,.cursor{animation:none!important}.eyebrow,.hero h1,.hero .lead,.hero-actions,.hero-proof,.hero-visual,.security-row,.bubble,.reveal,.stagger>*{opacity:1!important;transform:none!important;animation:none!important;transition:none!important}.btn,.bento-card,.big-dashboard,.topbar{transition:none!important}
}
</style>
</head>
<body>
<a class="skip" href="#main">Aller au contenu</a>
<div class="progress-line" id="progress"></div>
<header class="topbar" id="topbar">
 <div class="wrap navbar" id="navbar">
  <a class="brand" href="/" aria-label="SentriX, accueil"><img src="/sentrix-avatar.png?v=55" width="40" height="40" alt=""><span>SentriX</span></a>
  <nav class="navlinks" id="navlinks" aria-label="Navigation principale">
   <a href="#features">Fonctions</a><a href="#security">Sécurité</a><a href="#dashboard">Dashboard</a><a href="#automation">Automatisation</a><a href="#ai">IA</a><a href="#faq">FAQ</a><a href="/support">Support</a>
  </nav>
  <div class="nav-actions"><a class="btn ghost" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a><a class="btn primary" href="/app" data-dashboard-entry>Dashboard</a><button class="menu-btn" id="menuBtn" type="button" aria-expanded="false" aria-controls="navlinks" aria-label="Ouvrir le menu"><i></i><i></i><i></i></button></div>
 </div>
</header>
<p id="sxAuthNotice" class="auth-notice" hidden></p>

<main id="main">
<section class="hero-shell">
 <div class="wrap hero">
  <div class="hero-copy">
   <div class="eyebrow"><i></i>SentriX · plateforme Discord</div>
   <h1>Votre serveur Discord. <span>Enfin sous contrôle.</span></h1>
   <p class="lead">Une seule plateforme pour protéger, modérer, automatiser et faire vivre votre communauté. Dashboard, AutoMod, sécurité, tickets, logs, économie, niveaux et IA travaillent ensemble au lieu de s’empiler.</p>
   <div class="hero-actions"><a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a><a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX à Discord</a><a class="btn ghost" href="#features">Explorer les fonctions</a></div>
   <div class="hero-proof"><span><i></i>Configuration par serveur</span><span><i></i>Slash + préfixe</span><span><i></i>Dashboard web</span><span><i></i>Architecture HA</span></div>
  </div>
  <div class="hero-visual" id="heroVisual" aria-label="Aperçu animé du dashboard SentriX">
   <div class="hero-orbit"></div>
   <div class="console">
    <aside class="console-side"><div class="console-logo">S</div><div class="console-nav"><span class="active"></span><span></span><span></span><span></span><span></span><span></span><span></span></div></aside>
    <div class="console-main">
     <div class="console-top"><div class="console-title"><b>Centre de contrôle</b><small>Vue d’ensemble du serveur</small></div><div class="status-pill"><i></i>Synchronisé</div></div>
     <div class="console-metrics"><div class="metric-mini"><small>Protection</small><b>Active</b></div><div class="metric-mini"><small>Tickets</small><b>Centre staff</b></div><div class="metric-mini"><small>Automatisation</small><b>Prête</b></div></div>
     <div class="console-grid">
      <div class="dash-card tall"><h4>Activité du serveur</h4><p>Les métriques réelles restent réservées au dashboard connecté.</p><div class="live-chart"><svg viewBox="0 0 260 90" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7568ff" stop-opacity=".28"/><stop offset="1" stop-color="#7568ff" stop-opacity="0"/></linearGradient></defs><path class="chart-area" d="M0 72 C35 55 45 68 72 48 S112 30 137 45 S176 70 202 39 S232 31 260 17 L260 90 L0 90Z" fill="url(#cg)"/><path class="chart-line" d="M0 72 C35 55 45 68 72 48 S112 30 137 45 S176 70 202 39 S232 31 260 17" fill="none" stroke="#8f83ff" stroke-width="2.3"/></svg></div></div>
      <div class="dash-card"><h4>Modules</h4><p>Activation centralisée.</p><div class="module-list"><div class="module-line"><span>AutoMod</span><i class="mini-toggle"></i></div><div class="module-line"><span>Logs</span><i class="mini-toggle"></i></div><div class="module-line"><span>Tickets</span><i class="mini-toggle"></i></div></div></div>
      <div class="dash-card"><h4>Événements récents</h4><div class="event-feed"><div class="event"><i>LG</i><div><b>Log enregistré</b><small>Événement serveur</small></div></div><div class="event"><i>SC</i><div><b>Protection active</b><small>Règles synchronisées</small></div></div></div></div>
     </div>
    </div>
   </div>
   <div class="floating-card fc-one"><b>Protection multicouche</b><span>AutoMod · anti-raid · logs</span><div class="command-pulse"><i></i><i></i><i></i></div></div>
   <div class="floating-card fc-two"><b>Dashboard unifié</b><span>Les réglages restent au même endroit.</span></div>
  </div>
 </div>
</section>

<section class="wrap live-strip reveal" aria-label="État public SentriX">
 <div class="live-cell live-state"><i class="live-dot" id="publicDot"></i><div><b id="publicStatus">Service web disponible</b><span id="publicStatusDetail">Chargement de l’état Discord…</span></div></div>
 <div class="live-cell"><small>Serveurs</small><strong id="publicGuilds">—</strong></div>
 <div class="live-cell"><small>Membres accessibles</small><strong id="publicMembers">—</strong></div>
 <div class="live-cell"><small>Latence</small><strong id="publicLatency">—</strong></div>
 <div class="live-cell"><small>Uptime</small><strong id="publicUptime">—</strong></div>
</section>

<div class="module-marquee" aria-hidden="true"><div class="marquee-track" id="marquee">
 <span class="module-chip"><i></i>AutoMod</span><span class="module-chip"><i></i>Sécurité</span><span class="module-chip"><i></i>Tickets</span><span class="module-chip"><i></i>Logs</span><span class="module-chip"><i></i>Niveaux</span><span class="module-chip"><i></i>Économie</span><span class="module-chip"><i></i>Rôles</span><span class="module-chip"><i></i>Bienvenue</span><span class="module-chip"><i></i>Notifications</span><span class="module-chip"><i></i>Invitations</span><span class="module-chip"><i></i>IA</span><span class="module-chip"><i></i>Jeux</span>
 <span class="module-chip"><i></i>AutoMod</span><span class="module-chip"><i></i>Sécurité</span><span class="module-chip"><i></i>Tickets</span><span class="module-chip"><i></i>Logs</span><span class="module-chip"><i></i>Niveaux</span><span class="module-chip"><i></i>Économie</span><span class="module-chip"><i></i>Rôles</span><span class="module-chip"><i></i>Bienvenue</span><span class="module-chip"><i></i>Notifications</span><span class="module-chip"><i></i>Invitations</span><span class="module-chip"><i></i>IA</span><span class="module-chip"><i></i>Jeux</span>
</div></div>

<section class="wrap section" id="features">
 <div class="section-head reveal"><div><span class="kicker">Un seul écosystème</span><h2>Pas juste un bot. Un vrai centre de contrôle.</h2></div><p>Chaque module partage la même logique de permissions, la même configuration par serveur et le même dashboard.</p></div>
 <div class="bento stagger">
  <article class="bento-card large"><div class="bento-icon">SE</div><h3>Sécurité & AutoMod</h3><p>Anti-spam, anti-raid, protections sensibles, règles AutoMod, vérification et journalisation réunis dans le même environnement.</p><div class="mini-flow"><div class="flow-row"><i>01</i><div><b>Événement détecté</b><small>Une règle correspond au contexte.</small></div><em>Analyse</em></div><div class="flow-row"><i>02</i><div><b>Action contrôlée</b><small>Les permissions sont vérifiées.</small></div><em>Protection</em></div><div class="flow-row"><i>03</i><div><b>Trace disponible</b><small>Le staff retrouve l’événement dans les logs.</small></div><em>Journal</em></div></div></article>
  <article class="bento-card medium"><div class="bento-icon">TK</div><h3>Tickets</h3><p>Assistance structurée, gestion staff, formulaires et historique.</p></article>
  <article class="bento-card medium"><div class="bento-icon">LG</div><h3>Logs</h3><p>Messages, membres, rôles, salons, sécurité et modération.</p></article>
  <article class="bento-card medium"><div class="bento-icon">EC</div><h3>Économie</h3><p>Portefeuille, récompenses, objets et boutique reliés aux activités.</p></article>
  <article class="bento-card medium"><div class="bento-icon">LV</div><h3>Niveaux</h3><p>XP, progression, classements et récompenses communautaires.</p></article>
  <article class="bento-card wide"><div class="bento-icon">AI</div><h3>Intelligence artificielle</h3><p>Une interface naturelle pour aider à comprendre SentriX, retrouver le bon réglage et guider certaines actions sans inventer de commandes.</p></article>
  <article class="bento-card small"><div class="bento-icon">RL</div><h3>Rôles</h3><p>Autoroles et systèmes interactifs.</p></article>
  <article class="bento-card small"><div class="bento-icon">NT</div><h3>Notifications</h3><p>Sources et alertes centralisées.</p></article>
  <article class="bento-card small"><div class="bento-icon">IV</div><h3>Invitations</h3><p>Suivi et récompenses configurables.</p></article>
  <article class="bento-card small"><div class="bento-icon">GM</div><h3>Jeux</h3><p>Activités communautaires et économie.</p></article>
 </div>
</section>

<section class="wrap section" id="security">
 <div class="story">
  <div class="story-copy reveal"><span class="kicker">Sécurité</span><h2>Voir le problème. Réagir. Garder une trace.</h2><p>SentriX ne promet pas un serveur “impossible à attaquer”. Il regroupe les protections, les permissions et les logs nécessaires pour réduire les abus et aider le staff à comprendre ce qui s’est passé.</p><div class="story-points"><div><i>01</i><span>Détection des comportements indésirables avec AutoMod et protections configurables.</span></div><div><i>02</i><span>Contrôles dédiés aux actions sensibles sur les rôles, salons et permissions.</span></div><div><i>03</i><span>Historique et logs pour éviter de modérer à l’aveugle.</span></div></div><a class="btn" href="/start">Voir comment démarrer</a></div>
  <div class="security-stage reveal" id="securityStage"><div class="radar"><i class="radar-dot rd1"></i><i class="radar-dot rd2"></i><i class="radar-dot rd3"></i></div><div class="security-feed"><div class="security-row"><i>AM</i><div><b>AutoMod</b><small>Une règle de contenu vient d’être évaluée.</small></div><em>Analysé</em></div><div class="security-row"><i>LG</i><div><b>Journalisation</b><small>L’événement est associé au bon contexte.</small></div><em>Enregistré</em></div><div class="security-row"><i>ST</i><div><b>Staff</b><small>Les informations utiles sont regroupées pour décision.</small></div><em>Prêt</em></div></div></div>
 </div>
</section>

<section class="wrap section" id="dashboard">
 <div class="dashboard-zone">
  <div class="dashboard-copy reveal"><span class="kicker">Dashboard</span><h2>Configurez votre serveur sans vous battre avec 80 commandes.</h2><p>Le dashboard SentriX transforme les principaux réglages en écrans cohérents, avec sélection du serveur, contrôles, aperçus et validation des droits Discord.</p><div class="checklist"><div class="check"><i>✓</i><span>Configuration isolée par serveur</span></div><div class="check"><i>✓</i><span>Modules regroupés dans une navigation unique</span></div><div class="check"><i>✓</i><span>OAuth Discord uniquement quand l’administration est nécessaire</span></div></div><a class="btn primary" href="/app" data-dashboard-entry>Entrer dans le dashboard</a></div>
  <div class="big-dashboard reveal" id="dashboardMockup"><div class="browserbar"><i></i><i></i><i></i><span>SentriX / Dashboard</span></div><div class="dashboard-inner"><aside class="db-sidebar"><b>SentriX</b><span>Vue d’ensemble</span><span>Communauté</span><span>Rôles</span><span class="active">Sécurité</span><span>Logs</span><span>Tickets</span><span>Économie</span><span>Notifications</span></aside><div class="db-main"><h3>Sécurité</h3><p>Protections et règles du serveur.</p><div class="db-cards"><div class="db-panel"><b>Modules actifs</b><small>État de la configuration</small><div class="switch-list"><div class="switch-row"><span>Anti-spam</span><i></i></div><div class="switch-row"><span>Anti-liens</span><i></i></div><div class="switch-row"><span>Vérification</span><i></i></div></div></div><div class="db-panel"><b>Activité</b><small>Illustration sans données fictives</small><div class="activity-bars"><i style="--h:46%"></i><i style="--h:72%"></i><i style="--h:58%"></i><i style="--h:84%"></i><i style="--h:66%"></i><i style="--h:92%"></i><i style="--h:70%"></i></div></div><div class="db-panel full"><b>Règles du serveur</b><small>Les changements réels sont enregistrés depuis le dashboard connecté.</small><div class="switch-list"><div class="switch-row"><span>Protection des mentions massives</span><i></i></div><div class="switch-row"><span>Journalisation des actions sensibles</span><i></i></div></div></div></div></div></div></div>
 </div>
</section>

<section class="wrap section" id="automation">
 <div class="section-head reveal"><div><span class="kicker">Automatiser sans perdre le contrôle</span><h2>Des flux simples pour les tâches répétitives.</h2></div><p>Bienvenue, rôles, notifications et outils communautaires peuvent être configurés pour réduire les actions manuelles du staff.</p></div>
 <div class="workflows stagger"><article class="workflow"><div class="workflow-num">01</div><h3>Bienvenue & départs</h3><p>Messages personnalisés, variables de serveur et aperçu avant publication.</p></article><article class="workflow"><div class="workflow-num">02</div><h3>Rôles & progression</h3><p>Autoroles, niveaux et récompenses reliés à la vie de la communauté.</p></article><article class="workflow"><div class="workflow-num">03</div><h3>Notifications</h3><p>Centralisez les sources utiles dans les salons choisis avec déduplication et historique.</p></article></div>
</section>

<section class="wrap section" id="ai">
 <div class="section-head reveal"><div><span class="kicker">IA & commandes</span><h2>Parlez à SentriX comme à un outil, pas comme à une documentation.</h2></div><p>Les commandes restent disponibles, mais l’IA peut aussi vous guider vers la bonne fonction sans inventer de raccourcis inexistants.</p></div>
 <div class="ai-grid">
  <div class="ai-card reveal"><h3>Assistance naturelle</h3><p>SentriX peut expliquer où se trouve une option, aider à comprendre une fonction ou orienter vers les commandes réellement chargées.</p><div class="chat" id="chatDemo"><div class="bubble user">Où je règle les logs de modération ?</div><div class="bubble bot">Dans le dashboard, choisissez votre serveur puis ouvrez la section Logs. Les catégories et salons configurés y sont regroupés.</div><div class="bubble user">Et si je préfère le préfixe + ?</div><div class="bubble bot">Les commandes préfixées utiles restent disponibles quand elles existent réellement.</div></div></div>
  <div class="terminal reveal"><div class="terminal-head"><i></i><i></i><i></i><span>Discord · commandes SentriX</span></div><div class="terminal-body"><div><span class="prompt">membre</span> <span class="term-muted">›</span> <span class="cmd">+help</span></div><div class="term-muted">SentriX affiche les commandes réellement disponibles.</div><br><div><span class="prompt">membre</span> <span class="term-muted">›</span> <span class="cmd">/help</span></div><div class="term-muted">Les commandes slash restent prises en charge.</div><br><div><span class="prompt">membre</span> <span class="term-muted">›</span> <span class="cmd">SentriX, où est la sécurité ?</span><span class="cursor"></span></div></div></div>
 </div>
</section>

<section class="wrap section">
 <div class="section-head reveal"><div><span class="kicker">Démarrage</span><h2>Ajoutez. Connectez. Configurez.</h2></div><p>Le site public ne demande aucune connexion. Discord OAuth intervient uniquement pour l’administration.</p></div>
 <div class="workflows stagger"><article class="workflow"><div class="workflow-num">01</div><h3>Ajoutez SentriX</h3><p>Choisissez le serveur Discord sur lequel vous souhaitez installer le bot.</p></article><article class="workflow"><div class="workflow-num">02</div><h3>Ouvrez le dashboard</h3><p>Connectez-vous avec Discord pour retrouver les serveurs que vous pouvez administrer.</p></article><article class="workflow"><div class="workflow-num">03</div><h3>Activez vos modules</h3><p>Configurez uniquement ce dont votre communauté a besoin.</p></article></div>
</section>

<section class="wrap section" id="faq">
 <div class="faq">
  <div class="faq-copy reveal"><span class="kicker">FAQ</span><h2>Les questions qui comptent vraiment.</h2><p>Pas de faux chiffres, pas de promesses absolues : uniquement le fonctionnement réel de SentriX.</p><a class="btn ghost" href="/support">Ouvrir le support</a></div>
  <div class="faq-list reveal"><details><summary>Dois-je me connecter pour voir ce site ?</summary><p>Non. La page d’accueil et les ressources publiques restent accessibles sans session. La connexion Discord est demandée uniquement pour ouvrir le dashboard d’administration.</p></details><details><summary>SentriX remplace-t-il tous les autres bots ?</summary><p>SentriX regroupe de nombreuses fonctions courantes, mais l’objectif est surtout de centraliser les outils qu’il fournit réellement : modération, sécurité, tickets, logs, communauté, économie, automatisations et IA.</p></details><details><summary>Les commandes avec + vont-elles disparaître ?</summary><p>Les commandes préfixées utiles peuvent rester disponibles en parallèle des commandes slash. La liste publique des commandes reflète ce qui est réellement chargé.</p></details><details><summary>Comment fonctionne la sécurité ?</summary><p>Elle combine plusieurs protections configurables et des logs. Aucune solution ne garantit qu’un serveur est impossible à attaquer ; les permissions et la configuration restent essentielles.</p></details><details><summary>Mes serveurs partagent-ils leurs réglages ?</summary><p>Non. La configuration SentriX est conçue pour rester séparée par serveur.</p></details><details><summary>Où trouver les commandes ?</summary><p>La page Commandes expose les commandes slash et préfixées réellement disponibles.</p></details></div>
 </div>
</section>

<section class="wrap final reveal"><span class="kicker">Prêt à utiliser SentriX ?</span><h2>Une seule plateforme pour faire tourner votre serveur proprement.</h2><p>Ajoutez le bot à Discord ou ouvrez le dashboard pour commencer à configurer votre serveur.</p><div class="hero-actions"><a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a><a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a></div></section>
</main>

<footer><div class="wrap"><div class="footer-grid"><div class="footer-brand"><a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" width="40" height="40" alt=""><span>SentriX</span></a><p>Plateforme Discord pour centraliser modération, sécurité, communauté et automatisations dans un seul environnement.</p></div><div class="footer-col"><b>Produit</b><a href="#features">Fonctions</a><a href="#security">Sécurité</a><a href="/dashboard-sentrix">Dashboard</a><a href="/stats">Statistiques</a></div><div class="footer-col"><b>Ressources</b><a href="/commands">Commandes</a><a href="/start">Commencer</a><a href="/support">Support</a><a href="/media-kit">Media kit</a></div><div class="footer-col"><b>Légal</b><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a></div></div><div class="footer-bottom"><span>SentriX — plateforme Discord tout-en-un.</span><span>Données publiques affichées uniquement lorsqu’elles viennent du service réel.</span></div></div></footer>

<div class="sx-loader" id="sxDashboardLoader" aria-hidden="true"><div class="loader-card"><div class="spinner"></div><b>Ouverture du dashboard</b><span id="sxDashboardLoaderText">Vérification de votre session Discord…</span></div></div>
<script>
(()=>{
 "use strict";
 const qs=(s,r=document)=>r.querySelector(s),qsa=(s,r=document)=>Array.from(r.querySelectorAll(s));
 const reduced=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
 const nav=qs("#navbar"),menu=qs("#menuBtn"),topbar=qs("#topbar"),progress=qs("#progress");
 function closeMenu(){nav?.classList.remove("open");menu?.setAttribute("aria-expanded","false")}
 menu?.addEventListener("click",()=>{const open=nav?.classList.toggle("open");menu.setAttribute("aria-expanded",open?"true":"false")});
 qsa("#navlinks a").forEach(a=>a.addEventListener("click",closeMenu));
 document.addEventListener("click",e=>{if(nav?.classList.contains("open")&&!nav.contains(e.target))closeMenu()});
 function onScroll(){const y=window.scrollY,max=Math.max(1,document.documentElement.scrollHeight-innerHeight);topbar?.classList.toggle("scrolled",y>12);if(progress)progress.style.transform="scaleX("+Math.min(1,y/max)+")"}
 window.addEventListener("scroll",onScroll,{passive:true});onScroll();
 if(!reduced){window.addEventListener("pointermove",e=>{document.documentElement.style.setProperty("--mx",e.clientX+"px");document.documentElement.style.setProperty("--my",e.clientY+"px")},{passive:true})}

 const reveals=qsa(".reveal,.stagger");
 if(!reduced&&"IntersectionObserver" in window){
   const io=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add("visible");io.unobserve(entry.target)}}),{threshold:.10,rootMargin:"0px 0px -40px"});
   reveals.forEach(el=>io.observe(el));
 }else reveals.forEach(el=>el.classList.add("visible"));

 const sec=qs("#securityStage");
 if(sec){
   const rows=qsa(".security-row",sec);
   if(!reduced&&"IntersectionObserver" in window){const sio=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){rows.forEach(r=>r.classList.add("visible"));sio.disconnect()}}),{threshold:.3});sio.observe(sec)}else rows.forEach(r=>r.classList.add("visible"));
 }
 const chat=qs("#chatDemo");
 if(chat){
   const bubbles=qsa(".bubble",chat);
   if(!reduced&&"IntersectionObserver" in window){const cio=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){bubbles.forEach((b,i)=>setTimeout(()=>b.classList.add("visible"),i*180));cio.disconnect()}}),{threshold:.35});cio.observe(chat)}else bubbles.forEach(b=>b.classList.add("visible"));
 }

 if(!reduced){
   const visual=qs("#heroVisual"),dash=qs("#dashboardMockup");
   function tilt(el,e,amount){if(!el)return;const r=el.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;el.style.transform="perspective(1400px) rotateX("+(-y*amount)+"deg) rotateY("+(x*amount)+"deg)"}
   visual?.addEventListener("pointermove",e=>tilt(visual,e,3));visual?.addEventListener("pointerleave",()=>visual.style.transform="");
   dash?.addEventListener("pointermove",e=>tilt(dash,e,2.2));dash?.addEventListener("pointerleave",()=>dash.style.transform="");
 }

 const fmt=n=>new Intl.NumberFormat("fr-FR").format(Number(n)||0);
 function age(sec){sec=Math.max(0,Number(sec)||0);const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);return d?d+" j "+h+" h":h?h+" h "+m+" min":m+" min"}
 function animateNum(id,value){const el=document.getElementById(id);if(!el)return;const target=Math.max(0,Number(value)||0);if(reduced||!Number.isFinite(target)){el.textContent=fmt(target);return}const start=performance.now(),dur=720;function frame(now){const p=Math.min(1,(now-start)/dur),e=1-Math.pow(1-p,3);el.textContent=fmt(Math.round(target*e));if(p<1)requestAnimationFrame(frame)}requestAnimationFrame(frame)}
 async function loadPublic(){
   try{
     const r=await fetch("/api/public",{cache:"no-store",credentials:"same-origin"});if(!r.ok)throw new Error("public");
     const d=await r.json(),active=Boolean(d.online),dot=document.getElementById("publicDot");
     document.getElementById("publicStatus").textContent=active?"Bot Discord connecté":"Service web disponible";
     document.getElementById("publicStatusDetail").textContent=active?"État public reçu depuis SentriX":"Cette instance web reste disponible pendant la bascule HA";
     dot.style.background=active?"var(--green)":"var(--amber)";dot.style.boxShadow=active?"0 0 18px rgba(92,221,160,.65)":"0 0 18px rgba(240,191,99,.45)";
     if(active||Number(d.guilds)>0){animateNum("publicGuilds",d.guilds);animateNum("publicMembers",d.members)}
     document.getElementById("publicLatency").textContent=d.latency_ms==null?"—":Math.round(d.latency_ms)+" ms";
     document.getElementById("publicUptime").textContent=age(d.uptime_seconds);
   }catch(_){
     document.getElementById("publicStatus").textContent="Site web disponible";
     document.getElementById("publicStatusDetail").textContent="Les statistiques Discord sont momentanément indisponibles";
     const dot=document.getElementById("publicDot");dot.style.background="var(--amber)";dot.style.boxShadow="0 0 18px rgba(240,191,99,.45)";
   }
 }
 loadPublic();

 const overlay=qs("#sxDashboardLoader"),loaderText=qs("#sxDashboardLoaderText");let opening=false;
 async function openDashboard(event){
   if(opening)return;event.preventDefault();opening=true;overlay?.classList.add("show");overlay?.setAttribute("aria-hidden","false");
   if(loaderText)loaderText.textContent="Vérification de votre session Discord…";let target="/login";
   try{const response=await fetch("/api/me",{cache:"no-store",credentials:"same-origin"});if(response.ok){target="/app";if(loaderText)loaderText.textContent="Session trouvée. Ouverture du dashboard…"}else if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}catch(_){if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}
   setTimeout(()=>location.assign(target),180);
 }
 qsa("[data-dashboard-entry]").forEach(a=>a.addEventListener("click",openDashboard));
 addEventListener("pageshow",()=>{opening=false;overlay?.classList.remove("show");overlay?.setAttribute("aria-hidden","true")});

 const params=new URLSearchParams(location.search);
 if(params.get("auth")==="missing"){
   const notice=qs("#sxAuthNotice");if(notice){notice.textContent="Connexion Discord momentanément indisponible. Réessayez dans quelques instants ou consultez le support.";notice.hidden=false}
   history.replaceState(null,"",location.pathname);
 }
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
