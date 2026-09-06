"""Compatibilité JavaScript minimale requise par l'éditeur Tickets V62.

Le frontend canonique expose channelOptions()/roleOptions(), mais pas categoryOptions().
V62 utilise ce sélecteur pour choisir la catégorie où créer les tickets. On le définit
AVANT l'injection de V62 afin que l'éditeur soit exécutable dans le navigateur final.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v62-compat")

SCRIPT = r'''
<script id="sentrix-v62-compat">
function categoryOptions(current=''){
  const channels=(state.guildData?.channels||[]).filter(channel=>channel.type==='category');
  return '<option value="">Non configuré</option>'+channels.map(channel=>`<option value="${esc(channel.id)}" ${String(current)===String(channel.id)?'selected':''}>${esc(channel.name)}</option>`).join('');
}
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v62-compat"' in html:
        return True
    if 'id="sentrix-v61-unified"' not in html or "</body>" not in html:
        logger.error("Compat V62 refusée : V61 ou </body> absent.")
        return False
    dashboard.INDEX_HTML = html.replace("</body>", SCRIPT + "\n</body>", 1)
    logger.info("Compat V62 installée : categoryOptions() disponible avant l'éditeur Tickets.")
    return True


__all__ = ["install"]
