/* Proforma invoice / general quote: any business, free-text lines.
 * Separate from the travel quotes: saved in the `invoices` table, never on the supplier report.
 * app.js calls window.InvoiceModule(ctx) once it has logged in and loaded the data.
 * Each agent has their own letterhead (logo, company name and details, payment details, terms,
 * tax) in the agent_profiles table, saved to their login. A saved invoice shows the logo of
 * the agent who made it. The invoice being edited stays in this
 * browser under qc.invoiceDraft. Data shape: see DATA_FORMAT.md.
 */
window.InvoiceModule = function (ctx) {
  'use strict';
  const { $, esc, fmtNum, round2, uid, today, isValidDate, fmtDate, parseNum, setMsg, persist } = ctx;
  const DRAFT_KEY = 'qc.invoiceDraft';
  const TITLES = ['PROFORMA INVOICE', 'QUOTATION', 'ESTIMATE', 'INVOICE'];
  let invoices = ctx.invoices || [];
  let profiles = ctx.profiles || {};
  let showErrors = false, saving = false;

  const profile = (agent) => Object.assign({
    logo: '', companyName: ctx.settings().businessName === 'Your Business Name' ? '' : (ctx.settings().businessName || ''), companyDetails: ctx.settings().businessDetails || '',
    payment: '', terms: 'Prices are valid until the date shown. Payment confirms the booking.', taxLabel: 'GST', taxRate: 0, validDays: 14
  }, profiles[agent || ctx.agent()] || {});
  const isLogo = (s) => typeof s === 'string' && /^data:image\/(png|jpeg|webp|gif);base64,[a-z0-9+/=]+$/i.test(s);
  function addDays(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); const p = (x) => String(x).padStart(2, '0'); return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()); }

  function nextNumber(date) {
    const prefix = 'PI-' + String(date || today()).replace(/-/g, '') + '-';
    let max = 0;
    invoices.forEach((v) => { if (v.invoiceNumber && v.invoiceNumber.startsWith(prefix)) max = Math.max(max, parseInt(v.invoiceNumber.slice(prefix.length), 10) || 0); });
    return prefix + String(max + 1).padStart(3, '0');
  }
  const blankItem = () => ({ description: '', qty: 1, unitPrice: '' });
  function blankDraft() {
    const p = profile(), d = today();
    return { id: null, autoNumber: true, invoiceNumber: nextNumber(d), title: TITLES[0], date: d, validUntil: p.validDays ? addDays(d, Number(p.validDays)) : '',
      reference: '', companyName: p.companyName, companyDetails: p.companyDetails, clientName: '', clientDetails: '',
      currency: ctx.settings().currency || 'SGD', items: [blankItem()], discount: 0, taxLabel: p.taxLabel, taxRate: p.taxRate,
      notes: '', payment: p.payment, terms: p.terms, itemised: true };
  }
  function draftFrom(v) {
    return { id: v.id, createdBy: v.createdBy || '', autoNumber: false, invoiceNumber: v.invoiceNumber, title: v.title || TITLES[0], date: v.date, validUntil: v.validUntil || '',
      reference: v.reference || '', companyName: (v.company && v.company.name) || '', companyDetails: (v.company && v.company.details) || '',
      clientName: (v.billTo && v.billTo.name) || '', clientDetails: (v.billTo && v.billTo.details) || '', currency: v.currency || '',
      items: (v.items || []).map((l) => ({ description: l.description, qty: l.qty, unitPrice: l.unitPrice })), discount: v.discount || 0,
      taxLabel: v.taxLabel || '', taxRate: v.taxRate || 0, notes: v.notes || '', payment: v.payment || '', terms: v.terms || '', itemised: v.itemised !== false };
  }
  let draft = (() => { try { const d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); return d && Array.isArray(d.items) ? d : null; } catch (e) { return null; } })() || blankDraft();
  const saveDraft = () => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch (e) {} };

  // ---------- totals ----------
  const lineAmount = (l) => { const q = parseNum(l.qty), p = parseNum(l.unitPrice); return isNaN(q) || isNaN(p) ? 0 : round2(q * p); };
  function calc(d) {
    const subtotal = round2(d.items.reduce((s, l) => s + lineAmount(l), 0));
    const discount = round2(Math.max(0, parseNum(d.discount) || 0));
    const rate = Math.max(0, parseNum(d.taxRate) || 0);
    const tax = round2((subtotal - discount) * rate / 100);
    return { subtotal, discount, rate, tax, total: round2(subtotal - discount + tax) };
  }
  const money = (n, cur) => (cur ? cur + ' ' : '') + fmtNum(n);

  // ---------- validation ----------
  function validate(d) {
    const errors = [], fields = [];
    const bad = (sel, msg) => { fields.push(sel); if (msg && !errors.includes(msg)) errors.push(msg); };
    if (!String(d.companyName || '').trim()) bad('#invCoName', 'Enter your company name.');
    const num = String(d.invoiceNumber || '').trim();
    if (!num) bad('#invNumber', 'Enter a document number.');
    else if (invoices.some((v) => v.invoiceNumber.toLowerCase() === num.toLowerCase() && v.id !== d.id)) bad('#invNumber', 'Number ' + num + ' is already used by another saved invoice.');
    if (!isValidDate(d.date || '')) bad('#invDate', 'Enter the date.');
    if (d.validUntil && (!isValidDate(d.validUntil) || (isValidDate(d.date || '') && d.validUntil < d.date))) bad('#invValid', '"Valid until" must be on or after the date.');
    if (!String(d.clientName || '').trim()) bad('#invClient', 'Enter who the invoice is for (Bill to).');
    if (!d.items.length) errors.push('Add at least one line.');
    d.items.forEach((l, i) => {
      const n = 'Line ' + (i + 1) + ': ';
      if (!String(l.description || '').trim()) bad('#invItems [data-i="' + i + '"] [data-f="description"]', n + 'write a description.');
      const q = parseNum(l.qty); if (isNaN(q) || q <= 0) bad('#invItems [data-i="' + i + '"] [data-f="qty"]', n + 'quantity must be more than 0.');
      const p = parseNum(l.unitPrice); if (isNaN(p) || p < 0) bad('#invItems [data-i="' + i + '"] [data-f="unitPrice"]', n + 'enter a unit price (0 or more).');
    });
    const c = calc(d);
    const disc = parseNum(d.discount);
    if (d.discount !== '' && d.discount != null && (isNaN(disc) || disc < 0)) bad('#invDiscount', 'Discount must be 0 or more.');
    else if (c.discount > c.subtotal) bad('#invDiscount', 'Discount is more than the subtotal.');
    const r = parseNum(d.taxRate);
    if (d.taxRate !== '' && d.taxRate != null && (isNaN(r) || r < 0 || r > 100)) bad('#invTaxRate', 'Tax rate must be between 0 and 100.');
    if (!String(d.currency || '').trim()) bad('#invCurrency', 'Enter the currency.');
    return { errors, fields };
  }
  function showValidation(force) {
    document.querySelectorAll('#view-invoice .invalid').forEach((el) => el.classList.remove('invalid'));
    const v = validate(draft);
    if (!(showErrors || force) || !v.errors.length) { $('invValidation').classList.add('hidden'); return v; }
    v.fields.forEach((s) => { const el = document.querySelector(s); if (el) el.classList.add('invalid'); });
    $('invValidation').innerHTML = '<b>Fix these first:</b><ul>' + v.errors.map((e) => '<li>' + esc(e) + '</li>').join('') + '</ul>';
    $('invValidation').classList.remove('hidden');
    return v;
  }

  // ---------- editor ----------
  const FIELDS = { invCoName: 'companyName', invCoDetails: 'companyDetails', invTitle: 'title', invNumber: 'invoiceNumber', invDate: 'date',
    invValid: 'validUntil', invRef: 'reference', invClient: 'clientName', invClientDetails: 'clientDetails', invNotes: 'notes',
    invPayment: 'payment', invTerms: 'terms', invDiscount: 'discount', invTaxLabel: 'taxLabel', invTaxRate: 'taxRate', invCurrency: 'currency' };
  function renderLogo() {
    const logo = profile().logo;
    $('invLogoPreview').innerHTML = isLogo(logo) ? '<img alt="Company logo" src="' + logo + '">' : '<span>No logo yet</span>';
    $('invLogoRemove').classList.toggle('hidden', !isLogo(logo));
  }
  function itemHTML(l, i, n) {
    const k = ' data-i="' + i + '"';
    return '<div class="inv-item"' + k + '>' +
      '<div class="inv-no">' + (i + 1) + '</div>' +
      '<label class="inv-desc"><span class="sr">Description</span><textarea data-f="description" rows="2" placeholder="Description, e.g. 3D2N Bangkok package, twin sharing">' + esc(l.description) + '</textarea></label>' +
      '<div class="inv-nums">' +
        '<label>Qty<input type="number" inputmode="decimal" min="0" step="any" data-f="qty" value="' + esc(l.qty) + '"></label>' +
        '<label>Unit price<input type="number" inputmode="decimal" min="0" step="0.01" data-f="unitPrice" value="' + esc(l.unitPrice) + '" placeholder="0.00"></label>' +
        '<div class="inv-amt"><span>Amount</span><b data-amt>' + fmtNum(lineAmount(l)) + '</b></div>' +
      '</div>' +
      '<div class="inv-tools">' +
        '<button type="button" class="icon-btn" data-act="up"' + k + ' title="Move up"' + (i === 0 ? ' disabled' : '') + '>▲</button>' +
        '<button type="button" class="icon-btn" data-act="down"' + k + ' title="Move down"' + (i === n - 1 ? ' disabled' : '') + '>▼</button>' +
        '<button type="button" class="btn small ghost danger" data-act="del"' + k + ' title="Remove line">✕</button>' +
      '</div></div>';
  }
  function renderItems() {
    $('invItems').innerHTML = draft.items.map((l, i) => itemHTML(l, i, draft.items.length)).join('') ||
      '<p class="muted empty-day">No lines yet. Click "+ Add line".</p>';
  }
  function render() {
    $('invHeading').textContent = draft.id ? 'Editing ' + draft.invoiceNumber : 'New proforma invoice';
    Object.entries(FIELDS).forEach(([id, f]) => { $(id).value = draft[f] == null ? '' : draft[f]; });
    $('invItemised').checked = draft.itemised !== false;
    renderLogo(); renderItems(); updateTotals();
  }
  function updateTotals() {
    const c = calc(draft), cur = draft.currency;
    document.querySelectorAll('#invItems .inv-item').forEach((el) => { el.querySelector('[data-amt]').textContent = fmtNum(lineAmount(draft.items[el.dataset.i])); });
    $('invSub').textContent = money(c.subtotal, cur);
    $('invTaxAmt').textContent = money(c.tax, cur);
    $('invGrand').textContent = money(c.total, cur);
    $('mInvTotal').textContent = money(c.total, cur);
    $('invHeroSub').textContent = (draft.clientName ? draft.clientName + ' · ' : '') + draft.items.length + ' line' + (draft.items.length === 1 ? '' : 's');
    showValidation();
    if (!validate(draft).errors.length && $('invSaveMsg').classList.contains('err')) setMsg('invSaveMsg', '');
  }

  Object.entries(FIELDS).forEach(([id, f]) => {
    $(id).addEventListener('input', () => {
      draft[f] = $(id).value;
      if (id === 'invNumber') draft.autoNumber = false;
      if (id === 'invDate' && isValidDate(draft.date)) {
        if (draft.autoNumber && !draft.id) { draft.invoiceNumber = nextNumber(draft.date); $('invNumber').value = draft.invoiceNumber; }
      }
      saveDraft(); updateTotals();
    });
  });
  $('invItemised').addEventListener('change', () => { draft.itemised = $('invItemised').checked; saveDraft(); });
  $('invItems').addEventListener('input', (e) => {
    const el = e.target.closest('[data-f]'); const row = e.target.closest('.inv-item'); if (!el || !row) return;
    draft.items[row.dataset.i][el.dataset.f] = el.value; saveDraft(); updateTotals();
  });
  $('invItems').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const i = Number(b.dataset.i), it = draft.items;
    if (b.dataset.act === 'del') {
      if (String(it[i].description || '').trim() && !confirm('Remove line ' + (i + 1) + '?')) return;
      it.splice(i, 1);
    }
    if (b.dataset.act === 'up' && i > 0) [it[i - 1], it[i]] = [it[i], it[i - 1]];
    if (b.dataset.act === 'down' && i < it.length - 1) [it[i + 1], it[i]] = [it[i], it[i + 1]];
    saveDraft(); renderItems(); updateTotals();
  });
  $('invAddItem').addEventListener('click', () => {
    draft.items.push(blankItem()); saveDraft(); renderItems(); updateTotals();
    const ta = document.querySelector('#invItems .inv-item:last-child textarea'); if (ta) ta.focus();
  });
  $('invNewBtn').addEventListener('click', () => {
    const has = draft.clientName || draft.items.some((l) => String(l.description || '').trim());
    if (has && !draft.id && !confirm('Discard this unsaved invoice?')) return;
    draft = blankDraft(); showErrors = false; saveDraft(); setMsg('invSaveMsg', ''); render(); $('invClient').focus();
  });

  // ---------- company profile + logo (shared by everyone, saved in settings) ----------
  function saveProfile(patch, msgId, okText) {
    const before = profiles[ctx.agent()];
    const next = Object.assign({}, before || {}, patch);
    profiles[ctx.agent()] = next;
    setMsg(msgId, 'Saving…');
    return persist(Cloud.saveMyProfile(next), 'save your letterhead').then((ok) => {
      if (!ok) { if (before) profiles[ctx.agent()] = before; else delete profiles[ctx.agent()]; }
      setMsg(msgId, ok ? okText : 'Not saved.', ok ? 'ok' : 'err'); return ok;
    });
  }
  $('invCoSave').addEventListener('click', () => {
    if (!String(draft.companyName || '').trim()) { setMsg('invCoMsg', 'Enter the company name first.', 'err'); return; }
    const rate = parseNum(draft.taxRate);
    saveProfile({ companyName: String(draft.companyName).trim(), companyDetails: String(draft.companyDetails || '').trim(),
      payment: String(draft.payment || '').trim(), terms: String(draft.terms || '').trim(), taxLabel: String(draft.taxLabel || '').trim(),
      taxRate: isNaN(rate) ? 0 : rate }, 'invCoMsg', 'Saved to your login (' + ctx.agent() + '). Your new invoices start with these details.');
  });

  // Shrinks the picture so it stays small in the database (at most 600 × 240 pixels).
  function readLogo(file) {
    return new Promise((resolve, reject) => {
      if (!/^image\/(png|jpeg|webp|gif|svg\+xml)$/.test(file.type)) { reject(new Error('Choose a PNG, JPG, WebP, GIF or SVG picture.')); return; }
      if (file.size > 10 * 1024 * 1024) { reject(new Error('That picture is over 10 MB. Choose a smaller one.')); return; }
      const fr = new FileReader();
      fr.onerror = () => reject(new Error('That file could not be read.'));
      fr.onload = () => {
        const img = new Image();
        img.onerror = () => reject(new Error('That picture could not be opened.'));
        img.onload = () => {
          const w0 = img.naturalWidth || 600, h0 = img.naturalHeight || 240;
          const s = Math.min(1, 600 / w0, 240 / h0);
          const c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(w0 * s)); c.height = Math.max(1, Math.round(h0 * s));
          const g = c.getContext('2d');
          g.drawImage(img, 0, 0, c.width, c.height);
          let url = c.toDataURL('image/png');
          if (url.length > 300000) { // a big photo-like logo: JPEG on white is far smaller
            g.globalCompositeOperation = 'destination-over'; g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
            url = c.toDataURL('image/jpeg', 0.9);
          }
          resolve(url);
        };
        img.src = fr.result;
      };
      fr.readAsDataURL(file);
    });
  }
  $('invLogoInput').addEventListener('change', async (e) => {
    const f = e.target.files[0]; e.target.value = ''; if (!f) return;
    try {
      setMsg('invCoMsg', 'Uploading the logo…');
      const url = await readLogo(f);
      const ok = await saveProfile({ logo: url }, 'invCoMsg', 'Logo saved to your login (' + ctx.agent() + '). It shows on your invoices on any device.');
      renderLogo();
      if (!ok) setMsg('invCoMsg', 'The logo was not saved online. Try again.', 'err');
    } catch (err) { setMsg('invCoMsg', err.message, 'err'); }
  });
  $('invLogoRemove').addEventListener('click', () => {
    if (!confirm('Remove your logo? It disappears from all invoices you made.')) return;
    saveProfile({ logo: '' }, 'invCoMsg', 'Logo removed.').then(renderLogo);
  });

  // ---------- saving ----------
  function build(d) {
    const c = calc(d), rate = c.rate;
    return {
      title: String(d.title || '').trim() || TITLES[0], date: d.date, validUntil: d.validUntil || '', reference: String(d.reference || '').trim(),
      company: { name: String(d.companyName).trim(), details: String(d.companyDetails || '').trim() },
      billTo: { name: String(d.clientName).trim(), details: String(d.clientDetails || '').trim() },
      currency: String(d.currency || '').trim(),
      items: d.items.map((l) => ({ description: String(l.description).trim(), qty: Number(l.qty), unitPrice: round2(l.unitPrice), amount: lineAmount(l) })),
      subtotal: c.subtotal, discount: c.discount, taxLabel: String(d.taxLabel || '').trim(), taxRate: rate, tax: c.tax, total: c.total,
      notes: String(d.notes || '').trim(), payment: String(d.payment || '').trim(), terms: String(d.terms || '').trim(), itemised: d.itemised !== false
    };
  }
  async function saveCurrent() {
    if (saving) return null;
    showErrors = true;
    const v = showValidation(true);
    if (v.errors.length) { setMsg('invSaveMsg', 'Not saved. Fix the highlighted fields.', 'err'); return null; }
    saving = true;
    const btns = ['invSaveBtn', 'invPdfBtn', 'invPngBtn', 'mInvSave'].map($);
    btns.forEach((b) => { b.disabled = true; });
    setMsg('invSaveMsg', 'Saving…');
    try {
      const now = new Date().toISOString();
      const existing = draft.id ? invoices.find((x) => x.id === draft.id) : null;
      const inv = Object.assign({ id: draft.id || uid(), invoiceNumber: String(draft.invoiceNumber).trim() }, build(draft), {
        createdAt: existing ? existing.createdAt : now, updatedAt: now,
        createdBy: existing ? (existing.createdBy || '') : ctx.agent(), updatedBy: ctx.agent() });
      try {
        await Cloud.saveInvoice(inv);
      } catch (err) {
        // Someone else just saved the same automatic number: take the next one.
        if (existing || !draft.autoNumber || err.code !== '23505') throw err;
        invoices = await Cloud.loadInvoices();
        inv.invoiceNumber = nextNumber(draft.date);
        await Cloud.saveInvoice(inv);
      }
      const i = invoices.findIndex((x) => x.id === inv.id);
      if (i >= 0) invoices[i] = inv; else invoices.push(inv);
      draft.id = inv.id; draft.createdBy = inv.createdBy; draft.invoiceNumber = inv.invoiceNumber; draft.autoNumber = false; saveDraft();
      $('invNumber').value = inv.invoiceNumber;
      $('invHeading').textContent = 'Editing ' + inv.invoiceNumber;
      setMsg('invSaveMsg', 'Saved as ' + inv.invoiceNumber + ' (' + fmtDate(inv.date) + ').', 'ok');
      renderSaved();
      return inv;
    } catch (err) {
      console.error(err);
      setMsg('invSaveMsg', 'Not saved: ' + (err.code === '23505' ? 'that number is already used. Change the number.' : Cloud.explain(err)), 'err');
      return null;
    } finally {
      saving = false;
      btns.forEach((b) => { b.disabled = false; });
    }
  }

  // ---------- the document (PDF / PNG / preview) ----------
  function paperHTML(v, itemised) {
    const cur = v.currency, logo = profile(v.createdBy || ctx.agent()).logo;
    const pre = (s) => esc(s).replace(/\n/g, '<br>');
    let h = '<div class="i-head">' +
      '<div class="i-co">' + (isLogo(logo) ? '<img class="i-logo" alt="" src="' + logo + '">' : '') +
        '<div class="i-co-name">' + esc(v.company.name) + '</div>' + (v.company.details ? '<div class="i-co-det">' + pre(v.company.details) + '</div>' : '') + '</div>' +
      '<div class="i-doc"><div class="i-title">' + esc(v.title) + '</div><table class="i-meta">' +
        '<tr><td>No.</td><td>' + esc(v.invoiceNumber) + '</td></tr>' +
        '<tr><td>Date</td><td>' + esc(fmtDate(v.date)) + '</td></tr>' +
        (v.validUntil ? '<tr><td>Valid until</td><td>' + esc(fmtDate(v.validUntil)) + '</td></tr>' : '') +
      '</table></div></div>';
    h += '<div class="i-parties keep"><div class="i-box"><div class="i-label">Bill to</div><div class="i-client">' + esc(v.billTo.name) + '</div>' +
      (v.billTo.details ? '<div class="i-co-det">' + pre(v.billTo.details) + '</div>' : '') + '</div>' +
      (v.reference ? '<div class="i-box"><div class="i-label">Reference</div><div>' + pre(v.reference) + '</div></div>' : '') + '</div>';
    h += '<table class="i-items"><thead><tr><th class="i-n">#</th><th>Description</th>' +
      (itemised ? '<th class="num">Qty</th><th class="num">Unit price</th><th class="num">Amount' + (cur ? ' (' + esc(cur) + ')' : '') + '</th>' : '') + '</tr></thead><tbody>' +
      v.items.map((l, i) => '<tr><td class="i-n">' + (i + 1) + '</td><td class="i-d">' + pre(l.description) + '</td>' +
        (itemised ? '<td class="num">' + esc(String(l.qty)) + '</td><td class="num">' + fmtNum(l.unitPrice) + '</td><td class="num">' + fmtNum(l.amount) + '</td>' : '') + '</tr>').join('') +
      '</tbody></table>';
    const showSub = v.discount > 0 || v.tax > 0;
    h += '<div class="i-bottom keep"><table class="i-totals">' +
      (showSub ? '<tr><td>Subtotal</td><td class="num">' + money(v.subtotal, cur) + '</td></tr>' : '') +
      (v.discount > 0 ? '<tr><td>Discount</td><td class="num">− ' + money(v.discount, cur) + '</td></tr>' : '') +
      (v.tax > 0 ? '<tr><td>' + esc(v.taxLabel || 'Tax') + ' ' + esc(String(v.taxRate)) + '%</td><td class="num">' + money(v.tax, cur) + '</td></tr>' : '') +
      '<tr class="i-grand"><td>Total</td><td class="num">' + money(v.total, cur) + '</td></tr></table></div>';
    [['Notes', v.notes], ['Payment details', v.payment], ['Terms', v.terms]].forEach(([t, s]) => {
      if (s) h += '<div class="i-block keep"><div class="i-label">' + t + '</div><div>' + pre(s) + '</div></div>';
    });
    h += '<div class="i-sign keep"><div class="i-sigline"></div><div>Authorised signature</div><div class="i-co-det">for ' + esc(v.company.name) + '</div></div>';
    if (/proforma/i.test(v.title)) h += '<div class="i-foot">This is a proforma invoice, not a tax invoice. A final invoice will be issued on payment.</div>';
    return h;
  }
  const fileName = (v, itemised) => (v.invoiceNumber + '_' + (v.billTo.name || 'client')).replace(/[^a-z0-9_-]+/gi, '_').replace(/_+/g, '_').replace(/_$/, '').slice(0, 60) + (itemised ? '' : '_summary');
  const exportInv = (v, kind, itemised) => ctx.exportPaper(paperHTML(v, itemised), kind, fileName(v, itemised), { paperClass: 'inv-paper', avoidSplit: true });

  let pv = null, pvSaved = false;
  function openPreview(v, saved) {
    pv = v; pvSaved = saved;
    $('ipvItemised').checked = v.itemised !== false;
    $('ipvPdf').disabled = $('ipvPng').disabled = !saved;
    $('ipvPdf').title = $('ipvPng').title = saved ? '' : 'Save the invoice first';
    $('ipvNote').textContent = saved ? '' : 'Preview only. Save to download.';
    $('invPreviewModal').classList.remove('hidden');
    paintPreview();
  }
  function paintPreview() { $('ipaper').innerHTML = paperHTML(pv, $('ipvItemised').checked); ctx.fitPaper($('ipaper')); }
  $('ipvItemised').addEventListener('change', paintPreview);
  $('ipvClose').addEventListener('click', () => $('invPreviewModal').classList.add('hidden'));
  $('invPreviewModal').addEventListener('click', (e) => { if (e.target.id === 'invPreviewModal') $('invPreviewModal').classList.add('hidden'); });
  $('ipvPdf').addEventListener('click', () => pvSaved && exportInv(pv, 'pdf', $('ipvItemised').checked));
  $('ipvPng').addEventListener('click', () => pvSaved && exportInv(pv, 'png', $('ipvItemised').checked));

  $('invSaveBtn').addEventListener('click', saveCurrent);
  $('mInvSave').addEventListener('click', saveCurrent);
  $('invPdfBtn').addEventListener('click', async () => { const v = await saveCurrent(); if (v) exportInv(v, 'pdf', v.itemised); });
  $('invPngBtn').addEventListener('click', async () => { const v = await saveCurrent(); if (v) exportInv(v, 'png', v.itemised); });
  $('invPreviewBtn').addEventListener('click', () => openPreview(Object.assign({ invoiceNumber: String(draft.invoiceNumber || '').trim() || '(not saved yet)', createdBy: draft.createdBy || ctx.agent() }, build(draft)), false));

  // ---------- saved invoices ----------
  function renderSaved() {
    const s = $('ivSearch').value.trim().toLowerCase(), from = $('ivFrom').value, to = $('ivTo').value;
    const list = invoices.filter((v) =>
      (!s || [v.invoiceNumber, v.billTo && v.billTo.name, v.reference, v.createdBy].join(' ').toLowerCase().includes(s)) &&
      (!from || v.date >= from) && (!to || v.date <= to)
    ).sort((a, b) => (b.date + b.invoiceNumber).localeCompare(a.date + a.invoiceNumber));
    $('ivRows').innerHTML = list.map((v) =>
      '<tr><td>' + esc(fmtDate(v.date)) + '</td><td>' + esc(v.invoiceNumber) + '</td><td>' + esc(v.billTo ? v.billTo.name : '') + '</td>' +
      '<td>' + esc(v.reference || '') + '</td><td>' + esc(v.createdBy || '') + '</td><td class="num">' + esc(money(v.total, v.currency)) + '</td>' +
      '<td class="actions"><button class="btn small" data-act="view" data-id="' + esc(v.id) + '">View / download</button> ' +
      '<button class="btn small" data-act="edit" data-id="' + esc(v.id) + '">Edit</button> ' +
      '<button class="btn small" data-act="dup" data-id="' + esc(v.id) + '">Copy as new</button> ' +
      '<button class="btn small ghost danger" data-act="del" data-id="' + esc(v.id) + '">Delete</button></td></tr>').join('');
    $('ivEmpty').classList.toggle('hidden', list.length > 0);
    $('ivEmpty').textContent = invoices.length ? 'No invoices match.' : 'No saved invoices yet.';
  }
  ['ivSearch', 'ivFrom', 'ivTo'].forEach((id) => $(id).addEventListener('input', renderSaved));
  $('ivRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const v = invoices.find((x) => x.id === b.dataset.id); if (!v) return;
    const act = b.dataset.act;
    if (act === 'view') openPreview(v, true);
    if (act === 'edit' || act === 'dup') {
      const has = !draft.id && (draft.clientName || draft.items.some((l) => String(l.description || '').trim()));
      if (has && !confirm('You have an unsaved invoice open. Replace it?')) return;
      draft = draftFrom(v);
      if (act === 'dup') {
        const p = profile();
        draft.id = null; draft.createdBy = ''; draft.autoNumber = true; draft.date = today(); draft.invoiceNumber = nextNumber(draft.date);
        draft.validUntil = p.validDays ? addDays(draft.date, Number(p.validDays)) : '';
      }
      showErrors = false; saveDraft(); render();
      setMsg('invSaveMsg', act === 'dup' ? 'Copied. This will save as a new invoice.' : '');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    if (act === 'del') {
      if (!confirm('Delete ' + v.invoiceNumber + ' for ' + (v.billTo ? v.billTo.name : '') + '? This cannot be undone.')) return;
      b.disabled = true;
      persist(Cloud.deleteInvoice(v.id), 'delete the invoice').then((ok) => {
        if (!ok) { b.disabled = false; return; }
        invoices = invoices.filter((x) => x.id !== v.id);
        if (draft.id === v.id) { draft.id = null; draft.autoNumber = true; draft.invoiceNumber = nextNumber(draft.date); saveDraft(); render(); }
        renderSaved();
      });
    }
  });
  let refreshing = false;
  function refresh() {
    if (refreshing) return; refreshing = true;
    Promise.all([Cloud.loadInvoices(), Cloud.loadProfiles()]).then(([l, p]) => { invoices = l; profiles = p; renderSaved(); renderLogo(); }, (err) => Cloud.fail('load the latest invoices', err)).finally(() => { refreshing = false; });
  }

  // ---------- backup / restore ----------
  // Adds invoices from a backup: new ones are added, an existing one is replaced only by a newer copy.
  // A clashing number on a different invoice gets the next free automatic number.
  async function importList(list) {
    const res = { added: 0, updated: 0, renumbered: [] }, up = [];
    (Array.isArray(list) ? list : []).forEach((v0) => {
      const v = JSON.parse(JSON.stringify(v0));
      if (!v.id) v.id = uid();
      if (!isValidDate(v.date || '') || !Array.isArray(v.items)) return;
      v.billTo = v.billTo || { name: '', details: '' }; v.company = v.company || { name: '', details: '' };
      const i = invoices.findIndex((x) => x.id === v.id);
      if (i >= 0) {
        if (!(String(v.updatedAt || '') > String(invoices[i].updatedAt || ''))) return;
        v.invoiceNumber = invoices[i].invoiceNumber; invoices[i] = v; up.push(v); res.updated++; return;
      }
      if (!v.invoiceNumber || invoices.some((x) => x.invoiceNumber === v.invoiceNumber)) {
        const old = v.invoiceNumber; v.invoiceNumber = nextNumber(v.date); if (old) res.renumbered.push(old + ' → ' + v.invoiceNumber);
      }
      invoices.push(v); up.push(v); res.added++;
    });
    await Cloud.saveInvoices(up);
    return res;
  }

  render(); renderSaved();
  return {
    show() { refresh(); render(); },
    list: () => invoices,
    setList(l, p) { invoices = l || []; if (p) profiles = p; renderSaved(); renderLogo(); },
    importList,
  };
};
