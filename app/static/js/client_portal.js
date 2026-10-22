/* The client portal (kohal, 2026-10-22: "client should only be able to see the projects they belong to...
   there should be a new subtab in projects called progress... client should be able to see only this
   subtab of his projects") - a customer's own cut-down view: a list of their own projects, each opening
   straight to its Progress tab alone, nothing else. See app/client_portal.py. Progress is the fixed
   installation checklist, one stage at a time (kohal: "stages of project, work pics at each phase...
   follow the same template as lead") - the same finished/current/upcoming wizard shape as the admin's own
   Progress tab (app/static/js/projects.js), but every row here is read-only: no days input, no pause/
   resume/mark-done buttons, no photo upload/remove. */
(() => {
  'use strict';

  const { $, h, clear, api } = window.LD;
  const view = $('#view');
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const parseDay = (iso) => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
  const longDate = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  const shortDate = (d) => `${WEEKDAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;

  // Same status labels/tones as the admin's own project list (app/static/js/projects.js's STATUS) - a
  // client sees the identical word for the identical state, not a different vocabulary of its own.
  const STATUS = {
    planned: ['Planned', 'planned'],
    running: ['Running', 'running'],
    on_hold: ['On hold', 'hold'],
    final_estimate_sent: ['Final estimate sent', 'sent'],
    completed: ['Completed', 'done'],
  };
  const statusChip = (s) => {
    const [label, tone] = STATUS[s] || [s, 'planned'];
    return h('span', { class: `chip chip-p-${tone}` }, label);
  };

  function projectRow(p) {
    return h('li', {}, h('a', { class: 'p-row', href: `#p${p.id}` },
      h('span', { class: 'p-main' },
        h('span', { class: 'row-title' }, p.title),
        h('span', { class: 'row-sub' }, [p.code, p.site_name].filter(Boolean).join(' · '))),
      statusChip(p.status),
      h('span', { class: 'row-chevron', 'aria-hidden': 'true' }, '›')));
  }

  async function showList() {
    LD.resetAppbarBack?.();
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api('/api/my-projects'); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    clear(view).append(
      data.projects.length
        ? h('ul', { class: 'card-group' }, data.projects.map(projectRow))
        : h('p', { class: 'empty-state' }, 'No projects yet - once one starts, it shows up here.'));
  }

  function finishedStageRow(stage) {
    return h('div', { class: 'step-row' },
      h('span', { class: 'step-circle paid', 'aria-hidden': 'true' }, '✓'),
      h('span', { class: 'step-main' }, h('span', { class: 'step-title' }, stage.label)),
      h('span', { class: 'step-amount' }, shortDate(parseDay(stage.completed_at))));
  }

  function upcomingStageRow(stage, idx) {
    return h('div', { class: 'upcoming-row' },
      h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(idx + 1)),
      h('span', { class: 'step-main' },
        h('span', { class: 'step-title' }, stage.label),
        stage.note ? h('span', { class: 'step-sub' }, stage.note) : null));
  }

  function currentStageCard(stage, idx, reasons) {
    const photoGrid = stage.photos.length
      ? h('div', { class: 'photo-grid' }, stage.photos.map((p) => h('div', { class: 'photo-thumb' },
          h('a', { href: p.url, target: '_blank', rel: 'noopener noreferrer' }, h('img', { src: p.url, alt: 'Progress photo' })))))
      : null;
    const pauseLabel = stage.pause_reason ? (reasons.find(([k]) => k === stage.pause_reason) || [, stage.pause_reason])[1] : '';
    return h('div', { class: 'current-card' },
      h('div', { class: 'current-card-head' },
        h('span', { class: 'step-circle', 'aria-hidden': 'true' }, String(idx + 1)),
        h('h3', {}, stage.label)),
      stage.note ? h('p', { class: 'hint' }, stage.note) : null,
      stage.paused ? h('p', { class: 'stage-paused-note' },
        `Paused · ${pauseLabel}`, stage.pause_note ? ` — ${stage.pause_note}` : '') : null,
      stage.days != null ? h('p', { class: 'hint' }, `Planned: ${stage.days} day${stage.days === 1 ? '' : 's'}`) : null,
      stage.remarks ? h('p', { class: 'hint' }, stage.remarks) : null,
      photoGrid);
  }

  async function showProject(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/my-projects/${id}`); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const p = data.project;
    const stages = data.stages;
    const currentIdx = stages.findIndex((s) => s.key === data.current_stage_key);
    const bar = h('div', { class: 'lead-progress' },
      stages.map((s, i) => h('i', { class: s.done ? 'done' : (i === currentIdx ? 'current' : null) })));
    const stepText = currentIdx === -1 ? 'All stages complete' : `Step ${currentIdx + 1} of ${stages.length} · ${stages[currentIdx].label}`;
    const body = stages.map((stage, idx) => {
      if (stage.done) return finishedStageRow(stage);
      if (idx === currentIdx) return currentStageCard(stage, idx, data.pause_reasons);
      return upcomingStageRow(stage, idx);
    });

    LD.setAppbarBack?.('Your projects', '#');
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, p.code), statusChip(p.status)),
      h('p', { class: 'hint' }, [p.title, p.site_name].filter(Boolean).join(' · ')),
      h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Project section' },
        h('a', { class: 'filter-chip', href: `#p${p.id}`, 'aria-current': 'page' }, 'Progress')),
      bar, h('p', { class: 'lead-step-text' }, stepText),
      ...body));
  }

  function route() {
    const m = /^#p(\d+)$/.exec(window.location.hash);
    if (m) return showProject(Number(m[1]));
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
