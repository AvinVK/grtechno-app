/* Petrol: what an employee on petrol payment is owed for the kilometres they ride (kohal, 2026-10-27: "same
   as fooding, we need option of petrol payment") - see app/petrol.py. One page, two audiences, same split as
   fooding.js:
   - mode "manage" (the admin or accountant): two tabs, Employees (everyone on petrol payment with this
     month's amount; tap a person for their register) and Requests (cash the employees have asked for -
     active to approve, and the history).
   - mode "own" (an employee on petrol payment): their own register and totals, and a button on each approved
     day to ask for that amount in cash (kohal, 2026-10-30).
   An entry only counts towards the totals once the admin or the project manager has approved it; the cash is
   paid only once the admin or accountant approves the request and says how it was paid. */
(() => {
  'use strict';

  const { $, h, clear, api, money, toast, field, selectField, closeOnBack, showFieldErrors } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;

  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  };
  const fmtStamp = (iso) => (iso ? fmtDate(iso.slice(0, 10)) : '');

  const STATUS = { pending: ['Waiting for approval', 'chip-off'], approved: ['Approved', 'chip-role'], rejected: ['Rejected', 'chip-off'] };

  /* Where an approved day's cash stands, and (for the employee) the button to ask for it. */
  function cashPart(e, { own, onChanged }) {
    if (e.status !== 'approved') return null;
    if (e.cash_status === 'requested') return h('span', { class: 'chip chip-off' }, 'Cash requested');
    if (e.cash_status === 'paid') {
      return h('span', { class: 'chip chip-role' },
        ['Paid', e.cash_mode, fmtStamp(e.cash_decided_at)].filter(Boolean).join(' · '));
    }
    return e.cash_status === 'rejected' ? h('span', { class: 'chip chip-off' }, 'Cash request rejected') : null;
  }

  function entryRow(cur, opts) {
    return (e) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, `${fmtDate(e.work_date)} · ${e.km} km`),
        h('span', { class: 'row-sub' }, [`${e.in_reading} → ${e.out_reading}`, e.project_title, e.approved_by_name ? `by ${e.approved_by_name}` : null].filter(Boolean).join(' · ')),
        e.status === 'approved' ? null : h('span', { class: `chip ${STATUS[e.status][1]}` }, STATUS[e.status][0]),
        cashPart(e, opts)),
      h('span', { class: 'row-value' }, e.status === 'approved' ? money(e.amount, cur) : `(${money(e.amount, cur)})`));
  }

  /* The employee's ask: any amount up to what they are still owed (kohal, 2026-11-04) - the sheet opens with all of it. */
  function openRequestSheet(data, onDone) {
    const cur = data.currency;
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: data.suggested_amount > 0 ? String(data.suggested_amount) : '' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const sendBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Send request');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    const form = h('form', { novalidate: true, class: 'amount-sheet-form', onsubmit: async (e) => {
      e.preventDefault();
      sendBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      try {
        await api('/api/petrol/payouts', { method: 'POST', body: { amount: amountInput.value } });
        finish();
        toast('Request sent to the admin');
        await onDone();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        sendBtn.disabled = false;
      }
    } },
    field('amount', 'Amount', amountInput, { hint: 'Any amount - it is taken off automatically as your petrol is approved, and can go below zero.' }),
    errEl,
    h('div', { class: 'confirm-actions' }, cancelBtn, sendBtn));
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' }, h('h2', {}, 'Request petrol cash'), form));
    document.body.append(overlay);
  }

  function requestPart(data, onChanged) {
    const cur = data.currency;
    const waiting = (data.payouts || []).find((p) => p.status === 'requested');
    if (waiting) return h('p', { class: 'hint' }, `Your request for ${money(waiting.amount, cur)} is waiting for the admin.`);
    const note = data.settled ? h('p', { class: 'hint' }, 'All settled - nothing is owed to you right now.')
      : (data.advance > 0 ? h('p', { class: 'hint' }, `You are ${money(data.advance, cur)} ahead - it comes off as your petrol is approved.`) : null);
    // Asked for day by day, before one request could cover any amount - still waiting on the admin.
    const earlier = data.requested_total > 0 ? h('p', { class: 'hint' }, `${money(data.requested_total, cur)} you asked for earlier is waiting for the admin.`) : null;
    return h('div', {}, note, earlier,
      h('div', { class: 'acct-actions' },
        h('button', { class: 'btn primary', type: 'button', onclick: () => openRequestSheet(data, onChanged) }, 'Request cash')));
  }

  function paymentsSection(data) {
    const cur = data.currency;
    if (!data.payouts || !data.payouts.length) return null;
    return h('section', { class: 'p-section' },
      h('h3', {}, 'Payments'),
      h('ul', { class: 'card-group' }, data.payouts.map((p) => h('li', { class: 'p-row' },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, p.status === 'paid' ? `Paid ${money(p.amount_paid, cur)}` : (p.status === 'rejected' ? 'Request rejected' : 'Waiting for the admin')),
          h('span', { class: 'row-sub' }, [fmtStamp(p.decided_at || p.requested_at), p.status === 'paid' && p.amount_paid < p.amount ? `asked ${money(p.amount, cur)}` : null,
            p.payment_account || null, p.decided_by_name ? `by ${p.decided_by_name}` : null].filter(Boolean).join(' · '))),
        h('span', { class: 'row-value' }, money(p.status === 'paid' ? p.amount_paid : p.amount, cur))))));
  }

  function registerBlock(data, opts = {}) {
    const cur = data.currency;
    return h('div', { class: 'petrol-register' },
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'This month'),
          h('span', { class: 'stat-value is-text' }, money(data.month_total, cur)),
          h('span', { class: 'stat-note' }, `${data.month_km} km approved`)),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, data.settled ? 'Settled' : (data.advance > 0 ? 'Advance taken' : 'Balance owed')),
          h('span', { class: 'stat-value is-text' }, money(data.advance > 0 ? data.advance : data.unpaid_total, cur)),
          h('span', { class: 'stat-note' }, `${money(data.paid_total, cur)} paid · ${money(data.rate_per_km, cur)} per km`))),
      opts.own ? requestPart(data, opts.onChanged) : null,
      h('p', { class: 'hint' }, opts.own
        ? 'Each day is the kilometres between the two odometer readings, paid per km once approved. Approved days add up into your balance. Ask for petrol money any time, in any amount - it is taken off as your petrol is approved, and can go below zero. Amounts in brackets are not approved yet.'
        : 'Each day is the kilometres between the two odometer readings, paid per km once approved. Approved days add up into a balance, paid when the employee asks - they can also ask before any petrol is recorded, which shows as an advance. Amounts in brackets are not approved yet.'),
      paymentsSection(data),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Register'),
        data.entries.length
          ? h('ul', { class: 'card-group' }, data.entries.map(entryRow(cur, opts)))
          : h('p', { class: 'hint' }, 'Nothing yet - it fills in as check-ins and check-outs with an odometer reading are approved.')));
  }

  /* ---------- mode "own" ---------- */

  async function loadOwn() {
    try {
      const data = await api('/api/petrol/me');
      clear(view).append(h('div', { class: 'project-detail' }, registerBlock(data, { own: true, onChanged: loadOwn })));
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
    }
  }

  /* ---------- mode "manage" ---------- */

  const tabBar = (active, waiting) => h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Petrol section' },
    [['employees', 'Employees', '#'], ['requests', waiting ? `Requests (${waiting})` : 'Requests', '#requests']].map(([key, label, href]) => h('a', {
      class: 'filter-chip', href, 'aria-current': active === key ? 'page' : null,
    }, label)));

  async function loadManage() {
    LD.resetAppbarBack?.();
    let data;
    try {
      data = await api('/api/petrol');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;
    clear(view).append(h('div', {},
      tabBar('employees', data.cash_waiting),
      h('p', { class: 'result-count' }, `${data.workers.length} employee${data.workers.length === 1 ? '' : 's'} on petrol payment`),
      data.workers.length
        ? h('ul', { class: 'card-group' }, data.workers.map((w) => h('li', {}, h('button', {
          type: 'button', class: 'card me-row approval-row fooding-row', onclick: () => { window.location.hash = `#p${w.worker_id}`; },
        },
        h('div', { class: 'approval-main' },
          h('strong', {}, w.worker_name),
          h('span', { class: 'hint' }, [`${w.month_km} km this month`, w.pending ? `${w.pending} waiting for approval` : null,
            w.unpaid_total > 0 ? `${money(w.unpaid_total, cur)} to be paid` : (w.unpaid_total < 0 ? `${money(-w.unpaid_total, cur)} advance` : null)].filter(Boolean).join(' · '))),
        h('span', { class: 'fn-stat-value' }, money(w.month_total, cur))))))
        : h('p', { class: 'empty-state' }, 'Nobody is on petrol payment yet - switch it on for someone in Employee management.')));
  }

  /* A person's register opens as its own page, like an employee in the attendance register. */
  async function showPerson(id) {
    LD.setAppbarBack?.('Petrol', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    try {
      const data = await api(`/api/petrol/worker/${id}`);
      clear(view).append(h('div', { class: 'people' },
        h('div', { class: 'att-head' }, h('h2', {}, data.worker_name)),
        registerBlock(data)));
      window.scrollTo(0, 0);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back')));
    }
  }

  /* ---------- Requests: cash the employees have asked for ---------- */

  /* Approving means paying it, so the approver says how (kohal: "the approver have to enter the mode of
     payment") - a small sheet with the two modes and a Pay button. */
  function openPaySheet(r, paymentModes, cur, onDone) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const modeSel = selectField(paymentModes, '', { title: 'Account', placeholder: 'Choose an account' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const payBtn = h('button', { class: 'btn primary', type: 'button' }, 'Approve and mark paid');
    // Optionally pay through an app (kohal, 2026-11-02): it opens already filled in, then "Mark paid" records it.
    const picker = LD.payAppPicker({
      name: r.user_name, amount: r.amount, payee: r.payee || {}, note: 'Petrol', currency: cur,
      onChange: (app) => { payBtn.textContent = app ? 'Mark paid & approve' : 'Approve and mark paid'; },
      onError: (msg) => { errEl.textContent = msg; },
    });
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    payBtn.onclick = async () => {
      payBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api(`/api/petrol/requests/${r.id}/approve`, { method: 'POST', body: { payment_mode: modeSel.value } });
        finish();
        toast('Approved');
        await onDone();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        payBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, `${r.user_name} · ${money(r.amount, cur)}`),
      h('p', { class: 'hint' }, `${fmtDate(r.work_date)} · ${r.km} km`),
      field('payment_mode', 'Account', modeSel),
      ...picker.nodes,
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, payBtn)));
    document.body.append(overlay);
  }

  /* Paying a payout: the amount (all of what was asked, or less), the account it comes from, and optionally through
     PhonePe / Google Pay - what is paid settles against their balance and the rest stays owed (kohal, 2026-11-04). */
  function openPayoutSheet(r, paymentModes, cur, onDone) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: String(r.amount) });
    const modeSel = selectField(paymentModes, '', { title: 'Account', placeholder: 'Choose an account' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const payBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Approve and mark paid');
    const picker = LD.payAppPicker({
      name: r.user_name, amount: () => amountInput.value, payee: r.payee || {}, note: 'Petrol', currency: cur,
      onChange: (app) => { payBtn.textContent = app ? 'Mark paid & approve' : 'Approve and mark paid'; },
      onError: (msg) => { errEl.textContent = msg; },
    });
    amountInput.addEventListener('input', () => picker.refresh());
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    const form = h('form', { novalidate: true, class: 'amount-sheet-form', onsubmit: async (e) => {
      e.preventDefault();
      payBtn.disabled = true;
      errEl.textContent = '';
      showFieldErrors(form, {});
      try {
        await api(`/api/petrol/payouts/${r.id}/approve`, { method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value } });
        finish();
        toast('Paid');
        await onDone();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        payBtn.disabled = false;
      }
    } },
    field('amount', 'Amount paid', amountInput, { hint: `Asked for ${money(r.amount, cur)} · ${r.balance < 0 ? `already ${money(-r.balance, cur)} ahead` : `balance owed ${money(r.balance, cur)}`}. Pay less and the rest stays owed.` }),
    field('payment_mode', 'Account', modeSel),
    ...picker.nodes,
    errEl,
    h('div', { class: 'confirm-actions' }, cancelBtn, payBtn));
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' }, h('h2', {}, r.user_name), form));
    document.body.append(overlay);
  }

  async function showRequests() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try {
      data = await api('/api/petrol/requests');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;

    async function reject(r) {
      try {
        await api(`/api/petrol/requests/${r.id}/reject`, { method: 'POST' });
        toast('Rejected');
        await showRequests();
      } catch (err) { toast(err.message, true); }
    }

    const activeRow = (r) => h('li', { class: 'card approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.user_name} · ${money(r.amount, cur)}`),
        h('span', { class: 'hint' }, [fmtDate(r.work_date), `${r.km} km`, r.project_title, `asked ${fmtStamp(r.cash_requested_at)}`].filter(Boolean).join(' · '))),
      data.can_decide ? h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => openPaySheet(r, data.payment_modes, cur, showRequests) }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => reject(r) }, 'Reject')) : null);

    async function rejectPayout(r) {
      try {
        await api(`/api/petrol/payouts/${r.id}/reject`, { method: 'POST' });
        toast('Rejected');
        await showRequests();
      } catch (err) { toast(err.message, true); }
    }

    const payoutRow = (r) => h('li', { class: 'card approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.user_name} · ${money(r.amount, cur)}`),
        h('span', { class: 'hint' }, [r.balance < 0 ? `already ${money(-r.balance, cur)} ahead` : `balance owed ${money(r.balance, cur)}`, `asked ${fmtStamp(r.requested_at)}`].join(' · '))),
      data.can_decide ? h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => openPayoutSheet(r, data.payment_modes, cur, showRequests) }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => rejectPayout(r) }, 'Reject')) : null);

    const payoutHistoryRow = (r) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, r.user_name),
        h('span', { class: 'row-sub' }, [fmtStamp(r.decided_at), r.status === 'paid' && r.amount_paid < r.amount ? `asked ${money(r.amount, cur)}` : null,
          r.decided_by_name ? `${r.status === 'paid' ? 'paid' : 'rejected'} by ${r.decided_by_name}` : null].filter(Boolean).join(' · ')),
        h('span', { class: `chip ${r.status === 'paid' ? 'chip-role' : 'chip-off'}` }, r.status === 'paid' ? `Paid · ${r.payment_account}` : 'Rejected')),
      h('span', { class: 'row-value' }, money(r.status === 'paid' ? r.amount_paid : r.amount, cur)));

    const historyRow = (r) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, r.user_name),
        h('span', { class: 'row-sub' }, [fmtDate(r.work_date), `${r.km} km`, r.cash_decided_by_name ? `${r.cash_status === 'paid' ? 'paid' : 'rejected'} by ${r.cash_decided_by_name}` : null,
          fmtStamp(r.cash_decided_at)].filter(Boolean).join(' · ')),
        h('span', { class: `chip ${r.cash_status === 'paid' ? 'chip-role' : 'chip-off'}` },
          r.cash_status === 'paid' ? `Paid · ${r.cash_mode}` : 'Rejected')),
      h('span', { class: 'row-value' }, money(r.amount, cur)));

    clear(view).append(h('div', {},
      tabBar('requests', data.pending.length + data.payouts.length),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Active'),
        data.pending.length || data.payouts.length
          ? h('ul', { class: 'card-group' }, [...data.payouts.map(payoutRow), ...data.pending.map(activeRow)])
          : h('p', { class: 'hint' }, 'Nothing waiting. When an employee asks for petrol cash it shows up here.')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'History'),
        data.history.length || data.payout_history.length
          ? h('ul', { class: 'card-group' }, [...data.payout_history.map(payoutHistoryRow), ...data.history.map(historyRow)])
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
