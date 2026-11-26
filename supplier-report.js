/*
 * Supplier cross check report: pure functions, no DOM.
 * Works in the browser (window.SupplierReport) and in Node (module.exports).
 *
 * Expected saved-quote shape (adapt via normaliseQuote if the app differs):
 * {
 *   id, quoteNumber, date: "YYYY-MM-DD", clientName, status?: "draft"|"booked"|...,
 *   serviceCharge: number,
 *   tickets:   [{ code, name, supplier, travelDate, pax, unitPrice, adults?, children?, adultPrice?, childPrice?, total? }],
 *   transport: [{ description, supplier, date, travelDate, qty, unitPrice, total? }],
 *   hotels?:   [{ description, supplier?, amount }]   (no date of their own)
 * }
 * A line's saved `total` is used when present; qty x unitPrice is only a fallback for older quotes
 * (on split adult/child tickets unitPrice is a rounded average, so qty x unitPrice can be cents off).
 */
(function (root) {
  'use strict';

  const UNKNOWN_SUPPLIER = '(No supplier set)';

  // Money is handled in cents so totals never pick up floating point errors.
  const toCents = (v) => Math.round((Number(v) || 0) * 100);
  const fromCents = (c) => (c / 100).toFixed(2);

  function isIsoDate(s) {
    return typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(Date.parse(s));
  }

  // Map whatever the app stores into the shape this report uses.
  const optNum = (v) => (v === '' || v == null || isNaN(Number(v)) ? null : Number(v));

  function normaliseQuote(q) {
    const date = String(q.date || q.createdAt || '').slice(0, 10);
    const lineDates = [...(q.tickets || []), ...(q.transport || [])]
      .map((t) => t.travelDate || t.date || '').filter(isIsoDate)
      .concat((q.days || []).map((d) => d && d.date).filter(isIsoDate)).sort();
    const tripStart = lineDates[0] || q.travelDate || '';
    return {
      id: q.id ?? q.quoteNumber ?? '',
      quoteNumber: q.quoteNumber ?? q.number ?? q.id ?? '',
      date,
      clientName: q.clientName ?? q.client ?? '',
      status: q.status ?? null,
      serviceCharge: Number(q.serviceCharge) || 0,
      currency: q.currency || "",
      tickets: (q.tickets || []).map((t) => ({
        code: t.code ?? '',
        name: t.name ?? t.description ?? '',
        supplier: (t.supplier || '').trim() || UNKNOWN_SUPPLIER,
        qty: Number(t.pax ?? t.qty) || 0,
        unitPrice: Number(t.unitPrice ?? t.price) || 0,
        adults: optNum(t.adults), children: optNum(t.children),
        adultPrice: optNum(t.adultPrice), childPrice: optNum(t.childPrice),
        total: optNum(t.total),
        travelDate: t.travelDate || t.date || q.travelDate || '',
      })),
      transport: (q.transport || []).map((t) => ({
        code: t.code ?? '',
        name: t.description ?? t.name ?? '',
        supplier: (t.supplier || '').trim() || UNKNOWN_SUPPLIER,
        qty: Number(t.qty ?? t.quantity ?? 1) || 0,
        unitPrice: Number(t.unitPrice ?? t.price) || 0,
        total: optNum(t.total),
        travelDate: t.travelDate || t.date || q.travelDate || '',
      })),
      // Hotels have no date of their own, so they are dated by the first day of the trip.
      hotels: (q.hotels || []).map((h) => ({
        code: '',
        name: h.description ?? h.name ?? '',
        supplier: (h.supplier || '').trim() || UNKNOWN_SUPPLIER,
        qty: 1,
        unitPrice: Number(h.amount) || 0,
        total: optNum(h.amount),
        travelDate: tripStart,
        tripStartDate: !!tripStart,
      })),
    };
  }

  /**
   * Build the report.
   * opts: { from: "YYYY-MM-DD", to: "YYYY-MM-DD" (inclusive), statuses?: string[] | null }
   * Lines are filtered by their travel date, because supplier invoices go by travel date.
   * A line with no travel date falls back to the quote date and is flagged (dateIsFallback).
   * statuses = null means include every quote; otherwise only quotes whose status is listed.
   * Quotes with no status field at all are always included (the app may not track status).
   */
  function buildReport(rawQuotes, opts) {
    const { from, to } = opts;
    if (!isIsoDate(from) || !isIsoDate(to)) throw new Error('From and To must be valid dates');
    if (from > to) throw new Error('From date is after To date');
    const statuses = opts.statuses || null;

    const quotes = (rawQuotes || []).map(normaliseQuote).filter((q) =>
      !(statuses && q.status != null && !statuses.includes(q.status)));

    const lines = [];
    const usedQuotes = new Set();
    for (const q of quotes) {
      const push = (type, l) => {
        const dateIsFallback = !isIsoDate(l.travelDate);
        const reportDate = dateIsFallback ? q.date : l.travelDate;
        if (!isIsoDate(reportDate) || reportDate < from || reportDate > to) return;
        usedQuotes.add(q);
        const totalCents = l.total != null ? toCents(l.total) : toCents(l.unitPrice) * l.qty;
        const split = l.adults != null && l.children != null && l.adultPrice != null && l.childPrice != null;
        lines.push({
          reportDate, dateIsFallback, tripStartDate: !!l.tripStartDate,
          adults: split ? l.adults : null, children: split ? l.children : null,
          adultCents: split ? toCents(l.adultPrice) : null, childCents: split ? toCents(l.childPrice) : null,
          // One unit price only makes sense when every pax paid the same.
          singlePrice: !split || l.children === 0 || l.adults === 0 || toCents(l.adultPrice) === toCents(l.childPrice),
          supplier: l.supplier, type, quoteDate: q.date, quoteNumber: String(q.quoteNumber),
          clientName: q.clientName, code: l.code, item: l.name, travelDate: l.travelDate,
          qty: l.qty,
          unitCents: split ? toCents(l.adults === 0 ? l.childPrice : l.adultPrice) : toCents(l.unitPrice),
          totalCents,
        });
      };
      q.tickets.forEach((t) => push('Ticket', t));
      q.transport.forEach((t) => push('Transport', t));
      q.hotels.forEach((h) => push('Hotel', h));
    }

    lines.sort((a, b) =>
      a.supplier.localeCompare(b.supplier) || a.type.localeCompare(b.type) ||
      a.reportDate.localeCompare(b.reportDate) || a.quoteNumber.localeCompare(b.quoteNumber));

    const bySupplier = new Map();
    for (const l of lines) {
      if (!bySupplier.has(l.supplier)) bySupplier.set(l.supplier, { supplier: l.supplier, lines: [], qty: 0, totalCents: 0 });
      const g = bySupplier.get(l.supplier);
      g.lines.push(l); g.qty += l.qty; g.totalCents += l.totalCents;
    }

    const groups = [...bySupplier.values()];
    return {
      from, to,
      quoteCount: usedQuotes.size,
      groups,
      lines,
      supplierTotalCents: groups.reduce((s, g) => s + g.totalCents, 0),
      // Service charge of quotes that have at least one line in range (counted once per quote).
      serviceChargeCents: [...usedQuotes].reduce((s, q) => s + toCents(q.serviceCharge), 0),
      missingTravelDate: lines.filter((l) => l.dateIsFallback).length,
      missingSupplier: lines.filter((l) => l.supplier === UNKNOWN_SUPPLIER).length,
    };
  }

  // CSV that opens cleanly in Excel / Google Sheets.
  function csvCell(v) {
    let s = v == null ? '' : String(v);
    // Stop text that looks like a formula from running in a spreadsheet.
    if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = "'" + s;
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  const CSV_HEADERS = ['Supplier', 'Type', 'Travel date', 'Quote no', 'Quote date', 'Client', 'Code', 'Item',
    'Qty', 'Adults', 'Children', 'Adult price', 'Child price', 'Unit price', 'Line total', 'Note'];

  function lineNote(l) {
    if (l.dateIsFallback) return 'No travel date on quote; quote date used';
    if (l.tripStartDate) return 'Hotel has no date; first day of trip used';
    return '';
  }

  function toCsv(lines) {
    const rows = [CSV_HEADERS];
    for (const l of lines) {
      rows.push([l.supplier, l.type, l.travelDate, l.quoteNumber, l.quoteDate, l.clientName, l.code, l.item,
        l.qty, l.adults ?? '', l.children ?? '',
        l.adultCents != null ? fromCents(l.adultCents) : '', l.childCents != null ? fromCents(l.childCents) : '',
        l.singlePrice ? fromCents(l.unitCents) : '', fromCents(l.totalCents), lineNote(l)]);
    }
    return '﻿' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
  }

  function monthRange(year, month /* 1-12 */) {
    const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const mm = String(month).padStart(2, '0');
    return { from: `${year}-${mm}-01`, to: `${year}-${mm}-${String(last).padStart(2, '0')}` };
  }

  const api = { buildReport, toCsv, monthRange, normaliseQuote, fromCents, lineNote, UNKNOWN_SUPPLIER };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SupplierReport = api;
})(typeof window !== 'undefined' ? window : globalThis);
