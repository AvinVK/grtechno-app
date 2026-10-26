/* The client portal (kohal, 2026-10-22: "client should only be able to see the projects they belong to...
   there should be a new subtab in projects called progress... client should be able to see only this
   subtab of his projects") - a customer's own cut-down view: a list of their own projects, each opening
   straight to its Progress tab alone, nothing else. See app/client_portal.py. Progress is the fixed
   installation checklist, one stage at a time (kohal: "stages of project, work pics at each phase...
   follow the same template as lead") - the same finished/current/upcoming wizard shape as the admin's own
   Progress tab (app/static/js/projects.js), but every row here is read-only: no days input, no pause/
   resume/mark-done buttons, no photo upload/remove. */
(() => {
  'use strict';

  const { $, h, clear, api, money } = window.LD;
  const view = $('#view');
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const parseDay = (iso) => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
  const longDate = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  const shortDate = (d) => `${WEEKDAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;

  // Same status labels/tones as the admin's own project list (app/static/js/projects.js's STATUS) - a
  // client sees the identical word for the identical state, not a different vocabulary of its own.
  const STATUS = {
    planned: ['Planned', 'planned'],
    running: ['Running', 'running'],
    on_hold: ['On hold', 'hold'],
    final_estimate_sent: ['Final estimate sent', 'sent'],
    completed: ['Completed', 'done'],
  };
  const statusChip = (s) => {
    const [label, tone] = STATUS[s] || [s, 'planned'];
    return h('span', { class: `chip chip-p-${tone}` }, label);
  };

  function projectRow(p) {
    return h('li', {}, h('a', { class: 'p-row', href: `#p${p.id}` },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, p.title),
        h('span', { class: 'row-sub' }, [p.code, p.site_name].filter(Boolean).join(' · '))),
      statusChip(p.status),
      h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›')));
  }

  async function showList() {
    // The list is a client's top level - the "back" arrow would only lead to the Me hub, which a client doesn't have.
    LD.resetAppbarBack?.();
    $('#appbar-back')?.style.setProperty('display', 'none');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/my-projects'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(
      data.projects.length
        ? h('ul', { class: 'card-group' }, data.projects.map(projectRow))
        : h('p', { class: 'empty-state' }, 'No projects yet - once one starts, it shows up here.'));
  }

  function finishedStageRow(stage) {
    return h('div', { class: 'step-row' },
      h('span', { class: 'step-circle paid', 'aria-hidden': 'true' }, '✓'),
      h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, stage.label)),
      h('span', { class: 'step-amount' }, shortDate(new Date(stage.completed_at))));
  }

  function upcomingStageRow(stage, idx) {
    return h('div', { class: 'upcoming-row' },
      h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(idx + 1)),
      h('span', { class: 'step-main' },
        h('span', { class: 'step-title' }, stage.label),
        stage.note ? h('span', { class: 'step-sub' }, stage.note) : null));
  }

  function currentStageCard(stage, idx, reasons, currency) {
    const photoGrid = stage.photos.length
      ? h('div', { class: 'photo-grid' }, stage.photos.map((p) => h('div', { class: 'photo-thumb' },
          h('a', { href: p.url, target: '_blank', rel: 'noopener noreferrer' }, h('img', { src: p.url, alt: 'Progress photo' })))))
      : null;
    const pauseLabel = stage.pause_reason ? (reasons.find(([k]) => k === stage.pause_reason) || [, stage.pause_reason])[1] : '';
    // A scheduled payment the admin has attached to this stage (kohal, 2026-10-22: "give an option of
    // adding 'add sheduled payment' checkbox after every step... until then it should show please pay for
    // the project to move to next step") - read-only here, same message the admin sees either way.
    const paymentDetail = stage.payment_required ? h('div', { class: 'stage-payment-detail' },
      stage.payment_amount != null || stage.payment_due_date
        ? h('p', { class: 'hint' }, [
            stage.payment_amount != null ? money(stage.payment_amount, currency) : null,
            stage.payment_due_date ? `due ${longDate(parseDay(stage.payment_due_date))}` : null,
          ].filter(Boolean).join(' · '))
        : null,
      stage.payment_received
        ? h('p', { class: 'stage-payment-received' }, `Payment received ${longDate(new Date(stage.payment_received_at))}`)
        : h('p', { class: 'stage-paused-note' }, 'Please pay for the project to move to the next step.')) : null;
    return h('div', { class: 'current-card' },
      h('div', { class: 'current-card-head' },
        h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(idx + 1)),
        h('h3', {}, stage.label)),
      stage.note ? h('p', { class: 'hint' }, stage.note) : null,
      stage.paused ? h('p', { class: 'stage-paused-note' },
        `Paused · ${pauseLabel}`, stage.pause_note ? ` — ${stage.pause_note}` : '') : null,
      stage.days != null ? h('p', { class: 'hint' }, `Planned: ${stage.days} day${stage.days === 1 ? '' : 's'}`) : null,
      stage.remarks ? h('p', { class: 'hint' }, stage.remarks) : null,
      paymentDetail,
      photoGrid);
  }

  // kohal, 2026-10-23: "client should be able to see everything in project except material, expenses and
  // attendance. only view access" - the same Overview / Payment / More details / Progress tabs as the
  // admin's project page (app/static/js/projects.js), every one of them read-only here.
  const TABS = [['', 'Overview'], ['payments', 'Payment'], ['details', 'More details'], ['progress', 'Progress']];
  const tabBar = (id, active) => h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Project section' },
    TABS.map(([slug, label]) => h('a', {
      class: 'filter-chip', href: slug ? `#p${id}/${slug}` : `#p${id}`, 'aria-current': active === slug ? 'page' : null,
    }, label)));

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const startOfToday = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };
  // "2 yrs 3 mos", "5 months", "12 days" - same wording as the admin's Overview.
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

  function timeTile(p, d) {
    const today = startOfToday();
    const started = parseDay(d.started);
    const from = d.start_date_set ? `Since ${longDate(started)}` : `Since ${longDate(started)}, when it was added`;
    let label; let value; let note;
    if (p.status === 'completed') {
      const closed = d.completed_at ? new Date(d.completed_at) : today;
      label = 'Ran for'; value = duration(started, closed);
      note = d.completed_at ? `${longDate(started)} – ${longDate(closed)}` : from;
    } else if (started > today) {
      label = 'Starts in'; value = duration(today, started); note = `On ${longDate(started)}`;
    } else if (p.status === 'planned') {
      label = 'Waiting to start'; value = duration(started, today); note = from;
    } else {
      label = p.status === 'on_hold' ? 'Running for (on hold)' : 'Running for';
      value = duration(started, today); note = from;
    }
    return h('div', { class: 'stat' },
      h('span', { class: 'stat-label' }, label),
      h('span', { class: 'stat-value is-text' }, value),
      h('span', { class: 'stat-note' }, note));
  }

  const infoRow = (label, value, sub) => (value ? h('div', { class: 'dash-info-row' },
    h('span', { class: 'stat-label' }, label),
    h('span', { class: 'dash-info-value' }, value),
    sub ? h('span', { class: 'dash-info-sub' }, sub) : null) : null);

  function renderOverview(data) {
    const p = data.project;
    const c = data.client;
    const cur = data.currency;
    const valueNote = p.final_amount != null ? 'Final amount, after measurement'
      : p.estimated_amount == null ? 'No estimate yet'
        : p.discount_amount ? `${money(p.estimated_amount, cur)} less ${money(p.discount_amount, cur)} discount`
          : 'Estimated amount';
    return [
      h('div', { class: 'client-stats' },
        timeTile(p, data.dashboard),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Value'),
          h('span', { class: 'stat-value' }, p.net_amount != null ? money(p.net_amount, cur) : '—'),
          h('span', { class: 'stat-note' }, valueNote))),
      h('div', { class: 'dash-info' },
        infoRow('Project manager', p.manager_name || 'Not assigned'),
        infoRow('Client', c.name, [c.contact_name, c.phone].filter(Boolean).join(' · ') || null)),
    ];
  }

  function renderPayments(data) {
    const p = data.project;
    const cur = data.currency;
    const payments = p.payments;
    const paidSoFar = payments.reduce((sum, s) => sum + (s.paid_date ? Number(s.amount) : 0), 0);
    const net = p.net_amount;
    const rows = payments.map((s, i) => {
      const paid = !!s.paid_date;
      const sub = (paid ? [`Paid ${longDate(parseDay(s.paid_date))}`, s.mode || null] : ['Not paid yet']).filter(Boolean).join(' · ');
      return h('div', { class: 'step-row' },
        h('span', { class: paid ? 'step-circle paid' : 'step-circle', 'aria-hidden': 'true' }, paid ? '✓' : String(i + 1)),
        h('span', { class: 'step-main' },
          h('span', { class: 'step-title' }, s.label),
          h('span', { class: 'step-sub' }, s.comments ? `${sub} · ${s.comments}` : sub)),
        h('span', { class: 'step-amount' }, money(s.amount, cur)));
    });
    return [h('section', { class: 'p-section' },
      h('h3', {}, 'Payment timeline'),
      h('div', { class: 'pay-overview' },
        h('dl', { class: 'pay-overview-grid' },
          h('dt', {}, p.final_amount != null ? 'Final amount' : 'Negotiated amount'), h('dd', {}, net != null ? money(net, cur) : '—'),
          h('dt', {}, 'Advance payment'), h('dd', {}, payments.length ? money(payments[0].amount, cur) : '—'),
          h('dt', {}, 'Paid so far'), h('dd', {}, money(paidSoFar, cur)),
          h('dt', {}, 'Remaining'), h('dd', {}, net != null ? money(net - paidSoFar, cur) : '—'))),
      payments.length
        ? [h('p', { class: 'steps-label' }, `Payments · ${payments.length}`), h('div', { class: 'card-group step-list' }, rows)]
        : h('p', { class: 'hint' }, 'No payments have been scheduled yet.'))];
  }

  function renderDetails(data) {
    const p = data.project;
    const c = data.client;
    const site = [p.site_address, p.site_city, p.site_district, p.site_state].filter(Boolean).join(', ');
    let expected = null;
    if (p.start_date && p.completion_days != null) {
      const d = parseDay(p.start_date);
      d.setDate(d.getDate() + Number(p.completion_days));
      expected = longDate(d);
    }
    const docs = data.document_types
      .filter(([key]) => p.documents[key])
      .map(([key, label]) => h('li', {}, h('a', { href: p.documents[key].url, target: '_blank', rel: 'noopener noreferrer' }, label)));
    return [
      h('section', { class: 'p-client' },
        h('div', {}, h('span', { class: 'p-label' }, 'Client'), h('span', { class: 'p-client-name' }, c.name)),
        site ? h('p', { class: 'hint' }, `Site: ${site}${p.site_pincode ? ` - ${p.site_pincode}` : ''}`) : null),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Project'),
        h('div', { class: 'dash-info' },
          infoRow('Site name', p.site_name || p.title),
          infoRow('Status', (STATUS[p.status] || [p.status])[0]),
          infoRow('Project manager', p.manager_name))),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Work order'),
        h('div', { class: 'dash-info' },
          infoRow('Work order number', p.work_order_no),
          infoRow('Work order date', p.work_order_date && longDate(parseDay(p.work_order_date))),
          infoRow('Approx. start date', p.start_date && longDate(parseDay(p.start_date))),
          infoRow('Completion period', p.completion_days != null && plural(p.completion_days, 'day', 'days')),
          infoRow('Expected completion', expected))),
      p.payment_terms || p.special_terms ? h('section', { class: 'p-section' },
        h('h3', {}, 'Terms'),
        p.payment_terms ? h('p', { class: 'hint' }, `Payment: ${p.payment_terms}`) : null,
        p.special_terms ? h('p', { class: 'hint' }, `Special: ${p.special_terms}`) : null) : null,
      docs.length ? h('section', { class: 'p-section' }, h('h3', {}, 'Documents'), h('ul', {}, docs)) : null,
    ];
  }

  function renderProgress(data) {
    const stages = data.stages;
    const currentIdx = stages.findIndex((s) => s.key === data.current_stage_key);
    const bar = h('div', { class: 'lead-progress' },
      stages.map((s, i) => h('i', { class: s.done ? 'done' : (i === currentIdx ? 'current' : null) })));
    const stepText = currentIdx === -1 ? 'All stages complete' : `Step ${currentIdx + 1} of ${stages.length} · ${stages[currentIdx].label}`;
    const body = stages.map((stage, idx) => {
      if (stage.done) return finishedStageRow(stage);
      if (idx === currentIdx) return currentStageCard(stage, idx, data.pause_reasons, data.currency);
      return upcomingStageRow(stage, idx);
    });
    return [bar, h('p', { class: 'lead-step-text' }, stepText), ...body];
  }

  const SECTIONS = { '': renderOverview, payments: renderPayments, details: renderDetails, progress: renderProgress };

  async function showProject(id, section) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/my-projects/${id}`); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const p = data.project;

    LD.setAppbarBack?.('Your projects', '#');
    $('#appbar-back')?.style.removeProperty('display');
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, p.code), statusChip(p.status)),
      h('p', { class: 'hint' }, [p.title, p.site_name].filter(Boolean).join(' · ')),
      tabBar(p.id, section),
      ...SECTIONS[section](data)));
    window.scrollTo(0, 0);
  }

  function route() {
    const m = /^#p(\d+)(?:\/(payments|details|progress))?$/.exec(window.location.hash);
    if (m) return showProject(Number(m[1]), m[2] || '');
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
