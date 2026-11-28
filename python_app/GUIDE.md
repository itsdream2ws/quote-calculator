# Quote Calculator for Mac: the guide

This is the Python version of the Quote Calculator. It runs on your own Mac, works without internet,
and shares the same online database (Supabase) as the website version. So agents on the website and
agents on the Mac app see the same price list, quotes and supplier report.

- [1. Set it up (once per Mac)](#1-set-it-up-once-per-mac)
- [2. Using it every day](#2-using-it-every-day)
- [3. What needs internet and what doesn't](#3-what-needs-internet-and-what-doesnt)
- [4. Changing the code](#4-changing-the-code)
- [5. Getting a newer version](#5-getting-a-newer-version)
- [6. If something goes wrong](#6-if-something-goes-wrong)
- [7. How it works inside](#7-how-it-works-inside)

---

## 1. Set it up (once per Mac)

### Step 1: install Python
1. Go to https://www.python.org/downloads/ and click the big yellow **Download Python 3.x** button.
2. Open the downloaded file and click **Continue** and **Install** until it says it's done.
   (It's free and made by the people who make Python.)

### Step 2: get the app's files
**Easiest:** open https://github.com/itsdream2ws/quote-calculator, click the green **Code** button,
then **Download ZIP**. Double-click the ZIP in your Downloads folder to unpack it. Move the
`quote-calculator-main` folder somewhere you'll find it again, such as your Documents folder.

**If you'll be changing the code:** use [GitHub Desktop](https://desktop.github.com/) (free) instead:
**File → Clone repository → itsdream2ws/quote-calculator**. That way you can save your changes to
GitHub and get updates easily (see [section 5](#5-getting-a-newer-version)).

### Step 3: start it the first time
1. Open the `python_app` folder inside it.
2. Double-click **Start Quote Calculator.command**.
3. The first time, your Mac may say it "cannot be opened" or "cannot verify the developer". That's
   normal for files you made yourself or downloaded. To allow it:
   - Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to
     the message about "Start Quote Calculator.command". Then double-click the file again.
   - On older macOS versions you can instead right-click (or Control-click) the file and choose **Open**.
4. A Terminal window opens. The first time it says "Setting up for the first time..." and installs
   what the app needs. That needs internet and takes about a minute.
5. Your browser then opens the app at **http://127.0.0.1:5055**. Log in with your agent code (for
   example `AG01`) and your password. Logging in the first time needs internet.

**If double-clicking doesn't work at all**, open the **Terminal** app and type this (drag the
`python_app` folder onto the Terminal window to fill in its location after `cd `), then press Enter:
```
cd /path/to/quote-calculator-main/python_app
bash "Start Quote Calculator.command"
```

The Terminal window shows a warning that says "This is a development server". You can ignore it:
it means the app is only meant for your own computer, which is how this app works.

---

## 2. Using it every day

- **Start:** double-click **Start Quote Calculator.command**. Keep the Terminal window open while
  you work. Closing it (or pressing Ctrl+C in it) stops the app.
  Tip: drag the file to your Dock (on the right, next to the bin) to start it from there.
- **Already running?** Double-clicking it again just opens the app in your browser.
- **Bookmark** http://127.0.0.1:5055 in your browser.
- **Sync now** (bottom left of the menu) sends your new quotes up to Supabase and brings down
  the latest price list, settings, and quotes made by other agents. It also syncs when you log in.
  Saving a quote also sends it straight away when there is internet.
- Under the menu it says **All sent** or **2 not sent yet**. Quotes that aren't sent yet also show
  a **Not sent** label in Saved quotes. They're safe on this Mac, and they're sent at the next sync.

The pages are the same as the website: **New quote**, **Saved quotes**, **Price list**,
**Proforma invoice**, **Supplier report** and **Settings**.

---

## 3. What needs internet and what doesn't

| Works offline | Needs internet |
|---|---|
| Making, editing, copying and deleting quotes and invoices | Logging in the first time on a Mac |
| PDF and PNG downloads, previews | Changing the price list (so every Mac has the same prices) |
| Supplier report (from the quotes on this Mac: sync first for everyone's latest) | Changing settings and your password |
| Uploading your logo (it's sent at the next sync) | Sync now |

**Quote numbers** look like `Q-20261128-AG01-001`: the date, your agent code, then 001, 002 and so on.
The agent code is there so two agents working offline can never pick the same number.
Invoices work the same way: `PI-20261128-AG01-001`.

**If two people change the same quote**, the copy saved most recently wins at the next sync.

**Logging out** is blocked while some quotes aren't sent yet, so nothing gets lost. Sync first.

---

## 4. Changing the code

You need a text editor for code. [Visual Studio Code](https://code.visualstudio.com/) is free and
good. Open the `python_app` folder in it (**File → Open Folder**).

**After any change:** close the Terminal window to stop the app, then double-click
**Start Quote Calculator.command** again, and refresh the browser page.

### Where things are

| To change... | Open this file |
|---|---|
| Totals, what's checked before saving, what each button on the quote page does, quote numbers | `quotes.py` |
| Invoice totals, checks and numbers | `invoices.py` |
| Price list rules: codes, "expired", "confirm this month", the sample price list | `prices.py` |
| The supplier report and its CSV | `report.py` |
| How the PDF and PNG look (colours, sizes, layout) | `exports.py` |
| What happens when you click something on a page (one function per page or button) | `app.py` |
| The words and boxes on a page | `templates/` (`quote.html`, `prices.html`...) |
| Colours and spacing on the pages | `static/styles.css` (shared with the website) and `static/app.css` |
| Supabase address, agent email ending, time zone, port | `config.py` |
| Saving on this Mac | `store.py` |
| Sending and fetching from Supabase | `sync.py` and `supabase_api.py` |

The quote page is the only page with JavaScript (`static/editor.js`). It has no prices or rules
in it: it only collects what you typed, sends it to `app.py`, and shows the answer. So nearly every
change is in Python.

### Examples

**Add a "Snack" meal button.** In `quotes.py` change
`MEALS = ["Breakfast", "Lunch", "Dinner"]` to `MEALS = ["Breakfast", "Lunch", "Dinner", "Snack"]`.
The button appears on every day, and the PDF and report handle it automatically.

**Change a message.** Search the code for the words you see on screen (in VS Code:
**Edit → Find in Files**, or ⇧⌘F). For example, search for `Enter the client name.` to find it in
`quotes.py`.

**Change the PDF's main colour.** In `exports.py`, change `TEAL = (13, 138, 138)` (red, green, blue
from 0 to 255) and the `GRAD_FROM`/`GRAD_TO` colours of the stripe at the top.

**Add a new box to the quote**, for example a "Booking reference":
1. `templates/_quote_editor.html`: copy the Notes `<label>` and change `data-path="notes"` to
   `data-path="bookingRef"` (the data-path is the name it's saved under).
2. `quotes.py`: in `blank_draft` add `"bookingRef": ""`; in `draft_from_quote` add
   `"bookingRef": q.get("bookingRef") or ""`; in `build_quote` add
   `"bookingRef": str(d.get("bookingRef") or "").strip(),` to the dict it returns.
3. `exports.py`: draw it where you want it on the PDF (look at how `notes` is drawn).

Saved quotes are stored as one block of data (JSON), so a new box needs no database change.
The website version simply ignores boxes it doesn't know.

### Check you didn't break anything
The `tests` folder has automatic checks. To run them, open Terminal in the `python_app` folder and type:
```
.venv/bin/python3 -m pip install pytest
.venv/bin/python3 -m pytest tests
```
It should end with `passed` and no `failed`. (`tests/test_browser.py` is skipped unless Playwright
is installed. That's fine.) The tests use a pretend Supabase, so they never touch your real data.

---

## 5. Getting a newer version

- **With GitHub Desktop:** click **Fetch origin**, then **Pull origin**. Then restart the app.
  The start file notices if new libraries are needed and installs them.
- **With a ZIP:** download it again and replace the folder. Your quotes are not in this folder, so
  nothing is lost (see below).

**Your data on this Mac** is in `~/Library/Application Support/Quote Calculator/quote-calculator.db`
(Settings shows the exact path). Deleting the app folder doesn't delete it. Everything that has been
synced is also in Supabase. **Settings → Download backup** makes an extra copy.

---

## 6. If something goes wrong

| Problem | What to do |
|---|---|
| "Python 3 is not installed" | Do [step 1](#step-1-install-python), then try again. |
| "Could not install the libraries" | The first start needs internet. Connect and try again. |
| The browser says the page can't be reached | The app isn't running. Double-click the start file and keep its Terminal window open. |
| "No internet" when syncing | Your work is safe on this Mac. Sync again when you're online. |
| "You have been logged out" or the sync says the login expired | Log out and in again (with internet). |
| A page shows "Internal Server Error" | Look at the Terminal window: the last lines say what went wrong and in which file and line. |
| Another program uses port 5055 | In `config.py` change `PORT`, or start with `QC_PORT=5056 bash "Start Quote Calculator.command"`. |

---

## 7. How it works inside

```
 Browser (Safari / Chrome)  <-->  app.py (Flask, on your Mac)  <-->  quote-calculator.db (SQLite, on your Mac)
                                        |
                                        +--- sync.py / supabase_api.py  <-->  Supabase (online, shared with the website)
```

- **Flask** turns Python functions into web pages. In `app.py`, `@app.get("/quotes")` above a
  function means "when the browser opens /quotes, run this function". `render_template` fills in an
  HTML file from `templates/` with data.
- **SQLite** is a database in one file, and it comes with Python. `store.py` keeps each quote as JSON
  text, with a `dirty` flag meaning "changed here, not sent yet".
- **Sync** (`sync.py`): download everyone's quotes, keep the newer copy of each, send up the ones
  marked dirty, send deletes, then download the price list and settings.
- **Login:** Supabase gives the app a token (like a ticket) that lasts about an hour, plus a refresh
  token to get a new one. They're kept in the local database so the app still knows who you are
  offline. Supabase checks the token on every request (row level security), exactly as for the website.
- **PDF/PNG** (`exports.py`): the fpdf2 library draws on an A4 page in millimetres. For a PNG, the same
  drawing goes on one long page, and pypdfium2 turns it into a picture.
- The saved data has exactly the same shape as the website's (see `../DATA_FORMAT.md`), which is why
  both versions can share one database.

What the Mac app doesn't have, compared with the website: the one-time "copy data from the old
offline version" button (that data only lived inside a browser), and a phone layout (it's a Mac app).
