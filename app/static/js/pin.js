/* Boxes-per-character fields on the sign-in and Set PIN pages (see _pin.html): mirror the hidden input's
   characters into the boxes, mark the next box to fill, and - on a field marked data-autosubmit - send the
   form as soon as it's full and the rest of the form is filled. Two flavours share this:
     .pin-entry  - digits only, shown as dots (a PIN shouldn't be readable over someone's shoulder)
     .code-entry - the setup code: letters and digits, uppercased and shown as typed (nothing secret about
                   the first half - see _name_prefix in auth.py), 8 boxes grouped 4-and-4 around a plain
                   visual hyphen (.code-sep) that isn't one of the boxes and never holds a character. */
(() => {
  'use strict';

  document.querySelectorAll('.pin-entry, .code-entry').forEach((wrap) => {
    const input = wrap.querySelector('input');
    const isCode = wrap.classList.contains('code-entry');
    const boxes = [...wrap.querySelectorAll(isCode ? '.code-boxes span:not(.code-sep)' : '.pin-boxes span')];
    const length = boxes.length;
    const clean = (v) => (isCode ? v.replace(/[^A-Za-z0-9]/g, '').toUpperCase() : v.replace(/\D/g, '')).slice(0, length);

    function sync() {
      const value = clean(input.value);
      if (input.value !== value) input.value = value;
      const focused = document.activeElement === input;
      boxes.forEach((box, i) => {
        box.textContent = i < value.length ? (isCode ? value[i] : '•') : '';
        box.classList.toggle('filled', i < value.length);
        box.classList.toggle('next', focused && i === Math.min(value.length, length - 1));
      });
    }

    input.addEventListener('input', () => {
      sync();
      if ('autosubmit' in input.dataset && input.value.length === length && input.form.checkValidity()) {
        input.form.requestSubmit();
      }
    });
    input.addEventListener('focus', sync);
    input.addEventListener('blur', sync);
    sync();
  });
})();
