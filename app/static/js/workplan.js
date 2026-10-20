/* Work plan and announcements (kohal, 2026-10-19): two subtabs, same shape as Inventory's own Materials/
   Material requests split -
   - Work plan: a project manager, the accountant, or the admin drafts a day's work - against a project for
     a field worker, or a location for office staff - and only the admin can approve it.
   - Announcements: the admin sends a message to a chosen set of employees, no approval needed.
   One page, one audience (whoever drafts/sends or approves) - the assigned/addressed person's own side (the
   Work plan alert on their Me hub, the announcement popup on every page) lives in app/me.py and common.js
   instead, not here. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, dateField, searchField, field, closeOnBack } = window.LD;
  const view = $('#view');

  const KIND_LABEL = { field: 'Field work', office: 'Office work' };

  const todayIso = () => new Date().toISOString().slice(0, 10);
  const tomorrowIso = () => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); };

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  function fmtDateTime(iso) {
    return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
  }

  function statusChip(status) {
    if (status === 'pending') return h('span', { class: 'chip chip-today' }, 'Pending');
    if (status === 'rejected') return h('span', { class: 'chip chip-off' }, 'Rejected');
    return h('span', { class: 'chip chip-active' }, 'Approved');
  }

  // Two tabs at the top, same pill shape as Inventory's own section tabs.
  function tabs(active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Work plan section' },
      h('a', { class: 'filter-chip', href: '#', 'aria-current': active === 'plan' ? 'page' : null }, 'Work plan'),
      h('a', { class: 'filter-chip', href: '#announcements', 'aria-current': active === 'announcements' ? 'page' : null }, 'Announcements'));
  }

  /* ---------- Work plan ---------- */

  async function showWorkPlan() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    const dateInput = dateField(tomorrowIso(), { clearable: false });
    dateInput.setAttribute('aria-label', 'Date');
    const fieldList = h('ul', { class: 'card-group' });
    const officeList = h('ul', { class: 'card-group' });
    const addFieldBtn = h('button', { class: 'btn small', type: 'button' }, '+ Add field work');
    const addOfficeBtn = h('button', { class: 'btn small', type: 'button' }, '+ Add office work');
    let state = null;

    async function refresh() {
      try {
        state = await api(`/api/work-assignments?date=${encodeURIComponent(dateInput.value)}`);
      } catch (err) {
        clear(view).append(h('p', { class: 'empty-state' }, err.message));
        return;
      }
      render();
    }

    function row(a) {
      const where = a.kind === 'field' ? a.project_title : a.location;
      const canAct = state.can_approve && a.status === 'pending';
      // The admin can always fix one; anyone else only while it's still pending - the server has the same
      // rule (kohal, 2026-10-19: "give option to update work plan") and is the real enforcement either way.
      const canChange = state.can_approve || a.status === 'pending';
      return h('li', { class: 'p-row' },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, a.worker_name),
          h('span', { class: 'row-sub' }, [where, a.task].filter(Boolean).join(' · '))),
        h('div', { class: 'approval-actions' },
          statusChip(a.status),
          canAct ? h('button', { class: 'btn small primary', type: 'button', onclick: () => act(a, 'approve') }, 'Approve') : null,
          canAct ? h('button', { class: 'btn small', type: 'button', onclick: () => act(a, 'reject') }, 'Reject') : null,
          canChange ? h('a', { href: '#', class: 'att-delete-link', onclick: (e) => { e.preventDefault(); openSheet(a.kind, a); } }, 'Edit') : null,
          canChange ? h('a', { href: '#', class: 'att-delete-link', onclick: (e) => { e.preventDefault(); removeOne(a); } }, 'Delete') : null));
    }

    async function act(a, action) {
      try {
        await api(`/api/work-assignments/${a.id}/${action}`, { method: 'POST' });
        toast(action === 'approve' ? 'Approved' : 'Rejected');
        refresh();
      } catch (err) {
        toast(err.message, true);
      }
    }

    async function removeOne(a) {
      const sure = await confirm('Delete this work assignment?', { ok: 'Delete', danger: true, title: 'Delete assignment' });
      if (!sure) return;
      try {
        await api(`/api/work-assignments/${a.id}`, { method: 'DELETE' });
        toast('Deleted');
        refresh();
      } catch (err) {
        toast(err.message, true);
      }
    }

    // Same shape as a project's own detail-page sections (.project-detail's grid gap is what actually
    // spaces Field work and Office work apart uniformly - kohal, 2026-10-19: "the box spacing isnt
    // uniform... follow the uniformity of the app"; .p-section-head + .p-section is the exact pattern
    // Projects' own Commission section uses for "a heading with a button next to it").
    function render() {
      const fieldRows = state.assignments.filter((a) => a.kind === 'field');
      const officeRows = state.assignments.filter((a) => a.kind === 'office');
      clear(fieldList).append(...(fieldRows.length ? fieldRows.map(row) : [h('li', { class: 'empty-state' }, 'Nothing scheduled yet.')]));
      clear(officeList).append(...(officeRows.length ? officeRows.map(row) : [h('li', { class: 'empty-state' }, 'Nothing scheduled yet.')]));

      // dateInput goes straight into the grid (not wrapped in .filters) - .filters' own `margin: 0 auto`
      // centering, meant for sitting directly in normal block flow (see attendance.js), fights .project-
      // detail's grid-stretch and collapses it to content width instead of filling the row.
      clear(view).append(h('div', { class: 'project-detail' },
        tabs('plan'),
        dateInput,
        h('section', { class: 'p-section' },
          h('div', { class: 'p-section-head' }, h('h3', {}, 'Field work'), addFieldBtn),
          fieldList),
        h('section', { class: 'p-section' },
          h('div', { class: 'p-section-head' }, h('h3', {}, 'Office work'), addOfficeBtn),
          officeList)));
    }

    function workerOptions() {
      return state.workers.map((w) => ({ value: String(w.id), label: w.has_login ? w.name : `${w.name} (no login - won't see an alert)` }));
    }

    function projectOptions() {
      return state.projects.map((p) => ({ value: String(p.id), label: `${p.client_name} – ${p.title}` }));
    }

    // `existing`, when given, edits that assignment instead of adding a new one (kohal, 2026-10-19: "give
    // option to update work plan") - same sheet, pre-filled, PATCHing instead of POSTing.
    function openSheet(kind, existing) {
      const workerSel = searchField(workerOptions(), existing ? String(existing.worker_id) : '', { placeholder: 'Choose an employee' });
      const projectSel = kind === 'field'
        ? searchField(projectOptions(), existing ? String(existing.project_id) : '', { placeholder: 'Choose a project' })
        : null;
      const locationInput = kind === 'office'
        ? h('input', { type: 'text', maxlength: 120, autocomplete: 'off', placeholder: 'e.g. Head office', value: existing ? existing.location : '' })
        : null;
      const taskInput = h('input', { type: 'text', maxlength: 300, autocomplete: 'off', placeholder: 'What they should do', value: existing ? existing.task : '' });
      const errEl = h('p', { class: 'err', role: 'alert' });
      const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
      const saveBtn = h('button', { class: 'btn primary', type: 'button' }, existing ? 'Save' : 'Add');
      const finish = closeOnBack(() => overlay.remove());
      const overlay = h('div', { class: 'confirm-overlay sheet-overlay', onclick: (e) => { if (e.target === overlay) finish(); } });
      cancelBtn.onclick = () => finish();
      saveBtn.onclick = async () => {
        saveBtn.disabled = true;
        errEl.textContent = '';
        try {
          const body = {
            for_date: dateInput.value, kind, worker_id: workerSel.value,
            project_id: projectSel ? projectSel.value : null,
            location: locationInput ? locationInput.value : null,
            task: taskInput.value,
          };
          if (existing) await api(`/api/work-assignments/${existing.id}`, { method: 'PATCH', body });
          else await api('/api/work-assignments', { method: 'POST', body });
          finish();
          toast(existing ? 'Saved' : 'Added');
          refresh();
        } catch (err) {
          errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
          saveBtn.disabled = false;
        }
      };
      overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
        h('h2', {}, `${existing ? 'Edit' : 'Add'} ${KIND_LABEL[kind].toLowerCase()}`),
        field('worker_id', 'Employee', workerSel),
        kind === 'field' ? field('project_id', 'Project', projectSel) : field('location', 'Work location', locationInput),
        field('task', 'Work assigned', taskInput),
        errEl,
        h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
      document.body.append(overlay);
    }

    addFieldBtn.onclick = () => openSheet('field');
    addOfficeBtn.onclick = () => openSheet('office');
    dateInput.onchange = refresh;
    await refresh();
  }

  /* ---------- Announcements ---------- */

  // Search-and-pick more than one employee, same search field everything else uses, with each pick turning
  // into a removable chip below it (kohal, 2026-10-19: "choose the employees (give same search facility as
  // mentioned above)"), plus a "Select all" tick box (kohal, 2026-10-20: "need multiselect employee option
  // and also select all tick box") - ticked, every employee becomes a chip (still individually removable
  // afterward, same as any other pick); the box itself reflects whether everyone shown is currently chosen,
  // so removing even one chip unticks it again rather than silently lying about the state. `.value` is the
  // list of chosen worker ids.
  function multiWorkerPicker(workers) {
    const byId = new Map(workers.map((w) => [w.id, w]));
    const chosen = new Map();
    const chipsBox = h('div', { class: 'chip-row' });
    const search = searchField(
      workers.map((w) => ({ value: w.id, label: w.has_login ? w.name : `${w.name} (no login - won't see it)` })),
      '', { placeholder: 'Search employees…' },
    );
    const selectAllInput = h('input', { type: 'checkbox' });
    selectAllInput.addEventListener('change', () => {
      if (selectAllInput.checked) workers.forEach((w) => chosen.set(w.id, true));
      else chosen.clear();
      renderChips();
    });
    function renderChips() {
      selectAllInput.checked = workers.length > 0 && chosen.size === workers.length;
      clear(chipsBox).append(...[...chosen.keys()].map((id) => {
        const w = byId.get(id);
        const removeBtn = h('button', { type: 'button', 'aria-label': `Remove ${w.name}` }, '×');
        removeBtn.onclick = () => { chosen.delete(id); renderChips(); };
        return h('span', { class: 'chip chip-removable' }, w.name, removeBtn);
      }));
    }
    search.addEventListener('change', () => {
      const id = Number(search.value);
      if (id && byId.has(id) && !chosen.has(id)) {
        chosen.set(id, true);
        renderChips();
      }
      search.value = '';   // clears the field so the same box can pick the next person too
    });
    const wrap = h('div', {},
      h('label', { class: 'toggle-row' }, h('span', {}, 'Select all'), selectAllInput),
      search, chipsBox);
    Object.defineProperty(wrap, 'value', { get: () => [...chosen.keys()], configurable: true });
    return wrap;
  }

  async function showAnnouncements() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try {
      data = await api('/api/announcements');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }

    const pickerBox = h('div', {});
    const messageInput = h('textarea', { maxlength: 500, rows: 3, placeholder: 'What do you want to tell them?' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const sendBtn = h('button', { class: 'btn primary', type: 'button' }, 'Send');
    let picker = multiWorkerPicker(data.workers);
    clear(pickerBox).append(picker);

    const historyList = h('ul', { class: 'card-group' });
    function renderHistory() {
      clear(historyList).append(...(data.announcements.length ? data.announcements.map((a) => h('li', { class: 'p-row' },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, a.message),
          h('span', { class: 'row-sub' },
            `${fmtDateTime(a.created_at)} · sent to ${a.recipient_count} · seen by ${a.dismissed_count}`)))) :
        [h('li', { class: 'empty-state' }, 'Nothing sent yet.')]));
    }
    renderHistory();

    sendBtn.onclick = async () => {
      sendBtn.disabled = true;
      errEl.textContent = '';
      try {
        const res = await api('/api/announcements', {
          method: 'POST', body: { message: messageInput.value, worker_ids: picker.value },
        });
        toast('Sent');
        data.announcements.unshift(res.announcement);
        renderHistory();
        messageInput.value = '';
        picker = multiWorkerPicker(data.workers);
        clear(pickerBox).append(picker);
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
      }
      sendBtn.disabled = false;
    };

    clear(view).append(h('div', { class: 'project-detail' },
      tabs('announcements'),
      h('section', { class: 'p-section' },
        field('worker_ids', 'Employees', pickerBox),
        field('message', 'Message', messageInput, { wide: true }),
        errEl,
        h('div', { class: 'form-actions' }, sendBtn)),
      h('section', { class: 'p-section' },
        h('h3', {}, 'History'),
        historyList)));
  }

  function route() {
    if (window.location.hash === '#announcements') return showAnnouncements();
    return showWorkPlan();
  }

  window.addEventListener('hashchange', route);
  route();
})();
