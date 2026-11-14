/* Inventory report (kohal, 2026-11-14: "in me tab in inventory block, i want to see inventory report ... monthly reports of total stock in,
   stocks allocated to projects" - plus stock value now, a low-stock list and an Excel download). One month at a time, picked at the top;
   everything on it comes from app/inventory_report.py. */
(() => {
  'use strict';

  const { $, h, clear, api, money, field, selectField, plural } = window.LD;
  const view = $('#view');
  let month = '';

  const qty = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const withUnit = (n, unit) => `${qty(n)}${unit ? ` ${unit}` : ''}`;
  const stat = (label, value) => h('div', { class: 'stat' }, h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value is-text' }, value));
  const row = (title, sub, value) => h('li', { class: 'p-row' },
    h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, title), sub ? h('span', { class: 'row-sub' }, sub) : null),
    value ? h('span', { class: 'row-value' }, value) : null);
  const section = (title, note, list, empty, total) => h('section', { class: 'p-section' },
    h('div', { class: 'p-section-head' }, h('h3', {}, title)),
    note ? h('p', { class: 'hint' }, note) : null,
    list.length ? h('ul', { class: 'card-group' }, list) : h('p', { class: 'hint' }, empty),
    list.length && total ? h('p', { class: 'pay-summary' }, total) : null);

  async function load() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let d;
    try { d = await api(`/api/inventory/report${month ? `?month=${month}` : ''}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    month = d.month;
    render(d);
  }

  function render(d) {
    const cur = d.currency;
    const monthSel = selectField(d.months, d.month, { title: 'Month', placeholder: 'Choose a month' });
    monthSel.addEventListener('change', () => { month = monthSel.value || d.current; load(); });

    const bought = d.stock_in.rows.map((r) => row(r.name, `${withUnit(r.quantity, r.unit)} · ${plural(r.entries, 'purchase', 'purchases')}`, money(r.total, cur)));
    const given = d.allocated.projects.map((p) => row(p.title, [p.code, ...p.materials.map((m) => `${m.name} ${withUnit(m.quantity, m.unit)}`)].filter(Boolean).join(' · '), money(p.amount, cur)));
    const inStock = d.stock.rows.map((r) => row(r.name, `${withUnit(r.quantity, r.unit)} at ${money(r.rate, cur)}`, money(r.value, cur)));
    const short = d.low.short.map((r) => row(r.name, `${withUnit(r.in_stock, r.unit)} in stock · ${withUnit(r.requested, r.unit)} asked for${r.projects.length ? ` by ${r.projects.join(', ')}` : ''}`, `Short ${withUnit(r.short_by, r.unit)}`));
    const out = d.low.out.map((r) => row(r.name, 'None left in stock', null));

    clear(view).append(h('div', { class: 'project-detail' },
      field('month', 'Month', monthSel),
      h('div', { class: 'client-stats' },
        stat('Stock in', money(d.stock_in.total, cur)),
        stat('Allocated to projects', money(d.allocated.total, cur))),
      h('div', { class: 'client-stats' },
        stat('Stock value now', money(d.stock.total, cur))),
      h('div', { class: 'acct-actions' }, h('a', { class: 'btn primary', download: '', href: `/api/inventory/report.xlsx?month=${d.month}` }, 'Download Excel')),
      section('Stock in', `What was bought in ${d.label}, with GST.`, bought, `Nothing was bought in ${d.label}.`, `Total stock in: ${money(d.stock_in.total, cur)}`),
      section('Allocated to projects', `What went out to projects in ${d.label}, less anything sent back, at the stock’s own cost.`, given,
        `No material was allocated to a project in ${d.label}.`, `Total allocated: ${money(d.allocated.total, cur)}`),
      section('Stock value now', 'What is in stock today and what it is worth - today’s picture, whichever month is picked.', inStock, 'Nothing is in stock.',
        `Total stock value: ${money(d.stock.total, cur)}`),
      section('Low stock', 'Materials that cannot cover the project requests waiting on them, and ones that have run out.', [...short, ...out], 'Nothing is running low.')));
    window.scrollTo(0, 0);
  }

  load();
})();
