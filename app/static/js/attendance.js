/* Attendance: check yourself in and out as many times a day as you like (a lunch break, a second site),
   optionally against a running project. Admin and the Accountant also get a Team link with everyone's
   register for a chosen day. The admin doesn't check in at all (data-team-only): their Attendance is just
   that register. Anyone who can also see the workforce module gets a second subtab, "Attendance register"
   (kohal, 2026-10-20) - everyone ranked by attendance, lowest first; see showRegister below, and
   app/workers.py/people.js for the fuller page (HR details, payments, day-by-day record) it links out to. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, confirm, dateField, pickList, field, closeOnBack } = window.LD;
  // Location, project picking and time helpers shared with the Me hub's check-in card (attendance-core.js).
  const { fmtTime, elapsedSince, renderToday } = window.ATT;
  const view = $('#view');
  const teamOnly = view.dataset.teamOnly === '1';
  const canSeeWorkforce = view.dataset.canSeeWorkforce === '1';

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

  // Pending/rejected shows right next to the time - approved (the common case) gets no chip of its own
  // (see Attendance.status, kohal, 2026-10-16).
  function statusChip(a) {
    if (a.status === 'pending') return h('span', { class: 'chip chip-today' }, 'Pending');
    if (a.status === 'rejected') return h('span', { class: 'chip chip-off' }, 'Rejected');
    return null;
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
      right: h('span', { class: 'att-day-right' }, statusChip(a), h('span', { class: 'att-day-hours' }, a.hours != null ? `${a.hours} h` : '')),
      sub: a.work_label ? [a.work_label, ' · ', timesText(a)] : timesText(a),
      hours: a.hours,
      links: [mapLink(a), onDeleted ? deleteLink(a, onDeleted) : null],
    });
  }

  /* Picks which of a day's more-than-one sessions to delete, then deletes it the same way deleteLink
     does - there's no room for a delete link per session once they're joined onto one line (see
     groupedDayRow), so this is reached through one shared "Delete" link for the day instead. */
  async function deleteOneOf(sessions, onDeleted) {
    const id = await pickList(
      sessions.map((a) => ({ value: String(a.id), label: a.check_out_at ? `${fmtTime(a.check_in_at)} – ${fmtTime(a.check_out_at)}` : `${fmtTime(a.check_in_at)} – still checked in` })),
      '', { title: 'Delete which session?' },
    );
    if (!id) return;
    const sure = await confirm('Delete this attendance record? This cannot be undone.', { ok: 'Delete', danger: true, title: 'Delete record' });
    if (!sure) return;
    try {
      await api(`/api/attendance/${id}`, { method: 'DELETE' });
      toast('Record deleted');
      await onDeleted();
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* A day with more than one check-in/out that day - one line per session ("7:00 am – 1:00 pm · Sprinkler
     install", "2:00 pm – 7:00 pm · Office work"), so which project each stretch of the day was against
     stays visible even when it changed session to session, not just the times joined together (kohal,
     2026-10-16). The day's total hours shows where a single session's row would show its own. */
  function groupedDayRow(title, sessions, onDeleted) {
    const totalHours = sessions.reduce((sum, a) => sum + (a.hours || 0), 0);
    const lines = sessions.map((a) => h('span', { class: 'att-day-sub-line' },
      a.work_label ? [a.work_label, ' · ', timesText(a)] : timesText(a), statusChip(a) ? [' ', statusChip(a)] : null));
    return dayRow({
      title,
      right: h('span', { class: 'att-day-hours' }, totalHours ? `${roundHours(totalHours)} h` : ''),
      sub: lines,
      hours: totalHours,
      links: [onDeleted ? h('a', { href: '#', class: 'att-delete-link', onclick: (e) => { e.preventDefault(); deleteOneOf(sessions, onDeleted); } }, 'Delete') : null],
    });
  }

  /* History grouped into Mon–Sun weeks, newest first. A past Mon–Sat with no session at all, inside the
     span the history covers, is marked Absent; Sundays and today (still time to check in) never are. More
     than one session on the same day (a lunch break, a second site) becomes one row with every session's
     times joined and the day's total hours - see groupedDayRow. */
  function historyWeeks(history, onDeleted) {
    if (!history.length) return [h('p', { class: 'empty-state att-history-empty' }, 'No attendance recorded yet.')];
    const byDay = new Map();
    for (const a of history) {
      if (!byDay.has(a.work_date)) byDay.set(a.work_date, []);
      byDay.get(a.work_date).push(a);
    }
    for (const sessions of byDay.values()) sessions.sort((a, b) => a.check_in_at.localeCompare(b.check_in_at));
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
        const sessions = byDay.get(dayKey(day));
        if (sessions && sessions.length) {
          // Only an approved session counts toward the week's worked days/hours (see Attendance.status) -
          // a day with nothing approved but something rejected counts as absent instead (kohal, 2026-10-20:
          // "if the attendance is rejected, it should show absent for the person"), same as a day with no
          // session at all; a still-pending one (no approval yet, nothing rejected either) stays uncounted
          // either way until it's decided. The row itself still shows its own "Rejected" chip either way -
          // more specific than a plain Absent would be.
          const approved = sessions.filter((a) => a.status === 'approved');
          if (approved.length) {
            worked += 1;
            total += approved.reduce((sum, a) => sum + (a.hours || 0), 0);
          } else if (sessions.some((a) => a.status === 'rejected')) {
            absent += 1;
          }
          rows.push(sessions.length === 1 ? recordRow(shortDate(day), sessions[0], onDeleted) : groupedDayRow(shortDate(day), sessions, onDeleted));
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

  /* ---------- marking yourself absent ahead of time (kohal, 2026-10-19: "For absent provide option within
     check in tab ... Absent should be inform 1 day before") - daily-wage workers only (can_mark_absent),
     same shape as a pending check-in: waits for the admin or a project manager to see it (not tied to any
     one project - see app/attendance.py's absence routes). ---------- */

  function absenceStatusChip(status) {
    if (status === 'pending') return h('span', { class: 'chip chip-today' }, 'Pending');
    if (status === 'rejected') return h('span', { class: 'chip chip-off' }, 'Rejected');
    return h('span', { class: 'chip chip-active' }, 'Noted');
  }

  function absenceRow(a) {
    return h('li', { class: 'att-day' },
      h('div', { class: 'att-day-top' }, h('span', { class: 'att-day-date' }, shortDate(parseDay(a.for_date))), absenceStatusChip(a.status)),
      a.reason ? h('span', { class: 'att-day-sub' }, a.reason) : null);
  }

  function openAbsenceSheet(onDone) {
    const tomorrowIso = dayKey(addDays(new Date(), 1));
    const dateInput = dateField(tomorrowIso, { clearable: false });
    const reasonInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off', placeholder: 'e.g. Family function' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Mark absent');
    const finish = closeOnBack(() => overlay.remove());
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay', onclick: (e) => { if (e.target === overlay) finish(); } });
    cancelBtn.onclick = () => finish();
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api('/api/attendance/absences', { method: 'POST', body: { for_date: dateInput.value, reason: reasonInput.value } });
        finish();
        toast('Thanks for letting them know');
        onDone();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        saveBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Mark yourself absent'),
      field('for_date', 'Which day', dateInput),
      field('reason', 'Reason (optional)', reasonInput),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
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

  /* "Today's attendance" / "Attendance register" subtabs - same .stage-filter/.filter-chip pattern as
     Work plan/Announcements (app/static/js/workplan.js), kohal, 2026-10-20: "cant both be clubbed and
     shown as 2 subtabs? attendance register and today's attendance" (an earlier, lighter attempt just
     linked out to the Attendance sheet page from the app bar - this replaces that). Only shown to someone
     who can also see the register; "Today's attendance" covers both the Mine and Team screens, which stay
     reachable from each other the same way they always were (the "Team" app-bar link, untouched). */
  function tabs(active) {
    if (!canSeeWorkforce) return null;
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Attendance section' },
      h('a', { class: 'filter-chip', href: window.location.pathname, 'aria-current': active === 'today' ? 'page' : null }, "Today's attendance"),
      h('a', { class: 'filter-chip', href: '#register', 'aria-current': active === 'register' ? 'page' : null }, 'Attendance register'));
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
    const absenceBox = h('div', {});
    const historyBox = h('div', {});
    const barBox = h('div', {});

    function renderHistory() {
      clear(historyBox).append(...historyWeeks(data.history, data.can_see_team ? reload : null));
    }

    function renderAbsence() {
      if (!data.can_mark_absent) { clear(absenceBox); return; }
      const markBtn = h('button', { class: 'btn small', type: 'button' }, 'Mark myself absent');
      markBtn.onclick = () => openAbsenceSheet(reload);
      clear(absenceBox).append(h('section', { class: 'att-week' },
        h('div', { class: 'att-week-head' }, h('h3', {}, 'Absence notices'), markBtn),
        data.my_absences.length
          ? h('ul', { class: 'att-week-card' }, data.my_absences.map(absenceRow))
          : h('p', { class: 'hint' }, "Letting them know a day ahead you won't be in - at least a day before.")));
    }

    /* Check-in and check-out both change today's row and add (or change) it in the history right below it,
       so re-fetch the whole screen's data after either one instead of only patching the card. */
    async function reload() {
      try {
        data = await api('/api/attendance/state');
        renderCard();
        renderAbsence();
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
      // t is always the open session here (data.today is null otherwise, handled above) - so this is
      // always the "still checked in" timeline; once they check out, the very next render falls into the
      // !t branch above instead (Check in again), earlier sessions today showing in the history below.
      const links = [mapLink(t), data.can_see_team ? deleteLink(t, reload) : null].filter(Boolean);
      const checkedIn = step('done', 'Checked in', h('span', { class: 'att-step-time' }, fmtTime(t.check_in_at)),
        h('span', { class: 'att-step-sub' }, t.work_label),
        links.length ? h('div', { class: 'att-day-links' }, links) : null);

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
          if (await ATT.checkOut({ petrol: !!data.petrol_required })) {
            toast('Checked out');
            await reload();
            return;
          }
          checkOutBtn.disabled = false;
        } catch (err) {
          toast(err.message, true);
          checkOutBtn.disabled = false;
        }
      };
      bar = actionBar(checkOutBtn);
      // The admin can reject an open session without closing it (kohal, 2026-10-20: "what will the person
      // who's attendance was rejectedd, see" - answered: nothing at all until now, it just sat as a
      // "Rejected" chip further down in their own history) - this banner is the only thing on the live card
      // itself that says so; the session stays open and Check out still works exactly the same either way.
      const rejectedNotice = t.status === 'rejected'
        ? h('p', { class: 'notice error' }, `Rejected by ${t.approved_by_name || 'the admin'} - you can still check out, but this session won't count toward your attendance.`)
        : null;
      clear(cardBox).append(h('div', {}, rejectedNotice, h('div', { class: 'att-today' }, h('ol', { class: 'att-steps' }, steps))));
      clear(barBox);
      if (bar) barBox.append(bar);
    }
    renderCard();
    renderAbsence();
    renderHistory();

    clear(view).append(h('div', {},
      tabs('today'),
      h('div', { class: 'att-head' },
        h('h2', {}, 'Today'),
        h('span', { class: 'att-head-date' }, shortDate(new Date()))),
      cardBox,
      absenceBox,
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
      tabs('today'),
      // The top bar already says "Team attendance" for the admin (team_only) - only worth repeating
      // in-page for someone whose top bar still says "Your attendance" while they're looking at this;
      // the way back for them is the appbar's own back link (set above), not an in-page one.
      teamOnly ? null : h('div', { class: 'list-head' }, h('h2', {}, 'Team attendance')),
      h('div', { class: 'filters' }, dateInput), count, list));
    refresh();
  }

  /* ---------- attendance register: everyone ranked by attendance, lowest first (kohal, 2026-10-20) -
     same data and shape as the top list on the Attendance sheet page (app/workers.py/people.js), folded in
     here as an instant-switch subtab instead of a separate page to click through to. A person's full
     day-by-day record (HR details, payments, weeks of history) stays on that page though - richer code
     shared with Employee management's own detail view, not worth duplicating here - so tapping a row is an
     ordinary link out to it, not a hash within this script. ---------- */

  const UNASSIGNED = 'unassigned';
  const groupLabel = (k, roles) => (k === UNASSIGNED ? 'Unassigned' : roles[k] || k);
  const rate = (p) => (p.days ? p.present_days / p.days : 1);

  function sheetRow(p) {
    const pct = Math.round(rate(p) * 100);
    const fill = h('i', { class: pct >= 80 ? 'full' : pct < 50 ? 'low' : null });
    fill.style.width = `${pct}%`;
    return h('li', {}, h('a', { class: 'att-day people-row', href: `/attendance-sheet#p${p.id}` },
      h('div', { class: 'att-day-top' },
        h('span', { class: 'att-day-date' }, p.name),
        h('span', { class: 'att-day-hours', 'aria-label': `${p.present_days} of ${p.days} days` }, p.days ? `${p.present_days}/${p.days}` : '—')),
      h('span', { class: 'att-day-sub' }, p.days
        ? `${pct}% present · ${plural(p.days - p.present_days, 'day', 'days')} missed`
        : 'Not counted - started after this period'),
      p.days ? h('div', { class: 'att-bar', 'aria-hidden': 'true' }, fill) : null));
  }

  async function showRegister() {
    LD.resetAppbarBack?.();
    setTeamLink(false);
    stopElapsedTimer();
    document.body.classList.remove('has-att-bar');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/workforce'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const groups = Object.keys(data).filter((k) => Array.isArray(data[k]));
    const state = { q: '', group: 'all' };
    const period = data.period ? `${dayMonth(parseDay(data.period.start))} – ${dayMonth(parseDay(data.period.end))}` : null;
    const order = (a, b) => rate(a) - rate(b) || a.name.localeCompare(b.name);

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
      count.textContent = plural(people.length, 'person', 'people');
      clear(chips).append(...[['all', 'All', groups.reduce((n, g) => n + data[g].length, 0)],
        ...groups.map((g) => [g, groupLabel(g, data.roles), data[g].length])].map(([value, label, n]) => h('button', {
        type: 'button', class: 'filter-chip', 'aria-pressed': String(state.group === value),
        onclick: () => { state.group = value; render(); },
      }, label, h('span', { class: 'n' }, n))));
      clear(listBox).append(people.length
        ? h('ul', { class: 'att-week-card' }, people.map(sheetRow))
        : h('p', { class: 'empty-state' }, pool.length ? 'Nobody matches this search.' : 'Nobody here yet.'));
    }
    render();

    clear(view).append(h('div', {},
      tabs('register'),
      h('div', { class: 'list-head' }, h('h2', {}, 'Everyone'), count),
      search,
      chips,
      h('p', { class: 'wk-legend' }, ['Lowest attendance first', period].filter(Boolean).join(' · ')),
      listBox,
      h('p', { class: 'hint people-note' }, data.data_until
        ? `Attendance data up to ${shortDate(parseDay(data.data_until))}`
        : 'No attendance data yet.')));
  }

  function route() {
    if (canSeeWorkforce && window.location.hash === '#register') return showRegister();
    if (teamOnly || window.location.hash === '#team') return showTeam();
    return showMine();
  }

  window.addEventListener('hashchange', route);
  route();
})();
