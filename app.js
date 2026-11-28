/* Quote Calculator — plain JS, no build step.
 * Price list, saved quotes and settings are stored online in Supabase (see cloud.js and
 * supabase/schema.sql); you have to log in first. The quote being edited (the draft) is kept
 * in this browser's localStorage under qc.draft, so a refresh doesn't lose work.
 * The objects the app works with are described in DATA_FORMAT.md.
 */
(async function () {
  'use strict';

  // ---------------- storage ----------------
  const DRAFT_KEY = 'qc.draft';
  const DEFAULT_SETTINGS = {
    businessName: 'Your Business Name',
    businessDetails: '',
    currency: 'SGD',
    defaultServiceCharge: 0,
    profitDisplay: 'service',
    footer: 'Prices are subject to availability at the time of booking.'
  };

  function load(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch (e) { return false; }
  }
  // Older price lists had one price per pax: use it for adults and children.
  function fixTicket(t) {
    if (t.adultPrice == null) t.adultPrice = Number(t.price) || 0;
    if (t.childPrice == null || t.childPrice === '') t.childPrice = t.adultPrice;
    t.price = t.adultPrice;
    return t;
  }

  // Log in, then read everything from the online database.
  await Cloud.requireLogin();
  Cloud.showLoading('Loading your quotes and price list…');
  let prices, quotes, settings, settingsSaved, invoicesLoaded = [], profilesLoaded = {};
  for (;;) {
    try {
      const d = await Cloud.loadAll();
      prices = d.prices; quotes = d.quotes; invoicesLoaded = d.invoices || []; profilesLoaded = d.profiles || {};
      settingsSaved = !!d.settings;
      settings = Object.assign({}, DEFAULT_SETTINGS, d.settings || {});
      break;
    } catch (err) {
      Cloud.showLoading('Could not load your data: ' + Cloud.explain(err) + ' Trying again in 5 seconds…');
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
  prices.tickets.forEach(fixTicket);
  prices.guides = prices.guides || [];
  Cloud.hideGate();

  // Writes to the online database run in the background; a failure shows a message.
  const persist = (promise, what) => promise.then(() => true, (err) => { Cloud.fail(what, err); return false; });
  const saveSettings = () => persist(Cloud.saveSettings(settings), 'save the settings').then((ok) => { if (ok) settingsSaved = true; return ok; });

  // ---------------- helpers ----------------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const round2 = (n) => Math.round((Number(n) + Number.EPSILON) * 100) / 100;
  const fmtNum = (n) => round2(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = (n) => (settings.currency ? settings.currency + ' ' : '') + fmtNum(n);
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  function isoDate(d) {
    const p = (x) => String(x).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }
  const today = () => isoDate(new Date());
  const thisMonth = () => today().slice(0, 7);
  const isValidDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(new Date(s + 'T00:00:00').getTime());
  function fmtDate(s) {
    if (!s) return '';
    const d = new Date(s + 'T00:00:00');
    return isNaN(d) ? s : d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  }
  function daysBetween(a, b) { return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000); }
  const parseNum = (v) => (v === '' || v == null ? NaN : Number(v));
  const normCode = (code) => String(code == null ? '' : code).trim().toUpperCase().replace(/\s+/g, '');
  const findTicket = (code) => prices.tickets.find((t) => t.code === normCode(code));
  const findTransport = (code) => { const c = normCode(code); return c ? prices.transport.find((t) => t.code === c) : undefined; };
  const findGuide = (code) => { const c = normCode(code); return c ? prices.guides.find((t) => t.code === c) : undefined; };
  // A code belongs to one ticket, transfer or guide only.
  const codeOwner = (code) => findTicket(code) || findTransport(code) || findGuide(code);
  const codeInUse = (code, except) => { const o = codeOwner(code); return !!o && o !== except; };
  const codeKind = (code) => (findTicket(code) ? 'a ticket' : findTransport(code) ? 'a transfer' : 'a guide');

  // Price status for a ticket in the price list.
  function ticketStatus(t) {
    const t0 = today();
    if (!t.validUntil || t.validUntil < t0) return { level: 'bad', text: 'Expired' };
    const left = daysBetween(t0, t.validUntil);
    if (!t.confirmedAt || t.confirmedAt.slice(0, 7) !== thisMonth()) return { level: 'warn', text: 'Confirm for this month' };
    if (left <= 7) return { level: 'warn', text: 'Expires in ' + left + ' day' + (left === 1 ? '' : 's') };
    return { level: 'ok', text: 'OK' };
  }

  // ---------------- tabs ----------------
  function showView(name) {
    document.querySelectorAll('button.tab').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('hidden', v.id !== 'view-' + name));
    if (name === 'saved') { renderSaved(); refreshSaved(); }
    if (name === 'prices') renderPrices();
    if (name === 'settings') renderSettings();
    if (name === 'quote') { refreshPickers(); renderQuote(); }
    if (name === 'invoice') Invoice.show();
    window.scrollTo(0, 0);
    try { history.replaceState(null, '', '#' + name); } catch (e) {}
  }
  document.querySelectorAll('button.tab').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));

  // ============================================================
  //                          QUOTE
  // ============================================================
  // Draft shape (what the quote page edits):
  //   { id, quoteNumber, clientName, adults, children, date, notes, serviceCharge (= profit), itemised,
  //     days: [{ date, lines: [TicketLine | TransportLine] }], hotels: [{ description, supplier, amount }] }
  //   TicketLine    { type:'ticket', code, name, supplier, adults, children, adultPrice, childPrice }
  //   TransportLine { type:'transport', code (optional), description, supplier, qty, unitPrice }
  //   MealLine      { type:'meal', meal:'Breakfast'|'Lunch'|'Dinner', description, supplier, adults, children, adultPrice, childPrice }
  //   GuideLine     { type:'guide', description, supplier, qty, unitPrice }
  // group: true for a group quote; additional: [{ description, supplier, amount }] only counts on group quotes.
  const childPriceOf = (t) => (t.childPrice === '' || t.childPrice == null ? Number(t.adultPrice != null ? t.adultPrice : t.price) : Number(t.childPrice));
  const adultPriceOf = (t) => Number(t.adultPrice != null ? t.adultPrice : t.price);
  function addDays(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return isoDate(d); }
  const paxLabel = (a, c) => (Number(a) || 0) + ' A' + ((Number(c) || 0) ? '+' + Number(c) + 'C' : '');

  function blankDraft() {
    return {
      id: null, quoteNumber: null, clientName: '', adults: 2, children: 0, date: today(), notes: '',
      serviceCharge: round2(settings.defaultServiceCharge || 0), itemised: true,
      days: [{ date: '', lines: [] }], hotels: [], group: false, additional: []
    };
  }
  const MEALS = ['Breakfast', 'Lunch', 'Dinner'];
  const perPax = (l) => l.type === 'ticket' || l.type === 'meal';

  // Turns a saved quote (new or old format) into an editable draft.
  function draftFromQuote(q) {
    const c = JSON.parse(JSON.stringify(q));
    if (Array.isArray(c.days)) {
      return { id: c.id, quoteNumber: c.quoteNumber, clientName: c.clientName || '', adults: c.adults != null ? c.adults : 1, children: c.children || 0,
        date: c.date, notes: c.notes || '', serviceCharge: c.serviceCharge, itemised: c.itemised !== false, days: c.days, hotels: c.hotels || [],
        group: c.quoteType === 'group', additional: c.additionalCharges || [] };
    }
    // Older quotes: separate ticket/transport lists with travel dates -> group by date.
    const byDate = {};
    const day = (d) => (byDate[d || ''] = byDate[d || ''] || { date: d || '', lines: [] });
    (c.tickets || []).forEach((l) => day(l.travelDate || l.date).lines.push({ type: 'ticket', code: l.code, name: l.name, supplier: l.supplier,
      adults: l.adults != null ? l.adults : l.pax, children: l.children || 0, adultPrice: l.adultPrice != null ? l.adultPrice : l.unitPrice, childPrice: l.childPrice != null ? l.childPrice : l.unitPrice }));
    (c.transport || []).forEach((l) => day(l.travelDate || l.date).lines.push({ type: 'transport', code: l.code || '', description: l.description, supplier: l.supplier, qty: l.qty, unitPrice: l.unitPrice }));
    const days = Object.keys(byDate).sort().map((k) => byDate[k]);
    const maxPax = Math.max(1, ...(c.tickets || []).map((l) => Number(l.pax) || 0));
    return { id: c.id, quoteNumber: c.quoteNumber, clientName: c.clientName || '', adults: c.adults != null ? c.adults : maxPax, children: c.children || 0,
      date: c.date, notes: c.notes || '', serviceCharge: c.serviceCharge, itemised: c.itemised !== false, days: days.length ? days : [{ date: '', lines: [] }], hotels: c.hotels || [] };
  }

  let draft = load(DRAFT_KEY, null);
  if (!draft || !Array.isArray(draft.days)) draft = draft && (draft.tickets || draft.transport) ? draftFromQuote(draft) : blankDraft();
  draft.group = !!draft.group; draft.additional = Array.isArray(draft.additional) ? draft.additional : [];
  let showErrors = false;
  const saveDraft = () => save(DRAFT_KEY, draft);

  function lineTotal(l) {
    if (perPax(l)) return round2((Number(l.adults) || 0) * (Number(l.adultPrice) || 0) + (Number(l.children) || 0) * (Number(l.childPrice) || 0));
    return round2((Number(l.qty) || 0) * (Number(l.unitPrice) || 0));
  }
  function calc(q) {
    let tickets = 0, transport = 0, meals = 0, guides = 0;
    q.days.forEach((d) => d.lines.forEach((l) => {
      const t = lineTotal(l);
      if (l.type === 'ticket') tickets += t; else if (l.type === 'meal') meals += t; else if (l.type === 'guide') guides += t; else transport += t;
    }));
    const hotel = (q.hotels || []).reduce((s, h) => s + (Number(h.amount) || 0), 0);
    const additional = q.group ? (q.additional || []).reduce((s, h) => s + (Number(h.amount) || 0), 0) : 0;
    const service = round2(Number(q.serviceCharge) || 0);
    tickets = round2(tickets); transport = round2(transport); meals = round2(meals); guides = round2(guides);
    return { tickets, transport, meals, guides, hotel: round2(hotel), additional: round2(additional), service,
      total: round2(tickets + transport + meals + guides + hotel + additional + service) };
  }

  function refreshPickers() {
    $('ticketList').innerHTML = prices.tickets.map((t) => '<option value="' + esc(t.code) + '">' +
      esc(t.code + ' — ' + t.name + ' (A ' + fmtNum(adultPriceOf(t)) + ' / C ' + fmtNum(childPriceOf(t)) + ')') + '</option>').join('') +
      prices.transport.filter((t) => t.code).map((t) => '<option value="' + esc(t.code) + '">' +
      esc(t.code + ' — ' + t.name + ' (transfer ' + fmtNum(t.price) + ')') + '</option>').join('') +
      prices.guides.map((t) => '<option value="' + esc(t.code) + '">' + esc(t.code + ' — Guide, ' + t.name + ' (' + fmtNum(t.price) + ')') + '</option>').join('');
    const sup = new Set(); prices.tickets.forEach((t) => t.supplier && sup.add(t.supplier)); prices.transport.forEach((t) => t.supplier && sup.add(t.supplier));
    prices.guides.forEach((t) => t.supplier && sup.add(t.supplier));
    (draft.hotels || []).forEach((h) => h.supplier && sup.add(h.supplier));
    (draft.additional || []).forEach((h) => h.supplier && sup.add(h.supplier));
    quotes.forEach((q) => (q.days || []).forEach((d) => d.lines.forEach((l) => { if ((l.type === 'meal' || l.type === 'guide') && l.supplier) sup.add(l.supplier); })));
    // Additional charges: a few common ones, plus anything typed on earlier quotes.
    const extras = new Set(['Coach / bus', 'Tour leader', 'Entrance permits', 'Tips', 'Group handling fee', 'Porterage']);
    quotes.forEach((q) => (q.additionalCharges || []).forEach((a) => a.description && extras.add(a.description)));
    $('extraList').innerHTML = [...extras].sort().map((x) => '<option value="' + esc(x) + '">').join('');
    $('supplierList').innerHTML = [...sup].sort().map((s) => '<option value="' + esc(s) + '">').join('');
  }
  const transportOptions = () => '<option value="">Custom transport line</option>' + prices.transport
    .map((t) => '<option value="' + esc(t.id) + '">' + esc((t.code ? t.code + ' — ' : '') + t.name + ' — ' + fmtNum(t.price)) + '</option>').join('');

  function lineRow(l, d, i, n) {
    const key = ' data-d="' + d + '" data-l="' + i + '"';
    const move = '<div class="mv"><button class="icon-btn" data-act="up"' + key + ' title="Move up"' + (i === 0 ? ' disabled' : '') + '>▲</button>' +
      '<button class="icon-btn" data-act="down"' + key + ' title="Move down"' + (i === n - 1 ? ' disabled' : '') + '>▼</button></div>';
    const del = '<button class="btn small ghost danger" data-act="del-line"' + key + ' title="Remove">✕</button>';
    if (l.type === 'ticket') {
      return '<tr class="ln ticket"' + key + '><td>' + move + '</td>' +
        '<td><span class="kind t">Attraction</span><div class="ln-name"><b class="code">' + esc(l.code) + '</b> ' + esc(l.name) + '</div><div class="ln-sup">' + esc(l.supplier) + '</div></td>' +
        '<td><div class="pax2"><label>A<input class="n" type="number" min="0" step="1" data-f="adults" value="' + esc(l.adults) + '"></label>' +
        '<label>C<input class="n" type="number" min="0" step="1" data-f="children" value="' + esc(l.children) + '"></label></div></td>' +
        '<td><div class="pax2"><label>A<input class="n price" type="number" min="0" step="0.01" data-f="adultPrice" value="' + esc(l.adultPrice) + '"></label>' +
        '<label>C<input class="n price" type="number" min="0" step="0.01" data-f="childPrice" value="' + esc(l.childPrice) + '"></label></div></td>' +
        '<td class="amt" data-amt></td><td>' + del + '</td></tr>';
    }
    if (l.type === 'meal') {
      return '<tr class="ln meal"' + key + '><td>' + move + '</td>' +
        '<td><span class="kind m">Meal</span><select class="meal-pick" data-f="meal">' + MEALS.map((m) => '<option' + (m === l.meal ? ' selected' : '') + '>' + m + '</option>').join('') + '</select>' +
        '<input data-f="description" placeholder="Restaurant or menu (optional)" value="' + esc(l.description) + '">' +
        '<input class="sup" data-f="supplier" placeholder="Supplier" list="supplierList" value="' + esc(l.supplier) + '"></td>' +
        '<td><div class="pax2"><label>A<input class="n" type="number" min="0" step="1" data-f="adults" value="' + esc(l.adults) + '"></label>' +
        '<label>C<input class="n" type="number" min="0" step="1" data-f="children" value="' + esc(l.children) + '"></label></div></td>' +
        '<td><div class="pax2"><label>A<input class="n price" type="number" min="0" step="0.01" data-f="adultPrice" value="' + esc(l.adultPrice) + '"></label>' +
        '<label>C<input class="n price" type="number" min="0" step="0.01" data-f="childPrice" value="' + esc(l.childPrice) + '"></label></div></td>' +
        '<td class="amt" data-amt></td><td>' + del + '</td></tr>';
    }
    if (l.type === 'guide') {
      return '<tr class="ln guide"' + key + '><td>' + move + '</td>' +
        '<td><span class="kind g">Guide</span>' + (l.code ? '<b class="code tr-code">' + esc(l.code) + '</b>' : '') + '<input data-f="description" placeholder="e.g. English-speaking guide, full day" value="' + esc(l.description) + '">' +
        '<input class="sup" data-f="supplier" placeholder="Supplier" list="supplierList" value="' + esc(l.supplier) + '"></td>' +
        '<td><div class="pax2"><label>Qty<input class="n" type="number" min="1" step="1" data-f="qty" value="' + esc(l.qty) + '"></label></div></td>' +
        '<td><div class="pax2"><label>Price<input class="n price" type="number" min="0" step="0.01" data-f="unitPrice" value="' + esc(l.unitPrice) + '"></label></div></td>' +
        '<td class="amt" data-amt></td><td>' + del + '</td></tr>';
    }
    return '<tr class="ln transport"' + key + '><td>' + move + '</td>' +
      '<td><span class="kind r">Transport</span>' + (l.code ? '<b class="code tr-code">' + esc(l.code) + '</b>' : '') + '<input data-f="description" placeholder="e.g. Transport from Night Safari (2 way)" value="' + esc(l.description) + '">' +
      '<input class="sup" data-f="supplier" placeholder="Supplier" list="supplierList" value="' + esc(l.supplier) + '"></td>' +
      '<td><div class="pax2"><label>Qty<input class="n" type="number" min="1" step="1" data-f="qty" value="' + esc(l.qty) + '"></label></div></td>' +
      '<td><div class="pax2"><label>Price<input class="n price" type="number" min="0" step="0.01" data-f="unitPrice" value="' + esc(l.unitPrice) + '"></label></div></td>' +
      '<td class="amt" data-amt></td><td>' + del + '</td></tr>';
  }

  function renderDays() {
    const topts = transportOptions();
    $('days').innerHTML = draft.days.map((day, d) =>
      '<div class="day" data-d="' + d + '">' +
        '<div class="day-head"><span class="day-no">Day ' + (d + 1) + '</span>' +
        '<input type="date" class="day-date" data-d="' + d + '" value="' + esc(day.date) + '">' +
        '<span class="day-dow">' + (day.date ? esc(new Date(day.date + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long' })) : '') + '</span>' +
        '<span class="day-sub" data-daysub="' + d + '"></span>' +
        '<button class="btn small ghost danger" data-act="del-day" data-d="' + d + '">Remove day</button></div>' +
        '<div class="scroll"><table class="lines day-lines"><tbody>' +
          (day.lines.map((l, i) => lineRow(l, d, i, day.lines.length)).join('') || '<tr><td colspan="6" class="muted empty-day">Nothing on this day yet. Type a ticket, transfer or guide code, or use the buttons below.</td></tr>') +
        '</tbody></table></div>' +
        '<div class="day-add">' +
          '<div class="cashier"><svg class="cashier-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>' +
          '<input class="code-in" data-d="' + d + '" list="ticketList" placeholder="Ticket, transfer or guide code, then Enter" autocomplete="off"></div>' +
          '<select class="tr-pick" data-d="' + d + '">' + topts + '</select>' +
          '<button class="btn" data-act="add-tr" data-d="' + d + '">+ Transport</button>' +
        '</div>' +
        '<div class="day-add day-extras">' + MEALS.map((m) => '<button class="btn small" data-act="add-meal" data-meal="' + m + '" data-d="' + d + '">+ ' + m + '</button>').join('') +
          '<button class="btn small" data-act="add-guide" data-d="' + d + '">+ Guide</button></div>' +
        '<div class="msg" data-codemsg="' + d + '"></div>' +
      '</div>').join('');
  }

  function renderHotels() {
    $('hotelRows').innerHTML = draft.hotels.map((h, i) =>
      '<tr data-h="' + i + '"><td><input data-f="description" placeholder="e.g. Grand Central (3 nights)" value="' + esc(h.description) + '"></td>' +
      '<td><input data-f="supplier" list="supplierList" placeholder="e.g. Booked direct" value="' + esc(h.supplier) + '"></td>' +
      '<td class="num"><input class="n price" type="number" min="0" step="0.01" data-f="amount" value="' + esc(h.amount) + '"></td>' +
      '<td><button class="btn small ghost danger" data-act="del-hotel" data-h="' + i + '" title="Remove">✕</button></td></tr>'
    ).join('') || '<tr><td colspan="4" class="muted">No hotel on this quote.</td></tr>';
  }

  function renderAdditional() {
    $('additionalCard').classList.toggle('hidden', !draft.group);
    $('additionalRows').innerHTML = draft.additional.map((h, i) =>
      '<tr data-x="' + i + '"><td><input data-f="description" list="extraList" placeholder="e.g. Coach / bus" value="' + esc(h.description) + '"></td>' +
      '<td><input data-f="supplier" list="supplierList" placeholder="Optional" value="' + esc(h.supplier) + '"></td>' +
      '<td class="num"><input class="n price" type="number" min="0" step="0.01" data-f="amount" value="' + esc(h.amount) + '"></td>' +
      '<td><button class="btn small ghost danger" data-act="del-extra" data-x="' + i + '" title="Remove">✕</button></td></tr>'
    ).join('') || '<tr><td colspan="4" class="muted">No additional charges.</td></tr>';
  }

  function renderQuote() {
    $('quoteHeading').textContent = draft.id ? 'Editing quote ' + draft.quoteNumber : 'New quote';
    $('qClient').value = draft.clientName;
    $('qAdults').value = draft.adults;
    $('qChildren').value = draft.children;
    $('qDate').value = draft.date;
    $('qNotes').value = draft.notes || '';
    $('qService').value = draft.serviceCharge;
    $('qItemised').checked = draft.itemised !== false;
    $('qTypeNormal').checked = !draft.group; $('qTypeGroup').checked = !!draft.group;
    $('profitHint').textContent = { service: 'shown as Service charge', hide: 'hidden from client', profit: 'shown as PROFIT' }[settings.profitDisplay] || '';
    renderDays(); renderHotels(); renderAdditional(); updateTotals();
  }

  const lineSel = (d, i, f) => '#days tr[data-d="' + d + '"][data-l="' + i + '"] [data-f="' + f + '"]';

  function updateTotals() {
    document.querySelectorAll('#days tr.ln').forEach((tr) => {
      const l = draft.days[tr.dataset.d].lines[tr.dataset.l];
      tr.querySelector('[data-amt]').textContent = fmtNum(lineTotal(l));
      if (l.type === 'ticket') {
        const t = findTicket(l.code);
        [['adultPrice', t && adultPriceOf(t)], ['childPrice', t && childPriceOf(t)]].forEach(([f, listP]) => {
          const el = tr.querySelector('[data-f="' + f + '"]');
          const edited = t && l[f] !== '' && round2(listP) !== round2(l[f]);
          el.classList.toggle('edited', !!edited);
          el.title = edited ? 'Changed for this quote. Price list: ' + fmtNum(listP) : 'You can change this for this quote only.';
        });
      }
    });
    draft.days.forEach((day, d) => {
      const el = document.querySelector('[data-daysub="' + d + '"]');
      if (el) el.textContent = day.lines.length ? fmtNum(day.lines.reduce((s, l) => s + lineTotal(l), 0)) : '';
    });
    const c = calc(draft);
    $('tTickets').textContent = money(c.tickets);
    $('tTransport').textContent = money(c.transport);
    $('tHotel').textContent = money(c.hotel);
    $('tMeals').textContent = money(c.meals + c.guides);
    $('tExtra').textContent = money(c.additional);
    document.querySelectorAll('.extra-total').forEach((el) => el.classList.toggle('hidden', !draft.group));
    $('tService').textContent = money(c.service);
    $('tGrand').textContent = money(c.total);
    $('tPax').textContent = (draft.clientName ? draft.clientName + ' · ' : '') + paxLabel(draft.adults, draft.children) + (draft.group ? ' · Group' : '');
    const v = validate(draft);
    renderWarnings(v.warnings);
    if (showErrors) renderErrors(v); else clearErrors();
    if (!v.errors.length && $('saveMsg').classList.contains('err')) setMsg('saveMsg', '');
  }

  // ---------- validation ----------
  const isWhole = (v, min) => { const n = parseNum(v); return Number.isInteger(n) && n >= min; };
  const isMoney = (v) => { const n = parseNum(v); return !isNaN(n) && n >= 0; };
  function validate(q) {
    const errors = [], bad = [], warnings = [];
    if (!q.clientName.trim()) { errors.push('Enter the client name.'); bad.push('#qClient'); }
    if (!isWhole(q.adults, 0)) { errors.push('Adults must be a whole number.'); bad.push('#qAdults'); }
    if (!isWhole(q.children, 0)) { errors.push('Children must be a whole number (0 if none).'); bad.push('#qChildren'); }
    if (isWhole(q.adults, 0) && isWhole(q.children, 0) && Number(q.adults) + Number(q.children) < 1) { errors.push('Enter at least 1 adult or child.'); bad.push('#qAdults'); }
    if (!isValidDate(q.date)) { errors.push('Enter a valid quote date.'); bad.push('#qDate'); }
    const lineCount = q.days.reduce((s, d) => s + d.lines.length, 0);
    if (!lineCount && !q.hotels.length && !(q.group && q.additional.length)) errors.push('Add at least one attraction, transport line or hotel.');
    if (!isMoney(q.serviceCharge)) { errors.push('Profit must be 0 or more.'); bad.push('#qService'); }
    const seen = {};
    q.days.forEach((day, d) => {
      const dn = 'Day ' + (d + 1);
      if (!isValidDate(day.date || '')) { errors.push(dn + ': enter the date.'); bad.push('.day-date[data-d="' + d + '"]'); }
      else if (seen[day.date]) warnings.push(dn + ' has the same date as Day ' + seen[day.date] + '.');
      else seen[day.date] = d + 1;
      if (!day.lines.length && (q.days.length > 1 || q.hotels.length === 0)) errors.push(dn + ' has nothing on it. Add a line or remove the day.');
      day.lines.forEach((l, i) => {
        if (l.type === 'ticket') {
          const n = dn + ', ' + l.code;
          if (!isWhole(l.adults, 0)) { errors.push(n + ': adults must be a whole number.'); bad.push(lineSel(d, i, 'adults')); }
          if (!isWhole(l.children, 0)) { errors.push(n + ': children must be a whole number.'); bad.push(lineSel(d, i, 'children')); }
          if (isWhole(l.adults, 0) && isWhole(l.children, 0) && Number(l.adults) + Number(l.children) < 1) { errors.push(n + ': needs at least 1 adult or child.'); bad.push(lineSel(d, i, 'adults')); }
          if (!isMoney(l.adultPrice)) { errors.push(n + ': adult price must be 0 or more.'); bad.push(lineSel(d, i, 'adultPrice')); }
          if (!isMoney(l.childPrice)) { errors.push(n + ': child price must be 0 or more.'); bad.push(lineSel(d, i, 'childPrice')); }
          const t = findTicket(l.code);
          if (!t) errors.push(n + ' is no longer in the price list.');
          else {
            const st = ticketStatus(t);
            if (st.level === 'bad') errors.push(n + ' price expired on ' + fmtDate(t.validUntil) + '. Update it in the price list.');
            else if (st.text === 'Confirm for this month') warnings.push(n + ' price has not been confirmed this month.');
            if (isMoney(l.adultPrice) && round2(adultPriceOf(t)) !== round2(l.adultPrice)) warnings.push(n + ' adult price is ' + fmtNum(l.adultPrice) + ' here; the price list says ' + fmtNum(adultPriceOf(t)) + '.');
            if (Number(l.children) > 0 && isMoney(l.childPrice) && round2(childPriceOf(t)) !== round2(l.childPrice)) warnings.push(n + ' child price is ' + fmtNum(l.childPrice) + ' here; the price list says ' + fmtNum(childPriceOf(t)) + '.');
          }
        } else if (l.type === 'meal') {
          const n = dn + ', ' + String(l.meal || 'meal').toLowerCase();
          if (!String(l.supplier).trim()) { errors.push(n + ': enter the supplier.'); bad.push(lineSel(d, i, 'supplier')); }
          if (!isWhole(l.adults, 0)) { errors.push(n + ': adults must be a whole number.'); bad.push(lineSel(d, i, 'adults')); }
          if (!isWhole(l.children, 0)) { errors.push(n + ': children must be a whole number.'); bad.push(lineSel(d, i, 'children')); }
          if (isWhole(l.adults, 0) && isWhole(l.children, 0) && Number(l.adults) + Number(l.children) < 1) { errors.push(n + ': needs at least 1 adult or child.'); bad.push(lineSel(d, i, 'adults')); }
          if (!isMoney(l.adultPrice)) { errors.push(n + ': adult price must be 0 or more.'); bad.push(lineSel(d, i, 'adultPrice')); }
          if (!isMoney(l.childPrice)) { errors.push(n + ': child price must be 0 or more.'); bad.push(lineSel(d, i, 'childPrice')); }
        } else if (l.type === 'guide') {
          const n = dn + ', guide';
          if (!String(l.supplier).trim()) { errors.push(n + ': enter the supplier.'); bad.push(lineSel(d, i, 'supplier')); }
          if (!isWhole(l.qty, 1)) { errors.push(n + ': quantity must be 1 or more.'); bad.push(lineSel(d, i, 'qty')); }
          if (!isMoney(l.unitPrice)) { errors.push(n + ': price must be 0 or more.'); bad.push(lineSel(d, i, 'unitPrice')); }
        } else {
          const n = dn + ', transport line ' + (i + 1);
          if (!String(l.description).trim()) { errors.push(n + ': enter a description.'); bad.push(lineSel(d, i, 'description')); }
          if (!String(l.supplier).trim()) { errors.push(n + ': enter the supplier.'); bad.push(lineSel(d, i, 'supplier')); }
          if (!isWhole(l.qty, 1)) { errors.push(n + ': quantity must be 1 or more.'); bad.push(lineSel(d, i, 'qty')); }
          if (!isMoney(l.unitPrice)) { errors.push(n + ': price must be 0 or more.'); bad.push(lineSel(d, i, 'unitPrice')); }
        }
      });
    });
    q.hotels.forEach((h, i) => {
      const n = 'Hotel ' + (i + 1);
      if (!String(h.description).trim()) { errors.push(n + ': enter the hotel name.'); bad.push('#hotelRows tr[data-h="' + i + '"] [data-f="description"]'); }
      if (!isMoney(h.amount)) { errors.push(n + ': amount must be 0 or more.'); bad.push('#hotelRows tr[data-h="' + i + '"] [data-f="amount"]'); }
    });
    if (q.group) q.additional.forEach((h, i) => {
      const n = 'Additional charge ' + (i + 1);
      if (!String(h.description).trim()) { errors.push(n + ': enter what it is for.'); bad.push('#additionalRows tr[data-x="' + i + '"] [data-f="description"]'); }
      if (!isMoney(h.amount)) { errors.push(n + ': amount must be 0 or more.'); bad.push('#additionalRows tr[data-x="' + i + '"] [data-f="amount"]'); }
    });
    return { errors, bad, warnings };
  }
  function clearErrors() {
    $('validation').classList.add('hidden');
    document.querySelectorAll('#view-quote .invalid').forEach((e) => e.classList.remove('invalid'));
  }
  function renderErrors(v) {
    clearErrors();
    if (!v.errors.length) return;
    $('validation').innerHTML = '<b>Fix these before saving:</b><ul>' + v.errors.map((e) => '<li>' + esc(e) + '</li>').join('') + '</ul>';
    $('validation').classList.remove('hidden');
    v.bad.forEach((sel) => { const el = document.querySelector(sel); if (el) el.classList.add('invalid'); });
  }
  function renderWarnings(w) {
    $('warnings').classList.toggle('hidden', !w.length);
    $('warnings').innerHTML = w.length ? '<b>Check:</b><ul>' + w.map((e) => '<li>' + esc(e) + '</li>').join('') + '</ul>' : '';
  }

  // ---------- editing ----------
  function setMsg(id, text, kind) { const el = typeof id === 'string' ? $(id) : id; if (!el) return; el.textContent = text; el.className = 'msg' + (kind ? ' ' + kind : ''); }
  function focusField(sel) { const el = document.querySelector(sel); if (el) { el.focus(); el.select && el.select(); } }
  const dayMsg = (d) => document.querySelector('[data-codemsg="' + d + '"]');

  function restoreCode(d, raw) { const el = document.querySelector('.code-in[data-d="' + d + '"]'); if (el) el.value = raw; }
  function addTransportLine(d, t) {
    draft.days[d].lines.push({ type: 'transport', code: t.code || '', description: t.name, supplier: t.supplier, qty: 1, unitPrice: round2(t.price) });
    saveDraft(); renderDays(); updateTotals();
    setMsg(dayMsg(d), 'Added ' + (t.code ? t.code + ' — ' : '') + t.name + '.', 'ok');
  }
  function addGuideLine(d, g) {
    draft.days[d].lines.push({ type: 'guide', code: g.code, description: g.name, supplier: g.supplier, qty: 1, unitPrice: round2(g.price) });
    saveDraft(); renderDays(); updateTotals();
    setMsg(dayMsg(d), 'Added guide ' + g.code + ' — ' + g.name + '.', 'ok');
  }
  function addByCode(d, raw) {
    raw = raw.trim(); if (!raw) return;
    let t = findTicket(raw);
    let tr = t ? null : findTransport(raw);
    let g = t || tr ? null : findGuide(raw);
    if (!t && !tr && !g) { // a unique part of the name also works
      const q = raw.toLowerCase();
      const m = prices.tickets.filter((x) => x.name.toLowerCase().includes(q));
      const mr = prices.transport.filter((x) => x.name.toLowerCase().includes(q));
      const mg = prices.guides.filter((x) => ('guide ' + x.name).toLowerCase().includes(q));
      if (m.length + mr.length + mg.length === 1) { t = m[0]; tr = mr[0]; g = mg[0]; }
      else { restoreCode(d, raw); setMsg(dayMsg(d), m.length + mr.length + mg.length ? 'More than one item matches "' + raw + '". Type the code.' : 'No ticket, transfer or guide with code "' + raw + '".', 'err'); return; }
    }
    if (tr) { addTransportLine(d, tr); focusField('.code-in[data-d="' + d + '"]'); return; }
    if (g) { addGuideLine(d, g); focusField('.code-in[data-d="' + d + '"]'); return; }
    const st = ticketStatus(t);
    if (st.level === 'bad') { restoreCode(d, raw); setMsg(dayMsg(d), t.code + ' price expired on ' + fmtDate(t.validUntil) + '. Update it in the price list first.', 'err'); return; }
    draft.days[d].lines.push({ type: 'ticket', code: t.code, name: t.name, supplier: t.supplier,
      adults: Number(draft.adults) || 0, children: Number(draft.children) || 0, adultPrice: round2(adultPriceOf(t)), childPrice: round2(childPriceOf(t)) });
    saveDraft(); renderDays(); updateTotals();
    setMsg(dayMsg(d), 'Added ' + t.code + ' — ' + t.name + '.' + (st.level === 'warn' ? ' (' + st.text + ')' : ''), 'ok');
    focusField('.code-in[data-d="' + d + '"]');
  }

  function takeCode(el) { const v = el.value; el.value = ''; addByCode(Number(el.dataset.d), v); }
  $('days').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.classList.contains('code-in')) { e.preventDefault(); takeCode(e.target); }
  });
  $('days').addEventListener('input', (e) => {
    const t = e.target;
    // picking a ticket from the suggestion list adds it straight away
    if (t.classList.contains('code-in')) { if ((!e.inputType || e.inputType === 'insertReplacementText') && codeOwner(t.value)) takeCode(t); return; }
    if (t.classList.contains('day-date')) {
      draft.days[t.dataset.d].date = t.value; saveDraft();
      const dow = t.parentNode.querySelector('.day-dow');
      dow.textContent = isValidDate(t.value) ? new Date(t.value + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long' }) : '';
      updateTotals(); return;
    }
    const f = t.dataset.f, tr = t.closest('tr.ln'); if (!f || !tr) return;
    let v = t.value;
    if (['adults', 'children', 'adultPrice', 'childPrice', 'qty', 'unitPrice'].includes(f)) v = v === '' ? '' : Number(v);
    draft.days[tr.dataset.d].lines[tr.dataset.l][f] = v;
    saveDraft(); updateTotals();
  });
  $('days').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const d = Number(b.dataset.d), i = Number(b.dataset.l), lines = draft.days[d] && draft.days[d].lines;
    switch (b.dataset.act) {
      case 'add-tr': {
        const sel = document.querySelector('.tr-pick[data-d="' + d + '"]');
        const t = prices.transport.find((x) => x.id === sel.value);
        lines.push(t ? { type: 'transport', code: t.code || '', description: t.name, supplier: t.supplier, qty: 1, unitPrice: round2(t.price) }
                     : { type: 'transport', description: '', supplier: '', qty: 1, unitPrice: '' });
        saveDraft(); renderDays(); updateTotals();
        focusField(lineSel(d, lines.length - 1, t ? 'unitPrice' : 'description'));
        return;
      }
      case 'add-meal':
        lines.push({ type: 'meal', meal: b.dataset.meal, description: '', supplier: '', adults: Number(draft.adults) || 0, children: Number(draft.children) || 0, adultPrice: '', childPrice: '' });
        saveDraft(); renderDays(); updateTotals(); refreshPickers();
        focusField(lineSel(d, lines.length - 1, 'description'));
        return;
      case 'add-guide':
        lines.push({ type: 'guide', description: '', supplier: '', qty: 1, unitPrice: '' });
        saveDraft(); renderDays(); updateTotals();
        focusField(lineSel(d, lines.length - 1, 'description'));
        return;
      case 'del-line': lines.splice(i, 1); break;
      case 'up': if (i > 0) [lines[i - 1], lines[i]] = [lines[i], lines[i - 1]]; break;
      case 'down': if (i < lines.length - 1) [lines[i + 1], lines[i]] = [lines[i], lines[i + 1]]; break;
      case 'del-day':
        if (draft.days[d].lines.length && !confirm('Remove Day ' + (d + 1) + ' and its ' + draft.days[d].lines.length + ' line(s)?')) return;
        draft.days.splice(d, 1);
        if (!draft.days.length) draft.days.push({ date: '', lines: [] });
        break;
      default: return;
    }
    saveDraft(); renderDays(); updateTotals();
  });
  $('addDayBtn').addEventListener('click', () => {
    const last = draft.days[draft.days.length - 1];
    draft.days.push({ date: last && isValidDate(last.date) ? addDays(last.date, 1) : '', lines: [] });
    saveDraft(); renderDays(); updateTotals();
    focusField('.code-in[data-d="' + (draft.days.length - 1) + '"]');
  });

  $('addHotelBtn').addEventListener('click', () => {
    draft.hotels.push({ description: '', supplier: '', amount: '' });
    saveDraft(); renderHotels(); updateTotals();
    focusField('#hotelRows tr[data-h="' + (draft.hotels.length - 1) + '"] [data-f="description"]');
  });
  $('hotelRows').addEventListener('input', (e) => {
    const f = e.target.dataset.f, tr = e.target.closest('tr[data-h]'); if (!f || !tr) return;
    draft.hotels[tr.dataset.h][f] = f === 'amount' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value;
    saveDraft(); updateTotals();
  });
  $('hotelRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-act="del-hotel"]'); if (!b) return;
    draft.hotels.splice(Number(b.dataset.h), 1); saveDraft(); renderHotels(); updateTotals();
  });

  ['qTypeNormal', 'qTypeGroup'].forEach((id) => $(id).addEventListener('change', () => {
    draft.group = $('qTypeGroup').checked; saveDraft(); renderAdditional(); updateTotals();
  }));
  $('addExtraBtn').addEventListener('click', () => {
    draft.additional.push({ description: '', supplier: '', amount: '' });
    saveDraft(); renderAdditional(); updateTotals();
    focusField('#additionalRows tr[data-x="' + (draft.additional.length - 1) + '"] [data-f="description"]');
  });
  $('additionalRows').addEventListener('input', (e) => {
    const f = e.target.dataset.f, tr = e.target.closest('tr[data-x]'); if (!f || !tr) return;
    draft.additional[tr.dataset.x][f] = f === 'amount' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value;
    saveDraft(); updateTotals();
  });
  $('additionalRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-act="del-extra"]'); if (!b) return;
    draft.additional.splice(Number(b.dataset.x), 1); saveDraft(); renderAdditional(); updateTotals();
  });

  // Changing the group's adults/children also updates ticket lines that still had the old numbers.
  function onPaxChange(field, el) {
    const old = Number(draft[field]);
    const v = el.value === '' ? '' : Number(el.value);
    draft.days.forEach((day) => day.lines.forEach((l) => { if (perPax(l) && Number(l[field]) === old && l[field] !== '') l[field] = v; }));
    draft[field] = v;
    saveDraft();
    document.querySelectorAll('#days [data-f="' + field + '"]').forEach((inp) => {
      const tr = inp.closest('tr.ln'); inp.value = draft.days[tr.dataset.d].lines[tr.dataset.l][field];
    });
    updateTotals();
  }
  $('qAdults').addEventListener('input', (e) => onPaxChange('adults', e.target));
  $('qChildren').addEventListener('input', (e) => onPaxChange('children', e.target));
  $('qClient').addEventListener('input', (e) => { draft.clientName = e.target.value; saveDraft(); updateTotals(); });
  $('qDate').addEventListener('input', (e) => { draft.date = e.target.value; saveDraft(); updateTotals(); });
  $('qNotes').addEventListener('input', (e) => { draft.notes = e.target.value; saveDraft(); });
  $('qService').addEventListener('input', (e) => { draft.serviceCharge = e.target.value === '' ? '' : Number(e.target.value); saveDraft(); updateTotals(); });
  $('qItemised').addEventListener('change', (e) => { draft.itemised = e.target.checked; saveDraft(); });

  // ---------- saving ----------
  function nextQuoteNumber(date) {
    const prefix = 'Q-' + date.replace(/-/g, '') + '-';
    let max = 0;
    quotes.forEach((q) => { if (q.quoteNumber && q.quoteNumber.startsWith(prefix)) max = Math.max(max, parseInt(q.quoteNumber.slice(prefix.length), 10) || 0); });
    return prefix + String(max + 1).padStart(3, '0');
  }

  // Builds the saved record. `days`/`hotels` keep the layout; `tickets`/`transport` are flat copies
  // (with travel dates and line totals) that the supplier report reads.
  function buildQuote(src, c) {
    const days = src.days.map((day) => ({ date: day.date, lines: day.lines.map((l) => l.type === 'ticket'
      ? { type: 'ticket', code: l.code, name: l.name, supplier: l.supplier, adults: Number(l.adults), children: Number(l.children), adultPrice: round2(l.adultPrice), childPrice: round2(l.childPrice), total: lineTotal(l) }
      : l.type === 'meal'
      ? { type: 'meal', meal: l.meal, description: String(l.description || '').trim(), supplier: String(l.supplier).trim(), adults: Number(l.adults), children: Number(l.children), adultPrice: round2(l.adultPrice), childPrice: round2(l.childPrice), total: lineTotal(l) }
      : l.type === 'guide'
      ? { type: 'guide', code: l.code || '', description: String(l.description || '').trim(), supplier: String(l.supplier).trim(), qty: Number(l.qty), unitPrice: round2(l.unitPrice), total: lineTotal(l) }
      : { type: 'transport', code: l.code || '', description: String(l.description).trim(), supplier: String(l.supplier).trim(), qty: Number(l.qty), unitPrice: round2(l.unitPrice), total: lineTotal(l) }) }));
    const tickets = [], transport = [], meals = [], guides = [];
    days.forEach((day) => day.lines.forEach((l) => {
      if (l.type === 'meal') {
        meals.push({ meal: l.meal, description: l.description, supplier: l.supplier, travelDate: day.date, adults: l.adults, children: l.children,
          adultPrice: l.adultPrice, childPrice: l.childPrice, pax: l.adults + l.children, total: l.total });
      } else if (l.type === 'guide') {
        guides.push({ code: l.code, description: l.description, supplier: l.supplier, travelDate: day.date, qty: l.qty, unitPrice: l.unitPrice, total: l.total });
      } else if (l.type === 'ticket') {
        const pax = l.adults + l.children;
        tickets.push({ code: l.code, name: l.name, supplier: l.supplier, travelDate: day.date, adults: l.adults, children: l.children,
          adultPrice: l.adultPrice, childPrice: l.childPrice, pax, unitPrice: pax ? round2(l.total / pax) : 0, total: l.total });
      } else {
        transport.push({ code: l.code, description: l.description, supplier: l.supplier, date: day.date, travelDate: day.date, qty: l.qty, unitPrice: l.unitPrice, total: l.total });
      }
    }));
    return {
      clientName: src.clientName.trim(), adults: Number(src.adults), children: Number(src.children), date: src.date,
      notes: (src.notes || '').trim(), currency: settings.currency, serviceCharge: c.service, itemised: src.itemised !== false,
      days, hotels: src.hotels.map((h) => ({ description: String(h.description).trim(), supplier: String(h.supplier || '').trim(), amount: round2(h.amount) })),
      quoteType: src.group ? 'group' : 'normal',
      additionalCharges: src.group ? (src.additional || []).map((h) => ({ description: String(h.description).trim(), supplier: String(h.supplier || '').trim(), amount: round2(h.amount) })) : [],
      tickets, transport, meals, guides,
      subtotalTickets: c.tickets, subtotalTransport: c.transport, subtotalMeals: c.meals, subtotalGuides: c.guides, subtotalHotel: c.hotel,
      subtotalAdditional: c.additional, total: c.total
    };
  }

  // Validates and saves the draft to the online database. Resolves with the saved quote or null.
  let saving = false;
  async function saveCurrent() {
    if (saving) return null; // ignore double clicks while a save is on its way
    showErrors = true;
    const v = validate(draft);
    renderErrors(v);
    if (v.errors.length) { setMsg('saveMsg', 'Not saved. Fix the highlighted fields.', 'err'); return null; }
    saving = true;
    const btns = ['saveBtn', 'pdfBtn', 'pngBtn'].map($);
    btns.forEach((b) => { b.disabled = true; });
    setMsg('saveMsg', 'Saving…');
    try {
      const c = calc(draft);
      const now = new Date().toISOString();
      const existing = draft.id ? quotes.find((q) => q.id === draft.id) : null;
      const q = Object.assign({
        id: draft.id || uid(),
        quoteNumber: existing ? existing.quoteNumber : nextQuoteNumber(draft.date)
      }, buildQuote(draft, c), { createdAt: existing ? existing.createdAt : now, updatedAt: now,
        createdBy: existing ? (existing.createdBy || '') : Cloud.agent, updatedBy: Cloud.agent });
      try {
        await Cloud.saveQuote(q);
      } catch (err) {
        // Someone else saved a quote with the same number a moment ago: fetch the latest list and renumber.
        if (existing || err.code !== '23505') throw err;
        quotes = await Cloud.loadQuotes();
        q.quoteNumber = nextQuoteNumber(draft.date);
        await Cloud.saveQuote(q);
      }
      const i = quotes.findIndex((x) => x.id === q.id);
      if (i >= 0) quotes[i] = q; else quotes.push(q);
      draft.id = q.id; draft.quoteNumber = q.quoteNumber; saveDraft();
      $('quoteHeading').textContent = 'Editing quote ' + q.quoteNumber;
      setMsg('saveMsg', 'Saved as ' + q.quoteNumber + ' (' + fmtDate(q.date) + ').', 'ok');
      return q;
    } catch (err) {
      console.error(err);
      setMsg('saveMsg', 'Not saved: ' + Cloud.explain(err), 'err');
      return null;
    } finally {
      saving = false;
      btns.forEach((b) => { b.disabled = false; });
    }
  }
  $('saveBtn').addEventListener('click', saveCurrent);
  $('pdfBtn').addEventListener('click', async () => { const q = await saveCurrent(); if (q) exportQuote(q, 'pdf', q.itemised); });
  $('pngBtn').addEventListener('click', async () => { const q = await saveCurrent(); if (q) exportQuote(q, 'png', q.itemised); });
  $('previewBtn').addEventListener('click', () => {
    openPreview(Object.assign({ quoteNumber: draft.quoteNumber || '(not saved yet)' }, buildQuote(draft, calc(draft))), false);
  });
  $('clearBtn').addEventListener('click', () => {
    const hasContent = draft.clientName || draft.hotels.length || draft.additional.length || draft.days.some((d) => d.lines.length);
    if (hasContent && !draft.id && !confirm('Discard this unsaved quote?')) return;
    draft = blankDraft(); showErrors = false; saveDraft(); setMsg('saveMsg', ''); renderQuote(); $('qClient').focus();
  });

  // ============================================================
  //                       EXPORT (PDF / PNG)
  // ============================================================
  // Laid out like the spreadsheet: client + pax on top, a block per day (date on the left,
  // attractions and transport in order, a total per line), then HOTEL, profit and TOTAL.
  function paperHTML(q, itemised) {
    const cur = q.currency || settings.currency;
    const m = (n) => (cur ? cur + ' ' : '') + fmtNum(n);
    const mode = settings.profitDisplay || 'service';
    const cols = itemised ? 3 : 2;
    const src = Array.isArray(q.days) ? q : buildQuote(draftFromQuote(q), calc(draftFromQuote(q)));
    const groupA = Number(src.adults) || 0, groupC = Number(src.children) || 0;
    let h = '<div class="p-head"><div><div class="p-biz">' + esc(settings.businessName) + '</div><div class="p-details">' + esc(settings.businessDetails) + '</div></div>' +
      '<div><div class="p-title">QUOTATION</div><div class="p-meta">No. ' + esc(q.quoteNumber) + '<br>Date: ' + esc(fmtDate(q.date)) + '</div></div></div>';
    h += '<table class="p-sheet"><thead>' +
      '<tr><th colspan="' + cols + '" class="p-client-bar">' + esc((src.clientName || '').toUpperCase()) + ' (' + esc(paxLabel(groupA, groupC)) + ')' + (src.quoteType === 'group' ? ' · GROUP' : '') + '</th></tr>' +
      '<tr><th class="c-date">Date</th><th>Transport and attractions</th>' + (itemised ? '<th class="num c-total">Total</th>' : '') + '</tr></thead><tbody>';
    src.days.forEach((day, di) => {
      if (di > 0) h += '<tr class="p-gap"><td colspan="' + cols + '"></td></tr>';
      day.lines.forEach((l, i) => {
        let label = l.type === 'ticket' ? l.name : l.description;
        if (l.type === 'ticket' && (l.adults !== groupA || l.children !== groupC)) label += ' (' + paxLabel(l.adults, l.children) + ')';
        if (l.type === 'meal') label = l.meal + (l.description ? ' — ' + l.description : '') + (l.adults !== groupA || l.children !== groupC ? ' (' + paxLabel(l.adults, l.children) + ')' : '');
        if (l.type === 'guide') label = 'Guide' + (l.description ? ' — ' + l.description : '');
        if ((l.type === 'transport' || l.type === 'guide') && l.qty > 1) label += ' × ' + l.qty;
        h += '<tr class="p-line">' +
          (i === 0 ? '<td class="c-date p-day" rowspan="' + day.lines.length + '"><b>' + esc(fmtDate(day.date)) + '</b><span>' +
            esc(new Date(day.date + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long' })) + '</span></td>' : '') +
          '<td>' + esc(label) + '</td>' + (itemised ? '<td class="num">' + fmtNum(l.total) + '</td>' : '') + '</tr>';
      });
    });
    if (src.hotels && src.hotels.length) {
      h += '<tr class="p-gap"><td colspan="' + cols + '"></td></tr>';
      src.hotels.forEach((ht, i) => {
        h += '<tr class="p-line p-hotel">' + (i === 0 ? '<td class="c-date p-tag" rowspan="' + src.hotels.length + '">Hotel</td>' : '') +
          '<td>' + esc(ht.description) + '</td>' + (itemised ? '<td class="num">' + fmtNum(ht.amount) + '</td>' : '') + '</tr>';
      });
    }
    const extra = src.quoteType === 'group' ? (src.additionalCharges || []) : [];
    if (extra.length) {
      h += '<tr class="p-gap"><td colspan="' + cols + '"></td></tr>';
      extra.forEach((x, i) => {
        h += '<tr class="p-line p-hotel">' + (i === 0 ? '<td class="c-date p-tag p-extra" rowspan="' + extra.length + '">Additional</td>' : '') +
          '<td>' + esc(x.description) + '</td>' + (itemised ? '<td class="num">' + fmtNum(x.amount) + '</td>' : '') + '</tr>';
      });
    }
    if (itemised && mode !== 'hide' && src.serviceCharge > 0) {
      h += '<tr class="p-line p-profit"><td class="c-date"></td><td class="right">' + (mode === 'profit' ? 'PROFIT' : 'Service charge') + '</td><td class="num">' + fmtNum(src.serviceCharge) + '</td></tr>';
    }
    h += '<tr class="p-grand"><td class="c-date"></td><td class="right">TOTAL</td>' + (itemised ? '<td class="num">' + m(src.total) + '</td>' : '') + '</tr>';
    if (!itemised) h = h.replace(/<td class="right">TOTAL<\/td><\/tr>$/, '<td class="right">TOTAL&nbsp;&nbsp;' + m(src.total) + '</td></tr>');
    h += '</tbody></table>';
    if (q.notes) h += '<div class="p-notes"><b>Notes</b><br>' + esc(q.notes) + '</div>';
    if (settings.footer) h += '<div class="p-foot">' + esc(settings.footer) + '</div>';
    return h;
  }

  function fileBase(q) {
    const client = (q.clientName || 'client').replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').slice(0, 40);
    return q.quoteNumber + '_' + client;
  }
  function download(href, name) {
    const a = document.createElement('a'); a.href = href; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  }

  const exportQuote = (q, kind, itemised) => exportPaper(paperHTML(q, itemised), kind, fileBase(q) + (itemised ? '' : '_summary'));

  // A4 is 210 × 297 mm; the paper is drawn 794 px wide, so one page is about 1123 px tall.
  // With avoidSplit, rows and blocks marked .keep that would be cut by a page break are pushed
  // to the next page, so no line of text is cut in half in the PDF.
  function keepOffPageBreaks(el) {
    const page = el.offsetWidth * 297 / 210, top0 = el.getBoundingClientRect().top;
    const items = [...el.querySelectorAll('tbody tr, .keep')];
    for (const it of items) {
      const r = it.getBoundingClientRect(), t = r.top - top0, b = r.bottom - top0;
      if (r.height >= page - 80) continue;
      const brk = Math.ceil(t / page) * page;
      if (b > brk - 2 && t < brk) {
        const push = brk - t + 36;
        if (it.tagName === 'TR') {
          const sp = document.createElement('tr'); sp.className = 'pg-space';
          sp.innerHTML = '<td colspan="20" style="height:' + push + 'px;padding:0;border:0;background:#fff"></td>';
          it.parentNode.insertBefore(sp, it);
        } else it.style.marginTop = (parseFloat(getComputedStyle(it).marginTop) || 0) + push + 'px';
      }
    }
  }
  async function exportPaper(html, kind, name, opts) {
    opts = opts || {};
    const stage = document.createElement('div');
    stage.style.cssText = 'position:absolute;left:-10000px;top:0;';
    stage.innerHTML = '<div class="paper ' + (opts.paperClass || '') + '">' + html + '</div>';
    document.body.appendChild(stage);
    const el = stage.firstChild;
    if (kind === 'png') el.style.minHeight = '0'; // PNG: crop to content; PDF keeps a full A4 page
    try {
      if (kind === 'pdf' && opts.avoidSplit) keepOffPageBreaks(el);
      const canvas = await window.html2canvas(el, { scale: 2, backgroundColor: '#ffffff', useCORS: true });
      if (kind === 'png') {
        download(canvas.toDataURL('image/png'), name + '.png');
      } else {
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
        const pageW = 210, pageH = 297;
        const imgH = canvas.height * pageW / canvas.width;
        const img = canvas.toDataURL('image/jpeg', 0.95);
        let y = 0;
        pdf.addImage(img, 'JPEG', 0, y, pageW, imgH);
        let left = imgH - pageH;
        while (left > 1) { y -= pageH; pdf.addPage(); pdf.addImage(img, 'JPEG', 0, y, pageW, imgH); left -= pageH; }
        pdf.save(name + '.pdf');
      }
    } catch (err) {
      alert('Export failed: ' + err.message);
    } finally {
      stage.remove();
    }
  }

  let previewQuote = null, previewSaved = false;
  function openPreview(q, saved) {
    previewQuote = q; previewSaved = saved;
    $('pvItemised').checked = q.itemised !== false;
    $('previewModal').classList.remove('hidden');
    $('paper').innerHTML = paperHTML(q, $('pvItemised').checked); fitPaper($('paper'));
    $('pvPdf').disabled = $('pvPng').disabled = !saved;
    $('pvPdf').title = $('pvPng').title = saved ? '' : 'Save the quote first';
    $('previewModal').classList.remove('hidden');
  }
  $('pvItemised').addEventListener('change', () => { $('paper').innerHTML = paperHTML(previewQuote, $('pvItemised').checked); fitPaper($('paper')); });
  $('pvClose').addEventListener('click', () => $('previewModal').classList.add('hidden'));
  $('previewModal').addEventListener('click', (e) => { if (e.target.id === 'previewModal') $('previewModal').classList.add('hidden'); });
  $('pvPdf').addEventListener('click', () => previewSaved && exportQuote(previewQuote, 'pdf', $('pvItemised').checked));
  $('pvPng').addEventListener('click', () => previewSaved && exportQuote(previewQuote, 'png', $('pvItemised').checked));

  // ============================================================
  //                       SAVED QUOTES
  // ============================================================
  // Opening Saved quotes also fetches the latest list, so quotes saved by others show up.
  let refreshing = false;
  function refreshSaved() {
    if (refreshing) return;
    refreshing = true;
    Cloud.loadQuotes().then((list) => { quotes = list; renderSaved(); }, (err) => Cloud.fail('load the latest quotes', err))
      .finally(() => { refreshing = false; });
  }
  function renderSaved() {
    const s = $('sSearch').value.trim().toLowerCase(), from = $('sFrom').value, to = $('sTo').value;
    const list = quotes.filter((q) =>
      (!s || q.clientName.toLowerCase().includes(s) || q.quoteNumber.toLowerCase().includes(s) || String(q.createdBy || '').toLowerCase().includes(s)) &&
      (!from || q.date >= from) && (!to || q.date <= to)
    ).sort((a, b) => (b.date + b.quoteNumber).localeCompare(a.date + a.quoteNumber));
    $('savedRows').innerHTML = list.map((q) =>
      '<tr><td>' + esc(fmtDate(q.date)) + '</td><td>' + esc(q.quoteNumber) + '</td><td>' + esc(q.clientName) + (q.quoteType === 'group' ? ' <span class="pill ok">Group</span>' : '') + '</td>' +
      '<td>' + esc(q.adults != null ? paxLabel(q.adults, q.children) : '') + '</td><td>' + esc(q.createdBy || '') + '</td><td class="num">' + esc((q.currency ? q.currency + ' ' : '') + fmtNum(q.total)) + '</td>' +
      '<td class="actions"><button class="btn small" data-act="view" data-id="' + esc(q.id) + '">View / download</button> ' +
      '<button class="btn small" data-act="edit" data-id="' + esc(q.id) + '">Edit</button> ' +
      '<button class="btn small" data-act="dup" data-id="' + esc(q.id) + '">Copy as new</button> ' +
      '<button class="btn small ghost danger" data-act="del" data-id="' + esc(q.id) + '">Delete</button></td></tr>'
    ).join('');
    $('savedEmpty').classList.toggle('hidden', list.length > 0);
    $('savedEmpty').textContent = quotes.length ? 'No quotes match.' : 'No saved quotes yet.';
  }
  ['sSearch', 'sFrom', 'sTo'].forEach((id) => $(id).addEventListener('input', renderSaved));
  $('savedRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const q = quotes.find((x) => x.id === b.dataset.id); if (!q) return;
    const act = b.dataset.act;
    if (act === 'view') openPreview(q, true);
    if (act === 'edit' || act === 'dup') {
      const hasContent = draft.hotels.length || draft.days.some((d) => d.lines.length);
      if (hasContent && !draft.id && !confirm('You have an unsaved quote open. Replace it?')) return;
      draft = draftFromQuote(q);
      if (act === 'dup') { draft.id = null; draft.quoteNumber = null; draft.date = today(); }
      showErrors = false; saveDraft(); setMsg('saveMsg', act === 'dup' ? 'Copied. This will save as a new quote.' : ''); showView('quote');
    }
    if (act === 'del') {
      if (!confirm('Delete quote ' + q.quoteNumber + ' for ' + q.clientName + '? This cannot be undone.')) return;
      b.disabled = true;
      persist(Cloud.deleteQuote(q.id), 'delete the quote').then((ok) => {
        if (!ok) { b.disabled = false; return; }
        quotes = quotes.filter((x) => x.id !== q.id);
        if (draft.id === q.id) { draft.id = null; draft.quoteNumber = null; saveDraft(); }
        renderSaved();
      });
    }
  });

  // ============================================================
  //                         PRICE LIST
  // ============================================================
  function renderPriceBadge() {
    const n = prices.tickets.filter((t) => ticketStatus(t).level !== 'ok').length;
    $('priceAlertBadge').textContent = n; $('priceAlertBadge').classList.toggle('hidden', n === 0);
  }
  function renderPrices() {
    refreshPickers();
    const f = $('tfFilter').value.trim().toLowerCase();
    const sorted = prices.tickets.slice().sort((a, b) => a.code.localeCompare(b.code));
    const expired = sorted.filter((t) => ticketStatus(t).level === 'bad').length;
    const unconf = sorted.filter((t) => ticketStatus(t).text === 'Confirm for this month').length;
    $('priceAlerts').innerHTML =
      (expired ? '<div class="alert bad">' + expired + ' ticket price' + (expired > 1 ? 's have' : ' has') + ' expired. Update the price and valid-until date.</div>' : '') +
      (unconf ? '<div class="alert warn">' + unconf + ' ticket price' + (unconf > 1 ? 's need' : ' needs') + ' confirming for ' + new Date().toLocaleDateString('en-GB', { month: 'long', year: 'numeric' }) + '.</div>' : '');
    $('ticketPriceRows').innerHTML = sorted.filter((t) => !f || (t.code + ' ' + t.name + ' ' + t.supplier).toLowerCase().includes(f)).map((t) => {
      const st = ticketStatus(t);
      return '<tr><td><b>' + esc(t.code) + '</b></td><td>' + esc(t.name) + '</td><td>' + esc(t.supplier) + '</td><td class="num">' + fmtNum(adultPriceOf(t)) + '</td><td class="num">' + fmtNum(childPriceOf(t)) + '</td>' +
        '<td>' + esc(fmtDate(t.validUntil)) + '</td><td>' + esc(fmtDate(t.confirmedAt)) + '</td><td><span class="pill ' + st.level + '">' + esc(st.text) + '</span></td>' +
        '<td class="actions">' + (st.level !== 'bad' ? '<button class="btn small" data-tact="confirm" data-code="' + esc(t.code) + '">Confirm</button> ' : '') +
        '<button class="btn small" data-tact="edit" data-code="' + esc(t.code) + '">Edit</button> ' +
        '<button class="btn small ghost danger" data-tact="del" data-code="' + esc(t.code) + '">Delete</button></td></tr>';
    }).join('') || '<tr><td colspan="9" class="muted">No tickets yet. Add one above, or load the sample price list from Settings.</td></tr>';

    const tf = $('trFilter').value.trim().toLowerCase();
    $('transportPriceRows').innerHTML = prices.transport.slice().sort((a, b) => (a.code || '~' + a.name).localeCompare(b.code || '~' + b.name))
      .filter((t) => !tf || ((t.code || '') + ' ' + t.name + ' ' + t.supplier).toLowerCase().includes(tf)).map((t) =>
      '<tr><td>' + (t.code ? '<b>' + esc(t.code) + '</b>' : '<span class="pill warn">Add a code</span>') + '</td><td>' + esc(t.name) + '</td><td>' + esc(t.supplier) + '</td><td class="num">' + fmtNum(t.price) + '</td>' +
      '<td class="actions"><button class="btn small" data-ract="edit" data-id="' + esc(t.id) + '">Edit</button> ' +
      '<button class="btn small ghost danger" data-ract="del" data-id="' + esc(t.id) + '">Delete</button></td></tr>'
    ).join('') || '<tr><td colspan="5" class="muted">No transport items yet.</td></tr>';
    const gf = $('gdFilter').value.trim().toLowerCase();
    $('guidePriceRows').innerHTML = prices.guides.slice().sort((a, b) => a.code.localeCompare(b.code))
      .filter((t) => !gf || (t.code + ' ' + t.name + ' ' + t.supplier).toLowerCase().includes(gf)).map((t) =>
      '<tr><td><b>' + esc(t.code) + '</b></td><td>' + esc(t.name) + '</td><td>' + esc(t.supplier) + '</td><td class="num">' + fmtNum(t.price) + '</td>' +
      '<td class="actions"><button class="btn small" data-gact="edit" data-id="' + esc(t.id) + '">Edit</button> ' +
      '<button class="btn small ghost danger" data-gact="del" data-id="' + esc(t.id) + '">Delete</button></td></tr>'
    ).join('') || '<tr><td colspan="5" class="muted">No guides yet.</td></tr>';
    renderPriceBadge();
  }
  $('tfFilter').addEventListener('input', renderPrices);
  $('gdFilter').addEventListener('input', renderPrices);
  $('trFilter').addEventListener('input', renderPrices);

  function resetTicketForm() {
    $('ticketForm').reset(); $('tfEditing').value = '';
    $('tfSubmit').textContent = 'Add ticket'; $('tfCancel').classList.add('hidden');
  }
  $('tfCancel').addEventListener('click', resetTicketForm);
  $('ticketForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const code = $('tfCode').value.trim().toUpperCase().replace(/\s+/g, '');
    const name = $('tfName').value.trim(), supplier = $('tfSupplier').value.trim();
    const price = parseNum($('tfPrice').value), validUntil = $('tfValid').value;
    const child = $('tfChild').value === '' ? price : parseNum($('tfChild').value);
    const editing = $('tfEditing').value;
    if (!code || !name || !supplier) return setMsg('tfMsg', 'Code, name and supplier are required.', 'err');
    if (isNaN(price) || price < 0) return setMsg('tfMsg', 'Adult price must be 0 or more.', 'err');
    if (isNaN(child) || child < 0) return setMsg('tfMsg', 'Child price must be 0 or more (or leave it blank).', 'err');
    if (!isValidDate(validUntil)) return setMsg('tfMsg', 'Enter a valid "valid until" date.', 'err');
    if (code !== editing && codeInUse(code)) return setMsg('tfMsg', 'Code ' + code + ' is already used by ' + (findTicket(code) ? 'another ticket' : codeKind(code)) + '.', 'err');
    const item = { code, name, supplier, adultPrice: round2(price), childPrice: round2(child), price: round2(price), validUntil, confirmedAt: today() };
    if (editing) {
      const i = prices.tickets.findIndex((t) => t.code === editing);
      prices.tickets[i] = item;
    } else prices.tickets.push(item);
    // A changed code is a new row: save it, then remove the old one.
    persist(Cloud.upsertTickets([item]).then(() => (editing && editing !== code ? Cloud.deleteTicket(editing) : null)), 'save ticket ' + code);
    resetTicketForm(); renderPrices(); setMsg('tfMsg', (editing ? 'Updated ' : 'Added ') + code + '.', 'ok'); $('tfCode').focus();
  });
  $('ticketPriceRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-tact]'); if (!b) return;
    const t = findTicket(b.dataset.code); if (!t) return;
    if (b.dataset.tact === 'confirm') { t.confirmedAt = today(); persist(Cloud.upsertTickets([t]), 'confirm ' + t.code); renderPrices(); }
    if (b.dataset.tact === 'edit') {
      $('tfEditing').value = t.code; $('tfCode').value = t.code; $('tfName').value = t.name; $('tfSupplier').value = t.supplier;
      $('tfPrice').value = adultPriceOf(t); $('tfChild').value = childPriceOf(t); $('tfValid').value = t.validUntil;
      $('tfSubmit').textContent = 'Save changes'; $('tfCancel').classList.remove('hidden'); $('tfPrice').focus();
    }
    if (b.dataset.tact === 'del' && confirm('Delete ticket ' + t.code + ' — ' + t.name + '? Saved quotes keep their copy.')) {
      prices.tickets = prices.tickets.filter((x) => x !== t); persist(Cloud.deleteTicket(t.code), 'delete ' + t.code); renderPrices();
    }
  });
  $('confirmAllBtn').addEventListener('click', () => {
    const done = [];
    prices.tickets.forEach((t) => { if (ticketStatus(t).level !== 'bad') { t.confirmedAt = today(); done.push(t); } });
    const n = done.length;
    if (n) persist(Cloud.upsertTickets(done), 'confirm the prices');
    renderPrices();
    if (prices.tickets.some((t) => ticketStatus(t).level === 'bad')) alert('Confirmed ' + n + '. Expired prices were skipped: edit them with the new price and date.');
  });

  function resetTransportForm() {
    $('transportForm').reset(); $('trEditing').value = '';
    $('trSubmit').textContent = 'Add transport'; $('trCancel').classList.add('hidden');
  }
  $('trCancel').addEventListener('click', resetTransportForm);
  $('transportForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const code = normCode($('trCode').value);
    const name = $('trName').value.trim(), supplier = $('trSupplier').value.trim(), price = parseNum($('trPrice').value);
    if (!code || !name || !supplier) return setMsg('trMsg', 'Code, name and supplier are required.', 'err');
    if (isNaN(price) || price < 0) return setMsg('trMsg', 'Price must be 0 or more.', 'err');
    const id = $('trEditing').value;
    const current = id ? prices.transport.find((t) => t.id === id) : null;
    if (codeInUse(code, current)) return setMsg('trMsg', 'Code ' + code + ' is already used by ' + (findTransport(code) ? 'another transfer' : codeKind(code)) + '.', 'err');
    let item;
    if (current) item = Object.assign(current, { code, name, supplier, price: round2(price) });
    else prices.transport.push(item = { id: uid(), code, name, supplier, price: round2(price) });
    persist(Cloud.upsertTransport([item]), 'save transport item ' + name);
    resetTransportForm(); renderPrices(); setMsg('trMsg', (id ? 'Updated ' : 'Added ') + name + '.', 'ok');
  });
  $('transportPriceRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-ract]'); if (!b) return;
    const t = prices.transport.find((x) => x.id === b.dataset.id); if (!t) return;
    if (b.dataset.ract === 'edit') {
      $('trEditing').value = t.id; $('trCode').value = t.code || ''; $('trName').value = t.name; $('trSupplier').value = t.supplier; $('trPrice').value = t.price;
      $('trSubmit').textContent = 'Save changes'; $('trCancel').classList.remove('hidden'); $('trPrice').focus();
    }
    if (b.dataset.ract === 'del' && confirm('Delete transport item "' + t.name + '"?')) {
      prices.transport = prices.transport.filter((x) => x !== t); persist(Cloud.deleteTransport(t.id), 'delete transport item ' + t.name); renderPrices();
    }
  });

  function resetGuideForm() {
    $('guideForm').reset(); $('gdEditing').value = '';
    $('gdSubmit').textContent = 'Add guide'; $('gdCancel').classList.add('hidden');
  }
  $('gdCancel').addEventListener('click', resetGuideForm);
  $('guideForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const code = normCode($('gdCode').value);
    const name = $('gdName').value.trim(), supplier = $('gdSupplier').value.trim(), price = parseNum($('gdPrice').value);
    if (!code || !name || !supplier) return setMsg('gdMsg', 'Code, place and supplier are required.', 'err');
    if (isNaN(price) || price < 0) return setMsg('gdMsg', 'Price must be 0 or more.', 'err');
    const id = $('gdEditing').value;
    const current = id ? prices.guides.find((t) => t.id === id) : null;
    if (codeInUse(code, current)) return setMsg('gdMsg', 'Code ' + code + ' is already used by ' + (findGuide(code) ? 'another guide' : codeKind(code)) + '.', 'err');
    let item;
    if (current) item = Object.assign(current, { code, name, supplier, price: round2(price) });
    else prices.guides.push(item = { id: uid(), code, name, supplier, price: round2(price) });
    persist(Cloud.upsertGuides([item]), 'save guide ' + code);
    resetGuideForm(); renderPrices(); setMsg('gdMsg', (id ? 'Updated ' : 'Added ') + code + '.', 'ok'); $('gdCode').focus();
  });
  $('guidePriceRows').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-gact]'); if (!b) return;
    const t = prices.guides.find((x) => x.id === b.dataset.id); if (!t) return;
    if (b.dataset.gact === 'edit') {
      $('gdEditing').value = t.id; $('gdCode').value = t.code; $('gdName').value = t.name; $('gdSupplier').value = t.supplier; $('gdPrice').value = t.price;
      $('gdSubmit').textContent = 'Save changes'; $('gdCancel').classList.remove('hidden'); $('gdPrice').focus();
    }
    if (b.dataset.gact === 'del' && confirm('Delete guide ' + t.code + ' — ' + t.name + '? Saved quotes keep their copy.')) {
      prices.guides = prices.guides.filter((x) => x !== t); persist(Cloud.deleteGuide(t.id), 'delete guide ' + t.code); renderPrices();
    }
  });

  // ============================================================
  //                     SETTINGS + BACKUP
  // ============================================================
  function applyBrand() { $('brandName').textContent = settings.businessName || 'Quote Calculator'; }
  function renderSettings() {
    $('stBusiness').value = settings.businessName; $('stDetails').value = settings.businessDetails;
    $('stCurrency').value = settings.currency; $('stService').value = settings.defaultServiceCharge; $('stFooter').value = settings.footer;
    $('stProfit').value = settings.profitDisplay || 'service';
  }
  $('settingsForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const sc = parseNum($('stService').value);
    if (isNaN(sc) || sc < 0) { setMsg('settingsMsg', 'Profit must be 0 or more.', 'err'); return; }
    settings = Object.assign({}, settings, { businessName: $('stBusiness').value.trim(), businessDetails: $('stDetails').value.trim(), currency: $('stCurrency').value.trim(), defaultServiceCharge: round2(sc), footer: $('stFooter').value.trim(), profitDisplay: $('stProfit').value });
    applyBrand();
    if (!draft.id && !draft.hotels.length && !draft.days.some((d) => d.lines.length)) { draft.serviceCharge = settings.defaultServiceCharge; saveDraft(); }
    setMsg('settingsMsg', 'Saving…');
    saveSettings().then((ok) => setMsg('settingsMsg', ok ? 'Saved.' : 'Not saved.', ok ? 'ok' : 'err'));
  });

  // ---------- account ----------
  $('accountEmail').textContent = Cloud.agent;
  $('sideUser').textContent = 'Agent ' + Cloud.agent;
  $('signOutBtn').addEventListener('click', () => Cloud.signOut());
  $('sideSignOut').addEventListener('click', () => Cloud.signOut());
  $('passwordForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const a = $('pwNew').value, b = $('pwAgain').value;
    if (a.length < 8) return setMsg('pwMsg', 'Use at least 8 characters.', 'err');
    if (a !== b) return setMsg('pwMsg', 'The two passwords are different.', 'err');
    setMsg('pwMsg', 'Saving…');
    try { await Cloud.changePassword(a); $('passwordForm').reset(); setMsg('pwMsg', 'Password changed. Use the new one next time you log in.', 'ok'); }
    catch (err) { setMsg('pwMsg', 'Not changed: ' + Cloud.explain(err), 'err'); }
  });

  // ---------- backup, restore and importing old data ----------
  $('backupBtn').addEventListener('click', () => {
    const data = { app: 'quote-calculator', version: 1, exportedAt: new Date().toISOString(), settings, prices, quotes, invoices: Invoice.list() };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    download(url, 'quote-calculator-backup-' + today() + '.json');
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    setMsg('backupMsg', 'Backup downloaded.', 'ok');
  });

  // Adds a backup (or the old offline data) to the online database. Nothing is deleted.
  //  - Quotes: new ones are added. A quote that is already there is replaced only if the
  //    incoming copy was saved more recently. A clashing quote number gets the next free number.
  //  - Price list: new tickets/transport items are added. Existing ones (same code, or same
  //    transport name and supplier) are replaced only when `overwrite` is true (restoring a backup).
  //  - Settings: taken from the file when `overwrite` is true or nothing has been saved online yet.
  async function importData(d, overwrite) {
    const res = { invoices: null, quotesAdded: 0, quotesUpdated: 0, renumbered: [], tickets: 0, transport: 0, guides: 0, skipped: 0 };
    const tUp = [], rUp = [], qUp = [];
    ((d.prices && d.prices.tickets) || []).forEach((t0) => {
      const t = fixTicket(Object.assign({}, t0));
      t.code = String(t.code || '').trim().toUpperCase().replace(/\s+/g, '');
      if (!t.code || !String(t.name || '').trim() || !String(t.supplier || '').trim() || !isValidDate(t.validUntil || '') ||
          isNaN(Number(t.adultPrice)) || isNaN(Number(t.childPrice))) { res.skipped++; return; }
      if (t.confirmedAt && !isValidDate(t.confirmedAt)) t.confirmedAt = '';
      const i = prices.tickets.findIndex((x) => x.code === t.code);
      if (i >= 0 && !overwrite) return;
      if (i >= 0) prices.tickets[i] = t; else prices.tickets.push(t);
      tUp.push(t); res.tickets++;
    });
    ((d.prices && d.prices.transport) || []).forEach((t0) => {
      const t = { id: t0.id || uid(), code: normCode(t0.code), name: String(t0.name || '').trim(), supplier: String(t0.supplier || '').trim(), price: Number(t0.price) };
      if (!t.name || !t.supplier || isNaN(t.price) || t.price < 0) { res.skipped++; return; }
      const i = prices.transport.findIndex((x) => x.id === t.id || (x.name === t.name && x.supplier === t.supplier));
      if (t.code && codeInUse(t.code, prices.transport[i])) t.code = ''; // clashing code: leave it to be set by hand
      if (i >= 0 && !overwrite) return;
      if (i >= 0) { t.id = prices.transport[i].id; prices.transport[i] = t; } else prices.transport.push(t);
      rUp.push(t); res.transport++;
    });
    const gUp = [];
    ((d.prices && d.prices.guides) || []).forEach((t0) => {
      const t = { id: t0.id || uid(), code: normCode(t0.code), name: String(t0.name || '').trim(), supplier: String(t0.supplier || '').trim(), price: Number(t0.price) };
      if (!t.code || !t.name || !t.supplier || isNaN(t.price) || t.price < 0) { res.skipped++; return; }
      const i = prices.guides.findIndex((x) => x.id === t.id || x.code === t.code);
      if (i >= 0 && !overwrite) return;
      if (codeInUse(t.code, prices.guides[i])) { res.skipped++; return; }
      if (i >= 0) { t.id = prices.guides[i].id; prices.guides[i] = t; } else prices.guides.push(t);
      gUp.push(t); res.guides++;
    });
    (Array.isArray(d.quotes) ? d.quotes : []).forEach((q0) => {
      const q = JSON.parse(JSON.stringify(q0));
      if (!q.id) q.id = uid();
      if (!isValidDate(q.date || '')) { res.skipped++; return; }
      const i = quotes.findIndex((x) => x.id === q.id);
      if (i >= 0) {
        if (!(String(q.updatedAt || '') > String(quotes[i].updatedAt || ''))) return;
        q.quoteNumber = quotes[i].quoteNumber;
        quotes[i] = q; qUp.push(q); res.quotesUpdated++;
        return;
      }
      if (!q.quoteNumber || quotes.some((x) => x.quoteNumber === q.quoteNumber)) {
        const old = q.quoteNumber;
        q.quoteNumber = nextQuoteNumber(q.date);
        if (old) res.renumbered.push(old + ' → ' + q.quoteNumber);
      }
      quotes.push(q); qUp.push(q); res.quotesAdded++;
    });
    const takeSettings = d.settings && (overwrite || !settingsSaved);
    try {
      await Cloud.upsertTickets(tUp);
      await Cloud.upsertTransport(rUp);
      await Cloud.upsertGuides(gUp);
      await Cloud.saveQuotes(qUp);
      if (Array.isArray(d.invoices)) res.invoices = await Invoice.importList(d.invoices);
      if (takeSettings) await Cloud.saveSettings(Object.assign({}, DEFAULT_SETTINGS, d.settings));
    } finally {
      // Whatever happened, show what is really saved online now.
      const fresh = await Cloud.loadAll();
      prices = fresh.prices; prices.tickets.forEach(fixTicket); prices.guides = prices.guides || []; quotes = fresh.quotes;
      settingsSaved = !!fresh.settings; settings = Object.assign({}, DEFAULT_SETTINGS, fresh.settings || {});
      Invoice.setList(fresh.invoices, fresh.profiles);
      applyBrand(); renderSettings(); renderPriceBadge(); refreshPickers();
    }
    return res;
  }
  function importSummary(r) {
    let t = 'Added ' + r.quotesAdded + ' quote(s)' + (r.quotesUpdated ? ', updated ' + r.quotesUpdated : '') +
      ', and ' + r.tickets + ' ticket(s), ' + r.transport + ' transport item(s) and ' + r.guides + ' guide(s) to the price list.';
    if (r.invoices) t += ' Invoices: ' + r.invoices.added + ' added' + (r.invoices.updated ? ', ' + r.invoices.updated + ' updated' : '') + '.' + (r.invoices.renumbered.length ? ' Invoice numbers already in use were changed: ' + r.invoices.renumbered.join(', ') + '.' : '');
    if (r.renumbered.length) t += ' Quote numbers already in use were changed: ' + r.renumbered.join(', ') + '.';
    if (r.skipped) t += ' Skipped ' + r.skipped + ' item(s) with missing details.';
    return t;
  }

  $('restoreInput').addEventListener('change', (e) => {
    const file = e.target.files[0]; if (!file) return;
    const r = new FileReader();
    r.onload = async () => {
      try {
        const d = JSON.parse(r.result);
        if (!d.prices || !Array.isArray(d.quotes)) throw new Error('This is not a quote calculator backup file.');
        if (!confirm('Add this backup (' + d.quotes.length + ' quotes, ' + (d.prices.tickets || []).length + ' tickets) to the online database?\n\n' +
          'Nothing is deleted. Price list items and settings in the file replace the ones online; quotes are added, or updated where the file has a newer copy.')) return;
        setMsg('backupMsg', 'Restoring…');
        const res = await importData(d, true);
        setMsg('backupMsg', importSummary(res), 'ok');
      } catch (err) { console.error(err); setMsg('backupMsg', 'Restore failed: ' + Cloud.explain(err), 'err'); }
      finally { e.target.value = ''; }
    };
    r.readAsText(file);
  });

  // One-time copy of data saved by the old offline version in this browser.
  const IMPORTED_FLAG = 'qc.importedToCloud';
  function localOldData() {
    const p = load('qc.prices', null) || {}, q = load('qc.quotes', null), st = load('qc.settings', null);
    const d = { prices: { tickets: Array.isArray(p.tickets) ? p.tickets : [], transport: Array.isArray(p.transport) ? p.transport : [] },
      quotes: Array.isArray(q) ? q : [], settings: st };
    d.count = d.quotes.length + d.prices.tickets.length + d.prices.transport.length;
    return d;
  }
  async function importLocal(msgEl) {
    const d = localOldData();
    if (!d.count) { setMsg(msgEl, 'There is no data from the old version in this browser.', 'ok'); return true; }
    setMsg(msgEl, 'Copying…');
    try {
      const res = await importData(d, false);
      try { localStorage.setItem(IMPORTED_FLAG, new Date().toISOString()); } catch (e) {}
      setMsg(msgEl, 'Done. ' + importSummary(res) + ' The old copy is left in this browser, untouched.', 'ok');
      if (!$('view-saved').classList.contains('hidden')) renderSaved();
      return true;
    } catch (err) { console.error(err); setMsg(msgEl, 'Copy failed: ' + Cloud.explain(err) + ' Nothing was lost; try again.', 'err'); return false; }
  }
  $('importLocalBtn').addEventListener('click', () => importLocal('backupMsg'));
  (function offerLocalImport() {
    const d = localOldData();
    let done = null; try { done = localStorage.getItem(IMPORTED_FLAG); } catch (e) {}
    if (!d.count || done) return;
    const box = document.createElement('div');
    box.className = 'alert warn import-offer';
    box.innerHTML = '<div><b>Found data from the old offline version in this browser:</b> ' + d.quotes.length + ' quote(s), ' +
      d.prices.tickets.length + ' ticket(s) and ' + d.prices.transport.length + ' transport item(s). Copy them to the online database so they are not lost?</div>' +
      '<div class="import-btns"><button class="btn primary" type="button" data-imp="go">Copy them now</button>' +
      '<button class="btn ghost" type="button" data-imp="no">Don\'t ask again</button></div><div class="msg"></div>';
    document.querySelector('main.content').prepend(box);
    box.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-imp]'); if (!b) return;
      if (b.dataset.imp === 'no') {
        try { localStorage.setItem(IMPORTED_FLAG, 'dismissed'); } catch (err) {}
        box.remove(); return;
      }
      box.querySelectorAll('button').forEach((x) => { x.disabled = true; });
      importLocal(box.querySelector('.msg')).then((ok) => {
        if (ok) box.querySelector('.import-btns').remove();
        else box.querySelectorAll('button').forEach((x) => { x.disabled = false; });
      });
    });
  })();

  $('sampleBtn').addEventListener('click', () => {
    if (prices.tickets.length && !confirm('Add sample items to your existing price list?')) return;
    const d = new Date(); const end = isoDate(new Date(d.getFullYear(), d.getMonth() + 2, 0));
    const sample = [ // [code, name, supplier, adult, child] — made-up sample prices
      ['CT01', 'City tour', 'City Tours Co', 14, 10], ['SF01', 'Singapore Flyer', 'Singapore Flyer', 45, 29],
      ['GB01', 'Gardens by the Bay', 'Gardens by the Bay', 30, 22], ['NS01', 'Night Safari', 'Mandai Wildlife', 48, 34],
      ['CC01', 'Cable car', 'Mount Faber Leisure', 26, 18], ['US01', 'Universal Studios', 'Resorts World Sentosa', 83, 62.5]
    ];
    const newT = [], newR = [];
    sample.forEach(([code, name, supplier, a, c]) => { if (!findTicket(code)) newT.push({ code, name, supplier, adultPrice: a, childPrice: c, price: a, validUntil: end, confirmedAt: today() }); });
    [['APU', 'Pickup from airport', 'Metro Transport', 45], ['APD', 'Drop off to airport', 'Metro Transport', 45], ['T7R', 'Transfer, 7 seater (2 way)', 'Metro Transport', 80], ['T7S', 'Transfer, 7 seater (1 way)', 'Metro Transport', 40]]
      .forEach(([code, name, supplier, price]) => { if (!prices.transport.some((t) => t.name === name) && !codeInUse(code)) newR.push({ id: uid(), code, name, supplier, price }); });
    const newG = [];
    [['GUSS', 'Universal Studios (full day)', 'City Guides', 180], ['GSEN', 'Sentosa (half day)', 'City Guides', 120], ['GCITY', 'City tour (full day)', 'City Guides', 200]]
      .forEach(([code, name, supplier, price]) => { if (!codeInUse(code)) newG.push({ id: uid(), code, name, supplier, price }); });
    prices.tickets.push(...newT); prices.transport.push(...newR); prices.guides.push(...newG);
    persist(Cloud.upsertTickets(newT).then(() => Cloud.upsertTransport(newR)).then(() => Cloud.upsertGuides(newG)), 'add the sample price list');
    renderPriceBadge(); refreshPickers();
    setMsg('backupMsg', 'Sample price list added. Have a look in the Price list tab.', 'ok');
  });

  // ============================================================
  //                 PROFORMA INVOICE + MOBILE
  // ============================================================
  // Phones: the A4 paper (794 px wide) is shrunk to fit the screen in the preview.
  function fitPaper(paper) {
    const wrap = paper.parentElement;
    paper.style.zoom = '';
    const avail = wrap.clientWidth - (parseFloat(getComputedStyle(wrap).paddingLeft) || 0) * 2;
    if (avail > 0 && avail < paper.offsetWidth) paper.style.zoom = String(avail / paper.offsetWidth);
  }
  window.addEventListener('resize', () => document.querySelectorAll('.modal:not(.hidden) .paper').forEach(fitPaper));

  const Invoice = window.InvoiceModule({
    $, esc, fmtNum, round2, uid, today, isValidDate, fmtDate, parseNum, setMsg, persist, exportPaper, fitPaper,
    settings: () => settings, agent: () => Cloud.agent, invoices: invoicesLoaded, profiles: profilesLoaded
  });

  // Phone bottom bar on the quote page: total, Save, and a jump to the full summary.
  $('mQuoteSave').addEventListener('click', saveCurrent);
  document.querySelectorAll('[data-goto]').forEach((b) => b.addEventListener('click', () => $(b.dataset.goto).scrollIntoView({ behavior: 'smooth', block: 'start' })));
  new MutationObserver(() => { $('mQuoteTotal').textContent = $('tGrand').textContent; }).observe($('tGrand'), { childList: true, characterData: true, subtree: true });

  // ---------------- start ----------------
  applyBrand(); refreshPickers(); renderQuote(); renderPriceBadge();
  $('mQuoteTotal').textContent = $('tGrand').textContent;
  const startView = location.hash.slice(1);
  if (['saved', 'prices', 'settings', 'invoice'].includes(startView)) showView(startView);
})();
