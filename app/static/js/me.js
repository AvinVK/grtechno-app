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

/* Stock-ins waiting specifically on the signed-in person - an accountant, an office assistant, or the admin
   (kohal, 2026-10-16: "i want to see the requests in me tab"). Issue requests moved to their own Material
   requests tab inside Inventory (kohal, 2026-10-17) - this section only ever sees a stock-in now (see
   app/me.py's material_approvals, which drops issue-type rows entirely). Not gated on module access, same
   as the approve route itself isn't. Hidden when nothing's waiting. */
(() => {
  'use strict';

  const section = document.getElementById('me-material-approvals');
  if (!section) return;
  const list = document.getElementById('me-material-approvals-list');
  const { h, clear, api, toast, confirm } = window.LD;

  async function load() {
    let data;
    try {
      data = await api('/api/me/material-approvals');
    } catch (err) {
      section.hidden = true;
      return;
    }
    section.hidden = data.approvals.length === 0;
    clear(list);
    data.approvals.forEach((r) => list.append(approvalRow(r)));
  }

  async function act(r, action) {
    if (action === 'reject') {
      const sure = await confirm("Reject this request? It never drew down stock, so there's nothing to undo.", { ok: 'Reject', danger: true, title: 'Reject request' });
      if (!sure) return;
    }
    try {
      await api(`/api/inventory/materials/${r.material_id}/movements/${r.id}/${action}`, { method: 'POST' });
      toast(action === 'approve' ? 'Approved' : 'Rejected');
      load();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function approvalRow(r) {
    return h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.material_code} · ${r.material_name}`),
        h('span', { class: 'hint' }, `Stock in ${r.quantity} ${r.unit || ''}`.trim()),
        h('span', { class: 'hint' }, [r.requested_by ? `Requested by ${r.requested_by}` : null, r.note || null].filter(Boolean).join(' · '))),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject')));
  }

  load();
})();

/* Attendance waiting specifically on the signed-in person - same approvers as the material section above
   (kohal, 2026-10-16: "Attendance should be approved by project manager or site supervisor who is checked
   in on tha project"), see auth.can_approve_attendance. Hidden when nothing's waiting. */
(() => {
  'use strict';

  const section = document.getElementById('me-attendance-approvals');
  if (!section) return;
  const list = document.getElementById('me-attendance-approvals-list');
  const { h, clear, api, toast, confirm } = window.LD;

  function fmtTime(iso) {
    return iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : '';
  }

  async function load() {
    let data;
    try {
      data = await api('/api/attendance/approvals');
    } catch (err) {
      section.hidden = true;
      return;
    }
    section.hidden = data.approvals.length === 0;
    clear(list);
    data.approvals.forEach((r) => list.append(approvalRow(r)));
  }

  async function act(r, action) {
    if (action === 'reject') {
      const sure = await confirm('Reject this attendance record? This cannot be undone.', { ok: 'Reject', danger: true, title: 'Reject record' });
      if (!sure) return;
    }
    try {
      await api(`/api/attendance/${r.id}/${action}`, { method: 'POST' });
      toast(action === 'approve' ? 'Approved' : 'Rejected');
      load();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function approvalRow(r) {
    const times = r.check_out_at ? `${fmtTime(r.check_in_at)} – ${fmtTime(r.check_out_at)}` : `${fmtTime(r.check_in_at)} – still checked in`;
    return h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, r.user_name),
        h('span', { class: 'hint' }, [r.work_label, times].filter(Boolean).join(' · ')),
        r.notes ? h('span', { class: 'hint' }, r.notes) : null),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject')));
  }

  load();
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

/* Fooding (kohal, 2026-10-18): every daily-wage employee, what's been allotted to them and what's left -
   for the admin or accountant to top up or pause. Empty for anyone else (see app/fooding.py's
   can_manage_fooding), same "hidden until there's something to show" shape as the approval sections above,
   though this one is never really empty for an eligible manager - it lists every daily-wage worker, not
   just ones waiting on something. */
(() => {
  'use strict';

  const section = document.getElementById('me-fooding');
  if (!section) return;
  const list = document.getElementById('me-fooding-list');
  const { h, clear, api, toast, confirm, money, field, closeOnBack } = window.LD;

  async function load() {
    let data;
    try {
      data = await api('/api/fooding');
    } catch (err) {
      section.hidden = true;
      return;
    }
    section.hidden = data.workers.length === 0;
    clear(list);
    data.workers.forEach((w) => list.append(row(w, data.daily_amount, data.currency)));
  }

  function row(w, dailyAmount, cur) {
    const sub = w.is_paused
      ? 'Paused'
      : `${money(w.allotted_total, cur)} allotted · ${money(dailyAmount, cur)}/day`;
    return h('button', {
      type: 'button', class: `card me-row approval-row fooding-row${w.is_paused ? ' is-paused' : ''}`,
      onclick: () => openSheet(w, dailyAmount, cur),
    },
      h('div', { class: 'approval-main' },
        h('strong', {}, w.worker_name),
        h('span', { class: 'hint' }, sub)),
      h('span', { class: 'fn-stat-value' }, money(w.remaining, cur)));
  }

  function openSheet(w, dailyAmount, cur) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'number', min: '1', step: 'any', inputmode: 'decimal', placeholder: 'Amount to add' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Close');
    const allotBtn = h('button', { class: 'btn primary', type: 'button' }, 'Add');
    const pauseBtn = h('button', {
      class: 'btn small', type: 'button',
    }, w.is_paused ? 'Resume' : 'Pause');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    allotBtn.onclick = async () => {
      allotBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api(`/api/fooding/${w.worker_id}/allot`, { method: 'POST', body: { amount: amountInput.value } });
        finish();
        toast('Added to fooding balance');
        await load();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        allotBtn.disabled = false;
      }
    };
    pauseBtn.onclick = async () => {
      pauseBtn.disabled = true;
      try {
        await api(`/api/fooding/${w.worker_id}/${w.is_paused ? 'resume' : 'pause'}`, { method: 'POST' });
        finish();
        toast(w.is_paused ? 'Fooding resumed' : 'Fooding paused');
        await load();
      } catch (err) {
        toast(err.message, true);
        pauseBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, w.worker_name),
      h('p', { class: 'hint' },
        `${money(w.allotted_total, cur)} allotted so far · ${money(w.remaining, cur)} remaining · ${money(dailyAmount, cur)}/day`,
        w.is_paused ? ' · Paused' : ''),
      field('amount', 'Add to balance', amountInput),
      errEl,
      h('div', { class: 'confirm-actions' }, pauseBtn, cancelBtn, allotBtn)));
    document.body.append(overlay);
    amountInput.focus();
  }

  load();
})();
