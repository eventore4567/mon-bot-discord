"""Moteur visuel partagé SentriX — fond animé, verre, profondeur.

Une seule source pour l'identité des pages publiques. Avant ce module, chaque
page réinventait son fond : la landing avait un canvas de particules, les
pages secondaires un dégradé CSS, et la page d'erreur rien du tout. Trois
identités pour un même produit.

Le fond est un canvas unique qui dessine quatre couches de profondeur — grille
en perspective, nœuds reliés, halos mouvants, poussière lumineuse. Tout part
d'une seule boucle ``requestAnimationFrame`` : quatre animations séparées
coûteraient quatre fois plus cher pour le même résultat.

Ce que le moteur respecte, parce que ce sont des exigences et pas des options :

  - ``prefers-reduced-motion`` coupe le mouvement, pas l'affichage ;
  - l'onglet masqué arrête la boucle (``visibilitychange``) — un fond animé
    dans un onglet qu'on ne regarde pas est du CPU brûlé pour rien ;
  - un écran tactile ou étroit reçoit moins de nœuds et pas de parallaxe ;
  - la boucle se réarme proprement, et un seul ``rAF`` est en vol à la fois.
"""
from __future__ import annotations

#: Palette unique. Bleu SentriX, bleu clair, blanc, graphite profond — et un
#: indigo discret pour la profondeur. Aucun noir pur : un fond plat est
#: exactement ce que cette refonte doit supprimer.
PALETTE = {
    "fond": "#070b14",
    "fond2": "#0b1220",
    "panneau": "rgba(18,26,42,.72)",
    "ligne": "rgba(118,163,230,.16)",
    "texte": "#eef4ff",
    "doux": "#9aabc4",
    "bleu": "#4da3ff",
    "bleu2": "#8ccbff",
    "indigo": "#6f7dff",
    "ok": "#55d69a",
}

CSS = """
:root{--fond:#070b14;--fond2:#0b1220;--panneau:rgba(18,26,42,.72);--ligne:rgba(118,163,230,.16);
--texte:#eef4ff;--doux:#9aabc4;--bleu:#4da3ff;--bleu2:#8ccbff;--indigo:#6f7dff;--ok:#55d69a}
*{box-sizing:border-box}
html{background:var(--fond);scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;position:relative;overflow-x:hidden;color:var(--texte);
font:16px/1.6 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
background:
 radial-gradient(1200px 620px at 78% -14%,rgba(77,163,255,.20),transparent 62%),
 radial-gradient(900px 520px at 6% 34%,rgba(111,125,255,.13),transparent 58%),
 linear-gradient(180deg,var(--fond),var(--fond2) 58%,var(--fond))}
#sxfx{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none;display:block}
.sx-shell{position:relative;z-index:1}
a{color:inherit}
:focus-visible{outline:2px solid var(--bleu2);outline-offset:3px;border-radius:8px}
.sx-verre{position:relative;border:1px solid var(--ligne);border-radius:18px;
background:linear-gradient(165deg,rgba(28,39,62,.78),rgba(13,20,34,.72));
box-shadow:0 26px 70px rgba(2,6,16,.55),inset 0 1px 0 rgba(160,200,255,.10);
backdrop-filter:blur(14px) saturate(120%);-webkit-backdrop-filter:blur(14px) saturate(120%);
overflow:hidden}
.sx-verre::before{content:"";position:absolute;inset:-40% -30%;pointer-events:none;
background:linear-gradient(112deg,transparent 40%,rgba(140,203,255,.10) 50%,transparent 61%);
transform:translateX(-78%) rotate(8deg);transition:transform .9s cubic-bezier(.2,.7,.3,1)}
.sx-verre:hover::before{transform:translateX(78%) rotate(8deg)}
.sx-entree{animation:sxMonte .8s cubic-bezier(.16,.84,.31,1) both}
.sx-entree-2{animation:sxMonte .8s .09s cubic-bezier(.16,.84,.31,1) both}
.sx-entree-3{animation:sxMonte .8s .18s cubic-bezier(.16,.84,.31,1) both}
@keyframes sxMonte{from{opacity:0;transform:translateY(34px) scale(.985)}to{opacity:1;transform:none}}
@media(max-width:760px){.sx-verre{border-radius:15px}}
@media(prefers-reduced-motion:reduce){
 html{scroll-behavior:auto}
 .sx-entree,.sx-entree-2,.sx-entree-3{animation:none!important}
 .sx-verre::before{display:none}}
"""

#: Le canvas. Volontairement sans dépendance : Three.js pour quatre couches de
#: points serait des centaines de kilo-octets pour ce que 2D fait très bien.
JS = """
(()=>{"use strict";
const c=document.getElementById("sxfx");if(!c)return;
const ctx=c.getContext("2d",{alpha:true});if(!ctx)return;
const doux=matchMedia("(prefers-reduced-motion: reduce)");
const petit=()=>innerWidth<760||matchMedia("(pointer:coarse)").matches;
let L=0,H=0,dpr=1,noeuds=[],poussiere=[],raf=0,t=0,vise={x:0,y:0},vue={x:0,y:0},vivant=true;
function dimensionner(){
 dpr=Math.min(devicePixelRatio||1,petit()?1.5:2);
 L=innerWidth;H=innerHeight;c.width=Math.floor(L*dpr);c.height=Math.floor(H*dpr);
 c.style.width=L+"px";c.style.height=H+"px";ctx.setTransform(dpr,0,0,dpr,0,0);semer();}
function semer(){
 const n=petit()?26:Math.min(74,Math.round(L*H/22000));
 noeuds=Array.from({length:n},()=>({x:Math.random()*L,y:Math.random()*H,
  z:.35+Math.random()*.65,vx:(Math.random()-.5)*.13,vy:(Math.random()-.5)*.13}));
 const p=petit()?34:Math.min(130,Math.round(L*H/12000));
 poussiere=Array.from({length:p},()=>({x:Math.random()*L,y:Math.random()*H,
  z:.2+Math.random()*.8,r:.5+Math.random()*1.5,vy:-(.05+Math.random()*.16)}));}
function grille(dx,dy){
 const hz=H*.60,pas=68,prof=16;
 ctx.lineWidth=1;
 for(let i=0;i<prof;i++){
  const k=i/prof,y=hz+Math.pow(k,1.9)*(H-hz)*1.5+((t*.22)%((H-hz)/prof));
  if(y<hz||y>H+40)continue;
  ctx.strokeStyle="rgba(118,163,230,"+(0.026+0.052*k).toFixed(3)+")";
  ctx.beginPath();ctx.moveTo(-40,y+dy*.05);ctx.lineTo(L+40,y+dy*.05);ctx.stroke();}
 for(let x=-6;x<=6;x++){
  ctx.strokeStyle="rgba(118,163,230,.030)";
  ctx.beginPath();ctx.moveTo(L/2+x*pas*.55+dx*.06,hz);
  ctx.lineTo(L/2+x*pas*5.2+dx*.30,H+40);ctx.stroke();}}
function halos(dx,dy){
 const a=[[0.78,-0.06,"77,163,255",.17],[0.10,0.40,"111,125,255",.13],[0.52,0.92,"140,203,255",.09]];
 for(let i=0;i<a.length;i++){
  const[hx,hy,rgb,al]=a[i],ph=t*.00035+i*2.1,
   x=L*hx+Math.cos(ph)*L*.06+dx*(.10+i*.05),
   y=H*hy+Math.sin(ph*1.3)*H*.05+dy*(.10+i*.05),
   r=Math.min(L,H)*(.30+.08*Math.sin(ph*.8));
  const g=ctx.createRadialGradient(x,y,0,x,y,r);
  g.addColorStop(0,"rgba("+rgb+","+al+")");g.addColorStop(1,"rgba("+rgb+",0)");
  ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r,0,6.2832);ctx.fill();}}
function reseau(dx,dy){
 const seuil=petit()?118:152;
 for(let i=0;i<noeuds.length;i++){
  const a=noeuds[i];a.x+=a.vx*a.z;a.y+=a.vy*a.z;
  if(a.x<-30)a.x=L+30;if(a.x>L+30)a.x=-30;if(a.y<-30)a.y=H+30;if(a.y>H+30)a.y=-30;
  const ax=a.x+dx*a.z*.5,ay=a.y+dy*a.z*.5;
  for(let j=i+1;j<noeuds.length;j++){
   const b=noeuds[j],bx=b.x+dx*b.z*.5,by=b.y+dy*b.z*.5,
    d=Math.hypot(ax-bx,ay-by);
   if(d>seuil)continue;
   ctx.strokeStyle="rgba(118,163,230,"+(0.17*(1-d/seuil)*a.z*b.z).toFixed(3)+")";
   ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke();}
  ctx.fillStyle="rgba(160,205,255,"+(0.30*a.z).toFixed(3)+")";
  ctx.beginPath();ctx.arc(ax,ay,1.5*a.z+.5,0,6.2832);ctx.fill();}}
function grains(dx,dy){
 for(const p of poussiere){
  p.y+=p.vy*p.z;if(p.y<-8){p.y=H+8;p.x=Math.random()*L;}
  ctx.fillStyle="rgba(200,226,255,"+(0.24*p.z).toFixed(3)+")";
  ctx.beginPath();ctx.arc(p.x+dx*p.z*.8,p.y+dy*p.z*.8,p.r*p.z,0,6.2832);ctx.fill();}}
function image(){
 raf=0;if(!vivant)return;
 t+=16;vue.x+=(vise.x-vue.x)*.045;vue.y+=(vise.y-vue.y)*.045;
 ctx.clearRect(0,0,L,H);
 halos(vue.x,vue.y);grille(vue.x,vue.y);reseau(vue.x,vue.y);grains(vue.x,vue.y);
 if(vivant&&!raf)raf=requestAnimationFrame(image);}
function relancer(){if(vivant&&!raf)raf=requestAnimationFrame(image);}
function fixe(){ctx.clearRect(0,0,L,H);halos(0,0);grille(0,0);reseau(0,0);grains(0,0);}
addEventListener("resize",()=>{dimensionner();if(doux.matches)fixe();},{passive:true});
document.addEventListener("visibilitychange",()=>{
 // Un fond animé dans un onglet masqué est du calcul jeté.
 vivant=!document.hidden&&!doux.matches;
 if(vivant)relancer();else if(raf){cancelAnimationFrame(raf);raf=0;}});
if(!petit()){addEventListener("pointermove",e=>{
 vise.x=(e.clientX/innerWidth-.5)*52;vise.y=(e.clientY/innerHeight-.5)*38;},{passive:true});}
dimensionner();
if(doux.matches){vivant=false;fixe();}else relancer();
doux.addEventListener&&doux.addEventListener("change",()=>{
 if(doux.matches){vivant=false;if(raf){cancelAnimationFrame(raf);raf=0;}fixe();}
 else{vivant=true;relancer();}});
})();
"""


def fond() -> str:
    """Le canvas, à poser en premier enfant de ``<body>``."""
    return '<canvas id="sxfx" aria-hidden="true"></canvas>'


def script() -> str:
    return f"<script>{JS}</script>"


def styles() -> str:
    return f"<style>{CSS}</style>"
