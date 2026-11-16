/* The admin's meeting planner and scheduler (kohal, 2026-11-16: "a meeting planner and scheduler (auto and manual scheduler) for admin to plan the day and
   meetings for future"). Two tabs: Plan (today at the top, then each coming day, every day's meetings and tasks as tiles the admin drags into the order he
   wants; anything from earlier days still open sits after today - kohal: "club day and upcoming tabs") and Held (meetings and calls that took place, newest
   first, searchable). Four categories (kohal, 2026-11-16: "client meeting, site visit, call to make, work to
   do"): a Client meeting and a Call to make are meetings (they carry the client's details), a Site visit and Work to do are tasks. A "next schedule
   plan" with a date becomes a follow-up meeting on its own (see app/planner.py). Every tile looks the same - what, a tag, and a "Mark held" /
   "Mark done" button. Admin only. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, field, showFieldErrors, selectField, searchField, dateField, timeField, closeOnBack } = window.LD;
  const view = $('#view');

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
      h('a', { class: 'filter-chip', href: '#', 'aria-current': active === 'plan' ? 'page' : null }, 'Plan'),
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

    // What was said and what comes next belong to a meeting that has been held (kohal, 2026-11-16: "the scheduled part should be only once the meeting is
    // getting marked as held") - a new meeting does not ask for them, and an existing one shows them only while its Status is Held. Marking a meeting held
    // from the list asks for them in a bottom form instead (heldSheet).
    const heldPart = h('div', { class: 'plan-held-part' },
      field('remark', 'Remark or feedback', remark),
      field('next_plan', 'Next schedule plan', nextPlan),
      field('next_date', 'Next meeting on', nextDate, { hint: 'With a date, the next meeting is added to the end of that day by itself.' }));
    const showHeldPart = () => { heldPart.style.display = status.value === 'done' ? '' : 'none'; };
    status.addEventListener('change', showHeldPart);
    showHeldPart();
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add' : 'Save');
    // A held meeting is only looked at (kohal, 2026-11-16: "when clicking on held meeting or tasks, have the form as read only") - to change it, un-tick
    // "✓ Held" on its tile first.
    const readOnly = !isNew && m.status === 'done';
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      readOnly ? h('p', { class: 'hint' }, 'This meeting has been held, so it is view only. Tap "✓ Held" on its tile to reopen it.') : null,
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
      isNew ? null : heldPart,
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, readOnly ? null : saveBtn));
    if (readOnly) {
      fPick.style.display = 'none';
      form.querySelectorAll('input, textarea, button:not(.btn)').forEach((el) => { el.disabled = true; });
      cancelBtn.textContent = 'Close';
    }
    const finish = openSheet(isNew ? 'Add meeting or call' : `${kind.value === 'call' ? 'Call' : 'Meeting'}${readOnly ? ' · held' : ''}`, form);
    cancelBtn.onclick = () => finish();
    form.onsubmit = async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      const body = {
        kind: kind.value, client_id: clientId, client_name: name.value, address: address.value, contact_no: contact.value, purpose: purpose.value, place: place.value,
        meeting_date: date.value, meeting_time: when.value,
      };
      if (!isNew) Object.assign(body, { status: status.value, remark: remark.value, next_plan: nextPlan.value, next_date: nextDate.value });
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
    const readOnly = !isNew && t.done;                                  // a finished task is only looked at, like a held meeting
    const removeBtn = isNew || readOnly ? null : h('button', { class: 'btn danger', type: 'button' }, 'Remove');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isNew ? 'Add' : 'Save');
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      readOnly ? h('p', { class: 'hint' }, 'This task is done, so it is view only. Tap "✓ Done" on its tile to reopen it.') : null,
      kind.node,
      field('title', 'What', title),
      h('div', { class: 'field-row' }, field('task_date', 'Day', date), field('task_time', 'Time', when)),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, removeBtn, readOnly ? null : saveBtn));
    if (readOnly) {
      form.querySelectorAll('input, textarea, button:not(.btn)').forEach((el) => { el.disabled = true; });
      cancelBtn.textContent = 'Close';
    }
    const finish = openSheet(isNew ? 'Add site visit or work' : `Task${readOnly ? ' · done' : ''}`, form);
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

  /* "✓ Mark held" opens this form from the bottom (kohal, 2026-11-16: "when clicked on the marked as held button, it should show scheduled part form from
     bottom side"): how it went, the next schedule plan and - if there is one - the date of the next meeting, saved together with marking the meeting held. */
  function heldSheet(m, done) {
    const remark = h('textarea', { rows: 3, maxlength: 4000, placeholder: 'How it went, what was decided' }, m.remark || '');
    const nextPlan = h('input', { type: 'text', autocomplete: 'off', maxlength: 500, placeholder: 'e.g. Send the revised quote', value: m.next_plan || '' });
    const nextDate = dateField(m.next_date || '', { placeholder: 'No date yet' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, '✓ Mark held');
    const form = h('form', { novalidate: true, class: 'amount-sheet-form' },
      h('p', { class: 'hint' }, [m.client_name, m.purpose].filter(Boolean).join(' · ')),
      field('remark', 'Remark or feedback', remark),
      field('next_plan', 'Next schedule plan', nextPlan),
      field('next_date', 'Next meeting on', nextDate, { hint: 'With a date, the next meeting is added to the end of that day by itself.' }),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn));
    const finish = openSheet(m.kind === 'call' ? 'Call held' : 'Meeting held', form);
    cancelBtn.onclick = () => finish();
    form.onsubmit = async (e) => {
      e.preventDefault();
      saveBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      try {
        await api(`/api/planner/meetings/${m.id}`, { method: 'PATCH', body: { status: 'done', remark: remark.value, next_plan: nextPlan.value, next_date: nextDate.value } });
        finish();
        toast(nextDate.value ? 'Marked held - next meeting added' : 'Marked held');
        done();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    remark.focus();
  }

  /* ---------- tiles: grip | what | tag and flags | tick ---------- */

  const whenLine = (dayText, time) => [dayText, time ? clock(time) : null].filter(Boolean).join(' · ');

  // `state` colours the whole tile (kohal, 2026-11-16: "yellow for upcoming unheld and green for held, color the whole tile"): open (yellow), held (green),
  // cancelled (plain, faded).
  function planRow({ key, lines, title, kind, flags, state, action, grip, onOpen }) {
    return h('li', { class: `p-row plan-row is-${state}${grip ? ' has-grip' : ''}`, 'data-key': key },
      grip ? h('span', { class: 'plan-grip', role: 'img', 'aria-label': 'Drag to move up or down' }) : null,
      h('button', { type: 'button', class: 'plan-hit', onclick: onOpen },
        h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, title), ...lines.filter(Boolean).map((line) => h('span', { class: 'row-sub' }, line)))),
      h('div', { class: 'plan-aside' }, h('span', { class: 'chip chip-role' }, TAG[kind]), ...flags, action));
  }

  // The button that marks a tile finished (kohal, 2026-11-16: "for checkbox, its not clear. give text, check mark for meeting held") - a check mark and
  // words, "✓ Mark held" until it is, then a green "✓ Held". Tap it again to take it back.
  function doneButton(on, offText, onText, onToggle) {
    const btn = h('button', { type: 'button', class: `plan-done${on ? ' is-on' : ''}`, 'aria-pressed': String(on) }, `✓ ${on ? onText : offText}`);
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try { if ((await onToggle(!on)) === false) btn.disabled = false; } catch (err) { toast(err.message); btn.disabled = false; }   // false: it only opened a form
    });
    return btn;
  }

  function meetingRow(m, reload, { showDay = false, held = false, grip = false } = {}) {
    const action = m.status === 'cancelled' ? null : doneButton(m.status === 'done', 'Mark held', 'Held', async (on) => {
      if (on) { heldSheet(m, reload); return false; }                    // marking it held asks how it went and what comes next
      await api(`/api/planner/meetings/${m.id}`, { method: 'PATCH', body: { status: 'planned' } });
      reload();
      return true;
    });
    return planRow({
      key: `meeting:${m.id}`, title: m.client_name, kind: m.kind, grip, action,
      lines: [whenLine(showDay ? dayLabel(m.meeting_date) : '', m.meeting_time),
        [m.purpose, m.kind === 'call' ? m.contact_no : m.place].filter(Boolean).join(' · '),
        held && m.remark ? `Remark: ${m.remark}` : null,
        held && m.next_plan ? `Next: ${m.next_plan}${m.next_date ? ` (${dayLabel(m.next_date)})` : ''}` : null],
      state: m.status === 'done' ? 'held' : m.status === 'cancelled' ? 'cancelled' : 'open',
      flags: [m.status === 'cancelled' ? h('span', { class: 'chip chip-off' }, 'Cancelled') : null, m.clash ? h('span', { class: 'chip chip-today' }, 'Clash') : null],
      onOpen: () => meetingSheet(m, { date: m.meeting_date }, reload),
    });
  }

  function taskRow(t, reload, { showDay = false, grip = false } = {}) {
    const action = doneButton(t.done, 'Mark done', 'Done', async (on) => {
      await api(`/api/planner/tasks/${t.id}`, { method: 'PATCH', body: { done: on } });
      reload();
    });
    return planRow({
      key: `task:${t.id}`, title: t.title, kind: t.kind, grip, action, lines: [whenLine(showDay ? dayLabel(t.task_date) : '', t.task_time)], state: t.done ? 'held' : 'open',
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

  /* ---------- The plan: today at the top, then each coming day ---------- */

  async function showPlan() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let d;
    try { d = await api('/api/planner/agenda'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const reload = showPlan;
    const today = d.days.find((x) => x.date === d.today);
    const thisYear = d.today.slice(0, 4);
    const dayName = (iso) => {
      const [y, m, dd] = iso.split(('-')).map(Number);
      return new Date(y, m - 1, dd).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', ...(String(y) === thisYear ? {} : { year: 'numeric' }) });
    };
    const ahead = (iso) => Math.round((new Date(`${iso}T00:00:00`) - new Date(`${d.today}T00:00:00`)) / 86400000);
    const heading = (iso) => (iso === d.today ? `Today · ${dayName(iso)}` : ahead(iso) === 1 ? `Tomorrow · ${dayName(iso)}` : dayName(iso));

    // One list of tiles per day, each dragged on its own - the order is kept per day.
    const daySection = (day) => {
      const meetings = new Map(day.meetings.map((m) => [m.id, m]));
      const tasks = new Map(day.tasks.map((t) => [t.id, t]));
      const grip = day.order.length > 1;
      const tiles = day.order.map(([kind, id]) => (kind === 'meeting' ? meetingRow(meetings.get(id), reload, { grip }) : taskRow(tasks.get(id), reload, { grip })));
      const list = tiles.length ? h('ul', { class: 'card-group plan-list' }, tiles) : h('p', { class: 'hint' }, 'Nothing planned for today. Add a meeting, a call, a site visit or some work.');
      if (grip) {
        makeSortable(list, async (keys) => {
          try {
            await api('/api/planner/order', { method: 'POST', body: { date: day.date, items: keys.map((k) => { const [kind, id] = k.split(':'); return [kind, Number(id)]; }) } });
          } catch (err) { toast(err.message); reload(); }
        });
      }
      const left = [[day.meetings.filter((m) => m.status === 'planned').length, 'meeting', 'meetings'], [day.tasks.filter((t) => !t.done).length, 'task', 'tasks']]
        .filter(([n]) => n).map(([n, one, many]) => plural(n, one, many)).join(' · ');
      return h('section', { class: 'p-section' }, h('div', { class: 'p-section-head' }, h('h3', {}, heading(day.date)), left ? h('span', { class: 'plan-count' }, left) : null), list);
    };

    const earlier = d.earlier.map((e) => (e.type === 'meeting' ? meetingRow(e, reload, { showDay: true }) : taskRow(e, reload, { showDay: true })));
    const [now, later] = [d.days[0], d.days.slice(1)];
    clear(view).append(h('div', {},
      tabs('plan'),
      h('div', { class: 'project-detail plan-page' },
        h('div', { class: 'plan-actions' },
          h('button', { class: 'btn', type: 'button', onclick: () => meetingSheet(null, { date: d.today }, reload) }, '+ Meeting'),
          h('button', { class: 'btn', type: 'button', onclick: () => taskSheet(null, { date: d.today }, reload) }, '+ Task')),
        h('p', { class: 'plan-legend' }, h('span', { class: 'plan-key is-open' }, 'Upcoming, not held yet'), h('span', { class: 'plan-key is-held' }, 'Held or done')),
        d.days.some((x) => x.order.length > 1) ? h('p', { class: 'plan-hint' }, 'Hold the dots on a tile and drag it up or down.') : null,
        daySection(now),
        earlier.length ? group('Earlier, still open', 'These days have passed - mark each held or done, or open it to write the remark and plan the next step.', earlier) : null,
        later.map(daySection))));
  }

  /* ---------- Held: meetings and calls that took place ---------- */

  function showHeld() {
    const mine = { from: '', to: '', q: '' };
    const from = dateField('', { placeholder: 'From', clearable: true });
    const to = dateField('', { placeholder: 'To', clearable: true });
    const search = h('input', { type: 'search', autocomplete: 'off', placeholder: 'Search a client or purpose', 'aria-label': 'Search a client or purpose' });
    from.setAttribute('aria-label', 'From date');
    to.setAttribute('aria-label', 'To date');
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
          h('div', { class: 'field-row' }, h('div', { class: 'field' }, from), h('div', { class: 'field' }, to)),
          search),
        list)));
    draw();
  }

  function route() {
    if (window.location.hash === '#held') showHeld(); else showPlan();
  }
  window.addEventListener('hashchange', route);
  route();
})();
