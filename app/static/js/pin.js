/* PIN boxes on the sign-in and Set PIN pages (see _pin.html): mirror the hidden input's digits into the
   boxes, mark the next box to fill, and - on a field marked data-autosubmit - send the form as soon as all
   the digits are in and the rest of the form is filled. */
(() => {
  'use strict';

  document.querySelectorAll('.pin-entry').forEach((wrap) => {
    const input = wrap.querySelector('input');
    const boxes = [...wrap.querySelectorAll('.pin-boxes span')];
    const length = boxes.length;

    function sync() {
      const digits = input.value.replace(/\D/g, '').slice(0, length);
      if (input.value !== digits) input.value = digits;
      const focused = document.activeElement === input;
      boxes.forEach((box, i) => {
        box.textContent = i < digits.length ? '•' : '';
        box.classList.toggle('filled', i < digits.length);
        box.classList.toggle('next', focused && i === Math.min(digits.length, length - 1));
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
