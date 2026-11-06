/* Lead analysis (kohal, 2026-11-05: "have graph of leads per month. leads per source. time spent on each stage. brought by count of
   each lead by each sales man"; then: "make brought by a pie chart and lead per month with filter of 30 days, 1 month, 3 month, 6 month
   and 1 year") - four charts over the leads this person may see, drawn with the shared plain-markup pieces in charts.js. Leads over
   time has a range of its own; the other three share a period. See app/lead_analysis.py for exactly how each figure is worked out. */
(() => {
  'use strict';

  const { $, h, clear, api, selectField } = window.LD;
  const { panel, columnChart, barRows, pieSlices, pieSvg } = window.LD.charts;
  const view = $('#view');
  let period = '30d';                    // the page opens on the last 30 days (kohal, 2026-11-06)
  let trend = '30d';
  let scrollTo = null;                   // the id of the panel whose filter was just changed, kept in view across the reload

  const days = (v) => `${v} day${v === 1 ? '' : 's'}`;

  // Success rate (kohal, 2026-11-06: "success rate of each person who brings lead ... 2 pie charts side by side"): of the leads a
  // person brought that have been decided, the share won. Open leads count neither way.
  const successRate = (p) => (p.won + p.lost ? Math.round((p.won * 100) / (p.won + p.lost)) : null);
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  // One pie with its caption underneath; `slices` are {name, total, colour}.
  function pieFigure(title, slices, total, empty) {
    const pie = h('div', { class: 'pie-wrap' });
    if (total) pie.innerHTML = pieSvg(slices, total);
    return h('figure', { class: 'pie-fig', role: 'img', 'aria-label': `${title}: ${slices.map((s) => `${s.name} ${s.total}`).join(', ') || empty}` },
      total ? pie : h('div', { class: 'pie-wrap pie-empty' }, h('span', {}, empty)),
      h('figcaption', {}, h('b', {}, title), ` · ${total}`));
  }

  // Who brought the leads: the smallest few are grouped into one "Others" slice, with their outcomes added up. Two pies side by side -
  // the share of all leads, and the share of the wins - drawn in the same colour per person, with one legend under both.
  function broughtBy(people) {
    const total = people.reduce((n, p) => n + p.total, 0);
    if (!total) return h('p', { class: 'hint' }, 'No leads in this period.');
    const sum = (rest, key) => rest.reduce((n, p) => n + p[key], 0);
    const slices = pieSlices(people, (rest) => ({ name: `Others (${rest.length})`, total: sum(rest, 'total'), won: sum(rest, 'won'), lost: sum(rest, 'lost'), open: sum(rest, 'open') }));
    const wins = slices.map((s) => ({ ...s, total: s.won })).filter((s) => s.total);
    const totalWins = wins.reduce((n, s) => n + s.total, 0);
    return h('div', {},
      h('div', { class: 'pie-pair' },
        pieFigure('Leads brought', slices, total, 'No leads'),
        pieFigure('Leads won', wins, totalWins, 'No wins yet')),
      h('ul', { class: 'pie-legend' }, slices.map((s) => {
        const rate = successRate(s);
        return h('li', {},
          h('span', { class: 'pie-swatch', style: `background:${s.colour}` }),
          h('span', { class: 'pie-text' },
            h('span', { class: 'bar-name' }, s.name),
            h('span', { class: 'bar-note' }, `${plural(s.total, 'lead')} · ${Math.round((s.total / total) * 100)}% of all leads`),
            h('span', { class: 'bar-note' }, rate === null ? `Success rate: none decided yet · ${s.open} open`
              : `Success rate ${rate}% · ${s.won} won · ${s.lost} lost · ${s.open} open`)));
      })));
  }

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
      panel('panel-brought', 'Brought by', 'Who took the enquiry for each lead, and how often those leads were won (won out of the ones decided).', periodFor('panel-brought'), broughtBy(data.brought_by))));
    if (scrollTo) { document.getElementById(scrollTo)?.scrollIntoView({ block: 'center' }); scrollTo = null; }
  }

  async function load() {
    let data;
    try { data = await api(`/api/lead-analysis?period=${encodeURIComponent(period)}&trend=${encodeURIComponent(trend)}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    render(data);
  }

  load();
})();
