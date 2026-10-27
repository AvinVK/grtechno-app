/* Fooding: a daily-wage employee's food (and now any) allowance - see app/fooding.py and
   models.FoodingAccount/FoodingEntry for the no-cron settle() design and the ledger this all rests on.
   One page, two audiences, same split as attendance.js's own team_only (kohal, 2026-10-18: "fooding should
   open its own page!" - this used to only be a block on the Me hub for the managing side):
   - mode "manage" (the admin or accountant): every daily-wage employee, what's been allotted and what's
     left, tap a row to top up (with how it was paid) or pause/resume.
   - mode "own" (a daily-wage worker): their own balance, or "Paused" if it is, plus "+ Add expense" to log
     spending the balance on travel or anything else (kohal: "the daily wages employee can also use the
     money for travelling or for any reason") - amount, how it was paid, and what it was for. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, money, field, selectField, closeOnBack } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;

  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  };

  /* ---------- mode "own": a daily-wage worker's own balance ---------- */

  async function loadOwn() {
    let data;
    try {
      data = await api('/api/fooding/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    renderOwn(data);
  }

  function renderOwn(data) {
    const f = data.fooding;
    const cur = data.currency;
    const entries = data.entries || [];
    clear(view).append(h('div', { class: 'project-detail' },
      f.is_paused ? h('p', {}, h('span', { class: 'chip chip-off' }, 'Paused')) : null,
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Allotted'),
          h('span', { class: 'stat-value is-text' }, money(f.allotted_total, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Remaining'),
          h('span', { class: 'stat-value is-text' }, money(f.remaining, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Daily deduction'),
          h('span', { class: 'stat-value is-text' }, f.is_paused ? 'Paused' : `${money(f.daily_amount, cur)}/day`))),
      h('p', { class: 'hint' }, f.is_paused
        ? 'The admin or accountant has paused your fooding deduction - nothing is coming off your balance right now.'
        : `₹${f.daily_amount} comes off your fooding balance automatically, every day, until the admin or accountant pauses it or your balance runs out.`),
      h('div', { class: 'form-actions' },
        h('button', { class: 'btn primary', type: 'button', onclick: () => openExpenseSheet(data.payment_modes, cur) }, '+ Add expense')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Expenses'),
        entries.length
          ? h('ul', { class: 'card-group' }, entries.map(entryRow(cur)))
          : h('p', { class: 'hint' }, 'Nothing logged yet - use + Add expense when you spend some of this on travel or anything else.'))));
  }

  function entryRow(cur, { forManager = false } = {}) {
    return (e) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, e.kind === 'allot' ? (forManager ? 'Credited' : 'Allotted to you') : (e.purpose || 'Expense')),
        h('span', { class: 'row-sub' }, [fmtDate(e.entry_date), e.payment_mode,
          e.created_by_name ? `${e.kind === 'allot' ? 'by' : 'logged by'} ${e.created_by_name}` : null].filter(Boolean).join(' · '))),
      h('span', { class: 'row-value' }, (e.kind === 'allot' ? '+' : '−') + money(e.amount, cur)));
  }

  function openExpenseSheet(paymentModes, cur) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'number', min: '1', step: 'any', inputmode: 'decimal' });
    const modeSel = selectField(paymentModes, '', { title: 'How was it paid', placeholder: 'Choose one' });
    const purposeInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off', placeholder: 'e.g. Bus fare to site' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Add expense');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      errEl.textContent = '';
      try {
        const res = await api('/api/fooding/me/expenses', {
          method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value, purpose: purposeInput.value },
        });
        finish();
        toast('Expense added');
        renderOwn({ fooding: res.fooding, entries: res.entries, currency: cur, payment_modes: paymentModes });
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        saveBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Add expense'),
      field('amount', 'Amount', amountInput),
      field('payment_mode', 'How was it paid', modeSel),
      field('purpose', 'What was it for', purposeInput),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
    amountInput.focus();
  }

  /* ---------- mode "manage": the admin or accountant's own page ---------- */

  /* Employees | Requests (kohal, 2026-10-27: "a subtab or request in fooding tab where one can see active
     request and history"). `waiting` is how many requests are waiting on this person, shown on the tab. */
  const tabBar = (active, waiting) => h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Fooding section' },
    [['employees', 'Employees', '#'], ['requests', waiting ? `Requests (${waiting})` : 'Requests', '#requests']].map(([key, label, href]) => h('a', {
      class: 'filter-chip', href, 'aria-current': active === key ? 'page' : null,
    }, label)));

  async function waitingCount() {
    try {
      const r = await api('/api/fooding/requests');
      return r.pending.filter((p) => p.can_decide).length;
    } catch (err) { return 0; }
  }

  async function loadManage() {
    LD.resetAppbarBack?.();
    let data;
    let waiting = 0;
    try {
      [data, waiting] = await Promise.all([api('/api/fooding'), waitingCount()]);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    clear(view).append(h('div', {},
      tabBar('employees', waiting),
      h('p', { class: 'result-count' }, `${data.workers.length} daily-wage employee${data.workers.length === 1 ? '' : 's'}`),
      data.workers.length
        ? h('ul', { class: 'card-group' }, data.workers.map((w) => row(w, data.daily_amount, data.currency)))
        : h('p', { class: 'empty-state' }, 'No daily-wage employees yet - mark someone from Employee management first.')));
  }

  function row(w, dailyAmount, cur) {
    const sub = w.is_paused
      ? 'Paused'
      : `${money(w.allotted_total, cur)} allotted · ${money(dailyAmount, cur)}/day`;
    return h('li', {}, h('button', {
      type: 'button', class: `card me-row approval-row fooding-row${w.is_paused ? ' is-paused' : ''}`,
      onclick: () => { window.location.hash = `#p${w.worker_id}`; },
    },
      h('div', { class: 'approval-main' },
        h('strong', {}, w.worker_name),
        h('span', { class: 'hint' }, sub)),
      h('span', { class: 'fn-stat-value' }, money(w.remaining, cur))));
  }

  /* One person's own page, opened from the list the way an employee opens from the attendance register
     (kohal, 2026-10-27: "it should open like how attendance register opens") - the register of everything
     credited and spent with date and who entered it (kohal: "show credited, spent with date, who credited
     just like a register"), then adding to the balance and pausing the daily deduction. */
  async function showPerson(id) {
    LD.setAppbarBack?.('Fooding', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    let reg;
    try {
      reg = await api(`/api/fooding/${id}`);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back')));
      return;
    }
    const f = reg.fooding;
    const cur = reg.currency;
    const amountInput = h('input', { type: 'number', min: '1', step: 'any', inputmode: 'decimal', placeholder: 'Amount to add' });
    const modeSel = selectField(reg.payment_modes, '', { title: 'How was it paid', placeholder: 'Choose one' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const allotBtn = h('button', { class: 'btn primary', type: 'button' }, 'Send for approval');
    const pauseBtn = h('button', { class: 'btn', type: 'button' }, f.is_paused ? 'Resume' : 'Pause');
    allotBtn.onclick = async () => {
      allotBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api(`/api/fooding/${id}/allot`, { method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value } });
        toast('Sent for approval');
        await showPerson(id);
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        allotBtn.disabled = false;
      }
    };
    pauseBtn.onclick = async () => {
      pauseBtn.disabled = true;
      try {
        await api(`/api/fooding/${id}/${f.is_paused ? 'resume' : 'pause'}`, { method: 'POST' });
        toast(f.is_paused ? 'Fooding resumed' : 'Fooding paused');
        await showPerson(id);
      } catch (err) {
        toast(err.message, true);
        pauseBtn.disabled = false;
      }
    };
    const entries = reg.entries || [];
    clear(view).append(h('div', { class: 'people' },
      h('div', { class: 'att-head' },
        h('h2', {}, f.worker_name),
        h('span', { class: 'att-head-date' }, f.is_paused ? 'Paused' : `${money(f.daily_amount, cur)}/day`)),
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Allotted'),
          h('span', { class: 'stat-value is-text' }, money(f.allotted_total, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Remaining'),
          h('span', { class: 'stat-value is-text' }, money(f.remaining, cur)),
          h('span', { class: 'stat-note' }, `Daily food deducted: ${money(reg.auto_deducted, cur)}`))),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Register'),
        entries.length
          ? h('ul', { class: 'card-group' }, entries.map(entryRow(cur, { forManager: true })))
          : h('p', { class: 'hint' }, 'Nothing credited or spent yet.')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Add to balance'),
        h('p', { class: 'hint' }, 'The admin or accountant who didn\u2019t ask for it has to approve it before it is added.'),
        field('amount', 'Amount', amountInput),
        field('payment_mode', 'How was it paid', modeSel),
        errEl,
        h('div', { class: 'confirm-actions' }, pauseBtn, allotBtn))));
    window.scrollTo(0, 0);
  }

  /* ---------- Requests: what is waiting on someone, and the history of what was decided ---------- */

  const STATUS = { approved: ['Approved', 'chip-role'], rejected: ['Rejected', 'chip-off'], cancelled: ['Withdrawn', 'chip-off'], pending: ['Waiting', 'chip-off'] };

  async function showRequests() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    let data;
    try {
      data = await api('/api/fooding/requests');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;
    const waiting = data.pending.filter((p) => p.can_decide).length;

    async function act(r, action, doneText) {
      try {
        await api(`/api/fooding/requests/${r.id}/${action}`, { method: 'POST' });
        toast(doneText);
        await showRequests();
      } catch (err) { toast(err.message, true); }
    }

    const activeRow = (r) => h('li', { class: 'card approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.worker_name} \u00b7 ${money(r.amount, cur)}`),
        h('span', { class: 'hint' }, [r.payment_mode, `asked by ${r.created_by_name || 'someone'}`, fmtDate(r.entry_date)].join(' \u00b7 ')),
        r.is_mine ? h('span', { class: 'hint' }, 'Waiting for the other of admin / accountant to approve') : null),
      h('div', { class: 'approval-actions' },
        r.can_decide ? h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve', 'Approved') }, 'Approve') : null,
        r.can_decide ? h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject', 'Rejected') }, 'Reject') : null,
        r.is_mine ? h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'cancel', 'Request withdrawn') }, 'Withdraw') : null));

    const historyRow = (r) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, r.worker_name),
        h('span', { class: 'row-sub' }, [fmtDate(r.entry_date), r.payment_mode, r.created_by_name ? `asked by ${r.created_by_name}` : null,
          r.decided_by_name ? `${r.status === 'cancelled' ? 'withdrawn' : r.status} by ${r.decided_by_name}` : null].filter(Boolean).join(' \u00b7 ')),
        h('span', { class: `chip ${STATUS[r.status][1]}` }, STATUS[r.status][0])),
      h('span', { class: 'row-value' }, money(r.amount, cur)));

    clear(view).append(h('div', {},
      tabBar('requests', waiting),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Active'),
        data.pending.length
          ? h('ul', { class: 'card-group' }, data.pending.map(activeRow))
          : h('p', { class: 'hint' }, 'Nothing waiting. When someone allots fooding money it shows up here until the other of admin / accountant approves it.')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'History'),
        data.history.length
          ? h('ul', { class: 'card-group' }, data.history.map(historyRow))
          : h('p', { class: 'hint' }, 'Nothing decided yet.'))));
  }

  function route() {
    const m = /^#p(\d+)$/.exec(window.location.hash);
    if (m) return showPerson(Number(m[1]));
    if (window.location.hash === '#requests') return showRequests();
    return loadManage();
  }

  if (mode === 'manage') {
    window.addEventListener('hashchange', route);
    route();
  } else loadOwn();
})();
