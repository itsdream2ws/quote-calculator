// Run: node tests/test-report.js
const assert = require('assert');
const R = require('../supplier-report.js');
const data = require('./sample-backup.json');
const nov = R.monthRange(2026, 11);
assert.deepStrictEqual(nov, { from: '2026-11-01', to: '2026-11-30' });
assert.deepStrictEqual(R.monthRange(2028, 2), { from: '2028-02-01', to: '2028-02-29' });
const old = data.quotes.filter(q => q.id !== 'q5'); // original-format quotes
const r = R.buildReport(old, nov);
// q1, q2 (no travel dates -> quote date in Nov), q4 (saved Oct, travels Nov); q3 saved Dec, no travel date -> excluded
assert.strictEqual(r.quoteCount, 3);
assert.strictEqual(r.lines.length, 8, 'Dec return coach of q4 excluded');
const g = Object.fromEntries(r.groups.map(x => [x.supplier, x.totalCents]));
assert.strictEqual(g['Emaar'], 89700);           // 6 x 149.50
assert.strictEqual(g['Arabian Adventures'], 40); // 4 x 0.10, no float error
assert.strictEqual(g['City Cabs'], 18040 + 12000); // 180 + 2 x 0.20 + 120
assert.strictEqual(g['Zoo'], 14400);
assert.strictEqual(g['(No supplier set)'], 5000);
assert.strictEqual(r.missingSupplier, 1);
assert.strictEqual(r.missingTravelDate, 5);      // q1 tickets x2, q2 all 3 lines
assert.strictEqual(r.serviceChargeCents, 8000);
const dec = R.buildReport(old, R.monthRange(2026, 12));
assert.deepStrictEqual(dec.lines.map(l => l.item).sort(), ['Burj', 'Return coach']);
assert.throws(() => R.buildReport(data.quotes, { from: '2026-11-30', to: '2026-11-01' }));
assert.throws(() => R.buildReport(data.quotes, { from: '', to: '2026-11-01' }));
const csv = R.toCsv(r.lines);
assert.ok(csv.startsWith('﻿Supplier,Type,Travel date'));
assert.ok(csv.includes(`"'=Acme, ""Corp"""`), 'formula guarded and quoted');
assert.strictEqual(csv.trim().split('\r\n').length, 9);
// New day-by-day format (q5): saved line totals, adult/child split, hotels
const n = R.buildReport(data.quotes, { from: '2026-11-20', to: '2026-11-21' });
const nl = (item) => n.lines.find(l => l.item === item);
assert.strictEqual(nl('Night safari').totalCents, 13333, 'uses saved total, not 3 x 44.44 = 133.32');
assert.strictEqual(nl('Night safari').singlePrice, false);
assert.strictEqual(nl('River cruise').singlePrice, true, 'no children so one price');
assert.strictEqual(nl('River cruise').unitCents, 4000);
assert.strictEqual(nl('Hotel 3 nights').reportDate, '2026-11-20', 'hotel dated at trip start');
assert.strictEqual(nl('Hotel 3 nights').supplier, 'Booked by Binoy');
assert.strictEqual(nl('Late checkout').supplier, R.UNKNOWN_SUPPLIER);
assert.strictEqual(n.supplierTotalCents, 13333 + 8000 + 6550 + 54000 + 3000);
assert.strictEqual(n.serviceChargeCents, 2000);
const ncsv = R.toCsv(n.lines);
assert.ok(ncsv.includes('Zoo,Ticket,2026-11-21,Q-20261126-001,2026-11-26,Tan family,CT02,Night safari,3,2,1,50.00,33.33,,133.33,'));
assert.ok(ncsv.includes('Hotel has no date; first day of trip used'));
// A hotel on a quote whose trip is in December must not land in November
assert.ok(!R.buildReport(data.quotes, R.monthRange(2026, 10)).lines.some(l => l.type === 'Hotel'));
console.log('all tests passed'); console.log(csv);
