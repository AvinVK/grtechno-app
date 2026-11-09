/* Salary slips (kohal, 2026-11-10: "in payroll sheet, have a Release salary button. once clicked, it should show the same payroll sheet to the
   employee the salary was released. also, have a vertical salary slip instead of horizontal when showing the slip to the employee. have
   them downloadable as well") - the signed-in employee's own released slips: a list, newest first, and each one as a vertical slip with a
   PDF download. The figures are the ones the admin released (app/slips.py), not recalculated. */
(() => {
  'use strict';

  const { $, h, clear, api, money } = window.LD;
  const view = $('#view');

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const longDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

  function shown(row, cur) {
    if (row.type === 'money') return money(row.value, cur);
    if (row.type === 'num') return String(Number.isInteger(row.value) ? row.value : Math.round(row.value * 10) / 10);
    return String(row.value);
  }

  async function showList() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/salary-slips'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    if (!data.slips.length) {
      clear(view).append(h('p', { class: 'empty-state' }, data.has_record
        ? 'No salary slip has been released to you yet. It appears here when the admin releases your salary.'
        : 'There is no employee record for you, so there are no salary slips.'));
      return;
    }
    clear(view).append(h('section', { class: 'att-week' },
      h('ul', { class: 'att-week-card' }, data.slips.map((s) => h('li', {},
        h('a', { class: 'att-day people-row', href: `#${s.id}` },
          h('div', { class: 'att-day-top' },
            h('span', { class: 'att-day-date' }, s.label),
            h('span', { class: 'att-day-hours' }, money(s.net, data.currency))),
          h('span', { class: 'att-day-sub' }, `${s.net_label} · released ${longDate(s.released_on)}`)))))));
  }

  async function showSlip(id) {
    LD.setAppbarBack?.('Salary slips', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/salary-slips/${id}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const s = data.slip;
    const cur = data.currency;
    clear(view).append(h('div', { class: 'slip-wrap' },
      h('article', { class: 'slip' },
        h('header', { class: 'slip-head' }, h('span', { class: 'slip-title' }, 'Salary slip'), h('span', { class: 'slip-period' }, s.label)),
        h('div', { class: 'slip-who' },
          h('strong', {}, s.name),
          h('span', {}, s.type_label),
          h('span', { class: 'slip-range' }, `${longDate(s.from)} – ${longDate(s.to)}`)),
        s.sections.map((sec) => h('section', { class: 'slip-sec' },
          h('h3', {}, sec.title),
          h('dl', {}, sec.rows.flatMap((r) => [
            h('dt', { class: r.strong ? 'is-strong' : null }, r.label),
            h('dd', { class: r.strong ? 'is-strong' : null }, shown(r, cur)),
          ])))),
        h('div', { class: 'slip-net' }, h('span', {}, s.net.label), h('strong', {}, money(s.net.value, cur))),
        s.released_on ? h('p', { class: 'slip-foot' }, `Released on ${longDate(s.released_on)}`) : null),
      h('a', { class: 'btn primary slip-download', href: `/api/salary-slips/${id}.pdf`, download: '' }, 'Download PDF')));
    window.scrollTo(0, 0);
  }

  function route() {
    const m = /^#(\d+)$/.exec(window.location.hash);
    return m ? showSlip(Number(m[1])) : showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
