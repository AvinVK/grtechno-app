/* Reports (kohal, 2026-11-05: "monthly reports in excel format to document everything happening in the business") -
   one subtab per report, each with a month filter of its own (kohal: "diff subtabs for diff reports with month filter
   separately for all") plus any extra filter that report has (the Projects report filters on project status), and a
   button to download that report as an Excel file. Admin only; see app/reports.py. What is picked on one tab is
   remembered for that tab alone while the page is open. */
(() => {
  'use strict';

  const { $, h, clear, api, field, selectField } = window.LD;
  const view = $('#view');
  const picked = {};                     // report key -> { month, <filter key>: value }

  function tabBar(reports, active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Report' },
      reports.map((r) => h('a', { class: 'filter-chip', href: `#${r.key}`, 'aria-current': r.key === active ? 'page' : null }, r.title)));
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
