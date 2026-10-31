/* Adhoc projects' items and order form (kohal, 2026-10-30, moved to Projects 2026-10-31) - see app/adhoc.py. Used
   by the Projects page (the new-order form, and an adhoc project's Overview and Edit items):
   - Refilling of FE: FE type, weight, qty, rate, refilling date, HPT date, expiry date, remark.
   - Supply of FE and Retail sale: FE type or fire material, weight / spec, qty, rate.
   "Add more" adds another item; the total of qty x rate is the project's value. */
window.ADHOC = (() => {
  'use strict';

  const { h, clear, api, toast, money, dateField, field, selectField, showFieldErrors } = window.LD;

  const LABELS = {
    refilling: { type: 'FE type', weight: 'Weight' },
    supply: { type: 'FE type or fire material', weight: 'Weight / spec' },
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
  function itemsEditor(kind, initial, currency) {
    const lab = LABELS[kind];
    const list = h('div', { class: 'adhoc-items' });
    const total = h('p', { class: 'adhoc-total' });
    const listErr = h('p', { class: 'err', role: 'alert' });
    const rows = [];

    function recompute() {
      const sum = rows.reduce((n, r) => n + (Number(r.c.qty.control.value) || 0) * (Number(r.c.rate.control.value) || 0), 0);
      total.textContent = `Total ${money(sum, currency)}`;
    }

    function renumber() {
      rows.forEach((r, i) => {
        r.title.textContent = `Item ${i + 1}`;
        r.remove.hidden = rows.length < 2;
      });
    }

    function addRow(v = {}) {
      const c = {
        fe_type: box(lab.type, h('input', { type: 'text', value: v.fe_type || '', maxlength: 120, autocomplete: 'off' })),
        weight: box(lab.weight, h('input', { type: 'text', value: v.weight || '', maxlength: 60, autocomplete: 'off' })),
        qty: box('Qty', h('input', { type: 'number', min: '1', step: '1', inputmode: 'numeric', value: v.qty ?? '' })),
        rate: box('Rate', h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', value: v.rate ?? '' })),
      };
      if (kind === 'refilling') {
        c.refill_date = box('Refilling date', dateField(v.refill_date || ''));
        c.hpt_date = box('HPT date', dateField(v.hpt_date || ''));
        c.expiry_date = box('Expiry date', dateField(v.expiry_date || ''));
        const remark = h('textarea', { rows: 2, maxlength: 400 });
        remark.value = v.remark || '';
        c.remark = box('Remark', remark, false);
      }
      const title = h('strong', {}, 'Item');
      const remove = h('button', { class: 'btn small', type: 'button' }, 'Remove');
      const row = { c, title, remove };
      const grid = h('div', { class: 'form-grid' },
        ...Object.entries(c).map(([key, b]) => {
          if (key === 'remark') b.node.classList.add('wide');
          if (key === 'fe_type') b.node.classList.add('wide');
          return b.node;
        }));
      row.node = h('section', { class: 'adhoc-item card' }, h('div', { class: 'adhoc-item-head' }, title, remove), grid);
      remove.onclick = () => {
        rows.splice(rows.indexOf(row), 1);
        row.node.remove();
        renumber();
        recompute();
      };
      row.node.addEventListener('input', recompute);
      rows.push(row);
      list.append(row.node);
      renumber();
      recompute();
    }

    (initial && initial.length ? initial : [{}]).forEach(addRow);
    const addBtn = h('button', { class: 'btn', type: 'button', onclick: () => addRow() }, '+ Add more');

    return {
      node: h('div', { class: 'adhoc-editor' }, list, listErr, h('div', { class: 'adhoc-add' }, addBtn, total)),
      getItems: () => rows.map((r) => {
        const out = {};
        Object.entries(r.c).forEach(([key, b]) => { out[key] = b.control.value; });
        return out;
      }),
      showErrors(fields) {
        rows.forEach((r) => Object.values(r.c).forEach((b) => { b.err.textContent = ''; }));
        listErr.textContent = '';
        let first = null;
        for (const [name, message] of Object.entries(fields || {})) {
          if (name === 'items') { listErr.textContent = message; first = first || listErr; continue; }
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
        h('span', { class: 'row-sub' }, `${i.qty} × ${money(i.rate, currency)}`),
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
      editor = itemsEditor(state.service, state.draftItems || [], cur);
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
        saveBtn.disabled = true;
        const body = { service: state.service, items: editor ? editor.getItems() : [] };
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
          const plain = Object.fromEntries(Object.entries(err.fields || {}).filter(([k]) => !k.startsWith('items')));
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
      h('p', { class: 'hint' }, 'Stage 1 of 4 \u00b7 Fill details'),
      restored ? h('p', { class: 'hint' }, 'What you had typed has been put back. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => { clearDraft(); showOrder(view, opts); } }, 'Start over')) : null,
      form));
    window.scrollTo(0, 0);
  }

  return { itemsEditor, itemsList, showOrder, KIND_LABEL };
})();
