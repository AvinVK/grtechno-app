/* Attendance: check yourself in and out once a day, optionally against a running project.
   Admin and Accounts also get a Team tab with everyone's register for a chosen day. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural } = window.LD;
  const view = $('#view');

  function fmtTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  }

  function fmtDate(iso) {
    const [y, m, d] = iso.split('-');
    return new Date(Date.UTC(+y, m - 1, +d)).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }

  const today = () => new Date().toISOString().slice(0, 10);

  /* Where the phone was, fetched once (getCurrentPosition, never watchPosition) after the person has agreed
     in our own prompt below - so the phone's own permission dialog is never a surprise. One fixed reading is
     taken and nothing is kept open or asked for again; the phone's location access ends the moment this
     resolves. Best-effort throughout: no GPS, no permission, or too slow all just mean the check-in goes
     through without a location - it never blocks or fails the check-in itself. */
  function getLocation() {
    if (!navigator.geolocation) return Promise.resolve(null);
    return new Promise((resolve) => {
      const done = (result) => { clearTimeout(timer); resolve(result); };
      const timer = setTimeout(() => done(null), 8000);
      navigator.geolocation.getCurrentPosition(
        (pos) => done({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
        () => done(null),
        { enableHighAccuracy: false, timeout: 7500, maximumAge: 60000 },
      );
    });
  }

  /* Our own explanation before the phone's own location prompt appears, so nobody is asked for their
     location out of nowhere. "Share location" is the only path that ever touches navigator.geolocation -
     "Not now" checks in without going near it, so no OS prompt shows at all. Reuses the confirm box's
     look (see common.js) but not confirmBox() itself: here both buttons check in, they just differ on
     whether we ask for a location first, unlike a plain confirm where "no" means stop. */
  function askToShareLocation() {
    return new Promise((resolve) => {
      const shareBtn = h('button', { class: 'btn primary', type: 'button' }, 'Share location');
      const skipBtn = h('button', { class: 'btn', type: 'button' }, 'Not now');
      const card = h('div', { class: 'confirm-card', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'loc-title', 'aria-describedby': 'loc-message' },
        h('h2', { id: 'loc-title' }, 'Share your location?'),
        h('p', { id: 'loc-message' }, "We'll fetch it once, for this check-in, and let it go right away - we don't track you through the day."),
        h('div', { class: 'confirm-actions' }, skipBtn, shareBtn));
      const overlay = h('div', { class: 'confirm-overlay' }, card);
      const finish = (result) => { overlay.remove(); resolve(result); };
      shareBtn.onclick = () => finish(true);
      skipBtn.onclick = () => finish(false);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(false); });
      window.addEventListener('keydown', function onKey(e) {
        if (e.key !== 'Escape') return;
        window.removeEventListener('keydown', onKey);
        finish(false);
      });
      document.body.append(overlay);
      shareBtn.focus();
    });
  }

  function mapLink(a) {
    return a.check_in_map_url ? h('a', { class: 'att-map-link', href: a.check_in_map_url, target: '_blank', rel: 'noopener noreferrer' }, 'View location') : null;
  }

  function historyRow(a) {
    const times = a.check_out_at ? `${fmtTime(a.check_in_at)} – ${fmtTime(a.check_out_at)}` : `${fmtTime(a.check_in_at)} – still checked in`;
    return h('li', { class: 'att-row' },
      h('span', { class: 'att-main' },
        h('span', { class: 'row-title' }, fmtDate(a.work_date)),
        h('span', { class: 'row-sub' }, [a.project_title, times].filter(Boolean).join(' · ')),
        mapLink(a)),
      h('span', { class: 'row-value' }, a.hours != null ? `${a.hours} h` : ''));
  }

  /* ---------- my attendance ---------- */

  async function showMine() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading attendance…'));
    let data;
    try { data = await api('/api/attendance/state'); } catch (err) { clear(view).append(h('p', { class: 'empty-state' }, err.message)); return; }

    const projectSelect = h('select', { id: 'att-project' },
      h('option', { value: '' }, 'No project (office work)'),
      data.projects.map((p) => h('option', { value: p.id }, `${p.client_name} – ${p.title}`)));

    const cardBox = h('div', {});
    const historyList = h('ul', { class: 'rows att-history' });

    function renderHistory() {
      clear(historyList).append(...(data.history.length
        ? data.history.map(historyRow)
        : [h('li', { class: 'empty-state' }, 'No attendance recorded yet.')]));
    }

    /* Check-in and check-out both change today's row and add (or change) it in the history right below it,
       so re-fetch the whole screen's data after either one instead of only patching the card. */
    async function reload() {
      try {
        data = await api('/api/attendance/state');
        renderCard();
        renderHistory();
      } catch (err) {
        toast(err.message, true);
      }
    }

    function renderCard() {
      let card;
      if (!data.today) {
        const errBox = h('p', { class: 'err', role: 'alert' });
        const checkInBtn = h('button', { class: 'btn primary', type: 'button' }, 'Check in');
        checkInBtn.onclick = async () => {
          errBox.textContent = '';
          const wantsLocation = await askToShareLocation();
          checkInBtn.disabled = true;
          checkInBtn.textContent = wantsLocation ? 'Getting your location…' : 'Checking in…';
          const location = wantsLocation ? await getLocation() : null;
          try {
            await api('/api/attendance/check-in', {
              method: 'POST',
              body: { project_id: projectSelect.value || null, lat: location?.lat ?? null, lng: location?.lng ?? null },
            });
            toast(location ? 'Checked in with your location' : 'Checked in');
            await reload();
          } catch (err) {
            errBox.textContent = err.message;
            checkInBtn.disabled = false;
            checkInBtn.textContent = 'Check in';
          }
        };
        card = h('div', { class: 'att-card' },
          h('h3', {}, "You haven't checked in today"),
          h('label', { for: 'att-project' }, 'Working on'),
          projectSelect, errBox, checkInBtn);
      } else if (!data.today.check_out_at) {
        const checkOutBtn = h('button', { class: 'btn primary', type: 'button' }, 'Check out');
        checkOutBtn.onclick = async () => {
          checkOutBtn.disabled = true;
          try {
            await api('/api/attendance/check-out', { method: 'POST' });
            toast('Checked out');
            await reload();
          } catch (err) {
            toast(err.message, true);
            checkOutBtn.disabled = false;
          }
        };
        card = h('div', { class: 'att-card' },
          h('h3', {}, 'Checked in'),
          h('p', { class: 'hint' }, [data.today.project_title, `since ${fmtTime(data.today.check_in_at)}`].filter(Boolean).join(' · ')),
          mapLink(data.today),
          checkOutBtn);
      } else {
        card = h('div', { class: 'att-card' },
          h('h3', {}, 'Done for today'),
          h('p', { class: 'hint' }, [data.today.project_title, `${fmtTime(data.today.check_in_at)} – ${fmtTime(data.today.check_out_at)}`, `${data.today.hours} h`].filter(Boolean).join(' · ')),
          mapLink(data.today));
      }
      clear(cardBox).append(card);
    }
    renderCard();
    renderHistory();

    clear(view).append(h('div', {},
      h('div', { class: 'list-head' }, h('h2', {}, 'Attendance'),
        data.can_see_team ? h('a', { class: 'btn', href: '#team' }, 'Team') : null),
      cardBox,
      h('h3', { class: 'att-sub-head' }, 'Your history'),
      historyList));
  }

  /* ---------- team register (admin, accounts) ---------- */

  async function showTeam() {
    clear(view).append(h('p', { class: 'loading' }, 'Loading team attendance…'));
    const dateInput = h('input', { type: 'date', value: today(), 'aria-label': 'Date' });
    const list = h('ul', { class: 'rows att-history' });
    const count = h('p', { class: 'result-count', 'aria-live': 'polite' });

    async function refresh() {
      clear(list).append(h('li', { class: 'loading' }, 'Loading…'));
      try {
        const data = await api(`/api/attendance/team?date=${encodeURIComponent(dateInput.value)}`);
        count.textContent = plural(data.records.length, 'person', 'people') + ' checked in';
        clear(list);
        if (!data.records.length) { list.append(h('li', { class: 'empty-state' }, 'Nobody checked in on this day.')); return; }
        data.records.forEach((a) => list.append(h('li', { class: 'att-row' },
          h('span', { class: 'att-main' },
            h('span', { class: 'row-title' }, a.user_name),
            h('span', { class: 'row-sub' }, [a.project_title, a.check_out_at ? `${fmtTime(a.check_in_at)} – ${fmtTime(a.check_out_at)}` : `${fmtTime(a.check_in_at)} – still checked in`].filter(Boolean).join(' · ')),
            mapLink(a)),
          h('span', { class: 'row-value' }, a.hours != null ? `${a.hours} h` : ''))));
      } catch (err) {
        clear(list).append(h('li', { class: 'empty-state' }, err.message));
      }
    }
    dateInput.onchange = refresh;

    clear(view).append(h('div', {},
      h('a', { class: 'back-link', href: '#' }, '← Your attendance'),
      h('div', { class: 'list-head' }, h('h2', {}, 'Team attendance')),
      h('div', { class: 'filters' }, dateInput), count, list));
    refresh();
  }

  function route() {
    if (window.location.hash === '#team') return showTeam();
    return showMine();
  }

  window.addEventListener('hashchange', route);
  route();
})();
