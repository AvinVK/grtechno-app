/* Fooding: a daily-wage employee's food allowance - see app/fooding.py and models.FoodingAccount for the
   no-cron settle() design this all rests on. One page, two audiences, same split as attendance.js's own
   team_only (kohal, 2026-10-18: "fooding should open its own page!" - this used to only be a block on the
   Me hub for the managing side):
   - mode "manage" (the admin or accountant): every daily-wage employee, what's been allotted and what's
     left, tap a row to top up or pause/resume.
   - mode "own" (a daily-wage worker): just their own balance, read-only, or "Paused" if it is. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, money, field, closeOnBack } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;

  /* ---------- mode "own": a daily-wage worker's own balance ---------- */

  async function loadOwn() {
    let data;
    try {
      data = await api('/api/fooding/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    const f = data.fooding;
    const cur = data.currency;
    clear(view).append(h('div', { class: 'project-detail' },
      f.is_paused ? h('p', {}, h('span', { class: 'chip chip-off' }, 'Paused')) : null,
      h('div', { class: 'client-stats' },
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Allotted'),
          h('span', { class: 'stat-value is-text' }, money(f.allotted_total, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Remaining'),
          h('span', { class: 'stat-value is-text' }, money(f.remaining, cur))),
        h('div', { class: 'stat' },
          h('span', { class: 'stat-label' }, 'Daily deduction'),
          h('span', { class: 'stat-value is-text' }, f.is_paused ? 'Paused' : `${money(f.daily_amount, cur)}/day`))),
      h('p', { class: 'hint' }, f.is_paused
        ? 'The admin or accountant has paused your fooding deduction - nothing is coming off your balance right now.'
        : `₹${f.daily_amount} comes off your fooding balance automatically, every day, until the admin or accountant pauses it or your balance runs out.`)));
  }

  /* ---------- mode "manage": the admin or accountant's own page ---------- */

  async function loadManage() {
    let data;
    try {
      data = await api('/api/fooding');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    clear(view).append(h('div', {},
      h('p', { class: 'result-count' }, `${data.workers.length} daily-wage employee${data.workers.length === 1 ? '' : 's'}`),
      data.workers.length
        ? h('ul', { class: 'card-group' }, data.workers.map((w) => row(w, data.daily_amount, data.currency)))
        : h('p', { class: 'empty-state' }, 'No daily-wage employees yet - mark someone from Employee management first.')));
  }

  function row(w, dailyAmount, cur) {
    const sub = w.is_paused
      ? 'Paused'
      : `${money(w.allotted_total, cur)} allotted · ${money(dailyAmount, cur)}/day`;
    return h('li', {}, h('button', {
      type: 'button', class: `card me-row approval-row fooding-row${w.is_paused ? ' is-paused' : ''}`,
      onclick: () => openSheet(w, dailyAmount, cur),
    },
      h('div', { class: 'approval-main' },
        h('strong', {}, w.worker_name),
        h('span', { class: 'hint' }, sub)),
      h('span', { class: 'fn-stat-value' }, money(w.remaining, cur))));
  }

  function openSheet(w, dailyAmount, cur) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'number', min: '1', step: 'any', inputmode: 'decimal', placeholder: 'Amount to add' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Close');
    const allotBtn = h('button', { class: 'btn primary', type: 'button' }, 'Add');
    const pauseBtn = h('button', { class: 'btn small', type: 'button' }, w.is_paused ? 'Resume' : 'Pause');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    allotBtn.onclick = async () => {
      allotBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api(`/api/fooding/${w.worker_id}/allot`, { method: 'POST', body: { amount: amountInput.value } });
        finish();
        toast('Added to fooding balance');
        await loadManage();
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        allotBtn.disabled = false;
      }
    };
    pauseBtn.onclick = async () => {
      pauseBtn.disabled = true;
      try {
        await api(`/api/fooding/${w.worker_id}/${w.is_paused ? 'resume' : 'pause'}`, { method: 'POST' });
        finish();
        toast(w.is_paused ? 'Fooding resumed' : 'Fooding paused');
        await loadManage();
      } catch (err) {
        toast(err.message, true);
        pauseBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, w.worker_name),
      h('p', { class: 'hint' },
        `${money(w.allotted_total, cur)} allotted so far · ${money(w.remaining, cur)} remaining · ${money(dailyAmount, cur)}/day`,
        w.is_paused ? ' · Paused' : ''),
      field('amount', 'Add to balance', amountInput),
      errEl,
      h('div', { class: 'confirm-actions' }, pauseBtn, cancelBtn, allotBtn)));
    document.body.append(overlay);
    amountInput.focus();
  }

  if (mode === 'manage') loadManage(); else loadOwn();
})();
