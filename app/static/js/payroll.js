/* Payroll (kohal, 2026-10-20: "we will need a payroll tab inside manage itself... based on their
   attendance, their wages will be calculated as running sum... have 2 subtabs inside payroll: overview and
   wages payments"): two subtabs, same shape as Work plan/Announcements -
   - Overview: every employee with a wage set, and what they've earned so far (app/payroll.py computes
     this fresh each time, never stored - see its own docstring for exactly how daily-wage/contractor and
     salaried employees differ).
   - Wages & payments: pick an employee, see/add/edit/delete their payment log - the same WorkerPayment log
     that used to live on the Attendance sheet's own person page (app/static/js/people.js), moved here
     (kohal: "remove the paymant thing inside the attendance and move it here"); still saved through the
     Worker's own PATCH /api/workforce/<id>, nothing changed server-side except where this UI lives. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, confirm, money, field, showFieldErrors, selectField, searchField, dateField, closeOnBack } = window.LD;
  const view = $('#view');
  const canWrite = view.dataset.canWrite === '1';

  const EMPLOYMENT_LABEL = { regular: 'Salary', daily_wages: 'Daily wages', contractor: 'Contractor' };
  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const parseDay = (iso) => { const [y, m, d] = iso.split('-'); return new Date(+y, m - 1, +d); };
  const shortDate = (d) => `${WEEKDAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  const toNumber = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? 0 : Number(v));

  function tabs(active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Payroll section' },
      h('a', { class: 'filter-chip', href: '#overview', 'aria-current': active === 'overview' ? 'page' : null }, 'Overview'),
      h('a', { class: 'filter-chip', href: '#payments', 'aria-current': active === 'payments' ? 'page' : null }, 'Wages & payments'));
  }

  /* ---------- Overview: computed running sum, read-only ---------- */

  async function showOverview() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/payroll/overview'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    const rows = data.employees || [];
    const state = { q: '' };
    const count = h('span', { class: 'att-week-sum' });
    const listBox = h('div', {});
    const totalOutstanding = rows.reduce((sum, e) => sum + e.outstanding, 0);
    const search = h('input', {
      type: 'search', placeholder: 'Search by name', 'aria-label': 'Search by name',
      oninput: (e) => { state.q = e.target.value; render(); },
    });

    function employeeRow(e) {
      const basis = e.employment_type === 'regular'
        ? `${plural(e.months || 0, 'month', 'months')} since they started`
        : `${plural(e.days || 0, 'day', 'days')} paid, Sundays included`;
      return h('li', { class: 'p-row' },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, e.name),
          h('span', { class: 'row-sub' },
            `${EMPLOYMENT_LABEL[e.employment_type]} · ${money(e.wage_amount, cur)} · ${basis} · Earned ${money(e.earned, cur)} · Paid ${money(e.paid, cur)}`)),
        h('span', { class: 'row-value' }, money(e.outstanding, cur)));
    }

    function render() {
      const q = state.q.trim().toLowerCase();
      const people = rows.filter((e) => !q || e.name.toLowerCase().includes(q));
      count.textContent = plural(people.length, 'person', 'people');
      clear(listBox).append(people.length
        ? h('ul', { class: 'card-group' }, people.map(employeeRow))
        : h('p', { class: 'empty-state' }, rows.length ? 'Nobody matches this search.' : 'No employee has a wage set yet - add one from Employee management.'));
    }
    render();

    clear(view).append(h('div', { class: 'project-detail' },
      tabs('overview'),
      h('div', { class: 'list-head' }, h('h2', {}, 'Everyone with a wage'), count),
      search,
      rows.length ? h('p', { class: 'wk-legend' }, `Total outstanding: ${money(totalOutstanding, cur)}`) : null,
      listBox));
  }

  /* ---------- Wages & payments: pick an employee, manage their payment log ---------- */

  const paymentLabelFor = (index) => {
    const n = index + 1;
    const suffix = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th';
    return `${n}${suffix} payment`;
  };

  function paymentsSection(worker, id, currency, modes, onChange) {
    let steps = (worker.payments || []).map((p) => ({ ...p }));
    const stepsLabel = h('p', { class: 'steps-label' });
    const stepsList = h('div', { class: 'card-group step-list' });
    const paidNote = h('p', { class: 'wk-legend' });

    function toPayload(arr) {
      return arr.map((s, i) => ({
        label: (s.label || '').trim() || paymentLabelFor(i),
        amount: s.amount === '' || s.amount == null ? 0 : s.amount,
        mode: s.mode || '', paid_date: s.paid_date || null, comments: (s.comments || '').trim(),
      }));
    }

    async function persistSteps(next) {
      const saved = await api(`/api/workforce/${id}`, { method: 'PATCH', body: { payments: toPayload(next) } });
      steps = saved.worker.payments.map((p) => ({ ...p }));
      onChange(saved.worker);
      renderStepsList();
    }

    function renderStepsList() {
      const paid = steps.reduce((sum, s) => sum + (s.paid_date ? toNumber(s.amount) : 0), 0);
      stepsLabel.textContent = `Payments · ${steps.length}`;
      paidNote.textContent = steps.length ? `Paid so far: ${money(paid, currency)}` : '';
      clear(stepsList);
      steps.forEach((s, i) => {
        const isPaid = !!s.paid_date;
        const circle = isPaid
          ? h('span', { class: 'step-circle paid', 'aria-hidden': 'true' }, '✓')
          : h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(i + 1));
        const title = (s.label || '').trim() || paymentLabelFor(i);
        const subParts = isPaid ? [`Paid ${shortDate(parseDay(s.paid_date))}`, s.mode || null].filter(Boolean) : ['Not paid yet'];
        let sub = subParts.join(' · ');
        if (s.comments) sub += ' · note';
        const rowProps = canWrite ? { onclick: () => openStepSheet(i) } : {};
        stepsList.append(h('button', {
          type: 'button', class: 'step-row', disabled: !canWrite,
          'aria-label': `${title}, ${money(toNumber(s.amount), currency)}, ${isPaid ? 'paid' : 'not paid'}`,
          ...rowProps,
        },
          circle,
          h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, title), h('span', { class: 'step-sub' }, sub)),
          h('span', { class: 'step-amount' }, money(toNumber(s.amount), currency))));
      });
      if (canWrite) {
        stepsList.append(h('button', { type: 'button', class: 'step-row step-add', onclick: () => openStepSheet(steps.length) },
          h('span', { class: 'step-circle dashed', 'aria-hidden': 'true' }, '+'),
          h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, '+ Add payment'))));
      }
    }

    function openStepSheet(index) {
      const isNew = index === steps.length;
      const current = isNew ? { label: '', amount: '', mode: '', paid_date: null, comments: '' } : steps[index];
      const trigger = document.activeElement;
      const overlay = h('div', { class: 'overlay' });
      const scroll = h('div', { class: 'drawer-scroll' });
      const foot = h('div', { class: 'drawer-foot' });
      const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });

      const finish = closeOnBack(() => {
        overlay.remove();
        drawer.remove();
        document.body.classList.remove('locked');
        if (trigger && trigger.isConnected) trigger.focus();
      });
      overlay.onclick = () => finish();
      const closeX = h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close' }, '×');
      closeX.onclick = () => finish();

      const labelInput = h('input', { type: 'text', maxlength: 120, value: current.label || '' });
      const amountInput = h('input', { type: 'number', id: 'f-amount', min: '0', step: 'any', inputmode: 'decimal', value: current.amount ?? '' });
      const chips = h('div', { class: 'step-chips' });
      if (worker.wage_amount != null) {
        chips.append(h('button', {
          type: 'button', class: 'btn small',
          onclick: () => { amountInput.value = worker.wage_amount; amountInput.dispatchEvent(new Event('input', { bubbles: true })); },
        }, `Wage/salary amount · ${money(worker.wage_amount, currency)}`));
      }

      const modeSel = selectField(
        [{ value: '', label: 'Mode of payment' }, ...modes.map((m) => ({ value: m, label: m }))],
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
          label: labelInput.value, amount: amountInput.value, mode: modeSel.value,
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
          const sure = await confirm(`Remove ${(current.label || '').trim() || paymentLabelFor(index)}?`, { ok: 'Delete', danger: true, title: 'Delete payment' });
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
      const title = (current.label || '').trim() || paymentLabelFor(index);
      scroll.append(
        errorBox,
        field('label', 'Label', labelInput),
        h('div', { class: 'field' },
          h('label', { for: 'f-amount' }, 'Amount'),
          h('div', { class: 'amount-input-wrap' }, h('span', { class: 'amount-prefix', 'aria-hidden': 'true' }, currency), amountInput),
          chips,
          h('p', { class: 'err', id: 'err-amount', role: 'alert' })),
        h('div', { class: 'toggle-row' }, h('span', {}, 'Payment made'), paidToggle),
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
      document.body.append(overlay, drawer);
      (isNew ? amountInput : labelInput).focus();
    }

    renderStepsList();
    return h('section', { class: 'p-section' }, stepsLabel, paidNote, stepsList);
  }

  async function showPayments(personId) {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let roster;
    try { roster = await api('/api/workforce'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const groups = Object.keys(roster).filter((k) => Array.isArray(roster[k]));
    const people = groups.flatMap((g) => roster[g]).map((p) => ({ value: p.id, label: p.name }));

    const picker = searchField(people, personId || '', { placeholder: 'Search employees…' });
    const detailBox = h('div', {});

    async function loadPerson(id) {
      clear(detailBox).append(h('p', { class: 'loading' }, 'Loading…'));
      let data;
      try { data = await api(`/api/workforce/${id}`); } catch (err) { clear(detailBox).append(h('p', { class: 'empty-state' }, err.message)); return; }
      const sub = [EMPLOYMENT_LABEL[data.worker.employment_type],
        data.worker.wage_amount != null ? money(data.worker.wage_amount, data.currency) : null].filter(Boolean).join(' · ');
      clear(detailBox).append(
        h('div', { class: 'att-head' }, h('h3', {}, data.worker.name), h('span', { class: 'att-head-date' }, sub)),
        paymentsSection(data.worker, id, data.currency, data.payment_modes, () => loadPerson(id)));
    }

    picker.addEventListener('change', () => {
      const id = picker.value;
      window.location.hash = id ? `#payments/${id}` : '#payments';
    });

    if (personId) await loadPerson(personId);
    else clear(detailBox).append(h('p', { class: 'hint' }, 'Search for an employee above to see or add their payments.'));

    clear(view).append(h('div', { class: 'project-detail' },
      tabs('payments'),
      field('employee', 'Employee', picker),
      detailBox));
  }

  function route() {
    const hash = window.location.hash;
    const m = /^#payments(?:\/(\d+))?$/.exec(hash);
    if (m) return showPayments(m[1] ? Number(m[1]) : null);
    return showOverview();
  }

  window.addEventListener('hashchange', route);
  route();
})();
