/* ---------- Musique : lecteur, file et playlists ----------
   Ce panneau contrôle le même Cog Music que /music dans Discord. */
const musicData = (force = false) => cached('music', () => gget('/music'), { force, ttl: 2500 });

function musicTime(value) {
  const sec = Math.max(0, Number(value || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}
function musicTrackName(track) {
  if (!track) return '—';
  return track.artist && !String(track.title || '').toLocaleLowerCase('fr').includes(String(track.artist).toLocaleLowerCase('fr'))
    ? `${track.artist} — ${track.title}` : (track.title || 'Titre inconnu');
}
function musicVoiceOptions(data) {
  const current = String(data.voice_channel_id || '');
  const rows = data.voice_channels || [];
  return '<option value="">Choisir un salon vocal</option>' + rows.map(ch => {
    const disabled = !ch.can_connect || !ch.can_speak;
    const suffix = ch.category ? ` — ${ch.category}` : '';
    const members = Number(ch.members || 0) ? ` · ${ch.members} membre(s)` : '';
    return `<option value="${esc(ch.id)}" ${String(ch.id) === current ? 'selected' : ''} ${disabled ? 'disabled' : ''}>🔊 ${esc(ch.name)}${esc(suffix + members)}${disabled ? ' — permissions manquantes' : ''}</option>`;
  }).join('');
}
async function musicRequest(path, body = {}, method = 'POST') {
  try {
    const result = await api(guildUrl(path), { method, body: JSON.stringify(body) });
    toast(result.message || 'Action musique appliquée.');
    invalidate('music');
    await renderMusic();
    return result;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}
function musicSelectedVoice(data) {
  return $('musicVoice')?.value || data.voice_channel_id || '';
}

async function renderMusicPlayer(data) {
  const current = data.current;
  const voiceLabel = data.connected ? `Connecté à ${data.voice_channel_name}` : 'Déconnecté';
  const currentBody = current ? `
    <div class="row" style="align-items:flex-start">
      ${current.thumbnail ? `<img src="${esc(current.thumbnail)}" alt="" style="width:76px;height:76px;border-radius:12px;object-fit:cover">` : ''}
      <div class="row-main"><b>${esc(musicTrackName(current))}</b>
        <small>${esc(current.playback_provider || current.provider || 'source inconnue')} · ${musicTime(current.position_seconds)}${current.duration ? ` / ${musicTime(current.duration)}` : ''}</small>
        ${current.original_url ? `<a class="btn link sm" href="${esc(current.original_url)}" target="_blank" rel="noopener">Ouvrir la source</a>` : ''}
      </div>
    </div>` : emptyState('Aucune musique en cours', 'Choisissez un vocal puis recherchez un titre, un artiste ou collez un lien.');

  content().innerHTML = `<div class="grid">
    ${card('Connexion vocale', 'Choisissez exactement le salon que SentriX doit rejoindre.', `
      <div class="fields">
        <div class="field full"><label for="musicVoice">Salon vocal</label><select id="musicVoice">${musicVoiceOptions(data)}</select>
          <small>${esc(voiceLabel)}. Le dashboard peut déplacer SentriX vers un autre vocal.</small>
        </div>
      </div>
      <div class="toolbar">
        <button class="btn primary" type="button" id="musicConnect">Rejoindre / déplacer</button>
        <button class="btn danger" type="button" id="musicLeave" ${data.connected ? '' : 'disabled'}>Quitter le vocal</button>
      </div>`, 'full')}

    ${card('Lancer une musique', 'YouTube, YouTube Music, Spotify, Deezer, SoundCloud, lien audio ou simple recherche.', `
      <div class="fields"><div class="field full"><label for="musicQuery">Titre, artiste ou lien</label>
        <input id="musicQuery" type="text" maxlength="1000" placeholder="Ex. Faded Alan Walker ou https://…">
      </div></div>
      <div class="toolbar"><button class="btn primary" type="button" id="musicPlay">Lire / ajouter à la file</button></div>`, 'full')}

    ${card('En lecture', '', currentBody, 'full')}

    <section class="card full">
      <div class="kpis">
        ${kpi('État', data.paused ? 'En pause' : data.playing ? 'Lecture' : data.connected ? 'Prêt' : 'Hors vocal')}
        ${kpi('Volume', `${data.volume}%`)}
        ${kpi('File', `${data.queue_total || 0} titre(s)`)}
        ${kpi('Boucle', data.loop === 'track' ? 'Piste' : data.loop === 'queue' ? 'File' : 'Off')}
      </div>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn" type="button" data-music-control="previous">Précédent</button>
        <button class="btn" type="button" data-music-control="${data.paused ? 'resume' : 'pause'}">${data.paused ? 'Reprendre' : 'Pause'}</button>
        <button class="btn" type="button" data-music-control="skip">Suivant</button>
        <button class="btn danger" type="button" data-music-control="stop">Stop</button>
      </div>
      <div class="fields" style="margin-top:14px">
        <div class="field"><label for="musicVolume">Volume</label><input id="musicVolume" type="range" min="0" max="100" value="${Number(data.volume || 0)}"><small id="musicVolumeValue">${Number(data.volume || 0)}%</small></div>
        <div class="field"><label for="musicLoop">Répétition</label><select id="musicLoop"><option value="off" ${data.loop === 'off' ? 'selected' : ''}>Désactivée</option><option value="track" ${data.loop === 'track' ? 'selected' : ''}>Piste actuelle</option><option value="queue" ${data.loop === 'queue' ? 'selected' : ''}>Toute la file</option></select></div>
        <label class="switch-row"><span class="switch-copy"><b>Autoplay</b><span>Continue avec des titres proches quand la file se termine.</span></span><input id="musicAutoplay" class="switch" type="checkbox" ${data.autoplay ? 'checked' : ''}></label>
        <div class="field"><label for="musicSeek">Aller à (secondes)</label><input id="musicSeek" type="number" min="0" max="${Number(current?.duration || 36000)}" value="${Number(current?.position_seconds || 0)}"></div>
      </div>
      <div class="toolbar"><button class="btn" type="button" id="musicSeekApply" ${current ? '' : 'disabled'}>Déplacer la lecture</button></div>
    </section>
  </div>`;

  $('musicConnect').onclick = () => {
    const channelId = $('musicVoice').value;
    if (!channelId) return toast('Choisissez un salon vocal.', true);
    musicRequest('/music/connect', { channel_id: channelId });
  };
  $('musicLeave').onclick = () => musicRequest('/music/control', { action: 'leave' });
  $('musicPlay').onclick = () => {
    const query = $('musicQuery').value.trim();
    if (!query) return toast('Entrez un titre, un artiste ou un lien.', true);
    musicRequest('/music/play', { query, channel_id: musicSelectedVoice(data) });
  };
  $('musicQuery').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); $('musicPlay').click(); } };
  content().querySelectorAll('[data-music-control]').forEach(btn => btn.onclick = () => musicRequest('/music/control', { action: btn.dataset.musicControl }));
  $('musicVolume').oninput = () => $('musicVolumeValue').textContent = `${$('musicVolume').value}%`;
  $('musicVolume').onchange = () => musicRequest('/music/control', { action: 'volume', value: Number($('musicVolume').value) });
  $('musicLoop').onchange = () => musicRequest('/music/control', { action: 'loop', value: $('musicLoop').value });
  $('musicAutoplay').onchange = () => musicRequest('/music/control', { action: 'autoplay', value: $('musicAutoplay').checked });
  $('musicSeekApply').onclick = () => musicRequest('/music/control', { action: 'seek', value: Number($('musicSeek').value || 0) });
}

async function renderMusicQueue(data) {
  const queue = data.queue || [];
  content().innerHTML = `<div class="grid">
    ${card('File d’attente', `${data.queue_total || 0} titre(s) en attente. Le titre en cours n’est pas compté ici.`, `
      <div class="toolbar"><button class="btn" id="musicQueueShuffle" type="button" ${queue.length < 2 ? 'disabled' : ''}>Mélanger</button><button class="btn danger" id="musicQueueClear" type="button" ${queue.length ? '' : 'disabled'}>Vider la file</button></div>
      <div class="list" style="margin-top:12px">
        ${queue.length ? queue.map(track => `<div class="row"><div class="row-main"><b>${track.position}. ${esc(musicTrackName(track))}</b><small>${track.duration ? musicTime(track.duration) + ' · ' : ''}${esc(track.playback_provider || track.provider || '')}</small></div><button class="btn sm danger" type="button" data-music-remove="${track.position}">Retirer</button></div>`).join('') : emptyState('File vide', 'Ajoutez une musique depuis l’onglet Lecteur ou lancez une playlist.')}
        ${data.queue_truncated ? `<div class="notice">${data.queue_truncated} autre(s) titre(s) non affiché(s).</div>` : ''}
      </div>`, 'full')}
  </div>`;
  $('musicQueueShuffle').onclick = () => musicRequest('/music/control', { action: 'shuffle' });
  $('musicQueueClear').onclick = async () => {
    if (await confirmDialog({ title: 'Vider la file', body: 'Le titre actuellement en lecture continuera, mais tous les titres en attente seront retirés.', confirm: 'Vider', danger: true })) {
      musicRequest('/music/control', { action: 'clear' });
    }
  };
  content().querySelectorAll('[data-music-remove]').forEach(btn => btn.onclick = () => musicRequest('/music/control', { action: 'remove', position: Number(btn.dataset.musicRemove) }));
}

function musicPlaylistCard(pl, data) {
  return `<div class="row" style="align-items:flex-start"><div class="row-main"><b>${esc(pl.name)}</b><small>${pl.count} titre(s) · mise à jour ${esc(when(pl.updated_at))}</small>
    <div class="toolbar" style="margin-top:8px">
      <button class="btn sm primary" type="button" data-pl-play="${esc(pl.name)}">Lire</button>
      <button class="btn sm" type="button" data-pl-add="${esc(pl.name)}">Ajouter des titres</button>
      <button class="btn sm" type="button" data-pl-show="${esc(pl.key)}">Voir</button>
      <button class="btn sm danger" type="button" data-pl-delete="${esc(pl.name)}">Supprimer</button>
    </div></div></div>`;
}
async function renderMusicPlaylists(data) {
  const playlists = data.playlists || [];
  content().innerHTML = `<div class="grid">
    ${card('Créer une playlist', 'Les playlists sont personnelles à votre compte Discord sur ce serveur et restent enregistrées après un redémarrage.', `
      <div class="fields"><div class="field full"><label for="musicPlaylistName">Nom</label><input id="musicPlaylistName" maxlength="40" placeholder="Ex. Chill, Gaming, Soirée"></div></div>
      <div class="toolbar"><button class="btn primary" id="musicPlaylistCreate" type="button">Créer</button></div>`, 'full')}
    ${card('Mes playlists', `${playlists.length} playlist(s).`, `<div class="list">${playlists.length ? playlists.map(pl => musicPlaylistCard(pl, data)).join('') : emptyState('Aucune playlist', 'Créez votre première playlist puis ajoutez-y des titres ou des liens de playlists.')}</div>`, 'full')}
  </div>`;

  $('musicPlaylistCreate').onclick = () => {
    const name = $('musicPlaylistName').value.trim();
    if (!name) return toast('Entrez un nom de playlist.', true);
    musicRequest('/music/playlists/create', { name });
  };
  content().querySelectorAll('[data-pl-play]').forEach(btn => btn.onclick = () => musicRequest('/music/playlists/play', { name: btn.dataset.plPlay, channel_id: data.voice_channel_id || '' }));
  content().querySelectorAll('[data-pl-add]').forEach(btn => btn.onclick = async () => {
    const query = await promptDialog({ title: `Ajouter à ${btn.dataset.plAdd}`, label: 'Titre, artiste ou lien de playlist', placeholder: 'https://… ou nom du titre', confirm: 'Ajouter' });
    if (query?.trim()) await musicRequest('/music/playlists/add', { name: btn.dataset.plAdd, query: query.trim() });
  });
  content().querySelectorAll('[data-pl-show]').forEach(btn => btn.onclick = () => {
    const pl = playlists.find(x => String(x.key) === String(btn.dataset.plShow));
    if (!pl) return;
    const tracks = pl.tracks || [];
    openModal({
      title: pl.name,
      body: tracks.length ? `<div class="list">${tracks.map(t => `<div class="row"><div class="row-main"><b>${t.position}. ${esc(t.artist ? t.artist + ' — ' + t.title : t.title)}</b><small>${t.duration ? musicTime(t.duration) : 'Durée inconnue'}</small></div></div>`).join('')}${pl.truncated ? `<div class="notice">${pl.truncated} titre(s) supplémentaire(s) non affiché(s).</div>` : ''}</div>` : '<div class="empty">Cette playlist est vide.</div>',
      actions: [{ label: 'Fermer' }],
    });
  });
  content().querySelectorAll('[data-pl-delete]').forEach(btn => btn.onclick = async () => {
    if (!(await confirmDialog({ title: 'Supprimer la playlist', body: `Supprimer définitivement « ${btn.dataset.plDelete} » ?`, confirm: 'Supprimer', danger: true }))) return;
    await musicRequest('/music/playlists', { name: btn.dataset.plDelete }, 'DELETE');
  });
}

async function renderMusic() {
  let data;
  try { data = await musicData(); } catch (e) { return errorView(e); }
  if (!['player', 'queue', 'playlists'].includes(state.sub)) state.sub = 'player';
  if (state.sub === 'queue') return renderMusicQueue(data);
  if (state.sub === 'playlists') return renderMusicPlaylists(data);
  return renderMusicPlayer(data);
}
