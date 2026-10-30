/* Clients & Projects: clients only ever come from a won lead now (see app.js), so this is a browse screen,
   not an add screen - grouped by district (the "city" box) then city (the area within it, see
   app/static/css/app.css for why that's the natural way round for this data), both collapsed to start
   with, each client showing just its name and how many projects it has; a search and a service filter
   open every box so no match stays hidden. Clicking a client opens a short look at the relationship (how long they've been a
   client, what their work is worth, their projects); editing their contact details is one tap further. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, money, fmtShort, field, showFieldErrors, pincodeLookup, selectField, closeOnBack } = window.LD;

  const view = $('#view');
  const canOpenProjects = view.dataset.projects === '1';
  const STATUS = {
    planned: ['Planned', 'planned'],
    running: ['Running', 'running'],
    on_hold: ['On hold', 'hold'],
    final_estimate_sent: ['Final estimate sent', 'sent'],
    completed: ['Completed', 'done'],
  };
  const sortUnknownLast = (a, b) => (a === 'Not set') - (b === 'Not set') || a.localeCompare(b);

  const statusChip = (s) => {
    const [label, tone] = STATUS[s] || [s, 'planned'];
    return h('span', { class: `chip chip-p-${tone}` }, label);
  };

  // The Clients page has no back arrow in its top bar (its bottom tab is the way out), so every screen below the
  // list carries its own way back right under the bar (kohal, 2026-10-30: "no back button to client list").
  const backLink = (href, label) => h('a', { class: 'back-link adhoc-back', href }, `← ${label}`);

  /* ---------- list, grouped by area, with a search and a service filter ---------- */

  let listCurrency = '';

  // A stable hash of the id, so a client keeps the same tile colour across visits (3 tones, see app.css).
  function tileTone(id) {
    let n = id;
    n = ((n >> 16) ^ n) * 0x45d9f3b;
    n = ((n >> 16) ^ n) * 0x45d9f3b;
    n = (n >> 16) ^ n;
    return Math.abs(n) % 3;
  }

  // An initial tile, the name and project count, and what their projects are worth on the right.
  function clientRow(c) {
    return h('li', {}, h('a', { class: 'client-row', href: `#c${c.id}` },
      h('span', { class: 'client-tile', 'data-tone': String(tileTone(c.id)), 'aria-hidden': 'true' }, (c.name[0] || '?').toUpperCase()),
      h('span', { class: 'client-row-main' },
        h('span', { class: 'client-row-name' }, c.name, c.has_logged_in ? h('span', { class: 'client-login-tag' }, 'Has logged in') : null),
        h('span', { class: 'client-row-count' }, c.is_adhoc
          ? [c.phone, plural(c.project_count, 'order', 'orders')].filter(Boolean).join(' \u00b7 ')
          : plural(c.project_count, 'project', 'projects'))),
      c.total_estimated_value != null ? h('span', { class: 'client-row-value' }, fmtShort(c.total_estimated_value, listCurrency)) : null,
      h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›')));
  }

  function areaBlock(area, clients, expand) {
    return h('details', { class: 'area-block', open: expand || undefined },
      h('summary', { class: 'area-title' }, area, h('span', { class: 'p-code', 'aria-label': plural(clients.length, 'client', 'clients') }, clients.length)),
      h('ul', { class: 'card-group' }, clients.map(clientRow)));
  }

  function cityBox(city, areas, total, expand) {
    return h('details', { class: 'city-box', open: expand || undefined },
      h('summary', { class: 'city-box-title' }, city, h('span', { class: 'p-code', 'aria-label': plural(total, 'client', 'clients') }, total)),
      h('div', { class: 'city-box-body' }, Object.keys(areas).sort(sortUnknownLast).map((area) => areaBlock(area, areas[area], expand))));
  }

  function stateBox(state, districts, total, expand) {
    return h('details', { class: 'state-box', open: expand || undefined },
      h('summary', { class: 'state-box-title' }, state, h('span', { class: 'p-code', 'aria-label': plural(total, 'client', 'clients') }, total)),
      h('div', { class: 'state-box-body' }, Object.keys(districts).sort(sortUnknownLast).map((city) => {
        const areas = districts[city];
        const cityTotal = Object.values(areas).reduce((n, list) => n + list.length, 0);
        return cityBox(city, areas, cityTotal, expand);
      })));
  }

  async function showList() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading clients…'));
    let data;
    try { data = await api('/api/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    listCurrency = data.currency;

    // 'all' = the normal clients, 'logged' = the normal clients who have logged in, 'adhoc' = the adhoc ones, kept
    // as their own list (kohal, 2026-10-30: "option 2" - a separate list).
    const filter = { q: '', service: '', tab: 'all' };
    const normal = data.clients.filter((c) => !c.is_adhoc);
    const adhoc = data.clients.filter((c) => c.is_adhoc);
    const allServices = [...new Set(normal.flatMap((c) => c.services))].sort();

    // "Logged in clients" subtab (kohal, 2026-10-22: "in the client tab, have one subtab called logged in
    // clients") - same filter-chip pattern as the Projects list's own status chips.
    const tabs = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Filter clients' });
    function renderTabs() {
      clear(tabs);
      const loggedInCount = normal.filter((c) => c.has_logged_in).length;
      const options = [['all', 'All clients', normal.length], ['logged', 'Logged in clients', loggedInCount], ['adhoc', 'Adhoc', adhoc.length]];
      for (const [value, label, n] of options) {
        tabs.append(h('button', {
          class: 'filter-chip', type: 'button', 'aria-pressed': String(filter.tab === value),
          onclick: () => { filter.tab = value; renderTabs(); refresh(); },
        }, label, h('span', { class: 'n' }, n)));
      }
    }

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
      const textOk = !q || [c.name, c.contact_name, c.phone, c.email, c.city, c.district, c.state].some((v) => (v || '').toLowerCase().includes(q));
      const serviceOk = !filter.service || c.services.includes(filter.service);
      const loggedInOk = filter.tab !== 'logged' || c.has_logged_in;
      const kindOk = filter.tab === 'adhoc' ? c.is_adhoc : !c.is_adhoc;
      return textOk && serviceOk && loggedInOk && kindOk;
    }

    function refresh() {
      const items = data.clients.filter(matches);
      count.textContent = plural(items.length, 'client', 'clients');
      clear(results);
      serviceSel.hidden = filter.tab === 'adhoc';       // services only describe the normal clients
      if (filter.tab === 'adhoc') {
        // Adhoc clients have no site, only an address - one plain list, newest first.
        results.append(items.length
          ? h('ul', { class: 'card-group' }, items.map(clientRow))
          : h('p', { class: 'empty-state' }, adhoc.length ? 'No adhoc clients match this search.' : 'No adhoc clients yet. Use + Client, then Adhoc client.'));
        return;
      }
      if (!items.length) {
        results.append(h('p', { class: 'empty-state' }, normal.length
          ? 'No clients match this search.'
          : 'No clients yet. A client appears here automatically once a lead is won.'));
        return;
      }
      // State, then district (the "city" box), then city (the area within it) - three levels deep, each
      // collapsed to start with.
      const byState = {};
      for (const c of items) {
        const state = c.state || 'Not set';
        const city = c.district || 'Not set';
        const area = c.city || 'Not set';
        if (!byState[state]) byState[state] = {};
        if (!byState[state][city]) byState[state][city] = {};
        if (!byState[state][city][area]) byState[state][city][area] = [];
        byState[state][city][area].push(c);
      }
      const expand = !!(filter.q.trim() || filter.service || filter.tab === 'logged');  // don't leave a match hidden inside a closed box
      results.append(...Object.keys(byState).sort(sortUnknownLast).map((state) => {
        const districts = byState[state];
        const total = Object.values(districts).reduce((n, areas) => n + Object.values(areas).reduce((m, list) => m + list.length, 0), 0);
        return stateBox(state, districts, total, expand);
      }));
    }

    clear(view).append(h('div', {},
      tabs,
      h('div', { class: 'filters' }, search, serviceSel),
      count, results));
    renderTabs();
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
      else renderSummary(data.client, data.projects, data.currency, data.brought_by, data.is_admin, data.login);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to clients')));
    }
    window.scrollTo(0, 0);
  }

  // What the admin hands a client once they have a login (kohal, 2026-10-26: "no need for setup code as
  // well. as soon as give login access is clicked, it should show login phone number and share link on
  // whatsapp to the client. that client just needs to enter the contact and see the projects") - nothing
  // secret to reveal once any more: the client's phone number is the whole sign-in, so this is just the
  // number and a WhatsApp message with the sign-in link.
  function showLoginLink(resultBox, data, client) {
    const u = data.user;
    const link = `${window.location.origin}/welcome`;
    const message = `GR Techno Fire Safety

See your projects here:
${link}

Sign in with your phone number: ${u.userid}`;
    clear(resultBox).append(h('section', { class: 'code-card' },
      h('h3', {}, `Login for ${client.name}`),
      h('dl', {}, h('dt', {}, 'Phone number (login)'), h('dd', { class: 'code-value' }, u.userid)),
      h('p', { class: 'hint' }, 'They open the link, enter this phone number and see their projects. No code or PIN.'),
      h('div', { class: 'code-actions' },
        h('a', { class: 'btn primary', href: `https://wa.me/?text=${encodeURIComponent(message)}`, target: '_blank', rel: 'noopener noreferrer' }, 'Share on WhatsApp'),
        h('button', { class: 'btn', type: 'button', onclick: async () => {
          try { await navigator.clipboard.writeText(link); toast('Copied'); }
          catch (err) { toast('Could not copy. Select the link and copy it.', true); }
        } }, 'Copy link')),
      h('button', { class: 'link-btn code-done', type: 'button', onclick: () => { resultBox.hidden = true; clear(resultBox); } }, 'Done')));
    resultBox.hidden = false;
    resultBox.scrollIntoView({ block: 'nearest' });
  }

  // TEMPORARY (admin only): removes a duplicate client. The server refuses while the client has projects.
  async function deleteClient(client) {
    const ok = await LD.confirm(`Delete ${client.name}? This can't be undone.`, { ok: 'Delete', danger: true });
    if (!ok) return;
    try {
      await api(`/api/clients/${client.id}`, { method: 'DELETE' });
      toast('Client deleted');
      window.location.hash = '#';
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderSummary(client, projects, currency, broughtBy, isAdmin, login) {
    LD.setAppbarBack?.('Clients', '#');
    const resultBox = h('div', { hidden: true, 'aria-live': 'polite' });
    const loginBtn = h('button', { class: 'btn small', type: 'button' }, login ? 'Share login again' : 'Give login access');
    loginBtn.onclick = async () => {
      loginBtn.disabled = true;
      try {
        const data = await api(`/api/clients/${client.id}/login`, { method: 'POST' });
        showLoginLink(resultBox, data, client);
      } catch (err) {
        toast(err.message, true);
      } finally {
        loginBtn.disabled = false;
      }
    };
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
      backLink('#', 'Back to clients'),
      h('div', { class: 'client-head' },
        h('div', {},
          h('h2', {}, client.name),
          contact ? h('p', { class: 'hint' }, contact) : null,
          client.is_adhoc ? h('p', { class: 'hint' }, 'Adhoc client') : h('p', { class: 'hint client-brought' }, 'Brought by ',
            broughtBy ? [h('strong', {}, broughtBy.name), ` · ${broughtBy.how.toLowerCase()}`] : 'not recorded')),
        h('a', { class: 'btn small', href: `#c${client.id}/edit` }, 'Edit details')),
      isAdmin ? h('div', { class: 'client-login-row' },
        login ? h('p', { class: 'hint' }, `Client login: ${login.userid} (${login.status})`) : null,
        loginBtn) : null,
      resultBox,
      isAdmin ? h('p', { class: 'hint' }, h('button', { class: 'btn small danger', type: 'button', onclick: () => deleteClient(client) }, 'Delete client (temporary)')) : null,
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
          : h('p', { class: 'hint' }, 'No projects for this client yet.'),
        client.is_adhoc
          ? h('a', { class: 'btn primary add-project-btn', href: `#adhoc/c${client.id}` }, '+ New order')
          : (canOpenProjects ? h('a', { class: 'btn primary add-project-btn', href: `/projects#new/c${client.id}` }, '+ Add project') : null))));
  }

  /* ---------- one client: edit contact and site details ---------- */

  function renderForm(client, categories) {
    LD.setAppbarBack?.(client.name, `#c${client.id}`);
    const C = client;
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const area = (rows, value) => { const t = h('textarea', { rows }); t.value = value ?? ''; return t; };

    const category = LD.categoryPicker(categories, C.site_category, { blank: 'Not set', title: 'Site category' });
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
      site_name: text('text', C.site_name, { maxlength: 160, autocomplete: 'off' }),
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
        field('site_name', 'Site name', controls.site_name),
        field('site_category', 'Site category', controls.site_category),
        pinField,
        field('state', 'State', controls.state),
        field('district', 'District', controls.district),
        field('city', 'City', controls.city),
        field('address', 'Address', controls.address, { wide: true }),
        field('notes', 'Notes', controls.notes, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', { class: 'project-detail' },
      backLink(`#c${C.id}`, 'Back to client'),
      h('div', { class: 'p-head' }, h('h2', {}, 'Edit details')),
      form));
  }

  /* ---------- add a client directly (old clients who never came in as a lead) ---------- */

  async function showNew() {
    LD.setAppbarBack?.('Clients', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    renderNewForm(data.site_categories);
  }

  // A label with the red asterisk the enquiry form puts on mandatory fields.
  const req = (text) => [text, h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *')];

  // The same fields as the new-enquiry form: company, contact, site and its address, notes.
  function renderNewForm(categories) {
    const text = (type, extra = {}) => h('input', { type, value: '', ...extra });
    const area = (rows) => h('textarea', { rows });

    const category = LD.categoryPicker(categories, '', { blank: 'Not set', title: 'Site category' });
    const pin = text('text', { maxlength: 6, inputmode: 'numeric', autocomplete: 'off' });
    const state = text('text', { maxlength: 80, autocomplete: 'off' });
    const district = text('text', { maxlength: 80, autocomplete: 'off' });
    const city = text('text', { maxlength: 120, autocomplete: 'off' });
    const pinHint = h('p', { class: 'hint', 'aria-live': 'polite' });
    pincodeLookup(pin, { state, district, city }, pinHint);
    const pinField = field('pincode', 'Pincode', pin);
    pinField.append(pinHint);

    const controls = {
      name: text('text', { maxlength: 160, autocomplete: 'off' }),
      contact_name: text('text', { maxlength: 120, autocomplete: 'off' }),
      phone: text('tel', { maxlength: 40, autocomplete: 'off' }),
      email: text('email', { maxlength: 160, autocomplete: 'off' }),
      site_name: text('text', { maxlength: 160, autocomplete: 'off' }),
      site_category: category, pincode: pin, state, district, city,
      address: area(2), notes: area(3),
    };

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Add client');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        // The same fields the enquiry form makes mandatory (email and notes stay optional).
        const missing = {};
        for (const name of ['name', 'contact_name', 'phone', 'site_name', 'site_category', 'pincode', 'state', 'district', 'city', 'address']) {
          if (!controls[name].value.trim()) missing[name] = 'This field is required';
        }
        if (Object.keys(missing).length) {
          errorBox.textContent = 'Check the highlighted fields';
          errorBox.hidden = false;
          (showFieldErrors(form, missing) || errorBox).focus?.();
          return;
        }
        saveBtn.disabled = true;
        const body = {};
        for (const [name, el] of Object.entries(controls)) body[name] = el.value;
        try {
          const saved = await api('/api/clients', { method: 'POST', body });
          toast('Client added');
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
        field('name', req('Company'), controls.name, { wide: true }),
        field('contact_name', req('Contact person'), controls.contact_name),
        field('phone', req('Phone'), controls.phone),
        field('email', 'Email', controls.email),
        field('site_name', req('Site name'), controls.site_name),
        field('site_category', req('Site category'), controls.site_category),
        (() => { pinField.querySelector('label').replaceWith(...req('Pincode')); return pinField; })(),
        field('state', req('State'), controls.state),
        field('district', req('District'), controls.district),
        field('city', req('City'), controls.city),
        field('address', req('Address'), controls.address, { wide: true }),
        field('notes', 'Notes', controls.notes, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', { class: 'project-detail' },
      backLink('#', 'Back to clients'),
      h('div', { class: 'p-head' }, h('h2', {}, 'Add client')),
      form));
  }

  /* ---------- + Client: normal or adhoc? ---------- */

  function openChooser() {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    // Closing the box also steps the history back once (closeOnBack's pushed entry), which lands a moment
    // later - so the move to the form waits for that, or the back step would undo it and leave the list showing
    // (kohal, 2026-10-30: "when i click on adhoc client, its not opening the form").
    const go = (hash) => {
      const stepsBack = !!(history.state && history.state.ldOverlay != null);
      finish();
      if (stepsBack) window.addEventListener('popstate', () => { window.location.hash = hash; }, { once: true });
      else window.location.hash = hash;
    };
    const choice = (title, sub, hash) => h('button', {
      type: 'button', class: 'card me-row approval-row chooser-row',
      onclick: () => go(hash),
    }, h('div', { class: 'approval-main' }, h('strong', {}, title), h('span', { class: 'hint' }, sub)));
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Add a client'),
      choice('Normal client', 'A company or site we do installation work for.', '#new'),
      choice('Adhoc client', 'Buys or gets extinguishers refilled now and then. Found by contact number.', '#adhoc'),
      h('div', { class: 'confirm-actions' }, h('button', { class: 'btn', type: 'button', onclick: () => finish() }, 'Cancel'))));
    document.body.append(overlay);
  }
  $('#add-client-btn')?.addEventListener('click', openChooser);

  /* ---------- adhoc order: a new or existing adhoc client, one service, and its items ---------- */

  async function showAdhoc(presetId) {
    LD.setAppbarBack?.(presetId ? 'Client' : 'Clients', presetId ? `#c${presetId}` : '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    let data;
    try { data = await api('/api/adhoc/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = (await api('/api/clients').catch(() => ({ currency: '' }))).currency;

    const state = { who: presetId ? 'existing' : 'new', service: '' };
    const text = (type, extra = {}) => h('input', { type, value: '', ...extra });
    const nameIn = text('text', { maxlength: 160, autocomplete: 'off' });
    const addressIn = h('textarea', { rows: 2, maxlength: 400 });
    const phoneIn = text('tel', { maxlength: 40, autocomplete: 'off', inputmode: 'numeric' });
    const existingSel = selectField(
      data.clients.map((c) => ({ value: String(c.id), label: `${c.name} \u00b7 ${c.phone}` })),
      presetId ? String(presetId) : '', { title: 'Choose an adhoc client', placeholder: 'Choose a client' });

    // A refresh must not wipe a half-filled order (kohal, 2026-10-30: "refresh should not clear the form"), so
    // what has been typed is kept as a draft in the browser and put back when the form opens again; it is
    // cleared when the order is saved or the person chooses Start over.
    const DRAFT_KEY = 'adhoc-order-draft';
    const readDraft = () => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { return null; } };
    const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* storage unavailable - nothing to clear */ } };
    const saved = readDraft();
    const restored = !!(saved && (saved.preset || null) === (presetId || null)
      && (saved.name || saved.address || saved.phone || saved.service || (saved.items || []).some((i) => Object.values(i).some(Boolean))));
    if (restored) {
      state.who = saved.who === 'existing' ? 'existing' : state.who;
      state.service = data.services.some((x) => x.key === saved.service) ? saved.service : '';
      state.draftItems = saved.items || [];
      nameIn.value = saved.name || '';
      addressIn.value = saved.address || '';
      phoneIn.value = saved.phone || '';
      if (saved.existingId && data.clients.some((c) => String(c.id) === String(saved.existingId))) existingSel.value = String(saved.existingId);
    }

    const whoBox = h('div', {});
    const serviceBox = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Service' });
    const itemsBox = h('div', {});
    let editor = null;
    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save order');
    const whoTabs = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'New or existing client' });

    function renderWho() {
      clear(whoTabs);
      [['new', 'New client'], ['existing', 'Existing client']].forEach(([key, label]) => whoTabs.append(h('button', {
        class: 'filter-chip', type: 'button', 'aria-pressed': String(state.who === key),
        onclick: () => { state.who = key; renderWho(); },
      }, label)));
      clear(whoBox).append(state.who === 'new'
        ? h('div', { class: 'form-grid' },
          field('name', req('Client name'), nameIn, { wide: true }),
          field('address', req('Address'), addressIn, { wide: true }),
          field('phone', req('Contact no'), phoneIn, { hint: 'Their 10-digit number. It is how this client is found next time.' }))
        : h('div', { class: 'form-grid' },
          field('client_id', req('Adhoc client'), existingSel, { wide: true,
            hint: data.clients.length ? null : 'There are no adhoc clients yet - use New client first.' })));
    }

    function renderService() {
      clear(serviceBox);
      data.services.forEach((s) => serviceBox.append(h('button', {
        class: 'filter-chip', type: 'button', 'aria-pressed': String(state.service === s.key),
        onclick: () => { state.service = s.key; renderService(); renderItems(); },
      }, s.label)));
    }

    function renderItems() {
      clear(itemsBox);
      editor = null;
      if (!state.service) { itemsBox.append(h('p', { class: 'hint' }, 'Choose what this order is for.')); return; }
      editor = window.ADHOC.itemsEditor(state.service, state.draftItems || [], cur);
      state.draftItems = null;
      itemsBox.append(h('h3', {}, state.service === 'refilling' ? 'Items to refill' : 'Items supplied'), editor.node);
    }

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        editor?.showErrors({});
        saveBtn.disabled = true;
        const body = { service: state.service, items: editor ? editor.getItems() : [] };
        if (state.who === 'existing') body.client_id = existingSel.value;
        else Object.assign(body, { name: nameIn.value, address: addressIn.value, phone: phoneIn.value });
        try {
          const res = await api('/api/adhoc/orders', { method: 'POST', body });
          clearDraft();
          toast('Order saved');
          if (canOpenProjects) window.location.href = `/projects#p${res.project_id}`;
          else window.location.hash = `#c${res.client_id}`;
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          // The items' errors ('items.0.qty'...) belong to the editor's own boxes; the plain form fields go through
          // showFieldErrors (which looks them up by id, and an id with dots in it isn't a valid selector).
          const plain = Object.fromEntries(Object.entries(err.fields || {}).filter(([k]) => !k.startsWith('items')));
          const first = showFieldErrors(form, plain);
          const firstItem = editor ? editor.showErrors(err.fields) : null;
          (first || firstItem || errorBox).scrollIntoView?.({ block: 'center' });
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('section', { class: 'p-section' }, h('h3', {}, 'Client'), whoTabs, whoBox),
      h('section', { class: 'p-section' }, h('h3', {}, 'Service'), serviceBox, h('p', { class: 'err', id: 'err-service', role: 'alert' })),
      h('section', { class: 'p-section' }, itemsBox),
      h('div', { class: 'form-actions' }, saveBtn));

    function saveDraft() {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({
          preset: presetId || null, who: state.who, service: state.service, name: nameIn.value, address: addressIn.value,
          phone: phoneIn.value, existingId: existingSel.value, items: editor ? editor.getItems() : [],
        }));
      } catch (e) { /* storage full or blocked - the form still works, it just won't survive a refresh */ }
    }
    // After every edit, and after every click (chips, Add more, Remove) once its own handler has run.
    ['input', 'change'].forEach((type) => form.addEventListener(type, saveDraft));
    form.addEventListener('click', () => setTimeout(saveDraft, 0));

    renderWho();
    renderService();
    renderItems();
    clear(view).append(h('div', { class: 'project-detail' },
      backLink(presetId ? `#c${presetId}` : '#', presetId ? 'Back to client' : 'Back to clients'),
      h('div', { class: 'p-head' }, h('h2', {}, 'Adhoc order')),
      restored ? h('p', { class: 'hint' }, 'What you had typed has been put back. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => { clearDraft(); showAdhoc(presetId); } }, 'Start over')) : null,
      form));
    window.scrollTo(0, 0);
  }

  function route() {
    const hash = window.location.hash;
    // "+ Client" is for starting a client - not shown while already on a client form.
    const addBtn = $('#add-client-btn');
    if (addBtn) addBtn.hidden = hash === '#new' || hash.startsWith('#adhoc');
    if (hash === '#new') return showNew();
    const adhocRoute = /^#adhoc(?:\/c(\d+))?$/.exec(hash);
    if (adhocRoute) return showAdhoc(adhocRoute[1] ? Number(adhocRoute[1]) : null);
    const m = /^#c(\d+)(\/edit)?$/.exec(hash);
    if (m) return showDetail(Number(m[1]), !!m[2]);
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
