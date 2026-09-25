"""Landing page publique SentriX.

Cette page est volontairement indépendante du programme du dashboard : la racine publique
reste légère et consultable sans session, tandis que /app conserve le frontend admin.
Aucune statistique n'est inventée ; les compteurs vivants viennent uniquement de /api/public.
"""
from __future__ import annotations

import html


PAGE_TEMPLATE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#090b10">
<meta name="color-scheme" content="dark">
<title>SentriX — Modération, sécurité et gestion Discord</title>
<meta name="description" content="SentriX réunit modération, sécurité, tickets, logs, niveaux, économie, rôles, notifications, automatisations et intelligence artificielle dans une seule plateforme Discord.">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<link rel="canonical" href="__CANONICAL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SentriX">
<meta property="og:title" content="SentriX — Gérez, protégez et faites évoluer votre serveur Discord">
<meta property="og:description" content="Un bot Discord complet avec dashboard web, AutoMod, sécurité, tickets, logs, niveaux, économie, rôles, notifications, automatisations et IA.">
<meta property="og:url" content="__CANONICAL__">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{
  --bg:#090b10;--bg2:#0d1017;--panel:#11151d;--panel2:#151a24;--panel3:#1b2230;
  --line:#252d3b;--line2:#344055;--text:#f5f7fb;--muted:#98a3b4;--soft:#c8d0dc;
  --accent:#6d78ff;--accent2:#9d8cff;--accent3:#4aa8ff;--green:#55d69a;--amber:#efbd61;
  --shadow:0 24px 80px rgba(0,0,0,.38);--radius:20px;--nav:72px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--bg)}
body{margin:0;min-height:100vh;overflow-x:hidden;background:
 radial-gradient(circle at 18% -12%,rgba(109,120,255,.20),transparent 34%),
 radial-gradient(circle at 88% 16%,rgba(74,168,255,.10),transparent 28%),
 linear-gradient(180deg,var(--bg),var(--bg2) 62%,var(--bg));
 color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;
 -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
button{font:inherit}
img{max-width:100%;display:block}
::selection{background:rgba(109,120,255,.36)}
:focus-visible{outline:2px solid var(--accent2);outline-offset:3px}
.skip{position:fixed;left:16px;top:-80px;z-index:1000;padding:10px 14px;border-radius:10px;background:var(--text);color:#080a0f;font-weight:800}
.skip:focus{top:12px}
.ambient{position:fixed;inset:0;pointer-events:none;z-index:-1;overflow:hidden}
.ambient:before,.ambient:after{content:"";position:absolute;border-radius:50%;filter:blur(30px);opacity:.34}
.ambient:before{width:440px;height:440px;left:-180px;top:18%;background:rgba(109,120,255,.16);animation:orbA 14s ease-in-out infinite alternate}
.ambient:after{width:520px;height:520px;right:-240px;top:48%;background:rgba(74,168,255,.10);animation:orbB 17s ease-in-out infinite alternate}
.wrap{width:min(1180px,calc(100% - 40px));margin:0 auto}
.topbar{position:sticky;top:0;z-index:80;height:var(--nav);border-bottom:1px solid rgba(255,255,255,.06);background:rgba(9,11,16,.76);backdrop-filter:blur(18px);transition:background .2s ease,box-shadow .2s ease}
.topbar.scrolled{background:rgba(9,11,16,.92);box-shadow:0 12px 42px rgba(0,0,0,.24)}
.navbar{height:100%;display:flex;align-items:center;justify-content:space-between;gap:24px}
.brand{display:flex;align-items:center;gap:11px;font-size:18px;font-weight:900;letter-spacing:-.02em;white-space:nowrap}
.brand img{width:38px;height:38px;border-radius:12px;border:1px solid var(--line);box-shadow:0 8px 30px rgba(0,0,0,.34)}
.navlinks{display:flex;align-items:center;gap:4px}
.navlinks>a{padding:9px 11px;border-radius:9px;color:var(--muted);font-size:13px;font-weight:720;transition:color .16s ease,background .16s ease}
.navlinks>a:hover{color:var(--text);background:rgba(255,255,255,.045)}
.nav-actions{display:flex;align-items:center;gap:8px}
.menu-btn{display:none;width:42px;height:42px;border:1px solid var(--line);border-radius:11px;background:var(--panel);color:var(--text);cursor:pointer}
.menu-btn span{display:block;width:18px;height:2px;background:currentColor;margin:4px auto;border-radius:999px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:10px 15px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--text);font-weight:800;font-size:13px;cursor:pointer;transition:transform .18s ease,border-color .18s ease,background .18s ease,box-shadow .18s ease}
.btn:hover{transform:translateY(-2px);border-color:var(--line2);background:var(--panel3)}
.btn.primary{border-color:transparent;background:linear-gradient(135deg,var(--accent),#6757e7);box-shadow:0 12px 32px rgba(109,120,255,.22)}
.btn.primary:hover{box-shadow:0 16px 42px rgba(109,120,255,.30)}
.btn.ghost{background:transparent}
.hero{position:relative;display:grid;grid-template-columns:minmax(0,1.02fr) minmax(420px,.98fr);gap:56px;align-items:center;padding:92px 0 70px;min-height:calc(100vh - var(--nav))}
.hero-copy{max-width:700px}
.kicker{display:inline-flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid rgba(109,120,255,.27);border-radius:999px;background:rgba(109,120,255,.08);color:#b8b2ff;font-size:11px;font-weight:900;letter-spacing:.09em;text-transform:uppercase}
.kicker i{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 14px rgba(85,214,154,.8)}
.hero h1{margin:20px 0 20px;font-size:clamp(46px,6.2vw,78px);line-height:.99;letter-spacing:-.058em;text-wrap:balance}
.hero h1 span{background:linear-gradient(110deg,#fff 0 22%,#b8b2ff 52%,#70bfff 96%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero .lead{max-width:660px;margin:0;color:var(--muted);font-size:18px;line-height:1.72}
.hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:30px}
.hero-note{display:flex;flex-wrap:wrap;gap:9px 18px;margin-top:22px;color:var(--muted);font-size:12px}
.hero-note span{display:inline-flex;align-items:center;gap:7px}
.hero-note i{width:6px;height:6px;border-radius:50%;background:var(--accent)}
.product-preview{position:relative;min-height:510px;perspective:1200px}
.product-preview:before{content:"";position:absolute;inset:12% 2% 8% 12%;border-radius:38px;background:radial-gradient(circle at center,rgba(109,120,255,.20),transparent 67%);filter:blur(28px)}
.app-window{position:absolute;inset:28px 0 26px 22px;display:grid;grid-template-columns:88px 1fr;overflow:hidden;border:1px solid rgba(255,255,255,.11);border-radius:24px;background:linear-gradient(155deg,rgba(22,27,38,.96),rgba(11,14,20,.98));box-shadow:var(--shadow);transform:rotateY(-4deg) rotateX(2deg);animation:floatWindow 7s ease-in-out infinite}
.preview-side{padding:18px 13px;border-right:1px solid var(--line);background:rgba(11,14,20,.76)}
.preview-logo{width:42px;height:42px;margin:0 auto 22px;border-radius:13px;background:linear-gradient(135deg,var(--accent),var(--accent2));display:grid;place-items:center;font-weight:950;color:white}
.preview-nav{display:grid;gap:9px}
.preview-nav i{height:31px;border-radius:8px;background:#171c27}
.preview-nav i.active{background:rgba(109,120,255,.20);box-shadow:inset 3px 0 0 var(--accent)}
.preview-main{padding:22px;min-width:0}
.preview-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:24px}
.preview-title b{display:block;font-size:17px}.preview-title span{color:var(--muted);font-size:11px}
.preview-status{display:inline-flex;align-items:center;gap:7px;padding:6px 9px;border:1px solid rgba(85,214,154,.22);border-radius:999px;background:rgba(85,214,154,.07);color:#8ae7bd;font-size:10px;font-weight:850}
.preview-status i{width:6px;height:6px;border-radius:50%;background:var(--green)}
.preview-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.preview-card{min-height:108px;padding:15px;border:1px solid var(--line);border-radius:14px;background:rgba(18,22,31,.92)}
.preview-card.wide{grid-column:1/-1;min-height:150px}
.preview-label{color:var(--muted);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}
.preview-card h3{margin:8px 0 6px;font-size:15px}.preview-card p{margin:0;color:var(--muted);font-size:11px}
.toggle-row{display:grid;gap:9px;margin-top:14px}
.toggle{display:flex;justify-content:space-between;align-items:center;padding:8px 9px;border-radius:9px;background:#0d1118;color:var(--soft);font-size:10px}
.toggle i{width:28px;height:16px;border-radius:99px;background:rgba(109,120,255,.25);position:relative}
.toggle i:after{content:"";position:absolute;width:10px;height:10px;right:3px;top:3px;border-radius:50%;background:var(--accent2)}
.preview-float{position:absolute;right:-18px;bottom:12px;width:190px;padding:14px;border:1px solid rgba(157,140,255,.24);border-radius:15px;background:rgba(18,22,31,.94);box-shadow:0 18px 50px rgba(0,0,0,.38);animation:floatCard 5.5s ease-in-out infinite}
.preview-float b{display:block;font-size:12px}.preview-float span{display:block;margin-top:4px;color:var(--muted);font-size:10px}
.public-strip{display:grid;grid-template-columns:1.2fr repeat(4,1fr);gap:10px;padding:13px;border:1px solid var(--line);border-radius:18px;background:rgba(17,21,29,.72);box-shadow:0 10px 34px rgba(0,0,0,.17)}
.live-state{display:flex;align-items:center;gap:10px;padding:11px 13px}
.live-dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 16px rgba(85,214,154,.65)}
.live-state b,.live-state span{display:block}.live-state span{font-size:11px;color:var(--muted);margin-top:2px}
.public-stat{padding:11px 13px;border-left:1px solid var(--line)}
.public-stat small{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;font-weight:800}
.public-stat strong{display:block;margin-top:3px;font-size:19px;letter-spacing:-.03em}
.section{padding:105px 0}
.section-head{display:flex;justify-content:space-between;gap:32px;align-items:end;margin-bottom:38px}
.section-head>div{max-width:700px}.section-kicker{color:var(--accent2);font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.11em}
.section h2{margin:9px 0 0;font-size:clamp(30px,4vw,48px);letter-spacing:-.045em;line-height:1.08;text-wrap:balance}
.section-head p{max-width:440px;margin:0;color:var(--muted);line-height:1.7}
.feature-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.feature{position:relative;min-height:190px;padding:21px;border:1px solid var(--line);border-radius:17px;background:linear-gradient(160deg,rgba(21,26,36,.88),rgba(13,16,23,.90));overflow:hidden;transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease}
.feature:before{content:"";position:absolute;right:-42px;top:-42px;width:120px;height:120px;border-radius:50%;background:radial-gradient(circle,rgba(109,120,255,.12),transparent 68%)}
.feature:hover{transform:translateY(-4px);border-color:#3b465b;box-shadow:0 16px 44px rgba(0,0,0,.22)}
.feature-icon{width:40px;height:40px;border-radius:12px;border:1px solid var(--line2);background:var(--panel3);display:grid;place-items:center;color:#c8c3ff;font-size:11px;font-weight:950;letter-spacing:.04em}
.feature h3{margin:17px 0 7px;font-size:16px}.feature p{margin:0;color:var(--muted);font-size:13px;line-height:1.62}
.security-panel{display:grid;grid-template-columns:1fr 1fr;gap:34px;padding:34px;border:1px solid rgba(109,120,255,.20);border-radius:24px;background:
 radial-gradient(circle at 100% 0%,rgba(109,120,255,.10),transparent 34%),
 linear-gradient(150deg,rgba(18,22,31,.95),rgba(11,14,20,.96));box-shadow:var(--shadow)}
.security-copy h2{margin:10px 0 14px}.security-copy p{color:var(--muted);font-size:15px;line-height:1.72}
.security-list{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:25px}
.security-list div{padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#0d1118;color:var(--soft);font-size:12px;font-weight:700}
.security-visual{display:grid;align-content:center;gap:10px}
.security-event{display:grid;grid-template-columns:44px 1fr auto;align-items:center;gap:11px;padding:13px;border:1px solid var(--line);border-radius:13px;background:#0d1118}
.security-mark{width:38px;height:38px;border-radius:11px;background:rgba(109,120,255,.13);display:grid;place-items:center;color:#c5c0ff;font-size:10px;font-weight:950}
.security-event b{display:block;font-size:12px}.security-event span{display:block;color:var(--muted);font-size:10px;margin-top:2px}
.security-badge{padding:5px 8px;border-radius:99px;background:rgba(85,214,154,.08);color:#83ddb4;font-size:9px;font-weight:900}
.dashboard-showcase{display:grid;grid-template-columns:.82fr 1.18fr;gap:36px;align-items:center}
.dashboard-copy p{color:var(--muted);line-height:1.72}.dashboard-points{display:grid;gap:10px;margin:24px 0}
.dashboard-points div{display:flex;gap:10px;align-items:flex-start;color:var(--soft);font-size:13px}
.dashboard-points i{flex:none;width:20px;height:20px;border-radius:7px;background:rgba(109,120,255,.15);display:grid;place-items:center;color:#c6c0ff;font-style:normal;font-size:9px;font-weight:900}
.dashboard-frame{padding:12px;border:1px solid var(--line);border-radius:22px;background:#0c0f15;box-shadow:var(--shadow)}
.dashboard-browser{height:36px;display:flex;align-items:center;gap:6px;padding:0 10px;border-bottom:1px solid var(--line)}
.dashboard-browser i{width:7px;height:7px;border-radius:50%;background:#303849}.dashboard-browser i:nth-child(1){background:#ff7081}.dashboard-browser i:nth-child(2){background:#efbd61}.dashboard-browser i:nth-child(3){background:#55d69a}
.dashboard-body{display:grid;grid-template-columns:150px 1fr;min-height:330px}
.dashboard-sidebar{padding:17px 12px;border-right:1px solid var(--line)}
.dashboard-sidebar b{display:block;margin:4px 8px 14px;font-size:12px}.dashboard-sidebar span{display:block;margin:4px 0;padding:8px;border-radius:8px;color:var(--muted);font-size:9px}.dashboard-sidebar span.active{background:rgba(109,120,255,.13);color:#d3d0ff}
.dashboard-content{padding:18px}.dashboard-content h3{margin:0 0 4px;font-size:15px}.dashboard-content>p{margin:0 0 18px;color:var(--muted);font-size:10px}
.setting{display:flex;justify-content:space-between;align-items:center;gap:15px;padding:12px;margin-bottom:8px;border:1px solid var(--line);border-radius:10px;background:#10141c}
.setting b{display:block;font-size:10px}.setting span{display:block;margin-top:2px;color:var(--muted);font-size:8px}
.setting .switch{width:31px;height:18px;border-radius:99px;background:rgba(109,120,255,.28);position:relative;flex:none}.setting .switch:after{content:"";position:absolute;width:12px;height:12px;right:3px;top:3px;border-radius:50%;background:var(--accent2)}
.ai-panel{display:grid;grid-template-columns:1fr 1fr;gap:30px;padding:32px;border:1px solid var(--line);border-radius:23px;background:linear-gradient(145deg,#111620,#0c1017)}
.ai-chat{padding:18px;border:1px solid var(--line);border-radius:16px;background:#0b0f15}
.bubble{max-width:88%;padding:11px 13px;border-radius:12px;margin-bottom:9px;font-size:11px}
.bubble.user{margin-left:auto;background:rgba(109,120,255,.17);color:#e5e2ff}.bubble.bot{background:#151b25;color:var(--soft);border:1px solid var(--line)}
.ai-copy p{color:var(--muted);line-height:1.7}.ai-copy ul{list-style:none;padding:0;margin:21px 0 0;display:grid;gap:9px}.ai-copy li{padding:10px 11px;border:1px solid var(--line);border-radius:10px;color:var(--soft);font-size:12px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;counter-reset:step}
.step{padding:24px;border:1px solid var(--line);border-radius:17px;background:var(--panel);counter-increment:step}
.step:before{content:"0" counter(step);display:block;color:var(--accent2);font-size:12px;font-weight:950;letter-spacing:.1em}.step h3{margin:14px 0 7px}.step p{margin:0;color:var(--muted);font-size:13px}
.faq{display:grid;grid-template-columns:.8fr 1.2fr;gap:34px}.faq-copy p{color:var(--muted);line-height:1.7}.faq-list{display:grid;gap:8px}
details{border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}summary{padding:15px 17px;cursor:pointer;font-weight:800;list-style:none}summary::-webkit-details-marker{display:none}details p{padding:0 17px 16px;margin:0;color:var(--muted);font-size:13px;line-height:1.65}
.final-cta{position:relative;overflow:hidden;text-align:center;padding:58px 24px;border:1px solid rgba(109,120,255,.24);border-radius:26px;background:linear-gradient(145deg,rgba(109,120,255,.13),rgba(17,21,29,.92));box-shadow:var(--shadow)}
.final-cta:before{content:"";position:absolute;inset:-60% 25% auto;width:50%;height:160%;background:radial-gradient(circle,rgba(157,140,255,.20),transparent 65%);pointer-events:none}
.final-cta h2{position:relative;margin:0 auto 12px;max-width:700px}.final-cta p{position:relative;margin:0 auto;color:var(--muted);max-width:620px}.final-cta .hero-actions{position:relative;justify-content:center}
footer{padding:42px 0 34px;border-top:1px solid rgba(255,255,255,.06);margin-top:105px}
.footer-grid{display:grid;grid-template-columns:1.3fr repeat(3,1fr);gap:28px}.footer-brand p{max-width:330px;color:var(--muted);font-size:12px}.footer-col b{display:block;margin-bottom:10px;font-size:11px;text-transform:uppercase;letter-spacing:.08em}.footer-col a{display:block;width:max-content;max-width:100%;margin:7px 0;color:var(--muted);font-size:12px}.footer-col a:hover{color:var(--text)}
.footer-bottom{display:flex;justify-content:space-between;gap:18px;margin-top:32px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}
.auth-notice{width:min(760px,calc(100% - 40px));margin:16px auto -24px;padding:12px 15px;border:1px solid rgba(239,189,97,.30);border-radius:11px;background:rgba(239,189,97,.08);color:#f7d99f;font-size:12px}
.reveal{opacity:0;transform:translateY(18px);transition:opacity .55s cubic-bezier(.2,.8,.2,1),transform .55s cubic-bezier(.2,.8,.2,1)}
.reveal.visible{opacity:1;transform:none}
.sx-loader{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:rgba(6,8,12,.78);backdrop-filter:blur(14px);opacity:0;visibility:hidden;transition:opacity .18s ease,visibility .18s ease}
.sx-loader.show{opacity:1;visibility:visible}.sx-loader-card{width:min(360px,calc(100vw - 36px));padding:28px;text-align:center;border:1px solid var(--line2);border-radius:18px;background:linear-gradient(180deg,#171c27,#0d1118);box-shadow:var(--shadow)}
.sx-spinner{width:38px;height:38px;margin:0 auto 15px;border-radius:50%;border:3px solid rgba(255,255,255,.09);border-top-color:var(--accent2);animation:spin .72s linear infinite}.sx-loader-card b{display:block}.sx-loader-card span{display:block;margin-top:6px;color:var(--muted);font-size:11px}
@keyframes floatWindow{0%,100%{transform:rotateY(-4deg) rotateX(2deg) translateY(0)}50%{transform:rotateY(-3deg) rotateX(1.4deg) translateY(-8px)}}
@keyframes floatCard{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
@keyframes orbA{to{transform:translate3d(90px,-60px,0) scale(1.14)}}@keyframes orbB{to{transform:translate3d(-90px,70px,0) scale(.88)}}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1050px){
 .navlinks{display:none}.menu-btn{display:block}.navbar.open .navlinks{display:flex;position:absolute;top:calc(var(--nav) - 2px);left:20px;right:20px;flex-direction:column;align-items:stretch;padding:10px;border:1px solid var(--line);border-radius:14px;background:rgba(15,18,26,.98);box-shadow:var(--shadow)}
 .navbar.open .navlinks>a{padding:11px}.hero{grid-template-columns:1fr;padding-top:70px}.hero-copy{max-width:780px}.product-preview{width:min(720px,100%);min-height:480px;margin:0 auto}.public-strip{grid-template-columns:1fr 1fr 1fr}.live-state{grid-column:1/-1}.public-stat:nth-last-child(1){display:none}
 .feature-grid{grid-template-columns:repeat(2,1fr)}.dashboard-showcase{grid-template-columns:1fr}.security-panel,.ai-panel{grid-template-columns:1fr}.faq{grid-template-columns:1fr}.footer-grid{grid-template-columns:1.2fr 1fr 1fr}.footer-col:last-child{display:none}
}
@media(max-width:680px){
 :root{--nav:64px}.wrap{width:min(calc(100% - 28px),1180px)}.topbar{height:64px}.brand span{font-size:16px}.nav-actions .btn.ghost{display:none}.nav-actions .btn.primary{padding:9px 11px}.hero{padding:56px 0 48px;min-height:auto;gap:30px}.hero h1{font-size:clamp(40px,13vw,58px)}.hero .lead{font-size:16px}.product-preview{min-height:350px}.app-window{inset:8px 0 8px 0;grid-template-columns:62px 1fr;border-radius:18px;transform:none;animation:none}.preview-side{padding:12px 8px}.preview-logo{width:34px;height:34px}.preview-main{padding:14px}.preview-grid{gap:8px}.preview-card{min-height:88px;padding:11px}.preview-card.wide{min-height:118px}.preview-float{display:none}
 .public-strip{grid-template-columns:1fr 1fr}.live-state{grid-column:1/-1}.public-stat{border-left:0;border-top:1px solid var(--line)}.public-stat:nth-last-child(1){display:block}
 .section{padding:76px 0}.section-head{display:block}.section-head p{margin-top:14px}.feature-grid{grid-template-columns:1fr}.security-panel{padding:23px}.security-list{grid-template-columns:1fr}.dashboard-body{grid-template-columns:94px 1fr}.dashboard-sidebar{padding:10px 7px}.dashboard-content{padding:12px}.ai-panel{padding:22px}.steps{grid-template-columns:1fr}.final-cta{padding:42px 18px}.footer-grid{grid-template-columns:1fr 1fr}.footer-brand{grid-column:1/-1}.footer-bottom{display:block}.footer-bottom span{display:block;margin-top:5px}
}
@media(prefers-reduced-motion:reduce){
 html{scroll-behavior:auto}.ambient:before,.ambient:after,.app-window,.preview-float,.sx-spinner{animation:none!important}
 .reveal{opacity:1!important;transform:none!important;transition:none!important}.btn,.feature,.topbar{transition:none!important}
}
</style>
</head>
<body>
<a class="skip" href="#main">Aller au contenu</a>
<div class="ambient" aria-hidden="true"></div>
<header class="topbar" id="topbar">
 <div class="wrap navbar" id="navbar">
  <a class="brand" href="/" aria-label="SentriX, accueil"><img src="/sentrix-avatar.png?v=55" alt="" width="38" height="38"><span>SentriX</span></a>
  <nav class="navlinks" id="navlinks" aria-label="Navigation principale">
   <a href="#features">Fonctionnalités</a><a href="#security">Sécurité</a><a href="#dashboard">Dashboard</a><a href="#ai">IA</a><a href="#faq">FAQ</a><a href="/support">Support</a>
  </nav>
  <div class="nav-actions">
   <a class="btn ghost" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a>
   <a class="btn primary" href="/app" data-dashboard-entry>Dashboard</a>
   <button class="menu-btn" id="menuBtn" type="button" aria-expanded="false" aria-controls="navlinks" aria-label="Ouvrir le menu"><span></span><span></span><span></span></button>
  </div>
 </div>
</header>
<p id="sxAuthNotice" class="auth-notice" hidden></p>
<main id="main">
 <section class="wrap hero">
  <div class="hero-copy reveal">
   <div class="kicker"><i></i>Plateforme Discord tout-en-un</div>
   <h1>Gérez votre serveur. <span>SentriX s’occupe du reste.</span></h1>
   <p class="lead">Modération, AutoMod, sécurité, tickets, logs, niveaux, économie, rôles, notifications, automatisations et intelligence artificielle réunis dans une seule expérience.</p>
   <div class="hero-actions">
    <a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a>
    <a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX à Discord</a>
    <a class="btn ghost" href="#features">Découvrir SentriX</a>
   </div>
   <div class="hero-note"><span><i></i>Configuration par serveur</span><span><i></i>Dashboard web</span><span><i></i>Commandes Discord</span></div>
  </div>
  <div class="product-preview reveal" aria-label="Aperçu visuel du dashboard SentriX">
   <div class="app-window">
    <aside class="preview-side"><div class="preview-logo">S</div><div class="preview-nav"><i class="active"></i><i></i><i></i><i></i><i></i><i></i></div></aside>
    <div class="preview-main">
     <div class="preview-top"><div class="preview-title"><b>Centre de contrôle</b><span>Configuration du serveur</span></div><div class="preview-status"><i></i>Aperçu</div></div>
     <div class="preview-grid">
      <div class="preview-card"><span class="preview-label">Sécurité</span><h3>Protections</h3><p>AutoMod et règles du serveur.</p></div>
      <div class="preview-card"><span class="preview-label">Communauté</span><h3>Tickets</h3><p>Assistance et organisation du staff.</p></div>
      <div class="preview-card wide"><span class="preview-label">Réglages</span><h3>Modules SentriX</h3><div class="toggle-row"><div class="toggle"><span>Anti-spam</span><i></i></div><div class="toggle"><span>Logs de modération</span><i></i></div><div class="toggle"><span>Niveaux</span><i></i></div></div></div>
     </div>
    </div>
   </div>
   <div class="preview-float"><b>Une seule plateforme</b><span>Les réglages restent regroupés au même endroit.</span></div>
  </div>
 </section>

 <section class="wrap public-strip reveal" aria-label="État public de SentriX">
  <div class="live-state"><i class="live-dot" id="publicDot"></i><div><b id="publicStatus">Service web disponible</b><span id="publicStatusDetail">Chargement de l’état Discord…</span></div></div>
  <div class="public-stat"><small>Serveurs</small><strong id="publicGuilds">—</strong></div>
  <div class="public-stat"><small>Membres accessibles</small><strong id="publicMembers">—</strong></div>
  <div class="public-stat"><small>Latence Discord</small><strong id="publicLatency">—</strong></div>
  <div class="public-stat"><small>Uptime</small><strong id="publicUptime">—</strong></div>
 </section>

 <section class="wrap section" id="features">
  <div class="section-head reveal"><div><span class="section-kicker">Fonctionnalités</span><h2>Tout votre serveur, dans un seul espace.</h2></div><p>SentriX regroupe les outils essentiels d’administration et de communauté pour éviter de multiplier les bots et les interfaces.</p></div>
  <div class="feature-grid">
   <article class="feature reveal"><div class="feature-icon">AM</div><h3>AutoMod</h3><p>Filtrage du spam, liens, mentions abusives et autres comportements perturbateurs selon la configuration du serveur.</p></article>
   <article class="feature reveal"><div class="feature-icon">SE</div><h3>Sécurité</h3><p>Protections contre les actions dangereuses, raids et modifications sensibles, avec outils de suivi pour le staff.</p></article>
   <article class="feature reveal"><div class="feature-icon">TK</div><h3>Tickets</h3><p>Centralisez l’assistance avec des tickets organisés, des formulaires et des outils de gestion pour l’équipe.</p></article>
   <article class="feature reveal"><div class="feature-icon">LG</div><h3>Logs</h3><p>Gardez une trace claire des événements importants : modération, membres, messages, rôles, salons et sécurité.</p></article>
   <article class="feature reveal"><div class="feature-icon">LV</div><h3>Niveaux</h3><p>Récompensez l’activité avec XP, progression et récompenses configurables adaptées à votre communauté.</p></article>
   <article class="feature reveal"><div class="feature-icon">EC</div><h3>Économie</h3><p>Portefeuille, récompenses, objets, boutique et activités communautaires reliés à une économie persistante.</p></article>
   <article class="feature reveal"><div class="feature-icon">RL</div><h3>Rôles</h3><p>Gérez les rôles, autoroles et systèmes interactifs depuis Discord ou le dashboard.</p></article>
   <article class="feature reveal"><div class="feature-icon">WD</div><h3>Bienvenue & départs</h3><p>Créez des messages d’arrivée et de départ personnalisés avec aperçu avant publication.</p></article>
   <article class="feature reveal"><div class="feature-icon">NT</div><h3>Notifications</h3><p>Regroupez les alertes et publications utiles dans les salons appropriés sans multiplier les intégrations.</p></article>
   <article class="feature reveal"><div class="feature-icon">AI</div><h3>Intelligence artificielle</h3><p>Une couche conversationnelle pour guider, expliquer certaines fonctions et simplifier l’utilisation de SentriX.</p></article>
   <article class="feature reveal"><div class="feature-icon">IV</div><h3>Invitations</h3><p>Suivez les invitations du serveur, leurs statistiques et les récompenses configurées.</p></article>
   <article class="feature reveal"><div class="feature-icon">GM</div><h3>Jeux & communauté</h3><p>Ajoutez des activités directement dans Discord avec progression et intégration à l’économie lorsque le jeu le prévoit.</p></article>
  </div>
 </section>

 <section class="wrap section" id="security">
  <div class="security-panel reveal">
   <div class="security-copy"><span class="section-kicker">Protection</span><h2>Une sécurité configurable, pas une promesse magique.</h2><p>SentriX aide le staff à réduire les abus et à réagir plus vite grâce à plusieurs couches : AutoMod, anti-raid, protections sensibles, vérification et journalisation.</p>
    <div class="security-list"><div>Anti-spam & mentions</div><div>Anti-raid</div><div>Protection rôles & salons</div><div>Vérification</div><div>Logs de sécurité</div><div>Contrôle des permissions</div></div>
   </div>
   <div class="security-visual" aria-label="Exemples de protections SentriX">
    <div class="security-event"><div class="security-mark">01</div><div><b>Comportement détecté</b><span>Une règle AutoMod correspond au message.</span></div><small class="security-badge">Analysé</small></div>
    <div class="security-event"><div class="security-mark">02</div><div><b>Action sensible suivie</b><span>Les changements critiques peuvent être journalisés.</span></div><small class="security-badge">Suivi</small></div>
    <div class="security-event"><div class="security-mark">03</div><div><b>Staff informé</b><span>Les informations utiles restent regroupées dans les logs.</span></div><small class="security-badge">Visible</small></div>
   </div>
  </div>
 </section>

 <section class="wrap section" id="dashboard">
  <div class="dashboard-showcase">
   <div class="dashboard-copy reveal"><span class="section-kicker">Dashboard</span><h2>Configurez SentriX sans mémoriser chaque commande.</h2><p>Le dashboard rassemble les modules du serveur dans une interface commune. Les permissions Discord sont revérifiées avant les actions d’administration.</p>
    <div class="dashboard-points"><div><i>1</i><span>Sélectionnez un serveur auquel vous avez réellement accès.</span></div><div><i>2</i><span>Réglez les modules avec des champs, aperçus et contrôles adaptés.</span></div><div><i>3</i><span>Enregistrez la configuration et continuez à utiliser Discord normalement.</span></div></div>
    <a class="btn primary" href="/app" data-dashboard-entry>Accéder au dashboard</a>
   </div>
   <div class="dashboard-frame reveal" aria-label="Exemple de configuration dans le dashboard">
    <div class="dashboard-browser"><i></i><i></i><i></i></div>
    <div class="dashboard-body"><aside class="dashboard-sidebar"><b>SentriX</b><span>Vue d’ensemble</span><span>Accueil</span><span>Rôles</span><span class="active">Sécurité</span><span>Logs</span><span>Tickets</span><span>Économie</span></aside><div class="dashboard-content"><h3>Protections</h3><p>Activez uniquement les règles dont votre serveur a besoin.</p><div class="setting"><div><b>Anti-spam</b><span>Limite les rafales répétitives.</span></div><i class="switch"></i></div><div class="setting"><div><b>Anti-liens</b><span>Contrôle les liens selon vos règles.</span></div><i class="switch"></i></div><div class="setting"><div><b>Escalade AutoMod</b><span>Adapte les sanctions à la récidive.</span></div><i class="switch"></i></div></div></div>
   </div>
  </div>
 </section>

 <section class="wrap section" id="ai">
  <div class="ai-panel reveal">
   <div class="ai-chat" aria-label="Illustration d’une conversation avec SentriX"><div class="bubble user">Où est-ce que je configure les logs de modération ?</div><div class="bubble bot">Ouvrez le dashboard, choisissez votre serveur puis la section Logs. SentriX y regroupe les catégories et salons configurés.</div><div class="bubble user">Et si je préfère une commande Discord ?</div><div class="bubble bot">Je peux vous orienter vers les commandes réellement disponibles sans inventer de raccourci.</div></div>
   <div class="ai-copy"><span class="section-kicker">Intelligence artificielle</span><h2>Une aide plus naturelle, reliée au produit réel.</h2><p>L’IA SentriX peut servir de guide pour comprendre certaines fonctions et retrouver le bon réglage, tout en respectant les permissions et les commandes réellement chargées.</p><ul><li>Compréhension de demandes formulées naturellement</li><li>Guidage vers les bons modules du dashboard</li><li>Aide au staff sans remplacer les décisions humaines</li></ul></div>
  </div>
 </section>

 <section class="wrap section">
  <div class="section-head reveal"><div><span class="section-kicker">Démarrage</span><h2>Trois étapes pour commencer.</h2></div><p>La page publique reste accessible sans compte. La connexion Discord n’est demandée que pour administrer vos serveurs.</p></div>
  <div class="steps"><article class="step reveal"><h3>Ajoutez SentriX</h3><p>Choisissez le serveur Discord sur lequel vous souhaitez installer le bot.</p></article><article class="step reveal"><h3>Connectez-vous</h3><p>Utilisez Discord OAuth pour ouvrir le dashboard et retrouver vos serveurs administrables.</p></article><article class="step reveal"><h3>Configurez</h3><p>Activez uniquement les modules et réglages adaptés à votre communauté.</p></article></div>
 </section>

 <section class="wrap section" id="faq">
  <div class="faq">
   <div class="faq-copy reveal"><span class="section-kicker">FAQ</span><h2>Les réponses essentielles.</h2><p>Les informations ci-dessous correspondent au fonctionnement actuel du site et du dashboard SentriX.</p><a class="btn ghost" href="/support">Centre de support</a></div>
   <div class="faq-list reveal">
    <details><summary>Dois-je me connecter pour consulter le site ?</summary><p>Non. La page d’accueil et les ressources publiques sont accessibles sans session. La connexion Discord est nécessaire lorsque vous ouvrez le dashboard d’administration.</p></details>
    <details><summary>Comment accéder au dashboard ?</summary><p>Utilisez le bouton Dashboard. Si une session Discord valide existe déjà, SentriX ouvre directement l’application ; sinon, le flux de connexion Discord sécurisé est proposé.</p></details>
    <details><summary>SentriX possède-t-il un système de tickets ?</summary><p>Oui. SentriX comprend un module de tickets et des outils associés dans le dashboard.</p></details>
    <details><summary>Que couvre la sécurité ?</summary><p>Le projet comprend notamment AutoMod, protections anti-raid/anti-nuke, vérification, logs de sécurité et contrôles liés aux permissions. Leur efficacité dépend toujours de la configuration et des permissions accordées au bot.</p></details>
    <details><summary>Puis-je gérer plusieurs serveurs ?</summary><p>Le dashboard affiche les serveurs auxquels votre compte Discord possède un niveau d’accès administratif accepté par SentriX. Les configurations restent séparées par serveur.</p></details>
    <details><summary>Où trouver les conditions et la confidentialité ?</summary><p>Les pages publiques Conditions et Confidentialité sont disponibles dans le pied de page.</p></details>
   </div>
  </div>
 </section>

 <section class="wrap final-cta reveal">
  <span class="section-kicker">SentriX</span><h2>Prêt à reprendre le contrôle de votre serveur ?</h2><p>Ajoutez SentriX à Discord ou ouvrez le dashboard pour configurer les modules dont votre communauté a réellement besoin.</p><div class="hero-actions"><a class="btn primary" href="/app" data-dashboard-entry>Ouvrir le dashboard</a><a class="btn" href="__INVITE__" target="_blank" rel="noopener">Ajouter SentriX</a></div>
 </section>
</main>

<footer>
 <div class="wrap">
  <div class="footer-grid"><div class="footer-brand"><a class="brand" href="/"><img src="/sentrix-avatar.png?v=55" alt="" width="38" height="38"><span>SentriX</span></a><p>Bot Discord et plateforme web pour centraliser modération, sécurité, communauté et automatisations.</p></div><div class="footer-col"><b>Produit</b><a href="#features">Fonctionnalités</a><a href="#security">Sécurité</a><a href="/dashboard-sentrix">Dashboard</a><a href="/stats">Statistiques</a></div><div class="footer-col"><b>Ressources</b><a href="/start">Commencer</a><a href="/support">Support</a><a href="/media-kit">Media kit</a><a href="/commands">Commandes</a></div><div class="footer-col"><b>Légal</b><a href="/privacy">Confidentialité</a><a href="/terms">Conditions</a></div></div>
  <div class="footer-bottom"><span>SentriX — plateforme Discord tout-en-un.</span><span>Les données affichées publiquement ne sont jamais inventées.</span></div>
 </div>
</footer>

<div class="sx-loader" id="sxDashboardLoader" aria-hidden="true"><div class="sx-loader-card"><div class="sx-spinner"></div><b>Ouverture du dashboard</b><span id="sxDashboardLoaderText">Vérification de votre session Discord…</span></div></div>
<script>
(()=>{
 "use strict";
 const qs=(s,r=document)=>r.querySelector(s),qsa=(s,r=document)=>Array.from(r.querySelectorAll(s));
 const nav=qs("#navbar"),menu=qs("#menuBtn"),topbar=qs("#topbar");
 function closeMenu(){nav?.classList.remove("open");menu?.setAttribute("aria-expanded","false")}
 menu?.addEventListener("click",()=>{const open=nav?.classList.toggle("open");menu.setAttribute("aria-expanded",open?"true":"false")});
 qsa("#navlinks a").forEach(a=>a.addEventListener("click",closeMenu));
 document.addEventListener("click",e=>{if(nav?.classList.contains("open")&&!nav.contains(e.target))closeMenu()});
 window.addEventListener("scroll",()=>topbar?.classList.toggle("scrolled",window.scrollY>12),{passive:true});

 const reduced=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
 const reveals=qsa(".reveal");
 if(!reduced&&"IntersectionObserver" in window){
   const io=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add("visible");io.unobserve(entry.target)}}),{threshold:.12,rootMargin:"0px 0px -40px"});
   reveals.forEach(el=>io.observe(el));
 }else reveals.forEach(el=>el.classList.add("visible"));

 const fmt=n=>new Intl.NumberFormat("fr-FR").format(Number(n)||0);
 function age(sec){sec=Math.max(0,Number(sec)||0);const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);return d?d+" j "+h+" h":h?h+" h "+m+" min":m+" min"}
 function setNum(id,value){const el=document.getElementById(id);if(!el)return;if(reduced||!Number.isFinite(Number(value))){el.textContent=fmt(value);return}const target=Math.max(0,Number(value)||0),started=performance.now(),duration=600;function frame(now){const p=Math.min(1,(now-started)/duration),e=1-Math.pow(1-p,3);el.textContent=fmt(Math.round(target*e));if(p<1)requestAnimationFrame(frame)}requestAnimationFrame(frame)}
 async function loadPublic(){
   try{
     const r=await fetch("/api/public",{cache:"no-store",credentials:"same-origin"});if(!r.ok)throw new Error("public");
     const d=await r.json(),active=Boolean(d.online);
     document.getElementById("publicStatus").textContent=active?"Bot Discord connecté":"Service web disponible";
     document.getElementById("publicStatusDetail").textContent=active?"État public reçu depuis SentriX":"Cette instance web reste disponible pendant la bascule HA";
     document.getElementById("publicDot").style.background=active?"var(--green)":"var(--amber)";document.getElementById("publicDot").style.boxShadow=active?"0 0 16px rgba(85,214,154,.65)":"0 0 16px rgba(239,189,97,.45)";
     if(active||Number(d.guilds)>0){setNum("publicGuilds",d.guilds);setNum("publicMembers",d.members)}
     document.getElementById("publicLatency").textContent=d.latency_ms==null?"—":Math.round(d.latency_ms)+" ms";
     document.getElementById("publicUptime").textContent=age(d.uptime_seconds);
   }catch(_){
     document.getElementById("publicStatus").textContent="Site web disponible";
     document.getElementById("publicStatusDetail").textContent="Les statistiques Discord sont momentanément indisponibles";
     document.getElementById("publicDot").style.background="var(--amber)";
   }
 }
 loadPublic();

 const overlay=document.getElementById("sxDashboardLoader"),loaderText=document.getElementById("sxDashboardLoaderText");let opening=false;
 async function openDashboard(event){
   if(opening)return;event.preventDefault();opening=true;overlay?.classList.add("show");overlay?.setAttribute("aria-hidden","false");
   if(loaderText)loaderText.textContent="Vérification de votre session Discord…";let target="/login";
   try{const response=await fetch("/api/me",{cache:"no-store",credentials:"same-origin"});if(response.ok){target="/app";if(loaderText)loaderText.textContent="Session trouvée. Ouverture du dashboard…"}else if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}catch(_){if(loaderText)loaderText.textContent="Connexion Discord sécurisée…"}
   window.setTimeout(()=>window.location.assign(target),180);
 }
 qsa("[data-dashboard-entry]").forEach(link=>link.addEventListener("click",openDashboard));
 window.addEventListener("pageshow",()=>{opening=false;overlay?.classList.remove("show");overlay?.setAttribute("aria-hidden","true")});

 const params=new URLSearchParams(location.search);
 if(params.get("auth")==="missing"){
   const notice=document.getElementById("sxAuthNotice");
   if(notice){notice.textContent="Connexion Discord momentanément indisponible. Réessayez dans quelques instants ou consultez le support.";notice.hidden=false}
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
