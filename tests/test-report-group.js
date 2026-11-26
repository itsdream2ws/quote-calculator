// Run: node tests/test-report-group.js   (meals, guides and group additional charges)
const assert = require('assert');
const R = require('../supplier-report.js');
const q = { id: 'g', quoteNumber: 'Q-1', date: '2026-11-26', clientName: 'Grp', quoteType: 'group', serviceCharge: 10,
  days: [{ date: '2026-12-05', lines: [] }],
  tickets: [], transport: [],
  meals: [{ meal: 'Lunch', description: 'Hawker', supplier: 'Food Co', travelDate: '2026-12-05', adults: 10, children: 2, adultPrice: 12, childPrice: 8, pax: 12, total: 136 }],
  guides: [{ description: 'Full day', supplier: 'Guides Ltd', travelDate: '2026-12-06', qty: 2, unitPrice: 150, total: 300 }],
  hotels: [], additionalCharges: [{ description: 'Coach / bus', supplier: 'Bus Co', amount: 500 }, { description: 'Handling fee', supplier: '', amount: 200 }] };
const r = R.buildReport([q], R.monthRange(2026, 12));
const g = Object.fromEntries(r.groups.map((x) => [x.supplier, x.totalCents]));
assert.deepStrictEqual(g, { 'Bus Co': 50000, 'Food Co': 13600, 'Guides Ltd': 30000 });
const bus = r.lines.find((l) => l.supplier === 'Bus Co'); assert.strictEqual(bus.reportDate, '2026-12-05'); assert.strictEqual(bus.type, 'Additional');
const meal = r.lines.find((l) => l.type === 'Meal'); assert.strictEqual(meal.adults, 10); assert.strictEqual(meal.item, 'Lunch — Hawker');
const normal = Object.assign({}, q, { quoteType: 'normal' });
assert(!R.buildReport([normal], R.monthRange(2026, 12)).lines.some((l) => l.type === 'Additional'));
console.log('report types ok', R.toCsv(r.lines).split('\r\n').length);
