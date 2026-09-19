/* ---------- Profil SentriX éditable ----------
   Les champs ci-dessous écrivent dans la table profiles, la même que +profile. */
const _renderProfileBase = renderProfile;
const sentrixProfileData = (force = false) => cached('sentrix-profile-me', () => gget('/profile/me'), { force });

renderProfile = async function renderEditableProfile() {
  _renderProfileBase();
  if (!state.guild || !state.guildId) return;

  let d;
  try { d = await sentrixProfileData(); } catch (e) {
    const grid = content().querySelector('.grid');
    if (grid) grid.insertAdjacentHTML('afterbegin', `<section class="card full"><div class="notice bad">${esc(e.message || 'Profil SentriX indisponible.')}</div></section>`);
    return;
  }
  const p = d.profile || {}, s = d.stats || {}, m = d.member || {};
  const grid = content().querySelector('.grid');
  if (!grid) return;

  const section = document.createElement('section');
  section.className = 'card full';
  section.id = 'sentrixCommunityProfile';
  section.innerHTML = `<div class="card-head">
    <div>
      <h2>Profil SentriX sur ${esc(state.guild.guild?.name || 'ce serveur')}</h2>
      <p>Ces informations apparaissent dans votre profil communautaire SentriX.</p>
    </div>
    <span class="badge blue">${esc(String((d.badges || []).length))} badge${(d.badges || []).length === 1 ? '' : 's'}</span>
  </div>
  <div class="profile-line" style="margin-top:14px">
    <span class="avatar big">${m.avatar_url ? `<img src="${esc(m.avatar_url)}" alt="">` : esc((m.display_name || m.username || '?').slice(0,2).toUpperCase())}</span>
    <div><h3>${esc(m.display_name || m.username || 'Profil')}</h3><p>@${esc(m.username || '')}</p></div>
  </div>
  <div class="kpis" style="margin-top:14px">
    <div class="kpi"><small>Niveau</small><b>${number(s.level || 0)}</b></div>
    <div class="kpi"><small>Messages</small><b>${number(s.messages || 0)}</b></div>
    <div class="kpi"><small>Réputation</small><b>${number(p.reputation || 0)}</b></div>
    <div class="kpi"><small>Série</small><b>${number(s.daily_streak || 0)} j</b></div>
  </div>
  ${(d.badges || []).length ? `<div class="chips" style="margin-top:12px">${d.badges.map(x => `<span class="chip on">${esc(x)}</span>`).join('')}</div>` : ''}
  <div class="fields" style="margin-top:16px">
    <div class="field full">
      <label for="profileBio">Bio</label>
      <textarea id="profileBio" maxlength="500" rows="4" placeholder="Présentez-vous en quelques lignes…">${esc(p.bio || '')}</textarea>
      <small>500 caractères maximum.</small>
    </div>
    <div class="field">
      <label for="profileBirthday">Anniversaire</label>
      <input id="profileBirthday" value="${esc(p.birthday || '')}" placeholder="JJ/MM ou AAAA-MM-JJ">
    </div>
    <div class="field">
      <label for="profileBackground">Fond de carte</label>
      <input id="profileBackground" type="url" value="${esc(p.background || '')}" placeholder="https://…">
      <small>Facultatif · URL HTTPS.</small>
    </div>
  </div>
  <div class="toolbar" style="margin-top:14px">
    <button class="btn primary" type="button" id="profileSentrixSave">Enregistrer le profil</button>
    <button class="btn ghost" type="button" id="profileSentrixRefresh">Actualiser</button>
  </div>
  <div style="margin-top:16px">
    <h3>Aperçu</h3>
    <div id="profileSentrixPreview" style="margin-top:8px"></div>
  </div>`;

  grid.insertBefore(section, grid.children[1] || null);

  const paint = () => {
    const bio = $('profileBio').value.trim() || 'Aucune bio définie pour le moment.';
    $('profileSentrixPreview').innerHTML = discordMessage({
      embed: {
        title: `Profil de ${m.display_name || m.username || 'membre'}`,
        description: bio,
        image: $('profileBackground').value.trim(),
        fields: [
          ['Niveau', String(s.level || 0), true],
          ['Messages', number(s.messages || 0), true],
          ['Réputation', number(p.reputation || 0), true],
          ['Anniversaire', $('profileBirthday').value.trim() || 'Non défini', true],
        ],
      },
    });
  };
  ['profileBio','profileBirthday','profileBackground'].forEach(id => $(id).addEventListener('input', paint));
  paint();

  $('profileSentrixSave').onclick = async () => {
    const button = $('profileSentrixSave');
    button.disabled = true;
    try {
      const r = await gpost('/profile/me', {
        bio: $('profileBio').value,
        birthday: $('profileBirthday').value,
        background: $('profileBackground').value,
      }, 'PUT');
      invalidate('sentrix-profile-me');
      toast(r.message || 'Profil enregistré.');
      await renderProfile();
    } catch (e) { toast(e.message, true); }
    finally { button.disabled = false; }
  };
  $('profileSentrixRefresh').onclick = async () => {
    invalidate('sentrix-profile-me');
    await renderProfile();
  };
};
