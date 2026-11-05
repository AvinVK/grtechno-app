/* Reports (kohal, 2026-11-05: "monthly reports in excel format to document everything happening in the business") -
   pick a month, download a report as an Excel file. Admin only; see app/reports.py. */
(() => {
  'use strict';

  const { $, h, clear, api, field, selectField } = window.LD;
  const view = $('#view');

  async function load() {
    let data;
    try { data = await api('/api/reports'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const monthSel = selectField(data.months, data.current, { title: 'Month', placeholder: 'Choose a month' });
    const cards = data.reports.map((r) => {
      const link = h('a', { class: 'btn primary', download: '', href: '#' }, 'Download Excel');
      const sync = () => { link.href = `/api/reports/${r.key}?month=${encodeURIComponent(monthSel.value || data.current)}`; };
      monthSel.addEventListener('change', sync);
      sync();
      return h('div', { class: 'card report-card' },
        h('h3', {}, r.title),
        h('p', { class: 'hint' }, r.about),
        h('div', { class: 'acct-actions' }, link));
    });
    clear(view).append(h('div', { class: 'project-detail' },
      h('p', { class: 'hint' }, 'One Excel file per month, rebuilt from the live records each time you download it.'),
      field('month', 'Month', monthSel),
      ...cards));
  }

  load();
})();
