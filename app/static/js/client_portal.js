/* The client portal (kohal, 2026-10-22: "client should only be able to see the projects they belong to...
   there should be a new subtab in projects called progress... client should be able to see only this
   subtab of his projects") - a customer's own cut-down view: a list of their own projects, each opening
   straight to its Progress tab alone, nothing else. See app/client_portal.py. Progress itself is still
   empty (kohal: "i will tell u this later, fow now let it be blank") - this is just the shell. */
(() => {
  'use strict';

  const { $, h, clear, api } = window.LD;
  const view = $('#view');

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

  async function showProject(id) {
    clear(view).append(h('p', { class: 'loading' }, 'Loading…'));
    let data;
    try { data = await api(`/api/my-projects/${id}`); }
    catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }
    const p = data.project;
    LD.setAppbarBack?.('Your projects', '#');
    clear(view).append(h('div', { class: 'project-detail' },
      h('div', { class: 'p-head' }, h('h2', {}, p.code), statusChip(p.status)),
      h('p', { class: 'hint' }, [p.title, p.site_name].filter(Boolean).join(' · ')),
      h('div', { class: 'stage-filter', role: 'group', 'aria-label': 'Project section' },
        h('a', { class: 'filter-chip', href: `#p${p.id}`, 'aria-current': 'page' }, 'Progress')),
      h('p', { class: 'empty-state' }, 'Nothing here yet.')));
  }

  function route() {
    const m = /^#p(\d+)$/.exec(window.location.hash);
    if (m) return showProject(Number(m[1]));
    return showList();
  }

  window.addEventListener('hashchange', route);
  route();
})();
