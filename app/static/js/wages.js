/* Wages: a placeholder for a daily-wage employee's own wage tracking, which doesn't exist yet (kohal,
   2026-10-18: "wages wont be populated yet") - just the day rate already on file for them from Employee
   management, so the tile isn't a dead end. See app/wages.py. */
(() => {
  'use strict';

  const { $, h, clear, api, money } = window.LD;
  const view = $('#view');

  async function load() {
    let data;
    try {
      data = await api('/api/wages/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Daily wage'),
          h('span', { class: 'stat-value is-text' }, data.daily_rate != null ? `${money(data.daily_rate, data.currency)}/day` : 'Not set'))),
      h('p', { class: 'hint' }, "Day-by-day wage tracking isn't built yet - this will show what you've earned and what's been paid, once it is.")));
  }

  load();
})();
