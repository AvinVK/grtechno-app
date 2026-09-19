/* Lead desk front end. Plain JavaScript, no build step.
   All server data goes through /api/state and the lead endpoints.
   DOM is built with h() and text nodes only, never innerHTML, so lead text cannot inject markup. */
(() => {
  'use strict';

  const VIEWS = ['pipeline', 'followups', 'leads'];
  const SNOOZE = [['Tomorrow', 1], ['In 3 days', 3], ['Next week', 7]];
  const CLOSED_COLUMN_LIMIT = 15;

  let S = null;                 // latest server state
  let view = 'pipeline';
  let openId;                   // undefined = drawer closed, null = new lead, number = existing lead
  let lastFocus = null;
  const filters = { q: '', service: '', stage: '', sort: 'newest' };

  const $ = (sel, root = document) => root.querySelector(sel);

  /* ---------- tiny DOM helper ---------- */

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value' || k === 'selected' || k === 'checked') el[k] = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

  /* ---------- API ---------- */

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Not signed in');
    }
    const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || 'Something went wrong. Try again.');
      err.fields = data.fields || {};
      throw err;
    }
    return data;
  }

  async function load() {
    S = await api('/api/state');
    renderAll();
  }

  /* ---------- dates and money ---------- */

  const parseISO = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const toISO = (d) => d.toISOString().slice(0, 10);
  const addDays = (iso, n) => { const d = parseISO(iso); d.setUTCDate(d.getUTCDate() + n); return toISO(d); };
  const diffDays = (a, b) => Math.round((parseISO(a) - parseISO(b)) / 86400000);

  function fmtDate(iso) {
    const sameYear = iso.slice(0, 4) === S.today.slice(0, 4);
    return parseISO(iso).toLocaleDateString('en-IN', {
      day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric', timeZone: 'UTC',
    });
  }

  const fmtMoney = (v) => (v === null || v === undefined ? '' :
    S.settings.currency + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(v));

  // Indian shorthand (K, L, Cr) when the country code is 91, otherwise K / M / B.
  function fmtCompact(v) {
    const c = S.settings.currency;
    if (S.settings.country_code === '91') {
      const one = (n) => String(Math.round(n * 10) / 10);
      if (v >= 1e7) return `${c}${one(v / 1e7)}Cr`;
      if (v >= 1e5) return `${c}${one(v / 1e5)}L`;
      if (v >= 1e3) return `${c}${one(v / 1e3)}K`;
      return `${c}${Math.round(v)}`;
    }
    return c + new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v);
  }

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  /* ---------- lead helpers ---------- */

  const title = (l) => l.company || l.contact_name;
  const subtitle = (l) => (l.company && l.contact_name ? l.contact_name : '');
  const isOpen = (l) => S.open_stages.includes(l.stage);
  const telNumber = (p) => p.replace(/[^\d+]/g, '');

  function waNumber(p) {
    let digits = p.replace(/\D/g, '');
    if (p.trim().startsWith('+')) return digits;
    digits = digits.replace(/^0+/, '');
    return digits.length === 10 ? S.settings.country_code + digits : digits;
  }

  const byFollowUp = (a, b) => {
    if (a.follow_up_date && b.follow_up_date) {
      return a.follow_up_date.localeCompare(b.follow_up_date) || b.created_at.localeCompare(a.created_at);
    }
    if (a.follow_up_date) return -1;
    if (b.follow_up_date) return 1;
    return b.created_at.localeCompare(a.created_at);
  };

  const chip = (tone, text) => h('span', { class: `chip chip-${tone}` }, text);

  function followChip(l) {
    if (!l.follow_up_date || !isOpen(l)) return null;
    const d = diffDays(l.follow_up_date, S.today);
    if (d < 0) return chip('overdue', `${plural(-d, 'day', 'days')} overdue`);
    if (d === 0) return chip('today', 'Today');
    if (d === 1) return chip('soon', 'Tomorrow');
    return chip('later', fmtDate(l.follow_up_date));
  }

  /* ---------- feedback ---------- */

  let toastTimer;
  function toast(message, isError = false) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), isError ? 4500 : 2600);
  }

  /* ---------- mutations ---------- */

  async function patchLead(id, body, okMessage) {
    try {
      await api(`/api/leads/${id}`, { method: 'PATCH', body });
      if (okMessage) toast(okMessage);
    } catch (err) {
      toast(err.message, true);
    }
    await load();
  }

  async function moveLead(id, stage) {
    const lead = S.leads.find((l) => l.id === id);
    if (!lead || lead.stage === stage) return;
    lead.stage = stage;               // show the move immediately
    renderMain();
    await patchLead(id, { stage }, `Moved to ${stage}`);
  }

  const snooze = (id, days, label) =>
    patchLead(id, { follow_up_date: addDays(S.today, days) }, `Follow-up set for ${label.toLowerCase()}`);

  /* ---------- summary and navigation ---------- */

  function renderSummary() {
    const s = S.summary;
    const stat = (label, value, notes, opts = {}) => {
      const body = [
        h('span', { class: 'stat-label' }, label),
        h('span', { class: 'stat-value' }, value),
        notes.map((n, i) => h('span', { class: `stat-note${opts.warn && i === 0 ? ' warn' : ''}` }, n)),
      ];
      return opts.href ? h('a', { class: 'stat', href: opts.href }, body) : h('div', { class: 'stat' }, body);
    };

    const winNote = s.win_rate === null ? 'No closed leads yet' : `Win rate ${s.win_rate}%`;
    const worth = s.won_month_value ? `Worth ${fmtCompact(s.won_month_value)}` : 'No wins yet this month';
    // Full figure on wide screens, compact (lakh / crore) on phones. CSS picks which one shows.
    const openValue = [
      h('span', { class: 'money-full' }, fmtMoney(s.open_value)),
      h('span', { class: 'money-compact' }, fmtCompact(s.open_value)),
    ];

    clear($('#summary')).append(
      stat('Open pipeline', openValue, [plural(s.open_count, 'open lead', 'open leads')]),
      stat('Follow-ups due', String(s.due_count),
        [s.overdue_count ? `${s.overdue_count} overdue` : 'Nothing overdue'],
        { href: '#followups', warn: s.overdue_count > 0 }),
      stat('Won this month', String(s.won_month_count), s.won_month_count ? [worth, winNote] : [winNote]),
    );
  }

  function renderNav() {
    document.querySelectorAll('.tabs a').forEach((a) => {
      if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    const badge = $('.tabs a[data-view="followups"] .badge');
    badge.textContent = S.summary.due_count;
    badge.hidden = S.summary.due_count === 0;
  }

  function renderAll() {
    renderSummary();
    renderNav();
    renderMain();
  }

  function renderMain() {
    const root = clear($('#view'));
    if (view === 'pipeline') root.append(pipelineView());
    else if (view === 'followups') root.append(followupsView());
    else root.append(leadsView());
  }

  /* ---------- pipeline ---------- */

  function leadCard(l) {
    const sub = subtitle(l);
    const card = h('article', {
      class: 'card',
      tabindex: '0',
      role: 'button',
      draggable: 'true',
      'aria-label': `Open ${title(l)}`,
      onclick: () => openDrawer(l.id),
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(l.id); }
      },
      ondragstart: (e) => {
        e.dataTransfer.setData('text/plain', String(l.id));
        e.dataTransfer.effectAllowed = 'move';
        card.classList.add('dragging');
      },
      ondragend: () => card.classList.remove('dragging'),
    },
      h('h3', { class: 'card-title' }, title(l)),
      sub ? h('p', { class: 'card-sub' }, sub) : null,
      l.service ? h('p', { class: 'card-service' }, l.service) : null,
      h('div', { class: 'card-foot' },
        l.est_value !== null ? h('span', { class: 'value' }, fmtMoney(l.est_value)) : null,
        followChip(l)),
    );
    return card;
  }

  function pipelineView() {
    const board = h('div', { class: 'board' });

    for (const stage of S.stages) {
      const all = S.leads.filter((l) => l.stage === stage);
      const open = S.open_stages.includes(stage);
      all.sort(open ? byFollowUp : (a, b) => (b.closed_at || '').localeCompare(a.closed_at || ''));
      const shown = open ? all : all.slice(0, CLOSED_COLUMN_LIMIT);
      const total = all.reduce((sum, l) => sum + (l.est_value || 0), 0);

      const col = h('section', { class: 'col', 'data-stage': stage, 'aria-label': stage },
        h('div', { class: 'col-head' },
          h('h2', {}, stage),
          h('span', { class: 'col-count' }, all.length),
          h('span', { class: 'col-total' }, fmtCompact(total))),
        h('div', { class: 'col-body' },
          shown.length ? shown.map(leadCard) : h('p', { class: 'col-empty' }, 'No leads here'),
        ),
        all.length > shown.length
          ? h('p', { class: 'col-more' }, `${all.length - shown.length} older. `,
              h('a', { href: '#leads', onclick: () => { filters.stage = stage; } }, 'See all'))
          : null,
      );

      col.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        col.classList.add('drop');
      });
      col.addEventListener('dragleave', (e) => {
        if (!col.contains(e.relatedTarget)) col.classList.remove('drop');
      });
      col.addEventListener('drop', (e) => {
        e.preventDefault();
        col.classList.remove('drop');
        const id = Number(e.dataTransfer.getData('text/plain'));
        if (id) moveLead(id, stage);
      });

      board.append(col);
    }
    return board;
  }

  /* ---------- follow-ups ---------- */

  function followupsView() {
    const open = S.leads.filter(isOpen);
    const buckets = [
      ['Overdue', 'overdue', (d) => d !== null && d < 0],
      ['Today', '', (d) => d === 0],
      ['Next 7 days', '', (d) => d !== null && d >= 1 && d <= 7],
      ['Later', '', (d) => d !== null && d > 7],
      ['No follow-up date', '', (d) => d === null],
    ];
    const daysOf = (l) => (l.follow_up_date ? diffDays(l.follow_up_date, S.today) : null);

    const wrap = h('div', {});
    let any = false;

    for (const [label, cls, test] of buckets) {
      const items = open.filter((l) => test(daysOf(l))).sort(byFollowUp);
      if (!items.length) continue;
      any = true;
      wrap.append(h('section', { class: `group ${cls}` },
        h('div', { class: 'group-head' }, h('h2', {}, label), h('span', { class: 'count' }, items.length)),
        items.map(followupRow),
      ));
    }

    if (!any) {
      wrap.append(h('p', { class: 'empty-state' }, 'No open leads to follow up. Add one with New lead.'));
    }
    return wrap;
  }

  function followupRow(l) {
    const sub = subtitle(l);
    const d = l.follow_up_date ? diffDays(l.follow_up_date, S.today) : null;
    const when = d === null ? null : d < 0 ? `${plural(-d, 'day', 'days')} overdue` : fmtDate(l.follow_up_date);

    return h('div', { class: 'followup' },
      h('div', { class: 'followup-main' },
        h('button', { class: 'followup-title', type: 'button', onclick: () => openDrawer(l.id) }, title(l)),
        h('div', { class: 'followup-meta' },
          sub ? h('span', {}, sub) : null,
          l.service ? h('span', {}, l.service) : null,
          h('span', {}, l.stage),
          l.est_value !== null ? h('span', {}, fmtMoney(l.est_value)) : null,
          when ? h('span', {}, when) : null),
      ),
      h('div', { class: 'followup-actions' },
        l.phone ? h('a', { class: 'btn small primary', href: `tel:${telNumber(l.phone)}`, 'aria-label': `Call ${title(l)}` }, 'Call') : null,
        SNOOZE.map(([label, days]) =>
          h('button', {
            class: 'btn small', type: 'button',
            'aria-label': `${label}: set follow-up for ${title(l)}`,
            onclick: () => snooze(l.id, days, label),
          }, label)),
      ),
    );
  }

  /* ---------- all leads ---------- */

  function leadsView() {
    const wrap = h('div', {});
    const list = h('ul', { class: 'rows' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });

    const select = (name, blank, options, current) => {
      const s = h('select', { 'aria-label': blank },
        h('option', { value: '' }, blank),
        options.map((o) => (Array.isArray(o) ? h('option', { value: o[0] }, o[1]) : h('option', { value: o }, o))));
      s.value = current;
      s.addEventListener('change', () => { filters[name] = s.value; refresh(); });
      return s;
    };

    const search = h('input', {
      type: 'search', placeholder: 'Search name, phone, site, notes', 'aria-label': 'Search leads',
      value: filters.q,
      oninput: (e) => { filters.q = e.target.value; refresh(); },
    });

    const services = [...new Set([...S.settings.services, ...S.leads.map((l) => l.service).filter(Boolean)])];
    const sortSelect = h('select', { class: 'sort', 'aria-label': 'Sort by' },
      [['newest', 'Sort: newest'], ['followup', 'Sort: follow-up date'], ['value', 'Sort: value']]
        .map(([v, t]) => h('option', { value: v }, t)));
    sortSelect.value = filters.sort;
    sortSelect.addEventListener('change', () => { filters.sort = sortSelect.value; refresh(); });

    wrap.append(
      h('div', { class: 'filters' },
        h('div', { class: 'search' }, search),
        select('service', 'All services', services, filters.service),
        select('stage', 'All stages', S.stages, filters.stage),
        sortSelect),
      count,
      list,
      h('p', { class: 'export-note' }, h('a', { href: $('#view').dataset.exportUrl }, 'Export all leads as CSV')),
    );

    function refresh() {
      const q = filters.q.trim().toLowerCase();
      let items = S.leads.filter((l) => {
        if (filters.service && l.service !== filters.service) return false;
        if (filters.stage && l.stage !== filters.stage) return false;
        if (!q) return true;
        return [l.company, l.contact_name, l.phone, l.email, l.site_address, l.service, l.notes]
          .some((f) => f.toLowerCase().includes(q));
      });

      if (filters.sort === 'followup') items.sort(byFollowUp);
      else if (filters.sort === 'value') items.sort((a, b) => (b.est_value ?? -1) - (a.est_value ?? -1));
      else items.sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);

      count.textContent = plural(items.length, 'lead', 'leads');
      clear(list);
      if (!items.length) {
        list.append(h('li', { class: 'empty-state' },
          S.leads.length ? 'No leads match these filters.' : 'No leads yet. Add your first with New lead.'));
        return;
      }
      items.forEach((l) => list.append(h('li', {}, leadRow(l))));
    }

    refresh();
    return wrap;
  }

  function leadRow(l) {
    const sub = subtitle(l);
    return h('button', { class: 'row', type: 'button', onclick: () => openDrawer(l.id) },
      h('span', { class: 'row-main' },
        h('span', { class: 'row-title' }, title(l)),
        sub ? h('span', { class: 'row-sub' }, sub) : null),
      h('span', { class: 'row-service' }, l.service),
      h('span', { class: 'row-stage stage-tag', 'data-stage': l.stage }, l.stage),
      h('span', { class: 'row-value' }, l.est_value !== null ? fmtMoney(l.est_value) : ''),
      h('span', { class: 'row-chip' }, followChip(l)),
    );
  }

  /* ---------- drawer ---------- */

  const drawer = $('#drawer');
  const overlay = $('#overlay');

  function openDrawer(id) {
    lastFocus = document.activeElement;
    openId = id;
    const lead = id === null ? null : S.leads.find((l) => l.id === id);
    if (id !== null && !lead) return;
    buildDrawer(lead);
    overlay.hidden = false;
    drawer.hidden = false;
    document.body.classList.add('locked');
    (lead ? $('#drawer-title') : $('#f-company')).focus();
    if (lead) loadActivity(lead.id);
  }

  function closeDrawer() {
    if (openId === undefined) return;
    openId = undefined;
    drawer.hidden = true;
    overlay.hidden = true;
    document.body.classList.remove('locked');
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }

  function contactLinks(l) {
    const links = [];
    if (l.phone) {
      links.push(h('a', { class: 'btn small', href: `tel:${telNumber(l.phone)}` }, 'Call'));
      links.push(h('a', {
        class: 'btn small', href: `https://wa.me/${waNumber(l.phone)}`, target: '_blank', rel: 'noopener noreferrer',
      }, 'WhatsApp'));
    }
    if (l.email) {
      links.push(h('a', { class: 'btn small', href: `mailto:${encodeURIComponent(l.email).replace('%40', '@')}` }, 'Email'));
    }
    return links.length ? h('div', { class: 'contact-actions' }, links) : null;
  }

  function buildDrawer(lead) {
    const L = lead || {
      company: '', contact_name: '', phone: '', email: '', site_address: '', service: '', source: '',
      est_value: null, stage: S.stages[0], follow_up_date: null, notes: '',
    };
    const inputs = {};

    const wrapField = (name, label, control, cls = '') => {
      control.id = `f-${name}`;
      control.name = name;
      control.setAttribute('aria-describedby', `err-${name}`);
      inputs[name] = control;
      return h('div', { class: `field ${cls}` },
        h('label', { for: `f-${name}` }, label),
        control,
        h('p', { class: 'err', id: `err-${name}`, role: 'alert' }));
    };

    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const area = (rows, value) => { const t = h('textarea', { rows }); t.value = value ?? ''; return t; };
    const choice = (options, value, blank) => {
      const list = [...options];
      if (value && !list.includes(value)) list.push(value);   // keep a value that was removed from Settings
      const s = h('select', {}, blank ? h('option', { value: '' }, blank) : null, list.map((o) => h('option', { value: o }, o)));
      s.value = value || '';
      return s;
    };

    const dateInput = text('date', L.follow_up_date);
    const quick = h('div', { class: 'quick-dates' },
      SNOOZE.map(([label, days]) => h('button', {
        class: 'btn small', type: 'button',
        onclick: () => { dateInput.value = addDays(S.today, days); },
      }, label)));

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, lead ? 'Save changes' : 'Add lead');

    const form = h('form', { novalidate: true, id: 'lead-form' },
      errorBox,
      h('div', { class: 'form-grid' },
        wrapField('company', 'Company', text('text', L.company, { maxlength: 160, autocomplete: 'off' })),
        wrapField('contact_name', 'Contact person', text('text', L.contact_name, { maxlength: 120, autocomplete: 'off' })),
        wrapField('phone', 'Phone', text('tel', L.phone, { maxlength: 40, autocomplete: 'off' })),
        wrapField('email', 'Email', text('email', L.email, { maxlength: 160, autocomplete: 'off' })),
        wrapField('site_address', 'Site address', area(2, L.site_address), 'wide'),
        wrapField('service', 'Service', choice(S.settings.services, L.service, 'Not set')),
        wrapField('source', 'Source', choice(S.settings.sources, L.source, 'Not set')),
        wrapField('est_value', `Estimated value (${S.settings.currency})`,
          text('number', L.est_value, { min: '0', step: 'any', inputmode: 'decimal' })),
        wrapField('stage', 'Stage', choice(S.stages, L.stage)),
        h('div', { class: 'field wide' },
          wrapField('follow_up_date', 'Follow-up date', dateInput),
          quick),
        wrapField('notes', 'Notes', area(4, L.notes), 'wide'),
      ),
    );

    const remove = lead ? h('button', {
      class: 'btn danger', type: 'button',
      onclick: async () => {
        if (!window.confirm(`Delete ${title(lead)}? This also removes its activity log.`)) return;
        try {
          await api(`/api/leads/${lead.id}`, { method: 'DELETE' });
          closeDrawer();
          toast('Lead deleted');
        } catch (err) {
          toast(err.message, true);
        }
        await load();
      },
    }, 'Delete') : null;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      form.querySelectorAll('.err').forEach((p) => { p.textContent = ''; });
      Object.values(inputs).forEach((i) => i.removeAttribute('aria-invalid'));
      errorBox.hidden = true;

      const body = {};
      for (const [name, el] of Object.entries(inputs)) body[name] = el.value;
      if (body.est_value === '') body.est_value = null;
      if (!body.follow_up_date) body.follow_up_date = null;

      saveBtn.disabled = true;
      const isNew = !lead;
      try {
        if (isNew) await api('/api/leads', { method: 'POST', body });
        else await api(`/api/leads/${lead.id}`, { method: 'PATCH', body });
        closeDrawer();
        toast(isNew ? 'Lead added' : 'Changes saved');
        await load();
      } catch (err) {
        errorBox.textContent = err.message;
        errorBox.hidden = false;
        let first = null;
        for (const [name, message] of Object.entries(err.fields || {})) {
          const p = $(`#err-${name}`, form);
          if (p) p.textContent = message;
          if (inputs[name]) { inputs[name].setAttribute('aria-invalid', 'true'); first = first || inputs[name]; }
        }
        (first || errorBox).focus?.();
      } finally {
        saveBtn.disabled = false;
      }
    });

    clear(drawer).append(
      h('div', { class: 'drawer-head' },
        h('h2', { id: 'drawer-title', tabindex: '-1' }, lead ? title(lead) : 'New lead'),
        h('button', { class: 'btn small', type: 'button', onclick: closeDrawer }, 'Close')),
      h('div', { class: 'drawer-scroll' },
        lead ? contactLinks(lead) : null,
        form,
        lead ? activitySection(lead.id) : null),
      h('div', { class: 'drawer-foot' },
        saveBtn,
        h('button', { class: 'btn', type: 'button', onclick: closeDrawer }, 'Cancel'),
        h('span', { class: 'spacer' }),
        remove),
    );
    // The footer sits outside the <form>, so tie the save button to it explicitly.
    saveBtn.setAttribute('form', 'lead-form');
  }

  /* ---------- activity log ---------- */

  function activitySection(id) {
    const input = h('input', { type: 'text', id: 'note-input', maxlength: '2000', placeholder: 'Add a call note or update', 'aria-label': 'New note' });
    const error = h('p', { class: 'err', role: 'alert' });
    const submit = async (e) => {
      e.preventDefault();
      error.textContent = '';
      if (!input.value.trim()) { error.textContent = 'Write a note first'; input.focus(); return; }
      try {
        const lead = await api(`/api/leads/${id}/notes`, { method: 'POST', body: { text: input.value } });
        input.value = '';
        renderTimeline(lead.activities);
        input.focus();
      } catch (err) {
        error.textContent = err.message;
      }
    };
    return h('section', { class: 'activity', 'aria-labelledby': 'activity-title' },
      h('h3', { id: 'activity-title' }, 'Activity'),
      h('form', { class: 'note-form', onsubmit: submit }, input, h('button', { class: 'btn', type: 'submit' }, 'Add note')),
      error,
      h('ul', { class: 'timeline', id: 'timeline' }),
    );
  }

  function renderTimeline(activities) {
    const list = $('#timeline');
    if (!list) return;
    clear(list);
    activities.forEach((a) => {
      const when = new Date(a.created_at).toLocaleString('en-IN', {
        day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
      });
      list.append(h('li', { class: a.kind },
        h('span', { class: 't-text' }, a.text),
        h('time', { datetime: a.created_at }, when)));
    });
  }

  async function loadActivity(id) {
    try {
      const lead = await api(`/api/leads/${id}`);
      if (openId === id) renderTimeline(lead.activities);
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* ---------- global events ---------- */

  function syncView() {
    const next = window.location.hash.slice(1);
    view = VIEWS.includes(next) ? next : 'pipeline';
    if (S) { renderNav(); renderMain(); }
  }

  window.addEventListener('hashchange', syncView);

  $('#new-lead').addEventListener('click', () => { if (S) openDrawer(null); });
  overlay.addEventListener('click', closeDrawer);

  document.addEventListener('keydown', (e) => {
    if (openId === undefined) return;
    if (e.key === 'Escape') { closeDrawer(); return; }
    if (e.key !== 'Tab') return;

    // Keep keyboard focus inside the open drawer.
    const focusable = [...drawer.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex="0"]')]
      .filter((el) => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const at = document.activeElement;
    if (e.shiftKey && (at === first || at === drawer || at.id === 'drawer-title')) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  });

  // Pick up changes made on another device when the tab comes back into view.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && S && openId === undefined) load().catch(() => {});
  });

  function start() {
    syncView();
    load().catch((err) => {
      clear($('#view')).append(h('p', { class: 'empty-state' }, `Could not load leads. ${err.message} `,
        h('button', { class: 'link-btn', type: 'button', onclick: () => window.location.reload() }, 'Try again')));
    });
  }

  start();
})();
