/* Inventory (admin only): materials bought in bulk, their stock and average cost, and the ledger of
   stock-in (purchases/receipts) and issue (used on a project) entries that move them - see app/inventory.py
   for how stock_qty/avg_rate are kept in step with that ledger, server side. This file never computes a
   balance itself; it only shows what the server already worked out. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, plural, money, field, showFieldErrors, selectField, dateField, closeOnBack } = window.LD;

  const view = $('#view');
  const todayIso = () => new Date().toISOString().slice(0, 10);

  // The chevron only makes sense once you're a level deeper than the list - Inventory's own bottom tab
  // already gets you back to the list itself, same as Clients/Projects, so it stays hidden there and
  // only appears on a material, or a form, same as setAppbarBack repoints it below.
  const backLink = $('#appbar-back');
  const showBack = (visible) => { if (backLink) backLink.hidden = !visible; };

  // "+ Material" opens the same add-material form this button already sits on top of, so it's hidden
  // there (and restored everywhere else) - same idea as showBack above, just for the other appbar link.
  const addLink = $('.appbar-primary');
  const showAddLink = (visible) => { if (addLink) addLink.hidden = !visible; };

  /* ---------- list: every material, its stock and what it's worth ---------- */

  async function showList() {
    showBack(false);
    showAddLink(true);
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading inventory…'));
    let data;
    try { data = await api('/api/inventory/materials'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const search = h('input', { type: 'search', placeholder: 'Search materials', 'aria-label': 'Search materials' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const results = h('ul', { class: 'card-group' });

    function materialRow(m) {
      return h('li', {}, h('a', { class: 'p-row', href: `#m${m.id}` },
        h('span', { class: 'p-tile', 'data-status': m.is_active ? 'running' : 'planned', 'aria-hidden': 'true' }, (m.name[0] || '?').toUpperCase()),
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, m.name, !m.is_active ? h('span', { class: 'chip chip-off' }, 'Archived') : null),
          h('span', { class: 'row-sub' }, `${m.code} · ${m.stock_qty} ${m.unit || ''}`.trim(), ' in stock')),
        h('span', { class: 'row-value' }, money(m.stock_value, data.currency)),
        h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›')));
    }

    function refresh() {
      const q = search.value.trim().toLowerCase();
      const items = data.materials.filter((m) => !q || m.name.toLowerCase().includes(q));
      count.textContent = `${plural(items.length, 'material', 'materials')} · ${money(data.total_stock_value, data.currency)} in stock`;
      clear(results).append(...items.map(materialRow));
      if (!items.length) results.append(h('li', {}, h('p', { class: 'empty-state' }, data.materials.length
        ? 'No materials match this search.' : 'No materials yet. Add one to start tracking stock.')));
    }
    search.oninput = refresh;

    clear(view).append(h('div', {}, h('div', { class: 'filters' }, search), count, results));
    refresh();
  }

  /* ---------- one material: stock, cost, and its movement history ---------- */

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmtDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

  async function archiveMaterial(material, toActive) {
    const verb = toActive ? 'Restore' : 'Archive';
    const ok = await confirm(`${verb} ${material.name}?`, { ok: verb });
    if (!ok) return;
    try {
      await api(`/api/inventory/materials/${material.id}`, { method: 'PATCH', body: { is_active: toActive } });
      toast(toActive ? 'Material restored' : 'Material archived');
      showDetail(material.id);
    } catch (err) { toast(err.message, true); }
  }

  // The bill (a photo or PDF of the receipt) isn't always to hand when the stock-in itself is logged, so
  // it's attached here, after the fact, from the material's own history - not part of the stock-in form.
  function billControl(materialId, mv, onChanged) {
    if (!mv.bill_url) {
      const fileInput = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp,application/pdf', hidden: true });
      fileInput.onchange = async () => {
        if (!fileInput.files.length) return;
        const body = new FormData();
        body.append('bill', fileInput.files[0]);
        try {
          const res = await fetch(`/api/inventory/materials/${materialId}/movements/${mv.id}/bill`, { method: 'POST', body, credentials: 'same-origin' });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || 'Could not upload the bill');
          toast('Bill added');
          onChanged();
        } catch (err) { toast(err.message, true); }
      };
      return h('label', { class: 'link-btn' }, 'Add bill', fileInput);
    }
    // Siblings, not wrapped in their own .bill-links span - movementRow puts the whole action row
    // (bill controls plus Edit/Delete) in one shared one below.
    return [
      h('a', { href: mv.bill_url, target: '_blank', rel: 'noopener noreferrer', class: 'link-btn' }, 'View bill'),
      h('button', {
        type: 'button', class: 'link-btn', onclick: async () => {
          const ok = await confirm('Remove this bill?', { ok: 'Remove', danger: true });
          if (!ok) return;
          try {
            await api(`/api/inventory/materials/${materialId}/movements/${mv.id}/bill`, { method: 'DELETE' });
            toast('Bill removed');
            onChanged();
          } catch (err) { toast(err.message, true); }
        },
      }, 'Remove'),
    ];
  }

  // A bulk-entry mistake can be on any field, not just quantity - this edits everything the entry was
  // ever saved with, same fields as its own add form (see movementForm below), just pre-filled and PATCHed
  // instead of POSTed. `data` is the material detail response (suppliers/workers/projects/currency) it was
  // loaded alongside.
  function editMovementSheet(materialId, mv, data, onSaved) {
    const isIn = mv.kind === 'in';
    const { currency } = data;
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const qty = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: mv.quantity });
    const rate = isIn ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: mv.rate }) : null;
    const supplierSel = isIn ? supplierPicker(data.suppliers.map((s) => ({ value: s.id, label: s.name })), mv.supplier_id ?? '') : null;
    const billNo = isIn ? h('input', { type: 'text', maxlength: 60, autocomplete: 'off', value: mv.bill_no || '' }) : null;
    const paymentMode = isIn ? selectField(PAYMENT_MODES, mv.payment_mode || 'cash', { title: 'Credit or cash', placeholder: 'Choose one' }) : null;
    const gstPercent = isIn ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: mv.gst_percent }) : null;
    const gstAmount = isIn ? h('input', { type: 'text', disabled: true, value: money(mv.gst_amount, currency) }) : null;
    const totalCost = isIn ? h('input', { type: 'text', disabled: true, value: money(mv.total_cost, currency) }) : null;
    // A project that's since been completed drops out of the "current projects" list this picker is
    // normally offered - keep this entry's own project selectable regardless, same as a lead's "previously
    // picked" enquired-by.
    const projectOptions = !isIn ? data.projects.map((p) => ({ value: p.id, label: `${p.code} · ${p.title}` })) : [];
    if (!isIn && mv.project_id && !projectOptions.some((o) => o.value === mv.project_id)) {
      projectOptions.push({ value: mv.project_id, label: mv.project_title ? `${mv.project_code} · ${mv.project_title}` : 'Previously picked' });
    }
    const project = !isIn ? selectField(projectOptions, mv.project_id ?? '', { title: 'Project', placeholder: 'Choose a project' }) : null;
    const givenBy = !isIn ? selectField(data.workers.map((w) => ({ value: w.id, label: w.name })), mv.given_by_worker_id ?? '', { title: 'Given by', placeholder: 'Who gave it out' }) : null;
    const date = dateField(mv.entry_date, { placeholder: 'Date' });
    const note = h('input', { type: 'text', maxlength: 200, autocomplete: 'off', value: mv.note || '' });

    if (isIn) {
      const recalc = () => {
        const q = Number(qty.value) || 0;
        const r = Number(rate.value) || 0;
        const g = Number(gstPercent.value) || 0;
        const amount = q * r;
        const gst = amount * g / 100;
        gstAmount.value = money(gst, currency);
        totalCost.value = money(amount + gst, currency);
      };
      [qty, rate, gstPercent].forEach((el) => el.addEventListener('input', recalc));
    }

    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Save');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      errEl.textContent = '';
      if (isIn && supplierSel.newSupplierName) {
        try {
          const created = await api('/api/inventory/suppliers', { method: 'POST', body: { name: supplierSel.newSupplierName } });
          data.suppliers.push(created.supplier);
          supplierSel.setOptions(data.suppliers.map((s) => ({ value: s.id, label: s.name })));
          supplierSel.value = created.supplier.id;
        } catch (err) {
          errEl.textContent = (err.fields && err.fields.name) || err.message;
          saveBtn.disabled = false;
          return;
        }
      }
      const body = { quantity: qty.value, entry_date: date.value, note: note.value };
      if (isIn) Object.assign(body, {
        rate: rate.value, supplier_id: supplierSel.value || null, bill_no: billNo.value,
        payment_mode: paymentMode.value, gst_percent: gstPercent.value || '0',
      });
      else Object.assign(body, { project_id: project.value ? Number(project.value) : null, given_by_worker_id: givenBy.value ? Number(givenBy.value) : null });
      try {
        await api(`/api/inventory/materials/${materialId}/movements/${mv.id}`, { method: 'PATCH', body });
        finish();
        toast('Entry updated');
        onSaved();
      } catch (err) {
        errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, isIn ? 'Edit stock in' : 'Edit issue'),
      field('quantity', 'Quantity', qty),
      isIn ? field('rate', 'Purchase cost', rate) : field('project_id', 'Project', project),
      isIn ? field('supplier_id', 'Supplier name', supplierSel) : field('given_by_worker_id', 'Given by', givenBy),
      isIn ? field('bill_no', 'Bill no', billNo) : null,
      isIn ? field('payment_mode', 'Credit or cash', paymentMode) : null,
      isIn ? field('gst_percent', 'GST %', gstPercent) : null,
      isIn ? field('gst_amount', 'GST amt', gstAmount) : null,
      isIn ? field('total_cost', 'Total cost', totalCost) : null,
      field('entry_date', 'Date', date),
      field('note', 'Remarks', note),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
    qty.focus();
  }

  async function deleteMovement(materialId, mv, onChanged) {
    const ok = await confirm(`Delete this ${mv.kind === 'in' ? 'stock-in' : 'issue'} entry? Stock and average cost will be recalculated.`, { ok: 'Delete', danger: true });
    if (!ok) return;
    try {
      await api(`/api/inventory/materials/${materialId}/movements/${mv.id}`, { method: 'DELETE' });
      toast('Entry deleted');
      onChanged();
    } catch (err) { toast(err.message, true); }
  }

  function movementRow(materialId, mv, data, onChanged) {
    const isIn = mv.kind === 'in';
    const { currency } = data;
    const extra = isIn
      ? [mv.supplier_name, mv.bill_no ? `Bill ${mv.bill_no}` : null, mv.payment_mode ? (mv.payment_mode === 'credit' ? 'Credit' : 'Cash') : null]
      : [mv.given_by_name ? `Given by ${mv.given_by_name}` : null];
    return h('li', { class: 'p-row' },
      h('span', { class: `chip ${isIn ? 'chip-active' : 'chip-off'}` }, isIn ? '+ Stock in' : '− Issued'),
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, `${mv.quantity} ${isIn ? 'at ' + money(mv.rate, currency) : ''}`.trim()),
        h('span', { class: 'row-sub' }, [fmtDate(mv.entry_date), mv.project_title ? `${mv.project_code} · ${mv.project_title}` : null, ...extra, mv.note || null, mv.created_by_name ? `by ${mv.created_by_name}` : null].filter(Boolean).join(' · ')),
        h('span', { class: 'bill-links' },
          isIn ? billControl(materialId, mv, onChanged) : null,
          h('button', { type: 'button', class: 'link-btn', onclick: () => editMovementSheet(materialId, mv, data, onChanged) }, 'Edit'),
          h('button', { type: 'button', class: 'link-btn', onclick: () => deleteMovement(materialId, mv, onChanged) }, 'Delete'))),
      h('span', { class: 'row-value' }, money(isIn ? mv.total_cost : mv.amount, currency)));
  }

  async function showDetail(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading material…'));
    let data;
    try { data = await api(`/api/inventory/materials/${id}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to inventory'))); return; }
    const m = data.material;
    showBack(true);
    showAddLink(true);
    LD.setAppbarBack?.('Inventory', '#');

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' },
        h('h2', {}, m.name, !m.is_active ? h('span', { class: 'chip chip-off' }, ' Archived') : null),
        h('a', { class: 'btn small', href: `#m${m.id}/edit` }, 'Edit')),
      h('p', { class: 'hint' }, m.code),
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Stock on hand'),
          h('span', { class: 'stat-value is-text' }, `${m.stock_qty} ${m.unit || ''}`.trim())),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Average cost'),
          h('span', { class: 'stat-value is-text' }, money(m.avg_rate, data.currency))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Stock value'),
          h('span', { class: 'stat-value is-text' }, money(m.stock_value, data.currency)))),
      h('div', { class: 'form-actions' },
        h('a', { class: 'btn primary', href: `#m${m.id}/stock-in` }, '+ Stock in'),
        h('a', { class: 'btn', href: `#m${m.id}/issue` }, 'Issue to project'),
        h('button', { class: `btn small ${m.is_active ? 'danger' : ''}`, type: 'button', onclick: () => archiveMaterial(m, !m.is_active) }, m.is_active ? 'Archive' : 'Restore')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'History'),
        data.movements.length
          ? h('ul', { class: 'card-group' }, data.movements.map((mv) => movementRow(m.id, mv, data, () => showDetail(id))))
          : h('p', { class: 'hint' }, 'No stock-in or issue entries yet.'))));
  }

  /* ---------- add / edit a material ---------- */

  // `data` (suppliers + currency, from GET /api/inventory/materials) is only needed while adding - editing
  // a material that may already have its own stock-in history doesn't touch any of this; use Stock in for
  // a later purchase instead.
  function materialForm(material, data) {
    const isAdd = !material;
    const M = material || { name: '', unit: '', notes: '' };
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const controls = {
      name: text('text', M.name, { maxlength: 120, autocomplete: 'off' }),
      unit: text('text', M.unit, { maxlength: 20, autocomplete: 'off', placeholder: 'bags, kg, pcs, mtr…' }),
      notes: (() => { const t = h('textarea', { rows: 3 }); t.value = M.notes ?? ''; return t; })(),
    };

    // Supply detail - on Add, this material's first purchase (optional, leave quantity blank to add it
    // with no stock yet). On Edit, the same fields reopen for its one stock-in, when it has exactly one
    // and nothing else has happened since (the overwhelmingly common case right after a bulk entry) - once
    // there's more than one movement, which one "is" the material's purchase is ambiguous, so this stays
    // material-only fields and the entries themselves are edited from History below instead.
    const movements = (data && data.movements) || [];
    const soleMovement = !isAdd && movements.length === 1 && movements[0].kind === 'in' ? movements[0] : null;
    const showSupply = isAdd || !!soleMovement;
    const SM = soleMovement || {};
    const currency = data ? data.currency : '';
    const qty = showSupply ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'Quantity', value: SM.quantity ?? '' }) : null;
    const rate = showSupply ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'Cost per unit', value: SM.rate ?? '' }) : null;
    const supplierSel = showSupply ? supplierPicker((data.suppliers || []).map((s) => ({ value: s.id, label: s.name })), SM.supplier_id ?? '') : null;
    const billNo = showSupply ? h('input', { type: 'text', maxlength: 60, autocomplete: 'off', value: SM.bill_no || '' }) : null;
    const paymentMode = showSupply ? selectField(PAYMENT_MODES, SM.payment_mode || 'cash', { title: 'Credit or cash', placeholder: 'Choose one' }) : null;
    const gstPercent = showSupply ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '0', value: SM.gst_percent ?? '' }) : null;
    const gstAmount = showSupply ? h('input', { type: 'text', disabled: true, value: money(SM.gst_amount || 0, currency) }) : null;
    const totalCost = showSupply ? h('input', { type: 'text', disabled: true, value: money(SM.total_cost || 0, currency) }) : null;
    const remarks = showSupply ? h('input', { type: 'text', maxlength: 200, autocomplete: 'off', value: SM.note || '' }) : null;

    if (showSupply) {
      const recalc = () => {
        const q = Number(qty.value) || 0;
        const r = Number(rate.value) || 0;
        const g = Number(gstPercent.value) || 0;
        const amount = q * r;
        const gst = amount * g / 100;
        gstAmount.value = money(gst, currency);
        totalCost.value = money(amount + gst, currency);
      };
      [qty, rate, gstPercent].forEach((el) => el.addEventListener('input', recalc));
      recalc();
    }

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, material ? 'Save material' : 'Add material');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        if (showSupply && supplierSel.newSupplierName) {
          try {
            const created = await api('/api/inventory/suppliers', { method: 'POST', body: { name: supplierSel.newSupplierName } });
            data.suppliers.push(created.supplier);
            supplierSel.setOptions(data.suppliers.map((s) => ({ value: s.id, label: s.name })));
            supplierSel.value = created.supplier.id;
          } catch (err) {
            errorBox.textContent = (err.fields && err.fields.name) || err.message;
            errorBox.hidden = false;
            saveBtn.disabled = false;
            return;
          }
        }
        const supplyBody = showSupply ? {
          quantity: qty.value, rate: rate.value, supplier_id: supplierSel.value || null, bill_no: billNo.value,
          payment_mode: paymentMode.value, gst_percent: gstPercent.value || '0', note: remarks.value,
        } : null;
        const body = {};
        for (const [name, el] of Object.entries(controls)) body[name] = el.value;
        // Add material: the material and its optional first purchase are created together, in one call.
        // Edit material: the material's own fields PATCH separately from its sole movement (a different
        // row, its own endpoint) - the entry_date isn't shown here, so it's carried over unchanged.
        if (isAdd && supplyBody) Object.assign(body, supplyBody);
        try {
          const saved = material
            ? await api(`/api/inventory/materials/${material.id}`, { method: 'PATCH', body })
            : await api('/api/inventory/materials', { method: 'POST', body });
          if (!isAdd && soleMovement) {
            await api(`/api/inventory/materials/${material.id}/movements/${soleMovement.id}`,
              { method: 'PATCH', body: { ...supplyBody, entry_date: soleMovement.entry_date } });
          }
          toast(material ? 'Material saved' : 'Material added');
          window.location.hash = `#m${saved.material.id}`;
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('div', { class: 'form-grid' },
        field('name', 'Material name', controls.name, { wide: true }),
        field('unit', 'Unit', controls.unit),
        field('notes', 'Notes', controls.notes, { wide: true }),
        showSupply ? field('quantity', 'Quantity', qty) : null,
        showSupply ? field('rate', 'Purchase cost', rate) : null,
        showSupply ? field('supplier_id', 'Supplier name', supplierSel) : null,
        showSupply ? field('bill_no', 'Bill no', billNo) : null,
        showSupply ? field('payment_mode', 'Credit or cash', paymentMode) : null,
        showSupply ? field('gst_percent', 'GST %', gstPercent) : null,
        showSupply ? field('gst_amount', 'GST amt', gstAmount) : null,
        showSupply ? field('total_cost', 'Total cost', totalCost) : null,
        showSupply ? field('note', 'Remarks', remarks, { wide: true }) : null),
      h('div', { class: 'form-actions' }, saveBtn),
      isAdd ? h('p', { class: 'hint' }, 'Leave quantity blank to add the material with no stock yet - you can stock it in later.') : null,
      !isAdd && !showSupply && movements.length
        ? h('p', { class: 'hint' }, 'This material has more than one stock-in or issue entry, so edit those individually from its history.')
        : null);

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, material ? 'Edit material' : 'Add material')),
      form));
  }

  async function showNew() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/inventory/materials'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    showBack(true);
    showAddLink(false);            // already on the form it opens - nothing for it to do here
    LD.setAppbarBack?.('Inventory', '#');
    materialForm(null, data);
  }

  async function showEdit(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    try {
      const data = await api(`/api/inventory/materials/${id}`);
      showBack(true);
      showAddLink(true);
      LD.setAppbarBack?.(data.material.name, `#m${id}`);
      materialForm(data.material, data);
    } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); }
  }

  /* ---------- stock in / issue ---------- */

  // A supplier picker: the list, plus "+ Add a new supplier…" - same shape as LD.rolePicker (see
  // common.js), just id/name instead of key/name, since nothing else needs to refer to a supplier by a
  // stable string key. `.value` is the chosen supplier's id, or '' while a new one is only typed, not
  // created yet; `.newSupplierName` is that typed name (trimmed). The stock-in form below POSTs
  // /api/inventory/suppliers with it, gets the new id back, and sets `.value` to that before saving.
  function supplierPicker(items, value, opts = {}) {
    const NEW = '__new_supplier__';
    let list = items.map((i) => (typeof i === 'object' ? i : { value: i, label: i }));
    const withExtras = () => [{ value: '', label: 'Not set' }, ...list, { value: NEW, label: '+ Add a new supplier…' }];
    const sel = selectField(withExtras(), value || '', { title: opts.title || 'Supplier', placeholder: 'Choose a supplier' });
    const typed = h('input', { type: 'text', maxlength: 160, autocomplete: 'off', placeholder: 'Name of the new supplier', hidden: true });
    typed.setAttribute('aria-label', 'New supplier name');
    const wrap = h('div', { class: 'category-picker' }, sel, typed);
    sel.addEventListener('change', () => {
      typed.hidden = sel.value !== NEW;
      if (!typed.hidden) typed.focus();
    });
    Object.defineProperty(wrap, 'value', {
      get: () => (sel.value === NEW ? '' : sel.value),
      set: (v) => { sel.value = v || ''; typed.hidden = true; },
      configurable: true,
    });
    Object.defineProperty(wrap, 'newSupplierName', {
      get: () => (sel.value === NEW ? typed.value.trim() : ''),
      configurable: true,
    });
    wrap.setOptions = (newItems) => { list = newItems.map((i) => (typeof i === 'object' ? i : { value: i, label: i })); sel.setOptions(withExtras()); };
    return wrap;
  }

  const PAYMENT_MODES = [{ value: 'cash', label: 'Cash' }, { value: 'credit', label: 'Credit' }];

  function movementForm(material, kind, data) {
    const isIn = kind === 'in';
    const { currency } = data;
    const qty = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: `Quantity (${material.unit || 'units'})` });
    const rate = isIn ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'Cost per unit' }) : null;
    const supplierSel = isIn ? supplierPicker(data.suppliers.map((s) => ({ value: s.id, label: s.name })), '') : null;
    const billNo = isIn ? h('input', { type: 'text', maxlength: 60, autocomplete: 'off' }) : null;
    const paymentMode = isIn ? selectField(PAYMENT_MODES, 'cash', { title: 'Credit or cash', placeholder: 'Choose one' }) : null;
    const gstPercent = isIn ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '0' }) : null;
    const gstAmount = isIn ? h('input', { type: 'text', disabled: true, value: money(0, currency) }) : null;
    const totalCost = isIn ? h('input', { type: 'text', disabled: true, value: money(0, currency) }) : null;
    const project = !isIn ? selectField(data.projects.map((p) => ({ value: p.id, label: `${p.code} · ${p.title}` })), '', { title: 'Project', placeholder: 'Choose a project' }) : null;
    const givenBy = !isIn ? selectField(data.workers.map((w) => ({ value: w.id, label: w.name })), '', { title: 'Given by', placeholder: 'Who gave it out' }) : null;
    const date = dateField(todayIso(), { placeholder: 'Date' });
    const note = h('input', { type: 'text', maxlength: 200, autocomplete: 'off' });

    if (isIn) {
      const recalc = () => {
        const q = Number(qty.value) || 0;
        const r = Number(rate.value) || 0;
        const g = Number(gstPercent.value) || 0;
        const amount = q * r;
        const gst = amount * g / 100;
        gstAmount.value = money(gst, currency);
        totalCost.value = money(amount + gst, currency);
      };
      [qty, rate, gstPercent].forEach((el) => el.addEventListener('input', recalc));
      recalc();
    }

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isIn ? 'Add stock' : 'Issue material');

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        if (isIn && supplierSel.newSupplierName) {
          try {
            const created = await api('/api/inventory/suppliers', { method: 'POST', body: { name: supplierSel.newSupplierName } });
            data.suppliers.push(created.supplier);
            supplierSel.setOptions(data.suppliers.map((s) => ({ value: s.id, label: s.name })));
            supplierSel.value = created.supplier.id;
          } catch (err) {
            errorBox.textContent = (err.fields && err.fields.name) || err.message;
            errorBox.hidden = false;
            saveBtn.disabled = false;
            return;
          }
        }
        const body = { quantity: qty.value, entry_date: date.value, note: note.value };
        if (isIn) Object.assign(body, {
          rate: rate.value, supplier_id: supplierSel.value || null, bill_no: billNo.value,
          payment_mode: paymentMode.value, gst_percent: gstPercent.value || '0',
        });
        else Object.assign(body, { project_id: project.value ? Number(project.value) : null, given_by_worker_id: givenBy.value ? Number(givenBy.value) : null });
        try {
          await api(`/api/inventory/materials/${material.id}/${isIn ? 'stock-in' : 'issue'}`, { method: 'POST', body });
          toast(isIn ? 'Stock added' : 'Material issued');
          window.location.hash = `#m${material.id}`;
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          (showFieldErrors(form, err.fields) || errorBox).focus?.();
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('div', { class: 'form-grid' },
        field('quantity', 'Quantity', qty),
        isIn ? field('rate', 'Purchase cost', rate) : field('project_id', 'Project', project),
        isIn ? field('supplier_id', 'Supplier name', supplierSel) : field('given_by_worker_id', 'Given by', givenBy),
        isIn ? field('bill_no', 'Bill no', billNo) : null,
        isIn ? field('payment_mode', 'Credit or cash', paymentMode) : null,
        isIn ? field('gst_percent', 'GST %', gstPercent) : null,
        isIn ? field('gst_amount', 'GST amt', gstAmount) : null,
        isIn ? field('total_cost', 'Total cost', totalCost) : null,
        field('entry_date', 'Date', date),
        field('note', 'Remarks', note, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn),
      isIn ? h('p', { class: 'hint' }, "You can attach the bill afterwards, from the material's history, once you have it to hand.") : null);

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' },
        h('h2', {}, isIn ? `Stock in · ${material.name}` : `Issue · ${material.name}`),
        h('p', { class: 'hint' }, `${material.code} · Currently ${material.stock_qty} ${material.unit || ''} in stock`.trim())),
      form));
  }

  async function showMovement(id, kind) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/inventory/materials/${id}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    showBack(true);
    showAddLink(true);
    LD.setAppbarBack?.(data.material.name, `#m${id}`);
    movementForm(data.material, kind, data);
  }

  function route() {
    const hash = window.location.hash;
    if (hash === '#new') return showNew();
    let m = /^#m(\d+)\/edit$/.exec(hash);
    if (m) return showEdit(Number(m[1]));
    m = /^#m(\d+)\/stock-in$/.exec(hash);
    if (m) return showMovement(Number(m[1]), 'in');
    m = /^#m(\d+)\/issue$/.exec(hash);
    if (m) return showMovement(Number(m[1]), 'out');
    m = /^#m(\d+)$/.exec(hash);
    if (m) return showDetail(Number(m[1]));
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
