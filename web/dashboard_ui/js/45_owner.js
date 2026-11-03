/* ---------- Serveurs du bot (propriétaire uniquement) ----------
   03/11/2026 : la page /owner-servers existait mais son lien était effacé à la
   restauration de la page principale. Elle vit maintenant DANS le dashboard :
   tous les serveurs où SentriX est, « Rejoindre » (invitation 1 h, 1 utilisation)
   et « Retirer SentriX ». Visible seulement si /api/me.developer est vrai ; le
   serveur revérifie de toute façon (web/owner_server_manager.py). */
async function renderBotServers() {
  if (!state.developer) {
    content().innerHTML = emptyState('Page réservée', 'Seul le propriétaire de SentriX voit cette page.');
    return;
  }
  let data;
  try { data = await api('/api/owner/guilds'); }
  catch (e) { content().innerHTML = notice(`Serveurs indisponibles : ${e.message}`, 'warn'); return; }
  let guilds = data.guilds || [];
  const members = () => guilds.reduce((n, g) => n + Number(g.members || 0), 0);
  content().innerHTML = `<div class="grid">
    <section class="card full"><div class="card-head"><div><h2>Serveurs du bot</h2><p>Tous les serveurs où SentriX est présent.</p></div><span class="badge blue" id="botServersCount"></span></div>
    <div class="toolbar"><input class="search-input" id="botServersSearch" type="search" placeholder="Rechercher par nom ou ID…"></div>
    <div class="list" id="botServersList"></div></section></div>`;
  const row = g => {
    const icon = g.icon_url ? `<img src="${esc(g.icon_url)}" alt="" width="36" height="36" style="border-radius:10px;flex:none">` : `<span class="badge" style="width:36px;height:36px;display:grid;place-items:center;flex:none">${esc(String(g.name || '?').slice(0, 2).toUpperCase())}</span>`;
    const join = g.joined
      ? `<a class="btn sm" href="https://discord.com/channels/${esc(g.id)}" target="_blank" rel="noopener">Ouvrir</a>`
      : `<button class="btn sm primary" type="button" data-bot-join="${esc(g.id)}">Rejoindre</button>`;
    return `<div class="row"><div style="display:flex;gap:12px;align-items:center;min-width:0">${icon}<div class="row-main"><b>${esc(g.name)}</b><small>${number(g.members)} membres · propriétaire ${esc(g.owner)} · ${esc(g.id)}</small></div></div>
      <div class="toolbar" style="margin:0;flex-wrap:nowrap">${join}<button class="btn sm danger" type="button" data-bot-leave="${esc(g.id)}" data-name="${esc(g.name)}">Retirer SentriX</button></div></div>`;
  };
  const draw = () => {
    const q = ($('botServersSearch').value || '').trim().toLowerCase();
    const shown = q ? guilds.filter(g => String(g.name).toLowerCase().includes(q) || String(g.id).includes(q)) : guilds;
    $('botServersCount').textContent = `${number(guilds.length)} serveurs · ${number(members())} membres`;
    $('botServersList').innerHTML = shown.length ? shown.map(row).join('') : emptyState('Aucun serveur', q ? 'Aucun serveur ne correspond.' : 'SentriX n’est sur aucun serveur.');
    $('botServersList').querySelectorAll('[data-bot-join]').forEach(b => b.onclick = async () => {
      // Onglet ouvert AVANT l'appel : un onglet ouvert après un await est bloqué par le navigateur.
      const tab = window.open('', '_blank');
      b.disabled = true;
      try {
        const d = await api(`/api/owner/guilds/${encodeURIComponent(b.dataset.botJoin)}/invite`, { method: 'POST' });
        if (tab) tab.location = d.url; else location.href = d.url;
        toast(d.message || 'Invitation ouverte.');
      } catch (e) { if (tab) tab.close(); toast(e.message, true); }
      b.disabled = false;
    });
    $('botServersList').querySelectorAll('[data-bot-leave]').forEach(b => b.onclick = async () => {
      const name = b.dataset.name;
      if (!(await confirmDialog({ title: `Retirer SentriX de « ${name} » ?`, body: 'Le bot quitte ce serveur immédiatement. Il faudra le réinviter pour revenir.', confirm: 'Retirer', danger: true }))) return;
      b.disabled = true;
      try {
        const d = await api(`/api/owner/guilds/${encodeURIComponent(b.dataset.botLeave)}/leave`, { method: 'POST' });
        guilds = guilds.filter(g => g.id !== b.dataset.botLeave);
        toast(d.message || 'SentriX a quitté ce serveur.');
        draw();
      } catch (e) { b.disabled = false; toast(e.message, true); }
    });
  };
  $('botServersSearch').oninput = draw;
  draw();
}
