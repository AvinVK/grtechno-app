/* Suppliers: what is owed to each supplier on credit stock-ins (kohal, 2026-11-04) - a list of suppliers with
   their credit, and tapping one lists the purchases behind it. Read-only; see app/inventory.py's
   supplier_credit_list / supplier_credit_detail. */
(() => {
  'use strict';

  const { $, h, clear, api, money, setAppbarBack, resetAppbarBack } = window.LD;
  const view = $('#view');

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmtDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };
  const stat = (label, value) => h('div', { class: 'client-stats' },
    h('div', { class: 'stat' }, h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value is-text' }, value)));

  async function showList() {
    resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/inventory/suppliers/credit'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    clear(view).append(h('div', { class: 'project-detail' },
      stat('Total credit owed to suppliers', money(data.total, cur)),
      h('section', { class: 'p-section' },
        data.suppliers.length
          ? h('ul', { class: 'card-group' }, data.suppliers.map((s) => h('li', {},
              h('a', { class: 'p-row', href: `#s${s.id}` },
                h('span', { class: 'p-main' },
                  h('span', { class: 'row-title' }, s.name),
                  h('span', { class: 'row-sub' }, s.purchases ? `${s.purchases} credit purchase${s.purchases === 1 ? '' : 's'}` : 'No credit purchases')),
                h('span', { class: 'row-value' }, money(s.credit, cur))))))
          : h('p', { class: 'hint' }, 'No suppliers yet - they are added when you stock in material on credit.'))));
  }

  async function showSupplier(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/inventory/suppliers/${id}/credit`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    setAppbarBack?.('Suppliers', '#');
    const cur = data.currency;
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, data.name)),
      stat('Credit owed', money(data.credit, cur)),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Credit purchases'),
        data.entries.length
          ? h('ul', { class: 'card-group' }, data.entries.map((e) => h('li', { class: 'p-row' },
              h('span', { class: 'p-main' },
                h('span', { class: 'row-title' }, e.material_name),
                h('span', { class: 'row-sub' }, [fmtDate(e.entry_date), `${e.quantity} ${e.unit || ''}`.trim(), e.bill_no ? `Bill ${e.bill_no}` : null, e.note || null].filter(Boolean).join(' · '))),
              h('span', { class: 'row-value' }, money(e.total_cost, cur)))))
          : h('p', { class: 'hint' }, 'Nothing on credit with this supplier.'))));
  }

  function route() {
    const m = /^#s(\d+)$/.exec(window.location.hash);
    return m ? showSupplier(Number(m[1])) : showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
