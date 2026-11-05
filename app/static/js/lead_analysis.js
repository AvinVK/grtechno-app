/* Lead analysis (kohal, 2026-11-05: "have graph of leads per month. leads per source. time spent on each stage. brought by count of
   each lead by each sales man"; then: "make brought by a pie chart and lead per month with filter of 30 days, 1 month, 3 month, 6 month
   and 1 year") - four charts over the leads this person may see, drawn with the shared plain-markup pieces in charts.js. Leads over
   time has a range of its own; the other three share a period. See app/lead_analysis.py for exactly how each figure is worked out. */
(() => {
  'use strict';

  const { $, h, clear, api, selectField } = window.LD;
  const { panel, columnChart, barRows, pieChart } = window.LD.charts;
  const view = $('#view');
  let period = 'all';
  let trend = '12';
  let scrollTo = null;                   // the id of the panel whose filter was just changed, kept in view across the reload

  const days = (v) => `${v} day${v === 1 ? '' : 's'}`;

  // Who brought the leads: the smallest few are grouped into one "Others" slice, with their outcomes added up.
  const broughtPie = (people) => pieChart(people.map((p) => ({ ...p, name: p.name })), {
    ariaNoun: 'Leads brought by', empty: 'No leads in this period.',
    others: (rest) => ({ name: `Others (${rest.length})`, total: rest.reduce((n, p) => n + p.total, 0), won: rest.reduce((n, p) => n + p.won, 0),
      lost: rest.reduce((n, p) => n + p.lost, 0), open: rest.reduce((n, p) => n + p.open, 0) }),
    legend: (s, pct) => `${s.total} lead${s.total === 1 ? '' : 's'} · ${pct}% · ${s.won} won · ${s.lost} lost · ${s.open} open`,
  });

  function render(data) {
    const trendSel = selectField(data.trends, data.trend.range, { title: 'Show leads for', placeholder: 'Range' });
    trendSel.classList.add('compact');
    trendSel.addEventListener('change', () => { trend = trendSel.value || '12'; scrollTo = 'panel-trend'; load(); });
    // The same period filter sits on each of the three charts it applies to - changing any one changes all three.
    const periodFor = (panelId) => {
      const sel = selectField(data.periods, data.period, { title: 'Period', placeholder: 'Period' });
      sel.classList.add('compact');
      sel.addEventListener('change', () => { period = sel.value || 'all'; scrollTo = panelId; load(); });
      return sel;
    };
    const sources = data.sources.length
      ? barRows(data.sources, { value: (r) => r.count, label: (r) => r.source, note: (r) => `${Math.round((r.count / data.total) * 100)}% of leads` })
      : h('p', { class: 'hint' }, 'No leads in this period.');
    const stages = barRows(data.stage_times, {
      value: (r) => r.avg_days, label: (r) => r.stage, format: days,
      note: (r) => [r.stays ? `${r.stays} lead${r.stays === 1 ? '' : 's'} moved on, typically ${days(r.median_days)}` : 'None have moved on yet',
        r.now ? `${r.now} here now${r.now_avg_days !== null ? `, ${days(r.now_avg_days)} so far` : ''}` : null].filter(Boolean).join(' · '),
    });

    clear(view).append(h('div', {},
      h('p', { class: 'hint' }, `Over ${data.scope}.`),
      panel('panel-trend', 'Leads over time', `New leads received - ${data.trend.total} ${data.trend.label.startsWith('Last') ? 'in the ' : ''}${data.trend.label.toLowerCase()}.`, trendSel, columnChart(data.trend)),
      panel('panel-source', 'Leads per source', `Where the ${data.total} lead${data.total === 1 ? '' : 's'} in this period came from.`, periodFor('panel-source'), sources),
      panel('panel-stage', 'Time spent on each stage', 'Average days a lead stayed in a stage before moving on, from the stage changes recorded on each lead.', periodFor('panel-stage'), stages),
      panel('panel-brought', 'Brought by', 'Share of leads each person took the enquiry for, and how they turned out.', periodFor('panel-brought'), broughtPie(data.brought_by))));
    if (scrollTo) { document.getElementById(scrollTo)?.scrollIntoView({ block: 'center' }); scrollTo = null; }
  }

  async function load() {
    let data;
    try { data = await api(`/api/lead-analysis?period=${encodeURIComponent(period)}&trend=${encodeURIComponent(trend)}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    render(data);
  }

  load();
})();
