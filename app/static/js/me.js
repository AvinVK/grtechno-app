/* The Me hub's Today card - drawn by attendance-core.js's renderToday, the same card Your attendance shows
   before you check in. This just loads today's state and redraws after a check-in or check-out. */
(() => {
  'use strict';

  const box = document.getElementById('me-today');
  if (!box) return;
  const { h, clear, api } = window.LD;

  async function load() {
    try {
      window.ATT.renderToday(box, await api('/api/attendance/state'), { onChange: load });
    } catch (err) {
      clear(box).append(h('p', { class: 'me-today-status' }, err.message));
    }
  }

  load();
})();
