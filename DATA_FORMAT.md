# Data format

The app works with the objects below. They are stored online in Supabase (see `cloud.js` and `supabase/schema.sql`):

| Supabase table | Contents |
|---|---|
| `tickets` | one row per Ticket: `code, name, supplier, adult_price, child_price, valid_until, confirmed_at` |
| `transport_items` | one row per TransportItem: `id, code, name, supplier, price` |
| `guide_items` | one row per guide price: `id, code, name` (place or attraction), `supplier, price` |
| `quotes` | one row per Quote: `id, quote_number, quote_date, client_name, total`, and `data` = the whole Quote object below |
| `invoices` | one row per proforma invoice / general quote: `id, invoice_number, invoice_date, client_name, total`, and `data` = the whole Invoice object below |
| `agent_profiles` | one row per login: `user_id, email` (both set by the database from the login), `data` = that agent's Letterhead below |
| `settings` | one row (`id` 1); `data` = `{ businessName, businessDetails, currency, defaultServiceCharge, profitDisplay, footer }` |
| `supplier_lines` (view) | every ticket/transport/meal/guide/hotel/additional line of every quote with its travel date, read-only |

The quote being edited stays in the browser's localStorage under `qc.draft`; the invoice being edited under `qc.invoiceDraft`.
The supplier report (`report.html`) reads the quotes' flat `tickets`/`transport`/`hotels` lists. Don't rename line fields without updating it.

Backup file (Settings → Download backup): `{ app: "quote-calculator", version: 1, exportedAt, settings, prices: { tickets, transport, guides }, quotes, invoices }`. Letterheads (logos) are not in the backup.
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
           | { type: "transport", code, description, supplier, qty, unitPrice, total }
           | { type: "meal", meal: "Breakfast"|"Lunch"|"Dinner", description, supplier, adults, children, adultPrice, childPrice, total }
           | { type: "guide", code, description, supplier, qty, unitPrice, total } ] }],
  hotels: [{ description, supplier (optional), amount }],
  quoteType: "normal" | "group",
  additionalCharges: [{ description, supplier (optional), amount }]   (group quotes only; empty otherwise),

  // Flat copies for the supplier report (travel date = the day's date):
  tickets:   [{ code, name, supplier, travelDate, adults, children, adultPrice, childPrice, pax, unitPrice (= total / pax, rounded), total }],
  transport: [{ code, description, supplier, date, travelDate, qty, unitPrice, total }],
  meals:     [{ meal, description, supplier, travelDate, adults, children, adultPrice, childPrice, pax, total }],
  guides:    [{ code, description, supplier, travelDate, qty, unitPrice, total }],

  subtotalTickets, subtotalTransport, subtotalMeals, subtotalGuides, subtotalHotel, subtotalAdditional, total,
  createdAt, updatedAt (ISO timestamps), createdBy, updatedBy (agent codes)
}
```
Prices are copied onto each line when the quote is saved, and can be changed per line, so later price list changes never alter saved quotes. Use `total` for line amounts (a ticket's unitPrice is only an average when adult and child prices differ).
Quotes saved before the day-by-day layout have only `tickets`/`transport`; the app converts them when opened.
Settings also hold `profitDisplay`: "service" (show as Service charge), "hide", or "profit".

## GuideItem (price list)
`{ id, code (unique across tickets, transfers and guides), name (place or attraction), supplier, price }`

## Invoice (proforma invoice / general quote)
```
{
  id, invoiceNumber: "PI-YYYYMMDD-NNN" (editable, unique), title: "PROFORMA INVOICE" | "QUOTATION" | any text,
  date: "YYYY-MM-DD", validUntil: "YYYY-MM-DD" or "", reference,
  company: { name, details },            // copied from the form when saved
  billTo:  { name, details },
  currency,
  items: [{ description (free text, may have line breaks), qty, unitPrice, amount (= qty × unitPrice, rounded) }],
  subtotal, discount (flat amount), taxLabel ("GST"), taxRate (percent), tax (= (subtotal − discount) × rate), total,
  notes, payment, terms, itemised (bool: show qty and prices),
  createdAt, updatedAt, createdBy, updatedBy (agent codes)
}
```
The logo is not stored on the invoice: it is drawn from the Letterhead of the agent in `createdBy`.

## Letterhead (agent_profiles.data)
`{ logo: "data:image/png;base64,…" (shrunk to at most 600 × 240 px), companyName, companyDetails, payment, terms, taxLabel, taxRate }`
