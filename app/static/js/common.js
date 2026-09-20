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

  let toastTimer;
  function toast(message, isError = false) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), isError ? 4500 : 2600);
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

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  const money = (v, currency) => (v === null || v === undefined ? '' :
    currency + new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(v));

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

  return { $, h, clear, api, toast, confirm: confirmBox, plural, money, field, showFieldErrors, pincodeLookup };
})();
