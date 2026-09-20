/* The left menu. Shared by every service page: the top-left button opens it, and it closes on the
   dark backdrop, the X, Escape, or choosing an item. */
(() => {
  'use strict';

  const button = document.getElementById('menu-btn');
  const panel = document.getElementById('sidebar');
  const overlay = document.getElementById('menu-overlay');
  const closeButton = document.getElementById('menu-close');
  if (!button || !panel || !overlay) return;

  const isOpen = () => document.body.classList.contains('menu-open');

  function open() {
    document.body.classList.add('menu-open');
    button.setAttribute('aria-expanded', 'true');
    closeButton.focus();
  }

  function close(returnFocus = true) {
    if (!isOpen()) return;
    document.body.classList.remove('menu-open');
    button.setAttribute('aria-expanded', 'false');
    if (returnFocus) button.focus();
  }

  button.addEventListener('click', () => (isOpen() ? close() : open()));
  closeButton.addEventListener('click', () => close());
  overlay.addEventListener('click', () => close());
  // Choosing an item on the page you are already on (for example Users) changes only the hash, so close here.
  panel.querySelectorAll('a').forEach((a) => a.addEventListener('click', () => close(false)));

  document.addEventListener('keydown', (e) => {
    if (!isOpen()) return;
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Tab') return;

    // Keep keyboard focus inside the open menu.
    const focusable = [...panel.querySelectorAll('a[href], button:not([disabled])')];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
})();
