"""Transactions report (kohal, 2026-11-25: "i want report of every and any expense and every and any received. have the report follow the same
format as other reports, the pdf and date filter and other stuff").

Every rupee that came in and every rupee that went out between two dates, whichever account it went through. It is built from the same records the
Accounts page lines up (app/accounts.py all_rows), so the two always agree:

  Received: project payments, lead advances.
  Spent:    salary and wages, salary advances, commission and project expenses, fooding, cash given for purchases, petrol, inventory bought for cash,
            what the admin bought directly, payments to suppliers.

Left out on purpose: self transfers (money only moving between the admin's own accounts), and an employee's own fooding spend or what they buy with the
cash they were handed - the money already left as one of the rows above (the same rule the Accounts page follows). An entry made before the account
list existed has no account; it is still here, shown as "(no account)".

It can be narrowed to money received or money spent, and to one account. The Reports page shows it day by day, and downloads the same figures as
an Excel workbook (Summary, All entries, Received, Spent) or a PDF (app/reports.py, app/static/js/reports.js)."""

from datetime import date
from decimal import Decimal

from flask import abort

from .accounts import all_rows
from .constants import PAYMENT_ACCOUNTS
from .models import settings_for_client
from .pdf import Page, build_pdf
from .slips import _clip, _indian
from .timeutil import today_local

ZERO = Decimal("0")
MAX_DAYS = 740                  # the longest range one report covers - about two years
KINDS = {"all": "Received and spent", "in": "Received only", "out": "Spent only"}
NO_ACCOUNT = "none"             # the account filter's value for entries that went through none of the listed accounts
NO_ACCOUNT_LABEL = "(no account)"


def _f(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _day(raw, default, what):
    if not raw:
        return default
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        abort(422, f"Pick a valid {what}")


def parse_args(args):
    """(from, to, kind, account) from the request - dates default to this month so far; a bad value is a 422, not a guess."""
    today = today_local()
    start = _day(args.get("from"), today.replace(day=1), "from date")
    end = _day(args.get("to"), today, "to date")
    if start > end:
        abort(422, "The from date is after the to date")
    if end > today:
        abort(422, "That day hasn't happened yet")
    if (end - start).days > MAX_DAYS:
        abort(422, "Pick a range of two years or less")
    kind = args.get("kind") or "all"
    if kind not in KINDS:
        abort(422, "Pick received, spent or both")
    account = args.get("account") or ""
    if account and account != NO_ACCOUNT and account not in PAYMENT_ACCOUNTS:
        abort(422, "Pick an account from the list")
    return start, end, kind, account


def entries(start, end, kind="all", account="") -> list:
    """The report's rows, oldest first: each a dict from the Accounts ledger (kind credit / debit, date, amount, reason, party, detail, account...)."""
    lo, hi = start.isoformat(), end.isoformat()
    rows = []
    for r in all_rows():
        if r["reason"] == "Self transfer" or r["date"] is None or not lo <= r["date"] <= hi:
            continue
        if kind != "all" and r["kind"] != ("credit" if kind == "in" else "debit"):
            continue
        listed = r["account"] in PAYMENT_ACCOUNTS
        if account == NO_ACCOUNT and listed or account not in ("", NO_ACCOUNT) and r["account"] != account:
            continue
        rows.append({**r, "account": r["account"] if listed else "", "received": r["kind"] == "credit"})
    rows.sort(key=lambda r: (r["date"], r["kind"] != "credit", r["reason"], r["party"] or ""))
    return rows


def _sum(rows, received):
    return sum((Decimal(str(r["amount"])) for r in rows if r["received"] is received), ZERO)


def totals(rows) -> dict:
    got, spent = _sum(rows, True), _sum(rows, False)
    return {"received": _f(got), "spent": _f(spent), "net": _f(got - spent), "count": len(rows)}


def by_reason(rows, received) -> list:
    """[(reason, entries, amount)] for the money received (or spent), the biggest first."""
    sums = {}
    for r in rows:
        if r["received"] is received:
            n, total = sums.get(r["reason"], (0, ZERO))
            sums[r["reason"]] = (n + 1, total + Decimal(str(r["amount"])))
    return sorted(((reason, n, _f(total)) for reason, (n, total) in sums.items()), key=lambda t: (-t[2], t[0]))


def by_account(rows) -> list:
    """[(account, received, spent, net)] - the accounts in their usual order, then the entries that had none."""
    out = []
    for name in [*PAYMENT_ACCOUNTS, ""]:
        mine = [r for r in rows if r["account"] == name]
        if mine:
            got, spent = _sum(mine, True), _sum(mine, False)
            out.append((name or NO_ACCOUNT_LABEL, _f(got), _f(spent), _f(got - spent)))
    return out


def days(rows) -> list:
    """The rows grouped by day, oldest first, each day with what came in and what went out."""
    grouped = {}
    for r in rows:
        grouped.setdefault(r["date"], []).append(r)
    return [{"date": d, **totals(group), "entries": group} for d, group in grouped.items()]


def report(args) -> dict:
    """What the Reports page shows."""
    start, end, kind, account = parse_args(args)
    rows = entries(start, end, kind, account)
    return {"from": start.isoformat(), "to": end.isoformat(), "kind": kind, "account": account, **totals(rows), "days": days(rows),
            "accounts": [{"value": a, "label": a} for a in PAYMENT_ACCOUNTS] + [{"value": NO_ACCOUNT, "label": NO_ACCOUNT_LABEL}],
            "currency": settings_for_client()["currency"]}


def _period(start, end) -> str:
    return f"{start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}"


def _scope(kind, account) -> str:
    return f"{KINDS[kind]} · {'all accounts' if not account else NO_ACCOUNT_LABEL if account == NO_ACCOUNT else account}"


# ---------- the Excel workbook ----------

def sheets(args) -> list:
    start, end, kind, account = parse_args(args)
    cur = settings_for_client()["currency"]
    rows = entries(start, end, kind, account)
    t = totals(rows)

    summary = [["Transactions", None], ["Period", _period(start, end)], ["Showing", _scope(kind, account)], [None, None]]
    bold = {0}
    if kind != "out":
        summary.append([f"Received ({cur})", t["received"]])
    if kind != "in":
        summary.append([f"Spent ({cur})", t["spent"]])
    if kind == "all":
        summary.append([f"Net: received less spent ({cur})", t["net"]])
    bold |= set(range(4, len(summary)))
    for title, received in (("Received by reason", True), ("Spent by reason", False)):
        if (received and kind == "out") or (not received and kind == "in"):
            continue
        part = by_reason(rows, received)
        summary += [[None, None, None], [title, "Entries", f"Amount ({cur})"]]
        bold.add(len(summary) - 1)
        summary += [[reason, n, amount] for reason, n, amount in part] or [["(none)", 0, 0]]
        summary.append(["Total", sum(n for _r, n, _a in part), t["received"] if received else t["spent"]])
        bold.add(len(summary) - 1)
    accounts = by_account(rows)
    if accounts:
        summary += [[None, None, None], ["By account", f"Received ({cur})", f"Spent ({cur})", f"Net ({cur})"]]
        bold.add(len(summary) - 1)
        summary += [list(a) for a in accounts]
    width = max(len(r) for r in summary)
    summary = [r + [None] * (width - len(r)) for r in summary]

    def sheet(name, header, body, total=None):
        data = [header] + body + ([total] if total else [])
        return {"name": name, "freeze": 1, "bold_rows": {0, len(data) - 1} if total else {0}, "filter": True, "rows": data}

    def line(r):
        return [r["date"], "Received" if r["received"] else "Spent", r["reason"], r["party"] or "", r["detail"] or "", r["account"] or NO_ACCOUNT_LABEL,
                r["requested_by"] or "", r["approved_by"] or ""]

    everything = sheet("All entries", ["Date", "Received / spent", "Reason", "Party", "Detail", "Account", "Requested by", "Approved by", f"Received ({cur})", f"Spent ({cur})"],
                       [line(r) + ([r["amount"], None] if r["received"] else [None, r["amount"]]) for r in rows],
                       ["Total", None, None, None, None, None, None, None, t["received"], t["spent"]] if rows else None)

    def only(name, received):
        mine = [r for r in rows if r["received"] is received]
        who = "From" if received else "Paid to"
        return sheet(name, ["Date", "Reason", who, "Detail", "Account", "Requested by", "Approved by", f"Amount ({cur})"],
                     [[r["date"], r["reason"], r["party"] or "", r["detail"] or "", r["account"] or NO_ACCOUNT_LABEL, r["requested_by"] or "", r["approved_by"] or "", r["amount"]] for r in mine],
                     ["Total", None, None, None, None, None, None, t["received"] if received else t["spent"]] if mine else None)

    out = [{"name": "Summary", "rows": summary, "bold_rows": bold}, everything]
    if kind != "out":
        out.append(only("Received", True))
    if kind != "in":
        out.append(only("Spent", False))
    return out


def filename(args, extension="xlsx") -> str:
    start, end, kind, account = parse_args(args)
    parts = [f"transactions-report-{start.isoformat()}-to-{end.isoformat()}"]
    if kind != "all":
        parts.append("received" if kind == "in" else "spent")
    if account:
        parts.append(NO_ACCOUNT if account == NO_ACCOUNT else account.lower().replace(" ", "-"))
    return "-".join(parts) + f".{extension}"


# ---------- the PDF ----------

_RED, _GREEN, _GREY, _INK = (0.85, 0.22, 0.12), (0.08, 0.35, 0.27), (0.4, 0.4, 0.4), (0.12, 0.1, 0.08)
_PAGE = (842, 595)              # A4, landscape: eight columns of figures and names do not fit across a portrait page
_LEFT, _RIGHT, _TOP, _BOTTOM = 30, 842 - 30, 595 - 36, 40
# (heading, width, right-aligned) - the widths add up to the page's text width
_COLUMNS = [("Date", 62, False), ("Reason", 105, False), ("Party", 140, False), ("Detail", 215, False), ("Account", 90, False), ("Received", 85, True), ("Spent", 85, True)]


def _rs(value) -> str:
    return f"Rs. {_indian(value)}"


def pdf(args) -> bytes:
    start, end, kind, account = parse_args(args)
    rows = entries(start, end, kind, account)
    t = totals(rows)
    pages = []

    def new_page():
        page = Page(_PAGE)
        pages.append(page)
        page.rect(0, _PAGE[1] - 58, _PAGE[0], 58, fill=_RED)
        page.text(_LEFT, _PAGE[1] - 30, "TRANSACTIONS", size=18, bold=True, color=(1, 1, 1))
        page.text_right(_RIGHT, _PAGE[1] - 30, _period(start, end), size=12, bold=True, color=(1, 1, 1))
        page.text(_LEFT, _PAGE[1] - 47, f"Lead desk · {_scope(kind, account)}", size=9, color=(1, 0.9, 0.85))
        return page, _PAGE[1] - 84

    def table_head(page, y):
        page.rect(_LEFT, y - 5, _RIGHT - _LEFT, 17, fill=(0.93, 0.91, 0.87))
        x = _LEFT
        for title, width, right in _COLUMNS:
            if right:
                page.text_right(x + width - 4, y, title, size=8.5, bold=True, color=(0.3, 0.27, 0.22))
            else:
                page.text(x + 4, y, title, size=8.5, bold=True, color=(0.3, 0.27, 0.22))
            x += width
        return y - 19

    page, y = new_page()
    shown = [("Received", t["received"], _GREEN)] if kind == "in" else [("Spent", t["spent"], _RED)] if kind == "out" else \
        [("Received", t["received"], _GREEN), ("Spent", t["spent"], _RED), ("Net", t["net"], _INK)]
    box_w = (_RIGHT - _LEFT - 12 * (len(shown) - 1)) / len(shown)
    for i, (label, value, color) in enumerate(shown):
        x = _LEFT + i * (box_w + 12)
        page.rect(x, y - 26, box_w, 44, fill=(0.98, 0.97, 0.94), stroke=(0.85, 0.82, 0.76))
        page.text(x + 10, y + 6, label.upper(), size=8, bold=True, color=_GREY)
        page.text(x + 10, y - 16, _rs(value), size=15, bold=True, color=color)
    y -= 50

    def heading(page, y, text):
        page.text(_LEFT, y, text, size=10.5, bold=True, color=_INK)
        return y - 17

    for title, received in (("Received by reason", True), ("Spent by reason", False)):
        part = by_reason(rows, received)
        if not part or (received and kind == "out") or (not received and kind == "in"):
            continue
        if y < _BOTTOM + 40 + 15 * len(part):
            page, y = new_page()
        y = heading(page, y, title)
        for reason, n, amount in part:
            page.text(_LEFT + 4, y, reason, size=9)
            page.text(_LEFT + 260, y, f"{n} {'entry' if n == 1 else 'entries'}", size=9, color=_GREY)
            page.text_right(_LEFT + 400, y, _rs(amount), size=9)
            page.line(_LEFT, y - 4, _LEFT + 400, y - 4, width=0.3)
            y -= 15
        y -= 10

    accounts = by_account(rows)
    if accounts:
        if y < _BOTTOM + 40 + 15 * len(accounts):
            page, y = new_page()
        y = heading(page, y, "By account")
        page.text_right(_LEFT + 260, y + 2, "Received", size=8, bold=True, color=_GREY)
        page.text_right(_LEFT + 330, y + 2, "Spent", size=8, bold=True, color=_GREY)
        page.text_right(_LEFT + 400, y + 2, "Net", size=8, bold=True, color=_GREY)
        y -= 8
        for name, got, spent, net in accounts:
            page.text(_LEFT + 4, y, name, size=9)
            page.text_right(_LEFT + 260, y, _indian(got), size=9)
            page.text_right(_LEFT + 330, y, _indian(spent), size=9)
            page.text_right(_LEFT + 400, y, _indian(net), size=9, bold=True)
            page.line(_LEFT, y - 4, _LEFT + 400, y - 4, width=0.3)
            y -= 15
        y -= 10

    if y < _BOTTOM + 70:
        page, y = new_page()
    y = heading(page, y, f"All entries ({t['count']})")
    if not rows:
        page.text(_LEFT + 4, y, "Nothing was received or spent between these dates.", size=9, color=_GREY)
    else:
        y = table_head(page, y)
    for r in rows:
        if y < _BOTTOM + 12:
            page, y = new_page()
            y = table_head(page, y)
        cells = [date.fromisoformat(r["date"]).strftime("%d %b %Y"), r["reason"], r["party"] or "", r["detail"] or "", r["account"] or NO_ACCOUNT_LABEL]
        x = _LEFT
        for (title, width, right), text in zip(_COLUMNS, cells):
            page.text(x + 4, y, _clip(text, width - 8, 8.5, False), size=8.5)
            x += width
        amount = _indian(r["amount"])
        if r["received"]:
            page.text_right(_RIGHT - _COLUMNS[6][1] - 4, y, amount, size=8.5, color=_GREEN)
        else:
            page.text_right(_RIGHT - 4, y, amount, size=8.5, color=_RED)
        page.line(_LEFT, y - 4, _RIGHT, y - 4, width=0.3)
        y -= 15
    if rows:
        y -= 3
        page.rect(_LEFT, y - 5, _RIGHT - _LEFT, 17, fill=(0.93, 0.91, 0.87))
        page.text(_LEFT + 4, y, "Total", size=9, bold=True)
        if kind != "out":
            page.text_right(_RIGHT - _COLUMNS[6][1] - 4, y, _indian(t["received"]), size=9, bold=True, color=_GREEN)
        if kind != "in":
            page.text_right(_RIGHT - 4, y, _indian(t["spent"]), size=9, bold=True, color=_RED)

    stamp = f"Figures as on {today_local().strftime('%d %b %Y')}, from the live records. Self transfers between accounts are not counted."
    for n, p in enumerate(pages, start=1):
        p.text(_LEFT, 22, stamp, size=7.5, color=(0.5, 0.5, 0.5))
        p.text_right(_RIGHT, 22, f"Page {n} of {len(pages)}", size=7.5, color=(0.5, 0.5, 0.5))
    return build_pdf(pages, title=f"Transactions - {_period(start, end)}")
