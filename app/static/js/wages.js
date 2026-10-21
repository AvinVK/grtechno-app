/* Wages: a daily-wage/contractor employee's own day-by-day pay log (kohal, 2026-10-21: "i wanna have day
   by day cumulative wages tracking for daily wages and it should show in wages block in me tab. also once
   15 days are over (the payroll cycle), it should show a flag saying 15 days cycle total is this much, u
   were absent this much") - the current cycle's own running total, day by day, plus the most recently
   *completed* cycle shown as its own flag above it rather than folded into the day list, same two pieces
   app/wages.py's my_wages returns (current/completed). Same day-row shape as the admin's own
   app/static/js/payroll.js (dayRow/showPersonDays) for a worker's days, just this worker's own, no picking
   anyone first. See app/wages.py. */
(() => {
  'use strict';

  const { $, h, clear, api, money, plural } = window.LD;
  const view = $('#view');

  function shortDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  function completedCycleFlag(c, cur) {
    return h('div', { class: 'pay-overview is-flag' },
      h('p', { class: 'pay-overview-title' }, `${c.period_label} cycle complete`),
      h('dl', { class: 'pay-overview-grid' },
        h('dt', {}, 'Total earned'), h('dd', {}, money(c.earned, cur)),
        h('dt', {}, 'Days present'), h('dd', {}, c.days),
        h('dt', {}, 'Days absent'), h('dd', {}, c.absent)));
  }

  function dayRow(d, cur) {
    let subLabel;
    if (d.not_yet) subLabel = 'No data yet';
    else if (d.present) subLabel = d.hours != null ? `${d.hours} h logged` : 'Present (no in/out time)';
    else if (d.is_sunday) subLabel = 'Sunday · credited';
    else subLabel = 'Absent';
    return h('li', { class: 'att-day' },
      h('div', { class: 'att-day-top' },
        h('span', { class: 'att-day-date' }, shortDate(d.date)),
        h('span', { class: 'att-day-hours' }, money(d.pay, cur))),
      h('span', { class: 'att-day-sub' },
        h('span', { class: 'att-day-sub-line' }, subLabel),
        h('span', { class: 'att-day-sub-line' }, `Running total: ${money(d.cumulative, cur)}`)));
  }

  async function load() {
    let data;
    try {
      data = await api('/api/wages/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;
    const c = data.current;
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Daily wage'),
          h('span', { class: 'stat-value is-text' }, data.daily_rate != null ? `${money(data.daily_rate, cur)}/day` : 'Not set'))),
      data.completed ? completedCycleFlag(data.completed, cur) : null,
      c ? h('div', {},
        h('div', { class: 'att-head' }, h('h2', {}, c.period_label), h('span', { class: 'att-head-date' }, 'Current cycle')),
        h('p', { class: 'wk-legend' },
          `${money(c.earned, cur)} so far · ${plural(c.days, 'day', 'days')} present · ${plural(c.absent, 'day', 'days')} absent`),
        data.days.length
          ? h('ul', { class: 'att-week-card' }, data.days.map((d) => dayRow(d, cur)))
          : h('p', { class: 'empty-state' }, 'No attendance data yet this cycle.'))
        : h('p', { class: 'hint' }, "Nothing to show yet - this fills in once your attendance starts being recorded.")));
  }

  load();
})();
