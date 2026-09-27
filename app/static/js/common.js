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

      function finish(result) {
        window.removeEventListener('keydown', onKey, true);
        overlay.remove();
        if (!lockedBefore) document.body.classList.remove('locked');
        if (previous && previous.isConnected) previous.focus();
        resolve(result);
      }
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
      const finish = (result) => {
        window.removeEventListener('keydown', onKey);
        overlay.remove();
        resolve(result);
      };
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

      const finish = (result) => {
        window.removeEventListener('keydown', onKey);
        overlay.remove();
        resolve(result);
      };
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
    pickList, selectField, pickDate, dateField,
  };
})();
