# Data format

The app works with the objects below. They are stored online in Supabase (see `cloud.js` and `supabase/schema.sql`):

| Supabase table | Contents |
|---|---|
| `tickets` | one row per Ticket: `code, name, supplier, adult_price, child_price, valid_until, confirmed_at` |
| `transport_items` | one row per TransportItem: `id, code, name, supplier, price` |
| `quotes` | one row per Quote: `id, quote_number, quote_date, client_name, total`, and `data` = the whole Quote object below |
| `settings` | one row (`id` 1); `data` = `{ businessName, businessDetails, currency, defaultServiceCharge, profitDisplay, footer }` |
| `supplier_lines` (view) | every ticket/transport/hotel line of every quote with its travel date, read-only |

The quote being edited stays in the browser's localStorage under `qc.draft`.
The supplier report (`report.html`) reads the quotes' flat `tickets`/`transport`/`hotels` lists. Don't rename line fields without updating it.

Backup file (Settings → Download backup): `{ app: "quote-calculator", version: 1, exportedAt, settings, prices: { tickets, transport }, quotes }`.
The old offline version kept the same objects in localStorage under `qc.prices`, `qc.quotes` and `qc.settings`; the app offers to copy them online once.

## Ticket (price list)
`{ code: "CT01" (uppercase, unique), name, supplier, adultPrice, childPrice, price (= adultPrice, kept for older code), validUntil: "YYYY-MM-DD", confirmedAt: "YYYY-MM-DD" }`

## TransportItem (price list)
`{ id, code ("APU": uppercase, unique across tickets and transfers; blank on older items until edited), name, supplier, price }`

## Quote
```
{
  id, quoteNumber: "Q-YYYYMMDD-NNN", date: "YYYY-MM-DD", clientName, adults, children, notes,
  currency, serviceCharge (flat fee, called Profit in the app), itemised (bool),

  // Layout, in the order shown on the quote:
  days:   [{ date: "YYYY-MM-DD", lines: [
             { type: "ticket", code, name, supplier, adults, children, adultPrice, childPrice, total }
           | { type: "transport", code, description, supplier, qty, unitPrice, total } ] }],
  hotels: [{ description, supplier (optional), amount }],

  // Flat copies for the supplier report (travel date = the day's date):
  tickets:   [{ code, name, supplier, travelDate, adults, children, adultPrice, childPrice, pax, unitPrice (= total / pax, rounded), total }],
  transport: [{ code, description, supplier, date, travelDate, qty, unitPrice, total }],

  subtotalTickets, subtotalTransport, subtotalHotel, total,
  createdAt, updatedAt (ISO timestamps), createdBy, updatedBy (agent codes)
}
```
Prices are copied onto each line when the quote is saved, and can be changed per line, so later price list changes never alter saved quotes. Use `total` for line amounts (a ticket's unitPrice is only an average when adult and child prices differ).
Quotes saved before the day-by-day layout have only `tickets`/`transport`; the app converts them when opened.
Settings also hold `profitDisplay`: "service" (show as Service charge), "hide", or "profit".
