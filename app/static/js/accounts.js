/* Accounts (kohal, 2026-10-31) - the admin's view of every bank / cash account: how much came in, how much went
   out, and per account each debit and credit with who asked for it, when, and why (fooding, petrol, salary,
   wages ...). See app/accounts.py. Two views on one page: the list of accounts, and (#<account name>) one
   account's entries. */
(() => {
  'use strict';

  const { $, h, clear, api, money, plural, toast, confirm, field, selectField, dateField, closeOnBack, showFieldErrors } = window.LD;
  const view = $('#view');

  const fmtDate = (iso) => {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  };

  /* Self transfer (kohal, 2026-11-02): move money between two of the admin's own accounts. One record - it shows as a
     debit on the account it left and a credit on the one it reached. `from` pre-fills the "From" box. */
  function openTransferSheet(names, from, cur, onDone) {
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' });
    const fromSel = selectField(names, from || '', { title: 'From account', placeholder: 'Choose an account' });
    const toSel = selectField(names, '', { title: 'To account', placeholder: 'Choose an account' });
    const amountInput = h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal' });
    const dateSel = dateField('', { placeholder: 'Today' });
    const noteInput = h('input', { type: 'text', maxlength: 200, autocomplete: 'off', placeholder: 'Optional' });
    const errEl = h('p', { class: 'err', role: 'alert' });
    const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Transfer');
    const finish = closeOnBack(() => overlay.remove());
    overlay.onclick = (e) => { if (e.target === overlay) finish(); };
    cancelBtn.onclick = () => finish();
    const form = h('div', {},
      field('from_account', 'From', fromSel), field('to_account', 'To', toSel),
      field('amount', 'Amount', amountInput), field('entry_date', 'Date', dateSel),
      field('note', 'Note', noteInput), errEl);
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      errEl.textContent = '';
      try {
        await api('/api/accounts/transfers', { method: 'POST', body: {
          from_account: fromSel.value, to_account: toSel.value, amount: amountInput.value, entry_date: dateSel.value, note: noteInput.value } });
        finish();
        toast('Transferred');
        onDone();
      } catch (err) {
        if (err.fields) showFieldErrors(form, err.fields); else errEl.textContent = err.message;
        saveBtn.disabled = false;
      }
    };
    overlay.append(h('div', { class: 'amount-sheet', role: 'dialog', 'aria-modal': 'true' },
      h('h2', {}, 'Transfer money'), form, h('div', { class: 'confirm-actions' }, cancelBtn, saveBtn)));
    document.body.append(overlay);
  }

  const transferButton = (names, from, cur, onDone) => h('button', {
    class: 'btn small primary', type: 'button', onclick: () => openTransferSheet(names, from, cur, onDone) }, 'Transfer money');

  // On the list the button sits up in the "Accounts" title row (same app-bar slot Attendance's "Team" link uses);
  // inside one account it stays in the page, since the app bar there carries the back arrow.
  function setTransferLink(show, onClick) {
    document.getElementById('acct-transfer-link')?.remove();
    const actions = document.querySelector('.appbar-actions');
    if (show && actions) actions.append(h('button', { id: 'acct-transfer-link', class: 'att-team-link', type: 'button', onclick: onClick }, 'Transfer money'));
  }

  async function showList() {
    setTransferLink(false);
    window.LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/accounts'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const names = data.accounts.map((a) => a.name);
    setTransferLink(true, () => openTransferSheet(names, '', data.currency, showList));
    clear(view).append(
      h('ul', { class: 'card-group' }, data.accounts.map((a) => h('li', {},
      h('a', { class: 'p-row acct-row', href: `#${encodeURIComponent(a.name)}` },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, a.name),
          h('span', { class: 'row-sub' }, `In ${money(a.credits, data.currency)} · Out ${money(a.debits, data.currency)} · ${plural(a.count, 'entry', 'entries')}`)),
        h('span', { class: 'row-value' }, money(a.balance, data.currency)))))));
  }

  async function showAccount(name) {
    setTransferLink(false);
    window.LD.setAppbarBack?.('Accounts', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/accounts/detail?name=${encodeURIComponent(name)}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    let filter = 'all';
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Show' });
    const list = h('div', {});

    async function removeTransfer(e) {
      if (!await confirm('Remove this transfer? Both accounts go back to how they were.', { ok: 'Remove', title: 'Remove transfer', danger: true })) return;
      try { await api(`/api/accounts/transfers/${e.transfer_id}`, { method: 'DELETE' }); toast('Transfer removed'); showAccount(name); }
      catch (err) { toast(err.message, true); }
    }

    function entryRow(e) {
      const credit = e.kind === 'credit';
      const who = [e.requested_by ? `asked by ${e.requested_by}` : null, e.approved_by ? `approved by ${e.approved_by}` : null].filter(Boolean).join(' · ');
      return h('li', { class: 'p-row' },
        h('span', { class: 'p-main' },
          // Who the money went to / came from is the headline (kohal, 2026-10-31); asked-by and approved-by follow where known.
          h('span', { class: 'row-title' }, e.party ? `${credit ? 'From' : 'To'} ${e.party}` : e.reason),
          h('span', { class: 'row-sub' }, [e.detail, fmtDate(e.date), who].filter(Boolean).join(' · ')),
          h('span', { class: `chip ${credit ? 'chip-role' : 'chip-off'}` }, e.reason)),
        h('span', { class: `row-value ${credit ? 'acct-credit' : 'acct-debit'}` }, `${credit ? '+' : '−'}${money(e.amount, cur)}`));
    }

    function render() {
      clear(chips);
      [['all', 'All'], ['credit', 'Credits'], ['debit', 'Debits']].forEach(([key, label]) => chips.append(h('button', {
        class: 'filter-chip', type: 'button', 'aria-pressed': String(filter === key), onclick: () => { filter = key; render(); },
      }, label)));
      const rows = data.entries.filter((e) => filter === 'all' || e.kind === filter);
      clear(list).append(rows.length ? h('ul', { class: 'card-group' }, rows.map(entryRow))
        : h('p', { class: 'hint' }, 'Nothing here yet.'));
    }

    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, data.name)),
      h('p', { class: 'hint' }, `In ${money(data.credits, cur)} · Out ${money(data.debits, cur)} · Balance ${money(data.balance, cur)}`),
      h('div', { class: 'acct-actions' }, transferButton(data.account_names, name, cur, () => showAccount(name))),
      chips, list));
    render();
  }

  function route() {
    const hash = decodeURIComponent(window.location.hash.slice(1));
    return hash ? showAccount(hash) : showList();
  }
  window.addEventListener('hashchange', route);
  route();
})();
