"""Initialisation du dashboard SentriX en mode stable.

Les routes avancées restent chargées, mais la page principale /app utilise volontairement
le HTML/JavaScript natif de web.dashboard. Les anciennes couches visuelles injectaient
plusieurs wrappers autour de renderTab/selectGuild/fetch et pouvaient finir par bloquer les
clics. On conserve donc leurs routes serveur, puis on restaure l'interface principale sûre.
"""

from . import dashboard as _dashboard
from . import setup_dashboard as _setup_dashboard
from . import design_setup_dashboard as _design_setup_dashboard
from . import setup_center as _setup_center
from . import setup_center_exclusive as _setup_center_exclusive
from . import setup_center_search as _setup_center_search
from . import dashboard_explanations_search as _dashboard_explanations_search
from . import setup_center_explanations as _setup_center_explanations
from . import embed_center as _embed_center
from . import dashboard_polish as _dashboard_polish
from . import persistent_dashboard_sessions as _persistent_dashboard_sessions
from . import owner_server_manager as _owner_server_manager
from . import admin_only_dashboard as _admin_only_dashboard
from . import dashboard_control_center as _dashboard_control_center
from . import ticket_ping_dashboard as _ticket_ping_dashboard
from . import dashboard_oxyde_theme as _dashboard_oxyde_theme
from . import dashboard_deeplinks as _dashboard_deeplinks
from . import dashboard_safe_plus as _dashboard_safe_plus
from . import dashboard_profile_images as _dashboard_profile_images
from . import dashboard_role_channel_search as _dashboard_role_channel_search
from . import dashboard_system_features as _dashboard_system_features
from . import setup_center_systems_rework as _setup_center_systems_rework
from . import setup_center_security_v2 as _setup_center_security_v2
from . import operations_center as _operations_center
from . import dashboard_simple_mode as _dashboard_simple_mode
from . import dashboard_simple_mode_switch_fix as _dashboard_simple_mode_switch_fix
from . import dashboard_no_decorative_icons as _dashboard_no_decorative_icons
from . import community_growth as _community_growth_dashboard
from . import community_card_polish as _community_card_polish
from . import engagement_hub as _engagement_hub
from . import dashboard_instance_runtime as _dashboard_instance_runtime
from . import instance_dashboard_branding as _instance_dashboard_branding
from . import log_settings_dashboard_v32 as _log_settings_dashboard_v32
from . import ticket_center_v35 as _ticket_center_v35
from . import feature_control_v36 as _feature_control_v36


# Copie propre AVANT toute injection. C'est cette version qui est finalement servie sur /app.
_CORE_INDEX_HTML = _dashboard.INDEX_HTML
_original_handle_index = _dashboard.handle_index


async def _handle_index_without_cache(request):
    """Force toujours le navigateur à récupérer la dernière interface corrigée."""
    response = await _original_handle_index(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


_dashboard.handle_index = _handle_index_without_cache

# Les modules suivants conservent leurs routes/API/pages secondaires. Leurs injections dans
# INDEX_HTML seront volontairement annulées plus bas pour éviter les conflits JavaScript.
_dashboard_explanations_search.install(_dashboard)
_setup_center_exclusive.install(_setup_center, _setup_dashboard)
_setup_center_search.install(_setup_center)
_setup_center_explanations.install(_setup_center)
_setup_center.install(_dashboard, _setup_dashboard, _design_setup_dashboard)
_embed_center.install(_dashboard)

# Correctifs propres aux pages secondaires.
_embed_center.EMBED_CENTER_HTML = _embed_center.EMBED_CENTER_HTML.replace(
    'id="saveButton" class="btn primary" type="submit"',
    'id="saveButton" class="btn primary" type="button"',
    1,
)
_embed_center.EMBED_CENTER_HTML = _embed_center.EMBED_CENTER_HTML.replace(
    '$("applyTemplate").addEventListener("click",applyTemplate);',
    '$("applyTemplate").addEventListener("click",()=>{applyTemplate();scheduleDraft();});',
    1,
)

_dashboard_polish.POLISH_JS = _dashboard_polish.POLISH_JS.replace(
    'document.documentElement.append(progress, offline);\n  document.body.appendChild(health);',
    'document.body.append(progress, offline, health);',
    1,
)
_dashboard_polish.POLISH_JS = _dashboard_polish.POLISH_JS.replace(
    'if (!confirmServerChange(event)) return;\n      if (event.target.value',
    'if (!confirmServerChange(event)) {\n        event.target.value = localStorage.getItem(storageKey("guild")) || "";\n        return;\n      }\n      if (event.target.value',
    1,
)
_dashboard_polish.install(_dashboard, _setup_center, _embed_center)

# Sessions persistantes et routes propriétaires restent actives côté serveur.
_persistent_dashboard_sessions.install(_dashboard)
_owner_server_manager.install(_dashboard)
_admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/embed-builder")
_admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/owner-servers")
_admin_only_dashboard.install(_dashboard)

# Conserve aussi les API ajoutées par ces modules. Leur UI principale sera retirée juste après.
_dashboard_control_center.install(_dashboard)
_ticket_ping_dashboard.install(_dashboard)
_dashboard_oxyde_theme.install(_dashboard)
_dashboard_deeplinks.install(_dashboard)


# Filet de sécurité spécifique au démarrage Railway : le serveur HTTP peut répondre avant
# que Discord ait fini de connecter le bot. Le bouton de connexion reste visible et la liste
# des serveurs se recharge automatiquement dès que SentriX devient prêt, sans F5 manuel.
_CORE_RECOVERY_JS = r"""
<script id="sentrix-core-recovery">
(() => {
  "use strict";
  if (window.__sentrixCoreRecovery) return;
  window.__sentrixCoreRecovery = true;

  const login = document.getElementById("loginButton");
  if (login) login.classList.remove("hidden");

  let attempts = 0;
  let guildReloading = false;
  const refreshRuntime = async () => {
    attempts += 1;
    try {
      const response = await fetch("/api/public", {cache:"no-store", credentials:"same-origin"});
      if (!response.ok) return;
      const data = await response.json();

      const status = document.getElementById("publicStatus");
      const dot = document.getElementById("publicDot");
      if (status) status.textContent = data.online ? "SentriX est opérationnel" : "Connexion Discord en cours";
      if (dot) dot.style.background = data.online ? "var(--ok)" : "var(--warn)";

      if (login) {
        login.classList.remove("hidden");
        login.setAttribute("aria-disabled", data.oauth_ready ? "false" : "true");
        login.title = data.oauth_ready ? "Se connecter avec Discord" : "SentriX termine son démarrage — réessayez dans quelques secondes";
      }

      if (
        data.online &&
        typeof state !== "undefined" &&
        state.user &&
        typeof loadGuilds === "function" &&
        !guildReloading &&
        (!state.guildId || !state.guildData)
      ) {
        guildReloading = true
        try { await loadGuilds(); } catch (_) {}
        finally { guildReloading = false; }
      }

      if (data.online && data.oauth_ready && attempts >= 6) clearInterval(timer);
    } catch (_) {
      // Le script principal affiche déjà les erreurs réseau. Ce polling reste silencieux.
    }
    if (attempts >= 90) clearInterval(timer);
  };

  const timer = setInterval(refreshRuntime, 2000);
  setTimeout(refreshRuntime, 100);
})();
</script>
"""


# IMPORTANT : on restaure la page principale d'origine après TOUS les installateurs.
# Cela supprime les anciens intercepts de clics/fetch et les wrappers imbriqués qui rendaient
# parfois toute l'interface inerte, tout en gardant les routes backend installées ci-dessus.
_main_html = _CORE_INDEX_HTML
_main_html = _main_html.replace(
    '$("loginButton").classList.add("hidden");',
    '',
    1,
)
if 'id="sentrix-core-recovery"' not in _main_html:
    _main_html = _main_html.replace("</body>", _CORE_RECOVERY_JS + "\n</body>", 1)
_dashboard.INDEX_HTML = _main_html

# V32/V35 sont installés APRÈS la restauration de la page principale : leurs interfaces
# ne peuvent donc pas être effacées par les anciennes couches visuelles.
_log_settings_dashboard_v32.install(_dashboard)
_ticket_center_v35.install(_dashboard)

# Community Growth doit être branché AVANT build_app()/le bind HTTP. Auparavant il était
# installé depuis une tâche asynchrone de cog ; Railway pouvait donc créer l'application
# aiohttp avant l'installation du wrapper build_app et /community répondait 404.
_community_growth_dashboard.install(_dashboard)
_community_card_polish.install(_dashboard)

# Engagement V3 s'installe aussi avant le bind HTTP : la route /engagement, les API et le
# bootstrap du cog sont ainsi disponibles dès le démarrage de l'application aiohttp.
_engagement_hub.install(_dashboard, _community_growth_dashboard)

_dashboard_instance_runtime.install(_dashboard)
_instance_dashboard_branding.install(_dashboard, _community_growth_dashboard)

# Enrichissements finaux sans monkey-patch des fonctions critiques du dashboard.
_dashboard_safe_plus.install(_dashboard)
_dashboard_profile_images.install(_dashboard)
_dashboard_role_channel_search.install(_dashboard, _setup_center)

# Les routes Argent/Niveaux restent actives, mais leur carte n'est PLUS injectée dans /app.
# Les interrupteurs sont volontairement déplacés dans /setup-center.
_dashboard_system_features.install(_dashboard)
_dashboard.INDEX_HTML = _dashboard.INDEX_HTML.replace(_dashboard_system_features.SYSTEMS_CSS, "")
_dashboard.INDEX_HTML = _dashboard.INDEX_HTML.replace(_dashboard_system_features.SYSTEMS_JS, "")
_setup_center_systems_rework.install(_setup_center)
_setup_center_security_v2.install(_dashboard, _setup_center)

# Operations est une page secondaire isolée + des routes backend. Installation ici, avant
# le démarrage HTTP anticipé de Railway, afin que /operations existe dès le premier bind.
_operations_center.install(_dashboard)

# Mode simple activé par défaut : accueil guidé, recherche et accès direct aux fonctions.
# Le dashboard historique reste intact derrière le bouton Mode avancé.
_dashboard_simple_mode.install(_dashboard)

# Correctif final de bascule : les deux modes restent toujours accessibles, même si le
# conteneur de navigation est masqué ou si le stockage local du navigateur est indisponible.
_dashboard_simple_mode_switch_fix.install(_dashboard)

# V36 est installé après le mode simple : son centre de fonctionnalités est visible à la fois
# sur l'accueil simple et dans Configuration générale en mode avancé.
_feature_control_v36.install(_dashboard)

# Toujours en dernier : retire les emojis/icônes décoratifs ajoutés par n'importe quelle
# couche précédente, sans toucher aux photos de profil ni au contenu configuré par l'utilisateur.
_dashboard_no_decorative_icons.install(
    _dashboard,
    _setup_center,
    _setup_dashboard,
    _design_setup_dashboard,
    _embed_center,
    _owner_server_manager,
    _operations_center,
    _engagement_hub,
)
