/* Adhoc projects' items and order form (kohal, 2026-10-30, moved to Projects 2026-10-31) - see app/adhoc.py. Used
   by the Projects page (the new-order form, and an adhoc project's Overview and Edit items):
   - Refilling of FE: FE type, weight, qty, rate, refilling date, HPT date, expiry date, remark.
   - Supply of FE and Retail sale: FE type or fire material, weight / spec, qty, rate.
   "Add more" adds another item; the total of qty x rate is the project's value. */
window.ADHOC = (() => {
  'use strict';

  const { h, clear, api, toast, money, dateField, field, selectField, searchField, showFieldErrors } = window.LD;

  const LABELS = {
    refilling: { type: 'FE type', weight: 'Weight' },
    supply: { type: 'FE type or fire material' },
  };
  const KIND_LABEL = { refilling: 'Refilling of FE', supply: 'Supply of FE and Retail sale' };

  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  };

  // Every box but the remark is mandatory (kohal, 2026-10-30), marked with the same red asterisk as the other forms.
  function box(label, control, required = true) {
    const err = h('p', { class: 'err', role: 'alert' });
    const mark = required ? h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *') : null;
    return { node: h('div', { class: 'field' }, h('label', {}, label, mark), control, err), err, control };
  }

  /* The editable list. `initial` is the items to start with (an adhoc project's, when editing); a new order
     starts with one empty item. Returns { node, getItems(), showErrors(fields) }. */
  // `stock` is inventory's item list: a supplied item is picked from it, with a search (kohal, 2026-10-31: "the FE
  // is already 4kg or 6kg in stock name in inventory, so just give a dropdown and search option from inventory").
  // `gstRates` are the GST slabs to choose from; `charges` the order's installation / transportation charges.
  function itemsEditor(kind, initial, currency, stock = [], gstRates = [0, 5, 12, 18, 28], charges = {}, locked = []) {
    const lab = LABELS[kind];
    const list = h('div', { class: 'adhoc-items' });
    const total = h('p', { class: 'adhoc-total' });
    const listErr = h('p', { class: 'err', role: 'alert' });
    const rows = [];
    const num = (el) => Number(el.value) || 0;
    const chargeBoxes = {
      installation_charge: box('Installation charges', h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', value: charges.installation || '' }), false),
      transport_charge: box('Transportation charges', h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', value: charges.transport || '' }), false),
    };
    const lineTotal = (r) => {
      const base = num(r.c.qty.control) * num(r.c.rate.control);
      return base + Math.round(base * num(r.c.gst_percent.control)) / 100;
    };

    function recompute() {
      rows.forEach((r) => { r.sum.textContent = `Item total ${money(lineTotal(r), currency)}`; });
      const sum = rows.reduce((n, r) => n + lineTotal(r), 0)
        + num(chargeBoxes.installation_charge.control) + num(chargeBoxes.transport_charge.control);
      total.textContent = `Total ${money(sum, currency)}`;
    }

    function renumber() {
      rows.forEach((r, i) => {
        r.title.textContent = `Item ${i + 1}`;
        r.remove.hidden = rows.length < 2 || !!r.locked;
      });
    }

    function addRow(v = {}) {
      const picked = kind === 'supply' ? stock.find((m) => m.name.trim().toLowerCase() === (v.fe_type || '').trim().toLowerCase()) : null;
      const c = {
        fe_type: kind === 'supply'
          ? box(lab.type, searchField(stock.map((m) => ({ value: m.id, label: `${m.name} (${m.stock_qty} ${m.unit || ''} in stock)`.trim() })),
            picked ? picked.id : '', { placeholder: 'Search inventory\u2026' }))
          : box(lab.type, h('input', { type: 'text', value: v.fe_type || '', maxlength: 120, autocomplete: 'off' })),
        ...(kind === 'refilling' ? { weight: box(lab.weight, h('input', { type: 'text', value: v.weight || '', maxlength: 60, autocomplete: 'off' })) } : {}),
        qty: box('Qty', h('input', { type: 'number', min: '1', step: '1', inputmode: 'numeric', value: v.qty ?? '' })),
        rate: box('Selling price', h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', value: v.rate ?? '' })),
        gst_percent: box('GST %', selectField(gstRates.map((r) => ({ value: String(r), label: `${r}%` })),
          String(v.gst_percent ?? (v.fe_type ? 0 : 18)), { title: 'GST %', placeholder: 'Choose GST' })),
      };
      if (kind === 'refilling') {
        c.refill_date = box('Refilling date', dateField(v.refill_date || ''));
        c.hpt_date = box('HPT date', dateField(v.hpt_date || ''));
        c.expiry_date = box('Expiry date', dateField(v.expiry_date || ''));
        const remark = h('textarea', { rows: 2, maxlength: 400 });
        remark.value = v.remark || '';
        c.remark = box('Remark', remark, false);
      }
      // Live hint under the item's name (kohal, 2026-11-14): something like it is already in inventory.
      const nameControl = c.fe_type.control;
      c.fe_type.node.append(LD.similarMaterialHint(nameControl, kind === 'supply'
        ? { isPicked: () => !!nameControl.value, onUse: (m) => { nameControl.value = String(m.id); } }
        : { isPicked: () => false, onUse: (m) => { nameControl.value = m.name; } }));
      const title = h('strong', {}, 'Item');
      const remove = h('button', { class: 'btn small', type: 'button' }, 'Remove');
      const sum = h('p', { class: 'adhoc-total' });
      const row = { c, title, remove, sum };
      const grid = h('div', { class: 'form-grid' },
        ...Object.entries(c).map(([key, b]) => {
          // Qty and Selling price sit side by side (kohal, 2026-10-31); every other box takes the full width.
          if (key !== 'qty' && key !== 'rate') b.node.classList.add('wide');
          return b.node;
        }));
      row.node = h('section', { class: 'adhoc-item card' }, h('div', { class: 'adhoc-item-head' }, title, remove), grid, sum);
      remove.onclick = () => {
        rows.splice(rows.indexOf(row), 1);
        row.node.remove();
        renumber();
        recompute();
      };
      row.node.addEventListener('input', recompute);
      row.node.addEventListener('change', recompute);
      // An item whose material has been requested is locked: nothing in it can change, and it can't be removed.
      if (locked.includes((v.fe_type || '').trim().toLowerCase())) {
        row.node.querySelectorAll('input, select, textarea, button').forEach((el) => { el.disabled = true; });
        row.node.querySelectorAll('.name-suggest, .select-field, [role=combobox]').forEach((el) => el.setAttribute('aria-disabled', 'true'));
        title.after(h('span', { class: 'chip chip-off' }, 'Requested · locked'));
        row.locked = true;
      }
      rows.push(row);
      list.append(row.node);
      renumber();
      recompute();
    }

    (initial && initial.length ? initial : [{}]).forEach(addRow);
    const addBtn = h('button', { class: 'btn', type: 'button', onclick: () => addRow() }, '+ Add more items');

    return {
      node: h('div', { class: 'adhoc-editor' }, list, listErr, h('div', { class: 'adhoc-add' }, addBtn),
        h('div', { class: 'adhoc-charges' },
          h('h3', {}, 'Other charges'),
          h('div', { class: 'form-grid', onchange: recompute, oninput: recompute }, chargeBoxes.installation_charge.node, chargeBoxes.transport_charge.node)),
        h('div', { class: 'adhoc-add' }, total)),
      // Before saving: an item typed in that is not in inventory but looks like something that is - use that one, or keep what was typed. False when
      // the person backs out.
      async resolveSimilar() {
        for (const r of rows) {
          if (r.locked) continue;
          const ctl = r.c.fe_type.control;
          const picked = kind === 'supply' ? stock.find((s) => String(s.id) === String(ctl.value)) : null;
          const typed = (picked ? picked.name : (kind === 'supply' ? ctl.querySelector('input').value : ctl.value)).trim();
          if (picked || typed.length < 3 || stock.some((s) => s.name.trim().toLowerCase() === typed.toLowerCase())) continue;
          const choice = await LD.checkSimilarMaterial(typed, { newLabel: `Keep \u201c${typed}\u201d as typed` });
          if (!choice) return false;
          if (choice.use) ctl.value = kind === 'supply' ? String(choice.use.id) : choice.use.name;
        }
        return true;
      },
      getItems: () => rows.map((r) => {
        const out = {};
        Object.entries(r.c).forEach(([key, b]) => { out[key] = b.control.value; });
        if (kind === 'supply') {
          // The inventory pick is held as an id; what is saved is the item's name (what is typed, if nothing was picked).
          const m = stock.find((s) => String(s.id) === String(r.c.fe_type.control.value));
          out.fe_type = m ? m.name : r.c.fe_type.control.querySelector('input').value;
        }
        return out;
      }),
      getCharges: () => ({
        installation_charge: chargeBoxes.installation_charge.control.value,
        transport_charge: chargeBoxes.transport_charge.control.value,
      }),
      showErrors(fields) {
        rows.forEach((r) => Object.values(r.c).forEach((b) => { b.err.textContent = ''; }));
        Object.values(chargeBoxes).forEach((b) => { b.err.textContent = ''; });
        listErr.textContent = '';
        let first = null;
        for (const [name, message] of Object.entries(fields || {})) {
          if (name === 'items') { listErr.textContent = message; first = first || listErr; continue; }
          if (chargeBoxes[name]) { chargeBoxes[name].err.textContent = message; first = first || chargeBoxes[name].node; continue; }
          const m = /^items\.(\d+)\.(\w+)$/.exec(name);
          if (!m || !rows[Number(m[1])] || !rows[Number(m[1])].c[m[2]]) continue;
          const b = rows[Number(m[1])].c[m[2]];
          b.err.textContent = message;
          first = first || b.node;
        }
        return first;
      },
    };
  }

  /* A read-only list of an adhoc project's items, for its Overview. */
  function itemsList(items, kind, currency) {
    if (!items.length) return h('p', { class: 'hint' }, 'No items yet.');
    return h('ul', { class: 'card-group adhoc-list' }, items.map((i) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, [i.fe_type, i.weight].filter(Boolean).join(' · ')),
        h('span', { class: 'row-sub' }, `${i.qty} × ${money(i.rate, currency)}${i.gst_percent ? ` + ${i.gst_percent}% GST` : ''}`),
        kind === 'refilling' && (i.refill_date || i.hpt_date || i.expiry_date)
          ? h('span', { class: 'row-sub' }, [i.refill_date ? `Refilled ${fmtDate(i.refill_date)}` : null, i.hpt_date ? `HPT ${fmtDate(i.hpt_date)}` : null,
            i.expiry_date ? `Expires ${fmtDate(i.expiry_date)}` : null].filter(Boolean).join(' · ')) : null,
        i.remark ? h('span', { class: 'row-sub' }, i.remark) : null),
      h('span', { class: 'row-value' }, money(i.amount, currency)))));
  }

  /* ---------- the order form: Projects > + Project > Adhoc project ---------- */

  /* A new adhoc order (kohal, 2026-10-31: "this adhoc thing wont be a client, it will be adhoc project but it will
     have client details. same form but in add projects"): the customer (new, or an earlier one picked by contact
     number), the service, and the items. Saving makes the project - Unbilled - and asks inventory for the items.
     `opts.kindChips()` is the Normal/Adhoc switch shown at the top; `opts.onSaved(projectId)` takes over after. */
  async function showOrder(view, opts) {
    window.LD.setAppbarBack?.('Projects', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading\u2026'));
    let data;
    try { data = await api('/api/adhoc/clients'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    const req = (text) => [text, h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *')];

    const state = { who: 'new', service: '' };
    const text = (type, extra = {}) => h('input', { type, value: '', ...extra });
    const nameIn = text('text', { maxlength: 160, autocomplete: 'off' });
    const addressIn = h('textarea', { rows: 2, maxlength: 400 });
    const phoneIn = text('tel', { maxlength: 40, autocomplete: 'off', inputmode: 'numeric' });
    const existingSel = selectField(
      data.clients.map((c) => ({ value: String(c.id), label: `${c.name} \u00b7 ${c.phone}` })),
      '', { title: 'Choose an earlier customer', placeholder: 'Choose a customer' });

    // A refresh must not wipe a half-filled order (kohal, 2026-10-30: "refresh should not clear the form"), so
    // what has been typed is kept as a draft in the browser and put back when the form opens again; it is
    // cleared when the order is saved or the person chooses Start over.
    const DRAFT_KEY = 'adhoc-order-draft';
    const readDraft = () => { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { return null; } };
    const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* storage unavailable - nothing to clear */ } };
    const saved = readDraft();
    const restored = !!(saved && (saved.name || saved.address || saved.phone || saved.service
      || (saved.items || []).some((i) => Object.values(i).some(Boolean))));
    if (restored) {
      state.who = saved.who === 'existing' ? 'existing' : state.who;
      state.service = data.services.some((x) => x.key === saved.service) ? saved.service : '';
      state.draftItems = saved.items || [];
      state.draftCharges = { installation: saved.charges && saved.charges.installation_charge, transport: saved.charges && saved.charges.transport_charge };
      nameIn.value = saved.name || '';
      addressIn.value = saved.address || '';
      phoneIn.value = saved.phone || '';
      if (saved.existingId && data.clients.some((c) => String(c.id) === String(saved.existingId))) existingSel.value = String(saved.existingId);
    }

    const whoBox = h('div', {});
    const serviceBox = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Service' });
    const itemsBox = h('div', {});
    let editor = null;
    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Save and continue');
    const whoTabs = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'New or earlier customer' });

    function renderWho() {
      clear(whoTabs);
      [['new', 'New customer'], ['existing', 'Earlier customer']].forEach(([key, label]) => whoTabs.append(h('button', {
        class: 'filter-chip', type: 'button', 'aria-pressed': String(state.who === key),
        onclick: () => { state.who = key; renderWho(); },
      }, label)));
      clear(whoBox).append(state.who === 'new'
        ? h('div', { class: 'form-grid' },
          field('name', req('Client name'), nameIn, { wide: true }),
          field('address', req('Address'), addressIn, { wide: true }),
          field('phone', req('Contact no'), phoneIn, { hint: 'Their 10-digit number. It is how this customer is found next time.' }))
        : h('div', { class: 'form-grid' },
          field('client_id', req('Customer'), existingSel, { wide: true,
            hint: data.clients.length ? null : 'There are no earlier adhoc customers yet - use New customer first.' })));
    }

    function renderService() {
      clear(serviceBox);
      data.services.forEach((s) => serviceBox.append(h('button', {
        class: 'filter-chip', type: 'button', 'aria-pressed': String(state.service === s.key),
        onclick: () => { state.service = s.key; renderService(); renderItems(); },
      }, s.label)));
    }

    function renderItems() {
      clear(itemsBox);
      editor = null;
      if (!state.service) { itemsBox.append(h('p', { class: 'hint' }, 'Choose what this order is for.')); return; }
      editor = itemsEditor(state.service, state.draftItems || [], cur, data.materials, data.gst_rates, state.draftCharges || {});
      state.draftCharges = null;
      state.draftItems = null;
      itemsBox.append(h('h3', {}, state.service === 'refilling' ? 'Items to refill' : 'Items supplied'), editor.node,
        h('p', { class: 'hint' }, 'Next: request the material, then the payment details, then mark it billed. It stays Unbilled until then.'));
    }

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        editor?.showErrors({});
        if (editor && !(await editor.resolveSimilar())) return;        // an item that looks like one in stock - asked about before it is saved
        saveBtn.disabled = true;
        const body = { service: state.service, items: editor ? editor.getItems() : [], ...(editor ? editor.getCharges() : {}) };
        if (state.who === 'existing') body.client_id = existingSel.value;
        else Object.assign(body, { name: nameIn.value, address: addressIn.value, phone: phoneIn.value });
        try {
          const res = await api('/api/adhoc/orders', { method: 'POST', body });
          clearDraft();
          toast('Details saved');
          opts.onSaved(res.project_id);
        } catch (err) {
          errorBox.textContent = err.message;
          errorBox.hidden = false;
          // The items' errors ('items.0.qty'...) belong to the editor's own boxes; the plain form fields go through
          // showFieldErrors (which looks them up by id, and an id with dots in it isn't a valid selector).
          const plain = Object.fromEntries(Object.entries(err.fields || {}).filter(([k]) => !k.startsWith('items') && !k.endsWith('_charge')));
          const first = showFieldErrors(form, plain);
          const firstItem = editor ? editor.showErrors(err.fields) : null;
          (first || firstItem || errorBox).scrollIntoView?.({ block: 'center' });
          saveBtn.disabled = false;
        }
      } },
      errorBox,
      h('section', { class: 'p-section' }, h('h3', {}, 'Client details'), whoTabs, whoBox),
      h('section', { class: 'p-section' }, h('h3', {}, 'Service'), serviceBox, h('p', { class: 'err', id: 'err-service', role: 'alert' })),
      h('section', { class: 'p-section' }, itemsBox),
      h('div', { class: 'form-actions' }, saveBtn));

    function saveDraft() {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({
          who: state.who, service: state.service, name: nameIn.value, address: addressIn.value,
          phone: phoneIn.value, existingId: existingSel.value, items: editor ? editor.getItems() : [],
          charges: editor ? editor.getCharges() : {},
        }));
      } catch (e) { /* storage full or blocked - the form still works, it just won't survive a refresh */ }
    }
    // After every edit, and after every click (chips, Add more, Remove) once its own handler has run.
    ['input', 'change'].forEach((type) => form.addEventListener(type, saveDraft));
    form.addEventListener('click', () => setTimeout(saveDraft, 0));

    renderWho();
    renderService();
    renderItems();
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, 'Add project')),
      opts.kindChips(),
      h('p', { class: 'hint' }, 'Stage 1 of 3 \u00b7 Fill details and request material'),
      restored ? h('p', { class: 'hint' }, 'What you had typed has been put back. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => { clearDraft(); showOrder(view, opts); } }, 'Start over')) : null,
      form));
    window.scrollTo(0, 0);
  }

  return { itemsEditor, itemsList, showOrder, KIND_LABEL };
})();
