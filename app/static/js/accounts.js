/* Accounts (kohal, 2026-10-31) - the admin's view of every bank / cash account: how much came in, how much went
   out, and per account each debit and credit with who asked for it, when, and why (fooding, petrol, salary,
   wages ...). See app/accounts.py. Two views on one page: the list of accounts, and (#<account name>) one
   account's entries. */
(() => {
  'use strict';

  const { $, h, clear, api, money, plural } = window.LD;
  const view = $('#view');

  const fmtDate = (iso) => {
    if (!iso) return '';
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  };

  async function showList() {
    window.LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/accounts'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(h('ul', { class: 'card-group' }, data.accounts.map((a) => h('li', {},
      h('a', { class: 'p-row acct-row', href: `#${encodeURIComponent(a.name)}` },
        h('span', { class: 'p-main' },
          h('span', { class: 'row-title' }, a.name),
          h('span', { class: 'row-sub' }, `In ${money(a.credits, data.currency)} · Out ${money(a.debits, data.currency)} · ${plural(a.count, 'entry', 'entries')}`)),
        h('span', { class: 'row-value' }, money(a.balance, data.currency)))))));
  }

  async function showAccount(name) {
    window.LD.setAppbarBack?.('Accounts', '#');
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/accounts/detail?name=${encodeURIComponent(name)}`); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const cur = data.currency;
    let filter = 'all';
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Show' });
    const list = h('div', {});

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
