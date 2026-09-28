/* Attendance pieces shared by the Your attendance page (attendance.js) and the Me hub's check-in card
   (me.js): where the phone is, our own "location is required" explanation before the phone's prompt, the
   project picker, and a couple of time formatters. Loaded before either page script. */
window.ATT = (() => {
  'use strict';

  const { h, clear } = window.LD;

  function fmtTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  }

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

  function elapsedSince(iso) {
    const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
    return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`;
  }

  /* Check in: explain why the location is needed (unless we already have one), fetch it once, let the
     person pick what they're working on (narrowed to projects near them), then record it. Resolves the
     server's reply, or null if they backed out at any step. Throws the API's error, or a "no location"
     one, for the caller to show. `projects` is the list /api/attendance/state returns. */
  async function checkIn(projects, { location = null } = {}) {
    let here = location;
    if (!here) {
      if (!(await explainLocationIsRequired())) return null;
      here = await getLocation();
      if (!here) throw new Error("We couldn't get your location. Allow location access for this site in your browser, then try again.");
    }
    const projectId = await pickProject(projects, '', nearestDistrict(here));
    if (projectId === undefined) return null;                   // closed the list without choosing
    return window.LD.api('/api/attendance/check-in', {
      method: 'POST', body: { project_id: projectId || null, lat: here.lat, lng: here.lng },
    });
  }

  const checkOut = () => window.LD.api('/api/attendance/check-out', { method: 'POST' });

  /* The dark Today card: where today's check-in stands, the time since checking in, and one big Check in /
     Check out button. Drawn into `box` from /api/attendance/state's `data`; after a check-in or check-out
     it calls onChange() so the page can fetch fresh data and draw again. Used on the Me hub, and on Your
     attendance while you haven't checked in yet (historyLink false there - the history is right below). */
  function renderToday(box, data, { onChange, historyLink = true }) {
    const { toast } = window.LD;
    clearInterval(box._timer);
    const t = data.today;
    let status;
    let big = null;
    let button = null;

    if (!t) {
      status = 'Not checked in yet';
      button = h('button', { class: 'btn primary me-today-btn', type: 'button' }, 'Check in');
      button.onclick = async () => {
        button.disabled = true;
        button.textContent = 'Checking in\u2026';
        try {
          if (await checkIn(data.projects)) {
            toast('Checked in with your location');
            await onChange();
            return;
          }
        } catch (err) {
          toast(err.message, true);
        }
        button.disabled = false;
        button.textContent = 'Check in';
      };
    } else if (!t.check_out_at) {
      status = [`Checked in at ${fmtTime(t.check_in_at)}`, t.project_title].filter(Boolean).join(' \u00b7 ');
      big = h('span', { class: 'me-today-big' }, elapsedSince(t.check_in_at));
      box._timer = setInterval(() => {
        if (!box.isConnected) { clearInterval(box._timer); return; }
        big.textContent = elapsedSince(t.check_in_at);
      }, 30000);
      button = h('button', { class: 'btn me-today-btn me-out', type: 'button' }, 'Check out');
      button.onclick = async () => {
        button.disabled = true;
        try {
          await checkOut();
          toast('Checked out');
          await onChange();
        } catch (err) {
          toast(err.message, true);
          button.disabled = false;
        }
      };
    } else {
      status = `Done for today \u00b7 ${fmtTime(t.check_in_at)} \u2013 ${fmtTime(t.check_out_at)}`;
      big = h('span', { class: 'me-today-big' }, `${t.hours} h`);
    }

    clear(box).append(...[
      // On the hub: a "Today" label and a link to the full history. Your attendance has both already.
      historyLink ? h('div', { class: 'me-today-top' },
        h('span', { class: 'me-today-label' }, 'Today'),
        h('a', { class: 'me-today-link', href: '/attendance' }, 'History \u203a')) : null,
      h('p', { class: 'me-today-status' }, status),
      big,
      button,
      !t ? h('p', { class: 'me-today-note' }, 'Uses your location once') : null,
    ].filter(Boolean));
  }

  return {
    fmtTime, nearestDistrict, getLocation, explainLocationIsRequired, pickProject, elapsedSince, checkIn, checkOut,
    renderToday,
  };
})();
