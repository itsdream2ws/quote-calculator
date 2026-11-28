"""Small helpers used everywhere: money rounding, number formatting and dates.

Nothing in here talks to the database or the web page, so it is easy to test.
"""
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import config


# ---------------------------------------------------------------- money

def round2(value):
    """Round to 2 decimal places, halves going up (2.345 -> 2.35), like a calculator.

    Python's own round() uses "banker's rounding" (2.345 -> 2.34), which is not what
    people expect on a quote, so we use Decimal instead.
    """
    try:
        d = Decimal(str(value))
    except Exception:
        return 0.0
    if not d.is_finite():
        return 0.0
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_num(value):
    """1234.5 -> '1,234.50'"""
    return f"{round2(value):,.2f}"


def money(value, currency="SGD"):
    """1234.5 -> 'SGD 1,234.50'"""
    return (currency + " " if currency else "") + fmt_num(value)


def to_number(value):
    """Turn what was typed into a number, or None if it isn't one ('' -> None, '12' -> 12.0)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):  # NaN or infinity
        return None
    return n


def is_whole(value, minimum):
    """True if value is a whole number >= minimum (e.g. a number of people)."""
    n = to_number(value)
    return n is not None and n == int(n) and n >= minimum


def is_money(value):
    """True if value is a number that is 0 or more."""
    n = to_number(value)
    return n is not None and n >= 0


def num_or_zero(value):
    n = to_number(value)
    return 0.0 if n is None else n


def as_int(value):
    """Whole numbers are saved as ints (2, not 2.0) so the saved data matches the old app."""
    n = num_or_zero(value)
    return int(n) if n == int(n) else n


# ---------------------------------------------------------------- dates

def today():
    """Today's date as 'YYYY-MM-DD', in the business's time zone (see config.py)."""
    return datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat()


def this_month():
    return today()[:7]


def now_iso():
    """The time now, like '2026-11-28T05:30:00.000Z' (the same format the old app saved)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def is_valid_date(text):
    """True for a real date written as YYYY-MM-DD."""
    if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return False
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


def fmt_date(text):
    """'2026-11-28' -> '28 Nov 2026'"""
    if not is_valid_date(text):
        return text or ""
    return date.fromisoformat(text).strftime("%d %b %Y")


def weekday(text):
    """'2026-11-28' -> 'Saturday'"""
    return date.fromisoformat(text).strftime("%A") if is_valid_date(text) else ""


def add_days(text, n):
    return (date.fromisoformat(text) + timedelta(days=n)).isoformat()


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def month_range(year, month):
    """(2026, 2) -> ('2026-02-01', '2026-02-28')"""
    first = date(year, month, 1)
    next_first = date(year + (month == 12), month % 12 + 1, 1)
    return first.isoformat(), (next_first - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------- other

def new_id():
    """A random id for a new quote, invoice or price list item."""
    return uuid.uuid4().hex[:16]


def norm_code(code):
    """' ct 01 ' -> 'CT01' (codes are upper case with no spaces)."""
    return re.sub(r"\s+", "", str(code or "")).upper()


def pax_label(adults, children):
    """(2, 1) -> '2 A+1C', (2, 0) -> '2 A'"""
    a, c = as_int(adults), as_int(children)
    return f"{a} A" + (f"+{c}C" if c else "")


def safe_filename(text, limit=60):
    """'Q-1 Tan family' -> 'Q-1_Tan_family' (only letters, digits, - and _)."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return re.sub(r"_+", "_", s)[:limit] or "file"
