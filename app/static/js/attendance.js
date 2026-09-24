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

  /* Approximate centre of each district we do work in, so a check-in location can be matched to "which
     city am I in" without calling any external geocoding service - not needed at this scale, and one more
     place a free-plan network restriction or an API key could get in the way. Add a district here once
     work starts in a new one; until then, projects there just won't get auto-filtered (everything still
     shows via "Show all projects"). Beyond NEARBY_KM from every known centre, we don't trust a match at
     all - better to show everything than confidently filter to the wrong city. */
  const DISTRICT_CENTERS = {
    Chandrapur: [19.9615, 79.2961],
    Dhanbad: [23.7957, 86.4304],
    Giridih: [24.1913, 86.3000],
    Hazaribagh: [23.9925, 85.3637],
    Nagpur: [21.1458, 79.0882],
    Ramgarh: [23.6300, 85.5100],
    Sundargarh: [22.1167, 84.0333],
    Wardha: [20.7453, 78.6022],
  };
  const NEARBY_KM = 100;

  function distanceKm(lat1, lng1, lat2, lng2) {
    const R = 6371;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  function nearestDistrict(location) {
    if (!location) return null;
    let best = null;
    let bestKm = Infinity;
    for (const [district, [lat, lng]] of Object.entries(DISTRICT_CENTERS)) {
      const km = distanceKm(location.lat, location.lng, lat, lng);
      if (km < bestKm) { bestKm = km; best = district; }
    }
    return bestKm <= NEARBY_KM ? best : null;
  }

  /* Where the phone was, fetched once (getCurrentPosition, never watchPosition) after the person has seen
     our own explanation below - so the phone's own permission dialog is never a surprise. One fixed reading
     is taken and nothing is kept open or asked for again; the phone's location access ends the moment this
     resolves. A location is required to check in, so a failure here (no GPS, permission refused, too slow)
     is reported to the person, not silently skipped - see checkInBtn.onclick. */
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
     location out of nowhere. Location is required to check in, so there is only one way forward, Continue -
     closing this box (Escape, tapping outside) just cancels this attempt, the same as never having tapped
     Check in; it does not check them in without a location. Reuses the confirm box's look (see common.js)
     but not confirmBox() itself, since that always offers a real Cancel. */
  function explainLocationIsRequired() {
    return new Promise((resolve) => {
      const continueBtn = h('button', { class: 'btn primary', type: 'button' }, 'Continue');
      const card = h('div', { class: 'confirm-card', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'loc-title', 'aria-describedby': 'loc-message' },
        h('h2', { id: 'loc-title' }, 'Location required to check in'),
        h('p', { id: 'loc-message' }, "Your phone will ask to share your location. We use it to show projects near you and record where you checked in, fetching it once and letting it go right away."),
        h('div', { class: 'confirm-actions' }, continueBtn));
      const overlay = h('div', { class: 'confirm-overlay' }, card);
      const finish = (result) => { overlay.remove(); resolve(result); };
      continueBtn.onclick = () => finish(true);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(false); });
      window.addEventListener('keydown', function onKey(e) {
        if (e.key !== 'Escape') return;
        window.removeEventListener('keydown', onKey);
        finish(false);
      });
      document.body.append(overlay);
      continueBtn.focus();
    });
  }

  /* An in-app list to choose the project (or office work) to check in against, instead of the phone's own
     native <select> popup - which drops the app's own look and, with a long project list, is awkward to
     scroll on some phones. Resolves the chosen id ('' for office work), or undefined if closed without
     choosing, so the caller can tell "picked office work" apart from "changed their mind". */
  /* nearDistrict, when given, narrows the list to projects in that district to start with - a guess from
     where the phone is right now, not a hard rule, so a toggle row always offers the full list too (the
     guess can be wrong near a border, or the work is genuinely outside every district we know about). */
  function pickProject(projects, selectedId, nearDistrict) {
    return new Promise((resolve) => {
      const toOption = (p) => ({ id: String(p.id), label: `${p.client_name} – ${p.title}`, district: p.site_district });
      const all = [{ id: '', label: 'No project (office work)' }, ...projects.map(toOption)];
      const inDistrict = nearDistrict ? projects.filter((p) => p.site_district === nearDistrict) : [];
      let showingAll = !nearDistrict || inDistrict.length === 0;

      const finish = (id) => { overlay.remove(); resolve(id); };
      const list = h('ul', { class: 'picker-list', role: 'radiogroup', 'aria-label': 'Choose what you are working on' });
      const toggle = nearDistrict && inDistrict.length
        ? h('button', { type: 'button', class: 'picker-toggle' })
        : null;

      function renderRows() {
        clear(list);
        const shown = showingAll ? all : [all[0], ...inDistrict.map(toOption)];
        shown.forEach((opt) => {
          const selected = String(selectedId ?? '') === opt.id;
          list.append(h('li', {
            class: `picker-row${selected ? ' selected' : ''}`, role: 'radio', 'aria-checked': String(selected), tabindex: '0',
            onclick: () => finish(opt.id),
            onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); finish(opt.id); } },
          }, h('span', {}, opt.label), h('span', { class: 'picker-dot', 'aria-hidden': 'true' })));
        });
        if (toggle) toggle.textContent = showingAll ? `Show only ${nearDistrict} projects` : `Not in ${nearDistrict}? Show all projects`;
      }
      if (toggle) toggle.onclick = () => { showingAll = !showingAll; renderRows(); };
      renderRows();

      const card = h('div', { class: 'confirm-card picker-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Choose what you are working on' }, toggle, list);
      const overlay = h('div', { class: 'confirm-overlay', onclick: (e) => { if (e.target === overlay) finish(undefined); } }, card);
      window.addEventListener('keydown', function onKey(e) {
        if (e.key !== 'Escape') return;
        window.removeEventListener('keydown', onKey);
        finish(undefined);
      });
      document.body.append(overlay);
      (list.querySelector('.picker-row.selected') || list.firstChild).focus();
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

    let selectedProjectId = '';
    let cachedLocation = null;                                 // reused so check-in doesn't ask a second time
    const projectLabel = (id) => {
      const p = id && data.projects.find((pr) => String(pr.id) === String(id));
      return p ? `${p.client_name} – ${p.title}` : 'No project (office work)';
    };
    const projectBtn = h('button', { type: 'button', id: 'att-project', class: 'field-picker' }, projectLabel(''));
    projectBtn.onclick = async () => {
      if (!cachedLocation && (await explainLocationIsRequired())) cachedLocation = await getLocation();
      const chosen = await pickProject(data.projects, selectedProjectId, nearestDistrict(cachedLocation));
      if (chosen === undefined) return;                        // closed without choosing
      selectedProjectId = chosen;
      projectBtn.textContent = projectLabel(chosen);
    };

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
          if (!cachedLocation) {
            const proceed = await explainLocationIsRequired();
            if (!proceed) return;                                  // they closed the box; nothing happened
            checkInBtn.disabled = true;
            checkInBtn.textContent = 'Getting your location…';
            cachedLocation = await getLocation();
          }
          const location = cachedLocation;
          if (!location) {
            errBox.textContent = "We couldn't get your location. Allow location access for this site in your browser, then try again.";
            checkInBtn.disabled = false;
            checkInBtn.textContent = 'Check in';
            return;
          }

          checkInBtn.textContent = 'Checking in…';
          try {
            await api('/api/attendance/check-in', {
              method: 'POST',
              body: { project_id: selectedProjectId || null, lat: location.lat, lng: location.lng },
            });
            toast('Checked in with your location');
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
          projectBtn, errBox, checkInBtn,
          h('p', { class: 'hint' }, 'Location is required to check in.'));
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
