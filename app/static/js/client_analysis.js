/* Client analysis (kohal, 2026-11-05: "client rename to client analysis and have 2 subtabs, analysis and tally"), two subtabs:
   - Tally ("the way i see supplier tally, i wanna see client tally ... for each client whats the total worth of the client, how much
     is paid and how much is left"): every client with what their projects are worth, what has been received and what is left; tap
     one for the same split project by project. See app/clients.py's client_tally / client_tally_detail.
   - Analysis: charts over the same figures (client_analysis). Read only. */
(() => {
  'use strict';

  const { $, h, clear, api, money, selectField, setAppbarBack, resetAppbarBack, closeOnBack } = window.LD;
  const { panel, columnChart, barRows, pieChart } = window.LD.charts;
  const view = $('#view');

  const STATUS = { planned: 'Planned', running: 'Running', on_hold: 'On hold', final_estimate_sent: 'Final estimate sent', completed: 'Completed' };

  // Three figures side by side, each its own small card.
  const trio = (worth, paid, left, cur) => h('div', { class: 'tally-stats' },
    [['Total worth', worth], ['Paid', paid], ['Left', left]].map(([label, value]) =>
      h('div', { class: 'stat' }, h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value is-text' }, money(value, cur)))));

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const fmtDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

  // A project's payment steps in a bottom sheet (kohal, 2026-11-05: "just open on the fly payment subtab" - not the project's own
  // page, so going back is still the client's tally). Read only: what each step is, what it is for, and whether it was received.
  function openPaymentsSheet(p, cur) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const closeBtn = h('button', { class: 'btn', type: 'button' }, 'Close');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    closeBtn.onclick = () => finish();
    const step = (x) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, x.label),
        h('span', { class: 'row-sub' }, [x.paid_date ? `Received ${fmtDate(x.paid_date)}` : (x.due_date ? `Due ${fmtDate(x.due_date)}` : 'Not received yet'),
          x.paid_date ? x.mode : null, x.comments || null].filter(Boolean).join(' \u00b7 '))),
      h('span', { class: 'row-value' }, money(x.amount, cur)),
      h('span', { class: `chip ${x.paid_date ? 'chip-active' : 'chip-today'}` }, x.paid_date ? 'Paid' : 'Pending'));
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Payments' },
      h('h2', {}, p.title ? `${p.code} \u00b7 ${p.title}` : p.code),
      trio(p.worth === null ? 0 : p.worth, p.paid, p.left === null ? 0 : p.left, cur),
      h('h3', {}, 'Payments'),
      p.payments.length ? h('ul', { class: 'card-group' }, p.payments.map(step)) : h('p', { class: 'hint' }, 'No payment steps set for this project yet.'),
      h('div', { class: 'confirm-actions' }, closeBtn)));
    document.body.append(overlay);
  }

  // "Analysis" / "Tally" subtabs - the same .stage-filter/.filter-chip pattern as Work plan/Announcements.
  const tabs = (active) => h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Client analysis section' },
    h('a', { class: 'filter-chip', href: '#analysis', 'aria-current': active === 'analysis' ? 'page' : null }, 'Analysis'),
    h('a', { class: 'filter-chip', href: '#tally', 'aria-current': active === 'tally' ? 'page' : null }, 'Tally'));

  let span = '12';
  let scrollTo = null;

  async function showAnalysis() {
    resetAppbarBack?.();
    clear(view).append(tabs('analysis'), h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/clients/analysis?range=${encodeURIComponent(span)}`); } catch (err) { clear(view).append(tabs('analysis'), h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    const short = (v) => money(v, cur);
    const rangeSel = selectField(data.ranges, data.received.range, { title: 'Show money received for', placeholder: 'Range' });
    rangeSel.classList.add('compact');
    rangeSel.addEventListener('change', () => { span = rangeSel.value || '12'; scrollTo = 'panel-received'; showAnalysis(); });

    const TOP = 8;
    const top = data.top_clients.slice(0, TOP);
    const topBars = top.length
      ? [barRows(top, { value: (r) => r.worth, label: (r) => r.name, format: short, share: (r) => Math.min(r.paid / r.worth, 1),
        note: (r) => `${short(r.paid)} paid · ${short(Math.max(r.left, 0))} left` }),
      data.top_clients.length > TOP ? h('p', { class: 'hint' }, `+ ${data.top_clients.length - TOP} more clients - see the Tally tab.`) : null]
      : [h('p', { class: 'hint' }, 'No client has a project with a value set yet.')];
    const status = pieChart(data.status.filter((s) => s.projects).map((s) => ({ name: s.label, total: s.projects, worth: s.worth })), {
      ariaNoun: 'Projects by status', empty: 'No projects yet.',
      others: (rest) => ({ name: `Others (${rest.length})`, total: rest.reduce((n, p) => n + p.total, 0), worth: rest.reduce((n, p) => n + p.worth, 0) }),
      legend: (s, pct) => `${s.total} project${s.total === 1 ? '' : 's'} · ${pct}% · worth ${short(s.worth)}`,
    });
    const paidPct = data.totals.worth > 0 ? Math.round((Math.min(data.totals.paid, data.totals.worth) / data.totals.worth) * 100) : 0;

    clear(view).append(h('div', {},
      tabs('analysis'),
      trio(data.totals.worth, data.totals.paid, data.totals.left, cur),
      h('p', { class: 'hint' }, `${data.clients} client${data.clients === 1 ? '' : 's'} · ${paidPct}% of the total worth received.`),
      panel('panel-top', 'Worth by client', `The biggest clients by what their projects are worth, with how much of it has been paid.`, null, ...topBars),
      panel('panel-received', 'Money received', `Payments received - ${short(data.received.total)} ${data.received.label.startsWith('Last') ? 'in the ' : ''}${data.received.label.toLowerCase()}.`, rangeSel,
        columnChart(data.received, { noun: 'Money received', format: (v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(Math.round(v))) })),
      panel('panel-status', 'Projects by status', 'How many of the clients\' projects are in each stage of work.', null, status)));
    if (scrollTo) { document.getElementById(scrollTo)?.scrollIntoView({ block: 'center' }); scrollTo = null; }
  }

  async function showList() {
    resetAppbarBack?.();
    clear(view).append(tabs('tally'), h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/clients/tally'); } catch (err) { clear(view).append(tabs('tally'), h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    const search = h('input', { type: 'search', placeholder: 'Search clients', 'aria-label': 'Search clients' });
    const list = h('ul', { class: 'card-group' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const rows = data.clients.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.contact_name || '').toLowerCase().includes(q) || (c.city || '').toLowerCase().includes(q));
      count.textContent = `${rows.length} client${rows.length === 1 ? '' : 's'}`;
      clear(list).append(...(rows.length ? rows.map((c) => h('li', {},
        h('a', { class: 'p-row', href: `#c${c.id}` },
          h('span', { class: 'p-main' },
            h('span', { class: 'row-title' }, c.name),
            h('span', { class: 'row-sub' }, [`${c.projects} project${c.projects === 1 ? '' : 's'}`, `worth ${money(c.worth, cur)}`, `paid ${money(c.paid, cur)}`].join(' · '))),
          h('span', { class: 'row-value' }, money(c.left, cur)),
          h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›'))))
        : [h('li', {}, h('p', { class: 'empty-state' }, data.clients.length ? 'No clients match this search.' : 'No clients yet.'))]));
    };
    search.oninput = draw;
    clear(view).append(h('div', {},
      tabs('tally'),
      trio(data.totals.worth, data.totals.paid, data.totals.left, cur),
      h('div', { class: 'filters' }, search), count, list));
    draw();
  }

  async function showClient(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/clients/${id}/tally`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    setAppbarBack?.('Client analysis', '#tally');
    const cur = data.currency;
    const c = data.client;
    const money0 = (v) => (v === null ? 'Not set' : money(v, cur));
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, c.name), c.contact_name || c.city ? h('p', { class: 'hint' }, [c.contact_name, c.city].filter(Boolean).join(' · ')) : null),
      trio(c.worth, c.paid, c.left, cur),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Projects'),
        data.projects.length
          ? h('ul', { class: 'card-group' }, data.projects.map((p) => {
            const body = [
              h('span', { class: 'p-main' },
                h('span', { class: 'row-title' }, p.title ? `${p.code} · ${p.title}` : p.code),
                h('span', { class: 'row-sub' }, [STATUS[p.status] || p.status, `worth ${money0(p.worth)}`, `paid ${money(p.paid, cur)}`].join(' · '))),
              h('span', { class: 'row-value' }, p.left === null ? '' : money(p.left, cur))];
            return h('li', {}, h('button', { class: 'p-row tally-project', type: 'button', onclick: () => openPaymentsSheet(p, cur) }, ...body));
          }))
          : h('p', { class: 'hint' }, 'No projects for this client yet.'))));
  }

  function route() {
    const m = /^#c(\d+)$/.exec(window.location.hash);
    if (m) return showClient(Number(m[1]));
    return window.location.hash === '#tally' ? showList() : showAnalysis();
  }

  window.addEventListener('hashchange', route);
  route();
})();
