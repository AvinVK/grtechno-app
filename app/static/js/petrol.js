/* Petrol: what an employee on petrol payment is owed for the kilometres they ride (kohal, 2026-10-27: "same
   as fooding, we need option of petrol payment") - see app/petrol.py. One page, two audiences, same split as
   fooding.js:
   - mode "manage" (the admin or accountant): everyone on petrol payment with this month's amount, tap a
     person for their register - every day with the two readings, km, amount and whether it's approved.
   - mode "own" (an employee on petrol payment): their own register and totals.
   An entry only counts towards the totals once the admin or the project manager has approved it. */
(() => {
  'use strict';

  const { $, h, clear, api, money } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;

  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  };

  const STATUS = { pending: ['Waiting for approval', 'chip-off'], approved: ['Approved', 'chip-role'], rejected: ['Rejected', 'chip-off'] };

  function entryRow(cur) {
    return (e) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, `${fmtDate(e.work_date)} · ${e.km} km`),
        h('span', { class: 'row-sub' }, [`${e.in_reading} → ${e.out_reading}`, e.project_title, e.approved_by_name ? `by ${e.approved_by_name}` : null].filter(Boolean).join(' · ')),
        e.status === 'approved' ? null : h('span', { class: `chip ${STATUS[e.status][1]}` }, STATUS[e.status][0])),
      h('span', { class: 'row-value' }, e.status === 'approved' ? money(e.amount, cur) : `(${money(e.amount, cur)})`));
  }

  function registerBlock(data) {
    const cur = data.currency;
    return h('div', { class: 'petrol-register' },
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'This month'),
          h('span', { class: 'stat-value is-text' }, money(data.month_total, cur)),
          h('span', { class: 'stat-note' }, `${data.month_km} km approved`)),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'All time'),
          h('span', { class: 'stat-value is-text' }, money(data.approved_total, cur)),
          h('span', { class: 'stat-note' }, `${money(data.rate_per_km, cur)} per km`))),
      h('p', { class: 'hint' }, 'Each day is the kilometres between the two odometer readings, paid per km once approved. Amounts in brackets are not approved yet.'),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Register'),
        data.entries.length
          ? h('ul', { class: 'card-group' }, data.entries.map(entryRow(cur)))
          : h('p', { class: 'hint' }, 'Nothing yet - it fills in as check-ins and check-outs with an odometer reading are approved.')));
  }

  /* ---------- mode "own" ---------- */

  async function loadOwn() {
    try {
      clear(view).append(h('div', { class: 'project-detail' }, registerBlock(await api('/api/petrol/me'))));
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
    }
  }

  /* ---------- mode "manage" ---------- */

  async function loadManage() {
    LD.resetAppbarBack?.();
    let data;
    try {
      data = await api('/api/petrol');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;
    clear(view).append(h('div', {},
      h('p', { class: 'result-count' }, `${data.workers.length} employee${data.workers.length === 1 ? '' : 's'} on petrol payment`),
      data.workers.length
        ? h('ul', { class: 'card-group' }, data.workers.map((w) => h('li', {}, h('button', {
          type: 'button', class: 'card me-row approval-row fooding-row', onclick: () => { window.location.hash = `#p${w.worker_id}`; },
        },
        h('div', { class: 'approval-main' },
          h('strong', {}, w.worker_name),
          h('span', { class: 'hint' }, [`${w.month_km} km this month`, w.pending ? `${w.pending} waiting for approval` : null].filter(Boolean).join(' \u00b7 '))),
        h('span', { class: 'fn-stat-value' }, money(w.month_total, cur))))))
        : h('p', { class: 'empty-state' }, 'Nobody is on petrol payment yet - switch it on for someone in Employee management.')));
  }

  /* A person's register opens as its own page, like an employee in the attendance register. */
  async function showPerson(id) {
    LD.setAppbarBack?.('Petrol', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    try {
      const data = await api(`/api/petrol/worker/${id}`);
      clear(view).append(h('div', { class: 'people' },
        h('div', { class: 'att-head' }, h('h2', {}, data.worker_name)),
        registerBlock(data)));
      window.scrollTo(0, 0);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back')));
    }
  }

  function route() {
    const m = /^#p(\d+)$/.exec(window.location.hash);
    if (m) return showPerson(Number(m[1]));
    return loadManage();
  }

  if (mode === 'manage') {
    window.addEventListener('hashchange', route);
    route();
  } else loadOwn();
})();
