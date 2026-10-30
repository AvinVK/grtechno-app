/* Petrol: what an employee on petrol payment is owed for the kilometres they ride (kohal, 2026-10-27: "same
   as fooding, we need option of petrol payment") - see app/petrol.py. One page, two audiences, same split as
   fooding.js:
   - mode "manage" (the admin or accountant): two tabs, Employees (everyone on petrol payment with this
     month's amount; tap a person for their register) and Requests (cash the employees have asked for -
     active to approve, and the history).
   - mode "own" (an employee on petrol payment): their own register and totals, and a button on each approved
     day to ask for that amount in cash (kohal, 2026-10-30).
   An entry only counts towards the totals once the admin or the project manager has approved it; the cash is
   paid only once the admin or accountant approves the request and says how it was paid. */
(() => {
  'use strict';

  const { $, h, clear, api, money, toast, field, selectField, closeOnBack } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;

  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  };
  const fmtStamp = (iso) => (iso ? fmtDate(iso.slice(0, 10)) : '');

  const STATUS = { pending: ['Waiting for approval', 'chip-off'], approved: ['Approved', 'chip-role'], rejected: ['Rejected', 'chip-off'] };

  /* Where an approved day's cash stands, and (for the employee) the button to ask for it. */
  function cashPart(e, { own, onChanged }) {
    if (e.status !== 'approved') return null;
    if (e.cash_status === 'requested') return h('span', { class: 'chip chip-off' }, 'Cash requested');
    if (e.cash_status === 'paid') {
      return h('span', { class: 'chip chip-role' },
        ['Paid', e.cash_mode, fmtStamp(e.cash_decided_at)].filter(Boolean).join(' · '));
    }
    const rejected = e.cash_status === 'rejected' ? h('span', { class: 'chip chip-off' }, 'Cash request rejected') : null;
    if (!own) return rejected;
    const btn = h('button', { class: 'btn small', type: 'button' }, e.cash_status === 'rejected' ? 'Request again' : 'Request cash');
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api(`/api/petrol/${e.id}/request-cash`, { method: 'POST' });
        toast('Cash requested');
        await onChanged();
      } catch (err) {
        toast(err.message, true);
        btn.disabled = false;
      }
    };
    return h('span', { class: 'petrol-cash' }, rejected, btn);
  }

  function entryRow(cur, opts) {
    return (e) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, `${fmtDate(e.work_date)} · ${e.km} km`),
        h('span', { class: 'row-sub' }, [`${e.in_reading} → ${e.out_reading}`, e.project_title, e.approved_by_name ? `by ${e.approved_by_name}` : null].filter(Boolean).join(' · ')),
        e.status === 'approved' ? null : h('span', { class: `chip ${STATUS[e.status][1]}` }, STATUS[e.status][0]),
        cashPart(e, opts)),
      h('span', { class: 'row-value' }, e.status === 'approved' ? money(e.amount, cur) : `(${money(e.amount, cur)})`));
  }

  function registerBlock(data, opts = {}) {
    const cur = data.currency;
    return h('div', { class: 'petrol-register' },
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'This month'),
          h('span', { class: 'stat-value is-text' }, money(data.month_total, cur)),
          h('span', { class: 'stat-note' }, `${data.month_km} km approved`)),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'To be paid'),
          h('span', { class: 'stat-value is-text' }, money(data.unpaid_total, cur)),
          h('span', { class: 'stat-note' }, `${money(data.paid_total, cur)} paid · ${money(data.rate_per_km, cur)} per km`))),
      h('p', { class: 'hint' }, opts.own
        ? 'Each day is the kilometres between the two odometer readings, paid per km once approved. When a day is approved, use Request cash to ask for that amount. Amounts in brackets are not approved yet.'
        : 'Each day is the kilometres between the two odometer readings, paid per km once approved. Amounts in brackets are not approved yet.'),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Register'),
        data.entries.length
          ? h('ul', { class: 'card-group' }, data.entries.map(entryRow(cur, opts)))
          : h('p', { class: 'hint' }, 'Nothing yet - it fills in as check-ins and check-outs with an odometer reading are approved.')));
  }

  /* ---------- mode "own" ---------- */

  async function loadOwn() {
    try {
      const data = await api('/api/petrol/me');
      clear(view).append(h('div', { class: 'project-detail' }, registerBlock(data, { own: true, onChanged: loadOwn })));
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
    }
  }

  /* ---------- mode "manage" ---------- */

  const tabBar = (active, waiting) => h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Petrol section' },
    [['employees', 'Employees', '#'], ['requests', waiting ? `Requests (${waiting})` : 'Requests', '#requests']].map(([key, label, href]) => h('a', {
      class: 'filter-chip', href, 'aria-current': active === key ? 'page' : null,
    }, label)));

  async function loadManage() {
    LD.resetAppbarBack?.();
    let data;
    try {
      data = await api('/api/petrol');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;
    clear(view).append(h('div', {},
      tabBar('employees', data.cash_waiting),
      h('p', { class: 'result-count' }, `${data.workers.length} employee${data.workers.length === 1 ? '' : 's'} on petrol payment`),
      data.workers.length
        ? h('ul', { class: 'card-group' }, data.workers.map((w) => h('li', {}, h('button', {
          type: 'button', class: 'card me-row approval-row fooding-row', onclick: () => { window.location.hash = `#p${w.worker_id}`; },
        },
        h('div', { class: 'approval-main' },
          h('strong', {}, w.worker_name),
          h('span', { class: 'hint' }, [`${w.month_km} km this month`, w.pending ? `${w.pending} waiting for approval` : null,
            w.unpaid_total ? `${money(w.unpaid_total, cur)} to be paid` : null].filter(Boolean).join(' · '))),
        h('span', { class: 'fn-stat-value' }, money(w.month_total, cur))))))
        : h('p', { class: 'empty-state' }, 'Nobody is on petrol payment yet - switch it on for someone in Employee management.')));
  }

  /* A person's register opens as its own page, like an employee in the attendance register. */
  async function showPerson(id) {
    LD.setAppbarBack?.('Petrol', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    try {
      const data = await api(`/api/petrol/worker/${id}`);
      clear(view).append(h('div', { class: 'people' },
        h('div', { class: 'att-head' }, h('h2', {}, data.worker_name)),
        registerBlock(data)));
      window.scrollTo(0, 0);
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message, ' ', h('a', { href: '#' }, 'Back')));
    }
  }

  /* ---------- Requests: cash the employees have asked for ---------- */

  /* Approving means paying it, so the approver says how (kohal: "the approver have to enter the mode of
     payment") - a small sheet with the two modes and a Pay button. */
  function openPaySheet(r, paymentModes, cur, onDone) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const modeSel = selectField(paymentModes, '', { title: 'Account', placeholder: 'Choose an account' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const payBtn = h('button', { class: 'btn primary', type: 'button' }, 'Approve and mark paid');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    payBtn.onclick = async () => {
      payBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api(`/api/petrol/requests/${r.id}/approve`, { method: 'POST', body: { payment_mode: modeSel.value } });
        finish();
        toast('Approved');
        await onDone();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        payBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, `${r.user_name} · ${money(r.amount, cur)}`),
      h('p', { class: 'hint' }, `${fmtDate(r.work_date)} · ${r.km} km`),
      field('payment_mode', 'Account', modeSel),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, payBtn)));
    document.body.append(overlay);
  }

  async function showRequests() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try {
      data = await api('/api/petrol/requests');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const cur = data.currency;

    async function reject(r) {
      try {
        await api(`/api/petrol/requests/${r.id}/reject`, { method: 'POST' });
        toast('Rejected');
        await showRequests();
      } catch (err) { toast(err.message, true); }
    }

    const activeRow = (r) => h('li', { class: 'card approval-row' },
      h('div', { class: 'approval-main' },
        h('strong', {}, `${r.user_name} · ${money(r.amount, cur)}`),
        h('span', { class: 'hint' }, [fmtDate(r.work_date), `${r.km} km`, r.project_title, `asked ${fmtStamp(r.cash_requested_at)}`].filter(Boolean).join(' · '))),
      h('div', { class: 'approval-actions' },
        h('button', { class: 'btn small primary', type: 'button', onclick: () => openPaySheet(r, data.payment_modes, cur, showRequests) }, 'Approve'),
        h('button', { class: 'btn small', type: 'button', onclick: () => reject(r) }, 'Reject')));

    const historyRow = (r) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, r.user_name),
        h('span', { class: 'row-sub' }, [fmtDate(r.work_date), `${r.km} km`, r.cash_decided_by_name ? `${r.cash_status === 'paid' ? 'paid' : 'rejected'} by ${r.cash_decided_by_name}` : null,
          fmtStamp(r.cash_decided_at)].filter(Boolean).join(' · ')),
        h('span', { class: `chip ${r.cash_status === 'paid' ? 'chip-role' : 'chip-off'}` },
          r.cash_status === 'paid' ? `Paid · ${r.cash_mode}` : 'Rejected')),
      h('span', { class: 'row-value' }, money(r.amount, cur)));

    clear(view).append(h('div', {},
      tabBar('requests', data.pending.length),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Active'),
        data.pending.length
          ? h('ul', { class: 'card-group' }, data.pending.map(activeRow))
          : h('p', { class: 'hint' }, 'Nothing waiting. When an employee asks for the cash for an approved day it shows up here.')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'History'),
        data.history.length
          ? h('ul', { class: 'card-group' }, data.history.map(historyRow))
          : h('p', { class: 'hint' }, 'Nothing decided yet.'))));
  }

  function route() {
    const m = /^#p(\d+)$/.exec(window.location.hash);
    if (m) return showPerson(Number(m[1]));
    if (window.location.hash === '#requests') return showRequests();
    return loadManage();
  }

  if (mode === 'manage') {
    window.addEventListener('hashchange', route);
    route();
  } else loadOwn();
})();
