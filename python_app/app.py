"""The Quote Calculator window (made with Tkinter, which comes with Python).

Start it with:  python3 app.py   (or double-click "Start Quote Calculator.command")

The window has 4 tabs, and each tab is one class below:
  QuoteTab    make or edit a quote
  SavedTab    the saved quotes: open, copy, PDF, delete
  PricesTab   the price list (tickets, transport, guides): changes need internet
  ReportTab   the supplier report for a month, by travel date

The rules (totals, checks, numbers) are in rules.py, saving and syncing in data.py and the PDF in
pdf.py. This file only shows things on screen and reacts to clicks.

Tkinter in one minute:
  ttk.Label / ttk.Entry / ttk.Button ...   a widget (something on screen)
  .grid(row=, column=) or .pack()          puts it in its parent
  tk.StringVar()                           holds the text of an Entry; .get() reads it, .set() changes it
  var.trace_add("write", function)         runs function every time the text changes
  ttk.Treeview                             a table (rows can have rows inside them, like folders)
"""
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import data
import pdf
import rules


def show(value):
    """A number as text for a box: 14.0 -> '14', 14.5 -> '14.5'. Text stays as it is."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return "" if value is None else str(value)


def open_file(path):
    """Open a file with the Mac's own app (a PDF opens in Preview)."""
    subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)


def make_table(parent, columns, height=12):
    """A table with headings and a scroll bar. columns: [(name, heading, width), ...]"""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], height=height, selectmode="browse")
    for name, heading, width in columns:
        tree.heading(name, text=heading, anchor="w")
        tree.column(name, width=width, anchor="e" if heading in ("Total", "Price", "Adult", "Child") else "w")
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return frame, tree


# =============================================================== the main window

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Quote Calculator")
        self.geometry("1250x800")

        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.status = ttk.Label(top)
        self.status.pack(side="left")
        ttk.Button(top, text="Log out", command=self.log_out).pack(side="right")
        ttk.Button(top, text="Sync now", command=self.sync).pack(side="right", padx=6)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.quote_tab = QuoteTab(self.tabs, self)
        self.saved_tab = SavedTab(self.tabs, self)
        self.prices_tab = PricesTab(self.tabs, self)
        self.report_tab = ReportTab(self.tabs, self)
        for tab, name in ((self.quote_tab, "New quote"), (self.saved_tab, "Saved quotes"),
                          (self.prices_tab, "Price list"), (self.report_tab, "Supplier report")):
            self.tabs.add(tab, text=name, padding=10)
        # every time a tab is opened, show its latest data
        self.tabs.bind("<<NotebookTabChanged>>", lambda e: self.tabs.nametowidget(self.tabs.select()).refresh())
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.after(100, self.start)

    def start(self):
        if not data.agent():
            LoginWindow(self)                      # waits until the agent has logged in
        self.sync(quiet=True)

    def online(self, work):
        """Run work() (something that needs internet) with a busy mouse pointer.
        Returns True if it worked; shows the problem and returns False if not."""
        self.config(cursor="watch")
        self.update()
        try:
            work()
            return True
        except data.OnlineError as e:
            messagebox.showerror("Quote Calculator", str(e), parent=self)
            return False
        finally:
            self.config(cursor="")
            self.refresh_status()

    def sync(self, quiet=False):
        result = []
        if self.online(lambda: result.append(data.sync_now())) and not quiet:
            messagebox.showinfo("Sync", result[0], parent=self)
        self.tabs.nametowidget(self.tabs.select()).refresh()

    def refresh_status(self):
        unsent = len(data.unsent_ids())
        last = data.get("last_sync")
        self.status.config(text=f"Logged in as {data.agent()}   ·   "
                                + ("All quotes sent" if not unsent else f"{unsent} not sent yet (Sync now sends them)")
                                + (f"   ·   last sync {last[:16].replace('T', ' ')} UTC" if last else ""))

    def log_out(self):
        question = "Log out of this Mac? You need internet to log in again."
        if data.unsent_ids():
            question += ("\n\nSome quotes aren't sent yet. They stay on this Mac and are sent at the first "
                         "sync after you log in again.")
        if messagebox.askyesno("Log out", question, parent=self):
            data.put("login", None)
            LoginWindow(self)
            self.sync(quiet=True)

    def quit_app(self):
        if self.quote_tab.changed and not messagebox.askyesno(
                "Quit", "The quote you are making isn't saved. Quit anyway?", parent=self):
            return
        self.destroy()


class LoginWindow(tk.Toplevel):
    """Asks for the agent code and password. Closing it closes the app."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Log in")
        self.resizable(False, False)
        box = ttk.Frame(self, padding=20)
        box.pack()
        ttk.Label(box, text="Log in to the Quote Calculator", font=("", 14, "bold")).grid(columnspan=2, pady=(0, 10))
        self.agent, self.password = tk.StringVar(), tk.StringVar()
        ttk.Label(box, text="Agent code").grid(row=1, column=0, sticky="w")
        first = ttk.Entry(box, textvariable=self.agent)
        first.grid(row=1, column=1, pady=3)
        ttk.Label(box, text="Password").grid(row=2, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.password, show="•").grid(row=2, column=1, pady=3)
        ttk.Button(box, text="Log in", command=self.log_in).grid(row=3, column=1, sticky="e", pady=(10, 0))
        ttk.Label(box, text="Logging in needs internet the first time.", foreground="grey").grid(row=4, columnspan=2)
        self.bind("<Return>", lambda e: self.log_in())
        self.protocol("WM_DELETE_WINDOW", app.destroy)
        first.focus_set()
        self.transient(app)
        self.wait_visibility()
        self.grab_set()                            # the main window can't be used until logged in
        app.wait_window(self)

    def log_in(self):
        if self.app.online(lambda: data.log_in(self.agent.get(), self.password.get())):
            self.destroy()


# =============================================================== New quote

# The boxes shown under the table for the selected row: (label, key in the line, width)
FIELDS = {
    "day":       [("Date (YYYY-MM-DD)", "date", 14)],
    "ticket":    [("Supplier", "supplier", 22), ("Adults", "adults", 5), ("Children", "children", 5),
                  ("Adult price", "adultPrice", 8), ("Child price", "childPrice", 8)],
    "meal":      [("Meal", "meal", 10), ("Description", "description", 22), ("Supplier", "supplier", 18),
                  ("Adults", "adults", 5), ("Children", "children", 5), ("Adult price", "adultPrice", 8),
                  ("Child price", "childPrice", 8)],
    "transport": [("Description", "description", 30), ("Supplier", "supplier", 18), ("Qty", "qty", 5),
                  ("Price", "unitPrice", 8)],
    "hotel":     [("Hotel", "description", 30), ("Supplier", "supplier", 18), ("Amount", "amount", 10)],
}
FIELDS["guide"] = FIELDS["transport"]


class QuoteTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.changed = False                       # True when there are changes that aren't saved

        # ---- client, date, people, notes
        head = ttk.Frame(self)
        head.pack(fill="x")
        self.vars = {key: tk.StringVar() for key in ("clientName", "date", "adults", "children", "notes", "serviceCharge")}
        for col, (label, key, width) in enumerate([("Client *", "clientName", 28), ("Quote date *", "date", 11),
                                                   ("Adults", "adults", 5), ("Children", "children", 5)]):
            ttk.Label(head, text=label).grid(row=0, column=col * 2, sticky="w", padx=(0 if col == 0 else 12, 4))
            ttk.Entry(head, textvariable=self.vars[key], width=width).grid(row=0, column=col * 2 + 1)
        ttk.Label(head, text="Notes").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(head, textvariable=self.vars["notes"], width=90).grid(row=1, column=1, columnspan=7, sticky="w", pady=(6, 0))
        self.heading = ttk.Label(head, font=("", 13, "bold"))
        self.heading.grid(row=0, column=8, padx=20)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(10, 0))

        # ---- the right side: totals and buttons
        side = ttk.Frame(body, padding=(14, 0, 0, 0))
        side.pack(side="right", fill="y")
        self.totals = ttk.Frame(side)
        self.totals.pack(anchor="w", fill="x")
        row = ttk.Frame(side)
        row.pack(anchor="w", pady=6)
        ttk.Label(row, text="Profit / service charge").pack(side="left")
        ttk.Entry(row, textvariable=self.vars["serviceCharge"], width=9).pack(side="left", padx=4)
        self.total = ttk.Label(side, font=("", 20, "bold"))
        self.total.pack(anchor="w", pady=6)
        self.itemised = tk.BooleanVar()
        ttk.Checkbutton(side, text="Itemised PDF (a price on every line)", variable=self.itemised,
                        command=self.edited).pack(anchor="w", pady=4)
        ttk.Button(side, text="Save quote", command=self.save).pack(fill="x", pady=(10, 2))
        ttk.Button(side, text="Save + PDF", command=lambda: self.save(make_pdf=True)).pack(fill="x", pady=2)
        ttk.Button(side, text="Start a new quote", command=self.new_quote).pack(fill="x", pady=(14, 2))
        self.message = ttk.Label(side, wraplength=300, justify="left")
        self.message.pack(anchor="w", pady=10)

        # ---- the table of days and lines
        table, self.tree = make_table(body, [("code", "Code", 60), ("item", "Item", 210), ("supplier", "Supplier", 130),
                                             ("pax", "Pax / qty", 70), ("price", "Price", 120), ("total", "Total", 85)], 16)
        self.tree.heading("#0", text="Day")
        self.tree.column("#0", width=185)
        table.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_fields())

        # ---- buttons under the table
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=6)
        ttk.Label(bar, text="Code").pack(side="left")
        self.code = ttk.Combobox(bar, width=28, postcommand=self.fill_codes)
        self.code.pack(side="left", padx=4)
        self.code.bind("<Return>", lambda e: self.add_code())
        self.code.bind("<<ComboboxSelected>>", lambda e: self.add_code())
        ttk.Button(bar, text="Add", command=self.add_code).pack(side="left")
        for text, command in (("+ Meal", lambda: self.add_line("meal")), ("+ Other transport", lambda: self.add_line("transport")),
                              ("+ Hotel", self.add_hotel), ("+ Day", self.add_day)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(8 if text == "+ Meal" else 2, 0))
        bar2 = ttk.Frame(body)
        bar2.pack(fill="x")
        ttk.Label(bar2, text="Click a day or a line in the table to change it here:", foreground="grey").pack(side="left")
        for text, command in (("Remove", self.remove), ("Move down", lambda: self.move(1)), ("Move up", lambda: self.move(-1))):
            ttk.Button(bar2, text=text, command=command).pack(side="right", padx=2)
        self.fields = ttk.Frame(body)
        self.fields.pack(fill="x", pady=4)

        for key, var in self.vars.items():
            var.trace_add("write", lambda *args, key=key: self.top_changed(key))
        self.new_quote()

    def refresh(self):
        pass                                        # nothing to reload when this tab is opened

    # ---------------------------------------------------------- loading a quote into the screen

    def load(self, draft, heading):
        self.draft = draft
        self.loading = True                         # stop top_changed() from reacting while we fill the boxes
        for key, var in self.vars.items():
            var.set(show(draft.get(key)))
        self.itemised.set(draft["itemised"])
        self.loading = False
        self.old_pax = {"adults": rules.whole(draft["adults"]), "children": rules.whole(draft["children"])}
        self.heading.config(text=heading)
        self.message.config(text="")
        self.fill_tree("day:0")
        self.changed = False

    def new_quote(self):
        if self.changed and not messagebox.askyesno("New quote", "Throw away the changes to this quote?", parent=self):
            return
        self.load(rules.blank_draft(data.settings()), "New quote")

    def open_quote(self, q, copy=False):
        if self.changed and not messagebox.askyesno("Open quote", "Throw away the changes to this quote?", parent=self):
            return
        draft = rules.draft_from_quote(q)
        if copy:
            draft.update(id=None, quoteNumber=None, date=rules.today(), createdBy=None, createdAt=None)
        self.load(draft, "Copy of " + q["quoteNumber"] if copy else "Editing " + q["quoteNumber"])
        self.app.tabs.select(self)

    # ---------------------------------------------------------- the table

    def fill_tree(self, select=None):
        """Draw the whole table again from the draft."""
        self.tree.delete(*self.tree.get_children())
        for di, day in enumerate(self.draft["days"]):
            self.tree.insert("", "end", f"day:{di}", open=True)
            for li in range(len(day["lines"])):
                self.tree.insert(f"day:{di}", "end", f"line:{di}:{li}")
        self.tree.insert("", "end", "hotels", text="Hotels", open=True)
        for hi in range(len(self.draft["hotels"])):
            self.tree.insert("hotels", "end", f"hotel:{hi}")
        for iid in self.all_rows():
            self.show_row(iid)
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)
        self.show_fields()
        self.show_totals()

    def all_rows(self):
        for top in self.tree.get_children():
            yield top
            yield from self.tree.get_children(top)

    def target(self, iid):
        """The row id -> (kind, the dict it shows).  'line:0:2' is line 2 of day 0."""
        parts = iid.split(":")
        if parts[0] == "day":
            return "day", self.draft["days"][int(parts[1])]
        if parts[0] == "line":
            line = self.draft["days"][int(parts[1])]["lines"][int(parts[2])]
            return line["type"], line
        if parts[0] == "hotel":
            return "hotel", self.draft["hotels"][int(parts[1])]
        return "hotels", None

    def show_row(self, iid):
        """Write one row of the table from the draft."""
        kind, item = self.target(iid)
        if kind == "day":
            di = int(iid.split(":")[1])
            day_total = sum(rules.line_total(l) for l in item["lines"])
            self.tree.item(iid, text=f"Day {di + 1}  {rules.nice_date(item['date']) or '(enter the date)'}",
                           values=("", "", "", "", "", rules.fmt(day_total)))
        elif kind == "hotel":
            self.tree.item(iid, values=("", item.get("description"), item.get("supplier"), "", "", rules.fmt(rules.num0(item.get("amount")))))
        elif kind == "hotels":
            pass
        elif rules.per_person(item):
            self.tree.item(iid, values=(item.get("code", ""), rules.line_label(item, self.draft), item.get("supplier"),
                                        rules.pax_text(item.get("adults"), item.get("children")),
                                        f"A {show(item.get('adultPrice'))} / C {show(item.get('childPrice'))}",
                                        rules.fmt(rules.line_total(item))))
        else:
            self.tree.item(iid, values=(item.get("code", ""), rules.line_label(item, self.draft), item.get("supplier"),
                                        show(item.get("qty")), show(item.get("unitPrice")), rules.fmt(rules.line_total(item))))

    def show_totals(self):
        t = rules.totals(self.draft)
        rows = [("Tickets", t["tickets"]), ("Transport", t["transport"]), ("Meals", t["meals"]),
                ("Guides", t["guides"]), ("Hotel", t["hotel"])] + ([("Additional", t["additional"])] if self.draft.get("group") else [])
        for widget in self.totals.winfo_children():
            widget.destroy()
        for i, (name, value) in enumerate(rows):
            ttk.Label(self.totals, text=name).grid(row=i, column=0, sticky="w")
            ttk.Label(self.totals, text=rules.fmt(value)).grid(row=i, column=1, sticky="e", padx=(30, 0))
        self.total.config(text=f"Total  {data.settings().get('currency', 'SGD')} {rules.fmt(t['total'])}")

    def selected(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None

    def selected_day(self):
        """The day of the selected row (or the last day if nothing is selected)."""
        iid = self.selected() or ""
        return int(iid.split(":")[1]) if iid.startswith(("day:", "line:")) else len(self.draft["days"]) - 1

    # ---------------------------------------------------------- the boxes under the table

    def show_fields(self):
        """Show the boxes for the selected row. Typing in them changes the draft straight away."""
        for widget in self.fields.winfo_children():
            widget.destroy()
        iid = self.selected()
        if not iid:
            return
        kind, item = self.target(iid)
        for col, (label, key, width) in enumerate(FIELDS.get(kind, [])):
            ttk.Label(self.fields, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            var = tk.StringVar(value=show(item.get(key)))
            if key == "meal":
                ttk.Combobox(self.fields, textvariable=var, values=rules.MEALS, width=width, state="readonly").grid(row=1, column=col, padx=(0, 8))
            else:
                ttk.Entry(self.fields, textvariable=var, width=width).grid(row=1, column=col, padx=(0, 8))
            var.trace_add("write", lambda *args, item=item, key=key, var=var, iid=iid: self.field_changed(iid, item, key, var))

    def field_changed(self, iid, item, key, var):
        item[key] = var.get()
        self.show_row(iid)
        if self.tree.parent(iid):
            self.show_row(self.tree.parent(iid))   # the day's total
        self.show_totals()
        self.edited()

    def top_changed(self, key):
        """A box at the top (client, date, adults...) changed."""
        if self.loading:
            return
        self.draft[key] = self.vars[key].get()
        if key in ("adults", "children"):
            # Lines that had the old number of adults (or children) follow the new number.
            new = rules.whole(self.draft[key])
            if new is not None and new >= 0:
                for day in self.draft["days"]:
                    for line in day["lines"]:
                        if rules.per_person(line) and rules.whole(line.get(key)) == self.old_pax[key]:
                            line[key] = new
                self.old_pax[key] = new
                self.fill_tree(self.selected())
        self.show_totals()
        self.edited()

    def edited(self):
        self.draft["itemised"] = self.itemised.get()
        self.changed = True

    # ---------------------------------------------------------- the buttons under the table

    def fill_codes(self):
        """The list under the Code box: every ticket, transfer and guide."""
        p = data.prices()
        self.code["values"] = ([f"{t['code']}  {t['name']} (ticket)" for t in p["tickets"]]
                               + [f"{t['code']}  {t['name']} (transport)" for t in p["transport"] if t.get("code")]
                               + [f"{t['code']}  Guide, {t['name']}" for t in p["guides"]])

    def say(self, text, good=True):
        self.message.config(text=text, foreground="dark green" if good else "red")

    def add_code(self):
        typed = self.code.get().split("  ")[0]   # "CT01  City tour (ticket)" -> "CT01"
        kind, item = rules.find_code(data.prices(), typed)
        if not item:
            self.say(f'No ticket, transport or guide has the code "{typed}".', good=False)
            return
        if kind == "ticket":
            level, status = rules.ticket_status(item)
            if level == "bad":
                self.say(f"{item['code']}: the price expired on {rules.nice_date(item['validUntil'])}. "
                         "Update it in the price list first.", good=False)
                return
            self.say(f"Added {item['code']} {item['name']}." + (f" ({status})" if level == "warn" else ""))
        else:
            self.say(f"Added {item['code']} {item['name']}.")
        self.push_line(rules.line_from_price_list(item, kind, self.draft))
        self.code.set("")

    def add_line(self, kind):
        if kind == "meal":
            line = {"type": "meal", "meal": "Lunch", "description": "", "supplier": "",
                    "adults": rules.whole(self.draft["adults"]) or 0, "children": rules.whole(self.draft["children"]) or 0,
                    "adultPrice": "", "childPrice": ""}
        else:
            line = {"type": "transport", "code": "", "description": "", "supplier": "", "qty": 1, "unitPrice": ""}
        self.push_line(line)
        self.say("Fill in the new line in the boxes under the table.")

    def push_line(self, line):
        di = self.selected_day()
        self.draft["days"][di]["lines"].append(line)
        self.fill_tree(f"line:{di}:{len(self.draft['days'][di]['lines']) - 1}")
        self.edited()

    def add_hotel(self):
        self.draft["hotels"].append({"description": "", "supplier": "", "amount": ""})
        self.fill_tree(f"hotel:{len(self.draft['hotels']) - 1}")
        self.edited()

    def add_day(self):
        days = self.draft["days"]
        last = days[-1]["date"] if days else ""
        days.append({"date": rules.add_days(last, 1) if rules.is_date(last) else "", "lines": []})
        self.fill_tree(f"day:{len(days) - 1}")
        self.edited()

    def move(self, step):
        """Move the selected line (or day) up (step -1) or down (step 1)."""
        iid = self.selected() or ""
        parts = iid.split(":")
        if parts[0] == "line":
            rows, i, prefix = self.draft["days"][int(parts[1])]["lines"], int(parts[2]), f"line:{parts[1]}:"
        elif parts[0] in ("day", "hotel"):
            rows, i, prefix = (self.draft["days"] if parts[0] == "day" else self.draft["hotels"]), int(parts[1]), parts[0] + ":"
        else:
            return
        j = i + step
        if 0 <= j < len(rows):
            rows[i], rows[j] = rows[j], rows[i]
            self.fill_tree(prefix + str(j))
            self.edited()

    def remove(self):
        iid = self.selected() or ""
        parts = iid.split(":")
        if parts[0] == "line":
            self.draft["days"][int(parts[1])]["lines"].pop(int(parts[2]))
        elif parts[0] == "hotel":
            self.draft["hotels"].pop(int(parts[1]))
        elif parts[0] == "day":
            day = self.draft["days"][int(parts[1])]
            if day["lines"] and not messagebox.askyesno("Remove day", "Remove this day and its lines?", parent=self):
                return
            self.draft["days"].remove(day)
            if not self.draft["days"]:
                self.draft["days"].append({"date": "", "lines": []})
        else:
            return
        self.fill_tree()
        self.edited()

    # ---------------------------------------------------------- saving

    def save(self, make_pdf=False):
        d = self.draft
        errors, warnings = rules.check_quote(d, data.prices())
        if errors:
            self.say("Not saved yet. Please fix:\n• " + "\n• ".join(errors), good=False)
            return
        if warnings and not messagebox.askyesno("Please check", "\n".join(warnings) + "\n\nSave anyway?", parent=self):
            return
        q = rules.build_quote(d, data.settings())
        everyone, me, now = data.all_quotes(), data.agent(), rules.now_iso()
        if d["id"]:                                 # an existing quote keeps its number and who made it
            q.update(id=d["id"], quoteNumber=d["quoteNumber"], createdAt=d.get("createdAt") or now, createdBy=d.get("createdBy") or me)
        else:
            q.update(id=rules.new_id(), quoteNumber=rules.next_quote_number(everyone, d["date"], me), createdAt=now, createdBy=me)
        q.update(updatedAt=now, updatedBy=me)
        data.keep_quote(q)                          # safe on this Mac first
        try:
            renumbered = data.send_quote(q)         # then straight to Supabase if there is internet
            note = f"Saved as {q['quoteNumber']} and sent." + (f" ({renumbered} was taken.)" if renumbered else "")
        except data.OnlineError:
            note = f"Saved as {q['quoteNumber']} on this Mac. It is sent at the next sync."
        d.update(id=q["id"], quoteNumber=q["quoteNumber"], createdAt=q["createdAt"], createdBy=q["createdBy"])
        self.heading.config(text="Editing " + q["quoteNumber"])
        self.changed = False
        self.say(note)
        self.app.refresh_status()
        if make_pdf:
            save_pdf(self, q)


def save_pdf(parent, q):
    """Ask where to save the PDF, save it and open it."""
    path = filedialog.asksaveasfilename(parent=parent, title="Save the PDF", initialfile=pdf.file_name(q),
                                        defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
    if path:
        pdf.quote_pdf(q, data.settings(), path)
        open_file(path)


# =============================================================== Saved quotes

class SavedTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Search").pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *args: self.refresh())
        ttk.Entry(bar, textvariable=self.search, width=30).pack(side="left", padx=4)
        for text, command in (("Delete", self.delete), ("PDF", self.make_pdf),
                              ("Copy as new", lambda: self.open(copy=True)), ("Open", self.open)):
            ttk.Button(bar, text=text, command=command).pack(side="right", padx=2)
        table, self.tree = make_table(self, [("date", "Date", 100), ("number", "Number", 190), ("client", "Client", 220),
                                             ("travel", "Travel", 200), ("agent", "Agent", 70), ("total", "Total", 110),
                                             ("sent", "", 80)], 25)
        self.tree.column("#0", width=0, stretch=False)
        table.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.open())

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.quotes = {}
        unsent, words = data.unsent_ids(), self.search.get().lower().split()
        for q in data.all_quotes():
            dates = sorted(d["date"] for d in rules.days_of(q) if rules.is_date(d.get("date") or ""))
            travel = (rules.nice_date(dates[0]) + (" to " + rules.nice_date(dates[-1]) if len(dates) > 1 else "")) if dates else ""
            row = (q.get("date"), q.get("quoteNumber"), q.get("clientName"), travel, q.get("createdBy", ""),
                   f"{q.get('currency', '')} {rules.fmt(q.get('total', 0))}", "Not sent" if q["id"] in unsent else "")
            if all(w in " ".join(map(str, row)).lower() for w in words):
                self.tree.insert("", "end", q["id"], values=row)
                self.quotes[q["id"]] = q

    def chosen(self):
        iid = self.tree.selection()
        if not iid:
            messagebox.showinfo("Saved quotes", "Click a quote in the list first.", parent=self)
            return None
        return self.quotes[iid[0]]

    def open(self, copy=False):
        q = self.chosen()
        if q:
            self.app.quote_tab.open_quote(q, copy)

    def make_pdf(self):
        q = self.chosen()
        if q:
            save_pdf(self, q)

    def delete(self):
        q = self.chosen()
        if q and messagebox.askyesno("Delete", f"Delete {q['quoteNumber']} ({q['clientName']})? "
                                     "It is deleted for everyone at the next sync.", parent=self):
            data.delete_quote(q["id"])
            self.refresh()
            self.app.refresh_status()


# =============================================================== Price list

PRICE_KINDS = {  # kind -> (tab name, [(box label, key, width)], key in the price list)
    "ticket": ("Tickets", [("Code", "code", 8), ("Name", "name", 28), ("Supplier", "supplier", 20),
                           ("Adult price", "adultPrice", 9), ("Child price (empty = adult)", "childPrice", 9),
                           ("Valid until (YYYY-MM-DD)", "validUntil", 12)], "tickets"),
    "transport": ("Transport", [("Code", "code", 8), ("Name", "name", 34), ("Supplier", "supplier", 20),
                                ("Price", "price", 9)], "transport"),
    "guide": ("Guides", [("Code", "code", 8), ("Place or attraction", "name", 34), ("Supplier", "supplier", 20),
                         ("Price", "price", 9)], "guides"),
}


class PricesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        ttk.Label(self, text="Changes here need internet: they go straight to the online database, "
                             "so every Mac and the website have the same prices.", foreground="grey").pack(anchor="w")
        inner = ttk.Notebook(self)
        inner.pack(fill="both", expand=True, pady=6)
        self.lists = [PriceList(inner, app, kind) for kind in PRICE_KINDS]
        for part in self.lists:
            inner.add(part, text=PRICE_KINDS[part.kind][0], padding=8)

    def refresh(self):
        for part in self.lists:
            part.refresh()


class PriceList(ttk.Frame):
    """One list (tickets, transport or guides) with its form."""

    def __init__(self, parent, app, kind):
        super().__init__(parent)
        self.app, self.kind = app, kind
        name, self.fields, self.list_key = PRICE_KINDS[kind]
        self.editing = None                         # the item being changed, None when adding a new one

        form = ttk.Frame(self)
        form.pack(fill="x")
        self.vars = {}
        for col, (label, key, width) in enumerate(self.fields):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            self.vars[key] = tk.StringVar()
            ttk.Entry(form, textvariable=self.vars[key], width=width).grid(row=1, column=col, padx=(0, 8), sticky="w")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=6)
        self.save_button = ttk.Button(bar, text="Add", command=self.save)
        self.save_button.pack(side="left")
        ttk.Button(bar, text="Clear (add a new one)", command=self.clear).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete", command=self.delete).pack(side="left", padx=4)
        if kind == "ticket":
            ttk.Button(bar, text="✓ Confirm all valid prices this month", command=self.confirm_all).pack(side="right")
        columns = [(key, label.split(" (")[0], 110 if key not in ("name",) else 280) for label, key, width in self.fields]
        if kind == "ticket":
            columns.append(("status", "Status", 170))
        table, self.tree = make_table(self, columns, 18)
        self.tree.column("#0", width=0, stretch=False)
        table.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.pick())

    def items(self):
        return data.prices()[self.list_key]

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.items()):
            if self.kind == "ticket":
                row = [t["code"], t["name"], t["supplier"], rules.fmt(rules.adult_price(t)), rules.fmt(rules.child_price(t)),
                       t["validUntil"], rules.ticket_status(t)[1]]
            else:
                row = [t.get("code") or "(add a code)", t["name"], t["supplier"], rules.fmt(t["price"])]
            self.tree.insert("", "end", str(i), values=row)

    def pick(self):
        """A row was clicked: put it in the form to change it."""
        chosen = self.tree.selection()
        if not chosen:
            return
        self.editing = self.items()[int(chosen[0])]
        for key, var in self.vars.items():
            value = self.editing.get(key)
            var.set(show(rules.child_price(self.editing)) if key == "childPrice" else show(value))
        self.save_button.config(text="Save changes")

    def clear(self):
        self.editing = None
        for var in self.vars.values():
            var.set("")
        self.tree.selection_remove(self.tree.selection())
        self.save_button.config(text="Add")

    def save(self):
        form = {key: var.get() for key, var in self.vars.items()}
        item, error = rules.check_price_item(data.prices(), self.kind, form, self.editing)
        if error:
            messagebox.showerror("Price list", error, parent=self)
            return
        old_key = self.editing["code"] if self.editing and self.kind == "ticket" else None
        if self.app.online(lambda: data.save_price_item(self.kind, item, old_key)):
            self.clear()
            self.refresh()

    def delete(self):
        if self.editing and messagebox.askyesno("Delete", f"Delete {self.editing.get('code')} {self.editing['name']}? "
                                                "Saved quotes keep their own copy.", parent=self):
            if self.app.online(lambda: data.delete_price_item(self.kind, self.editing)):
                self.clear()
                self.refresh()

    def confirm_all(self):
        """Mark every ticket that hasn't expired as checked this month."""
        def work():
            for t in self.items():
                if rules.ticket_status(t)[0] != "bad":
                    data.save_price_item("ticket", dict(t, confirmedAt=rules.today()), refresh=False)
            data.download_prices()
        if self.app.online(work):
            self.refresh()


# =============================================================== Supplier report

class ReportTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        first, last = rules.month_range(rules.today())
        self.date_from, self.date_to = tk.StringVar(value=first), tk.StringVar(value=last)
        ttk.Label(bar, text="Travel dates from").pack(side="left")
        ttk.Entry(bar, textvariable=self.date_from, width=11).pack(side="left", padx=4)
        ttk.Label(bar, text="to").pack(side="left")
        ttk.Entry(bar, textvariable=self.date_to, width=11).pack(side="left", padx=4)
        ttk.Button(bar, text="Show", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(bar, text="Save as CSV (Excel)", command=self.save_csv).pack(side="right")
        self.summary = ttk.Label(self, foreground="grey")
        self.summary.pack(anchor="w", pady=6)
        table, self.tree = make_table(self, [("date", "Travel date", 110), ("type", "Type", 80), ("quote", "Quote", 180),
                                             ("client", "Client", 160), ("item", "Item", 300), ("qty", "Qty", 50),
                                             ("total", "Total", 100)], 25)
        self.tree.heading("#0", text="Supplier")
        self.tree.column("#0", width=200)
        table.pack(fill="both", expand=True)
        self.lines = []

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        a, b = self.date_from.get().strip(), self.date_to.get().strip()
        if not (rules.is_date(a) and rules.is_date(b)) or a > b:
            self.summary.config(text="Enter two dates like 2026-12-01, the first one before the second.")
            return
        self.lines = rules.report_lines(data.all_quotes(), a, b)
        sums = rules.report_by_supplier(self.lines)
        for supplier, cents in sums.items():
            self.tree.insert("", "end", supplier, text=supplier, open=True, values=("", "", "", "", "", "", rules.fmt(cents / 100)))
        for r in self.lines:
            self.tree.insert(r["supplier"], "end", values=(r["travelDate"], r["type"], r["quoteNumber"], r["client"],
                                                           r["item"], r["qty"], rules.fmt(r["cents"] / 100)))
        quotes = len({r["quoteNumber"] for r in self.lines})
        self.summary.config(text=f"{len(self.lines)} lines from {quotes} quote(s), {len(sums)} supplier(s). "
                                 f"Total owed to suppliers: {rules.fmt(sum(sums.values()) / 100)}. "
                                 "Sync first to include everyone's latest quotes.")

    def save_csv(self):
        self.refresh()
        path = filedialog.asksaveasfilename(parent=self, title="Save the report", defaultextension=".csv",
                                            initialfile=f"supplier-report_{self.date_from.get()}_to_{self.date_to.get()}.csv")
        if path:
            rules.write_csv(self.lines, path)
            open_file(path)


if __name__ == "__main__":
    App().mainloop()
