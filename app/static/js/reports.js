/* Reports (kohal, 2026-11-05: "monthly reports in excel format to document everything happening in the business") -
   one subtab per report, each with a month filter of its own (kohal: "diff subtabs for diff reports with month filter
   separately for all") plus any extra filter that report has (the Projects report filters on project status), and a
   button to download that report as an Excel file. Admin only; see app/reports.py. What is picked on one tab is
   remembered for that tab alone while the page is open.
   The Inventory subtab is different (kohal, 2026-11-14): three reports inside it - stock in, stock out and the inventory status on a day - picked
   by a date range (and a material) instead of a month, shown on screen and downloaded as one Excel with a sheet for each.
   The Transactions subtab (kohal, 2026-11-25) is picked by dates too - everything received and spent, day by day, narrowed to money in or out or to
   one account - and downloads as Excel or as a PDF. */
(() => {
  'use strict';

  const { $, h, clear, api, field, selectField, searchField, dateField, money, closeOnBack } = window.LD;
  const view = $('#view');
  const picked = {};                     // report key -> { month, <filter key>: value }

  function tabBar(reports, active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Report' },
      reports.map((r) => h('a', { class: 'filter-chip', href: `#${r.key}`, 'aria-current': r.key === active ? 'page' : null }, r.title)));
  }

  /* ---------- Inventory: stock in, stock out, inventory status ---------- */

  const qty = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const withUnit = (n, unit) => `${qty(n)}${unit ? ` ${unit}` : ''}`;
  const dayLabel = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
  };
  // The one-line total at the top of each report (kohal, 2026-11-14: "this ui is taking too much space") - big figure, then what it is.
  const summary = (big, rest) => h('p', { class: 'inv-summary' }, h('strong', {}, big), ` ${rest}`);
  const row = (title, sub, value) => h('li', { class: 'p-row' },
    h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, title), sub ? h('span', { class: 'row-sub' }, sub) : null),
    value ? h('span', { class: 'row-value' }, value) : null);
  const block = (title, total, list, empty) => h('section', { class: 'p-section' },
    h('div', { class: 'p-section-head' }, h('h3', {}, title), total ? h('span', { class: 'p-code' }, total) : null),
    list.length ? h('ul', { class: 'card-group' }, list) : h('p', { class: 'hint' }, empty));

  /* Stock in and stock out show one line per day - how many materials moved and what it cost - and "More" slides that day's materials up from the
     bottom in a scrollable sheet (kohal, 2026-11-14: "only show quantity and cost of that day and when clicking on more, it should open a bar from
     bottom which will be scrollable"). Quantities in different units (metres, pieces) can't be added up, so the line counts materials, not units. */
  function daySheet(day, rows, cur, hint) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const closeX = h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close' }, '×');
    const finish = closeOnBack(() => overlay.remove());
    closeX.onclick = () => finish();
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    overlay.append(h('div', { class: 'amount-sheet day-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': dayLabel(day.date) },
      h('div', { class: 'day-sheet-head' },
        h('div', {}, h('h2', {}, dayLabel(day.date)), h('p', { class: 'hint' }, hint || `${money(day.total, cur)} · ${day.entries.length} ${day.entries.length === 1 ? 'entry' : 'entries'}`)),
        closeX),
      h('ul', { class: 'card-group day-sheet-list' }, rows)));
    document.body.append(overlay);
  }

  const dayRow = (day, what, rows, cur) => {
    const names = new Set(day.entries.map((e) => e.name)).size;
    return h('li', { class: 'p-row day-row' },
      h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, dayLabel(day.date)),
        h('span', { class: 'row-sub' }, `${names} ${names === 1 ? 'material' : 'materials'} ${what}`)),
      h('span', { class: 'row-value' }, money(day.total, cur)),
      h('button', { class: 'btn small', type: 'button', onclick: () => daySheet(day, rows, cur) }, 'More'));
  };
  const dayList = (days, what, rowOf, cur, empty) => (days.length
    ? h('ul', { class: 'card-group' }, days.map((day) => dayRow(day, what, day.entries.map(rowOf), cur)))
    : h('p', { class: 'hint' }, empty));

  const PARTS = [['in', 'Stock in'], ['out', 'Stock out'], ['status', 'Inventory status']];

  function inventoryBlocks(part, d, cur) {
    const r = d.report;
    if (part === 'in') {
      return [
        summary(money(r.total, cur), `stock in, GST ${money(r.gst, cur)} · ${r.count} ${r.count === 1 ? 'purchase' : 'purchases'}`),
        dayList(r.days, 'bought', (e) => row(e.name,
          [`${withUnit(e.quantity, e.unit)} at ${money(e.rate, cur)}`, e.supplier || null, e.bill_no ? `Bill ${e.bill_no}` : null].filter(Boolean).join(' · '), money(e.total, cur)),
          cur, 'No stock came in between these dates.'),
      ];
    }
    if (part === 'out') {
      return [
        summary(money(r.total, cur), `allocated to projects · ${r.count} ${r.count === 1 ? 'entry' : 'entries'}`),
        dayList(r.days, 'allocated', (e) => row(e.name,
          [e.project_code, e.project, `${e.kind === 'Returned' ? 'Returned ' : ''}${withUnit(Math.abs(e.quantity), e.unit)}`].filter(Boolean).join(' · '), money(e.amount, cur)),
          cur, 'No material was allocated to a project between these dates.'),
      ];
    }
    const short = r.short.map((s) => row(s.name, `${withUnit(s.in_stock, s.unit)} in stock · ${withUnit(s.requested, s.unit)} asked for${s.projects.length ? ` by ${s.projects.join(', ')}` : ''}`, `Short ${withUnit(s.short_by, s.unit)}`));
    return [
      summary(money(r.total, cur), `stock value on ${dayLabel(r.date)}`),
      block('Inventory status', null, r.rows.map((m) => row(m.name, m.status === 'In stock' ? `${withUnit(m.quantity, m.unit)} at ${money(m.rate, cur)}` : 'None left in stock', m.status === 'In stock' ? money(m.value, cur) : null)),
        'Nothing had been stocked by this day.'),
      ...(short.length ? [block('Short for waiting requests', null, short, '')] : []),
    ];
  }

  function showInventory(data, report) {
    const mine = picked[report.key] = picked[report.key] || {};
    const today = new Date().toLocaleDateString('en-CA');
    Object.assign(mine, { part: mine.part || 'in', from: mine.from || `${today.slice(0, 8)}01`, to: mine.to || today, as_on: mine.as_on || today, material: mine.material || '' });
    const link = h('a', { class: 'btn primary', download: '', href: '#', title: 'One Excel file with a sheet for stock in, stock out and the inventory status' }, 'Download Excel');
    const body = h('div', { class: 'inventory-report' });
    const filters = h('div', { class: 'inventory-filters' });
    let ticket = 0;

    const syncLink = () => {
      const q = new URLSearchParams({ from: mine.from, to: mine.to, as_on: mine.as_on });
      if (mine.material) q.set('material_id', mine.material);
      link.href = `/api/reports/${report.key}?${q}`;
    };
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Inventory report' },
      PARTS.map(([key, label]) => h('button', { class: 'filter-chip', type: 'button', 'data-part': key, onclick: () => { mine.part = key; drawFilters(); draw(); } }, label)));
    const markChips = () => chips.querySelectorAll('.filter-chip').forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.part === mine.part)));

    let materials = null;
    function drawFilters() {
      markChips();
      clear(filters);
      if (mine.part === 'status') {
        const asOn = dateField(mine.as_on, { placeholder: 'Pick the day', clearable: false });
        asOn.addEventListener('change', () => { mine.as_on = asOn.value || today; syncLink(); draw(); });
        filters.append(h('div', { class: 'field-row inv-row' }, field('as_on', 'Status as on', asOn), link));
        return;
      }
      const from = dateField(mine.from, { placeholder: 'From', clearable: false });
      const to = dateField(mine.to, { placeholder: 'To', clearable: false });
      const mat = searchField([{ value: '', label: 'All materials' }, ...(materials || [])], mine.material, { placeholder: 'All materials' });
      from.addEventListener('change', () => { mine.from = from.value || mine.from; syncLink(); draw(); });
      to.addEventListener('change', () => { mine.to = to.value || mine.to; syncLink(); draw(); });
      mat.addEventListener('change', () => { mine.material = mat.value || ''; syncLink(); draw(); });
      filters.append(h('div', { class: 'field-row' }, field('from', 'From', from), field('to', 'To', to)),
        h('div', { class: 'field-row inv-row' }, field('material', 'Material', mat), link));
    }

    async function draw() {
      const mineTicket = ++ticket;
      syncLink();
      clear(body).append(h('p', { class: 'loading' }, 'Loading…'));
      const q = new URLSearchParams({ part: mine.part, from: mine.from, to: mine.to, as_on: mine.as_on });
      if (mine.material) q.set('material_id', mine.material);
      let d;
      try { d = await api(`/api/inventory/report?${q}`); } catch (err) { if (mineTicket === ticket) clear(body).append(h('p', { class: 'empty-state' }, err.message)); return; }
      if (mineTicket !== ticket) return;
      if (!materials) { materials = d.materials; drawFilters(); }            // the material list arrives with the first answer
      clear(body).append(...inventoryBlocks(mine.part, d, d.currency));
    }

    drawFilters();
    clear(view).append(h('div', {},
      tabBar(data.reports, report.key),
      h('div', { class: 'project-detail' },
        chips, filters, body)));
    draw();
  }

  /* ---------- Transactions ---------- */

  // Whole rupees would round an amount like 1,234.50 in a report, so these keep the paise when there are some.
  const exact = (v, cur) => `${cur}${Number(v).toLocaleString('en-IN', { minimumFractionDigits: Number.isInteger(Number(v)) ? 0 : 2, maximumFractionDigits: 2 })}`;
  const KINDS = [['all', 'All'], ['in', 'Received'], ['out', 'Spent']];

  function showTransactions(data, report) {
    const mine = picked[report.key] = picked[report.key] || {};
    const today = new Date().toLocaleDateString('en-CA');
    Object.assign(mine, { kind: mine.kind || 'all', from: mine.from || `${today.slice(0, 8)}01`, to: mine.to || today, account: mine.account || '' });
    const excel = h('a', { class: 'btn primary', download: '', href: '#' }, 'Download Excel');
    const pdf = h('a', { class: 'btn', download: '', href: '#' }, 'Download PDF');
    const body = h('div', { class: 'transactions-report' });
    const filters = h('div', { class: 'inventory-filters' });
    let ticket = 0;
    let accounts = null;

    const query = (extra) => {
      const q = new URLSearchParams({ from: mine.from, to: mine.to, kind: mine.kind, ...extra });
      if (mine.account) q.set('account', mine.account);
      return q;
    };
    const syncLinks = () => {
      excel.href = `/api/reports/${report.key}?${query({})}`;
      pdf.href = `/api/reports/${report.key}?${query({ format: 'pdf' })}`;
    };
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Show' },
      KINDS.map(([key, label]) => h('button', { class: 'filter-chip', type: 'button', 'data-kind': key, onclick: () => { mine.kind = key; markChips(); draw(); } }, label)));
    const markChips = () => chips.querySelectorAll('.filter-chip').forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.kind === mine.kind)));

    function drawFilters() {
      clear(filters);
      const from = dateField(mine.from, { placeholder: 'From', clearable: false });
      const to = dateField(mine.to, { placeholder: 'To', clearable: false });
      const acct = selectField([{ value: '', label: 'All accounts' }, ...(accounts || [])], mine.account, { title: 'Account', placeholder: 'All accounts' });
      from.addEventListener('change', () => { mine.from = from.value || mine.from; draw(); });
      to.addEventListener('change', () => { mine.to = to.value || mine.to; draw(); });
      acct.addEventListener('change', () => { mine.account = acct.value || ''; draw(); });
      filters.append(h('div', { class: 'field-row' }, field('from', 'From', from), field('to', 'To', to)),
        field('account', 'Account', acct),
        h('div', { class: 'acct-actions' }, excel, pdf));
    }

    const entryRow = (e, cur) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, e.reason),
        h('span', { class: 'row-sub' }, [e.party, e.detail, e.account || '(no account)'].filter(Boolean).join(' · '))),
      h('span', { class: `row-value ${e.kind === 'credit' ? 'acct-credit' : 'acct-debit'}` }, `${e.kind === 'credit' ? '+' : '−'}${exact(e.amount, cur)}`));

    const dayRow = (day, cur) => {
      const net = day.received - day.spent;
      const [value, positive] = mine.kind === 'in' ? [day.received, true] : mine.kind === 'out' ? [day.spent, false] : [Math.abs(net), net >= 0];
      const sub = mine.kind === 'all' ? `Received ${exact(day.received, cur)} · Spent ${exact(day.spent, cur)}` : `${day.count} ${day.count === 1 ? 'entry' : 'entries'}`;
      const hint = `Received ${exact(day.received, cur)} · Spent ${exact(day.spent, cur)} · ${day.count} ${day.count === 1 ? 'entry' : 'entries'}`;
      return h('li', { class: 'p-row day-row' },
        h('span', { class: 'p-main' }, h('span', { class: 'row-title' }, dayLabel(day.date)), h('span', { class: 'row-sub' }, sub)),
        h('span', { class: `row-value ${positive ? 'acct-credit' : 'acct-debit'}` }, `${mine.kind === 'all' ? (positive ? '+' : '−') : ''}${exact(value, cur)}`),
        h('button', { class: 'btn small', type: 'button', onclick: () => daySheet(day, day.entries.map((e) => entryRow(e, cur)), cur, hint) }, 'More'));
    };

    async function draw() {
      const mineTicket = ++ticket;
      syncLinks();
      clear(body).append(h('p', { class: 'loading' }, 'Loading…'));
      let d;
      try { d = await api(`/api/reports/${report.key}/view?${query({})}`); } catch (err) { if (mineTicket === ticket) clear(body).append(h('p', { class: 'empty-state' }, err.message)); return; }
      if (mineTicket !== ticket) return;
      if (!accounts) { accounts = d.accounts; drawFilters(); }               // the account list arrives with the first answer
      const cur = d.currency;
      const what = d.count === 1 ? 'entry' : 'entries';
      const top = mine.kind === 'in' ? summary(exact(d.received, cur), `received · ${d.count} ${what}`)
        : mine.kind === 'out' ? summary(exact(d.spent, cur), `spent · ${d.count} ${what}`)
          : summary(`${d.net < 0 ? '−' : ''}${exact(Math.abs(d.net), cur)}`, `net · received ${exact(d.received, cur)}, spent ${exact(d.spent, cur)} · ${d.count} ${what}`);
      clear(body).append(top, d.days.length
        ? h('ul', { class: 'card-group' }, d.days.map((day) => dayRow(day, cur)))
        : h('p', { class: 'hint' }, 'Nothing was received or spent between these dates.'));
    }

    markChips();
    drawFilters();
    clear(view).append(h('div', {},
      tabBar(data.reports, report.key),
      h('div', { class: 'project-detail' },
        chips, filters, body)));
    draw();
  }

  function showReport(data, report) {
    if (report.key === 'transactions') return showTransactions(data, report);
    if (report.range) return showInventory(data, report);
    const mine = picked[report.key] = picked[report.key] || { month: data.current };
    const link = h('a', { class: 'btn primary', download: '', href: '#' }, 'Download Excel');
    const sync = () => {
      const query = new URLSearchParams({ month: mine.month });
      report.filters.forEach((f) => { if (mine[f.key] && mine[f.key] !== f.options[0].value) query.set(f.key, mine[f.key]); });
      link.href = `/api/reports/${report.key}?${query}`;
    };
    const monthSel = selectField(data.months, mine.month, { title: 'Month', placeholder: 'Choose a month' });
    monthSel.addEventListener('change', () => { mine.month = monthSel.value || data.current; sync(); });
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
        h('p', { class: 'hint' }, 'One Excel file for the month, rebuilt from the live records each time you download it.'))));
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
