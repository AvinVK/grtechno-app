/* Worker list (admin only): field workers who don't sign in to the app, tracked instead from the WhatsApp
   group where they mark their attendance. Read-only - the data comes from a one-off import. */
(() => {
  'use strict';

  const { $, h, clear, api, plural } = window.LD;
  const view = $('#view');

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-');
    return new Date(Date.UTC(+y, m - 1, +d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }

  function fmtTime(iso) {
    if (!iso) return null;
    return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  }

  function mapLink(url, label) {
    return url ? h('a', { class: 'att-map-link', href: url, target: '_blank', rel: 'noopener noreferrer' }, label) : null;
  }

  /* ---------- list ---------- */

  async function showList() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading workers…'));
    let data;
    try { data = await api('/api/workers'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const list = h('ul', { class: 'rows' });
    if (!data.workers.length) {
      list.append(h('li', { class: 'empty-state' }, 'No workers yet.'));
    } else {
      data.workers.forEach((w) => list.append(h('li', {}, h('a', { class: 'p-row', href: `#w${w.id}` },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, w.name),
          h('span', { class: 'row-sub' }, w.last_seen ? `Last seen ${fmtDate(w.last_seen)}` : 'Never seen')),
        h('span', { class: 'row-value' }, plural(w.days_present, 'day', 'days')),
        h('span', { class: 'p-foot' }, h('span', { class: 'p-code' }, `of the last ${w.window_days} days`))))));
    }

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'Worker list')),
      h('p', { class: 'hint workers-intro' },
        'From the WhatsApp attendance group. Anyone who messaged it in the last 6 months is listed here, ' +
        'with their attendance for the last two weeks below their name.'),
      list));
  }

  /* ---------- one worker ---------- */

  function attendanceRow(a) {
    const times = [a.check_in_at && `In ${fmtTime(a.check_in_at)}`, a.check_out_at && `Out ${fmtTime(a.check_out_at)}`]
      .filter(Boolean).join(' · ') || 'No check-in or check-out time found';
    return h('li', { class: 'att-row' },
      h('span', { class: 'att-main' },
        h('span', { class: 'row-title' }, fmtDate(a.work_date)),
        h('span', { class: 'row-sub' }, times),
        mapLink(a.check_in_map_url, 'In location'), mapLink(a.check_out_map_url, 'Out location'),
        a.note ? h('span', { class: 'row-sub' }, a.note) : null),
      h('span', { class: 'row-value' }, a.hours != null ? `${a.hours} h` : ''));
  }

  async function showDetail(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading worker…'));
    let data;
    try { data = await api(`/api/workers/${id}`); } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to worker list')));
      return;
    }

    const list = h('ul', { class: 'rows att-history' },
      data.attendance.length ? data.attendance.map(attendanceRow) : h('li', { class: 'empty-state' }, 'No attendance found for this worker in the last two weeks.'));

    clear(view).append(h('div', {},
      h('a', { class: 'back-link', href: '#' }, '← Worker list'),
      h('div', { class: 'p-head' }, h('h2', {}, data.worker.name)),
      h('p', { class: 'hint' }, data.worker.last_seen ? `Last seen ${fmtDate(data.worker.last_seen)}` : 'Never seen'),
      h('h3', { class: 'att-sub-head' }, `Attendance, last ${data.window_days} days`),
      list));
    window.scrollTo(0, 0);
  }

  function route() {
    const m = /^#w(\d+)$/.exec(window.location.hash);
    if (m) return showDetail(Number(m[1]));
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
