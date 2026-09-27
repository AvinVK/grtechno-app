/* Manpower & staff, and the Attendance sheet (admin only): field workers and office staff who don't sign
   in to the app, tracked from the WhatsApp groups they mark attendance in. Both pages open on two boxes,
   Manpower and Staff, with a head count each; a box opens that group's people:
   - Manpower & staff (data-mode="roster"): each person, where they worked on their most recent working
     day, and the last 7 days as green (present) / red (absent) dots.
   - Attendance sheet (data-mode="sheet"): everyone ranked by attendance, lowest first.
   Either way, a person opens their day-by-day record, laid out like Your attendance's history.
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

  /* ---------- the two boxes ---------- */

  async function load() {
    return api('/api/workforce');
  }

  function showBoxes(data) {
    // Under each count: on Manpower & staff, how many were at work on the latest day we have data for;
    // on the Attendance sheet, the group's average attendance over the period.
    const note = (key) => {
      const people = data[key];
      if (!data.data_until || !people.length) return plural(people.length, 'person', 'people');
      if (mode === 'sheet') {
        const counted = people.filter((p) => p.days);
        const avg = counted.length ? Math.round((counted.reduce((sum, p) => sum + rate(p), 0) / counted.length) * 100) : 0;
        return `${avg}% average attendance`;
      }
      const atWork = people.filter((p) => p.deployed && p.deployed.date === data.data_until).length;
      const on = relativeDay(data.data_until, data.today);
      return `${atWork} at work ${on === 'Today' || on === 'Yesterday' ? on.toLowerCase() : `on ${dayMonth(parseDay(data.data_until))}`}`;
    };
    const box = (key) => h('a', { class: 'stat', href: `#${key}` },
      h('span', { class: 'stat-label' }, `Total ${GROUPS[key].toLowerCase()}`),
      h('span', { class: 'stat-value' }, data[key].length),
      h('span', { class: 'stat-note' }, note(key)));
    clear(view).append(h('div', { class: 'people' },
      h('div', { class: 'list-head' }, h('h2', {}, mode === 'sheet' ? 'Attendance sheet' : 'Manpower & staff')),
      h('div', { class: 'people-boxes' }, box('manpower'), box('staff')),
      dataNote(data)));
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
    return h('li', {}, h('a', { class: 'att-day people-row', href: `#p${p.id}` },
      h('div', { class: 'att-day-top' }, h('span', { class: 'att-day-date' }, p.name), weekDots(p.week)),
      h('span', { class: 'att-day-sub' }, where)));
  }

  function showRoster(data, key) {
    const people = data[key];
    const legend = h('p', { class: 'wk-legend' },
      'Last 7 days, oldest first: ',
      h('i', { class: 'wk-dot present' }), ' present ',
      h('i', { class: 'wk-dot absent' }), ' absent ',
      h('i', { class: 'wk-dot none' }), ' no data yet');
    clear(view).append(h('div', { class: 'people' },
      h('a', { class: 'back-link', href: '#' }, `← ${mode === 'sheet' ? 'Attendance sheet' : 'Manpower & staff'}`),
      h('div', { class: 'list-head' }, h('h2', {}, GROUPS[key]), h('span', { class: 'att-week-sum' }, plural(people.length, 'person', 'people'))),
      legend,
      people.length
        ? h('ul', { class: 'att-week-card' }, people.map((p) => rosterRow(p, data.today)))
        : h('p', { class: 'empty-state' }, `No ${GROUPS[key].toLowerCase()} yet.`),
      dataNote(data)));
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

  function showSheet(data, key) {
    const people = [...data[key]].sort((a, b) => rate(a) - rate(b) || a.name.localeCompare(b.name));
    const period = data.period
      ? `${dayMonth(parseDay(data.period.start))} – ${dayMonth(parseDay(data.period.end))}`
      : null;
    clear(view).append(h('div', { class: 'people' },
      h('a', { class: 'back-link', href: '#' }, '← Attendance sheet'),
      h('div', { class: 'list-head' }, h('h2', {}, GROUPS[key]), period ? h('span', { class: 'att-week-sum' }, period) : null),
      h('p', { class: 'wk-legend' }, 'Lowest attendance first.'),
      people.length
        ? h('ul', { class: 'att-week-card' }, people.map(sheetRow))
        : h('p', { class: 'empty-state' }, `No ${GROUPS[key].toLowerCase()} yet.`),
      dataNote(data)));
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
    if (GROUPS[hash]) return mode === 'sheet' ? showSheet(cache, hash) : showRoster(cache, hash);
    return showBoxes(cache);
  }

  window.addEventListener('hashchange', route);
  route();
})();
