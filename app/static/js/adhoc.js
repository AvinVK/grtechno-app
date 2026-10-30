/* Adhoc clients' items (kohal, 2026-10-30) - see app/adhoc.py. Shared by the Clients page (the new-order form)
   and the Projects page (an adhoc project's Overview and its Edit items), so both show the same boxes:
   - Refilling of FE: FE type, weight, qty, rate, refilling date, HPT date, expiry date, remark.
   - Supply of FE and Retail sale: FE type or fire material, weight / spec, qty, rate.
   "Add more" adds another item; the total of qty x rate is the project's value. */
window.ADHOC = (() => {
  'use strict';

  const { h, clear, money, dateField } = window.LD;

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

  return { itemsEditor, itemsList, KIND_LABEL };
})();
