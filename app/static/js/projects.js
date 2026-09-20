/* Projects: a list, and one screen per project for the work order, amounts, terms and payment schedule. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, money, field, showFieldErrors } = window.LD;

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

  const toNumber = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? 0 : Number(v));

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }

  /* ---------- list ---------- */

  async function showList() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading projects…'));
    let data;
    try { data = await api('/api/projects'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;

    const wrap = h('div', {});
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Filter by status' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const list = h('ul', { class: 'rows' });
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

    function refresh() {
      const q = filter.q.trim().toLowerCase();
      const items = data.projects.filter((p) => {
        if (filter.status && p.status !== filter.status) return false;
        return !q || [p.title, p.client_name, p.code, p.work_category].some((v) => (v || '').toLowerCase().includes(q));
      });
      count.textContent = plural(items.length, 'project', 'projects');
      clear(list);
      if (!items.length) {
        list.append(h('li', { class: 'empty-state' }, data.projects.length
          ? 'No projects match this search.'
          : 'No projects yet. Tap Add project, or win a lead and tap Create project on it.'));
        return;
      }
      items.forEach((p) => list.append(h('li', {}, h('a', { class: 'p-row', href: `#p${p.id}` },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, p.title),
          h('span', { class: 'row-sub' }, [p.client_name, p.work_category].filter(Boolean).join(' · '))),
        h('span', { class: 'row-value' }, money(p.net_amount, cur)),
        h('span', { class: 'p-foot' }, statusChip(p.status),
          h('span', { class: 'p-code' }, p.code),
          p.manager_name ? h('span', { class: 'p-manager' }, `PM: ${p.manager_name}`) : h('span', { class: 'p-manager none' }, 'No manager yet'))))));
    }

    wrap.append(
      h('div', { class: 'list-head' }, h('h2', {}, 'Projects'), h('a', { class: 'btn primary', href: '#new' }, 'Add project')),
      h('div', { class: 'filters' }, search, chips), count, list);
    clear(view).append(wrap);
    renderChips();
    refresh();
  }

  /* ---------- add a project that did not come from a lead ---------- */

  async function showNew() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    let data;
    try { data = await api('/api/projects'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const clientSel = h('select', {},
      h('option', { value: '' }, 'A new client\u2026'),
      data.clients.map((c) => h('option', { value: c.id }, c.name)));
    const newName = h('input', { type: 'text', maxlength: 160, autocomplete: 'off', placeholder: 'Client name' });
    const newNameField = field('new_client_name', 'New client name', newName);
    const titleInput = h('input', { type: 'text', maxlength: 160, autocomplete: 'off', placeholder: 'Optional (defaults to client and work)' });
    const category = h('select', {}, h('option', { value: '' }, 'Not set'), data.services.map((s) => h('option', { value: s }, s)));
    const statusSel = h('select', {}, data.statuses.map((s) => h('option', { value: s, selected: s === 'running' }, STATUS[s][0])));
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
          window.location.hash = `#p${saved.project.id}`;
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
      h('p', { class: 'hint' }, 'You can add the work order, amounts, terms and payment schedule on the next screen.'),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', { class: 'project-detail' },
      h('a', { class: 'back-link', href: '#' }, '\u2190 All projects'),
      h('div', { class: 'p-head' }, h('h2', {}, 'Add project')),
      form));
  }

  /* ---------- one project ---------- */

  async function showDetail(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading project…'));
    let data;
    try { data = await api(`/api/projects/${id}`); }
    catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to projects')));
      return;
    }
    renderDetail(data);
  }

  function renderDetail(data) {
    const P = data.project;
    const cur = data.currency;
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const area = (rows, value) => { const t = h('textarea', { rows }); t.value = value ?? ''; return t; };

    const title = text('text', P.title, { maxlength: 160, autocomplete: 'off' });
    const statusSel = h('select', {}, data.statuses.map((s) => h('option', { value: s, selected: s === P.status }, STATUS[s][0])));
    const woNo = text('text', P.work_order_no, { maxlength: 60, autocomplete: 'off' });
    const woDate = text('date', P.work_order_date);
    const startDate = text('date', P.start_date);
    const days = text('number', P.completion_days, { min: '0', step: '1', inputmode: 'numeric' });
    const estimated = text('number', P.estimated_amount, { min: '0', step: 'any', inputmode: 'decimal' });
    const discount = text('number', P.discount_amount || '', { min: '0', step: 'any', inputmode: 'decimal' });
    const payTerms = area(3, P.payment_terms);
    const specialTerms = area(3, P.special_terms);
    const managerSel = data.can_assign_manager
      ? h('select', {}, h('option', { value: '' }, 'Not assigned'),
        data.managers.map((m) => h('option', { value: m.code, selected: m.code === P.manager_code }, m.name)))
      : null;

    const finish = h('p', { class: 'hint', 'aria-live': 'polite' });
    const net = h('p', { class: 'net-amount', 'aria-live': 'polite' });

    /* payment schedule */
    const payRows = h('div', { class: 'pay-rows' });
    const paySummary = h('p', { class: 'pay-summary', 'aria-live': 'polite' });
    const payErr = h('p', { class: 'err', id: 'err-payments', role: 'alert' });

    function addPayRow(p = { label: '', amount: '', due_date: '' }) {
      const row = h('div', { class: 'pay-row' },
        h('input', { type: 'text', class: 'pay-label', maxlength: 120, placeholder: 'For example: Advance', 'aria-label': 'Payment step name', value: p.label }),
        h('input', { type: 'number', class: 'pay-amount', min: '0', step: 'any', inputmode: 'decimal', placeholder: `Amount (${cur})`, 'aria-label': 'Amount', value: p.amount ?? '' }),
        h('input', { type: 'date', class: 'pay-date', 'aria-label': 'Due date', value: p.due_date || '' }),
        h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Remove this payment step', onclick: () => { row.remove(); payErr.textContent = ''; recalc(); } }, '×'));
      payRows.append(row);
    }
    (P.payments.length ? P.payments : []).forEach(addPayRow);

    const payments = () => [...payRows.querySelectorAll('.pay-row')].map((r) => ({
      label: r.querySelector('.pay-label').value,
      amount: r.querySelector('.pay-amount').value === '' ? 0 : r.querySelector('.pay-amount').value,
      due_date: r.querySelector('.pay-date').value || null,
    }));

    function recalc() {
      const est = estimated.value === '' ? null : toNumber(estimated.value);
      const netValue = est === null ? null : est - toNumber(discount.value);
      net.textContent = netValue === null ? '' : `Net amount: ${money(netValue, cur)}`;
      net.classList.toggle('bad', netValue !== null && netValue < 0);

      const scheduled = payments().reduce((sum, p) => sum + toNumber(p.amount), 0);
      paySummary.className = 'pay-summary';
      if (!payRows.children.length) paySummary.textContent = '';
      else if (netValue === null) paySummary.textContent = `Scheduled: ${money(scheduled, cur)}`;
      else if (scheduled > netValue) { paySummary.textContent = `Scheduled ${money(scheduled, cur)} is more than the net amount ${money(netValue, cur)}`; paySummary.classList.add('bad'); }
      else if (scheduled === netValue) { paySummary.textContent = `All ${money(netValue, cur)} is scheduled`; paySummary.classList.add('good'); }
      else paySummary.textContent = `Scheduled ${money(scheduled, cur)} of ${money(netValue, cur)}. ${money(netValue - scheduled, cur)} is not scheduled yet.`;

      if (startDate.value && days.value !== '') {
        const [y, m, d] = startDate.value.split('-').map(Number);
        const end = new Date(Date.UTC(y, m - 1, d + toNumber(days.value)));
        finish.textContent = `Expected completion: ${fmtDate(end.toISOString().slice(0, 10))}`;
      } else finish.textContent = 'Add a start date and completion period to see the expected completion date.';
    }

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save project');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = {
          title: title.value, status: statusSel.value, work_order_no: woNo.value, work_order_date: woDate.value,
          start_date: startDate.value, completion_days: days.value, estimated_amount: estimated.value,
          discount_amount: discount.value, payment_terms: payTerms.value, special_terms: specialTerms.value,
          payments: payments(),
        };
        if (managerSel) body.manager_code = managerSel.value;
        try {
          const saved = await api(`/api/projects/${P.id}`, { method: 'PATCH', body });
          toast('Project saved');
          renderDetail(saved);
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
      h('section', { class: 'p-section' },
        h('h3', {}, 'Amount'),
        h('div', { class: 'form-grid' },
          field('estimated_amount', `Estimated amount (${cur})`, estimated),
          field('discount_amount', `Discount (${cur})`, discount)),
        net),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Terms'),
        h('div', { class: 'form-grid' },
          field('payment_terms', 'Payment terms', payTerms, { wide: true }),
          field('special_terms', 'Special terms', specialTerms, { wide: true }))),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Payment schedule'),
        h('p', { class: 'hint' }, 'Split the net amount into steps, for example advance, on delivery, on completion.'),
        payRows,
        payErr,
        h('button', { class: 'btn small', type: 'button', onclick: () => { addPayRow(); recalc(); payRows.lastChild.querySelector('input').focus(); } }, 'Add payment step'),
        paySummary),
      h('div', { class: 'form-actions' }, saveBtn));

    form.addEventListener('input', (e) => {
      // A payment message from the last save no longer applies once the amounts change.
      if (payRows.contains(e.target) || e.target === estimated || e.target === discount) payErr.textContent = '';
      recalc();
    });

    const site = [P.site_address, P.site_city, P.site_district, P.site_state].filter(Boolean).join(', ');
    const c = data.client;
    clear(view).append(h('div', { class: 'project-detail' },
      h('a', { class: 'back-link', href: '#' }, '← All projects'),
      h('div', { class: 'p-head' },
        h('h2', {}, P.code), statusChip(P.status)),
      h('section', { class: 'p-client' },
        h('div', {},
          h('span', { class: 'p-label' }, 'Client'),
          canOpenClients ? h('a', { class: 'p-client-name', href: `/clients#c${c.id}` }, c.name) : h('span', { class: 'p-client-name' }, c.name)),
        c.phone ? h('a', { class: 'btn small', href: `tel:${c.phone.replace(/[^\d+]/g, '')}` }, 'Call') : null,
        site ? h('p', { class: 'hint' }, `Site: ${site}${P.site_pincode ? ` - ${P.site_pincode}` : ''}`) : null),
      form));
    recalc();
    window.scrollTo(0, 0);
  }

  function route() {
    const m = /^#p(\d+)$/.exec(window.location.hash);
    if (m) return showDetail(Number(m[1]));
    return window.location.hash === '#new' ? showNew() : showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
