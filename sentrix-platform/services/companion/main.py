"""Application SentriX Companion.

Interface d'exploitation separee du dashboard de configuration Discord. Elle
observe le cluster HA, lance SentriX Doctor et expose la disponibilite Rescue.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from services.companion.doctor import SentrixDoctor
from services.companion.models import DoctorReport

_COOKIE_NAME = "sentrix_companion_session"
_SESSION_MESSAGE = b"sentrix-companion-v1"


class LoginRequest(BaseModel):
    access_key: str


def _access_key() -> str:
    return os.environ.get("COMPANION_ACCESS_TOKEN", "")


def _session_value(access_key: str) -> str:
    return hmac.new(access_key.encode("utf-8"), _SESSION_MESSAGE, hashlib.sha256).hexdigest()


def _cookie_secure() -> bool:
    return os.environ.get("COMPANION_COOKIE_SECURE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _is_authorized(request: Request) -> bool:
    key = _access_key()
    if not key:
        return False

    cookie = request.cookies.get(_COOKIE_NAME, "")
    if cookie and hmac.compare_digest(cookie, _session_value(key)):
        return True

    header = request.headers.get("X-Sentrix-Key", "")
    return bool(header and hmac.compare_digest(header, key))


async def require_access(request: Request) -> None:
    if not _access_key():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SentriX Companion n'est pas encore configure.",
        )
    if not _is_authorized(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")


def create_app(doctor_factory: Callable[[], SentrixDoctor] = SentrixDoctor) -> FastAPI:
    app = FastAPI(title="SentriX Companion", version="1.0.0")

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        """Healthcheck du Companion lui-meme, sans sonder la production."""
        return {"status": "ok"}

    @app.post("/api/login", tags=["auth"])
    async def login(payload: LoginRequest, response: Response) -> dict[str, bool]:
        key = _access_key()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="COMPANION_ACCESS_TOKEN absent",
            )
        if not hmac.compare_digest(payload.access_key, key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cle invalide")
        response.set_cookie(
            _COOKIE_NAME,
            _session_value(key),
            httponly=True,
            secure=_cookie_secure(),
            samesite="strict",
            max_age=12 * 3600,
            path="/",
        )
        return {"ok": True}

    @app.post("/api/logout", tags=["auth"])
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(_COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/session", tags=["auth"])
    async def session(request: Request) -> dict[str, bool]:
        return {"authenticated": _is_authorized(request), "configured": bool(_access_key())}

    @app.get("/api/doctor", response_model=DoctorReport, tags=["operations"])
    async def doctor(_: None = Depends(require_access)) -> DoctorReport:
        return await doctor_factory().run()

    @app.get("/api/rescue/readiness", tags=["operations"])
    async def rescue_readiness(_: None = Depends(require_access)) -> dict[str, object]:
        report = await doctor_factory().run()
        return {
            "severity": report.severity,
            "rescue": report.rescue.model_dump(),
            "active_incidents": len(report.incidents),
        }

    @app.get("/api/topology", tags=["operations"])
    async def topology(_: None = Depends(require_access)) -> dict[str, object]:
        report = await doctor_factory().run()
        return {
            "primary": report.primary.model_dump(),
            "standby": report.standby.model_dump(),
            "leader_count": report.rescue.leader_count,
            "automatic_failover": report.rescue.automatic_failover,
        }

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        return _HTML

    return app


app = create_app()


_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentriX Companion</title>
<style>
:root{color-scheme:dark;--bg:#070a10;--panel:#0e1420;--panel2:#121b2a;--line:#263247;--text:#eef4ff;--muted:#8f9bb0;--ok:#4fe09d;--warn:#f5c45d;--bad:#ff6b7a;--accent:#7c8cff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% -10%,#182241 0,transparent 35%),var(--bg);color:var(--text);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.shell{max-width:1180px;margin:auto;padding:28px 20px 60px}.top{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.brand{display:flex;align-items:center;gap:12px}.mark{width:42px;height:42px;border-radius:13px;background:linear-gradient(145deg,#7c8cff,#4c5ed9);display:grid;place-items:center;font-weight:900;font-size:19px;box-shadow:0 10px 30px #5568ff35}.brand h1{font-size:20px;margin:0}.brand p{margin:2px 0 0;color:var(--muted);font-size:12px}.actions{display:flex;gap:8px}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:10px;padding:9px 13px;font-weight:650;cursor:pointer}.btn:hover{border-color:#586985}.btn.primary{background:#5d6df0;border-color:#7886ff}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{background:linear-gradient(180deg,#111827e8,#0c121de8);border:1px solid var(--line);border-radius:16px;padding:17px;box-shadow:0 16px 50px #0003}.hero{grid-column:span 12;display:flex;justify-content:space-between;align-items:center;gap:24px}.hero h2{font-size:27px;margin:0 0 5px}.hero p{margin:0;color:var(--muted)}.status{padding:7px 11px;border-radius:999px;font-size:12px;font-weight:800;border:1px solid}.status.healthy{color:var(--ok);background:#10291f;border-color:#235b43}.status.warning{color:var(--warn);background:#2b2413;border-color:#5b4a25}.status.critical{color:var(--bad);background:#31161d;border-color:#6f2c39}.half{grid-column:span 6}.third{grid-column:span 4}.wide{grid-column:span 8}.card h3{margin:0 0 12px;font-size:13px;color:#b9c5d9;text-transform:uppercase;letter-spacing:.08em}.metric{font-size:28px;font-weight:800;letter-spacing:-.03em}.muted{color:var(--muted)}.instance{display:grid;grid-template-columns:1fr auto;gap:8px 14px;align-items:center;padding:11px 0;border-top:1px solid #202a3a}.instance:first-of-type{border-top:0}.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:7px;background:var(--muted)}.dot.ok{background:var(--ok);box-shadow:0 0 0 4px #4fe09d14}.dot.bad{background:var(--bad);box-shadow:0 0 0 4px #ff6b7a14}.kv{display:grid;grid-template-columns:1fr 1fr;gap:10px}.kv div{background:#0a1019;border:1px solid #202a3a;border-radius:11px;padding:11px}.kv b{display:block;font-size:16px;margin-top:3px}.incidents{display:flex;flex-direction:column;gap:9px}.incident{border:1px solid #342d2d;border-radius:12px;padding:12px;background:#130f13}.incident strong{display:block;margin-bottom:3px}.incident small{color:var(--muted)}.incident.critical{border-color:#642c38;background:#1b1015}.incident.warning{border-color:#5c4b27;background:#19160f}.empty{padding:24px;text-align:center;color:var(--muted);border:1px dashed #2b374a;border-radius:12px}.login{max-width:420px;margin:13vh auto 0}.login h2{font-size:25px;margin:0 0 7px}.login p{color:var(--muted)}input{width:100%;margin:12px 0;padding:12px 13px;border-radius:10px;border:1px solid var(--line);background:#080d15;color:var(--text);outline:none}input:focus{border-color:#7180ff}.hidden{display:none!important}.foot{margin-top:18px;color:#647086;font-size:11px}.skeleton{opacity:.5}@media(max-width:760px){.half,.third,.wide{grid-column:span 12}.top,.hero{align-items:flex-start;flex-direction:column}.actions{width:100%}.actions .btn{flex:1}}
</style>
</head>
<body>
<div class="shell">
<section id="login" class="card login hidden">
  <div class="brand"><div class="mark">S</div><div><h1>SentriX Companion</h1><p>Acces operationnel prive</p></div></div>
  <h2>Connexion</h2><p>Entrez la cle Companion configuree sur l'hebergeur.</p>
  <form id="loginForm"><input id="key" type="password" autocomplete="current-password" placeholder="Cle d'acces" required><button class="btn primary" type="submit">Ouvrir Companion</button></form>
  <p id="loginError" style="color:var(--bad)"></p>
</section>
<main id="app" class="hidden">
  <header class="top"><div class="brand"><div class="mark">S</div><div><h1>SentriX Companion</h1><p>Doctor · Rescue · Infrastructure</p></div></div><div class="actions"><button id="refresh" class="btn primary">Lancer le diagnostic</button><button id="logout" class="btn">Deconnexion</button></div></header>
  <div class="grid">
    <section class="card hero"><div><h2 id="headline">Analyse de SentriX…</h2><p id="subtitle">Verification du principal, du secours et des dependances.</p></div><span id="globalStatus" class="status warning">ANALYSE</span></section>
    <section class="card half"><h3>Cluster HA</h3><div id="instances"></div></section>
    <section class="card half"><h3>Rescue</h3><div class="metric" id="rescueReady">—</div><p class="muted" id="rescueReason">Verification en cours…</p><div class="kv"><div><span class="muted">Failover auto</span><b id="failover">—</b></div><div><span class="muted">Leaders</span><b id="leaders">—</b></div></div></section>
    <section class="card third"><h3>Redis / lease HA</h3><div class="metric" id="redis">—</div><p class="muted" id="redisLatency">—</p></section>
    <section class="card third"><h3>PostgreSQL / snapshots</h3><div class="metric" id="postgres">—</div><p class="muted" id="postgresLatency">—</p></section>
    <section class="card third"><h3>Incidents actifs</h3><div class="metric" id="incidentCount">—</div><p class="muted">Diagnostic automatique</p></section>
    <section class="card wide"><h3>Centre d'incidents</h3><div id="incidents" class="incidents"></div></section>
    <section class="card third"><h3>Derniere analyse</h3><div id="generated" class="metric" style="font-size:18px">—</div><p class="muted">Rapport Doctor</p></section>
  </div>
  <div class="foot">Le Doctor est volontairement en lecture seule : une verification ne peut ni casser le lease HA, ni forcer un failover.</div>
</main>
</div>
<script>
const $=id=>document.getElementById(id);
function setText(id,value){$(id).textContent=value}
function endpointRow(r){const row=document.createElement('div');row.className='instance';const left=document.createElement('div');const dot=document.createElement('span');dot.className='dot '+(r.reachable&&r.ok?'ok':'bad');left.append(dot,document.createTextNode(r.name==='primary'?'SentriX principal':'SentriX standby'));const right=document.createElement('strong');right.textContent=(r.state||'inconnu').toUpperCase();const detail=document.createElement('small');detail.className='muted';detail.textContent=`Discord ${r.discord_ready?'connecte':'standby'} · ${r.latency_ms??'—'} ms`;const role=document.createElement('small');role.className='muted';role.textContent=r.role||'role inconnu';row.append(left,right,detail,role);return row}
function render(d){setText('headline',d.severity==='healthy'?'SentriX est operationnel':d.severity==='warning'?'SentriX fonctionne avec une alerte':'Intervention requise');setText('subtitle',d.rescue.reason);const badge=$('globalStatus');badge.className='status '+d.severity;badge.textContent=d.severity.toUpperCase();const inst=$('instances');inst.replaceChildren(endpointRow(d.primary),endpointRow(d.standby));setText('rescueReady',d.rescue.ready?'PRET':'NON PRET');setText('rescueReason',d.rescue.reason);setText('failover',d.rescue.automatic_failover?'ACTIF':'INDISPONIBLE');setText('leaders',String(d.rescue.leader_count));setText('redis',d.redis.healthy?'OK':d.redis.configured?'ERREUR':'NON CONFIGURE');setText('redisLatency',d.redis.latency_ms==null?'—':`${d.redis.latency_ms} ms`);setText('postgres',d.postgres.healthy?'OK':d.postgres.configured?'ERREUR':'NON CONFIGURE');setText('postgresLatency',d.postgres.latency_ms==null?'—':`${d.postgres.latency_ms} ms`);setText('incidentCount',String(d.incidents.length));setText('generated',new Date(d.generated_at).toLocaleTimeString());const box=$('incidents');box.replaceChildren();if(!d.incidents.length){const e=document.createElement('div');e.className='empty';e.textContent='Aucun incident detecte.';box.append(e)}else d.incidents.forEach(i=>{const e=document.createElement('div');e.className='incident '+i.severity;const t=document.createElement('strong');t.textContent=i.title;const detail=document.createElement('div');detail.textContent=i.detail;const rec=document.createElement('small');rec.textContent='Action : '+i.recommendation;e.append(t,detail,rec);box.append(e)})}
async function load(){const r=await fetch('/api/doctor');if(r.status===401){$('app').classList.add('hidden');$('login').classList.remove('hidden');return}if(!r.ok)throw new Error('Diagnostic indisponible');$('login').classList.add('hidden');$('app').classList.remove('hidden');render(await r.json())}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();$('loginError').textContent='';const r=await fetch('/api/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({access_key:$('key').value})});if(!r.ok){$('loginError').textContent='Cle invalide ou Companion non configure.';return}$('key').value='';await load()});
$('refresh').addEventListener('click',()=>load().catch(()=>setText('subtitle','Le diagnostic n\'a pas pu etre execute.')));
$('logout').addEventListener('click',async()=>{await fetch('/api/logout',{method:'POST'});location.reload()});
fetch('/api/session').then(r=>r.json()).then(s=>{if(s.authenticated)load();else{$('login').classList.remove('hidden')}}).catch(()=>{$('login').classList.remove('hidden')});
</script>
</body>
</html>"""
