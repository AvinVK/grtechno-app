/* Fooding: a daily-wage employee's own food allowance - what's been allotted, what's left, and the ₹200/
   day that comes off it automatically (see app/fooding.py and models.FoodingAccount), or "Paused" if the
   admin or accountant has switched that off for them. Read-only here - allotting/pausing happens from the
   admin's own Fooding block on the Me hub (app/static/js/me.js). */
(() => {
  'use strict';

  const { $, h, clear, api, money } = window.LD;
  const view = $('#view');

  async function load() {
    let data;
    try {
      data = await api('/api/fooding/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const f = data.fooding;
    const cur = data.currency;
    clear(view).append(h('div', { class: 'project-detail' },
      f.is_paused ? h('p', {}, h('span', { class: 'chip chip-off' }, 'Paused')) : null,
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Allotted'),
          h('span', { class: 'stat-value is-text' }, money(f.allotted_total, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Remaining'),
          h('span', { class: 'stat-value is-text' }, money(f.remaining, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Daily deduction'),
          h('span', { class: 'stat-value is-text' }, f.is_paused ? 'Paused' : `${money(f.daily_amount, cur)}/day`))),
      h('p', { class: 'hint' }, f.is_paused
        ? 'The admin or accountant has paused your fooding deduction - nothing is coming off your balance right now.'
        : `₹${f.daily_amount} comes off your fooding balance automatically, every day, until the admin or accountant pauses it or your balance runs out.`)));
  }

  load();
})();
