/* Purchase approval (kohal, 2026-10-21: "this pending approval should have its own block next to fooding.
   named as purchase approval - this is only visisble to admin. inside this there will be approvals and
   alocate cash (same as fooding types)"; then: "allocate cash should be a button and then this form should
   open. and the subtab should be allocated cash and balance and their it should show employees to whom
   cash is allocated and how much they have balance rn. clicking on one employee should show the history of
   cash expense and whether approved or rejected"; then: "add cash request for employees so that admin sees
   the request and then alocates... for admin in purchase approval, there should be a cash requests shubtab
   which will show user has requested for 5k and then after clicking on that, it should open allocate
   form"; then: "should show the count of request in the subtab ust like in material reuest in inventory",
   "and rename approval to expense approval") - admin/accountant only, its own page off a Me-hub tile.
   Three subtabs, same pill shape as Inventory's own Materials/Material requests/Restock bar, each carrying
   a count badge the same way (see inventoryTabs in app/static/js/inventory.js):
   - Expense approval (default): every pending purchase, approve or reject it.
   - Cash requests: every employee's unanswered ask for cash, tapping one opens the same Allocate form as
     "+ Allocate cash" below, pre-filled - giving the cash closes the request out as fulfilled (see
     app/cash_purchases.py's give()); a reject link turns it down without giving anything.
   - Allocated cash & balance: every employee cash has actually been given to and what they have left,
     "+ Allocate cash" opening a sheet (same idea as Fooding's own allot) rather than a form on the page
     itself, tapping a row opening that one employee's own purchase history.
   The employee's own balance, requests and purchase log stay on the Me hub itself (see
   app/static/js/me.js) - this page is the management side only, see app/cash_purchases.py. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, field, selectField, searchField, money, closeOnBack } = window.LD;
  const view = $('#view');

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  function tabs(active, approvalBadge, requestBadge) {
    const badge = (n) => (n ? h('span', { class: 'nav-badge' }, String(n)) : null);
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Purchase approval section' },
      h('a', { class: 'filter-chip', href: '#approvals', 'aria-current': active === 'approvals' ? 'page' : null },
        'Expense approval', badge(approvalBadge)),
      h('a', { class: 'filter-chip', href: '#requests', 'aria-current': active === 'requests' ? 'page' : null },
        'Cash requests', badge(requestBadge)),
      h('a', { class: 'filter-chip', href: '#balances', 'aria-current': active === 'balances' ? 'page' : null }, 'Allocated cash & balance'));
  }

  /* ---------- Approvals: every pending purchase, approve or reject it ---------- */

  async function act(r, action) {
    if (action === 'reject') {
      const sure = await confirm('Reject this purchase? Nothing was deducted from their balance yet, so there is nothing to undo.', { ok: 'Reject', danger: true, title: 'Reject purchase' });
      if (!sure) return;
    }
    try {
      await api(`/api/cash-purchases/${r.id}/${action}`, { method: 'POST' });
      toast(action === 'approve' ? 'Approved' : 'Rejected');
      showApprovals();
    } catch (err) { toast(err.message, true); }
  }

  function row(r, cur, canDecide) {
    const sub = [fmtDate(r.entry_date), r.quantity != null ? `${r.quantity} ${r.unit || ''}`.trim() : null,
      r.supplier || null, r.created_by_name ? `Logged by ${r.created_by_name}` : null, r.note || null].filter(Boolean).join(' · ');
    return h('li', {}, h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.worker_name} · ${r.material_name}`),
        h('span', { class: 'hint' }, r.category === 'material' ? 'Material - will be added to Inventory stock on approval' : 'Other expenses'),
        h('span', { class: 'hint' }, `${money(r.amount, cur)} · ${sub}`),
        r.bill_url ? h('a', { href: r.bill_url, target: '_blank', rel: 'noopener noreferrer', class: 'link-btn' }, 'View bill') : null),
      canDecide ? h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject')) : null));
  }

  async function showApprovals() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/cash-purchases/pending'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(h('div', {},
      tabs('approvals', data.pending.length, data.pending_request_count),
      data.can_decide ? null : h('p', { class: 'hint' }, 'Only the admin can approve these.'),
      h('div', { class: 'list-head' }, h('h2', {}, `${data.pending.length} pending`)),
      data.pending.length
        ? h('ul', { class: 'card-group' }, data.pending.map((r) => row(r, data.currency, data.can_decide)))
        : h('p', { class: 'empty-state' }, 'Nothing waiting on approval right now.')));
  }

  /* ---------- Cash requests: an employee's own unanswered ask, tap to open the Allocate form ---------- */

  async function rejectRequest(r, reload) {
    const sure = await confirm(`Turn down ${r.worker_name}'s request for ${r.amount}? Nothing will be given.`,
      { ok: 'Reject', danger: true, title: 'Reject request' });
    if (!sure) return;
    try {
      await api(`/api/cash-purchases/requests/${r.id}/reject`, { method: 'POST' });
      toast('Request rejected');
      reload();
    } catch (err) { toast(err.message, true); }
  }

  function requestRow(r, data, cur, reload) {
    const canDecide = data.can_decide;
    return h('li', {}, h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.worker_name} · ${money(r.amount, cur)}`),
        h('span', { class: 'hint' }, [fmtDate(r.created_at.slice(0, 10)), r.note || null].filter(Boolean).join(' · '))),
      canDecide ? h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button',
          onclick: () => openGiveSheet(data, reload, { worker_id: r.worker_id, amount: r.amount, request_id: r.id }) }, 'Allocate'),
        h('button', { class: 'btn small', type: 'button', onclick: () => rejectRequest(r, reload) }, 'Reject')) : null));
  }

  async function showRequests() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/cash-purchases/requests'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(h('div', {},
      tabs('requests', data.pending_purchase_count, data.requests.length),
      data.can_decide ? null : h('p', { class: 'hint' }, 'Only the admin can allocate cash.'),
      h('div', { class: 'list-head' }, h('h2', {}, `${data.requests.length} waiting`)),
      data.requests.length
        ? h('ul', { class: 'card-group' }, data.requests.map((r) => requestRow(r, data, data.currency, showRequests)))
        : h('p', { class: 'empty-state' }, 'Nobody has asked for cash right now.')));
  }

  /* ---------- Allocated cash & balance: who's been given cash, and what's left ---------- */

  // `prefill` (worker_id, amount, request_id) comes from tapping a Cash requests row (kohal, 2026-10-21:
  // "clicking on that, it should open allocate form") - still just this same form, pre-filled rather than
  // blank, and request_id rides along so give() can close that request out as fulfilled.
  function openGiveSheet(data, onDone, prefill) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const workerSel = searchField(data.workers.map((w) => ({ value: w.id, label: w.name })), prefill?.worker_id ?? '', { placeholder: 'Choose an employee' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: prefill?.amount ?? '' });
    const modeSel = selectField([{ value: '', label: 'Account' }, ...data.payment_modes.map((m) => ({ value: m, label: m }))],
      '', { title: 'Account', placeholder: 'Account' });
    const noteInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Give cash');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    saveBtn.onclick = async () => {
      if (!workerSel.value) { errEl.textContent = 'Choose an employee'; return; }
      saveBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api(`/api/cash-purchases/${workerSel.value}/give`, {
          method: 'POST', body: {
            amount: amountInput.value, payment_mode: modeSel.value, note: noteInput.value,
            request_id: prefill?.request_id ?? null,
          },
        });
        finish();
        toast('Cash given');
        onDone();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        saveBtn.disabled = false;
      }
    };
    // Someone on the fooding wallet (a daily-wage worker) is paid out of that wallet, not an admin account
    // (kohal, 2026-11-02) - so for them the account box gives way to a line saying what is left there.
    const accountField = field('payment_mode', 'Account', modeSel);
    const walletNote = h('p', { class: 'hint' });
    const syncSource = () => {
      const w = data.workers.find((x) => String(x.id) === String(workerSel.value));
      const wallet = w && w.fooding_remaining != null;
      accountField.hidden = !!wallet;
      walletNote.hidden = !wallet;
      if (wallet) walletNote.textContent = `Paid from ${w.name}’s fooding balance · ${money(w.fooding_remaining, data.currency)} left. No bank account is debited.`;
    };
    // Optionally pay through an app (kohal, 2026-11-02) - not for someone paid out of their fooding balance, since no bank
    // account is debited then. It reads the employee and amount as they are when it opens the app.
    let pickedApp = '';
    const workerOf = () => data.workers.find((x) => String(x.id) === String(workerSel.value));
    const onWallet = () => { const w = workerOf(); return !!w && w.fooding_remaining != null; };
    const relabel = () => { saveBtn.textContent = pickedApp && !onWallet() ? 'Mark paid & give cash' : 'Give cash'; };
    const picker = LD.payAppPicker({
      name: () => (workerOf() ? workerOf().name : 'the employee'), amount: () => amountInput.value,
      payee: () => { const w = workerOf() || {}; return { upi_id: w.upi_id, phone: w.phone }; }, note: 'Cash', currency: data.currency,
      onChange: (app) => { pickedApp = app; relabel(); }, onError: (msg) => { errEl.textContent = msg; },
    });
    const payBox = h('div', {}, ...picker.nodes);
    const form = h('div', {}, field('worker_id', 'Employee', workerSel), field('amount', 'Amount', amountInput),
      accountField, walletNote, payBox, field('note', 'Note', noteInput));
    const syncAll = () => { syncSource(); payBox.hidden = onWallet(); picker.refresh(); relabel(); };
    form.addEventListener('change', syncAll);
    amountInput.addEventListener('input', () => picker.refresh());
    syncAll();
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Give cash'),
      form,
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
    workerSel.focus?.();
  }

  function balanceRow(a, cur) {
    return h('li', {}, h('a', { class: 'p-row', href: `#balances/person/${a.worker_id}` },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, a.worker_name),
        h('span', { class: 'row-sub' }, `Given ${money(a.given_total, cur)} · Spent ${money(a.spent_total, cur)}`)),
      h('span', { class: 'row-value' }, money(a.remaining, cur)),
      h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›')));
  }

  async function showBalances() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/cash-purchases/accounts'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(h('div', {},
      tabs('balances', data.pending_purchase_count, data.pending_request_count),
      h('div', { class: 'list-head' },
        h('h2', {}, `${data.accounts.length} ${data.accounts.length === 1 ? 'employee' : 'employees'}`),
        data.can_decide ? h('button', { class: 'btn small', type: 'button', onclick: () => openGiveSheet(data, showBalances) }, '+ Allocate cash') : null),
      data.accounts.length
        ? h('ul', { class: 'card-group' }, data.accounts.map((a) => balanceRow(a, data.currency)))
        : h('p', { class: 'empty-state' }, 'Nobody has been given cash yet - use + Allocate cash to start.')));
  }

  /* ---------- one employee's own cash-purchase history ---------- */

  const STATUS_LABEL = { pending: 'Pending', approved: 'Approved', rejected: 'Rejected' };
  const STATUS_CLASS = { pending: 'chip-today', approved: 'chip-active', rejected: 'chip-off' };

  function historyRow(e, cur) {
    const sub = [fmtDate(e.entry_date), e.quantity != null ? `${e.quantity} ${e.unit || ''}`.trim() : null,
      e.supplier || null, e.created_by_name ? `Logged by ${e.created_by_name}` : null,
      e.approved_by_name ? `${e.status === 'approved' ? 'Approved' : 'Rejected'} by ${e.approved_by_name}` : null,
      e.note || null].filter(Boolean).join(' · ');
    return h('li', { class: 'p-row' },
      h('span', { class: `chip ${STATUS_CLASS[e.status]}` }, STATUS_LABEL[e.status]),
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, e.material_name),
        h('span', { class: 'row-sub' }, sub),
        e.bill_url ? h('a', { href: e.bill_url, target: '_blank', rel: 'noopener noreferrer', class: 'link-btn' }, 'View bill') : null),
      h('span', { class: 'row-value' }, money(e.amount, cur)));
  }

  // One "admin gave this employee cash" entry - always applied straight away, so no approve/reject status.
  function topupRow(t, cur) {
    return h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, 'Cash given'),
        h('span', { class: 'row-sub' }, [fmtDate(t.entry_date), t.payment_mode, t.created_by_name ? `Given by ${t.created_by_name}` : null, t.note || null]
          .filter(Boolean).join(' \u00b7 '))),
      h('span', { class: 'row-value acct-credit' }, `+${money(t.amount, cur)}`));
  }

  async function showPersonHistory(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/cash-purchases/${id}`); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    LD.setAppbarBack?.('Allocated cash & balance', '#balances');
    const cur = data.currency;
    const a = data.account;
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'att-head' }, h('h2', {}, data.worker.name), h('span', { class: 'att-head-date' }, 'Cash account')),
      a ? h('p', { class: 'wk-legend' }, `Given ${money(a.given_total, cur)} · Spent ${money(a.spent_total, cur)} · Remaining ${money(a.remaining, cur)}`) : null,
      h('section', { class: 'p-section' },
        h('h3', {}, 'Cash given'),
        data.topups.length
          ? h('ul', { class: 'card-group' }, data.topups.map((t) => topupRow(t, cur)))
          : h('p', { class: 'hint' }, 'No cash given yet.')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Cash purchases'),
        data.entries.length
          ? h('ul', { class: 'card-group' }, data.entries.map((e) => historyRow(e, cur)))
          : h('p', { class: 'hint' }, 'Nothing logged yet.'))));
  }

  function route() {
    const hash = window.location.hash;
    let m = /^#balances\/person\/(\d+)$/.exec(hash);
    if (m) return showPersonHistory(Number(m[1]));
    if (hash === '#balances') return showBalances();
    if (hash === '#requests') return showRequests();
    return showApprovals();
  }

  window.addEventListener('hashchange', route);
  route();
})();
