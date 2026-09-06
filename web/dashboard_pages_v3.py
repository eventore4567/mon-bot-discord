"""Entrée de compatibilité du dashboard SentriX V56.

Le dashboard a longtemps été réécrit par plusieurs générations de couches visuelles
(Oxyde, V5, fiabilité, clarté, compact puis hotfixes). Ces transformations dépendaient de
fragments HTML exacts et rendaient ``/app`` difficile à stabiliser.

V56 conserve le backend/API existant mais publie une seule base frontend. Les outils qui ont
réellement besoin d'UI (notamment Embeds) sont intégrés une seule fois ici, avec des points
d'insertion génériques et testés. Le snapshot V55 fige ensuite ce document avant le bind HTTP.
"""

from .dashboard_oxyde_hotfix import patch_dashboard_runtime
from .dashboard_frontend_freeze_v55 import install_product_prestart_hook
from . import embed_dashboard as _embed_dashboard


# Correction backend uniquement : une table secondaire absente ne doit jamais vider /app.
patch_dashboard_runtime()
# Fige le document final après les extensions produit pré-start, avant build_app().
install_product_prestart_hook()


_EMBEDS_V56_JS = r"""
    (() => {
      "use strict";
      tabs.embeds={
        title:"Embeds",
        description:"Créez, prévisualisez et envoyez un message enrichi dans Discord.",
        embeds:true,
        fields:[]
      };

      const navigation=document.getElementById("navigation");
      if(navigation && !navigation.querySelector('[data-tab="embeds"]')){
        const button=document.createElement("button");
        button.type="button";
        button.dataset.tab="embeds";
        button.textContent="Embeds";
        const roles=navigation.querySelector('[data-tab="roles"]');
        navigation.insertBefore(button,roles||null);
      }

      const renderTabV56Base=renderTab;
      renderTab=function(){
        if(state.tab!=="embeds") return renderTabV56Base();
        if(!state.guildData) return;
        const tab=tabs.embeds;
        document.body.dataset.tab="embeds";
        $("tabTitle").textContent=tab.title;
        $("tabDescription").textContent=tab.description;
        document.querySelectorAll("#navigation button[data-tab]").forEach(
          button=>button.classList.toggle("active",button.dataset.tab==="embeds")
        );
        renderEmbeds();
        $("saveBar").classList.remove("hidden");
        $("saveButton").textContent="Envoyer l'embed";
        $("saveStatus").textContent="Aperçu en direct";
      };

      const saveV56Base=save;
      save=async function(event){
        if(state.tab!=="embeds") return saveV56Base(event);
        event.preventDefault();
        if(!state.guildId||!state.guildData) return;
        await sendEmbed();
      };
    })();
"""


def _noop_embed_html_patch(html: str) -> str:
    """Le backend Embeds reste installé, mais son ancien patch HTML n'est plus nécessaire."""
    return html


def apply_dashboard_pages(html: str) -> str:
    """Construit le frontend canonique V56 sans réappliquer les anciennes générations UI."""
    if "/* sentrix-v56-embeds */" in html:
        return html

    boot_marker = "    Promise.all([loadPublic(),loadSession()])"
    style_marker = "  </style>"
    if boot_marker not in html or style_marker not in html:
        # Échec fermé : mieux vaut conserver le dashboard canonique que servir un document
        # partiellement réécrit. V55 vérifiera encore la chaîne session/guilds avant de figer.
        return html

    html = html.replace(
        style_marker,
        "    /* sentrix-v56-embeds */\n" + _embed_dashboard.EMBED_CSS + "\n" + style_marker,
        1,
    )
    html = html.replace(
        boot_marker,
        _embed_dashboard.EMBED_JS + "\n" + _EMBEDS_V56_JS + "\n" + boot_marker,
        1,
    )

    # L'extension historique continue d'installer sa route POST et ses headers de sécurité,
    # mais elle ne doit plus tenter de réécrire une seconde fois le document V56.
    _embed_dashboard._patch_html = _noop_embed_html_patch
    return html


__all__ = ["apply_dashboard_pages"]
