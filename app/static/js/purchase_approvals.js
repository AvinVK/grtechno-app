/* Purchase approval (kohal, 2026-10-21: "this pending approval should have its own block next to fooding.
   named as purchase approval - this is only visisble to admin. inside this there will be approvals and
   alocate cash (same as fooding types)") - admin/accountant only, its own page off a Me-hub tile, same idea
   as Fooding's own management mode: hand an employee cash ("+ Give cash"), and approve or reject what they
   say they bought with it. The employee's own balance and purchase log stays on the Me hub itself (see
   app/static/js/me.js) - this page is the management side only, see app/cash_purchases.py. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, field, selectField, searchField, money, closeOnBack } = window.LD;
  const view = $('#view');

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  function openGiveSheet(data) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const workerSel = searchField(data.workers.map((w) => ({ value: w.id, label: w.name })), '', { placeholder: 'Choose an employee' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off' });
    const modeSel = selectField([{ value: '', label: 'Mode of payment' }, ...data.payment_modes.map((m) => ({ value: m, label: m }))],
      '', { title: 'How was it paid', placeholder: 'Mode of payment' });
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
          method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value, note: noteInput.value },
        });
        finish();
        toast('Cash given');
        load();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        saveBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Give cash'),
      field('worker_id', 'Employee', workerSel),
      field('amount', 'Amount', amountInput),
      field('payment_mode', 'Mode of payment', modeSel),
      field('note', 'Note', noteInput),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
    workerSel.focus?.();
  }

  async function act(r, action) {
    if (action === 'reject') {
      const sure = await confirm('Reject this purchase? Nothing was deducted from their balance yet, so there is nothing to undo.', { ok: 'Reject', danger: true, title: 'Reject purchase' });
      if (!sure) return;
    }
    try {
      await api(`/api/cash-purchases/${r.id}/${action}`, { method: 'POST' });
      toast(action === 'approve' ? 'Approved' : 'Rejected');
      load();
    } catch (err) { toast(err.message, true); }
  }

  function row(r, cur) {
    const sub = [fmtDate(r.entry_date), r.quantity != null ? `${r.quantity} ${r.unit || ''}`.trim() : null,
      r.supplier || null, r.created_by_name ? `Logged by ${r.created_by_name}` : null, r.note || null].filter(Boolean).join(' · ');
    return h('li', {}, h('div', { class: 'card me-row approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.worker_name} · ${r.material_name}`),
        h('span', { class: 'hint' }, `${money(r.amount, cur)} · ${sub}`),
        r.bill_url ? h('a', { href: r.bill_url, target: '_blank', rel: 'noopener noreferrer', class: 'link-btn' }, 'View bill') : null),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => act(r, 'approve') }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => act(r, 'reject') }, 'Reject'))));
  }

  async function load() {
    let data;
    try { data = await api('/api/cash-purchases/pending'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(h('div', {},
      h('div', { class: 'list-head' },
        h('h2', {}, `${data.pending.length} pending`),
        h('button', { class: 'btn small', type: 'button', onclick: () => openGiveSheet(data) }, '+ Give cash')),
      data.pending.length
        ? h('ul', { class: 'card-group' }, data.pending.map((r) => row(r, data.currency)))
        : h('p', { class: 'empty-state' }, 'Nothing waiting on approval right now.')));
  }

  load();
})();
