# Quote Calculator for Mac: the guide

This is the Python version of the Quote Calculator. It is a normal Mac window, it works without
internet, and it shares the online database (Supabase) with the website. That means agents on the
website and agents on the Mac see the same price list and the same quotes.

It is all Python: **4 code files**, and nothing else to learn.

| File | What's in it |
|---|---|
| `rules.py` | the business rules: totals, the checks before saving, quote numbers, price list rules, the supplier report |
| `data.py` | saving: the database on this Mac (SQLite) and syncing with Supabase |
| `pdf.py` | how the PDF looks |
| `app.py` | the window: tabs, boxes, buttons, and what each click does |
| `test_app.py` | automatic checks (see [section 5](#5-check-you-didnt-break-anything)) |

---

## 1. Set it up (once per Mac)

1. **Install Python.** Go to https://www.python.org/downloads/, click the yellow **Download Python 3.x**
   button, open the file and click **Continue** and **Install**. It's free, and it includes
   Tkinter, which draws the window.
2. **Get the app.** Open https://github.com/itsdream2ws/quote-calculator, click the green **Code**
   button, then **Download ZIP**. Double-click the ZIP to unpack it and move the folder to your
   Documents. (If you'll change the code, use [GitHub Desktop](https://desktop.github.com/) instead:
   **File → Clone repository**.)
3. **Start it.** Open the `python_app` folder and double-click **Start Quote Calculator.command**.
   - The first time, your Mac may say it "cannot verify the developer". Open **System Settings →
     Privacy & Security**, scroll down, click **Open Anyway**, and double-click the file again.
   - A Terminal window opens. The first time it installs 3 small libraries (needs internet, about a minute).
   - Then the app opens. Log in with your agent code (like `AG01`) and password. Logging in needs
     internet the first time.

Keep the Terminal window open while you work: closing it closes the app.

---

## 2. Using it every day

- **New quote:** type the client, date and number of adults and children. Then for each day:
  - click the day in the table, and type its date in the box underneath
  - type a code (like `CT01`) in the **Code** box and press Enter, or pick one from the list
  - **+ Meal** and **+ Other transport** add a line you fill in yourself
  - click any line to change its supplier, people or prices in the boxes under the table
  - **+ Day** adds the next day, **+ Hotel** adds a hotel
  - type the profit on the right, then **Save quote** or **Save + PDF**
- **Saved quotes:** search, then **Open** (to change it), **Copy as new**, **PDF** or **Delete**.
  Double-clicking a quote opens it too.
- **Price list:** click a row to change it, or fill in the empty boxes and click **Add**.
- **Supplier report:** pick the travel dates (this month is filled in), click **Show**. **Save as
  CSV** makes a file for Excel or Numbers.
- **Sync now** (top right) sends your quotes up and brings down the price list and everyone's
  quotes. The app also syncs when it starts, and each saved quote is sent straight away if there
  is internet. The top line says **All quotes sent** or how many are waiting.

**Quote numbers** look like `Q-20261128-AG01-001`: the date, your agent code, then 001, 002 and so
on. The agent code is there so two agents working offline never pick the same number.

---

## 3. What needs internet

| Works offline | Needs internet |
|---|---|
| Making, changing, copying and deleting quotes | Logging in the first time |
| PDFs | Changing the price list (so everyone has the same prices) |
| The supplier report (sync first for everyone's latest quotes) | Sync now |

If two people change the same quote, the copy saved most recently wins at the next sync.
Logging out doesn't delete anything: quotes that aren't sent yet stay on this Mac and are sent
at the first sync after you log in again.

Your quotes on this Mac are in `~/Library/Application Support/Quote Calculator/quote-calculator.db`.
Replacing the app folder with a newer version doesn't touch them.

---

## 4. Changing the code

Use a free code editor like [Visual Studio Code](https://code.visualstudio.com/): **File → Open
Folder** and pick `python_app`. After a change, close the Terminal window and double-click the
start file again.

**To find something,** search for the words you see on screen (in VS Code: ⇧⌘F). For example,
search for `Enter the client name.` and you land on the check in `rules.py`.

Examples:

- **Add a "Snack" meal:** in `rules.py`, change `MEALS = ["Breakfast", "Lunch", "Dinner"]` to
  `MEALS = ["Breakfast", "Lunch", "Dinner", "Snack"]`.
- **Change the PDF colour:** in `pdf.py`, change `TEAL = (13, 138, 138)` (red, green, blue, from 0 to 255).
- **Change a check before saving:** they are all in `check_quote()` in `rules.py`. Each one is an
  `if` that adds a sentence to `errors` (stops saving) or `warnings` (only asks).
- **Change the boxes under the table:** the `FIELDS` list near the top of the "New quote" part of
  `app.py` says which boxes each kind of line has.
- **Change the window size:** `self.geometry("1250x800")` in `app.py`.

Saved quotes are kept as one block of data (JSON) in the same shape as the website's (see
`../DATA_FORMAT.md`). Keep the names of the saved fields the same, or the website won't read them.

**Tkinter in one minute:** `ttk.Label`, `ttk.Entry` and `ttk.Button` are things on screen.
`.grid(row=, column=)` or `.pack()` puts them in the window. A `tk.StringVar()` holds what's typed in
a box: `.get()` reads it and `.set()` changes it. `ttk.Treeview` is a table.

---

## 5. Check you didn't break anything

Open Terminal in the `python_app` folder (drag the folder onto the Terminal window after typing `cd `), then:
```
.venv/bin/python3 -m pip install pytest
.venv/bin/python3 -m pytest test_app.py
```
It should end with `passed` and no `failed`. The tests use a pretend Supabase, so they never touch
your real data.

---

## 6. Not in this first version

These are on the website but not here yet. They can be added later, one at a time:
- Proforma invoices and the company logo
- PNG pictures of a quote (only PDF for now)
- Settings and password changes (change them on the website; the app downloads the settings when it syncs)
- Making group quotes with additional charges (group quotes made on the website open and keep
  their charges, but you can't add new ones here)
- Backup and restore buttons, and the sample price list
- Non-English letters in the PDF (such as Chinese names) show as "?"
- A date picker: type dates as `2026-12-31`

---

## 7. If something goes wrong

| Problem | What to do |
|---|---|
| "Python 3 (with Tkinter) is not installed" | Do step 1 of [section 1](#1-set-it-up-once-per-mac). |
| "Could not install the libraries" | The first start needs internet. Connect and try again. |
| "No internet connection" | Your quotes are safe on this Mac. Sync again when you're online. |
| "Your login has expired" | Click **Log out**, then log in again (with internet). |
| The app closes with an error | The Terminal window shows the last lines of the error, with the file name and line number. |
