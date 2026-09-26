"""Pages d'erreur SentriX — une vraie page, pas « 404: Not Found ».

Mesuré en production le 2026-09-26 : une route inexistante renvoyait
quatorze octets de texte brut, le défaut d'aiohttp. Un visiteur qui se trompe
d'URL tombait sur une page blanche sans logo, sans lien, sans issue — alors
que tout le reste du site venait d'être refait.

Le middleware n'intercepte que ce qui doit l'être :

  - uniquement les réponses d'erreur ``4xx``/``5xx`` ;
  - uniquement quand le client demande du HTML. Une erreur d'API reste du
    JSON, sans quoi le dashboard recevrait une page web là où il attend un
    objet et casserait silencieusement ;
  - jamais sous ``/api/``, ``/health`` ni les fichiers statiques, même si un
    navigateur les ouvre à la main.

Il ne change aucun code de statut : un 404 reste un 404, un 500 reste un 500.
Seul le corps devient lisible.
"""
from __future__ import annotations

import html
import logging

from aiohttp import web

from web import sentrix_fx_v1 as fx

logger = logging.getLogger("bot.dashboard.pages-erreur")

_INSTALLED = False

#: Préfixes que le middleware laisse strictement tranquilles. Le dashboard et
#: les sondes de Railway attendent du JSON ou du texte court ; leur renvoyer
#: une page HTML casserait leur lecture.
_INTACTS = ("/api/", "/health", "/metrics", "/assets/", "/static/", "/favicon")

#: Ce qu'on dit au visiteur, par code. Un message utile nomme ce qui s'est
#: passé ET ce qu'il peut faire — « Not Found » ne fait ni l'un ni l'autre.
_MESSAGES = {
    404: (
        "Page introuvable",
        "Cette adresse n'existe pas ou n'existe plus. Les liens ci-dessous "
        "mènent aux pages réellement en ligne.",
    ),
    403: (
        "Accès refusé",
        "Cette page demande une autorisation que votre session n'a pas. "
        "Connectez-vous avec Discord, puis réessayez.",
    ),
    429: (
        "Trop de requêtes",
        "Vous avez ouvert beaucoup de pages en peu de temps. Patientez "
        "quelques secondes avant de réessayer.",
    ),
    500: (
        "Erreur interne",
        "Quelque chose s'est mal passé de notre côté. L'incident est "
        "journalisé ; réessayez dans un instant.",
    ),
    502: (
        "Service momentanément indisponible",
        "SentriX redémarre ou déploie une mise à jour. Réessayez dans "
        "quelques secondes.",
    ),
    503: (
        "Service momentanément indisponible",
        "SentriX redémarre ou déploie une mise à jour. Réessayez dans "
        "quelques secondes.",
    ),
}

_LIENS = (
    ("/", "Accueil"),
    ("/docs", "Documentation"),
    ("/app", "Dashboard"),
    ("/support", "Support"),
    ("/commands", "Commandes"),
)


def _veut_du_html(request: web.Request) -> bool:
    accept = str(request.headers.get("Accept", ""))
    if "text/html" in accept:
        return True
    # Un navigateur qui ne précise rien reste un navigateur : on ne se fie pas
    # à l'absence d'en-tête pour renvoyer du texte brut.
    return accept in ("", "*/*") and "Mozilla" in str(request.headers.get("User-Agent", ""))


def rendre(statut: int, chemin: str = "") -> str:
    titre, explication = _MESSAGES.get(
        statut,
        ("Erreur", "La requête n'a pas abouti. Réessayez ou passez par le support."),
    )
    liens = "".join(
        f'<a class="sx-lien" href="{h}">{html.escape(libelle)}</a>'
        for h, libelle in _LIENS
    )
    demande = (
        f'<p class="sx-chemin"><span>Adresse demandée</span><code>{html.escape(chemin)}</code></p>'
        if chemin else ""
    )
    return f"""<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{statut} · {html.escape(titre)} — SentriX</title>
<meta name="robots" content="noindex,follow">
<meta name="description" content="{html.escape(explication, quote=True)}">
{fx.styles()}
<style>
.sx-shell{{min-height:100vh;display:flex;flex-direction:column}}
.sx-tete{{max-width:1120px;width:100%;margin:auto;padding:22px 24px;display:flex;
 justify-content:space-between;align-items:center;gap:14px}}
.sx-marque{{display:flex;align-items:center;gap:11px;font-weight:900;font-size:19px;
 text-decoration:none;letter-spacing:-.02em}}
.sx-marque img{{width:34px;height:34px;border-radius:11px;
 box-shadow:0 0 0 1px var(--ligne),0 8px 26px rgba(77,163,255,.22)}}
.sx-corps{{flex:1;display:flex;align-items:center;justify-content:center;
 padding:28px 24px 72px}}
.sx-carte{{max-width:720px;width:100%;padding:44px 42px 38px;text-align:center}}
.sx-code{{font-size:clamp(76px,17vw,148px);line-height:.88;font-weight:900;
 letter-spacing:-.06em;margin:0;
 background:linear-gradient(168deg,#ffffff 4%,var(--bleu2) 42%,var(--bleu) 72%,var(--indigo));
 -webkit-background-clip:text;background-clip:text;color:transparent;
 filter:drop-shadow(0 16px 42px rgba(77,163,255,.32))}}
.sx-anneau{{position:absolute;left:50%;top:92px;width:330px;height:330px;margin-left:-165px;
 border:1px solid rgba(118,163,230,.20);border-radius:50%;pointer-events:none;
 animation:sxTourne 26s linear infinite}}
.sx-anneau.b{{width:452px;height:452px;margin-left:-226px;top:31px;
 border-color:rgba(111,125,255,.13);animation-duration:40s;animation-direction:reverse}}
@keyframes sxTourne{{to{{transform:rotate(360deg)}}}}
h1{{font-size:clamp(23px,4.2vw,31px);margin:16px 0 10px;letter-spacing:-.025em}}
.sx-texte{{color:var(--doux);margin:0 auto;max-width:520px;font-size:16.5px}}
.sx-chemin{{margin:22px auto 0;display:inline-flex;align-items:center;gap:10px;
 flex-wrap:wrap;justify-content:center;font-size:13px;color:var(--doux)}}
.sx-chemin code{{background:rgba(10,17,30,.82);border:1px solid var(--ligne);
 border-radius:9px;padding:5px 11px;color:var(--bleu2);
 font:13px ui-monospace,SFMono-Regular,Menlo,monospace;
 max-width:min(440px,78vw);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sx-liens{{display:flex;gap:9px;flex-wrap:wrap;justify-content:center;margin-top:30px}}
.sx-lien{{border:1px solid var(--ligne);border-radius:11px;padding:11px 17px;
 text-decoration:none;font-weight:750;font-size:14.5px;
 background:linear-gradient(170deg,rgba(32,45,70,.72),rgba(15,23,39,.72));
 transition:transform .2s cubic-bezier(.2,.7,.3,1),border-color .2s,box-shadow .2s}}
.sx-lien:hover{{transform:translateY(-2px);border-color:rgba(140,203,255,.44);
 box-shadow:0 14px 34px rgba(2,6,16,.48),0 0 24px rgba(77,163,255,.14)}}
.sx-lien:first-child{{background:linear-gradient(135deg,#2f7fd4,var(--bleu),var(--bleu2));
 color:#04101d;border-color:transparent;font-weight:850}}
.sx-pied{{text-align:center;color:var(--doux);font-size:12.5px;padding:0 24px 30px}}
@media(max-width:560px){{.sx-carte{{padding:34px 22px 30px}}
 .sx-anneau{{width:250px;height:250px;margin-left:-125px;top:74px}}
 .sx-anneau.b{{width:340px;height:340px;margin-left:-170px;top:28px}}
 .sx-lien{{flex:1 1 44%;text-align:center}}}}
@media(max-width:360px){{.sx-tete{{padding:16px 13px}}.sx-corps{{padding:18px 13px 56px}}}}
@media(prefers-reduced-motion:reduce){{.sx-anneau{{animation:none}}
 .sx-lien{{transition:none}}.sx-lien:hover{{transform:none}}}}
</style></head>
<body>{fx.fond()}
<div class="sx-shell">
 <header class="sx-tete">
  <a class="sx-marque" href="/"><img src="/sentrix-avatar.png" alt="" width="34" height="34"><span>SentriX</span></a>
 </header>
 <main class="sx-corps">
  <div class="sx-verre sx-carte sx-entree">
   <div class="sx-anneau" aria-hidden="true"></div>
   <div class="sx-anneau b" aria-hidden="true"></div>
   <p class="sx-code">{statut}</p>
   <h1>{html.escape(titre)}</h1>
   <p class="sx-texte">{html.escape(explication)}</p>
   {demande}
   <nav class="sx-liens" aria-label="Aller à">{liens}</nav>
  </div>
 </main>
 <p class="sx-pied">SentriX · modération, sécurité et automatisation pour Discord</p>
</div>
{fx.script()}
</body></html>"""


@web.middleware
async def pages_erreur(request: web.Request, handler):
    chemin = request.path
    intact = chemin.startswith(_INTACTS)
    try:
        reponse = await handler(request)
    except web.HTTPException as exc:
        statut = exc.status
        if intact or statut < 400 or not _veut_du_html(request):
            raise
        return web.Response(
            text=rendre(statut, chemin), status=statut, content_type="text/html",
            charset="utf-8",
        )
    if intact or reponse.status < 400 or not _veut_du_html(request):
        return reponse
    # Une réponse d'erreur déjà rendue en HTML par une couche métier garde sa
    # page : on ne remplace que le texte brut par défaut.
    if str(reponse.content_type) == "text/html" and (reponse.body or b"") and len(reponse.body) > 400:
        return reponse
    return web.Response(
        text=rendre(reponse.status, chemin), status=reponse.status,
        content_type="text/html", charset="utf-8",
    )


def install(dashboard) -> None:
    """Ajoute le middleware au sommet de la pile, en conservant l'existant."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    build_origine = dashboard.build_app

    def build_app(bot):
        app = build_origine(bot)
        if pages_erreur not in app.middlewares:
            # En dernier : aiohttp applique les middlewares de l'extérieur vers
            # l'intérieur, donc le dernier inscrit voit la réponse en premier
            # au retour, ce qui est exactement ce qu'il faut pour la réécrire.
            app.middlewares.append(pages_erreur)
        return app

    dashboard.build_app = build_app
    logger.info("Pages d'erreur SentriX installées (404, 403, 429, 5xx).")


__all__ = ["install", "rendre", "pages_erreur"]
