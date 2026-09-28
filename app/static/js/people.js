/* Manpower & staff, and the Attendance sheet (admin only): field workers and office staff who don't sign
   in to the app, tracked from the WhatsApp groups they mark attendance in. Both pages open straight on
   the list of people, with a search and chips for All and each group (Manpower, Staff):
   - Manpower & staff (data-mode="roster"): each person, where they worked on their most recent working
     day, and the last 7 days as green (present) / red (absent) dots. A person opens a popup: their current
     site, average hours, and the last 2 weeks as dates circled green or red.
   - Attendance sheet (data-mode="sheet"): everyone ranked by attendance, lowest first.
   On the sheet, a person opens their day-by-day record, laid out like Your attendance's history.
   Workers often work Sundays, so every day counts here (unlike Your attendance, which skips Sundays). The
   data arrives through imports, so days after the last one are "no data yet" - never marked absent. */
(() => {
  'use strict';

  const { $, h, clear, api, plural } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;
  const GROUPS = { manpower: 'Manpower', staff: 'Staff' };

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

  /* ---------- Manpower & staff: where each person is, and their last 7 days ---------- */

  const DOT_LABEL = { present: 'present', absent: 'absent', none: 'no data yet' };

  function weekDots(week) {
    const present = week.filter((d) => d.status === 'present').length;
    return h('span', { class: 'wk-dots', role: 'img', 'aria-label': `Present ${present} of the last ${week.length} days` },
      week.map((d) => h('i', { class: `wk-dot ${d.status}`, title: `${shortDate(parseDay(d.date))}: ${DOT_LABEL[d.status]}` })));
  }

  function rosterRow(p, today) {
    const dep = p.deployed;
    const where = dep
      ? [relativeDay(dep.date, today), dep.project_code ? `${dep.project_code} · ${dep.project_title}` : 'site not recorded'].join(' · ')
      : 'No working day on record';
    return h('li', {}, h('button', { type: 'button', class: 'att-day people-row', onclick: () => openPerson(p) },
      h('div', { class: 'att-day-top' }, h('span', { class: 'att-day-date' }, p.name), weekDots(p.week)),
      h('span', { class: 'att-day-sub' }, where)));
  }

  const groupLabel = (k) => GROUPS[k] || k.charAt(0).toUpperCase() + k.slice(1);

  // The list both pages open on: a search by name and a chip per group, taken from the groups the data
  // actually has (not a fixed list), plus All. Manpower & staff lists by name with the week's dots; the
  // Attendance sheet lists lowest attendance first. The chip in use goes into the address (#manpower,
  // #staff), so coming back from a person lands on the same one.
  function showList(data, key) {
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
    const row = sheet ? sheetRow : (p) => rosterRow(p, data.today);

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
      heading.textContent = state.group === 'all' ? 'Everyone' : groupLabel(state.group);
      count.textContent = plural(people.length, 'person', 'people');
      clear(chips).append(...[['all', 'All', groups.reduce((n, g) => n + data[g].length, 0)],
        ...groups.map((g) => [g, groupLabel(g), data[g].length])].map(([value, label, n]) => h('button', {
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

  function openPerson(p) {
    const opener = document.activeElement;
    const body = h('div', { class: 'fn-body' }, h('p', { class: 'loading' }, 'Loading…'));
    const closeBtn = h('button', { type: 'button', class: 'icon-x', 'aria-label': 'Close' }, '×');
    const card = h('div', { class: 'confirm-card fn-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'fn-title' },
      h('div', { class: 'fn-head' },
        h('div', {}, h('h2', { id: 'fn-title' }, p.name), h('span', { class: 'fn-group' }, GROUPS[p.category] || '')),
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
      .then((data) => clear(body).append(...popupBody(p, data)))
      .catch((err) => clear(body).append(h('p', { class: 'empty-state' }, err.message)));
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

  async function showPerson(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/workforce/${id}`); } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back')));
      return;
    }
    const key = data.worker.category;
    const came = data.attendance.filter((a) => a.status === 'present').length;
    const days = data.period ? Math.round((parseDay(data.period.end) - parseDay(data.period.start)) / 86400000) + 1 : 0;
    clear(view).append(h('div', { class: 'people' },
      h('a', { class: 'back-link', href: `#${key}` }, `← ${GROUPS[key] || 'Back'}`),
      h('div', { class: 'att-head' },
        h('h2', {}, data.worker.name),
        h('span', { class: 'att-head-date' }, GROUPS[key] || '')),
      data.period
        ? h('p', { class: 'wk-legend' }, `Came ${came} of ${days} days, ${dayMonth(parseDay(data.period.start))} – ${dayMonth(parseDay(data.period.end))}`)
        : null,
      ...(data.period ? weeks(data) : [h('p', { class: 'empty-state' }, 'No attendance recorded for this person.')]),
      dataNote(data)));
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

  window.addEventListener('hashchange', route);
  route();
})();
