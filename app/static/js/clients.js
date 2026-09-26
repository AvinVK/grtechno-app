/* Clients & Projects: clients only ever come from a won lead now (see app.js), so this is a browse-and-edit
   screen, not an add screen - grouped by district (the "city" box) then city (the area within it, see
   app/static/css/app.css for why that's the natural way round for this data), with a service filter,
   the same grouping the old admin-only "All clients" page used before it was folded in here. Clicking a
   client shows its own projects and their estimates. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, money, field, showFieldErrors, pincodeLookup } = window.LD;

  const view = $('#view');
  const canOpenProjects = view.dataset.projects === '1';
  const STATUS_LABEL = { planned: 'Planned', running: 'Running', on_hold: 'On hold', completed: 'Completed' };

  const sortUnknownLast = (a, b) => (a === 'Not set') - (b === 'Not set') || a.localeCompare(b);

  /* ---------- list, grouped by area with a service filter ---------- */

  function clientRow(c) {
    return h('li', {}, h('a', { class: 'p-row', href: `#c${c.id}` },
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
    const serviceSel = h('select', { 'aria-label': 'Filter by service' },
      h('option', { value: '' }, 'All services'),
      allServices.map((s) => h('option', { value: s }, s)));
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
      const cities = Object.keys(byCity).sort(sortUnknownLast);
      results.append(...cities.map((city) => {
        const areas = byCity[city];
        const total = Object.values(areas).reduce((n, list) => n + list.length, 0);
        return cityBox(city, areas, total);
      }));
    }

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'Clients & Projects')),
      h('div', { class: 'filters' }, search, serviceSel), count, results));
    refresh();
  }

  /* ---------- one client: edit details, see its projects and their estimates ---------- */

  async function showDetail(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading client…'));
    try {
      const data = await api(`/api/clients/${id}`);
      renderForm(data.client, data.projects, data.site_categories, data.currency);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to clients')));
    }
  }

  function renderForm(client, projects, categories, currency) {
    const C = client;
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const area = (rows, value) => { const t = h('textarea', { rows }); t.value = value ?? ''; return t; };

    const category = h('select', {}, h('option', { value: '' }, 'Not set'),
      [...new Set([...categories, C.site_category].filter(Boolean))].map((n) => h('option', { value: n, selected: n === C.site_category }, n)));
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
          renderForm(saved.client, saved.projects, categories, currency);
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

    function projectRow(p) {
      const meta = [STATUS_LABEL[p.status] || p.status, p.services.join(', '), p.estimated_amount != null ? money(p.estimated_amount, currency) : null]
        .filter(Boolean).join(' · ');
      return h('li', {},
        canOpenProjects ? h('a', { href: `/projects#p${p.id}` }, `${p.code} · ${p.title}`) : h('span', {}, `${p.code} · ${p.title}`),
        h('span', { class: 'p-code' }, meta));
    }

    const projectList = h('section', { class: 'p-section' },
      h('div', { class: 'p-section-head' },
        h('h3', {}, 'Projects'),
        C.total_estimated_value != null ? h('span', { class: 'p-code' }, `Total ${money(C.total_estimated_value, currency)}`) : null),
      projects.length
        ? h('ul', { class: 'client-projects' }, projects.map(projectRow))
        : h('p', { class: 'hint' }, 'No projects for this client yet.'));

    clear(view).append(h('div', { class: 'project-detail' },
      h('a', { class: 'back-link', href: '#' }, '← Clients & Projects'),
      h('div', { class: 'p-head' }, h('h2', {}, client.name)),
      form, projectList));
    window.scrollTo(0, 0);
  }

  function route() {
    const hash = window.location.hash;
    const m = /^#c(\d+)$/.exec(hash);
    if (m) return showDetail(Number(m[1]));
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
