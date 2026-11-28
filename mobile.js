/* Phones: lists (saved quotes, price list, invoices, supplier report) are shown as cards
 * instead of wide tables. This copies each column heading onto its cells (data-label) so
 * styles.css can show "Client: Tan family" on small screens. Works on tables drawn later too.
 */
(function () {
  'use strict';
  function label(table) {
    const heads = [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim());
    if (!heads.length) return;
    table.classList.add('mcards');
    table.querySelectorAll('tbody tr').forEach((tr) => {
      let col = 0;
      [...tr.children].forEach((td) => {
        if (td.colSpan > 1) td.classList.add('m-wide');
        else if (!td.hasAttribute('data-label')) td.setAttribute('data-label', heads[col] || '');
        col += td.colSpan || 1;
      });
    });
  }
  const pick = (root) => root.querySelectorAll('main table:not(.lines)');
  function run() { pick(document).forEach((t) => { if (!t.closest('.paper')) label(t); }); }
  let queued = false;
  new MutationObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; run(); }); })
    .observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('DOMContentLoaded', run);
})();
