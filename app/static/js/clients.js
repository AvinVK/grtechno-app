/* Clients & Projects: clients only ever come from a won lead now (see app.js), so this is a browse screen,
   not an add screen - grouped by district (the "city" box) then city (the area within it, see
   app/static/css/app.css for why that's the natural way round for this data), both collapsed to start
   with, each client showing just its name and how many projects it has; a search and a service filter
   open every box so no match stays hidden. Clicking a client opens a short look at the relationship (how long they've been a
   client, what their work is worth, their projects); editing their contact details is one tap further. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, money, field, showFieldErrors, pincodeLookup, selectField } = window.LD;

  const view = $('#view');
  const canOpenProjects = view.dataset.projects === '1';
  const STATUS = {
    planned: ['Planned', 'planned'],
    running: ['Running', 'running'],
    on_hold: ['On hold', 'hold'],
    completed: ['Completed', 'done'],
  };
  const sortUnknownLast = (a, b) => (a === 'Not set') - (b === 'Not set') || a.localeCompare(b);

  const statusChip = (s) => {
    const [label, tone] = STATUS[s] || [s, 'planned'];
    return h('span', { class: `chip chip-p-${tone}` }, label);
  };

  /* ---------- list, grouped by area, with a search and a service filter ---------- */

  function clientRow(c) {
    return h('li', {}, h('a', { class: 'client-row', href: `#c${c.id}` },
      h('span', { class: 'client-row-name' }, c.name),
      h('span', { class: 'client-row-count' }, plural(c.project_count, 'project', 'projects'))));
  }

  function areaBlock(area, clients, expand) {
    return h('details', { class: 'area-block', open: expand || undefined },
      h('summary', { class: 'area-title' }, area, h('span', { class: 'p-code' }, plural(clients.length, 'client', 'clients'))),
      h('ul', { class: 'client-list' }, clients.map(clientRow)));
  }

  function cityBox(city, areas, total, expand) {
    return h('details', { class: 'city-box', open: expand || undefined },
      h('summary', { class: 'city-box-title' }, city, h('span', { class: 'p-code' }, plural(total, 'client', 'clients'))),
      h('div', { class: 'city-box-body' }, Object.keys(areas).sort(sortUnknownLast).map((area) => areaBlock(area, areas[area], expand))));
  }

  async function showList() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading clients…'));
    let data;
    try { data = await api('/api/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const filter = { q: '', service: '' };
    const allServices = [...new Set(data.clients.flatMap((c) => c.services))].sort();

    const search = h('input', {
      type: 'search', placeholder: 'Search name, contact, phone, city', 'aria-label': 'Search clients',
      oninput: (e) => { filter.q = e.target.value; refresh(); },
    });
    const serviceSel = selectField(
      [{ value: '', label: 'All services' }, ...allServices.map((s) => ({ value: s, label: s }))],
      '', { title: 'Filter by service', placeholder: 'All services' });
    serviceSel.setAttribute('aria-label', 'Filter by service');
    serviceSel.onchange = () => { filter.service = serviceSel.value; refresh(); };

    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const results = h('div', {});

    function matches(c) {
      const q = filter.q.trim().toLowerCase();
      const textOk = !q || [c.name, c.contact_name, c.phone, c.email, c.city, c.district].some((v) => (v || '').toLowerCase().includes(q));
      const serviceOk = !filter.service || c.services.includes(filter.service);
      return textOk && serviceOk;
    }

    function refresh() {
      const items = data.clients.filter(matches);
      count.textContent = plural(items.length, 'client', 'clients');
      clear(results);
      if (!items.length) {
        results.append(h('p', { class: 'empty-state' }, data.clients.length
          ? 'No clients match this search.'
          : 'No clients yet. A client appears here automatically once a lead is won.'));
        return;
      }
      const byCity = {};
      for (const c of items) {
        const city = c.district || 'Not set';
        const area = c.city || 'Not set';
        if (!byCity[city]) byCity[city] = {};
        if (!byCity[city][area]) byCity[city][area] = [];
        byCity[city][area].push(c);
      }
      const expand = !!(filter.q.trim() || filter.service);       // don't leave a match hidden inside a closed box
      results.append(...Object.keys(byCity).sort(sortUnknownLast).map((city) => {
        const areas = byCity[city];
        const total = Object.values(areas).reduce((n, list) => n + list.length, 0);
        return cityBox(city, areas, total, expand);
      }));
    }

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'Clients & Projects')),
      h('div', { class: 'filters' }, search, serviceSel), count, results));
    refresh();
  }

  /* ---------- one client: how the relationship stands, then their projects ---------- */

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  /* "2 yrs 3 mos", "5 months", "12 days" - how long ago `since` was, in the largest units that read well. */
  function durationSince(since) {
    const now = new Date();
    let months = (now.getFullYear() - since.getFullYear()) * 12 + (now.getMonth() - since.getMonth());
    if (now.getDate() < since.getDate()) months -= 1;
    if (months < 1) {
      const days = Math.max(0, Math.floor((now - since) / 86400000));
      return days === 0 ? 'Today' : plural(days, 'day', 'days');
    }
    if (months < 12) return plural(months, 'month', 'months');
    const years = Math.floor(months / 12);
    const rest = months % 12;
    return rest ? `${plural(years, 'yr', 'yrs')} ${plural(rest, 'mo', 'mos')}` : plural(years, 'year', 'years');
  }

  async function showDetail(id, editing) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading client…'));
    try {
      const data = await api(`/api/clients/${id}`);
      if (editing) renderForm(data.client, data.site_categories);
      else renderSummary(data.client, data.projects, data.currency, data.brought_by);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to clients')));
    }
    window.scrollTo(0, 0);
  }

  function renderSummary(client, projects, currency, broughtBy) {
    const since = new Date(client.created_at);
    const sinceText = `Since ${since.getDate()} ${MONTHS[since.getMonth()]} ${since.getFullYear()}`;

    // What the work is worth: each project's estimate less its discount (net). Projects with no estimate
    // yet are counted separately so the total isn't read as covering them.
    const priced = projects.filter((p) => p.net_amount != null);
    const total = priced.reduce((sum, p) => sum + p.net_amount, 0);
    const unpriced = projects.length - priced.length;
    const valueNote = [plural(projects.length, 'project', 'projects'), unpriced ? `${unpriced} without an amount yet` : null]
      .filter(Boolean).join(' · ');

    const counts = {};
    projects.forEach((p) => { counts[p.status] = (counts[p.status] || 0) + 1; });
    const statusLine = Object.keys(STATUS).filter((s) => counts[s])
      .map((s) => h('span', { class: `chip chip-p-${STATUS[s][1]}` }, `${counts[s]} ${STATUS[s][0].toLowerCase()}`));

    const contact = [client.contact_name, client.phone].filter(Boolean).join(' · ');

    function projectRow(p) {
      const title = `${p.code} · ${p.title}`;
      return h('li', { class: 'client-project' },
        h('span', { class: 'client-project-main' },
          canOpenProjects ? h('a', { href: `/projects#p${p.id}` }, title) : h('span', { class: 'client-project-title' }, title),
          h('span', { class: 'client-project-meta' }, statusChip(p.status), p.services.length ? h('span', {}, p.services.join(', ')) : null)),
        h('span', { class: 'row-value' }, p.net_amount != null ? money(p.net_amount, currency) : '—'));
    }

    clear(view).append(h('div', { class: 'project-detail' },
      h('a', { class: 'back-link', href: '#' }, '← Clients & Projects'),
      h('div', { class: 'client-head' },
        h('div', {},
          h('h2', {}, client.name),
          contact ? h('p', { class: 'hint' }, contact) : null,
          h('p', { class: 'hint client-brought' }, 'Brought by ',
            broughtBy ? [h('strong', {}, broughtBy.name), ` · ${broughtBy.how.toLowerCase()}`] : 'not recorded')),
        h('a', { class: 'btn small', href: `#c${client.id}/edit` }, 'Edit details')),
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Client for'),
          h('span', { class: 'stat-value is-text' }, durationSince(since)),
          h('span', { class: 'stat-note' }, sinceText)),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Total value'),
          h('span', { class: 'stat-value' }, priced.length ? money(total, currency) : '—'),
          h('span', { class: 'stat-note' }, valueNote))),
      statusLine.length ? h('div', { class: 'client-status-line' }, statusLine) : null,
      h('section', { class: 'p-section' },
        h('h3', {}, 'Projects'),
        projects.length
          ? h('ul', { class: 'client-projects' }, projects.map(projectRow))
          : h('p', { class: 'hint' }, 'No projects for this client yet.'))));
  }

  /* ---------- one client: edit contact and site details ---------- */

  function renderForm(client, categories) {
    const C = client;
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const area = (rows, value) => { const t = h('textarea', { rows }); t.value = value ?? ''; return t; };

    const category = selectField(
      [{ value: '', label: 'Not set' }, ...[...new Set([...categories, C.site_category].filter(Boolean))].map((n) => ({ value: n, label: n }))],
      C.site_category || '', { title: 'Site category', placeholder: 'Not set' });
    const pin = text('text', C.pincode, { maxlength: 6, inputmode: 'numeric', autocomplete: 'off' });
    const state = text('text', C.state, { maxlength: 80, autocomplete: 'off' });
    const district = text('text', C.district, { maxlength: 80, autocomplete: 'off' });
    const city = text('text', C.city, { maxlength: 120, autocomplete: 'off' });
    const pinHint = h('p', { class: 'hint', 'aria-live': 'polite' });
    pincodeLookup(pin, { state, district, city }, pinHint);
    const pinField = field('pincode', 'Pincode', pin);
    pinField.append(pinHint);

    const controls = {
      name: text('text', C.name, { maxlength: 160, autocomplete: 'off' }),
      contact_name: text('text', C.contact_name, { maxlength: 120, autocomplete: 'off' }),
      phone: text('tel', C.phone, { maxlength: 40, autocomplete: 'off' }),
      email: text('email', C.email, { maxlength: 160, autocomplete: 'off' }),
      site_category: category, pincode: pin, state, district, city,
      address: area(2, C.address), notes: area(3, C.notes),
    };

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save client');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = {};
        for (const [name, el] of Object.entries(controls)) body[name] = el.value;
        try {
          const saved = await api(`/api/clients/${client.id}`, { method: 'PATCH', body });
          toast('Client saved');
          window.location.hash = `#c${saved.client.id}`;
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('div', { class: 'form-grid' },
        field('name', 'Client name', controls.name, { wide: true }),
        field('contact_name', 'Contact person', controls.contact_name),
        field('phone', 'Phone', controls.phone),
        field('email', 'Email', controls.email),
        field('site_category', 'Site category', controls.site_category),
        pinField,
        field('state', 'State', controls.state),
        field('district', 'District', controls.district),
        field('city', 'City', controls.city),
        field('address', 'Address', controls.address, { wide: true }),
        field('notes', 'Notes', controls.notes, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', { class: 'project-detail' },
      h('a', { class: 'back-link', href: `#c${client.id}` }, `← ${client.name}`),
      h('div', { class: 'p-head' }, h('h2', {}, 'Edit details')),
      form));
  }

  function route() {
    const hash = window.location.hash;
    const m = /^#c(\d+)(\/edit)?$/.exec(hash);
    if (m) return showDetail(Number(m[1]), !!m[2]);
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
