/* Attendance: check yourself in and out once a day, optionally against a running project.
   Admin and the Accountant also get a Team tab with everyone's register for a chosen day. The admin doesn't
   check in at all (data-team-only): their Attendance is just that register. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, confirm, dateField } = window.LD;
  // Location, project picking and time helpers shared with the Me hub's check-in card (attendance-core.js).
  const { fmtTime, elapsedSince, renderToday } = window.ATT;
  const view = $('#view');
  const teamOnly = view.dataset.teamOnly === '1';

  const today = () => new Date().toISOString().slice(0, 10);

  function mapLink(a) {
    return a.check_in_map_url ? h('a', { class: 'att-map-link', href: a.check_in_map_url, target: '_blank', rel: 'noopener noreferrer' }, 'View location') : null;
  }

  /* Admin/Accountant only (the backend enforces this too) - removes a wrong or test record. A regular
     person cannot delete their own attendance; that would defeat the point of keeping one. */
  function deleteLink(a, onDeleted) {
    const link = h('a', { href: '#', class: 'att-delete-link' }, 'Delete');
    link.onclick = async (e) => {
      e.preventDefault();
      const sure = await confirm('Delete this attendance record? This cannot be undone.', { ok: 'Delete', danger: true, title: 'Delete record' });
      if (!sure) return;
      try {
        await api(`/api/attendance/${a.id}`, { method: 'DELETE' });
        toast('Record deleted');
        await onDeleted();
      } catch (err) {
        toast(err.message, true);
      }
    };
    return link;
  }

  /* ---------- dates and hours ---------- */

  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  const parseDay = (iso) => { const [y, m, d] = iso.split('-'); return new Date(+y, m - 1, +d); };
  const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
  const dayMonth = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  const shortDate = (d) => `${WEEKDAYS[d.getDay()]}, ${dayMonth(d)}`;               // "Sun, 27 Sep"
  const roundHours = (n) => Math.round(n * 10) / 10;

  /* The average time of day this person has checked out, over whatever history we have - a rough "you
     usually leave around" guide, not a target. null when nothing in the history has a check-out yet. */
  function usualFinish(history) {
    const outs = history.filter((a) => a.check_out_at).map((a) => new Date(a.check_out_at));
    if (!outs.length) return null;
    const avg = Math.round(outs.reduce((sum, d) => sum + d.getHours() * 60 + d.getMinutes(), 0) / outs.length);
    const at = new Date();
    at.setHours(Math.floor(avg / 60), avg % 60, 0, 0);
    return at.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  }

  function timesText(a) {
    return a.check_out_at
      ? h('span', { class: 'att-num' }, `${fmtTime(a.check_in_at)} – ${fmtTime(a.check_out_at)}`)
      : [h('span', { class: 'att-num' }, fmtTime(a.check_in_at)), ' – still checked in'];
  }

  /* 4px bar filled to hours/9 (a full day plus lunch), green once it reaches 8 h, amber when shorter. */
  function hoursBar(hours) {
    if (hours == null) return null;
    const fill = h('i', { class: hours >= 8 ? 'full' : null });
    fill.style.width = `${Math.min(100, (hours / 9) * 100)}%`;
    return h('div', { class: 'att-bar', 'aria-hidden': 'true' }, fill);
  }

  /* One day (or, on the Team screen, one person) as a row inside a white card. */
  function dayRow({ title, right, sub, hours, links }) {
    const shownLinks = (links || []).filter(Boolean);
    return h('li', { class: 'att-day' },
      h('div', { class: 'att-day-top' }, h('span', { class: 'att-day-date' }, title), right),
      sub ? h('span', { class: 'att-day-sub' }, sub) : null,
      hoursBar(hours),
      shownLinks.length ? h('div', { class: 'att-day-links' }, shownLinks) : null);
  }

  function recordRow(title, a, onDeleted) {
    return dayRow({
      title,
      right: h('span', { class: 'att-day-hours' }, a.hours != null ? `${a.hours} h` : ''),
      sub: a.work_label ? [a.work_label, ' · ', timesText(a)] : timesText(a),
      hours: a.hours,
      links: [mapLink(a), onDeleted ? deleteLink(a, onDeleted) : null],
    });
  }

  /* History grouped into Mon–Sun weeks, newest first. A past Mon–Sat with no record, inside the span the
     history covers, is marked Absent; Sundays and today (still time to check in) never are. */
  function historyWeeks(history, onDeleted) {
    if (!history.length) return [h('p', { class: 'empty-state att-history-empty' }, 'No attendance recorded yet.')];
    const byDay = new Map(history.map((a) => [a.work_date, a]));
    const todayDate = parseDay(dayKey(new Date()));
    const firstDay = parseDay(history.reduce((min, a) => (a.work_date < min ? a.work_date : min), history[0].work_date));
    const thisMonday = mondayOf(todayDate);
    const weeks = [];

    for (let monday = thisMonday; monday >= mondayOf(firstDay); monday = addDays(monday, -7)) {
      const rows = [];
      let worked = 0;
      let absent = 0;
      let total = 0;
      for (let i = 6; i >= 0; i -= 1) {
        const day = addDays(monday, i);
        if (day < firstDay || day > todayDate) continue;
        const a = byDay.get(dayKey(day));
        if (a) {
          worked += 1;
          total += a.hours || 0;
          rows.push(recordRow(shortDate(day), a, onDeleted));
        } else if (day < todayDate && day.getDay() !== 0) {
          absent += 1;
          rows.push(dayRow({ title: shortDate(day), right: h('span', { class: 'chip chip-absent' }, 'Absent') }));
        }
      }
      if (!rows.length) continue;
      const label = +monday === +thisMonday ? 'This week'
        : +monday === +addDays(thisMonday, -7) ? 'Last week'
          : `${dayMonth(monday)} – ${dayMonth(addDays(monday, 6))}`;
      weeks.push(h('section', { class: 'att-week' },
        h('div', { class: 'att-week-head' },
          h('h3', {}, label),
          h('span', { class: 'att-week-sum' }, `${roundHours(total)} h · ${worked} of ${worked + absent} days`)),
        h('ul', { class: 'att-week-card' }, rows)));
    }
    return weeks;
  }

  /* ---------- today's timeline ---------- */

  // The same check the bottom nav's "Won / Lost" item draws.
  const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';

  /* state: 'done' (green check), 'current' (hollow ring), 'active' (tinted ring) or 'pending' (grey dot). */
  function marker(state) {
    let mark;
    if (state === 'done') { mark = h('i', { class: 'check' }); mark.innerHTML = CHECK_SVG; }
    else if (state === 'current') mark = h('i', { class: 'ring' });
    else if (state === 'active') mark = h('i', { class: 'ring filled' });
    else mark = h('i', { class: 'dot' });
    return h('span', { class: 'att-marker' }, mark);
  }

  function step(state, label, right, ...body) {
    return h('li', { class: `att-step ${state === 'done' || state === 'pending' ? state : 'current'}` },
      marker(state),
      h('div', { class: 'att-step-body' },
        h('div', { class: 'att-step-top' }, h('span', { class: 'att-step-label' }, label), right),
        body));
  }

  let elapsedTimer = null;
  const stopElapsedTimer = () => { clearInterval(elapsedTimer); elapsedTimer = null; };

  /* The Team link lives in the app bar, outside #view, so it is added and removed by hand. */
  function setTeamLink(show) {
    const existing = document.getElementById('att-team-link');
    if (existing) existing.remove();
    const actions = document.querySelector('.appbar-actions');
    if (show && actions) actions.append(h('a', { id: 'att-team-link', class: 'att-team-link', href: '#team' }, 'Team'));
  }

  /* ---------- my attendance ---------- */

  async function showMine() {
    LD.resetAppbarBack?.();
    stopElapsedTimer();
    clear(view).append(h('p', { class: 'loading' }, 'Loading attendance…'));
    let data;
    try { data = await api('/api/attendance/state'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    setTeamLink(data.can_see_team);

    const cardBox = h('div', {});
    const historyBox = h('div', {});
    const barBox = h('div', {});

    function renderHistory() {
      clear(historyBox).append(...historyWeeks(data.history, data.can_see_team ? reload : null));
    }

    /* Check-in and check-out both change today's row and add (or change) it in the history right below it,
       so re-fetch the whole screen's data after either one instead of only patching the card. */
    async function reload() {
      try {
        data = await api('/api/attendance/state');
        renderCard();
        renderHistory();
      } catch (err) {
        toast(err.message, true);
      }
    }

    /* The sticky bottom bar; the body gets extra bottom padding while it is up so nothing hides behind it. */
    function actionBar(...kids) {
      document.body.classList.add('has-att-bar');
      return h('div', { class: 'att-actionbar' }, h('div', { class: 'att-actionbar-inner' }, kids));
    }

    function renderCard() {
      stopElapsedTimer();
      document.body.classList.remove('has-att-bar');
      const t = data.today;
      let steps;
      let bar = null;
      if (!t) {
        // Not checked in yet (or today's record was just deleted): the same dark card with one big Check in
        // button as the Me hub - it asks for the location and the project itself (attendance-core.js).
        const box = h('section', { class: 'me-today att-today-dark', 'aria-live': 'polite', 'aria-label': 'Today' });
        renderToday(box, data, { onChange: reload, historyLink: false });
        clear(cardBox).append(box);
        clear(barBox);
        return;
      }
      const links = [mapLink(t), data.can_see_team ? deleteLink(t, reload) : null].filter(Boolean);
      const checkedIn = step('done', 'Checked in', h('span', { class: 'att-step-time' }, fmtTime(t.check_in_at)),
        h('span', { class: 'att-step-sub' }, t.work_label),
        links.length ? h('div', { class: 'att-day-links' }, links) : null);

      if (!t.check_out_at) {
        // TODO: "Switch project" mid-day - needs a new endpoint that changes today's project_id.
        const elapsed = h('span', { class: 'att-elapsed' }, elapsedSince(t.check_in_at));
        elapsedTimer = setInterval(() => { elapsed.textContent = elapsedSince(t.check_in_at); }, 30000);
        const finish = usualFinish(data.history);
        steps = [
          checkedIn,
          step('active', 'Working', elapsed, finish ? h('span', { class: 'att-step-note' }, 'Usual finish around ', h('span', { class: 'att-num' }, finish)) : null),
          step('pending', 'Check out', null),
        ];

        const checkOutBtn = h('button', { class: 'btn ink', type: 'button' }, 'Check out');
        checkOutBtn.onclick = async () => {
          checkOutBtn.disabled = true;
          try {
            await api('/api/attendance/check-out', { method: 'POST' });
            toast('Checked out');
            await reload();
          } catch (err) {
            toast(err.message, true);
            checkOutBtn.disabled = false;
          }
        };
        bar = actionBar(checkOutBtn);
      } else {
        steps = [
          checkedIn,
          step('done', 'Working', null),
          step('done', 'Checked out', h('span', { class: 'att-step-time' }, fmtTime(t.check_out_at)),
            h('span', { class: 'att-step-sub' }, h('span', { class: 'att-num' }, `${t.hours} h`), ' total')),
        ];
      }
      clear(cardBox).append(h('div', { class: 'att-today' }, h('ol', { class: 'att-steps' }, steps)));
      clear(barBox);
      if (bar) barBox.append(bar);
    }
    renderCard();
    renderHistory();

    clear(view).append(h('div', {},
      h('div', { class: 'att-head' },
        h('h2', {}, 'Today'),
        h('span', { class: 'att-head-date' }, shortDate(new Date()))),
      cardBox,
      historyBox,
      barBox));
  }

  /* ---------- team register (admin, accounts) ---------- */

  async function showTeam() {
    if (!teamOnly) LD.setAppbarBack?.('Your attendance', '#');
    stopElapsedTimer();
    setTeamLink(false);
    document.body.classList.remove('has-att-bar');
    clear(view).append(h('p', { class: 'loading' }, 'Loading team attendance…'));
    const dateInput = dateField(today(), { clearable: false });
    dateInput.setAttribute('aria-label', 'Date');
    const list = h('ul', { class: 'att-week-card att-team-list' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });

    async function refresh() {
      clear(list).append(h('li', { class: 'loading' }, 'Loading…'));
      try {
        const data = await api(`/api/attendance/team?date=${encodeURIComponent(dateInput.value)}`);
        count.textContent = plural(data.records.length, 'person', 'people') + ' checked in';
        clear(list);
        if (!data.records.length) { list.append(h('li', { class: 'empty-state' }, 'Nobody checked in on this day.')); return; }
        data.records.forEach((a) => list.append(recordRow(a.user_name, a, refresh)));
      } catch (err) {
        clear(list).append(h('li', { class: 'empty-state' }, err.message));
      }
    }
    dateInput.onchange = refresh;

    clear(view).append(h('div', {},
      // The top bar already says "Team attendance" for the admin (team_only) - only worth repeating
      // in-page for someone whose top bar still says "Your attendance" while they're looking at this;
      // the way back for them is the appbar's own back link (set above), not an in-page one.
      teamOnly ? null : h('div', { class: 'list-head' }, h('h2', {}, 'Team attendance')),
      h('div', { class: 'filters' }, dateInput), count, list));
    refresh();
  }

  function route() {
    if (teamOnly || window.location.hash === '#team') return showTeam();
    return showMine();
  }

  window.addEventListener('hashchange', route);
  route();
})();
