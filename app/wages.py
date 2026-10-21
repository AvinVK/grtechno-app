"""Wages (kohal, 2026-10-18: "when they login they should see attendance, wages and fooding. wages wont
be populated yet" - then, 2026-10-21: "i wanna have day by day cumulative wages tracking for daily wages
and it should show in wages block in me tab. also once 15 days are over (the payroll cycle), it should
show a flag saying 15 days cycle total is this much, u were absent this much"): a daily-wage/contractor
employee's own view of the same pay-period math Payroll already computes for the admin
(app/payroll.py's _day_rate_periods/_day_by_day) - current cycle's day-by-day log with a running total,
and the most recently *completed* cycle shown as its own flag (kohal's "15 days cycle total ... absent
this much") rather than folded into the day list. See app/fooding.py, its sibling tile, for the same
employment_type-gated shape."""

from datetime import date

from flask import Blueprint, abort, g, jsonify, render_template

from .models import Worker, settings_for_client
from .payroll import DAY_RATE_TYPES, _day_by_day, _day_rate_periods
from .workers import _period

bp = Blueprint("wages", __name__)


def _own_daily_wage_worker():
    worker = Worker.query.filter_by(user_code=g.user.code).first()
    if worker is None or worker.employment_type not in DAY_RATE_TYPES:
        abort(403, "Wages is only for daily-wage/contractor employees.")
    return worker


@bp.get("/wages")
def page():
    _own_daily_wage_worker()
    return render_template("wages.html")


@bp.get("/api/wages/me")
def my_wages():
    worker = _own_daily_wage_worker()
    today = date.today()
    _, data_until = _period()
    data_until_end = min(today, data_until) if data_until else None

    # _day_rate_periods assumes a wage to compute earned with (same as Payroll's own _payroll_rows, which
    # only ever calls it for a worker it already filtered to wage_amount.isnot(None)) - nothing to show
    # without one here either, same "not set" shape as before day-by-day existed.
    periods = _day_rate_periods(worker, today, data_until_end) if worker.wage_amount is not None else []
    current = periods[0] if periods else None
    completed = periods[1] if len(periods) > 1 else None

    days = []
    if current is not None:
        start = date.fromisoformat(current["period_start"])
        end = min(date.fromisoformat(current["period_end"]), today)
        days = _day_by_day(worker, start, end, data_until_end)
        running = 0.0
        for d in days:
            running = round(running + (d["pay"] or 0), 2)
            d["cumulative"] = running

    return jsonify(
        daily_rate=float(worker.wage_amount) if worker.wage_amount is not None else None,
        currency=settings_for_client()["currency"],
        current=current,
        completed=completed,
        days=days,
    )
