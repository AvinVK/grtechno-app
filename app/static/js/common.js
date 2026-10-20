/* Helpers shared by every page: build DOM without innerHTML, call the API, show a toast.
   DOM is built with h() and text nodes only, so text from the database cannot inject markup. */
window.LD = (() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value' || k === 'selected' || k === 'checked') el[k] = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Not signed in');
    }
    const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || 'Something went wrong. Try again.');
      err.fields = data.fields || {};
      throw err;
    }
    return data;
  }

  /* A short message at the bottom of the screen. The second argument is either true (an error) or options:
     { error, actionLabel, onAction, ms } - with an action (for example Undo) the toast carries a button for
     it and stays a little longer. */
  let toastTimer;
  function toast(message, opts = false) {
    const o = opts && typeof opts === 'object' ? opts : { error: !!opts };
    const el = $('#toast');
    const hide = () => el.classList.remove('show');
    clear(el).append(message);
    if (o.actionLabel && o.onAction) {
      el.append(h('button', {
        type: 'button', class: 'toast-action',
        onclick: () => { clearTimeout(toastTimer); hide(); o.onAction(); },
      }, o.actionLabel));
    }
    el.classList.toggle('error', !!o.error);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hide, o.ms || (o.error ? 4500 : o.onAction ? 6000 : 2600));
  }

  /* Makes the phone's back gesture/button close a custom overlay (confirm box, picker, the lead drawer...)
     the same way tapping its own close control does, instead of leaving it open while the page underneath
     navigates away. Call right after the overlay is shown, with its own no-argument-aware close function;
     use the function this returns as that overlay's "I'm done" path everywhere (button clicks, outside
     click, Escape) instead of the raw one - it's safe to call more than once or from both paths at once. */
  let backSeq = 0;
  function closeOnBack(rawFinish) {
    const id = ++backSeq;
    let settled = false;
    function finish(result) {
      if (settled) return;
      settled = true;
      window.removeEventListener('popstate', onPop);
      rawFinish(result);
      if (history.state && history.state.ldOverlay === id) history.back();
    }
    function onPop() {
      // A nested overlay (a picker opened from inside this one) closing itself also fires popstate, by
      // the same history.back() below - but that one lands back on this overlay's own pushed state, not
      // past it, so this isn't the back-gesture this listener exists for. Only a popstate that actually
      // moves away from `id` means someone backed (or another finish()) out of this overlay itself.
      if (history.state && history.state.ldOverlay === id) return;
      finish(undefined);
    }
    window.addEventListener('popstate', onPop);
    history.pushState({ ldOverlay: id }, '', location.href);
    return finish;
  }

  /* An in-app "are you sure?" box, used instead of the browser's own popup. Resolves true or false.
     Cancel has the focus to begin with, so pressing Enter by mistake never confirms a delete. */
  function confirmBox(message, { ok = 'Yes', title = 'Confirm', danger = false } = {}) {
    return new Promise((resolve) => {
      const previous = document.activeElement;
      const lockedBefore = document.body.classList.contains('locked');
      const cancelBtn = h('button', { class: 'btn', type: 'button' }, 'Cancel');
      const okBtn = h('button', { class: `btn ${danger ? 'danger-solid' : 'primary'}`, type: 'button' }, ok);
      const titleEl = h('h2', { id: 'confirm-title' }, title);
      const card = h('div', { class: 'confirm-card', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'confirm-title', 'aria-describedby': 'confirm-message' },
        titleEl, h('p', { id: 'confirm-message' }, message), h('div', { class: 'confirm-actions' }, cancelBtn, okBtn));
      const overlay = h('div', { class: 'confirm-overlay' }, card);

      const finish = closeOnBack((result) => {
        window.removeEventListener('keydown', onKey, true);
        overlay.remove();
        if (!lockedBefore) document.body.classList.remove('locked');
        if (previous && previous.isConnected) previous.focus();
        resolve(result ?? false);
      });
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); return; }
        if (e.key === 'Tab') {                                            // keep focus inside the box
          e.preventDefault();
          (document.activeElement === cancelBtn ? okBtn : cancelBtn).focus();
        }
      }
      cancelBtn.addEventListener('click', () => finish(false));
      okBtn.addEventListener('click', () => finish(true));
      overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(false); });
      window.addEventListener('keydown', onKey, true);
      document.body.classList.add('locked');
      document.body.append(overlay);
      cancelBtn.focus();
    });
  }

  /* An in-app list to choose one of several options, instead of the phone's own native <select> popup -
     which drops the app's own look and is awkward to scroll through on some phones. Resolves the chosen
     value, or undefined if closed without choosing. `items` is [{value, label}, ...]. */
  function pickList(items, selectedValue, { title = 'Choose an option' } = {}) {
    return new Promise((resolve) => {
      const finish = closeOnBack((result) => {
        window.removeEventListener('keydown', onKey);
        overlay.remove();
        resolve(result);
      });
      const list = h('ul', { class: 'picker-list', role: 'radiogroup', 'aria-label': title });
      items.forEach((opt) => {
        const selected = String(selectedValue ?? '') === String(opt.value);
        list.append(h('li', {
          class: `picker-row${selected ? ' selected' : ''}`, role: 'radio', 'aria-checked': String(selected), tabindex: '0',
          onclick: () => finish(opt.value),
          onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); finish(opt.value); } },
        }, h('span', {}, opt.label), h('span', { class: 'picker-dot', 'aria-hidden': 'true' })));
      });
      const card = h('div', { class: 'confirm-card picker-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, list);
      const overlay = h('div', { class: 'confirm-overlay', onclick: (e) => { if (e.target === overlay) finish(undefined); } }, card);
      function onKey(e) { if (e.key === 'Escape') finish(undefined); }
      window.addEventListener('keydown', onKey);
      document.body.append(overlay);
      (list.querySelector('.picker-row.selected') || list.firstChild)?.focus();
    });
  }

  /* A button that looks like a form field and, in place of a real <select>, opens the picker above. Reads
     and writes like an ordinary input - `.value` gets/sets the chosen value and a real change/input event
     fires on pick - so it drops into existing form code without that code needing to know the difference.
     `items` is [{value, label}, ...] (or plain strings, taken as value === label). */
  /* A site category picker: the list, plus "+ Add a new category…", which shows a box to type the name in.
     Reads and writes like selectField - `.value` is the chosen category, or whatever was typed for a new one -
     so forms can use it without knowing about the extra box. The typed name only counts once the admin has
     approved it; the server holds it until then. `names` are plain strings; `opts.blank` is the empty choice. */
  function categoryPicker(names, value, opts = {}) {
    const NEW = '__new__';
    const current = value || '';
    const items = [{ value: '', label: opts.blank || 'Not set' }, ...names.map((n) => ({ value: n, label: n }))];
    if (current && !names.includes(current)) items.push({ value: current, label: current });
    items.push({ value: NEW, label: '+ Add a new category…' });
    const sel = selectField(items, current, { title: opts.title || 'Site category', placeholder: opts.blank || 'Not set' });
    const typed = h('input', { type: 'text', maxlength: 60, autocomplete: 'off', placeholder: 'Name of the new category', hidden: true });
    typed.setAttribute('aria-label', 'New site category name');
    const wrap = h('div', { class: 'category-picker' }, sel, typed);
    sel.addEventListener('change', () => {
      typed.hidden = sel.value !== NEW;
      if (!typed.hidden) typed.focus();
    });
    Object.defineProperty(wrap, 'value', {
      get: () => (sel.value === NEW ? typed.value.trim() : sel.value),
      set: (v) => { sel.value = v || ''; typed.hidden = true; },
      configurable: true,
    });
    Object.defineProperty(wrap, 'disabled', {
      get: () => sel.disabled,
      set: (d) => { sel.disabled = d; typed.disabled = d; },
      configurable: true,
    });
    return wrap;
  }

  /* A role picker: the list, plus "+ Add a new role…", which shows a box to type the name in. Unlike
     categoryPicker, a role is a key/name pair (User.role_key and Worker.role_key are a real foreign key,
     not a free-text string) - so a typed name isn't usable on its own. `.value` is the chosen role's key,
     or '' while a new one is only typed, not created yet; `.newRoleName` is that typed name (trimmed), or
     '' otherwise. The caller POSTs /api/roles with it, gets the new key back, and sets `.value` to that
     before saving the form it's part of - see employeeForm in people.js or the Add user form in users.js
     for the exact sequence. `items` is [{value: key, label: name}, ...]; `opts.blank` is the empty choice,
     left out entirely (no "Not set") when the role itself is required, as it is for a user. */
  function rolePicker(items, value, opts = {}) {
    const NEW = '__new_role__';
    const current = value || '';
    let list = items.map((i) => (typeof i === 'object' ? i : { value: i, label: i }));
    const withExtras = () => {
      const out = opts.blank ? [{ value: '', label: opts.blank }] : [];
      out.push(...list, { value: NEW, label: '+ Add a new role…' });
      return out;
    };
    const sel = selectField(withExtras(), current, { title: opts.title || 'Role', placeholder: opts.blank || 'Choose a role' });
    const typed = h('input', { type: 'text', maxlength: 60, autocomplete: 'off', placeholder: 'Name of the new role', hidden: true });
    typed.setAttribute('aria-label', 'New role name');
    const wrap = h('div', { class: 'category-picker' }, sel, typed);
    sel.addEventListener('change', () => {
      typed.hidden = sel.value !== NEW;
      if (!typed.hidden) typed.focus();
    });
    Object.defineProperty(wrap, 'value', {
      get: () => (sel.value === NEW ? '' : sel.value),
      set: (v) => { sel.value = v || ''; typed.hidden = true; },
      configurable: true,
    });
    Object.defineProperty(wrap, 'newRoleName', {
      get: () => (sel.value === NEW ? typed.value.trim() : ''),
      configurable: true,
    });
    Object.defineProperty(wrap, 'disabled', {
      get: () => sel.disabled,
      set: (d) => { sel.disabled = d; typed.disabled = d; },
      configurable: true,
    });
    wrap.setOptions = (newItems) => { list = newItems.map((i) => (typeof i === 'object' ? i : { value: i, label: i })); sel.setOptions(withExtras()); };
    return wrap;
  }

  function selectField(items, value, opts = {}) {
    let list = items.map((i) => (typeof i === 'object' ? i : { value: i, label: i }));
    let current = value ?? '';
    const btn = h('button', { type: 'button', class: 'field-picker' });
    const relabel = () => {
      const found = list.find((i) => String(i.value) === String(current));
      btn.textContent = found ? found.label : (opts.placeholder || '');
      btn.classList.toggle('placeholder', !found);
    };
    Object.defineProperty(btn, 'value', {
      get: () => current,
      set: (v) => { current = v ?? ''; relabel(); },
      configurable: true,
    });
    relabel();
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      const chosen = await pickList(list, current, { title: opts.title || 'Choose an option' });
      if (chosen === undefined) return;
      btn.value = chosen;
      btn.dispatchEvent(new Event('input', { bubbles: true }));
      btn.dispatchEvent(new Event('change', { bubbles: true }));
    });
    btn.addOption = (val, label = val) => { list.push({ value: val, label }); };
    btn.removeOption = (val) => { list = list.filter((i) => String(i.value) !== String(val)); };
    btn.setOptions = (newItems) => {
      list = newItems.map((i) => (typeof i === 'object' ? i : { value: i, label: i }));
      relabel();
    };
    return btn;
  }

  /* Same job as selectField (pick one of `items`, `.value` is the chosen one), but search-as-you-type
     instead of a full-screen tap-to-pick list - for a long, open-ended list (every worker, every project,
     every supplier...) where scrolling to find one is slower than just typing a few letters (kohal,
     2026-10-19: "add the search feature, like in request material, everywhere" - this generalizes what was
     first built one-off as materialSearchField in projects.js). Same item shape as selectField
     ([{value,label}] or plain strings), same opts.placeholder - a drop-in swap at any selectField(...) call
     site backed by a long list. Matches anywhere in the label, case-insensitive, capped at 8; an empty
     query shows the first 8 items instead of nothing, so tapping in still offers something before typing. */
  function searchField(items, value, opts = {}) {
    const list = items.map((i) => (typeof i === 'object' ? i : { value: i, label: i }));
    let current = value != null ? String(value) : '';
    const found = () => list.find((i) => String(i.value) === current);
    const input = h('input', { type: 'text', autocomplete: 'off', placeholder: opts.placeholder || 'Search…' });
    input.value = found() ? found().label : '';
    const dropdown = h('ul', { class: 'name-suggest-list', role: 'listbox' });
    dropdown.hidden = true;
    const wrap = h('div', { class: 'name-suggest' }, input, dropdown);

    const closeList = () => { dropdown.hidden = true; clear(dropdown); };
    // Picking a row sets input.value by hand (not a real keystroke, so no native 'input' event fires for
    // it) and then dispatches one itself, so anything watching the field - the surrounding form's own
    // error-clearing, say - notices the change. That synthetic event reaches this field's *own* listener
    // too, though, which would otherwise stomp the pick right back to '' a tick later - this flag tells
    // that one "already handled, don't reset".
    let justPicked = false;
    const showMatches = () => {
      const q = input.value.trim().toLowerCase();
      const matches = (q ? list.filter((i) => i.label.toLowerCase().includes(q)) : list).slice(0, 8);
      clear(dropdown);
      if (!matches.length) { dropdown.hidden = true; return; }
      matches.forEach((i) => dropdown.append(h('li', {
        class: 'name-suggest-row', role: 'option', tabindex: '-1',
        onmousedown: (e) => e.preventDefault(),      // keep focus on the field, so the click lands before blur closes the list
        onclick: () => {
          current = String(i.value);
          input.value = i.label;
          closeList();
          justPicked = true;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        },
      }, i.label)));
      dropdown.hidden = false;
    };
    input.addEventListener('input', () => {
      if (justPicked) { justPicked = false; return; }
      current = '';
      showMatches();
    });
    input.addEventListener('focus', showMatches);
    input.addEventListener('blur', () => { setTimeout(closeList, 120); });

    Object.defineProperty(wrap, 'value', {
      get: () => current,
      set: (v) => { current = v != null ? String(v) : ''; const f = found(); input.value = f ? f.label : ''; },
      configurable: true,
    });
    Object.defineProperty(wrap, 'disabled', {
      get: () => input.disabled,
      set: (v) => { input.disabled = v; },
      configurable: true,
    });
    wrap.focus = () => input.focus();
    return wrap;
  }

  /* An in-app month calendar, instead of the phone's own native date popup. Resolves the chosen date as an
     ISO string ('' for "cleared"), or undefined if closed without choosing. */
  function pickDate(currentIso, opts = {}) {
    return new Promise((resolve) => {
      const today = new Date();
      const base = currentIso ? new Date(`${currentIso}T00:00:00`) : today;
      let viewYear = base.getFullYear();
      let viewMonth = base.getMonth();
      const toIso = (y, m, d) => `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      const todayIso = toIso(today.getFullYear(), today.getMonth(), today.getDate());

      const finish = closeOnBack((result) => {
        window.removeEventListener('keydown', onKey);
        overlay.remove();
        resolve(result);
      });
      const grid = h('div', { class: 'cal-grid' });
      const monthLabel = h('span', { class: 'cal-month-label' });
      const prevBtn = h('button', { type: 'button', class: 'cal-nav', 'aria-label': 'Previous month' }, '‹');
      const nextBtn = h('button', { type: 'button', class: 'cal-nav', 'aria-label': 'Next month' }, '›');

      function render() {
        clear(grid);
        monthLabel.textContent = new Date(viewYear, viewMonth, 1).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
        ['S', 'M', 'T', 'W', 'T', 'F', 'S'].forEach((d) => grid.append(h('span', { class: 'cal-weekday' }, d)));
        const firstDow = new Date(viewYear, viewMonth, 1).getDay();
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
        for (let i = 0; i < firstDow; i++) grid.append(h('span', { class: 'cal-cell empty' }));
        for (let d = 1; d <= daysInMonth; d++) {
          const iso = toIso(viewYear, viewMonth, d);
          grid.append(h('button', {
            type: 'button',
            class: `cal-cell${iso === currentIso ? ' selected' : ''}${iso === todayIso ? ' today' : ''}`,
            onclick: () => finish(iso),
          }, String(d)));
        }
      }
      prevBtn.onclick = () => { viewMonth -= 1; if (viewMonth < 0) { viewMonth = 11; viewYear -= 1; } render(); };
      nextBtn.onclick = () => { viewMonth += 1; if (viewMonth > 11) { viewMonth = 0; viewYear += 1; } render(); };
      render();

      const todayBtn = h('button', { type: 'button', class: 'btn small', onclick: () => finish(todayIso) }, 'Today');
      const clearBtn = opts.clearable === false ? null :
        h('button', { type: 'button', class: 'btn small', onclick: () => finish('') }, 'Clear');
      const card = h('div', { class: 'confirm-card cal-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Pick a date' },
        h('div', { class: 'cal-head' }, prevBtn, monthLabel, nextBtn),
        grid,
        h('div', { class: 'cal-actions' }, todayBtn, clearBtn));
      const overlay = h('div', { class: 'confirm-overlay', onclick: (e) => { if (e.target === overlay) finish(undefined); } }, card);
      function onKey(e) { if (e.key === 'Escape') finish(undefined); }
      window.addEventListener('keydown', onKey);
      document.body.append(overlay);
    });
  }

  /* A button that looks like a form field and, in place of a native date input, opens the calendar above.
     Reads and writes like an ordinary input - `.value` is an ISO date string ('' when empty) and a real
     change/input event fires on pick. `opts.placeholder` shows while empty; pass `clearable: false` for a
     date that must always have a value. */
  function dateField(value, opts = {}) {
    let current = value || '';
    const btn = h('button', { type: 'button', class: 'field-picker' });
    const fmt = (iso) => {
      if (!iso) return opts.placeholder || 'Date';
      const [y, m, d] = iso.split('-').map(Number);
      return new Date(y, m - 1, d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
    };
    const relabel = () => { btn.textContent = fmt(current); btn.classList.toggle('placeholder', !current); };
    Object.defineProperty(btn, 'value', {
      get: () => current,
      set: (v) => { current = v || ''; relabel(); },
      configurable: true,
    });
    relabel();
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      const chosen = await pickDate(current, opts);
      if (chosen === undefined) return;
      btn.value = chosen;
      btn.dispatchEvent(new Event('input', { bubbles: true }));
      btn.dispatchEvent(new Event('change', { bubbles: true }));
    });
    return btn;
  }

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  const money = (v, currency) => (v === null || v === undefined ? '' :
    currency + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(v));

  /* Indian short form for lists and summaries: ₹1.2 Cr, ₹12.4 L, ₹85k, ₹900. Full figures elsewhere use money(). */
  function fmtShort(v, currency = '\u20b9') {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '';
    const n = Number(v);
    const one = (x) => String(Math.round(x * 10) / 10);
    const abs = Math.abs(n);
    if (abs >= 1e7) return `${currency}${one(n / 1e7)} Cr`;
    if (abs >= 1e5) return `${currency}${one(n / 1e5)} L`;
    if (abs >= 1e3) return `${currency}${one(n / 1e3)}k`;
    return `${currency}${Math.round(n)}`;
  }

  /* A labelled form control with a slot for its error message. `name` becomes the id (f-name) and the key
     used to show a server-side error next to the right field. */
  function field(name, label, control, { wide = false, hint = null } = {}) {
    control.id = `f-${name}`;
    control.name = name;
    control.setAttribute('aria-describedby', `err-${name}`);
    return h('div', { class: `field${wide ? ' wide' : ''}` },
      h('label', { for: `f-${name}` }, label),
      control,
      hint ? h('p', { class: 'hint' }, hint) : null,
      h('p', { class: 'err', id: `err-${name}`, role: 'alert' }));
  }

  function showFieldErrors(form, fields) {
    form.querySelectorAll('.err').forEach((p) => { p.textContent = ''; });
    form.querySelectorAll('[aria-invalid]').forEach((i) => i.removeAttribute('aria-invalid'));
    let first = null;
    for (const [name, message] of Object.entries(fields || {})) {
      const p = form.querySelector(`#err-${name}`);
      if (p) p.textContent = message;
      const input = form.querySelector(`#f-${name}`);
      if (input) { input.setAttribute('aria-invalid', 'true'); first = first || input; }
    }
    return first;
  }

  /* Typing a full 6-digit pincode fills state, district and city (looked up on the server). They stay
     editable if the lookup is wrong or missing. */
  function pincodeLookup(pinInput, targets, hint) {
    let seq = 0;
    pinInput.addEventListener('input', async () => {
      const pin = pinInput.value.replace(/\D/g, '').slice(0, 6);
      if (pinInput.value !== pin) pinInput.value = pin;
      const mine = ++seq;
      if (pin.length < 6) { hint.textContent = ''; return; }
      hint.textContent = 'Looking up…';
      try {
        const found = await api(`/api/pincode/${pin}`);
        if (mine !== seq) return;
        targets.state.value = found.state;
        targets.district.value = found.district;
        targets.city.value = found.city;
        hint.textContent = `${found.city}, ${found.district}, ${found.state}`;
      } catch (err) {
        if (mine === seq) hint.textContent = err.message;
      }
    });
  }

  return {
    $, h, clear, api, toast, confirm: confirmBox, plural, money, fmtShort, field, showFieldErrors, pincodeLookup,
    pickList, selectField, searchField, categoryPicker, rolePicker, pickDate, dateField, closeOnBack,
  };
})();

/* The large app bar (Leads views, Me) shrinks into a compact sticky bar once its sentinel - pinned to the
   document at the bar's own (expanded) height - scrolls up past the fold. One observer, no scroll
   listener; every page with the large bar gets this for free since common.js loads on every signed-in
   page. The sentinel is positioned in JS, not CSS, because collapsing shrinks the bar's own layout
   height - anchoring the sentinel to that height (as a normal sibling right after it) would drag the
   sentinel up with it the moment it collapses, and it would never see itself scroll back into view. */
(() => {
  'use strict';
  const bar = document.getElementById('appbar');
  const sentinel = document.querySelector('.appbar-sentinel');
  if (!bar || !sentinel || !('IntersectionObserver' in window)) return;
  sentinel.style.top = `${bar.offsetHeight}px`;
  new IntersectionObserver(([entry]) => {
    bar.classList.toggle('is-collapsed', !entry.isIntersecting);
  }, { rootMargin: '-48px 0px 0px 0px' }).observe(sentinel);
})();

/* Announcements: a message from the admin, waiting on every page until dismissed (kohal, 2026-10-19: "the
   selected users should get a pop up as soon as they open the app and a cut option to remove the popup") -
   checked once per load here, not on any one page's own script, since common.js already runs on every
   signed-in page (see base.html). More than one waiting shows one at a time, oldest first. */
(() => {
  'use strict';
  const { h, api } = window.LD;
  const CLOSE_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  function showNext(queue) {
    if (!queue.length) return;
    const a = queue.shift();
    const closeBtn = h('button', { type: 'button', class: 'icon-btn announcement-close', 'aria-label': 'Dismiss' });
    closeBtn.innerHTML = CLOSE_SVG;
    const card = h('div', {
      class: 'confirm-card announcement-card', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'announce-title',
    },
      closeBtn,
      h('h2', { id: 'announce-title' }, a.created_by_name ? `From ${a.created_by_name}` : 'Announcement'),
      h('p', {}, a.message));
    const overlay = h('div', { class: 'confirm-overlay' }, card);
    document.body.append(overlay);

    closeBtn.onclick = async () => {
      overlay.remove();
      try { await api(`/api/me/announcements/${a.recipient_id}/dismiss`, { method: 'POST' }); } catch (err) { /* already gone either way - nothing to show the person for this */ }
      showNext(queue);
    };
  }

  (async () => {
    try {
      const data = await api('/api/me/announcements');
      if (data.announcements && data.announcements.length) showNext(data.announcements);
    } catch (err) { /* nothing waiting, or not actually signed in on this load - quietly skip either way */ }
  })();
})();

/* A rejected check-in, popped up the same way an announcement is (kohal, 2026-10-20: "a popup as soon as
   attendance was rejected so that user knows") - the session itself stays open with no other sign of this
   (see the Attendance page's own banner for that), so this is the only thing that actively tells them,
   wherever in the app they happen to be when they next load a page. */
(() => {
  'use strict';
  const { h, api } = window.LD;
  const CLOSE_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  const fmtDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  };

  function showNext(queue) {
    if (!queue.length) return;
    const a = queue.shift();
    const closeBtn = h('button', { type: 'button', class: 'icon-btn announcement-close', 'aria-label': 'Dismiss' });
    closeBtn.innerHTML = CLOSE_SVG;
    const card = h('div', {
      class: 'confirm-card announcement-card', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'rejection-title',
    },
      closeBtn,
      h('h2', { id: 'rejection-title' }, 'Attendance rejected'),
      h('p', {}, `Your check-in on ${fmtDate(a.work_date)}${a.work_label ? ` (${a.work_label})` : ''} was rejected${a.approved_by_name ? ` by ${a.approved_by_name}` : ''}. It won't count toward your attendance.`));
    const overlay = h('div', { class: 'confirm-overlay' }, card);
    document.body.append(overlay);

    closeBtn.onclick = async () => {
      overlay.remove();
      try { await api(`/api/attendance/${a.id}/dismiss-rejection`, { method: 'POST' }); } catch (err) { /* already gone either way */ }
      showNext(queue);
    };
  }

  (async () => {
    try {
      const data = await api('/api/attendance/rejections');
      if (data.rejections && data.rejections.length) showNext(data.rejections);
    } catch (err) { /* nothing waiting, or not actually signed in on this load - quietly skip either way */ }
  })();
})();

/* Pushed screens' "‹" appbar back link (the label is spoken, not shown - see app.css), for a page whose
   own client-side routing goes deeper than one level (a person's detail under Manpower & staff, say) -
   the nearer place (LD.setAppbarBack) is more useful there than jumping straight back to Me, which is
   already one tap further via the link it replaces. LD.resetAppbarBack puts it back once that page
   returns to its own top-level view. */
(() => {
  'use strict';
  const link = document.getElementById('appbar-back');
  if (!link) return;
  const original = { label: link.getAttribute('aria-label'), href: link.getAttribute('href') };
  window.LD.setAppbarBack = (label, href) => {
    link.setAttribute('aria-label', `Back to ${label}`);
    link.setAttribute('href', href);
  };
  window.LD.resetAppbarBack = () => {
    link.setAttribute('aria-label', original.label);
    link.setAttribute('href', original.href);
  };
})();
