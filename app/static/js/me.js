/* The Me hub's Today card: where today's check-in stands, the time since checking in, and the Check in /
   Check out button. The check-in steps themselves (location explanation, one location reading, project
   picker) come from attendance-core.js - the same ones the Your attendance page uses. */
(() => {
  'use strict';

  const box = document.getElementById('me-today');
  if (!box) return;
  const { h, clear, api, toast } = window.LD;
  const { fmtTime, elapsedSince, checkIn, checkOut } = window.ATT;
  let timer = null;

  async function load() {
    try {
      render(await api('/api/attendance/state'));
    } catch (err) {
      clear(box).append(h('p', { class: 'me-today-status' }, err.message));
    }
  }

  function render(data) {
    clearInterval(timer);
    const t = data.today;
    let status;
    let big = null;
    let button = null;

    if (!t) {
      status = 'Not checked in yet';
      button = h('button', { class: 'btn primary me-today-btn', type: 'button' }, 'Check in');
      button.onclick = async () => {
        button.disabled = true;
        button.textContent = 'Checking in…';
        try {
          if (await checkIn(data.projects)) {
            toast('Checked in with your location');
            await load();
            return;
          }
        } catch (err) {
          toast(err.message, true);
        }
        button.disabled = false;
        button.textContent = 'Check in';
      };
    } else if (!t.check_out_at) {
      status = [`Checked in at ${fmtTime(t.check_in_at)}`, t.project_title].filter(Boolean).join(' · ');
      big = h('span', { class: 'me-today-big' }, elapsedSince(t.check_in_at));
      timer = setInterval(() => { big.textContent = elapsedSince(t.check_in_at); }, 30000);
      button = h('button', { class: 'btn me-today-btn me-out', type: 'button' }, 'Check out');
      button.onclick = async () => {
        button.disabled = true;
        try {
          await checkOut();
          toast('Checked out');
          await load();
        } catch (err) {
          toast(err.message, true);
          button.disabled = false;
        }
      };
    } else {
      status = `Done for today · ${fmtTime(t.check_in_at)} – ${fmtTime(t.check_out_at)}`;
      big = h('span', { class: 'me-today-big' }, `${t.hours} h`);
    }

    clear(box).append(...[
      h('div', { class: 'me-today-top' },
        h('span', { class: 'me-today-label' }, 'Today'),
        h('a', { class: 'me-today-link', href: '/attendance' }, 'History ›')),
      h('p', { class: 'me-today-status' }, status),
      big,
      button,
    ].filter(Boolean));
  }

  load();
})();
