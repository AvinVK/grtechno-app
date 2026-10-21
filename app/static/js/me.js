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

  // Why this one needs a stricter approver than usual (see auth.attendance_restriction) - only shown when
  // it applies, since the common case (on time, one session) has nothing special to say.
  function restrictionNote(r) {
    if (r.restriction === 'late') return 'Checked in late - admin only';
    if (r.restriction === 'multi_project') return 'Different project than an earlier session today - project manager only';
    return null;
  }

  function approvalRow(r) {
    const times = r.check_out_at ? `${fmtTime(r.check_in_at)} – ${fmtTime(r.check_out_at)}` : `${fmtTime(r.check_in_at)} – still checked in`;
    const note = restrictionNote(r);
    return h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, r.user_name),
        h('span', { class: 'hint' }, [r.work_label, times].filter(Boolean).join(' · ')),
        r.notes ? h('span', { class: 'hint' }, r.notes) : null,
        note ? h('span', { class: 'hint att-restriction-note' }, note) : null),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject')));
  }

  load();
})();

/* A daily-wage worker's advance notice that they won't be in on a future day (kohal, 2026-10-19: "Absent
   should be inform 1 day before ... alert should be given to admin and project manager") - the admin or a
   project manager, see auth.PROJECT_MANAGER_ROLE_KEYS and app/attendance.py's _can_see_absences. Not tied
   to a project, so there's no approver narrowing here the way a late check-in or a different-project
   session has. Hidden when nothing's waiting. */
(() => {
  'use strict';

  const section = document.getElementById('me-absence-requests');
  if (!section) return;
  const list = document.getElementById('me-absence-requests-list');
  const { h, clear, api, toast, confirm } = window.LD;

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  async function load() {
    let data;
    try {
      data = await api('/api/attendance/absences');
    } catch (err) {
      section.hidden = true;
      return;
    }
    section.hidden = data.absences.length === 0;
    clear(list);
    data.absences.forEach((r) => list.append(absenceRow(r)));
  }

  async function act(r, action) {
    if (action === 'reject') {
      const sure = await confirm('Reject this absence notice?', { ok: 'Reject', danger: true, title: 'Reject notice' });
      if (!sure) return;
    }
    try {
      await api(`/api/attendance/absences/${r.id}/${action}`, { method: 'POST' });
      toast(action === 'approve' ? 'Noted' : 'Rejected');
      load();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function absenceRow(r) {
    return h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, r.user_name),
        h('span', { class: 'hint' }, fmtDate(r.for_date)),
        r.reason ? h('span', { class: 'hint' }, r.reason) : null),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Acknowledge'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject')));
  }

  load();
})();

/* The signed-in person's own next scheduled piece of work, once approved (kohal, 2026-10-19: "Next day
   work scheduling... alert to each user home screen") - see app/me.py's my_work_assignment. Hidden once
   there's nothing upcoming. */
(() => {
  'use strict';

  const section = document.getElementById('me-work-assignment');
  if (!section) return;
  const card = document.getElementById('me-work-assignment-card');
  const { h, clear, api } = window.LD;

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const target = new Date(y, m - 1, d);
    if (+target === +today) return 'Today';
    if (+target === today.getTime() + 86400000) return 'Tomorrow';
    return target.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  }

  async function load() {
    let data;
    try {
      data = await api('/api/me/work-assignment');
    } catch (err) {
      section.hidden = true;
      return;
    }
    const a = data.assignment;
    section.hidden = !a;
    if (!a) return;
    const where = a.kind === 'field' ? a.project_title : a.location;
    clear(card).append(h('div', { class: 'card approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${fmtDate(a.for_date)} · ${where || ''}`),
        h('span', { class: 'hint' }, a.task),
        a.created_by_name ? h('span', { class: 'hint' }, `Assigned by ${a.created_by_name}`) : null)));
  }

  load();
})();

/* A drafted day's work waiting on the admin specifically to approve (kohal: "This allotment should
   approved by Admin") - see app/workplan.py. Hidden for anyone but the admin (the fetch itself 403s). */
(() => {
  'use strict';

  const section = document.getElementById('me-workplan-approvals');
  if (!section) return;
  const list = document.getElementById('me-workplan-approvals-list');
  const { h, clear, api, toast, confirm } = window.LD;

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  async function load() {
    let data;
    try {
      data = await api('/api/work-assignments/pending');
    } catch (err) {
      section.hidden = true;
      return;
    }
    section.hidden = data.assignments.length === 0;
    clear(list);
    data.assignments.forEach((r) => list.append(row(r)));
  }

  async function act(r, action) {
    if (action === 'reject') {
      const sure = await confirm('Reject this work assignment?', { ok: 'Reject', danger: true, title: 'Reject assignment' });
      if (!sure) return;
    }
    try {
      await api(`/api/work-assignments/${r.id}/${action}`, { method: 'POST' });
      toast(action === 'approve' ? 'Approved' : 'Rejected');
      load();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function row(r) {
    const where = r.kind === 'field' ? r.project_title : r.location;
    return h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, r.worker_name),
        h('span', { class: 'hint' }, [fmtDate(r.for_date), where].filter(Boolean).join(' · ')),
        h('span', { class: 'hint' }, r.task)),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject')));
  }

  load();
})();

/* The signed-in person's own cash-purchase balance and log (kohal, 2026-10-21: "need this in me tab as
   cash purchase block of employees") - hidden entirely until the admin/accountant has given them cash at
   least once (see app/cash_purchases.py's my_cash_purchases). Logging a purchase is a two-step affair,
   same as a material's own stock-in: the entry first (date, what, how much, cost, supplier, note), the
   bill (optional) attached after the fact from the entry's own row, not part of this form. */
(() => {
  'use strict';

  const section = document.getElementById('me-cash-purchases');
  if (!section) return;
  const body = document.getElementById('me-cash-purchases-body');
  const { h, clear, api, toast, field, dateField, showFieldErrors, money } = window.LD;

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  const STATUS_LABEL = { pending: 'Pending', approved: 'Approved', rejected: 'Rejected' };
  const STATUS_CLASS = { pending: 'chip-today', approved: 'chip-active', rejected: 'chip-off' };

  // Same "attached after the fact" pattern as a material stock-in's own bill (app/static/js/inventory.js's
  // billControl) - the file goes up the moment it's picked, no separate save step.
  function billControl(entry, onChanged) {
    if (!entry.bill_url) {
      const fileInput = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp,application/pdf', hidden: true });
      fileInput.onchange = async () => {
        if (!fileInput.files.length) return;
        const fd = new FormData();
        fd.append('bill', fileInput.files[0]);
        try {
          const res = await fetch(`/api/cash-purchases/${entry.id}/bill`, { method: 'POST', body: fd, credentials: 'same-origin' });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || 'Could not upload the bill');
          toast('Bill added');
          onChanged();
        } catch (err) { toast(err.message, true); }
      };
      return h('label', { class: 'link-btn' }, 'Add bill', fileInput);
    }
    return h('a', { href: entry.bill_url, target: '_blank', rel: 'noopener noreferrer', class: 'link-btn' }, 'View bill');
  }

  function entryRow(e, cur, onChanged) {
    const sub = [fmtDate(e.entry_date), e.quantity != null ? `${e.quantity} ${e.unit || ''}`.trim() : null,
      e.supplier || null, e.note || null].filter(Boolean).join(' · ');
    return h('li', { class: 'p-row' },
      h('span', { class: `chip ${STATUS_CLASS[e.status]}` }, STATUS_LABEL[e.status]),
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, e.material_name),
        h('span', { class: 'row-sub' }, sub),
        h('span', { class: 'bill-links' }, billControl(e, onChanged))),
      h('span', { class: 'row-value' }, money(e.amount, cur)));
  }

  function openLogSheet() {
    const dateInput = dateField(todayIso());
    const nameInput = h('input', { type: 'text', maxlength: 120, autocomplete: 'off' });
    const qtyInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off' });
    const unitInput = h('input', { type: 'text', maxlength: 20, autocomplete: 'off', placeholder: 'e.g. bags, litres' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off' });
    const supplierInput = h('input', { type: 'text', maxlength: 120, autocomplete: 'off' });
    const noteInput = h('textarea', { rows: 2, maxlength: 500 });
    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Log purchase');

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (ev) => {
        ev.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        try {
          await api('/api/cash-purchases/me', {
            method: 'POST', body: {
              entry_date: dateInput.value, material_name: nameInput.value, quantity: qtyInput.value || null,
              unit: unitInput.value, amount: amountInput.value, supplier: supplierInput.value, note: noteInput.value,
            },
          });
          toast('Purchase logged');
          overlay.remove();
          load();
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      field('entry_date', 'Date', dateInput),
      field('material_name', 'What did you buy', nameInput, { wide: true }),
      field('quantity', 'Quantity', qtyInput),
      field('unit', 'Unit', unitInput),
      field('amount', 'Cost', amountInput),
      field('supplier', 'Supplier', supplierInput, { wide: true }),
      field('note', 'Note', noteInput, { wide: true }),
      h('div', { class: 'confirm-actions' },
        h('button', { class: 'btn', type: 'button', onclick: () => overlay.remove() }, 'Cancel'),
        saveBtn));
    const card = h('div', { class: 'confirm-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Log purchase' },
      h('h2', {}, 'Log purchase'), form);
    const overlay = h('div', { class: 'confirm-overlay', onclick: (ev) => { if (ev.target === overlay) overlay.remove(); } }, card);
    document.body.append(overlay);
    nameInput.focus?.();
  }

  async function load() {
    let data;
    try { data = await api('/api/cash-purchases/me'); }
    catch (err) { section.hidden = true; return; }
    section.hidden = !data.account;
    if (!data.account) return;
    const cur = data.currency;
    const a = data.account;
    clear(body).append(
      h('div', { class: 'p-section-head' },
        h('p', { class: 'wk-legend' }, `Given ${money(a.given_total, cur)} · Spent ${money(a.spent_total, cur)} · Remaining ${money(a.remaining, cur)}`),
        h('button', { class: 'btn small', type: 'button', onclick: openLogSheet }, '+ Log purchase')),
      data.entries.length
        ? h('ul', { class: 'card-group' }, data.entries.map((e) => entryRow(e, cur, load)))
        : h('p', { class: 'hint' }, 'Nothing logged yet.'));
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

