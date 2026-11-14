/* Reports (kohal, 2026-11-05: "monthly reports in excel format to document everything happening in the business") -
   one subtab per report, each with a month filter of its own (kohal: "diff subtabs for diff reports with month filter
   separately for all") plus any extra filter that report has (the Projects report filters on project status), and a
   button to download that report as an Excel file. Admin only; see app/reports.py. What is picked on one tab is
   remembered for that tab alone while the page is open. */
(() => {
  'use strict';

  const { $, h, clear, api, field, selectField, money, plural } = window.LD;
  const view = $('#view');
  const picked = {};                     // report key -> { month, <filter key>: value }

  function tabBar(reports, active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Report' },
      reports.map((r) => h('a', { class: 'filter-chip', href: `#${r.key}`, 'aria-current': r.key === active ? 'page' : null }, r.title)));
  }

  /* The Inventory subtab shows its figures on screen as well as offering the Excel (kohal, 2026-11-14): this month's stock in, stock allocated to
     projects, stock value now and what is running low - from app/inventory_report.py. */
  const qty = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const withUnit = (n, unit) => `${qty(n)}${unit ? ` ${unit}` : ''}`;
  const stat = (label, value) => h('div', { class: 'stat' }, h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value is-text' }, value));
  const row = (title, sub, value) => h('li', { class: 'p-row' },
    h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, title), sub ? h('span', { class: 'row-sub' }, sub) : null),
    value ? h('span', { class: 'row-value' }, value) : null);
  const block = (title, note, list, empty, total) => h('section', { class: 'p-section' },
    h('div', { class: 'p-section-head' }, h('h3', {}, title)),
    note ? h('p', { class: 'hint' }, note) : null,
    list.length ? h('ul', { class: 'card-group' }, list) : h('p', { class: 'hint' }, empty),
    list.length && total ? h('p', { class: 'pay-summary' }, total) : null);

  function inventoryBlocks(d) {
    const cur = d.currency;
    const bought = d.stock_in.rows.map((r) => row(r.name, `${withUnit(r.quantity, r.unit)} \u00b7 ${plural(r.entries, 'purchase', 'purchases')}`, money(r.total, cur)));
    const given = d.allocated.projects.map((p) => row(p.title, [p.code, ...p.materials.map((m) => `${m.name} ${withUnit(m.quantity, m.unit)}`)].filter(Boolean).join(' \u00b7 '), money(p.amount, cur)));
    const inStock = d.stock.rows.map((r) => row(r.name, `${withUnit(r.quantity, r.unit)} at ${money(r.rate, cur)}`, money(r.value, cur)));
    const short = d.low.short.map((r) => row(r.name, `${withUnit(r.in_stock, r.unit)} in stock \u00b7 ${withUnit(r.requested, r.unit)} asked for${r.projects.length ? ` by ${r.projects.join(', ')}` : ''}`, `Short ${withUnit(r.short_by, r.unit)}`));
    const out = d.low.out.map((r) => row(r.name, 'None left in stock', null));
    return [
      h('div', { class: 'client-stats' }, stat('Stock in', money(d.stock_in.total, cur)), stat('Allocated to projects', money(d.allocated.total, cur))),
      h('div', { class: 'client-stats' }, stat('Stock value now', money(d.stock.total, cur))),
      block('Stock in', `What was bought in ${d.label}, with GST.`, bought, `Nothing was bought in ${d.label}.`, `Total stock in: ${money(d.stock_in.total, cur)}`),
      block('Allocated to projects', `What went out to projects in ${d.label}, less anything sent back, at the stock\u2019s own cost.`, given,
        `No material was allocated to a project in ${d.label}.`, `Total allocated: ${money(d.allocated.total, cur)}`),
      block('Stock value now', 'What is in stock today and what it is worth - today\u2019s picture, whichever month is picked.', inStock, 'Nothing is in stock.',
        `Total stock value: ${money(d.stock.total, cur)}`),
      block('Low stock', 'Materials that cannot cover the project requests waiting on them, and ones that have run out.', [...short, ...out], 'Nothing is running low.'),
    ];
  }

  function showReport(data, report) {
    const mine = picked[report.key] = picked[report.key] || { month: data.current };
    const link = h('a', { class: 'btn primary', download: '', href: '#' }, 'Download Excel');
    const sync = () => {
      const query = new URLSearchParams({ month: mine.month });
      report.filters.forEach((f) => { if (mine[f.key] && mine[f.key] !== f.options[0].value) query.set(f.key, mine[f.key]); });
      link.href = `/api/reports/${report.key}?${query}`;
    };
    const monthSel = selectField(data.months, mine.month, { title: 'Month', placeholder: 'Choose a month' });
    const onScreen = report.key === 'inventory' ? h('div', { class: 'inventory-report' }) : null;
    let ticket = 0;
    const drawOnScreen = async () => {
      if (!onScreen) return;
      const mineTicket = ++ticket;
      clear(onScreen).append(h('p', { class: 'loading' }, 'Loading\u2026'));
      let d;
      try { d = await api(`/api/inventory/report?month=${mine.month}`); } catch (err) { if (mineTicket === ticket) clear(onScreen).append(h('p', { class: 'empty-state' }, err.message)); return; }
      if (mineTicket === ticket) clear(onScreen).append(...inventoryBlocks(d));
    };
    monthSel.addEventListener('change', () => { mine.month = monthSel.value || data.current; sync(); drawOnScreen(); });
    const filterFields = report.filters.map((f) => {
      mine[f.key] = mine[f.key] || f.options[0].value;
      const sel = selectField(f.options, mine[f.key], { title: f.label, placeholder: f.label });
      sel.addEventListener('change', () => { mine[f.key] = sel.value || f.options[0].value; sync(); });
      return field(f.key, f.label, sel);
    });
    sync();
    clear(view).append(h('div', {},
      tabBar(data.reports, report.key),
      h('div', { class: 'project-detail' },
        h('p', { class: 'hint' }, report.about),
        field('month', 'Month', monthSel),
        ...filterFields,
        h('div', { class: 'acct-actions' }, link),
        h('p', { class: 'hint' }, 'One Excel file for the month, rebuilt from the live records each time you download it.'),
        onScreen)));
    drawOnScreen();
  }

  async function load() {
    let data;
    try { data = await api('/api/reports'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const route = () => {
      const key = window.location.hash.slice(1);
      showReport(data, data.reports.find((r) => r.key === key) || data.reports[0]);
    };
    window.addEventListener('hashchange', route);
    route();
  }

  load();
})();
