/* The Me hub's Today card - drawn by attendance-core.js's renderToday, the same card Your attendance shows
   before you check in. This just loads today's state and redraws after a check-in or check-out. */
(() => {
  'use strict';

  const box = document.getElementById('me-today');
  if (box) {
    const { h, clear, api } = window.LD;
    (async function load() {
      try {
        window.ATT.renderToday(box, await api('/api/attendance/state'), { onChange: load });
      } catch (err) {
        clear(box).append(h('p', { class: 'me-today-status' }, err.message));
      }
    })();
  }
})();

/* The avatar button in the top bar: a small menu anchored under it (View profile / Sign out), not a
   full-screen picker - there are only two options, and this reads at a glance as "the account menu"
   instead of looking like a list of equal choices to pick from. View profile shows the read-only
   name/userid/designation and the one thing a person can change about themselves here - their own phone
   number, so it's on hand for teammates without an admin having to set it up front. */
(() => {
  'use strict';

  const btn = document.getElementById('profile-btn');
  if (!btn) return;
  const { h, api, toast, closeOnBack, field, showFieldErrors } = window.LD;
  const menu = document.getElementById('profile-menu');

  async function openProfile() {
    let me;
    try {
      me = await api('/api/me');
    } catch (err) {
      toast(err.message, true);
      return;
    }

    const phoneInput = h('input', { type: 'tel', autocomplete: 'tel', value: me.phone || '' });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save');
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const row = (label, value) => h('p', { class: 'profile-row' }, h('span', {}, label), h('span', {}, value || '—'));
    const form = h('form', { class: 'confirm-card profile-card', 'aria-label': 'Profile' },
      h('h2', {}, 'Profile'),
      row('Name', me.name),
      row('User ID', me.userid),
      row('Designation', me.designation),
      field('phone', 'Phone', phoneInput),
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn));
    const overlay = h('div', { class: 'confirm-overlay', onclick: (e) => { if (e.target === overlay) overlay.remove(); } }, form);

    cancelBtn.addEventListener('click', () => overlay.remove());
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      try {
        const updated = await api('/api/me', { method: 'PATCH', body: { phone: phoneInput.value.trim() } });
        phoneInput.value = updated.phone;
        toast('Profile updated');
        overlay.remove();
      } catch (err) {
        showFieldErrors(form, err.fields);
        toast(err.message, true);
      } finally {
        saveBtn.disabled = false;
      }
    });

    document.body.append(overlay);
    phoneInput.focus();
  }

  // position:fixed (not CSS-anchored absolute), computed fresh on each open, so the menu is never clipped
  // by an ancestor's overflow:hidden and follows the button if the layout shifted since last time.
  let finishMenu = null;
  function openMenu() {
    const rect = btn.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 8}px`;
    menu.style.right = `${window.innerWidth - rect.right}px`;
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    finishMenu = closeOnBack(() => {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    });
  }
  function closeMenu() {
    if (menu.hidden || !finishMenu) return;
    finishMenu();
    finishMenu = null;
  }

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.hidden) openMenu(); else closeMenu();
  });
  btn.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMenu(); }
  });
  document.getElementById('profile-menu-view-btn').addEventListener('click', () => { closeMenu(); openProfile(); });
  document.getElementById('profile-menu-signout-btn').addEventListener('click', () => {
    closeMenu();
    document.getElementById('signout-form').requestSubmit();
  });
  document.addEventListener('click', (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) closeMenu();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });
})();

/* Admin only: site categories people typed in that aren't on the list yet. Each waits here until the
   admin approves it (it joins the list) or points it at an existing category (every survey and client
   using the typed name moves over). Hidden when nothing is waiting. */
(() => {
  'use strict';

  const section = document.getElementById('me-approvals');
  if (!section) return;
  const list = document.getElementById('me-approvals-list');
  const { h, clear, api, toast, selectField } = window.LD;

  async function load() {
    let data;
    try {
      data = await api('/api/site-categories/requests');
    } catch (err) {
      section.hidden = true;
      return;
    }
    section.hidden = data.requests.length === 0;
    clear(list);
    data.requests.forEach((r) => list.append(requestRow(r, data.categories)));
  }

  function requestRow(r, categories) {
    const target = selectField(
      categories.map((c) => ({ value: c, label: c })),
      categories[0] || '', { title: `Point "${r.name}" at`, placeholder: 'Choose a category' });
    target.setAttribute('aria-label', `Existing category for ${r.name}`);

    const act = async (path, body) => {
      try {
        await api(`/api/site-categories/requests/${r.id}/${path}`, { method: 'POST', body });
        toast(path === 'approve' ? `"${r.name}" added to the list` : `"${r.name}" pointed at ${body.target}`);
        load();
      } catch (err) {
        toast(err.message, true);
      }
    };

    const uses = r.uses ? `used on ${r.uses} ${r.uses === 1 ? 'record' : 'records'}` : 'not used yet';
    return h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, r.name),
        h('span', { class: 'hint' }, `Typed by ${r.requested_by || 'someone'} · ${uses}`)),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act('approve', {}) }, 'Approve'),
        target,
        h('button', { class: 'btn small', type: 'button', onclick: () => {
          if (!target.value) { toast('Choose a category first', true); return; }
          act('redirect', { target: target.value });
        } }, 'Redirect')));
  }

  load();
})();
