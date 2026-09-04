"""Panneau DM du Dashboard : diffusion à tout le serveur et message à un membre.

Ce module n'implémente AUCUN moteur d'envoi : il appelle celui de
``sentrix_broadcast_dmall_visual`` — exactement celui de ``+dmall``. Écrire à des
centaines de personnes est une action irréversible ; en avoir deux implémentations
concurrentes garantirait qu'un jour l'une des deux oublie une protection.

Sécurité : l'autorisation est vérifiée **côté serveur** à chaque appel. Cacher le
bouton dans le navigateur ne protège rien — la route reste appelable directement.
Le contrôle est volontairement plus strict que « peut administrer le serveur » :
seuls le propriétaire du serveur et le propriétaire de SentriX peuvent diffuser,
comme pour ``+dmall``.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.dm-panel")

_JOBS_KEY = "sentrix_dm_jobs"
# Un job terminé reste consultable un moment pour que l'onglet affiche le bilan.
_RETENTION_SECONDS = 600
LONGUEUR_MAX = 3500


def _moteur():
    import sentrix_broadcast_dmall_visual as moteur

    return moteur


def _jobs(app: web.Application) -> dict:
    magasin = app.get(_JOBS_KEY)
    if magasin is None:
        magasin = {}
        app[_JOBS_KEY] = magasin
    return magasin


def _purger(magasin: dict) -> None:
    limite = time.time() - _RETENTION_SECONDS
    for cle in [k for k, v in magasin.items() if v.get("termine") and v.get("fin", 0) < limite]:
        magasin.pop(cle, None)


async def _peut_diffuser(request: web.Request, guild) -> bool:
    """Propriétaire du serveur ou propriétaire de SentriX, comme +dmall."""
    session = request.get("sentrix_session") or {}
    try:
        user_id = int(session.get("user", {}).get("id"))
    except (TypeError, ValueError):
        return False
    if guild.owner_id == user_id:
        return True
    bot = request.app["bot"]
    try:
        return await bot.is_owner(discord_user(user_id))
    except Exception:
        return False


class discord_user:  # petit porteur d'ID, suffisant pour Bot.is_owner
    def __init__(self, identifiant: int) -> None:
        self.id = identifiant


def installer(dashboard) -> None:
    """Branche les routes DM sur le dashboard existant."""

    async def _autoriser(request: web.Request):
        """Retourne (guild, erreur). Vérifie session, serveur, puis droit de diffusion."""
        try:
            guild_id = int(request.match_info["guild_id"])
        except (KeyError, ValueError):
            return None, dashboard._json_error("Identifiant de serveur invalide.", 400)

        session, guild, erreur = await dashboard._manageable_guild(request, guild_id)
        if erreur:
            return None, erreur
        request["sentrix_session"] = session

        # Le CSRF ne concerne que les requetes qui AGISSENT : l'imposer sur les
        # lectures casserait le suivi de progression sans rien proteger.
        if request.method != "GET":
            erreur_csrf = dashboard._require_csrf(request, session)
            if erreur_csrf:
                return None, erreur_csrf

        if not await _peut_diffuser(request, guild):
            # Volontairement le même message qu'un serveur inconnu : ne pas révéler
            # l'existence d'une capacité à quelqu'un qui n'y a pas droit.
            return None, dashboard._json_error(
                "Seul le propriétaire du serveur peut écrire à ses membres en privé.", 403
            )
        return guild, None

    async def _texte(request: web.Request):
        try:
            charge = await request.json()
        except Exception:
            return None, dashboard._json_error("Requête invalide.", 400)
        contenu = str(charge.get("message") or "").strip()
        if not contenu:
            return None, dashboard._json_error("Le message est vide.", 400)
        if len(contenu) > LONGUEUR_MAX:
            return None, dashboard._json_error(
                f"Message trop long : {len(contenu)} caractères (maximum {LONGUEUR_MAX}).", 400
            )
        return (contenu, charge), None

    # ---------------------------------------------------------------- aperçu
    async def apercu(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        moteur = _moteur()
        bot = request.app["bot"]
        membres, bots = moteur.destinataires_du_serveur(guild, getattr(bot.user, "id", None))
        return web.json_response(
            {
                "guild": {"id": str(guild.id), "name": guild.name},
                "destinataires": len(membres),
                "bots_ignores": bots,
                "duree_estimee_secondes": round(len(membres) * moteur.SEND_DELAY_SECONDS),
            }
        )

    # ------------------------------------------------------------- DM ALL
    async def diffuser_tout(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        donnees, erreur = await _texte(request)
        if erreur:
            return erreur
        contenu, charge = donnees

        if not bool(charge.get("confirme")):
            return dashboard._json_error("Confirmation obligatoire avant diffusion.", 400)

        magasin = _jobs(request.app)
        _purger(magasin)
        job = magasin.get(guild.id)
        if job is not None and not job.get("termine"):
            # Anti double-clic ET anti double-envoi : la même réponse sert aux deux.
            return web.json_response({"deja_en_cours": True, "etat": job}, status=409)

        moteur = _moteur()
        # La commande +dmall utilise le même verrou : les deux surfaces ne peuvent
        # pas lancer une diffusion simultanée sur le même serveur.
        cog = request.app["bot"].get_cog("Broadcast")
        if cog is not None:
            if guild.id in cog.active_guilds:
                return web.json_response({"deja_en_cours": True}, status=409)
            cog.active_guilds.add(guild.id)

        membres, bots = moteur.destinataires_du_serveur(guild, getattr(request.app["bot"].user, "id", None))
        etat = {
            "total": len(membres),
            "envoyes": 0,
            "dms_fermes": 0,
            "echecs": 0,
            "bots_ignores": bots,
            "traites": 0,
            "termine": False,
            "debut": time.time(),
            "fin": 0.0,
        }
        magasin[guild.id] = etat

        async def progression(bilan):
            etat.update(bilan.en_dict())

        async def executer():
            try:
                await moteur.diffuser(
                    guild,
                    membres,
                    contenu,
                    bots_ignores=bots,
                    fabrique_panneau=getattr(cog, "_panneau_prive", None) if cog else None,
                    progression=progression,
                )
            except Exception:
                logger.exception("Diffusion DM échouée (serveur %s).", guild.id)
            finally:
                etat["termine"] = True
                etat["fin"] = time.time()
                if cog is not None:
                    cog.active_guilds.discard(guild.id)

        asyncio.create_task(executer(), name=f"sentrix-dm-all-{guild.id}")
        return web.json_response({"demarre": True, "etat": etat})

    # ----------------------------------------------------------- progression
    async def etat_job(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        magasin = _jobs(request.app)
        _purger(magasin)
        etat = magasin.get(guild.id)
        return web.json_response({"actif": etat is not None and not etat["termine"], "etat": etat})

    # -------------------------------------------------------- DM utilisateur
    async def diffuser_un(request: web.Request):
        guild, erreur = await _autoriser(request)
        if erreur:
            return erreur
        donnees, erreur = await _texte(request)
        if erreur:
            return erreur
        contenu, charge = donnees

        try:
            membre_id = int(str(charge.get("user_id") or "").strip())
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de membre invalide.", 400)

        membre = guild.get_member(membre_id)
        if membre is None:
            return dashboard._json_error("Ce membre est introuvable sur ce serveur.", 404)
        if membre.bot:
            return dashboard._json_error("Les bots ne reçoivent pas de message privé.", 400)

        moteur = _moteur()
        cog = request.app["bot"].get_cog("Broadcast")
        bilan = await moteur.diffuser(
            guild,
            [membre],
            contenu,
            fabrique_panneau=getattr(cog, "_panneau_prive", None) if cog else None,
        )
        if bilan.envoyes:
            resultat, message = "envoye", f"{membre.display_name} a bien reçu le message."
        elif bilan.dms_fermes:
            resultat, message = "dm_ferme", f"{membre.display_name} n'accepte pas les messages privés."
        else:
            resultat, message = "echec", "Discord a refusé l'envoi."
        return web.json_response({"resultat": resultat, "message": message, "bilan": bilan.en_dict()})

    dashboard.DM_PANEL_ROUTES = [
        ("GET", "/api/guilds/{guild_id}/dm/apercu", apercu),
        ("POST", "/api/guilds/{guild_id}/dm/all", diffuser_tout),
        ("GET", "/api/guilds/{guild_id}/dm/job", etat_job),
        ("POST", "/api/guilds/{guild_id}/dm/user", diffuser_un),
    ]

    original_build = dashboard.build_app

    def build_app_avec_dm(bot):
        app = original_build(bot)
        for methode, chemin, handler in dashboard.DM_PANEL_ROUTES:
            app.router.add_route(methode, chemin, handler)
        return app

    if not getattr(dashboard.build_app, "_sentrix_dm_panel", False):
        build_app_avec_dm._sentrix_dm_panel = True
        build_app_avec_dm._sentrix_original = original_build
        dashboard.build_app = build_app_avec_dm
        logger.info("Panneau DM du Dashboard installé (moteur +dmall partagé).")

    installer_interface(dashboard)


__all__ = ["installer", "installer_interface", "LONGUEUR_MAX"]


# ---------------------------------------------------------------------------
# Interface
#
# Injectée APRÈS la restauration de INDEX_HTML par web/__init__ : posée avant,
# elle serait effacée comme les anciennes couches visuelles.
#
# L'onglet n'affiche rien de sensible tant que le serveur n'a pas confirmé le
# droit : la visibilité est décidée par la réponse de /dm/apercu, pas par une
# supposition du navigateur. Cacher un bouton ne protège rien — c'est la route
# qui refuse, ici on ne fait qu'éviter de proposer une action interdite.
# ---------------------------------------------------------------------------
_DM_STYLE = """
<style id="sentrix-dm-style">
.dm-shell{display:flex;flex-direction:column;gap:16px}
.dm-card{border:1px solid var(--line,#2a2a3a);border-radius:12px;padding:16px;background:var(--card,#16161f)}
.dm-card h3{margin:0 0 4px;font-size:15px}
.dm-card p.dm-hint{margin:0 0 12px;opacity:.7;font-size:13px}
.dm-row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end}
.dm-row>*{flex:1 1 220px;min-width:0}
.dm-shell textarea{width:100%;min-height:110px;resize:vertical;box-sizing:border-box}
.dm-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:12px}
.dm-stat{border:1px solid var(--line,#2a2a3a);border-radius:10px;padding:10px 12px}
.dm-stat b{display:block;font-size:19px;line-height:1.2}
.dm-stat span{font-size:12px;opacity:.7}
.dm-preview{white-space:pre-wrap;word-break:break-word;border:1px dashed var(--line,#2a2a3a);
  border-radius:10px;padding:12px;min-height:44px;font-size:14px}
.dm-bar{height:8px;border-radius:999px;background:var(--line,#2a2a3a);overflow:hidden;margin-top:12px}
.dm-bar>i{display:block;height:100%;width:0;background:var(--ok,#3ba55d);transition:width .3s}
.dm-confirm{display:flex;gap:10px;align-items:flex-start;margin-top:12px;font-size:13px}
.dm-confirm input{flex:0 0 auto;margin-top:2px}
.dm-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
@media(max-width:620px){.dm-row>*{flex:1 1 100%}.dm-actions .btn{width:100%}}
</style>
"""

_DM_SCRIPT = r"""
<script id="sentrix-dm-panel">
(() => {
  "use strict";
  if (window.__sentrixDmPanel) return;
  window.__sentrixDmPanel = true;

  const $id = (x) => document.getElementById(x);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g,
    (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  let sondage = null;
  const stopSondage = () => { if (sondage) { clearInterval(sondage); sondage = null; } };

  async function appel(chemin, options) {
    const init = Object.assign({credentials: "same-origin", headers: {}}, options || {});
    if (init.method && init.method !== "GET") {
      init.headers["Content-Type"] = "application/json";
      try { init.headers["X-CSRF-Token"] = state.csrf; } catch (_) {}
    }
    const reponse = await fetch(chemin, init);
    let donnees = null;
    try { donnees = await reponse.json(); } catch (_) {}
    return {ok: reponse.ok, status: reponse.status, donnees: donnees || {}};
  }

  function statistiques(e) {
    return `<div class="dm-stats">
      <div class="dm-stat"><b>${esc(e.envoyes || 0)}</b><span>Envoyés</span></div>
      <div class="dm-stat"><b>${esc(e.dms_fermes || 0)}</b><span>MP fermés</span></div>
      <div class="dm-stat"><b>${esc(e.echecs || 0)}</b><span>Échecs</span></div>
      <div class="dm-stat"><b>${esc(e.bots_ignores || 0)}</b><span>Bots ignorés</span></div>
    </div>`;
  }

  function afficherEtat(etat) {
    const zone = $id("dmAllProgress");
    if (!zone || !etat) return;
    const total = etat.total || 0;
    const pct = total ? Math.round((etat.traites || 0) * 100 / total) : 0;
    zone.innerHTML =
      `<div class="dm-bar"><i style="width:${pct}%"></i></div>` +
      `<p class="dm-hint" style="margin-top:8px">${esc(etat.traites || 0)} / ${esc(total)} membre(s) traité(s)` +
      (etat.termine ? " — diffusion terminée." : "…") + `</p>` + statistiques(etat);
    const bouton = $id("dmAllSend");
    if (bouton) bouton.disabled = !etat.termine;
    if (etat.termine) stopSondage();
  }

  async function suivre(guildId) {
    stopSondage();
    sondage = setInterval(async () => {
      const r = await appel(`/api/guilds/${guildId}/dm/job`);
      if (!r.ok) { stopSondage(); return; }
      afficherEtat(r.donnees.etat);
    }, 1500);
  }

  async function envoyerTous(guildId) {
    const bouton = $id("dmAllSend");
    const message = ($id("dmAllMessage") || {}).value || "";
    const confirme = ($id("dmAllConfirm") || {}).checked;
    if (!message.trim()) { toast("Le message est vide.", true); return; }
    if (!confirme) { toast("Coche la confirmation avant d'envoyer.", true); return; }
    // Anti double-clic : le bouton est neutralisé AVANT le premier aller-retour.
    if (bouton) bouton.disabled = true;
    const r = await appel(`/api/guilds/${guildId}/dm/all`, {
      method: "POST",
      body: JSON.stringify({message: message, confirme: true}),
    });
    if (r.status === 409) {
      toast("Une diffusion est déjà en cours sur ce serveur.", true);
      afficherEtat(r.donnees.etat);
      suivre(guildId);
      return;
    }
    if (!r.ok) {
      toast(r.donnees.error || "Envoi refusé.", true);
      if (bouton) bouton.disabled = false;
      return;
    }
    afficherEtat(r.donnees.etat);
    suivre(guildId);
  }

  async function envoyerUn(guildId) {
    const bouton = $id("dmOneSend");
    const cible = (($id("dmOneUser") || {}).value || "").trim();
    const message = ($id("dmOneMessage") || {}).value || "";
    const zone = $id("dmOneResult");
    if (!cible) { toast("Indique un membre ou son ID.", true); return; }
    if (!message.trim()) { toast("Le message est vide.", true); return; }
    if (bouton) bouton.disabled = true;
    const r = await appel(`/api/guilds/${guildId}/dm/user`, {
      method: "POST",
      body: JSON.stringify({user_id: cible, message: message}),
    });
    if (bouton) bouton.disabled = false;
    if (zone) {
      const ok = r.ok && r.donnees.resultat === "envoye";
      zone.innerHTML = `<p class="dm-hint" style="margin:0">${
        ok ? "● " : "○ "}${esc(r.donnees.message || r.donnees.error || "Échec de l'envoi.")}</p>`;
    }
  }

  function apercu(sourceId, cibleId) {
    const source = $id(sourceId), cible = $id(cibleId);
    if (!source || !cible) return;
    const maj = () => {
      const v = source.value || "";
      cible.textContent = v.trim() ? v : "L'aperçu du message s'affichera ici.";
    };
    source.addEventListener("input", maj);
    maj();
  }

  window.sentrixRenderDM = async function renderDM() {
    stopSondage();
    const guildId = state.guildId;
    const hote = $id("fields");
    if (!hote || !guildId) return;
    hote.innerHTML = `<div class="dm-shell"><div class="dm-card"><p class="dm-hint" style="margin:0">Vérification des droits…</p></div></div>`;

    // C'est le SERVEUR qui décide : un membre non autorisé ne reçoit jamais le formulaire.
    const info = await appel(`/api/guilds/${guildId}/dm/apercu`);
    if (!info.ok) {
      hote.innerHTML = `<div class="dm-shell"><div class="dm-card">
        <h3>Réservé au propriétaire du serveur</h3>
        <p class="dm-hint">${esc(info.donnees.error || "Tu n'as pas accès à cette section.")}</p>
      </div></div>`;
      return;
    }
    const d = info.donnees;
    const minutes = Math.max(1, Math.round((d.duree_estimee_secondes || 0) / 60));

    hote.innerHTML = `<div class="dm-shell">
      <div class="dm-card">
        <h3>Message privé à tout le serveur</h3>
        <p class="dm-hint">${esc(d.guild.name)} — <b>${esc(d.destinataires)}</b> membre(s) ciblé(s),
          ${esc(d.bots_ignores)} bot(s) ignoré(s). Durée estimée : environ ${esc(minutes)} min.</p>
        <textarea id="dmAllMessage" maxlength="3500" placeholder="Message envoyé à chaque membre…"></textarea>
        <p class="dm-hint" style="margin:10px 0 6px">Aperçu</p>
        <div class="dm-preview" id="dmAllPreview"></div>
        <label class="dm-confirm">
          <input type="checkbox" id="dmAllConfirm">
          <span>Je confirme l'envoi à <b>${esc(d.destinataires)}</b> membre(s). Cette action est irréversible.</span>
        </label>
        <div class="dm-actions"><button class="btn primary" type="button" id="dmAllSend">Envoyer à tous</button></div>
        <div id="dmAllProgress"></div>
      </div>
      <div class="dm-card">
        <h3>Message privé à un membre</h3>
        <p class="dm-hint">Indique un identifiant Discord, ou colle une mention.</p>
        <div class="dm-row">
          <div><input id="dmOneUser" type="text" inputmode="numeric" placeholder="ID du membre"></div>
        </div>
        <textarea id="dmOneMessage" maxlength="3500" placeholder="Message privé…" style="margin-top:12px"></textarea>
        <p class="dm-hint" style="margin:10px 0 6px">Aperçu</p>
        <div class="dm-preview" id="dmOnePreview"></div>
        <div class="dm-actions"><button class="btn primary" type="button" id="dmOneSend">Envoyer</button></div>
        <div id="dmOneResult"></div>
      </div>
    </div>`;

    apercu("dmAllMessage", "dmAllPreview");
    apercu("dmOneMessage", "dmOnePreview");
    $id("dmAllSend").addEventListener("click", () => envoyerTous(guildId));
    $id("dmOneSend").addEventListener("click", () => envoyerUn(guildId));
    // Une diffusion lancée ailleurs (ou avant un rafraîchissement) reste visible.
    const job = await appel(`/api/guilds/${guildId}/dm/job`);
    if (job.ok && job.donnees.etat) {
      afficherEtat(job.donnees.etat);
      if (job.donnees.actif) suivre(guildId);
    }
    // Une mention collée est ramenée à son identifiant.
    $id("dmOneUser").addEventListener("input", (e) => {
      const m = /(\d{15,22})/.exec(e.target.value || "");
      if (m && e.target.value !== m[1]) e.target.value = m[1];
    });
  };
})();
</script>
"""


def installer_interface(dashboard) -> None:
    """Ajoute l'onglet « Messages privés » à la page principale du Dashboard."""
    html = dashboard.INDEX_HTML
    if 'id="sentrix-dm-panel"' in html:
        return

    # 1. Entrée de navigation, juste après le dernier onglet de configuration.
    html = html.replace(
        '<button data-tab="roles">Rôles et salons</button>',
        '<button data-tab="roles">Rôles et salons</button>\n'
        '        <button data-tab="dm">Messages privés</button>',
        1,
    )
    # 2. Déclaration de l'onglet.
    html = html.replace(
        "    const tabs={",
        '    const tabs={dm:{title:"Messages privés",'
        'description:"Écrire à tout le serveur ou à un membre. Réservé au propriétaire.",dm:true},',
        1,
    )
    # 3. Aiguillage du rendu + barre d'enregistrement masquée (rien à « enregistrer » ici).
    html = html.replace(
        "if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();",
        "if(tab.dm){window.sentrixRenderDM&&window.sentrixRenderDM();}"
        "else if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();",
        1,
    )
    html = html.replace(
        '$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));',
        '$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions||tab.dm));',
        1,
    )
    # 4. Style et script.
    html = html.replace("</head>", _DM_STYLE + "\n</head>", 1)
    html = html.replace("</body>", _DM_SCRIPT + "\n</body>", 1)

    dashboard.INDEX_HTML = html
    logger.info("Interface du panneau DM injectée dans le Dashboard.")
