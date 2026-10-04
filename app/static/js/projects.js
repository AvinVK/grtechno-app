/* Projects: a list, and one screen per project - a dashboard (how long it has been running, who brought it,
   who has worked on it, and Close project for the admin), with the work order, amounts, terms and payment
   schedule one tap further, behind Edit details. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, money, fmtShort, field, showFieldErrors, selectField, dateField, confirm, closeOnBack } = window.LD;

  const STATUS = {
    planned: ['Planned', 'planned'],
    running: ['Running', 'running'],
    on_hold: ['On hold', 'hold'],
    final_estimate_sent: ['Final estimate sent', 'sent'],
    completed: ['Completed', 'done'],
  };
  const view = $('#view');
  const canOpenClients = view.dataset.clients === '1';
  const filter = { q: '', status: '' };

  const statusChip = (s) => {
    const [label, tone] = STATUS[s] || [s, 'planned'];
    return h('span', { class: `chip chip-p-${tone}` }, label);
  };

  // One project's tabs (dashboard, payments, details, attendance) all lead back to the same nearer place:
  // its client if this role can open Clients & Projects, otherwise the project list itself.
  function setProjectAppbarBack(c) {
    LD.setAppbarBack?.(canOpenClients ? c.name : 'Projects', canOpenClients ? `/clients#c${c.id}` : '#');
  }

  // The four sections of one project - a horizontally-scrolling chip row, same pattern as the stage
  // filters elsewhere, so it never depends on a fixed item count fitting a phone's width.
  const PROJECT_TABS = [['', 'Overview'], ['payments', 'Payment'], ['details', 'More details'], ['attendance', 'Attendance']];
  const projectTabs = (id, active) => h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Project section' },
    PROJECT_TABS.map(([slug, label]) => h('a', {
      class: 'filter-chip', href: slug ? `#p${id}/${slug}` : `#p${id}`,
      'aria-current': active === slug ? 'page' : null,
    }, label)));

  const toNumber = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? 0 : Number(v));

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }

  /* ---------- list ---------- */

  async function showList() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading projects…'));
    let data;
    try { data = await api('/api/projects'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;

    const wrap = h('div', {});
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Filter by status' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const results = h('div', {});
    const search = h('input', {
      type: 'search', placeholder: 'Search project, client, work order', 'aria-label': 'Search projects',
      value: filter.q, oninput: (e) => { filter.q = e.target.value; refresh(); },
    });

    function renderChips() {
      clear(chips);
      const options = [['', 'All', data.projects.length],
        ...data.statuses.map((s) => [s, STATUS[s][0], data.projects.filter((p) => p.status === s).length])];
      for (const [value, label, n] of options) {
        chips.append(h('button', {
          class: 'filter-chip', type: 'button', 'aria-pressed': String(filter.status === value),
          onclick: () => { filter.status = value; renderChips(); refresh(); },
        }, label, h('span', { class: 'n' }, n)));
      }
    }

    // Tiled by status, then a chevron - or, when the project has a progress value, a small bar instead.
    function projectRow(p) {
      const side = p.progress != null
        ? h('span', { class: 'p-side' },
            h('span', { class: 'p-progress-pct' }, `${Math.round(p.progress)}%`),
            h('span', { class: 'p-progress-bar' }, h('i', { style: `width:${Math.max(0, Math.min(100, p.progress))}%` })))
        : h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›');
      return h('li', {}, h('a', { class: 'p-row', href: `#p${p.id}` },
        h('span', { class: 'p-tile', 'data-status': p.status, 'aria-hidden': 'true' }, (p.title[0] || '?').toUpperCase()),
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, p.title),
          h('span', { class: 'row-sub' }, [p.client_name, STATUS[p.status][0]].filter(Boolean).join(' · ')),
          h('span', { class: 'p-foot' }, h('span', { class: 'p-code' }, p.code),
            fmtShort(p.net_amount, cur) ? h('span', {}, fmtShort(p.net_amount, cur)) : null,
            p.manager_name ? h('span', { class: 'p-manager' }, `PM: ${p.manager_name}`) : h('span', { class: 'p-manager none' }, 'No manager yet'))),
        side));
    }

    function refresh() {
      const q = filter.q.trim().toLowerCase();
      const items = data.projects.filter((p) => {
        if (filter.status && p.status !== filter.status) return false;
        return !q || [p.title, p.client_name, p.code, p.work_category].some((v) => (v || '').toLowerCase().includes(q));
      });
      count.textContent = plural(items.length, 'project', 'projects');
      clear(results);
      if (!items.length) {
        results.append(h('p', { class: 'empty-state' }, data.projects.length
          ? 'No projects match this search.'
          : 'No projects yet. Tap Add project, or win a lead and tap Create project on it.'));
        return;
      }
      // Grouped by status, in the pipeline's own order, each under a sticky header - same pattern as
      // the Leads list's follow-up groups.
      const groups = data.statuses.map((s) => ({ key: s, label: STATUS[s][0] === 'Completed' ? 'Done' : STATUS[s][0],
        items: items.filter((p) => p.status === s) }));
      groups.filter((g) => g.items.length).forEach((g) => results.append(h('section', { class: 'p-group lead-group' },
        h('h3', { class: 'group-head' }, g.label, h('span', { class: 'group-count' }, g.items.length)),
        h('ul', { class: 'card-group rows' }, g.items.map(projectRow)))));
    }

    wrap.append(
      h('div', { class: 'filters' }, search, chips), count, results);
    clear(view).append(wrap);
    renderChips();
    refresh();
  }

  /* ---------- add a project that did not come from a lead ---------- */

  async function showNew() {
    LD.setAppbarBack?.('Clients', '/clients');
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    let data;
    try { data = await api('/api/projects'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const clientSel = selectField(
      [{ value: '', label: 'A new client\u2026' }, ...data.clients.map((c) => ({ value: c.id, label: c.name }))],
      '', { title: 'Client', placeholder: 'A new client\u2026' });
    const newName = h('input', { type: 'text', maxlength: 160, autocomplete: 'off', placeholder: 'Client name' });
    const newNameField = field('new_client_name', 'New client name', newName);
    const titleInput = h('input', { type: 'text', maxlength: 160, autocomplete: 'off', placeholder: 'Optional (defaults to client and services)' });
    const statusSel = selectField(
      data.statuses.map((s) => ({ value: s, label: STATUS[s][0] })), 'running', { title: 'Status' });

    // Same services checklist as the lead form - which services the project covers.
    const serviceBoxes = data.services.map((name) => {
      const cb = h('input', { type: 'checkbox', value: name });
      return { name, box: h('label', { class: 'check-row' }, cb, h('span', {}, name)) };
    });
    const serviceField = h('div', { class: 'field wide' },
      h('label', {}, 'Services', h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *')),
      h('div', { class: 'check-grid' }, serviceBoxes.map((s) => s.box)),
      h('p', { class: 'err', id: 'err-services', role: 'alert' }));

    const estimateInput = h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', autocomplete: 'off' });
    const woNo = h('input', { type: 'text', maxlength: 60, autocomplete: 'off' });
    const woDate = dateField('', { placeholder: 'Work order date' });
    const advanceInput = h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', autocomplete: 'off' });
    const advanceDate = dateField('', { placeholder: 'Date of payment' });
    const advanceMode = selectField(
      [{ value: '', label: 'Choose how it was paid' }, ...data.payment_modes.map((m) => ({ value: m, label: m }))],
      '', { title: 'Mode of payment', placeholder: 'Choose how it was paid' });
    const advanceComments = h('textarea', { rows: 2 });

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Add project');

    const syncClient = () => { newNameField.hidden = clientSel.value !== ''; };
    clientSel.addEventListener('change', syncClient);
    syncClient();

    const val = (el) => (el.value === '' ? null : el.value);
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        const services = serviceBoxes.filter((s) => s.box.querySelector('input').checked).map((s) => s.name);
        if (!services.length) {
          form.querySelector('#err-services').textContent = 'Choose at least one service';
          return;
        }
        saveBtn.disabled = true;
        try {
          const saved = await api('/api/projects', { method: 'POST', body: {
            client_id: clientSel.value || null, new_client_name: newName.value, title: titleInput.value,
            status: statusSel.value, services,
            estimated_amount: val(estimateInput), work_order_no: woNo.value, work_order_date: val(woDate),
            advance_amount: val(advanceInput), advance_date: val(advanceDate), advance_mode: val(advanceMode),
            advance_comments: advanceComments.value,
          } });
          toast('Project added');
          window.location.hash = `#p${saved.project.id}/details`;       // straight on to the work order details
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('div', { class: 'form-grid' },
        field('client_id', 'Client', clientSel, { wide: true }),
        newNameField,
        field('title', 'Project title', titleInput, { wide: true }),
        serviceField,
        field('status', 'Status', statusSel),
        field('estimated_amount', `Estimated amount (${data.currency})`, estimateInput)),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Work order'),
        h('div', { class: 'form-grid' },
          field('work_order_no', 'Work order number', woNo),
          field('work_order_date', 'Work order date', woDate))),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Advance received'),
        h('p', { class: 'hint' }, 'Leave blank if nothing has been received yet.'),
        h('div', { class: 'form-grid' },
          field('advance_amount', 'Advance amount', advanceInput),
          field('advance_date', 'Date of payment', advanceDate),
          field('advance_mode', 'Mode of payment', advanceMode),
          field('advance_comments', 'Comments', advanceComments, { wide: true }))),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, 'Add project')),
      form));
  }

  /* ---------- one project: dashboard ---------- */

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const parseDay = (iso) => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
  const longDate = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  const shortDate = (d) => `${WEEKDAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  const startOfToday = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };

  /* "2 yrs 3 mos", "5 months", "12 days" - the time from `from` to `to`, in the largest units that read well. */
  function duration(from, to) {
    let months = (to.getFullYear() - from.getFullYear()) * 12 + (to.getMonth() - from.getMonth());
    if (to.getDate() < from.getDate()) months -= 1;
    if (months < 1) {
      const days = Math.max(0, Math.round((to - from) / 86400000));
      return days === 0 ? 'Under a day' : plural(days, 'day', 'days');
    }
    if (months < 12) return plural(months, 'month', 'months');
    const years = Math.floor(months / 12);
    const rest = months % 12;
    return rest ? `${plural(years, 'yr', 'yrs')} ${plural(rest, 'mo', 'mos')}` : plural(years, 'year', 'years');
  }

  /* The first box: how long it has been running - or how long it ran, once closed; or, before it starts,
     when it will. Counts from the start date when there is one, else from when the project was added. */
  function timeTile(P, D) {
    const today = startOfToday();
    const started = parseDay(D.started);
    const from = D.start_date_set ? `Since ${longDate(started)}` : `Since ${longDate(started)}, when it was added`;
    let label;
    let value;
    let note;
    if (P.status === 'completed') {
      const closed = D.completed_at ? new Date(D.completed_at) : today;
      label = 'Ran for';
      value = duration(started, closed);
      note = D.completed_at ? `${longDate(started)} – ${longDate(closed)}` : from;
    } else if (started > today) {
      label = 'Starts in';
      value = duration(today, started);
      note = `On ${longDate(started)}`;
    } else if (P.status === 'planned') {
      label = 'Waiting to start';
      value = duration(started, today);
      note = from;
    } else {
      label = P.status === 'on_hold' ? 'Running for (on hold)' : 'Running for';
      value = duration(started, today);
      note = from;
    }
    return h('div', { class: 'stat' },
      h('span', { class: 'stat-label' }, label),
      h('span', { class: 'stat-value is-text' }, value),
      h('span', { class: 'stat-note' }, note));
  }

  // Who has checked in against this project - app users and manpower/staff alike. Used on the Attendance
  // on this site tab.
  const teamList = (D) => (D.team.length
    ? h('ul', { class: 'att-week-card' }, D.team.map((m) => h('li', { class: 'att-day' },
      h('div', { class: 'att-day-top' },
        h('span', { class: 'att-day-date' }, m.name),
        h('span', { class: 'dash-days' }, h('span', { class: 'att-num' }, m.days), m.days === 1 ? ' day' : ' days')),
      h('span', { class: 'att-day-sub' }, `${m.kind} · last on ${shortDate(parseDay(m.last_day))}`))))
    : h('p', { class: 'hint' }, 'No attendance has been recorded against this project yet.'));

  // Closing a project needs the final on-site measurement on file (it can land above or below what was
  // negotiated) and that figure fully paid - the same slide-up-panel pattern the lead drawer uses
  // elsewhere, rather than a single yes/no confirm box that can't hold a form. Once the amount is
  // recorded it's locked - a real measurement isn't something to second-guess from here - so a repeat
  // visit to this sheet only ever shows it read-only, with just Close project left to do.
  function openCloseSheet(P, cur, onClosed) {
    const overlay = h('div', { class: 'overlay' });
    const finish = closeOnBack(() => { overlay.remove(); drawer.remove(); });
    const closeX = h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close' }, '×');
    closeX.onclick = () => finish();
    overlay.onclick = () => finish();
    const scroll = h('div', { class: 'drawer-scroll' });
    const foot = h('div', { class: 'drawer-foot' });

    // Called once up front and again, in place (no re-opening the sheet - that would mean a second
    // closeOnBack push racing the first's history.back()), once the amount is recorded.
    function renderContent() {
      const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
      let body, footer;
      if (P.final_amount != null) {
      const remaining = P.final_amount - (P.paid_amount || 0);
      const closeBtn = h('button', { class: 'btn danger primary', type: 'button', disabled: remaining > 0 }, 'Close project');
      closeBtn.onclick = async () => {
        closeBtn.disabled = true;
        try {
          const closed = await api(`/api/projects/${P.id}/close`, { method: 'POST' });
          toast('Project closed');
          finish();
          onClosed(closed);
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          closeBtn.disabled = false;
        }
      };
      body = [
        errorBox,
        h('div', { class: 'field' },
          h('label', {}, 'Final amount after measurement'),
          h('p', { class: 'stat-value is-text' }, money(P.final_amount, cur))),
        h('p', { class: 'hint' }, remaining > 0
          ? `${money(remaining, cur)} still to be paid before this project can close.`
          : 'Fully paid - ready to close.'),
      ];
      footer = [closeBtn];
    } else {
      const amountInput = h('input', {
        type: 'number', min: '0', step: 'any', inputmode: 'decimal', id: 'f-final_amount',
      });
      let measured = false;
      const yesBtn = h('button', { type: 'button', class: 'btn small' }, 'Yes');
      const noBtn = h('button', { type: 'button', class: 'btn small' }, 'No');
      const amountField = h('div', { class: 'field' },
        h('label', { for: 'f-final_amount' }, `Final amount after measurement (${cur})`),
        amountInput,
        h('p', { class: 'err', id: 'err-final_amount', role: 'alert' }));
      const statusText = h('p', { class: 'hint' });
      const recordBtn = h('button', { class: 'btn danger primary', type: 'button' }, 'Record final amount');

      function refresh() {
        yesBtn.classList.toggle('primary', measured);
        noBtn.classList.toggle('primary', !measured);
        amountField.hidden = !measured;
        if (!measured) {
          statusText.textContent = 'Complete the final measurement before this project can close.';
          recordBtn.disabled = true;
        } else {
          statusText.textContent = '';
          recordBtn.disabled = amountInput.value === '';
        }
      }
      yesBtn.onclick = () => { measured = true; refresh(); amountInput.focus(); };
      noBtn.onclick = () => { measured = false; refresh(); };
      amountInput.addEventListener('input', refresh);
      recordBtn.onclick = async () => {
        errorBox.hidden = true;
        showFieldErrors(scroll, {});
        recordBtn.disabled = true;
        try {
          const saved = await api(`/api/projects/${P.id}`, { method: 'PATCH', body: { final_amount: amountInput.value } });
          P.final_amount = saved.project.final_amount;
          P.paid_amount = saved.project.paid_amount;
          toast('Final amount recorded');
          renderContent();                      // swap to the read-only view, Close project now on offer
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          showFieldErrors(scroll, err.fields);
          recordBtn.disabled = false;
        }
      };
      body = [
        errorBox,
        h('div', { class: 'field' },
          h('label', {}, 'Was the final measurement done?'),
          h('div', { class: 'yes-no-row' }, yesBtn, noBtn)),
        amountField,
        statusText,
      ];
      footer = [recordBtn];
      refresh();
    }
    clear(scroll).append(...body);
    clear(foot).append(...footer);
    }

    const drawer = h('div', { class: 'drawer' },
      h('div', { class: 'drawer-head' },
        h('div', { class: 'sheet-handle', 'aria-hidden': 'true' }),
        h('div', { class: 'drawer-head-row' },
          h('div', { class: 'drawer-titles' }, h('h2', {}, 'Close project'), h('p', { class: 'drawer-sub' }, `${P.code} · ${P.title}`)),
          closeX)),
      scroll);
    drawer.append(foot);
    document.body.append(overlay, drawer);
    renderContent();
  }

  function renderDashboard(data) {
    const P = data.project;
    const D = data.dashboard;
    setProjectAppbarBack(data.client);
    const c = data.client;
    const cur = data.currency;

    const valueNote = P.final_amount != null ? 'Final amount, after measurement'
      : P.estimated_amount == null ? 'No estimate yet'
        : P.discount_amount ? `${money(P.estimated_amount, cur)} less ${money(P.discount_amount, cur)} discount`
          : 'Estimated amount';

    const info = (label, value, sub) => h('div', { class: 'dash-info-row' },
      h('span', { class: 'stat-label' }, label),
      h('span', { class: 'dash-info-value' }, value),
      sub ? h('span', { class: 'dash-info-sub' }, sub) : null);

    let closeArea = null;
    if (P.status === 'completed') {
      closeArea = h('p', { class: 'hint' }, D.completed_at ? `Closed on ${longDate(new Date(D.completed_at))}.` : 'This project is closed.');
    } else if (D.can_close) {
      const closeBtn = h('button', { class: 'btn danger dash-close', type: 'button' }, 'Close project');
      closeBtn.onclick = () => openCloseSheet(P, cur, (saved) => renderDashboard(saved));
      closeArea = closeBtn;
    }

    // TEMPORARY - for backfilling old work; goes away with the delete route in projects.py.
    let deleteBtn = null;
    if (D.can_delete) {
      deleteBtn = h('button', { class: 'btn danger dash-close', type: 'button' }, 'Delete project');
      deleteBtn.onclick = async () => {
        const sure = await confirm(`Delete ${P.code}? Its details and payment timeline will be removed. This cannot be undone.`, { ok: 'Delete', danger: true, title: 'Delete project' });
        if (!sure) return;
        deleteBtn.disabled = true;
        try {
          await api(`/api/projects/${P.id}`, { method: 'DELETE' });
          toast('Project deleted');
          location.hash = '';
        } catch (err) {
          toast(err.message, true);
          deleteBtn.disabled = false;
        }
      };
    }

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, P.code), statusChip(P.status)),
      h('p', { class: 'hint' }, P.title),
      projectTabs(P.id, ''),
      h('div', { class: 'client-stats' },
        timeTile(P, D),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Value'),
          h('span', { class: 'stat-value' }, P.net_amount != null ? money(P.net_amount, cur) : '—'),
          h('span', { class: 'stat-note' }, valueNote))),
      h('div', { class: 'dash-info' },
        info('Brought by', D.brought_by ? D.brought_by.name : 'Not recorded', D.brought_by ? D.brought_by.how : null),
        info('Project manager', P.manager_name || 'Not assigned'),
        info('Client',
          canOpenClients ? h('a', { href: `/clients#c${c.id}` }, c.name) : c.name,
          [c.contact_name, c.phone].filter(Boolean).join(' · ') || null)),
      closeArea,
      deleteBtn));
    window.scrollTo(0, 0);
  }

  /* ---------- one project: the other three tabs ---------- */

  async function showDetail(id, section) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading project…'));
    let data;
    try { data = await api(`/api/projects/${id}`); }
    catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to projects')));
      return;
    }
    if (section === 'payments') renderPayments(data);
    else if (section === 'details') renderDetails(data);
    else if (section === 'attendance') renderAttendance(data);
    else renderDashboard(data);
  }

  // The header, identical on all three of the tabs below (dashboard has its own, near-identical version -
  // see renderDashboard); the back link itself goes in the appbar (setProjectAppbarBack), not in here.
  function projectHead(P, c) {
    setProjectAppbarBack(c);
    return [
      h('div', { class: 'p-head' }, h('h2', {}, P.code), statusChip(P.status)),
      h('p', { class: 'hint' }, P.title),
    ];
  }

  function renderPayments(data) {
    const P = data.project;
    const c = data.client;
    const cur = data.currency;

    // The amount is settled by the time a lead is won (see the figure below) - not something to hand-edit
    // here anymore. Once the closing measurement sets a final amount, that's this figure instead - it can
    // land above or below what was negotiated, see Project.net_amount.
    const netValue = P.net_amount;

    const ovNegotiated = h('dd', {}, '—');
    const ovAdvance = h('dd', {}, '—');
    const ovRemaining = h('dd', {}, '—');
    // Projects that didn't come from a lead have no negotiated amount to start from - offer to take the
    // total of their payments as it, rather than leaving Remaining stuck on a dash.
    const fillBtn = h('button', { class: 'link-btn fill-amount-btn', type: 'button', hidden: netValue !== null }, 'Fill amount');
    fillBtn.onclick = () => {
      const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
      const input = h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', id: 'f-negotiated_amount' });
      const errEl = h('p', { class: 'err', role: 'alert' });
      const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
      const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Save');
      const finish = closeOnBack(() => overlay.remove());
      overlay.onclick = (e) => { if (e.target === overlay) finish(); };
      cancelBtn.onclick = () => finish();
      saveBtn.onclick = async () => {
        if (input.value === '') { errEl.textContent = 'Enter the negotiated amount'; return; }
        saveBtn.disabled = true;
        try {
          await api(`/api/projects/${P.id}`, { method: 'PATCH', body: { estimated_amount: input.value } });
          finish();
          toast('Negotiated amount saved');
          renderPayments(await api(`/api/projects/${P.id}`));
        } catch (err) {
          errEl.textContent = err.message;
          saveBtn.disabled = false;
        }
      };
      overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
        h('h2', {}, 'Negotiated amount'),
        field('negotiated_amount', `Amount (${cur})`, input),
        errEl,
        h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
      document.body.append(overlay);
      input.focus();
    };
    const payOverview = h('div', { class: 'pay-overview' },
      h('p', { class: 'pay-overview-title' }, `${P.code} · ${P.title}`),
      h('dl', { class: 'pay-overview-grid' },
        h('dt', {}, P.final_amount != null ? 'Final amount' : 'Negotiated amount', fillBtn), ovNegotiated,
        h('dt', {}, 'Advance payment'), ovAdvance,
        h('dt', {}, 'Remaining'), ovRemaining));

    // A quick read of how each step was actually paid - mode, date, any note - as it stands saved on the
    // server, separate from the edit fields below (which only reflect the server once Save is pressed).
    const paidSteps = P.payments.filter((p) => p.mode || p.paid_date || p.comments);
    const payReceipts = paidSteps.length ? h('div', { class: 'pay-receipts' },
      paidSteps.map((p) => h('div', { class: 'pay-receipt' },
        h('p', { class: 'pay-receipt-head' },
          h('span', {}, p.label), h('span', {}, money(p.amount, cur))),
        h('p', { class: 'pay-receipt-meta' },
          [p.mode, p.paid_date ? fmtDate(p.paid_date) : null].filter(Boolean).join(' · ')),
        p.comments ? h('p', { class: 'pay-receipt-comments' }, p.comments) : null))) : null;

    const paySummary = h('p', { class: 'pay-summary', 'aria-live': 'polite' });
    const stepsLabel = h('p', { class: 'steps-label' });
    const stepsList = h('div', { class: 'card-group step-list' });

    // Step names are positional, not something the admin types - the first is always the advance, then
    // "2nd payment", "3rd payment" and so on, so they shift on their own as steps are added or removed.
    function labelFor(index) {
      if (index === 0) return 'Advance';
      const n = index + 1;
      const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th';
      return `${n}${suffix} payment`;
    }

    // In-memory working copy - each row's own sheet edits this, then PATCHes the whole array straight
    // away (there's no separate "save the timeline" step anymore, see openStepSheet).
    let steps = (P.payments.length ? P.payments : []).map((p) => ({ ...p }));

    // What actually goes to the server: the position tag is always there as a fallback, the milestone
    // (if any) is the admin's own description of what the step is tied to.
    function toPayload(arr) {
      return arr.map((s, i) => ({
        label: (s.label || '').trim() || labelFor(i),
        amount: s.amount === '' || s.amount == null ? 0 : s.amount,
        mode: s.mode || '',
        paid_date: s.paid_date || null,
        comments: (s.comments || '').trim(),
      }));
    }

    function recalc() {
      const rows = toPayload(steps);
      const scheduled = rows.reduce((sum, p) => sum + toNumber(p.amount), 0);
      // What's actually been paid, not just scheduled - a future step can sit there unpaid.
      const paidSoFar = rows.reduce((sum, p) => sum + (p.paid_date ? toNumber(p.amount) : 0), 0);
      // The advance is always the first step, by position - not by matching what its milestone says.
      const advanceAmt = rows.length ? toNumber(rows[0].amount) : 0;
      ovNegotiated.textContent = netValue === null ? '—' : money(netValue, cur);
      ovAdvance.textContent = rows.length ? money(advanceAmt, cur) : '—';
      ovRemaining.textContent = netValue === null ? '—' : money(netValue - paidSoFar, cur);

      paySummary.className = 'pay-summary';
      if (!rows.length) paySummary.textContent = '';
      else if (netValue === null) paySummary.textContent = `Scheduled: ${money(scheduled, cur)}`;
      else if (scheduled > netValue) { paySummary.textContent = `Scheduled ${money(scheduled, cur)} is more than the net amount ${money(netValue, cur)}`; paySummary.classList.add('bad'); }
      else if (scheduled === netValue) { paySummary.textContent = `All ${money(netValue, cur)} is scheduled`; paySummary.classList.add('good'); }
      else paySummary.textContent = `Scheduled ${money(scheduled, cur)} of ${money(netValue, cur)}. ${money(netValue - scheduled, cur)} is not scheduled yet.`;
    }

    // PATCHes the whole array (the schedule has always been saved as one list, not per-step rows on the
    // server) and reconciles the in-memory copy with whatever the server actually stored.
    async function persistSteps(next) {
      const saved = await api(`/api/projects/${P.id}`, { method: 'PATCH', body: { payments: toPayload(next) } });
      steps = saved.project.payments.map((p) => ({ ...p }));
      renderStepsList();
      recalc();
    }

    function renderStepsList() {
      stepsLabel.textContent = `Payments · ${steps.length}`;
      clear(stepsList);
      steps.forEach((s, i) => {
        const paid = !!s.paid_date;
        const circle = paid
          ? h('span', { class: 'step-circle paid', 'aria-hidden': 'true' }, '✓')
          : h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(i + 1));
        const title = (s.label || '').trim() || labelFor(i);
        const subParts = paid
          ? [`Paid ${fmtDate(s.paid_date)}`, s.mode || null].filter(Boolean)
          : ['Not paid yet'];
        let sub = subParts.join(' · ');
        if (s.comments) sub += ' · note';
        stepsList.append(h('button', {
          type: 'button', class: 'step-row', 'aria-label': `${title}, ${money(toNumber(s.amount), cur)}, ${paid ? 'paid' : 'not paid'}`,
          onclick: () => openStepSheet(i),
        },
          circle,
          h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, title), h('span', { class: 'step-sub' }, sub)),
          h('span', { class: 'step-amount' }, money(toNumber(s.amount), cur))));
      });
      stepsList.append(h('button', {
        type: 'button', class: 'step-row step-add',
        onclick: () => openStepSheet(steps.length),
      },
        h('span', { class: 'step-circle dashed', 'aria-hidden': 'true' }, '+'),
        h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, '+ Add payment'))));
    }

    // One step's own sheet - add (index === steps.length) or edit. Saves and deletes both PATCH the
    // whole array immediately; there's nothing left to do from the list screen itself.
    function openStepSheet(index) {
      const isNew = index === steps.length;
      const current = isNew ? { label: '', amount: '', mode: '', paid_date: null, comments: '' } : steps[index];
      const trigger = document.activeElement;

      const overlay = h('div', { class: 'overlay' });
      const scroll = h('div', { class: 'drawer-scroll' });
      const foot = h('div', { class: 'drawer-foot' });
      const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });

      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); finish(); return; }
        if (e.key !== 'Tab') return;
        const focusables = [...drawer.querySelectorAll('button, input, select, textarea')].filter((el) => !el.disabled && el.offsetParent !== null);
        if (!focusables.length) return;
        const first = focusables[0], last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
      const finish = closeOnBack(() => {
        window.removeEventListener('keydown', onKey, true);
        overlay.remove();
        drawer.remove();
        document.body.classList.remove('locked');
        if (trigger && trigger.isConnected) trigger.focus();
      });
      overlay.onclick = () => finish();
      const closeX = h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close' }, '×');
      closeX.onclick = () => finish();

      const milestoneInput = h('input', { type: 'text', maxlength: 120, value: current.label || '' });
      const amountInput = h('input', {
        type: 'number', id: 'f-amount', min: '0', step: 'any', inputmode: 'decimal', value: current.amount ?? '',
        'aria-describedby': 'err-amount',
      });
      const chips = h('div', { class: 'step-chips' });
      function renderChips() {
        clear(chips);
        if (netValue === null) return;
        const quarter = Math.round(netValue * 0.25 * 100) / 100;
        chips.append(h('button', {
          type: 'button', class: 'btn small',
          onclick: () => { amountInput.value = quarter; amountInput.dispatchEvent(new Event('input', { bubbles: true })); },
        }, '25% of net'));
        const otherTotal = steps.reduce((sum, s, i) => (i === index ? sum : sum + toNumber(s.amount)), 0);
        const rest = netValue - otherTotal;
        if (rest > 0) {
          chips.append(h('button', {
            type: 'button', class: 'btn small',
            onclick: () => { amountInput.value = rest; amountInput.dispatchEvent(new Event('input', { bubbles: true })); },
          }, `Rest · ${money(rest, cur)}`));
        }
      }
      renderChips();

      const modeSel = selectField(
        [{ value: '', label: 'Mode of payment' }, ...data.payment_modes.map((m) => ({ value: m, label: m }))],
        current.mode || '', { title: 'Mode of payment', placeholder: 'Mode of payment' });
      const paidDateInput = dateField(current.paid_date || '', { placeholder: 'Date of payment' });
      const modeField = field('mode', 'Mode of payment', modeSel);
      const dateFieldEl = field('paid_date', 'Date of payment', paidDateInput);
      const paidToggleInput = h('input', { type: 'checkbox', checked: !!current.paid_date });
      const paidToggle = h('label', { class: 'switch' },
        paidToggleInput, h('span', { class: 'switch-track', 'aria-hidden': 'true' }), h('span', { class: 'switch-thumb', 'aria-hidden': 'true' }));
      function todayIso() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      }
      function refreshPaidFields() {
        const on = paidToggleInput.checked;
        modeField.hidden = !on;
        dateFieldEl.hidden = !on;
        if (on && !paidDateInput.value) paidDateInput.value = todayIso();
        if (!on) { modeSel.value = ''; paidDateInput.value = ''; }
      }
      paidToggleInput.addEventListener('change', refreshPaidFields);
      refreshPaidFields();

      const noteTextarea = h('textarea', { rows: 2 });
      noteTextarea.value = current.comments || '';
      const noteField = field('comments', 'Note', noteTextarea);
      const noteToggleBtn = h('button', { type: 'button', class: 'link-btn' }, '+ Add a note');
      const hasNote = !!(current.comments || '').trim();
      noteField.hidden = !hasNote;
      noteToggleBtn.hidden = hasNote;
      noteToggleBtn.onclick = () => { noteField.hidden = false; noteToggleBtn.hidden = true; noteTextarea.focus(); };

      const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Save payment');
      saveBtn.onclick = async () => {
        errorBox.hidden = true;
        showFieldErrors(scroll, {});
        saveBtn.disabled = true;
        const draft = {
          label: milestoneInput.value, amount: amountInput.value, mode: modeSel.value,
          paid_date: paidDateInput.value || null, comments: noteTextarea.value,
        };
        const next = steps.slice();
        if (isNew) next.push(draft); else next[index] = draft;
        try {
          await persistSteps(next);
          toast('Payment saved');
          finish();
        } catch (err) {
          errorBox.textContent = (err.fields && err.fields.payments) || err.message;
          errorBox.hidden = false;
          saveBtn.disabled = false;
        }
      };

      let deleteBtn = null;
      if (!isNew) {
        deleteBtn = h('button', { type: 'button', class: 'link-btn step-sheet-delete' }, 'Delete');
        deleteBtn.onclick = async () => {
          const sure = await confirm(`Remove ${(current.label || '').trim() || labelFor(index)}?`, { ok: 'Delete', danger: true, title: 'Delete payment' });
          if (!sure) return;
          deleteBtn.disabled = true;
          const next = steps.slice();
          next.splice(index, 1);
          try {
            await persistSteps(next);
            toast('Payment removed');
            finish();
          } catch (err) {
            errorBox.textContent = (err.fields && err.fields.payments) || err.message;
            errorBox.hidden = false;
            deleteBtn.disabled = false;
          }
        };
      }

      const total = isNew ? steps.length + 1 : steps.length;
      const title = (current.label || '').trim() || labelFor(index);
      scroll.append(
        errorBox,
        field('label', 'Milestone', milestoneInput),
        h('div', { class: 'field' },
          h('label', { for: 'f-amount' }, 'Amount'),
          h('div', { class: 'amount-input-wrap' }, h('span', { class: 'amount-prefix', 'aria-hidden': 'true' }, cur), amountInput),
          chips,
          h('p', { class: 'err', id: 'err-amount', role: 'alert' })),
        h('div', { class: 'toggle-row' }, h('span', {}, 'Payment received'), paidToggle),
        modeField, dateFieldEl,
        noteToggleBtn, noteField);
      foot.append(saveBtn);

      const drawer = h('div', { class: 'drawer' },
        h('div', { class: 'drawer-head' },
          h('div', { class: 'sheet-handle', 'aria-hidden': 'true' }),
          h('div', { class: 'drawer-head-row' },
            h('div', { class: 'drawer-titles' },
              h('p', { class: 'step-sheet-eyebrow' }, `Payment ${index + 1} of ${total}`),
              h('h2', {}, title)),
            deleteBtn, closeX)),
        scroll);
      drawer.append(foot);
      document.body.classList.add('locked');
      window.addEventListener('keydown', onKey, true);
      document.body.append(overlay, drawer);
      (isNew ? amountInput : milestoneInput).focus();
    }

    renderStepsList();

    clear(view).append(h('div', { class: 'project-detail' },
      ...projectHead(P, c),
      projectTabs(P.id, 'payments'),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Payment timeline'),
        payOverview,
        payReceipts,
        h('p', { class: 'hint' }, 'Split the net amount into payments, each tied to its own site milestone.'),
        stepsLabel,
        stepsList,
        paySummary)));
    recalc();
    window.scrollTo(0, 0);
  }

  function renderDetails(data) {
    const P = data.project;
    const c = data.client;
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });

    const title = text('text', P.title, { maxlength: 160, autocomplete: 'off' });
    const statusSel = selectField(
      data.statuses.map((s) => ({ value: s, label: STATUS[s][0] })), P.status, { title: 'Status' });
    const woNo = text('text', P.work_order_no, { maxlength: 60, autocomplete: 'off' });
    const woDate = dateField(P.work_order_date);
    const startDate = dateField(P.start_date);
    const days = text('number', P.completion_days, { min: '0', step: '1', inputmode: 'numeric' });
    const managerSel = data.can_assign_manager
      ? selectField(
        [{ value: '', label: 'Not assigned' }, ...data.managers.map((m) => ({ value: m.code, label: m.name }))],
        P.manager_code || '', { title: 'Manager', placeholder: 'Not assigned' })
      : null;

    const finish = h('p', { class: 'hint', 'aria-live': 'polite' });
    function recalcFinish() {
      if (startDate.value && days.value !== '') {
        const [y, m, d] = startDate.value.split('-').map(Number);
        const end = new Date(Date.UTC(y, m - 1, d + toNumber(days.value)));
        finish.textContent = `Expected completion: ${fmtDate(end.toISOString().slice(0, 10))}`;
      } else finish.textContent = 'Add a start date and completion period to see the expected completion date.';
    }

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save details');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = {
          title: title.value, status: statusSel.value, work_order_no: woNo.value, work_order_date: woDate.value,
          start_date: startDate.value, completion_days: days.value,
        };
        if (managerSel) body.manager_code = managerSel.value;
        try {
          await api(`/api/projects/${P.id}`, { method: 'PATCH', body });
          toast('Project details saved');
          window.location.hash = `#p${P.id}`;
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          const first = showFieldErrors(form, err.fields);
          (first || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('section', { class: 'p-section' },
        h('h3', {}, 'Project'),
        h('div', { class: 'form-grid' },
          field('title', 'Title', title, { wide: true }),
          field('status', 'Status', statusSel),
          managerSel ? field('manager_code', 'Project manager', managerSel) : null)),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Work order'),
        h('div', { class: 'form-grid' },
          field('work_order_no', 'Work order number', woNo),
          field('work_order_date', 'Work order date', woDate),
          field('start_date', 'Approx. start date', startDate),
          field('completion_days', 'Completion period (days)', days)),
        finish),
      h('div', { class: 'form-actions' }, saveBtn));

    form.addEventListener('input', recalcFinish);

    const site = [P.site_address, P.site_city, P.site_district, P.site_state].filter(Boolean).join(', ');
    clear(view).append(h('div', { class: 'project-detail' },
      ...projectHead(P, c),
      projectTabs(P.id, 'details'),
      h('section', { class: 'p-client' },
        h('div', {},
          h('span', { class: 'p-label' }, 'Client'),
          canOpenClients ? h('a', { class: 'p-client-name', href: `/clients#c${c.id}` }, c.name) : h('span', { class: 'p-client-name' }, c.name)),
        c.phone ? h('a', { class: 'btn small', href: `tel:${c.phone.replace(/[^\d+]/g, '')}` }, 'Call') : null,
        site ? h('p', { class: 'hint' }, `Site: ${site}${P.site_pincode ? ` - ${P.site_pincode}` : ''}`) : null),
      form));
    recalcFinish();
    window.scrollTo(0, 0);
  }

  function renderAttendance(data) {
    const P = data.project;
    const D = data.dashboard;
    const c = data.client;
    clear(view).append(h('div', { class: 'project-detail' },
      ...projectHead(P, c),
      projectTabs(P.id, 'attendance'),
      h('section', { class: 'p-section' },
        h('div', { class: 'p-section-head' },
          h('h3', {}, 'Attendance on this site'),
          D.team.length ? h('span', { class: 'p-code' }, plural(D.team.length, 'person', 'people')) : null),
        teamList(D))));
    window.scrollTo(0, 0);
  }

  function route() {
    const m = /^#p(\d+)(\/(payments|details|attendance))?$/.exec(window.location.hash);
    if (m) return showDetail(Number(m[1]), m[3] || '');
    return window.location.hash === '#new' ? showNew() : showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
