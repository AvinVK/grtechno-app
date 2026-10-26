/* Leads front end. Plain JavaScript, no build step.
   All server data goes through /api/state and the lead endpoints.
   DOM is built with h() and text nodes only, never innerHTML, so lead text cannot inject markup. */
(() => {
  'use strict';

  const VIEWS = ['active', 'add'];
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
  let leadId = null;            // set only while view === 'lead' - which lead's detail is open
  let listScrollY = 0;          // where the list was scrolled to when a lead was opened from it
  // One list now covers everything - `view` is the top-level bucket (the four chips: open, overdue, Won,
  // Lost); `stage` narrows further to one open stage, picked from the Filters sheet, and still reads the
  // way it always has for anything that sets it directly.
  const filters = { leads: { q: '', view: 'open', stage: '', area: '', service: '', source: '', from: '', to: '' } };

  const { $, h, clear, api, toast, plural, selectField, searchField, dateField } = window.LD;

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

  // The site name disambiguates leads for the same company at different sites - two leads for the same
  // client otherwise look identical in a list, with no way to tell which one is which without opening it.
  const title = (l) => {
    const base = l.company || l.contact_name || l.client_name || 'Untitled lead';
    return l.survey?.site_name ? `${base} · ${l.survey.site_name}` : base;
  };
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

  function renderNav() {
    // The bottom nav has one Leads tab for every view here (the active list, the add-lead form, and a
    // lead's own detail page) - it reads "current" if its own data-view matches, or for either of the
    // other two, which have no tab of their own.
    document.querySelectorAll('.bottom-nav a[data-view]').forEach((a) => {
      const current = a.dataset.view === view || (a.dataset.view === 'active' && (view === 'add' || view === 'lead'));
      if (current) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    const badge = $('.bottom-nav .nav-badge');
    badge.textContent = S.summary.due_count;
    badge.hidden = S.summary.due_count === 0;
  }

  // Set right before a save on the lead detail page completes, so the one renderAll() its own `load()`
  // triggers afterwards is let through below - the guard right after it exists for an unrelated background
  // refresh (the page regaining focus, say) landing mid-edit, not for the save that was just made.
  let forceNextRender = false;

  function renderAll() {
    renderNav();
    if (forceNextRender) { forceNextRender = false; renderMain(); return; }
    // Refreshing data must not wipe a half-filled Add lead form, nor rebuild the lead detail page from
    // under someone mid-edit - but only once either is actually showing; a first load (straight to
    // #lead/<id>, say, or a page refresh) still needs to render normally. loadActivity already keeps its
    // own Activity list current on a background reload.
    if ((view === 'add' && $('#view .add-lead')) || (view === 'lead' && $('#view .lead-detail-page'))) return;
    renderMain();
  }

  function renderMain() {
    if (view === 'lead') {
      const lead = S.leads.find((l) => l.id === leadId);
      if (!lead) {
        clear($('#view')).append(h('p', { class: 'empty-state' }, "Can't find that lead. ", h('a', { href: '#active' }, 'Back to Leads')));
        document.title = 'Leads';
        return;
      }
      clear($('#view')).append(leadDetailView(lead));
      loadActivity(lead.id);
      document.title = `${title(lead)} · Leads`;
      return;
    }
    if (view === 'add') { clear($('#view')).append(addView()); document.title = 'New lead · Leads'; return; }
    document.title = 'Leads';
    clear($('#view')).append(listView());
    // Coming back from a lead's own page (browser back, or the back link there) lands where the list
    // was left, not back at the top - restored after the list's own content exists to scroll within.
    if (listScrollY) window.scrollTo(0, listScrollY);
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
        { key: 'stage', label: 'Stage', options: S.open_stages, allLabel: 'All stages' },
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

  // The one Leads list - what used to be three tabs (Active, Won/Lost, Status). Won and Lost are two more
  // stage chips rather than a separate screen; "All" still means the open pipeline, same as the old
  // Active tab's All did, so picking Won or Lost is always an explicit choice, not something "All" buries
  // leads in. The status dashboard collapses above the list instead of living on its own tab.
  function listView() {
    const f = filters.leads;
    const isClosed = f.view === 'Won' || f.view === 'Lost';
    const isOverdueView = f.view === 'overdue';
    const pool = isClosed ? S.leads.filter((l) => l.stage === f.view)
      : isOverdueView ? S.leads.filter((l) => isOpen(l) && l.follow_up_date && l.follow_up_date < S.today)
        : S.leads.filter(isOpen);

    const wrap = h('div', { class: 'lead-list' });
    const chips = h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'View' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });
    const activeFilters = h('div', { class: 'active-filters' });
    const results = h('div', { class: 'lead-groups' });

    const search = h('input', {
      type: 'search', placeholder: 'Search name, phone, site, notes', 'aria-label': 'Search leads',
      value: f.q,
      oninput: (e) => { f.q = e.target.value; refresh(); },
    });

    // Stage/area/service/source/date filters - mainly useful for triaging fresh New enquiry leads, but
    // they apply to whichever of Open/Overdue is picked above; Won/Lost have no use for them, same as
    // before. Picked in a popup (openFilterPicker) rather than shown inline; the ones in use show as
    // removable chips under the count.
    let filterButton = null;
    let areas = [];
    const filterCount = () => [f.stage, f.area, f.service, f.source, f.from || f.to].filter(Boolean).length;
    function renderFilterButton() {
      if (!filterButton) return;
      const n = filterCount();
      clear(filterButton).append(...[icon(...FILTER_ICON), 'Filters', n ? h('span', { class: 'filter-count' }, n) : null].filter(Boolean));
    }
    if (!isClosed) {
      areas = [...new Set(pool.map((l) => l.survey?.site_district).filter(Boolean))].sort();
      // A filter left over from an earlier visit (this state persists across the view chips) can point at
      // a value that no longer applies here - drop it instead of silently hiding everything.
      if (f.stage && !S.open_stages.includes(f.stage)) f.stage = '';
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
    const searchFilterRow = h('div', { class: 'search-filter-row' }, search, filterButton);

    function renderActiveFilters() {
      clear(activeFilters);
      if (isClosed) return;
      const range = (f.from || f.to) ? `${f.from ? fmtDate(f.from) : '…'} – ${f.to ? fmtDate(f.to) : '…'}` : '';
      [['stage', f.stage ? (SHORT_STAGE[f.stage] || f.stage) : ''], ['area', f.area], ['service', f.service],
        ['source', f.source], ['date', range]].forEach(([key, text]) => {
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

    // Four views instead of the old eight stage chips: Open (the default) and Overdue stay within the
    // open pipeline (Overdue is just Open narrowed to a late follow-up), Won/Lost are their own pool.
    // Picking a specific stage within Open/Overdue is still possible - it moved into the Filters sheet
    // above (the Stage category) instead of living here as its own chip.
    function renderChips() {
      clear(chips);
      const openPool = S.leads.filter(isOpen);
      const overdueCount = openPool.filter((l) => l.follow_up_date && l.follow_up_date < S.today).length;
      const options = [
        ['open', 'Open', openPool.length, false],
        ['overdue', 'Overdue', overdueCount, true],
        ['Won', 'Won', S.leads.filter((l) => l.stage === 'Won').length, false],
        ['Lost', 'Lost', S.leads.filter((l) => l.stage === 'Lost').length, false],
      ];
      for (const [value, label, n, signal] of options) {
        chips.append(h('button', {
          class: `filter-chip${signal ? ' tone-signal' : ''}`, type: 'button', 'aria-pressed': String(f.view === value),
          // Which pool applies (open leads, overdue leads, or one closed stage) depends on f.view, so
          // switching it needs the whole view rebuilt, not just a local refresh() of the results list.
          onclick: () => { f.view = value; if (value !== 'open' && value !== 'overdue') f.stage = ''; renderMain(); },
        }, label, h('span', { class: 'n' }, n)));
      }
    }

    function emptyState(message, action) {
      return h('div', { class: 'empty-state' }, h('p', {}, message), action);
    }

    function refresh() {
      const q = f.q.trim().toLowerCase();
      const items = pool.filter((l) => {
        if (!isClosed) {
          if (f.stage && l.stage !== f.stage) return false;
          if (f.area && l.survey?.site_district !== f.area) return false;
          if (f.service && !(l.services.includes(f.service) || l.service === f.service)) return false;
          if (f.source && l.source !== f.source) return false;
          const day = l.created_at.slice(0, 10);
          if (f.from && day < f.from) return false;
          if (f.to && day > f.to) return false;
        }
        if (!q) return true;
        const sv = l.survey || {};
        return [l.company, l.contact_name, l.phone, l.email, sv.site_name, sv.site_pincode, sv.site_city, sv.site_district, sv.site_state,
          sv.site_address, sv.site_category, serviceLabel(l), l.notes]
          .some((v) => (v || '').toLowerCase().includes(q));
      });
      items.sort(isClosed ? (a, b) => (b.closed_at || '').localeCompare(a.closed_at || '') : byFollowUp);

      count.textContent = `${plural(items.length, 'lead', 'leads')} · ${isClosed ? 'by closing date' : 'by follow-up'}`;
      renderActiveFilters();
      clear(results);
      if (!items.length) {
        results.append(pool.length
          ? emptyState('No leads match this search.')
          : isClosed
            ? emptyState('Nothing won or lost yet. Open a lead and tap Mark won or Mark lost.')
            : isOverdueView
              ? emptyState('No overdue follow-ups. Nice work!')
              : emptyState('No active leads yet.', h('a', { class: 'btn primary', href: '#add' }, 'Add lead')));
        return;
      }

      // Open / Overdue: grouped by how urgent the follow-up is. Won / Lost: by the month it closed, newest first.
      const groups = isClosed
        ? [...new Set(items.map(closedMonth))].map((ym) => ({ key: 'month', label: monthLabel(ym), items: items.filter((l) => closedMonth(l) === ym) }))
        : FOLLOW_GROUPS.map((g) => ({ ...g, items: items.filter((l) => followBucket(l) === g.key) }));
      groups.filter((g) => g.items.length).forEach((g) => results.append(h('section', { class: 'lead-group' },
        h('h3', { class: `group-head group-${g.key}` }, g.label, h('span', { class: 'group-count' }, g.items.length)),
        h('ul', { class: 'card-group rows' }, g.items.map((l) => h('li', {}, leadRow(l, !isClosed)))))));
    }

    // Column headers for the wide-screen row layout only - the phone layout below 820px stacks each
    // row's pieces instead, where a header naming six "columns" wouldn't line up with anything.
    const rowHead = h('div', { class: 'row-head', 'aria-hidden': 'true' },
      h('span', {}, 'Lead'), h('span', {}, 'Service'), h('span', {}, 'Stage'),
      h('span', {}, 'Value / round'), h('span', {}, 'Follow-up'), !isClosed ? h('span', {}, 'Added') : null);

    wrap.append(...[
      chips,
      searchFilterRow,
      count,
      activeFilters,
      rowHead,
      results].filter(Boolean));
    if (isClosed) {
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
    const sub = [subtitle(l), l.enquired_by_name ? `Brought by: ${l.enquired_by_name}` : '', S.me.is_admin && l.owner_name ? `Owner: ${l.owner_name}` : '']
      .filter(Boolean).join(' · ');
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
    // Where this lead stands in the 5-step pipeline, as "n / 5" - not shown once it's closed, since
    // Won/Lost aren't a position on that pipeline, they're where it ended.
    const stepNum = STAGE_ORDER.indexOf(l.stage) + 1;
    return h('a', { class: 'row', href: `#lead/${l.id}` },
      h('span', { class: 'row-main' },
        h('span', { class: 'row-title' }, title(l)),
        sub ? h('span', { class: 'row-sub' }, sub) : null),
      h('span', { class: 'row-service' }, serviceLabel(l),
        area ? h('span', { class: 'row-area' }, ` · ${area}`) : null),
      h('span', { class: 'row-stage' },
        pipeBar(l),
        h('span', { class: 'stage-tag', 'data-stage': l.stage }, l.stage,
          l.stage === 'Negotiation' && latestRound ? h('span', { class: 'stage-round' }, ` · R${latestRound}`) : null),
        stepNum > 0 ? h('span', { class: 'step-tag' }, `${stepNum} / ${STAGE_ORDER.length}`) : null),
      h('span', { class: 'row-value' },
        l.est_value !== null ? fmtShortMoney(l.est_value) : '',
        roundText ? h('span', { class: `row-round${shownRound.finalized ? ' finalized' : ''}` }, roundText) : null),
      h('span', { class: 'row-chip' }, followChip(l)),
      showCreated ? h('span', { class: 'row-created' }, fmtDateTime(l.created_at)) : null,
    );
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

    // Who took the call - sales only. Also the default pick for "surveyed by" below, since it's usually
    // the same person, though the survey can always be reassigned to whoever actually went out. A lead
    // already attributed to someone outside sales (set before this list existed, or since moved role)
    // keeps showing that name rather than silently going blank - and blocking - on the next save.
    const enquiryOptions = S.enquiry_staff.map((w) => ({ value: w.id, label: w.name }));
    if (L.enquired_by_id && !enquiryOptions.some((o) => o.value === L.enquired_by_id)) {
      enquiryOptions.push({ value: L.enquired_by_id, label: L.enquired_by_name || 'Previously picked' });
    }
    const enquiredBySel = searchField(
      [{ value: '', label: 'Not set' }, ...enquiryOptions],
      L.enquired_by_id ?? '', { placeholder: 'Not set' });

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
    let negotiationSectionNode = null;
    let negotiationBody = null;         // set only when this is the lead's first (stage-advancing) round
    let workOrderSectionNode = null;
    let woServiceBoxes = null;          // set only once Work order & advance exists - read by the submit handler
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
      const surveyorSel = searchField(
        [{ value: '', label: 'Not set' }, ...S.staff.map((w) => ({ value: w.id, label: w.name }))],
        defaultSurveyor ?? '', { placeholder: 'Not set' });
      const repName = h('input', { type: 'text', value: sv.rep_name || '', maxlength: 120 });
      const repRole = h('input', { type: 'text', value: sv.rep_role || '', maxlength: 60, placeholder: 'Manager, guard, ...' });
      const repPhone = h('input', { type: 'tel', value: sv.rep_phone || '', maxlength: 40 });

      // Site details - captured here, not at New enquiry, since they're what the survey itself confirms.
      // Site name is what tells this site apart from another one at the same client - shown everywhere
      // this lead (and the project it becomes) is listed, see title() above.
      const siteNameInput = h('input', { type: 'text', value: sv.site_name || '', maxlength: 160, autocomplete: 'off' });
      const siteCategorySel = LD.categoryPicker(S.settings.site_categories, sv.site_category, { blank: 'Not set', title: 'Site category' });
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
      const siteControls = [siteNameInput, siteCategorySel, pinInput, siteState, siteDistrict, siteCity, siteAddress];
      surveyCheck = () => (sv.survey_date || [surveyDateInput, repName, repRole, repPhone, ...siteControls].some((c) => c.value.trim())
        ? [surveyDateInput, surveyorSel, repName, repRole, repPhone, ...siteControls] : []);
      surveyBody = () => ({
        survey_date: surveyDateInput.value || null, surveyor_id: surveyorSel.value || null,
        rep_name: repName.value, rep_role: repRole.value, rep_phone: repPhone.value,
        site_name: siteNameInput.value,
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

      // hidden: the "Add photos" label is the button - the browser's own "Choose files / No file chosen" widget
      // used to show inside it and stretch the row (same as the project Progress tab's photo input).
      const fileInput = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', multiple: true, hidden: true });
      // Disabled (with a hint alongside) rather than letting someone pick a file and only then finding out
      // it was refused - same rule as before (the survey must be saved first), just said up front.
      if (!lead.survey) fileInput.disabled = true;
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
            (() => { const f = reqField('Site name', siteNameInput); f.classList.add('wide'); return f; })(),
            reqField('Site representative', repName), reqField('Role (manager, guard, ...)', repRole),
            reqField('Representative phone', repPhone),
            reqField('Site category', siteCategorySel), pinField,
            reqField('State', siteState), reqField('District', siteDistrict), reqField('City', siteCity),
            siteAddressField),
          surveyErr,
          h('p', { class: 'hint' }, 'Site photos'), photoGrid,
          surveyLocked ? null : h('div', { class: 'photo-add-row' },
            h('label', { class: 'btn small' }, 'Add photos', fileInput),
            lead.survey ? null : h('span', { class: 'hint' }, 'Save the survey to add photos'))));

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
        const negStarted = () => negFinalized.checked
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
        // No Save round button of its own any more - typing anything here already makes it required
        // (negStarted above), so it just rides along with the one current-step Save button like every
        // other stage's fields do.
        negotiationSectionNode = h('details', { class: `stage-section${quoteSent ? '' : ' locked'}`, open: quoteSent && expand === 3 },
          h('summary', { class: 'stage-section-title' }, 'Negotiation'),
          h('div', { class: 'stage-section-body' },
            h('div', { class: 'negotiation-round' },
              h('p', { class: 'negotiation-round-label' }, 'Round 1 (new)'),
              negFields)));

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

      // Scope often shifts right here - "can you knock off this service" or "add one more" - once the
      // client has seen a number. A second, editable checklist rather than reopening New enquiry's (long
      // since locked) one, since that's not where this conversation is actually happening.
      woServiceBoxes = S.service_options.map((opt) => {
        const cb = h('input', { type: 'checkbox', value: String(opt.id) });
        cb.checked = (lead.services || []).includes(opt.name);
        return { id: opt.id, box: h('label', { class: 'check-row' }, cb, h('span', {}, opt.name)) };
      });
      const woServiceField = h('div', { class: 'field wide' },
        h('label', {}, 'Services', h('span', { class: 'req-mark', 'aria-hidden': 'true' }, ' *')),
        h('div', { class: 'check-grid' }, woServiceBoxes.map((s) => s.box)),
        h('p', { class: 'err', id: 'err-wo_service_ids', role: 'alert' }));

      const workOrderFields = h('div', { class: 'form-grid' },
        woServiceField,
        wrapField('work_order_no', 'Work order no.', text('text', L.work_order_no, { maxlength: 60, autocomplete: 'off' }), '', true),
        wrapField('work_order_date', 'Work order date', dateField(L.work_order_date), '', true),
        wrapField('advance_amount', `Advance received (${S.settings.currency})`,
          text('number', L.advance_amount, { min: '0', step: 'any', inputmode: 'decimal' }), '', true),
        wrapField('advance_date', 'Date of payment', dateField(L.advance_date), '', true),
        wrapField('advance_mode', 'Mode of payment', choice(S.payment_modes, L.advance_mode, 'Choose how it was paid'), '', true),
        wrapField('advance_comments', 'Comments', area(2, L.advance_comments), 'wide'));
      workOrderSectionNode = h('details', { class: `stage-section${negotiationFinalized ? '' : ' locked'}`, open: negotiationFinalized && expand === 4 },
        h('summary', { class: 'stage-section-title' }, 'Work order & advance'),
        h('div', { class: 'stage-section-body' }, workOrderFields));

      if (!negotiationFinalized) {
        // Nothing here can be entered before a negotiation round is finalized - lock the fields and
        // explain why, same as the quote section does while the survey is still open.
        woServiceBoxes.forEach((s) => { s.box.querySelector('input').disabled = true; });
        ['work_order_no', 'work_order_date', 'advance_amount', 'advance_date', 'advance_mode', 'advance_comments'].forEach((name) => { inputs[name].disabled = true; });
        workOrderSectionNode.querySelector('summary').addEventListener('click', (e) => {
          e.preventDefault();
          toast('Finalize a negotiation round first', true);
        });
      } else if (isPastStage('Work order & advance')) {
        // The lead is Won or Lost - viewable, but read only, same as the earlier stages once passed.
        woServiceBoxes.forEach((s) => { s.box.querySelector('input').disabled = true; });
        ['work_order_no', 'work_order_date', 'advance_amount', 'advance_date', 'advance_mode', 'advance_comments'].forEach((name) => { inputs[name].disabled = true; });
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
        // Picking an option here is the confirmation itself - there's no second "are you sure?" after it.
        const newLabel = `New client — ${L.company || L.contact_name}`;
        const choice = await LD.pickList(
          [{ value: '', label: newLabel }, ...S.clients.map((c) => ({ value: c.id, label: c.name }))],
          '', { title: 'Mark won · map to a client' });
        if (choice === undefined) return;             // closed without choosing - don't mark it won
        clientId = choice || null;
      } else {
        const sure = await LD.confirm(`Mark ${title(lead)} as lost?`,
          { title: 'Mark lost', ok: 'Yes, mark lost', danger: true });
        if (!sure) return;
      }
      outcome = result;
      outcomeClientId = clientId;
      inputs.stage.addOption(result, result);
      inputs.stage.value = result;
      // Not saveBtn.click(): once the work order is saved every step is done, there's no current-step card,
      // and saveBtn isn't in the page at all - a detached button's click submits nothing, so Mark won/lost
      // silently did nothing (kohal, 2026-10-26). The form itself is always in the document.
      form.requestSubmit();
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
      // Once Work order & advance exists, its own services checklist is the live one - New enquiry's
      // copy is locked read-only by then (see isPastStage('New enquiry') above), showing what the lead
      // started as, not what it stands at now.
      const activeServiceBoxes = woServiceBoxes || serviceBoxes;
      body.service_ids = activeServiceBoxes.filter((s) => s.box.querySelector('input').checked).map((s) => s.id);
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
          if (!body.service_ids.length) missing[woServiceBoxes ? 'wo_service_ids' : 'service_ids'] = 'Choose at least one service';
          if (!body.enquired_by_id) missing.enquired_by_id = 'This field is required';
          if (!body.follow_up_date) missing.follow_up_date = 'This field is required';
          // Quote sent: once either box is filled (or the quote was already sent), both are required.
          if (!isNew && !inputs.quote_sent_date.disabled && (body.quote_sent_date || body.est_value !== null || lead.quote_sent_date)) {
            if (!body.quote_sent_date) missing.quote_sent_date = 'This field is required';
            if (body.est_value === null) missing.est_value = 'This field is required';
          }
          // Work order & advance: same all-or-nothing rule, once negotiation has been finalized.
          if (!isNew && !inputs.work_order_no.disabled
            && (body.work_order_no || body.work_order_date || body.advance_amount !== null || body.advance_date || body.advance_mode || lead.work_order_no)) {
            if (!body.work_order_no) missing.work_order_no = 'This field is required';
            if (!body.work_order_date) missing.work_order_date = 'This field is required';
            if (body.advance_amount === null) missing.advance_amount = 'This field is required';
            if (!body.advance_date) missing.advance_date = 'This field is required';
            if (!body.advance_mode) missing.advance_mode = 'This field is required';
          }
          const stageOk = requireFilled([...surveyCheck(), ...negotiationCheck()]);
          if (Object.keys(missing).length || !stageOk) {
            Object.keys(missing).forEach((name) => inputs[name]?.closest('details')?.setAttribute('open', ''));
            // The survey/negotiation boxes requireFilled flags sit in step sheets that aren't on screen on a
            // lead's detail page, so say where to look instead of an unexplained "highlighted fields".
            throw {
              message: stageOk ? 'Check the highlighted fields'
                : 'Some Site survey or Negotiation details are incomplete - open that step and fill them in',
              fields: missing,
            };
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
        const unshown = [];
        for (const [name, message] of Object.entries(err.fields || {})) {
          const p = formRoots.map((root) => root.querySelector(`#err-${name}`)).find(Boolean);
          if (p && p.isConnected) p.textContent = message;
          else unshown.push(`${name.replace(/_/g, ' ')}: ${message}`);
          if (inputs[name]) { inputs[name].setAttribute('aria-invalid', 'true'); first = first || inputs[name]; }
        }
        // On a lead's detail page the form's own fields live in step sheets that aren't on screen, so a
        // message with nowhere to land would leave only "Check the highlighted fields" and nothing
        // highlighted - say which ones in the error box instead.
        if (unshown.length) errorBox.textContent = `${err.message} (${unshown.join('; ')})`;
        (first || errorBox).focus?.();
      } finally {
        saveBtn.disabled = false;
      }
    });

    // The save button lives outside the <form> in the drawer footer, so tie it to the form explicitly.
    saveBtn.setAttribute('form', 'lead-form');
    return { form, saveBtn, markOutcome, quoteSection, surveySectionNode, negotiationSectionNode, workOrderSectionNode };
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

  // A small menu of the less-used, mostly destructive actions, sliding up from the bottom like the sheet.
  function actionSheet(actions) {
    const previous = document.activeElement;
    const cancel = h('button', { class: 'btn', type: 'button' }, 'Cancel');
    const card = h('div', { class: 'confirm-card action-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'More actions' },
      actions.map(({ label, danger, run }) => h('button', {
        class: `btn${danger ? ' danger' : ''}`, type: 'button',
        // finish() pops this sheet's own history entry via history.back(), which resolves asynchronously;
        // if `run` opens another back-closable overlay (a confirm, a picker...) before that pop is actually
        // processed, the new one's own popstate listener can catch it instead and read it as "closed",
        // resolving false before anyone touched it. A short delay lets the pop land first.
        onclick: () => { finish(); setTimeout(run, 60); },
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

  /* ---------- lead detail: a full screen with a stepper, not a side drawer ---------- */

  // A self-contained slide-up sheet (its own overlay + drawer, not the old #drawer/#overlay elements -
  // those are gone) - same pattern projects.js already uses for one payment step's own sheet.
  function openSheet({ eyebrow, title: sheetTitle, body, foot } = {}) {
    const previous = document.activeElement;
    const closeX = h('button', { class: 'icon-x', type: 'button', 'aria-label': 'Close' });
    const titleEl = h('h2', { tabindex: '-1' }, sheetTitle);
    const drawerEl = h('div', { class: 'drawer' },
      h('div', { class: 'drawer-head' },
        h('div', { class: 'sheet-handle', 'aria-hidden': 'true' }),
        h('div', { class: 'drawer-head-row' },
          h('div', { class: 'drawer-titles' },
            eyebrow ? h('p', { class: 'step-sheet-eyebrow' }, eyebrow) : null, titleEl),
          closeX)),
      h('div', { class: 'drawer-scroll' }, body));
    if (foot) drawerEl.append(h('div', { class: 'drawer-foot' }, foot));
    const overlayEl = h('div', { class: 'overlay' });
    function onKey(e) { if (e.key === 'Escape') finish(); }
    const finish = LD.closeOnBack(() => {
      window.removeEventListener('keydown', onKey, true);
      overlayEl.remove();
      drawerEl.remove();
      document.body.classList.remove('locked');
      if (previous && previous.isConnected) previous.focus();
    });
    closeX.onclick = finish;
    overlayEl.addEventListener('click', finish);
    window.addEventListener('keydown', onKey, true);
    document.body.classList.add('locked');
    document.body.append(overlayEl, drawerEl);
    titleEl.focus();
    return finish;
  }

  // Why a not-yet-reached step is waiting - each names the step right before it.
  const UPCOMING_REASON = {
    'Site survey': 'After the enquiry is logged',
    'Quote sent': 'After the site survey',
    Negotiation: 'After the quote',
    'Work order & advance': 'After negotiation',
  };

  // The line a finished step's row shows on the right - a short fact about it, not the full form.
  function finishedSummary(stageName, lead) {
    const sv = lead.survey || {};
    const rounds = lead.negotiations || [];
    const shownRound = [...rounds].reverse().find((r) => r.finalized) || (rounds.length ? rounds[rounds.length - 1] : null);
    if (stageName === 'New enquiry') return [fmtDate(lead.created_at.slice(0, 10)), lead.source].filter(Boolean).join(' · ');
    if (stageName === 'Site survey') {
      const photos = (sv.photos || []).length;
      return [sv.survey_date ? fmtDate(sv.survey_date) : '', photos ? plural(photos, 'photo', 'photos') : ''].filter(Boolean).join(' · ');
    }
    if (stageName === 'Quote sent') {
      return lead.est_value != null ? `Quote ${fmtShortMoney(lead.est_value)}` : (lead.quote_sent_date ? fmtDate(lead.quote_sent_date) : '');
    }
    if (stageName === 'Negotiation') {
      return [plural(rounds.length, 'round', 'rounds'),
        shownRound && shownRound.estimate != null ? `${fmtShortMoney(shownRound.estimate)}${shownRound.finalized ? ' final' : ''}` : '']
        .filter(Boolean).join(' · ');
    }
    return [lead.work_order_no, lead.advance_amount != null ? `${fmtShortMoney(lead.advance_amount)} advance` : ''].filter(Boolean).join(' · ');
  }

  // A finished step: a green check, its name, and the summary above - tapping it opens the same fields
  // in a sheet, read only if the stage is actually locked (same rule as today), still live and savable
  // (through the one current-step Save button) if it isn't - e.g. Site survey, once done but not yet
  // superseded by Quote sent.
  function finishedStepRow(stageIndex, stageName, body, lead, saveBtn) {
    let finish;
    const row = h('button', {
      type: 'button', class: 'step-row', id: `lead-stage-row-${stageIndex}`,
      onclick: () => {
        const editable = !!body && [...body.querySelectorAll('input, select, textarea, button.field-picker')].some((c) => !c.disabled);
        const saveRow = editable
          ? h('button', { class: 'btn primary', type: 'button', onclick: () => { finish(); saveBtn.click(); } }, 'Save changes')
          : null;
        finish = openSheet({
          eyebrow: stageName, title: stageName,
          body: body || h('p', { class: 'hint' }, 'Nothing recorded yet.'), foot: saveRow,
        });
      },
    },
      h('span', { class: 'step-circle paid', 'aria-hidden': 'true' }, '✓'),
      h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, stageName)),
      h('span', { class: 'step-amount' }, finishedSummary(stageName, lead)));
    return row;
  }

  function upcomingStepRow(stageIndex, stageName) {
    return h('div', { class: 'upcoming-row' },
      h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(stageIndex + 1)),
      h('span', { class: 'step-main' },
        h('span', { class: 'step-title' }, stageName),
        h('span', { class: 'step-sub' }, UPCOMING_REASON[stageName] || '')));
  }

  function currentStepCard(stageIndex, stageName, body) {
    return h('div', { class: 'current-card', id: `lead-stage-current-${stageIndex}` },
      h('div', { class: 'current-card-head' },
        h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(stageIndex + 1)),
        h('h3', {}, stageName)),
      body || h('p', { class: 'hint' }, 'Nothing to fill in here yet.'));
  }

  // The 5-part bar across the top, plus "Step n of 5 · <stage>" - done parts in --ok, the current one in
  // --accent, the rest in --line; a closed lead fills every part (its own colour) and says Won / Lost.
  function leadProgress(lead, next) {
    const won = lead.stage === 'Won';
    const lost = lead.stage === 'Lost';
    const bar = h('div', { class: `lead-progress${lost ? ' lost' : ''}` },
      STAGE_ORDER.map((_, i) => h('i', { class: won || lost || i < next ? 'done' : i === next ? 'current' : null })));
    // The stage named here is the one the current card is about - lead.stage can lag behind it (e.g. a
    // lead still sitting at "Negotiation" once its round is finalized is already working towards Work
    // order & advance, which is what the card below actually shows).
    const stepText = lost ? 'Lost' : won ? 'Won' : `Step ${next + 1} of ${STAGE_ORDER.length} · ${STAGE_ORDER[next] || lead.stage}`;
    return h('div', {}, bar, h('p', { class: 'lead-step-text' }, stepText));
  }

  // The follow-up date, shown as its own card (not folded into New enquiry) since it stays live for the
  // lead's whole open life, not just while New enquiry is the current step. Reschedule opens a small sheet
  // (the SNOOZE buttons plus the same calendar dateField already uses) that applies straight to the real,
  // live follow_up_date control and submits through the one shared Save button - nothing here is a second
  // copy of that field.
  function followupCard(lead, dateInput, saveBtn) {
    const late = isOpen(lead) && lead.follow_up_date && diffDays(lead.follow_up_date, S.today) < 0;
    const dateText = !lead.follow_up_date ? 'Not set'
      : late ? `${plural(-diffDays(lead.follow_up_date, S.today), 'day', 'days')} late · ${fmtDate(lead.follow_up_date)}`
        : fmtDate(lead.follow_up_date);

    function apply(iso) {
      dateInput.value = iso;
      dateInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    function openReschedule() {
      let finish;
      const quick = h('div', { class: 'quick-dates' },
        SNOOZE.map(([label, days]) => h('button', {
          class: 'btn small', type: 'button',
          onclick: () => { apply(addDays(S.today, days)); finish(); saveBtn.click(); },
        }, label)));
      const pickBtn = h('button', { class: 'btn', type: 'button',
        onclick: async () => {
          const chosen = await LD.pickDate(dateInput.value);
          if (chosen === undefined) return;
          apply(chosen);
          finish();
          saveBtn.click();
        },
      }, dateInput.value ? `Pick another date (now ${fmtDate(dateInput.value)})` : 'Pick a date');
      finish = openSheet({ title: 'Reschedule follow-up', body: [quick, pickBtn] });
    }

    return h('div', { class: `followup-card${late ? ' late' : ''}` },
      h('div', {}, h('p', { class: 'followup-label' }, 'Follow up'), h('p', { class: 'followup-date' }, dateText)),
      isOpen(lead) ? h('button', { class: 'btn small', type: 'button', onclick: openReschedule }, 'Reschedule') : null);
  }

  // A note just logs an activity entry (kind "note") - there's no separate Lead.notes field to edit.
  function noteComposer(lead) {
    const text = h('textarea', { rows: 2, placeholder: 'Add a note…', maxlength: 2000 });
    const err = h('p', { class: 'err', role: 'alert' });
    const btn = h('button', { class: 'btn small', type: 'button' }, 'Add note');
    btn.onclick = async () => {
      if (!text.value.trim()) { err.textContent = 'Write a note first'; return; }
      err.textContent = '';
      btn.disabled = true;
      try {
        const res = await api(`/api/leads/${lead.id}/notes`, { method: 'POST', body: { text: text.value } });
        text.value = '';
        renderTimeline(res.activities);
        toast('Note added');
      } catch (e) { err.textContent = e.message; } finally { btn.disabled = false; }
    };
    return h('div', {}, h('div', { class: 'note-composer' }, text, btn), err);
  }

  function leadDetailView(lead) {
    // onSaved: stay on this page and let the forced re-render below show the lead's new state, instead of
    // navigating anywhere - closeDrawer (the old side-drawer's onSaved) made sense for a modal; it doesn't
    // for a page of its own.
    const { form, saveBtn, markOutcome, quoteSection, surveySectionNode, negotiationSectionNode, workOrderSectionNode }
      = buildLeadForm(lead, () => { forceNextRender = true; });
    const hasRounds = (lead.negotiations || []).length > 0;
    const negotiation = hasRounds ? negotiationSection(lead) : negotiationSectionNode;
    const sectionNodes = [form.querySelector('details.stage-section'), surveySectionNode, quoteSection, negotiation, workOrderSectionNode];
    const sectionBodies = sectionNodes.map((n) => (n ? n.querySelector(':scope > .stage-section-body') : null));
    // Follow-up date lives among New enquiry's own fields (wherever that section ends up below), but it's
    // always shown and changeable from its own card further down - captured here, by reference, before
    // that happens, so the card can read/set it (and fire its change event) no matter where its section
    // itself is currently sitting (open on screen, or tucked inside a finished step's sheet).
    const dateInput = form.querySelector('#f-follow_up_date');
    // Once its body is handed to a row/card below, the empty <details> shell left behind in `form` would
    // otherwise render as a second, content-less "New enquiry" accordion - drop it; what's left in `form`
    // (the error box, the read-only "Current stage" line) stays, just not shown - see `form.hidden` below.
    sectionNodes[0]?.remove();

    const next = nextStageIndex(lead);
    const rounds = lead.negotiations || [];
    // New enquiry is always finished once a lead exists at all - creating one requires its fields in the
    // first place (see addView's own required-field check) - so, unlike every other stage, there's no
    // state where a saved lead is still "working on" it; nextStageIndex already assumes this (it always
    // resolves to at least 1 while a lead sits at this very stage), so done[0] has to match that or New
    // enquiry would land in neither the done nor the current bucket below.
    const done = [
      true,
      !!lead.survey?.survey_date,
      !!lead.quote_sent_date,
      rounds.some((r) => r.finalized) || CLOSED_STAGES.includes(lead.stage),
      !!lead.work_order_no,
    ];
    const closedLead = CLOSED_STAGES.includes(lead.stage);

    const finishedRows = [];
    const upcomingRows = [];
    let currentCard = null;
    STAGE_ORDER.forEach((stageName, i) => {
      const body = sectionBodies[i];
      if (done[i]) finishedRows.push(finishedStepRow(i, stageName, body, lead, saveBtn));
      else if (!closedLead && i === next) currentCard = currentStepCard(i, stageName, body);
      else if (!closedLead) upcomingRows.push(upcomingStepRow(i, stageName));
      // A closed (Lost) lead that never reached this stage: nothing to show, it was never reached.
    });

    // Mark won only once the deal is actually being negotiated, not from New enquiry onward - and only
    // for the admin, since it's the step that maps the lead to a client. Mark lost has no such gate.
    const canMarkWon = S.me.is_admin && STAGE_ORDER.indexOf(lead.stage) >= STAGE_ORDER.indexOf('Negotiation');
    // Once the work order itself is saved, Won is actually reachable (the server's own gate) - that's its
    // own prominent Mark won / Mark lost row further down then, not tucked in this menu alongside Edit
    // contact.
    const workOrderSaved = isOpen(lead) && !!lead.work_order_no;
    const menuActions = [
      !closedLead && !workOrderSaved && canMarkWon ? { label: 'Mark won', run: () => markOutcome('Won') } : null,
      !closedLead && !workOrderSaved ? { label: 'Mark lost', danger: true, run: () => markOutcome('Lost') } : null,
      {
        label: 'Edit contact',
        run: () => {
          const row = document.getElementById('lead-stage-row-0');
          if (row) { row.scrollIntoView({ behavior: 'smooth', block: 'center' }); row.click(); return; }
          document.getElementById('lead-stage-current-0')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        },
      },
    ].filter(Boolean);
    const outcomeRow = workOrderSaved ? h('div', { class: 'outcome-row' },
      S.me.is_admin ? h('button', { class: 'btn ok-solid', type: 'button', onclick: () => markOutcome('Won') }, 'Mark won') : null,
      h('button', { class: 'btn danger-solid', type: 'button', onclick: () => markOutcome('Lost') }, 'Mark lost')) : null;
    const moreBtn = h('button', {
      class: 'btn small', type: 'button', 'aria-label': 'More actions', onclick: () => actionSheet(menuActions),
    }, '⋯');
    const callBtn = lead.phone ? h('a', { class: 'btn small', href: `tel:${telNumber(lead.phone)}` }, 'Call') : null;

    const contactLine = [subtitle(lead), serviceLabel(lead)].filter(Boolean).join(' · ');
    const header = h('div', { class: 'p-head' },
      h('div', {},
        h('a', { class: 'back-link lead-back-link', href: '#active' }, '‹ Leads'),
        h('h2', {}, title(lead)),
        contactLine ? h('p', { class: 'hint' }, contactLine) : null),
      h('div', { class: 'lead-head-actions' }, callBtn, moreBtn));

    // `form` stays in the document - saveBtn's form="lead-form" needs it to exist, and (unlike the button
    // itself) a *hidden* form silently refuses to submit - but nothing is left inside worth showing: the
    // error box is pulled out so a validation error is still visible, right under the header, and the
    // read-only "Current stage" line is dropped as redundant with the progress bar above.
    const errorBox = form.querySelector('.form-error');
    form.querySelector('.current-stage')?.remove();

    return h('div', { class: 'lead-detail-page' },
      header,
      errorBox,
      leadProgress(lead, next),
      projectBox(lead),
      finishedRows.length ? h('div', { class: 'card-group step-list' }, finishedRows) : null,
      outcomeRow,
      currentCard,
      currentCard ? saveBtn : null,
      upcomingRows.length ? h('div', {}, upcomingRows) : null,
      followupCard(lead, dateInput, saveBtn),
      form,
      noteComposer(lead),
      activitySection());
  }

  /* ---------- add lead (a full screen, like the other tabs) ---------- */

  // Built once and kept here, not rebuilt every time addView() is called - switching to Active leads and
  // back to Add lead must not clear whatever was already typed in. Only a successful save (onSaved below)
  // throws this away, so the next visit to Add lead starts blank again.
  let addViewNode = null;

  function addView() {
    if (!addViewNode) {
      const { form, saveBtn } = buildLeadForm(null, () => { addViewNode = null; });
      form.append(h('div', { class: 'form-actions' }, saveBtn));
      addViewNode = h('div', { class: 'add-lead' },
        h('h2', {}, 'Add lead'),
        h('p', { class: 'hint' }, 'A new lead starts at New enquiry.'),
        form);
    }
    return addViewNode;
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
      // A saved round is only still editable if it's the latest one, negotiation is still the current
      // stage, and it isn't finalized yet - every earlier round is read-only history, and once a round is
      // finalized, so is this one. The Finalized box itself stays the one exception: it (and only it) can
      // still be unticked - the escape hatch below for reopening negotiation after finalizing by mistake -
      // and saving that still goes through the same Save button.
      const isLatest = roundNo === lead.negotiations.length;
      const stageStillOpen = lead.stage === 'Negotiation';
      const fieldsEditable = !round || (isLatest && stageStillOpen && !round.finalized);
      const canReopen = !!round && isLatest && stageStillOpen && round.finalized;
      const dateInput = dateField(round ? round.date || '' : '', { placeholder: 'Round date' });
      const person = h('input', { type: 'text', value: round ? round.authorized_person || '' : '', maxlength: 120 });
      const estimate = h('input', {
        type: 'number', min: '0', step: 'any', inputmode: 'decimal',
        value: round && round.estimate != null ? round.estimate : '', placeholder: `Amount (${S.settings.currency})`,
      });
      const finalized = h('input', { type: 'checkbox' });
      finalized.checked = !!(round && round.finalized);
      [dateInput, person, estimate].forEach((c) => { c.disabled = !fieldsEditable; });
      finalized.disabled = !(fieldsEditable || canReopen);
      let actions = null;
      if (fieldsEditable || canReopen) {
        const saveBtn = h('button', { class: 'btn small', type: 'button' }, round ? 'Save' : 'Save round');
        saveBtn.onclick = async () => {
          err.textContent = '';
          if (fieldsEditable && !requireFilled([dateInput, person, estimate])) return;
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
            toast(`Project ${res.code} created`);
            forceNextRender = true;
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
      if (view === 'lead' && leadId === id) renderTimeline(lead.activities);
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* ---------- global events ---------- */

  function resolveView() {
    const next = window.location.hash.slice(1);
    const leadMatch = /^lead\/(\d+)$/.exec(next);
    if (leadMatch) { view = 'lead'; leadId = Number(leadMatch[1]); return; }
    view = VIEWS.includes(next) ? next : 'active';
    leadId = null;
  }

  function syncView() {
    if (view === 'active') listScrollY = window.scrollY;      // leaving the list - remember where from
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

  // Pick up changes made on another device when the tab comes back into view.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && S) load().catch(() => {});
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
