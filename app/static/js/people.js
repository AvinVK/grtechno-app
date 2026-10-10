/* Employee management, and the Attendance sheet (admin only): field workers and office staff who don't
   sign in to the app, tracked from the WhatsApp groups they mark attendance in. Grouped by role - the
   same roles table Users & roles uses (minus Admin) - not the old manpower/staff split. Both pages open
   straight on the list of people, with a search and a chip for All and each role in use:
   - Employee management (data-mode="roster"): each person, where they worked on their most recent
     working day, and the last 7 days as green (present) / red (absent) dots. Edit and Remove sit beside
     each row; + Employee (top bar) adds one. A person's name opens a popup: their current site, average
     hours, and the last 2 weeks as dates circled green or red.
   - Attendance sheet (data-mode="sheet"): everyone ranked by attendance, lowest first.
   On the sheet, a person opens their day-by-day record, laid out like Your attendance's history.
   Workers often work Sundays, so every day counts here (unlike Your attendance, which skips Sundays). The
   data arrives through imports, so days after the last one are "no data yet" - never marked absent. */
(() => {
  'use strict';

  const { $, h, clear, api, plural, toast, confirm, field, showFieldErrors, selectField, dateField, money, closeOnBack } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;
  const UNASSIGNED = 'unassigned';

  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const parseDay = (iso) => { const [y, m, d] = iso.split('-'); return new Date(+y, m - 1, +d); };
  const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
  const dayMonth = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  const shortDate = (d) => `${WEEKDAYS[d.getDay()]}, ${dayMonth(d)}`;
  const roundHours = (n) => Math.round(n * 10) / 10;

  function fmtTime(iso) {
    return iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : null;
  }

  function relativeDay(iso, todayIso) {
    const days = Math.round((parseDay(todayIso) - parseDay(iso)) / 86400000);
    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    return shortDate(parseDay(iso));
  }

  function mapLink(url, label) {
    return url ? h('a', { class: 'att-map-link', href: url, target: '_blank', rel: 'noopener noreferrer' }, label) : null;
  }

  const dataNote = (data) => h('p', { class: 'hint people-note' }, data.data_until
    ? `Attendance data up to ${shortDate(parseDay(data.data_until))}`
    : 'No attendance data yet.');

  async function load() {
    return api('/api/workforce');
  }

  /* ---------- Employee management: where each person is, and their last 7 days ---------- */

  const DOT_LABEL = { present: 'present', absent: 'absent', none: 'no data yet' };

  function weekDots(week) {
    const present = week.filter((d) => d.status === 'present').length;
    return h('span', { class: 'wk-dots', role: 'img', 'aria-label': `Present ${present} of the last ${week.length} days` },
      week.map((d) => h('i', { class: `wk-dot ${d.status}`, title: `${shortDate(parseDay(d.date))}: ${DOT_LABEL[d.status]}` })));
  }

  function rosterRow(p, today, roles, onChange) {
    const dep = p.deployed;
    const where = dep
      ? [relativeDay(dep.date, today), dep.project_code ? `${dep.project_code} · ${dep.project_title}` : 'site not recorded'].join(' · ')
      : 'No working day on record';
    return h('li', { class: 'people-row-li' },
      h('button', { type: 'button', class: 'att-day people-row', onclick: () => openPerson(p, roles, onChange) },
        h('div', { class: 'att-day-top' }, h('span', { class: 'att-day-date' }, p.name), weekDots(p.week)),
        h('span', { class: 'att-day-sub' }, where)),
      h('div', { class: 'people-row-actions' },
        h('button', { type: 'button', class: 'people-action-btn', 'aria-label': `Edit ${p.name}`, title: 'Edit',
          onclick: () => openEditPerson(p, roles, onChange) }, '✎'),
        h('button', { type: 'button', class: 'people-action-btn danger', 'aria-label': `Remove ${p.name}`, title: 'Remove',
          onclick: () => deletePerson(p, { afterDelete: onChange }) }, '×')));
  }

  const groupLabel = (k, roles) => (k === UNASSIGNED ? 'Unassigned' : roles[k] || k);

  // The list both pages open on: a search by name and a chip per group, taken from the groups the data
  // actually has (not a fixed list - whatever roles are in use, same as Users & roles), plus All.
  // Employee management lists by name with the week's dots; the Attendance sheet lists lowest attendance
  // first. The chip in use goes into the address (#welder, #unassigned, ...), so coming back from a
  // person lands on the same one.
  function showList(data, key) {
    LD.resetAppbarBack?.();
    const groups = Object.keys(data).filter((k) => Array.isArray(data[k]));
    const state = { q: '', group: groups.includes(key) ? key : 'all' };
    const sheet = mode === 'sheet';
    const period = data.period ? `${dayMonth(parseDay(data.period.start))} – ${dayMonth(parseDay(data.period.end))}` : null;
    const legend = sheet
      ? h('p', { class: 'wk-legend' }, ['Lowest attendance first', period].filter(Boolean).join(' · '))
      : h('p', { class: 'wk-legend' },
        'Last 7 days, oldest first: ',
        h('i', { class: 'wk-dot present' }), ' present ',
        h('i', { class: 'wk-dot absent' }), ' absent ',
        h('i', { class: 'wk-dot none' }), ' no data yet');
    const order = sheet
      ? (a, b) => rate(a) - rate(b) || a.name.localeCompare(b.name)
      : (a, b) => a.name.localeCompare(b.name);
    const onChange = () => { invalidateCache(); route(); };
    const row = sheet ? sheetRow : (p) => rosterRow(p, data.today, data.roles, onChange);

    const heading = h('h2', {});
    const count = h('span', { class: 'att-week-sum' });
    const chips = h('div', { class: 'stage-filter people-chips', role: 'group', 'aria-label': 'Show group' });
    const listBox = h('div', {});
    const search = h('input', {
      type: 'search', placeholder: 'Search by name', 'aria-label': 'Search by name',
      oninput: (e) => { state.q = e.target.value; render(); },
    });

    function render() {
      const pool = state.group === 'all' ? groups.flatMap((g) => data[g]) : data[state.group];
      const q = state.q.trim().toLowerCase();
      const people = pool.filter((p) => !q || p.name.toLowerCase().includes(q)).sort(order);
      heading.textContent = state.group === 'all' ? 'Everyone' : groupLabel(state.group, data.roles);
      count.textContent = plural(people.length, 'person', 'people');
      clear(chips).append(...[['all', 'All', groups.reduce((n, g) => n + data[g].length, 0)],
        ...groups.map((g) => [g, groupLabel(g, data.roles), data[g].length])].map(([value, label, n]) => h('button', {
        type: 'button', class: 'filter-chip', 'aria-pressed': String(state.group === value),
        onclick: () => {
          state.group = value;
          history.replaceState(null, '', value === 'all' ? window.location.pathname : `#${value}`);
          render();
        },
      }, label, h('span', { class: 'n' }, n))));
      clear(listBox).append(people.length
        ? h('ul', { class: 'att-week-card' }, people.map(row))
        : h('p', { class: 'empty-state' }, pool.length ? 'Nobody matches this search.' : 'Nobody here yet.'));
    }
    render();

    clear(view).append(h('div', { class: 'people' },
      h('div', { class: 'list-head' }, heading, count),
      search,
      chips,
      legend,
      listBox,
      dataNote(data)));
  }

  /* ---------- Manpower & staff: one person at a glance, in a popup ---------- */

  const FORTNIGHT = 14;
  const WEEKDAY_LETTER = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

  /* How a day stands for this person: present, absent, or "none" - after the data ends, before they first
     turned up (period.start is already their own start), or no data at all. Same rule as the week dots. */
  function dayStatus(dayIso, byDay, data) {
    const a = byDay.get(dayIso);
    if (a && a.status === 'present') return 'present';
    if (!data.period || !data.data_until || dayIso > data.data_until || dayIso < data.period.start) return 'none';
    return 'absent';
  }

  function fortnightGrid(data, byDay) {
    const today = parseDay(data.today);
    const cells = [];
    for (let back = FORTNIGHT - 1; back >= 0; back -= 1) {
      const day = addDays(today, -back);
      const status = dayStatus(dayKey(day), byDay, data);
      cells.push(h('li', { class: 'fn-cell', title: `${shortDate(day)}: ${DOT_LABEL[status]}` },
        h('span', { class: 'fn-weekday', 'aria-hidden': 'true' }, WEEKDAY_LETTER[day.getDay()]),
        h('span', { class: `fn-date ${status}` }, day.getDate()),
        h('span', { class: 'visually-hidden' }, `${shortDate(day)}, ${DOT_LABEL[status]}`)));
    }
    return h('ol', { class: 'fn-grid', 'aria-label': 'Last 2 weeks, oldest first' }, cells);
  }

  function popupBody(p, data) {
    const today = parseDay(data.today);
    const first = dayKey(addDays(today, -(FORTNIGHT - 1)));
    const inFortnight = data.attendance.filter((a) => a.work_date >= first && a.work_date <= data.today);
    const byDay = new Map(inFortnight.map((a) => [a.work_date, a]));
    const came = inFortnight.filter((a) => a.status === 'present');
    const counted = [...Array(FORTNIGHT).keys()]
      .map((i) => dayStatus(dayKey(addDays(today, -i)), byDay, data))
      .filter((s) => s !== 'none').length;
    const timed = came.filter((a) => a.hours != null);
    const avg = timed.length ? roundHours(timed.reduce((sum, a) => sum + a.hours, 0) / timed.length) : null;

    const dep = p.deployed;
    const site = h('div', { class: 'fn-site' },
      h('span', { class: 'stat-label' }, 'Current site'),
      h('strong', {}, dep ? (dep.project_code ? `${dep.project_code} · ${dep.project_title}` : 'Site not recorded') : 'No working day on record'),
      dep ? h('span', { class: 'fn-site-when' },
        `Last worked ${relativeDay(dep.date, data.today).replace(/^(Today|Yesterday)$/, (w) => w.toLowerCase())}`,
        dep.map_url ? ' · ' : null, mapLink(dep.map_url, 'Location')) : null);

    return [
      site,
      h('div', { class: 'fn-stats' },
        h('div', {},
          h('span', { class: 'stat-label' }, 'Average hours'),
          h('span', { class: 'fn-stat-value' }, avg != null ? `${avg} h` : '—'),
          h('span', { class: 'fn-stat-note' }, timed.length ? `a day, over ${plural(timed.length, 'day', 'days')} with in and out times` : 'No days with both in and out times')),
        h('div', {},
          h('span', { class: 'stat-label' }, 'Came'),
          h('span', { class: 'fn-stat-value' }, counted ? `${came.length}/${counted}` : '—'),
          h('span', { class: 'fn-stat-note' }, counted ? 'days, last 2 weeks' : 'No data for the last 2 weeks'))),
      h('div', { class: 'fn-section' },
        h('span', { class: 'stat-label' }, 'Last 2 weeks'),
        fortnightGrid(data, byDay),
        h('p', { class: 'wk-legend' },
          h('i', { class: 'wk-dot present' }), ' present ',
          h('i', { class: 'wk-dot absent' }), ' absent ',
          h('i', { class: 'wk-dot none' }), ' no data yet')),
      h('a', { class: 'fn-full-link', href: `/attendance-sheet#p${p.id}` }, 'Full attendance record →'),
    ];
  }

  function openPerson(p, roles, onChange) {
    const opener = document.activeElement;
    const body = h('div', { class: 'fn-body' }, h('p', { class: 'loading' }, 'Loading…'));
    const closeBtn = h('button', { type: 'button', class: 'icon-x', 'aria-label': 'Close' }, '×');
    const card = h('div', { class: 'confirm-card fn-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'fn-title' },
      h('div', { class: 'fn-head' },
        h('div', {}, h('h2', { id: 'fn-title' }, p.name), h('span', { class: 'fn-group' }, groupLabel(p.role_key, roles))),
        closeBtn),
      body);
    const overlay = h('div', { class: 'confirm-overlay' }, card);
    function onKey(e) { if (e.key === 'Escape') close(); }
    function close() {
      window.removeEventListener('keydown', onKey);
      overlay.remove();
      document.body.classList.remove('locked');
      opener?.focus?.();
    }
    closeBtn.onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    window.addEventListener('keydown', onKey);
    document.body.append(overlay);
    document.body.classList.add('locked');
    closeBtn.focus();

    api(`/api/workforce/${p.id}`)
      .then((data) => clear(body).append(
        ...popupBody(p, data),
        h('div', { class: 'fn-actions' },
          h('button', { class: 'btn small', type: 'button', onclick: () => { close(); openEditPerson(p, roles, onChange); } }, 'Edit'),
          h('button', { class: 'btn small danger', type: 'button', onclick: () => deletePerson(p, { afterDelete: () => { close(); onChange(); } }) }, 'Remove person'))))
      .catch((err) => clear(body).append(h('p', { class: 'empty-state' }, err.message)));
  }

  /* ---------- admin: add a person ahead of the next import, or remove one who left ---------- */

  // The group list cache goes stale the moment someone is added or removed - force the next route()
  // to reload it, same as any other data-changing action on this page.
  function invalidateCache() { cache = null; }

  function closeableModal(titleText, bodyNode) {
    const opener = document.activeElement;
    const closeBtn = h('button', { type: 'button', class: 'icon-x', 'aria-label': 'Close' }, '×');
    const card = h('div', { class: 'confirm-card fn-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'modal-title' },
      h('div', { class: 'fn-head' }, h('h2', { id: 'modal-title' }, titleText), closeBtn),
      bodyNode);
    const overlay = h('div', { class: 'confirm-overlay' }, card);
    function onKey(e) { if (e.key === 'Escape') close(); }
    function close() {
      window.removeEventListener('keydown', onKey);
      overlay.remove();
      document.body.classList.remove('locked');
      opener?.focus?.();
    }
    closeBtn.onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    window.addEventListener('keydown', onKey);
    document.body.append(overlay);
    document.body.classList.add('locked');
    return close;
  }

  const EMPLOYMENT_TYPES = [{ value: 'regular', label: 'Regular' }, { value: 'daily_wages', label: 'Daily wages' }];

  // Add and Edit share the full HR detail set and the same save/error handling - just a different title,
  // submit label, starting values and HTTP call. w is the worker to prefill from (its detail fields, e.g.
  // age/qualification/..., are only present once loaded via GET /api/workforce/<id> - empty for a brand
  // new employee or a roster-row's lightweight row data).
  function employeeForm({ titleText, submitLabel, worker: w = {}, roles, onSave }) {
    const text = (name, extra = {}) => h('input', { type: 'text', value: w[name] ?? '', ...extra });
    const nameInput = text('name', { maxlength: 120, autocomplete: 'off' });
    const roleSel = selectField(
      [{ value: UNASSIGNED, label: 'Unassigned' }, ...Object.entries(roles).map(([k, v]) => ({ value: k, label: v }))],
      w.role_key || UNASSIGNED, { title: 'Role' });
    const ageInput = text('age', { type: 'number', min: '14', max: '90', inputmode: 'numeric' });
    const qualificationInput = text('qualification', { maxlength: 160, autocomplete: 'off' });
    const experienceInput = text('experience', { maxlength: 200, autocomplete: 'off', placeholder: 'e.g. 5 years in fire systems' });
    const skillsInput = text('skills', { maxlength: 400, autocomplete: 'off' });
    const phoneInput = text('phone', { type: 'tel', maxlength: 40, autocomplete: 'off' });
    const joiningInput = dateField(w.joining_date || '', { placeholder: 'Joining date' });
    const employmentSel = selectField(
      [{ value: '', label: 'Not set' }, ...EMPLOYMENT_TYPES], w.employment_type || '',
      { title: 'Joining as', placeholder: 'Not set' });
    const wageInput = text('wage_amount', { type: 'number', min: '0', step: 'any', inputmode: 'decimal' });
    const pfInput = text('pf_number', { maxlength: 60, autocomplete: 'off' });
    const esicInput = text('esic_number', { maxlength: 60, autocomplete: 'off' });
    const referenceInput = text('reference', { maxlength: 200, autocomplete: 'off' });

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, submitLabel);
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        try {
          await onSave({
            name: nameInput.value, role_key: roleSel.value, age: ageInput.value,
            qualification: qualificationInput.value, experience: experienceInput.value, skills: skillsInput.value,
            phone: phoneInput.value, joining_date: joiningInput.value || null, employment_type: employmentSel.value,
            wage_amount: wageInput.value === '' ? null : wageInput.value, pf_number: pfInput.value,
            esic_number: esicInput.value, reference: referenceInput.value,
          });
          close();
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('div', { class: 'form-grid' },
        field('name', 'Name', nameInput, { wide: true }),
        field('role_key', 'Role', roleSel),
        field('age', 'Age', ageInput),
        field('qualification', 'Qualification', qualificationInput),
        field('experience', 'Experience', experienceInput, { wide: true }),
        field('skills', 'Skills', skillsInput, { wide: true }),
        field('phone', 'Mobile number', phoneInput),
        field('joining_date', 'Joining date', joiningInput),
        field('employment_type', 'Joining as', employmentSel),
        field('wage_amount', 'Salary or wages', wageInput),
        field('pf_number', 'PF number', pfInput),
        field('esic_number', 'ESIC number', esicInput),
        field('reference', 'Reference', referenceInput, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn));
    const close = closeableModal(titleText, form);
    nameInput.focus();
  }

  function openAddPerson() {
    employeeForm({
      titleText: 'Add employee', submitLabel: 'Add employee', roles: cache?.roles || {},
      onSave: async (body) => {
        await api('/api/workforce', { method: 'POST', body });
        toast('Employee added');
        invalidateCache();
        route();
      },
    });
  }

  // p can be a lightweight roster row (no detail fields) or a full worker (from the detail page, which
  // has already loaded them) - either way, fetch the current detail fields fresh so Edit never starts
  // from stale or missing data.
  async function openEditPerson(p, roles, onChange) {
    let worker;
    try {
      worker = 'age' in p ? p : (await api(`/api/workforce/${p.id}`)).worker;
    } catch (err) {
      toast(err.message, true);
      return;
    }
    employeeForm({
      titleText: 'Edit employee', submitLabel: 'Save', worker, roles,
      onSave: async (body) => {
        await api(`/api/workforce/${p.id}`, { method: 'PATCH', body });
        toast('Employee updated');
        onChange();
      },
    });
  }

  async function deletePerson(p, { afterDelete } = {}) {
    const ok = await confirm(`Remove ${p.name}? This also removes their attendance history.`, { ok: 'Remove', danger: true, title: 'Remove employee' });
    if (!ok) return;
    try {
      await api(`/api/workforce/${p.id}`, { method: 'DELETE' });
      toast('Employee removed');
      invalidateCache();
      afterDelete?.();
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* ---------- Attendance sheet: lowest attendance first ---------- */

  const rate = (p) => (p.days ? p.present_days / p.days : 1);

  function sheetRow(p) {
    const pct = Math.round(rate(p) * 100);
    const fill = h('i', { class: pct >= 80 ? 'full' : pct < 50 ? 'low' : null });
    fill.style.width = `${pct}%`;
    return h('li', {}, h('a', { class: 'att-day people-row', href: `#p${p.id}` },
      h('div', { class: 'att-day-top' },
        h('span', { class: 'att-day-date' }, p.name),
        h('span', { class: 'att-day-hours', 'aria-label': `${p.present_days} of ${p.days} days` }, p.days ? `${p.present_days}/${p.days}` : '—')),
      h('span', { class: 'att-day-sub' }, p.days
        ? `${pct}% present · ${plural(p.days - p.present_days, 'day', 'days')} missed`
        : 'Not counted - started after this period'),
      p.days ? h('div', { class: 'att-bar', 'aria-hidden': 'true' }, fill) : null));
  }


  /* ---------- one person: every day they came and skipped, by week ---------- */

  function hoursBar(hours) {
    if (hours == null) return null;
    const fill = h('i', { class: hours >= 8 ? 'full' : null });
    fill.style.width = `${Math.min(100, (hours / 9) * 100)}%`;
    return h('div', { class: 'att-bar', 'aria-hidden': 'true' }, fill);
  }

  function presentRow(day, a) {
    const times = [a.check_in_at && `In ${fmtTime(a.check_in_at)}`, a.check_out_at && `Out ${fmtTime(a.check_out_at)}`].filter(Boolean).join(' · ');
    const sub = [a.project_code ? `${a.project_code} · ${a.project_title}` : null, times || 'No check-in or check-out time found']
      .filter(Boolean).join(' · ');
    const links = [mapLink(a.check_in_map_url, 'In location'), mapLink(a.check_out_map_url, 'Out location')].filter(Boolean);
    return h('li', { class: 'att-day' },
      h('div', { class: 'att-day-top' },
        h('span', { class: 'att-day-date' }, shortDate(day)),
        h('span', { class: 'att-day-hours' }, a.hours != null ? `${a.hours} h` : '')),
      h('span', { class: 'att-day-sub' }, sub),
      a.note ? h('span', { class: 'att-day-sub' }, a.note) : null,
      hoursBar(a.hours),
      links.length ? h('div', { class: 'att-day-links' }, links) : null);
  }

  function absentRow(day, a) {
    return h('li', { class: 'att-day' },
      h('div', { class: 'att-day-top' },
        h('span', { class: 'att-day-date' }, shortDate(day)),
        h('span', { class: 'chip chip-absent' }, 'Absent')),
      a && a.note ? h('span', { class: 'att-day-sub' }, a.note) : null);
  }

  function weeks(data) {
    const byDay = new Map(data.attendance.map((a) => [a.work_date, a]));
    const start = parseDay(data.period.start);
    const end = parseDay(data.period.end);
    const thisMonday = mondayOf(parseDay(data.today));
    const out = [];
    for (let monday = mondayOf(end); monday >= mondayOf(start); monday = addDays(monday, -7)) {
      const rows = [];
      let came = 0;
      let days = 0;
      let total = 0;
      for (let i = 6; i >= 0; i -= 1) {
        const day = addDays(monday, i);
        if (day < start || day > end) continue;
        days += 1;
        const a = byDay.get(dayKey(day));
        if (a && a.status === 'present') {
          came += 1;
          total += a.hours || 0;
          rows.push(presentRow(day, a));
        } else {
          rows.push(absentRow(day, a));
        }
      }
      const label = +monday === +thisMonday ? 'This week'
        : +monday === +addDays(thisMonday, -7) ? 'Last week'
          : `${dayMonth(monday)} – ${dayMonth(addDays(monday, 6))}`;
      out.push(h('section', { class: 'att-week' },
        h('div', { class: 'att-week-head' },
          h('h3', {}, label),
          h('span', { class: 'att-week-sum' }, `${roundHours(total)} h · ${came} of ${days} days`)),
        h('ul', { class: 'att-week-card' }, rows)));
    }
    return out;
  }

  /* ---------- one employee: HR details, and the salary/wages log ---------- */

  const EMPLOYMENT_LABEL = { regular: 'Regular', daily_wages: 'Daily wages' };
  const toNumber = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? 0 : Number(v));

  function detailsSection(w) {
    const rows = [
      ['Age', w.age], ['Qualification', w.qualification], ['Experience', w.experience],
      ['Skills', w.skills], ['Mobile number', w.phone],
      ['Joining date', w.joining_date ? shortDate(parseDay(w.joining_date)) : null],
      ['Joining as', EMPLOYMENT_LABEL[w.employment_type] || null],
      ['PF number', w.pf_number], ['ESIC number', w.esic_number], ['Reference', w.reference],
    ].filter(([, v]) => v);
    if (!rows.length) return null;
    return h('section', { class: 'fn-section' },
      h('span', { class: 'stat-label' }, 'Details'),
      h('dl', { class: 'pay-overview-grid' }, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])));
  }

  // The log's own labels are positional, same convention as a project's payment schedule.
  function paymentLabelFor(index) {
    const n = index + 1;
    const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th';
    return `${n}${suffix} payment`;
  }

  function paymentsSection(worker, id, currency, modes, onChange) {
    let steps = (worker.payments || []).map((p) => ({ ...p }));
    const stepsLabel = h('p', { class: 'steps-label' });
    const stepsList = h('div', { class: 'card-group step-list' });
    const paidNote = h('p', { class: 'wk-legend' });

    function toPayload(arr) {
      return arr.map((s, i) => ({
        label: (s.label || '').trim() || paymentLabelFor(i),
        amount: s.amount === '' || s.amount == null ? 0 : s.amount,
        mode: s.mode || '', paid_date: s.paid_date || null, comments: (s.comments || '').trim(),
      }));
    }

    async function persistSteps(next) {
      const saved = await api(`/api/workforce/${id}`, { method: 'PATCH', body: { payments: toPayload(next) } });
      steps = saved.worker.payments.map((p) => ({ ...p }));
      onChange(saved.worker);
      renderStepsList();
    }

    function renderStepsList() {
      const paid = steps.reduce((sum, s) => sum + (s.paid_date ? toNumber(s.amount) : 0), 0);
      stepsLabel.textContent = `Payments · ${steps.length}`;
      paidNote.textContent = steps.length ? `Paid so far: ${money(paid, currency)}` : '';
      clear(stepsList);
      steps.forEach((s, i) => {
        const isPaid = !!s.paid_date;
        const circle = isPaid
          ? h('span', { class: 'step-circle paid', 'aria-hidden': 'true' }, '✓')
          : h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(i + 1));
        const title = (s.label || '').trim() || paymentLabelFor(i);
        const subParts = isPaid ? [`Paid ${shortDate(parseDay(s.paid_date))}`, s.mode || null].filter(Boolean) : ['Not paid yet'];
        let sub = subParts.join(' · ');
        if (s.comments) sub += ' · note';
        stepsList.append(h('button', {
          type: 'button', class: 'step-row',
          'aria-label': `${title}, ${money(toNumber(s.amount), currency)}, ${isPaid ? 'paid' : 'not paid'}`,
          onclick: () => openStepSheet(i),
        },
          circle,
          h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, title), h('span', { class: 'step-sub' }, sub)),
          h('span', { class: 'step-amount' }, money(toNumber(s.amount), currency))));
      });
      stepsList.append(h('button', { type: 'button', class: 'step-row step-add', onclick: () => openStepSheet(steps.length) },
        h('span', { class: 'step-circle dashed', 'aria-hidden': 'true' }, '+'),
        h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, '+ Add payment'))));
    }

    function openStepSheet(index) {
      const isNew = index === steps.length;
      const current = isNew ? { label: '', amount: '', mode: '', paid_date: null, comments: '' } : steps[index];
      const trigger = document.activeElement;
      const overlay = h('div', { class: 'overlay' });
      const scroll = h('div', { class: 'drawer-scroll' });
      const foot = h('div', { class: 'drawer-foot' });
      const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });

      const finish = closeOnBack(() => {
        overlay.remove();
        drawer.remove();
        document.body.classList.remove('locked');
        if (trigger && trigger.isConnected) trigger.focus();
      });
      overlay.onclick = () => finish();
      const closeX = h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close' }, '×');
      closeX.onclick = () => finish();

      const labelInput = h('input', { type: 'text', maxlength: 120, value: current.label || '' });
      const amountInput = h('input', { type: 'number', id: 'f-amount', min: '0', step: 'any', inputmode: 'decimal', value: current.amount ?? '' });
      const chips = h('div', { class: 'step-chips' });
      if (worker.wage_amount != null) {
        chips.append(h('button', {
          type: 'button', class: 'btn small',
          onclick: () => { amountInput.value = worker.wage_amount; amountInput.dispatchEvent(new Event('input', { bubbles: true })); },
        }, `Wage/salary amount · ${money(worker.wage_amount, currency)}`));
      }

      const modeSel = selectField(
        [{ value: '', label: 'Mode of payment' }, ...modes.map((m) => ({ value: m, label: m }))],
        current.mode || '', { title: 'Mode of payment', placeholder: 'Mode of payment' });
      const paidDateInput = dateField(current.paid_date || '', { placeholder: 'Date of payment' });
      const modeField = field('mode', 'Mode of payment', modeSel);
      const dateFieldEl = field('paid_date', 'Date of payment', paidDateInput);
      const paidToggleInput = h('input', { type: 'checkbox', checked: !!current.paid_date });
      const paidToggle = h('label', { class: 'switch' },
        paidToggleInput, h('span', { class: 'switch-track', 'aria-hidden': 'true' }), h('span', { class: 'switch-thumb', 'aria-hidden': 'true' }));
      function todayIso() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      }
      function refreshPaidFields() {
        const on = paidToggleInput.checked;
        modeField.hidden = !on;
        dateFieldEl.hidden = !on;
        if (on && !paidDateInput.value) paidDateInput.value = todayIso();
        if (!on) { modeSel.value = ''; paidDateInput.value = ''; }
      }
      paidToggleInput.addEventListener('change', refreshPaidFields);
      refreshPaidFields();

      const noteTextarea = h('textarea', { rows: 2 });
      noteTextarea.value = current.comments || '';
      const noteField = field('comments', 'Note', noteTextarea);
      const noteToggleBtn = h('button', { type: 'button', class: 'link-btn' }, '+ Add a note');
      const hasNote = !!(current.comments || '').trim();
      noteField.hidden = !hasNote;
      noteToggleBtn.hidden = hasNote;
      noteToggleBtn.onclick = () => { noteField.hidden = false; noteToggleBtn.hidden = true; noteTextarea.focus(); };

      const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Save payment');
      saveBtn.onclick = async () => {
        errorBox.hidden = true;
        showFieldErrors(scroll, {});
        saveBtn.disabled = true;
        const draft = {
          label: labelInput.value, amount: amountInput.value, mode: modeSel.value,
          paid_date: paidDateInput.value || null, comments: noteTextarea.value,
        };
        const next = steps.slice();
        if (isNew) next.push(draft); else next[index] = draft;
        try {
          await persistSteps(next);
          toast('Payment saved');
          finish();
        } catch (err) {
          errorBox.textContent = (err.fields && err.fields.payments) || err.message;
          errorBox.hidden = false;
          saveBtn.disabled = false;
        }
      };

      let deleteBtn = null;
      if (!isNew) {
        deleteBtn = h('button', { type: 'button', class: 'link-btn step-sheet-delete' }, 'Delete');
        deleteBtn.onclick = async () => {
          const sure = await confirm(`Remove ${(current.label || '').trim() || paymentLabelFor(index)}?`, { ok: 'Delete', danger: true, title: 'Delete payment' });
          if (!sure) return;
          deleteBtn.disabled = true;
          const next = steps.slice();
          next.splice(index, 1);
          try {
            await persistSteps(next);
            toast('Payment removed');
            finish();
          } catch (err) {
            errorBox.textContent = (err.fields && err.fields.payments) || err.message;
            errorBox.hidden = false;
            deleteBtn.disabled = false;
          }
        };
      }

      const total = isNew ? steps.length + 1 : steps.length;
      const title = (current.label || '').trim() || paymentLabelFor(index);
      scroll.append(
        errorBox,
        field('label', 'Label', labelInput),
        h('div', { class: 'field' },
          h('label', { for: 'f-amount' }, 'Amount'),
          h('div', { class: 'amount-input-wrap' }, h('span', { class: 'amount-prefix', 'aria-hidden': 'true' }, currency), amountInput),
          chips,
          h('p', { class: 'err', id: 'err-amount', role: 'alert' })),
        h('div', { class: 'toggle-row' }, h('span', {}, 'Payment made'), paidToggle),
        modeField, dateFieldEl,
        noteToggleBtn, noteField);
      foot.append(saveBtn);

      const drawer = h('div', { class: 'drawer' },
        h('div', { class: 'drawer-head' },
          h('div', { class: 'sheet-handle', 'aria-hidden': 'true' }),
          h('div', { class: 'drawer-head-row' },
            h('div', { class: 'drawer-titles' },
              h('p', { class: 'step-sheet-eyebrow' }, `Payment ${index + 1} of ${total}`),
              h('h2', {}, title)),
            deleteBtn, closeX)),
        scroll);
      drawer.append(foot);
      document.body.classList.add('locked');
      document.body.append(overlay, drawer);
      (isNew ? amountInput : labelInput).focus();
    }

    renderStepsList();
    return h('section', { class: 'fn-section' },
      stepsLabel,
      paidNote,
      stepsList);
  }

  async function showPerson(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/workforce/${id}`); } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back')));
      return;
    }
    const key = data.worker.role_key || UNASSIGNED;
    const came = data.attendance.filter((a) => a.status === 'present').length;
    const days = data.period ? Math.round((parseDay(data.period.end) - parseDay(data.period.start)) / 86400000) + 1 : 0;
    const label = groupLabel(key, data.roles);
    LD.setAppbarBack?.(label, `#${key}`);
    const onChange = () => { invalidateCache(); window.location.hash = `#${key}`; };
    const onPaymentsChange = (freshWorker) => { data.worker = freshWorker; invalidateCache(); };
    clear(view).append(h('div', { class: 'people' },
      h('div', { class: 'att-head' },
        h('h2', {}, data.worker.name),
        h('span', { class: 'att-head-date' }, label)),
      detailsSection(data.worker),
      paymentsSection(data.worker, id, data.currency, data.payment_modes, onPaymentsChange),
      h('span', { class: 'stat-label' }, 'Attendance'),
      data.period
        ? h('p', { class: 'wk-legend' }, `Came ${came} of ${days} days, ${dayMonth(parseDay(data.period.start))} – ${dayMonth(parseDay(data.period.end))}`)
        : null,
      ...(data.period ? weeks(data) : [h('p', { class: 'empty-state' }, 'No attendance recorded for this person.')]),
      dataNote(data),
      h('div', { class: 'fn-actions fn-remove' },
        h('button', { class: 'btn small', type: 'button', onclick: () => openEditPerson(data.worker, data.roles, onChange) }, 'Edit'),
        h('button', { class: 'btn small danger', type: 'button', onclick: () => deletePerson(data.worker, { afterDelete: onChange }) }, 'Remove employee'))));
    window.scrollTo(0, 0);
  }

  /* ---------- routing: '' boxes, #manpower / #staff a group, #p12 a person ---------- */

  let cache = null;                                 // the group list, so going back from a person is instant

  async function route() {
    const hash = window.location.hash.slice(1);
    const person = /^p(\d+)$/.exec(hash);
    if (person) return showPerson(Number(person[1]));
    if (!cache) {
      clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
      try { cache = await load(); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    }
    return showList(cache, hash);
  }

  document.getElementById('add-person-btn')?.addEventListener('click', openAddPerson);

  window.addEventListener('hashchange', route);
  route();
})();
