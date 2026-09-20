/* Leads front end. Plain JavaScript, no build step.
   All server data goes through /api/state and the lead endpoints.
   DOM is built with h() and text nodes only, never innerHTML, so lead text cannot inject markup. */
(() => {
  'use strict';

  const VIEWS = ['active', 'add', 'closed', 'status'];
  const CLOSED_STAGES = ['Won', 'Lost'];
  const SNOOZE = [['Tomorrow', 1], ['In 3 days', 3], ['Next week', 7]];

  let S = null;                 // latest server state
  let view = 'active';
  let openId;                   // undefined = drawer closed, otherwise the id of the open lead
  let lastFocus = null;
  const filters = { active: { q: '', stage: '' }, closed: { q: '', stage: '' } };

  const { $, h, clear, api, toast, plural } = window.LD;

  async function load() {
    S = await api('/api/state');
    resolveView();
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

  /* ---------- summary and navigation ---------- */

  function statusView() {
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

    return h('div', { class: 'status-cards' },
      stat('Signed in as', S.me.name, [S.me.userid, S.me.is_admin ? 'Admin: you see every lead' : 'You see only your own leads']),
      stat('Open pipeline', fmtMoney(s.open_value), [plural(s.open_count, 'open lead', 'open leads')]),
      stat('Follow-ups due', String(s.due_count),
        [s.overdue_count ? `${s.overdue_count} overdue` : 'Nothing overdue'],
        { href: '#active', warn: s.overdue_count > 0 }),
      stat('Won this month', String(s.won_month_count), s.won_month_count ? [worth, winNote] : [winNote],
        { href: '#closed' }),
    );
  }

  function renderNav() {
    document.querySelectorAll('.bottom-nav a[data-view]').forEach((a) => {
      if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    const badge = $('.bottom-nav .nav-badge');
    badge.textContent = S.summary.due_count;
    badge.hidden = S.summary.due_count === 0;
  }

  function renderAll() {
    renderNav();
    // Refreshing data must not wipe a half-filled Add lead form.
    if (!(view === 'add' && $('#view .add-lead'))) renderMain();
  }

  function renderMain() {
    const screens = { status: statusView, add: addView };
    clear($('#view')).append(screens[view] ? screens[view]() : listView(view));
  }


  /* ---------- lead lists (active and won / lost) ---------- */

  function listView(kind) {
    const isActive = kind === 'active';
    const stages = isActive ? S.open_stages : CLOSED_STAGES;
    const f = filters[kind];
    const pool = S.leads.filter((l) => stages.includes(l.stage));

    const wrap = h('div', {});
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Filter by stage' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const list = h('ul', { class: 'rows' });

    const search = h('input', {
      type: 'search', placeholder: 'Search name, phone, site, notes', 'aria-label': 'Search leads',
      value: f.q,
      oninput: (e) => { f.q = e.target.value; refresh(); },
    });

    function renderChips() {
      clear(chips);
      const options = [['', 'All', pool.length], ...stages.map((s) => [s, s, pool.filter((l) => l.stage === s).length])];
      for (const [value, label, n] of options) {
        chips.append(h('button', {
          class: 'filter-chip', type: 'button', 'aria-pressed': String(f.stage === value),
          onclick: () => { f.stage = value; renderChips(); refresh(); },
        }, label, h('span', { class: 'n' }, n)));
      }
    }

    function refresh() {
      const q = f.q.trim().toLowerCase();
      const items = pool.filter((l) => {
        if (f.stage && l.stage !== f.stage) return false;
        if (!q) return true;
        return [l.company, l.contact_name, l.phone, l.email, l.site_pincode, l.site_city, l.site_district, l.site_state,
          l.site_address, l.site_category, l.service, l.notes]
          .some((v) => v.toLowerCase().includes(q));
      });
      items.sort(isActive ? byFollowUp : (a, b) => (b.closed_at || '').localeCompare(a.closed_at || ''));

      count.textContent = plural(items.length, 'lead', 'leads');
      clear(list);
      if (!items.length) {
        list.append(h('li', { class: 'empty-state' }, pool.length
          ? 'No leads match this search.'
          : isActive ? 'No active leads. Tap Add lead to enter a new enquiry.'
            : 'Nothing won or lost yet. Open a lead and tap Mark won or Mark lost.'));
        return;
      }
      items.forEach((l) => list.append(h('li', {}, leadRow(l))));
    }

    wrap.append(h('div', { class: 'filters' }, search, chips), count, list);
    if (!isActive) {
      wrap.append(h('p', { class: 'export-note' }, h('a', { href: $('#view').dataset.exportUrl }, 'Export all leads as CSV')));
    }
    renderChips();
    refresh();
    return wrap;
  }

  function leadRow(l) {
    const sub = [subtitle(l), S.me.is_admin && l.owner_name ? `Owner: ${l.owner_name}` : ''].filter(Boolean).join(' · ');
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
    const lead = S.leads.find((l) => l.id === id);
    if (!lead) return;
    lastFocus = document.activeElement;
    openId = id;
    buildDrawer(lead);
    overlay.hidden = false;
    drawer.hidden = false;
    document.body.classList.add('locked');
    $('#drawer-title').focus();
    loadActivity(lead.id);
  }

  function closeDrawer() {
    if (openId === undefined) return;
    openId = undefined;
    drawer.hidden = true;
    clear(drawer);
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

  function buildLeadForm(lead, onSaved) {
    const L = lead || {
      company: '', contact_name: '', phone: '', email: '', site_address: '', service: '', source: '',
      site_category: '', site_pincode: '', site_state: '', site_district: '', site_city: '',
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

    // Typing a full pincode fills state, district and city. They stay editable if the lookup is wrong or missing.
    const pinHint = h('p', { class: 'hint', 'aria-live': 'polite' });
    let pinSeq = 0;
    const pinInput = text('text', L.site_pincode, { maxlength: 6, inputmode: 'numeric', autocomplete: 'off' });
    pinInput.addEventListener('input', async () => {
      const pin = pinInput.value.replace(/\D/g, '').slice(0, 6);
      if (pinInput.value !== pin) pinInput.value = pin;
      const mine = ++pinSeq;
      if (pin.length < 6) { pinHint.textContent = ''; return; }
      pinHint.textContent = 'Looking up\u2026';
      try {
        const found = await api(`/api/pincode/${pin}`);
        if (mine !== pinSeq) return;
        inputs.site_state.value = found.state;
        inputs.site_district.value = found.district;
        inputs.site_city.value = found.city;
        pinHint.textContent = `${found.city}, ${found.district}, ${found.state}`;
      } catch (err) {
        if (mine === pinSeq) pinHint.textContent = err.message;
      }
    });
    const pinField = wrapField('site_pincode', 'Site pincode', pinInput);
    pinField.append(pinHint);

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, lead ? 'Save changes' : 'Add lead');

    const form = h('form', { novalidate: true, id: 'lead-form' },
      errorBox,
      h('div', { class: 'form-grid' },
        wrapField('company', 'Company', text('text', L.company, { maxlength: 160, autocomplete: 'off' })),
        wrapField('contact_name', 'Contact person', text('text', L.contact_name, { maxlength: 120, autocomplete: 'off' })),
        wrapField('phone', 'Phone', text('tel', L.phone, { maxlength: 40, autocomplete: 'off' })),
        wrapField('email', 'Email', text('email', L.email, { maxlength: 160, autocomplete: 'off' })),
        wrapField('site_category', 'Site category', choice(S.settings.site_categories, L.site_category, 'Not set')),
        pinField,
        wrapField('site_state', 'State', text('text', L.site_state, { maxlength: 80, autocomplete: 'off' })),
        wrapField('site_district', 'District', text('text', L.site_district, { maxlength: 80, autocomplete: 'off' })),
        wrapField('site_city', 'City', text('text', L.site_city, { maxlength: 120, autocomplete: 'off' })),
        wrapField('site_address', 'Site address', area(2, L.site_address), 'wide'),
        wrapField('service', 'Service', choice(S.settings.services, L.service, 'Not set')),
        wrapField('source', 'Source', choice(S.settings.sources, L.source, 'Not set')),
        wrapField('est_value', `Estimated value (${S.settings.currency})`,
          text('number', L.est_value, { min: '0', step: 'any', inputmode: 'decimal' })),
        lead ? wrapField('stage', isOpen(lead) ? 'Stage' : 'Status', choice(isOpen(lead) ? S.open_stages : S.stages, L.stage)) : null,
        h('div', { class: 'field wide' },
          wrapField('follow_up_date', 'Follow-up date', dateInput),
          quick),
        wrapField('notes', 'Notes', area(4, L.notes), 'wide'),
      ),
    );

    // Won / Lost is only set by pressing Mark won / Mark lost, which saves the form with that outcome.
    let outcome = null;
    const markOutcome = (result) => {
      if (!window.confirm(`Mark ${title(lead)} as ${result.toLowerCase()}?`)) return;
      outcome = result;
      inputs.stage.append(h('option', { value: result }, result));
      inputs.stage.value = result;
      saveBtn.click();
    };
    const outcomeButtons = lead && isOpen(lead) ? h('div', { class: 'outcome' },
      h('button', { class: 'btn primary', type: 'button', onclick: () => markOutcome('Won') }, 'Mark won'),
      h('button', { class: 'btn danger', type: 'button', onclick: () => markOutcome('Lost') }, 'Mark lost')) : null;

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
      if (isNew) body.stage = S.open_stages[0];
      try {
        if (isNew) await api('/api/leads', { method: 'POST', body });
        else await api(`/api/leads/${lead.id}`, { method: 'PATCH', body });
        onSaved();
        toast(isNew ? 'Lead added' : outcome ? `Marked ${outcome.toLowerCase()}` : 'Changes saved');
        if (isNew && view !== 'active') window.location.hash = '#active';
        await load();
      } catch (err) {
        if (outcome) {
          inputs.stage.querySelector(`option[value="${outcome}"]`)?.remove();
          inputs.stage.value = lead.stage;
          outcome = null;
        }
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

    // The save button lives outside the <form> in the drawer footer, so tie it to the form explicitly.
    saveBtn.setAttribute('form', 'lead-form');
    return { form, saveBtn, outcomeButtons };
  }

  function buildDrawer(lead) {
    const { form, saveBtn, outcomeButtons } = buildLeadForm(lead, closeDrawer);

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

    clear(drawer).append(
      h('div', { class: 'drawer-head' },
        h('h2', { id: 'drawer-title', tabindex: '-1' }, title(lead)),
        h('button', { class: 'btn small', type: 'button', onclick: closeDrawer }, 'Close')),
      h('div', { class: 'drawer-scroll' },
        contactLinks(lead),
        outcomeButtons,
        projectBox(lead),
        form,
        checklistSection(lead.id),
        activitySection(lead.id)),
      h('div', { class: 'drawer-foot' },
        saveBtn,
        h('button', { class: 'btn', type: 'button', onclick: closeDrawer }, 'Cancel'),
        h('span', { class: 'spacer' }),
        remove),
    );
  }

  /* ---------- add lead (a full screen, like the other tabs) ---------- */

  function addView() {
    const { form, saveBtn } = buildLeadForm(null, () => {});
    form.append(h('div', { class: 'form-actions' }, saveBtn));
    return h('div', { class: 'add-lead' },
      h('h2', {}, 'Add lead'),
      h('p', { class: 'hint' }, 'A new lead starts at New enquiry.'),
      form);
  }


  /* ---------- work checklist ---------- */

  let checklistApi = null;

  function checklistSection(id) {
    const input = h('input', { type: 'text', id: 'check-input', maxlength: '200', placeholder: 'Add a step, for example: Site survey done', 'aria-label': 'New checklist item' });
    const error = h('p', { class: 'err', role: 'alert' });
    const base = `/api/leads/${id}/checklist`;
    const call = async (path, opts) => {
      try { renderChecklist((await api(path, opts)).checklist); error.textContent = ''; }
      catch (err) { error.textContent = err.message; }
    };
    checklistApi = {
      toggle: (itemId, done) => call(`${base}/${itemId}`, { method: 'PATCH', body: { done } }),
      remove: (itemId) => call(`${base}/${itemId}`, { method: 'DELETE' }),
    };
    const submit = async (e) => {
      e.preventDefault();
      if (!input.value.trim()) { error.textContent = 'Write the step first'; input.focus(); return; }
      await call(base, { method: 'POST', body: { text: input.value } });
      input.value = '';
      input.focus();
    };
    return h('section', { class: 'activity', 'aria-labelledby': 'checklist-title' },
      h('div', { class: 'checklist-head' },
        h('h3', { id: 'checklist-title' }, 'Checklist'),
        h('span', { class: 'checklist-count', id: 'checklist-count' })),
      h('form', { class: 'note-form', onsubmit: submit }, input, h('button', { class: 'btn', type: 'submit' }, 'Add')),
      error,
      h('ul', { class: 'checklist', id: 'checklist' }));
  }

  function renderChecklist(items) {
    const list = $('#checklist');
    if (!list) return;
    clear(list);
    $('#checklist-count').textContent = items.length ? `${items.filter((i) => i.done).length} of ${items.length} done` : '';
    items.forEach((item) => list.append(h('li', { class: item.done ? 'done' : '' },
      h('label', {},
        h('input', { type: 'checkbox', checked: item.done, onchange: (e) => checklistApi.toggle(item.id, e.target.checked) }),
        h('span', {}, item.text)),
      h('button', { class: 'icon-x', type: 'button', 'aria-label': `Remove ${item.text}`, onclick: () => checklistApi.remove(item.id) }, '\u00d7'))));
  }

  /* ---------- won lead -> project ---------- */

  function projectBox(lead) {
    if (lead.stage !== 'Won') return null;
    const canOpen = S.me.modules.includes('projects');
    let action;
    if (lead.project_id) {
      action = canOpen
        ? h('a', { class: 'btn', href: `/projects#p${lead.project_id}` }, 'Open project')
        : null;
    } else {
      action = h('button', {
        class: 'btn primary', type: 'button',
        onclick: async (e) => {
          if (!window.confirm(`Create a client and a project from ${title(lead)}?`)) return;
          e.target.disabled = true;
          try {
            const res = await api(`/api/leads/${lead.id}/project`, { method: 'POST' });
            closeDrawer();
            toast(`Project ${res.code} created`);
            await load();
            if (canOpen) window.location.href = `/projects#p${res.project_id}`;
          } catch (err) {
            toast(err.message, true);
            e.target.disabled = false;
          }
        },
      }, 'Create project');
    }
    return h('section', { class: 'project-box' },
      h('h3', {}, lead.project_id ? 'This lead is now a project' : 'Won: next step'),
      lead.project_id
        ? (canOpen ? null : h('p', { class: 'hint' }, 'The project manager will complete the work order details.'))
        : h('p', { class: 'hint' }, 'Copy this lead into Clients and Projects so the work order details can be added.'),
      action);
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
      if (openId === id) { renderTimeline(lead.activities); renderChecklist(lead.checklist); }
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* ---------- global events ---------- */

  function resolveView() {
    const next = window.location.hash.slice(1);
    view = VIEWS.includes(next) ? next : 'active';
  }

  function syncView() {
    resolveView();
    if (S) { renderNav(); renderMain(); }
  }

  window.addEventListener('hashchange', syncView);

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
