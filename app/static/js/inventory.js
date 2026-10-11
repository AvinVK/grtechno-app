/* Inventory (admin only): materials bought in bulk, their stock and average cost, and the ledger of
   stock-in (purchases/receipts) and issue (used on a project) entries that move them - see app/inventory.py
   for how stock_qty/avg_rate are kept in step with that ledger, server side. This file never computes a
   balance itself; it only shows what the server already worked out. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, confirm, plural, money, field, showFieldErrors, selectField, dateField } = window.LD;

  const view = $('#view');
  const todayIso = () => new Date().toISOString().slice(0, 10);

  // The chevron only makes sense once you're a level deeper than the list - Inventory's own bottom tab
  // already gets you back to the list itself, same as Clients/Projects, so it stays hidden there and
  // only appears on a material, or a form, same as setAppbarBack repoints it below.
  const backLink = $('#appbar-back');
  const showBack = (visible) => { if (backLink) backLink.hidden = !visible; };

  /* ---------- list: every material, its stock and what it's worth ---------- */

  async function showList() {
    showBack(false);
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
          h('span', { class: 'row-sub' }, `${m.stock_qty} ${m.unit || ''}`.trim(), ' in stock')),
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
    return h('span', { class: 'bill-links' },
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
      }, 'Remove'));
  }

  function movementRow(materialId, mv, currency, onChanged) {
    const isIn = mv.kind === 'in';
    const seller = isIn ? [mv.seller_name, mv.seller_contact].filter(Boolean).join(' · ') : '';
    return h('li', { class: 'p-row' },
      h('span', { class: `chip ${isIn ? 'chip-active' : 'chip-off'}` }, isIn ? '+ Stock in' : '− Issued'),
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, `${mv.quantity} ${isIn ? 'at ' + money(mv.rate, currency) : ''}`.trim()),
        h('span', { class: 'row-sub' }, [fmtDate(mv.entry_date), mv.project_title ? `${mv.project_code} · ${mv.project_title}` : null, seller || null, mv.note || null, mv.created_by_name ? `by ${mv.created_by_name}` : null].filter(Boolean).join(' · ')),
        isIn ? billControl(materialId, mv, onChanged) : null),
      h('span', { class: 'row-value' }, money(mv.amount, currency)));
  }

  async function showDetail(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading material…'));
    let data;
    try { data = await api(`/api/inventory/materials/${id}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back to inventory'))); return; }
    const m = data.material;
    showBack(true);
    LD.setAppbarBack?.('Inventory', '#');

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' },
        h('h2', {}, m.name, !m.is_active ? h('span', { class: 'chip chip-off' }, ' Archived') : null),
        h('a', { class: 'btn small', href: `#m${m.id}/edit` }, 'Edit')),
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
          ? h('ul', { class: 'card-group' }, data.movements.map((mv) => movementRow(m.id, mv, data.currency, () => showDetail(id))))
          : h('p', { class: 'hint' }, 'No stock-in or issue entries yet.'))));
  }

  /* ---------- add / edit a material ---------- */

  function materialForm(material) {
    const M = material || { name: '', unit: '', notes: '' };
    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const controls = {
      name: text('text', M.name, { maxlength: 120, autocomplete: 'off' }),
      unit: text('text', M.unit, { maxlength: 20, autocomplete: 'off', placeholder: 'bags, kg, pcs, mtr…' }),
      notes: (() => { const t = h('textarea', { rows: 3 }); t.value = M.notes ?? ''; return t; })(),
    };

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, material ? 'Save material' : 'Add material');
    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = {};
        for (const [name, el] of Object.entries(controls)) body[name] = el.value;
        try {
          const saved = material
            ? await api(`/api/inventory/materials/${material.id}`, { method: 'PATCH', body })
            : await api('/api/inventory/materials', { method: 'POST', body });
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
        field('notes', 'Notes', controls.notes, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn));

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, material ? 'Edit material' : 'Add material')),
      form));
  }

  async function showNew() {
    showBack(true);
    LD.setAppbarBack?.('Inventory', '#');
    materialForm(null);
  }

  async function showEdit(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    try {
      const data = await api(`/api/inventory/materials/${id}`);
      showBack(true);
      LD.setAppbarBack?.(data.material.name, `#m${id}`);
      materialForm(data.material);
    } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); }
  }

  /* ---------- stock in / issue ---------- */

  function movementForm(material, kind, projects, currency) {
    const isIn = kind === 'in';
    const qty = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: `Quantity (${material.unit || 'units'})` });
    const rate = isIn ? h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'Cost per unit' }) : null;
    const sellerName = isIn ? h('input', { type: 'text', maxlength: 120, autocomplete: 'off' }) : null;
    const sellerContact = isIn ? h('input', { type: 'tel', maxlength: 40, autocomplete: 'off' }) : null;
    const project = !isIn ? selectField(projects.map((p) => ({ value: p.id, label: `${p.code} · ${p.title}` })), '', { title: 'Project', placeholder: 'Choose a project' }) : null;
    const date = dateField(todayIso(), { placeholder: 'Date' });
    const note = h('input', { type: 'text', maxlength: 200, autocomplete: 'off' });

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, isIn ? 'Add stock' : 'Issue material');
    const fields = { quantity: qty, entry_date: date, note };
    if (isIn) Object.assign(fields, { rate, seller_name: sellerName, seller_contact: sellerContact });
    if (!isIn) fields.project_id = project;

    const form = h('form', { novalidate: true, class: 'project-form',
      onsubmit: async (e) => {
        e.preventDefault();
        errorBox.hidden = true;
        showFieldErrors(form, {});
        saveBtn.disabled = true;
        const body = { quantity: qty.value, entry_date: date.value, note: note.value };
        if (isIn) Object.assign(body, { rate: rate.value, seller_name: sellerName.value, seller_contact: sellerContact.value });
        else body.project_id = project.value ? Number(project.value) : null;
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
        isIn ? field('rate', 'Cost per unit', rate) : field('project_id', 'Project', project),
        isIn ? field('seller_name', 'Seller name', sellerName) : null,
        isIn ? field('seller_contact', 'Seller contact', sellerContact) : null,
        field('entry_date', 'Date', date),
        field('note', 'Note', note, { wide: true })),
      h('div', { class: 'form-actions' }, saveBtn),
      isIn ? h('p', { class: 'hint' }, "You can attach the bill afterwards, from the material's history, once you have it to hand.") : null);

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' },
        h('h2', {}, isIn ? `Stock in · ${material.name}` : `Issue · ${material.name}`),
        h('p', { class: 'hint' }, `Currently ${material.stock_qty} ${material.unit || ''} in stock`.trim())),
      form));
  }

  async function showMovement(id, kind) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/inventory/materials/${id}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    showBack(true);
    LD.setAppbarBack?.(data.material.name, `#m${id}`);
    movementForm(data.material, kind, data.projects, data.currency);
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
