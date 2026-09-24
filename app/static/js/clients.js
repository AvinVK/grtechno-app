/* Clients: a searchable list, and one screen per client (edit details, see their projects). */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, field, showFieldErrors, pincodeLookup } = window.LD;

  const view = $('#view');
  const canOpenProjects = view.dataset.projects === '1';
  const filter = { q: '' };
  // Arriving here from the admin's All clients page is a full page load, so the referrer is still
  // set when this script starts - send the back link there instead of to this person's own Clients
  // list, which for a non-admin browsing their own clients (referrer unset) is the right place instead.
  const backLinkHref = document.referrer.endsWith('/all-clients') ? '/all-clients' : '#';
  const STATUS_LABEL = { planned: 'Planned', running: 'Running', on_hold: 'On hold', completed: 'Completed' };

  /* ---------- list ---------- */

  async function showList() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading clients…'));
    let data;
    try { data = await api('/api/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const list = h('ul', { class: 'rows' });
    const search = h('input', {
      type: 'search', placeholder: 'Search name, contact, phone, city', 'aria-label': 'Search clients',
      value: filter.q, oninput: (e) => { filter.q = e.target.value; refresh(); },
    });

    function refresh() {
      const q = filter.q.trim().toLowerCase();
      const items = data.clients.filter((c) => !q
        || [c.name, c.contact_name, c.phone, c.email, c.city, c.district].some((v) => (v || '').toLowerCase().includes(q)));
      count.textContent = plural(items.length, 'client', 'clients');
      clear(list);
      if (!items.length) {
        list.append(h('li', { class: 'empty-state' }, data.clients.length
          ? 'No clients match this search.'
          : 'No clients yet. They appear when a won lead becomes a project, or add one with Add client.'));
        return;
      }
      items.forEach((c) => list.append(h('li', {}, h('a', { class: 'p-row', href: `#c${c.id}` },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, c.name),
          h('span', { class: 'row-sub' }, [c.contact_name, c.city].filter(Boolean).join(' · '))),
        h('span', { class: 'row-value' }, plural(c.project_count, 'project', 'projects')),
        h('span', { class: 'p-foot' }, c.site_category ? h('span', { class: 'p-code' }, c.site_category) : null)))));
    }

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'Clients'), h('a', { class: 'btn primary', href: '#new' }, 'Add client')),
      h('div', { class: 'filters' }, search), count, list));
    refresh();
  }

  /* ---------- one client (also the "add client" form) ---------- */

  async function showDetail(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading client…'));
    try {
      const data = await api(`/api/clients/${id}`);
      renderForm(data.client, data.projects, data.site_categories);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to clients')));
    }
  }

  async function showNew() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    try {
      renderForm(null, [], (await api('/api/clients')).site_categories);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
    }
  }

  function renderForm(client, projects, categories) {
    const C = client || { name: '', contact_name: '', phone: '', email: '', site_category: '', pincode: '', state: '', district: '', city: '', address: '', notes: '' };
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
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, client ? 'Save client' : 'Add client');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = {};
        for (const [name, el] of Object.entries(controls)) body[name] = el.value;
        try {
          if (client) {
            const saved = await api(`/api/clients/${client.id}`, { method: 'PATCH', body });
            toast('Client saved');
            renderForm(saved.client, saved.projects, categories);
          } else {
            const saved = await api('/api/clients', { method: 'POST', body });
            toast('Client added');
            window.location.hash = `#c${saved.client.id}`;
          }
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

    const projectList = client ? h('section', { class: 'p-section' },
      h('h3', {}, 'Projects'),
      projects.length
        ? h('ul', { class: 'client-projects' }, projects.map((p) => h('li', {},
          canOpenProjects ? h('a', { href: `/projects#p${p.id}` }, `${p.code} · ${p.title}`) : h('span', {}, `${p.code} · ${p.title}`),
          h('span', { class: 'p-code' }, STATUS_LABEL[p.status] || p.status))))
        : h('p', { class: 'hint' }, 'No projects for this client yet.')) : null;

    clear(view).append(h('div', { class: 'project-detail' },
      h('a', { class: 'back-link', href: backLinkHref }, '← All clients'),
      h('div', { class: 'p-head' }, h('h2', {}, client ? client.name : 'Add client')),
      form, projectList));
    window.scrollTo(0, 0);
  }

  function route() {
    const hash = window.location.hash;
    const m = /^#c(\d+)$/.exec(hash);
    if (m) return showDetail(Number(m[1]));
    if (hash === '#new') return showNew();
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
