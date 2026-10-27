"""Private transcript browser page. No token in HTTP paths, query strings or logs."""
from __future__ import annotations

import logging
from html import escape

from aiohttp import web

from services import ticket_transcript_links as links
from services import ticket_transcript_html as renderer

logger = logging.getLogger("bot.ticket-transcript-viewer")

_VIEWER = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Transcription · SentriX</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
body{background:#202127;color:#f3f4f7;margin:0}
header{background:#181a20;border-bottom:1px solid #383b44;padding:24px max(20px,calc((100% - 980px)/2))}
h1{font-size:23px;margin:0}p{color:#adb0bb;line-height:1.55}
main{max-width:1020px;margin:auto;padding:48px 20px}
.panel{border:1px solid #3b3e47;border-radius:14px;background:#292b32;padding:24px}
small{color:#adb0bb}#status{overflow-wrap:anywhere}
</style></head><body>
<header><h1>SentriX · Transcription</h1><p>Consultation privée du ticket</p></header>
<main><section class="panel">
<h2 id="title">Ouverture de la conversation</h2>
<p id="status">Vérification du lien privé…</p>
<small>Ce lien est personnel. Ne le partagez pas.</small>
</section></main>
<script>
(async function () {
 const target=document.getElementById('status');
 const token=location.hash.substring(1);
 if(!/^[A-Za-z0-9_-]{40,60}$/.test(token)){
   document.getElementById('title').textContent='Lien invalide';
   target.textContent='Ouvrez le lien privé reçu en message Discord.';
   return;
 }
 try{
   const response=await fetch('/transcripts/view',{
     method:'POST',credentials:'omit',cache:'no-store',
     headers:{'Content-Type':'application/json'},
     body:JSON.stringify({token:token})
   });
   if(!response.ok){
     document.getElementById('title').textContent='Transcription inaccessible';
     target.textContent='Le lien est invalide, a expiré ou la transcription est indisponible.';
     return;
   }
   const html=await response.text();
   document.open();
   document.write(html);
   document.close();
 }catch(_){
   document.getElementById('title').textContent='Erreur de connexion';
   target.textContent='Impossible de charger la transcription. Réessayez.';
 }
})();
</script></body></html>"""


def _private_headers(response: web.StreamResponse):
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


async def handle_page(_request: web.Request) -> web.Response:
    return _private_headers(web.Response(
        text=_VIEWER, content_type="text/html", charset="utf-8",
    ))


async def handle_transcript(request: web.Request) -> web.Response:
    """Private bearer capability is passed in the POST body, never in the URL."""
    if request.content_type != "application/json" or request.content_length and request.content_length > 300:
        return _private_headers(web.Response(status=415, text="Requête invalide"))
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return _private_headers(web.Response(status=400, text="Requête invalide"))
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not links.TOKEN_RE.fullmatch(token):
        return _private_headers(web.Response(status=404, text="Lien indisponible"))
    try:
        data = await links.load_archive(request.app["bot"], token)
    except Exception:
        logger.exception("La base des transcriptions privées est indisponible.")
        return _private_headers(web.Response(status=503, text="Service indisponible"))
    if not data:
        return _private_headers(web.Response(status=404, text="Lien indisponible"))
    archive, ticket = data["archive"], data["ticket"]
    bot = request.app["bot"]
    guild = bot.get_guild(int(archive["guild_id"]))
    html = renderer.render_transcript_html(
        archive["transcript_text"],
        guild_name=guild.name if guild else "Serveur Discord",
        ticket_label=f"TICKET-{int(archive['ticket_id']):04d}",
        subject=str(archive["channel_name"] or "Assistance"),
        created_at=ticket["created_at"],
        closed_at=ticket["closed_at"],
        closed_by=data["closed_by"], close_reason=data["close_reason"],
    )
    return _private_headers(web.Response(
        text=html, content_type="text/html", charset="utf-8",
    ))


def register_routes(app: web.Application) -> None:
    """Used by recovery V54 after full builder and by its fallback app."""
    existing = {
        getattr(getattr(route, "resource", None), "canonical", "")
        for route in app.router.routes()
    }
    if "/transcripts" not in existing:
        app.router.add_get("/transcripts", handle_page)
    if "/transcripts/view" not in existing:
        app.router.add_post("/transcripts/view", handle_transcript)
