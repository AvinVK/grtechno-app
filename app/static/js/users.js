/* Users (admin only): add people, choose their role, hand out setup codes, reset a PIN, turn someone off.
   This is an app-wide screen, so it lives on its own page and not inside Leads. */
(() => {
  'use strict';

  const { $, h, clear, api, toast, plural, confirm } = window.LD;

  const chip = (tone, text) => h('span', { class: `chip chip-${tone}` }, text);

  /* ---------- users (admin only) ---------- */

  const STATUS_CHIPS = {
    active: ['active', 'Active'],
    pending: ['today', 'Waiting for PIN'],
    expired: ['overdue', 'Setup code expired'],
    off: ['off', 'Turned off'],
  };

  function usersView() {
    const wrap = h('div', { class: 'users' });
    const listBox = h('div', { class: 'user-list' }, h('p', { class: 'loading' }, 'Loading users…'));
    const resultBox = h('div', { hidden: true, 'aria-live': 'polite' });
    let roles = [];
    const roleSelect = h('select', { id: 'u-role', 'aria-label': 'Role' });

    function showCode(data, heading) {
      const u = data.user;
      const message = `Leads\nUserid: ${u.userid}\nSetup code: ${data.setup_code} (works once, valid ${data.code_days} days)\nSet your PIN at: ${window.location.origin}/set-pin`;
      clear(resultBox).append(h('section', { class: 'code-card' },
        h('h3', {}, `${heading} for ${u.name}`),
        h('dl', {},
          h('dt', {}, 'Userid'), h('dd', { class: 'code-value' }, u.userid),
          h('dt', {}, 'Setup code'), h('dd', { class: 'code-value' }, data.setup_code)),
        h('p', { class: 'hint' }, `Shown only now. It works once and is valid for ${data.code_days} days. ${u.name} opens the app, taps "Set a new PIN" on the sign-in page and enters both.`),
        h('div', { class: 'code-actions' },
          h('a', { class: 'btn primary', href: `https://wa.me/?text=${encodeURIComponent(message)}`, target: '_blank', rel: 'noopener noreferrer' }, 'Send on WhatsApp'),
          h('button', {
            class: 'btn', type: 'button',
            onclick: async () => {
              try { await navigator.clipboard.writeText(message); toast('Message copied'); }
              catch (err) { toast('Could not copy. Select the text and copy it.', true); }
            },
          }, 'Copy message'),
          h('button', { class: 'btn', type: 'button', onclick: () => { resultBox.hidden = true; clear(resultBox); } }, 'Done'))));
      resultBox.hidden = false;
      resultBox.scrollIntoView({ block: 'nearest' });
    }

    async function refresh() {
      try {
        const data = await api('/api/users');
        roles = data.roles;
        const chosen = roleSelect.value || 'sales_field';
        clear(roleSelect).append(...roles.map((r) => h('option', { value: r.key }, r.name)));
        roleSelect.value = chosen;
        clear(listBox).append(...data.users.map(userRow));
      } catch (err) {
        clear(listBox).append(h('p', { class: 'empty-state' }, err.message));
      }
    }

    async function act(path, body, ask, onOk) {
      if (ask && !(await confirm(ask.message, ask))) return;
      try {
        const data = await api(path, { method: 'POST', body });
        onOk(data);
      } catch (err) {
        toast(err.message, true);
      }
      await refresh();
    }

    function roleControl(u) {
      return h('select', {
        class: 'role-select', 'aria-label': `Role for ${u.name}`,
        onchange: async (e) => {
          const select = e.target;
          const next = roles.find((r) => r.key === select.value);
          const sure = await confirm(
            `Change ${u.name}'s role from ${u.role_name} to ${next.name}? What they can open and see changes straight away.`,
            { title: 'Change role', ok: 'Yes, change' });
          if (!sure) { select.value = u.role; return; }                   // cancelled: put the old role back
          act(`/api/users/${u.code}/role`, { role: next.key }, null,
            (data) => toast(`${u.name} is now ${data.user.role_name}`));
        },
      }, roles.map((r) => h('option', { value: r.key, selected: r.key === u.role }, r.name)));
    }

    function userRow(u) {
      const key = u.status === 'pending' && u.code_expired ? 'expired' : u.status;
      const [tone, label] = STATUS_CHIPS[key];
      const actions = u.is_admin ? null : h('div', { class: 'user-actions' },
        roleControl(u),
        h('button', {
          class: 'btn small', type: 'button',
          onclick: () => act(`/api/users/${u.code}/reset`, {},
            { title: u.status === 'pending' ? 'New setup code' : 'Reset PIN', ok: 'Yes, give new code',
              message: `Give ${u.name} a new setup code? Their current PIN stops working until they set a new one.` },
            (data) => showCode(data, 'New setup code')),
        }, u.status === 'pending' ? 'New setup code' : 'Reset PIN'),
        u.status === 'off'
          ? h('button', { class: 'btn small', type: 'button', onclick: () => act(`/api/users/${u.code}/active`, { active: true }, null, () => toast(`${u.name} is on again`)) }, 'Turn on')
          : h('button', {
            class: 'btn small danger', type: 'button',
            onclick: () => act(`/api/users/${u.code}/active`, { active: false },
              { title: 'Turn off user', ok: 'Yes, turn off', danger: true,
                message: `Turn off ${u.name}? They are signed out and cannot sign in until you turn them on again. Their leads stay.` },
              () => toast(`${u.name} is turned off`)),
          }, 'Turn off'));
      return h('article', { class: 'user-row' },
        h('div', { class: 'user-main' },
          h('span', { class: 'user-name' }, u.name, u.is_admin ? h('span', { class: 'user-tag' }, 'Admin') : null),
          h('span', { class: 'user-id' }, u.userid),
          h('span', { class: 'user-meta' }, `${u.role_name} \u00b7 ${plural(u.leads, 'lead', 'leads')}`)),
        chip(tone, label),
        actions);
    }

    const nameInput = h('input', { id: 'u-name', type: 'text', maxlength: 60, autocomplete: 'off', placeholder: 'For example: Ravi Kumar' });
    const nameErr = h('p', { class: 'err', role: 'alert' });
    const addBtn = h('button', { class: 'btn primary', type: 'submit' }, 'Add user');
    const form = h('form', {
      class: 'add-user', novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        nameErr.textContent = '';
        addBtn.disabled = true;
        try {
          const data = await api('/api/users', { method: 'POST', body: { name: nameInput.value, role: roleSelect.value } });
          nameInput.value = '';
          showCode(data, 'Setup code');
        } catch (err) {
          nameErr.textContent = err.message;
        } finally {
          addBtn.disabled = false;
        }
        await refresh();
      },
    },
      h('label', { for: 'u-name' }, 'Name'),
      nameInput,
      nameErr,
      h('label', { for: 'u-role' }, 'Role'),
      roleSelect,
      addBtn,
      h('p', { class: 'hint' }, 'The role decides which services they can open. The app gives them a userid (their name plus 4 digits) and a one-time setup code to share.'));

    wrap.append(h('h2', {}, 'Users & roles'), form, resultBox, listBox);
    refresh();
    return wrap;
  }

  clear($('#view')).append(usersView());
})();
