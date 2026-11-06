/* Shared chart pieces (plain markup, no chart library: nothing to load, and it works offline) used by Lead analysis and Client
   analysis: a boxed panel with its filter in the heading's right corner, a column chart, bar rows and a pie with a legend.
   Exposed as window.LD.charts. */
(() => {
  'use strict';

  const { h } = window.LD;

  // A titled block with a one-line explanation under the heading and, in the heading's right corner, the filter that chart uses
  // (kohal, 2026-11-05: "have the period next to the chart heading but right corner").
  const panel = (id, title, about, control, ...body) => h('section', { class: 'analysis-panel', id },
    h('div', { class: 'panel-head' }, h('h3', {}, title), control),
    about ? h('p', { class: 'hint' }, about) : null, ...body);

  // One column per day or month, the count over each. A day-by-day chart labels only some columns so they fit. `t` is
  // {unit, label, total, points: [{label, count}]}; `format` shapes the figure over a column.
  function columnChart(t, { noun = 'Leads received', format = String } = {}) {
    const max = Math.max(1, ...t.points.map((p) => p.count));
    const every = t.points.length > 14 ? 5 : 1;
    return h('div', { class: `col-chart${t.unit === 'day' ? ' dense' : ''}`, role: 'img',
      'aria-label': `${noun}, ${t.label.toLowerCase()}: ${format(t.total)} in all` },
    t.points.map((p, i) => h('div', { class: 'col', title: `${p.label}: ${format(p.count)}` },
      h('span', { class: `col-n${p.count ? '' : ' zero'}` }, t.unit === 'day' && !p.count ? '' : format(p.count)),
      h('span', { class: 'col-bar', style: `height:${Math.round((p.count / max) * 100)}%` }),
      h('span', { class: 'col-label' }, i % every === 0 || i === t.points.length - 1 ? p.label : ''))));
  }

  // One bar per row with the figure at its end; `format` shapes the figure, `note` is the small text under the label.
  // `share` (optional) is how much of the bar is "filled in" a second, darker colour, as a fraction of the row's own value.
  function barRows(rows, { value, label, format = String, note = () => null, share = null }) {
    const max = Math.max(1, ...rows.map((r) => value(r) || 0));
    return h('ul', { class: 'bar-rows' }, rows.map((r) => {
      const v = value(r);
      const width = v ? Math.max(2, Math.round((v / max) * 100)) : 0;
      const inner = share && v ? h('span', { class: 'bar-fill', style: `width:${Math.round(Math.min(Math.max(share(r), 0), 1) * 100)}%` }) : null;
      return h('li', {},
        h('div', { class: 'bar-head' }, h('span', { class: 'bar-name' }, label(r)), h('span', { class: 'bar-val' }, v === null ? '–' : format(v))),
        h('div', { class: 'bar-track' },
          share ? h('span', { class: 'bar-fill bar-fill-soft', style: `width:${width}%` }, inner)
            : h('span', { class: 'bar-fill', style: `width:${width}%` })),
        note(r) ? h('span', { class: 'bar-note' }, note(r)) : null);
    }));
  }

  // A pie with a legend: one slice per item (the smallest few grouped as "Others" so the pie stays readable).
  const PIE_COLOURS = ['#d9391f', '#2f6f8f', '#e0a526', '#4b8b5a', '#7a5195', '#8c6d46', '#c2527a', '#5f6b73'];
  const OTHERS_COLOUR = '#b8afa0';

  // `items` are {name, total, ...}; `others` merges the leftover items into the single "Others" slice.
  function pieSlices(items, others) {
    const keep = items.length > PIE_COLOURS.length ? PIE_COLOURS.length - 1 : items.length;
    const slices = items.slice(0, keep).map((p, i) => ({ ...p, colour: PIE_COLOURS[i] }));
    const rest = items.slice(keep);
    if (rest.length) slices.push({ ...others(rest), colour: OTHERS_COLOUR });
    return slices;
  }

  // The slices as an SVG string (only numbers and fixed colours go into it, so nothing typed by a user is ever inserted as markup).
  function pieSvg(slices, total) {
    const point = (angle) => [50 + 48 * Math.sin(angle), 50 - 48 * Math.cos(angle)].map((n) => n.toFixed(3));
    let start = 0;
    const parts = slices.map((s) => {
      const sweep = (s.total / total) * Math.PI * 2;
      if (slices.length === 1) return `<circle cx="50" cy="50" r="48" fill="${s.colour}"/>`;
      const [x1, y1] = point(start);
      const [x2, y2] = point(start + sweep);
      const d = `M50 50 L${x1} ${y1} A48 48 0 ${sweep > Math.PI ? 1 : 0} 1 ${x2} ${y2} Z`;
      start += sweep;
      return `<path d="${d}" fill="${s.colour}" stroke="#fffdf9" stroke-width="0.8"/>`;
    });
    return `<svg viewBox="0 0 100 100" class="pie-svg" aria-hidden="true">${parts.join('')}</svg>`;
  }

  // `legend(slice, percent)` is the small line under each name; `empty` is shown when there is nothing to draw.
  function pieChart(items, { others, legend, ariaNoun, empty }) {
    const total = items.reduce((n, p) => n + p.total, 0);
    if (!total) return h('p', { class: 'hint' }, empty);
    const slices = pieSlices(items, others);
    const pie = h('div', { class: 'pie-wrap' });
    pie.innerHTML = pieSvg(slices, total);
    return h('div', { class: 'pie-chart', role: 'img', 'aria-label': `${ariaNoun}: ${slices.map((s) => `${s.name} ${s.total}`).join(', ')}` },
      pie,
      h('ul', { class: 'pie-legend' }, slices.map((s) => h('li', {},
        h('span', { class: 'pie-swatch', style: `background:${s.colour}` }),
        h('span', { class: 'pie-text' },
          h('span', { class: 'bar-name' }, s.name),
          h('span', { class: 'bar-note' }, legend(s, Math.round((s.total / total) * 100))))))));
  }

  window.LD.charts = { panel, columnChart, barRows, pieChart, pieSlices, pieSvg };
})();
