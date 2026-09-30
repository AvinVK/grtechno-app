/* Projects: a list, and one screen per project - a dashboard (how long it has been running, who brought it,
   who has worked on it, and Close project for the admin), with the work order, amounts, terms and payment
   schedule one tap further, behind Edit details. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, money, fmtShort, field, showFieldErrors, selectField, dateField, confirm } = window.LD;

  const STATUS = {
    planned: ['Planned', 'planned'],
    running: ['Running', 'running'],
    on_hold: ['On hold', 'hold'],
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
    const titleInput = h('input', { type: 'text', maxlength: 160, autocomplete: 'off', placeholder: 'Optional (defaults to client and work)' });
    const category = selectField(
      [{ value: '', label: 'Not set' }, ...data.services.map((s) => ({ value: s, label: s }))],
      '', { title: 'Work category', placeholder: 'Not set' });
    const statusSel = selectField(
      data.statuses.map((s) => ({ value: s, label: STATUS[s][0] })), 'running', { title: 'Status' });
    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Add project');

    const syncClient = () => { newNameField.hidden = clientSel.value !== ''; };
    clientSel.addEventListener('change', syncClient);
    syncClient();

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        try {
          const saved = await api('/api/projects', { method: 'POST', body: {
            client_id: clientSel.value || null, new_client_name: newName.value, title: titleInput.value,
            work_category: category.value, status: statusSel.value,
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
        field('work_category', 'Work category', category),
        field('status', 'Status', statusSel)),
      h('p', { class: 'hint' }, 'You can add the work order details on the next screen, and the payment timeline from its own tab.'),
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

  function renderDashboard(data) {
    const P = data.project;
    const D = data.dashboard;
    setProjectAppbarBack(data.client);
    const c = data.client;
    const cur = data.currency;

    const valueNote = P.estimated_amount == null ? 'No estimate yet'
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
      closeBtn.onclick = async () => {
        const sure = await confirm(`Close ${P.code}? It will be marked completed.`, { ok: 'Close project', danger: true, title: 'Close project' });
        if (!sure) return;
        closeBtn.disabled = true;
        try {
          const saved = await api(`/api/projects/${P.id}/close`, { method: 'POST' });
          toast('Project closed');
          renderDashboard(saved);
        } catch (err) {
          toast(err.message, true);
          closeBtn.disabled = false;
        }
      };
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

    // The amount is settled by the time a lead is won (see the negotiated figure below) - not something
    // to hand-edit here anymore.
    const netValue = P.estimated_amount == null ? null : P.estimated_amount - (P.discount_amount || 0);

    const ovNegotiated = h('dd', {}, '—');
    const ovAdvance = h('dd', {}, '—');
    const ovRemaining = h('dd', {}, '—');
    const payOverview = h('div', { class: 'pay-overview' },
      h('p', { class: 'pay-overview-title' }, `${P.code} · ${P.title}`),
      h('dl', { class: 'pay-overview-grid' },
        h('dt', {}, 'Negotiated amount'), ovNegotiated,
        h('dt', {}, 'Advance payment'), ovAdvance,
        h('dt', {}, 'Remaining'), ovRemaining));
    const payRows = h('div', { class: 'pay-rows' });
    const paySummary = h('p', { class: 'pay-summary', 'aria-live': 'polite' });
    const payErr = h('p', { class: 'err', id: 'err-payments', role: 'alert' });

    // Step names are positional, not something the admin types - the first is always the advance, then
    // "2nd payment", "3rd payment" and so on, renumbered live as rows are added or removed.
    function labelFor(index) {
      if (index === 0) return 'Advance';
      const n = index + 1;
      const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th';
      return `${n}${suffix} payment`;
    }
    function renumberPayRows() {
      [...payRows.children].forEach((row, i) => { row._labelEl.textContent = labelFor(i); });
    }

    function addPayRow(p = { amount: '', label: '' }) {
      const labelEl = h('p', { class: 'pay-label-text' }, '');
      const milestoneInput = h('input', {
        type: 'text', class: 'pay-milestone', maxlength: 120,
        placeholder: 'Milestone, for example: Material delivery, Site handover', 'aria-label': 'Milestone', value: p.label ?? '',
      });
      const row = h('div', { class: 'pay-row' },
        labelEl,
        milestoneInput,
        h('input', { type: 'number', class: 'pay-amount', min: '0', step: 'any', inputmode: 'decimal', placeholder: `Amount (${cur})`, 'aria-label': 'Amount', value: p.amount ?? '' }),
        h('button', {
          class: 'icon-x', type: 'button', 'aria-label': 'Remove this payment step',
          onclick: () => { row.remove(); payErr.textContent = ''; renumberPayRows(); recalc(); },
        }, '×'));
      row._labelEl = labelEl;
      payRows.append(row);
    }
    (P.payments.length ? P.payments : []).forEach(addPayRow);
    renumberPayRows();

    // The position tag (Advance, 2nd payment, ...) is always shown; the milestone is the admin's own
    // description of what that step is tied to, and falls back to the position tag when left blank.
    const payments = () => [...payRows.querySelectorAll('.pay-row')].map((r, i) => ({
      label: r.querySelector('.pay-milestone').value.trim() || labelFor(i),
      amount: r.querySelector('.pay-amount').value === '' ? 0 : r.querySelector('.pay-amount').value,
    }));

    function recalc() {
      const rows = payments();
      const scheduled = rows.reduce((sum, p) => sum + toNumber(p.amount), 0);
      // The advance is always the first step, by position - not by matching what its milestone says.
      const advanceAmt = rows.length ? toNumber(rows[0].amount) : 0;
      ovNegotiated.textContent = P.estimated_amount == null ? '—' : money(P.estimated_amount, cur);
      ovAdvance.textContent = rows.length ? money(advanceAmt, cur) : '—';
      ovRemaining.textContent = netValue === null ? '—' : money(netValue - scheduled, cur);

      paySummary.className = 'pay-summary';
      if (!payRows.children.length) paySummary.textContent = '';
      else if (netValue === null) paySummary.textContent = `Scheduled: ${money(scheduled, cur)}`;
      else if (scheduled > netValue) { paySummary.textContent = `Scheduled ${money(scheduled, cur)} is more than the net amount ${money(netValue, cur)}`; paySummary.classList.add('bad'); }
      else if (scheduled === netValue) { paySummary.textContent = `All ${money(netValue, cur)} is scheduled`; paySummary.classList.add('good'); }
      else paySummary.textContent = `Scheduled ${money(scheduled, cur)} of ${money(netValue, cur)}. ${money(netValue - scheduled, cur)} is not scheduled yet.`;
    }

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save payment timeline');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        try {
          await api(`/api/projects/${P.id}`, { method: 'PATCH', body: { payments: payments() } });
          toast('Payment timeline saved');
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
        h('h3', {}, 'Payment timeline'),
        payOverview,
        h('p', { class: 'hint' }, 'Split the net amount into steps, each tied to its own site milestone.'),
        payRows,
        payErr,
        h('button', { class: 'btn small', type: 'button', onclick: () => { addPayRow(); renumberPayRows(); recalc(); payRows.lastChild.querySelector('input').focus(); } }, 'Add payment step'),
        paySummary),
      h('div', { class: 'form-actions' }, saveBtn));

    form.addEventListener('input', (e) => {
      // A payment message from the last save no longer applies once the amounts change.
      if (payRows.contains(e.target)) payErr.textContent = '';
      recalc();
    });

    clear(view).append(h('div', { class: 'project-detail' },
      ...projectHead(P, c),
      projectTabs(P.id, 'payments'),
      form));
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
