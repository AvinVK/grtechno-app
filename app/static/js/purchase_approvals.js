/* Purchase approval (kohal, 2026-10-21: "this pending approval should have its own block next to fooding.
   named as purchase approval - this is only visisble to admin. inside this there will be approvals and
   alocate cash (same as fooding types)"; then: "here there should be an subtab with aoption to assign
   money/cash to someone. and one subtab for apoorvals") - admin/accountant only, its own page off a Me-hub
   tile. Two subtabs, same pill shape as Inventory's own Materials/Material requests/Restock bar:
   - Approvals (default): every pending purchase, approve or reject it.
   - Allocate cash: hand an employee cash - applied immediately, same as Fooding's own allot.
   The employee's own balance and purchase log stays on the Me hub itself (see app/static/js/me.js) - this
   page is the management side only, see app/cash_purchases.py. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, field, selectField, searchField, showFieldErrors, money } = window.LD;
  const view = $('#view');

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  }

  function tabs(active) {
    return h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Purchase approval section' },
      h('a', { class: 'filter-chip', href: '#approvals', 'aria-current': active === 'approvals' ? 'page' : null }, 'Approvals'),
      h('a', { class: 'filter-chip', href: '#allocate', 'aria-current': active === 'allocate' ? 'page' : null }, 'Allocate cash'));
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

  async function showApprovals() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/cash-purchases/pending'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(h('div', {},
      tabs('approvals'),
      h('div', { class: 'list-head' }, h('h2', {}, `${data.pending.length} pending`)),
      data.pending.length
        ? h('ul', { class: 'card-group' }, data.pending.map((r) => row(r, data.currency)))
        : h('p', { class: 'empty-state' }, 'Nothing waiting on approval right now.')));
  }

  /* ---------- Allocate cash: hand an employee cash, applied immediately ---------- */

  async function showAllocate() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/cash-purchases/pending'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const workerSel = searchField(data.workers.map((w) => ({ value: w.id, label: w.name })), '', { placeholder: 'Choose an employee' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off' });
    const modeSel = selectField([{ value: '', label: 'Mode of payment' }, ...data.payment_modes.map((m) => ({ value: m, label: m }))],
      '', { title: 'How was it paid', placeholder: 'Mode of payment' });
    const noteInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off' });
    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Give cash');

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        if (!workerSel.value) {
          errorBox.textContent = 'Choose an employee';
          errorBox.hidden = false;
          return;
        }
        saveBtn.disabled = true;
        try {
          await api(`/api/cash-purchases/${workerSel.value}/give`, {
            method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value, note: noteInput.value },
          });
          toast('Cash given');
          workerSel.value = '';
          amountInput.value = '';
          modeSel.value = '';
          noteInput.value = '';
          workerSel.focus?.();
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
        } finally {
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      field('worker_id', 'Employee', workerSel, { wide: true }),
      field('amount', 'Amount', amountInput),
      field('payment_mode', 'Mode of payment', modeSel),
      field('note', 'Note', noteInput, { wide: true }),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', {}, tabs('allocate'), h('section', { class: 'p-section' }, form)));
    workerSel.focus?.();
  }

  function route() {
    if (window.location.hash === '#allocate') return showAllocate();
    return showApprovals();
  }

  window.addEventListener('hashchange', route);
  route();
})();
