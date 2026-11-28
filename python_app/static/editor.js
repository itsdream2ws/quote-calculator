/* The small bit of JavaScript for the quote and invoice pages.
 *
 * It has no prices, totals or rules in it: all of that is in Python (quotes.py, invoices.py).
 * This file only:
 *   1. reads every box on the page that has data-path="..." into one object (the "draft"),
 *   2. sends the draft to app.py when something changes, and shows the totals and problems
 *      that come back (each data-out="name" element gets the text for that name),
 *   3. sends button clicks (data-action="...") to app.py, which changes the draft and sends
 *      back new HTML for the form,
 *   4. keeps the unsaved draft in the browser (localStorage) so a refresh doesn't lose it.
 */
window.Editor = (function () {
  'use strict';
  let opts, showErrors = false, timer = null, busy = false;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];

  // ---------- 1. the draft <-> the boxes on the page ----------
  // "days.0.lines.2.adults" -> draft.days[0].lines[2].adults
  function setPath(obj, path, value) {
    const keys = path.split('.');
    let o = obj;
    keys.forEach((k, i) => {
      if (i === keys.length - 1) { o[k] = value; return; }
      if (o[k] == null) o[k] = /^\d+$/.test(keys[i + 1]) ? [] : {};
      o = o[k];
    });
  }
  function readDraft() {
    const d = { days: [], hotels: [], additional: [], items: [] };
    $$('#draftForm [data-path]').forEach((el) => {
      const type = el.dataset.type;
      if (type === 'radio') { if (el.checked) setPath(d, el.dataset.path, el.value === 'group'); return; }
      let v = el.value;
      if (type === 'number') v = v === '' ? '' : Number(v);
      if (type === 'checkbox') v = el.checked;
      if (type === 'bool') v = v === 'true';
      if (el.type === 'hidden' && v === '' && (el.dataset.path === 'id' || el.dataset.path === 'quoteNumber')) v = null;
      setPath(d, el.dataset.path, v);
    });
    d.days.forEach((day) => { if (day && !day.lines) day.lines = []; });
    if (opts.extra) Object.assign(d, opts.extra());
    return d;
  }
  function remember(d) { try { localStorage.setItem(opts.storageKey, JSON.stringify(d)); } catch (e) { /* private window */ } }
  function forget() { try { localStorage.removeItem(opts.storageKey); } catch (e) {} }

  // ---------- talking to app.py ----------
  async function post(path, body, asBlob) {
    const r = await fetch(opts.url + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error('The app answered ' + r.status + '. Is it still running?');
    return asBlob ? r.blob() : r.json();
  }

  // ---------- 2. totals and problems ----------
  function showCheck(c) {
    Object.entries(c.out).forEach(([name, text]) => $$('[data-out="' + name + '"]').forEach((el) => { el.textContent = text; }));
    const list = (title, items) => items.length ? '<b>' + title + '</b><ul>' + items.map((e) => '<li>' + esc(e) + '</li>').join('') + '</ul>' : '';
    $('#errors').innerHTML = list('Fix these before saving:', c.errors);
    $('#errors').classList.toggle('hidden', !c.errors.length);
    if ($('#warnings')) { $('#warnings').innerHTML = list('Check:', c.warnings); $('#warnings').classList.toggle('hidden', !c.warnings.length); }
    $$('#draftForm .invalid').forEach((el) => el.classList.remove('invalid'));
    c.bad.forEach((p) => $$('[data-path="' + p + '"]').forEach((el) => el.classList.add('invalid')));
    $$('#draftForm .edited').forEach((el) => el.classList.remove('edited'));
    c.edited.forEach((p) => $$('[data-path="' + p + '"]').forEach((el) => { el.classList.add('edited'); el.title = 'Changed for this quote only'; }));
    const group = !!readDraft().group;
    $$('[data-if-group]').forEach((el) => el.classList.toggle('hidden', !group));
    if (c.ok && $('#saveMsg').classList.contains('err')) setMsg('', '');
  }
  const esc = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  function setMsg(text, kind) { const m = $('#saveMsg'); m.textContent = text; m.className = 'msg' + (kind ? ' ' + kind : ''); }

  function changed() {
    const d = readDraft(); remember(d);
    clearTimeout(timer);
    timer = setTimeout(() => post('/check', { draft: d, showErrors }).then(showCheck).catch((e) => setMsg(e.message, 'err')), 250);
  }

  // ---------- 3. buttons ----------
  async function action(a, draft) {
    if (busy) return;
    busy = true;
    try {
      const res = await post('/action', { draft: draft || readDraft(), action: a, showErrors });
      $('#editor').innerHTML = res.html;
      // boxes outside the redrawn part that the server changed (e.g. a new automatic invoice number)
      Object.entries(res.draft).forEach(([k, v]) => {
        const el = $('#draftForm [data-path="' + k + '"]');
        if (el && !el.closest('#editor') && el.type !== 'radio' && el.type !== 'checkbox' && typeof v !== 'object') el.value = v == null ? '' : v;
      });
      remember(res.draft);
      showCheck(res.check);
      if (res.message && a.day != null) {
        const m = $('[data-day-msg="' + a.day + '"]');
        if (m) { m.textContent = res.message; m.className = 'msg ' + (res.kind || ''); }
      }
      if (res.kind === 'err' && a.code) { const box = $('[data-focus="code.' + a.day + '"]'); if (box) box.value = a.code; }
      if (res.focus) { const el = $('[data-path="' + res.focus + '"]') || $('[data-focus="' + res.focus + '"]'); if (el) { el.focus(); if (el.select) el.select(); } }
    } catch (e) { setMsg(e.message, 'err'); } finally { busy = false; }
  }
  function buttonAction(b) {
    if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
    const a = { name: b.dataset.action, day: b.dataset.day, index: b.dataset.index, meal: b.dataset.meal };
    if (a.name === 'add_transport') a.id = $('.tr-pick[data-day="' + a.day + '"]').value;
    action(a);
  }

  // ---------- saving, downloads, preview ----------
  async function save(kind) {
    if (busy) return;
    busy = true; showErrors = true;
    $$('[data-save]').forEach((b) => { b.disabled = true; });
    setMsg('Saving…');
    try {
      const res = await post('/save', { draft: readDraft() });
      showCheck(res.check);
      setMsg(res.message, res.saved ? 'ok' : 'err');
      if (!res.saved) return;
      // remember the id and number so the next save updates this quote instead of making a new one
      Object.entries({ id: res.id, quoteNumber: res.number, invoiceNumber: res.number, createdBy: res.draft.createdBy, autoNumber: false })
        .forEach(([k, v]) => { const el = $('[data-path="' + k + '"]'); if (el) el.value = v; });
      remember(readDraft());
      $('#heading').textContent = opts.heading(res.number);
      if (kind) {
        const itemised = readDraft().itemised !== false ? '1' : '0';
        window.location = opts.fileUrl(res.id) + kind + '?download=1&itemised=' + itemised;
      }
    } catch (e) { setMsg('Not saved: ' + e.message, 'err'); } finally {
      busy = false; $$('[data-save]').forEach((b) => { b.disabled = false; });
    }
  }
  async function preview() {
    const modal = $('#previewModal'), img = $('.preview-img', modal);
    modal.classList.remove('hidden'); img.classList.add('loading');
    try {
      const blob = await post('/preview', { draft: readDraft(), itemised: readDraft().itemised !== false }, true);
      if (img.src) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(blob);
    } catch (e) { modal.classList.add('hidden'); setMsg(e.message, 'err'); } finally { img.classList.remove('loading'); }
  }

  // ---------- start ----------
  function start(o) {
    opts = o;
    const form = $('#draftForm');
    form.addEventListener('input', (e) => {
      if (e.target.classList.contains('code-in')) {
        // picking a code from the suggestion list adds it straight away
        const listed = [...document.querySelectorAll('#codeList option')].some((op) => op.value === e.target.value);
        if (listed && (!e.inputType || e.inputType === 'insertReplacementText')) takeCode(e.target);
        return;
      }
      if (e.target.dataset.path) changed();
    });
    form.addEventListener('change', (e) => {
      const el = e.target;
      if (el.hasAttribute('data-redraw')) { action({ name: 'render' }); return; }
      if (el.dataset.path === 'adults' || el.dataset.path === 'children') {
        // lines that still had the old number of adults/children follow the new one
        action({ name: 'set_pax', field: el.dataset.path, old: el.dataset.old });
        el.dataset.old = el.value;
      }
      if (el.dataset.path === 'date' && o.onDateChange) action({ name: 'date_changed' });
    });
    form.addEventListener('focusin', (e) => { if (e.target.dataset.path === 'adults' || e.target.dataset.path === 'children') e.target.dataset.old = e.target.value; });
    form.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.classList.contains('code-in')) { e.preventDefault(); takeCode(e.target); }
    });
    form.addEventListener('click', (e) => { const b = e.target.closest('button[data-action]'); if (b) buttonAction(b); });
    $$('[data-save]').forEach((b) => b.addEventListener('click', () => save(b.dataset.save)));
    $$('[data-preview]').forEach((b) => b.addEventListener('click', preview));
    $$('[data-close]').forEach((b) => b.addEventListener('click', () => $('#previewModal').classList.add('hidden')));
    $('#previewModal').addEventListener('click', (e) => { if (e.target.id === 'previewModal') e.target.classList.add('hidden'); });
    $('#newBtn').addEventListener('click', () => {
      const d = readDraft();
      if (!d.id && o.hasContent && o.hasContent(d) && !confirm('Discard this unsaved one?')) return;
      forget(); window.location = o.newUrl;
    });

    let stored = null;
    try { stored = JSON.parse(localStorage.getItem(o.storageKey) || 'null'); } catch (e) {}
    if (o.restore && stored) action({ name: 'render' }, stored);  // bring back the unsaved one
    else {
      remember(readDraft());
      // Drop ?new / ?edit / ?copy from the address, so a refresh brings back what you are typing.
      const u = new URL(location.href);
      ['new', 'edit', 'copy'].forEach((k) => u.searchParams.delete(k));
      history.replaceState(null, '', u.pathname + u.search);
      changed();
    }
  }
  function takeCode(input) {
    const code = input.value; input.value = '';
    action({ name: 'add_code', day: input.dataset.day, code });
  }

  return { start, readDraft };
})();
