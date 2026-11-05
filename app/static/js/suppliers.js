/* Suppliers: what is owed to each supplier on credit stock-ins (kohal, 2026-11-04) - a list of suppliers with
   what is still owed, and tapping one lists the purchases behind it and the payments made. The admin can Make
   payment from there: the supplier's name and contact come in filled, the amount and account are chosen, and
   with UPI as the mode the same PhonePe / Google Pay step as every other payout (LD.payAppPicker). The admin can also add
   a supplier with its details and a starting balance (what was owed in the ledger kept before this app) and edit them
   later - one form for both (openSupplierSheet). See
   app/inventory.py's supplier_credit_list / supplier_credit_detail / pay_supplier. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, money, field, selectField, dateField, showFieldErrors, closeOnBack, payAppPicker, setAppbarBack, resetAppbarBack } = window.LD;
  const view = $('#view');

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmtDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };
  const todayIso = () => new Date().toLocaleDateString('en-CA');
  const stat = (label, value) => h('div', { class: 'client-stats' },
    h('div', { class: 'stat' }, h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value is-text' }, value)));

  // One form for adding a supplier and for editing one (kohal, 2026-11-05): who they are, how to pay them, and the starting
  // balance carried over from the ledger kept before this app. `existing` is a supplier's detail response, or null to add.
  function openSupplierSheet(existing, onDone) {
    const e = existing || {};
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const text = (value, extra = {}) => h('input', { type: 'text', autocomplete: 'off', value: value || '', ...extra });
    const name = text(e.name, { maxlength: 160 });
    const contact = text(e.contact_person, { maxlength: 120 });
    const phone = text(e.phone, { inputmode: 'tel', maxlength: 40 });
    const email = text(e.email, { inputmode: 'email', maxlength: 160 });
    const gstin = text(e.gstin, { maxlength: 20 });
    const address = h('textarea', { rows: 3, maxlength: 400 });
    address.value = e.address || '';
    const upi = text(e.upi_id, { maxlength: 80, placeholder: 'name@bank' });
    const starting = text(e.starting ? String(e.starting) : '', { inputmode: 'decimal' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, existing ? 'Save details' : 'Add supplier');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (ev) => { if (ev.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    const form = h('form', { novalidate: true, class: 'amount-sheet-form',
      onsubmit: async (ev) => {
        ev.preventDefault();
        errEl.textContent = '';
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = { name: name.value, contact_person: contact.value, phone: phone.value, email: email.value, gstin: gstin.value,
          address: address.value, upi_id: upi.value.trim(), opening_balance: starting.value };
        try {
          const res = existing
            ? await api(`/api/inventory/suppliers/${existing.id}`, { method: 'PATCH', body })
            : await api('/api/inventory/suppliers', { method: 'POST', body });
          toast(existing ? 'Details saved' : 'Supplier added');
          finish();
          onDone(existing ? existing.id : res.supplier.id);
        } catch (err) {
          errEl.textContent = err.fields ? '' : err.message;
          (showFieldErrors(form, err.fields) || errEl).focus?.();
          saveBtn.disabled = false;
        }
      } },
      field('name', 'Supplier name', name, { wide: true }),
      field('opening_balance', 'Starting balance', starting, { wide: true, hint: 'What was already owed to this supplier in your earlier ledger. Leave blank if nothing.' }),
      field('contact_person', 'Contact person', contact, { wide: true }),
      field('phone', 'Contact number', phone, { wide: true }),
      field('email', 'Email', email, { wide: true }),
      field('gstin', 'GST number', gstin, { wide: true }),
      field('address', 'Address', address, { wide: true }),
      field('upi_id', 'UPI ID', upi, { wide: true }),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn));
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': existing ? 'Edit supplier' : 'Add supplier' },
      h('h2', {}, existing ? 'Edit supplier' : 'Add supplier'), form));
    document.body.append(overlay);
  }

  async function showList() {
    resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/inventory/suppliers/credit'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    clear(view).append(h('div', { class: 'project-detail' },
      data.can_edit ? h('div', { class: 'supplier-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => openSupplierSheet(null, (newId) => setTimeout(() => { window.location.hash = `#s${newId}`; }, 250)) }, '+ Supplier')) : null,
      stat('Total credit owed to suppliers', money(data.total, cur)),
      h('section', { class: 'p-section' },
        data.suppliers.length
          ? h('ul', { class: 'card-group' }, data.suppliers.map((s) => h('li', {},
              h('a', { class: 'p-row', href: `#s${s.id}` },
                h('span', { class: 'p-main' },
                  h('span', { class: 'row-title' }, s.name),
                  h('span', { class: 'row-sub' }, [s.purchases ? `${s.purchases} credit purchase${s.purchases === 1 ? '' : 's'}` : 'No credit purchases', s.starting ? `starting ${money(s.starting, cur)}` : null].filter(Boolean).join(' · '))),
                h('span', { class: 'row-value' }, money(s.credit, cur))))))
          : h('p', { class: 'hint' }, 'No suppliers yet - they are added when you stock in material on credit.'))));
  }

  // The payment form: name (fixed) and contact come in filled; the amount, account and mode are the admin's to pick.
  // With UPI chosen the PhonePe / Google Pay step appears, reading the contact and UPI ID as they are typed.
  function openPaySheet(id, data, onDone) {
    const cur = data.currency;
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const nameInput = h('input', { type: 'text', value: data.name, readonly: true });
    const phoneInput = h('input', { type: 'text', inputmode: 'tel', maxlength: 40, autocomplete: 'off', value: data.phone, placeholder: 'Contact number' });
    const upiInput = h('input', { type: 'text', maxlength: 80, autocomplete: 'off', value: data.upi_id, placeholder: 'name@bank' });
    const amountInput = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: `Up to ${money(data.credit, cur)}` });
    const accountSel = selectField(data.payment_accounts.map((a) => ({ value: a, label: a })), '', { title: 'Paid from', placeholder: 'Choose an account' });
    const modeSel = selectField(data.pay_modes.map((m) => ({ value: m, label: m })), '', { title: 'Mode of payment', placeholder: 'Choose a mode' });
    const dateInput = dateField(todayIso());
    const noteInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save payment');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();

    let pickedApp = '';
    const picker = payAppPicker({
      name: data.name, amount: () => amountInput.value, payee: () => ({ upi_id: upiInput.value.trim(), phone: phoneInput.value.trim() }),
      note: 'Supplier payment', currency: cur,
      missing: `No UPI ID or contact number for ${data.name} yet - fill one in above.`,
      onChange: (app) => { pickedApp = app; saveBtn.textContent = app ? 'Mark paid & save' : 'Save payment'; },
      onError: (msg) => { errEl.textContent = msg; },
    });
    const payBox = h('div', {}, ...picker.nodes);
    const syncMode = () => { payBox.hidden = modeSel.value !== 'UPI'; if (modeSel.value !== 'UPI') pickedApp = ''; picker.refresh(); };
    modeSel.addEventListener('change', syncMode);
    [amountInput, phoneInput, upiInput].forEach((el) => el.addEventListener('input', () => picker.refresh()));
    syncMode();

    const form = h('form', { novalidate: true, class: 'amount-sheet-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errEl.textContent = '';
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        try {
          await api(`/api/inventory/suppliers/${id}/payments`, { method: 'POST', body: {
            amount: amountInput.value, payment_account: accountSel.value, mode: modeSel.value, phone: phoneInput.value,
            upi_id: upiInput.value.trim(), entry_date: dateInput.value, note: noteInput.value,
          } });
          toast('Payment saved');
          finish();
          onDone();
        } catch (err) {
          errEl.textContent = err.fields ? '' : err.message;
          (showFieldErrors(form, err.fields) || errEl).focus?.();
          saveBtn.disabled = false;
        }
      } },
      field('supplier_name', 'Supplier', nameInput, { wide: true }),
      field('phone', 'Contact', phoneInput, { wide: true }),
      field('upi_id', 'UPI ID', upiInput, { wide: true }),
      field('amount', 'Amount', amountInput, { wide: true }),
      field('payment_account', 'Paid from', accountSel, { wide: true }),
      field('mode', 'Mode of payment', modeSel, { wide: true }),
      payBox,
      field('entry_date', 'Date', dateInput, { wide: true }),
      field('note', 'Note', noteInput, { wide: true }),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn));
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Make payment' },
      h('h2', {}, 'Make payment'), form));
    document.body.append(overlay);
  }

  // Who the supplier is - only the lines that are filled in.
  function detailsCard(data) {
    const lines = [['Contact person', data.contact_person], ['Contact number', data.phone], ['Email', data.email], ['GST number', data.gstin],
      ['UPI ID', data.upi_id], ['Address', data.address]].filter(([, v]) => v);
    if (!lines.length) return data.can_edit ? h('p', { class: 'hint' }, 'No details saved yet - use Edit details to add contact, address and UPI ID.') : null;
    return h('div', { class: 'card supplier-details' }, lines.map(([k, v]) => h('p', { class: 'supplier-line' }, h('span', { class: 'hint' }, `${k}: `), v)));
  }

  async function deleteSupplier(id, data) {
    const sure = await confirm(`Delete ${data.name}? It is removed from the supplier list for good.`, { ok: 'Delete', danger: true, title: 'Delete supplier' });
    if (!sure) return;
    try {
      await api(`/api/inventory/suppliers/${id}`, { method: 'DELETE' });
      toast('Supplier deleted');
      window.location.hash = '';
    } catch (err) { toast(err.message, true); }
  }

  async function showSupplier(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/inventory/suppliers/${id}/credit`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    setAppbarBack?.('Suppliers', '#');
    const cur = data.currency;
    clear(view).append(h('div', { class: 'project-detail' },
      data.can_pay ? h('div', { class: 'supplier-actions' },
        h('button', { class: 'btn small primary', type: 'button', disabled: data.credit <= 0, onclick: () => openPaySheet(id, data, () => showSupplier(id)) }, 'Make payment'),
        data.can_edit ? h('button', { class: 'btn small', type: 'button', onclick: () => openSupplierSheet({ ...data, id }, () => showSupplier(id)) }, 'Edit details') : null) : null,
      h('div', { class: 'p-head' }, h('h2', {}, data.name)),
      detailsCard(data),
      stat('Credit owed', money(data.credit, cur)),
      data.paid || data.starting ? h('p', { class: 'hint' }, [data.starting ? `Starting balance ${money(data.starting, cur)}` : null,
        `Bought ${money(data.bought, cur)} on credit`, data.paid ? `Paid ${money(data.paid, cur)}` : null].filter(Boolean).join(' · ')) : null,
      data.payments.length ? h('section', { class: 'p-section' },
        h('h3', {}, 'Payments made'),
        h('ul', { class: 'card-group' }, data.payments.map((p) => h('li', { class: 'p-row' },
          h('span', { class: 'p-main' },
            h('span', { class: 'row-title' }, `${p.mode} · ${p.payment_account}`),
            h('span', { class: 'row-sub' }, [fmtDate(p.entry_date), p.note || null].filter(Boolean).join(' · '))),
          h('span', { class: 'row-value' }, money(p.amount, cur)))))) : null,
      h('section', { class: 'p-section' },
        h('h3', {}, 'Credit purchases'),
        data.entries.length
          ? h('ul', { class: 'card-group' }, data.entries.map((e) => h('li', { class: 'p-row' },
              h('span', { class: 'p-main' },
                h('span', { class: 'row-title' }, e.material_name),
                h('span', { class: 'row-sub' }, [fmtDate(e.entry_date), `${e.quantity} ${e.unit || ''}`.trim(), e.bill_no ? `Bill ${e.bill_no}` : null, e.note || null].filter(Boolean).join(' · '))),
              h('span', { class: 'row-value' }, money(e.total_cost, cur)))))
          : h('p', { class: 'hint' }, 'Nothing on credit with this supplier.')),
      data.can_delete ? h('div', { class: 'supplier-actions' },
        h('button', { class: 'btn small', type: 'button', onclick: () => deleteSupplier(id, data) }, 'Delete supplier'))
        : (data.can_pay ? h('p', { class: 'hint' }, 'A supplier with purchases, payments or a starting balance on record cannot be deleted.') : null)));
  }

  function route() {
    const m = /^#s(\d+)$/.exec(window.location.hash);
    return m ? showSupplier(Number(m[1])) : showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
