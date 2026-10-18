/* Commission: a Project manager Chandrapur's own read-only view of what they've earned, project by
   project (kohal, 2026-10-18: "how does he check that?") - see app/commissions.py. Nothing here is
   editable - a commission entry is only ever created from a project's own Payment tab. */
(() => {
  'use strict';

  const { $, h, clear, api, money } = window.LD;
  const view = $('#view');

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmtDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

  async function load() {
    let data;
    try {
      data = await api('/api/commissions/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;
    const rows = data.commissions || [];
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Total commission earned'),
          h('span', { class: 'stat-value is-text' }, money(data.commission_total, cur)))),
      h('section', { class: 'p-section' },
        h('h3', {}, 'By project'),
        rows.length
          ? h('ul', { class: 'card-group' }, rows.map((c) => h('li', { class: 'p-row' },
              h('span', { class: 'p-main' },
                h('span', { class: 'row-title' }, c.project_title ? `${c.project_code} · ${c.project_title}` : 'Unknown project'),
                h('span', { class: 'row-sub' }, `${c.percent}% of ${money(c.basis_amount, cur)} · ${fmtDate(c.entry_date)}`)),
              h('span', { class: 'row-value' }, money(c.amount, cur)))))
          : h('p', { class: 'hint' }, 'No commission recorded yet.'))));
  }

  load();
})();
