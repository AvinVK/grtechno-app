/* Fooding: a daily-wage employee's food (and now any) allowance - see app/fooding.py and
   models.FoodingAccount/FoodingEntry for the no-cron settle() design and the ledger this all rests on.
   One page, two audiences, same split as attendance.js's own team_only (kohal, 2026-10-18: "fooding should
   open its own page!" - this used to only be a block on the Me hub for the managing side):
   - mode "manage" (the admin or accountant): every daily-wage employee, what's been allotted and what's
     left, tap a row to top up (with how it was paid) or pause/resume.
   - mode "own" (a daily-wage worker): their own balance, or "Paused" if it is, plus "+ Add expense" to log
     spending the balance on travel or anything else (kohal: "the daily wages employee can also use the
     money for travelling or for any reason") - amount, how it was paid, and what it was for. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, money, field, selectField, closeOnBack } = window.LD;
  const view = $('#view');
  const mode = view.dataset.mode;

  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  };

  /* ---------- mode "own": a daily-wage worker's own balance ---------- */

  async function loadOwn() {
    let data;
    try {
      data = await api('/api/fooding/me');
    } catch (err) {
      clear(view).append(h('p', { class: 'empty-state' }, err.message));
      return;
    }
    renderOwn(data);
  }

  function renderOwn(data) {
    const f = data.fooding;
    const cur = data.currency;
    const entries = data.entries || [];
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
        : `₹${f.daily_amount} comes off your fooding balance automatically, every day, until the admin or accountant pauses it or your balance runs out.`),
      h('div', { class: 'form-actions' },
        h('button', { class: 'btn primary', type: 'button', onclick: () => openExpenseSheet(data.payment_modes, cur) }, '+ Add expense')),
      h('section', { class: 'p-section' },
        h('h3', {}, 'Expenses'),
        entries.length
          ? h('ul', { class: 'card-group' }, entries.map(entryRow(cur)))
          : h('p', { class: 'hint' }, 'Nothing logged yet - use + Add expense when you spend some of this on travel or anything else.'))));
  }

  function entryRow(cur, { forManager = false } = {}) {
    return (e) => h('li', { class: 'p-row' },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, e.kind === 'allot' ? (forManager ? 'Credited' : 'Allotted to you') : (e.purpose || 'Expense')),
        h('span', { class: 'row-sub' }, [fmtDate(e.entry_date), e.payment_mode,
          e.created_by_name ? `${e.kind === 'allot' ? 'by' : 'logged by'} ${e.created_by_name}` : null].filter(Boolean).join(' · '))),
      h('span', { class: 'row-value' }, (e.kind === 'allot' ? '+' : '−') + money(e.amount, cur)));
  }

  function openExpenseSheet(paymentModes, cur) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'number', min: '1', step: 'any', inputmode: 'decimal' });
    const modeSel = selectField(paymentModes, '', { title: 'How was it paid', placeholder: 'Choose one' });
    const purposeInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off', placeholder: 'e.g. Bus fare to site' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Add expense');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      errEl.textContent = '';
      try {
        const res = await api('/api/fooding/me/expenses', {
          method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value, purpose: purposeInput.value },
        });
        finish();
        toast('Expense added');
        renderOwn({ fooding: res.fooding, entries: res.entries, currency: cur, payment_modes: paymentModes });
      } catch (err) {
        errEl.textContent = (err.fields && Object.values(err.fields)[0]) || err.message;
        saveBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Add expense'),
      field('amount', 'Amount', amountInput),
      field('payment_mode', 'How was it paid', modeSel),
      field('purpose', 'What was it for', purposeInput),
      errEl,
      h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
    amountInput.focus();
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
        ? h('ul', { class: 'card-group' }, data.workers.map((w) => row(w, data.daily_amount, data.currency, data.payment_modes)))
        : h('p', { class: 'empty-state' }, 'No daily-wage employees yet - mark someone from Employee management first.')));
  }

  function row(w, dailyAmount, cur, paymentModes) {
    const sub = w.is_paused
      ? 'Paused'
      : `${money(w.allotted_total, cur)} allotted · ${money(dailyAmount, cur)}/day`;
    return h('li', {}, h('button', {
      type: 'button', class: `card me-row approval-row fooding-row${w.is_paused ? ' is-paused' : ''}`,
      onclick: () => openManageSheet(w, dailyAmount, cur, paymentModes),
    },
      h('div', { class: 'approval-main' },
        h('strong', {}, w.worker_name),
        h('span', { class: 'hint' }, sub)),
      h('span', { class: 'fn-stat-value' }, money(w.remaining, cur))));
  }

  function openManageSheet(w, dailyAmount, cur, paymentModes) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const amountInput = h('input', { type: 'number', min: '1', step: 'any', inputmode: 'decimal', placeholder: 'Amount to add' });
    const modeSel = selectField(paymentModes, '', { title: 'How was it paid', placeholder: 'Choose one' });
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
        await api(`/api/fooding/${w.worker_id}/allot`, {
          method: 'POST', body: { amount: amountInput.value, payment_mode: modeSel.value },
        });
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
    // The register: every credit and every expense with its date and who entered it (kohal, 2026-10-27:
    // "when clicking on one daily wages person, it should show credited, spent with date, who credited just
    // like a register"). Loaded after the sheet opens so the top-up form is there straight away.
    const registerBox = h('section', { class: 'fooding-register' }, h('p', { class: 'loading' }, 'Loading register…'));
    api(`/api/fooding/${w.worker_id}`).then((reg) => {
      const entries = reg.entries || [];
      clear(registerBox).append(
        h('h3', {}, 'Register'),
        h('p', { class: 'hint' }, `Daily food deducted so far: ${money(reg.auto_deducted, cur)}`),
        entries.length
          ? h('ul', { class: 'card-group' }, entries.map(entryRow(cur, { forManager: true })))
          : h('p', { class: 'hint' }, 'Nothing credited or spent yet.'));
    }).catch((err) => { clear(registerBox).append(h('p', { class: 'hint' }, err.message)); });

    overlay.append(h('div', { class: 'amount-sheet register-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, w.worker_name),
      h('p', { class: 'hint' },
        `${money(w.allotted_total, cur)} allotted so far · ${money(w.remaining, cur)} remaining · ${money(dailyAmount, cur)}/day`,
        w.is_paused ? ' · Paused' : ''),
      registerBox,
      field('amount', 'Add to balance', amountInput),
      field('payment_mode', 'How was it paid', modeSel),
      errEl,
      h('div', { class: 'confirm-actions' }, pauseBtn, cancelBtn, allotBtn)));
    document.body.append(overlay);
  }

  if (mode === 'manage') loadManage(); else loadOwn();
})();
