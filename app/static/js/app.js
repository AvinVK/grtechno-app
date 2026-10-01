/* Leads front end. Plain JavaScript, no build step.
   All server data goes through /api/state and the lead endpoints.
   DOM is built with h() and text nodes only, never innerHTML, so lead text cannot inject markup. */
(() => {
  'use strict';

  const VIEWS = ['active', 'add', 'closed', 'status'];
  const CLOSED_STAGES = ['Won', 'Lost'];
  const STAGE_ORDER = ['New enquiry', 'Site survey', 'Quote sent', 'Negotiation', 'Work order & advance'];

  // Which stage section should open by default: the one right after where the lead actually is, so
  // whatever's already done stays out of the way and what's next is one tap away. The last stage keeps
  // itself open once reached (min() clamps at the end); a closed (Won/Lost) lead opens nothing.
  function nextStageIndex(lead) {
    const i = STAGE_ORDER.indexOf(lead.stage);
    return i === -1 ? -1 : Math.min(i + 1, STAGE_ORDER.length - 1);
  }
  const SNOOZE = [['Tomorrow', 1], ['In 3 days', 3], ['Next week', 7]];

  let S = null;                 // latest server state
  let view = 'active';
  let openId;                   // undefined = drawer closed, otherwise the id of the open lead
  let lastFocus = null;
  const filters = {
    active: { q: '', stage: '', area: '', service: '', source: '', from: '', to: '' },
    closed: { q: '', stage: '' },
  };

  const { $, h, clear, api, toast, plural, selectField, dateField } = window.LD;

  async function load() {
    S = await api('/api/state');
    resolveView();
    renderAll();
  }

  /* ---------- dates and money ---------- */

  const parseISO = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const toISO = (d) => d.toISOString().slice(0, 10);
  const addDays = (iso, n) => { const d = parseISO(iso); d.setUTCDate(d.getUTCDate() + n); return toISO(d); };
  const diffDays = (a, b) => Math.round((parseISO(a) - parseISO(b)) / 86400000);

  function fmtDate(iso) {
    const sameYear = iso.slice(0, 4) === S.today.slice(0, 4);
    return parseISO(iso).toLocaleDateString('en-IN', {
      day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric', timeZone: 'UTC',
    });
  }

  const fmtMoney = (v) => (v === null || v === undefined ? '' :
    S.settings.currency + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(v));

  // Indian shorthand (₹85k, ₹12.4 L, ₹1.2 Cr) when the country code is 91, otherwise K / M / B.
  function fmtCompact(v) {
    const c = S.settings.currency;
    if (S.settings.country_code === '91') return LD.fmtShort(v, c);
    return c + new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v);
  }
  const fmtShortMoney = (v) => (v === null || v === undefined ? '' : fmtCompact(v));

  /* ---------- lead helpers ---------- */

  const title = (l) => l.company || l.contact_name || l.client_name || 'Untitled lead';
  const subtitle = (l) => (l.company && l.contact_name ? l.contact_name : '');
  const isOpen = (l) => S.open_stages.includes(l.stage);
  const telNumber = (p) => p.replace(/[^\d+]/g, '');

  function waNumber(p) {
    let digits = p.replace(/\D/g, '');
    if (p.trim().startsWith('+')) return digits;
    digits = digits.replace(/^0+/, '');
    return digits.length === 10 ? S.settings.country_code + digits : digits;
  }

  const byFollowUp = (a, b) => {
    if (a.follow_up_date && b.follow_up_date) {
      return a.follow_up_date.localeCompare(b.follow_up_date) || b.created_at.localeCompare(a.created_at);
    }
    if (a.follow_up_date) return -1;
    if (b.follow_up_date) return 1;
    return b.created_at.localeCompare(a.created_at);
  };

  const chip = (tone, text) => h('span', { class: `chip chip-${tone}` }, text);

  function followChip(l) {
    if (!l.follow_up_date || !isOpen(l)) return null;
    const d = diffDays(l.follow_up_date, S.today);
    if (d < 0) return chip('overdue', `${plural(-d, 'day', 'days')} late`);
    if (d === 0) return chip('today', 'Today');
    if (d === 1) return chip('soon', 'Tomorrow');
    return chip('later', `in ${d} days`);
  }

  /* ---------- feedback ---------- */

  /* ---------- summary and navigation ---------- */

  // Set by the overdue card's "Open": after switching to Active, scroll to the Overdue group.
  let scrollToGroup = null;

  function statusView() {
    const s = S.summary;
    const open = S.leads.filter(isOpen);
    const openValue = open.reduce((sum, l) => sum + (l.est_value || 0), 0);

    // Hero: the whole open pipeline, with a bar split by how many leads sit at each open stage.
    const byStage = S.open_stages.map((stage) => ({ stage, n: open.filter((l) => l.stage === stage).length }));
    const bar = h('div', { class: 'hero-bar', 'aria-hidden': 'true' },
      byStage.filter((b) => b.n).map((b) => {
        const seg = h('i', { 'data-stage': b.stage });
        seg.style.flexGrow = String(b.n);
        return seg;
      }));
    const hero = h('section', { class: 'status-hero' },
      h('span', { class: 'hero-label' }, 'Open pipeline'),
      h('span', { class: 'hero-value' }, fmtMoney(openValue)),
      h('span', { class: 'hero-note' }, plural(open.length, 'open lead', 'open leads')),
      open.length ? bar : null,
      open.length ? h('ul', { class: 'hero-legend' }, byStage.map((b) => h('li', { 'data-stage': b.stage },
        h('i', { 'aria-hidden': 'true' }), `${SHORT_STAGE[b.stage] || b.stage} `, h('b', {}, b.n)))) : null);

    // Overdue follow-ups, if any: how many, and the one that has waited longest.
    const overdue = open.filter((l) => l.follow_up_date && l.follow_up_date < S.today)
      .sort((a, b) => a.follow_up_date.localeCompare(b.follow_up_date));
    const overdueCard = overdue.length ? h('a', {
      class: 'status-alert', href: '#active',
      onclick: () => { filters.active.stage = ''; scrollToGroup = 'overdue'; },
    },
    h('span', { class: 'alert-count' }, overdue.length),
    h('span', { class: 'alert-text' },
      h('strong', {}, overdue.length === 1 ? 'Follow-up overdue' : 'Follow-ups overdue'),
      h('span', {}, `Oldest: ${title(overdue[0])}, ${plural(-diffDays(overdue[0].follow_up_date, S.today), 'day', 'days')}`)),
    h('span', { class: 'alert-open' }, 'Open ›')) : null;

    // The rest: numbers already in the summary, or counted from the leads we have.
    const dueToday = open.filter((l) => l.follow_up_date === S.today).length;
    const weekStart = addDays(S.today, -((parseISO(S.today).getUTCDay() + 6) % 7));
    const newThisWeek = S.leads.filter((l) => l.created_at.slice(0, 10) >= weekStart).length;
    const tile = (label, value, note, href) => {
      const body = [h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value' }, value),
        note ? h('span', { class: 'stat-note' }, note) : null];
      return href ? h('a', { class: 'stat', href }, body) : h('div', { class: 'stat' }, body);
    };
    const grid = h('div', { class: 'status-grid' },
      tile('Due today', String(dueToday), s.due_count > dueToday ? `${s.due_count} due incl. overdue` : 'Follow-ups', '#active'),
      tile('New this week', String(newThisWeek), 'Leads added since Monday'),
      tile('Won this month', String(s.won_month_count), s.won_month_count ? `Worth ${fmtCompact(s.won_month_value)}` : 'No wins yet', '#closed'),
      tile('Win rate', s.win_rate === null ? '—' : `${s.win_rate}%`, s.win_rate === null ? 'No closed leads yet' : 'Of all closed leads'));

    return h('div', { class: 'status-cards' },
      hero,
      overdueCard,
      grid,
      h('p', { class: 'status-me' }, `Signed in as ${S.me.name} (${S.me.userid}) · `,
        S.me.is_admin ? 'Admin: you see every lead' : 'You see only your own leads'));
  }

  const VIEW_TITLE = { active: 'Active leads', closed: 'Won / Lost', add: 'New lead', status: 'Your status' };

  function renderNav() {
    document.querySelectorAll('.bottom-nav a[data-view]').forEach((a) => {
      if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    const badge = $('.bottom-nav .nav-badge');
    badge.textContent = S.summary.due_count;
    badge.hidden = S.summary.due_count === 0;

    const titleEl = $('#appbar-title-text');
    const countEl = $('.appbar-count');
    if (titleEl) titleEl.textContent = VIEW_TITLE[view] || VIEW_TITLE.active;
    if (countEl) countEl.textContent = view === 'active' ? String(S.leads.filter(isOpen).length) : '';
  }

  function renderAll() {
    renderNav();
    // Refreshing data must not wipe a half-filled Add lead form.
    if (!(view === 'add' && $('#view .add-lead'))) renderMain();
  }

  function renderMain() {
    const screens = { status: statusView, add: addView };
    clear($('#view')).append(screens[view] ? screens[view]() : listView(view));
    if (view === 'active' && scrollToGroup) {
      $(`#view .group-${scrollToGroup}`)?.scrollIntoView({ block: 'start' });
      scrollToGroup = null;
    }
  }


  /* ---------- lead lists (active and won / lost) ---------- */

  const serviceLabel = (l) => (l.services && l.services.length ? l.services.join(', ') : l.service);

  function fmtDateTime(iso) {
    return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
  }

  /* A master-detail popup for the active-leads filters: category names on the left, that category's
     own options on the right - tapping a category swaps the right pane, tapping an option sets it
     straight away (no separate "apply" per field). Mutates `f` in place; resolves once closed via Done,
     Escape or tapping outside, so the caller just re-runs its own refresh() afterwards. */
  function openFilterPicker(f, { areas }) {
    return new Promise((resolve) => {
      const CATS = [
        { key: 'area', label: 'Area', options: areas, allLabel: 'All areas' },
        { key: 'service', label: 'Service', options: S.settings.services, allLabel: 'All services' },
        { key: 'source', label: 'Source', options: S.settings.sources, allLabel: 'All sources' },
        { key: 'date', label: 'Date', options: null, allLabel: 'All dates' },
      ];
      let active = CATS[0].key;

      const catList = h('div', { class: 'filter-cats', role: 'tablist', 'aria-label': 'Filter by' });
      const optionsPane = h('div', { class: 'filter-options' });

      const valueText = (cat) => {
        if (cat.key === 'date') return (f.from || f.to) ? `${f.from || '…'} – ${f.to || '…'}` : cat.allLabel;
        return f[cat.key] || cat.allLabel;
      };

      function renderCats() {
        clear(catList);
        CATS.forEach((cat) => catList.append(h('button', {
          type: 'button', role: 'tab', 'aria-selected': String(cat.key === active),
          class: `filter-cat${cat.key === active ? ' active' : ''}`,
          onclick: () => { active = cat.key; renderCats(); renderOptions(); },
        }, h('span', { class: 'filter-cat-name' }, cat.label),
           h('span', { class: 'filter-cat-value' }, valueText(cat)))));
      }

      function renderOptions() {
        clear(optionsPane);
        const cat = CATS.find((c) => c.key === active);
        if (cat.key === 'date') {
          const fromInput = dateField(f.from, { placeholder: 'Any date' });
          const toInput = dateField(f.to, { placeholder: 'Any date' });
          fromInput.setAttribute('aria-label', 'From date');
          toInput.setAttribute('aria-label', 'To date');
          fromInput.onchange = () => { f.from = fromInput.value; renderCats(); };
          toInput.onchange = () => { f.to = toInput.value; renderCats(); };
          optionsPane.append(h('label', { class: 'filter-date-field' }, 'From', fromInput),
            h('label', { class: 'filter-date-field' }, 'To', toInput));
          return;
        }
        const opts = [{ value: '', label: cat.allLabel }, ...cat.options.map((o) => ({ value: o, label: o }))];
        opts.forEach((opt) => optionsPane.append(h('button', {
          type: 'button', class: `filter-opt${(f[cat.key] || '') === opt.value ? ' selected' : ''}`,
          onclick: () => { f[cat.key] = opt.value; renderCats(); renderOptions(); },
        }, opt.label)));
      }

      renderCats();
      renderOptions();

      const doneBtn = h('button', { class: 'btn primary', type: 'button' }, 'Done');
      const exportLink = h('a', { class: 'btn', href: $('#view').dataset.exportUrl }, 'Export CSV');
      const card = h('div', { class: 'confirm-card filter-modal-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Filters' },
        h('h2', { class: 'filter-modal-title' }, 'Filters'),
        h('div', { class: 'filter-modal-body' }, catList, optionsPane),
        h('div', { class: 'confirm-actions' }, exportLink, doneBtn));
      const overlay = h('div', { class: 'confirm-overlay filter-overlay', onclick: (e) => { if (e.target === overlay) finish(); } }, card);
      const finish = LD.closeOnBack(() => { overlay.remove(); resolve(); });
      doneBtn.onclick = finish;
      window.addEventListener('keydown', function onKey(e) {
        if (e.key !== 'Escape') return;
        window.removeEventListener('keydown', onKey);
        finish();
      });
      document.body.append(overlay);
    });
  }

  // Phone-width labels for the stage chips - display only, the filter values stay the full stage names.
  const SHORT_STAGE = {
    'New enquiry': 'New', 'Site survey': 'Survey', 'Quote sent': 'Quote', Negotiation: 'Negotiation',
    'Work order & advance': 'W.O. & advance',
  };

  const SVG_NS = 'http://www.w3.org/2000/svg';
  // A small line icon (24x24 viewBox, stroked in currentColor) - h() only makes HTML elements.
  function icon(...paths) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    paths.forEach((d) => {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      svg.append(path);
    });
    return svg;
  }
  const FILTER_ICON = ['M4 5h16l-6 8v6l-4-2v-4z'];

  // Follow-up urgency buckets - the same split followChip's colours use (overdue / today / tomorrow /
  // later), plus leads with no follow-up date at all. The Active list is grouped by these, in this order.
  const FOLLOW_GROUPS = [
    { key: 'overdue', label: 'Overdue' },
    { key: 'today', label: 'Today' },
    { key: 'soon', label: 'Tomorrow' },
    { key: 'later', label: 'Later' },
    { key: 'none', label: 'No follow-up date' },
  ];
  function followBucket(l) {
    if (!l.follow_up_date) return 'none';
    const d = diffDays(l.follow_up_date, S.today);
    if (d < 0) return 'overdue';
    if (d === 0) return 'today';
    if (d === 1) return 'soon';
    return 'later';
  }

  const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
    'October', 'November', 'December'];
  const closedMonth = (l) => (l.closed_at ? l.closed_at.slice(0, 7) : '');
  const monthLabel = (ym) => (ym ? `${MONTH_NAMES[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}` : 'No closing date');

  function listView(kind) {
    const isActive = kind === 'active';
    const stages = isActive ? S.open_stages : CLOSED_STAGES;
    const f = filters[kind];
    const pool = S.leads.filter((l) => stages.includes(l.stage));

    const wrap = h('div', { class: 'lead-list' });
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Filter by stage' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const activeFilters = h('div', { class: 'active-filters' });
    const results = h('div', { class: 'lead-groups' });

    const search = h('input', {
      type: 'search', placeholder: 'Search name, phone, site, notes', 'aria-label': 'Search leads',
      value: f.q,
      oninput: (e) => { f.q = e.target.value; refresh(); },
    });
    const searchRow = h('div', { class: 'search-row' }, search);

    // Area/service/source/date filters - mainly useful for triaging fresh New enquiry leads, but they
    // apply across whichever stage chip is selected on the Active tab. Picked in a popup (openFilterPicker)
    // rather than shown inline; the ones in use show as removable chips under the count.
    let filterButton = null;
    let areas = [];
    const filterCount = () => [f.area, f.service, f.source, f.from || f.to].filter(Boolean).length;
    function renderFilterButton() {
      if (!filterButton) return;
      const n = filterCount();
      clear(filterButton).append(...[icon(...FILTER_ICON), 'Filters', n ? h('span', { class: 'filter-count' }, n) : null].filter(Boolean));
    }
    if (isActive) {
      areas = [...new Set(pool.map((l) => l.survey?.site_district).filter(Boolean))].sort();
      // A filter left over from an earlier visit (this view's state persists across tab switches) can
      // point at a value that no longer applies here - drop it instead of silently hiding everything.
      if (f.area && !areas.includes(f.area)) f.area = '';
      if (f.service && !S.settings.services.includes(f.service)) f.service = '';
      if (f.source && !S.settings.sources.includes(f.source)) f.source = '';

      filterButton = h('button', { type: 'button', class: 'link-btn filter-btn' });
      filterButton.onclick = async () => {
        await openFilterPicker(f, { areas });
        renderFilterButton();
        refresh();
      };
      renderFilterButton();
    }

    function renderActiveFilters() {
      clear(activeFilters);
      if (!isActive) return;
      const range = (f.from || f.to) ? `${f.from ? fmtDate(f.from) : '…'} – ${f.to ? fmtDate(f.to) : '…'}` : '';
      [['area', f.area], ['service', f.service], ['source', f.source], ['date', range]].forEach(([key, text]) => {
        if (!text) return;
        activeFilters.append(h('button', {
          type: 'button', class: 'active-filter', 'aria-label': `Remove filter ${text}`,
          onclick: () => {
            if (key === 'date') { f.from = ''; f.to = ''; } else f[key] = '';
            renderFilterButton();
            refresh();
          },
        }, text, h('span', { class: 'active-filter-x', 'aria-hidden': 'true' }, '×')));
      });
    }

    function renderChips() {
      clear(chips);
      const options = [['', 'All', pool.length], ...stages.map((s) => [s, s, pool.filter((l) => l.stage === s).length])];
      for (const [value, label, n] of options) {
        const short = SHORT_STAGE[label];
        chips.append(h('button', {
          class: 'filter-chip', type: 'button', 'aria-pressed': String(f.stage === value),
          onclick: () => { f.stage = value; renderChips(); refresh(); },
        }, short && short !== label
          ? [h('span', { class: 'lbl-full' }, label), h('span', { class: 'lbl-short', 'aria-hidden': 'true' }, short)]
          : label,
        h('span', { class: 'n' }, n)));
      }
    }

    function emptyState(message, action) {
      return h('div', { class: 'empty-state' }, h('p', {}, message), action);
    }

    function refresh() {
      const q = f.q.trim().toLowerCase();
      const items = pool.filter((l) => {
        if (f.stage && l.stage !== f.stage) return false;
        if (isActive) {
          if (f.area && l.survey?.site_district !== f.area) return false;
          if (f.service && !(l.services.includes(f.service) || l.service === f.service)) return false;
          if (f.source && l.source !== f.source) return false;
          const day = l.created_at.slice(0, 10);
          if (f.from && day < f.from) return false;
          if (f.to && day > f.to) return false;
        }
        if (!q) return true;
        const sv = l.survey || {};
        return [l.company, l.contact_name, l.phone, l.email, sv.site_pincode, sv.site_city, sv.site_district, sv.site_state,
          sv.site_address, sv.site_category, serviceLabel(l), l.notes]
          .some((v) => (v || '').toLowerCase().includes(q));
      });
      items.sort(isActive ? byFollowUp : (a, b) => (b.closed_at || '').localeCompare(a.closed_at || ''));

      count.textContent = `${plural(items.length, 'lead', 'leads')} · ${isActive ? 'by follow-up' : 'by closing date'}`;
      renderActiveFilters();
      clear(results);
      if (!items.length) {
        results.append(pool.length
          ? emptyState('No leads match this search.')
          : isActive
            ? emptyState('No active leads yet.', h('a', { class: 'btn primary', href: '#add' }, 'Add lead'))
            : emptyState('Nothing won or lost yet. Open a lead and tap Mark won or Mark lost.'));
        return;
      }

      // Active: grouped by how urgent the follow-up is. Won / Lost: by the month it closed, newest first.
      const groups = isActive
        ? FOLLOW_GROUPS.map((g) => ({ ...g, items: items.filter((l) => followBucket(l) === g.key) }))
        : [...new Set(items.map(closedMonth))].map((ym) => ({ key: 'month', label: monthLabel(ym), items: items.filter((l) => closedMonth(l) === ym) }));
      groups.filter((g) => g.items.length).forEach((g) => results.append(h('section', { class: 'lead-group' },
        h('h3', { class: `group-head group-${g.key}` }, g.label, h('span', { class: 'group-count' }, g.items.length)),
        h('ul', { class: 'card-group rows' }, g.items.map((l) => h('li', {}, leadRow(l, isActive)))))));
    }

    // Column headers for the wide-screen row layout only - the phone layout below 820px stacks each
    // row's pieces instead, where a header naming six "columns" wouldn't line up with anything.
    const rowHead = h('div', { class: 'row-head', 'aria-hidden': 'true' },
      h('span', {}, 'Lead'), h('span', {}, 'Service'), h('span', {}, 'Stage'),
      h('span', {}, 'Value / round'), h('span', {}, 'Follow-up'), isActive ? h('span', {}, 'Added') : null);

    wrap.append(...[
      searchRow,
      chips,
      h('div', { class: 'list-meta' }, count, filterButton),
      activeFilters,
      rowHead,
      results].filter(Boolean));
    if (!isActive) {
      wrap.append(h('p', { class: 'export-note' }, h('a', { href: $('#view').dataset.exportUrl }, 'Export all leads as CSV')));
    }
    renderChips();
    refresh();
    return wrap;
  }

  // How far along the pipeline a lead is, as filled segments of a bar with one segment per open stage
  // (New enquiry ... Work order & advance). A closed lead fills every segment in its Won / Lost colour.
  function pipeBar(l) {
    const total = STAGE_ORDER.length;
    const filled = CLOSED_STAGES.includes(l.stage) ? total : STAGE_ORDER.indexOf(l.stage) + 1;
    return h('span', { class: 'pipe', 'data-stage': l.stage, 'aria-hidden': 'true' },
      STAGE_ORDER.map((_, i) => h('i', { class: i < filled ? 'on' : null })));
  }

  function leadRow(l, showCreated) {
    const sub = [subtitle(l), S.me.is_admin && l.owner_name ? `Owner: ${l.owner_name}` : ''].filter(Boolean).join(' · ');
    // The figure to show next to the original estimate - not below it - so a lead being negotiated
    // down (or up) is visible without opening it, in the same single-line cell rather than growing the
    // row onto a second line. Once a round is marked Finalized that's the number that matters, even if
    // a later (still-open) round exists after it - otherwise it stays the most recent round. If more than
    // one round is ticked Finalized, the latest one is the deal that stands.
    const rounds = l.negotiations || [];
    const shownRound = [...rounds].reverse().find((r) => r.finalized) || (rounds.length ? rounds[rounds.length - 1] : null);
    const roundText = shownRound && shownRound.estimate != null
      ? `R${shownRound.round_no}${shownRound.finalized ? ' ✓' : ''} ${fmtShortMoney(shownRound.estimate)}` : null;
    const latestRound = rounds.length ? rounds[rounds.length - 1].round_no : null;
    const area = l.survey?.site_city || l.survey?.site_district;
    return h('button', { class: 'row', type: 'button', onclick: () => openDrawer(l.id) },
      h('span', { class: 'row-main' },
        h('span', { class: 'row-title' }, title(l)),
        sub ? h('span', { class: 'row-sub' }, sub) : null),
      h('span', { class: 'row-service' }, serviceLabel(l),
        area ? h('span', { class: 'row-area' }, ` · ${area}`) : null),
      h('span', { class: 'row-stage' },
        pipeBar(l),
        h('span', { class: 'stage-tag', 'data-stage': l.stage }, l.stage,
          l.stage === 'Negotiation' && latestRound ? h('span', { class: 'stage-round' }, ` · R${latestRound}`) : null)),
      h('span', { class: 'row-value' },
        l.est_value !== null ? fmtShortMoney(l.est_value) : '',
        roundText ? h('span', { class: `row-round${shownRound.finalized ? ' finalized' : ''}` }, roundText) : null),
      h('span', { class: 'row-chip' }, followChip(l)),
      showCreated ? h('span', { class: 'row-created' }, fmtDateTime(l.created_at)) : null,
    );
  }

  /* ---------- drawer ---------- */

  const drawer = $('#drawer');
  const overlay = $('#overlay');

  // closeDrawer is passed around as a stable callback (buildLeadForm's onSaved, the overlay's click
  // listener, swipeToClose...), so it can never itself be swapped out - the back-gesture hookup instead
  // lives in this one flag, set each time a drawer opens and consulted each time one closes.
  let drawerPopHandler = null;

  function openDrawer(id) {
    const lead = S.leads.find((l) => l.id === id);
    if (!lead) return;
    lastFocus = document.activeElement;
    openId = id;
    buildDrawer(lead);
    overlay.hidden = false;
    drawer.hidden = false;
    document.body.classList.add('locked');
    $('#drawer-title').focus();
    loadActivity(lead.id);
    drawerPopHandler = () => closeDrawer(true);
    window.addEventListener('popstate', drawerPopHandler);
    history.pushState({ ldOverlay: 'drawer' }, '', location.href);
  }

  function closeDrawer(fromPopstate) {
    if (openId === undefined) return;
    openId = undefined;
    drawer.hidden = true;
    clear(drawer);
    overlay.hidden = true;
    document.body.classList.remove('locked');
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    if (drawerPopHandler) {
      window.removeEventListener('popstate', drawerPopHandler);
      drawerPopHandler = null;
      // closeDrawer is also used directly as a DOM event handler (the overlay's click, the × button), so
      // an Event object can land here as this argument - only the popstate path itself passes true.
      if (fromPopstate !== true) history.back();
    }
  }

  function buildLeadForm(lead, onSaved) {
    const L = lead || {
      company: '', contact_name: '', phone: '', email: '', service: '', services: [], source: '',
      est_value: null, quote_sent_date: null, stage: S.stages[0], follow_up_date: null, client_id: null,
      enquired_by_id: null,
    };
    const inputs = {};

    const wrapField = (name, label, control, cls = '', required = false) => {
      control.id = `f-${name}`;
      control.name = name;
      control.setAttribute('aria-describedby', `err-${name}`);
      inputs[name] = control;
      return h('div', { class: `field ${cls}` },
        h('label', { for: `f-${name}` }, label, required ? h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *') : null),
        control,
        h('p', { class: 'err', id: `err-${name}`, role: 'alert' }));
    };

    const text = (type, value, extra = {}) => h('input', { type, value: value ?? '', ...extra });
    const area = (rows, value) => { const t = h('textarea', { rows }); t.value = value ?? ''; return t; };
    const choice = (options, value, blank) => {
      const list = [...options];
      if (value && !list.includes(value)) list.push(value);   // keep a value that was removed from Settings
      const items = blank ? [{ value: '', label: blank }, ...list] : list;
      return selectField(items, value || '', { title: blank || 'Choose an option', placeholder: blank || '' });
    };

    const dateInput = dateField(L.follow_up_date);
    const quick = h('div', { class: 'quick-dates' },
      SNOOZE.map(([label, days]) => h('button', {
        class: 'btn small', type: 'button',
        onclick: () => { dateInput.value = addDays(S.today, days); },
      }, label)));

    // Every new lead is for a company we haven't worked with yet - it's only mapped to a client (an
    // existing one, or a new one) once it's won; see markOutcome below. A lead already carrying a
    // client_id here is a legacy one won before that change, or the record of an already-won lead -
    // company/contact fields stay hidden for it since the client already has those on file.
    let companyFields = null;

    const serviceBoxes = S.service_options.map((opt) => {
      const cb = h('input', { type: 'checkbox', value: String(opt.id) });
      cb.checked = (L.services || []).includes(opt.name);
      return { id: opt.id, box: h('label', { class: 'check-row' }, cb, h('span', {}, opt.name)) };
    });
    const serviceField = h('div', { class: 'field wide' },
      h('label', {}, 'Services', h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *')),
      h('div', { class: 'check-grid' }, serviceBoxes.map((s) => s.box)),
      h('p', { class: 'err', id: 'err-service_ids', role: 'alert' }));

    // Who took the call - also the default pick for "surveyed by" below, since it's usually the same
    // person, though the survey can always be reassigned to whoever actually went out.
    const enquiredBySel = selectField(
      [{ value: '', label: 'Not set' }, ...S.staff.map((w) => ({ value: w.id, label: w.name }))],
      L.enquired_by_id ?? '', { title: 'Enquired by', placeholder: 'Not set' });

    const errorBox = h('div', { class: 'form-error', role: 'alert', tabindex: '-1', hidden: true });
    const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, lead ? 'Save changes' : 'Add lead');

    companyFields = h('div', { class: 'form-grid', hidden: !!L.client_id },
      wrapField('company', 'Company', text('text', L.company, { maxlength: 160, autocomplete: 'off' }), '', true),
      wrapField('contact_name', 'Contact person', text('text', L.contact_name, { maxlength: 120, autocomplete: 'off' }), '', true));

    const enquiryFields = [
      wrapField('phone', 'Phone', text('tel', L.phone, { maxlength: 40, autocomplete: 'off' }), '', true),
      wrapField('email', 'Email', text('email', L.email, { maxlength: 160, autocomplete: 'off' })),
      serviceField,
      wrapField('source', 'Source', choice(S.settings.sources, L.source, 'Not set'), '', true),
      wrapField('enquired_by_id', 'Enquired by', enquiredBySel, '', true),
      h('div', { class: 'field wide' },
        wrapField('follow_up_date', 'Follow-up date', dateInput, '', true),
        quick),
    ];

    // Read only, one line - the stage moves on its own, as each step's own fields are completed (or
    // via Mark won / Mark lost), never by picking a value here directly.
    let stageField = null;
    if (lead) {
      const stageDisplay = choice(isOpen(lead) ? S.open_stages : S.stages, L.stage);
      stageDisplay.disabled = true;
      stageDisplay.id = 'f-stage';
      stageDisplay.name = 'stage';
      stageDisplay.setAttribute('aria-describedby', 'err-stage');
      inputs.stage = stageDisplay;
      stageField = h('p', { class: 'current-stage' },
        h('span', { class: 'current-stage-label' }, 'Current stage: '),
        h('span', { class: 'current-stage-value' }, L.stage),
        h('span', { class: 'err', id: 'err-stage', role: 'alert' }));
    }

    // Quote sent's fields (and, below, Site survey's) are built into this same <form> so one Save
    // changes button submits everything together - no separate per-stage save button. Each is rendered
    // as a separate DOM node so the caller can place it in pipeline order; its inputs still land in
    // `inputs`/get submitted normally since the submit handler reads them by JS reference, not by DOM
    // position.
    let form;
    let quoteSection = null;
    let surveySectionNode = null;
    let surveyBody = null;              // set only when the survey section exists - read by the submit handler
    let surveyCheck = () => [];         // the survey controls that must be filled before saving
    let negotiationCheck = () => [];    // same, for the first negotiation round
    let roundRequested = false;         // Save round was tapped - the first round's fields are then required
    let negotiationSectionNode = null;
    let negotiationBody = null;         // set only when this is the lead's first (stage-advancing) round
    let workOrderSectionNode = null;
    if (!lead) {
      // Creating: one flat form, same as always - the stage accordion only makes sense once a lead exists.
      form = h('form', { novalidate: true, id: 'lead-form' },
        errorBox, companyFields,
        h('div', { class: 'form-grid' }, enquiryFields));
    } else {
      const expand = nextStageIndex(lead);
      const surveyDone = !!(lead.survey && lead.survey.survey_date);
      const quoteSent = !!lead.quote_sent_date;
      // -1 for a closed lead (Won/Lost aren't in STAGE_ORDER) - nothing is "current" on one of those, so
      // every stage section reads as past and locks read-only, same as if it had moved beyond each one.
      const stageIndex = STAGE_ORDER.indexOf(lead.stage);
      const isPastStage = (stage) => stageIndex === -1 || stageIndex > STAGE_ORDER.indexOf(stage);

      // Site survey - editable while it's either already done or exactly what's next; once the lead has
      // moved on to Quote sent or beyond, it's read-only history (see isPastStage below).
      const sv = lead.survey || {};
      const defaultSurveyor = sv.surveyor_id ?? lead.enquired_by_id;
      const surveyDateInput = dateField(sv.survey_date || '');
      const surveyorSel = selectField(
        [{ value: '', label: 'Not set' }, ...S.staff.map((w) => ({ value: w.id, label: w.name }))],
        defaultSurveyor ?? '', { title: 'Surveyed by', placeholder: 'Not set' });
      const repName = h('input', { type: 'text', value: sv.rep_name || '', maxlength: 120 });
      const repRole = h('input', { type: 'text', value: sv.rep_role || '', maxlength: 60, placeholder: 'Manager, guard, ...' });
      const repPhone = h('input', { type: 'tel', value: sv.rep_phone || '', maxlength: 40 });

      // Site details - captured here, not at New enquiry, since they're what the survey itself confirms.
      const siteCategorySel = choice(S.settings.site_categories, sv.site_category, 'Not set');
      const siteState = h('input', { type: 'text', value: sv.site_state || '', maxlength: 80, autocomplete: 'off' });
      const siteDistrict = h('input', { type: 'text', value: sv.site_district || '', maxlength: 80, autocomplete: 'off' });
      const siteCity = h('input', { type: 'text', value: sv.site_city || '', maxlength: 120, autocomplete: 'off' });
      const siteAddress = area(2, sv.site_address);
      // Typing a full pincode fills state, district and city. They stay editable if the lookup is wrong or missing.
      const pinHint = h('p', { class: 'hint', 'aria-live': 'polite' });
      let pinSeq = 0;
      const pinInput = text('text', sv.site_pincode, { maxlength: 6, inputmode: 'numeric', autocomplete: 'off' });
      pinInput.addEventListener('input', async () => {
        const pin = pinInput.value.replace(/\D/g, '').slice(0, 6);
        if (pinInput.value !== pin) pinInput.value = pin;
        const mine = ++pinSeq;
        if (pin.length < 6) { pinHint.textContent = ''; return; }
        pinHint.textContent = 'Looking up…';
        try {
          const found = await api(`/api/pincode/${pin}`);
          if (mine !== pinSeq) return;
          siteState.value = found.state;
          siteDistrict.value = found.district;
          siteCity.value = found.city;
          pinHint.textContent = `${found.city}, ${found.district}, ${found.state}`;
        } catch (err) {
          if (mine === pinSeq) pinHint.textContent = err.message;
        }
      });
      const pinField = reqField('Site pincode', pinInput);
      pinField.append(pinHint);
      const siteAddressField = reqField('Site address', siteAddress);
      siteAddressField.classList.add('wide');

      const surveyErr = h('p', { class: 'err', role: 'alert' });
      // Once any part of the survey is entered (or it was already saved), every survey box must be filled.
      // Surveyed by is left out of "started" since it's prefilled with whoever took the enquiry.
      const siteControls = [siteCategorySel, pinInput, siteState, siteDistrict, siteCity, siteAddress];
      surveyCheck = () => (sv.survey_date || [surveyDateInput, repName, repRole, repPhone, ...siteControls].some((c) => c.value.trim())
        ? [surveyDateInput, surveyorSel, repName, repRole, repPhone, ...siteControls] : []);
      surveyBody = () => ({
        survey_date: surveyDateInput.value || null, surveyor_id: surveyorSel.value || null,
        rep_name: repName.value, rep_role: repRole.value, rep_phone: repPhone.value,
        site_category: siteCategorySel.value, site_pincode: pinInput.value, site_state: siteState.value,
        site_district: siteDistrict.value, site_city: siteCity.value, site_address: siteAddress.value,
      });

      if (lead.stage === 'New enquiry' && !sv.survey_date) {
        const updateSaveLabel = () => {
          saveBtn.textContent = surveyDateInput.value ? 'Save & move to Site survey' : 'Save changes';
        };
        surveyDateInput.addEventListener('input', updateSaveLabel);
        surveyDateInput.addEventListener('change', updateSaveLabel);
        updateSaveLabel();
      }

      const surveyLocked = isPastStage('Site survey');
      const photoGrid = h('div', { class: 'photo-grid' });
      function renderPhotos() {
        clear(photoGrid);
        (lead.survey?.photos || []).forEach((p) => photoGrid.append(h('div', { class: 'photo-thumb' },
          h('a', { href: p.url, target: '_blank', rel: 'noopener noreferrer' }, h('img', { src: p.url, alt: 'Site photo' })),
          surveyLocked ? null : h('button', {
            class: 'icon-x', type: 'button', 'aria-label': 'Remove photo',
            onclick: async () => {
              await api(`/api/leads/${lead.id}/survey/photos/${p.id}`, { method: 'DELETE' });
              lead.survey.photos = lead.survey.photos.filter((x) => x.id !== p.id);
              renderPhotos();
            },
          }, '×'))));
      }
      renderPhotos();

      const fileInput = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', multiple: true });
      fileInput.onchange = async () => {
        if (!fileInput.files.length) return;
        if (!lead.survey) { surveyErr.textContent = 'Save the survey details first'; fileInput.value = ''; return; }
        const body = new FormData();
        for (const f of fileInput.files) body.append('photos', f);
        try {
          const res = await fetch(`/api/leads/${lead.id}/survey/photos`, { method: 'POST', body, credentials: 'same-origin' });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || 'Could not upload the photo');
          lead.survey = data.survey;
          renderPhotos();
          toast('Photos added');
        } catch (e) { surveyErr.textContent = e.message; }
        fileInput.value = '';
      };

      if (surveyLocked) {
        [surveyDateInput, surveyorSel, repName, repRole, repPhone, ...siteControls].forEach((c) => { c.disabled = true; });
      }
      surveySectionNode = h('details', { class: 'stage-section', open: expand === 1 },
        h('summary', { class: 'stage-section-title' }, 'Site survey'),
        h('div', { class: 'stage-section-body' },
          h('div', { class: 'form-grid' },
            reqField('Survey date', surveyDateInput), reqField('Surveyed by', surveyorSel),
            reqField('Site representative', repName), reqField('Role (manager, guard, ...)', repRole),
            reqField('Representative phone', repPhone),
            reqField('Site category', siteCategorySel), pinField,
            reqField('State', siteState), reqField('District', siteDistrict), reqField('City', siteCity),
            siteAddressField),
          surveyErr,
          h('p', { class: 'hint' }, 'Site photos'), photoGrid,
          surveyLocked ? null : h('label', { class: 'btn small' }, 'Add photos', fileInput)));

      const quoteFields = h('div', { class: 'form-grid' },
        wrapField('quote_sent_date', 'Quote sent', dateField(L.quote_sent_date), '', true),
        wrapField('est_value', `Estimated value (${S.settings.currency})`,
          text('number', L.est_value, { min: '0', step: 'any', inputmode: 'decimal' }), '', true));
      quoteSection = h('details', { class: `stage-section${surveyDone ? '' : ' locked'}`, open: surveyDone && expand === 2 },
        h('summary', { class: 'stage-section-title' }, 'Quote sent'),
        h('div', { class: 'stage-section-body' }, quoteFields));

      if (!surveyDone) {
        // Nothing about a quote can be entered before the survey it depends on exists - lock the fields
        // and explain why, rather than letting someone type into a section that will just be rejected.
        inputs.quote_sent_date.disabled = true;
        inputs.est_value.disabled = true;
        quoteSection.querySelector('summary').addEventListener('click', (e) => {
          e.preventDefault();
          toast('Complete the site survey first', true);
        });
      } else if (isPastStage('Quote sent')) {
        // Already done, and the lead has moved on - viewable, but read only, same as Site survey above.
        inputs.quote_sent_date.disabled = true;
        inputs.est_value.disabled = true;
      } else if (lead.stage === 'Site survey' && !lead.quote_sent_date) {
        // Sending the quote for the first time is what completes Site survey's own step - make that
        // outcome visible on the button itself, before it's clicked, instead of only in the toast after.
        const quoteDateInput = inputs.quote_sent_date;
        const updateSaveLabel = () => {
          saveBtn.textContent = quoteDateInput.value ? 'Save & move to Quote sent' : 'Save changes';
        };
        quoteDateInput.addEventListener('input', updateSaveLabel);
        quoteDateInput.addEventListener('change', updateSaveLabel);
        updateSaveLabel();
      }

      // Negotiation's first round is what completes Quote sent's own step, so - same as the survey and
      // quote sections above - it rides along with the one Save changes button instead of a button of its
      // own. Once a round already exists, further rounds are a repeatable list of their own (edited below,
      // in negotiationSection) rather than something one Save button can represent.
      const hasRounds = (lead.negotiations || []).length > 0;
      if (!hasRounds) {
        const negDateInput = dateField('', { placeholder: 'Round date' });
        const negPerson = h('input', { type: 'text', maxlength: 120 });
        const negEstimate = h('input', { type: 'number', min: '0', step: 'any', inputmode: 'decimal', placeholder: `Amount (${S.settings.currency})` });
        const negFinalized = h('input', { type: 'checkbox' });
        const negStarted = () => roundRequested || negFinalized.checked
          || [negDateInput, negPerson, negEstimate].some((c) => c.value.trim());
        negotiationCheck = () => (negStarted() ? [negDateInput, negPerson, negEstimate] : []);
        negotiationBody = () => (negStarted() ? {
          date: negDateInput.value, authorized_person: negPerson.value,
          estimate: negEstimate.value === '' ? null : negEstimate.value, finalized: negFinalized.checked,
        } : null);

        const negFields = h('div', { class: 'form-grid' },
          reqField('Round date', negDateInput),
          reqField('Authorized person', negPerson),
          reqField(`Estimate (${S.settings.currency})`, negEstimate),
          h('label', { class: 'check-row wide' }, negFinalized, h('span', {}, 'Finalized')));
        // Its own Save round button, same as later rounds have - it still goes through the one Save changes
        // submit (so the lead's other edits and the move to Negotiation land together), just with the
        // round's fields required even if all of them were left empty.
        const saveRoundBtn = h('button', {
          class: 'btn small', type: 'button', onclick: () => { roundRequested = true; saveBtn.click(); },
        }, 'Save round');
        negotiationSectionNode = h('details', { class: `stage-section${quoteSent ? '' : ' locked'}`, open: quoteSent && expand === 3 },
          h('summary', { class: 'stage-section-title' }, 'Negotiation'),
          h('div', { class: 'stage-section-body' },
            h('div', { class: 'negotiation-round' },
              h('p', { class: 'negotiation-round-label' }, 'Round 1 (new)'),
              negFields, h('div', { class: 'round-actions' }, saveRoundBtn))));

        if (!quoteSent) {
          negotiationSectionNode.querySelector('summary').addEventListener('click', (e) => {
            e.preventDefault();
            toast('Send a quote first', true);
          });
        } else {
          const updateSaveLabel = () => {
            saveBtn.textContent = negDateInput.value ? 'Save & move to Negotiation' : 'Save changes';
          };
          negDateInput.addEventListener('input', updateSaveLabel);
          negDateInput.addEventListener('change', updateSaveLabel);
          updateSaveLabel();
        }
      }

      // Work order & advance: a single one-time set of fields, not a repeatable list like negotiation -
      // entering them is what completes Negotiation's own step, once a round has been finalized.
      const negotiationFinalized = (lead.negotiations || []).some((n) => n.finalized);
      const workOrderFields = h('div', { class: 'form-grid' },
        wrapField('work_order_no', 'Work order no.', text('text', L.work_order_no, { maxlength: 60, autocomplete: 'off' }), '', true),
        wrapField('work_order_date', 'Work order date', dateField(L.work_order_date), '', true),
        wrapField('advance_amount', `Advance received (${S.settings.currency})`,
          text('number', L.advance_amount, { min: '0', step: 'any', inputmode: 'decimal' }), '', true),
        wrapField('advance_date', 'Advance date', dateField(L.advance_date), '', true));
      workOrderSectionNode = h('details', { class: `stage-section${negotiationFinalized ? '' : ' locked'}`, open: negotiationFinalized && expand === 4 },
        h('summary', { class: 'stage-section-title' }, 'Work order & advance'),
        h('div', { class: 'stage-section-body' }, workOrderFields));

      if (!negotiationFinalized) {
        // Nothing here can be entered before a negotiation round is finalized - lock the fields and
        // explain why, same as the quote section does while the survey is still open.
        ['work_order_no', 'work_order_date', 'advance_amount', 'advance_date'].forEach((name) => { inputs[name].disabled = true; });
        workOrderSectionNode.querySelector('summary').addEventListener('click', (e) => {
          e.preventDefault();
          toast('Finalize a negotiation round first', true);
        });
      } else if (isPastStage('Work order & advance')) {
        // The lead is Won or Lost - viewable, but read only, same as the earlier stages once passed.
        ['work_order_no', 'work_order_date', 'advance_amount', 'advance_date'].forEach((name) => { inputs[name].disabled = true; });
      } else if (lead.stage === 'Negotiation' && !lead.work_order_no) {
        const woInput = inputs.work_order_no;
        const updateSaveLabel = () => {
          saveBtn.textContent = woInput.value ? 'Save & move to Work order & advance' : 'Save changes';
        };
        woInput.addEventListener('input', updateSaveLabel);
        woInput.addEventListener('change', updateSaveLabel);
        updateSaveLabel();
      }

      // Once the lead has moved past New enquiry, its contact details are read only too, same as every
      // other stage - except follow-up date and notes, which stay live for the lead's whole life (the
      // overdue banner's Reschedule jumps straight to that field, and with Activity read only, Notes is
      // the one place left to add anything).
      if (isPastStage('New enquiry')) {
        ['company', 'contact_name', 'phone', 'email', 'source', 'enquired_by_id'].forEach((name) => { inputs[name].disabled = true; });
        serviceBoxes.forEach((s) => { s.box.querySelector('input').disabled = true; });
      }

      form = h('form', { novalidate: true, id: 'lead-form' },
        errorBox,
        stageField,
        h('details', { class: 'stage-section', open: expand === 0 },
          h('summary', { class: 'stage-section-title' }, 'New enquiry'),
          h('div', { class: 'stage-section-body' }, companyFields, h('div', { class: 'form-grid' }, enquiryFields))),
      );
    }

    // Won / Lost is only set by pressing Mark won / Mark lost, which saves the form with that outcome.
    let outcome = null;
    let outcomeClientId = null;
    const markOutcome = async (result) => {
      let clientId = null;
      if (result === 'Won') {
        // Winning is the moment this lead gets mapped to a client - an existing one, or a brand-new one
        // named after it. No auto-matching by name, so the admin always makes this call on purpose.
        const newLabel = `New client — ${L.company || L.contact_name}`;
        const choice = await LD.pickList(
          [{ value: '', label: newLabel }, ...S.clients.map((c) => ({ value: c.id, label: c.name }))],
          '', { title: 'Map this lead to a client' });
        if (choice === undefined) return;             // closed without choosing - don't mark it won
        clientId = choice || null;
      }
      const sure = await LD.confirm(`Mark ${title(lead)} as ${result.toLowerCase()}?`,
        { title: `Mark ${result.toLowerCase()}`, ok: `Yes, mark ${result.toLowerCase()}`, danger: result === 'Lost' });
      if (!sure) return;
      outcome = result;
      outcomeClientId = clientId;
      inputs.stage.addOption(result, result);
      inputs.stage.value = result;
      saveBtn.click();
    };

    // quoteSection's fields belong to this form (see above) but live outside it in the DOM, so error
    // display has to check both roots instead of just `form`.
    const formRoots = [form, quoteSection, surveySectionNode, negotiationSectionNode, workOrderSectionNode].filter(Boolean);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      formRoots.forEach((root) => root.querySelectorAll('.err').forEach((p) => { p.textContent = ''; }));
      Object.values(inputs).forEach((i) => i.removeAttribute('aria-invalid'));
      errorBox.hidden = true;

      const body = {};
      for (const [name, el] of Object.entries(inputs)) body[name] = el.value;
      if (body.est_value === '') body.est_value = null;
      if (!body.follow_up_date) body.follow_up_date = null;
      if ('quote_sent_date' in body && !body.quote_sent_date) body.quote_sent_date = null;
      body.enquired_by_id = body.enquired_by_id || null;
      body.service_ids = serviceBoxes.filter((s) => s.box.querySelector('input').checked).map((s) => s.id);
      if ('advance_amount' in body && body.advance_amount === '') body.advance_amount = null;
      if ('work_order_date' in body && !body.work_order_date) body.work_order_date = null;
      if ('advance_date' in body && !body.advance_date) body.advance_date = null;
      if (outcome === 'Won') body.client_id = outcomeClientId;

      saveBtn.disabled = true;
      const isNew = !lead;
      if (isNew) body.stage = S.open_stages[0];
      try {
        // Every field is required except email and notes - on Add lead and when editing - checked here, in-app,
        // rather than leaning on the browser's own native "required" popups, which would look and behave
        // unlike the rest of this form's validation.
        {
          const missing = {};
          if (!(isNew ? body.client_id : L.client_id)) {
            if (!body.company.trim()) missing.company = 'This field is required';
            if (!body.contact_name.trim()) missing.contact_name = 'This field is required';
          }
          ['phone', 'source'].forEach((name) => {
            if (!body[name].trim()) missing[name] = 'This field is required';
          });
          if (!body.service_ids.length) missing.service_ids = 'Choose at least one service';
          if (!body.enquired_by_id) missing.enquired_by_id = 'This field is required';
          if (!body.follow_up_date) missing.follow_up_date = 'This field is required';
          // Quote sent: once either box is filled (or the quote was already sent), both are required.
          if (!isNew && !inputs.quote_sent_date.disabled && (body.quote_sent_date || body.est_value !== null || lead.quote_sent_date)) {
            if (!body.quote_sent_date) missing.quote_sent_date = 'This field is required';
            if (body.est_value === null) missing.est_value = 'This field is required';
          }
          // Work order & advance: same all-or-nothing rule, once negotiation has been finalized.
          if (!isNew && !inputs.work_order_no.disabled
            && (body.work_order_no || body.work_order_date || body.advance_amount !== null || body.advance_date || lead.work_order_no)) {
            if (!body.work_order_no) missing.work_order_no = 'This field is required';
            if (!body.work_order_date) missing.work_order_date = 'This field is required';
            if (body.advance_amount === null) missing.advance_amount = 'This field is required';
            if (!body.advance_date) missing.advance_date = 'This field is required';
          }
          const stageOk = requireFilled([...surveyCheck(), ...negotiationCheck()]);
          if (Object.keys(missing).length || !stageOk) {
            Object.keys(missing).forEach((name) => inputs[name]?.closest('details')?.setAttribute('open', ''));
            throw { message: 'Check the highlighted fields', fields: missing };
          }
        }

        let res = isNew
          ? await api('/api/leads', { method: 'POST', body })
          : await api(`/api/leads/${lead.id}`, { method: 'PATCH', body });
        // Site survey has no save button of its own - whatever's in its fields rides along with the
        // same Save changes click, right after the lead's own fields land.
        if (surveyBody) res = await api(`/api/leads/${lead.id}/survey`, { method: 'PUT', body: surveyBody() });
        // Same for the first negotiation round - but only when a round date was actually entered, since
        // (unlike the survey's upsert) this always creates a new round, so an untouched section must not
        // silently log an empty one just because Save changes was clicked for some other field.
        if (negotiationBody) {
          const nb = negotiationBody();
          if (nb) res = await api(`/api/leads/${lead.id}/negotiations`, { method: 'POST', body: nb });
        }
        onSaved();
        const autoAdvanced = !isNew && !outcome && res.stage !== lead.stage;
        const undoLost = outcome === 'Lost' ? {
          actionLabel: 'Undo',
          onAction: async () => {
            try {
              await api(`/api/leads/${lead.id}`, { method: 'PATCH', body: { stage: lead.stage } });
              toast(`Back to ${lead.stage}`);
              await load();
            } catch (e) { toast(e.message, true); }
          },
        } : undefined;
        toast(isNew ? 'Lead added' : outcome ? `Marked ${outcome.toLowerCase()}`
          : autoAdvanced ? `Changes saved – moved to ${res.stage}` : 'Changes saved', undoLost);
        if (isNew && view !== 'active') window.location.hash = '#active';
        await load();
      } catch (err) {
        if (outcome) {
          inputs.stage.removeOption(outcome);
          inputs.stage.value = lead.stage;
          outcome = null;
        }
        errorBox.textContent = err.message;
        errorBox.hidden = false;
        let first = null;
        for (const [name, message] of Object.entries(err.fields || {})) {
          const p = formRoots.map((root) => root.querySelector(`#err-${name}`)).find(Boolean);
          if (p) p.textContent = message;
          if (inputs[name]) { inputs[name].setAttribute('aria-invalid', 'true'); first = first || inputs[name]; }
        }
        (first || errorBox).focus?.();
      } finally {
        saveBtn.disabled = false;
        roundRequested = false;
      }
    });

    // The save button lives outside the <form> in the drawer footer, so tie it to the form explicitly.
    saveBtn.setAttribute('form', 'lead-form');
    return { form, saveBtn, markOutcome, quoteSection, surveySectionNode, negotiationSectionNode, workOrderSectionNode };
  }

  // The pipeline as five steps across the top of the sheet: done ones green, the current one in the accent.
  const STEP_STAGES = [['New enquiry', 'New'], ['Site survey', 'Survey'], ['Quote sent', 'Quote'], ['Negotiation', 'Negot.'], ['Work order & advance', 'W.O.'], ['Won', 'Won']];
  function stageSteps(lead) {
    const lost = lead.stage === 'Lost';
    const at = STEP_STAGES.findIndex(([s]) => s === lead.stage);
    return h('ol', {
      class: `stage-steps${lost ? ' lost' : ''}`, 'aria-label': `Stage: ${lead.stage}`,
      style: `grid-template-columns: repeat(${STEP_STAGES.length}, minmax(0, 1fr))`,
    },
      STEP_STAGES.map(([stage, short], i) => {
        const state = lost ? 'lost' : i < at || lead.stage === 'Won' ? 'done' : i === at ? 'current' : 'pending';
        return h('li', { class: `step ${state}`, 'aria-current': state === 'current' ? 'step' : null },
          h('i', { 'aria-hidden': 'true' }), h('span', {}, lost && i === STEP_STAGES.length - 1 ? 'Lost' : short));
      }));
  }

  const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const dayName = (iso) => `${WEEKDAY[parseISO(iso).getUTCDay()]}, ${fmtDate(iso)}`;

  // Call / WhatsApp / Map (and Email when there is one) - a button only for what this lead has.
  function contactActions(l) {
    const sv = l.survey || {};
    const site = [sv.site_address, sv.site_city, sv.site_district, sv.site_state, sv.site_pincode].filter(Boolean).join(', ');
    const links = [
      l.phone ? h('a', { class: 'btn contact-btn call', href: `tel:${telNumber(l.phone)}` }, 'Call') : null,
      l.phone ? h('a', { class: 'btn contact-btn', href: `https://wa.me/${waNumber(l.phone)}`, target: '_blank', rel: 'noopener noreferrer' }, 'WhatsApp') : null,
      site ? h('a', { class: 'btn contact-btn', href: `https://maps.google.com/?q=${encodeURIComponent(site)}`, target: '_blank', rel: 'noopener noreferrer' }, 'Map') : null,
      l.email ? h('a', { class: 'btn contact-btn', href: `mailto:${encodeURIComponent(l.email).replace('%40', '@')}` }, 'Email') : null,
    ].filter(Boolean);
    return links.length ? h('div', { class: 'contact-actions' }, links) : null;
  }

  // What each stage card's header says on its right: "Next step" on the one that's up next, "Done" (with a
  // detail like the photo count) on finished ones. Locked ones stay dimmed with nothing extra.
  function markSections(lead, sections) {
    const next = nextStageIndex(lead);
    const rounds = lead.negotiations || [];
    const photos = (lead.survey?.photos || []).length;
    const done = [
      STAGE_ORDER.indexOf(lead.stage) > 0 || CLOSED_STAGES.includes(lead.stage),
      !!lead.survey?.survey_date,
      !!lead.quote_sent_date,
      rounds.some((r) => r.finalized) || CLOSED_STAGES.includes(lead.stage),
      !!lead.work_order_no,
    ];
    const detail = ['', photos ? ` · ${plural(photos, 'photo', 'photos')}` : '', '',
      rounds.length ? ` · ${plural(rounds.length, 'round', 'rounds')}` : '', ''];
    sections.forEach((node, i) => {
      const summary = node && node.querySelector(':scope > summary');
      if (!summary || node.classList.contains('locked')) return;
      let status = null;
      if (done[i]) status = h('span', { class: 'section-status done' }, `Done${detail[i]}`);
      else if (i === next) status = h('span', { class: 'section-status next' }, 'Next step');
      if (status) summary.append(status);
    });
  }

  // A small menu of the less-used, mostly destructive actions, sliding up from the bottom like the sheet.
  function actionSheet(actions) {
    const previous = document.activeElement;
    const cancel = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const card = h('div', { class: 'confirm-card action-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'More actions' },
      actions.map(({ label, danger, run }) => h('button', {
        class: `btn${danger ? ' danger' : ''}`, type: 'button',
        onclick: () => { finish(); run(); },
      }, label)),
      cancel);
    const overlay = h('div', { class: 'confirm-overlay sheet-overlay' }, card);
    function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); finish(); } }
    const finish = LD.closeOnBack(() => {
      window.removeEventListener('keydown', onKey, true);
      overlay.remove();
      if (previous && previous.isConnected) previous.focus();
    });
    cancel.onclick = finish;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(); });
    window.addEventListener('keydown', onKey, true);
    document.body.append(overlay);
    card.querySelector('button').focus();
  }

  // Dragging the sheet's handle down more than 80px closes it; less springs it back.
  function swipeToClose(handle) {
    let startY = null;
    handle.addEventListener('pointerdown', (e) => {
      startY = e.clientY;
      handle.setPointerCapture(e.pointerId);
      drawer.style.transition = 'none';
    });
    handle.addEventListener('pointermove', (e) => {
      if (startY === null) return;
      drawer.style.transform = `translateY(${Math.max(0, e.clientY - startY)}px)`;
    });
    const end = (e) => {
      if (startY === null) return;
      const moved = e.clientY - startY;
      startY = null;
      drawer.style.transition = '';
      drawer.style.transform = '';
      if (moved > 80) closeDrawer();
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
  }

  function buildDrawer(lead) {
    const { form, saveBtn, markOutcome, quoteSection, surveySectionNode, negotiationSectionNode, workOrderSectionNode } = buildLeadForm(lead, closeDrawer);
    const hasRounds = !!(lead && (lead.negotiations || []).length > 0);
    const negotiation = hasRounds ? negotiationSection(lead) : negotiationSectionNode;
    markSections(lead, [form.querySelector('details.stage-section'), surveySectionNode, quoteSection, negotiation, workOrderSectionNode]);

    // Mark won only once the deal is actually being negotiated, not from New enquiry onward - and only
    // for the admin, since it's the step that maps the lead to a client. Mark lost has no such gate.
    const canMarkWon = S.me.is_admin && STAGE_ORDER.indexOf(lead.stage) >= STAGE_ORDER.indexOf('Negotiation');
    // Once the work order itself is saved, Won is actually reachable (the server's own gate), so both
    // outcomes get their own row above Activity instead of staying tucked in More actions.
    const workOrderSaved = isOpen(lead) && !!lead.work_order_no;
    const outcomeRow = workOrderSaved ? h('div', { class: 'outcome-row' },
      S.me.is_admin ? h('button', { class: 'btn ok-solid', type: 'button', onclick: () => markOutcome('Won') }, 'Mark won') : null,
      h('button', { class: 'btn danger-solid', type: 'button', onclick: () => markOutcome('Lost') }, 'Mark lost')) : null;
    const moreActions = [
      !workOrderSaved && isOpen(lead) && canMarkWon ? { label: 'Mark won', run: () => markOutcome('Won') } : null,
      !workOrderSaved && isOpen(lead) ? { label: 'Mark lost', danger: true, run: () => markOutcome('Lost') } : null,
    ].filter(Boolean);
    const moreBtn = moreActions.length
      ? h('button', { class: 'btn more-btn', type: 'button', 'aria-label': 'More actions', onclick: () => actionSheet(moreActions) }, '⋯')
      : null;

    // Overdue follow-up: say so up top, with a way straight to the date field.
    const overdue = isOpen(lead) && lead.follow_up_date && diffDays(lead.follow_up_date, S.today) < 0;
    const dueBanner = overdue ? h('div', { class: 'due-banner', role: 'status' },
      h('span', {}, `Follow-up was due ${dayName(lead.follow_up_date)}`),
      h('button', {
        class: 'btn small', type: 'button',
        onclick: () => {
          const dateBtn = form.querySelector('#f-follow_up_date');
          dateBtn.closest('details')?.setAttribute('open', '');
          dateBtn.scrollIntoView({ block: 'center' });
          dateBtn.click();
        },
      }, 'Reschedule')) : null;

    const handle = h('div', { class: 'sheet-handle', 'aria-hidden': 'true' });
    swipeToClose(handle);
    const contactLine = [lead.contact_name && lead.contact_name !== title(lead) ? lead.contact_name : null,
      lead.phone ? h('span', { class: 'drawer-phone' }, lead.phone) : null].filter(Boolean);

    clear(drawer).append(
      h('div', { class: 'drawer-head' },
        handle,
        h('div', { class: 'drawer-head-row' },
          h('div', { class: 'drawer-titles' },
            h('h2', { id: 'drawer-title', tabindex: '-1' }, title(lead)),
            contactLine.length ? h('p', { class: 'drawer-sub' }, contactLine.flatMap((part, i) => (i ? [' · ', part] : [part]))) : null),
          h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close', onclick: closeDrawer }, '×')),
        contactActions(lead)),
      h('div', { class: 'drawer-scroll' },
        stageSteps(lead),
        dueBanner,
        projectBox(lead),
        form,
        surveySectionNode,
        quoteSection,
        negotiation,
        workOrderSectionNode,
        outcomeRow,
        activitySection()),
      h('div', { class: 'drawer-foot' }, saveBtn, moreBtn),
    );
  }

  /* ---------- add lead (a full screen, like the other tabs) ---------- */

  function addView() {
    const { form, saveBtn } = buildLeadForm(null, () => {});
    form.append(h('div', { class: 'form-actions' }, saveBtn));
    return h('div', { class: 'add-lead' },
      h('h2', {}, 'Add lead'),
      h('p', { class: 'hint' }, 'A new lead starts at New enquiry.'),
      form);
  }


  const plainField = (label, control) => h('div', { class: 'field' }, h('label', {}, label), control);

  // A labeled field marked required (red asterisk) with its own inline error line, for the stage fields
  // that aren't part of buildLeadForm's `inputs` - checked with requireFilled below.
  const reqField = (label, control) => {
    control._err = h('p', { class: 'err', role: 'alert' });
    return h('div', { class: 'field' },
      h('label', {}, label, h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *')),
      control, control._err);
  };

  // Flags every empty reqField control (opening its section, focusing the first); true when all are filled.
  function requireFilled(controls) {
    let first = null;
    for (const c of controls) {
      const empty = !String(c.value ?? '').trim();
      c._err.textContent = empty ? 'This field is required' : '';
      if (empty) {
        c.setAttribute('aria-invalid', 'true');
        c.closest('details')?.setAttribute('open', '');
        first = first || c;
      } else c.removeAttribute('aria-invalid');
    }
    first?.focus?.();
    return !first;
  }

  /* ---------- negotiation rounds ---------- */

  /* Only called once at least one round already exists - a lead's very first round is what completes
     Quote sent's own step, so it's handled in buildLeadForm instead, riding along with the main Save
     changes button like the survey and quote sections. This is purely "edit a past round, or log one
     more" - neither changes the stage, so each keeps its own small Save / Save round button. */
  function negotiationSection(lead) {
    const list = h('div', { class: 'negotiation-rows' });
    const err = h('p', { class: 'err', role: 'alert' });

    function buildRow(round, roundNo) {
      // A saved round is only still editable if it's the latest one and negotiation is still the current
      // stage - every earlier round is read-only history, and once the lead has moved on, so is this one.
      const editable = !round || (roundNo === lead.negotiations.length && lead.stage === 'Negotiation');
      const dateInput = dateField(round ? round.date || '' : '', { placeholder: 'Round date' });
      const person = h('input', { type: 'text', value: round ? round.authorized_person || '' : '', maxlength: 120 });
      const estimate = h('input', {
        type: 'number', min: '0', step: 'any', inputmode: 'decimal',
        value: round && round.estimate != null ? round.estimate : '', placeholder: `Amount (${S.settings.currency})`,
      });
      const finalized = h('input', { type: 'checkbox' });
      finalized.checked = !!(round && round.finalized);
      let actions = null;
      if (!editable) {
        [dateInput, person, estimate, finalized].forEach((c) => { c.disabled = true; });
      } else {
        const saveBtn = h('button', { class: 'btn small', type: 'button' }, round ? 'Save' : 'Save round');
        saveBtn.onclick = async () => {
          err.textContent = '';
          if (!requireFilled([dateInput, person, estimate])) return;
          const body = {
            date: dateInput.value || null, authorized_person: person.value,
            estimate: estimate.value === '' ? null : estimate.value, finalized: finalized.checked,
          };
          try {
            const res = round
              ? await api(`/api/leads/${lead.id}/negotiations/${round.id}`, { method: 'PATCH', body })
              : await api(`/api/leads/${lead.id}/negotiations`, { method: 'POST', body });
            lead.negotiations = res.negotiations;
            adding = false;
            renderRows();
            toast('Saved');
            // The leads list behind the drawer shows each lead's finalized (or latest) round - refresh it so
            // a round saved here shows up there straight away, not only after the next full reload.
            await load();
          } catch (e) { err.textContent = e.message; }
        };
        actions = h('div', { class: 'round-actions' }, saveBtn);
      }
      // Same one-per-line labeled layout as every other stage's fields, in place of the old cramped
      // single row - five fields side by side never had room to also show which was which.
      return h('div', { class: 'negotiation-round' },
        h('p', { class: 'negotiation-round-label' }, round ? `Round ${roundNo}` : `Round ${roundNo} (new)`),
        h('div', { class: 'form-grid' },
          reqField('Round date', dateInput), reqField('Authorized person', person),
          reqField(`Estimate (${S.settings.currency})`, estimate)),
        h('label', { class: 'check-row' }, finalized, h('span', {}, 'Finalized')),
        actions);
    }

    // A blank new round only appears after tapping "+ Add new round", and never while a round is ticked
    // Finalized - the deal is settled, so untick (and save) that round first to reopen negotiation. Once
    // the lead has moved past Negotiation, none of that is offered any more - the rounds are just history.
    let adding = false;
    function renderRows() {
      clear(list);
      lead.negotiations.forEach((r, i) => list.append(buildRow(r, i + 1)));
      if (lead.stage !== 'Negotiation') return;
      const done = lead.negotiations.find((r) => r.finalized);
      if (done) {
        list.append(h('p', { class: 'hint' },
          `Round ${lead.negotiations.indexOf(done) + 1} is finalized. Untick Finalized on it and save to add another round.`));
      } else if (adding) {
        const row = buildRow(null, lead.negotiations.length + 1);
        row.querySelector('.round-actions').append(h('button', {
          class: 'btn small', type: 'button', onclick: () => { adding = false; renderRows(); },
        }, 'Cancel'));
        list.append(row);
      } else {
        list.append(h('button', {
          class: 'btn small add-round', type: 'button', onclick: () => { adding = true; renderRows(); },
        }, '+ Add new round'));
      }
    }
    renderRows();

    const section = h('details', { class: 'stage-section', open: nextStageIndex(lead) === 3 },
      h('summary', { class: 'stage-section-title' }, 'Negotiation'),
      h('div', { class: 'stage-section-body' }, list, err));
    return section;
  }

  /* ---------- won lead -> project ---------- */

  function projectBox(lead) {
    if (lead.stage !== 'Won') return null;
    const canOpen = S.me.modules.includes('projects');
    let action;
    if (lead.project_id) {
      action = canOpen
        ? h('a', { class: 'btn', href: `/projects#p${lead.project_id}` }, 'Open project')
        : null;
    } else {
      action = h('button', {
        class: 'btn primary', type: 'button',
        onclick: async (e) => {
          if (!(await LD.confirm(`Create a client and a project from ${title(lead)}?`,
            { title: 'Create project', ok: 'Yes, create' }))) return;
          e.target.disabled = true;
          try {
            const res = await api(`/api/leads/${lead.id}/project`, { method: 'POST' });
            closeDrawer();
            toast(`Project ${res.code} created`);
            await load();
            if (canOpen) window.location.href = `/projects#p${res.project_id}`;
          } catch (err) {
            toast(err.message, true);
            e.target.disabled = false;
          }
        },
      }, 'Create project');
    }
    return h('section', { class: 'project-box' },
      h('h3', {}, lead.project_id ? 'This lead is now a project' : 'Won: next step'),
      lead.project_id
        ? (canOpen ? null : h('p', { class: 'hint' }, 'The project manager will complete the work order details.'))
        : h('p', { class: 'hint' }, 'Copy this lead into Clients and Projects so the work order details can be added.'),
      action);
  }

  /* ---------- activity log ---------- */

  function activitySection() {
    return h('details', { class: 'stage-section' },
      h('summary', { class: 'stage-section-title' },
        h('span', { id: 'activity-title' }, 'Activity'),
        h('span', { class: 'section-count', id: 'activity-count' })),
      h('div', { class: 'stage-section-body' },
        h('ul', { class: 'timeline', id: 'timeline' })));
  }

  function renderTimeline(activities) {
    const list = $('#timeline');
    if (!list) return;
    clear(list);
    const count = $('#activity-count');
    if (count) count.textContent = activities.length || '';
    activities.forEach((a) => {
      const when = new Date(a.created_at).toLocaleString('en-IN', {
        day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
      });
      list.append(h('li', { class: a.kind },
        h('span', { class: 't-text' }, a.text),
        h('time', { datetime: a.created_at }, when)));
    });
  }

  async function loadActivity(id) {
    try {
      const lead = await api(`/api/leads/${id}`);
      if (openId === id) renderTimeline(lead.activities);
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* ---------- global events ---------- */

  function resolveView() {
    const next = window.location.hash.slice(1);
    view = VIEWS.includes(next) ? next : 'active';
  }

  function syncView() {
    resolveView();
    if (S) { renderNav(); renderMain(); }
  }

  window.addEventListener('hashchange', syncView);

  // Tapping the bottom-nav item for the tab you're already on doesn't change the hash (no hashchange
  // fires) - scroll back to the top instead, same as most native apps do.
  document.querySelectorAll('.bottom-nav a[data-view]').forEach((a) => {
    a.addEventListener('click', (e) => {
      if (a.dataset.view !== view) return;
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  });

  overlay.addEventListener('click', closeDrawer);

  document.addEventListener('keydown', (e) => {
    if (openId === undefined) return;
    if (e.key === 'Escape') { closeDrawer(); return; }
    if (e.key !== 'Tab') return;

    // Keep keyboard focus inside the open drawer.
    const focusable = [...drawer.querySelectorAll('a[href], button:not([disabled]), input, select, textarea, [tabindex="0"]')]
      .filter((el) => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const at = document.activeElement;
    if (e.shiftKey && (at === first || at === drawer || at.id === 'drawer-title')) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  });

  // Pick up changes made on another device when the tab comes back into view.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && S && openId === undefined) load().catch(() => {});
  });

  function start() {
    syncView();
    load().catch((err) => {
      clear($('#view')).append(h('p', { class: 'empty-state' }, `Could not load leads. ${err.message} `,
        h('button', { class: 'link-btn', type: 'button', onclick: () => window.location.reload() }, 'Try again')));
    });
  }

  start();
})();
