# Quote Calculator

**Open the app:** https://itsdream2ws.github.io/quote-calculator/

A web app for making travel quotes (SGD): a price list of tickets and transport, a day-by-day quote page laid out like the spreadsheet, PDF/PNG download, saved quotes, and a supplier report by travel date to check supplier invoices.

Everything is saved online in Supabase, so every agent in the company sees the same quotes, price list and report. Each agent logs in with their own **agent code** (like `AG01`) and password. Nobody can see or change anything without logging in.

---

## Part 1: One-time setup (do this once)

### 1. Switch off public sign-ups
This makes sure only the agents you add can ever log in.

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard) and open the project **Horbe tours quoting system database**.
2. In the left menu click **Authentication**, then **Sign In / Providers** (on some screens it is under **Configuration**).
3. Turn **off** "Allow new users to sign up".
4. Click **Save**.

### 2. Add yourself as the first agent
Follow "Add an agent" below to create your own login, for example `AG01`.

### 3. Turn on the website (GitHub Pages)
1. Open [github.com/itsdream2ws/quote-calculator](https://github.com/itsdream2ws/quote-calculator).
2. Click **Settings** (the tab at the top of the repository, with the gear icon).
3. In the left menu, under "Code and automation", click **Pages**.
4. Under "Build and deployment", set **Source** to **Deploy from a branch**.
5. Under **Branch**, pick **main**, leave the folder as **/ (root)**, and click **Save**.
6. Wait a minute or two, then refresh the page. The address of the site shows at the top: https://itsdream2ws.github.io/quote-calculator/

Every change merged into `main` updates the website by itself within a few minutes.

---

## Part 2: Opening the app

The app is a website: **https://itsdream2ws.github.io/quote-calculator/**

1. Open that address in Chrome, Edge, Safari or Firefox, on a computer or phone. Bookmark it.
2. Type your agent code and password, then click **Log in**. The browser remembers you until you click **Log out**.
3. The Supplier report is in the menu on the left.

You need an internet connection, because the quotes are stored online.

(Without the website, you can also open the two single files **Quote Calculator.html** and **Supplier Report.html**. Keep them in the same folder so the menu links work.)

### Bringing over quotes from the old version
The first time you log in on the computer where you used the old offline version, a yellow box offers to copy the old quotes and price list online. Click **Copy them now**. Nothing is deleted from that computer. You can also do this later from **Settings → Copy data from the old offline version**, or restore a backup file from **Settings → Restore from backup**.

---

## Part 3: Agents

An agent code is the first part of a hidden login email. Agent `AG02` logs in as `ag02@agents.local`. That address does not need to exist and never receives anything; it's only how Supabase stores the login.

### Add an agent
1. In Supabase, open the project, then click **Authentication** → **Users**.
2. Click **Add user** → **Create new user**.
3. **Email:** the agent code in small letters followed by `@agents.local`. For agent `AG02` type `ag02@agents.local`.
4. **Password:** make one up (at least 8 characters) and give it to the agent.
5. Tick **Auto Confirm User**.
6. Click **Create user**.

The agent can now log in with `AG02` and that password. They can change their password in the app under **Settings → Your account**.

### Remove an agent
1. **Authentication** → **Users**.
2. Click the three dots (⋯) at the end of their row → **Delete user**.

Their quotes stay in the company history. Quotes show which agent made them (the **Agent** column in Saved quotes).

### Someone forgot their password
Delete their user and add them again with the same agent code and a new password. Their old quotes are not affected.

---

## What's in the app
- **New quote:** client name, adults and children, quote date. Plan it day by day: type a ticket or transfer code (or part of the name) and press Enter, add any custom transport, then hotels. Prices can be changed on each line. Totals and the profit / service charge update as you type. Saving checks every field first. Download as PDF or PNG, itemised or as a summary.
- **Saved quotes:** search by client, quote number or agent, filter by date, re-download, edit, copy as a new quote, delete.
- **Price list:** tickets with code, supplier, adult and child prices, valid-until date and a monthly confirm. Expired prices are blocked from quotes. Transfers with code, supplier and price. A code can belong to one ticket or one transfer, not both.
- **Supplier report:** every ticket, transport and hotel line with a travel date in the chosen month or dates, grouped by supplier, with CSV download and print.
- **Settings:** business name and details on the quote, currency, default profit and how it shows to the client, footer, backups, your password.

The quote you are in the middle of typing is kept in your browser, so a refresh doesn't lose it. It goes online when you click **Save quote**.

You can also look at the data in Supabase: **Table Editor** shows `quotes`, `tickets`, `transport_items` and `settings`. The `supplier_lines` view lists every saved line with its travel date.

---

## For developers

Plain HTML, CSS and JavaScript with no build step and no server.

| File | What it does |
|---|---|
| `index.html`, `app.js`, `styles.css` | The app |
| `report.html`, `supplier-report.js` | Supplier report (`supplier-report.js` is pure functions, tested by `tests/test-report.js`) |
| `cloud.js` | Login screen and all reading and writing to Supabase |
| `config.js` | Supabase project URL, publishable key and the agent email domain |
| `supabase/schema.sql` | Tables, row level security and the `supplier_lines` view (already applied to the live project) |
| `build.py` | Makes the two single-file pages |
| `vendor/` | jsPDF 2.5.1, html2canvas 1.4.1, supabase-js 2.119.0 (all MIT, licences alongside) |

- Hosting: GitHub Pages serves the repository root from `main` (`.nojekyll` turns off Jekyll processing). Login is email + password only, with no email links or redirects, so Supabase's Site URL setting doesn't matter.
- Run locally: open `index.html` directly, or serve the folder with any static server.
- Single files: `python3 build.py . dist` writes `dist/Quote Calculator.html` and `dist/Supplier Report.html` with everything inlined.
- Tests: `node tests/test-report.js`.
- The publishable key in `config.js` is meant to be public. Security comes from row level security: every table only allows signed-in, non-anonymous users, and logged-out visitors have no table access at all. Public sign-ups must stay switched off in Supabase.
- Data shapes: see `DATA_FORMAT.md`.
