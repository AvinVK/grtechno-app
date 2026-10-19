/* Work plan (kohal, 2026-10-19): a project manager, the accountant, or the admin drafts a day's work -
   against a project for a field worker, or a location for office staff - and only the admin can approve
   it. One page, one audience (whoever drafts or approves) - the assigned worker's own alert, once
   approved, shows on their Me hub instead (app/me.py), not here. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, dateField, selectField, field, closeOnBack } = window.LD;
  const view = $('#view');

  const KIND_LABEL = { field: 'Field work', office: 'Office work' };

  const todayIso = () => new Date().toISOString().slice(0, 10);
  const tomorrowIso = () => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); };

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  function statusChip(status) {
    if (status === 'pending') return h('span', { class: 'chip chip-today' }, 'Pending');
    if (status === 'rejected') return h('span', { class: 'chip chip-off' }, 'Rejected');
    return h('span', { class: 'chip chip-active' }, 'Approved');
  }

  async function main() {
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
      const canDelete = a.status === 'pending';
      return h('li', { class: 'p-row' },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, a.worker_name),
          h('span', { class: 'row-sub' }, [where, a.task].filter(Boolean).join(' · '))),
        h('div', { class: 'approval-actions' },
          statusChip(a.status),
          canAct ? h('button', { class: 'btn small primary', type: 'button', onclick: () => act(a, 'approve') }, 'Approve') : null,
          canAct ? h('button', { class: 'btn small', type: 'button', onclick: () => act(a, 'reject') }, 'Reject') : null,
          canDelete ? h('a', { href: '#', class: 'att-delete-link', onclick: (e) => { e.preventDefault(); removeOne(a); } }, 'Delete') : null));
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

    function render() {
      const fieldRows = state.assignments.filter((a) => a.kind === 'field');
      const officeRows = state.assignments.filter((a) => a.kind === 'office');
      clear(fieldList).append(...(fieldRows.length ? fieldRows.map(row) : [h('li', { class: 'empty-state' }, 'Nothing scheduled yet.')]));
      clear(officeList).append(...(officeRows.length ? officeRows.map(row) : [h('li', { class: 'empty-state' }, 'Nothing scheduled yet.')]));

      clear(view).append(h('div', {},
        h('div', { class: 'list-head' }, h('h2', {}, 'Work plan'), dateInput),
        h('section', { class: 'p-section' },
          h('div', { class: 'att-week-head' }, h('h3', {}, 'Field work'), addFieldBtn),
          fieldList),
        h('section', { class: 'p-section' },
          h('div', { class: 'att-week-head' }, h('h3', {}, 'Office work'), addOfficeBtn),
          officeList)));
    }

    function workerOptions() {
      return state.workers.map((w) => ({ value: String(w.id), label: w.has_login ? w.name : `${w.name} (no login - won't see an alert)` }));
    }

    function projectOptions() {
      return state.projects.map((p) => ({ value: String(p.id), label: `${p.client_name} – ${p.title}` }));
    }

    function openSheet(kind) {
      const workerSel = selectField(workerOptions(), '', { title: 'Who is this for', placeholder: 'Choose an employee' });
      const projectSel = kind === 'field'
        ? selectField(projectOptions(), '', { title: 'Which project', placeholder: 'Choose a project' })
        : null;
      const locationInput = kind === 'office'
        ? h('input', { type: 'text', maxlength: 120, autocomplete: 'off', placeholder: 'e.g. Head office' })
        : null;
      const taskInput = h('input', { type: 'text', maxlength: 300, autocomplete: 'off', placeholder: 'What they should do' });
      const errEl = h('p', { class: 'err', role: 'alert' });
      const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
      const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Add');
      const finish = closeOnBack(() => overlay.remove());
      const overlay = h('div', { class: 'confirm-overlay sheet-overlay', onclick: (e) => { if (e.target === overlay) finish(); } });
      cancelBtn.onclick = () => finish();
      saveBtn.onclick = async () => {
        saveBtn.disabled = true;
        errEl.textContent = '';
        try {
          await api('/api/work-assignments', {
            method: 'POST',
            body: {
              for_date: dateInput.value, kind, worker_id: workerSel.value,
              project_id: projectSel ? projectSel.value : null,
              location: locationInput ? locationInput.value : null,
              task: taskInput.value,
            },
          });
          finish();
          toast('Added');
          refresh();
        } catch (err) {
          errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
          saveBtn.disabled = false;
        }
      };
      overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
        h('h2', {}, `Add ${KIND_LABEL[kind].toLowerCase()}`),
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

  main();
})();
