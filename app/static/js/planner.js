/* The admin's meeting planner and scheduler (kohal, 2026-11-16: "a meeting planner and scheduler (auto and manual scheduler) for admin to plan the day and
   meetings for future"). Two subtabs: Day (one day's meetings and tasks in time order, with "Auto-arrange" to give the ones without a time a free slot)
   and Upcoming (what is coming, what still waits for its remark). A meeting has the fields of his meeting sheet; a "next schedule plan" with a date
   becomes a follow-up meeting on its own (see app/planner.py). Admin only. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, field, showFieldErrors, selectField, searchField, dateField, timeField, closeOnBack } = window.LD;
  const view = $('#view');

  const todayIso = () => new Date().toLocaleDateString('en-CA');
  const shiftDay = (iso, by) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d + by).toLocaleDateString('en-CA');
  };
  const dayLabel = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  };
  const clock = (hhmm) => {
    if (!hhmm) return '';
    const [hh, mm] = hhmm.split(':').map(Number);
    return `${hh % 12 || 12}:${String(mm).padStart(2, '0')} ${hh >= 12 ? 'PM' : 'AM'}`;
  };
  const span = (mins) => (mins % 60 === 0 ? `${mins / 60} hr` : mins > 60 ? `${Math.floor(mins / 60)} hr ${mins % 60} min` : `${mins} min`);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  const DURATIONS = [15, 30, 45, 60, 90, 120, 180].map((m) => ({ value: m, label: span(m) }));
  const STATUS = [{ value: 'planned', label: 'Planned' }, { value: 'done', label: 'Held' }, { value: 'cancelled', label: 'Cancelled' }];

  function tabs(active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Planner' },
      h('a', { class: 'filter-chip', href: '#', 'aria-current': active === 'day' ? 'page' : null }, 'Day'),
      h('a', { class: 'filter-chip', href: '#upcoming', 'aria-current': active === 'upcoming' ? 'page' : null }, 'Upcoming'));
  }

  /* ---------- the bottom sheet both forms use ---------- */

  function openSheet(title, form) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, h('h2', {}, title), form));
    document.body.append(overlay);
    return finish;
  }

  /* ---------- a meeting ---------- */

  async function meetingSheet(meeting, defaults, done) {
    const isNew = !meeting;
    const m = meeting || {};
    let clients = [];
    try { clients = (await api('/api/planner/clients')).clients; } catch (err) { /* typing the name by hand still works */ }

    const text = (value, attrs = {}) => h('input', { type: 'text', autocomplete: 'off', value: value || '', ...attrs });
    const name = text(m.client_name, { maxlength: 160, placeholder: 'Who is the meeting with' });
    const address = h('textarea', { rows: 2, maxlength: 500, placeholder: 'Address' }, m.address || '');
    const contact = text(m.contact_no, { maxlength: 40, inputmode: 'tel', placeholder: 'Phone number' });
    const purpose = text(m.purpose, { maxlength: 300, placeholder: 'What it is about' });
    const place = text(m.place, { maxlength: 200, placeholder: 'Where it will be held' });
    const date = dateField(m.meeting_date || defaults.date, { placeholder: 'Date', clearable: false });
    const when = timeField(m.meeting_time || '', { placeholder: 'Not set - auto' });
    const length = selectField(DURATIONS, m.duration_min || 60, { title: 'How long', placeholder: 'How long' });
    const status = selectField(STATUS, m.status || 'planned', { title: 'Status', placeholder: 'Status' });
    const remark = h('textarea', { rows: 3, maxlength: 4000, placeholder: 'How it went, what was decided' }, m.remark || '');
    const nextPlan = text(m.next_plan, { maxlength: 500, placeholder: 'e.g. Send the revised quote' });
    const nextDate = dateField(m.next_date || '', { placeholder: 'No date yet' });
    let clientId = m.client_id || null;
    const pick = searchField([{ value: '', label: 'Type a new name below' }, ...clients.map((c) => ({ value: c.id, label: c.name }))], clientId || '', { placeholder: 'Pick an existing client (optional)' });
    pick.addEventListener('change', () => {
      const c = clients.find((x) => String(x.id) === String(pick.value));
      clientId = c ? c.id : null;
      if (c) { name.value = c.name; address.value = c.address; contact.value = c.contact_no; }
    });

    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add meeting' : 'Save');
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      isNew || !m.logged_on ? null : h('p', { class: 'hint' }, `Logged on ${dayLabel(m.logged_on)}${m.follow_up_of_id ? ' · a follow-up of an earlier meeting' : ''}`),
      field('client_id', 'Client', pick),
      field('client_name', 'Client name', name),
      field('address', 'Address', address),
      field('contact_no', 'Contact no', contact),
      field('purpose', 'Purpose of meeting', purpose),
      field('place', 'Place of meeting', place),
      h('div', { class: 'field-row' }, field('meeting_date', 'Date of meeting', date), field('meeting_time', 'Time of meeting', when)),
      field('duration_min', 'How long', length, { hint: 'Leave the time empty and Auto-arrange finds a free slot of this length.' }),
      isNew ? null : field('status', 'Status', status),
      isNew ? null : field('remark', 'Remark or feedback of meeting', remark),
      field('next_plan', 'Next schedule plan', nextPlan),
      field('next_date', 'Next meeting on', nextDate, { hint: 'With a date, the next meeting is added to that day by itself.' }),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn));
    const finish = openSheet(isNew ? 'Add meeting' : 'Meeting', form);
    cancelBtn.onclick = () => finish();
    form.onsubmit = async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      const body = {
        client_id: clientId, client_name: name.value, address: address.value, contact_no: contact.value, purpose: purpose.value, place: place.value,
        meeting_date: date.value, meeting_time: when.value, duration_min: length.value, next_plan: nextPlan.value, next_date: nextDate.value,
      };
      if (!isNew) Object.assign(body, { status: status.value, remark: remark.value });
      try {
        if (isNew) await api('/api/planner/meetings', { method: 'POST', body });
        else await api(`/api/planner/meetings/${m.id}`, { method: 'PATCH', body });
        finish();
        toast(isNew ? 'Meeting added' : 'Meeting saved');
        done();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    if (isNew) name.focus();                       // an existing one opens without the keyboard in the way
  }

  /* ---------- a task ---------- */

  function taskSheet(task, defaults, done) {
    const isNew = !task;
    const t = task || {};
    const title = h('input', { type: 'text', autocomplete: 'off', maxlength: 300, placeholder: 'e.g. Call the fire officer', value: t.title || '' });
    const date = dateField(t.task_date || defaults.date, { placeholder: 'Day', clearable: false });
    const when = timeField(t.task_time || '', { placeholder: 'Not set - auto' });
    const length = selectField(DURATIONS, t.duration_min || 30, { title: 'How long', placeholder: 'How long' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const removeBtn = isNew ? null : h('button', { class: 'btn danger', type: 'button' }, 'Remove');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add task' : 'Save');
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      field('title', 'Task', title),
      h('div', { class: 'field-row' }, field('task_date', 'Day', date), field('task_time', 'Time', when)),
      field('duration_min', 'How long', length),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, removeBtn, saveBtn));
    const finish = openSheet(isNew ? 'Add task' : 'Task', form);
    cancelBtn.onclick = () => finish();
    if (removeBtn) {
      removeBtn.onclick = async () => {
        try { await api(`/api/planner/tasks/${t.id}`, { method: 'DELETE' }); finish(); toast('Task removed'); done(); } catch (err) { errEl.textContent = err.message; }
      };
    }
    form.onsubmit = async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      const body = { title: title.value, task_date: date.value, task_time: when.value, duration_min: length.value };
      try {
        if (isNew) await api('/api/planner/tasks', { method: 'POST', body });
        else await api(`/api/planner/tasks/${t.id}`, { method: 'PATCH', body });
        finish();
        toast(isNew ? 'Task added' : 'Task saved');
        done();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    if (isNew) title.focus();
  }

  /* ---------- rows ---------- */

  const STATUS_CHIP = { done: ['chip chip-active', 'Held'], cancelled: ['chip chip-off', 'Cancelled'] };

  function meetingRow(m, reload, { showDay = false } = {}) {
    const chip = STATUS_CHIP[m.status];
    const timeText = m.meeting_time ? clock(m.meeting_time) : 'No time';
    return h('li', { class: `p-row plan-row${m.status === 'cancelled' ? ' is-cancelled' : ''}` },
      h('button', { type: 'button', class: 'plan-hit', onclick: () => meetingSheet(m, { date: m.meeting_date }, reload) },
        h('span', { class: `plan-time${m.meeting_time ? '' : ' is-empty'}` }, showDay ? dayLabel(m.meeting_date) : timeText,
          h('small', {}, showDay ? timeText : span(m.duration_min))),
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, m.client_name),
          h('span', { class: 'row-sub' }, [m.purpose, m.place].filter(Boolean).join(' · ')),
          m.next_plan && m.status === 'done' ? h('span', { class: 'row-sub' }, `Next: ${m.next_plan}${m.next_date ? ` (${dayLabel(m.next_date)})` : ''}`) : null),
        h('span', { class: 'plan-chips' },
          chip ? h('span', { class: chip[0] }, chip[1]) : null,
          m.clash ? h('span', { class: 'chip chip-today' }, 'Clash') : null)));
  }

  function taskRow(t, reload) {
    const box = h('input', { type: 'checkbox', class: 'plan-check', 'aria-label': `Mark ${t.title} done`, checked: t.done });
    box.addEventListener('change', async () => {
      try { await api(`/api/planner/tasks/${t.id}`, { method: 'PATCH', body: { done: box.checked } }); reload(); } catch (err) { box.checked = !box.checked; toast(err.message); }
    });
    return h('li', { class: `p-row plan-row${t.done ? ' is-cancelled' : ''}` },
      box,
      h('button', { type: 'button', class: 'plan-hit', onclick: () => taskSheet(t, { date: t.task_date }, reload) },
        h('span', { class: `plan-time${t.task_time ? '' : ' is-empty'}` }, t.task_time ? clock(t.task_time) : 'No time', h('small', {}, span(t.duration_min))),
        h('span', { class: 'p-main' }, h('span', { class: `row-title${t.done ? ' is-done' : ''}` }, t.title), h('span', { class: 'row-sub' }, 'Task')),
        h('span', { class: 'plan-chips' }, t.clash ? h('span', { class: 'chip chip-today' }, 'Clash') : null)));
  }

  const group = (title, hint, rows) => h('section', { class: 'p-section' },
    h('div', { class: 'p-section-head' }, h('h3', {}, title)),
    hint ? h('p', { class: 'hint' }, hint) : null,
    h('ul', { class: 'card-group' }, rows));

  /* ---------- Day ---------- */

  async function showDay(day) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let d;
    try { d = await api(`/api/planner/day?date=${encodeURIComponent(day)}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const reload = () => showDay(day);
    const pickDate = dateField(day, { placeholder: 'Day', clearable: false });
    pickDate.addEventListener('change', () => { if (pickDate.value) showDay(pickDate.value); });
    const step = (by, label) => h('button', { class: 'btn small', type: 'button', 'aria-label': label, onclick: () => showDay(shiftDay(day, by)) }, by < 0 ? '‹' : '›');

    const open = d.meetings.filter((m) => m.status === 'planned').length;
    const waiting = [...d.meetings.filter((m) => !m.meeting_time && m.status === 'planned'), ...d.tasks.filter((t) => !t.task_time && !t.done)];
    const timed = [
      ...d.meetings.filter((m) => m.meeting_time).map((m) => ({ at: m.meeting_time, row: meetingRow(m, reload) })),
      ...d.tasks.filter((t) => t.task_time).map((t) => ({ at: t.task_time, row: taskRow(t, reload) })),
    ].sort((a, b) => a.at.localeCompare(b.at)).map((x) => x.row);
    const untimed = [
      ...d.meetings.filter((m) => !m.meeting_time).map((m) => meetingRow(m, reload)),
      ...d.tasks.filter((t) => !t.task_time).map((t) => taskRow(t, reload)),
    ];

    const arrangeBtn = h('button', { class: 'btn primary', type: 'button', disabled: waiting.length ? null : '' }, 'Auto-arrange');
    arrangeBtn.onclick = async () => {
      arrangeBtn.disabled = true;
      try {
        const r = await api('/api/planner/arrange', { method: 'POST', body: { date: day } });
        toast(r.left ? `${plural(r.placed, 'item', 'items')} placed, ${r.left} did not fit between ${clock(d.window.start)} and ${clock(d.window.end)}` : `${plural(r.placed, 'item', 'items')} placed`);
        reload();
      } catch (err) { toast(err.message); arrangeBtn.disabled = false; }
    };

    clear(view).append(h('div', {},
      tabs('day'),
      h('div', { class: 'project-detail' },
        h('div', { class: 'plan-nav' }, step(-1, 'Previous day'), pickDate, step(1, 'Next day'),
          day === d.today ? null : h('button', { class: 'btn small', type: 'button', onclick: () => showDay(d.today) }, 'Today')),
        h('p', { class: 'inv-summary' }, h('strong', {}, plural(open, 'meeting', 'meetings')), ` planned · ${plural(d.tasks.filter((t) => !t.done).length, 'task', 'tasks')} to do`),
        h('div', { class: 'acct-actions plan-actions' },
          h('button', { class: 'btn', type: 'button', onclick: () => meetingSheet(null, { date: day }, reload) }, '+ Meeting'),
          h('button', { class: 'btn', type: 'button', onclick: () => taskSheet(null, { date: day }, reload) }, '+ Task'),
          arrangeBtn),
        timed.length ? group('Schedule', null, timed) : null,
        untimed.length ? group('Not timed yet', 'Pick a time yourself, or tap Auto-arrange to give these the first free slots.', untimed) : null,
        d.meetings.length || d.tasks.length ? null : h('p', { class: 'hint' }, 'Nothing planned for this day yet. Add a meeting or a task.'))));
  }

  /* ---------- Upcoming ---------- */

  async function showUpcoming() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let d;
    try { d = await api('/api/planner/upcoming'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const reload = showUpcoming;
    const byDay = new Map();
    d.meetings.forEach((m) => { if (!byDay.has(m.meeting_date)) byDay.set(m.meeting_date, []); byDay.get(m.meeting_date).push(m); });
    const unplaced = d.meetings.filter((m) => !m.meeting_time).length;
    const arrangeBtn = h('button', { class: 'btn primary', type: 'button', disabled: unplaced ? null : '' }, 'Auto-arrange all upcoming');
    arrangeBtn.onclick = async () => {
      arrangeBtn.disabled = true;
      try {
        const r = await api('/api/planner/arrange', { method: 'POST', body: { upcoming: true } });
        toast(r.left ? `${plural(r.placed, 'item', 'items')} placed, ${r.left} did not fit in their day` : `${plural(r.placed, 'item', 'items')} placed`);
        reload();
      } catch (err) { toast(err.message); arrangeBtn.disabled = false; }
    };
    clear(view).append(h('div', {},
      tabs('upcoming'),
      h('div', { class: 'project-detail' },
        h('div', { class: 'acct-actions plan-actions' },
          h('button', { class: 'btn', type: 'button', onclick: () => meetingSheet(null, { date: d.today }, reload) }, '+ Meeting'), arrangeBtn),
        d.needs_remark.length ? group('Waiting for your remark', 'These dates have passed - open one to say how it went, and plan the next step.',
          d.needs_remark.map((m) => meetingRow(m, reload, { showDay: true }))) : null,
        byDay.size ? [...byDay].map(([day, list]) => group(day === d.today ? `Today · ${dayLabel(day)}` : dayLabel(day), null, list.map((m) => meetingRow(m, reload)))) :
          h('p', { class: 'hint' }, 'No meetings are planned ahead. Add one, or write a next plan with a date on a meeting.'))));
  }

  function route() {
    if (window.location.hash === '#upcoming') showUpcoming(); else showDay(todayIso());
  }
  window.addEventListener('hashchange', route);
  route();
})();
