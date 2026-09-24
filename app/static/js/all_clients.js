/* All clients (admin only): every client in the company, grouped by area - not the Clients service's own
   list, which each person sees scoped to their own work. Same data (/api/clients already returns
   everything to the admin), just grouped by district (shown as the city box) then by city (the area
   within it) - in this data the "city" column is the specific town (Warora, Bramhapuri, ...) and
   "district" is the place people would recognise (Chandrapur), so that is the natural way round.
   Clicking a client's project count opens its normal detail page, which lists its projects. */
(() => {
  'use strict';

  const { $, h, clear, api, plural } = window.LD;
  const view = $('#view');

  function clientRow(c) {
    return h('li', {}, h('a', { class: 'p-row', href: `/clients#c${c.id}` },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, c.name),
        h('span', { class: 'row-sub' }, [c.contact_name, c.phone].filter(Boolean).join(' · '))),
      h('span', { class: 'row-value' }, plural(c.project_count, 'project', 'projects'))));
  }

  function areaBlock(area, clients) {
    return h('details', { class: 'area-block' },
      h('summary', { class: 'area-title' }, area, h('span', { class: 'p-code' }, plural(clients.length, 'client', 'clients'))),
      h('ul', { class: 'rows' }, clients.map(clientRow)));
  }

  function cityBox(city, areas, total) {
    return h('details', { class: 'city-box' },
      h('summary', { class: 'city-box-title' }, city, h('span', { class: 'p-code' }, plural(total, 'client', 'clients'))),
      h('div', { class: 'city-box-body' }, Object.keys(areas).sort(sortUnknownLast).map((area) => areaBlock(area, areas[area]))));
  }

  const sortUnknownLast = (a, b) => (a === 'Not set') - (b === 'Not set') || a.localeCompare(b);

  async function showList() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading clients…'));
    let data;
    try { data = await api('/api/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const byCity = {};
    for (const c of data.clients) {
      const city = c.district || 'Not set';
      const area = c.city || 'Not set';
      if (!byCity[city]) byCity[city] = {};
      if (!byCity[city][area]) byCity[city][area] = [];
      byCity[city][area].push(c);
    }
    const cities = Object.keys(byCity).sort(sortUnknownLast);

    const boxes = cities.map((city) => {
      const areas = byCity[city];
      const total = Object.values(areas).reduce((n, list) => n + list.length, 0);
      return cityBox(city, areas, total);
    });

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'All clients'), h('p', { class: 'result-count' }, plural(data.clients.length, 'client', 'clients'))),
      boxes.length ? boxes : h('p', { class: 'empty-state' }, 'No clients yet.')));
  }

  showList();
})();
