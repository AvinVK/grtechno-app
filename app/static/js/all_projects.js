/* All projects (admin only): every project in the company, grouped by area the same way All clients is -
   by site_district (the city box) then site_city (the area within it). Same data /api/projects already
   returns everything to the admin. Clicking a project opens its normal detail page. */
(() => {
  'use strict';

  const { $, h, clear, api, plural } = window.LD;
  const view = $('#view');

  const STATUS_LABEL = { planned: 'Planned', running: 'Running', on_hold: 'On hold', completed: 'Completed' };
  const STATUS_TONE = { planned: 'planned', running: 'running', on_hold: 'hold', completed: 'done' };

  function projectRow(p) {
    return h('li', {}, h('a', { class: 'p-row', href: `/projects#p${p.id}` },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, p.title),
        h('span', { class: 'row-sub' }, [p.code, p.client_name].filter(Boolean).join(' · '))),
      h('span', { class: 'row-value' }, h('span', { class: `chip chip-p-${STATUS_TONE[p.status] || 'planned'}` }, STATUS_LABEL[p.status] || p.status))));
  }

  function areaBlock(area, projects) {
    return h('details', { class: 'area-block' },
      h('summary', { class: 'area-title' }, area, h('span', { class: 'p-code' }, plural(projects.length, 'project', 'projects'))),
      h('ul', { class: 'rows' }, projects.map(projectRow)));
  }

  function cityBox(city, areas, total) {
    return h('details', { class: 'city-box' },
      h('summary', { class: 'city-box-title' }, city, h('span', { class: 'p-code' }, plural(total, 'project', 'projects'))),
      h('div', { class: 'city-box-body' }, Object.keys(areas).sort(sortUnknownLast).map((area) => areaBlock(area, areas[area]))));
  }

  const sortUnknownLast = (a, b) => (a === 'Not set') - (b === 'Not set') || a.localeCompare(b);

  async function showList() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading projects…'));
    let data;
    try { data = await api('/api/projects'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const byCity = {};
    for (const p of data.projects) {
      const city = p.site_district || 'Not set';
      const area = p.site_city || 'Not set';
      if (!byCity[city]) byCity[city] = {};
      if (!byCity[city][area]) byCity[city][area] = [];
      byCity[city][area].push(p);
    }
    const cities = Object.keys(byCity).sort(sortUnknownLast);

    const boxes = cities.map((city) => {
      const areas = byCity[city];
      const total = Object.values(areas).reduce((n, list) => n + list.length, 0);
      return cityBox(city, areas, total);
    });

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'All projects'), h('p', { class: 'result-count' }, plural(data.projects.length, 'project', 'projects'))),
      boxes.length ? boxes : h('p', { class: 'empty-state' }, 'No projects yet.')));
  }

  showList();
})();
