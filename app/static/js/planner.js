/* The admin's meeting planner and scheduler (kohal, 2026-11-16: "a meeting planner and scheduler (auto and manual scheduler) for admin to plan the day and
   meetings for future"). Subtabs: Day (one day's meetings and tasks as tiles the admin drags into the order he wants)
   and Upcoming (what is coming, what still waits for its remark), and Held (meetings and calls that took place, newest first, searchable). Four categories (kohal, 2026-11-16: "client meeting, site visit, call to make, work to
   do"): a Client meeting and a Call to make are meetings (they carry the client's details), a Site visit and Work to do are tasks. A "next schedule
   plan" with a date becomes a follow-up meeting on its own (see app/planner.py). Every tile looks the same - what, a tag, and a tick at the end
   (held / done). Admin only. */
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
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  const STATUS = [{ value: 'planned', label: 'Planned' }, { value: 'done', label: 'Held' }, { value: 'cancelled', label: 'Cancelled' }];
  const MEETING_KINDS = [{ value: 'client_meeting', label: 'Client meeting' }, { value: 'call', label: 'Call to make' }];
  const TASK_KINDS = [{ value: 'site_visit', label: 'Site visit' }, { value: 'work', label: 'Work to do' }];
  const TAG = { client_meeting: 'Meeting', call: 'Call', site_visit: 'Site visit', work: 'Work' };

  function tabs(active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Planner' },
      h('a', { class: 'filter-chip', href: '#', 'aria-current': active === 'day' ? 'page' : null }, 'Day'),
      h('a', { class: 'filter-chip', href: '#upcoming', 'aria-current': active === 'upcoming' ? 'page' : null }, 'Upcoming'),
      h('a', { class: 'filter-chip', href: '#held', 'aria-current': active === 'held' ? 'page' : null }, 'Held'));
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

  // "Client meeting | Call to make" or "Site visit | Work to do" - two pills at the top of a form; `.value` is the one picked.
  function kindPicker(options, current, onChange) {
    const state = { value: current };
    const group = h('div', { class: 'stage-filter plan-kind', role: 'group', 'aria-label': 'Type' });
    const draw = () => {
      clear(group).append(...options.map((o) => h('button', {
        class: 'filter-chip', type: 'button', 'aria-pressed': String(o.value === state.value),
        onclick: () => { state.value = o.value; draw(); onChange(o.value); } }, o.label)));
    };
    draw();
    return { node: h('div', { class: 'field' }, h('label', {}, 'Type'), group), get value() { return state.value; } };
  }

  const relabel = (fieldEl, text) => { fieldEl.querySelector('label').textContent = text; };

  /* ---------- a meeting or a call ---------- */

  async function meetingSheet(meeting, defaults, done) {
    const isNew = !meeting;
    const m = meeting || {};
    let clients = [];
    try { clients = (await api('/api/planner/clients')).clients; } catch (err) { /* typing the name by hand still works */ }

    const text = (value, attrs = {}) => h('input', { type: 'text', autocomplete: 'off', value: value || '', ...attrs });
    const name = text(m.client_name, { maxlength: 160, placeholder: 'Who is it with' });
    const address = h('textarea', { rows: 2, maxlength: 500, placeholder: 'Address' }, m.address || '');
    const contact = text(m.contact_no, { maxlength: 40, inputmode: 'tel', placeholder: 'Phone number' });
    const purpose = text(m.purpose, { maxlength: 300, placeholder: 'What it is about' });
    const place = text(m.place, { maxlength: 200, placeholder: 'Where it will be held' });
    const date = dateField(m.meeting_date || defaults.date, { placeholder: 'Date', clearable: false });
    const when = timeField(m.meeting_time || '', { placeholder: 'Optional' });
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

    const fPick = field('client_id', 'Existing client', pick);
    const fAddress = field('address', 'Address', address);
    const fPurpose = field('purpose', 'Purpose of meeting', purpose);
    const fPlace = field('place', 'Place of meeting', place);
    const fDate = field('meeting_date', 'Date of meeting', date);
    const fTime = field('meeting_time', 'Time of meeting', when);
    // A call has no address or place to go to - those two drop out, and the labels say "call".
    const apply = (kind) => {
      const call = kind === 'call';
      fAddress.style.display = fPlace.style.display = call ? 'none' : '';
      relabel(fPurpose, call ? 'Purpose of call' : 'Purpose of meeting');
      relabel(fDate, call ? 'Date of call' : 'Date of meeting');
      relabel(fTime, call ? 'Time of call' : 'Time of meeting');
    };
    const kind = kindPicker(MEETING_KINDS, m.kind || 'client_meeting', apply);
    apply(kind.value);

    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add' : 'Save');
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      isNew || !m.logged_on ? null : h('p', { class: 'hint' }, `Logged on ${dayLabel(m.logged_on)}${m.follow_up_of_id ? ' · a follow-up of an earlier meeting' : ''}`),
      kind.node,
      fPick,
      field('client_name', 'Client name', name),
      fAddress,
      field('contact_no', 'Contact no', contact),
      fPurpose,
      fPlace,
      h('div', { class: 'field-row' }, fDate, fTime),
      isNew ? null : field('status', 'Status', status),
      isNew ? null : field('remark', 'Remark or feedback', remark),
      field('next_plan', 'Next schedule plan', nextPlan),
      field('next_date', 'Next one on', nextDate, { hint: 'With a date, the next meeting is added to the end of that day by itself.' }),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn));
    const finish = openSheet(isNew ? 'Add meeting or call' : (kind.value === 'call' ? 'Call' : 'Meeting'), form);
    cancelBtn.onclick = () => finish();
    form.onsubmit = async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      const body = {
        kind: kind.value, client_id: clientId, client_name: name.value, address: address.value, contact_no: contact.value, purpose: purpose.value, place: place.value,
        meeting_date: date.value, meeting_time: when.value, next_plan: nextPlan.value, next_date: nextDate.value,
      };
      if (!isNew) Object.assign(body, { status: status.value, remark: remark.value });
      try {
        if (isNew) await api('/api/planner/meetings', { method: 'POST', body });
        else await api(`/api/planner/meetings/${m.id}`, { method: 'PATCH', body });
        finish();
        toast(isNew ? 'Added' : 'Saved');
        done();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    if (isNew) name.focus();                       // an existing one opens without the keyboard in the way
  }

  /* ---------- a task: a site visit or work to do ---------- */

  function taskSheet(task, defaults, done) {
    const isNew = !task;
    const t = task || {};
    const title = h('input', { type: 'text', autocomplete: 'off', maxlength: 300, value: t.title || '' });
    const date = dateField(t.task_date || defaults.date, { placeholder: 'Day', clearable: false });
    const when = timeField(t.task_time || '', { placeholder: 'Optional' });
    const apply = (kind) => { title.placeholder = kind === 'site_visit' ? 'e.g. Butibori cold storage - check hydrant line' : 'e.g. Prepare the AMC quotation'; };
    const kind = kindPicker(TASK_KINDS, t.kind || 'site_visit', apply);
    apply(kind.value);
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const removeBtn = isNew ? null : h('button', { class: 'btn danger', type: 'button' }, 'Remove');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add' : 'Save');
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      kind.node,
      field('title', 'What', title),
      h('div', { class: 'field-row' }, field('task_date', 'Day', date), field('task_time', 'Time', when)),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, removeBtn, saveBtn));
    const finish = openSheet(isNew ? 'Add site visit or work' : 'Task', form);
    cancelBtn.onclick = () => finish();
    if (removeBtn) {
      removeBtn.onclick = async () => {
        try { await api(`/api/planner/tasks/${t.id}`, { method: 'DELETE' }); finish(); toast('Removed'); done(); } catch (err) { errEl.textContent = err.message; }
      };
    }
    form.onsubmit = async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      const body = { kind: kind.value, title: title.value, task_date: date.value, task_time: when.value };
      try {
        if (isNew) await api('/api/planner/tasks', { method: 'POST', body });
        else await api(`/api/planner/tasks/${t.id}`, { method: 'PATCH', body });
        finish();
        toast(isNew ? 'Added' : 'Saved');
        done();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    if (isNew) title.focus();
  }

  /* ---------- tiles: grip | what | tag and flags | tick ---------- */

  const whenLine = (dayText, time) => [dayText, time ? clock(time) : null].filter(Boolean).join(' · ');

  function planRow({ key, lines, title, kind, flags, finished, tick, grip, onOpen }) {
    return h('li', { class: `p-row plan-row${finished ? ' is-finished' : ''}${grip ? ' has-grip' : ''}`, 'data-key': key },
      grip ? h('span', { class: 'plan-grip', role: 'img', 'aria-label': 'Drag to move up or down' }) : null,
      h('button', { type: 'button', class: 'plan-hit', onclick: onOpen },
        h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, title), ...lines.filter(Boolean).map((line) => h('span', { class: 'row-sub' }, line))),
        h('span', { class: 'plan-chips' }, h('span', { class: 'chip chip-role' }, TAG[kind]), ...flags)),
      tick);
  }

  function tickBox(checked, disabled, labelText, onToggle) {
    const box = h('input', { type: 'checkbox', class: 'plan-check', 'aria-label': labelText, checked, disabled: disabled ? '' : null });
    box.addEventListener('change', async () => {
      try { await onToggle(box.checked); } catch (err) { box.checked = !box.checked; toast(err.message); }
    });
    return box;
  }

  function meetingRow(m, reload, { showDay = false, held = false, grip = false } = {}) {
    const tick = tickBox(m.status === 'done', m.status === 'cancelled', `Mark the ${TAG[m.kind].toLowerCase()} with ${m.client_name} as held`, async (on) => {
      await api(`/api/planner/meetings/${m.id}`, { method: 'PATCH', body: { status: on ? 'done' : 'planned' } });
      reload();
    });
    return planRow({
      key: `meeting:${m.id}`, title: m.client_name, kind: m.kind, grip, tick,
      lines: [whenLine(showDay ? dayLabel(m.meeting_date) : '', m.meeting_time),
        [m.purpose, m.kind === 'call' ? m.contact_no : m.place].filter(Boolean).join(' · '),
        held && m.remark ? `Remark: ${m.remark}` : null,
        held && m.next_plan ? `Next: ${m.next_plan}${m.next_date ? ` (${dayLabel(m.next_date)})` : ''}` : null],
      finished: held ? false : m.status !== 'planned',
      flags: [m.status === 'cancelled' ? h('span', { class: 'chip chip-off' }, 'Cancelled') : null, m.clash ? h('span', { class: 'chip chip-today' }, 'Clash') : null],
      onOpen: () => meetingSheet(m, { date: m.meeting_date }, reload),
    });
  }

  function taskRow(t, reload, { grip = false } = {}) {
    const tick = tickBox(t.done, false, `Mark ${t.title} done`, async (on) => {
      await api(`/api/planner/tasks/${t.id}`, { method: 'PATCH', body: { done: on } });
      reload();
    });
    return planRow({
      key: `task:${t.id}`, title: t.title, kind: t.kind, grip, tick, lines: [whenLine('', t.task_time)], finished: t.done,
      flags: [t.clash ? h('span', { class: 'chip chip-today' }, 'Clash') : null],
      onOpen: () => taskSheet(t, { date: t.task_date }, reload),
    });
  }

  const group = (title, hint, rows) => h('section', { class: 'p-section' },
    h('div', { class: 'p-section-head' }, h('h3', {}, title)),
    hint ? h('p', { class: 'hint' }, hint) : null,
    h('ul', { class: 'card-group' }, rows));

  /* Drag a tile by its grip to move it up or down (kohal, 2026-11-16). Pointer events, so a finger and a mouse both work; the grip has touch-action: none
     so the page does not scroll under the finger. The tile follows the pointer; the tiles it passes step out of its way by swapping places in the list
     (the dragged one itself is never taken out of the page). The page scrolls by itself near the top and bottom edge. `onChange` gets the new order of
     the data-keys once the tile is let go - only if the order really changed. */
  function makeSortable(list, onChange) {
    list.addEventListener('pointerdown', (e) => {
      const grip = e.target.closest('.plan-grip');
      if (!grip || (e.pointerType === 'mouse' && e.button !== 0)) return;
      e.preventDefault();
      const item = grip.closest('li');
      const keys = () => [...list.children].map((li) => li.dataset.key).join();
      const before = keys();
      let startY = e.clientY;
      let lastY = e.clientY;
      item.classList.add('is-dragging');
      list.classList.add('is-sorting');

      const place = () => {
        item.style.transform = `translateY(${lastY - startY}px)`;
        for (let i = 0; i < 3; i += 1) {                               // a quick drag can pass more than one tile between two moves
          const r = item.getBoundingClientRect();
          const centre = r.top + r.height / 2;
          const prev = item.previousElementSibling;
          const next = item.nextElementSibling;
          if (prev && centre < prev.getBoundingClientRect().top + prev.offsetHeight / 2) {
            const moved = prev.offsetHeight;
            list.insertBefore(prev, item.nextSibling);
            startY -= moved;
          } else if (next && centre > next.getBoundingClientRect().top + next.offsetHeight / 2) {
            const moved = next.offsetHeight;
            list.insertBefore(next, item);
            startY += moved;
          } else break;
          item.style.transform = `translateY(${lastY - startY}px)`;
        }
      };
      const move = (ev) => { lastY = ev.clientY; place(); };
      const scroller = setInterval(() => {
        const top = 150;
        const bottom = window.innerHeight - 160;
        const speed = lastY < top ? -Math.ceil((top - lastY) / 8) : lastY > bottom ? Math.ceil((lastY - bottom) / 8) : 0;
        if (!speed) return;
        const was = window.scrollY;
        window.scrollBy(0, speed);
        const by = window.scrollY - was;
        if (by) { startY -= by; place(); }                          // the page moved under a finger that did not
      }, 16);
      const end = () => {
        clearInterval(scroller);
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', end);
        window.removeEventListener('pointercancel', end);
        item.classList.remove('is-dragging');
        list.classList.remove('is-sorting');
        item.style.transform = '';
        if (keys() !== before) onChange([...list.children].map((li) => li.dataset.key));
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', end);
      window.addEventListener('pointercancel', end);
    });
  }

  /* ---------- Day ---------- */

  async function showDay(day) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let d;
    try { d = await api(`/api/planner/day?date=${encodeURIComponent(day)}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const reload = () => showDay(day);
    const pickDate = dateField(day, { placeholder: 'Day', clearable: false });
    pickDate.addEventListener('change', () => { if (pickDate.value) showDay(pickDate.value); });
    const step = (by, text) => h('button', { class: 'btn', type: 'button', 'aria-label': text, onclick: () => showDay(shiftDay(day, by)) }, by < 0 ? '‹' : '›');

    const meetings = new Map(d.meetings.map((m) => [m.id, m]));
    const tasks = new Map(d.tasks.map((t) => [t.id, t]));
    const grip = d.order.length > 1;
    const tiles = d.order.map(([kind, id]) => (kind === 'meeting' ? meetingRow(meetings.get(id), reload, { grip }) : taskRow(tasks.get(id), reload, { grip })));
    const list = h('ul', { class: 'card-group plan-list' }, tiles);
    if (grip) {
      makeSortable(list, async (keys) => {
        try {
          await api('/api/planner/order', { method: 'POST', body: { date: day, items: keys.map((k) => { const [kind, id] = k.split(':'); return [kind, Number(id)]; }) } });
        } catch (err) { toast(err.message); reload(); }
      });
    }

    const open = d.meetings.filter((m) => m.status === 'planned').length;
    const openTasks = d.tasks.filter((t) => !t.done).length;
    clear(view).append(h('div', {},
      tabs('day'),
      h('div', { class: 'project-detail plan-page' },
        h('div', { class: 'plan-nav' }, step(-1, 'Previous day'), pickDate, step(1, 'Next day')),
        h('p', { class: 'inv-summary' }, h('strong', {}, String(open)), ` ${open === 1 ? 'meeting or call' : 'meetings and calls'} · ${plural(openTasks, 'task', 'tasks')} to do`),
        h('div', { class: 'plan-actions' },
          h('button', { class: 'btn', type: 'button', onclick: () => meetingSheet(null, { date: day }, reload) }, '+ Meeting'),
          h('button', { class: 'btn', type: 'button', onclick: () => taskSheet(null, { date: day }, reload) }, '+ Task')),
        grip ? h('p', { class: 'hint' }, 'Hold the dots on a tile and drag it up or down.') : null,
        tiles.length ? list : h('p', { class: 'hint' }, 'Nothing planned for this day yet. Add a meeting, a call, a site visit or some work.'))));
  }

  /* ---------- Upcoming ---------- */

  async function showUpcoming() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let d;
    try { d = await api('/api/planner/upcoming'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const reload = showUpcoming;
    const byDay = new Map();
    d.meetings.forEach((m) => { if (!byDay.has(m.meeting_date)) byDay.set(m.meeting_date, []); byDay.get(m.meeting_date).push(m); });
    clear(view).append(h('div', {},
      tabs('upcoming'),
      h('div', { class: 'project-detail plan-page' },
        h('div', { class: 'plan-actions' }, h('button', { class: 'btn', type: 'button', onclick: () => meetingSheet(null, { date: d.today }, reload) }, '+ Meeting')),
        d.needs_remark.length ? group('Waiting for your remark', 'These dates have passed - open one to say how it went, and plan the next step.',
          d.needs_remark.map((m) => meetingRow(m, reload, { showDay: true }))) : null,
        byDay.size ? [...byDay].map(([day, list]) => group(day === d.today ? `Today · ${dayLabel(day)}` : dayLabel(day), null, list.map((m) => meetingRow(m, reload)))) :
          h('p', { class: 'hint' }, 'No meetings are planned ahead. Add one, or write a next plan with a date on a meeting.'))));
  }

  /* ---------- Held: meetings and calls that took place ---------- */

  function showHeld() {
    const mine = { from: '', to: '', q: '' };
    const from = dateField('', { placeholder: 'From', clearable: true });
    const to = dateField('', { placeholder: 'To', clearable: true });
    const search = h('input', { type: 'search', autocomplete: 'off', placeholder: 'Search a client or purpose' });
    const list = h('div', {});
    let ticket = 0;
    const reload = () => draw();

    async function draw() {
      const mineTicket = ++ticket;
      clear(list).append(h('p', { class: 'loading' }, 'Loading…'));
      const q = new URLSearchParams();
      Object.entries(mine).forEach(([k, v]) => { if (v) q.set(k, v); });
      let d;
      try { d = await api(`/api/planner/history?${q}`); } catch (err) { if (mineTicket === ticket) clear(list).append(h('p', { class: 'empty-state' }, err.message)); return; }
      if (mineTicket !== ticket) return;
      const n = d.meetings.length;
      const filtered = mine.from || mine.to || mine.q;
      clear(list).append(
        n ? h('p', { class: 'inv-summary' }, h('strong', {}, d.more ? `${n}+` : String(n)), ` held ${n === 1 && !d.more ? 'meeting or call' : 'meetings and calls'}${d.more ? ' (newest first - narrow it down to see older ones)' : ''}`) : null,
        n ? h('ul', { class: 'card-group' }, d.meetings.map((m) => meetingRow(m, reload, { showDay: true, held: true })))
          : h('p', { class: 'hint' }, filtered ? 'Nothing held matches that.' : 'Nothing has been marked held yet. Tick a meeting or call once it has taken place and it shows up here.'));
    }

    from.addEventListener('change', () => { mine.from = from.value || ''; draw(); });
    to.addEventListener('change', () => { mine.to = to.value || ''; draw(); });
    let timer = null;
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { mine.q = search.value.trim(); draw(); }, 300); });

    clear(view).append(h('div', {},
      tabs('held'),
      h('div', { class: 'project-detail' },
        h('div', { class: 'plan-filters' },
          h('div', { class: 'field-row' }, field('from', 'From', from), field('to', 'To', to)),
          field('q', 'Client or purpose', search)),
        list)));
    draw();
  }

  function route() {
    if (window.location.hash === '#upcoming') showUpcoming();
    else if (window.location.hash === '#held') showHeld();
    else showDay(todayIso());
  }
  window.addEventListener('hashchange', route);
  route();
})();
